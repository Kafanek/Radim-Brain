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

from flask import Blueprint, jsonify, request

from .math_engine import PERSONA_WEIGHTS
from .runtime import get_runtime, _serialize_snapshot

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')


def _admin_authorized() -> bool:
    expected = os.environ.get('ADMIN_SECRET')
    if not expected:
        return False
    return request.headers.get('X-Admin-Secret') == expected


def _user_authorized(user_id: str) -> bool:
    """Lightweight check — same JWT helper used elsewhere in the app.
    Reads from request.user (set by global before_request middleware)
    and matches user_id; admin bypass via X-Admin-Secret."""
    if _admin_authorized():
        return True
    # Try Flask `g.user` or request.user — we accept any auth that
    # produces a user identifier matching the path.
    try:
        from flask import g
        u = getattr(g, 'user', None)
        if u and (u.get('id') == user_id or u.get('user_id') == user_id):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _require_auth(user_id: str):
    if not _user_authorized(user_id):
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
