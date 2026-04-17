"""
🔔 Notification routes — /api/notifications/* + /api/sos/* (v10.37)
=============================================================================
Endpoints:
    GET  /api/notifications/list            list own notifications
    GET  /api/notifications/unread-count
    POST /api/notifications/<id>/read
    POST /api/notifications/read-all

    POST /api/sos/trigger                   senior-auth, fires crisis flow +
                                             notifies linked family
"""

import logging
import os

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from rate_limiter import rate_limit
from notification_helpers import (
    list_notifications, unread_count, mark_read, mark_all_read,
    notify_senior_family,
)

logger = logging.getLogger(__name__)

notification_bp = Blueprint("notifications", __name__)


def _options_ok():
    return ("", 204)


def _current_uid():
    au = getattr(g, "auth_user", None) or {}
    return str(au.get("id") or au.get("user_id") or "")


# ═══════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════

@notification_bp.route("/api/notifications/list", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def list_route():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    unread_only = request.args.get("unread", "false").lower() == "true"
    limit = min(int(request.args.get("limit", 50)), 200)
    before_id = request.args.get("before_id")
    items = list_notifications(uid, limit=limit, unread_only=unread_only, before_id=before_id)
    return jsonify({"success": True, "items": items, "count": len(items),
                    "unread_count": unread_count(uid)})


@notification_bp.route("/api/notifications/unread-count", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=120, window_seconds=60, key_func="user")
@require_auth
def unread_count_route():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    return jsonify({"success": True, "count": unread_count(uid)})


@notification_bp.route("/api/notifications/<int:nid>/read", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=200, window_seconds=60, key_func="user")
@require_auth
def read_route(nid):
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    ok = mark_read(nid, uid)
    return jsonify({"success": True, "updated": ok, "unread_count": unread_count(uid)})


@notification_bp.route("/api/notifications/read-all", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@require_auth
def read_all_route():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    n = mark_all_read(uid)
    return jsonify({"success": True, "updated": n, "unread_count": 0})


# ═══════════════════════════════════════════════════════════════════
# SOS
# ═══════════════════════════════════════════════════════════════════

@notification_bp.route("/api/sos/trigger", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=5, window_seconds=60, key_func="user")
@require_auth
def sos_trigger():
    """Senior presses SOS button → notify all linked family + optional crisis flow.

    Body: {
        message: optional free-text "Potřebuji pomoc",
        trigger_crisis: bool (default true) — whether to also run HA mock + proactive call,
        source: "button" | "voice" | "fall_sensor"
    }
    """
    if request.method == "OPTIONS":
        return _options_ok()

    data = request.get_json(silent=True) or {}
    senior_id = _current_uid()
    if not senior_id:
        return jsonify({"success": False, "error": "Auth required"}), 401

    custom_msg = (data.get("message") or "").strip()[:240]
    source = (data.get("source") or "button").strip()
    trigger_crisis = data.get("trigger_crisis", True)

    senior_name = (g.auth_user.get("name") or g.auth_user.get("display_name")
                   or g.auth_user.get("email") or "Senior")

    title = "🆘 SOS — potřebuje pomoc!"
    body = custom_msg or f"{senior_name} stiskl/a tísňové tlačítko. Zavolejte prosím."

    # 1. Notify family accounts (in-app — replaces Twilio SMS)
    notif_ids = notify_senior_family(
        senior_id=senior_id,
        type="sos",
        title=title,
        body=body,
        severity="crisis",
        data={
            "source": source,
            "senior_name": senior_name,
            "custom_message": custom_msg,
        },
        include_caregiver=True,
    )

    # 2. Log agent observation (audit trail)
    try:
        from database import db_context, db_insert
        import json as _json
        with db_context(commit=True) as db:
            db_insert(db, "agent_observations",
                      ["user_id", "observation_type", "severity", "message",
                       "action_taken", "details"],
                      [senior_id, "sos_triggered", "crisis",
                       f"SOS tlačítko stisknuto ({source})",
                       "notify_family",
                       _json.dumps({"source": source, "recipients": len(notif_ids),
                                    "custom_message": custom_msg})])
    except Exception as e:
        logger.debug(f"SOS audit log: {e}")

    # 3. Optional: fire crisis flow (HA mock + proactive call)
    crisis_result = None
    if trigger_crisis:
        try:
            # Reuse admin_crisis_demo logic without admin check
            from agent_loop import _ha_crisis_actions
            obs = {
                "user_id": senior_id, "observation_type": "sos_triggered",
                "severity": "crisis", "message": body,
            }
            ha_result = None
            try:
                ha_result = _ha_crisis_actions(senior_id, obs)
            except Exception as e:
                logger.debug(f"HA crisis actions (live): {e}")

            crisis_result = {
                "ha_actions_fired": bool(ha_result),
                "ha_result": ha_result,
            }
        except Exception as e:
            logger.debug(f"SOS crisis flow: {e}")

    return jsonify({
        "success": True,
        "senior_id": senior_id,
        "source": source,
        "notified_count": len(notif_ids),
        "notification_ids": notif_ids,
        "crisis": crisis_result,
        "message": (
            f"Upozornění odesláno {len(notif_ids)} člen"
            + ("u rodiny." if len(notif_ids) == 1 else "ům rodiny.")
            if notif_ids
            else "Pozor: nemáte zatím propojenou žádnou rodinu. "
                 "V nastavení pozvěte blízké osoby."
        ),
    })


logger.info("🔔 Notification + SOS routes loaded: /api/notifications/*, /api/sos/trigger")
