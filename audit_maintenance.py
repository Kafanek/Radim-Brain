"""
📋 AUDIT MAINTENANCE — denní úlohy nad audit_log
==================================================

Scheduled jobs:
  • integrity_check  — denně 02:30 UTC
       Ověří hash chain pro nedávné dny (rolling 7 dní default).
       Pokud detekuje break, vystřelí audit('admin.audit.tamper_detected',
       severity='critical') + admin notifikaci.

  • retention_cleanup — denně 03:30 UTC
       Záznamy >365 dní:
         1. Export do JSONL souboru (volitelně S3 přes ARCHIVE_S3_BUCKET)
         2. INSERT do archivního souboru (off-server přes streaming)
         3. DELETE z hot tabulky
       Pokud chybí storage, jen DELETE (logika: kdo nezálohoval, nemá co
       archivovat). Pro produkci doporučeno nastavit AUDIT_S3_BUCKET +
       AWS_ACCESS_KEY_ID, jinak retention=DELETE-only.
"""

import logging
import os
import json
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Integrity check
# ═══════════════════════════════════════════════════════════════════════════

def run_integrity_check(window_days=7):
    """Verifikuj hash chain za posledních N dní.

    Vrací: dict {ok, broken_at, checked, window_days}
    """
    from audit_log import verify_chain, audit
    try:
        from database import db_context

        # Najdi první id v okně (index na timestamp DESC takže rychlé)
        with db_context() as db:
            row = db.execute(
                "SELECT MIN(id) FROM audit_log "
                f"WHERE created_at > NOW() - INTERVAL '{int(window_days)} days' "
                "AND current_hash IS NOT NULL"
            ).fetchone()
            start_id = (row[0] if row and row[0] else 1)

        result = verify_chain(start_id=start_id, limit=200000)
        result['window_days'] = window_days
        result['start_id'] = start_id

        if result['ok']:
            audit('admin.audit.integrity_check',
                  outcome='success', severity='info',
                  metadata={'checked': result['checked'],
                            'window_days': window_days})
            logger.info(f"📋 Audit integrity OK: {result['checked']} records in last {window_days}d")
        else:
            # Tamper detected — kritická událost
            audit('admin.audit.tamper_detected',
                  outcome='failure', severity='critical',
                  reason=result.get('reason', 'unknown'),
                  metadata={'broken_at': result['broken_at'],
                            'checked': result['checked'],
                            'window_days': window_days})
            logger.critical(f"🚨 AUDIT TAMPER DETECTED at id={result['broken_at']} "
                            f"(reason={result.get('reason')})")
            # Notifikuj admina (best-effort) — pošleme push všem s rolí admin
            try:
                from database import db_context
                from notification_helpers import notify
                with db_context() as db:
                    admins = db.execute(
                        "SELECT id FROM auth_users WHERE role IN ('admin','administrator','dpo')"
                    ).fetchall() or []
                for a in admins:
                    admin_id = a[0]
                    try:
                        notify(to_user_id=str(admin_id), type='security',
                               severity='crisis',
                               title='🚨 AUDIT INTEGRITY BREACH',
                               body=f"audit_log row {result['broken_at']} — "
                                    f"{result.get('reason')}",
                               data={'audit_id': result['broken_at'],
                                     'reason': result.get('reason')})
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Could not notify admins of tamper: {e}")

        return result
    except Exception as e:
        logger.error(f"Audit integrity check failed: {e}")
        return {'ok': False, 'error': str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════════
# Retention cleanup
# ═══════════════════════════════════════════════════════════════════════════

# ISO 27001 doporučuje 1 rok hot, dále archive.
# CZ zdravotnictví: 7 let (Zákon o zdravotních službách §53).
HOT_RETENTION_DAYS = int(os.environ.get('AUDIT_HOT_RETENTION_DAYS', '365'))
ARCHIVE_DIR = os.environ.get('AUDIT_ARCHIVE_DIR', '/tmp/audit_archive')
ARCHIVE_S3_BUCKET = os.environ.get('AUDIT_S3_BUCKET', '')


def _archive_to_jsonl(rows, timestamp_iso):
    """Zapíše batch do JSONL souboru (lokálně v ARCHIVE_DIR).

    Pokud je nakonfigurovaný S3 bucket, nahraje tam (jinak jen lokálně —
    na Heroku je to ephemeral, takže pro produkci je S3 nutnost).
    """
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
    except Exception as e:
        logger.warning(f"Cannot create archive dir: {e}")
        return False

    fname = f"audit_archive_{timestamp_iso}.jsonl"
    fpath = os.path.join(ARCHIVE_DIR, fname)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(row, default=str, ensure_ascii=False) + '\n')
        logger.info(f"📋 Audit archive written: {fpath} ({len(rows)} rows)")
    except Exception as e:
        logger.error(f"Audit archive write failed: {e}")
        return False

    # S3 upload (volitelné)
    if ARCHIVE_S3_BUCKET:
        try:
            import boto3
            s3 = boto3.client('s3')
            s3.upload_file(fpath, ARCHIVE_S3_BUCKET, f"audit/{fname}")
            logger.info(f"📋 Audit archive uploaded to s3://{ARCHIVE_S3_BUCKET}/audit/{fname}")
            os.remove(fpath)  # Po úspěšném uploadu smaž lokál
        except Exception as e:
            logger.warning(f"S3 upload failed (keeping local): {e}")

    return True


def run_retention_cleanup(retention_days=None, batch_size=1000):
    """Archivuj a smaž audit_log řádky starší než retention_days.

    Vrací: {archived, deleted, retention_days}
    """
    from audit_log import audit
    days = retention_days if retention_days is not None else HOT_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.strftime('%Y%m%d_%H%M%S')

    archived = 0
    deleted = 0

    try:
        from database import db_context, is_postgres

        while True:
            with db_context(commit=True) as db:
                if is_postgres():
                    rows = db.execute(
                        "SELECT id, created_at, user_id, user_email, user_role, "
                        "  action, outcome, severity, resource_type, resource_id, "
                        "  senior_id, reason, before_state, after_state, details, "
                        "  ip_address, user_agent, session_id, request_id, "
                        "  release_version, dyno, prev_hash, current_hash "
                        "FROM audit_log "
                        f"WHERE created_at < NOW() - INTERVAL '{int(days)} days' "
                        "ORDER BY id ASC LIMIT ?",
                        (batch_size,)
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT id, created_at, user_id, user_email, user_role, "
                        "  action, outcome, severity, resource_type, resource_id, "
                        "  senior_id, reason, before_state, after_state, details, "
                        "  ip_address, user_agent, session_id, request_id, "
                        "  release_version, dyno, prev_hash, current_hash "
                        "FROM audit_log "
                        f"WHERE created_at < datetime('now', '-{int(days)} days') "
                        "ORDER BY id ASC LIMIT ?",
                        (batch_size,)
                    ).fetchall()

                if not rows:
                    break

                # Archivuj (best-effort)
                batch = [{
                    'id': r[0], 'timestamp': str(r[1]), 'user_id': r[2],
                    'user_email': r[3], 'user_role': r[4], 'action': r[5],
                    'outcome': r[6], 'severity': r[7], 'resource_type': r[8],
                    'resource_id': r[9], 'senior_id': r[10], 'reason': r[11],
                    'before_state': r[12], 'after_state': r[13], 'details': r[14],
                    'ip_address': r[15], 'user_agent': r[16], 'session_id': r[17],
                    'request_id': r[18], 'release_version': r[19], 'dyno': r[20],
                    'prev_hash': r[21], 'current_hash': r[22],
                } for r in rows]

                if _archive_to_jsonl(batch, cutoff_iso):
                    archived += len(batch)

                # Smaž z hot tabulky.
                # Pokud existuje audit_log_archive_delete (SECURITY DEFINER),
                # použij ji — ta dočasně suspenduje no-delete trigger.
                # Jinak fallback na přímý DELETE (selže pokud je trigger
                # nainstalovaný, což je správné chování — admin musí
                # explicitně povolit).
                ids = [r[0] for r in rows]
                try:
                    if is_postgres():
                        cur = db.execute(
                            "SELECT audit_log_archive_delete(?::BIGINT[])",
                            (ids,)
                        )
                        row = cur.fetchone() if hasattr(cur, 'fetchone') else None
                        deleted_n = row[0] if row else len(ids)
                    else:
                        placeholders = ','.join(['?'] * len(ids))
                        cur = db.execute(
                            f"DELETE FROM audit_log WHERE id IN ({placeholders})",
                            tuple(ids)
                        )
                        deleted_n = cur.rowcount if hasattr(cur, 'rowcount') else len(ids)
                except Exception as del_err:
                    logger.warning(f"Audit archive_delete failed: {del_err}")
                    deleted_n = 0
                deleted += deleted_n

            if len(rows) < batch_size:
                break

        if deleted > 0 or archived > 0:
            audit('admin.audit.retention_cleanup',
                  outcome='success', severity='info',
                  metadata={'archived': archived, 'deleted': deleted,
                            'retention_days': days})
            logger.info(f"📋 Audit retention: archived {archived}, deleted {deleted} (>{days}d)")
        else:
            logger.debug("📋 Audit retention: nothing to clean")

        return {'archived': archived, 'deleted': deleted, 'retention_days': days}
    except Exception as e:
        logger.error(f"Audit retention failed: {e}")
        try:
            audit('admin.audit.retention_cleanup',
                  outcome='error', severity='warning',
                  reason=str(e)[:200],
                  metadata={'archived': archived, 'deleted': deleted})
        except Exception:
            pass
        return {'archived': archived, 'deleted': deleted, 'error': str(e)[:200]}
