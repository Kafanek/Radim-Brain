"""
🛡️ EMAIL SECURITY ROUTES v1.0 (Sprint C — part 1 of 2)
=============================================================================
Scam/phishing protection + family oversight for the Email module v2.0.

Endpoints:
  POST   /api/email/scan              — AI scam score for a given message
  POST   /api/email/flag-family       — senior flags an email for family
  GET    /api/email/family/<sid>/flagged  — family reads senior's flagged items
  POST   /api/email/block             — block a sender
  GET    /api/email/blocklist         — user's blocked senders
  DELETE /api/email/block/<sender>    — unblock

All endpoints require_auth. Family view additionally verifies
senior_family_links.confirmed=TRUE.

This blueprint DOES NOT send email (that stays in email_routes.py).
It DOES NOT read inbox (that's email_inbox_routes.py, Sprint C part 2).
"""

import json
import logging
import re
from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

email_security_bp = Blueprint('email_security', __name__)


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS email_blocklist (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        sender_email TEXT NOT NULL,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, sender_email)
    );

    CREATE TABLE IF NOT EXISTS email_family_flags (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        subject TEXT,
        from_email TEXT,
        from_name TEXT,
        snippet TEXT,
        reasons TEXT,
        sent_at TIMESTAMP,
        flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_email_blocklist_user ON email_blocklist(user_id);
    CREATE INDEX IF NOT EXISTS idx_email_flags_user ON email_family_flags(user_id, flagged_at DESC);
    CREATE INDEX IF NOT EXISTS idx_email_flags_unresolved ON email_family_flags(user_id) WHERE resolved_at IS NULL;
"""

# SQLite doesn't support WHERE in CREATE INDEX, so split out
SCHEMA_SQL_SQLITE = """
    CREATE TABLE IF NOT EXISTS email_blocklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        sender_email TEXT NOT NULL,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, sender_email)
    );

    CREATE TABLE IF NOT EXISTS email_family_flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        subject TEXT,
        from_email TEXT,
        from_name TEXT,
        snippet TEXT,
        reasons TEXT,
        sent_at TIMESTAMP,
        flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_email_blocklist_user ON email_blocklist(user_id);
    CREATE INDEX IF NOT EXISTS idx_email_flags_user ON email_family_flags(user_id, flagged_at DESC);
"""


def _init_schema():
    try:
        sql = SCHEMA_SQL if is_postgres() else SCHEMA_SQL_SQLITE
        with db_context(commit=True) as db:
            for stmt in sql.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"email_security schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


def _is_valid_email(addr):
    if not addr or not isinstance(addr, str):
        return False
    addr = addr.strip()
    return 5 <= len(addr) <= 254 and bool(EMAIL_RE.match(addr))


# ============================================================
# SCAM DETECTION (backend — complements frontend heuristics)
# ============================================================

# Keyword lookups — same coverage as frontend _scanForScam() but also adds
# Gemini AI analysis if available for deeper check.
_URGENCY = [
    r'urgent[nn][ěe]', r'okam[žz]it[ěe]', r'posledn[íi]\s+upozorn[ěe]n',
    r'b[ěe]hem\s+24\s+hodin', r'zablokov[áa]n', r'deaktivov[áa]n',
    r'expiruje', r'posledn[íi]\s+šance',
]
_MONEY = [
    r'v[ýy]hra', r'vyhr[áa]li\s+jste', r'bitcoin', r'kryptom[ěe]n',
    r'dl[uu]žn[áa]\s+č[áa]stka', r'dan[ovýýy]+\s+[úu][řr]ad',
    r'odemknut[íi]\s+[úu][čc]tu', r'platba\s+odm[íi]tnuta',
    r'vr[áa]cen[íi]\s+pen[ěě]z',
]
_CREDENTIALS = [
    r'\bheslo\b', r'\bpin\b', r'č[íi]slo\s+karty', r'cvv',
    r'ov[ěe][řr]te\s+sv', r'potvr[ďd]te\s+sv[ée]\s+heslo',
    r'resetujte\s+heslo',
]
_SUSPICIOUS_TLD = re.compile(
    r'@[^@]+\.(?:ru|cn|tk|ml|ga|cf|xyz|top|click|bid)\b', re.IGNORECASE)
_URL_SHORTENERS = re.compile(
    r'\b(bit\.ly|tinyurl\.com|goo\.gl|t\.co|is\.gd|ow\.ly|buff\.ly|'
    r'rebrand\.ly|rb\.gy|cutt\.ly|shorte\.st)\b', re.IGNORECASE)
_IP_URL = re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')

_BRANDS = [
    ('česká spořitelna', 'csas'),
    ('čsob', 'csob'),
    ('komerční banka', 'kb'),
    ('moneta', 'moneta'),
    ('čez', 'cez'),
    ('o2', 'o2'),
    ('vodafone', 'vodafone'),
    ('t-mobile', 'tmobile'),
    ('česká pošta', 'ceskaposta'),
    ('zásilkovna', 'zasilkovna'),
    ('paypal', 'paypal'),
    ('microsoft', 'microsoft'),
    ('apple', 'apple'),
    ('google', 'google'),
]


def _scan_heuristics(subject, body, from_email, from_name=''):
    """Deterministic heuristic scam detection. Pure function, easy to test."""
    reasons = []
    score = 0
    text = f'{subject or ""} {body or ""}'.lower()
    from_lower = (from_email or '').lower()
    name_lower = (from_name or '').lower()

    if any(re.search(p, text) for p in _URGENCY):
        reasons.append('Zní naléhavě — podvodníci vyvolávají tlak')
        score += 25

    if any(re.search(p, text) for p in _MONEY):
        reasons.append('Slibuje peníze, výhru nebo zmiňuje úřady — klasický trik')
        score += 30

    if any(re.search(p, text) for p in _CREDENTIALS):
        reasons.append('Požaduje heslo, PIN nebo údaje z karty — banka toto nikdy po vás emailem nežádá')
        score += 40

    # Brand impersonation: brand name in text but sender domain does not match
    sender_domain = from_lower.split('@', 1)[-1] if '@' in from_lower else ''
    for brand_text, brand_domain_hint in _BRANDS:
        if brand_text in text or brand_text in name_lower:
            # Permissive check: first 6 chars of hint anywhere in domain
            if not sender_domain or brand_domain_hint[:6] not in sender_domain:
                reasons.append(
                    f'Zmiňuje "{brand_text}" ale pochází z neobvyklé adresy '
                    f'({sender_domain or "neznámý odesilatel"})'
                )
                # Brand impersonation is a serious flag by itself — score
                # alone crosses the risky threshold (40).
                score += 40
                break

    if _URL_SHORTENERS.search(body or ''):
        reasons.append('Obsahuje zkrácený odkaz (bit.ly apod.) — pravé firmy je nepoužívají')
        score += 20

    if _IP_URL.search(body or ''):
        reasons.append('Odkaz obsahuje číselnou adresu místo jména webu')
        score += 30

    if re.search(r'[!]{3,}', subject or '') or (
            len(subject or '') >= 15 and (subject or '').upper() == (subject or '')):
        reasons.append('Předmět je v pozornost-upoutávajících velkých písmenech')
        score += 10

    if _SUSPICIOUS_TLD.search(from_email or ''):
        reasons.append(f'Odesilatel má neobvyklou doménu ({sender_domain})')
        score += 15

    return {
        'risky': score >= 40,
        'score': min(100, score),
        'reasons': reasons,
    }


def _scan_with_ai(subject, body, from_email):
    """Optional Gemini second opinion. Returns None if AI unavailable or fails."""
    try:
        from claude_helpers import call_ai_with_fallback
    except Exception:
        return None
    prompt = (
        "Posuď následující email na riziko podvodu/phishingu/spamu. "
        "Odpověz POUZE ve formátu JSON: "
        '{"risky": true/false, "score": 0-100, "reasons": ["duvod1", ...]}. '
        "Žádný další text.\n\n"
        f"Od: {from_email or '?'}\n"
        f"Předmět: {subject or ''}\n"
        f"Text (zkrácený):\n{(body or '')[:2000]}"
    )
    try:
        result = call_ai_with_fallback(prompt, max_tokens=400, temperature=0.0)
        if not result:
            return None
        # Extract first JSON object
        m = re.search(r'\{.*\}', result, flags=re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group(0))
        return {
            'risky': bool(parsed.get('risky')),
            'score': max(0, min(100, int(parsed.get('score') or 0))),
            'reasons': [str(r)[:200] for r in (parsed.get('reasons') or [])][:5],
        }
    except Exception as e:
        logger.debug(f'AI scan skipped: {e}')
        return None


@email_security_bp.route('/api/email/scan', methods=['POST', 'OPTIONS'])
@require_auth
def scan_email():
    """Score an email for scam risk.

    Body: {subject, body, from_email, from_name?, use_ai?}
    Returns: {success, score, risky, reasons, source: 'heuristic'|'ai'|'combined'}
    """
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    subject = (data.get('subject') or '')[:500]
    body = (data.get('body') or '')[:10000]
    from_email = (data.get('from_email') or data.get('from') or '')[:200]
    from_name = (data.get('from_name') or '')[:200]
    use_ai = bool(data.get('use_ai'))

    if not body and not subject:
        return jsonify({'success': False, 'error': 'subject or body required'}), 400

    heuristic = _scan_heuristics(subject, body, from_email, from_name)
    source = 'heuristic'
    risky = heuristic['risky']
    score = heuristic['score']
    reasons = list(heuristic['reasons'])

    if use_ai:
        ai = _scan_with_ai(subject, body, from_email)
        if ai:
            source = 'combined'
            score = max(score, ai['score'])
            risky = risky or ai['risky']
            # Merge reasons, dedup, cap 6
            for r in ai['reasons']:
                if r and r not in reasons:
                    reasons.append(r)
            reasons = reasons[:6]

    return jsonify({
        'success': True,
        'risky': risky,
        'score': score,
        'reasons': reasons,
        'source': source,
    })


# ============================================================
# FAMILY FLAGS
# ============================================================

@email_security_bp.route('/api/email/flag-family', methods=['POST', 'OPTIONS'])
@require_auth
def flag_family():
    """Senior asks family to review a suspicious email.

    Body: {subject, from, from_name?, snippet?, reasons?, sent_at?}
    Records the flag and attempts a family push notification.
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    subject = (data.get('subject') or '')[:500]
    from_email = (data.get('from') or data.get('from_email') or '')[:200]
    from_name = (data.get('from_name') or '')[:200]
    snippet = (data.get('snippet') or data.get('body') or '')[:500]
    reasons = data.get('reasons') or []
    try:
        reasons_json = json.dumps(reasons[:10])[:2000]
    except Exception:
        reasons_json = '[]'
    sent_at_raw = data.get('sent_at') or data.get('date')

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO email_family_flags "
                "(user_id, subject, from_email, from_name, snippet, reasons, sent_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, subject, from_email, from_name, snippet, reasons_json, sent_at_raw)
            )
    except Exception as e:
        logger.error(f"flag_family insert: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500

    # Best-effort: push to linked family members
    notified = 0
    try:
        from notification_helpers import notify_senior_family
        preview = (snippet or subject or '')[:80]
        notify_senior_family(
            senior_id=uid,
            type='warning',
            title='🚨 Váš blízký požádal o kontrolu emailu',
            body=f'Podezřelý email od "{from_email or from_name}": „{preview}"',
            severity='warning',
            data={'subject': subject, 'from': from_email},
            include_caregiver=True,
        )
        notified = 1
    except Exception as e:
        logger.debug(f"flag_family push: {e}")

    return jsonify({'success': True, 'notified': notified})


@email_security_bp.route('/api/email/family/<senior_id>/flagged', methods=['GET'])
@require_auth
def family_flagged(senior_id):
    """Family member reads the senior's flagged emails."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Verify link
    try:
        with db_context() as db:
            link = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                (senior_id, uid, True if is_postgres() else 1)
            ).fetchone()
    except Exception:
        link = None
    if not link:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, subject, from_email, from_name, snippet, reasons, "
                "sent_at, flagged_at, resolved_at "
                "FROM email_family_flags WHERE user_id = ? "
                "ORDER BY flagged_at DESC LIMIT 50",
                (senior_id,)
            ).fetchall()
    except Exception as e:
        logger.error(f"family_flagged: {e}")
        return jsonify({'success': True, 'flagged': []})

    flagged = []
    for r in rows or []:
        reasons_raw = _row_val(r, 5, 'reasons')
        try:
            reasons = json.loads(reasons_raw) if isinstance(reasons_raw, str) else (reasons_raw or [])
        except Exception:
            reasons = []
        flagged.append({
            'id': _row_val(r, 0, 'id'),
            'subject': _row_val(r, 1, 'subject'),
            'fromEmail': _row_val(r, 2, 'from_email'),
            'fromName': _row_val(r, 3, 'from_name'),
            'snippet': _row_val(r, 4, 'snippet'),
            'reasons': reasons,
            'sentAt': str(_row_val(r, 6, 'sent_at') or ''),
            'flaggedAt': str(_row_val(r, 7, 'flagged_at') or ''),
            'resolvedAt': str(_row_val(r, 8, 'resolved_at') or ''),
        })

    return jsonify({'success': True, 'flagged': flagged, 'count': len(flagged)})


@email_security_bp.route('/api/email/family/flag/<int:flag_id>/resolve', methods=['POST'])
@require_auth
def resolve_flag(flag_id):
    """Family marks a flag as resolved (reviewed)."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            # Verify the family member is actually linked to the senior
            row = db.execute(
                "SELECT user_id FROM email_family_flags WHERE id = ?",
                (flag_id,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            senior_id = _row_val(row, 0, 'user_id')
            link = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                (senior_id, uid, True if is_postgres() else 1)
            ).fetchone()
            if not link:
                return jsonify({'success': False, 'error': 'not linked'}), 403
            db.execute(
                "UPDATE email_family_flags SET resolved_at = CURRENT_TIMESTAMP "
                "WHERE id = ?", (flag_id,)
            )
        return jsonify({'success': True, 'resolved': True})
    except Exception as e:
        logger.error(f"resolve_flag: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# BLOCKLIST
# ============================================================

@email_security_bp.route('/api/email/block', methods=['POST', 'OPTIONS'])
@require_auth
def block_sender():
    """Block a sender email. Body: {sender, reason?}."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    sender = (data.get('sender') or data.get('sender_email') or '').strip().lower()
    if not _is_valid_email(sender):
        return jsonify({'success': False, 'error': 'invalid sender email'}), 400
    reason = (data.get('reason') or '')[:200] or None

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM email_blocklist WHERE user_id = ? AND sender_email = ?",
                (uid, sender)
            ).fetchone()
            if existing:
                return jsonify({'success': True, 'blocked': True, 'already_blocked': True})
            db.execute(
                "INSERT INTO email_blocklist (user_id, sender_email, reason) "
                "VALUES (?, ?, ?)",
                (uid, sender, reason)
            )
        return jsonify({'success': True, 'blocked': True})
    except Exception as e:
        logger.error(f"block_sender: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@email_security_bp.route('/api/email/blocklist', methods=['GET'])
@require_auth
def list_blocklist():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT sender_email, reason, created_at FROM email_blocklist "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 500",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_blocklist: {e}")
        return jsonify({'success': True, 'blocked': []})

    blocked = [{
        'sender': _row_val(r, 0, 'sender_email'),
        'reason': _row_val(r, 1, 'reason'),
        'createdAt': str(_row_val(r, 2, 'created_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'blocked': blocked, 'count': len(blocked)})


@email_security_bp.route('/api/email/block/<path:sender>', methods=['DELETE'])
@require_auth
def unblock_sender(sender):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    sender = (sender or '').strip().lower()
    if not sender:
        return jsonify({'success': False, 'error': 'sender required'}), 400
    try:
        with db_context(commit=True) as db:
            db.execute(
                "DELETE FROM email_blocklist WHERE user_id = ? AND sender_email = ?",
                (uid, sender)
            )
        return jsonify({'success': True, 'unblocked': True})
    except Exception as e:
        logger.error(f"unblock_sender: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


logger.info("🛡️ Email security routes v1.0 loaded — scan + family flag + blocklist")
