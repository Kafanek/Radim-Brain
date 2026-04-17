"""
🌐 Browser Agent Fetcher — Safe HTTP layer
=============================================================================
Fetches URLs that have already passed browser_agent_safety.validate_url().

- requests.Session with retry + timeout
- User-Agent identifies RADIM honestly
- Max response size (defends against gzip bombs)
- Redirect chain tracked and each hop re-validated against allowlist
- Content-Type filtered against is_safe_content_type()

No browser automation (no JS execution) — 95% of senior-safe content
is static HTML. Stays well under 500 MB Heroku slug limit.
"""

import logging
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

from browser_agent_safety import (
    SafetyError,
    is_safe_content_type,
    validate_url,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

USER_AGENT = (
    "RadimCare/1.0 (+https://app.radimcare.cz/browser-agent) "
    "Safe-readonly web agent for seniors"
)

DEFAULT_TIMEOUT = (5, 15)  # (connect, read) seconds
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB — senior-reading use case
MAX_REDIRECTS = 5


# ═══════════════════════════════════════════════════════════════════
# SESSION (shared, with retry on transient errors)
# ═══════════════════════════════════════════════════════════════════

def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset(['GET', 'HEAD']),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
    s.mount('http://', adapter)
    s.mount('https://', adapter)
    s.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'cs,en-US;q=0.8,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
    })
    return s


_session = _build_session()


# ═══════════════════════════════════════════════════════════════════
# FETCH
# ═══════════════════════════════════════════════════════════════════

class FetchError(Exception):
    def __init__(self, code: str, message: str, url: str = ""):
        self.code = code
        self.message = message
        self.url = url
        super().__init__(f"[{code}] {message} (url={url})")


def fetch(url: str, allow_external: bool = False) -> dict:
    """Fetch URL safely. Returns structured result dict.

    Raises:
        SafetyError — URL/redirect failed validation
        FetchError — HTTP/network problem
    """
    # 1. Pre-validate (raises SafetyError)
    validate_url(url, allow_external=allow_external)

    # 2. Fetch with manual redirect handling (so we can validate each hop)
    redirect_chain = []
    current_url = url
    start = time.time()

    for hop in range(MAX_REDIRECTS + 1):
        try:
            resp = _session.get(
                current_url,
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=False,
                stream=True,  # so we can cap body size
            )
        except requests.exceptions.ConnectTimeout:
            raise FetchError('TIMEOUT', 'Spojení vypršelo (connect timeout)', current_url)
        except requests.exceptions.ReadTimeout:
            raise FetchError('TIMEOUT', 'Spojení vypršelo (read timeout)', current_url)
        except requests.exceptions.SSLError as e:
            raise FetchError('SSL_ERROR', f'SSL/TLS chyba: {e}', current_url)
        except requests.exceptions.ConnectionError as e:
            raise FetchError('CONNECTION_ERROR', f'Nelze se připojit: {e}', current_url)
        except requests.exceptions.RequestException as e:
            raise FetchError('HTTP_ERROR', f'HTTP chyba: {e}', current_url)

        redirect_chain.append(current_url)

        # Follow redirect?
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get('Location', '').strip()
            resp.close()
            if not location:
                raise FetchError('HTTP_ERROR', 'Redirect bez Location hlavičky', current_url)
            # Resolve relative redirect
            from urllib.parse import urljoin
            next_url = urljoin(current_url, location)
            if hop >= MAX_REDIRECTS:
                raise FetchError('TOO_MANY_REDIRECTS',
                                 f'Překročen limit {MAX_REDIRECTS} přesměrování',
                                 next_url)
            # Re-validate next hop
            try:
                validate_url(next_url, allow_external=allow_external)
            except SafetyError as e:
                raise SafetyError(e.code, f'Přesměrování blokováno: {e.message}', next_url)
            current_url = next_url
            continue

        # Final response
        break

    # 3. HTTP status check
    if resp.status_code >= 400:
        resp.close()
        raise FetchError(
            'HTTP_ERROR',
            f'Server vrátil chybu {resp.status_code}',
            current_url,
        )

    # 4. Content-Type filter
    content_type = resp.headers.get('Content-Type', '')
    if not is_safe_content_type(content_type):
        resp.close()
        raise FetchError(
            'BLOCKED_CONTENT',
            f'Nepodporovaný typ obsahu: {content_type[:60]}',
            current_url,
        )

    # 5. Read body with size cap
    try:
        content = b''
        for chunk in resp.iter_content(chunk_size=65536, decode_unicode=False):
            if chunk:
                content += chunk
                if len(content) > MAX_RESPONSE_BYTES:
                    resp.close()
                    raise FetchError(
                        'TOO_LARGE',
                        f'Odpověď větší než {MAX_RESPONSE_BYTES // (1024*1024)} MB',
                        current_url,
                    )
    finally:
        resp.close()

    # 6. Decode text
    encoding = resp.encoding or 'utf-8'
    try:
        text = content.decode(encoding, errors='replace')
    except (LookupError, UnicodeDecodeError):
        text = content.decode('utf-8', errors='replace')

    latency_ms = int((time.time() - start) * 1000)

    host = urlparse(current_url).hostname or ''
    logger.info(
        f"🌐 Fetch OK: {host} {resp.status_code} "
        f"({len(content)} B, {latency_ms}ms, hops={len(redirect_chain)})"
    )

    return {
        'url': url,
        'final_url': current_url,
        'status_code': resp.status_code,
        'content_type': content_type,
        'content': text,
        'content_length': len(content),
        'encoding': encoding,
        'redirect_chain': redirect_chain,
        'latency_ms': latency_ms,
        'headers': {
            # Safe subset only
            'content-type': content_type,
            'content-length': resp.headers.get('Content-Length', ''),
            'last-modified': resp.headers.get('Last-Modified', ''),
            'etag': resp.headers.get('ETag', ''),
        },
    }


logger.info("🌐 Browser Agent Fetcher loaded (requests.Session, max 5MB, 5 redirects)")
