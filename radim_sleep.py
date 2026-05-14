"""
🌙 RADIM SLEEP — nightly memory hygiene + dream consolidation

X21.22: Runs nightly at 3 AM as an extension to agent_loop.run_daily_cleanup.

Three jobs in one place, all auditable:

  1. PRUNE   — drop expired data from grow-only tables
  2. FILTER  — remove "bad logs" (failed AI calls, empty entries, orphan obs)
  3. CONSOLIDATE — force summarization for users whose long-term context is stale
  4. VACUUM  — PG: VACUUM ANALYZE to reclaim space (skipped on SQLite)

Each phase logs its result + writes an audit_log entry so caregivers / admins
can verify what got cleaned. Safe to re-run — every operation is idempotent.

Tables touched (retention rationale in code comments):

  memory_history        — auto-trimmed on insert (MAX_HISTORY=50), no batch op here
  identity_activations  — 60d  (research / evolution data; older is noise)
  brain_feedback        — 30d  (loop closed within hours, older is stale)
  brain_adaptation      — 180d (long-term per-user tuning, keep more)
  user_notifications    — 14d  if delivered+read; 60d otherwise
  iot_sensor_data       — 7d   raw sensor; agent_loop reads aggregates only
  crisis_events         — KEEP ALL (safety audit, GDPR-friendly already)
  sos_events            — KEEP ALL (same)
  audit_log             — managed separately by audit_maintenance (1-year retention)

"Bad logs":
  - memory_history rows where assistant content matches known error fallbacks
    ("Omlouvám se, zkuste to prosím později.", "Nastala chyba…", etc.)
  - identity_activations with empty `text`
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Known assistant error-fallback strings across 5 languages. If memory_history
# stored one of these as Radim's response, the user got nothing useful. We
# drop these rows so they don't get summarized into long-term context as
# "Radim's tone" or count as real interactions in learning stats.
_BAD_RESPONSE_NEEDLES = (
    # CS
    "Omlouvám se, zkuste to prosím později.",
    "Nastala chyba, omlouvám se.",
    "Promiňte, nerozuměl jsem.",
    "Omlouvám se, nepodařilo se mi odpovědět.",
    "Omlouvám se, momentálně nejsem dostupný.",
    "Omlouvám se, nastala chyba.",
    "Dobrý den, momentálně nejsem dostupný. Zkuste to prosím později.",
    "Omlouvám se, zkuste to znovu.",
    # SK
    "Ospravedlňujem sa, skúste to prosím neskôr.",
    # PL
    "Przepraszam, spróbuj ponownie później.",
    # HU
    "Sajnálom, kérem próbálja meg később.",
    # EN
    "Sorry, please try again later.",
    "Something went wrong, sorry.",
    "Sorry, I didn't catch that.",
)


# Retention policies (days). Tunable.
RETENTION = {
    "identity_activations": 60,
    "brain_feedback":       30,
    "brain_adaptation":     180,
    "user_notifications_read":  14,   # read_at IS NOT NULL → 14d
    "user_notifications_other": 60,   # everything else → 60d
    "iot_sensor_data":      7,
}


def _safe_delete(label, sql_pg, sql_sqlite, is_pg):
    """Run a DELETE in its own transaction so a failure here doesn't
    poison the next prune. Returns rowcount or 0 on error.

    X21.23: PG aborts the WHOLE transaction on any error (e.g. missing
    column) and refuses subsequent statements until rollback. By isolating
    each delete into its own db_context, one bad query can't cascade.
    """
    from database import db_context
    sql = sql_pg if is_pg else sql_sqlite
    try:
        with db_context(commit=True) as db:
            cur = db.execute(sql)
            n = cur.rowcount if cur else 0
            if n > 0:
                logger.info(f"🌙 [sleep.prune] {label}: {n} rows removed")
            return n
    except Exception as e:
        logger.warning(f"🌙 [sleep.prune] {label} skipped: {str(e)[:120]}")
        return 0


def prune_expired(is_pg):
    """Drop rows older than per-table retention. Each delete is independent.
    Returns dict of counts.
    """
    counts = {}

    PRUNES = [
        ("identity_activations",
         "DELETE FROM identity_activations WHERE fired_at < NOW() - INTERVAL '%d days'" % RETENTION["identity_activations"],
         "DELETE FROM identity_activations WHERE fired_at < datetime('now', '-%d days')" % RETENTION["identity_activations"]),
        ("brain_feedback",
         "DELETE FROM brain_feedback WHERE created_at < NOW() - INTERVAL '%d days'" % RETENTION["brain_feedback"],
         "DELETE FROM brain_feedback WHERE created_at < datetime('now', '-%d days')" % RETENTION["brain_feedback"]),
        ("brain_adaptation",
         "DELETE FROM brain_adaptation WHERE updated_at < NOW() - INTERVAL '%d days'" % RETENTION["brain_adaptation"],
         "DELETE FROM brain_adaptation WHERE updated_at < datetime('now', '-%d days')" % RETENTION["brain_adaptation"]),
        ("iot_sensor_data",
         "DELETE FROM iot_sensor_data WHERE created_at < NOW() - INTERVAL '%d days'" % RETENTION["iot_sensor_data"],
         "DELETE FROM iot_sensor_data WHERE created_at < datetime('now', '-%d days')" % RETENTION["iot_sensor_data"]),
        # user_notifications.read_at IS NOT NULL → read by senior, can drop sooner (14d).
        # The schema has read_at + created_at — no delivered_at column (X21.23 fix).
        ("user_notifications_read",
         "DELETE FROM user_notifications WHERE read_at IS NOT NULL AND read_at < NOW() - INTERVAL '%d days'" % RETENTION["user_notifications_read"],
         "DELETE FROM user_notifications WHERE read_at IS NOT NULL AND read_at < datetime('now', '-%d days')" % RETENTION["user_notifications_read"]),
        # Unread notifications older than 60 days are stale anyway — drop them.
        ("user_notifications_old",
         "DELETE FROM user_notifications WHERE created_at < NOW() - INTERVAL '%d days'" % RETENTION["user_notifications_other"],
         "DELETE FROM user_notifications WHERE created_at < datetime('now', '-%d days')" % RETENTION["user_notifications_other"]),
    ]

    for label, sql_pg, sql_sqlite in PRUNES:
        counts[label] = _safe_delete(label, sql_pg, sql_sqlite, is_pg)

    return counts


def filter_bad_logs(is_pg):
    """Drop entries that are functionally useless. Each query isolated."""
    from database import db_context
    counts = {}

    # 1. Bad assistant responses in memory_history.
    placeholder = "%s" if is_pg else "?"
    where_clauses = " OR ".join(["content LIKE " + placeholder for _ in _BAD_RESPONSE_NEEDLES])
    params = tuple("%" + s + "%" for s in _BAD_RESPONSE_NEEDLES)
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "DELETE FROM memory_history WHERE role IN ('assistant','radim') AND (" + where_clauses + ")",
                params,
            )
            counts["bad_responses"] = cur.rowcount if cur else 0
            if counts["bad_responses"] > 0:
                logger.info(f"🌙 [sleep.filter] {counts['bad_responses']} bad-response rows removed")
    except Exception as e:
        counts["bad_responses"] = 0
        logger.warning(f"🌙 [sleep.filter] bad_responses skipped: {str(e)[:120]}")

    # 2. Empty identity_activations
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "DELETE FROM identity_activations WHERE text IS NULL OR text = ''"
            )
            counts["empty_identity"] = cur.rowcount if cur else 0
    except Exception as e:
        counts["empty_identity"] = 0
        logger.warning(f"🌙 [sleep.filter] empty_identity skipped: {str(e)[:120]}")

    # 3. Orphan user_message rows with no assistant reply (1+ hours old).
    try:
        with db_context(commit=True) as db:
            if is_pg:
                cur = db.execute(
                    "DELETE FROM memory_history WHERE role = 'user' AND id IN ("
                    "  SELECT h1.id FROM memory_history h1 "
                    "  WHERE h1.role = 'user' "
                    "  AND h1.created_at < NOW() - INTERVAL '1 hour' "
                    "  AND NOT EXISTS ("
                    "    SELECT 1 FROM memory_history h2 "
                    "    WHERE h2.user_id = h1.user_id "
                    "    AND h2.role IN ('assistant','radim') "
                    "    AND h2.created_at > h1.created_at "
                    "    AND h2.created_at < h1.created_at + INTERVAL '10 minutes'"
                    "  )"
                    ")"
                )
            else:
                cur = db.execute(
                    "DELETE FROM memory_history WHERE role='user' AND id IN ("
                    "  SELECT h1.id FROM memory_history h1 "
                    "  WHERE h1.role='user' "
                    "  AND h1.created_at < datetime('now', '-1 hour') "
                    "  AND NOT EXISTS ("
                    "    SELECT 1 FROM memory_history h2 "
                    "    WHERE h2.user_id = h1.user_id "
                    "    AND h2.role IN ('assistant','radim') "
                    "    AND h2.created_at > h1.created_at "
                    "    AND h2.created_at < datetime(h1.created_at, '+10 minutes')"
                    "  )"
                    ")"
                )
            counts["orphan_user_msgs"] = cur.rowcount if cur else 0
            if counts["orphan_user_msgs"] > 0:
                logger.info(f"🌙 [sleep.filter] {counts['orphan_user_msgs']} orphan user messages dropped")
    except Exception as e:
        counts["orphan_user_msgs"] = 0
        logger.debug(f"🌙 [sleep.filter] orphan_user_msgs skipped: {str(e)[:120]}")

    return counts


def consolidate_long_term(is_pg):
    """Trigger summarize_user_memory for users whose long-term context is stale.

    Users with >50 raw history rows and no summary OR summary >7 days old
    get re-summarized. Mirrors the natural per-100-message trigger but ensures
    nobody falls through the cracks (e.g. users who hit 50 msgs but didn't
    cross 100).
    """
    from database import db_context
    triggered = 0
    skipped = 0
    rows = []
    try:
        with db_context() as db:
            if is_pg:
                rows = db.execute(
                    "SELECT user_id, COUNT(*) AS n "
                    "FROM memory_history "
                    "WHERE created_at > NOW() - INTERVAL '30 days' "
                    "GROUP BY user_id "
                    "HAVING COUNT(*) > 50"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT user_id, COUNT(*) AS n "
                    "FROM memory_history "
                    "WHERE created_at > datetime('now', '-30 days') "
                    "GROUP BY user_id "
                    "HAVING COUNT(*) > 50"
                ).fetchall()
    except Exception as e:
        logger.warning(f"🌙 [sleep.consolidate] candidate query failed: {str(e)[:120]}")
        return {"triggered": 0, "skipped": 0}

    try:
        from memory_summarization import summarize_user_memory
    except ImportError:
        logger.warning("🌙 [sleep.consolidate] memory_summarization unavailable")
        return {"triggered": 0, "skipped": len(rows or [])}

    for r in rows or []:
        uid = r[0] if not hasattr(r, "get") else r["user_id"]
        try:
            # summarize_user_memory has its own internal threshold check; force=False
            # respects the "don't re-summarize too often" guard.
            result = summarize_user_memory(uid, force=False)
            if result:
                triggered += 1
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
            logger.debug(f"🌙 [sleep.consolidate] {uid} skipped: {e}")

    if triggered or skipped:
        logger.info(f"🌙 [sleep.consolidate] {triggered} users re-summarized, {skipped} skipped")
    return {"triggered": triggered, "skipped": skipped}


def vacuum_postgres(is_pg):
    """Run ANALYZE on PostgreSQL to refresh table statistics after big deletes.
    Skipped on SQLite (auto-vacuum handles it).
    """
    if not is_pg:
        return {"skipped": "sqlite"}
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute("ANALYZE")
        logger.info("🌙 [sleep.vacuum] ANALYZE complete (table statistics refreshed)")
        return {"analyze": "ok"}
    except Exception as e:
        logger.warning(f"🌙 [sleep.vacuum] ANALYZE failed: {e}")
        return {"analyze": "error: " + str(e)[:80]}


def run_sleep(app):
    """Main entry point — called by agent_loop.run_daily_cleanup.

    X21.23: every operation gets its OWN transaction so a schema mismatch
    on one table can't poison the next delete. (Previous bug: missing
    user_notifications.delivered_at column aborted the parent transaction
    in PG, causing later deletes to silently roll back despite reporting
    success rowcounts.)
    """
    try:
        from database import is_postgres
    except ImportError:
        logger.warning("🌙 [sleep] database module unavailable")
        return None

    is_pg = is_postgres()
    started = datetime.utcnow()
    result = {"started_at": started.isoformat(), "is_pg": is_pg}

    try:
        with app.app_context():
            result["prune"]       = prune_expired(is_pg)
            result["filter"]      = filter_bad_logs(is_pg)
            result["consolidate"] = consolidate_long_term(is_pg)
            result["vacuum"]      = vacuum_postgres(is_pg)

            # Audit-log the sleep summary so admins can see what happened.
            try:
                from memory_helpers import audit_log
                audit_log(
                    user_id="system",
                    action="radim_sleep",
                    resource="memory_hygiene",
                    detail=str(result)[:1000],
                )
            except Exception as e:
                logger.debug(f"🌙 [sleep] audit_log failed: {e}")

    except Exception as e:
        logger.error(f"🌙 [sleep] FAILED: {e}")
        result["error"] = str(e)[:200]
        return result

    finished = datetime.utcnow()
    result["duration_sec"] = (finished - started).total_seconds()
    logger.info(
        f"🌙 [sleep] done in {result['duration_sec']:.2f}s — "
        f"prune={sum(result['prune'].values())} "
        f"filter={sum(result['filter'].values())} "
        f"summarized={result['consolidate'].get('triggered', 0)}"
    )
    return result


def get_memory_stats():
    """Read-only snapshot of memory table sizes — for the admin dashboard.

    Returns:
        {
            "tables": {<name>: {"rows": int, "oldest": str|None}},
            "as_of": iso8601,
        }
    """
    try:
        from database import db_context
    except ImportError:
        return {"error": "db unavailable"}

    TABLES_AND_TIMECOLS = [
        ("memory_history",        "created_at"),
        ("memory_profiles",       "updated_at"),
        ("memory_learning",       "updated_at"),
        ("neuron_learning",       "updated_at"),
        ("identity_activations",  "fired_at"),
        ("brain_states",          "created_at"),
        ("brain_adaptation",      "updated_at"),
        ("brain_feedback",        "created_at"),
        ("agent_observations",    "created_at"),
        ("agent_messages",        "created_at"),
        ("crisis_events",         "created_at"),
        ("user_notifications",    "created_at"),
        ("iot_sensor_data",       "created_at"),
        ("audit_log",             "timestamp"),
    ]

    tables = {}
    for table, timecol in TABLES_AND_TIMECOLS:
        info = {"rows": 0, "oldest": None}
        try:
            with db_context() as db:
                r = db.execute("SELECT COUNT(*) FROM " + table).fetchone()
                info["rows"] = r[0] if r else 0
        except Exception as e:
            info["error"] = str(e)[:60]
            tables[table] = info
            continue
        try:
            with db_context() as db:
                r = db.execute("SELECT MIN(" + timecol + ") FROM " + table).fetchone()
                if r and r[0]:
                    info["oldest"] = str(r[0])[:19]
        except Exception:
            pass
        tables[table] = info

    return {
        "tables": tables,
        "as_of": datetime.utcnow().isoformat(),
        "retention_policy": RETENTION,
    }
