"""
🌐 Browser Agent HTTP Routes
=============================================================================
Flask blueprint exposing the browser agent as /api/browser/*.

Endpoints:
    POST   /api/browser/open             Open URL → new session
    GET    /api/browser/read/<sid>       Re-read cached page
    POST   /api/browser/find/<sid>       Search within page
    GET    /api/browser/links/<sid>      List links
    POST   /api/browser/click/<sid>      Follow link by index
    GET    /api/browser/snapshot/<sid>   Debug state
    POST   /api/browser/close/<sid>      Drop session
    GET    /api/browser/stats            Admin stats (feature flag, session count)

All endpoints honor ENABLE_BROWSER_AGENT flag in browser_agent module.
Rate-limited per-IP to prevent abuse.
"""

import logging

from flask import Blueprint, request, jsonify
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

browser_agent_bp = Blueprint('browser_agent', __name__)


# ═══════════════════════════════════════════════════════════════════
# CORS preflight helper — OPTIONS returns public snapshot of stats
# ═══════════════════════════════════════════════════════════════════

def _options_ok():
    return jsonify({'ok': True}), 200


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@browser_agent_bp.route('/api/browser/open', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=10, window_seconds=60, key_func='ip')
def route_open():
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import open_page
    except ImportError as e:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE',
                        'error': f'Browser agent not installed: {e}'}), 503

    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    user_id = data.get('user_id')
    if not url:
        return jsonify({'success': False, 'error_code': 'INVALID_URL',
                        'error': 'Parametr "url" je povinný'}), 400

    result = open_page(url, user_id=user_id)
    status = 200 if result.get('success') else 400
    # Map certain error codes to appropriate status
    code = result.get('error_code', '')
    if code == 'DISABLED':
        status = 503
    elif code in ('BLOCKED_DOMAIN', 'BLOCKED_SCHEME', 'BLOCKED_PORT', 'BLOCKED_CONTENT'):
        status = 403
    elif code == 'TIMEOUT':
        status = 504
    elif code == 'SESSION_NOT_FOUND':
        status = 404
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/read/<session_id>', methods=['GET', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def route_read(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import read_page
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    result = read_page(session_id)
    status = 200 if result.get('success') else (404 if result.get('error_code') == 'SESSION_NOT_FOUND' else 400)
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/find/<session_id>', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def route_find(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import find_on_page
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    data = request.get_json(silent=True) or {}
    query = (data.get('query') or '').strip()
    if not query:
        return jsonify({'success': False, 'error_code': 'INVALID_QUERY',
                        'error': 'Parametr "query" je povinný'}), 400
    result = find_on_page(session_id, query)
    status = 200 if result.get('success') else 404
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/links/<session_id>', methods=['GET', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def route_links(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import list_links
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    safe_only = request.args.get('safe_only', 'false').lower() == 'true'
    result = list_links(session_id, safe_only=safe_only)
    status = 200 if result.get('success') else 404
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/click/<session_id>', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=20, window_seconds=60, key_func='ip')
def route_click(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import click_link
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    data = request.get_json(silent=True) or {}
    index = data.get('index')
    if index is None:
        return jsonify({'success': False, 'error_code': 'INVALID_INDEX',
                        'error': 'Parametr "index" je povinný'}), 400
    result = click_link(session_id, index)
    status = 200 if result.get('success') else 400
    code = result.get('error_code', '')
    if code == 'SESSION_NOT_FOUND':
        status = 404
    elif code in ('BLOCKED_DOMAIN', 'BLOCKED_SCHEME'):
        status = 403
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/snapshot/<session_id>', methods=['GET', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def route_snapshot(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import get_snapshot
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    result = get_snapshot(session_id)
    status = 200 if result.get('success') else 404
    return jsonify(result), status


@browser_agent_bp.route('/api/browser/close/<session_id>', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def route_close(session_id):
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import close_session
    except ImportError:
        return jsonify({'success': False, 'error_code': 'NOT_AVAILABLE'}), 503
    result = close_session(session_id)
    return jsonify(result), 200


@browser_agent_bp.route('/api/browser/stats', methods=['GET', 'OPTIONS'])
def route_stats():
    """Public (no auth) — only returns feature flag state + session count."""
    if request.method == 'OPTIONS':
        return _options_ok()
    try:
        from browser_agent import stats
    except ImportError:
        return jsonify({'success': False, 'enabled': False,
                        'error_code': 'NOT_AVAILABLE'}), 200
    return jsonify(stats()), 200


logger.info("🌐 Browser Agent routes registered: /api/browser/*")
