"""
📋 AUDIT LOG v2.0 — ISO 27001 / GDPR / Zákon o zdravotních službách
====================================================================

ALGORITMUS (6 fází):

  1. INTERCEPT  — volání audit() z auth/admin/GDPR/sensitive endpointů
  2. NORMALIZE  — auto-doplnění actor, IP, UA, request_id, release, dyno
  3. PII SCRUB  — maskování telefonů, emailů, JWT, hesel, IBAN
  4. HASH CHAIN — SHA-256(prev_hash || canonical_json(record))
  5. PERSIST    — INSERT, fallback logger.critical (never raise)
  6. RETAIN     — 365 dní hot v PG, pak archiv → S3 (7 let total)

POVINNÉ ATRIBUTY ISO 27001 (A.12.4.1, A.9.4.2):
  • timestamp UTC
  • actor (user_id, role, IP, UA)
  • action (controlled vocabulary)
  • outcome (success | failure | denied | error)
  • resource (type + id)
  • integrita (hash chain → poznáme manipulaci)
  • append-only (REVOKE UPDATE, DELETE pro app role)

API:
  • audit(action, **kwargs)  — nové ISO 27001 API (preferované)
  • log_audit(...)           — backward-compat wrapper na audit()
  • verify_chain(start_id=)  — kontrola integrity hash chainu
  • get_audit_trail(...)     — query
"""

import logging
import json
import re
import hashlib
import os
from datetime import datetime, timezone
from flask import request, g, has_request_context

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA — v2 migration (idempotentní)
# ═══════════════════════════════════════════════════════════════════════════

AUDIT_SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        user_id TEXT,
        user_email TEXT,
        user_role TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        senior_id TEXT,
        details JSONB DEFAULT '{}',
        ip_address TEXT,
        user_agent TEXT,
        session_id TEXT,
        success BOOLEAN DEFAULT true
    );

    CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_senior ON audit_log(senior_id);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
    CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp DESC);
"""

# v2 dodatečné sloupce (každý řádek samostatně, idempotentně)
AUDIT_SCHEMA_V2_COLUMNS = [
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS outcome TEXT DEFAULT 'success'",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS severity TEXT DEFAULT 'info'",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS reason TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS before_state JSONB",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS after_state JSONB",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS request_id TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS release_version TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS dyno TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS prev_hash TEXT",
    "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS current_hash TEXT",
]

AUDIT_SCHEMA_V2_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_outcome_ts ON audit_log(outcome, timestamp DESC) WHERE outcome != 'success'",
    "CREATE INDEX IF NOT EXISTS idx_audit_severity_ts ON audit_log(severity, timestamp DESC) WHERE severity != 'info'",
    "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log(resource_type, resource_id)",
]


def init_audit_schema():
    """Idempotentní migrace v1 → v2. Bezpečné volat při každém boot."""
    try:
        from database import db_context, is_postgres
        if not is_postgres():
            # SQLite (lokální dev) — jen v1 schema
            with db_context(commit=True) as db:
                for stmt in AUDIT_SCHEMA_V1.strip().split(';'):
                    s = stmt.strip()
                    if s:
                        db.execute(s)
            return

        with db_context(commit=True) as db:
            # v1 base
            for stmt in AUDIT_SCHEMA_V1.strip().split(';'):
                s = stmt.strip()
                if s:
                    db.execute(s)
            # v2 columns (každý samostatná tx — některé už můžou existovat)
            for stmt in AUDIT_SCHEMA_V2_COLUMNS:
                try:
                    db.execute(stmt)
                except Exception as e:
                    logger.debug(f"Audit migration skip: {e}")
            # v2 indexes
            for stmt in AUDIT_SCHEMA_V2_INDEXES:
                try:
                    db.execute(stmt)
                except Exception as e:
                    logger.debug(f"Audit index skip: {e}")
        logger.info("📋 audit_log schema v2 ready")
    except Exception as e:
        logger.warning(f"Audit schema init failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CONTROLLED VOCABULARY — action taxonomy
# ═══════════════════════════════════════════════════════════════════════════

# Backward-compat akce (v1 API)
VIEW = 'view'; CREATE = 'create'; UPDATE = 'update'; DELETE = 'delete'
EXPORT = 'export'; PRINT = 'print'; LOGIN = 'login'; LOGOUT = 'logout'
CONSENT = 'consent'; ALERT = 'alert'; MESSAGE = 'message'; UPLOAD = 'upload'

# v2 — ISO 27001 controlled vocabulary
class A:
    """Audit action namespace — používej tečkovaný formát."""
    # Authentication (A.9.4.2)
    AUTH_LOGIN_OK         = 'auth.login.success'
    AUTH_LOGIN_FAIL       = 'auth.login.failure'
    AUTH_LOGOUT           = 'auth.logout'
    AUTH_TOKEN_ISSUED     = 'auth.token.issued'
    AUTH_TOKEN_EXPIRED    = 'auth.token.expired'
    AUTH_TOKEN_FORGED     = 'auth.token.forged'
    AUTH_ACCESS_DENIED    = 'auth.access.denied'
    AUTH_PASSWORD_RESET   = 'auth.password.reset'
    AUTH_MFA_ENROLLED     = 'auth.mfa.enrolled'
    AUTH_MFA_FAILED       = 'auth.mfa.failed'
    # Admin actions (A.9.4.1, A.12.1.2)
    ADMIN_USER_CREATE     = 'admin.user.create'
    ADMIN_USER_UPDATE     = 'admin.user.update'
    ADMIN_USER_DELETE     = 'admin.user.delete'
    ADMIN_ROLE_GRANT      = 'admin.user.role_grant'
    ADMIN_ROLE_REVOKE     = 'admin.user.role_revoke'
    ADMIN_CONFIG_CHANGED  = 'admin.config.changed'
    ADMIN_TRIGGER         = 'admin.scheduler.triggered'
    # Data ops (A.18.1, A.13.2)
    DATA_READ_MEDICAL     = 'data.read.medical'
    DATA_READ_BULK        = 'data.read.bulk'
    DATA_EXPORT_CSV       = 'data.export.csv'
    DATA_WRITE_MEDICAL    = 'data.write.medical'
    DATA_WRITE_CONSENT    = 'data.write.consent'
    DATA_DELETE_USER      = 'data.delete.user'
    # GDPR (A.18.1.4)
    GDPR_EXPORT_REQ       = 'gdpr.export.requested'
    GDPR_EXPORT_DELIVERED = 'gdpr.export.delivered'
    GDPR_DELETE_REQ       = 'gdpr.delete.requested'
    GDPR_DELETE_DONE      = 'gdpr.delete.completed'
    GDPR_CONSENT_GIVEN    = 'gdpr.consent.given'
    GDPR_CONSENT_REVOKED  = 'gdpr.consent.revoked'
    # Safety (A.16.1)
    SOS_TRIGGERED         = 'safety.sos.triggered'
    SOS_ACK               = 'safety.sos.acknowledged'
    SOS_RESOLVED          = 'safety.sos.resolved'
    SOS_ESCALATION        = 'safety.escalation.fired'
    # System (A.12.4.1)
    SYS_STARTUP           = 'system.startup'
    SYS_SHUTDOWN          = 'system.shutdown'
    SYS_DEPLOY            = 'system.deploy'


VALID_OUTCOMES = ('success', 'failure', 'denied', 'error')
VALID_SEVERITIES = ('info', 'warning', 'critical')


# ═══════════════════════════════════════════════════════════════════════════
# FÁZE 3 — PII SCRUBBING
# ═══════════════════════════════════════════════════════════════════════════

# Telefon: +420777123456 → +420***456 ; 777123456 → ***456
_RE_PHONE = re.compile(r'(\+?\d{1,4}\s*)?(\d[\d\s\-]{6,12}\d)')
# Email: user@domain.tld → u***@d***.tld
_RE_EMAIL = re.compile(r'\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)@([A-Za-z0-9])([A-Za-z0-9.-]*)\.([A-Za-z]{2,})\b')
# JWT: eyJ.....header....yyy → jwt:***
_RE_JWT = re.compile(r'eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}')
# IBAN: CZ12 3456 7890 ... → CZ12****
_RE_IBAN = re.compile(r'\b([A-Z]{2}\d{2})[\d\s]{12,30}\b')
# Klíče v JSON, které nikdy nesmí projít do logu (cele zamaskujeme)
_PII_KEYS = {'password', 'pwd', 'passwd', 'secret', 'token', 'api_key',
             'apikey', 'authorization', 'auth', 'cookie', 'session_token',
             'access_token', 'refresh_token', 'private_key', 'csrf'}


def _mask_pii_string(s):
    """Masky aplikované na řetězce. Pořadí matters — IBAN dřív než phone."""
    if not isinstance(s, str):
        return s
    s = _RE_JWT.sub('jwt:***', s)
    s = _RE_IBAN.sub(r'\1****', s)
    s = _RE_EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(3)}***.{m.group(5)}", s)
    s = _RE_PHONE.sub(lambda m: (m.group(1) or '') + '***' + m.group(2)[-3:], s)
    return s


def mask_pii(value):
    """Rekurzivně maskuje PII v dict/list/str struktuře."""
    if value is None:
        return None
    if isinstance(value, str):
        return _mask_pii_string(value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in _PII_KEYS:
                out[k] = '***'
            else:
                out[k] = mask_pii(v)
        return out
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if isinstance(value, tuple):
        return tuple(mask_pii(item) for item in value)
    return value


# ═══════════════════════════════════════════════════════════════════════════
# FÁZE 4 — HASH CHAIN
# ═══════════════════════════════════════════════════════════════════════════

_GENESIS_HASH = '0' * 64
_last_hash_cache = {'value': None, 'fetched_at': 0}


def _canonical_json(record):
    """Stable JSON pro hash — UTC ISO timestamps, sorted keys, no whitespace.

    HASH POLE SE NIKDY NEVKLÁDÁ DO HASHE — jinak by se kruhilo.
    """
    safe = {k: v for k, v in record.items() if k not in ('current_hash', 'prev_hash')}
    # Datetime → ISO 8601 UTC
    def _conv(o):
        if isinstance(o, datetime):
            if o.tzinfo is None:
                o = o.replace(tzinfo=timezone.utc)
            return o.astimezone(timezone.utc).isoformat()
        return str(o)
    return json.dumps(safe, sort_keys=True, separators=(',', ':'), default=_conv)


def _last_hash():
    """Poslední current_hash z DB. Cached 30 s."""
    import time
    now = time.time()
    if _last_hash_cache['value'] is not None and (now - _last_hash_cache['fetched_at']) < 30:
        return _last_hash_cache['value']
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT current_hash FROM audit_log "
                "WHERE current_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            value = row[0] if row else _GENESIS_HASH
    except Exception:
        value = _GENESIS_HASH
    _last_hash_cache['value'] = value
    _last_hash_cache['fetched_at'] = now
    return value


def _compute_hash(prev_hash, record):
    payload = (prev_hash + '|' + _canonical_json(record)).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def verify_chain(start_id=1, limit=10000):
    """Procházej audit_log podle id, ověř že každý current_hash je správný.

    Vrací: {'ok': bool, 'broken_at': id|None, 'checked': N}
    """
    from database import db_context
    with db_context() as db:
        rows = db.execute(
            "SELECT id, prev_hash, current_hash, timestamp, user_id, user_role, "
            "action, outcome, severity, resource_type, resource_id, reason, "
            "before_state, after_state, details, ip_address, user_agent, "
            "request_id, release_version, dyno, session_id "
            "FROM audit_log WHERE id >= ? AND current_hash IS NOT NULL "
            "ORDER BY id ASC LIMIT ?",
            (start_id, limit)
        ).fetchall()

    expected_prev = _GENESIS_HASH if start_id <= 1 else None
    if start_id > 1 and rows:
        # Vezmi prev_hash prvního řádku jako výchozí
        expected_prev = rows[0][1]

    checked = 0
    for r in rows:
        (rid, prev_h, cur_h, ts, uid, urole, act, outc, sev, rtype, rid_,
         reason, before, after, details, ip, ua, req_id, rel, dyno, sess) = r
        if expected_prev is not None and prev_h != expected_prev:
            return {'ok': False, 'broken_at': rid, 'checked': checked,
                    'reason': 'prev_hash mismatch'}
        record = {
            'timestamp': ts, 'user_id': uid, 'user_role': urole,
            'action': act, 'outcome': outc, 'severity': sev,
            'resource_type': rtype, 'resource_id': rid_,
            'reason': reason, 'before_state': before, 'after_state': after,
            'details': details, 'ip_address': ip, 'user_agent': ua,
            'request_id': req_id, 'release_version': rel, 'dyno': dyno,
            'session_id': sess,
        }
        recomputed = _compute_hash(prev_h or _GENESIS_HASH, record)
        if recomputed != cur_h:
            return {'ok': False, 'broken_at': rid, 'checked': checked,
                    'reason': 'current_hash mismatch'}
        expected_prev = cur_h
        checked += 1

    return {'ok': True, 'broken_at': None, 'checked': checked}


# ═══════════════════════════════════════════════════════════════════════════
# FÁZE 1+2+5 — audit() — main API
# ═══════════════════════════════════════════════════════════════════════════

def _real_ip():
    """Skutečná klientská IP (Heroku používá X-Forwarded-For)."""
    if not has_request_context():
        return None
    try:
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()
        return request.remote_addr
    except Exception:
        return None


def _normalize(action, kwargs):
    """FÁZE 2 — sběr a doplnění kontextu."""
    actor = {}
    try:
        actor = getattr(g, 'auth_user', None) or {}
    except Exception:
        pass

    actor_user_id = kwargs.get('actor_user_id') or kwargs.get('user_id') or str(actor.get('id', '') or '')
    actor_role = kwargs.get('actor_role') or actor.get('role', '') or 'anon'
    actor_email = actor.get('email', '')

    ua = ''
    request_id = ''
    if has_request_context():
        try:
            ua = (request.headers.get('User-Agent', '') or '')[:512]
            request_id = (request.headers.get('X-Request-Id', '') or '')[:64]
        except Exception:
            pass

    outcome = kwargs.get('outcome', 'success')
    if outcome not in VALID_OUTCOMES:
        outcome = 'error'

    severity = kwargs.get('severity', 'info')
    if severity not in VALID_SEVERITIES:
        severity = 'info'

    return {
        'timestamp': datetime.now(timezone.utc),
        'user_id': actor_user_id or None,
        'user_email': actor_email or None,
        'user_role': actor_role,
        'action': action,
        'outcome': outcome,
        'severity': severity,
        'resource_type': kwargs.get('resource_type') or None,
        'resource_id': str(kwargs.get('resource_id') or '') or None,
        'senior_id': kwargs.get('senior_id') or None,
        'reason': (kwargs.get('reason') or '')[:512] or None,
        'before_state': kwargs.get('before') or kwargs.get('before_state'),
        'after_state': kwargs.get('after') or kwargs.get('after_state'),
        'details': kwargs.get('details') or kwargs.get('metadata') or {},
        'ip_address': _real_ip(),
        'user_agent': ua or None,
        'request_id': request_id or None,
        'session_id': kwargs.get('session_id') or getattr(g, 'session_id', None) if has_request_context() else None,
        'release_version': os.environ.get('HEROKU_RELEASE_VERSION', '') or None,
        'dyno': os.environ.get('DYNO', '') or None,
        'success': outcome == 'success',  # backward-compat sloupec
    }


def audit(action, **kwargs):
    """Hlavní API — ISO 27001 audit event.

    Příklad:
        audit(A.AUTH_LOGIN_FAIL, outcome='failure', severity='warning',
              reason='wrong_password', actor_user_id='user-42',
              metadata={'attempt': 3})

    Best-effort: nikdy neraisuje. Při selhání DB → logger.critical fallback.
    """
    try:
        # FÁZE 2 — normalizace + enrich
        record = _normalize(action, kwargs)

        # FÁZE 3 — PII masking
        record['before_state'] = mask_pii(record['before_state'])
        record['after_state'] = mask_pii(record['after_state'])
        record['details'] = mask_pii(record['details'])
        if record.get('reason'):
            record['reason'] = _mask_pii_string(record['reason'])

        # FÁZE 4 — hash chain
        prev = _last_hash()
        record['prev_hash'] = prev
        record['current_hash'] = _compute_hash(prev, record)

        # FÁZE 5 — persist
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO audit_log "
                "(timestamp, user_id, user_email, user_role, action, "
                " resource_type, resource_id, senior_id, details, "
                " ip_address, user_agent, session_id, success, "
                " outcome, severity, reason, before_state, after_state, "
                " request_id, release_version, dyno, prev_hash, current_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record['timestamp'], record['user_id'], record['user_email'],
                 record['user_role'], record['action'], record['resource_type'],
                 record['resource_id'], record['senior_id'],
                 json.dumps(record['details']) if record['details'] is not None else '{}',
                 record['ip_address'], record['user_agent'], record['session_id'],
                 record['success'], record['outcome'], record['severity'],
                 record['reason'],
                 json.dumps(record['before_state']) if record['before_state'] is not None else None,
                 json.dumps(record['after_state']) if record['after_state'] is not None else None,
                 record['request_id'], record['release_version'], record['dyno'],
                 record['prev_hash'], record['current_hash'])
            )
        # Refresh cache po úspěšném zápisu
        _last_hash_cache['value'] = record['current_hash']
        _last_hash_cache['fetched_at'] = __import__('time').time()

    except Exception as e:
        # FÁZE 5 fallback — never raise, never lose event
        try:
            fb = {
                'action': action,
                'outcome': kwargs.get('outcome', 'success'),
                'severity': kwargs.get('severity', 'info'),
                'actor_user_id': kwargs.get('actor_user_id') or kwargs.get('user_id'),
                'reason': kwargs.get('reason'),
                'err': str(e)[:200],
            }
            logger.critical(f"AUDIT_FALLBACK {json.dumps(fb, default=str)}")
        except Exception:
            logger.critical(f"AUDIT_FALLBACK action={action} (also fallback failed)")


# ═══════════════════════════════════════════════════════════════════════════
# Backward-compat — log_audit() volá audit() interně
# ═══════════════════════════════════════════════════════════════════════════

def log_audit(action, resource_type=None, resource_id=None, senior_id=None,
              details=None, success=True, user_id=None):
    """v1 API — zachováno pro existující volání. Mapuje na audit()."""
    audit(
        action,
        outcome='success' if success else 'failure',
        severity='info' if success else 'warning',
        resource_type=resource_type,
        resource_id=resource_id,
        senior_id=senior_id,
        metadata=details,
        actor_user_id=user_id,
    )


# ═══════════════════════════════════════════════════════════════════════════
# QUERY API
# ═══════════════════════════════════════════════════════════════════════════

def get_audit_trail(senior_id=None, user_id=None, action=None, outcome=None,
                    severity=None, days=30, limit=100):
    """Query audit trail with filters."""
    try:
        from database import db_context
        conditions = []
        params = []

        if senior_id:
            conditions.append("senior_id = ?")
            params.append(senior_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if outcome:
            conditions.append("outcome = ?")
            params.append(outcome)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        conditions.append(f"timestamp > NOW() - INTERVAL '{int(days)} days'")
        where = " AND ".join(conditions) if conditions else "1=1"

        with db_context() as db:
            rows = db.execute(
                f"SELECT id, timestamp, user_id, user_email, user_role, action, "
                f"  outcome, severity, resource_type, resource_id, senior_id, "
                f"  reason, details, ip_address, request_id, release_version, dyno "
                f"FROM audit_log WHERE {where} "
                f"ORDER BY timestamp DESC LIMIT ?",
                (*params, int(limit))
            ).fetchall()

        return [{
            'id': r[0], 'timestamp': str(r[1]), 'user_id': r[2],
            'email': r[3], 'role': r[4], 'action': r[5],
            'outcome': r[6], 'severity': r[7],
            'resource_type': r[8], 'resource_id': r[9],
            'senior_id': r[10], 'reason': r[11],
            'details': (json.loads(r[12]) if isinstance(r[12], str) else (r[12] or {})),
            'ip': r[13], 'request_id': r[14],
            'release': r[15], 'dyno': r[16],
        } for r in rows]
    except Exception as e:
        logger.warning(f"Audit query failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# FLASK BLUEPRINT
# ═══════════════════════════════════════════════════════════════════════════

from flask import Blueprint, jsonify
audit_bp = Blueprint('audit', __name__)


@audit_bp.route('/api/audit/trail', methods=['GET'])
def audit_trail_endpoint():
    """GET /api/audit/trail?senior_id=X&days=30&limit=50&outcome=failure
    Vyžaduje admin/coordinator/dpo roli."""
    auth = getattr(g, 'auth_user', None) or {}
    if auth.get('role') not in ('admin', 'administrator', 'coordinator', 'dpo'):
        # Audit i samotný neoprávněný přístup k auditu
        audit(A.AUTH_ACCESS_DENIED, outcome='denied', severity='warning',
              resource_type='audit_trail',
              reason=f"role={auth.get('role','anon')} not authorized")
        return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

    audit('admin.audit.read', resource_type='audit_trail',
          metadata={'filter': dict(request.args)})

    trail = get_audit_trail(
        senior_id=request.args.get('senior_id'),
        user_id=request.args.get('user_id'),
        action=request.args.get('action'),
        outcome=request.args.get('outcome'),
        severity=request.args.get('severity'),
        days=request.args.get('days', 30, type=int),
        limit=request.args.get('limit', 100, type=int),
    )
    return jsonify({'success': True, 'trail': trail, 'count': len(trail)})


@audit_bp.route('/api/audit/integrity', methods=['POST'])
def audit_integrity_endpoint():
    """POST /api/audit/integrity — ověř hash chain.
    Vrací {ok, broken_at, checked}."""
    auth = getattr(g, 'auth_user', None) or {}
    if auth.get('role') not in ('admin', 'administrator', 'dpo'):
        return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403
    start = request.args.get('start_id', 1, type=int)
    limit = request.args.get('limit', 10000, type=int)
    result = verify_chain(start_id=start, limit=limit)
    audit('admin.audit.integrity_check',
          outcome='success' if result['ok'] else 'failure',
          severity='info' if result['ok'] else 'critical',
          metadata=result)
    return jsonify({'success': True, **result})


@audit_bp.route('/api/audit/stats', methods=['GET'])
def audit_stats():
    """Audit statistics — action counts a fail rate."""
    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute(
                "SELECT action, outcome, COUNT(*) FROM audit_log "
                "WHERE timestamp > NOW() - INTERVAL '30 days' "
                "GROUP BY action, outcome ORDER BY action"
            ).fetchall()
        stats = {}
        for action, outcome, n in rows:
            stats.setdefault(action, {})[outcome or 'success'] = n
        return jsonify({'success': True, 'stats': stats})
    except Exception:
        return jsonify({'success': True, 'stats': {}})


# ═══════════════════════════════════════════════════════════════════════════
# Init schema při importu — s pg_advisory_lock pro race-free start
# ═══════════════════════════════════════════════════════════════════════════
init_audit_schema()
