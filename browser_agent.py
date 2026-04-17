"""
🌐 RADIM Browser Agent — Core orchestrator
=============================================================================
Stateful session-based public API for the read-only web agent.

Pipeline:
    open_page(url) → [safety → fetch → extract] → session stored
    read_page / find / list_links / click_link → operate on session state
    close_session / cleanup

Session store = in-memory TTL cache (same pattern as rtcf_bridge._psi_previous).
No disk, no DB — sessions live 30 min then vanish.

Feature-flagged via ENABLE_BROWSER_AGENT env var. When disabled, all public
API calls return structured {success: false, error_code: 'DISABLED'}.
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

ENABLE_BROWSER_AGENT = os.environ.get('ENABLE_BROWSER_AGENT', 'false').lower() == 'true'


# ═══════════════════════════════════════════════════════════════════
# SESSION STORE (TTL cache)
# ═══════════════════════════════════════════════════════════════════

_SESSION_TTL = 1800        # 30 minutes
_MAX_SESSIONS = 100        # LRU eviction after this
_sessions = {}             # {session_id: session_dict}
_sessions_lock = threading.Lock()


def _new_session_id() -> str:
    return 'br_' + secrets.token_urlsafe(12)


def _cleanup_stale():
    """Evict expired sessions. Called lazily on each session access."""
    now = time.time()
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items()
                 if now - s.get('last_activity', 0) > _SESSION_TTL]
        for sid in stale:
            _sessions.pop(sid, None)
        # LRU: evict oldest if still over limit
        if len(_sessions) > _MAX_SESSIONS:
            oldest = sorted(_sessions.items(), key=lambda kv: kv[1].get('last_activity', 0))
            excess = len(_sessions) - _MAX_SESSIONS
            for sid, _ in oldest[:excess]:
                _sessions.pop(sid, None)
    if stale:
        logger.info(f"🌐 Browser agent: evicted {len(stale)} stale sessions")


def _get_session(session_id: str):
    _cleanup_stale()
    with _sessions_lock:
        s = _sessions.get(session_id)
        if s:
            s['last_activity'] = time.time()
        return s


def _save_session(session_id: str, state: dict):
    with _sessions_lock:
        _sessions[session_id] = state


def get_session_count() -> int:
    with _sessions_lock:
        return len(_sessions)


# ═══════════════════════════════════════════════════════════════════
# STRUCTURED ERROR HELPER
# ═══════════════════════════════════════════════════════════════════

def _error(code: str, message: str, url: str = '', details: dict = None) -> dict:
    return {
        'success': False,
        'error_code': code,
        'error': message,
        'details': {
            **(details or {}),
            'url': url,
        } if url else (details or {}),
    }


def _disabled() -> dict:
    return _error('DISABLED',
                  'Browser Agent je vypnutý. Požádejte administrátora o aktivaci.')


# ═══════════════════════════════════════════════════════════════════
# AUDIT LOG (writes to agent_observations via background-safe path)
# ═══════════════════════════════════════════════════════════════════

def _audit_log(event_type: str, url: str, user_id: str = None, details: dict = None):
    """Fire-and-forget audit trail. Failures never break the public API."""
    try:
        from database import db_context, db_insert, is_postgres
        import json as _json
        msg_url = (url or '')[:140]
        severity = 'info' if event_type.startswith('web_') else 'warning'
        msg_map = {
            'web_fetch': f'🌐 Otevřeno: {msg_url}',
            'web_click': f'🌐 Kliknuto na odkaz: {msg_url}',
            'web_find': f'🌐 Vyhledáno na stránce',
            'web_blocked': f'🛡️ Blokováno: {msg_url}',
            'web_error': f'⚠️ Chyba prohlížeče: {msg_url}',
            'web_close': f'🌐 Relace uzavřena',
        }
        with db_context(commit=True) as db:
            db_insert(db, 'agent_observations',
                      ['user_id', 'observation_type', 'severity', 'message', 'action_taken', 'details'],
                      [user_id or 'anonymous', event_type, severity,
                       msg_map.get(event_type, f'🌐 {event_type}'),
                       'browser_agent',
                       _json.dumps(details or {})])
    except Exception as e:
        logger.debug(f"Audit log failed (non-fatal): {e}")


# ═══════════════════════════════════════════════════════════════════
# PUBLIC API — called from routes AND from other agents
# ═══════════════════════════════════════════════════════════════════

def open_page(url: str, user_id: str = None, allow_external: bool = False) -> dict:
    """Open a URL: validate → fetch → extract → store as session.

    Args:
        url: target URL (must be http/https)
        user_id: optional user id for audit trail
        allow_external: bypass allowlist (admin-only; NEVER from user input)

    Returns:
        Structured result (see module docstring for schema) or error object.
    """
    if not ENABLE_BROWSER_AGENT:
        return _disabled()

    try:
        from browser_agent_safety import SafetyError, validate_url
        from browser_agent_fetcher import FetchError, fetch
        from browser_agent_extractor import ExtractError, extract
    except ImportError as e:
        return _error('NOT_AVAILABLE', f'Browser agent dependencies missing: {e}', url)

    # 1. Validate URL (early reject)
    try:
        validate_url(url, allow_external=allow_external)
    except SafetyError as e:
        _audit_log('web_blocked', url, user_id, {'reason': e.message, 'code': e.code})
        return _error(e.code, e.message, url)

    # 2. Fetch
    try:
        fetched = fetch(url, allow_external=allow_external)
    except SafetyError as e:
        _audit_log('web_blocked', url, user_id, {'reason': e.message, 'code': e.code})
        return _error(e.code, e.message, url)
    except FetchError as e:
        _audit_log('web_error', url, user_id, {'reason': e.message, 'code': e.code})
        return _error(e.code, e.message, url)
    except Exception as e:
        logger.warning(f"Unexpected fetch failure for {url}: {e}")
        _audit_log('web_error', url, user_id, {'reason': str(e)})
        return _error('FETCH_FAILED', f'Neočekávaná chyba při stahování: {e}', url)

    # 3. Extract
    try:
        extracted = extract(fetched['content'], fetched['final_url'])
    except ExtractError as e:
        _audit_log('web_error', url, user_id, {'reason': e.message, 'code': e.code})
        return _error(e.code, e.message, url)
    except Exception as e:
        logger.warning(f"Unexpected extract failure for {url}: {e}")
        return _error('EXTRACT_FAILED', f'Nepodařilo se přečíst obsah: {e}', url)

    # 4. Store session
    session_id = _new_session_id()
    state = {
        'session_id': session_id,
        'user_id': user_id,
        'url': url,
        'final_url': fetched['final_url'],
        'title': extracted['title'],
        'description': extracted['description'],
        'main_content': extracted['main_content'],
        'text_excerpt': extracted['text_excerpt'],
        'links': extracted['links'],
        'metadata': {
            'description': extracted['description'],
            'status_code': fetched['status_code'],
            'content_type': fetched['content_type'],
            'language': extracted['language'],
            'site_name': extracted['site_name'],
            'fetched_at': datetime.utcnow().isoformat() + 'Z',
            'latency_ms': fetched['latency_ms'],
            'content_length': fetched['content_length'],
        },
        'reasoning': {
            'load_state': 'complete',
            'extractor_used': extracted['extractor_used'],
            'extractor_fallback': extracted['extractor_fallback'],
            'domain_allowed': True,
            'redirect_chain': fetched['redirect_chain'],
        },
        'created_at': time.time(),
        'last_activity': time.time(),
        'history': [fetched['final_url']],
    }
    _save_session(session_id, state)
    _audit_log('web_fetch', fetched['final_url'], user_id, {
        'title': extracted['title'][:80],
        'content_length': fetched['content_length'],
        'latency_ms': fetched['latency_ms'],
        'session_id': session_id,
    })

    # Structured output contract
    return {
        'success': True,
        'session_id': session_id,
        'url': state['url'],
        'final_url': state['final_url'],
        'title': state['title'],
        'text_excerpt': state['text_excerpt'],
        'main_content': state['main_content'],
        'links': state['links'],
        'metadata': state['metadata'],
        'reasoning': state['reasoning'],
    }


def read_page(session_id: str) -> dict:
    """Return cached page content for given session."""
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    state = _get_session(session_id)
    if not state:
        return _error('SESSION_NOT_FOUND', 'Relace neexistuje nebo vypršela')
    return {
        'success': True,
        'session_id': session_id,
        'url': state['url'],
        'final_url': state['final_url'],
        'title': state['title'],
        'text_excerpt': state['text_excerpt'],
        'main_content': state['main_content'],
        'links': state['links'],
        'metadata': state['metadata'],
        'reasoning': state['reasoning'],
    }


def find_on_page(session_id: str, query: str) -> dict:
    """Search within cached page content."""
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    state = _get_session(session_id)
    if not state:
        return _error('SESSION_NOT_FOUND', 'Relace neexistuje nebo vypršela')
    try:
        from browser_agent_extractor import find_in_content
    except ImportError:
        return _error('NOT_AVAILABLE', 'Extractor není k dispozici')

    matches = find_in_content(state['main_content'], query)
    _audit_log('web_find', state['final_url'], state.get('user_id'), {
        'query': query[:80],
        'matches': len(matches),
        'session_id': session_id,
    })
    return {
        'success': True,
        'session_id': session_id,
        'query': query,
        'matches': matches,
        'count': len(matches),
    }


def list_links(session_id: str, safe_only: bool = False) -> dict:
    """Return link list of cached page."""
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    state = _get_session(session_id)
    if not state:
        return _error('SESSION_NOT_FOUND', 'Relace neexistuje nebo vypršela')
    links = state['links']
    if safe_only:
        links = [l for l in links if l.get('is_safe')]
    return {
        'success': True,
        'session_id': session_id,
        'count': len(links),
        'links': links,
    }


def click_link(session_id: str, index: int) -> dict:
    """Navigate to link[index] in the current session's link list.

    Under the hood: new fetch to that URL, reuses same session_id.
    """
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    state = _get_session(session_id)
    if not state:
        return _error('SESSION_NOT_FOUND', 'Relace neexistuje nebo vypršela')

    try:
        idx = int(index)
    except (TypeError, ValueError):
        return _error('INVALID_INDEX', 'Index odkazu musí být číslo')

    if idx < 0 or idx >= len(state['links']):
        return _error('INVALID_INDEX', f'Index {idx} mimo rozsah (0..{len(state["links"])-1})')

    link = state['links'][idx]
    if not link.get('is_safe'):
        _audit_log('web_blocked', link['href'], state.get('user_id'),
                   {'reason': 'Link outside allowlist', 'index': idx, 'session_id': session_id})
        return _error('BLOCKED_DOMAIN',
                      f'Odkaz "{link["text"][:60]}" vede na nepovolenou doménu',
                      link['href'])

    # Re-fetch target URL (new session_id to keep semantics clean)
    # But we also keep history on the original session for "zpět" support
    new_result = open_page(link['href'], user_id=state.get('user_id'))
    if new_result.get('success'):
        # Patch: use original session_id + append to history
        new_sid = new_result['session_id']
        with _sessions_lock:
            # Pop the brand-new session, merge history into original
            new_state = _sessions.pop(new_sid, None)
            if new_state:
                # Carry forward history
                history = state.get('history', []) + [new_state['final_url']]
                new_state['session_id'] = session_id
                new_state['history'] = history
                new_state['user_id'] = state.get('user_id')
                _sessions[session_id] = new_state
        _audit_log('web_click', link['href'], state.get('user_id'), {
            'from': state['final_url'],
            'link_text': link['text'][:80],
            'index': idx,
            'session_id': session_id,
        })
        # Return result with original session_id
        new_result['session_id'] = session_id
    return new_result


def get_snapshot(session_id: str) -> dict:
    """Full state dump — for debugging / UI reconciliation."""
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    state = _get_session(session_id)
    if not state:
        return _error('SESSION_NOT_FOUND', 'Relace neexistuje nebo vypršela')
    return {
        'success': True,
        'session_id': session_id,
        'state': {
            'url': state['url'],
            'final_url': state['final_url'],
            'title': state['title'],
            'history': state.get('history', []),
            'links_count': len(state['links']),
            'created_at': state['created_at'],
            'last_activity': state['last_activity'],
            'user_id': state.get('user_id'),
        },
    }


def close_session(session_id: str) -> dict:
    """Drop a session."""
    if not ENABLE_BROWSER_AGENT:
        return _disabled()
    with _sessions_lock:
        existed = _sessions.pop(session_id, None) is not None
    if existed:
        _audit_log('web_close', '', None, {'session_id': session_id})
    return {'success': True, 'closed': existed, 'session_id': session_id}


def stats() -> dict:
    """Admin-only: session counters, feature flag state."""
    return {
        'success': True,
        'enabled': ENABLE_BROWSER_AGENT,
        'sessions_active': get_session_count(),
        'session_ttl_sec': _SESSION_TTL,
        'max_sessions': _MAX_SESSIONS,
    }


logger.info(f"🌐 Browser Agent loaded (enabled={ENABLE_BROWSER_AGENT})")
