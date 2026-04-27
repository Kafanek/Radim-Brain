# -*- coding: utf-8 -*-
"""
🎁 LEGACY DELIVERY — Sprint AV
Posmrtné (nebo plánované) předání odkazu seniora rodině.

Podporuje 3 trigger typy:
  - manual         — senior nebo rodina ručně spustí
  - inactivity_*   — Radim 30/60/90 dní senior offline
  - birthday       — narozeniny příjemce (TODO: cron job)

Předání:
  - Email s formátovaným textem (nebo HTML)
  - Audit log
  - Bus event topic=legacy_delivered
  - Email failure → log, reschedule není (jen jednou)
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ============================================================================
# TEMPLATE — friendly intro + categorized content
# ============================================================================

def _format_legacy_text(senior_name, profile, legacy):
    """Compose human-readable legacy text for email body."""
    approved = legacy.get('approved_entries') or {}

    lines = [
        f"Tohle vám nechal/a {senior_name}.",
        "",
        f"Sbíral/a jsem to spolu s Radimem během našich rozhovorů. "
        f"Teď je čas vám to předat.",
        "",
        "─" * 60,
        "",
    ]

    from legacy_engine import LEGACY_CATEGORIES
    for cid, cdef in LEGACY_CATEGORIES.items():
        entries = approved.get(cid) or []
        if not entries:
            continue
        lines.append(f"\n{cdef['icon']} {cdef['name'].upper()}")
        lines.append("─" * 40)
        for e in entries:
            summary = e.get('summary', '').strip()
            quote = e.get('quote')
            if quote:
                lines.append('„' + quote.strip() + '"')
                if summary and summary != quote:
                    lines.append('  (' + summary + ')')
            else:
                lines.append('• ' + summary)
            lines.append("")

    lines.append("─" * 60)
    lines.append("")
    lines.append(f"S láskou,")
    lines.append(senior_name)
    lines.append("")
    lines.append("(Předáno přes Radim, kterého {senior} používal/a každý den)")

    return '\n'.join(lines).replace('{senior}', senior_name)


def _format_legacy_html(senior_name, profile, legacy):
    """HTML version of the same — better for email clients."""
    from legacy_engine import LEGACY_CATEGORIES
    approved = legacy.get('approved_entries') or {}

    parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        '<style>',
        'body { font-family: -apple-system, sans-serif; max-width: 640px; margin: 30px auto; padding: 20px; color: #1a4a44; line-height: 1.6; }',
        'h1 { color: #5BA8A0; font-size: 1.4em; margin-bottom: 0.2em; }',
        'h2 { color: #5BA8A0; font-size: 1.1em; margin-top: 1.5em; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }',
        '.entry { margin: 14px 0; padding: 12px 14px; background: #f8fafc; border-left: 3px solid #5BA8A0; border-radius: 6px; }',
        '.quote { font-style: italic; color: #2d3748; }',
        '.summary { color: #64748b; font-size: 0.92em; margin-top: 4px; }',
        '.intro { background: #e6f7f4; padding: 14px 18px; border-radius: 10px; margin-bottom: 20px; }',
        '.footer { margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 0.85em; }',
        '</style></head><body>',
        f'<h1>🪶 Odkaz od {senior_name}</h1>',
        f'<div class="intro">Tohle vám nechal/a <strong>{senior_name}</strong>. '
        f'Sbíral/a to spolu s Radimem během našich rozhovorů. Teď je čas vám to předat.</div>',
    ]

    for cid, cdef in LEGACY_CATEGORIES.items():
        entries = approved.get(cid) or []
        if not entries:
            continue
        parts.append(f'<h2>{cdef["icon"]} {cdef["name"]}</h2>')
        for e in entries:
            summary = (e.get('summary') or '').strip()
            quote = (e.get('quote') or '').strip()
            parts.append('<div class="entry">')
            if quote:
                parts.append(f'<div class="quote">„{quote}"</div>')
                if summary and summary != quote:
                    parts.append(f'<div class="summary">{summary}</div>')
            else:
                parts.append(f'<div>{summary}</div>')
            parts.append('</div>')

    parts.append(
        f'<div class="footer">S láskou,<br>{senior_name}<br><br>'
        f'<em>Předáno přes Radim, který nám pomáhal pamatovat.</em></div>'
    )
    parts.append('</body></html>')
    return '\n'.join(parts)


# ============================================================================
# DELIVERY
# ============================================================================

def _send_email(to_email, subject, text_body, html_body):
    """Use SMTP env config. Returns True on success."""
    smtp_host = os.environ.get('SMTP_HOST') or os.environ.get('EMAIL_HOST')
    smtp_user = os.environ.get('SMTP_USER') or os.environ.get('EMAIL_USER')
    smtp_pass = os.environ.get('SMTP_PASSWORD') or os.environ.get('EMAIL_PASSWORD')
    smtp_port = int(os.environ.get('SMTP_PORT') or '587')
    sender = (os.environ.get('SMTP_FROM') or os.environ.get('EMAIL_FROM') or
              smtp_user or 'noreply@radimcare.cz')

    if not (smtp_host and smtp_user and smtp_pass):
        logger.warning("SMTP not configured — legacy email skipped")
        return False

    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = to_email
        msg.attach(MIMEText(text_body, 'plain', 'utf-8'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.sendmail(sender, [to_email], msg.as_string())
        logger.info(f"📧 legacy email sent to {to_email}")
        return True
    except Exception as e:
        logger.warning(f"legacy email send failed: {e}")
        return False


def _resolve_recipient_email(family_link_id):
    """Look up email for a senior_family_links row."""
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT family_email, family_name FROM senior_family_links "
                "WHERE id = ?",
                (family_link_id,)
            ).fetchone()
            if not row:
                return None, None
            email = row.get('family_email') if hasattr(row, 'get') else row[0]
            name = row.get('family_name') if hasattr(row, 'get') else row[1]
            return email, name
    except Exception as e:
        logger.debug(f"resolve recipient email failed: {e}")
        return None, None


def deliver_legacy_to_recipients(senior_id, profile, recipients, trigger='manual'):
    """Deliver legacy to all configured recipients.

    Args:
        senior_id: senior's user id
        profile: full profile dict (with legacy field)
        recipients: list of {"family_link_id", "deliver_when"}
        trigger: 'manual' | 'inactivity_30d' | etc.

    Returns:
        {"sent": N, "failed": M, "details": [...]}
    """
    senior_name = profile.get('name') or 'Vaše blízká osoba'
    legacy = profile.get('legacy') or {}
    text_body = _format_legacy_text(senior_name, profile, legacy)
    html_body = _format_legacy_html(senior_name, profile, legacy)

    if trigger == 'manual':
        subject = f'🪶 Odkaz od {senior_name}'
    else:
        subject = f'🪶 Vzkaz od {senior_name}'

    sent = 0
    failed = 0
    details = []

    for rec in recipients:
        link_id = rec.get('family_link_id')
        if not link_id:
            details.append({'link_id': None, 'status': 'skipped', 'reason': 'no link_id'})
            failed += 1
            continue

        email, name = _resolve_recipient_email(link_id)
        if not email:
            details.append({'link_id': link_id, 'status': 'failed', 'reason': 'email not found'})
            failed += 1
            continue

        ok = _send_email(email, subject, text_body, html_body)
        if ok:
            sent += 1
            details.append({'link_id': link_id, 'email': email, 'name': name, 'status': 'sent'})
        else:
            failed += 1
            details.append({'link_id': link_id, 'email': email, 'name': name,
                            'status': 'failed', 'reason': 'smtp_error'})

    # Audit + bus
    try:
        from memory_helpers import audit_log
        audit_log(senior_id, 'legacy_deliver', trigger,
                  f"sent={sent} failed={failed}",
                  None)
    except Exception:
        pass

    try:
        from agent_bus import emit as _bus_emit
        _bus_emit(
            user_id=senior_id,
            sender='legacy_delivery',
            kind='observation',
            severity='info',
            topic='legacy_delivered',
            payload={
                'trigger': trigger,
                'sent': sent,
                'failed': failed,
                'recipients': len(recipients),
            },
            ttl_minutes=60 * 24 * 30,
        )
    except Exception:
        pass

    return {
        'method': 'email_smtp' if (sent or failed) else 'no_config',
        'sent': sent,
        'failed': failed,
        'details': details,
    }


# ============================================================================
# Inactivity check job (APScheduler — daily at 04:00)
# ============================================================================

def check_inactivity_delivery():
    """Daily job: deliver legacy to recipients waiting on inactivity trigger.

    Only fires if:
      - senior has at least 1 approved legacy entry
      - last_active >= configured threshold (30/60/90 days)
      - recipient.delivered_at is None
    """
    try:
        from database import db_context
        from memory_helpers import db_load_profile

        with db_context() as db:
            try:
                rows = db.execute("SELECT user_id FROM memory_profiles").fetchall()
            except Exception:
                return

        now = datetime.utcnow()
        triggered = 0
        for r in (rows or []):
            try:
                uid = r.get('user_id') if hasattr(r, 'get') else r[0]
                profile = db_load_profile(uid) or {}
                legacy = profile.get('legacy') or {}
                recipients = legacy.get('recipients') or []
                approved_total = sum(len(v) for v in (legacy.get('approved_entries') or {}).values())
                if approved_total == 0 or not recipients:
                    continue

                # Inactivity = days since last memory_history entry
                try:
                    last_row = db.execute(
                        "SELECT created_at FROM memory_history WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if last_row:
                        last = last_row.get('created_at') if hasattr(last_row, 'get') else last_row[0]
                        if hasattr(last, 'isoformat'):
                            last_dt = last
                        else:
                            last_dt = datetime.fromisoformat(str(last).replace('Z', ''))
                        inactive_days = (now - last_dt).days
                    else:
                        continue
                except Exception:
                    continue

                pending = [r for r in recipients
                           if not r.get('delivered_at') and
                           r.get('deliver_when', '').startswith('inactivity_')]
                if not pending:
                    continue

                # Match threshold per recipient
                for rec in pending:
                    when = rec.get('deliver_when', 'inactivity_30d')
                    threshold = int(when.split('_')[1].replace('d', '')) if '_' in when else 30
                    if inactive_days < threshold:
                        continue
                    # Trigger
                    result = deliver_legacy_to_recipients(uid, profile, [rec], trigger=when)
                    if result.get('sent'):
                        rec['delivered_at'] = now.isoformat()
                        rec['delivery_method'] = result.get('method')
                        triggered += 1
                # Save updated recipients
                legacy['recipients'] = recipients
                profile['legacy'] = legacy
                from memory_helpers import db_save_profile
                db_save_profile(uid, profile)
            except Exception as e:
                logger.debug(f"inactivity legacy check user={uid} failed: {e}")

        logger.info(f"🪶 legacy inactivity check: {triggered} deliveries triggered")
    except Exception as e:
        logger.warning(f"check_inactivity_delivery failed: {e}")
