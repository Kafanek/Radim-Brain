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


@notification_bp.route("/api/notifications/preferences", methods=["GET", "PUT", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def notification_prefs():
    """Sprint C: per-user notification preferences (DND + type mutes).

    Body on PUT: { muted_types: [string], dnd_until: ISO8601|null }
    SOS and crisis severity ignore these (safety-critical).
    """
    if request.method == "OPTIONS":
        return _options_ok()

    from database import db_context, is_postgres
    import json as _json

    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    # Ensure table exists
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "  user_id TEXT PRIMARY KEY,"
                    "  muted_types JSONB DEFAULT '[]',"
                    "  dnd_until TIMESTAMP,"
                    "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            else:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "  user_id TEXT PRIMARY KEY,"
                    "  muted_types TEXT DEFAULT '[]',"
                    "  dnd_until TIMESTAMP,"
                    "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
    except Exception as e:
        logger.debug(f"notif prefs schema: {e}")

    if request.method == "GET":
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT muted_types, dnd_until FROM user_notification_prefs WHERE user_id = ?",
                    (uid,)
                ).fetchone()
            if not row:
                return jsonify({"success": True, "muted_types": [], "dnd_until": None})
            muted_raw = row[0] if isinstance(row, (list, tuple)) else row.get("muted_types")
            dnd = row[1] if isinstance(row, (list, tuple)) else row.get("dnd_until")
            try:
                muted = _json.loads(muted_raw) if isinstance(muted_raw, str) else (muted_raw or [])
            except Exception:
                muted = []
            return jsonify({
                "success": True,
                "muted_types": muted,
                "dnd_until": str(dnd) if dnd else None,
            })
        except Exception as e:
            logger.error(f"prefs GET error: {e}")
            return jsonify({"success": True, "muted_types": [], "dnd_until": None})

    # PUT
    data = request.get_json(silent=True) or {}
    muted = data.get("muted_types") or []
    if not isinstance(muted, list):
        return jsonify({"success": False, "error": "muted_types must be array"}), 400
    # Sanitize: only strings, max 20 entries, each ≤64 chars
    muted = [str(t)[:64] for t in muted if isinstance(t, str)][:20]
    # Filter out SOS/crisis types — they can never be muted server-side
    muted = [t for t in muted if t not in ("sos", "crisis_alert")]

    dnd_until = data.get("dnd_until")
    if dnd_until:
        try:
            # Validate ISO8601
            from datetime import datetime as _dt
            _dt.fromisoformat(dnd_until.replace("Z", "+00:00"))
        except Exception:
            return jsonify({"success": False, "error": "invalid dnd_until format"}), 400

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO user_notification_prefs (user_id, muted_types, dnd_until, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "muted_types = EXCLUDED.muted_types, "
                    "dnd_until = EXCLUDED.dnd_until, "
                    "updated_at = CURRENT_TIMESTAMP",
                    (uid, _json.dumps(muted), dnd_until)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO user_notification_prefs "
                    "(user_id, muted_types, dnd_until, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (uid, _json.dumps(muted), dnd_until)
                )
        return jsonify({
            "success": True,
            "muted_types": muted,
            "dnd_until": dnd_until,
        })
    except Exception as e:
        logger.error(f"prefs PUT error: {e}")
        return jsonify({"success": False, "error": str(e)[:100]}), 500


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

    # 0. Create sos_event for escalation tracking
    sos_event_id = None
    try:
        from database import db_context, db_insert
        with db_context(commit=True) as db:
            sos_event_id = db_insert(
                db, "sos_events",
                ["senior_id", "source", "message", "escalation_stage"],
                [senior_id, source, body[:240], 0],
            )
    except Exception as e:
        logger.debug(f"sos_events insert: {e}")

    # ISO 27001 A.16.1 — SOS je security incident, povinný audit
    try:
        from audit_log import audit, A
        audit(A.SOS_TRIGGERED, severity='critical',
              resource_type='sos_event', resource_id=sos_event_id,
              senior_id=senior_id,
              metadata={'source': source, 'has_custom_message': bool(custom_msg)})
    except Exception:
        pass

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
            "sos_event_id": sos_event_id,
            "actionable": True,  # marks that Ack button should appear
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
        "sos_event_id": sos_event_id,
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


# ═══════════════════════════════════════════════════════════════════
# SOS ESCALATION — Ack + Resolve + scheduler engine (v10.40)
# ═══════════════════════════════════════════════════════════════════

@notification_bp.route("/api/sos/<int:sos_id>/ack", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def sos_ack(sos_id):
    """Family member taps 'Už řeším' — stops escalation.

    Senior may also ack their own event (false alarm).
    """
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        from database import db_context, is_postgres
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT senior_id, ack_by_user_id, resolved_at "
                "FROM sos_events WHERE id = ?",
                (sos_id,)
            ).fetchone()
            if not row:
                return jsonify({"success": False, "error": "SOS událost nenalezena."}), 404
            senior_id, current_ack, resolved_at = row[0], row[1], row[2]
            if resolved_at:
                return jsonify({"success": True, "already_resolved": True,
                                "message": "Událost už je uzavřená."})
            if current_ack:
                return jsonify({"success": True, "already_ack": True,
                                "ack_by_user_id": current_ack,
                                "message": "Už řeší někdo jiný z rodiny."})

            # Permission: senior themselves, or anyone in their confirmed family links
            authorized = (str(uid) == str(senior_id))
            if not authorized:
                link = db.execute(
                    "SELECT 1 FROM senior_family_links "
                    "WHERE senior_id = ? AND family_user_id = ? "
                    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                    (str(senior_id), str(uid))
                ).fetchone()
                authorized = bool(link)
            if not authorized:
                return jsonify({"success": False, "error": "Nemáte oprávnění k této události."}), 403

            if is_postgres():
                db.execute(
                    "UPDATE sos_events SET ack_by_user_id = ?, ack_at = NOW() "
                    "WHERE id = ?", (str(uid), sos_id)
                )
            else:
                db.execute(
                    "UPDATE sos_events SET ack_by_user_id = ?, ack_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?", (str(uid), sos_id)
                )

            # Notify everyone else in the family that someone is on it
            try:
                acker_name = (g.auth_user.get("name") or g.auth_user.get("email") or "Někdo z rodiny")
                notify_senior_family(
                    senior_id=senior_id, type="sos",
                    title="✅ SOS — už je u toho",
                    body=f"{acker_name} řeší situaci. Eskalace se zastavila.",
                    severity="info",
                    data={"sos_event_id": sos_id, "ack_update": True,
                          "ack_by": str(uid)},
                    include_caregiver=True,
                )
            except Exception:
                pass

            # Also notify the senior themselves
            try:
                from notification_helpers import notify
                if str(senior_id) != str(uid):
                    notify(to_user_id=senior_id, type="sos",
                           severity="info",
                           title="🆘 Rodina reaguje",
                           body=f"{acker_name} už je na cestě nebo vás hned zavolá.",
                           from_user_id=uid,
                           data={"sos_event_id": sos_id, "ack_update": True})
            except Exception:
                pass

        # ISO 27001 A.16.1 — incident handling audit
        try:
            from audit_log import audit, A
            audit(A.SOS_ACK, severity='info',
                  resource_type='sos_event', resource_id=sos_id,
                  senior_id=str(senior_id),
                  metadata={'acked_by_self': str(uid) == str(senior_id)})
        except Exception:
            pass

        return jsonify({
            "success": True, "sos_event_id": sos_id,
            "ack_by_user_id": str(uid),
            "message": "Označeno jako 'řeším'. Eskalace zastavena.",
        })
    except Exception as e:
        logger.error(f"sos_ack: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


@notification_bp.route("/api/sos/<int:sos_id>/resolve", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def sos_resolve(sos_id):
    """Mark SOS as fully resolved (false alarm or situation handled)."""
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        from database import db_context, is_postgres
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT senior_id, resolved_at FROM sos_events WHERE id = ?",
                (sos_id,)
            ).fetchone()
            if not row:
                return jsonify({"success": False, "error": "Nenalezeno."}), 404
            senior_id, resolved_at = row[0], row[1]
            if resolved_at:
                return jsonify({"success": True, "already": True})

            # Authorization same as ack
            authorized = (str(uid) == str(senior_id))
            if not authorized:
                link = db.execute(
                    "SELECT 1 FROM senior_family_links "
                    "WHERE senior_id = ? AND family_user_id = ? "
                    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                    (str(senior_id), str(uid))
                ).fetchone()
                authorized = bool(link)
            if not authorized:
                return jsonify({"success": False, "error": "Nemáte oprávnění."}), 403

            if is_postgres():
                db.execute(
                    "UPDATE sos_events SET resolved_at = NOW(), "
                    "ack_by_user_id = COALESCE(ack_by_user_id, ?) "
                    "WHERE id = ?", (str(uid), sos_id)
                )
            else:
                db.execute(
                    "UPDATE sos_events SET resolved_at = CURRENT_TIMESTAMP, "
                    "ack_by_user_id = COALESCE(ack_by_user_id, ?) "
                    "WHERE id = ?", (str(uid), sos_id)
                )

        # ISO 27001 A.16.1 — incident closure audit
        try:
            from audit_log import audit, A
            audit(A.SOS_RESOLVED, severity='info',
                  resource_type='sos_event', resource_id=sos_id,
                  senior_id=str(senior_id),
                  metadata={'resolved_by_self': str(uid) == str(senior_id)})
        except Exception:
            pass

        return jsonify({"success": True, "sos_event_id": sos_id,
                        "message": "Událost uzavřena."})
    except Exception as e:
        logger.error(f"sos_resolve: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


@notification_bp.route("/api/sos/active", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def sos_active():
    """Return active (unresolved) SOS events for the current user.

    Senior: their own unresolved events.
    Family: unresolved events of their linked seniors.
    """
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute(
                "SELECT id, senior_id, source, message, "
                "       ack_by_user_id, ack_at, escalation_stage, created_at "
                "FROM sos_events "
                "WHERE resolved_at IS NULL "
                "AND (senior_id = ? "
                "  OR senior_id IN (SELECT senior_id FROM senior_family_links "
                "                   WHERE family_user_id = ? "
                "                   AND confirmed_at IS NOT NULL "
                "                   AND revoked_at IS NULL)) "
                "ORDER BY id DESC LIMIT 50",
                (str(uid), str(uid))
            ).fetchall() or []
        items = [{
            "id": r[0], "senior_id": r[1], "source": r[2],
            "message": r[3], "ack_by_user_id": r[4],
            "ack_at": str(r[5]) if r[5] else None,
            "escalation_stage": r[6],
            "created_at": str(r[7]) if r[7] else None,
        } for r in rows]
        return jsonify({"success": True, "items": items, "count": len(items)})
    except Exception as e:
        logger.error(f"sos_active: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


# ═══════════════════════════════════════════════════════════════════
# FESTIVE GREETING — v10.40
# ═══════════════════════════════════════════════════════════════════

@notification_bp.route("/api/festive-greeting", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def festive_greeting_get():
    """Build today's festive greeting for the authenticated senior."""
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        from festive_greeting import build_greeting, load_user_template
        greeting = build_greeting(user_id=uid)
        template = load_user_template(uid)
        return jsonify({
            "success": True,
            "greeting": greeting,
            "template": template,
        })
    except Exception as e:
        logger.error(f"festive_greeting_get: {e}")
        return jsonify({"success": False, "error": "Chyba při sestavení pozdravu."}), 500


@notification_bp.route("/api/festive-greeting/template", methods=["PUT", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@require_auth
def festive_greeting_template():
    """Save per-senior greeting template (salutation, addressee, suffix, flags)."""
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    allowed = ("salutation", "addressee", "suffix", "use_nameday", "use_holiday")
    template = {k: data[k] for k in allowed if k in data}
    if not template:
        return jsonify({"success": False, "error": "Žádná pole nejsou zadaná."}), 400

    try:
        from festive_greeting import save_user_template, build_greeting
        ok = save_user_template(uid, template)
        if not ok:
            return jsonify({"success": False, "error": "Uložení selhalo."}), 500
        preview = build_greeting(user_id=uid)
        return jsonify({
            "success": True,
            "message": "Pozdrav uložen.",
            "preview": preview,
        })
    except Exception as e:
        logger.error(f"festive_greeting_template: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


logger.info("🔔 Notification + SOS + Festive routes loaded: /api/notifications/*, /api/sos/trigger, /api/sos/<id>/ack, /api/sos/<id>/resolve, /api/sos/active, /api/festive-greeting")
