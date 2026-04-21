"""
🌐 INTERNET ROUTES v1.0 (Sprint C)
=============================================================================
Backend sync for the Internet module v4.0:
- Favorites per user (idempotent toggle)
- Persistent visit history (last 200 per user)
- Server-side search proxy (DuckDuckGo HTML, no tracking)
- Server-side page translation (Gemini, falls back to Google Translate URL)
- Family activity report (linked relatives view senior's web activity)
- GDPR compliant: history can be cleared on demand

Auth: all endpoints require_auth. Family view additionally verifies
senior_family_links.confirmed=TRUE.
"""

import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

internet_bp = Blueprint('internet', __name__)


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS web_favorites (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        category TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, url)
    );

    CREATE TABLE IF NOT EXISTS web_history (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        host TEXT,
        visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_web_favorites_user ON web_favorites(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_web_history_user ON web_history(user_id, visited_at DESC);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in SCHEMA_SQL.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"internet schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


def _host_from(url):
    try:
        return urllib.parse.urlparse(url).hostname or ''
    except Exception:
        return ''


def _validate_url(url):
    """Reject obviously bad / dangerous URLs."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if len(url) > 2048:
        return False
    if not re.match(r'^https?://', url, re.IGNORECASE):
        return False
    # Block local/private addresses
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or '').lower()
    if not host:
        return False
    if host in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False
    if host.startswith('192.168.') or host.startswith('10.') or host.startswith('172.16.'):
        return False
    return True


# ============================================================
# FAVORITES
# ============================================================

@internet_bp.route('/api/internet/favorite', methods=['POST', 'OPTIONS'])
@require_auth
def toggle_favorite():
    """Toggle a URL in user's favorites. Body: {url, title?, category?}."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not _validate_url(url):
        return jsonify({'success': False, 'error': 'invalid url'}), 400
    title = (data.get('title') or '')[:200] or None
    category = (data.get('category') or '')[:64] or None

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM web_favorites WHERE user_id = ? AND url = ?",
                (uid, url)
            ).fetchone()
            if existing:
                db.execute(
                    "DELETE FROM web_favorites WHERE user_id = ? AND url = ?",
                    (uid, url)
                )
                return jsonify({'success': True, 'favorited': False})
            db.execute(
                "INSERT INTO web_favorites (user_id, url, title, category) "
                "VALUES (?, ?, ?, ?)",
                (uid, url, title, category)
            )
        return jsonify({'success': True, 'favorited': True})
    except Exception as e:
        logger.error(f"toggle_favorite: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@internet_bp.route('/api/internet/favorites', methods=['GET'])
@require_auth
def list_favorites():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT url, title, category, created_at FROM web_favorites "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_favorites: {e}")
        return jsonify({'success': True, 'favorites': []})

    favorites = [{
        'url': _row_val(r, 0, 'url'),
        'title': _row_val(r, 1, 'title'),
        'category': _row_val(r, 2, 'category'),
        'createdAt': str(_row_val(r, 3, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'favorites': favorites, 'count': len(favorites)})


# ============================================================
# HISTORY
# ============================================================

@internet_bp.route('/api/internet/history', methods=['POST', 'OPTIONS'])
@require_auth
def add_history():
    """Append a visit to user's history. Body: {url, title?}."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    url = (data.get('url') or '').strip()
    if not _validate_url(url):
        return jsonify({'success': False, 'error': 'invalid url'}), 400
    title = (data.get('title') or '')[:200] or None
    host = _host_from(url)

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO web_history (user_id, url, title, host) "
                "VALUES (?, ?, ?, ?)",
                (uid, url, title, host)
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"add_history: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@internet_bp.route('/api/internet/history', methods=['GET'])
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
                "SELECT url, title, host, visited_at FROM web_history "
                "WHERE user_id = ? AND visited_at >= ? "
                "ORDER BY visited_at DESC LIMIT ?",
                (uid, cutoff, limit)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_history: {e}")
        return jsonify({'success': True, 'history': []})

    history = [{
        'url': _row_val(r, 0, 'url'),
        'title': _row_val(r, 1, 'title'),
        'host': _row_val(r, 2, 'host'),
        'visitedAt': str(_row_val(r, 3, 'visited_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'history': history, 'count': len(history)})


@internet_bp.route('/api/internet/history', methods=['DELETE'])
@require_auth
def delete_history():
    """GDPR — wipe all of the user's web history."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM web_history WHERE user_id = ?", (uid,))
        return jsonify({'success': True, 'cleared': True})
    except Exception as e:
        logger.error(f"delete_history: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# SEARCH PROXY (DuckDuckGo HTML, no tracking)
# ============================================================

@internet_bp.route('/api/internet/search', methods=['GET'])
@require_auth
def search_proxy():
    """Lightweight search results: parses DuckDuckGo HTML for senior reader.

    Returns title, snippet, host for top 10 hits. No JS, no tracking pixels.
    On any failure returns success=true with empty results — frontend
    falls back to opening DuckDuckGo directly in iframe.
    """
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    q = (request.args.get('q') or '').strip()
    if not q or len(q) > 200:
        return jsonify({'success': False, 'error': 'invalid query'}), 400

    results = []
    try:
        import urllib.request
        url = 'https://duckduckgo.com/html/?q=' + urllib.parse.quote(q + ' lang:cs')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; RadimCare/1.0; +https://radim.cz)'
        })
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read(200_000).decode('utf-8', errors='ignore')

        # Parse DDG HTML — looking for result blocks
        # Each result: <a class="result__a" href="..."> title </a>
        #              <a class="result__snippet"> snippet </a>
        link_re = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL
        )
        snippet_re = re.compile(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL
        )

        links = link_re.findall(html)[:10]
        snippets = snippet_re.findall(html)[:10]

        def _strip_html(s):
            return re.sub(r'<[^>]+>', '', s).replace('&nbsp;', ' ').strip()

        for i, (href, title) in enumerate(links):
            # DuckDuckGo redirects via /l/?uddg=...
            real = href
            m = re.search(r'uddg=([^&]+)', href)
            if m:
                try:
                    real = urllib.parse.unquote(m.group(1))
                except Exception:
                    pass
            snippet = _strip_html(snippets[i]) if i < len(snippets) else ''
            results.append({
                'title': _strip_html(title)[:160],
                'url': real,
                'host': _host_from(real),
                'snippet': snippet[:300],
            })
    except Exception as e:
        logger.warning(f"search_proxy: {e}")

    return jsonify({'success': True, 'query': q, 'results': results, 'count': len(results)})


# ============================================================
# TRANSLATE (delegates to Gemini if available)
# ============================================================

@internet_bp.route('/api/internet/translate', methods=['POST', 'OPTIONS'])
@require_auth
def translate_text():
    """Translate provided text into Czech. Body: {text, sourceLang?}.

    Tries Gemini if configured; otherwise returns a Google Translate URL
    the frontend can open in an iframe.
    """
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    source = (data.get('sourceLang') or 'auto')[:8]
    if not text:
        return jsonify({'success': False, 'error': 'text required'}), 400
    text = text[:6000]

    # Try Gemini path (re-uses existing AI helper if available)
    translated = None
    try:
        from claude_helpers import call_ai_with_fallback  # type: ignore
        prompt = (
            f"Přelož následující text do češtiny. Vrať POUZE překlad, "
            f"bez vysvětlení a bez původního textu.\n\nTEXT:\n{text}"
        )
        result = call_ai_with_fallback(prompt, max_tokens=2000, temperature=0.2)
        if result and isinstance(result, str) and len(result.strip()) > 5:
            translated = result.strip()
    except Exception as e:
        logger.debug(f"translate_text Gemini path skipped: {e}")

    if translated:
        return jsonify({
            'success': True,
            'translated': translated[:6000],
            'source': source,
            'engine': 'gemini',
        })

    # Fallback: return URL the frontend can navigate to
    fallback_url = (
        'https://translate.google.com/?sl=' + urllib.parse.quote(source)
        + '&tl=cs&op=translate&text=' + urllib.parse.quote(text[:1500])
    )
    return jsonify({
        'success': True,
        'translated': None,
        'fallbackUrl': fallback_url,
        'engine': 'fallback',
    })


# ============================================================
# FAMILY ACTIVITY
# ============================================================

@internet_bp.route('/api/internet/family/<senior_id>/activity', methods=['GET'])
@require_auth
def family_activity(senior_id):
    """Read-only weekly web activity for a linked family member.

    Returns:
      - count of visits in last 7 days
      - top 5 hosts (by visit count)
      - 5 most recent titles (no full URLs to protect privacy)
      - favorite count
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
                "SELECT host, title, visited_at FROM web_history "
                "WHERE user_id = ? AND visited_at >= ? "
                "ORDER BY visited_at DESC LIMIT 200",
                (senior_id, week_ago)
            ).fetchall() or []
            fav_rows = db.execute(
                "SELECT COUNT(*) FROM web_favorites WHERE user_id = ?",
                (senior_id,)
            ).fetchone()
    except Exception as e:
        logger.error(f"family_activity: {e}")
        hist_rows = []
        fav_rows = None

    host_counts = {}
    recent_titles = []
    for r in hist_rows:
        host = _row_val(r, 0, 'host') or 'unknown'
        title = _row_val(r, 1, 'title') or host
        host_counts[host] = host_counts.get(host, 0) + 1
        if len(recent_titles) < 5:
            recent_titles.append({
                'title': title[:120],
                'host': host,
                'visitedAt': str(_row_val(r, 2, 'visited_at') or ''),
            })

    top_hosts = sorted(host_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    fav_count = int(_row_val(fav_rows, 0, 'count') or 0) if fav_rows else 0

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'visitsLast7d': len(hist_rows),
        'topHosts': [{'host': h, 'count': c} for h, c in top_hosts],
        'recentTitles': recent_titles,
        'favoritesTotal': fav_count,
    })


logger.info("🌐 Internet routes v1.0 loaded — favorites + history + search + translate + family")
