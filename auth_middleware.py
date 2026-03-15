# ============================================
# 🔐 AUTH MIDDLEWARE v1.1.0
# JWT ověření pro Radim Brain API
# Token pochází z WordPress (radimcare.cz)
# ============================================

import os
import json
import hmac
import hashlib
import base64
import time
import logging
from functools import wraps
from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# JWT secret — musí být STEJNÝ jako KAFANEK_JWT_SECRET v wp-config.php
WP_JWT_SECRET = os.environ.get('WP_JWT_SECRET')
if not WP_JWT_SECRET:
    logger.warning("⚠️ WP_JWT_SECRET not set — JWT auth will reject all tokens!")
    WP_JWT_SECRET = None  # Forces all decode_jwt() calls to return None

# Maximum token lifetime (30 days)
MAX_TOKEN_AGE = 30 * 24 * 3600


def _base64url_decode(data):
    """Base64url decode (JWT standard)"""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def _base64url_encode(data):
    """Base64url encode (JWT standard)"""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def decode_jwt(token):
    """
    Dekóduj a ověř JWT token (HS256).
    Vrací payload dict nebo None.
    """
    try:
        if not WP_JWT_SECRET:
            return None  # No secret configured — reject all tokens

        parts = token.split('.')
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # Ověř podpis
        message = f"{header_b64}.{payload_b64}".encode('utf-8')
        expected_sig = _base64url_encode(
            hmac.new(WP_JWT_SECRET.encode('utf-8'), message, hashlib.sha256).digest()
        )

        if not hmac.compare_digest(expected_sig, signature_b64):
            return None

        # Dekóduj payload
        payload = json.loads(_base64url_decode(payload_b64))

        # Zkontroluj expiraci
        now = time.time()
        if 'exp' in payload:
            if payload['exp'] < now:
                return None  # Token expired
            if payload['exp'] - now > MAX_TOKEN_AGE:
                return None  # Token too long-lived (>30 days)
        elif 'iat' in payload:
            # v327 C1 FIX: Tokens without exp but with iat — enforce MAX_TOKEN_AGE from issue time
            if now - payload['iat'] > MAX_TOKEN_AGE:
                logger.warning(f"JWT without exp rejected — iat too old ({int(now - payload['iat'])}s ago)")
                return None
        else:
            # v327 C1 FIX: Tokens with neither exp nor iat are rejected
            # (legacy WP tokens must be re-issued with proper claims)
            logger.warning("JWT rejected — no exp and no iat claim")
            return None

        return payload

    except Exception:
        return None


def require_auth(f):
    """
    Decorator: Vyžaduje platný JWT token v Authorization headeru.

    Použití:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            user = g.auth_user  # {'id': 123, 'email': '...', 'role': 'free'}
            return jsonify({"user": user})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # CORS preflight (OPTIONS) nesmí vyžadovat auth
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)

        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

        if not token:
            return jsonify({
                "success": False,
                "error": "Authorization token je vyžadován",
                "code": "token_required"
            }), 401

        payload = decode_jwt(token)
        if not payload:
            return jsonify({
                "success": False,
                "error": "Neplatný nebo expirovaný token",
                "code": "invalid_token"
            }), 401

        # Ulož user data do Flask g context
        g.auth_user = payload.get('user', {})
        g.auth_payload = payload

        return f(*args, **kwargs)
    return decorated


def require_premium(f):
    """
    Decorator: Vyžaduje premium uživatele.
    Musí být použit PO @require_auth.

    Použití:
        @app.route('/api/premium-feature')
        @require_auth
        @require_premium
        def premium_route():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, 'auth_user', {})
        if user.get('role') not in ('premium', 'administrator'):
            return jsonify({
                "success": False,
                "error": "Tato funkce vyžaduje Premium předplatné",
                "code": "premium_required"
            }), 403

        return f(*args, **kwargs)
    return decorated


def require_teacher(f):
    """
    Decorator: Vyžaduje roli učitele (teacher, spc_supervisor, administrator).
    Musí být použit PO @require_auth.

    Použití:
        @app.route('/api/education/teacher/dashboard')
        @require_auth
        @require_teacher
        def teacher_dashboard():
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, 'auth_user', {})
        if user.get('role') not in ('teacher', 'spc_supervisor', 'administrator'):
            return jsonify({
                "success": False,
                "error": "Tato funkce vyžaduje roli učitele",
                "code": "teacher_required"
            }), 403

        return f(*args, **kwargs)
    return decorated


def optional_auth(f):
    """
    Decorator: JWT je volitelný — pokud je přítomen, ověří se.
    Pokud není, request projde bez g.auth_user.

    Použití pro endpointy, které fungují i bez přihlášení,
    ale s přihlášením poskytují více dat.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''

        g.auth_user = None
        g.auth_payload = None

        if token:
            payload = decode_jwt(token)
            if payload:
                g.auth_user = payload.get('user', {})
                g.auth_payload = payload

        return f(*args, **kwargs)
    return decorated
