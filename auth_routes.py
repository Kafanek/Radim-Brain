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

from datetime import datetime
from flask import Blueprint, request, jsonify, g
from database import get_connection, is_postgres
from auth_middleware import require_auth, _base64url_encode, WP_JWT_SECRET

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
    """Hash password with SHA256 + salt."""
    salt = os.environ.get('WP_JWT_SECRET', 'radim-default-salt')
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _ensure_auth_table():
    """Create auth_users table if not exists."""
    db = None
    try:
        db = get_connection()
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
        db.commit()
    except Exception as e:
        logger.warning(f"Auth table init: {e}")
    finally:
        if db:
            try: db.close()
            except: pass


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


# Init auth table at startup
try:
    _ensure_auth_table()
except Exception:
    pass


# ============================================
# Auth Routes
# ============================================

@auth_bp.route('/api/auth/register', methods=['POST', 'OPTIONS'])
def auth_register():
    """Register user in PostgreSQL (+ try WordPress sync)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400
    if len(password) < 6:
        return jsonify({"success": False, "error": "Heslo musí mít alespoň 6 znaků", "code": "password_weak"}), 400

    db = None
    try:
        db = get_connection()
        # Check if exists
        ph = '%s' if is_postgres() else '?'
        row = db.execute(f"SELECT id FROM auth_users WHERE email = {ph}", (email,)).fetchone()
        if row:
            return jsonify({"success": False, "error": "Účet s tímto emailem již existuje", "code": "email_exists"}), 409

        # Insert
        pw_hash = _hash_password(password)
        if is_postgres():
            cur = db.execute(
                "INSERT INTO auth_users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
                (email, pw_hash, name)
            )
            ret = cur.fetchone()
            user_id = ret['id'] if isinstance(ret, dict) else ret[0]
        else:
            cur = db.execute(
                "INSERT INTO auth_users (email, password_hash, name) VALUES (?, ?, ?)",
                (email, pw_hash, name)
            )
            user_id = cur.lastrowid
        db.commit()

        token = _create_jwt(user_id, email, name)

        # Best-effort WordPress sync (non-blocking)
        try:
            http_requests.post(f"{WP_AUTH_BASE}/register", json={
                "email": email, "password": password, "name": name
            }, headers=WP_PROXY_HEADERS, timeout=5)
        except Exception:
            pass  # WP sync is optional

        return jsonify({
            "success": True,
            "token": token,
            "user": {"id": user_id, "email": email, "name": name, "role": "subscriber"},
            "gdpr_consent": False,
            "message": "Registrace úspěšná!"
        })

    except Exception as e:
        logger.error(f"Auth register error: {e}")
        return jsonify({"success": False, "error": "Chyba při registraci", "code": "db_error"}), 500
    finally:
        if db:
            try: db.close()
            except: pass


@auth_bp.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    """Login from PostgreSQL (+ WordPress fallback)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400

    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        row = db.execute(
            f"SELECT id, email, name, role, password_hash FROM auth_users WHERE email = {ph}", (email,)
        ).fetchone()

        if row:
            user_id = row['id'] if isinstance(row, dict) else row[0]
            user_email = row['email'] if isinstance(row, dict) else row[1]
            user_name = row['name'] if isinstance(row, dict) else row[2]
            role = row['role'] if isinstance(row, dict) else row[3]
            pw_hash = row['password_hash'] if isinstance(row, dict) else row[4]
            if pw_hash == _hash_password(password):
                token = _create_jwt(user_id, user_email, user_name, role or 'subscriber')
                # Fetch GDPR consent status (one response = no extra API call)
                gdpr_consent = False
                try:
                    from memory_routes import get_gdpr_consent
                    consent = get_gdpr_consent(str(user_id))
                    gdpr_consent = bool(consent.get("data_processing", False))
                except Exception:
                    pass
                return jsonify({
                    "success": True,
                    "token": token,
                    "user": {"id": user_id, "email": user_email, "name": user_name, "role": role},
                    "gdpr_consent": gdpr_consent,
                    "message": "Přihlášení úspěšné"
                })

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
                # Sync to local DB for next time
                try:
                    pw_hash = _hash_password(password)
                    if is_postgres():
                        db.execute(
                            "INSERT INTO auth_users (email, password_hash, name, role) VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, name = EXCLUDED.name",
                            (email, pw_hash, wp_name, wp_role)
                        )
                    else:
                        db.execute(
                            "INSERT OR REPLACE INTO auth_users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
                            (email, pw_hash, wp_name, wp_role)
                        )
                    db.commit()
                except Exception:
                    pass
                return jsonify({
                    "success": True,
                    "token": token,
                    "user": {"id": wp_id, "email": email, "name": wp_name, "role": wp_role},
                    "gdpr_consent": False,
                    "message": "Přihlášení úspěšné"
                })
        except Exception:
            pass  # WP unreachable -- use only local result

        return jsonify({"success": False, "error": "Nesprávný email nebo heslo", "code": "invalid_credentials"}), 401

    except Exception as e:
        logger.error(f"Auth login error: {e}")
        return jsonify({"success": False, "error": "Chyba při přihlášení", "code": "db_error"}), 500
    finally:
        if db:
            try: db.close()
            except: pass


@auth_bp.route('/api/auth/lost-password', methods=['POST', 'OPTIONS'])
def auth_lost_password():
    """Password reset -- try WordPress, always return success"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
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
    """GDPR: Export všech dat uživatele z backendu"""
    user_id = str(g.auth_user.get('id', ''))
    export_data = {
        "export_date": now_iso(),
        "user_id": user_id,
        "backend_data": {}
    }

    # Export memory data
    conn = None
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            # Profile
            cursor.execute("SELECT data FROM memory_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row:
                export_data["backend_data"]["profile"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            # History (last 500)
            cursor.execute(
                "SELECT role, content, timestamp FROM memory_history WHERE user_id = %s ORDER BY timestamp DESC LIMIT 500",
                (user_id,)
            )
            export_data["backend_data"]["history"] = [
                {"role": r[0], "content": r[1], "timestamp": str(r[2])} for r in cursor.fetchall()
            ]

            # Learning data
            cursor.execute("SELECT data FROM memory_learning WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row:
                export_data["backend_data"]["learning"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            cursor.close()
    except Exception as e:
        # v330: Don't leak exception details in GDPR export
        logger.error(f"GDPR export error for user: {e}")
        export_data["backend_data"]["error"] = "Chyba při načítání dat"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return jsonify({
        "success": True,
        "data": export_data
    })

@auth_bp.route('/api/auth/data', methods=['DELETE'])
@require_auth
def auth_data_delete():
    """GDPR: Smaže všechna data uživatele z backendu"""
    user_id = str(g.auth_user.get('id', ''))
    deleted = {"profile": False, "history": False, "learning": False}

    conn = None
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_profiles WHERE user_id = %s", (user_id,))
            deleted["profile"] = cursor.rowcount > 0
            cursor.execute("DELETE FROM memory_history WHERE user_id = %s", (user_id,))
            deleted["history"] = cursor.rowcount > 0
            cursor.execute("DELETE FROM memory_learning WHERE user_id = %s", (user_id,))
            deleted["learning"] = cursor.rowcount > 0
            conn.commit()
            cursor.close()
    except Exception as e:
        logger.error(f"auth data delete error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

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
