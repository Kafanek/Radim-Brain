# -*- coding: utf-8 -*-
"""
Senior → Caregiver authorization flow (v8.19.71)
==================================================
Senior požádá Radima o destruktivní akci → Radim místo exekuce vytvoří
pending_authorization → push notifikace + SocketIO všem pečujícím
→ pečující rozhodne → SocketIO event seniorovi → Radim řekne výsledek.

Endpointy:
    POST /api/caregiver/request-authorize    senior-auth, vytvoří pending request
    GET  /api/caregiver/pending-authorizations family-auth, list pending k rozhodnutí
    POST /api/caregiver/decide-authorize/<id> family-auth, schválí/zamítne

Tabulka:
    pending_authorizations (
        id, senior_id, action_id, label, summary, requested_at,
        decided_by, decided_at, approved (NULL=pending), expires_at
    )

SocketIO eventy:
    caregiver:auth-request         → pečující (room user_<caregiver_id>)
    senior:auth-decided            → senior (room user_<senior_id>)
"""
import logging
import json
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, current_app

from auth_middleware import require_auth
from database import db_context, db_insert, is_postgres

logger = logging.getLogger(__name__)

senior_authorize_bp = Blueprint("senior_authorize", __name__)

# 5 min default TTL — pečující musí rozhodnout, jinak default deny.
AUTHORIZATION_TTL_MIN = 5


def _uid():
    """Get authenticated user id from request context."""
    from flask import g
    return getattr(g, 'user_id', None) or getattr(g, 'uid', None)


def _ensure_schema():
    """Create pending_authorizations table if missing."""
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS pending_authorizations (
                        id SERIAL PRIMARY KEY,
                        senior_id TEXT NOT NULL,
                        action_id TEXT NOT NULL,
                        label TEXT NOT NULL,
                        summary TEXT,
                        requested_at TIMESTAMP DEFAULT NOW(),
                        expires_at TIMESTAMP NOT NULL,
                        decided_by TEXT,
                        decided_at TIMESTAMP,
                        approved BOOLEAN
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_pa_senior ON pending_authorizations(senior_id, decided_at)")
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS pending_authorizations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        senior_id TEXT NOT NULL,
                        action_id TEXT NOT NULL,
                        label TEXT NOT NULL,
                        summary TEXT,
                        requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        expires_at TEXT NOT NULL,
                        decided_by TEXT,
                        decided_at TEXT,
                        approved INTEGER
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_pa_senior ON pending_authorizations(senior_id, decided_at)")
    except Exception as e:
        logger.warning(f"pending_authorizations schema init: {e}")


def _get_caregivers_for_senior(senior_id):
    """Return list of family_user_id linked to this senior (confirmed, not revoked)."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT family_user_id FROM senior_family_links "
                "WHERE senior_id = ? AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id,)
            ).fetchall()
        return [r[0] if isinstance(r, (list, tuple)) else r['family_user_id'] for r in (rows or [])]
    except Exception as e:
        logger.debug(f"_get_caregivers_for_senior error: {e}")
        return []


def _send_caregiver_push(caregiver_id, request_id, label, summary, senior_name):
    """Push notification to one caregiver about pending authorization."""
    try:
        send_push = current_app.config.get('SEND_PUSH_FN')
        if not send_push:
            return False
        title = f"🔐 {senior_name} potřebuje vaše schválení"
        body = f"{label}: {summary[:80] if summary else ''}"
        data = {
            "type": "auth_request",
            "request_id": request_id,
            "action_id": label,
            "deep_link": f"/?caregiver_auth={request_id}",
        }
        send_push(caregiver_id, title, body, data=data)
        return True
    except Exception as e:
        logger.debug(f"_send_caregiver_push error: {e}")
        return False


def _emit_socketio(room, event, payload):
    """Best-effort SocketIO emit — fail-open."""
    try:
        socketio = current_app.config.get('SOCKETIO_INSTANCE')
        if socketio:
            socketio.emit(event, payload, room=room)
    except Exception as e:
        logger.debug(f"_emit_socketio({event}, {room}) error: {e}")


def _addressee_name(user_id):
    """Best-effort senior display name."""
    try:
        from memory_helpers import db_load_profile
        prof = db_load_profile(user_id) or {}
        return prof.get('name') or prof.get('first_name') or 'Senior'
    except Exception:
        return 'Senior'


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@senior_authorize_bp.route('/api/caregiver/request-authorize', methods=['POST', 'OPTIONS'])
@require_auth
def request_authorize():
    """SENIOR endpoint — request caregiver approval for destructive action.

    Body: {action_id, label, summary?}
    Returns: {success, request_id, expires_at}
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    _ensure_schema()
    senior_id = _uid()
    if not senior_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    action_id = (data.get('action_id') or '').strip()
    label = (data.get('label') or '').strip()
    summary = (data.get('summary') or '').strip()
    if not action_id or not label:
        return jsonify({'success': False, 'error': 'action_id + label required'}), 400

    expires_at = datetime.utcnow() + timedelta(minutes=AUTHORIZATION_TTL_MIN)

    # Find caregivers
    caregivers = _get_caregivers_for_senior(senior_id)
    if not caregivers:
        # No caregiver linked → cannot get approval, default deny
        return jsonify({
            'success': False,
            'error': 'no_caregiver_linked',
            'message': 'Pro tuto akci je potřeba pečující osoba — žádná není napojená.'
        }), 400

    # Insert pending row
    request_id = None
    try:
        with db_context(commit=True) as db:
            request_id = db_insert(
                db,
                'pending_authorizations',
                ['senior_id', 'action_id', 'label', 'summary', 'expires_at'],
                [senior_id, action_id, label, summary,
                 expires_at if is_postgres() else expires_at.isoformat()]
            )
    except Exception as e:
        logger.error(f"request_authorize insert error: {e}")
        return jsonify({'success': False, 'error': 'db_error'}), 500

    senior_name = _addressee_name(senior_id)

    # Notify all caregivers via push + socketio
    notified = 0
    for cg_id in caregivers:
        if _send_caregiver_push(cg_id, request_id, label, summary, senior_name):
            notified += 1
        _emit_socketio(f'user_{cg_id}', 'caregiver:auth-request', {
            'request_id': request_id,
            'senior_id': senior_id,
            'senior_name': senior_name,
            'action_id': action_id,
            'label': label,
            'summary': summary,
            'expires_at': expires_at.isoformat(),
        })

    logger.info(f"🔐 Authorize request #{request_id}: {senior_name} → {label} → {len(caregivers)} caregivers ({notified} pushed)")

    return jsonify({
        'success': True,
        'request_id': request_id,
        'expires_at': expires_at.isoformat(),
        'caregivers_notified': len(caregivers),
    })


@senior_authorize_bp.route('/api/caregiver/pending-authorizations', methods=['GET', 'OPTIONS'])
@require_auth
def pending_authorizations():
    """CAREGIVER endpoint — list active pending requests for any senior they're linked to."""
    if request.method == 'OPTIONS':
        return ('', 204)

    _ensure_schema()
    caregiver_id = _uid()
    if not caregiver_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Find seniors caregiver is linked to
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT senior_id FROM senior_family_links "
                "WHERE family_user_id = ? AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (caregiver_id,)
            ).fetchall()
    except Exception:
        rows = []
    senior_ids = [r[0] if isinstance(r, (list, tuple)) else r['senior_id'] for r in (rows or [])]
    if not senior_ids:
        return jsonify({'success': True, 'requests': []})

    # Fetch pending (not yet decided + not expired)
    requests_list = []
    try:
        with db_context() as db:
            placeholders = ','.join(['?'] * len(senior_ids))
            now = datetime.utcnow() if is_postgres() else datetime.utcnow().isoformat()
            rows = db.execute(
                f"SELECT id, senior_id, action_id, label, summary, requested_at, expires_at "
                f"FROM pending_authorizations "
                f"WHERE senior_id IN ({placeholders}) "
                f"AND decided_at IS NULL "
                f"AND expires_at > ? "
                f"ORDER BY requested_at DESC LIMIT 50",
                tuple(senior_ids) + (now,)
            ).fetchall()
        for r in rows or []:
            def v(i):
                return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
            requests_list.append({
                'id': v(0),
                'senior_id': v(1),
                'senior_name': _addressee_name(v(1)),
                'action_id': v(2),
                'label': v(3),
                'summary': v(4),
                'requested_at': str(v(5) or ''),
                'expires_at': str(v(6) or ''),
            })
    except Exception as e:
        logger.error(f"pending_authorizations list error: {e}")

    return jsonify({'success': True, 'requests': requests_list, 'count': len(requests_list)})


@senior_authorize_bp.route('/api/caregiver/decide-authorize/<int:request_id>', methods=['POST', 'OPTIONS'])
@require_auth
def decide_authorize(request_id):
    """CAREGIVER endpoint — approve or deny a pending request.

    Body: {approved: true/false}
    Returns: {success, decided_at, approved}
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    _ensure_schema()
    caregiver_id = _uid()
    if not caregiver_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    if 'approved' not in data:
        return jsonify({'success': False, 'error': 'approved field required (true/false)'}), 400
    approved = bool(data.get('approved'))

    # Load + validate
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT senior_id, action_id, label, decided_at, expires_at FROM pending_authorizations WHERE id = ?",
                (request_id,)
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    def v(i):
        return row[i] if isinstance(row, (list, tuple)) else list(row.values())[i]
    senior_id = v(0)
    action_id = v(1)
    label = v(2)
    already_decided = v(3) is not None
    expires_at_raw = v(4)

    if already_decided:
        return jsonify({'success': False, 'error': 'already_decided'}), 409

    # Check expiry
    try:
        if isinstance(expires_at_raw, str):
            expires_at = datetime.fromisoformat(expires_at_raw.replace('Z', ''))
        else:
            expires_at = expires_at_raw
        if expires_at and expires_at < datetime.utcnow():
            return jsonify({'success': False, 'error': 'expired'}), 410
    except Exception:
        pass

    # Verify caregiver is linked
    try:
        with db_context() as db:
            link = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id = ? "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id, caregiver_id)
            ).fetchone()
        if not link:
            return jsonify({'success': False, 'error': 'not_linked'}), 403
    except Exception:
        return jsonify({'success': False, 'error': 'auth_check_failed'}), 500

    # Update row
    decided_at = datetime.utcnow()
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE pending_authorizations SET decided_by = ?, decided_at = ?, approved = ? WHERE id = ?",
                (caregiver_id,
                 decided_at if is_postgres() else decided_at.isoformat(),
                 (True if is_postgres() else 1) if approved else (False if is_postgres() else 0),
                 request_id)
            )
    except Exception as e:
        logger.error(f"decide_authorize update error: {e}")
        return jsonify({'success': False, 'error': 'db_error'}), 500

    # Notify senior via SocketIO
    _emit_socketio(f'user_{senior_id}', 'senior:auth-decided', {
        'request_id': request_id,
        'action_id': action_id,
        'label': label,
        'approved': approved,
        'caregiver_id': caregiver_id,
        'decided_at': decided_at.isoformat(),
    })

    logger.info(f"🔐 Authorize decision #{request_id}: {label} → {'APPROVED' if approved else 'DENIED'} by {caregiver_id}")

    return jsonify({
        'success': True,
        'request_id': request_id,
        'approved': approved,
        'decided_at': decided_at.isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Cleanup — expired requests (volá daily_cleanup)
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_expired_authorizations():
    """Mark expired pending requests as denied (timeout). Volá agent_loop daily."""
    try:
        with db_context(commit=True) as db:
            now = datetime.utcnow() if is_postgres() else datetime.utcnow().isoformat()
            cur = db.execute(
                "UPDATE pending_authorizations "
                "SET decided_at = ?, approved = ? "
                "WHERE decided_at IS NULL AND expires_at < ?",
                (now, (False if is_postgres() else 0), now)
            )
            count = getattr(cur, 'rowcount', 0)
            if count > 0:
                logger.info(f"🔐 Cleanup: {count} expired authorization(s) auto-denied")
            return count
    except Exception as e:
        logger.warning(f"cleanup_expired_authorizations: {e}")
        return 0


logger.info("✅ Senior authorize routes ready: POST /api/caregiver/request-authorize, GET /pending-authorizations, POST /decide-authorize/<id>")
