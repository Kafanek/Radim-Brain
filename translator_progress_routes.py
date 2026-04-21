"""
🌐 TRANSLATOR PROGRESS ROUTES v1.0 (Sprint C)
=============================================================================
Backend sync for the Translator module v2.0:
- Translation history per user (with client_id idempotent dedupe)
- Phrase favorites per user (toggle, UNIQUE per user+phrase_id)
- Family activity report (linked relatives view senior's translation activity)
- GDPR compliant: history can be cleared on demand

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

translator_progress_bp = Blueprint('translator_progress', __name__)


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS translation_history (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        source_text TEXT NOT NULL,
        translated_text TEXT,
        source_lang TEXT,
        target_lang TEXT,
        provider TEXT,
        client_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS phrase_favorites (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        phrase_id TEXT NOT NULL,
        source_text TEXT,
        target_text TEXT,
        lang_pair TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, phrase_id)
    );

    CREATE INDEX IF NOT EXISTS idx_trans_hist_user ON translation_history(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_trans_hist_client ON translation_history(user_id, client_id);
    CREATE INDEX IF NOT EXISTS idx_phrase_fav_user ON phrase_favorites(user_id, created_at DESC);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in SCHEMA_SQL.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"translator schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


def _valid_lang(code):
    if not code or not isinstance(code, str):
        return False
    return bool(code.strip()) and len(code) <= 8 and code.replace('-', '').isalnum()


# ============================================================
# TRANSLATION HISTORY
# ============================================================

@translator_progress_bp.route('/api/translator/history', methods=['POST', 'OPTIONS'])
@require_auth
def add_history():
    """Save a translation. Body: {sourceText, translatedText, sourceLang,
    targetLang, provider?, clientId?}.

    Idempotent on (user_id, client_id) — re-posts return the existing id.
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    source_text = (data.get('sourceText') or data.get('source_text') or '').strip()
    if not source_text:
        return jsonify({'success': False, 'error': 'sourceText required'}), 400
    source_text = source_text[:5000]

    translated = (data.get('translatedText') or data.get('translated_text') or '')[:5000] or None
    source_lang = (data.get('sourceLang') or data.get('source_lang') or '')[:8] or None
    target_lang = (data.get('targetLang') or data.get('target_lang') or '')[:8] or None
    provider = (data.get('provider') or '')[:32] or None
    client_id = (data.get('clientId') or data.get('client_id') or '')[:64] or None

    # Validate language codes
    if source_lang and source_lang != 'auto' and not _valid_lang(source_lang):
        return jsonify({'success': False, 'error': 'invalid sourceLang'}), 400
    if target_lang and not _valid_lang(target_lang):
        return jsonify({'success': False, 'error': 'invalid targetLang'}), 400

    try:
        with db_context(commit=True) as db:
            # Idempotent upsert on client_id
            if client_id:
                existing = db.execute(
                    "SELECT id FROM translation_history "
                    "WHERE user_id = ? AND client_id = ?",
                    (uid, client_id)
                ).fetchone()
                if existing:
                    eid = _row_val(existing, 0, 'id')
                    return jsonify({'success': True, 'id': eid, 'deduped': True})

            if is_postgres():
                row = db.execute(
                    "INSERT INTO translation_history "
                    "(user_id, source_text, translated_text, source_lang, "
                    "target_lang, provider, client_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, source_text, translated, source_lang, target_lang,
                     provider, client_id)
                ).fetchone()
                new_id = _row_val(row, 0, 'id')
            else:
                cur = db.execute(
                    "INSERT INTO translation_history "
                    "(user_id, source_text, translated_text, source_lang, "
                    "target_lang, provider, client_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, source_text, translated, source_lang, target_lang,
                     provider, client_id)
                )
                new_id = getattr(cur, 'lastrowid', None)
        return jsonify({'success': True, 'id': new_id})
    except Exception as e:
        logger.error(f"add_history: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@translator_progress_bp.route('/api/translator/history', methods=['GET'])
@require_auth
def list_history():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    days = max(1, min(int(request.args.get('days', 30)), 365))
    cutoff = datetime.utcnow() - timedelta(days=days)
    limit = max(1, min(int(request.args.get('limit', 50)), 200))

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, source_text, translated_text, source_lang, "
                "target_lang, provider, created_at FROM translation_history "
                "WHERE user_id = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (uid, cutoff, limit)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_history: {e}")
        return jsonify({'success': True, 'history': []})

    history = [{
        'id': _row_val(r, 0, 'id'),
        'sourceText': _row_val(r, 1, 'source_text'),
        'translatedText': _row_val(r, 2, 'translated_text'),
        'sourceLang': _row_val(r, 3, 'source_lang'),
        'targetLang': _row_val(r, 4, 'target_lang'),
        'provider': _row_val(r, 5, 'provider'),
        'createdAt': str(_row_val(r, 6, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'history': history, 'count': len(history)})


@translator_progress_bp.route('/api/translator/history', methods=['DELETE'])
@require_auth
def delete_history():
    """GDPR — wipe all translation history for current user."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM translation_history WHERE user_id = ?", (uid,))
        return jsonify({'success': True, 'cleared': True})
    except Exception as e:
        logger.error(f"delete_history: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# PHRASE FAVORITES
# ============================================================

@translator_progress_bp.route('/api/translator/favorite', methods=['POST', 'OPTIONS'])
@require_auth
def toggle_favorite():
    """Toggle a phrase favorite. Body: {phraseId, sourceText?, targetText?,
    langPair?}."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    phrase_id = (data.get('phraseId') or data.get('phrase_id') or '').strip()
    if not phrase_id:
        return jsonify({'success': False, 'error': 'phraseId required'}), 400
    phrase_id = phrase_id[:64]
    source_text = (data.get('sourceText') or data.get('source_text') or '')[:500] or None
    target_text = (data.get('targetText') or data.get('target_text') or '')[:500] or None
    lang_pair = (data.get('langPair') or data.get('lang_pair') or '')[:16] or None

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM phrase_favorites "
                "WHERE user_id = ? AND phrase_id = ?",
                (uid, phrase_id)
            ).fetchone()
            if existing:
                db.execute(
                    "DELETE FROM phrase_favorites "
                    "WHERE user_id = ? AND phrase_id = ?",
                    (uid, phrase_id)
                )
                return jsonify({'success': True, 'favorited': False})
            db.execute(
                "INSERT INTO phrase_favorites "
                "(user_id, phrase_id, source_text, target_text, lang_pair) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, phrase_id, source_text, target_text, lang_pair)
            )
        return jsonify({'success': True, 'favorited': True})
    except Exception as e:
        logger.error(f"toggle_favorite: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@translator_progress_bp.route('/api/translator/favorites', methods=['GET'])
@require_auth
def list_favorites():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT phrase_id, source_text, target_text, lang_pair, created_at "
                "FROM phrase_favorites "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_favorites: {e}")
        return jsonify({'success': True, 'favorites': []})

    favorites = [{
        'phraseId': _row_val(r, 0, 'phrase_id'),
        'sourceText': _row_val(r, 1, 'source_text'),
        'targetText': _row_val(r, 2, 'target_text'),
        'langPair': _row_val(r, 3, 'lang_pair'),
        'createdAt': str(_row_val(r, 4, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'favorites': favorites, 'count': len(favorites)})


# ============================================================
# FAMILY ACTIVITY (read-only weekly view for linked relatives)
# ============================================================

@translator_progress_bp.route('/api/translator/family/<senior_id>/activity', methods=['GET'])
@require_auth
def family_activity(senior_id):
    """Read-only weekly translation activity for a linked family member.

    Returns:
      - total translations in last 7 days
      - top 5 language pairs (by count)
      - 5 most recent source texts (no full translations to keep summary brief)
      - favorite phrases count
    """
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

    week_ago = datetime.utcnow() - timedelta(days=7)
    try:
        with db_context() as db:
            hist_rows = db.execute(
                "SELECT source_text, source_lang, target_lang, created_at "
                "FROM translation_history "
                "WHERE user_id = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT 200",
                (senior_id, week_ago)
            ).fetchall() or []
            fav_rows = db.execute(
                "SELECT COUNT(*) FROM phrase_favorites WHERE user_id = ?",
                (senior_id,)
            ).fetchone()
    except Exception as e:
        logger.error(f"family_activity: {e}")
        hist_rows = []
        fav_rows = None

    pair_counts = {}
    recent_texts = []
    for r in hist_rows:
        src = _row_val(r, 1, 'source_lang') or 'auto'
        tgt = _row_val(r, 2, 'target_lang') or '?'
        pair = f'{src}→{tgt}'
        pair_counts[pair] = pair_counts.get(pair, 0) + 1
        if len(recent_texts) < 5:
            text = (_row_val(r, 0, 'source_text') or '')[:80]
            recent_texts.append({
                'sourceText': text,
                'pair': pair,
                'createdAt': str(_row_val(r, 3, 'created_at') or ''),
            })

    top_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    fav_count = int(_row_val(fav_rows, 0, 'count') or 0) if fav_rows else 0

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'translationsLast7d': len(hist_rows),
        'topLanguagePairs': [{'pair': p, 'count': c} for p, c in top_pairs],
        'recentTexts': recent_texts,
        'favoritesTotal': fav_count,
    })


logger.info("🌐 Translator progress routes v1.0 loaded — history + favorites + family activity")
