"""
👨‍👩‍👧 Family link routes — senior ↔ family account linking (v10.37)
=============================================================================
Senior invites family member by email → token email → family clicks link →
signs up or logs in → link is confirmed → family receives in-app notifications
on crisis, SOS, health alerts.

Endpoints (blueprint prefix-free, /api/family/link/*):
    POST   /api/family/link/invite          senior-auth, body {email, name, relation}
    GET    /api/family/link/my-links        senior-auth, list my invites+links
    DELETE /api/family/link/<id>            senior-auth, revoke link
    POST   /api/family/link/accept          any-auth, body {token}
    GET    /api/family/link/my-seniors      family-auth, seniors I can monitor

All CORS-aware (OPTIONS bypass).
"""

import logging
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, db_insert, is_postgres
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

family_link_bp = Blueprint("family_link", __name__)


INVITE_TTL_HOURS = 72
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://app.radimcare.cz")


def _options_ok():
    return ("", 204)


def _relation_label(relation):
    mapping = {
        "daughter": "dcera", "son": "syn", "spouse": "manžel/manželka",
        "parent": "rodič", "sibling": "sourozenec", "caregiver": "pečovatel",
        "friend": "přítel", "other": "blízká osoba",
    }
    return mapping.get((relation or "").lower(), relation or "")


# ═══════════════════════════════════════════════════════════════════
# EMAIL
# ═══════════════════════════════════════════════════════════════════

def _send_invite_email(to_email, to_name, senior_name, token, relation):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", 465))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not host or not user or not password:
        logger.warning("SMTP not configured — invite email skipped")
        return False

    accept_link = f"{FRONTEND_URL}/?family_invite={token}"
    greet = f"Dobrý den{' ' + to_name if to_name else ''},"
    relation_cz = _relation_label(relation)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Radim Care <{from_addr}>"
    msg["To"] = to_email
    msg["Subject"] = f"{senior_name} vás zve do rodinného propojení — Radim Care"

    body_html = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#2d3748;">
  <div style="text-align:center;margin-bottom:24px;">
    <img src="{FRONTEND_URL}/assets/logo-radim.png" alt="Radim Care" style="height:56px;">
  </div>
  <h2 style="color:#2d3748;font-weight:700;margin:0 0 8px;">Pozvánka do rodiny</h2>
  <p style="font-size:16px;line-height:1.55;">{greet}</p>
  <p style="font-size:16px;line-height:1.55;">
    <strong>{senior_name}</strong> vás zve, abyste se stali součástí jeho/jejího
    <strong>rodinného propojení v aplikaci Radim Care</strong>{' jako ' + relation_cz if relation_cz else ''}.
  </p>
  <p style="font-size:16px;line-height:1.55;">
    Díky tomu dostanete upozornění, pokud se něco stane — například pád, SOS tlačítko
    nebo důležitá zdravotní událost. Všechno zůstává uvnitř aplikace, žádné SMS,
    žádní prostředníci.
  </p>
  <div style="text-align:center;margin:32px 0;">
    <a href="{accept_link}" style="background:#5BA8A0;color:white;padding:14px 32px;
       border-radius:12px;text-decoration:none;font-weight:600;font-size:16px;display:inline-block;">
      Přijmout pozvánku
    </a>
  </div>
  <p style="font-size:14px;color:#718096;line-height:1.5;">
    Pozvánka je platná {INVITE_TTL_HOURS} hodin. Pokud odkaz nefunguje, zkopírujte
    tento řádek do prohlížeče:<br>
    <span style="color:#4a5568;word-break:break-all;">{accept_link}</span>
  </p>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
  <p style="color:#a0aec0;font-size:12px;text-align:center;">
    Radim Care — Váš AI asistent péče &middot; radimcare.cz
  </p>
</div>"""

    body_text = (
        f"{greet}\n\n"
        f"{senior_name} vás zve do rodinného propojení v aplikaci Radim Care.\n"
        f"Přijměte pozvánku: {accept_link}\n\n"
        f"Platnost {INVITE_TTL_HOURS} hodin.\n"
    )

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, password)
                server.sendmail(from_addr, to_email, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                server.login(user, password)
                server.sendmail(from_addr, to_email, msg.as_string())
        logger.info(f"📨 Family invite sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Family invite email failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════

@family_link_bp.route("/api/family/link/invite", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=10, window_seconds=3600, key_func="user")
@require_auth
def family_invite():
    if request.method == "OPTIONS":
        return _options_ok()

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    relation = (data.get("relation") or "").strip().lower()

    if not email or "@" not in email:
        return jsonify({"success": False, "error": "Zadejte platný email."}), 400

    senior_id = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    senior_email = (g.auth_user.get("email") or "").lower()
    senior_name = (g.auth_user.get("name") or g.auth_user.get("display_name")
                   or g.auth_user.get("email") or "Někdo blízký")

    if not senior_id:
        return jsonify({"success": False, "error": "Auth required"}), 401
    if email == senior_email:
        return jsonify({"success": False, "error": "Nemůžete pozvat sám sebe."}), 400

    token = secrets.token_urlsafe(24)
    expires_at = (datetime.utcnow() + timedelta(hours=INVITE_TTL_HOURS)).isoformat()

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id, confirmed_at, revoked_at FROM senior_family_links "
                "WHERE senior_id = ? AND family_email = ?",
                (senior_id, email)
            ).fetchone()

            if existing:
                if existing[1]:
                    return jsonify({
                        "success": False, "error": "Tento člen je už propojený.",
                        "link_id": existing[0],
                    }), 409
                db.execute(
                    "UPDATE senior_family_links SET invite_token = ?, "
                    "invite_expires_at = ?, family_name = COALESCE(?, family_name), "
                    "relation = COALESCE(?, relation), revoked_at = NULL "
                    "WHERE id = ?",
                    (token, expires_at, name or None, relation or None, existing[0])
                )
                link_id = existing[0]
            else:
                link_id = db_insert(
                    db, "senior_family_links",
                    ["senior_id", "family_email", "family_name", "relation",
                     "invite_token", "invite_expires_at"],
                    [senior_id, email, name or None, relation or None,
                     token, expires_at]
                )
    except Exception as e:
        logger.error(f"family_invite DB: {e}")
        return jsonify({"success": False, "error": "Nepodařilo se uložit pozvánku."}), 500

    email_sent = _send_invite_email(email, name, senior_name, token, relation)

    return jsonify({
        "success": True,
        "link_id": link_id,
        "email": email,
        "email_sent": email_sent,
        "expires_at": expires_at,
        "accept_url": f"{FRONTEND_URL}/?family_invite={token}",
        "message": (
            "Pozvánka odeslána na email." if email_sent
            else "Pozvánku jsme vytvořili, ale email se nepodařilo odeslat. "
                 "Odkaz můžete sdílet ručně."
        ),
    })


@family_link_bp.route("/api/family/link/my-links", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def family_my_links():
    if request.method == "OPTIONS":
        return _options_ok()
    senior_id = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    if not senior_id:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, family_email, family_name, relation, "
                "       family_user_id, confirmed_at, revoked_at, "
                "       invite_expires_at, created_at, "
                "       COALESCE(sos_priority, NULL) as sos_priority, "
                "       COALESCE(notify_on_sos, TRUE) as notify_on_sos, "
                "       COALESCE(notify_on_crisis, TRUE) as notify_on_crisis, "
                "       COALESCE(notify_on_daily, FALSE) as notify_on_daily "
                "FROM senior_family_links WHERE senior_id = ? "
                "ORDER BY COALESCE(sos_priority, 999), created_at DESC",
                (senior_id,)
            ).fetchall() or []
    except Exception as e:
        logger.error(f"family_my_links: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    links = []
    for r in rows:
        status = "revoked" if r[6] else ("confirmed" if r[5] else "pending")
        links.append({
            "id": r[0], "email": r[1], "name": r[2], "relation": r[3],
            "family_user_id": r[4], "status": status,
            "confirmed_at": str(r[5]) if r[5] else None,
            "expires_at": str(r[7]) if r[7] else None,
            "created_at": str(r[8]) if r[8] else None,
            "sos_priority": r[9],
            "notify_on_sos": bool(r[10]),
            "notify_on_crisis": bool(r[11]),
            "notify_on_daily": bool(r[12]),
        })
    return jsonify({"success": True, "links": links, "count": len(links)})


@family_link_bp.route("/api/family/link/<int:link_id>/settings", methods=["PATCH", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def family_settings(link_id):
    """Update SOS priority + opt-in flags for a family link (v10.38)."""
    if request.method == "OPTIONS":
        return _options_ok()
    senior_id = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    if not senior_id:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    updates = []
    params = []
    if "sos_priority" in data:
        v = data["sos_priority"]
        if v is None:
            updates.append("sos_priority = ?"); params.append(None)
        else:
            try:
                vi = int(v)
                if 1 <= vi <= 9:
                    updates.append("sos_priority = ?"); params.append(vi)
            except (TypeError, ValueError):
                pass
    for col in ("notify_on_sos", "notify_on_crisis", "notify_on_daily"):
        if col in data:
            updates.append(f"{col} = ?")
            if is_postgres():
                params.append(bool(data[col]))
            else:
                params.append(1 if data[col] else 0)
    if not updates:
        return jsonify({"success": False, "error": "Žádné změny."}), 400

    params.extend([link_id, senior_id])
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                f"UPDATE senior_family_links SET {', '.join(updates)} "
                f"WHERE id = ? AND senior_id = ?",
                tuple(params)
            )
            if not cur.rowcount:
                return jsonify({"success": False, "error": "Propojení nenalezeno."}), 404
    except Exception as e:
        logger.error(f"family_settings: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    return jsonify({"success": True, "message": "Nastavení uloženo."})


@family_link_bp.route("/api/family/link/<int:link_id>", methods=["DELETE", "OPTIONS"])
@require_auth
def family_revoke(link_id):
    if request.method == "OPTIONS":
        return _options_ok()
    senior_id = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    if not senior_id:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT senior_id, family_user_id FROM senior_family_links WHERE id = ?",
                (link_id,)
            ).fetchone()
            if not row:
                return jsonify({"success": False, "error": "Propojení nenalezeno."}), 404
            if str(row[0]) != senior_id:
                return jsonify({"success": False, "error": "Přístup odepřen."}), 403

            if is_postgres():
                db.execute("UPDATE senior_family_links SET revoked_at = NOW() WHERE id = ?", (link_id,))
            else:
                db.execute("UPDATE senior_family_links SET revoked_at = CURRENT_TIMESTAMP WHERE id = ?", (link_id,))

            if row[1]:
                try:
                    from notification_helpers import notify
                    notify(
                        to_user_id=row[1], type="family_revoked", severity="info",
                        title="Rodinné propojení bylo zrušeno",
                        body="Přístup k upozorněním seniora byl zrušen.",
                        from_user_id=senior_id,
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"family_revoke: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    return jsonify({"success": True, "message": "Propojení zrušeno."})


@family_link_bp.route("/api/family/link/accept", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=3600, key_func="user")
@require_auth
def family_accept():
    if request.method == "OPTIONS":
        return _options_ok()
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"success": False, "error": "Chybí token."}), 400

    family_uid = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    family_email = (g.auth_user.get("email") or "").strip().lower()
    family_name = g.auth_user.get("name") or g.auth_user.get("display_name")
    if not family_uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, senior_id, family_email, invite_expires_at, "
                "       confirmed_at, revoked_at "
                "FROM senior_family_links WHERE invite_token = ?",
                (token,)
            ).fetchone()
            if not row:
                return jsonify({"success": False, "error": "Neplatná pozvánka."}), 404

            lid = row[0]; senior_id = row[1]; invited_email = row[2]
            expires_at = row[3]; confirmed_at = row[4]; revoked_at = row[5]
            if revoked_at:
                return jsonify({"success": False, "error": "Pozvánka byla zrušena."}), 410
            if confirmed_at:
                return jsonify({"success": False, "error": "Pozvánka už byla přijata."}), 409

            try:
                if expires_at and datetime.fromisoformat(str(expires_at).replace("Z", "")) < datetime.utcnow():
                    return jsonify({"success": False, "error": "Pozvánka vypršela."}), 410
            except Exception:
                pass

            if family_email and invited_email and family_email != invited_email.lower():
                return jsonify({
                    "success": False,
                    "error": f"Pozvánka byla poslána na jiný email ({invited_email}). "
                             f"Přihlaste se prosím účtem s tímto emailem.",
                }), 403

            if is_postgres():
                db.execute(
                    "UPDATE senior_family_links SET family_user_id = ?, "
                    "family_name = COALESCE(?, family_name), "
                    "confirmed_at = NOW(), invite_token = NULL "
                    "WHERE id = ?",
                    (family_uid, family_name, lid)
                )
            else:
                db.execute(
                    "UPDATE senior_family_links SET family_user_id = ?, "
                    "family_name = COALESCE(?, family_name), "
                    "confirmed_at = CURRENT_TIMESTAMP, invite_token = NULL "
                    "WHERE id = ?",
                    (family_uid, family_name, lid)
                )
    except Exception as e:
        logger.error(f"family_accept: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    try:
        from notification_helpers import notify
        notify(
            to_user_id=senior_id, type="family_accepted", severity="info",
            title="Rodinné propojení přijato",
            body=f"{family_name or family_email} přijal/a vaši pozvánku.",
            from_user_id=family_uid,
            data={"link_id": lid},
        )
    except Exception:
        pass

    return jsonify({"success": True, "link_id": lid, "senior_id": senior_id,
                    "message": "Propojení přijato. Budete dostávat upozornění."})


@family_link_bp.route("/api/family/link/my-seniors", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def family_my_seniors():
    if request.method == "OPTIONS":
        return _options_ok()
    family_uid = str(g.auth_user.get("id") or g.auth_user.get("user_id") or "")
    if not family_uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, senior_id, relation, confirmed_at "
                "FROM senior_family_links "
                "WHERE family_user_id = ? AND confirmed_at IS NOT NULL "
                "AND revoked_at IS NULL "
                "ORDER BY confirmed_at DESC",
                (family_uid,)
            ).fetchall() or []
    except Exception as e:
        logger.error(f"family_my_seniors: {e}")
        return jsonify({"success": False, "error": "DB error"}), 500

    seniors = []
    for r in rows:
        seniors.append({
            "link_id": r[0], "senior_id": r[1],
            "relation": r[2], "linked_at": str(r[3]) if r[3] else None,
        })
    return jsonify({"success": True, "seniors": seniors, "count": len(seniors)})


logger.info("👨‍👩‍👧 Family link routes loaded: /api/family/link/*")
