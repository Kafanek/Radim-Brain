"""
🛡️ Browser Agent Safety — URL validation, domain allowlist, SSRF defense
=============================================================================
First line of defense for the read-only web agent. Every URL must pass
validate_url() before any HTTP request is made.

Principles:
    1. Default deny — only whitelisted domains allowed
    2. No local/private networks (SSRF defense)
    3. No file:// / javascript: / data: schemes
    4. Only ports 80/443
    5. Block known dangerous file extensions

Pattern borrowed from tv_proxy_routes.py:19-35 (_is_allowed + ALLOWED_DOMAINS).
"""

import ipaddress
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# DOMAIN ALLOWLIST (v1 — Czech senior-safe curated list)
# ═══════════════════════════════════════════════════════════════════

ALLOWED_DOMAINS = frozenset([
    # Zprávy
    'idnes.cz', 'ct24.ceskatelevize.cz', 'ceskatelevize.cz',
    'novinky.cz', 'seznam.cz', 'irozhlas.cz', 'lidovky.cz',
    'aktualne.cz', 'denik.cz',
    # Informace a encyklopedie
    'wikipedia.org', 'cs.wikipedia.org', 'en.wikipedia.org',
    # Mapy a doprava
    'mapy.cz', 'idos.cz', 'idos.idnes.cz', 'cd.cz', 'dpp.cz',
    # Počasí
    'pocasi.idnes.cz', 'meteocentrum.cz', 'in-pocasi.cz',
    'chmi.cz', 'pocasi.seznam.cz',
    # Senior-friendly
    'nasebabicka.cz', 'seniorskydum.cz', 'senior.cz',
    # Zdraví (oficiální)
    'nzip.cz', 'szu.cz', 'mzcr.cz',
    # Kultura / volný čas
    'kinopole.cz', 'csfd.cz',
])


# ═══════════════════════════════════════════════════════════════════
# DENY RULES
# ═══════════════════════════════════════════════════════════════════

BLOCKED_SCHEMES = frozenset(['file', 'javascript', 'data', 'ftp', 'gopher', 'ldap'])
ALLOWED_PORTS = frozenset([80, 443])

# File extensions that should never be fetched by the agent
DANGEROUS_EXTENSIONS = frozenset([
    '.exe', '.dmg', '.apk', '.msi', '.deb', '.rpm',
    '.zip', '.rar', '.7z', '.tar', '.gz',
    '.iso', '.img', '.bin',
    '.scr', '.bat', '.cmd', '.ps1',
    '.jar', '.app',
])

# Content-Type strings that should be rejected
DANGEROUS_CONTENT_TYPES = (
    'application/octet-stream',
    'application/x-msdownload',
    'application/x-executable',
    'application/x-apple-diskimage',
    'application/vnd.android.package-archive',
)


# ═══════════════════════════════════════════════════════════════════
# ERROR CODES
# ═══════════════════════════════════════════════════════════════════

class SafetyError(Exception):
    """Raised when a URL fails safety validation."""

    def __init__(self, code: str, message: str, url: str = ""):
        self.code = code
        self.message = message
        self.url = url
        super().__init__(f"[{code}] {message} (url={url})")


# ═══════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════

def _is_private_ip(host: str) -> bool:
    """Check if host resolves to a private / local / reserved IP."""
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private or
            ip.is_loopback or
            ip.is_link_local or
            ip.is_reserved or
            ip.is_multicast or
            ip.is_unspecified
        )
    except ValueError:
        # Not an IP — treat as hostname (we check those by name below)
        return False


def _is_dangerous_hostname(host: str) -> bool:
    """Block known SSRF-prone hostnames even when they aren't IPs."""
    if not host:
        return True
    h = host.lower()
    # Cloud metadata endpoints
    if h in ('metadata.google.internal', 'metadata.goog', 'metadata'):
        return True
    if h.endswith('.internal') or h.endswith('.localhost') or h == 'localhost':
        return True
    # Literal IPv6 loopback / link-local
    if h in ('::1', '[::1]'):
        return True
    return False


def _domain_matches_allowlist(host: str) -> bool:
    """Accept exact match OR subdomain of an allowlisted domain."""
    if not host:
        return False
    h = host.lower()
    for allowed in ALLOWED_DOMAINS:
        if h == allowed or h.endswith('.' + allowed):
            return True
    return False


def validate_url(url: str, allow_external: bool = False) -> dict:
    """Validate URL. Returns {ok, host, scheme, reason} or raises SafetyError.

    Args:
        url: user-provided URL string
        allow_external: if True, bypass allowlist (for admin/debug only).
                        NEVER set True from user input.
    """
    if not url or not isinstance(url, str):
        raise SafetyError('INVALID_URL', 'URL is empty or not a string', str(url))

    url = url.strip()
    if len(url) > 2048:
        raise SafetyError('INVALID_URL', 'URL too long (>2048 chars)', url[:80])

    # Control characters / embedded newlines (request smuggling defense)
    if any(c in url for c in ('\r', '\n', '\t', '\x00')):
        raise SafetyError('INVALID_URL', 'URL contains control characters', url[:80])

    try:
        parsed = urlparse(url)
    except Exception as e:
        raise SafetyError('INVALID_URL', f'Parse failed: {e}', url[:80])

    # Scheme must be http/https
    scheme = (parsed.scheme or '').lower()
    if scheme in BLOCKED_SCHEMES:
        raise SafetyError('BLOCKED_SCHEME', f'Scheme "{scheme}" not allowed', url)
    if scheme not in ('http', 'https'):
        raise SafetyError('INVALID_URL', f'Only http/https allowed (got "{scheme}")', url)

    # Host required
    host = (parsed.hostname or '').lower()
    if not host:
        raise SafetyError('INVALID_URL', 'Missing hostname', url)

    # SSRF check FIRST (before port) — private IPs are more dangerous than unusual ports
    if _is_private_ip(host):
        raise SafetyError('BLOCKED_DOMAIN', f'Private/local IP not allowed: {host}', url)
    if _is_dangerous_hostname(host):
        raise SafetyError('BLOCKED_DOMAIN', f'Local/internal hostname not allowed: {host}', url)

    # Port check (after SSRF so localhost:8080 → BLOCKED_DOMAIN, not BLOCKED_PORT)
    port = parsed.port
    if port is not None and port not in ALLOWED_PORTS:
        raise SafetyError('BLOCKED_PORT', f'Port {port} not allowed (only 80/443)', url)

    # Path: block dangerous file extensions
    path_lower = (parsed.path or '').lower()
    for ext in DANGEROUS_EXTENSIONS:
        if path_lower.endswith(ext):
            raise SafetyError('BLOCKED_CONTENT', f'File extension "{ext}" not allowed', url)

    # Allowlist check (unless admin explicitly bypasses)
    if not allow_external and not _domain_matches_allowlist(host):
        raise SafetyError(
            'BLOCKED_DOMAIN',
            f'Doména "{host}" není na seznamu povolených',
            url
        )

    return {
        'ok': True,
        'host': host,
        'scheme': scheme,
        'port': port or (443 if scheme == 'https' else 80),
        'path': parsed.path or '/',
        'allowlisted': _domain_matches_allowlist(host),
    }


def is_safe_url(url: str) -> bool:
    """Non-raising version for quick boolean checks (e.g., link list marking)."""
    try:
        validate_url(url)
        return True
    except SafetyError:
        return False


def is_safe_content_type(content_type: str) -> bool:
    """Reject binary/executable content types."""
    if not content_type:
        return True  # Missing header is OK (many sites omit it)
    ct = content_type.lower().split(';')[0].strip()
    if ct in DANGEROUS_CONTENT_TYPES:
        return False
    # Only allow text/* and application/json, application/xml, application/xhtml+xml
    if ct.startswith('text/'):
        return True
    if ct in ('application/json', 'application/xml', 'application/xhtml+xml',
              'application/rss+xml', 'application/atom+xml', 'application/ld+json'):
        return True
    return False


def add_allowed_domain(domain: str):
    """Admin helper — extend the allowlist at runtime (in-memory only)."""
    global ALLOWED_DOMAINS
    if domain and re.match(r'^[a-z0-9][a-z0-9\-\.]*[a-z0-9]$', domain.lower()):
        ALLOWED_DOMAINS = ALLOWED_DOMAINS | frozenset([domain.lower()])
        logger.info(f"🛡️ Browser safety: added domain '{domain}' to allowlist")
        return True
    return False


logger.info(f"🛡️ Browser Agent Safety loaded — {len(ALLOWED_DOMAINS)} domains on allowlist")
