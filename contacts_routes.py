"""
📞 Contacts routes — senior phone book with optional FamilyLink pairing (v10.38)
=============================================================================
Endpoints:
    GET    /api/contacts                list my contacts
    POST   /api/contacts                create contact
    GET    /api/contacts/<id>           read one
    PATCH  /api/contacts/<id>           update (name/phone/priority/flags)
    DELETE /api/contacts/<id>           remove
    POST   /api/contacts/<id>/call      intent to call (audit + return tel link)
    POST   /api/contacts/<id>/sms       send SMS via Twilio or FAKE_SMS_MODE
    POST   /api/contacts/<id>/message   in-app notification (linked only)

Separation from family_link_routes: Contacts are a phone book (with or
without Radimcare account). FamilyLinks are Radimcare account pairings
receiving in-app notifications. A Contact may optionally point at one
FamilyLink (auto-paired by email on invite accept).
"""

import logging
import os
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, db_insert, is_postgres
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

contacts_bp = Blueprint("contacts", __name__)


def _options_ok():
    return ("", 204)


def _current_senior_id():
    au = getattr(g, "auth_user", None) or {}
    return str(au.get("id") or au.get("user_id") or "")


def _relation_label(relation):
    return {
        "daughter": "dcera", "son": "syn", "spouse": "manžel/manželka",
        "parent": "rodič", "sibling": "sourozenec", "caregiver": "pečovatel",
        "doctor": "lékař", "neighbor": "soused", "friend": "přítel",
        "emergency": "tísňová linka", "other": "blízká osoba",
    }.get((relation or "").lower(), relation or "")


def _normalize_phone(phone):
    if not phone:
        return None
    p = "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")
    return p or None


def _row_to_dict(row):
    (
        cid, senior_id, name, relation, phone, email, avatar_url, notes,
        linked_id, sos_priority, is_primary, can_call, can_sms,
        is_emergency, created_at, updated_at,
    ) = row
    return {
        "id": cid, "name": name, "relation": relation,
        "relation_label": _relation_label(relation),
        "phone": phone, "email": email,
        "avatar_url": avatar_url, "notes": notes,
        "linked_family_link_id": linked_id,
        "has_radimcare_account": bool(linked_id),
        "sos_priority": sos_priority,
        "is_primary": bool(is_primary),
        "can_call": bool(can_call),
        "can_sms": bool(can_sms),
        "is_emergency": bool(is_emergency),
        "created_at": str(created_at) if created_at else None,
        "updated_at": str(updated_at) if updated_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# CRUD
# ═══════════════════════════════════════════════════════════════════

@contacts_bp.route("/api/contacts", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def list_contacts():
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, senior_id, name, relation, phone, email, avatar_url, "
                "       notes, linked_family_link_id, sos_priority, is_primary, "
                "       can_call, can_sms, is_emergency, created_at, updated_at "
                "FROM contacts WHERE senior_id = ? "
                "ORDER BY is_primary DESC, COALESCE(sos_priority, 999), name",
                (sid,)
            ).fetchall() or []
        items = [_row_to_dict(r) for r in rows]
        return jsonify({"success": True, "items": items, "count": len(items)})
    except Exception as e:
        logger.error(f"list_contacts: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


@contacts_bp.route("/api/contacts", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def create_contact():
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Jméno je povinné."}), 400

    phone = _normalize_phone(data.get("phone"))
    email = (data.get("email") or "").strip().lower() or None
    relation = (data.get("relation") or "").strip().lower() or None
    notes = (data.get("notes") or "").strip() or None
    avatar_url = (data.get("avatar_url") or "").strip() or None
    sos_priority = data.get("sos_priority")
    if sos_priority is not None:
        try:
            sos_priority = int(sos_priority)
            if sos_priority < 1 or sos_priority > 9:
                sos_priority = None
        except (TypeError, ValueError):
            sos_priority = None
    is_primary = bool(data.get("is_primary", False))
    can_call = bool(data.get("can_call", True))
    can_sms = bool(data.get("can_sms", True))
    is_emergency = bool(data.get("is_emergency", False))

    if not phone and not email:
        return jsonify({"success": False, "error": "Vyplňte prosím telefon nebo email."}), 400

    try:
        with db_context(commit=True) as db:
            # Auto-link to existing FamilyLink by email (if exists)
            linked_id = None
            if email:
                row = db.execute(
                    "SELECT id FROM senior_family_links "
                    "WHERE senior_id = ? AND family_email = ? "
                    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                    (sid, email)
                ).fetchone()
                if row:
                    linked_id = row[0]

            # v10.41: PG needs real booleans — SQLite treats bool as int automatically
            cid = db_insert(
                db, "contacts",
                ["senior_id", "name", "relation", "phone", "email",
                 "avatar_url", "notes", "linked_family_link_id",
                 "sos_priority", "is_primary", "can_call", "can_sms",
                 "is_emergency"],
                [sid, name, relation, phone, email, avatar_url, notes,
                 linked_id, sos_priority,
                 bool(is_primary), bool(can_call),
                 bool(can_sms), bool(is_emergency)],
            )
    except Exception as e:
        logger.error(f"create_contact: {e}")
        return jsonify({"success": False, "error": "Nepodařilo se uložit kontakt."}), 500

    return jsonify({
        "success": True, "id": cid, "linked": bool(linked_id),
        "message": ("Kontakt uložen a automaticky propojen s Radimcare účtem."
                    if linked_id else "Kontakt uložen."),
    })


@contacts_bp.route("/api/contacts/<int:cid>", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def get_contact(cid):
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id, senior_id, name, relation, phone, email, avatar_url, "
                "       notes, linked_family_link_id, sos_priority, is_primary, "
                "       can_call, can_sms, is_emergency, created_at, updated_at "
                "FROM contacts WHERE id = ? AND senior_id = ?",
                (cid, sid)
            ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
        return jsonify({"success": True, "contact": _row_to_dict(row)})
    except Exception as e:
        logger.error(f"get_contact: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500


@contacts_bp.route("/api/contacts/<int:cid>", methods=["PATCH", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def update_contact(cid):
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    # Allowed fields to patch
    updates = []
    params = []
    ALLOWED = {
        "name": str, "relation": str, "phone": str, "email": str,
        "avatar_url": str, "notes": str, "sos_priority": int,
        "is_primary": bool, "can_call": bool, "can_sms": bool,
        "is_emergency": bool,
    }
    for k, vtype in ALLOWED.items():
        if k not in data:
            continue
        v = data[k]
        if v is None:
            updates.append(f"{k} = ?"); params.append(None); continue
        if vtype is str:
            v = str(v).strip() or None
            if k == "phone": v = _normalize_phone(v)
            if k == "email": v = v.lower() if v else None
        elif vtype is int:
            try:
                v = int(v)
                if k == "sos_priority" and (v < 1 or v > 9):
                    v = None
            except (TypeError, ValueError):
                v = None
        elif vtype is bool:
            v = bool(v)  # v10.41: real boolean for PG (SQLite accepts bool as int)
        updates.append(f"{k} = ?")
        params.append(v)

    if not updates:
        return jsonify({"success": False, "error": "Žádné změny."}), 400

    if is_postgres():
        updates.append("updated_at = NOW()")
    else:
        updates.append("updated_at = CURRENT_TIMESTAMP")
    params.extend([cid, sid])

    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                f"UPDATE contacts SET {', '.join(updates)} WHERE id = ? AND senior_id = ?",
                tuple(params)
            )
            if not cur.rowcount:
                return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
    except Exception as e:
        logger.error(f"update_contact: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    return jsonify({"success": True, "message": "Změny uloženy."})


@contacts_bp.route("/api/contacts/<int:cid>", methods=["DELETE", "OPTIONS"])
@require_auth
def delete_contact(cid):
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "DELETE FROM contacts WHERE id = ? AND senior_id = ?",
                (cid, sid)
            )
            if not cur.rowcount:
                return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
    except Exception as e:
        logger.error(f"delete_contact: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500
    return jsonify({"success": True, "message": "Kontakt odebrán."})


# ═══════════════════════════════════════════════════════════════════
# ACTIONS — call / sms / message
# ═══════════════════════════════════════════════════════════════════

@contacts_bp.route("/api/contacts/<int:cid>/call", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="user")
@require_auth
def contact_call(cid):
    """Log call intent + return tel: URI. Frontend opens the dialer.

    Does NOT initiate outbound Twilio call (that's for SOS escalation).
    Senior taps call button → device dials directly.
    """
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT name, phone, can_call FROM contacts WHERE id = ? AND senior_id = ?",
                (cid, sid)
            ).fetchone()
    except Exception:
        return jsonify({"success": False, "error": "DB error"}), 500

    if not row:
        return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
    name, phone, can_call = row
    if not phone or not can_call:
        return jsonify({"success": False, "error": "Tento kontakt nemá telefon."}), 400

    # Audit
    try:
        from database import db_insert
        import json as _json
        with db_context(commit=True) as db:
            db_insert(db, "agent_observations",
                      ["user_id", "observation_type", "severity", "message",
                       "action_taken", "details"],
                      [sid, "contact_call", "info",
                       f"Hovor na {name}", "dial",
                       _json.dumps({"contact_id": cid, "phone": phone[-4:]})])
    except Exception:
        pass

    return jsonify({
        "success": True, "name": name,
        "tel_uri": f"tel:{phone}",
        "phone": phone,
    })


@contacts_bp.route("/api/contacts/<int:cid>/sms", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=10, window_seconds=60, key_func="user")
@require_auth
def contact_sms(cid):
    """Send SMS via Twilio (FAKE_SMS_MODE aware)."""
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"success": False, "error": "Text zprávy je povinný."}), 400
    if len(body) > 480:
        return jsonify({"success": False, "error": "Zpráva je příliš dlouhá."}), 400

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT name, phone, can_sms FROM contacts WHERE id = ? AND senior_id = ?",
                (cid, sid)
            ).fetchone()
    except Exception:
        return jsonify({"success": False, "error": "DB error"}), 500

    if not row:
        return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
    name, phone, can_sms = row
    if not phone or not can_sms:
        return jsonify({"success": False, "error": "Tento kontakt SMS nepřijímá."}), 400

    # FAKE_SMS_MODE or real Twilio
    fake_mode = os.environ.get("FAKE_SMS_MODE", "false").lower() == "true"
    result = {"mode": "fake" if fake_mode else "twilio"}

    if fake_mode:
        result.update({"sent": True, "sid": "fake_" + str(cid), "fake": True})
        logger.info(f"📱 FAKE SMS to {name} ({phone[-4:]}): {body[:60]}")
    else:
        try:
            from twilio.rest import Client
            account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
            auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
            from_num = os.environ.get("TWILIO_PHONE_NUMBER")
            if not (account_sid and auth_token and from_num):
                return jsonify({"success": False, "error": "Twilio není nakonfigurován."}), 503
            client = Client(account_sid, auth_token)
            msg = client.messages.create(body=body, from_=from_num, to=phone)
            result.update({"sent": True, "sid": msg.sid})
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return jsonify({"success": False, "error": "SMS se nepodařilo odeslat.",
                            "detail": str(e)[:120]}), 502

    # Audit
    try:
        from database import db_insert
        import json as _json
        with db_context(commit=True) as db:
            db_insert(db, "agent_observations",
                      ["user_id", "observation_type", "severity", "message",
                       "action_taken", "details"],
                      [sid, "contact_sms", "info",
                       f"SMS odeslána na {name}",
                       "sms_sent" if not fake_mode else "sms_fake",
                       _json.dumps({"contact_id": cid, "mode": result["mode"],
                                    "body_preview": body[:80]})])
    except Exception:
        pass

    return jsonify({
        "success": True, "name": name,
        "message": ("SMS odeslána." if not fake_mode
                    else "SMS zaznamenána (demo režim)."),
        **result,
    })


@contacts_bp.route("/api/contacts/<int:cid>/message", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def contact_message(cid):
    """Send in-app notification to a linked contact (must have linked_family_link_id)."""
    if request.method == "OPTIONS":
        return _options_ok()
    sid = _current_senior_id()
    if not sid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"success": False, "error": "Text zprávy je povinný."}), 400

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT c.name, c.linked_family_link_id, sfl.family_user_id "
                "FROM contacts c "
                "LEFT JOIN senior_family_links sfl ON sfl.id = c.linked_family_link_id "
                "WHERE c.id = ? AND c.senior_id = ?",
                (cid, sid)
            ).fetchone()
    except Exception:
        return jsonify({"success": False, "error": "DB error"}), 500

    if not row:
        return jsonify({"success": False, "error": "Kontakt nenalezen."}), 404
    name, link_id, family_uid = row
    if not link_id or not family_uid:
        return jsonify({
            "success": False,
            "error": f"{name} nemá Radimcare účet. Zkuste SMS nebo hovor.",
        }), 400

    try:
        from notification_helpers import notify
        senior_name = (g.auth_user.get("name") or g.auth_user.get("email") or "Senior")
        nid = notify(
            to_user_id=family_uid, type="chat_msg", severity="info",
            title=f"Zpráva od {senior_name}",
            body=body[:240],
            from_user_id=sid,
            data={"contact_id": cid, "senior_name": senior_name},
        )
    except Exception as e:
        logger.error(f"contact_message notify: {e}")
        return jsonify({"success": False, "error": "Zprávu se nepodařilo doručit."}), 500

    return jsonify({"success": True, "notification_id": nid,
                    "message": f"Zpráva pro {name} odeslána."})


logger.info("📞 Contacts routes loaded: /api/contacts/*")
