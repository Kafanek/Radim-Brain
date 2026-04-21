"""
📚 LIBRARY PROGRESS ROUTES v1.0 (Sprint C)
=============================================================================
Backend sync for library v2.0 frontend:
- Idempotent reading progress per user+book (UNIQUE row)
- Bookmarks per user+book+paragraph
- Favorites per user+book
- "Continue reading" — last 30 days, in-progress books
- Family weekly reading report (linked relatives)

Auth: all endpoints require_auth. Family view additionally verifies
senior_family_links.confirmed=TRUE.
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

library_progress_bp = Blueprint('library_progress', __name__)


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS library_progress (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        title TEXT,
        chapter TEXT,
        paragraph INTEGER DEFAULT 0,
        percent INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, book_id)
    );

    CREATE TABLE IF NOT EXISTS library_bookmarks (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        paragraph INTEGER NOT NULL,
        label TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, book_id, paragraph)
    );

    CREATE TABLE IF NOT EXISTS library_favorites (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        book_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, book_id)
    );

    CREATE INDEX IF NOT EXISTS idx_lib_progress_user ON library_progress(user_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_lib_bookmarks_user_book ON library_bookmarks(user_id, book_id);
    CREATE INDEX IF NOT EXISTS idx_lib_favorites_user ON library_favorites(user_id);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in SCHEMA_SQL.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"library_progress schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


# ============================================================
# READING PROGRESS — upsert, list, get-one
# ============================================================

@library_progress_bp.route('/api/library/progress/<book_id>', methods=['POST', 'OPTIONS'])
@require_auth
def upsert_progress(book_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    book_id = (book_id or '').strip()[:64]
    if not book_id:
        return jsonify({'success': False, 'error': 'book_id required'}), 400

    data = request.get_json() or {}
    paragraph = max(0, int(data.get('paragraph') or 0))
    percent = max(0, min(100, int(data.get('percent') or 0)))
    title = (data.get('title') or '')[:160] or None
    chapter = (data.get('chapter') or '')[:64] or None

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id, percent FROM library_progress "
                "WHERE user_id = ? AND book_id = ?",
                (uid, book_id)
            ).fetchone()
            if existing:
                # Keep max percent (don't roll back if frontend sends stale)
                old_pct = int(_row_val(existing, 1, 'percent') or 0)
                new_pct = max(old_pct, percent)
                db.execute(
                    "UPDATE library_progress SET "
                    "title = COALESCE(?, title), chapter = ?, paragraph = ?, "
                    "percent = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = ? AND book_id = ?",
                    (title, chapter, paragraph, new_pct, uid, book_id)
                )
                return jsonify({'success': True, 'updated': True, 'percent': new_pct})
            db.execute(
                "INSERT INTO library_progress "
                "(user_id, book_id, title, chapter, paragraph, percent) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, book_id, title, chapter, paragraph, percent)
            )
        return jsonify({'success': True, 'created': True, 'percent': percent})
    except Exception as e:
        logger.error(f"upsert_progress: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@library_progress_bp.route('/api/library/progress', methods=['GET'])
@require_auth
def list_progress():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT book_id, title, chapter, paragraph, percent, updated_at "
                "FROM library_progress WHERE user_id = ? "
                "ORDER BY updated_at DESC LIMIT 200",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_progress: {e}")
        return jsonify({'success': True, 'progress': []})

    progress = [{
        'bookId': _row_val(r, 0, 'book_id'),
        'title': _row_val(r, 1, 'title'),
        'chapter': _row_val(r, 2, 'chapter'),
        'paragraph': int(_row_val(r, 3, 'paragraph') or 0),
        'percent': int(_row_val(r, 4, 'percent') or 0),
        'updatedAt': str(_row_val(r, 5, 'updated_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'progress': progress, 'count': len(progress)})


@library_progress_bp.route('/api/library/continue-reading', methods=['GET'])
@require_auth
def continue_reading():
    """In-progress books from last 30 days (percent 1-99)."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    cutoff = datetime.utcnow() - timedelta(days=30)
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT book_id, title, chapter, paragraph, percent, updated_at "
                "FROM library_progress "
                "WHERE user_id = ? AND percent > 0 AND percent < 100 "
                "AND updated_at >= ? "
                "ORDER BY updated_at DESC LIMIT 20",
                (uid, cutoff)
            ).fetchall()
    except Exception as e:
        logger.error(f"continue_reading: {e}")
        return jsonify({'success': True, 'books': []})

    books = [{
        'bookId': _row_val(r, 0, 'book_id'),
        'title': _row_val(r, 1, 'title'),
        'chapter': _row_val(r, 2, 'chapter'),
        'paragraph': int(_row_val(r, 3, 'paragraph') or 0),
        'percent': int(_row_val(r, 4, 'percent') or 0),
        'updatedAt': str(_row_val(r, 5, 'updated_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'books': books, 'count': len(books)})


# ============================================================
# BOOKMARKS
# ============================================================

@library_progress_bp.route('/api/library/bookmark/<book_id>', methods=['POST', 'OPTIONS'])
@require_auth
def add_bookmark(book_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    book_id = (book_id or '').strip()[:64]
    data = request.get_json() or {}
    paragraph = data.get('paragraph')
    if paragraph is None:
        return jsonify({'success': False, 'error': 'paragraph required'}), 400
    paragraph = max(0, int(paragraph))
    label = (data.get('label') or '')[:160] or None

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM library_bookmarks "
                "WHERE user_id = ? AND book_id = ? AND paragraph = ?",
                (uid, book_id, paragraph)
            ).fetchone()
            if existing:
                # Toggle: delete if already exists
                db.execute(
                    "DELETE FROM library_bookmarks "
                    "WHERE user_id = ? AND book_id = ? AND paragraph = ?",
                    (uid, book_id, paragraph)
                )
                return jsonify({'success': True, 'toggled': 'removed'})
            db.execute(
                "INSERT INTO library_bookmarks "
                "(user_id, book_id, paragraph, label) "
                "VALUES (?, ?, ?, ?)",
                (uid, book_id, paragraph, label)
            )
        return jsonify({'success': True, 'toggled': 'added'})
    except Exception as e:
        logger.error(f"add_bookmark: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@library_progress_bp.route('/api/library/bookmarks/<book_id>', methods=['GET'])
@require_auth
def list_bookmarks(book_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    book_id = (book_id or '').strip()[:64]
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT paragraph, label, created_at FROM library_bookmarks "
                "WHERE user_id = ? AND book_id = ? "
                "ORDER BY paragraph ASC LIMIT 200",
                (uid, book_id)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_bookmarks: {e}")
        return jsonify({'success': True, 'bookmarks': []})

    bookmarks = [{
        'paragraph': int(_row_val(r, 0, 'paragraph') or 0),
        'label': _row_val(r, 1, 'label'),
        'createdAt': str(_row_val(r, 2, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'bookmarks': bookmarks, 'count': len(bookmarks)})


# ============================================================
# FAVORITES
# ============================================================

@library_progress_bp.route('/api/library/favorite/<book_id>', methods=['POST', 'OPTIONS'])
@require_auth
def toggle_favorite(book_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    book_id = (book_id or '').strip()[:64]
    if not book_id:
        return jsonify({'success': False, 'error': 'book_id required'}), 400

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM library_favorites WHERE user_id = ? AND book_id = ?",
                (uid, book_id)
            ).fetchone()
            if existing:
                db.execute(
                    "DELETE FROM library_favorites WHERE user_id = ? AND book_id = ?",
                    (uid, book_id)
                )
                return jsonify({'success': True, 'favorited': False})
            db.execute(
                "INSERT INTO library_favorites (user_id, book_id) VALUES (?, ?)",
                (uid, book_id)
            )
        return jsonify({'success': True, 'favorited': True})
    except Exception as e:
        logger.error(f"toggle_favorite: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@library_progress_bp.route('/api/library/favorites', methods=['GET'])
@require_auth
def list_favorites():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT book_id, created_at FROM library_favorites "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_favorites: {e}")
        return jsonify({'success': True, 'favorites': []})

    favorites = [{
        'bookId': _row_val(r, 0, 'book_id'),
        'createdAt': str(_row_val(r, 1, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'favorites': favorites, 'count': len(favorites)})


# ============================================================
# FAMILY WEEKLY REPORT
# ============================================================

@library_progress_bp.route('/api/library/family/<senior_id>/reading', methods=['GET'])
@require_auth
def family_reading(senior_id):
    """Weekly reading summary for a family member linked to senior."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Verify senior_family_links
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

    week_ago = datetime.utcnow() - timedelta(days=7)
    try:
        with db_context() as db:
            prog_rows = db.execute(
                "SELECT book_id, title, percent, updated_at "
                "FROM library_progress "
                "WHERE user_id = ? AND updated_at >= ? "
                "ORDER BY updated_at DESC LIMIT 50",
                (senior_id, week_ago)
            ).fetchall() or []
            fav_rows = db.execute(
                "SELECT COUNT(*) FROM library_favorites WHERE user_id = ?",
                (senior_id,)
            ).fetchone()
    except Exception as e:
        logger.error(f"family_reading: {e}")
        prog_rows = []
        fav_rows = None

    books_read = []
    finished = 0
    in_progress = 0
    for r in prog_rows:
        pct = int(_row_val(r, 2, 'percent') or 0)
        books_read.append({
            'bookId': _row_val(r, 0, 'book_id'),
            'title': _row_val(r, 1, 'title'),
            'percent': pct,
            'updatedAt': str(_row_val(r, 3, 'updated_at') or ''),
        })
        if pct >= 100: finished += 1
        elif pct > 0: in_progress += 1

    fav_count = int(_row_val(fav_rows, 0, 'count') or 0) if fav_rows else 0

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'weekActivity': len(books_read),
        'finished': finished,
        'inProgress': in_progress,
        'favoritesTotal': fav_count,
        'recent': books_read[:10],
    })


logger.info("📚 Library progress routes v1.0 loaded — progress + bookmarks + favorites + family reading")
