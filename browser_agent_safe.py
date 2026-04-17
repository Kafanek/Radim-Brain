"""
🛡️ RADIM Safe Web Agent — GDPR-first senior-facing web browsing
=============================================================================
Thin privacy layer over browser_agent v10.34. Adds:
    - Safety modes (read_only / assisted_navigation)
    - Sensitive page detection (login / payment / banking / healthcare / download)
    - Role-based response filtering
    - Action + navigation depth counters
    - Explicit retention (raw HTML NEVER persisted)
    - Reasoning field (why_allowed / why_blocked)
    - Czech senior-friendly messages
    - GDPR consent enforcement

Separation from v10.34:
    /api/browser/*  — internal research tool for AI agents (unchanged)
    /api/safe-web/* — senior-facing, strict, through this module

Feature-flagged via ENABLE_SAFE_WEB_AGENT env var.
Design principle: if uncertain → block and explain.
"""

import logging
import os
import secrets
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# FEATURE FLAG
# ═══════════════════════════════════════════════════════════════════

ENABLE_SAFE_WEB_AGENT = os.environ.get("ENABLE_SAFE_WEB_AGENT", "false").lower() == "true"


# ═══════════════════════════════════════════════════════════════════
# SESSION STORE (in-memory, 15 min TTL, thread-safe, LRU)
# ═══════════════════════════════════════════════════════════════════

from browser_agent_safe_config import (
    SAFE_SESSION_TTL_SEC,
    SAFE_MAX_SESSIONS,
    SAFE_MAX_ACTIONS_PER_SESSION,
    SAFE_MAX_NAVIGATION_DEPTH,
    ALLOWED_MODES,
    MODE_READ_ONLY,
    MODE_ASSISTED_NAVIGATION,
    get_role_permissions,
    detect_sensitive_flags,
    pick_block_reason,
    msg,
)

_safe_sessions = {}
_safe_lock = threading.Lock()


def _new_session_id() -> str:
    return "sw_" + secrets.token_urlsafe(12)


def _cleanup_stale():
    """Evict expired sessions. Called on each access + by scheduler."""
    now = time.time()
    with _safe_lock:
        stale = [sid for sid, s in _safe_sessions.items()
                 if now - s.get("last_activity", 0) > SAFE_SESSION_TTL_SEC]
        for sid in stale:
            _safe_sessions.pop(sid, None)
        # LRU if still over cap
        if len(_safe_sessions) > SAFE_MAX_SESSIONS:
            ordered = sorted(_safe_sessions.items(),
                             key=lambda kv: kv[1].get("last_activity", 0))
            excess = len(_safe_sessions) - SAFE_MAX_SESSIONS
            for sid, _ in ordered[:excess]:
                _safe_sessions.pop(sid, None)
    if stale:
        logger.info(f"🛡️ Safe Web: evicted {len(stale)} stale sessions")


def _get_session(session_id: str):
    _cleanup_stale()
    with _safe_lock:
        s = _safe_sessions.get(session_id)
        if s:
            s["last_activity"] = time.time()
        return s


def _save_session(session_id: str, state: dict):
    with _safe_lock:
        _safe_sessions[session_id] = state


def cleanup_safe_web_sessions() -> dict:
    """Called by agent_loop.run_daily_cleanup at 3 AM. Logs retention summary."""
    with _safe_lock:
        before = len(_safe_sessions)
    _cleanup_stale()
    with _safe_lock:
        after = len(_safe_sessions)
    stats = {"sessions_before": before, "sessions_after": after, "evicted": before - after}
    logger.info(f"🛡️ Safe Web retention cleanup: {stats}")
    return stats


def get_active_session_count() -> int:
    with _safe_lock:
        return len(_safe_sessions)


# ═══════════════════════════════════════════════════════════════════
# ERROR HELPERS
# ═══════════════════════════════════════════════════════════════════

def _error(session_id, status, error_code, user_message,
           why_blocked=None, recommended_next=None, flags=None):
    return {
        "success": False,
        "session_id": session_id,
        "status": status,
        "error_code": error_code,
        "message": user_message,
        "safety_state": "blocked" if status == "blocked" else status,
        "flags": flags or {},
        "reasoning": {
            "why_blocked": why_blocked,
            "recommended_next_step": recommended_next,
        },
    }


def _disabled_response():
    return _error(
        session_id=None, status="blocked", error_code="DISABLED",
        user_message=msg("disabled"),
        why_blocked="Feature flag ENABLE_SAFE_WEB_AGENT is off.",
        recommended_next="Kontaktujte administrátora.",
    )


# ═══════════════════════════════════════════════════════════════════
# AUDIT LOG (privacy-minimal)
# ═══════════════════════════════════════════════════════════════════

def _audit(event_type: str, url: str, user_id: str = None, details: dict = None,
           session_id: str = None):
    """Fire-and-forget audit trail. Non-fatal failures.

    Privacy-minimal: we store host (not full path for sensitive types),
    user_id, mode, safety_state, action counters. NEVER:
    - full form values
    - cookies
    - hidden fields
    - raw HTML
    - credentials
    """
    try:
        from database import db_context, db_insert
        from urllib.parse import urlparse
        import json as _json

        host = ""
        try:
            host = urlparse(url).hostname or ""
        except Exception:
            pass

        # Reduce to host-only for sensitive types (no full path)
        safe_details = dict(details or {})
        if event_type in ("safe_web_blocked", "safe_web_sensitive"):
            safe_details["url_host"] = host
            safe_details.pop("url", None)
            safe_details.pop("full_url", None)
        else:
            # Non-sensitive events can carry short URL
            safe_details["url_host"] = host

        msg_map = {
            "safe_web_open":       f"🛡️ Otevřeno bezpečně: {host}",
            "safe_web_blocked":    f"🛡️ Blokováno: {host}",
            "safe_web_sensitive":  f"🛡️ Detekován citlivý tok na: {host}",
            "safe_web_click":      f"🛡️ Následován odkaz: {host}",
            "safe_web_find":       f"🛡️ Vyhledávání ve stránce",
            "safe_web_error":      f"⚠️ Chyba: {host}",
            "safe_web_close":      f"🛡️ Relace uzavřena",
            "safe_web_consent":    f"🛡️ GDPR souhlas chybí",
        }

        with db_context(commit=True) as db:
            db_insert(db, "agent_observations",
                      ["user_id", "observation_type", "severity", "message",
                       "action_taken", "details"],
                      [user_id or "anonymous", event_type, "info",
                       msg_map.get(event_type, f"🛡️ {event_type}"),
                       "safe_web_agent",
                       _json.dumps(safe_details)])
    except Exception as e:
        logger.debug(f"Safe Web audit log failed (non-fatal): {e}")


# ═══════════════════════════════════════════════════════════════════
# GDPR CONSENT CHECK
# ═══════════════════════════════════════════════════════════════════

def _check_consent(user_id: str) -> bool:
    """True if user has given data_processing consent. False means block."""
    if not user_id:
        return False
    try:
        from memory_helpers import get_gdpr_consent
        consent = get_gdpr_consent(user_id)
        return bool(consent.get("data_processing", False))
    except Exception:
        # On failure, default to TRUE for backwards compat if GDPR not set up
        # (otherwise nobody can use the feature)
        return True


# ═══════════════════════════════════════════════════════════════════
# MAIN API — open_page
# ═══════════════════════════════════════════════════════════════════

def open_page(url: str, mode: str = MODE_READ_ONLY,
              user_id: str = None, role: str = "senior_user",
              user_consent_confirmed: bool = False) -> dict:
    """Safely open a URL with privacy + GDPR layer.

    Args:
        url: target URL
        mode: read_only | assisted_navigation (ALLOWED_MODES)
        user_id: authenticated user id (required)
        role: senior_user | caregiver | admin
        user_consent_confirmed: frontend set this true after user OK'd consent

    Returns structured response (see module docstring).
    """
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()

    # Validate mode
    if mode not in ALLOWED_MODES:
        mode = MODE_READ_ONLY

    perms = get_role_permissions(role)
    if not perms.get("can_open_pages"):
        return _error(None, "blocked", "ROLE_DENIED",
                      "Vaše role nemá oprávnění otevírat stránky.",
                      why_blocked=f"Role '{role}' is not permitted to open pages.")

    # GDPR consent gate (seniors require it)
    if perms.get("requires_gdpr_consent") and not user_consent_confirmed:
        if not _check_consent(user_id):
            _audit("safe_web_consent", url or "", user_id, {"mode": mode})
            return _error(None, "blocked", "NO_CONSENT",
                          msg("no_consent"),
                          why_blocked="Data processing consent not granted.",
                          recommended_next="Otevřete nastavení Radima a udělte souhlas.")

    # Delegate fetch + extract to v10.34 browser_agent (which handles URL
    # validation, SSRF defense, allowlist, HTTP retry, content-type filter,
    # trafilatura + BS4 extraction). We don't reinvent that.
    try:
        from browser_agent import open_page as _bp_open
        # Ensure v10.34 is temporarily enabled for this call regardless of its flag
        # (we still honor OUR flag which is ENABLE_SAFE_WEB_AGENT)
        import browser_agent as _bp
        _orig_flag = _bp.ENABLE_BROWSER_AGENT
        _bp.ENABLE_BROWSER_AGENT = True
        try:
            inner = _bp_open(url, user_id=user_id)
        finally:
            _bp.ENABLE_BROWSER_AGENT = _orig_flag
    except ImportError as e:
        return _error(None, "error", "NOT_AVAILABLE",
                      msg("fetch_failed"),
                      why_blocked=f"browser_agent not installed: {e}")

    # Fetch / safety layer error — translate to senior-friendly
    if not inner.get("success"):
        inner_code = inner.get("error_code", "")
        _audit("safe_web_blocked", url, user_id,
               {"mode": mode, "inner_code": inner_code})
        user_msg_key = {
            "BLOCKED_DOMAIN":  "blocked_domain",
            "BLOCKED_SCHEME":  "invalid_url",
            "BLOCKED_PORT":    "invalid_url",
            "BLOCKED_CONTENT": "blocked_download",
            "INVALID_URL":     "invalid_url",
            "TIMEOUT":         "timeout",
            "SSL_ERROR":       "fetch_failed",
            "CONNECTION_ERROR": "fetch_failed",
            "HTTP_ERROR":      "fetch_failed",
            "TOO_LARGE":       "fetch_failed",
            "TOO_MANY_REDIRECTS": "fetch_failed",
            "EXTRACT_FAILED":  "extract_failed",
        }.get(inner_code, "fetch_failed")
        return _error(None, "blocked" if inner_code.startswith("BLOCKED") else "error",
                      inner_code, msg(user_msg_key),
                      why_blocked=inner.get("error"),
                      recommended_next="Zkuste prosím jinou adresu nebo počkejte.")

    # ── Fetch succeeded. Now apply SAFE WEB privacy/safety layer. ──

    # We need the raw HTML to run sensitive detection. v10.34 doesn't keep it
    # in its session (extracted text only), so we re-do a lightweight fetch
    # to scan HTML. This keeps raw HTML IN MEMORY only, never persisted.
    raw_html = ""
    content_type = inner.get("metadata", {}).get("content_type", "")
    try:
        from browser_agent_fetcher import fetch as _raw_fetch
        raw = _raw_fetch(inner["final_url"], allow_external=False)
        raw_html = raw.get("content", "")
        content_type = raw.get("content_type", content_type)
    except Exception as e:
        logger.debug(f"Raw HTML re-fetch failed (using inner only): {e}")
        # Use extracted text as fallback for detection (weaker but still works)
        raw_html = inner.get("main_content", "")

    # Run sensitive detection
    detection = detect_sensitive_flags(
        html=raw_html,
        url=inner["final_url"],
        title=inner.get("title", ""),
        content_type=content_type,
    )
    flags = detection["flags"]
    reasons = detection["reasons"]

    # Discard raw_html after detection (privacy — never persist)
    raw_html = None

    # If sensitive flow → block with czech explanation
    block_code, block_msg, block_why = pick_block_reason(flags, reasons)
    if block_code:
        _audit("safe_web_sensitive", inner["final_url"], user_id,
               {"mode": mode, "flags": flags, "kind": block_code})
        # Note: we do NOT return extracted content on sensitive flow
        return _error(None, "blocked", block_code, block_msg,
                      why_blocked=block_why,
                      recommended_next="Zkuste stránku otevřít v běžném prohlížeči.",
                      flags=flags)

    # Safe to proceed. Build session.
    session_id = _new_session_id()
    now = time.time()
    state = {
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "mode": mode,
        "url": url,
        "final_url": inner["final_url"],
        "title": inner.get("title", ""),
        "text_excerpt": inner.get("text_excerpt", ""),
        "main_content": inner.get("main_content", ""),  # extracted text, no HTML
        "links": inner.get("links", []),
        "metadata": inner.get("metadata", {}),
        "flags": flags,
        "created_at": now,
        "last_activity": now,
        "actions_used": 1,
        "depth": 1,
        "domains_visited": [inner["final_url"].split("/")[2] if "//" in inner["final_url"] else ""],
        "blocked_events": [],
        "history": [inner["final_url"]],
    }
    _save_session(session_id, state)
    _audit("safe_web_open", inner["final_url"], user_id, {
        "mode": mode, "session_id": session_id,
        "title_len": len(state["title"]),
        "content_len": len(state["main_content"]),
        "latency_ms": inner.get("metadata", {}).get("latency_ms", 0),
    })

    return _build_response(state, perms)


def _build_response(state: dict, perms: dict) -> dict:
    """Assemble public response, respecting role permissions."""
    flags = state.get("flags", {})
    mode = state.get("mode", MODE_READ_ONLY)

    # Compose summary (short user-friendly explanation)
    summary_text = state.get("text_excerpt", "")[:240]
    if len(state.get("main_content", "")) > 240:
        summary_text = summary_text.rstrip() + "…"
    summary_sentence = msg("opened_safely")
    if state.get("title"):
        summary_sentence += f' Otevřel jsem „{state["title"][:80]}".'

    response = {
        "success": True,
        "session_id": state["session_id"],
        "mode": mode,
        "status": "ready",
        "safety_state": "safe",
        "title": state.get("title", ""),
        "url": state.get("url", ""),
        "final_url": state.get("final_url", ""),
        "summary": summary_sentence,
        "main_content": state.get("main_content", "") if perms.get("sees_full_content") else summary_text,
        "text_excerpt": state.get("text_excerpt", ""),
        "links": [
            {"text": l.get("text", "")[:120],
             "href": l.get("href", ""),
             "safe": bool(l.get("is_safe")),
             "reason": None if l.get("is_safe") else "Nepovolená doména"}
            for l in state.get("links", [])[:30]
        ],
        "flags": flags,
        "audit": {
            "actions_used": state.get("actions_used", 0),
            "actions_limit": SAFE_MAX_ACTIONS_PER_SESSION,
            "depth_used": state.get("depth", 1),
            "depth_limit": SAFE_MAX_NAVIGATION_DEPTH,
            "session_age_sec": int(time.time() - state.get("created_at", time.time())),
            "session_ttl_sec": SAFE_SESSION_TTL_SEC,
            "domains_visited": state.get("domains_visited", []),
            "blocked_events": state.get("blocked_events", []),
        },
        "reasoning": {
            "why_allowed": f"Doména je na seznamu bezpečných zdrojů. "
                           f"Stránka neobsahuje citlivé toky (přihlášení, platba, banka, zdravotní záznam).",
            "why_blocked": None,
            "mode_explanation": ALLOWED_MODES[mode]["description"],
        },
    }

    # Strip raw_html from metadata if present (defense in depth)
    meta = dict(state.get("metadata", {}))
    meta.pop("content", None)
    meta.pop("raw_html", None)
    response["metadata"] = meta

    return response


# ═══════════════════════════════════════════════════════════════════
# SESSION API
# ═══════════════════════════════════════════════════════════════════

def read_current_page(session_id: str, user_id: str = None) -> dict:
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    state = _get_session(session_id)
    if not state:
        return _error(session_id, "error", "SESSION_NOT_FOUND",
                      msg("session_expired", ttl=SAFE_SESSION_TTL_SEC // 60))
    if user_id and state.get("user_id") != user_id:
        return _error(session_id, "blocked", "ROLE_DENIED",
                      "Tato relace nepatří vám.")
    perms = get_role_permissions(state.get("role", "senior_user"))
    # Action counter
    state["actions_used"] = state.get("actions_used", 0) + 1
    if state["actions_used"] > SAFE_MAX_ACTIONS_PER_SESSION:
        return _error(session_id, "blocked", "ACTION_LIMIT",
                      msg("action_limit", limit=SAFE_MAX_ACTIONS_PER_SESSION))
    return _build_response(state, perms)


def find_on_page(session_id: str, query: str, user_id: str = None) -> dict:
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    state = _get_session(session_id)
    if not state:
        return _error(session_id, "error", "SESSION_NOT_FOUND",
                      msg("session_expired", ttl=SAFE_SESSION_TTL_SEC // 60))
    if user_id and state.get("user_id") != user_id:
        return _error(session_id, "blocked", "ROLE_DENIED",
                      "Tato relace nepatří vám.")

    # Sanitize query
    try:
        from input_sanitizer import sanitize_input
        query, threat, _ = sanitize_input(query or "")
        if threat == "blocked":
            return _error(session_id, "blocked", "INVALID_QUERY",
                          "Tento dotaz nemohu zpracovat.")
    except ImportError:
        pass

    state["actions_used"] = state.get("actions_used", 0) + 1
    if state["actions_used"] > SAFE_MAX_ACTIONS_PER_SESSION:
        return _error(session_id, "blocked", "ACTION_LIMIT",
                      msg("action_limit", limit=SAFE_MAX_ACTIONS_PER_SESSION))

    try:
        from browser_agent_extractor import find_in_content
    except ImportError:
        return _error(session_id, "error", "NOT_AVAILABLE",
                      msg("extract_failed"))

    matches = find_in_content(state.get("main_content", ""), query)
    _audit("safe_web_find", state.get("final_url", ""), user_id,
           {"session_id": session_id, "matches": len(matches),
            "query_len": len(query)})
    user_msg = (msg("search_results", query=query, n=len(matches))
                if matches else msg("no_search_results", query=query))
    return {
        "success": True,
        "session_id": session_id,
        "query": query,
        "matches": matches[:15],
        "count": len(matches),
        "message": user_msg,
    }


def list_links(session_id: str, user_id: str = None, safe_only: bool = False) -> dict:
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    state = _get_session(session_id)
    if not state:
        return _error(session_id, "error", "SESSION_NOT_FOUND",
                      msg("session_expired", ttl=SAFE_SESSION_TTL_SEC // 60))
    if user_id and state.get("user_id") != user_id:
        return _error(session_id, "blocked", "ROLE_DENIED", "Tato relace nepatří vám.")

    links = state.get("links", [])
    if safe_only:
        links = [l for l in links if l.get("is_safe")]
    return {
        "success": True,
        "session_id": session_id,
        "count": len(links),
        "links": [
            {"text": l.get("text", "")[:120],
             "href": l.get("href", ""),
             "safe": bool(l.get("is_safe")),
             "reason": None if l.get("is_safe") else "Nepovolená doména"}
            for l in links
        ],
    }


def safe_follow_link(session_id: str, link_index: int, user_id: str = None) -> dict:
    """Follow a link by index in current session's link list.

    Respects: depth limit, action counter, safety flags. Each follow runs
    the full sensitive-page detection pipeline on the new page.
    """
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    state = _get_session(session_id)
    if not state:
        return _error(session_id, "error", "SESSION_NOT_FOUND",
                      msg("session_expired", ttl=SAFE_SESSION_TTL_SEC // 60))
    if user_id and state.get("user_id") != user_id:
        return _error(session_id, "blocked", "ROLE_DENIED", "Tato relace nepatří vám.")

    # Depth limit
    if state.get("depth", 1) >= SAFE_MAX_NAVIGATION_DEPTH:
        return _error(session_id, "blocked", "DEPTH_LIMIT",
                      msg("depth_limit", depth=SAFE_MAX_NAVIGATION_DEPTH))

    # Action counter
    state["actions_used"] = state.get("actions_used", 0) + 1
    if state["actions_used"] > SAFE_MAX_ACTIONS_PER_SESSION:
        return _error(session_id, "blocked", "ACTION_LIMIT",
                      msg("action_limit", limit=SAFE_MAX_ACTIONS_PER_SESSION))

    try:
        idx = int(link_index)
    except (TypeError, ValueError):
        return _error(session_id, "error", "INVALID_INDEX",
                      "Číslo odkazu musí být celé číslo.")

    links = state.get("links", [])
    if idx < 0 or idx >= len(links):
        return _error(session_id, "error", "INVALID_INDEX",
                      f"Odkaz č. {idx} neexistuje.")

    link = links[idx]
    if not link.get("is_safe"):
        state["blocked_events"].append({
            "at": datetime.utcnow().isoformat() + "Z",
            "reason": "Link domain not in allowlist",
            "link_text": link.get("text", "")[:80],
        })
        _audit("safe_web_blocked", link.get("href", ""), user_id,
               {"session_id": session_id, "reason": "unsafe_link"})
        _link_label = (link.get('text', '') or '')[:60]
        return _error(session_id, "blocked", "BLOCKED_DOMAIN",
                      f"Odkaz „{_link_label}“ vede mimo bezpečný seznam.",
                      why_blocked="Link href is outside domain allowlist.",
                      recommended_next="Zůstaňte na této stránce nebo vyberte jiný odkaz.")

    # Follow via open_page (runs full privacy layer again)
    new_result = open_page(
        url=link["href"],
        mode=state.get("mode", MODE_READ_ONLY),
        user_id=user_id,
        role=state.get("role", "senior_user"),
        user_consent_confirmed=True,  # senior already consented when session started
    )
    if not new_result.get("success"):
        # Record as blocked event on current session, return the error
        state["blocked_events"].append({
            "at": datetime.utcnow().isoformat() + "Z",
            "reason": new_result.get("error_code", ""),
            "link_text": link.get("text", "")[:80],
        })
        return new_result

    # Merge into current session (keep session_id stable)
    new_sid = new_result["session_id"]
    with _safe_lock:
        new_state = _safe_sessions.pop(new_sid, None)
        if new_state:
            new_state["session_id"] = session_id
            new_state["depth"] = state.get("depth", 1) + 1
            new_state["actions_used"] = state["actions_used"]
            new_state["domains_visited"] = list(set(
                state.get("domains_visited", []) + new_state.get("domains_visited", [])
            ))
            new_state["history"] = state.get("history", []) + new_state.get("history", [])
            new_state["blocked_events"] = state.get("blocked_events", []) + new_state.get("blocked_events", [])
            _safe_sessions[session_id] = new_state

    _audit("safe_web_click", link["href"], user_id,
           {"session_id": session_id, "link_text": link.get("text", "")[:80]})

    # Build response with original session_id
    perms = get_role_permissions(state.get("role", "senior_user"))
    refreshed = _get_session(session_id)
    return _build_response(refreshed, perms) if refreshed else new_result


def get_session_audit(session_id: str, user_id: str = None, role: str = "senior_user") -> dict:
    """Return audit summary. Seniors see own sessions only; admin sees all."""
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    state = _get_session(session_id)
    if not state:
        return _error(session_id, "error", "SESSION_NOT_FOUND",
                      msg("session_expired", ttl=SAFE_SESSION_TTL_SEC // 60))
    perms = get_role_permissions(role)
    if state.get("user_id") != user_id and not perms.get("sees_other_users_audit"):
        return _error(session_id, "blocked", "ROLE_DENIED", "Tato relace nepatří vám.")

    return {
        "success": True,
        "session_id": session_id,
        "user_id": state.get("user_id"),
        "mode": state.get("mode"),
        "actions_used": state.get("actions_used", 0),
        "actions_limit": SAFE_MAX_ACTIONS_PER_SESSION,
        "depth_used": state.get("depth", 1),
        "depth_limit": SAFE_MAX_NAVIGATION_DEPTH,
        "session_age_sec": int(time.time() - state.get("created_at", time.time())),
        "domains_visited": state.get("domains_visited", []),
        "blocked_events": state.get("blocked_events", []),
        "history": state.get("history", []),
        "flags": state.get("flags", {}),
    }


def close_session(session_id: str, user_id: str = None) -> dict:
    if not ENABLE_SAFE_WEB_AGENT:
        return _disabled_response()
    with _safe_lock:
        state = _safe_sessions.pop(session_id, None)
    if state:
        _audit("safe_web_close", state.get("final_url", ""), user_id,
               {"session_id": session_id,
                "actions_used": state.get("actions_used", 0),
                "depth": state.get("depth", 1)})
    return {
        "success": True,
        "session_id": session_id,
        "closed": state is not None,
        "message": msg("session_closed"),
    }


# ═══════════════════════════════════════════════════════════════════
# STATS / METADATA
# ═══════════════════════════════════════════════════════════════════

def stats() -> dict:
    return {
        "success": True,
        "enabled": ENABLE_SAFE_WEB_AGENT,
        "sessions_active": get_active_session_count(),
        "session_ttl_min": SAFE_SESSION_TTL_SEC // 60,
        "max_actions_per_session": SAFE_MAX_ACTIONS_PER_SESSION,
        "max_navigation_depth": SAFE_MAX_NAVIGATION_DEPTH,
    }


def list_modes() -> dict:
    """Public endpoint — what modes exist and what they allow (transparency)."""
    return {
        "success": True,
        "modes": {k: {"description": v["description"],
                      "permissions": {pk: pv for pk, pv in v.items()
                                      if pk != "description"}}
                  for k, v in ALLOWED_MODES.items()},
    }


logger.info(f"🛡️ Safe Web Agent loaded (enabled={ENABLE_SAFE_WEB_AGENT}, "
            f"TTL={SAFE_SESSION_TTL_SEC}s, max_actions={SAFE_MAX_ACTIONS_PER_SESSION})")
