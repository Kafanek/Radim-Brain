"""
📧 Email Routes — SMTP sending via Wedos (info@radimcare.cz)
Supports per-client email configuration.

Env vars:
  SMTP_HOST     — e.g. smtp.wedos.cz
  SMTP_PORT     — e.g. 465 (SSL) or 587 (STARTTLS)
  SMTP_USER     — e.g. info@radimcare.cz
  SMTP_PASS     — email password
  SMTP_FROM     — default from address (defaults to SMTP_USER)
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

email_bp = Blueprint('email', __name__)

# ═══════════════════════════════════════════════════════════════
# SMTP CONFIG
# ═══════════════════════════════════════════════════════════════

def get_smtp_config():
    return {
        'host': os.environ.get('SMTP_HOST', ''),
        'port': int(os.environ.get('SMTP_PORT', '465')),
        'user': os.environ.get('SMTP_USER', ''),
        'password': os.environ.get('SMTP_PASS', ''),
        'from_addr': os.environ.get('SMTP_FROM', os.environ.get('SMTP_USER', '')),
        'use_ssl': int(os.environ.get('SMTP_PORT', '465')) == 465
    }


# ═══════════════════════════════════════════════════════════════
# CLIENT EMAIL MAPPING (from DB profiles)
# ═══════════════════════════════════════════════════════════════

# In-memory fallback; production uses memory_profiles table
_client_emails = {}
_CLIENT_EMAILS_MAX = 500

def _evict_old_client_emails():
    """Keep _client_emails bounded."""
    if len(_client_emails) <= _CLIENT_EMAILS_MAX:
        return
    # No timestamp to sort by, just remove arbitrary oldest entries
    excess = len(_client_emails) - _CLIENT_EMAILS_MAX
    for key in list(_client_emails.keys())[:excess]:
        del _client_emails[key]


def get_client_email(client_id):
    """Get client's configured email address."""
    if client_id in _client_emails:
        return _client_emails[client_id]

    # Try loading from database (memory_profiles)
    try:
        from database import get_db
        db = get_db()
        profile = db.execute(
            "SELECT data FROM memory_profiles WHERE user_id = %s AND profile_type = 'email_config'",
            (client_id,)
        )
        row = profile.fetchone() if profile else None
        if row and row[0]:
            import json
            data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            email = data.get('email')
            if email:
                _client_emails[client_id] = email
                return email
    except Exception as e:
        logger.debug(f"Could not load client email from DB: {e}")

    return None


# ═══════════════════════════════════════════════════════════════
# SEND EMAIL
# ═══════════════════════════════════════════════════════════════

@email_bp.route('/api/email/send', methods=['POST'])
def send_email():
    """Send email via SMTP.

    Body JSON:
      to       — recipient email (required)
      subject  — email subject (required)
      body     — email body text (required)
      from_email — sender override (optional, for client mapping)
      from_name  — sender name (optional)
      client_id  — client ID for email mapping (optional)
      html     — if true, send as HTML (optional)
    """
    data = request.get_json(silent=True) or {}

    to_addr = data.get('to', '').strip()
    subject = data.get('subject', '').strip()
    body = data.get('body', '').strip()

    if not to_addr:
        return jsonify({'success': False, 'error': 'Chybí příjemce (to)'}), 400
    if not subject:
        return jsonify({'success': False, 'error': 'Chybí předmět (subject)'}), 400
    if not body:
        return jsonify({'success': False, 'error': 'Chybí text emailu (body)'}), 400

    config = get_smtp_config()

    if not config['host'] or not config['user'] or not config['password']:
        return jsonify({
            'success': False,
            'error': 'SMTP není nakonfigurován. Nastavte SMTP_HOST, SMTP_USER, SMTP_PASS.'
        }), 503

    # Determine sender
    from_name = data.get('from_name', 'Radim Care')
    from_addr = config['from_addr']

    # Client-specific email
    client_id = data.get('client_id')
    if client_id:
        client_email = get_client_email(client_id)
        if client_email:
            from_addr = client_email

    # Override from frontend
    if data.get('from_email'):
        from_addr = data['from_email']

    # Build message
    msg = MIMEMultipart('alternative')
    msg['From'] = f"{from_name} <{from_addr}>"
    msg['To'] = to_addr
    msg['Subject'] = subject
    msg['Reply-To'] = from_addr

    if data.get('html'):
        msg.attach(MIMEText(body, 'html', 'utf-8'))
    else:
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        if config['use_ssl']:
            # SSL (port 465)
            with smtplib.SMTP_SSL(config['host'], config['port'], timeout=15) as server:
                server.login(config['user'], config['password'])
                server.send_message(msg)
        else:
            # STARTTLS (port 587)
            with smtplib.SMTP(config['host'], config['port'], timeout=15) as server:
                server.starttls()
                server.login(config['user'], config['password'])
                server.send_message(msg)

        logger.info(f"📧 Email sent: {from_addr} → {to_addr} ({subject})")
        return jsonify({
            'success': True,
            'message': 'Email úspěšně odeslán',
            'from': from_addr,
            'to': to_addr
        })

    except smtplib.SMTPAuthenticationError:
        logger.error("📧 SMTP authentication failed")
        return jsonify({'success': False, 'error': 'Přihlášení k SMTP selhalo — zkontrolujte heslo'}), 401
    except smtplib.SMTPRecipientsRefused:
        logger.error(f"📧 Recipient refused: {to_addr}")
        return jsonify({'success': False, 'error': f'Adresa {to_addr} odmítnuta'}), 400
    except Exception as e:
        logger.error(f"📧 Email send error: {e}")
        return jsonify({'success': False, 'error': 'Chyba odesílání emailu. Zkuste to prosím znovu.'}), 500


# ═══════════════════════════════════════════════════════════════
# CLIENT EMAIL CONFIG
# ═══════════════════════════════════════════════════════════════

@email_bp.route('/api/email/config', methods=['GET'])
def get_email_config():
    """Check if SMTP is configured."""
    config = get_smtp_config()
    return jsonify({
        'success': True,
        'configured': bool(config['host'] and config['user']),
        'from_email': config['from_addr'] if config['host'] else None,
        'smtp_host': config['host'] or None
    })


@email_bp.route('/api/email/client', methods=['POST'])
def set_client_email():
    """Set email address for a client.

    Body JSON:
      client_id — client identifier (required)
      email     — client's email address (required)
    """
    data = request.get_json(silent=True) or {}
    client_id = data.get('client_id', '').strip()
    email = data.get('email', '').strip()

    if not client_id or not email:
        return jsonify({'success': False, 'error': 'client_id a email jsou povinné'}), 400

    # Save to memory (bounded)
    _evict_old_client_emails()
    _client_emails[client_id] = email

    # Persist to database
    try:
        import json
        from database import get_db
        db = get_db()
        db.execute("""
            INSERT INTO memory_profiles (user_id, profile_type, data, updated_at)
            VALUES (%s, 'email_config', %s, NOW())
            ON CONFLICT (user_id, profile_type)
            DO UPDATE SET data = %s, updated_at = NOW()
        """, (client_id, json.dumps({'email': email}), json.dumps({'email': email})))
        db.connection.commit()
    except Exception as e:
        logger.warning(f"Could not persist client email to DB: {e}")

    return jsonify({'success': True, 'client_id': client_id, 'email': email})


@email_bp.route('/api/email/client/<client_id>', methods=['GET'])
def get_client_email_route(client_id):
    """Get client's configured email."""
    email = get_client_email(client_id)
    return jsonify({
        'success': True,
        'client_id': client_id,
        'email': email
    })
