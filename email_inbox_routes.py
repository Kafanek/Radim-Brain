"""
📥 EMAIL INBOX ROUTES v1.0 (Sprint C — part 2 of 2)
=============================================================================
IMAP bridge so seniors actually see their real inbox (Seznam, Wedos,
iCloud, etc. — anything accepting app password / regular IMAP auth).

Gmail & Outlook require OAuth 2.0 (not implemented here — planned for
Sprint D). Current scope: IMAP app-password flow for the 90%+ of Czech
seniors who use Seznam.

Endpoints:
  POST   /api/email/account       — save IMAP/SMTP config (password encrypted)
  GET    /api/email/account       — status (NO password returned)
  DELETE /api/email/account       — wipe config

  GET    /api/email/inbox?limit=50   — latest headers via IMAP
  GET    /api/email/message/<uid>    — fetch full body + attachments meta
  POST   /api/email/mark-read/<uid>  — IMAP \\Seen flag
  DELETE /api/email/message/<uid>    — IMAP move to Trash

All endpoints require_auth. Passwords are Fernet-encrypted at rest via
a key derived from JWT_SECRET (fallback env key EMAIL_IMAP_ENCRYPTION_KEY).

Timeouts: strict 8 seconds on IMAP ops (eventlet socket patching handles
the blocking I/O safely, but we don't want workers wedged).
"""

import base64
import email
import email.header
import email.utils
import imaplib
import logging
import os
import re
import socket
from datetime import datetime
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

email_inbox_bp = Blueprint('email_inbox', __name__)


IMAP_TIMEOUT_SECONDS = 8


# ============================================================
# SCHEMA
# ============================================================

SCHEMA_SQL_PG = """
    CREATE TABLE IF NOT EXISTS email_accounts (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL UNIQUE,
        email_address TEXT NOT NULL,
        imap_host TEXT NOT NULL,
        imap_port INTEGER DEFAULT 993,
        smtp_host TEXT,
        smtp_port INTEGER DEFAULT 465,
        encrypted_password TEXT NOT NULL,
        last_sync_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""

SCHEMA_SQL_SQLITE = """
    CREATE TABLE IF NOT EXISTS email_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL UNIQUE,
        email_address TEXT NOT NULL,
        imap_host TEXT NOT NULL,
        imap_port INTEGER DEFAULT 993,
        smtp_host TEXT,
        smtp_port INTEGER DEFAULT 465,
        encrypted_password TEXT NOT NULL,
        last_sync_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


def _init_schema():
    try:
        sql = SCHEMA_SQL_PG if is_postgres() else SCHEMA_SQL_SQLITE
        with db_context(commit=True) as db:
            for stmt in sql.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"email_accounts schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


# ============================================================
# PASSWORD ENCRYPTION (Fernet, key derived from JWT_SECRET)
# ============================================================

_FERNET_INSTANCE = None


def _get_fernet():
    """Lazy-init Fernet cipher. Key derives from EMAIL_IMAP_ENCRYPTION_KEY env
    var, or falls back to JWT_SECRET (already app-wide secret). If neither is
    set, returns None — callers should then reject the operation."""
    global _FERNET_INSTANCE
    if _FERNET_INSTANCE is not None:
        return _FERNET_INSTANCE
    try:
        from cryptography.fernet import Fernet
        import hashlib
    except Exception as e:
        logger.warning(f"cryptography not available: {e}")
        return None

    key_raw = (os.environ.get('EMAIL_IMAP_ENCRYPTION_KEY')
               or os.environ.get('JWT_SECRET')
               or os.environ.get('SECRET_KEY'))
    if not key_raw:
        logger.warning("No encryption key env — email account storage disabled")
        return None

    # Derive a 32-byte key, then urlsafe-b64 for Fernet
    digest = hashlib.sha256(key_raw.encode('utf-8')).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    _FERNET_INSTANCE = Fernet(fernet_key)
    return _FERNET_INSTANCE


def _encrypt_password(plaintext):
    f = _get_fernet()
    if not f:
        raise RuntimeError('encryption unavailable')
    token = f.encrypt(plaintext.encode('utf-8'))
    return token.decode('ascii')


def _decrypt_password(token):
    f = _get_fernet()
    if not f:
        raise RuntimeError('encryption unavailable')
    return f.decrypt(token.encode('ascii')).decode('utf-8')


# ============================================================
# ACCOUNT CONFIG ENDPOINTS
# ============================================================

# Czech ISP IMAP presets — saves senior from hunting server names
ISP_PRESETS = {
    'seznam.cz': {'imap': ('imap.seznam.cz', 993), 'smtp': ('smtp.seznam.cz', 465)},
    'email.cz':  {'imap': ('imap.seznam.cz', 993), 'smtp': ('smtp.seznam.cz', 465)},
    'post.cz':   {'imap': ('imap.seznam.cz', 993), 'smtp': ('smtp.seznam.cz', 465)},
    'centrum.cz':{'imap': ('imap.centrum.cz', 993), 'smtp': ('smtp.centrum.cz', 465)},
    'volny.cz':  {'imap': ('imap.volny.cz', 993), 'smtp': ('smtp.volny.cz', 465)},
    'atlas.cz':  {'imap': ('imap.centrum.cz', 993), 'smtp': ('smtp.centrum.cz', 465)},
    'icloud.com':{'imap': ('imap.mail.me.com', 993), 'smtp': ('smtp.mail.me.com', 587)},
    'me.com':    {'imap': ('imap.mail.me.com', 993), 'smtp': ('smtp.mail.me.com', 587)},
    # Gmail/Outlook require OAuth — skip
}


def _guess_imap_preset(email_address):
    domain = (email_address or '').split('@', 1)[-1].lower()
    return ISP_PRESETS.get(domain)


@email_inbox_bp.route('/api/email/account', methods=['POST', 'OPTIONS'])
@require_auth
def save_account():
    """Save/update the user's IMAP account. Body: {email, password,
    imap_host?, imap_port?, smtp_host?, smtp_port?}.

    If imap_host not provided, looked up from ISP_PRESETS by email domain.
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    email_addr = (data.get('email') or data.get('email_address') or '').strip().lower()
    password = data.get('password') or ''

    if not email_addr or '@' not in email_addr:
        return jsonify({'success': False, 'error': 'invalid email'}), 400
    if not password or len(password) > 256:
        return jsonify({'success': False, 'error': 'invalid password'}), 400

    preset = _guess_imap_preset(email_addr) or {'imap': (None, None), 'smtp': (None, None)}
    imap_host = (data.get('imap_host') or preset['imap'][0] or '').strip()
    if not imap_host:
        return jsonify({
            'success': False,
            'error': 'Tato adresa nemá přednastavený server. Zadejte imap_host ručně.'
        }), 400
    try:
        imap_port = int(data.get('imap_port') or preset['imap'][1] or 993)
        smtp_host = (data.get('smtp_host') or preset['smtp'][0] or '').strip() or None
        smtp_port = int(data.get('smtp_port') or preset['smtp'][1] or 465)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'invalid port'}), 400

    try:
        enc = _encrypt_password(password)
    except Exception:
        return jsonify({
            'success': False,
            'error': 'Server nemá nastavený šifrovací klíč (EMAIL_IMAP_ENCRYPTION_KEY).'
        }), 503

    try:
        with db_context(commit=True) as db:
            # Upsert (UNIQUE on user_id)
            existing = db.execute(
                "SELECT id FROM email_accounts WHERE user_id = ?",
                (uid,)
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE email_accounts SET email_address = ?, imap_host = ?, "
                    "imap_port = ?, smtp_host = ?, smtp_port = ?, "
                    "encrypted_password = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = ?",
                    (email_addr, imap_host, imap_port, smtp_host, smtp_port, enc, uid)
                )
            else:
                db.execute(
                    "INSERT INTO email_accounts "
                    "(user_id, email_address, imap_host, imap_port, smtp_host, "
                    "smtp_port, encrypted_password) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, email_addr, imap_host, imap_port, smtp_host, smtp_port, enc)
                )
        return jsonify({
            'success': True,
            'email': email_addr,
            'imap_host': imap_host,
        })
    except Exception as e:
        logger.error(f"save_account: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@email_inbox_bp.route('/api/email/account', methods=['GET'])
@require_auth
def get_account():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT email_address, imap_host, imap_port, smtp_host, smtp_port, "
                "last_sync_at, created_at FROM email_accounts WHERE user_id = ?",
                (uid,)
            ).fetchone()
    except Exception as e:
        logger.error(f"get_account: {e}")
        row = None

    if not row:
        return jsonify({'success': True, 'configured': False})

    return jsonify({
        'success': True,
        'configured': True,
        'email': _row_val(row, 0, 'email_address'),
        'imap_host': _row_val(row, 1, 'imap_host'),
        'imap_port': _row_val(row, 2, 'imap_port'),
        'smtp_host': _row_val(row, 3, 'smtp_host'),
        'smtp_port': _row_val(row, 4, 'smtp_port'),
        'last_sync_at': str(_row_val(row, 5, 'last_sync_at') or ''),
        'created_at': str(_row_val(row, 6, 'created_at') or ''),
    })


@email_inbox_bp.route('/api/email/account', methods=['DELETE'])
@require_auth
def delete_account():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM email_accounts WHERE user_id = ?", (uid,))
        return jsonify({'success': True, 'removed': True})
    except Exception as e:
        logger.error(f"delete_account: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# IMAP HELPERS
# ============================================================

def _load_account(uid):
    with db_context() as db:
        row = db.execute(
            "SELECT email_address, imap_host, imap_port, encrypted_password "
            "FROM email_accounts WHERE user_id = ?",
            (uid,)
        ).fetchone()
    if not row:
        return None
    return {
        'email': _row_val(row, 0, 'email_address'),
        'host': _row_val(row, 1, 'imap_host'),
        'port': int(_row_val(row, 2, 'imap_port') or 993),
        'password': _decrypt_password(_row_val(row, 3, 'encrypted_password')),
    }


def _open_imap(account):
    """Returns a logged-in IMAP4_SSL connection."""
    socket.setdefaulttimeout(IMAP_TIMEOUT_SECONDS)
    imap = imaplib.IMAP4_SSL(account['host'], account['port'])
    imap.login(account['email'], account['password'])
    return imap


def _decode_header(h):
    if not h:
        return ''
    try:
        parts = email.header.decode_header(h)
        out = []
        for text, enc in parts:
            if isinstance(text, bytes):
                out.append(text.decode(enc or 'utf-8', errors='replace'))
            else:
                out.append(text)
        return ''.join(out).strip()
    except Exception:
        return str(h)[:300]


def _parse_from(raw_from):
    """Returns (name, email) from a raw From header."""
    if not raw_from:
        return ('', '')
    decoded = _decode_header(raw_from)
    name, addr = email.utils.parseaddr(decoded)
    return (name or '', (addr or '').strip().lower())


# ============================================================
# INBOX ENDPOINTS
# ============================================================

@email_inbox_bp.route('/api/email/inbox', methods=['GET'])
@require_auth
def fetch_inbox():
    """Fetch latest headers. Query: ?limit=50 (max 200)."""
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        account = _load_account(uid)
    except Exception as e:
        logger.error(f"inbox load_account: {e}")
        return jsonify({'success': False, 'error': 'account storage error'}), 500
    if not account:
        # Sprint T: unconfigured is not an error — it's an expected state.
        # Return 200 with configured:false so frontend can show setup UI
        # without noisy console 404s.
        return jsonify({
            'success': True,
            'configured': False,
            'messages': [],
            'count': 0,
            'message': 'Nastavte prosím svůj emailový účet přes Nastavení → E-mail.',
        }), 200

    try:
        limit = max(1, min(int(request.args.get('limit', 50)), 200))
    except ValueError:
        limit = 50

    try:
        imap = _open_imap(account)
    except imaplib.IMAP4.error as e:
        return jsonify({'success': False, 'error': 'imap_auth', 'detail': str(e)[:120]}), 401
    except Exception as e:
        return jsonify({'success': False, 'error': 'imap_connect', 'detail': str(e)[:120]}), 502

    messages = []
    try:
        imap.select('INBOX', readonly=True)
        typ, data = imap.search(None, 'ALL')
        if typ != 'OK' or not data or not data[0]:
            return jsonify({'success': True, 'messages': [], 'count': 0})
        uids = data[0].split()
        uids = uids[-limit:]  # latest N
        uids.reverse()
        for uid_bytes in uids:
            try:
                typ, hdata = imap.fetch(uid_bytes,
                    '(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE TO)])')
                if typ != 'OK' or not hdata or not hdata[0]:
                    continue
                flags_raw = b''
                header_bytes = b''
                for part in hdata:
                    if isinstance(part, tuple) and len(part) >= 2:
                        flags_raw = part[0] or b''
                        header_bytes = part[1] or b''
                msg = email.message_from_bytes(header_bytes)
                from_name, from_email = _parse_from(msg.get('From', ''))
                subject = _decode_header(msg.get('Subject', ''))
                date_hdr = msg.get('Date', '')
                date_dt = None
                try:
                    parsed = email.utils.parsedate_to_datetime(date_hdr)
                    date_dt = parsed
                except Exception:
                    date_dt = None
                messages.append({
                    'uid': uid_bytes.decode('ascii') if isinstance(uid_bytes, bytes) else str(uid_bytes),
                    'from_name': from_name,
                    'from_email': from_email,
                    'subject': subject,
                    'date': date_dt.isoformat() if date_dt else date_hdr,
                    'unread': b'\\Seen' not in flags_raw,
                })
            except Exception as e:
                logger.debug(f'inbox fetch item: {e}')
                continue
    finally:
        try: imap.logout()
        except Exception: pass

    # Update last_sync_at
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE email_accounts SET last_sync_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ?", (uid,)
            )
    except Exception:
        pass

    return jsonify({'success': True, 'messages': messages, 'count': len(messages)})


@email_inbox_bp.route('/api/email/message/<uid>', methods=['GET'])
@require_auth
def fetch_message(uid):
    user_id = _uid()
    if not user_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not re.match(r'^\d+$', uid or ''):
        return jsonify({'success': False, 'error': 'invalid uid'}), 400

    try:
        account = _load_account(user_id)
    except Exception:
        return jsonify({'success': False, 'error': 'account storage error'}), 500
    if not account:
        return jsonify({'success': False, 'error': 'no_account'}), 404

    try:
        imap = _open_imap(account)
    except Exception as e:
        return jsonify({'success': False, 'error': 'imap_connect', 'detail': str(e)[:120]}), 502

    try:
        imap.select('INBOX', readonly=True)
        typ, data = imap.fetch(uid.encode('ascii'), '(RFC822)')
        if typ != 'OK' or not data or not data[0]:
            return jsonify({'success': False, 'error': 'not found'}), 404
        raw_bytes = data[0][1] if isinstance(data[0], tuple) else b''
        msg = email.message_from_bytes(raw_bytes)
    finally:
        try: imap.logout()
        except Exception: pass

    from_name, from_email = _parse_from(msg.get('From', ''))
    subject = _decode_header(msg.get('Subject', ''))
    body_plain = ''
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = str(part.get('Content-Disposition') or '')
            if ctype == 'text/plain' and 'attachment' not in disposition:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or 'utf-8'
                        body_plain += payload.decode(charset, errors='replace')
                except Exception:
                    pass
            elif 'attachment' in disposition or ctype.startswith('image/'):
                fn = _decode_header(part.get_filename() or '')
                if fn:
                    attachments.append({
                        'name': fn[:200],
                        'type': ctype,
                        'size': len(part.get_payload(decode=True) or b''),
                    })
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or 'utf-8'
                body_plain = payload.decode(charset, errors='replace')
        except Exception:
            body_plain = msg.get_payload() or ''

    return jsonify({
        'success': True,
        'uid': uid,
        'from_name': from_name,
        'from_email': from_email,
        'subject': subject,
        'date': msg.get('Date', ''),
        'body': body_plain[:20000],
        'attachments': attachments,
    })


@email_inbox_bp.route('/api/email/mark-read/<uid>', methods=['POST'])
@require_auth
def mark_read(uid):
    user_id = _uid()
    if not user_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not re.match(r'^\d+$', uid or ''):
        return jsonify({'success': False, 'error': 'invalid uid'}), 400

    try:
        account = _load_account(user_id)
    except Exception:
        return jsonify({'success': False, 'error': 'account storage error'}), 500
    if not account:
        return jsonify({'success': False, 'error': 'no_account'}), 404

    try:
        imap = _open_imap(account)
    except Exception as e:
        return jsonify({'success': False, 'error': 'imap_connect', 'detail': str(e)[:120]}), 502
    try:
        imap.select('INBOX')
        imap.store(uid.encode('ascii'), '+FLAGS', '\\Seen')
        imap.expunge()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:100]}), 500
    finally:
        try: imap.logout()
        except Exception: pass

    return jsonify({'success': True, 'marked': True})


@email_inbox_bp.route('/api/email/message/<uid>', methods=['DELETE'])
@require_auth
def delete_message(uid):
    user_id = _uid()
    if not user_id:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not re.match(r'^\d+$', uid or ''):
        return jsonify({'success': False, 'error': 'invalid uid'}), 400

    try:
        account = _load_account(user_id)
    except Exception:
        return jsonify({'success': False, 'error': 'account storage error'}), 500
    if not account:
        return jsonify({'success': False, 'error': 'no_account'}), 404

    try:
        imap = _open_imap(account)
    except Exception as e:
        return jsonify({'success': False, 'error': 'imap_connect', 'detail': str(e)[:120]}), 502
    try:
        imap.select('INBOX')
        imap.store(uid.encode('ascii'), '+FLAGS', '\\Deleted')
        imap.expunge()
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:100]}), 500
    finally:
        try: imap.logout()
        except Exception: pass

    return jsonify({'success': True, 'deleted': True})


logger.info("📥 Email inbox routes v1.0 loaded — IMAP bridge with Fernet-encrypted credentials")
