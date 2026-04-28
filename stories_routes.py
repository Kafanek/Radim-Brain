"""
📖 STORIES ROUTES v1.0 (Sprint C)
=============================================================================
Backend for the Stories frontend module — event CRUD + series continuation.

- GET/POST /api/stories — list/create user's stories
- GET/PUT/DELETE /api/stories/<id> — individual story ops
- POST /api/stories/<id>/continue — generate next chapter via Claude
  (fallback Gemini) with prior context.

All endpoints require auth (@require_auth). user_id = g.auth_user.id.
"""

import json
import logging
import os
from datetime import datetime
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

stories_bp = Blueprint('stories', __name__)


STORIES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_stories (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        genre TEXT DEFAULT 'fairy-tale',
        theme TEXT,
        length TEXT DEFAULT 'medium',
        favorite BOOLEAN DEFAULT FALSE,
        rating INTEGER DEFAULT 0,
        read_count INTEGER DEFAULT 0,
        series_id INTEGER,
        chapter_number INTEGER DEFAULT 1,
        parent_story_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_user_stories_user ON user_stories(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_user_stories_series ON user_stories(series_id, chapter_number);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in STORIES_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Stories schema init: {e}")


def _uid():
    au = getattr(g, "auth_user", None) or {}
    return str(au.get("id") or au.get("user_id") or "")


def _row_to_dict(r):
    def v(i, k):
        return r[i] if isinstance(r, (list, tuple)) else r.get(k)
    return {
        'id': v(0, 'id'),
        'title': v(1, 'title'),
        'content': v(2, 'content'),
        'genre': v(3, 'genre'),
        'theme': v(4, 'theme'),
        'length': v(5, 'length'),
        'favorite': bool(v(6, 'favorite')),
        'rating': v(7, 'rating') or 0,
        'readCount': v(8, 'read_count') or 0,
        'seriesId': v(9, 'series_id'),
        'chapterNumber': v(10, 'chapter_number') or 1,
        'parentStoryId': v(11, 'parent_story_id'),
        'createdAt': str(v(12, 'created_at') or ''),
    }


@stories_bp.route('/api/stories', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def stories_collection():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'GET':
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
        favorites_only = request.args.get('favorites') in ('1', 'true', 'yes')
        try:
            with db_context() as db:
                if favorites_only:
                    rows = db.execute(
                        "SELECT id, title, content, genre, theme, length, favorite, "
                        "rating, read_count, series_id, chapter_number, parent_story_id, created_at "
                        "FROM user_stories WHERE user_id = ? AND favorite = ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (uid, True if is_postgres() else 1, limit)
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT id, title, content, genre, theme, length, favorite, "
                        "rating, read_count, series_id, chapter_number, parent_story_id, created_at "
                        "FROM user_stories WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (uid, limit)
                    ).fetchall()
        except Exception as e:
            logger.error(f"stories GET: {e}")
            return jsonify({'success': True, 'stories': [], 'count': 0})

        stories = [_row_to_dict(r) for r in rows or []]
        return jsonify({'success': True, 'stories': stories, 'count': len(stories)})

    # POST
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()[:200]
    content = (data.get('content') or '').strip()[:20000]
    if not title or not content:
        return jsonify({'success': False, 'error': 'title + content required'}), 400

    genre = (data.get('genre') or 'fairy-tale')[:32]
    theme = (data.get('theme') or '')[:64]
    length = (data.get('length') or 'medium')[:16]
    favorite = bool(data.get('favorite'))
    rating = max(0, min(int(data.get('rating') or 0), 5))
    series_id = data.get('seriesId')
    chapter_number = max(1, int(data.get('chapterNumber') or 1))
    parent_id = data.get('parentStoryId')

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                row = db.execute(
                    "INSERT INTO user_stories "
                    "(user_id, title, content, genre, theme, length, favorite, rating, "
                    "series_id, chapter_number, parent_story_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, title, content, genre, theme, length, favorite, rating,
                     series_id, chapter_number, parent_id)
                ).fetchone()
                new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO user_stories "
                    "(user_id, title, content, genre, theme, length, favorite, rating, "
                    "series_id, chapter_number, parent_story_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, title, content, genre, theme, length,
                     1 if favorite else 0, rating,
                     series_id, chapter_number, parent_id)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        logger.error(f"stories POST: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@stories_bp.route('/api/stories/<int:story_id>', methods=['GET', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def story_item(story_id):
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
                    "DELETE FROM user_stories WHERE id = ? AND user_id = ?",
                    (story_id, uid)
                )
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    if request.method == 'GET':
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT id, title, content, genre, theme, length, favorite, "
                    "rating, read_count, series_id, chapter_number, parent_story_id, created_at "
                    "FROM user_stories WHERE id = ? AND user_id = ?",
                    (story_id, uid)
                ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            return jsonify({'success': True, 'story': _row_to_dict(row)})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    # PUT — partial update
    data = request.get_json(silent=True) or {}
    allowed = {
        'title': 'title', 'content': 'content', 'genre': 'genre',
        'theme': 'theme', 'length': 'length',
        'favorite': 'favorite', 'rating': 'rating',
        'readCount': 'read_count',
    }
    updates = {}
    for key_in, col in allowed.items():
        if key_in in data:
            val = data[key_in]
            if col == 'favorite':
                val = bool(val) if is_postgres() else (1 if val else 0)
            elif col == 'rating':
                val = max(0, min(int(val or 0), 5))
            elif col == 'read_count':
                val = max(0, int(val or 0))
            updates[col] = val
    if not updates:
        return jsonify({'success': False, 'error': 'no updatable fields'}), 400

    try:
        set_clause = ', '.join([f"{col} = ?" for col in updates.keys()])
        params = list(updates.values()) + [story_id, uid]
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE user_stories SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? AND user_id = ?",
                tuple(params)
            )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@stories_bp.route('/api/stories/<int:story_id>/continue', methods=['POST'])
@require_auth
def continue_story(story_id):
    """Generate next chapter continuing from this story (or its series).

    Passes prior chapter context to Claude; falls back to Gemini. Saves
    the new chapter linked via series_id + chapter_number+1.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Fetch the anchor story + any existing chapters in same series
    try:
        with db_context() as db:
            anchor = db.execute(
                "SELECT id, title, content, genre, theme, series_id, chapter_number "
                "FROM user_stories WHERE id = ? AND user_id = ?",
                (story_id, uid)
            ).fetchone()
    except Exception as e:
        return jsonify({'success': False, 'error': 'db_error'}), 500

    if not anchor:
        return jsonify({'success': False, 'error': 'story not found'}), 404

    def v(r, i, k): return r[i] if isinstance(r, (list, tuple)) else r.get(k)

    anchor_id = v(anchor, 0, 'id')
    anchor_title = v(anchor, 1, 'title')
    anchor_content = v(anchor, 2, 'content')
    genre = v(anchor, 3, 'genre') or 'fairy-tale'
    theme = v(anchor, 4, 'theme') or ''
    series_id = v(anchor, 5, 'series_id') or anchor_id  # anchor story seeds the series
    anchor_chapter = v(anchor, 6, 'chapter_number') or 1

    # Gather previous chapters (chronological)
    try:
        with db_context() as db:
            chapters = db.execute(
                "SELECT chapter_number, title, content FROM user_stories "
                "WHERE user_id = ? AND series_id = ? "
                "ORDER BY chapter_number",
                (uid, series_id)
            ).fetchall()
    except Exception:
        chapters = []

    if not chapters:
        # Anchor itself counts as chapter 1
        chapters_list = [(anchor_chapter, anchor_title, anchor_content)]
    else:
        chapters_list = [
            (v(c, 0, 'chapter_number'), v(c, 1, 'title'), v(c, 2, 'content'))
            for c in chapters
        ]
        # Ensure anchor is included (series_id might not be set on anchor yet)
        if not any(ch[0] == anchor_chapter for ch in chapters_list):
            chapters_list.insert(0, (anchor_chapter, anchor_title, anchor_content))

    next_chapter_num = max(ch[0] for ch in chapters_list) + 1

    # Build context (condense long chapters to avoid token bloat)
    context_parts = []
    for num, ttl, cnt in chapters_list[-3:]:  # last 3 chapters max
        snippet = cnt[:600] + ('…' if len(cnt) > 600 else '')
        context_parts.append(f"KAPITOLA {num}: {ttl}\n{snippet}")
    context = '\n\n'.join(context_parts)

    system = (
        f"Pokračuj v příběhu jako kapitola č. {next_chapter_num}. "
        f"Žánr: {genre}. Téma: {theme or 'pokračování'}. "
        "Styl pro seniory: pozitivní, česká jména a místa, bez násilí. "
        "Naznav přímo na předchozí kapitoly — zachovej postavy a místo. "
        "Délka: 150–300 slov. Odpověz POUZE JSON ve formátu:\n"
        '{"title": "Název kapitoly", "content": "Text kapitoly"}'
    )
    prompt_user = f"Předchozí kapitoly:\n{context}\n\nNapiš kapitolu {next_chapter_num}."

    text = None

    # Try Claude
    try:
        from claude_content_routes import _get_claude_helpers
        get_claude_client, extract_text_from_response, _, _, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
        client = get_claude_client()
        if client:
            try:
                resp = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=900,
                    system=system,
                    messages=[{"role": "user", "content": prompt_user}]
                )
                text = extract_text_from_response(resp)
            except Exception as claude_err:
                logger.debug(f"Claude continuation failed: {claude_err}")
        # Gemini fallback
        if not text and call_gemini_fallback:
            gemini_text = call_gemini_fallback(prompt_user, system, 900)
            if gemini_text:
                text = gemini_text
    except Exception as e:
        logger.debug(f"continuation import failed: {e}")

    if not text:
        return jsonify({
            'success': False,
            'error': 'Nepodařilo se vygenerovat pokračování.',
        }), 502

    # Parse JSON from response
    import re
    parsed = None
    try:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
    except Exception:
        parsed = None
    if not parsed:
        parsed = {
            'title': f"{anchor_title} — kapitola {next_chapter_num}",
            'content': text.strip()
        }

    new_title = (parsed.get('title') or f"Kapitola {next_chapter_num}")[:200]
    new_content = (parsed.get('content') or text.strip())[:20000]

    # Persist new chapter + backfill anchor's series_id if missing
    try:
        with db_context(commit=True) as db:
            # Update anchor to belong to this series if not already
            if not v(anchor, 5, 'series_id'):
                db.execute(
                    "UPDATE user_stories SET series_id = ? WHERE id = ? AND user_id = ?",
                    (series_id, anchor_id, uid)
                )

            if is_postgres():
                row = db.execute(
                    "INSERT INTO user_stories "
                    "(user_id, title, content, genre, theme, length, series_id, "
                    "chapter_number, parent_story_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, new_title, new_content, genre, theme, 'medium',
                     series_id, next_chapter_num, anchor_id)
                ).fetchone()
                new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO user_stories "
                    "(user_id, title, content, genre, theme, length, series_id, "
                    "chapter_number, parent_story_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, new_title, new_content, genre, theme, 'medium',
                     series_id, next_chapter_num, anchor_id)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"save continuation: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500

    return jsonify({
        'success': True,
        'id': new_id,
        'title': new_title,
        'content': new_content,
        'seriesId': series_id,
        'chapterNumber': next_chapter_num,
    })


logger.info("📖 Stories routes v1.0 loaded — CRUD + series continuation")
