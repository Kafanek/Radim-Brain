# -*- coding: utf-8 -*-
"""
🐛 BUG TELEMETRY AGENT — Frontend chyby v reálném čase

Když seniorovi cokoliv praskne v UI (TypeError, missing function, broken
state), Radim **automaticky zjistí** stack trace, deduplikuje opakované
výskyty, a:
  - uloží do DB (frontend_bugs table)
  - emit bus kind=observation severity=warning topic=frontend_bug
  - caregiver inbox vidí: "Babičce 3× za hodinu praskla hra X"
  - admin/operator dostane priority list (Pareto: 5% bugů = 80% incidentů)

Filozofie:
  Senior nemá hlásit bug. Aplikace má bug **sama poznat**.
  Bug není senior problém, je to náš problém.

Endpointy:
  POST /api/telemetry/bug      — frontend reportuje chybu
  GET  /api/admin/bug-summary  — dashboard pro vývojáře
  GET  /api/caregiver/senior/<id>/recent-bugs — pečovatel vidí
"""

import json
import hashlib
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g

logger = logging.getLogger(__name__)

bug_bp = Blueprint('bug_telemetry', __name__)


# ============================================================================
# SCHEMA
# ============================================================================

def init_bug_table():
    """Create frontend_bugs table if not exists."""
    try:
        from database import db_context, is_postgres
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS frontend_bugs (
                        id SERIAL PRIMARY KEY,
                        fingerprint VARCHAR(64) NOT NULL,
                        user_id VARCHAR(64),
                        message TEXT NOT NULL,
                        stack TEXT,
                        url VARCHAR(500),
                        module VARCHAR(80),
                        method VARCHAR(120),
                        user_agent VARCHAR(300),
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        occurrences INTEGER DEFAULT 1,
                        affected_users INTEGER DEFAULT 1,
                        status VARCHAR(20) DEFAULT 'new',
                        diagnosis TEXT,
                        priority INTEGER DEFAULT 0
                    )
                """)
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fb_fp ON frontend_bugs(fingerprint)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fb_user ON frontend_bugs(user_id)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fb_status ON frontend_bugs(status)"
                )
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS frontend_bugs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fingerprint TEXT NOT NULL,
                        user_id TEXT,
                        message TEXT NOT NULL,
                        stack TEXT,
                        url TEXT,
                        module TEXT,
                        method TEXT,
                        user_agent TEXT,
                        first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                        occurrences INTEGER DEFAULT 1,
                        affected_users INTEGER DEFAULT 1,
                        status TEXT DEFAULT 'new',
                        diagnosis TEXT,
                        priority INTEGER DEFAULT 0
                    )
                """)
        logger.info("✅ frontend_bugs table ready")
    except Exception as e:
        logger.warning(f"frontend_bugs init: {e}")


# Init on import (safe — idempotent)
try:
    init_bug_table()
except Exception:
    pass


# ============================================================================
# FINGERPRINT — group similar bugs
# ============================================================================

def _fingerprint(message: str, stack: str = '') -> str:
    """Hash key that groups duplicate bugs.

    Uses message + first 2 stack lines (function names) — different
    line numbers from minified builds shouldn't fragment.
    """
    # Strip line:col offsets that change between builds
    import re
    norm_stack = ''
    if stack:
        lines = stack.split('\n')[:3]
        # Drop :line:col offsets
        norm_stack = '\n'.join(re.sub(r':\d+:\d+', '', l) for l in lines)
    norm_msg = re.sub(r'\d+', 'N', (message or '')[:200])
    h = hashlib.sha256((norm_msg + '|' + norm_stack).encode()).hexdigest()
    return h[:16]


# ============================================================================
# AUTO-DIAGNOSIS via Gemini (optional, runs on first occurrence)
# ============================================================================

DIAGNOSIS_PROMPT = """Analyzuj následující JavaScript chybu z aplikace pro seniory:

Zpráva: {message}

Stack trace (zkráceno):
{stack}

Modul: {module}
Metoda: {method}
URL: {url}

Popiš v 2-3 stručných českých větách:
1. PRAVDĚPODOBNOU PŘÍČINU (technicky)
2. KONKRÉTNÍ NÁVRH OPRAVY (jaký řádek/funkce)
3. JE TO BLOKUJÍCÍ pro seniora? (kritické/střední/kosmetické)

Buď velmi stručný — toto je interní tooling pro vývojáře.
"""


def _diagnose_async(bug_id, bug_data):
    """Run in background thread — Gemini diagnosis."""
    try:
        import os
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            return
        import urllib.request
        from ai_config import gemini_url

        prompt = DIAGNOSIS_PROMPT.format(
            message=bug_data.get('message', '')[:500],
            stack=(bug_data.get('stack', '') or '')[:1500],
            module=bug_data.get('module', 'unknown'),
            method=bug_data.get('method', 'unknown'),
            url=bug_data.get('url', '')[:200],
        )
        body = json.dumps({
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 400},
        }).encode()
        req = urllib.request.Request(gemini_url(api_key), data=body, method='POST',
                                      headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        cands = resp.get('candidates') or []
        if not cands:
            return
        parts = (cands[0].get('content') or {}).get('parts') or []
        if not parts:
            return
        diagnosis = parts[0].get('text', '').strip()[:1000]

        # Save back to DB
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE frontend_bugs SET diagnosis = ? WHERE id = ?",
                (diagnosis, bug_id)
            )
        logger.info(f"🐛 bug {bug_id} diagnosed: {diagnosis[:80]}")
    except Exception as e:
        logger.debug(f"bug diagnosis failed: {e}")


# ============================================================================
# ROUTES
# ============================================================================

@bug_bp.route('/api/telemetry/bug', methods=['POST', 'OPTIONS'])
def report_bug():
    """Frontend hlásí JS chybu. Auth optional — chceme i pre-login bugy."""
    if request.method == 'OPTIONS':
        return ('', 204)

    body = request.get_json(silent=True) or {}
    message = (body.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'message required'}), 400
    if len(message) > 1000:
        message = message[:1000]

    stack = (body.get('stack') or '')[:5000]
    url = (body.get('url') or '')[:500]
    module = (body.get('module') or '')[:80]
    method = (body.get('method') or '')[:120]
    ua = (body.get('user_agent') or request.headers.get('User-Agent', ''))[:300]
    user_id = body.get('user_id') or ''

    fp = _fingerprint(message, stack)
    now = datetime.utcnow().isoformat()

    try:
        from database import db_context, is_postgres
        with db_context(commit=True) as db:
            # Check existing fingerprint
            row = db.execute(
                "SELECT id, occurrences, affected_users FROM frontend_bugs WHERE fingerprint = ?",
                (fp,)
            ).fetchone()

            if row:
                bug_id = row.get('id') if hasattr(row, 'get') else row[0]
                # Update occurrence count + check if new user
                db.execute(
                    "UPDATE frontend_bugs SET occurrences = occurrences + 1, "
                    "last_seen = ? WHERE id = ?",
                    (now, bug_id)
                )
                # Bump affected_users if new user
                if user_id:
                    existing_users = db.execute(
                        "SELECT COUNT(DISTINCT user_id) AS c FROM frontend_bugs "
                        "WHERE fingerprint = ? AND user_id = ?",
                        (fp, user_id)
                    ).fetchone()
                    cnt = (existing_users.get('c') if hasattr(existing_users, 'get')
                           else existing_users[0]) or 0
                    if not cnt:
                        db.execute(
                            "UPDATE frontend_bugs SET affected_users = affected_users + 1 "
                            "WHERE id = ?", (bug_id,)
                        )
                first_time = False
            else:
                # New bug — insert
                if is_postgres():
                    db.execute("""
                        INSERT INTO frontend_bugs
                        (fingerprint, user_id, message, stack, url, module, method, user_agent)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING id
                    """, (fp, user_id, message, stack, url, module, method, ua))
                    bug_id = db.fetchone()[0] if db.fetchone() else None
                else:
                    db.execute("""
                        INSERT INTO frontend_bugs
                        (fingerprint, user_id, message, stack, url, module, method, user_agent)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (fp, user_id, message, stack, url, module, method, ua))
                    bug_id = db.lastrowid
                first_time = True
    except Exception as e:
        logger.warning(f"bug telemetry insert failed: {e}")
        return jsonify({'success': False, 'error': 'storage failed'}), 500

    # Bus emit so caregiver inbox sees frontend_bug as observation
    if user_id:
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=user_id,
                sender='bug_telemetry',
                kind='observation',
                severity='warning',
                topic='frontend_bug',
                payload={
                    'fingerprint': fp,
                    'message': message[:200],
                    'module': module,
                    'method': method,
                    'first_time': first_time,
                },
                ttl_minutes=60 * 24,
            )
        except Exception:
            pass

    # Async diagnose new bugs only
    if first_time and bug_id:
        try:
            import threading
            threading.Thread(
                target=_diagnose_async,
                args=(bug_id, {
                    'message': message, 'stack': stack, 'url': url,
                    'module': module, 'method': method,
                }),
                daemon=True,
            ).start()
        except Exception:
            pass

    return jsonify({
        'success': True,
        'fingerprint': fp,
        'first_time': first_time,
    })


@bug_bp.route('/api/admin/bug-summary', methods=['GET'])
def bug_summary():
    """Dashboard for developers — top bugs by impact."""
    secret = request.headers.get('X-Admin-Secret', '')
    import os
    if secret != os.environ.get('ADMIN_SECRET', ''):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        from database import db_context
        with db_context() as db:
            # Top 20 by impact (occurrences * affected_users)
            rows = db.execute("""
                SELECT id, fingerprint, message, stack, module, method,
                       occurrences, affected_users, first_seen, last_seen,
                       status, diagnosis
                FROM frontend_bugs
                WHERE status != 'fixed'
                ORDER BY (occurrences * affected_users) DESC, last_seen DESC
                LIMIT 20
            """).fetchall()

            bugs = [{
                'id': r.get('id') if hasattr(r, 'get') else r[0],
                'fingerprint': r.get('fingerprint') if hasattr(r, 'get') else r[1],
                'message': (r.get('message') if hasattr(r, 'get') else r[2])[:200],
                'stack_preview': ((r.get('stack') if hasattr(r, 'get') else r[3]) or '')[:300],
                'module': r.get('module') if hasattr(r, 'get') else r[4],
                'method': r.get('method') if hasattr(r, 'get') else r[5],
                'occurrences': r.get('occurrences') if hasattr(r, 'get') else r[6],
                'affected_users': r.get('affected_users') if hasattr(r, 'get') else r[7],
                'first_seen': str(r.get('first_seen') if hasattr(r, 'get') else r[8]),
                'last_seen': str(r.get('last_seen') if hasattr(r, 'get') else r[9]),
                'status': r.get('status') if hasattr(r, 'get') else r[10],
                'diagnosis': r.get('diagnosis') if hasattr(r, 'get') else r[11],
            } for r in (rows or [])]

            # Total counts
            total_row = db.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(occurrences) AS total_occurrences "
                "FROM frontend_bugs WHERE status != 'fixed'"
            ).fetchone()

            return jsonify({
                'success': True,
                'bugs': bugs,
                'total_unique': (total_row.get('total') if hasattr(total_row, 'get')
                                 else total_row[0]) or 0,
                'total_occurrences': (total_row.get('total_occurrences')
                                      if hasattr(total_row, 'get') else total_row[1]) or 0,
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:120]}), 500


@bug_bp.route('/api/admin/bug/<int:bug_id>/status', methods=['POST'])
def update_bug_status(bug_id):
    """Mark bug as 'fixed' / 'investigating' / 'wont_fix'."""
    secret = request.headers.get('X-Admin-Secret', '')
    import os
    if secret != os.environ.get('ADMIN_SECRET', ''):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    body = request.get_json(silent=True) or {}
    status = body.get('status')
    if status not in ('new', 'investigating', 'fixed', 'wont_fix'):
        return jsonify({'success': False, 'error': 'invalid status'}), 400

    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE frontend_bugs SET status = ? WHERE id = ?",
                (status, bug_id)
            )
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:120]}), 500
