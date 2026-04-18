"""
🧠 Memory long-term routes — read/write + manual trigger (v10.45)
=============================================================================
Endpoints:
    GET  /api/memory/long-term           — own long-term summary
    POST /api/memory/summarize-now       — trigger summarization for me
    POST /api/admin/memory/summarize/<uid> — admin-forced summarize
    GET  /api/proactive/recall            — preview today's recall line
    POST /api/admin/proactive/send/<uid>  — admin send proactive now
"""

import logging
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

memory_lt_bp = Blueprint("memory_long_term", __name__)


def _options_ok():
    return ("", 204)


def _uid():
    au = getattr(g, "auth_user", None) or {}
    return str(au.get("id") or au.get("user_id") or "")


def _is_admin():
    au = getattr(g, "auth_user", None) or {}
    role = (au.get("role") or au.get("user", {}).get("role") or "").lower()
    if role in ("admin", "administrator"):
        return True
    import os
    secret_env = os.environ.get("ADMIN_SECRET", "")
    header_secret = request.headers.get("X-Admin-Secret", "")
    return bool(secret_env and header_secret and secret_env == header_secret)


@memory_lt_bp.route("/api/memory/long-term", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def get_long_term():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(uid) or {}
        ltc = profile.get("long_term_context")
        if isinstance(ltc, str):
            ltc = {"text": ltc}
        return jsonify({
            "success": True,
            "long_term_context": ltc or None,
            "has_summary": bool(ltc and (ltc.get("text") if isinstance(ltc, dict) else ltc)),
        })
    except Exception as e:
        logger.error(f"get_long_term: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


@memory_lt_bp.route("/api/memory/summarize-now", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=3, window_seconds=3600, key_func="user")
@require_auth
def summarize_now():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        from memory_summarization import summarize_user_memory
        result = summarize_user_memory(uid, force=True)
        return jsonify(result)
    except Exception as e:
        logger.error(f"summarize_now: {e}")
        return jsonify({"success": False, "error": "Chyba při shrnutí."}), 500


@memory_lt_bp.route("/api/admin/memory/summarize/<target_uid>",
                    methods=["POST", "OPTIONS"])
@require_auth
def admin_summarize(target_uid):
    if request.method == "OPTIONS":
        return _options_ok()
    if not _is_admin():
        return jsonify({"success": False, "error": "Admin required"}), 403
    try:
        from memory_summarization import summarize_user_memory
        result = summarize_user_memory(str(target_uid), force=True)
        return jsonify(result)
    except Exception as e:
        logger.error(f"admin_summarize: {e}")
        return jsonify({"success": False, "error": "Chyba"}), 500


@memory_lt_bp.route("/api/proactive/recall", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=10, window_seconds=60, key_func="user")
@require_auth
def get_recall():
    """Preview what today's proactive opening line would be."""
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        from proactive_engine import generate_proactive_prompt
        result = generate_proactive_prompt(uid)
        return jsonify({"success": True, "recall": result})
    except Exception as e:
        logger.error(f"get_recall: {e}")
        return jsonify({"success": False, "error": "Chyba"}), 500


@memory_lt_bp.route("/api/admin/proactive/send/<target_uid>",
                    methods=["POST", "OPTIONS"])
@require_auth
def admin_send_proactive(target_uid):
    """Admin: trigger a proactive message to a specific user right now."""
    if request.method == "OPTIONS":
        return _options_ok()
    if not _is_admin():
        return jsonify({"success": False, "error": "Admin required"}), 403
    try:
        from proactive_engine import send_proactive_message
        result = send_proactive_message(str(target_uid))
        return jsonify({"success": bool(result), "result": result})
    except Exception as e:
        logger.error(f"admin_send_proactive: {e}")
        return jsonify({"success": False, "error": "Chyba"}), 500


logger.info("🧠 Memory long-term + proactive routes loaded")
