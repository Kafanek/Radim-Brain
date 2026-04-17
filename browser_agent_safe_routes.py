"""
🛡️ Safe Web Agent — HTTP Routes (/api/safe-web/*)
=============================================================================
Senior-facing Flask blueprint with @require_auth + @rate_limit on every
endpoint. Returns structured safe responses with czech senior-friendly
messages and reasoning transparency.
"""

import logging

from flask import Blueprint, g, request, jsonify
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

safe_web_bp = Blueprint("safe_web", __name__)


def _current_user_and_role():
    """Extract (user_id, role) from g.auth_user. Fallback to anonymous."""
    au = getattr(g, "auth_user", None) or {}
    user_id = au.get("user_id") or au.get("id") or au.get("email")
    role = au.get("role", "senior_user")  # default when authenticated
    # Map WordPress / RADIM roles to our safe-web roles
    role_map = {
        "administrator": "admin",
        "admin": "admin",
        "spc_supervisor": "admin",
        "coordinator": "caregiver",
        "teacher": "caregiver",
        "caregiver": "caregiver",
        "family": "caregiver",
        "premium": "senior_user",
        "senior": "senior_user",
        "senior_user": "senior_user",
        "free": "senior_user",
        "subscriber": "senior_user",
    }
    return (user_id, role_map.get((role or "").lower(), "senior_user"))


def _options_ok():
    return jsonify({"ok": True}), 200


def _http_status_for(result: dict) -> int:
    """Map error_code to appropriate HTTP status."""
    if result.get("success"):
        return 200
    code = result.get("error_code", "")
    if code == "DISABLED":
        return 503
    if code == "NO_CONSENT":
        return 403
    if code == "ROLE_DENIED":
        return 403
    if code == "SESSION_NOT_FOUND":
        return 404
    if code.startswith("BLOCKED") or code == "SENSITIVE_PAGE":
        return 403
    if code == "TIMEOUT":
        return 504
    if code in ("ACTION_LIMIT", "DEPTH_LIMIT"):
        return 429
    if code == "INVALID_INDEX" or code == "INVALID_URL" or code == "INVALID_QUERY":
        return 400
    return 400


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@safe_web_bp.route("/api/safe-web/open", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=5, window_seconds=60, key_func="user")
@optional_auth
def route_open():
    """Open a page in safe mode. Requires auth for senior; anonymous denied."""
    if request.method == "OPTIONS":
        return _options_ok()

    try:
        from browser_agent_safe import open_page
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE",
                        "message": "Safe Web Agent není dostupný."}), 503

    user_id, role = _current_user_and_role()
    # Public/anonymous blocked explicitly
    if not user_id:
        return jsonify({
            "success": False,
            "error_code": "AUTH_REQUIRED",
            "message": "Pro bezpečné procházení webu se prosím přihlaste.",
            "reasoning": {"why_blocked": "No authenticated user in request.",
                          "recommended_next_step": "Přihlaste se v aplikaci."},
        }), 401

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    mode = (data.get("mode") or "read_only").strip()
    user_consent_confirmed = bool(data.get("user_consent_confirmed", False))

    if not url:
        return jsonify({"success": False, "error_code": "INVALID_URL",
                        "message": "Adresa URL je povinná."}), 400

    result = open_page(
        url=url, mode=mode, user_id=str(user_id),
        role=role, user_consent_confirmed=user_consent_confirmed,
    )
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/read/<session_id>", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@optional_auth
def route_read(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import read_current_page
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, _ = _current_user_and_role()
    if not user_id:
        return jsonify({"success": False, "error_code": "AUTH_REQUIRED",
                        "message": "Přihlaste se prosím."}), 401
    result = read_current_page(session_id, user_id=str(user_id))
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/find/<session_id>", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@optional_auth
def route_find(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import find_on_page
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, _ = _current_user_and_role()
    if not user_id:
        return jsonify({"success": False, "error_code": "AUTH_REQUIRED",
                        "message": "Přihlaste se prosím."}), 401
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error_code": "INVALID_QUERY",
                        "message": "Zadejte prosím, co hledáte."}), 400
    result = find_on_page(session_id, query, user_id=str(user_id))
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/links/<session_id>", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@optional_auth
def route_links(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import list_links
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, _ = _current_user_and_role()
    if not user_id:
        return jsonify({"success": False, "error_code": "AUTH_REQUIRED",
                        "message": "Přihlaste se prosím."}), 401
    safe_only = request.args.get("safe_only", "false").lower() == "true"
    result = list_links(session_id, user_id=str(user_id), safe_only=safe_only)
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/follow/<session_id>", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=15, window_seconds=60, key_func="user")
@optional_auth
def route_follow(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import safe_follow_link
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, _ = _current_user_and_role()
    if not user_id:
        return jsonify({"success": False, "error_code": "AUTH_REQUIRED",
                        "message": "Přihlaste se prosím."}), 401
    data = request.get_json(silent=True) or {}
    link_index = data.get("index")
    if link_index is None:
        return jsonify({"success": False, "error_code": "INVALID_INDEX",
                        "message": "Pole index je povinné."}), 400
    result = safe_follow_link(session_id, link_index, user_id=str(user_id))
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/audit/<session_id>", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@optional_auth
def route_audit(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import get_session_audit
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, role = _current_user_and_role()
    if not user_id:
        return jsonify({"success": False, "error_code": "AUTH_REQUIRED"}), 401
    result = get_session_audit(session_id, user_id=str(user_id), role=role)
    return jsonify(result), _http_status_for(result)


@safe_web_bp.route("/api/safe-web/close/<session_id>", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@optional_auth
def route_close(session_id):
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import close_session
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    user_id, _ = _current_user_and_role()
    result = close_session(session_id, user_id=str(user_id) if user_id else None)
    return jsonify(result), 200


@safe_web_bp.route("/api/safe-web/modes", methods=["GET", "OPTIONS"])
def route_modes():
    """Public: list available modes with descriptions (transparency)."""
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import list_modes
    except ImportError:
        return jsonify({"success": False, "error_code": "NOT_AVAILABLE"}), 503
    return jsonify(list_modes()), 200


@safe_web_bp.route("/api/safe-web/stats", methods=["GET", "OPTIONS"])
def route_stats():
    """Public: feature flag + session count."""
    if request.method == "OPTIONS":
        return _options_ok()
    try:
        from browser_agent_safe import stats
    except ImportError:
        return jsonify({"success": False, "enabled": False,
                        "error_code": "NOT_AVAILABLE"}), 200
    return jsonify(stats()), 200


logger.info("🛡️ Safe Web Agent routes registered: /api/safe-web/*")
