"""
📖 Browser Agent Extractor — HTML → structured content
=============================================================================
Turns raw HTML into clean structured data usable by:
    - TTS (main_content for "read aloud")
    - Chat context (text_excerpt for AI)
    - Link navigation (safe links)
    - Metadata (title, description, language)

Strategy:
    1. trafilatura — state-of-the-art article text extraction (primary)
    2. BeautifulSoup + heuristics — fallback when trafilatura returns nothing
    3. Always extract links + metadata with BS4 regardless of primary path

Senior-friendly post-processing:
    - Strip emoji/unicode garbage
    - Normalize whitespace
    - Cap main_content length so TTS doesn't drone for 20 minutes
"""

import logging
import re
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Optional deps — graceful fallback if missing
try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False
    logger.warning("⚠️ trafilatura not installed — using BS4-only extraction")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.error("❌ beautifulsoup4 not installed — extractor will fail")


MAX_MAIN_CONTENT_CHARS = 30_000   # ~10 min TTS at senior speed
MAX_EXCERPT_CHARS = 500
MAX_LINKS = 50
MAX_LINK_TEXT = 120


# ═══════════════════════════════════════════════════════════════════
# ERRORS
# ═══════════════════════════════════════════════════════════════════

class ExtractError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _clean_text(s: str) -> str:
    """Normalize whitespace, strip control chars."""
    if not s:
        return ''
    # Remove zero-width & control chars
    s = re.sub(r'[\u200b\u200c\u200d\ufeff\x00-\x08\x0b\x0c\x0e-\x1f]', '', s)
    # Collapse whitespace (but preserve paragraph breaks)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _extract_meta_bs4(soup) -> dict:
    """Pull title, description, language, OG tags."""
    meta = {
        'title': '',
        'description': '',
        'language': '',
        'site_name': '',
    }

    # Title
    if soup.title and soup.title.string:
        meta['title'] = _clean_text(soup.title.string)[:300]

    # OpenGraph / meta description
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content') and not meta['title']:
        meta['title'] = _clean_text(og_title['content'])[:300]

    desc = (soup.find('meta', {'name': 'description'}) or
            soup.find('meta', property='og:description'))
    if desc and desc.get('content'):
        meta['description'] = _clean_text(desc['content'])[:500]

    og_site = soup.find('meta', property='og:site_name')
    if og_site and og_site.get('content'):
        meta['site_name'] = _clean_text(og_site['content'])[:100]

    # Language
    html_tag = soup.find('html')
    if html_tag and html_tag.get('lang'):
        meta['language'] = html_tag['lang'][:10]

    return meta


def _extract_links_bs4(soup, base_url: str) -> list:
    """All <a href> links, resolved to absolute, deduped, safety-tagged."""
    # Lazy import to avoid circular (safety doesn't import this module)
    try:
        from browser_agent_safety import is_safe_url
    except ImportError:
        is_safe_url = lambda u: False

    links = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href_raw = a['href'].strip()
        if not href_raw or href_raw.startswith('#'):
            continue
        if href_raw.lower().startswith(('javascript:', 'data:', 'mailto:', 'tel:')):
            continue

        href = urljoin(base_url, href_raw)
        if href in seen:
            continue
        seen.add(href)

        text = _clean_text(a.get_text(' ', strip=True)) or _clean_text(a.get('title', ''))
        if not text:
            continue
        if len(text) > MAX_LINK_TEXT:
            text = text[:MAX_LINK_TEXT] + '…'

        host = urlparse(href).hostname or ''
        links.append({
            'text': text,
            'href': href,
            'domain': host,
            'is_safe': is_safe_url(href),
        })

        if len(links) >= MAX_LINKS:
            break

    return links


def _extract_main_content_bs4(soup) -> str:
    """Fallback main content — look for <article>, <main>, or heuristic."""
    # Strip noise first
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside',
                     'form', 'button', 'iframe', 'noscript']):
        tag.decompose()

    # Prefer semantic tags
    for selector in ('article', 'main', '[role="main"]', '.article-content',
                     '.article-body', '.post-content', '#main-content', '#content'):
        el = soup.select_one(selector)
        if el:
            text = el.get_text('\n', strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # Last resort: biggest text block
    body = soup.body or soup
    return _clean_text(body.get_text('\n', strip=True))


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def extract(html: str, base_url: str) -> dict:
    """Extract structured content from HTML.

    Returns:
        {
          title, description, language, site_name,
          main_content, text_excerpt, content_length,
          links: [{text, href, domain, is_safe}],
          extractor_used: "trafilatura" | "bs4",
          extractor_fallback: None | "bs4"
        }

    Raises:
        ExtractError — when HTML is unusable (empty, not HTML, BS4 missing).
    """
    if not html or not isinstance(html, str):
        raise ExtractError('EXTRACT_FAILED', 'HTML is empty')
    if not HAS_BS4:
        raise ExtractError('EXTRACT_FAILED', 'beautifulsoup4 not installed')

    # Parse once with lxml (faster) or html.parser (fallback)
    try:
        soup = BeautifulSoup(html, 'lxml')
    except Exception:
        soup = BeautifulSoup(html, 'html.parser')

    meta = _extract_meta_bs4(soup)
    links = _extract_links_bs4(soup, base_url)

    main_content = ''
    extractor_used = None
    extractor_fallback = None

    # Primary: trafilatura
    if HAS_TRAFILATURA:
        try:
            main_content = trafilatura.extract(
                html,
                url=base_url,
                favor_precision=True,
                include_comments=False,
                include_tables=False,
                include_images=False,
                no_fallback=False,
                output_format='txt',
            ) or ''
            main_content = _clean_text(main_content)
            if main_content and len(main_content) >= 100:
                extractor_used = 'trafilatura'
            else:
                main_content = ''
        except Exception as e:
            logger.debug(f"trafilatura extraction failed: {e}")

    # Fallback: BS4 heuristic
    if not main_content:
        main_content = _extract_main_content_bs4(soup)
        extractor_used = 'bs4'
        if HAS_TRAFILATURA:
            extractor_fallback = 'bs4'

    # Cap length
    original_length = len(main_content)
    if len(main_content) > MAX_MAIN_CONTENT_CHARS:
        main_content = main_content[:MAX_MAIN_CONTENT_CHARS] + '\n\n[…článek zkrácen pro čtení…]'

    # Excerpt = first sentence-ish chunk
    excerpt = main_content[:MAX_EXCERPT_CHARS]
    if len(main_content) > MAX_EXCERPT_CHARS:
        # cut at sentence boundary if possible
        cut_at = max(excerpt.rfind('. '), excerpt.rfind('? '), excerpt.rfind('! '))
        if cut_at > 200:
            excerpt = excerpt[:cut_at + 1]
        excerpt += ' …'

    result = {
        'title': meta['title'] or 'Bez titulu',
        'description': meta['description'],
        'language': meta['language'] or 'cs',
        'site_name': meta['site_name'],
        'main_content': main_content,
        'text_excerpt': excerpt,
        'content_length': original_length,
        'links': links,
        'extractor_used': extractor_used,
        'extractor_fallback': extractor_fallback,
    }

    logger.info(
        f"📖 Extract OK: title='{meta['title'][:40]}' "
        f"content={original_length}B links={len(links)} via {extractor_used}"
    )
    return result


def find_in_content(main_content: str, query: str, context_chars: int = 120) -> list:
    """Find query in main_content, return snippets with surrounding context.

    Case-insensitive, unicode-aware. Non-regex (query treated as literal).
    """
    if not main_content or not query:
        return []
    q = query.strip()
    if len(q) < 2:
        return []

    text = main_content
    text_lower = text.lower()
    q_lower = q.lower()

    matches = []
    start = 0
    while True:
        idx = text_lower.find(q_lower, start)
        if idx < 0:
            break
        left = max(0, idx - context_chars)
        right = min(len(text), idx + len(q) + context_chars)
        snippet = text[left:right].strip()
        # Pad with ellipsis if truncated
        if left > 0:
            snippet = '…' + snippet
        if right < len(text):
            snippet = snippet + '…'
        matches.append({
            'position': idx,
            'snippet': snippet,
            'match': text[idx:idx + len(q)],
        })
        start = idx + len(q)
        if len(matches) >= 20:
            break
    return matches


logger.info(
    f"📖 Browser Agent Extractor loaded "
    f"(trafilatura={HAS_TRAFILATURA}, bs4={HAS_BS4})"
)
