"""
📝 NOTES ROUTES v1.0 (Sprint C)
=============================================================================
Backend for the Notes frontend module — CRUD + family share + conversion
hooks to Calendar / Tasks modules.

- GET/POST /api/notes — list user's notes / create
- GET/PUT/DELETE /api/notes/<id> — individual CRUD
- POST /api/notes/<id>/share — toggle share_with_family flag + notify
- POST /api/notes/<id>/to-event — convert note to calendar event
- POST /api/notes/<id>/to-task — convert note to task

Family members with confirmed senior_family_links can read notes where
share_with_family=TRUE (separate list endpoint).
"""

import json
import logging
from datetime import datetime
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

notes_bp = Blueprint('notes', __name__)


NOTES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_notes (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        client_id TEXT,
        text TEXT NOT NULL,
        category TEXT DEFAULT 'personal',
        pinned BOOLEAN DEFAULT FALSE,
        important BOOLEAN DEFAULT FALSE,
        share_with_family BOOLEAN DEFAULT FALSE,
        mood JSONB,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_user_notes_user ON user_notes(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_user_notes_shared ON user_notes(share_with_family, user_id);
    CREATE INDEX IF NOT EXISTS idx_user_notes_client ON user_notes(user_id, client_id);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in NOTES_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Notes schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_to_dict(r):
    def v(i, k):
        return r[i] if isinstance(r, (list, tuple)) else r.get(k)
    mood_raw = v(7, 'mood')
    try:
        mood = json.loads(mood_raw) if isinstance(mood_raw, str) else (mood_raw or None)
    except Exception:
        mood = None
    return {
        'id': v(0, 'id'),
        'clientId': v(1, 'client_id'),
        'text': v(2, 'text'),
        'category': v(3, 'category') or 'personal',
        'pinned': bool(v(4, 'pinned')),
        'important': bool(v(5, 'important')),
        'shareWithFamily': bool(v(6, 'share_with_family')),
        'mood': mood,
        'createdAt': str(v(8, 'created_at') or ''),
    }


@notes_bp.route('/api/notes', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def notes_collection():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'GET':
        limit = max(1, min(int(request.args.get('limit', 100)), 500))
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, client_id, text, category, pinned, important, "
                    "share_with_family, mood, created_at "
                    "FROM user_notes WHERE user_id = ? "
                    "ORDER BY pinned DESC, created_at DESC LIMIT ?",
                    (uid, limit)
                ).fetchall()
        except Exception as e:
            logger.error(f"notes GET: {e}")
            return jsonify({'success': True, 'notes': [], 'count': 0})
        notes = [_row_to_dict(r) for r in rows or []]
        return jsonify({'success': True, 'notes': notes, 'count': len(notes)})

    # POST
    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'text required'}), 400
    text = text[:10000]

    category = (data.get('category') or 'personal')[:32]
    pinned = bool(data.get('pinned'))
    important = bool(data.get('important'))
    share = bool(data.get('shareWithFamily'))
    client_id = (data.get('clientId') or '')[:64] or None
    mood = data.get('mood')
    mood_json = json.dumps(mood) if mood else None

    try:
        with db_context(commit=True) as db:
            # Idempotent upsert by (user_id, client_id) if client_id provided
            if client_id:
                existing = db.execute(
                    "SELECT id FROM user_notes WHERE user_id = ? AND client_id = ?",
                    (uid, client_id)
                ).fetchone()
                if existing:
                    eid = existing[0] if isinstance(existing, (list, tuple)) else existing.get('id')
                    return jsonify({'success': True, 'id': eid, 'deduped': True})

            if is_postgres():
                row = db.execute(
                    "INSERT INTO user_notes "
                    "(user_id, client_id, text, category, pinned, important, "
                    "share_with_family, mood) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, client_id, text, category, pinned, important, share, mood_json)
                ).fetchone()
                new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO user_notes "
                    "(user_id, client_id, text, category, pinned, important, "
                    "share_with_family, mood) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, client_id, text, category,
                     1 if pinned else 0, 1 if important else 0,
                     1 if share else 0, mood_json)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        logger.error(f"notes POST: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@notes_bp.route('/api/notes/<int:note_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def note_item(note_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'DELETE':
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "DELETE FROM user_notes WHERE id = ? AND user_id = ?",
                    (note_id, uid)
                )
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    if request.method == 'GET':
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT id, client_id, text, category, pinned, important, "
                    "share_with_family, mood, created_at "
                    "FROM user_notes WHERE id = ? AND user_id = ?",
                    (note_id, uid)
                ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            return jsonify({'success': True, 'note': _row_to_dict(row)})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    # PUT — partial update
    data = request.get_json() or {}
    allowed = {
        'text': 'text', 'category': 'category',
        'pinned': 'pinned', 'important': 'important',
        'shareWithFamily': 'share_with_family',
    }
    updates = {}
    for key_in, col in allowed.items():
        if key_in in data:
            val = data[key_in]
            if col in ('pinned', 'important', 'share_with_family'):
                val = bool(val) if is_postgres() else (1 if val else 0)
            elif col == 'text':
                val = str(val or '').strip()[:10000]
                if not val:
                    return jsonify({'success': False, 'error': 'text cannot be empty'}), 400
            elif col == 'category':
                val = str(val or 'personal')[:32]
            updates[col] = val
    if not updates:
        return jsonify({'success': False, 'error': 'no updatable fields'}), 400

    try:
        set_clause = ', '.join([f"{col} = ?" for col in updates.keys()])
        params = list(updates.values()) + [note_id, uid]
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE user_notes SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? AND user_id = ?",
                tuple(params)
            )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@notes_bp.route('/api/notes/<int:note_id>/share', methods=['POST'])
@require_auth
def toggle_share(note_id):
    """Toggle share_with_family flag. Notify linked family members on enable."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT text, share_with_family FROM user_notes "
                "WHERE id = ? AND user_id = ?",
                (note_id, uid)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            text = row[0] if isinstance(row, (list, tuple)) else row.get('text')
            current = bool(row[1] if isinstance(row, (list, tuple)) else row.get('share_with_family'))
            new_value = not current
            db.execute(
                "UPDATE user_notes SET share_with_family = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (True if is_postgres() else (1 if new_value else 0), note_id, uid)
                if new_value else
                (False if is_postgres() else 0, note_id, uid)
            )
    except Exception as e:
        logger.error(f"share toggle: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500

    # Notify family on enable — reuse existing senior_family_links + notify()
    if new_value:
        try:
            from notification_helpers import notify_senior_family
            snippet = (text or '')[:80]
            notify_senior_family(
                senior_id=uid,
                type='info',
                title='📝 Nová sdílená poznámka',
                body=f'Váš blízký s vámi sdílí poznámku: „{snippet}"',
                severity='info',
                data={'note_id': note_id},
                include_caregiver=True,
            )
        except Exception as e:
            logger.debug(f"family notify on share: {e}")

    return jsonify({'success': True, 'shareWithFamily': new_value})


@notes_bp.route('/api/notes/family/<senior_id>', methods=['GET'])
@require_auth
def family_view(senior_id):
    """List shared notes from a senior for a linked family member."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Verify link
    try:
        with db_context() as db:
            link = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                (senior_id, uid, True if is_postgres() else 1)
            ).fetchone()
    except Exception:
        link = None

    if not link:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, client_id, text, category, pinned, important, "
                "share_with_family, mood, created_at "
                "FROM user_notes "
                "WHERE user_id = ? AND share_with_family = ? "
                "ORDER BY pinned DESC, created_at DESC LIMIT 100",
                (senior_id, True if is_postgres() else 1)
            ).fetchall()
    except Exception as e:
        logger.error(f"family view: {e}")
        return jsonify({'success': True, 'notes': [], 'count': 0})

    notes = [_row_to_dict(r) for r in rows or []]
    return jsonify({'success': True, 'notes': notes, 'count': len(notes)})


@notes_bp.route('/api/notes/<int:note_id>/to-event', methods=['POST'])
@require_auth
def convert_to_event(note_id):
    """Convert note → calendar event. Body may provide {date, time}.

    If not provided, server attempts to parse from note text via the
    calendar parser (reuses /api/calendar/parse). Creates event in
    calendar_events and returns event id.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT text FROM user_notes WHERE id = ? AND user_id = ?",
                (note_id, uid)
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return jsonify({'success': False, 'error': 'note not found'}), 404
    text = row[0] if isinstance(row, (list, tuple)) else row.get('text')

    data = request.get_json() or {}
    event_date = data.get('date')
    event_time = data.get('time')
    title = (data.get('title') or '').strip() or (text or '')[:80]
    description = (data.get('description') or text or '')[:1000]

    # Try parsing from text if date missing
    if not event_date:
        try:
            from calendar_routes import _parse_event_rule_based
            parsed = _parse_event_rule_based(text or '')
            event_date = parsed.get('date')
            if not event_time and parsed.get('time'):
                event_time = parsed.get('time')
            if parsed.get('title') and not data.get('title'):
                title = parsed['title'][:80]
        except Exception as e:
            logger.debug(f"parser fallback: {e}")

    if not event_date:
        return jsonify({
            'success': False,
            'error': 'Nelze určit datum. Uveďte prosím datum v požadavku.'
        }), 400

    # Validate date format
    try:
        datetime.strptime(event_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'success': False, 'error': 'invalid date format'}), 400

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                ev_row = db.execute(
                    "INSERT INTO calendar_events "
                    "(user_id, title, date, time, description, type, reminder) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, title, event_date, event_time or '',
                     description, 'reminder', 1)
                ).fetchone()
                event_id = ev_row[0] if isinstance(ev_row, (list, tuple)) else ev_row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO calendar_events "
                    "(user_id, title, date, time, description, type, reminder) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, title, event_date, event_time or '',
                     description, 'reminder', 1)
                )
                event_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"note→event: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500

    return jsonify({
        'success': True,
        'eventId': event_id,
        'date': event_date,
        'time': event_time,
        'title': title,
    })


@notes_bp.route('/api/notes/<int:note_id>/to-task', methods=['POST'])
@require_auth
def convert_to_task(note_id):
    """Convert note → task entry in radim_tasks (reuses existing schema)."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT text FROM user_notes WHERE id = ? AND user_id = ?",
                (note_id, uid)
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return jsonify({'success': False, 'error': 'note not found'}), 404
    text = row[0] if isinstance(row, (list, tuple)) else row.get('text')

    data = request.get_json() or {}
    title = (data.get('title') or '').strip() or (text or '')[:120]
    priority = (data.get('priority') or 'normal')[:16]
    due_date = (data.get('dueDate') or '')[:10] or None

    try:
        with db_context(commit=True) as db:
            # Use radim_tasks if available; else create_task via TaskService
            if is_postgres():
                ev_row = db.execute(
                    "INSERT INTO radim_tasks "
                    "(user_id, title, task_type, status, scheduled_date, priority, "
                    "description) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, title, 'reminder', 'pending', due_date, priority,
                     text[:500] if text else '')
                ).fetchone()
                task_id = ev_row[0] if isinstance(ev_row, (list, tuple)) else ev_row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO radim_tasks "
                    "(user_id, title, task_type, status, scheduled_date, priority, "
                    "description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, title, 'reminder', 'pending', due_date, priority,
                     text[:500] if text else '')
                )
                task_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"note→task: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500

    return jsonify({'success': True, 'taskId': task_id, 'title': title})


logger.info("📝 Notes routes v1.0 loaded — CRUD + family share + note→event/task")
