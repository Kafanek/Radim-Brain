"""
🏠 HOME ASSISTANT CONFIG ROUTES (v395) — per-user / per-home setup
=============================================================================

Endpoints for users to register and manage their own Home Assistant
instances. Each user can store multiple homes (default + secondary). A
home is identified by `home_id` (UUID, server-generated). Tokens are
encrypted at rest — see ha_user_config.py.

Endpoints (all require_auth except where noted):
    GET    /api/ha/config              — list my homes (no tokens)
    GET    /api/ha/config/<home_id>    — read one (no token)
    POST   /api/ha/config              — register new home
        body: {"label": "...", "ha_url": "...", "ha_token": "...",
               "is_default": false, "test": true}
    PUT    /api/ha/config/<home_id>    — update fields (token optional)
    DELETE /api/ha/config/<home_id>    — remove
    POST   /api/ha/config/<home_id>/test     — test connection now
    POST   /api/ha/config/<home_id>/default  — promote to default

    POST   /api/ha/refresh-tunnel-url   — webhook-secret authed (no JWT)
        v397.8 (Sprint X5/E): Used by tunnel-keeper.sh to update
        ha_url after Cloudflare quick-tunnel restart, without needing
        a JWT (which expires in 7 days). Authenticated via per-home
        webhook secret in X-Radim-Tunnel-Secret header.
        body: {"home_id": "<uuid>", "ha_url": "https://..."}
"""

import hmac
import logging
import re
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
import ha_user_config as cfg

logger = logging.getLogger(__name__)

ha_config_bp = Blueprint('ha_config', __name__)


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r'^https?://[^\s/$.?#].[^\s]*$', re.IGNORECASE)


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _validate_input(data, *, partial=False):
    """Validate POST/PUT body. Returns (errors_list, cleaned_dict)."""
    errors = []
    cleaned = {}

    label = (data.get('label') or '').strip()
    ha_url = (data.get('ha_url') or '').strip().rstrip('/')
    ha_token = (data.get('ha_token') or '').strip()

    if label:
        if len(label) > 80:
            errors.append('label too long (max 80)')
        cleaned['label'] = label
    elif not partial:
        errors.append('label required')

    if ha_url:
        if not _URL_RE.match(ha_url):
            errors.append('ha_url must be http(s) URL')
        elif len(ha_url) > 300:
            errors.append('ha_url too long')
        else:
            cleaned['ha_url'] = ha_url
    elif not partial:
        errors.append('ha_url required')

    if ha_token:
        # HA long-lived tokens are JWTs (~180–250 chars). Sanity check.
        if len(ha_token) < 30 or len(ha_token) > 4000 or '\n' in ha_token:
            errors.append('ha_token looks malformed')
        else:
            cleaned['ha_token'] = ha_token
    elif not partial:
        errors.append('ha_token required')

    if 'is_default' in data:
        cleaned['is_default'] = bool(data.get('is_default'))

    return errors, cleaned


def _test_connection(ha_url, ha_token):
    """Hit GET /api/ on the given HA. Returns (ok, message).

    Pre-flight checks for unreachable URLs *before* trying to connect:
    - localhost / 127.x → Heroku se tam nikdy nedostane
    - 192.168.x / 10.x / 172.16-31.x (RFC1918 private) → stejná situace
    Vrací srozumitelnou hlášku místo HTTPConnectionPool tracebacku.
    """
    import re
    import requests
    from urllib.parse import urlparse

    # Pre-flight: detect unreachable hosts before HTTP attempt
    try:
        parsed = urlparse(ha_url.strip())
        host = (parsed.hostname or '').lower()
    except Exception:
        host = ''

    if host in ('localhost', '127.0.0.1', '0.0.0.0', '::1') or host.startswith('127.'):
        return False, (
            'URL ukazuje na localhost — z Radim cloudu (Heroku) tam '
            'nedosáhneme. Vystav HA přes Cloudflare Tunnel '
            '(viz docs/DEPLOY.md krok 2) a zadej veřejnou URL '
            '(např. https://radim-ha-tvuj-byt.radimcare.cz).'
        )

    # RFC1918 private ranges
    if re.match(r'^10\.', host) or \
       re.match(r'^192\.168\.', host) or \
       re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', host):
        return False, (
            f'URL je v privátní síti ({host}) — z Radim cloudu tam '
            'nedosáhneme. Použij Cloudflare Tunnel a zadej veřejnou '
            'URL (např. https://radim-ha-tvuj-byt.radimcare.cz).'
        )

    if not host:
        return False, 'Neplatná URL — chybí hostname.'

    try:
        r = requests.get(
            f'{ha_url.rstrip("/")}/api/',
            headers={'Authorization': f'Bearer {ha_token}'},
            timeout=5,
        )
        if r.status_code == 200:
            try:
                return True, r.json().get('message', 'API running.')
            except Exception:
                return True, 'API running.'
        if r.status_code == 401:
            return False, 'Token byl odmítnut (401). Zkontroluj long-lived token v HA.'
        return False, f'HA vrátil HTTP {r.status_code}'
    except requests.exceptions.ConnectTimeout:
        return False, (
            f'Timeout — HA na {host} neodpovídá za 5s. Ověř, že tunel '
            'běží a HA je zapnuté.'
        )
    except requests.exceptions.ConnectionError:
        return False, (
            f'Nelze se připojit k {host}. Ověř, že URL je veřejně '
            'dostupná (Cloudflare Tunnel běží) a port je otevřený.'
        )
    except Exception as e:
        return False, f'Chyba: {str(e)[:120]}'


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@ha_config_bp.route('/api/ha/config', methods=['GET'])
@require_auth
def list_my_homes():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    homes = cfg.list_homes(uid)
    return jsonify({'success': True, 'homes': homes, 'count': len(homes)})


@ha_config_bp.route('/api/ha/config/<home_id>', methods=['GET'])
@require_auth
def get_my_home(home_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    home = cfg.get_home(uid, home_id)
    if not home:
        return jsonify({'success': False, 'error': 'not_found'}), 404
    return jsonify({'success': True, 'home': home})


@ha_config_bp.route('/api/ha/config', methods=['POST'])
@require_auth
def create_my_home():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    errors, cleaned = _validate_input(data)
    if errors:
        return jsonify({'success': False, 'error': 'validation', 'details': errors}), 400

    # Optional pre-flight test before saving
    if data.get('test', True):
        ok, msg = _test_connection(cleaned['ha_url'], cleaned['ha_token'])
        if not ok:
            return jsonify({
                'success': False, 'error': 'connection_failed',
                'message': msg, 'tested_url': cleaned['ha_url'],
            }), 400

    saved = cfg.save_home(
        user_id=uid,
        label=cleaned['label'],
        ha_url=cleaned['ha_url'],
        ha_token=cleaned['ha_token'],
        is_default=cleaned.get('is_default', False),
    )
    logger.info(f"HA home created: user={uid[:8]} home={saved['home_id'][:8]} url={cleaned['ha_url']}")
    return jsonify({'success': True, 'home': saved}), 201


@ha_config_bp.route('/api/ha/config/<home_id>', methods=['PUT'])
@require_auth
def update_my_home(home_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    existing = cfg.get_home(uid, home_id, with_token=True)
    if not existing:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    data = request.get_json(silent=True) or {}
    errors, cleaned = _validate_input(data, partial=True)
    if errors:
        return jsonify({'success': False, 'error': 'validation', 'details': errors}), 400
    if not cleaned:
        return jsonify({'success': False, 'error': 'no_fields'}), 400

    # Merge: keep current values for unchanged fields
    label = cleaned.get('label', existing.get('label'))
    ha_url = cleaned.get('ha_url', existing.get('ha_url'))
    ha_token = cleaned.get('ha_token', existing.get('ha_token'))
    is_default = cleaned.get('is_default', existing.get('is_default', False))

    if data.get('test', True) and 'ha_token' in cleaned:
        ok, msg = _test_connection(ha_url, ha_token)
        if not ok:
            return jsonify({
                'success': False, 'error': 'connection_failed', 'message': msg,
            }), 400

    saved = cfg.save_home(
        user_id=uid, label=label, ha_url=ha_url, ha_token=ha_token,
        home_id=home_id, is_default=is_default,
        ha_webhook_secret=existing.get('ha_webhook_secret'),
    )
    logger.info(f"HA home updated: user={uid[:8]} home={home_id[:8]}")
    return jsonify({'success': True, 'home': saved})


@ha_config_bp.route('/api/ha/config/<home_id>', methods=['DELETE'])
@require_auth
def delete_my_home(home_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if cfg.delete_home(uid, home_id):
        logger.info(f"HA home deleted: user={uid[:8]} home={home_id[:8]}")
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'not_found'}), 404


@ha_config_bp.route('/api/ha/config/<home_id>/test', methods=['POST'])
@require_auth
def test_my_home(home_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    home = cfg.get_home(uid, home_id, with_token=True)
    if not home:
        return jsonify({'success': False, 'error': 'not_found'}), 404
    ok, msg = _test_connection(home['ha_url'], home['ha_token'])
    cfg.record_connection_status(home_id, ok, None if ok else msg)
    return jsonify({'success': ok, 'message': msg, 'home_id': home_id})


@ha_config_bp.route('/api/ha/config/<home_id>/default', methods=['POST'])
@require_auth
def set_default(home_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if cfg.set_default_home(uid, home_id):
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'not_found'}), 404


# ═══════════════════════════════════════════════════════════════════
# Tunnel refresh — webhook-secret authed (no JWT)
# ═══════════════════════════════════════════════════════════════════
# Quick Cloudflare tunnels (https://*.trycloudflare.com) get a new URL
# every restart. The keeper script (radim-tunnel-keeper.sh) needs to push
# that URL to this backend so Heroku knows where to forward HA requests.
# Until v397.8 the keeper used a JWT — but JWTs expire in 7 days, so the
# keeper would silently break and need manual re-paste from the user's
# browser localStorage. This endpoint replaces that with a per-home
# webhook secret that never expires.

@ha_config_bp.route('/api/ha/refresh-tunnel-url', methods=['POST'])
def refresh_tunnel_url():
    data = request.get_json(silent=True) or {}
    home_id = (data.get('home_id') or '').strip()
    new_url = (data.get('ha_url') or '').strip().rstrip('/')

    if not home_id or not new_url:
        return jsonify({'success': False, 'error': 'missing_fields'}), 400
    if not _URL_RE.match(new_url):
        return jsonify({'success': False, 'error': 'invalid_url'}), 400

    provided_secret = request.headers.get('X-Radim-Tunnel-Secret', '').strip()
    if not provided_secret:
        return jsonify({'success': False, 'error': 'missing_secret'}), 401

    home = cfg.get_home_by_id(home_id, with_token=True)
    if not home:
        return jsonify({'success': False, 'error': 'home_not_found'}), 404

    expected = home.get('ha_webhook_secret') or ''
    if not expected or not hmac.compare_digest(expected, provided_secret):
        # Don't reveal whether home exists vs secret wrong (timing-safe)
        logger.warning(f"refresh-tunnel-url: bad secret for home={home_id[:8]}")
        return jsonify({'success': False, 'error': 'bad_secret'}), 401

    # Update only ha_url, preserve everything else
    saved = cfg.save_home(
        user_id=home['user_id'],
        label=home.get('label') or '',
        ha_url=new_url,
        ha_token=home.get('ha_token') or '',
        home_id=home_id,
        is_default=home.get('is_default', False),
        ha_webhook_secret=expected,
    )
    logger.info(
        f"🌐 Tunnel URL refreshed: home={home_id[:8]} url={new_url}"
    )
    return jsonify({
        'success': True,
        'home_id': home_id,
        'ha_url': new_url,
        'updated_at': saved.get('updated_at'),
    })


logger.info("🏠 HA config routes loaded (per-user / per-home + tunnel refresh)")
