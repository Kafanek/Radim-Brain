"""
Agent Context Hints API
=======================

Flask blueprint exposing the agent's current understanding of a user
to other modules (frontend or backend). Every module that wants
"agent-aware" behavior can hit one of these and adapt itself.

Endpoints (all under /api/agent):

  GET  /heartbeat/<user_id>              → full live snapshot
  GET  /context-hints/<user_id>/<module> → tone + speech + mode hints
  POST /tick/<user_id>                   → force a synchronous beat (debug)
  GET  /personas                         → list available personas + weights

Auth: all endpoints require either:
  - Authorization: Bearer <jwt>     (user-scoped, must match path user_id)
  - X-Admin-Secret: <secret>        (admin / cron / ops)

Sprint X20.1
"""
from __future__ import annotations

import os

from flask import Blueprint, g, jsonify, request

from .math_engine import PERSONA_WEIGHTS
from .runtime import get_runtime, _serialize_snapshot

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')


def _admin_authorized() -> bool:
    expected = os.environ.get('ADMIN_SECRET')
    if not expected:
        return False
    return request.headers.get('X-Admin-Secret') == expected


def _decode_jwt_from_header():
    """Read JWT from Authorization header and return (payload, user) or (None, None)."""
    try:
        from auth_middleware import decode_jwt
    except ImportError:
        return None, None
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, None
    token = auth_header[7:].strip()
    if not token:
        return None, None
    payload = decode_jwt(token)
    if not payload:
        return None, None
    user = payload.get('user') or {}
    return payload, user


def _user_authorized(user_id: str):
    """Returns (ok, jwt_user). ok=True if admin OR JWT user matches path uid.
    Path uid is normalized to string for comparison (JWT may carry int id)."""
    if _admin_authorized():
        return True, None
    _, jwt_user = _decode_jwt_from_header()
    if not jwt_user:
        return False, None
    # Coerce both to string for comparison — WP user ids are integers in JWT
    # but the frontend sends them as strings in the URL path.
    jwt_id = jwt_user.get('id') or jwt_user.get('user_id')
    if jwt_id is None:
        return False, jwt_user
    if str(jwt_id) == str(user_id):
        # Stash on g so handlers can reuse without re-decoding
        try:
            g.auth_user = jwt_user
        except Exception:
            pass
        return True, jwt_user
    return False, jwt_user


def _require_auth(user_id: str):
    ok, _ = _user_authorized(user_id)
    if not ok:
        return jsonify({'success': False, 'error': 'unauthorized',
                        'code': 'token_required'}), 401
    return None


@agent_bp.route('/heartbeat/<user_id>', methods=['GET'])
def heartbeat(user_id):
    err = _require_auth(user_id)
    if err:
        return err
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    snap = rt.latest(user_id)
    if not snap:
        # Cold start — ensure heartbeat exists, do an immediate tick
        try:
            snap = rt.force_tick(user_id)
        except Exception as e:  # noqa: BLE001
            return jsonify({'available': False, 'error': str(e)}), 500
    return jsonify({
        'available': True,
        'user_id': user_id,
        'snapshot': _serialize_snapshot(snap),
    })


@agent_bp.route('/context-hints/<user_id>/<module>', methods=['GET'])
def context_hints(user_id, module):
    """Lightweight, frontend-friendly context for `module` to adapt itself."""
    err = _require_auth(user_id)
    if err:
        return err
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    return jsonify(rt.context_hints(user_id, module))


@agent_bp.route('/tick/<user_id>', methods=['POST'])
def force_tick(user_id):
    """Debug — synchronously fire one heartbeat and return the snapshot.
    Admin-only (cron, debugging)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    try:
        snap = rt.force_tick(user_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'snapshot': _serialize_snapshot(snap)})


@agent_bp.route('/personas', methods=['GET'])
def list_personas():
    """List available personas with their weight + threshold profiles."""
    out = {}
    try:
        from .personas import PERSONA_THRESHOLDS
        for pid, w in PERSONA_WEIGHTS.items():
            out[pid] = {
                'weights': {
                    'emotional':     w.emotional,
                    'environmental': w.environmental,
                    'social':        w.social,
                    'physical':      w.physical,
                },
                'thresholds': PERSONA_THRESHOLDS.get(pid, {}),
            }
    except ImportError:
        for pid, w in PERSONA_WEIGHTS.items():
            out[pid] = {
                'weights': {
                    'emotional':     w.emotional,
                    'environmental': w.environmental,
                    'social':        w.social,
                    'physical':      w.physical,
                },
            }
    return jsonify({'personas': out})


@agent_bp.route('/persona/<user_id>', methods=['GET'])
def get_user_persona(user_id):
    """Get persona_id assigned to user. Self or admin."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .personas import get_persona_id, get_thresholds
        pid = get_persona_id(user_id)
        return jsonify({
            'success': True,
            'user_id': user_id,
            'persona_id': pid,
            'thresholds': get_thresholds(pid),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/persona/<user_id>', methods=['POST'])
def set_user_persona(user_id):
    """Set persona_id for user. Admin-only (caregiver-driven from dashboard).
    Body: {"persona_id": "senior" | "child_autism" | "child_adhd"}"""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    pid = body.get('persona_id')
    if not pid:
        return jsonify({'success': False, 'error': 'missing_persona_id'}), 400
    try:
        from .personas import set_persona_id, get_thresholds
        ok = set_persona_id(user_id, pid)
        if not ok:
            return jsonify({'success': False,
                            'error': 'unknown_persona_or_db_error'}), 400
        # Audit-log the change
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'persona_changed',
                      payload={'persona_id': pid})
        except Exception:
            pass
        return jsonify({'success': True, 'persona_id': pid,
                        'thresholds': get_thresholds(pid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/health', methods=['GET'])
def agent_health():
    """Public — light health check, no auth required."""
    rt = get_runtime()
    out = {
        'available': bool(rt),
        'active_heartbeats': len(rt._heartbeats) if rt else 0,
        'version': '1.0.0',
    }
    # Sprint X20.1/Fix 5 — surface ha_realtime registry status
    try:
        from .ha_realtime import get_registry
        reg = get_registry()
        out['ha_realtime'] = reg.status() if reg else {'available': False}
    except Exception:
        pass
    return jsonify(out)


@agent_bp.route('/ha-realtime/init', methods=['POST'])
def ha_realtime_init():
    """Admin: kick off WebSocket subscription for all configured HA homes.
    Useful after a Heroku restart or after a new home was added without
    waiting for the next agent_loop cycle to discover it."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .ha_realtime import get_registry, init_registry
        reg = get_registry() or init_registry()
        # Fetch the running Flask app for context binding
        try:
            from flask import current_app
            reg.app = reg.app or current_app._get_current_object()
        except Exception:
            pass
        started = reg.init_all()
        return jsonify({
            'success': True,
            'newly_started': started,
            'status': reg.status(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/ha-realtime/init/<user_id>', methods=['POST'])
def ha_realtime_init_user(user_id):
    """Admin: subscribe to a single user's HA. Idempotent."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .ha_realtime import get_registry, init_registry
        reg = get_registry() or init_registry()
        try:
            from flask import current_app
            reg.app = reg.app or current_app._get_current_object()
        except Exception:
            pass
        ok = reg.init_user(user_id)
        return jsonify({
            'success': True,
            'newly_started': ok,
            'user_id': user_id,
            'status': reg.status(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
