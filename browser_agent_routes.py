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


@browser_agent_bp.route('/api/browser/proxy', methods=['GET', 'OPTIONS'])
@rate_limit(max_requests=60, window_seconds=60, key_func='ip')
def route_proxy():
    """Proxy a whitelisted URL so the senior UI can iframe it.

    Fetches the URL server-side, strips X-Frame-Options / frame-ancestors
    so the response can be embedded. Injects <base href="..."> so relative
    assets (images, CSS) resolve against the original host. Senior's iframe
    sees the real page rendered from our domain.
    """
    if request.method == 'OPTIONS':
        return _options_ok()

    from flask import Response
    try:
        from browser_agent_safety import SafetyError, validate_url
        from browser_agent_fetcher import FetchError, fetch
    except ImportError as e:
        return _proxy_error(f'Proxy není dostupný: {e}', 503)

    url = (request.args.get('url') or '').strip()
    if not url:
        return _proxy_error('Chybí parametr "url".', 400)

    # Senior may browse any public website — no domain whitelist. We still
    # enforce real safety: scheme (http/https only), SSRF defense (no local/
    # private IPs), ports 80/443, and block dangerous file extensions.
    try:
        validate_url(url, allow_external=True)
    except SafetyError as e:
        return _proxy_error(f'Neplatná adresa: {e.message}', 400)

    try:
        result = fetch(url, allow_external=True)
    except SafetyError as e:
        return _proxy_error(f'Spojení přerušeno: {e.message}', 502)
    except FetchError as e:
        return _proxy_error(f'Stránku se nepodařilo načíst: {e.message}', 502)

    html = result.get('content', '') or ''
    final_url = result.get('final_url', url)

    # Minimal rewrites so relative URLs work + no embed-blocking meta tags.
    html = _rewrite_html_for_iframe(html, final_url)

    resp = Response(html, mimetype='text/html; charset=utf-8')
    # Strip response-level block flags (the fetcher didn't return them but
    # Flask/WSGI defaults are clean). Explicit policies:
    resp.headers['Content-Security-Policy'] = "frame-ancestors *"
    resp.headers['X-Frame-Options'] = 'ALLOWALL'
    resp.headers['Cache-Control'] = 'public, max-age=60'
    # Permissive Referrer-Policy so asset loads from the target work
    resp.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return resp


def _proxy_error(message: str, status: int):
    """Return a small human-readable HTML error the iframe can display.

    NOTE: we intentionally return HTTP 200 here — some browsers render their
    own "content blocked" page for iframe responses with 4xx/5xx status,
    hiding the friendly message. 200 with the explanation in the body is
    what the senior actually sees.
    """
    from flask import Response
    msg = (message or 'Chyba při načítání stránky.').replace('<', '&lt;')
    body = (
        '<!doctype html><html lang="cs"><meta charset="utf-8">'
        '<title>Nepodařilo se načíst</title>'
        '<body style="font-family:system-ui,-apple-system,sans-serif;padding:40px;'
        'margin:0;color:#2d3748;background:#f8fafa;text-align:center">'
        '<div style="max-width:560px;margin:60px auto;padding:32px;'
        'background:#fff;border:1.5px solid #e2e8f0;border-radius:18px;'
        'box-shadow:0 4px 16px rgba(0,0,0,0.04)">'
        '<div style="font-size:3rem;margin-bottom:12px">⚠️</div>'
        '<h2 style="margin:0 0 10px;color:#2d3748;font-weight:700">Stránku se nepodařilo otevřít</h2>'
        f'<p style="color:#4a5568;line-height:1.5;margin:0">{msg}</p>'
        '<p style="color:#a0aec0;line-height:1.5;margin:18px 0 0;font-size:0.9rem">'
        'Zkuste jinou adresu nebo klikněte 🏠 domů.</p>'
        '</div></body></html>'
    )
    r = Response(body, mimetype='text/html; charset=utf-8')
    r.status_code = 200  # intentional — see docstring
    r.headers['Content-Security-Policy'] = "frame-ancestors *"
    r.headers['X-Frame-Options'] = 'ALLOWALL'
    r.headers['X-Radim-Proxy-Reason'] = f'error:{status}'
    return r


_PROXY_PREFIX = '/api/browser/proxy?url='

# Injected into every proxied page. Wraps fetch() and XMLHttpRequest so
# that root-relative URLs resolve to the original host through our proxy
# (instead of hitting our backend origin and 404-ing). Also traps
# window.location navigations so single-page apps that SPA-route through
# history.pushState still keep working — falling back to top.location for
# full-reload cases.
_PROXY_SHIM_JS = r"""
(function(){
  try {
    var BASE = "__BASE__";
    var PREFIX = "/api/browser/proxy?url=";
    function absolutize(u) {
      try { return new URL(u, BASE).href; } catch(e) { return null; }
    }
    function proxify(u) {
      if (!u) return u;
      if (typeof u !== "string") return u;
      var lower = u.toLowerCase();
      if (lower.indexOf(PREFIX) !== -1) return u;
      if (lower.indexOf("data:") === 0 || lower.indexOf("blob:") === 0 ||
          lower.indexOf("javascript:") === 0 || lower.indexOf("mailto:") === 0 ||
          lower.indexOf("tel:") === 0 || lower.indexOf("#") === 0) return u;
      var abs = absolutize(u);
      if (!abs) return u;
      if (abs.indexOf("http://") !== 0 && abs.indexOf("https://") !== 0) return u;
      return PREFIX + encodeURIComponent(abs);
    }
    // fetch() shim
    if (window.fetch) {
      var origFetch = window.fetch.bind(window);
      window.fetch = function(input, init) {
        try {
          if (typeof input === "string") {
            input = proxify(input);
          } else if (input && typeof input.url === "string") {
            input = new Request(proxify(input.url), input);
          }
        } catch(e){}
        return origFetch(input, init);
      };
    }
    // XMLHttpRequest shim
    if (window.XMLHttpRequest) {
      var origOpen = XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.open = function(method, url) {
        try { url = proxify(url); } catch(e){}
        var rest = Array.prototype.slice.call(arguments, 2);
        return origOpen.apply(this, [method, url].concat(rest));
      };
    }
    // Form.submit() / action rewrites handled by HTML rewriter.
  } catch(e) {
    console.debug("[RadimProxyShim] init failed:", e && e.message);
  }
})();
"""


def _rewrite_html_for_iframe(html: str, base_url: str) -> str:
    """Prepare HTML so it renders cleanly inside an iframe:
      1. Inject <base href> so CSS/img/script relative URLs resolve against
         the original host (public CDN assets just work).
      2. Strip meta tags that block framing (XFO, frame-ancestors).
      3. Rewrite only <a href> anchor targets to continue through the proxy
         so in-frame clicks don't get blocked by the next site's XFO.

    Uses BeautifulSoup so we only touch real anchor tags — we do NOT rewrite
    <base>, <link rel="stylesheet">, <link rel="icon">, <area>, etc.
    """
    from urllib.parse import urljoin, quote as _quote

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # If bs4 isn't available, do a minimal safe transform (no anchor rewrite).
        return _rewrite_html_minimal(html, base_url)

    try:
        soup = BeautifulSoup(html, 'lxml')
    except Exception:
        soup = BeautifulSoup(html, 'html.parser')

    # 1. Ensure <base href> + inject a tiny shim so JS-initiated requests
    #    (fetch, XMLHttpRequest) using root-relative paths land on the
    #    original host through our proxy, not on our backend origin.
    head = soup.find('head')
    if head is not None:
        if not soup.find('base'):
            base_tag = soup.new_tag('base', href=base_url)
            head.insert(0, base_tag)
        shim = soup.new_tag('script')
        shim.string = _PROXY_SHIM_JS.replace('__BASE__', base_url)
        # Insert shim right after <base> (or at head start) so it runs
        # before page scripts.
        head.insert(1 if soup.find('base') else 0, shim)

    # 2. Strip meta tags that would re-impose framing restrictions
    for meta in list(soup.find_all('meta')):
        eq = (meta.get('http-equiv') or '').lower()
        if eq in ('x-frame-options', 'content-security-policy'):
            meta.decompose()

    # 3. Rewrite anchor hrefs through the proxy
    for a in soup.find_all('a'):
        href = a.get('href')
        if not href:
            continue
        raw = href.strip()
        if not raw:
            continue
        lower = raw.lower()
        if lower.startswith(('#', 'javascript:', 'mailto:', 'tel:', 'sms:', 'data:')):
            continue
        try:
            absolute = urljoin(base_url, raw)
        except Exception:
            continue
        if not absolute.lower().startswith(('http://', 'https://')):
            continue
        a['href'] = _PROXY_PREFIX + _quote(absolute, safe='')
        # Also drop target="_blank" so links stay in the iframe rather than
        # opening a new window (senior UX).
        if a.get('target'):
            a['target'] = '_self'

    # 4. Force <form> submissions to a new tab (can't proxy POST safely).
    for form in soup.find_all('form'):
        form['target'] = '_blank'

    return str(soup)


def _rewrite_html_minimal(html: str, base_url: str) -> str:
    """Fallback when bs4 isn't available — just inject <base> and strip XFO meta."""
    import re as _re
    html = _re.sub(
        r'<meta[^>]+http-equiv=["\']?(?:X-Frame-Options|Content-Security-Policy)[^>]*>',
        '', html, flags=_re.IGNORECASE,
    )
    if not _re.search(r'<base[\s>]', html, _re.IGNORECASE):
        base_tag = f'<base href="{base_url}">'
        if _re.search(r'<head[^>]*>', html, _re.IGNORECASE):
            html = _re.sub(r'(<head[^>]*>)', r'\1' + base_tag, html, count=1, flags=_re.IGNORECASE)
        else:
            html = base_tag + html
    return html


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
