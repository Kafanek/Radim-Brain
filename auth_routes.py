# ============================================
# AUTH ROUTES BLUEPRINT
# ============================================
# Extracted from app.py — handles /api/auth/* endpoints
# Registration, login, JWT refresh, GDPR data export/delete
# ============================================

import os
import json
import time
import hmac
import hashlib
import logging
import requests as http_requests
from rate_limiter import rate_limit

from datetime import datetime
from flask import Blueprint, request, jsonify, g
from database import get_connection, is_postgres, db_context, db_insert
from auth_middleware import require_auth, _base64url_encode, WP_JWT_SECRET
from utils import now_iso

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

# ============================================
# WordPress Auth Proxy Config
# ============================================

WP_AUTH_BASE = 'https://www.radimcare.cz/wp-json/radim-obchodnik/v1/user-auth'
WP_PROXY_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'RadimBrain/1.0 (Heroku; Auth Proxy)'
}


# ============================================
# Helper Functions
# ============================================

def _create_jwt(user_id, email, name, role='subscriber'):
    """Create JWT token compatible with WordPress plugin (HS256)."""
    if not WP_JWT_SECRET:
        return None
    now = int(time.time())
    header = _base64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "iss": "radim-brain",
        "iat": now,
        "exp": now + 7 * 86400,  # 7 days
        "user": {"id": user_id, "email": email, "name": name, "role": role}
    }
    payload = _base64url_encode(json.dumps(payload_data).encode())
    sig = _base64url_encode(
        hmac.new(WP_JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{sig}"


def _hash_password(password):
    """Hash password with PBKDF2-SHA256 (production-safe).

    v10.9: Replaced raw SHA256 with werkzeug PBKDF2 (600k iterations).
    Backwards compatible: _verify_password checks both formats.
    """
    from werkzeug.security import generate_password_hash
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


def _verify_password(stored_hash, password):
    """Verify password against stored hash.

    Supports both:
    - NEW: PBKDF2 hashes (werkzeug format: pbkdf2:sha256:...)
    - LEGACY: SHA256 hashes (hex string, 64 chars) — auto-migrated on next login
    """
    if stored_hash.startswith('pbkdf2:'):
        from werkzeug.security import check_password_hash
        return check_password_hash(stored_hash, password)
    else:
        # Legacy SHA256 — check and flag for migration
        salt = os.environ.get('WP_JWT_SECRET', 'radim-default-salt')
        legacy_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return hmac.compare_digest(stored_hash, legacy_hash)


def _ensure_auth_table():
    """Create auth_users table if not exists."""
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS auth_users (
                        id SERIAL PRIMARY KEY,
                        email VARCHAR(255) UNIQUE NOT NULL,
                        password_hash VARCHAR(255) NOT NULL,
                        name VARCHAR(255) DEFAULT '',
                        role VARCHAR(50) DEFAULT 'subscriber',
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """)
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS auth_users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        name TEXT DEFAULT '',
                        role TEXT DEFAULT 'subscriber',
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
    except Exception as e:
        logger.warning(f"Auth table init: {e}")

    # v10.10: Subscription columns (auto-migration)
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT 'trial'")
                db.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS subscription_expires TIMESTAMP")
                db.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS trial_started TIMESTAMP DEFAULT NOW()")
                db.execute("ALTER TABLE auth_users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP")
            else:
                # SQLite — check if columns exist
                cols = [r[1] for r in db.execute("PRAGMA table_info(auth_users)").fetchall()]
                if 'subscription_status' not in cols:
                    db.execute("ALTER TABLE auth_users ADD COLUMN subscription_status TEXT DEFAULT 'trial'")
                if 'subscription_expires' not in cols:
                    db.execute("ALTER TABLE auth_users ADD COLUMN subscription_expires TEXT")
                if 'trial_started' not in cols:
                    db.execute("ALTER TABLE auth_users ADD COLUMN trial_started TEXT DEFAULT CURRENT_TIMESTAMP")
                if 'last_active' not in cols:
                    db.execute("ALTER TABLE auth_users ADD COLUMN last_active TEXT")
    except Exception as e:
        logger.debug(f"Subscription columns migration: {e}")


# Init auth table at startup
try:
    _ensure_auth_table()
except Exception:
    pass


# ============================================
# Auth Routes
# ============================================

@auth_bp.route('/api/auth/register', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=5, window_seconds=300, key_func='ip')
def auth_register():
    """Register user in PostgreSQL (+ try WordPress sync)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400
    if len(password) < 6:
        return jsonify({"success": False, "error": "Heslo musí mít alespoň 6 znaků", "code": "password_weak"}), 400
    # X20.19: basic email format check (frontend uses HTML5 type=email but
    # never trust the client). Also require a name so Radim can greet the
    # user by name (better senior UX — frontend already enforces minlength=2).
    name = (name or '').strip()
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({"success": False, "error": "Neplatný email", "code": "invalid_email"}), 400
    if len(name) < 2:
        return jsonify({"success": False, "error": "Jméno je povinné (alespoň 2 znaky)", "code": "name_required"}), 400
    if len(name) > 60:
        name = name[:60]  # truncate, not reject

    try:
        with db_context(commit=True) as db:
            row = db.execute("SELECT id FROM auth_users WHERE email = ?", (email,)).fetchone()
            if row:
                return jsonify({"success": False, "error": "Účet s tímto emailem již existuje", "code": "email_exists"}), 409

            pw_hash = _hash_password(password)
            user_id = db_insert(db, 'auth_users',
                ['email', 'password_hash', 'name'],
                (email, pw_hash, name)
            )

        token = _create_jwt(user_id, email, name)

        # Best-effort WordPress sync (non-blocking)
        try:
            http_requests.post(f"{WP_AUTH_BASE}/register", json={
                "email": email, "password": password, "name": name
            }, headers=WP_PROXY_HEADERS, timeout=5)
        except Exception:
            pass

        # v10.41: Welcome email (non-blocking, best-effort)
        try:
            from onboarding_routes import send_welcome_email
            send_welcome_email(email, name)
        except Exception as e:
            logger.debug(f"Welcome email skipped: {e}")

        return jsonify({
            "success": True, "token": token,
            "user": {"id": user_id, "email": email, "name": name, "role": "subscriber"},
            "gdpr_consent": False, "message": "Registrace úspěšná!",
            "onboarding": {"show_wizard": True, "all_steps": ["profile", "family", "festive", "sos_test"]},
        })

    except Exception as e:
        logger.error(f"Auth register error: {e}")
        return jsonify({"success": False, "error": "Chyba při registraci", "code": "db_error"}), 500


@auth_bp.route('/api/auth/login', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=10, window_seconds=300, key_func='ip')
def auth_login():
    """Login from PostgreSQL (+ WordPress fallback)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, email, name, role, password_hash FROM auth_users WHERE email = ?", (email,)
            ).fetchone()

            if row:
                user_id = row['id'] if isinstance(row, dict) else row[0]
                user_email = row['email'] if isinstance(row, dict) else row[1]
                user_name = row['name'] if isinstance(row, dict) else row[2]
                role = row['role'] if isinstance(row, dict) else row[3]
                pw_hash = row['password_hash'] if isinstance(row, dict) else row[4]
                if _verify_password(pw_hash, password):
                    # Auto-migrate legacy SHA256 → PBKDF2 on successful login
                    if not pw_hash.startswith('pbkdf2:'):
                        try:
                            new_hash = _hash_password(password)
                            db.execute("UPDATE auth_users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
                            logger.info(f"Password migrated to PBKDF2 for user {user_id}")
                        except Exception:
                            pass
                    token = _create_jwt(user_id, user_email, user_name, role or 'subscriber')
                    gdpr_consent = False
                    try:
                        from memory_routes import get_gdpr_consent
                        consent = get_gdpr_consent(str(user_id))
                        gdpr_consent = bool(consent.get("data_processing", False))
                    except Exception:
                        pass
                    # ISO 27001 A.9.4.2 — auth audit
                    try:
                        from audit_log import audit, A
                        audit(A.AUTH_LOGIN_OK, severity='info',
                              actor_user_id=str(user_id), actor_role=role or 'subscriber',
                              metadata={'auth_source': 'local', 'email_masked': True})
                    except Exception:
                        pass
                    return jsonify({
                        "success": True, "token": token,
                        "user": {"id": user_id, "email": user_email, "name": user_name, "role": role},
                        "gdpr_consent": gdpr_consent, "message": "Přihlášení úspěšné"
                    })
                else:
                    # Local user existuje, ale špatné heslo
                    try:
                        from audit_log import audit, A
                        audit(A.AUTH_LOGIN_FAIL, outcome='failure', severity='warning',
                              actor_user_id=str(user_id), actor_role=role or 'subscriber',
                              reason='wrong_password',
                              metadata={'auth_source': 'local'})
                    except Exception:
                        pass

            # Not found locally or wrong password -> try WordPress
            try:
                wp_resp = http_requests.post(f"{WP_AUTH_BASE}/login", json={
                    "email": email, "password": password
                }, headers=WP_PROXY_HEADERS, timeout=8)
                wp_data = wp_resp.json()
                if wp_resp.status_code == 200 and wp_data.get('success'):
                    user = wp_data.get('data', {})
                    wp_id = user.get('user_id', 0)
                    wp_name = user.get('display_name', email)
                    wp_role = user.get('role', 'subscriber')
                    token = _create_jwt(wp_id, email, wp_name, wp_role)
                    # Sync to local DB — PG uses ON CONFLICT, SQLite uses INSERT OR REPLACE
                    try:
                        pw_hash = _hash_password(password)
                        if is_postgres():
                            db.execute(
                                "INSERT INTO auth_users (email, password_hash, name, role) VALUES (?, ?, ?, ?) ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, name = EXCLUDED.name",
                                (email, pw_hash, wp_name, wp_role)
                            )
                        else:
                            db.execute(
                                "INSERT OR REPLACE INTO auth_users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
                                (email, pw_hash, wp_name, wp_role)
                            )
                    except Exception:
                        pass
                    try:
                        from audit_log import audit, A
                        audit(A.AUTH_LOGIN_OK, severity='info',
                              actor_user_id=str(wp_id), actor_role=wp_role,
                              metadata={'auth_source': 'wordpress'})
                    except Exception:
                        pass
                    return jsonify({
                        "success": True, "token": token,
                        "user": {"id": wp_id, "email": email, "name": wp_name, "role": wp_role},
                        "gdpr_consent": False, "message": "Přihlášení úspěšné"
                    })
            except Exception:
                pass

        # Žádný úspěch — neznámý uživatel nebo špatné heslo (vč. WP fallback)
        try:
            from audit_log import audit, A
            audit(A.AUTH_LOGIN_FAIL, outcome='failure', severity='warning',
                  reason='invalid_credentials',
                  metadata={'auth_source': 'unknown_user'})
        except Exception:
            pass
        return jsonify({"success": False, "error": "Nesprávný email nebo heslo", "code": "invalid_credentials"}), 401

    except Exception as e:
        logger.error(f"Auth login error: {e}")
        return jsonify({"success": False, "error": "Chyba při přihlášení", "code": "db_error"}), 500


@auth_bp.route('/api/auth/lost-password', methods=['POST', 'OPTIONS'])
def auth_lost_password():
    """Password reset -- try WordPress, always return success"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({"success": False, "error": "Email je povinný"}), 400

    # Best-effort WordPress reset
    try:
        http_requests.post(f"{WP_AUTH_BASE}/lost-password", json={"email": email}, headers=WP_PROXY_HEADERS, timeout=5)
    except Exception:
        pass

    return jsonify({"success": True, "message": "Pokud účet s tímto emailem existuje, odeslali jsme instrukce pro obnovu hesla."})


@auth_bp.route('/api/auth/verify', methods=['GET'])
@require_auth
def auth_verify():
    """Ověří JWT token a vrátí user data"""
    return jsonify({
        "success": True,
        "user": g.auth_user,
        "message": "Token je platný"
    })

@auth_bp.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    """Odhlášení -- invalidate session (best effort)"""
    if request.method == 'OPTIONS':
        return '', 204
    # JWT je stateless -- klient jen smaže token
    # Server-side blacklist by se řešil přes Redis, zatím nepotřebujeme
    return jsonify({"success": True, "message": "Odhlášen"})

@auth_bp.route('/api/auth/refresh', methods=['POST', 'OPTIONS'])
@require_auth
def auth_refresh():
    """Obnoví JWT token"""
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user = g.auth_user
        new_token = _create_jwt(user['id'], user.get('email', ''), user.get('name', ''), user.get('role', 'user'))
        return jsonify({"success": True, "token": new_token})
    except Exception as e:
        logger.warning(f"auth_refresh error: {e}")
        return jsonify({"success": False, "error": "Nelze obnovit token"}), 500

@auth_bp.route('/api/auth/me', methods=['GET'])
@require_auth
def auth_me():
    """Vrátí profil aktuálně přihlášeného uživatele"""
    return jsonify({
        "success": True,
        "user": g.auth_user
    })

@auth_bp.route('/api/auth/resend-verification', methods=['POST', 'OPTIONS'])
@require_auth
def auth_resend_verification():
    """Znovu odešle verifikační email (placeholder -- email service TBD)"""
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({"success": True, "message": "Verifikační email byl odeslán (pokud je nakonfigurován)."})

@auth_bp.route('/api/auth/data-export', methods=['GET'])
@require_auth
def auth_data_export():
    """GDPR: Export všech dat uživatele z backendu.

    v841: Migrated from legacy cursor pattern to db_context. Old code used
    `conn.cursor()` which doesn't exist on PgConnectionWrapper — silently
    failed (returned 200 with error placeholder, not real data).
    """
    user_id = str(g.auth_user.get('id', ''))
    export_data = {
        "export_date": now_iso(),
        "user_id": user_id,
        "backend_data": {}
    }

    try:
        with db_context() as db:
            # Profile
            row = db.execute(
                "SELECT data FROM memory_profiles WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                # row[0] for tuple, row['data'] for dict-like
                data = row[0] if not hasattr(row, 'values') else row['data']
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                export_data["backend_data"]["profile"] = data

            # History (last 500). Column is 'created_at' not 'timestamp'.
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 500",
                (user_id,)
            ).fetchall()
            history = []
            for r in rows:
                if hasattr(r, 'values'):
                    history.append({
                        "role": r['role'],
                        "content": r['content'],
                        "timestamp": str(r['created_at']) if r['created_at'] else None,
                    })
                else:
                    history.append({
                        "role": r[0],
                        "content": r[1],
                        "timestamp": str(r[2]) if r[2] else None,
                    })
            export_data["backend_data"]["history"] = history
            export_data["backend_data"]["history_count"] = len(history)

            # Learning data
            row = db.execute(
                "SELECT data FROM memory_learning WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                data = row[0] if not hasattr(row, 'values') else row['data']
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        pass
                export_data["backend_data"]["learning"] = data
    except Exception as e:
        # v330: Don't leak exception details in GDPR export
        logger.exception(f"GDPR export error for user {user_id}: {e}")
        export_data["backend_data"]["error"] = "Chyba při načítání dat"

    return jsonify({
        "success": True,
        "data": export_data
    })

@auth_bp.route('/api/auth/data', methods=['DELETE'])
@require_auth
def auth_data_delete():
    """GDPR: Smaže všechna data uživatele z backendu.

    v841: Migrated from legacy cursor pattern to db_context. Old code used
    `conn.cursor()` which doesn't exist on PgConnectionWrapper — returned
    HTTP 500 every time. GDPR-mandated functionality was broken.
    """
    user_id = str(g.auth_user.get('id', ''))
    deleted = {"profile": False, "history": False, "learning": False}

    try:
        with db_context(commit=True) as db:
            # Memory profiles
            cur = db.execute(
                "DELETE FROM memory_profiles WHERE user_id = ?",
                (user_id,)
            )
            deleted["profile"] = (getattr(cur, 'rowcount', 0) or 0) > 0

            # Memory history
            cur = db.execute(
                "DELETE FROM memory_history WHERE user_id = ?",
                (user_id,)
            )
            deleted["history"] = (getattr(cur, 'rowcount', 0) or 0) > 0

            # Memory learning
            cur = db.execute(
                "DELETE FROM memory_learning WHERE user_id = ?",
                (user_id,)
            )
            deleted["learning"] = (getattr(cur, 'rowcount', 0) or 0) > 0
    except Exception as e:
        logger.exception(f"auth data delete error for user {user_id}: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru",
                       "detail": str(e)[:200]}), 500

    return jsonify({
        "success": True,
        "message": "Všechna data uživatele byla smazána",
        "deleted": deleted
    })

@auth_bp.route('/api/auth/delete-account', methods=['POST'])
@require_auth
def auth_delete_account():
    """GDPR: Smaže účet uživatele + všechna data"""
    user_id = str(g.auth_user.get('id', ''))
    email = g.auth_user.get('email', '')

    conn = None
    try:
        conn = get_connection()
        ph = '%s' if is_postgres() else '?'
        if conn:
            # 1. Smazat všechna data (memory, history, learning)
            conn.execute(f"DELETE FROM memory_profiles WHERE user_id = {ph}", (user_id,))
            conn.execute(f"DELETE FROM memory_history WHERE user_id = {ph}", (user_id,))
            conn.execute(f"DELETE FROM memory_learning WHERE user_id = {ph}", (user_id,))
            # 2. Smazat samotný účet
            result = conn.execute(f"DELETE FROM auth_users WHERE id = {ph}", (int(user_id),))
            account_deleted = getattr(result, 'rowcount', 0) > 0
            conn.commit()

            if account_deleted:
                logger.info(f"Account deleted: {email} (id={user_id})")
                return jsonify({
                    "success": True,
                    "message": "Účet a všechna data byly trvale smazány."
                })
            else:
                return jsonify({"success": False, "error": "Účet nenalezen"}), 404
    except Exception as e:
        logger.error(f"delete-account error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================
# FORGOT PASSWORD — v442
# ============================================

import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart as EmailMIME

_reset_tokens = {}
_RESET_TOKEN_TTL = 3600


def _send_reset_email(to_email, reset_token):
    """Send password reset email via SMTP."""
    host = os.environ.get('SMTP_HOST', '')
    port = int(os.environ.get('SMTP_PORT', '465'))
    user = os.environ.get('SMTP_USER', '')
    password = os.environ.get('SMTP_PASS', '')
    from_addr = os.environ.get('SMTP_FROM', user)
    if not host or not user or not password:
        logger.error("SMTP not configured for password reset")
        return False

    frontend_url = os.environ.get('FRONTEND_URL', 'https://app.radimcare.cz')
    reset_link = f"{frontend_url}/?reset={reset_token}"

    msg = EmailMIME('alternative')
    msg['From'] = f"Radim Care <{from_addr}>"
    msg['To'] = to_email
    msg['Subject'] = 'Obnovení hesla — Radim Care'

    body_html = f"""<div style="font-family:system-ui,sans-serif;max-width:500px;margin:0 auto;padding:20px;">
    <div style="text-align:center;margin-bottom:24px;">
        <img src="{frontend_url}/assets/logo-radim.png" alt="Radim" style="height:60px;">
    </div>
    <h2 style="color:#2d3748;">Obnovení hesla</h2>
    <p>Obdrželi jsme žádost o obnovení vašeho hesla.</p>
    <div style="text-align:center;margin:32px 0;">
        <a href="{reset_link}" style="background:#5BA8A0;color:white;padding:14px 32px;
           border-radius:8px;text-decoration:none;font-weight:600;font-size:16px;">
            Nastavit nové heslo
        </a>
    </div>
    <p style="color:#718096;font-size:14px;">Odkaz je platný 1 hodinu.</p>
    <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
    <p style="color:#a0aec0;font-size:12px;">Radim Care — Váš AI asistent péče</p>
</div>"""

    body_text = f"Obnovení hesla: {reset_link}\nPlatný 1 hodinu."

    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))

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
        logger.info(f"Password reset email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send reset email: {e}")
        return False


@auth_bp.route('/api/auth/forgot-password', methods=['POST', 'OPTIONS'])
def auth_forgot_password():
    """Request password reset — sends email with reset link."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({"success": False, "error": "Email je povinný"}), 400
    try:
        with db_context() as db:
            row = db.execute("SELECT id FROM auth_users WHERE email = ?", (email,)).fetchone()
            if row:
                token = secrets.token_urlsafe(32)
                _reset_tokens[token] = {'email': email, 'expires': int(time.time()) + _RESET_TOKEN_TTL}
                now_ts = int(time.time())
                for k in [k for k, v in _reset_tokens.items() if v['expires'] < now_ts]:
                    del _reset_tokens[k]
                _send_reset_email(email, token)
    except Exception as e:
        logger.error(f"Forgot password error: {e}")
    return jsonify({"success": True, "message": "Pokud existuje účet s tímto emailem, odeslali jsme odkaz pro obnovení hesla."})


@auth_bp.route('/api/auth/reset-password', methods=['POST', 'OPTIONS'])
def auth_reset_password():
    """Reset password using token from email."""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json(silent=True) or {}
    token = data.get('token', '').strip()
    new_password = data.get('password', '')
    if not token or not new_password:
        return jsonify({"success": False, "error": "Token a nové heslo jsou povinné"}), 400
    if len(new_password) < 6:
        return jsonify({"success": False, "error": "Heslo musí mít alespoň 6 znaků"}), 400
    token_data = _reset_tokens.get(token)
    if not token_data or token_data['expires'] < int(time.time()):
        if token in _reset_tokens:
            del _reset_tokens[token]
        return jsonify({"success": False, "error": "Neplatný nebo expirovaný odkaz."}), 400
    email = token_data['email']
    try:
        pw_hash = _hash_password(new_password)
        with db_context(commit=True) as db:
            db.execute("UPDATE auth_users SET password_hash = ? WHERE email = ?", (pw_hash, email))
        del _reset_tokens[token]
        logger.info(f"Password reset for {email}")
        return jsonify({"success": True, "message": "Heslo bylo změněno. Nyní se můžete přihlásit."})
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        return jsonify({"success": False, "error": "Chyba při změně hesla"}), 500


@auth_bp.route('/api/auth/admin-set-password', methods=['POST', 'OPTIONS'])
@require_auth
def admin_set_password():
    """Admin: set password for any user (requires admin role)."""
    if request.method == 'OPTIONS':
        return '', 204
    user = getattr(g, 'auth_user', {})
    if user.get('role') not in ('administrator', 'admin'):
        return jsonify({"success": False, "error": "Vyžaduje admin oprávnění"}), 403
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    new_password = data.get('new_password', '')
    if not email or not new_password or len(new_password) < 6:
        return jsonify({"success": False, "error": "Email a nové heslo (6+ znaků) jsou povinné"}), 400
    try:
        pw_hash = _hash_password(new_password)
        with db_context(commit=True) as db:
            result = db.execute("UPDATE auth_users SET password_hash = ? WHERE email = ?", (pw_hash, email))
            if getattr(result, 'rowcount', 0) == 0:
                return jsonify({"success": False, "error": f"Účet {email} nenalezen"}), 404
        logger.info(f"Admin password set for {email} by {user.get('email')}")
        return jsonify({"success": True, "message": f"Heslo pro {email} bylo změněno."})
    except Exception as e:
        logger.error(f"Admin set password error: {e}")
        return jsonify({"success": False, "error": "Chyba při změně hesla"}), 500


# ============================================
# 🔧 ADMIN: User Detail + Subscription Management
# ============================================

@auth_bp.route('/api/auth/admin-user-detail/<user_id>', methods=['GET', 'OPTIONS'])
@require_auth
def admin_user_detail(user_id):
    """Admin: get comprehensive user detail.

    Returns: profile, meds, contacts, brain state, activity, subscription.
    """
    if request.method == 'OPTIONS':
        return '', 204
    user = getattr(g, 'auth_user', {})
    if user.get('role') not in ('administrator', 'admin'):
        return jsonify({"success": False, "error": "Admin required"}), 403

    try:
        result = {'user_id': user_id}

        with db_context(commit=False) as db:
            # Auth info + subscription
            row = db.execute("""
                SELECT id, email, name, role, created_at,
                       subscription_status, subscription_expires, trial_started, last_active
                FROM auth_users WHERE id = ?
            """, (int(user_id),)).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Uživatel nenalezen"}), 404

            result['account'] = {
                'id': row[0], 'email': row[1], 'name': row[2], 'role': row[3],
                'created_at': str(row[4]) if row[4] else None,
                'subscription_status': row[5] or 'trial',
                'subscription_expires': str(row[6]) if row[6] else None,
                'trial_started': str(row[7]) if row[7] else None,
                'last_active': str(row[8]) if row[8] else None,
            }

            # Message count
            try:
                mc = db.execute("SELECT COUNT(*) FROM memory_history WHERE user_id = ?", (str(user_id),)).fetchone()
                result['message_count'] = mc[0] if mc else 0
            except Exception:
                result['message_count'] = 0

            # Latest brain state
            try:
                bs = db.execute("""
                    SELECT coherence, created_at FROM brain_states
                    WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
                """, (str(user_id),)).fetchone()
                if bs:
                    c = float(bs[0]) if bs[0] else 5.0
                    result['brain'] = {
                        'C': c,
                        'mode': 'CRISIS' if c > 27 else 'ALERT' if c > 12 else 'HARMONY',
                        'last_update': str(bs[1]) if bs[1] else None
                    }
            except Exception:
                pass

            # Observations count (24h)
            try:
                from datetime import datetime, timedelta
                obs = db.execute("""
                    SELECT COUNT(*) FROM agent_observations
                    WHERE user_id = ? AND created_at > ?
                """, (str(user_id), (datetime.utcnow() - timedelta(hours=24)).isoformat())).fetchone()
                result['alerts_24h'] = obs[0] if obs else 0
            except Exception:
                result['alerts_24h'] = 0

        # Profile (meds, contacts, etc.)
        try:
            from memory_helpers import db_load_profile
            profile = db_load_profile(str(user_id)) or {}
            result['profile'] = {
                'name': profile.get('name', ''),
                'medications': profile.get('medications', []),
                'emergency_contacts': profile.get('emergency_contacts', []),
                'interests': profile.get('interests', []),
                'hearing': profile.get('hearing', ''),
                'mobility': profile.get('mobility', ''),
            }
        except Exception:
            result['profile'] = {}

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.error(f"Admin user detail error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/admin-subscription/<user_id>', methods=['PUT', 'OPTIONS'])
@require_auth
def admin_set_subscription(user_id):
    """Admin: update user subscription status.

    Body: {
        "status": "trial|active|expired|suspended",
        "expires": "2026-06-01"  (optional, YYYY-MM-DD)
    }
    """
    if request.method == 'OPTIONS':
        return '', 204
    user = getattr(g, 'auth_user', {})
    if user.get('role') not in ('administrator', 'admin'):
        return jsonify({"success": False, "error": "Admin required"}), 403

    data = request.get_json(silent=True) or {}
    new_status = data.get('status', '').strip()
    expires = data.get('expires', '')

    valid_statuses = ('trial', 'active', 'expired', 'suspended')
    if new_status not in valid_statuses:
        return jsonify({"success": False, "error": f"Status musí být: {', '.join(valid_statuses)}"}), 400

    try:
        with db_context(commit=True) as db:
            if expires:
                db.execute("""
                    UPDATE auth_users SET subscription_status = ?, subscription_expires = ?
                    WHERE id = ?
                """, (new_status, expires, int(user_id)))
            else:
                db.execute("""
                    UPDATE auth_users SET subscription_status = ?
                    WHERE id = ?
                """, (new_status, int(user_id)))

        logger.info(f"Subscription updated: user {user_id} → {new_status} (by {user.get('email')})")
        return jsonify({"success": True, "status": new_status, "expires": expires or None})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@auth_bp.route('/api/auth/admin-users-list', methods=['GET', 'OPTIONS'])
@require_auth
def admin_users_list():
    """Admin: list all users with subscription info.

    Returns compact list: id, email, name, role, subscription, last_active, message_count
    """
    if request.method == 'OPTIONS':
        return '', 204
    user = getattr(g, 'auth_user', {})
    if user.get('role') not in ('administrator', 'admin'):
        return jsonify({"success": False, "error": "Admin required"}), 403

    try:
        with db_context(commit=False) as db:
            rows = db.execute("""
                SELECT a.id, a.email, a.name, a.role, a.created_at,
                       a.subscription_status, a.subscription_expires, a.last_active,
                       (SELECT COUNT(*) FROM memory_history WHERE user_id = CAST(a.id AS TEXT)) as msg_count
                FROM auth_users a
                ORDER BY a.last_active DESC NULLS LAST, a.id DESC
                LIMIT 100
            """).fetchall()

        users = []
        for r in (rows or []):
            users.append({
                'id': r[0], 'email': r[1], 'name': r[2], 'role': r[3],
                'created_at': str(r[4]) if r[4] else None,
                'subscription': r[5] or 'trial',
                'expires': str(r[6]) if r[6] else None,
                'last_active': str(r[7]) if r[7] else None,
                'messages': r[8] or 0
            })

        return jsonify({"success": True, "users": users, "count": len(users)})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


logger.info("🔧 Admin user management v10.10 loaded — subscription, detail, auto-cleanup")
