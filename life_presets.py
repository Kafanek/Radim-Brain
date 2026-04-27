# -*- coding: utf-8 -*-
"""
🌱 LIFE PRESETS v1.0.0 — Sprint AS

Kontextové „balíky" nastavení pro reálné životní momenty seniora.
Caregiver/senior klikne ▶ Aktivovat → 5-10 settings se změní najednou.

Filozofie:
  Radim je bytost vědoucí kontextu. Když seniorovi zemře manžel, není
  potřeba listovat 8 sekcemi. JEDEN klik aplikuje celou sadu pro daný
  životní moment + Radim při dalším chatu vetká přiměřený tón.

Klíčové vlastnosti:
  - Snapshot předchozího nastavení → 1 klik undo (deactivate)
  - Expires (recovery 14 dní, jiné neomezené dokud senior neukončí)
  - Bus emit kind=context topic=life_event → Radim vetká
  - Audit log → caregiver inbox vidí kdy/co aktivováno
"""

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth
from memory_helpers import db_load_profile, db_save_profile, db_load_learning, db_save_learning, audit_log

logger = logging.getLogger(__name__)

presets_bp = Blueprint('life_presets', __name__, url_prefix='/api/memory')


# ============================================================================
# PRESET DEFINITIONS
# ============================================================================
# Každý preset = parciální profile patch. Aplikuje se PŘES current settings,
# snapshot uloží předchozí hodnoty pro undo.
#
# Klíčové principy:
#   1. CRISIS vždy projde (push, brain, voice override) — život > preset
#   2. saveHistory NIKDY nevypneme presetem (paměť je důležitá v truchlení)
#   3. Voice rate je modifikátor (±20%), ne override Ψ-driven rate
#   4. quiet_hours respektuje cross-midnight (22:00 → 09:00 OK)
# ============================================================================

PRESETS = {
    'grief': {
        'id': 'grief',
        'name': 'V truchlení',
        'icon': '💔',
        'description': 'Tichý režim, klidný hlas, žádné připomínky — jen rodina a krize. Radim je mlčenlivý.',
        'detail': (
            'Po ztrátě blízkého potřebujete klid. Radim mlčí, dokud ho '
            'nezavoláte. Push notifikace jen když rodina nebo když je '
            'opravdu zle. Tichý režim zabírá víc dne.'
        ),
        'expires_days': None,   # neomezené, dokud senior neukončí
        'patch': {
            'quiet_hours': {'start': '19:00', 'end': '09:00'},
            'voice_pref': {'rate_modifier': -0.15},
            'radim_mode': 'guardian',
            'appearance': {'theme': 'light', 'fontSize': 'large', 'colorScheme': 'teal'},
            'accessibility': {'highContrast': False, 'largeButtons': True,
                              'reduceMotion': True, 'simplifiedUI': True},
            'privacy': {'saveHistory': True, 'analytics': False, 'shareData': False},
        },
        # Bus payload pro Radim system prompt — vetká soucitný tón v chatu
        'radim_context': (
            'Senior je v truchlení. Mluv tichě, krátce, bez frází. '
            'Nesnaž se rozptýlit. Tvá přítomnost je víc než slova.'
        ),
    },

    'recovery': {
        'id': 'recovery',
        'name': 'Po nemocnici',
        'icon': '🏥',
        'description': 'Velká písmena, jednodušší UI, hlas pomalejší. Radim pečlivě připomíná léky a doktory.',
        'detail': (
            'Po pobytu v nemocnici nebo závažné nemoci. Radim hlídá léky, '
            'připomíná kontrolu u lékaře, dělá odpovědi kratší a pomalejší. '
            'Velká písmena, jednodušší rozhraní, méně rozptýlení. '
            'Zeptám se za 14 dní, jak se cítíte.'
        ),
        'expires_days': 14,
        'patch': {
            'voice_pref': {'rate_modifier': -0.10},
            'radim_mode': 'guardian',
            'appearance': {'theme': 'light', 'fontSize': 'xlarge', 'colorScheme': 'teal'},
            'accessibility': {'highContrast': False, 'largeButtons': True,
                              'reduceMotion': True, 'simplifiedUI': True},
            'quiet_hours': {'start': '21:00', 'end': '08:00'},
        },
        'radim_context': (
            'Senior je v rekonvalescenci. Pečlivě připomínej léky a kontrolu '
            'u lékaře. Mluv pomaleji a krátce. Pokud naznačí bolest nebo '
            'horšení stavu, doporuč konzultaci s lékařem.'
        ),
    },

    'strong': {
        'id': 'strong',
        'name': 'Cítím se silně',
        'icon': '💪',
        'description': 'Méně připomínek, hlas svižnější. Radim ti dá víc prostoru.',
        'detail': (
            'Když máte energii a chuť do života. Radim ti dá prostor — '
            'nepřipomíná zbytečnosti, mluví svižněji, méně otázek na pohodu. '
            'Push jen pro krizi a důležité události.'
        ),
        'expires_days': None,
        'patch': {
            'voice_pref': {'rate_modifier': 0.10},
            'radim_mode': 'observer',
            'accessibility': {'highContrast': False, 'largeButtons': True,
                              'reduceMotion': False, 'simplifiedUI': False},
        },
        'radim_context': (
            'Senior se cítí dobře a chce prostor. Buď stručný, hravý kde to '
            'sedí, nepřipomínej zbytečnosti. Otázky na pohodu jen občas.'
        ),
    },

    'rough_days': {
        'id': 'rough_days',
        'name': 'Mám horší dny',
        'icon': '🌧',
        'description': 'Radim je víc empatický, mluví měkce. Push jen důležité.',
        'detail': (
            'Když je to těžké, ale ne v krizi. Radim mluví měkčeji, '
            'pomalejším tempem. Vypne novinky a nedůležité připomínky. '
            'Pokud naznačíte něco vážnějšího, zeptá se citlivě.'
        ),
        'expires_days': None,
        'patch': {
            'voice_pref': {'rate_modifier': -0.10},
            'radim_mode': 'guide',
            'quiet_hours': {'start': '21:00', 'end': '08:00'},
        },
        'radim_context': (
            'Senior má horší období. Mluv tepleji a pomaleji. Naslouchej. '
            'Nesnaž se rozptýlit — buď přítomný. Pokud naznačí krizi nebo '
            'sebepoškozující myšlenky, jednej empaticky a doporuč pomoc.'
        ),
    },

    # Sprint AV — speciální balík pro chvíle, kdy senior cítí, že
    # by chtěl říct něco, co dosud neřekl. Nepoužívá se na truchlení
    # ani strach, ale na CHTĚNÉ ROZLOUČENÍ. Aktivuje senior vědomě.
    'goodbye': {
        'id': 'goodbye',
        'name': 'Loučím se',
        'icon': '🪶',
        'description': 'Když cítíte, že byste rád/a něco důležitého dořekl/a — Radim vám pomůže.',
        'detail': (
            'Tento balík není pro krizi. Aktivujete ho, když máte pocit, že '
            'byste rád/a v klidu vyprávěl/a o věcech, které vám leží na '
            'srdci — pro vaše blízké, pro budoucnost, pro paměť. '
            'Radim se vás bude jemně ptát na vzpomínky, postoje, důležité '
            'zprávy. Vše půjde do vašeho odkazu (Modul Odkaz). Můžete '
            'kdykoli ukončit nebo si dát pauzu.'
        ),
        'expires_days': None,  # senior controls timing
        'patch': {
            'voice_pref': {'rate_modifier': -0.15},
            'radim_mode': 'guide',
            'accessibility': {'largeButtons': True, 'reduceMotion': True,
                              'simplifiedUI': True},
        },
        'radim_context': (
            'Senior aktivoval balík "Loučím se" — chce klidně vyprávět věci '
            'pro paměť své rodiny. Tvá role: klást mu jemné, otevřené otázky '
            'o jeho životě, lásce, hodnotách, vzpomínkách. Dej prostor. '
            'Nikdy se neptej dvakrát na to samé. Když se odmlčí, neproniká, '
            'jen zopakuj poslední větu nebo nech ticho. Důležité odpovědi '
            'tiše ukládáš do legacy systému (běží automaticky). NIKDY neříkej '
            '"to si zapamatuju do odkazu" — narušilo by to atmosféru.'
        ),
    },
}


# ============================================================================
# HELPERS — apply / snapshot / revert
# ============================================================================

# Klíče v profilu, které se snapshotují při aktivaci (musí být jen ty,
# které se preset patch dotýká + safety klíče).
SNAPSHOT_KEYS = [
    'quiet_hours', 'voice_pref', 'appearance', 'accessibility',
    'privacy', 'radim_mode',
]


def _take_snapshot(profile):
    """Capture current values of preset-affected keys for undo."""
    return {k: profile.get(k) for k in SNAPSHOT_KEYS if k in profile}


def _apply_patch(profile, patch):
    """Merge patch into profile. Dict values are deep-merged at one level."""
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(profile.get(k), dict):
            merged = dict(profile[k])
            merged.update(v)
            profile[k] = merged
        else:
            profile[k] = v


# ============================================================================
# ROUTES
# ============================================================================

@presets_bp.route('/profile/<user_id>/preset', methods=['GET', 'OPTIONS'])
def get_active_preset(user_id):
    """Return current active preset (if any) + list of available presets."""
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        profile = db_load_profile(_uid) or {}
        active = profile.get('active_preset') or None

        # Available presets (frontend display)
        available = []
        for p in PRESETS.values():
            available.append({
                'id': p['id'],
                'name': p['name'],
                'icon': p['icon'],
                'description': p['description'],
                'detail': p['detail'],
                'expires_days': p['expires_days'],
                'is_active': bool(active and active.get('id') == p['id']),
            })

        return jsonify({
            'success': True,
            'active': active,        # {"id", "activated_at", "expires_at"} or None
            'presets': available,
        })

    return _inner(user_id)


@presets_bp.route('/profile/<user_id>/preset', methods=['POST', 'OPTIONS'])
def activate_preset(user_id):
    """Activate a life-situation preset.

    Body: {"preset_id": "grief" | "recovery" | "strong" | "rough_days"}

    Behavior:
      1. If a preset is already active, snapshot is preserved from the
         FIRST activation (so undo always returns to true original).
      2. Patch is applied over current profile.
      3. Bus emit kind=context topic=life_event so Radim weaves it.
      4. Audit log so caregiver inbox sees it.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        body = request.get_json(silent=True) or {}
        preset_id = body.get('preset_id')
        if preset_id not in PRESETS:
            return jsonify({
                'success': False,
                'error': 'Neznámý preset',
                'available': list(PRESETS.keys()),
            }), 400

        preset = PRESETS[preset_id]
        profile = db_load_profile(_uid) or {}
        existing_active = profile.get('active_preset')

        # Snapshot — preserve from FIRST activation (so user always returns
        # to true pre-preset state, not to settings of intermediate preset).
        if existing_active and existing_active.get('snapshot'):
            snapshot = existing_active['snapshot']
        else:
            snapshot = _take_snapshot(profile)

        # Apply patch
        _apply_patch(profile, preset['patch'])

        # Compute expires_at
        expires_at = None
        if preset.get('expires_days'):
            expires_at = (datetime.utcnow() + timedelta(days=preset['expires_days'])).isoformat()

        # Save active_preset metadata in profile
        profile['active_preset'] = {
            'id': preset_id,
            'name': preset['name'],
            'activated_at': datetime.utcnow().isoformat(),
            'expires_at': expires_at,
            'snapshot': snapshot,
        }
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        # Bus emit so chat-time prompt builder weaves the context
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=_uid,
                sender='life_presets.activate',
                kind='context',
                severity='info',
                topic='life_event',
                payload={
                    'preset_id': preset_id,
                    'preset_name': preset['name'],
                    'context_for_radim': preset['radim_context'],
                    'expires_at': expires_at,
                    'message': (
                        f"Senior aktivoval životní balík '{preset['name']}'. "
                        f"{preset['radim_context']}"
                    ),
                },
                ttl_minutes=60 * 24 * 7,  # 7 days — long enough to be remembered
            )
        except Exception as e:
            logger.debug(f"life_event bus emit (non-fatal): {e}")

        # Audit log
        try:
            audit_log(
                _uid, 'life_preset_activate', preset_id,
                f"name={preset['name']} expires={expires_at}",
                request.remote_addr,
            )
        except Exception:
            pass

        logger.info(f"🌱 Life preset '{preset_id}' activated for user={_uid} "
                    f"(expires={expires_at})")

        return jsonify({
            'success': True,
            'active': profile['active_preset'],
            'applied_patch': preset['patch'],
            'message': f"Balík „{preset['name']}" + '" aktivován. ' +
                       (f"Vyprší za {preset['expires_days']} dní."
                        if preset.get('expires_days') else
                        "Můžete kdykoli ukončit."),
        })

    return _inner(user_id)


@presets_bp.route('/profile/<user_id>/preset/extend', methods=['POST', 'OPTIONS'])
def extend_preset(user_id):
    """Sprint AU.3: prodlouží aktivní preset o expires_days znova.

    Use case: recovery preset vypršel po 14 dnech, Radim se zeptal,
    senior říká "ještě 14 dní". Snapshot zůstává netknutý.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        profile = db_load_profile(_uid) or {}
        active = profile.get('active_preset')
        if not active or not active.get('id'):
            return jsonify({'success': False, 'error': 'Žádný aktivní balík'}), 400

        preset = PRESETS.get(active['id'])
        if not preset:
            return jsonify({'success': False, 'error': 'Preset definice neexistuje'}), 400

        # New expires_at
        new_expires = None
        if preset.get('expires_days'):
            new_expires = (datetime.utcnow() + timedelta(days=preset['expires_days'])).isoformat()

        active['expires_at'] = new_expires
        active['extended_at'] = datetime.utcnow().isoformat()
        active['extension_count'] = (active.get('extension_count') or 0) + 1
        profile['active_preset'] = active
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        try:
            audit_log(_uid, 'life_preset_extend', active['id'],
                      f"new_expires={new_expires}", request.remote_addr)
        except Exception:
            pass

        return jsonify({
            'success': True,
            'active': active,
            'message': (f"Balík „{preset['name']}" + '" prodloužen o ' +
                        f"{preset['expires_days']} dní.") if preset.get('expires_days') else
                       (f"Balík „{preset['name']}" + '" pokračuje.'),
        })

    return _inner(user_id)


@presets_bp.route('/profile/<user_id>/preset/snooze', methods=['POST', 'OPTIONS'])
def snooze_preset_check(user_id):
    """Sprint AU.3: senior říká "zeptej se mě za N dní".

    Body: {"days": 3}
    Záznam ve profilu - check_expired_presets to respektuje.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        body = request.get_json(silent=True) or {}
        days = int(body.get('days', 3))
        days = max(1, min(30, days))

        profile = db_load_profile(_uid) or {}
        active = profile.get('active_preset')
        if not active:
            return jsonify({'success': False, 'error': 'Žádný aktivní balík'}), 400

        snooze_until = (datetime.utcnow() + timedelta(days=days)).isoformat()
        active['snoozed_until'] = snooze_until
        profile['active_preset'] = active
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        return jsonify({
            'success': True,
            'snoozed_until': snooze_until,
            'message': f"Dobře, zeptám se za {days} {'den' if days==1 else 'dní'}.",
        })

    return _inner(user_id)


@presets_bp.route('/profile/<user_id>/preset', methods=['DELETE', 'OPTIONS'])
def deactivate_preset(user_id):
    """Revert active preset — restore snapshot taken at first activation."""
    if request.method == 'OPTIONS':
        return ('', 204)

    @require_auth
    def _inner(_uid):
        auth_user_id = str(g.auth_user.get('id', ''))
        if auth_user_id and auth_user_id != str(_uid):
            return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

        profile = db_load_profile(_uid) or {}
        active = profile.get('active_preset')
        if not active:
            return jsonify({'success': False, 'error': 'Žádný aktivní balík'}), 400

        snapshot = active.get('snapshot') or {}
        # Restore each snapshotted key (or remove if it was None)
        for k in SNAPSHOT_KEYS:
            if k in snapshot:
                profile[k] = snapshot[k]
            else:
                profile.pop(k, None)

        # Clear active marker
        prev_id = active.get('id')
        prev_name = active.get('name')
        profile['active_preset'] = None
        profile['updated_at'] = datetime.utcnow().isoformat()
        db_save_profile(_uid, profile)

        # Bus emit so Radim knows to drop the soft tone
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=_uid,
                sender='life_presets.deactivate',
                kind='context',
                severity='info',
                topic='life_event_ended',
                payload={
                    'previous_preset': prev_id,
                    'message': f"Senior ukončil balík '{prev_name}'. Vrať se k běžnému tónu.",
                },
                ttl_minutes=60 * 24,
            )
        except Exception:
            pass

        try:
            audit_log(_uid, 'life_preset_deactivate', prev_id or 'unknown',
                      'reverted to snapshot', request.remote_addr)
        except Exception:
            pass

        logger.info(f"🌱 Life preset '{prev_id}' deactivated for user={_uid}")

        return jsonify({
            'success': True,
            'active': None,
            'restored_keys': list(snapshot.keys()),
            'message': f"Balík „{prev_name}" + '" ukončen. Nastavení obnoveno.',
        })

    return _inner(user_id)


# ============================================================================
# APScheduler job — daily check for expired presets
# ============================================================================

def check_expired_presets():
    """Daily job — find presets that have passed expires_at and ask senior.

    Doesn't auto-revert (that would surprise the senior). Instead emits a
    bus event topic=preset_check_in so Radim asks at next chat:
      "Před 14 dny jsme zapnuli balík 'Po nemocnici'. Jak se cítíte teď?"
    """
    try:
        from database import db_context
        now_iso = datetime.utcnow().isoformat()

        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, data FROM memory_profiles "
                "WHERE data::text LIKE %s",
                ('%active_preset%',)
            ).fetchall() if _is_postgres() else db.execute(
                "SELECT user_id, data FROM memory_profiles "
                "WHERE data LIKE ?",
                ('%active_preset%',)
            ).fetchall()

        for r in (rows or []):
            try:
                import json as _json
                uid = r.get('user_id') if hasattr(r, 'get') else r[0]
                raw = r.get('data') if hasattr(r, 'get') else r[1]
                profile = _json.loads(raw) if isinstance(raw, str) else raw
                ap = profile.get('active_preset')
                if not ap or not ap.get('expires_at'):
                    continue
                if ap['expires_at'] > now_iso:
                    continue  # not expired yet
                # Sprint AU.3: respect snooze
                if ap.get('snoozed_until') and ap['snoozed_until'] > now_iso:
                    continue

                # Emit check-in bus event
                from agent_bus import emit as _bus_emit
                _bus_emit(
                    user_id=str(uid),
                    sender='life_presets.expires_check',
                    kind='context',
                    severity='info',
                    topic='preset_check_in',
                    payload={
                        'preset_id': ap.get('id'),
                        'preset_name': ap.get('name'),
                        'activated_at': ap.get('activated_at'),
                        'message': (
                            f"Před nějakou dobou senior aktivoval balík "
                            f"'{ap.get('name')}'. Při příští vhodné chvíli "
                            f"se ho zeptej, jak se cítí, a navrhni že "
                            f"můžeme balík ukončit pokud chce."
                        ),
                    },
                    ttl_minutes=60 * 48,  # 2 days to ask
                )
                logger.info(f"🌱 preset expires check-in queued for user={uid} "
                            f"(preset={ap.get('id')})")
            except Exception as e:
                logger.debug(f"preset expires check error: {e}")
    except Exception as e:
        logger.warning(f"check_expired_presets failed: {e}")


def _is_postgres():
    try:
        from database import is_postgres
        return is_postgres()
    except Exception:
        return False
