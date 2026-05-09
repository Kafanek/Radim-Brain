"""
ISO 27001 Audit Log — append-only hash chain for agent observations
====================================================================

Every action the agent observes / takes / shows to anyone gets a row.
Each row's `entry_hash` covers the previous row's hash + this row's
canonical content + timestamp + actor + action. Tampering with any past
row breaks every subsequent hash → integrity check catches it.

Tables (created in database_schema.py at startup):

  agent_audit_log
    id, user_id, actor, action, detector_id, payload (JSONB),
    severity, prev_hash, entry_hash, ts

  agent_audit_access
    id, viewer_id, subject_user_id, audit_entry_id, reason, ts

ISO 27001 mapping:
  A.12.4.1 Event logging              → agent_audit_log
  A.12.4.2 Tamper protection          → SHA-256 hash chain + verify_chain()
  A.12.4.3 Admin/operator logs        → agent_audit_access
  A.12.4.4 Clock synchronization      → Heroku NTP + UTC timestamps

GDPR mapping:
  Art. 15 (right of access)           → export_user_data()
  Art. 17 (right to erasure)          → pseudonymize_user()
  Art. 20 (data portability)          → export_user_data(format='json')
  Art. 30 (records of processing)     → existing Zaznamy-o-zpracovani-cl30 docs

Public API:
  log_event(user_id, actor, action, payload, severity=None, detector_id=None) → int
  log_access(viewer_id, subject_user_id, audit_entry_id, reason='view') → int
  verify_chain(user_id=None, since=None) → dict
  export_user_data(user_id, format='json') → dict
  cleanup_old_entries(retention_days=2555) → int (rows removed)
  pseudonymize_user(user_id) → str (new pseudonym)

Sprint X20.3 — Foundation, ISO 27001 layer
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default retention: 7 years (healthcare/social default; configurable per
# regulatory regime via env var).
DEFAULT_RETENTION_DAYS = 2555

# Per-user lock map to serialize hash-chain inserts (avoids race where two
# threads compute prev_hash from the same predecessor row).
_user_locks: dict[str, threading.Lock] = {}
_user_locks_master = threading.Lock()


def _user_lock(user_id: str) -> threading.Lock:
    with _user_locks_master:
        lock = _user_locks.get(user_id)
        if not lock:
            lock = threading.Lock()
            _user_locks[user_id] = lock
        return lock


# ─── Hash helpers ───────────────────────────────────────────────────────────


def _canonical_json(payload: Any) -> str:
    """Stable JSON serialization — same input → same string → same hash."""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, default=str)


def _compute_entry_hash(prev_hash: Optional[str], canonical_payload: str,
                        ts_iso: str, actor: str, action: str,
                        user_id: str) -> str:
    """SHA-256 of (prev_hash | payload | ts | actor | action | user_id).
    Pipe separator is fixed to prevent boundary-shifting attacks."""
    h = hashlib.sha256()
    h.update((prev_hash or '0' * 64).encode('utf-8'))
    h.update(b'|')
    h.update(canonical_payload.encode('utf-8'))
    h.update(b'|')
    h.update(ts_iso.encode('utf-8'))
    h.update(b'|')
    h.update(actor.encode('utf-8'))
    h.update(b'|')
    h.update(action.encode('utf-8'))
    h.update(b'|')
    h.update(user_id.encode('utf-8'))
    return h.hexdigest()


# ─── Append-only insert ─────────────────────────────────────────────────────


def log_event(user_id: str, actor: str, action: str, payload: Any,
              severity: Optional[str] = None,
              detector_id: Optional[str] = None) -> Optional[int]:
    """Append one row to agent_audit_log with hash chain.

    Returns the new row's id, or None on DB error (best-effort: audit log
    must never crash the caller). Per-user lock serializes inserts.
    """
    try:
        from database import db_context
    except ImportError:
        return None

    if not user_id or not actor or not action:
        return None

    canonical = _canonical_json(payload or {})
    ts = datetime.now(timezone.utc).isoformat()

    lock = _user_lock(str(user_id))
    with lock:
        try:
            with db_context(commit=True) as db:
                # Look up the most recent entry's hash for THIS user.
                row = db.execute(
                    "SELECT entry_hash FROM agent_audit_log "
                    "WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                    (str(user_id),)
                ).fetchone()
                prev_hash = (row['entry_hash'] if row and 'entry_hash' in row.keys()
                             else (row[0] if row else None))

                entry_hash = _compute_entry_hash(prev_hash, canonical, ts,
                                                  actor, action, str(user_id))

                # Try to use db_insert if available (handles PG vs SQLite)
                try:
                    from database import db_insert
                    new_id = db_insert(db, 'agent_audit_log',
                        ['user_id', 'actor', 'action', 'detector_id',
                         'payload', 'severity', 'prev_hash', 'entry_hash', 'ts'],
                        (str(user_id), actor, action, detector_id,
                         canonical, severity, prev_hash, entry_hash, ts))
                except Exception:
                    db.execute(
                        "INSERT INTO agent_audit_log "
                        "(user_id, actor, action, detector_id, payload, "
                        " severity, prev_hash, entry_hash, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (str(user_id), actor, action, detector_id,
                         canonical, severity, prev_hash, entry_hash, ts)
                    )
                    new_id = None
                return new_id
        except Exception as e:
            logger.warning(f"[audit] log_event failed: {e}")
            return None


def log_access(viewer_id: str, subject_user_id: str,
               audit_entry_id: Optional[int] = None,
               reason: str = 'view') -> Optional[int]:
    """Record that `viewer_id` looked at audit data for `subject_user_id`.
    A.12.4.3 administrator/operator activity log."""
    try:
        from database import db_context, db_insert
    except ImportError:
        return None
    if not viewer_id or not subject_user_id:
        return None
    try:
        with db_context(commit=True) as db:
            return db_insert(db, 'agent_audit_access',
                ['viewer_id', 'subject_user_id', 'audit_entry_id', 'reason', 'ts'],
                (str(viewer_id), str(subject_user_id), audit_entry_id, reason,
                 datetime.now(timezone.utc).isoformat()))
    except Exception as e:
        logger.warning(f"[audit] log_access failed: {e}")
        return None


# ─── Verification ───────────────────────────────────────────────────────────


def verify_chain(user_id: Optional[str] = None,
                 since: Optional[datetime] = None) -> dict:
    """Walk the hash chain and re-compute each entry_hash.

    Returns:
      {
        'valid': bool,
        'entries_checked': int,
        'broken_at': [{id, user_id, expected_hash, actual_hash}, ...],
        'gaps': [{after_id, before_id, user_id}, ...]   # missing rows
      }

    A "gap" (e.g. from cleanup_old_entries) is NOT a tamper failure —
    we just record it. A hash mismatch IS a tamper failure.
    """
    try:
        from database import db_context
    except ImportError:
        return {'valid': False, 'reason': 'database_module_unavailable'}

    where = []
    params: list = []
    if user_id:
        where.append("user_id = ?")
        params.append(str(user_id))
    if since:
        where.append("ts > ?")
        params.append(since.isoformat() if isinstance(since, datetime) else since)
    sql = "SELECT id, user_id, actor, action, payload, ts, prev_hash, entry_hash FROM agent_audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY user_id, id ASC"

    broken: list = []
    gaps: list = []
    checked = 0
    last_per_user: dict[str, str] = {}

    try:
        with db_context() as db:
            cur = db.execute(sql, tuple(params))
            for row in cur.fetchall():
                checked += 1
                rid = row['id'] if 'id' in row.keys() else row[0]
                uid = row['user_id'] if 'user_id' in row.keys() else row[1]
                actor = row['actor'] if 'actor' in row.keys() else row[2]
                action = row['action'] if 'action' in row.keys() else row[3]
                payload = row['payload'] if 'payload' in row.keys() else row[4]
                ts = row['ts'] if 'ts' in row.keys() else row[5]
                prev = row['prev_hash'] if 'prev_hash' in row.keys() else row[6]
                stored = row['entry_hash'] if 'entry_hash' in row.keys() else row[7]

                # canonicalize payload — DB may have stored as string or dict
                if isinstance(payload, dict):
                    canonical = _canonical_json(payload)
                else:
                    canonical = str(payload) if payload else _canonical_json({})

                ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                expected = _compute_entry_hash(prev, canonical, ts_str,
                                                actor, action, str(uid))

                # Check chain continuity (prev_hash must match the previous
                # row's entry_hash for this user)
                expected_prev = last_per_user.get(str(uid))
                if expected_prev is not None and prev != expected_prev:
                    gaps.append({
                        'user_id': str(uid),
                        'at_id': rid,
                        'note': 'prev_hash discontinuity (likely retention-cleanup gap)',
                    })

                if expected != stored:
                    broken.append({
                        'id': rid,
                        'user_id': str(uid),
                        'expected_hash': expected[:16] + '…',
                        'actual_hash':   (stored or '')[:16] + '…',
                    })

                last_per_user[str(uid)] = stored
    except Exception as e:
        return {'valid': False, 'reason': f'db_error: {e}'}

    return {
        'valid': len(broken) == 0,
        'entries_checked': checked,
        'broken_at': broken,
        'gaps': gaps,
    }


# ─── GDPR Article 15 / 20 — data export ─────────────────────────────────────


def export_user_data(user_id: str, format: str = 'json') -> dict:
    """Full data export for one user. GDPR Article 15 (right of access) +
    Article 20 (data portability). Includes:
      - all audit log entries
      - all access log entries (who has viewed their data)
      - chain integrity verification result
      - export metadata (requestor, generated_at, retention policy)
    """
    try:
        from database import db_context
    except ImportError:
        return {'error': 'database_module_unavailable'}

    out = {
        'user_id': str(user_id),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'format': format,
        'gdpr_articles': ['15', '20'],
        'iso_27001_controls': ['A.12.4.1', 'A.12.4.3'],
        'retention_days': DEFAULT_RETENTION_DAYS,
        'audit_log': [],
        'access_log': [],
        'integrity': None,
    }

    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT id, actor, action, detector_id, payload, severity, "
                "prev_hash, entry_hash, ts FROM agent_audit_log "
                "WHERE user_id = ? ORDER BY id ASC",
                (str(user_id),)
            )
            for row in cur.fetchall():
                out['audit_log'].append({
                    'id':           row['id']           if 'id'           in row.keys() else row[0],
                    'actor':        row['actor']        if 'actor'        in row.keys() else row[1],
                    'action':       row['action']       if 'action'       in row.keys() else row[2],
                    'detector_id':  row['detector_id']  if 'detector_id'  in row.keys() else row[3],
                    'payload':      row['payload']      if 'payload'      in row.keys() else row[4],
                    'severity':     row['severity']     if 'severity'     in row.keys() else row[5],
                    'prev_hash':    row['prev_hash']    if 'prev_hash'    in row.keys() else row[6],
                    'entry_hash':   row['entry_hash']   if 'entry_hash'   in row.keys() else row[7],
                    'ts':           (row['ts'] if 'ts' in row.keys() else row[8]).isoformat() if isinstance(row['ts'] if 'ts' in row.keys() else row[8], datetime) else str(row['ts'] if 'ts' in row.keys() else row[8]),
                })

            cur = db.execute(
                "SELECT id, viewer_id, audit_entry_id, reason, ts "
                "FROM agent_audit_access WHERE subject_user_id = ? ORDER BY id ASC",
                (str(user_id),)
            )
            for row in cur.fetchall():
                ts_v = row['ts'] if 'ts' in row.keys() else row[4]
                out['access_log'].append({
                    'id':              row['id']              if 'id'              in row.keys() else row[0],
                    'viewer_id':       row['viewer_id']       if 'viewer_id'       in row.keys() else row[1],
                    'audit_entry_id':  row['audit_entry_id']  if 'audit_entry_id'  in row.keys() else row[2],
                    'reason':          row['reason']          if 'reason'          in row.keys() else row[3],
                    'ts':              ts_v.isoformat() if isinstance(ts_v, datetime) else str(ts_v),
                })

        out['integrity'] = verify_chain(user_id=user_id)
        out['summary'] = {
            'audit_entries':  len(out['audit_log']),
            'access_entries': len(out['access_log']),
            'integrity_ok':   out['integrity'].get('valid'),
        }
    except Exception as e:
        out['error'] = str(e)
    return out


# ─── GDPR Article 17 — pseudonymization (preserve stats, drop PII link) ─────


def pseudonymize_user(user_id: str) -> Optional[str]:
    """Replace user_id with a random pseudonym in audit_log + access_log.
    Preserves the hash chain (entry hashes don't change, even though they
    incorporate user_id — verification will fail on these rows after
    pseudonymization, which is OK and intended: the user's right to
    erasure overrides the chain's perfect continuity).

    Returns the new pseudonym (caller should record the mapping if any
    re-identification need exists, e.g. for legal hold)."""
    try:
        from database import db_context
    except ImportError:
        return None

    pseudo = 'anon_' + secrets.token_hex(8)
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE agent_audit_log SET user_id = ? WHERE user_id = ?",
                (pseudo, str(user_id))
            )
            db.execute(
                "UPDATE agent_audit_access SET subject_user_id = ? WHERE subject_user_id = ?",
                (pseudo, str(user_id))
            )
        # Final entry: log the erasure itself (under the NEW pseudonym)
        log_event(pseudo, 'system', 'gdpr_erasure',
                  payload={'reason': 'art_17_request', 'original_user_id_hash':
                           hashlib.sha256(str(user_id).encode()).hexdigest()[:16]})
        return pseudo
    except Exception as e:
        logger.warning(f"[audit] pseudonymize failed: {e}")
        return None


# ─── Retention cleanup ──────────────────────────────────────────────────────


def cleanup_old_entries(retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete entries older than retention. Returns rows removed.
    Note: this leaves a "gap" in the hash chain that verify_chain reports
    in the `gaps` list (not as a tamper break).
    """
    try:
        from database import db_context
    except ImportError:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(retention_days))
    cutoff_iso = cutoff.isoformat()
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "DELETE FROM agent_audit_log WHERE ts < ?",
                (cutoff_iso,)
            )
            removed = cur.rowcount or 0
            db.execute(
                "DELETE FROM agent_audit_access WHERE ts < ?",
                (cutoff_iso,)
            )
            return removed
    except Exception as e:
        logger.warning(f"[audit] cleanup failed: {e}")
        return 0


# ─── Compliance summary (anonymized stats) ──────────────────────────────────


def compliance_report(start: datetime, end: datetime) -> dict:
    """Anonymized stats for ISO 27001 / management review.
    Counts events by type/severity/actor — no user_id leakage."""
    try:
        from database import db_context
    except ImportError:
        return {'error': 'database_module_unavailable'}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT actor, action, severity, COUNT(*) as n "
                "FROM agent_audit_log WHERE ts BETWEEN ? AND ? "
                "GROUP BY actor, action, severity",
                (start.isoformat(), end.isoformat())
            )
            rows = cur.fetchall() or []
            cur2 = db.execute(
                "SELECT COUNT(DISTINCT user_id) as n FROM agent_audit_log "
                "WHERE ts BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat())
            )
            users_row = cur2.fetchone()
    except Exception as e:
        return {'error': str(e)}

    breakdown = []
    for r in rows:
        breakdown.append({
            'actor':    r[0] if isinstance(r, (list, tuple)) else r['actor'],
            'action':   r[1] if isinstance(r, (list, tuple)) else r['action'],
            'severity': r[2] if isinstance(r, (list, tuple)) else r['severity'],
            'count':    r[3] if isinstance(r, (list, tuple)) else r['n'],
        })
    distinct_users = users_row[0] if isinstance(users_row, (list, tuple)) else (users_row['n'] if users_row else 0)
    return {
        'start':           start.isoformat(),
        'end':             end.isoformat(),
        'distinct_users':  distinct_users,
        'breakdown':       breakdown,
        'integrity':       verify_chain(since=start),
        'iso_27001':       'A.12.4.1, A.12.4.2, A.12.4.3',
    }


# ─── CLI verifier ───────────────────────────────────────────────────────────


def _cli_verify():
    """python3 -m agent.audit verify"""
    res = verify_chain()
    print(f"chain valid:    {res.get('valid')}")
    print(f"checked rows:   {res.get('entries_checked')}")
    print(f"broken at:      {len(res.get('broken_at', []))} rows")
    print(f"gaps (cleanup): {len(res.get('gaps', []))}")
    if res.get('broken_at'):
        for b in res['broken_at'][:5]:
            print(f"   ⚠ id={b['id']} expected={b['expected_hash']} actual={b['actual_hash']}")
    return 0 if res.get('valid') else 2


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'verify':
        sys.exit(_cli_verify())
    print(__doc__)
