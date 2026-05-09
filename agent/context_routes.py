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
    return jsonify({
        'personas': {
            pid: {
                'emotional':     w.emotional,
                'environmental': w.environmental,
                'social':        w.social,
                'physical':      w.physical,
            }
            for pid, w in PERSONA_WEIGHTS.items()
        }
    })


@agent_bp.route('/health', methods=['GET'])
def agent_health():
    """Public — light health check, no auth required."""
    rt = get_runtime()
    return jsonify({
        'available': bool(rt),
        'active_heartbeats': len(rt._heartbeats) if rt else 0,
        'version': '1.0.0',
    })
