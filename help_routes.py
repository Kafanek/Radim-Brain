"""
❓ HELP ROUTES v1.0 (Sprint B)
=============================================================================
Backend for the Help / Nápověda frontend module — feedback form + (later)
analytics. Uses @optional_auth so anonymous seniors can still leave feedback.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify

from auth_middleware import optional_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

help_bp = Blueprint('help', __name__)

HELP_SCHEMA = """
    CREATE TABLE IF NOT EXISTS help_feedback (
        id SERIAL PRIMARY KEY,
        user_id TEXT,
        email TEXT,
        message TEXT NOT NULL,
        user_agent TEXT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        resolved_by TEXT,
        resolution TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_help_feedback_submitted
        ON help_feedback(submitted_at DESC);
    CREATE INDEX IF NOT EXISTS idx_help_feedback_user
        ON help_feedback(user_id);
"""


def _init_help_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in HELP_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Help schema init: {e}")


@help_bp.route('/api/help/feedback', methods=['POST'])
@optional_auth
def help_feedback():
    """Submit feedback/support request from the Help module.

    Body: { email, message, user_id, user_agent, submitted_at }
    Stores in help_feedback table. Non-blocking — returns success even if
    email dispatch fails (DB row remains for admin to handle).
    """
    _init_help_schema()
    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    if len(message) < 3:
        return jsonify({'success': False, 'error': 'message too short'}), 400
    if len(message) > 2000:
        message = message[:2000]

    email = (data.get('email') or '').strip()[:200]
    user_id = (data.get('user_id') or '').strip()[:200]
    user_agent = (data.get('user_agent') or '')[:240]

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO help_feedback "
                "(user_id, email, message, user_agent) "
                "VALUES (?, ?, ?, ?)",
                (user_id, email, message, user_agent)
            )
        logger.info(f"📝 Help feedback from user={user_id or 'anon'} email={email or 'none'} len={len(message)}")
    except Exception as e:
        logger.error(f"help_feedback DB error: {e}")
        return jsonify({'success': False, 'error': 'db_error'}), 500

    # Optional: notify admin account via existing notify() pipeline
    try:
        import os
        admin_uid = os.environ.get('ADMIN_USER_ID')
        if admin_uid:
            from notification_helpers import notify as _notify
            subject = f"📝 Nová zpráva z nápovědy ({len(message)} znaků)"
            body_preview = message[:140] + ('…' if len(message) > 140 else '')
            _notify(to_user_id=admin_uid, type='info',
                    title=subject, body=body_preview, severity='info',
                    data={'user_id': user_id, 'email': email})
    except Exception as notify_err:
        logger.debug(f"admin notify skipped: {notify_err}")

    return jsonify({'success': True, 'message': 'Feedback uložen'})


@help_bp.route('/api/help/feedback/count', methods=['GET'])
@optional_auth
def help_feedback_count():
    """Lightweight stats endpoint — how many open items. Useful for admin."""
    _init_help_schema()
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM help_feedback WHERE resolved_at IS NULL"
            ).fetchone()
            n = 0
            if row:
                n = row[0] if isinstance(row, (list, tuple)) else row.get('n', 0)
        return jsonify({'success': True, 'open_count': int(n)})
    except Exception as e:
        return jsonify({'success': True, 'open_count': 0})


logger.info("❓ Help routes v1.0 loaded — feedback + count")
