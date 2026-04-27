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
from ai_config import GEMINI_MODEL

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

    CREATE TABLE IF NOT EXISTS help_analytics (
        id SERIAL PRIMARY KEY,
        user_id TEXT,
        event_type TEXT NOT NULL,
        section TEXT,
        query TEXT,
        result_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_help_analytics_type_date
        ON help_analytics(event_type, created_at DESC);
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


@help_bp.route('/api/help/ask', methods=['POST'])
@optional_auth
def help_ask():
    """Gemini helpdesk fallback — user typed a query that local FAQ search
    couldn't answer. Returns a short Czech answer constrained to
    RadimCare app topics only. Never diagnoses or gives medical advice.

    Body: { query: string, context: string (optional prior search hits) }
    """
    import os
    data = request.get_json() or {}
    query = (data.get('query') or '').strip()
    if len(query) < 3:
        return jsonify({'success': False, 'error': 'query too short'}), 400
    if len(query) > 500:
        query = query[:500]
    context = (data.get('context') or '')[:1500]

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({
            'success': True,
            'answer': 'Moc rád bych pomohl, ale teď se nemohu zeptat mozku. '
                      'Zkuste napsat jiná slova, nebo nás kontaktujte.',
            'source': 'fallback',
        })

    prompt = (
        "Jsi Radim, asistent aplikace RadimCare pro seniory. Uživatel se ptá "
        "na ovládání aplikace. Odpověz KRÁTCE (2-4 věty), česky, laskavě, "
        "jen o ovládání této aplikace. NEDÁVEJ zdravotní rady, NEDIAGNOSTIKUJ. "
        "Pokud otázka není o aplikaci, řekni to laskavě a odkaž na kontakt.\n\n"
        f"DOTAZ UŽIVATELE: {query}\n\n"
    )
    if context:
        prompt += f"KONTEXT (nalezené FAQ záznamy):\n{context}\n\n"
    prompt += "TVOJE ODPOVĚĎ:"

    try:
        import requests as req
        resp = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 300},
            },
            timeout=12,
        )
        if resp.ok:
            data_r = resp.json()
            text = (data_r.get('candidates', [{}])[0].get('content', {})
                        .get('parts', [{}])[0].get('text', '')).strip()
            if text:
                return jsonify({'success': True, 'answer': text, 'source': 'gemini'})
    except Exception as e:
        logger.debug(f"help_ask gemini error: {e}")

    return jsonify({
        'success': True,
        'answer': 'Moc rád bych pomohl, ale nepodařilo se mi teď odpovědět. '
                  'Zkuste prosím jinou formulaci, nebo nás kontaktujte.',
        'source': 'fallback_error',
    })


@help_bp.route('/api/help/view', methods=['POST'])
@optional_auth
def help_view():
    """Lightweight analytics — tracks which help sections + searches users hit.

    Body: { event_type: 'section'|'search'|'ask', section: str, query: str,
            result_count: int, user_id: str }
    Best-effort. Silently drops if analytics disabled or DB write fails.
    """
    data = request.get_json() or {}
    event_type = (data.get('event_type') or '')[:32]
    if event_type not in ('section', 'search', 'ask', 'tip_click', 'tutorial'):
        return jsonify({'success': False, 'error': 'invalid event_type'}), 400

    section = (data.get('section') or '')[:64]
    query = (data.get('query') or '')[:200]
    user_id = (data.get('user_id') or '')[:200]
    try:
        result_count = int(data.get('result_count', 0))
    except (ValueError, TypeError):
        result_count = 0

    try:
        _init_help_schema()
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO help_analytics "
                "(user_id, event_type, section, query, result_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, event_type, section, query, result_count)
            )
    except Exception as e:
        logger.debug(f"help_view DB (non-fatal): {e}")
        return jsonify({'success': True, 'tracked': False})
    return jsonify({'success': True, 'tracked': True})


@help_bp.route('/api/help/analytics/summary', methods=['GET'])
@optional_auth
def help_analytics_summary():
    """Admin-oriented: top searches + sections + zero-result queries last 30d."""
    try:
        _init_help_schema()
        with db_context() as db:
            # Top searches that returned 0 results (what's missing from FAQ)
            if is_postgres():
                zero_rows = db.execute(
                    "SELECT query, COUNT(*) AS n FROM help_analytics "
                    "WHERE event_type = 'search' AND result_count = 0 "
                    "AND created_at > CURRENT_TIMESTAMP - INTERVAL '30 days' "
                    "AND query != '' "
                    "GROUP BY query ORDER BY n DESC LIMIT 10"
                ).fetchall()
                top_sections = db.execute(
                    "SELECT section, COUNT(*) AS n FROM help_analytics "
                    "WHERE event_type = 'section' "
                    "AND created_at > CURRENT_TIMESTAMP - INTERVAL '30 days' "
                    "GROUP BY section ORDER BY n DESC"
                ).fetchall()
            else:
                zero_rows = db.execute(
                    "SELECT query, COUNT(*) AS n FROM help_analytics "
                    "WHERE event_type = 'search' AND result_count = 0 "
                    "AND created_at > datetime('now', '-30 days') "
                    "AND query != '' "
                    "GROUP BY query ORDER BY n DESC LIMIT 10"
                ).fetchall()
                top_sections = db.execute(
                    "SELECT section, COUNT(*) AS n FROM help_analytics "
                    "WHERE event_type = 'section' "
                    "AND created_at > datetime('now', '-30 days') "
                    "GROUP BY section ORDER BY n DESC"
                ).fetchall()

        def _rows(rows):
            out = []
            for r in rows or []:
                k = r[0] if isinstance(r, (list, tuple)) else r.get('query') or r.get('section')
                n = r[1] if isinstance(r, (list, tuple)) else r.get('n')
                out.append({'key': k or '', 'count': int(n or 0)})
            return out

        return jsonify({
            'success': True,
            'zero_result_searches': _rows(zero_rows),
            'top_sections': _rows(top_sections),
        })
    except Exception as e:
        return jsonify({'success': True, 'zero_result_searches': [], 'top_sections': []})


logger.info("❓ Help routes v1.1 loaded — feedback + count + ask (Gemini) + view analytics")
