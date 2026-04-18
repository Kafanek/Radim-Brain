"""
🛡️ Safe Web Agent — Configuration + Privacy Patterns
=============================================================================
All retention TTLs, sensitive detection patterns, role permissions, and
senior-friendly Czech messages live here. One place to audit, one place to
update. No magic numbers elsewhere.

Everything here is privacy-preserving: we block-by-default, explain in plain
Czech, and never persist raw HTML.
"""

import re

# ═══════════════════════════════════════════════════════════════════
# SESSION LIMITS
# ═══════════════════════════════════════════════════════════════════

SAFE_SESSION_TTL_SEC = 900          # 15 minutes — stricter than v10.34 (30 min)
SAFE_MAX_SESSIONS = 200             # per-process cap (LRU eviction)
SAFE_MAX_ACTIONS_PER_SESSION = 20   # hard ceiling for user actions (read/find/follow)
SAFE_MAX_NAVIGATION_DEPTH = 5       # how deep can user follow links

# Per-page timeouts — match v10.34 fetcher
SAFE_FETCH_TIMEOUT_SEC = (5, 15)    # (connect, read)


# ═══════════════════════════════════════════════════════════════════
# RETENTION POLICY
# ═══════════════════════════════════════════════════════════════════

RETENTION_POLICY = {
    "session_state_min":      15,   # minutes (in-memory only)
    "raw_html_days":           0,   # NEVER persisted
    "extracted_content_min":  15,   # lives only in session state
    "audit_days":             30,   # via agent_observations (existing)
    "client_history_days":     7,   # localStorage on client
    "blocked_attempts_days":  30,   # via agent_observations
}


# ═══════════════════════════════════════════════════════════════════
# SAFETY MODES
# ═══════════════════════════════════════════════════════════════════

MODE_READ_ONLY = "read_only"
MODE_ASSISTED_NAVIGATION = "assisted_navigation"

ALLOWED_MODES = {
    MODE_READ_ONLY: {
        "can_open_page": True,
        "can_read_content": True,
        "can_list_links": True,
        "can_find_on_page": True,
        "can_follow_safe_link": True,
        "can_submit_form": False,
        "can_login": False,
        "can_download": False,
        "description": "Pouze čtení. Neodesílám žádné formuláře, nikam se nepřihlašuji.",
    },
    MODE_ASSISTED_NAVIGATION: {
        "can_open_page": True,
        "can_read_content": True,
        "can_list_links": True,
        "can_find_on_page": True,
        "can_follow_safe_link": True,
        "can_submit_form": False,          # still no forms in v1
        "can_login": False,
        "can_download": False,
        "description": "Pouze čtení s průvodcem. Vysvětluji co na stránce vidím, ale stále neodesílám formuláře.",
    },
}


# ═══════════════════════════════════════════════════════════════════
# ROLE PERMISSIONS
# ═══════════════════════════════════════════════════════════════════

ROLE_PERMISSIONS = {
    "senior_user": {
        "can_open_pages": True,
        "max_sessions_per_day": 50,
        "sees_full_content": True,
        "sees_raw_html": False,
        "sees_other_users_audit": False,
        "requires_gdpr_consent": True,
    },
    "caregiver": {
        "can_open_pages": True,
        "max_sessions_per_day": 30,
        "sees_assigned_seniors_summary": True,
        "sees_full_content": True,
        "sees_raw_html": False,
        "sees_other_users_audit": False,
        "requires_gdpr_consent": False,
    },
    "admin": {
        "can_open_pages": True,
        "max_sessions_per_day": 200,
        "sees_all_audit": True,
        "sees_technical_errors": True,
        "sees_full_content": True,
        "sees_raw_html": False,             # admin nevidí raw buď
        "sees_other_users_audit": True,
        "requires_gdpr_consent": False,
    },
    # Default fallback for unauthenticated / unknown roles
    "anonymous": {
        "can_open_pages": False,
        "requires_gdpr_consent": True,
    },
}


def get_role_permissions(role: str) -> dict:
    """Return permissions dict for given role. Unknown role → anonymous (deny)."""
    return ROLE_PERMISSIONS.get((role or "").lower(), ROLE_PERMISSIONS["anonymous"])


# ═══════════════════════════════════════════════════════════════════
# SENSITIVE CONTENT DETECTION PATTERNS
# ═══════════════════════════════════════════════════════════════════
# All patterns case-insensitive. Applied to raw HTML (in-memory only).
# If ANY pattern matches → set respective flag → block action,
# return SENSITIVE_PAGE with clear czech explanation.

# ── LOGIN ─────────────────────────────────────────────────────────
LOGIN_HTML_PATTERNS = [
    re.compile(r'<input[^>]*type=["\']?password["\']?', re.I),
    re.compile(r'<form[^>]*action=["\'][^"\']*(?:login|prihlas|signin|log-in)', re.I),
    re.compile(r'<input[^>]*name=["\'](?:password|heslo|pwd|passwd|user|email|login)', re.I),
]
LOGIN_URL_KEYWORDS = ("/login", "/prihlaseni", "/auth", "/signin", "/sso", "/oauth")
LOGIN_TITLE_KEYWORDS = ("přihlášení", "přihlásit", "login", "sign in", "sign-in")


# ── PAYMENT ───────────────────────────────────────────────────────
PAYMENT_HTML_PATTERNS = [
    re.compile(r'<input[^>]*name=["\'][^"\']*(?:card|ccn|cvv|cvc|cardnumber)', re.I),
    re.compile(r'<input[^>]*autocomplete=["\']cc-', re.I),
    re.compile(r'<input[^>]*name=["\'][^"\']*(?:iban|swift|bic)', re.I),
    re.compile(r'stripe|braintree|paypal|gopay|3d[- ]?secure', re.I),
]
PAYMENT_URL_KEYWORDS = ("/platba", "/payment", "/checkout", "/pay", "/cart/checkout", "/objednavka/platba")
PAYMENT_KEYWORDS = ("platba kartou", "zaplatit kartou", "cvv", "číslo karty", "kartou online", "bankovní převod")


# ── BANKING ───────────────────────────────────────────────────────
BANKING_DOMAINS = frozenset([
    "ceskasporitelna.cz", "csob.cz", "kb.cz", "komercnibanka.cz",
    "rb.cz", "air-bank.cz", "airbank.cz", "fio.cz",
    "unicredit.cz", "mbank.cz", "mbank.com",
    "moneta.cz", "raiffeisenbank.cz", "equa.cz",
    "creditas.cz", "jnfb.cz", "trinitybank.cz",
])
BANKING_KEYWORDS = (
    "internetbanking", "online banking", "internetové bankovnictví",
    "přihlášení do banky", "zůstatek účtu",
)


# ── HEALTHCARE (with patient personal data) ──────────────────────
HEALTHCARE_DOMAINS = frozenset([
    "izip.cz", "mojezdravi.cz", "klient.vzp.cz",
    "ezkarta.cz", "edravotnipojisteni.cz",
    "pacientskyportal.cz",
])
HEALTHCARE_URL_KEYWORDS = ("/patient/", "/pacient/", "/zdravotni-zaznam", "/recept", "/erecept", "/zdravotnikarta")
HEALTHCARE_KEYWORDS = (
    "lékařský záznam", "zdravotní pojišťovna", "recept",
    "diagnóza", "anamnéza", "laboratorní výsledek",
)


# ── FILE DOWNLOAD ─────────────────────────────────────────────────
DOWNLOAD_CONTENT_TYPES = frozenset([
    "application/octet-stream",
    "application/x-msdownload",
    "application/x-executable",
    "application/x-apple-diskimage",
    "application/vnd.android.package-archive",
    "application/x-iso9660-image",
    "application/x-msi",
])
DOWNLOAD_EXTENSIONS = frozenset([
    ".exe", ".dmg", ".apk", ".msi", ".deb", ".rpm",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso",
    ".scr", ".bat", ".cmd", ".ps1", ".jar",
])


# ═══════════════════════════════════════════════════════════════════
# SENSITIVE DETECTOR
# ═══════════════════════════════════════════════════════════════════

def detect_sensitive_flags(html: str, url: str, title: str = "",
                           content_type: str = "") -> dict:
    """Scan HTML + URL + title for sensitive flow markers.

    Returns dict with flags:
        contains_form: any <form> with inputs
        contains_login: login-related patterns
        contains_payment: payment form / 3DS / card inputs
        contains_healthcare: patient portal / medical record
        contains_banking: banking domain or keywords
        contains_sensitive_flow: True if any of the above critical flags
        download_blocked: True if content-type or extension indicates download

    Also returns per-flag reason strings explaining *what* triggered.
    """
    flags = {
        "contains_form": False,
        "contains_login": False,
        "contains_payment": False,
        "contains_banking": False,
        "contains_healthcare": False,
        "contains_sensitive_flow": False,
        "download_blocked": False,
    }
    reasons = {}

    html_lower = (html or "").lower()
    url_lower = (url or "").lower()
    title_lower = (title or "").lower()
    ct_lower = (content_type or "").lower().split(";")[0].strip()

    # ── FORM (mild signal, may be allowed) ─────────────
    if "<form" in html_lower:
        flags["contains_form"] = True
        reasons["form"] = "Stránka obsahuje formulář."

    # ── LOGIN ──────────────────────────────────────────
    login_hits = []
    for pat in LOGIN_HTML_PATTERNS:
        if pat.search(html or ""):
            login_hits.append(pat.pattern[:60])
    if any(kw in url_lower for kw in LOGIN_URL_KEYWORDS):
        login_hits.append("login keyword in URL")
    if any(kw in title_lower for kw in LOGIN_TITLE_KEYWORDS):
        login_hits.append("login keyword in title")
    if login_hits:
        flags["contains_login"] = True
        flags["contains_sensitive_flow"] = True
        reasons["login"] = "Detekovány přihlašovací prvky: " + ", ".join(login_hits[:2])

    # ── PAYMENT ────────────────────────────────────────
    payment_hits = []
    for pat in PAYMENT_HTML_PATTERNS:
        if pat.search(html or ""):
            payment_hits.append(pat.pattern[:60])
    if any(kw in url_lower for kw in PAYMENT_URL_KEYWORDS):
        payment_hits.append("payment URL")
    for kw in PAYMENT_KEYWORDS:
        if kw in html_lower:
            payment_hits.append(f'keyword "{kw}"')
            break
    if payment_hits:
        flags["contains_payment"] = True
        flags["contains_sensitive_flow"] = True
        reasons["payment"] = "Detekován platební tok: " + ", ".join(payment_hits[:2])

    # ── BANKING ────────────────────────────────────────
    # Check domain (from URL)
    domain = ""
    try:
        from urllib.parse import urlparse
        domain = (urlparse(url).hostname or "").lower()
    except Exception:
        pass
    banking_hits = []
    if any(domain == d or domain.endswith("." + d) for d in BANKING_DOMAINS):
        banking_hits.append(f"banking domain {domain}")
    for kw in BANKING_KEYWORDS:
        if kw in html_lower or kw in title_lower:
            banking_hits.append(f'banking keyword "{kw}"')
            break
    if banking_hits:
        flags["contains_banking"] = True
        flags["contains_sensitive_flow"] = True
        reasons["banking"] = "Detekován bankovní kontext: " + ", ".join(banking_hits[:2])

    # ── HEALTHCARE ─────────────────────────────────────
    healthcare_hits = []
    if any(domain == d or domain.endswith("." + d) for d in HEALTHCARE_DOMAINS):
        healthcare_hits.append(f"healthcare portal {domain}")
    if any(kw in url_lower for kw in HEALTHCARE_URL_KEYWORDS):
        healthcare_hits.append("healthcare URL")
    for kw in HEALTHCARE_KEYWORDS:
        if kw in html_lower:
            healthcare_hits.append(f'medical keyword "{kw}"')
            break
    if healthcare_hits:
        flags["contains_healthcare"] = True
        flags["contains_sensitive_flow"] = True
        reasons["healthcare"] = "Detekován zdravotnický portál: " + ", ".join(healthcare_hits[:2])

    # ── DOWNLOAD ────────────────────────────────────────
    if ct_lower in DOWNLOAD_CONTENT_TYPES:
        flags["download_blocked"] = True
        reasons["download"] = f"Typ obsahu {ct_lower} = ke stažení, v bezpečném režimu blokováno."
    else:
        for ext in DOWNLOAD_EXTENSIONS:
            if url_lower.endswith(ext):
                flags["download_blocked"] = True
                reasons["download"] = f"URL končí příponou {ext} (soubor ke stažení)."
                break

    return {"flags": flags, "reasons": reasons}


# ═══════════════════════════════════════════════════════════════════
# CZECH SENIOR-FRIENDLY MESSAGES
# ═══════════════════════════════════════════════════════════════════

SENIOR_MESSAGES = {
    # Success
    "opened_safely":     "Stránku jsem otevřel bezpečně.",
    "content_summary":   "Našel jsem zde: {summary}",
    "link_found":        "Našel jsem {n} odkazů, které můžeme bezpečně následovat.",
    "search_results":    "Na této stránce jsem našel výraz „{query}“ celkem {n}×.",
    "no_search_results": "Výraz „{query}“ jsem na této stránce nenašel.",
    "session_closed":    "Relaci jsem bezpečně uzavřel. Vaše údaje nic neukládá.",

    # Blocks — only truly dangerous (download)
    "blocked_download":  "Tento odkaz stahuje soubor. V bezpečném režimu soubory nestahuji.",
    "blocked_domain":    "Doména této stránky není na seznamu povolených. Radim otevírá "
                         "jen ověřené české zdroje jako Wikipedii, ČT, novinky nebo počasí.",
    "blocked_form":      "Našel jsem formulář, ale v této verzi jej neodesílám.",

    # Warnings — page is readable but contains sensitive flow
    "warn_login":        "Tato stránka obsahuje přihlášení. Mohu Vám ji přečíst, "
                         "ale Radim se nikam nepřihlašuje.",
    "warn_payment":      "Tato stránka obsahuje platbu. Mohu Vám ji přečíst, "
                         "ale žádné platební údaje neodesílám.",
    "warn_banking":      "Jste na bankovní stránce. Mohu Vám obsah přečíst, "
                         "ale do bankovnictví se nikdy nepřihlašuji.",
    "warn_healthcare":   "Tato stránka obsahuje zdravotnické informace. Mohu Vám "
                         "ji přečíst, ale žádné Vaše údaje nikam neukládám.",

    # Technical errors
    "timeout":           "Stránka neodpovídá. Zkuste to prosím za chvíli znovu.",
    "fetch_failed":      "Stránku se nepodařilo načíst. Možná je dočasně nedostupná.",
    "extract_failed":    "Stránku jsem otevřel, ale obsah se nepodařilo přečíst.",
    "invalid_url":       "Tato adresa nevypadá správně. Zkontrolujte ji, prosím.",

    # Session limits
    "session_expired":   "Relace vypršela po {ttl} minutách neaktivity. Otevřete prosím novou.",
    "action_limit":      "Dosáhli jsme bezpečnostního limitu {limit} akcí v jedné relaci. "
                         "Otevřete prosím novou relaci.",
    "depth_limit":       "Jsme už {depth} odkazů hluboko. Pro bezpečnost zde končím. "
                         "Zkuste otevřít novou stránku.",

    # Consent
    "no_consent":        "Před používáním prohlížeče potřebuji vaše svolení se zpracováním údajů. "
                         "Najdete ho v nastavení Radima.",

    # Mode explanations
    "mode_read_only":           "Jste v režimu pouze čtení. Neodesílám žádné formuláře ani se nikam nepřihlašuji.",
    "mode_assisted_navigation": "Jste v průvodcovském režimu. Vysvětluji, co na stránce vidím, ale stále neodesílám formuláře.",

    # Disabled
    "disabled":          "Bezpečný prohlížeč je momentálně vypnutý.",
}


def msg(key: str, **kwargs) -> str:
    """Lookup + format a czech senior-friendly message."""
    template = SENIOR_MESSAGES.get(key, key)
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


# ═══════════════════════════════════════════════════════════════════
# DETERMINE USER-FACING ERROR CODE FROM FLAGS
# ═══════════════════════════════════════════════════════════════════

def pick_block_reason(flags: dict, reasons: dict):
    """Return (error_code, senior_message, technical_reason) only for HARD
    blocks — currently just downloads (executable content). Login, payment,
    banking and healthcare pages are surfaced as WARNINGS via flags so the
    senior can still read the page; they'll be advised not to fill forms.

    Returns (None, None, None) for pure "read but be careful" cases.
    """
    if flags.get("download_blocked"):
        return ("BLOCKED_CONTENT", msg("blocked_download"),
                reasons.get("download", "download"))
    return (None, None, None)


def build_warning(flags: dict, reasons: dict) -> dict:
    """Produce a non-blocking warning payload when a page is readable but
    contains a sensitive flow. UI should show the warning prominently but
    still render the page content.

    Priority (highest-risk first): banking > healthcare > payment > login.
    Returns {} if no warning needed.
    """
    if flags.get("contains_banking"):
        return {
            "level": "high",
            "message": msg("warn_banking"),
            "reason": reasons.get("banking", "banking"),
            "advice": "Nikam nevyplňujte přihlašovací údaje. Pro přihlášení "
                      "použijte prosím běžný prohlížeč.",
        }
    if flags.get("contains_healthcare"):
        return {
            "level": "high",
            "message": msg("warn_healthcare"),
            "reason": reasons.get("healthcare", "healthcare"),
            "advice": "Zdravotní údaje neuchovávám. Pro přístup do pacientského "
                      "portálu použijte prosím běžný prohlížeč.",
        }
    if flags.get("contains_payment"):
        return {
            "level": "medium",
            "message": msg("warn_payment"),
            "reason": reasons.get("payment", "payment"),
            "advice": "Nevyplňujte číslo karty ani platební údaje. "
                      "Pro platbu použijte prosím běžný prohlížeč.",
        }
    if flags.get("contains_login"):
        return {
            "level": "low",
            "message": msg("warn_login"),
            "reason": reasons.get("login", "login"),
            "advice": "Radim se nikam nepřihlašuje. Můžete si stránku přečíst, "
                      "ale pro přihlášení použijte běžný prohlížeč.",
        }
    return {}
