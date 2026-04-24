"""
🎯 Onboarding routes — first-run wizard tracking + welcome email (v10.41)
=============================================================================
After registration, the senior/family goes through a short wizard:
    1. Profile (name, year of birth, city)
    2. Family invite (email)
    3. Festive greeting
    4. SOS dry-run test

Endpoints:
    GET  /api/onboarding/status   → {completed_steps, pending_steps, is_done}
    POST /api/onboarding/step     → mark step complete {step: "profile" | "family" | ...}
    POST /api/onboarding/skip     → mark whole wizard as skipped
    POST /api/onboarding/welcome-email → (admin only) re-send welcome email

Status is persisted in memory_profiles.data.onboarding:
    { steps: ["profile", "family"], skipped: false, started_at, completed_at }
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Blueprint, g, jsonify, request

from database import db_context

from auth_middleware import require_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

onboarding_bp = Blueprint("onboarding", __name__)


STEPS = ["profile", "family", "festive", "sos_test"]


def _options_ok():
    return ("", 204)


def _current_uid():
    au = getattr(g, "auth_user", None) or {}
    return str(au.get("id") or au.get("user_id") or "")


# ═══════════════════════════════════════════════════════════════════
# WELCOME EMAIL (Czech, branded)
# ═══════════════════════════════════════════════════════════════════

def send_welcome_email(to_email, name=None):
    """Send a warm welcome email to newly registered user.

    Non-blocking helper. Returns True on success, False on failure.
    Never raises — safe to call from register flow.
    """
    try:
        host = os.environ.get("SMTP_HOST")
        port = int(os.environ.get("SMTP_PORT", 465))
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
        from_addr = os.environ.get("SMTP_FROM", user)
        frontend_url = os.environ.get("FRONTEND_URL", "https://app.radimcare.cz")

        if not host or not user or not password:
            logger.warning("SMTP not configured — welcome email skipped")
            return False

        greet = f"Dobrý den{' ' + name if name else ''},"

        msg = MIMEMultipart("alternative")
        msg["From"] = f"Radim Care <{from_addr}>"
        msg["To"] = to_email
        msg["Subject"] = "Vítejte v Radim Care 🌿"

        body_html = f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#2d3748;">
  <div style="text-align:center;margin-bottom:24px;">
    <img src="{frontend_url}/assets/logo-radim.png" alt="Radim Care" style="height:56px;">
  </div>

  <h2 style="color:#2d3748;font-weight:700;margin:0 0 16px;font-family:Georgia,serif;">Vítejte u nás</h2>

  <p style="font-size:16px;line-height:1.6;">{greet}</p>

  <p style="font-size:16px;line-height:1.6;">
    Jsme rádi, že jste se rozhodli zkusit <strong>Radim Care</strong>. Radim je tichý český
    AI asistent — mluví česky, pamatuje si jmeniny, pomáhá s léky, volá pomoc v krizi.
    Teď je na vás, jak ho seznámíte se svou rodinou.
  </p>

  <div style="background:linear-gradient(135deg,#e6f7f4 0%,#c9ece4 100%);padding:20px;border-radius:16px;margin:24px 0;">
    <strong style="color:#1a4a44;display:block;margin-bottom:8px;">👉 První 4 kroky:</strong>
    <ol style="margin:0;padding-left:20px;color:#2d6b65;line-height:1.7;">
      <li>Vyplňte krátký profil (jméno, město)</li>
      <li>Pozvěte rodinu — dostanou upozornění při SOS</li>
      <li>Nastavte si sváteční pozdrav</li>
      <li>Vyzkoušejte SOS tlačítko (žádná skutečná záchranka)</li>
    </ol>
  </div>

  <div style="text-align:center;margin:32px 0;">
    <a href="{frontend_url}" style="background:#5BA8A0;color:white;padding:14px 32px;
       border-radius:12px;text-decoration:none;font-weight:600;font-size:16px;display:inline-block;">
      Spustit Radima
    </a>
  </div>

  <p style="font-size:14px;color:#718096;line-height:1.6;">
    Pokud něco nefunguje nebo se chcete na něco zeptat, napište přímo na
    <a href="mailto:info@radimcare.cz" style="color:#5BA8A0;">info@radimcare.cz</a> — odpovídá jeden z našich
    čtyř lidí, ne chatbot.
  </p>

  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">

  <p style="color:#a0aec0;font-size:12px;text-align:center;line-height:1.5;">
    🇨🇿 Česká data, evropské servery · GDPR first<br>
    Radim Care · <a href="https://radimcare.cz" style="color:#a0aec0;">radimcare.cz</a>
  </p>
</div>"""

        body_text = (
            f"{greet}\n\n"
            f"Vítejte v Radim Care. Radim je tichý český AI asistent — mluví česky, "
            f"pamatuje si jmeniny, pomáhá s léky, volá pomoc v krizi.\n\n"
            f"První 4 kroky:\n"
            f"1. Vyplňte krátký profil\n"
            f"2. Pozvěte rodinu\n"
            f"3. Nastavte sváteční pozdrav\n"
            f"4. Vyzkoušejte SOS tlačítko\n\n"
            f"Otevřít aplikaci: {frontend_url}\n\n"
            f"Napsat: info@radimcare.cz\n"
        )

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, password)
                server.sendmail(from_addr, to_email, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                server.login(user, password)
                server.sendmail(from_addr, to_email, msg.as_string())

        logger.info(f"📨 Welcome email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Welcome email failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# STATUS + STEP TRACKING
# ═══════════════════════════════════════════════════════════════════

def _load_onboarding(user_id):
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        ob = profile.get("onboarding") or {}
        if not isinstance(ob, dict):
            ob = {}
        return ob, profile
    except Exception:
        return {}, {}


def _save_onboarding(user_id, ob):
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        profile["onboarding"] = ob
        db_save_profile(str(user_id), profile)
        return True
    except Exception as e:
        logger.error(f"save onboarding: {e}")
        return False


@onboarding_bp.route("/api/onboarding/status", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def onboarding_status():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    ob, _ = _load_onboarding(uid)
    completed = ob.get("steps", [])
    skipped = bool(ob.get("skipped"))
    pending = [s for s in STEPS if s not in completed]
    is_done = skipped or (not pending)

    return jsonify({
        "success": True,
        "completed_steps": completed,
        "pending_steps": pending,
        "all_steps": STEPS,
        "skipped": skipped,
        "is_done": is_done,
        "started_at": ob.get("started_at"),
        "completed_at": ob.get("completed_at"),
    })


@onboarding_bp.route("/api/onboarding/step", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=30, window_seconds=60, key_func="user")
@require_auth
def onboarding_step():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json(silent=True) or {}
    step = (data.get("step") or "").strip()
    if step not in STEPS:
        return jsonify({"success": False, "error": f"Neznámý krok '{step}'"}), 400

    ob, _ = _load_onboarding(uid)
    steps = ob.get("steps", [])
    if step not in steps:
        steps.append(step)
    ob["steps"] = steps
    ob["skipped"] = False
    if not ob.get("started_at"):
        ob["started_at"] = datetime.utcnow().isoformat()
    # Mark complete if all steps done
    if all(s in steps for s in STEPS) and not ob.get("completed_at"):
        ob["completed_at"] = datetime.utcnow().isoformat()

    _save_onboarding(uid, ob)

    pending = [s for s in STEPS if s not in steps]
    return jsonify({
        "success": True,
        "completed_steps": steps,
        "pending_steps": pending,
        "is_done": not pending,
        "message": f"Krok '{step}' označen jako dokončený.",
    })


@onboarding_bp.route("/api/onboarding/skip", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=10, window_seconds=60, key_func="user")
@require_auth
def onboarding_skip():
    if request.method == "OPTIONS":
        return _options_ok()
    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    ob, _ = _load_onboarding(uid)
    ob["skipped"] = True
    ob["completed_at"] = datetime.utcnow().isoformat()
    _save_onboarding(uid, ob)

    return jsonify({"success": True, "message": "Průvodce přeskočen.",
                    "is_done": True, "skipped": True})


@onboarding_bp.route("/api/onboarding/welcome-email", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=3, window_seconds=300, key_func="user")
@require_auth
def onboarding_resend_welcome():
    """Re-send welcome email to the current user. Useful for testing."""
    if request.method == "OPTIONS":
        return _options_ok()
    au = g.auth_user or {}
    email = (au.get("email") or "").strip()
    name = au.get("name") or au.get("display_name")
    if not email:
        return jsonify({"success": False, "error": "Auth required"}), 401

    ok = send_welcome_email(email, name)
    return jsonify({
        "success": ok,
        "message": "Email odeslán." if ok else "SMTP selhal — viz logy.",
    })


# ═══════════════════════════════════════════════════════════════════════
# SPRINT R — PILOT ONBOARDING (separate from generic onboarding)
# ═══════════════════════════════════════════════════════════════════════
#
# Pilot-specific onboarding tracks:
#   - Phone number (for Twilio fallback on iOS without ATHS)
#   - Privacy policy + T&Cs acceptance (GDPR audit record)
#   - Voice test completion + ATHS acknowledgement (UX health signal)
#
# Table: user_pilot_onboarding
#   user_id | phone | privacy_accepted_at | terms_accepted_at |
#   voice_tested | aths_acknowledged | completed_at

def _init_pilot_schema():
    """Lazy-create table — idempotent."""
    try:
        with db_context(commit=True) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS user_pilot_onboarding (
                    user_id TEXT PRIMARY KEY,
                    phone TEXT,
                    privacy_accepted_at TIMESTAMP,
                    terms_accepted_at TIMESTAMP,
                    voice_tested BOOLEAN DEFAULT FALSE,
                    aths_acknowledged BOOLEAN DEFAULT FALSE,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    except Exception as e:
        logger.debug(f"pilot onboarding schema: {e}")


@onboarding_bp.route("/api/onboarding/pilot/complete", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=10, window_seconds=60, key_func="user")
@require_auth
def pilot_onboarding_complete():
    """Record pilot onboarding completion (phone + consents).
    Legally this is the timestamp + audit trail for GDPR Art 7(1)
    (proof that consent was given)."""
    if request.method == "OPTIONS":
        return _options_ok()
    _init_pilot_schema()

    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    data = request.get_json() or {}
    phone_raw = (data.get("phone") or "").strip()
    phone = "".join(c for c in phone_raw if c.isdigit() or c == "+")[:20]
    privacy_accepted = bool(data.get("privacyAccepted"))
    terms_accepted = bool(data.get("termsAccepted"))
    voice_tested = bool(data.get("voiceTested"))
    aths_ack = bool(data.get("athsAcknowledged"))

    if not privacy_accepted or not terms_accepted:
        return jsonify({
            "success": False,
            "error": "Pro dokončení pilotu je nutné přijmout oba dokumenty.",
            "code": "consents_required",
        }), 400

    now = datetime.utcnow()
    is_pg = False
    try:
        from database import is_postgres
        is_pg = is_postgres()
    except Exception:
        pass

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT user_id FROM user_pilot_onboarding WHERE user_id = ?",
                (uid,)
            ).fetchone()

            bool_vt = voice_tested if is_pg else (1 if voice_tested else 0)
            bool_aa = aths_ack if is_pg else (1 if aths_ack else 0)

            if existing:
                db.execute("""
                    UPDATE user_pilot_onboarding
                    SET phone = ?, privacy_accepted_at = ?, terms_accepted_at = ?,
                        voice_tested = ?, aths_acknowledged = ?, completed_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (phone, now, now, bool_vt, bool_aa, now, uid))
            else:
                db.execute("""
                    INSERT INTO user_pilot_onboarding
                    (user_id, phone, privacy_accepted_at, terms_accepted_at,
                     voice_tested, aths_acknowledged, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (uid, phone, now, now, bool_vt, bool_aa, now))

            # Mirror phone into user_profiles if that table exists
            try:
                db.execute(
                    "UPDATE user_profiles SET phone = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = ?",
                    (phone, uid)
                )
            except Exception:
                pass  # table may not exist yet
    except Exception as e:
        logger.error(f"pilot onboarding write: {e}")
        return jsonify({"success": False, "error": "internal"}), 500

    logger.info(f"🌱 Pilot onboarding completed for {uid[:8]} (phone={bool(phone)})")

    return jsonify({
        "success": True,
        "message": "Děkujeme — pilot je připravený.",
        "completedAt": now.isoformat(),
    })


@onboarding_bp.route("/api/onboarding/pilot/status", methods=["GET", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="user")
@require_auth
def pilot_onboarding_status():
    if request.method == "OPTIONS":
        return _options_ok()
    _init_pilot_schema()

    uid = _current_uid()
    if not uid:
        return jsonify({"success": False, "error": "Auth required"}), 401

    try:
        with db_context() as db:
            row = db.execute("""
                SELECT phone, privacy_accepted_at, terms_accepted_at,
                       voice_tested, aths_acknowledged, completed_at
                FROM user_pilot_onboarding WHERE user_id = ?
            """, (uid,)).fetchone()
    except Exception:
        row = None

    if not row:
        return jsonify({
            "success": True, "completed": False, "data": None,
        })

    def v(i, k):
        return row[i] if isinstance(row, (list, tuple)) else row.get(k)

    return jsonify({
        "success": True,
        "completed": bool(v(5, "completed_at")),
        "data": {
            "phone": v(0, "phone") or "",
            "privacyAcceptedAt": str(v(1, "privacy_accepted_at") or ""),
            "termsAcceptedAt": str(v(2, "terms_accepted_at") or ""),
            "voiceTested": bool(v(3, "voice_tested")),
            "athsAcknowledged": bool(v(4, "aths_acknowledged")),
            "completedAt": str(v(5, "completed_at") or ""),
        },
    })


logger.info("🎯 Onboarding routes loaded: /api/onboarding/status, /step, /skip, /welcome-email, /pilot/complete, /pilot/status")
