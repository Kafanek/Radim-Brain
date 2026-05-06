"""
🆘 SOS escalation engine (v10.40)
=============================================================================
Background job that walks unresolved sos_events through escalation stages:

    stage 0 (t=0s)     in-app notification to family (already done in sos_trigger)
    stage 1 (t=30s)    SMS reminder to priority contacts (if Twilio) — or
                       second in-app push with higher urgency
    stage 2 (t=120s)   auto-initiate Twilio call to sos_priority=1 contact
    stage 3 (t=300s)   push prompt to senior device: "Mám zavolat 155?"

Any family Ack via /api/sos/<id>/ack stops further escalation (ack_by_user_id
is set, we skip). Senior or family may also /api/sos/<id>/resolve to close.

Runs every 10 seconds via APScheduler job `sos_escalator`. Designed to be
idempotent — we track stage per event, only advance once per stage.
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Escalation timing (seconds)
# ──────────────────────────────────────────────────────────────────────────
STAGE_AGE_SEC = {
    1: 30,    # 30 s — remind
    2: 120,   # 2 min — call priority 1
    3: 300,   # 5 min — ask senior about 155
}


def _age_seconds(created_at):
    """Return age of event in seconds. Robust to str/datetime PG values."""
    try:
        if isinstance(created_at, datetime):
            ref = created_at
        else:
            # PG returns isoformat strings; SQLite returns string
            s = str(created_at).replace("Z", "")
            # Strip timezone if present
            if "+" in s:
                s = s.split("+")[0]
            ref = datetime.fromisoformat(s[:19])
        return (datetime.utcnow() - ref).total_seconds()
    except Exception:
        return 0


def _advance_stage(db, sos_id, new_stage):
    """Bump escalation_stage if it's still below new_stage. Returns True if advanced."""
    from database import is_postgres
    cur = db.execute(
        "UPDATE sos_events SET escalation_stage = ? "
        "WHERE id = ? AND escalation_stage < ? AND resolved_at IS NULL "
        "AND ack_by_user_id IS NULL",
        (new_stage, sos_id, new_stage)
    )
    return (cur.rowcount if hasattr(cur, "rowcount") else 0) > 0


# ──────────────────────────────────────────────────────────────────────────
# Stage handlers
# ──────────────────────────────────────────────────────────────────────────

def _stage_1_remind(event):
    """30s — second wave in-app push with stronger urgency + ring sound hint."""
    try:
        from notification_helpers import notify_senior_family
        notify_senior_family(
            senior_id=event["senior_id"],
            type="sos",
            severity="crisis",
            title="🆘 STÁLE SOS — bez reakce 30 s",
            body="Nikdo z rodiny zatím nepotvrdil, že řeší. Prosím zavolejte.",
            data={
                "sos_event_id": event["id"],
                "escalation_stage": 1,
                "actionable": True,
                "ring": True,
            },
            include_caregiver=True,
        )
        logger.info(f"🆘 [escalator] stage 1 (remind) fired for sos#{event['id']}")
        return True
    except Exception as e:
        logger.error(f"SOS stage 1 failed: {e}")
        return False


def _stage_2_call_priority(event):
    """120s — auto-initiate Twilio call to highest-priority contact."""
    try:
        from database import db_context
        # Find highest-priority contact with can_call + phone
        phone = None
        name = None
        with db_context() as db:
            row = db.execute(
                "SELECT name, phone FROM contacts "
                "WHERE senior_id = ? AND can_call = TRUE "
                "AND phone IS NOT NULL AND sos_priority IS NOT NULL "
                "ORDER BY sos_priority ASC LIMIT 1",
                (str(event["senior_id"]),)
            ).fetchone()
            if row:
                name, phone = row[0], row[1]

        if not phone:
            logger.info(f"🆘 [escalator] stage 2 skipped — no priority contact for sos#{event['id']}")
            # Still log the attempt as observation
            return True

        # Try Twilio proactive call
        try:
            from twilio_voice_helpers import initiate_proactive_call
            msg = (f"Mluví Radim. Vaše blízký stiskl tísňové tlačítko a dosud se "
                   f"nikdo neohlásil. Pokud se k němu vydáte, stiskněte jedničku.")
            initiate_proactive_call(phone, msg,
                                    user_id=event["senior_id"],
                                    reason="sos_cascade")
            logger.info(f"🆘 [escalator] stage 2 called {name} ({phone[-4:]}) for sos#{event['id']}")
        except Exception as e:
            logger.warning(f"Twilio call for stage 2 failed (likely blocked): {e}")
            # Fallback: in-app notification
            try:
                from notification_helpers import notify_senior_family
                notify_senior_family(
                    senior_id=event["senior_id"], type="sos", severity="crisis",
                    title="🆘 ESKALACE — 2 min bez reakce",
                    body=f"Radim se snaží zavolat {name} ({phone}). Prosím reagujte.",
                    data={"sos_event_id": event["id"], "escalation_stage": 2},
                )
            except Exception:
                pass

        return True
    except Exception as e:
        logger.error(f"SOS stage 2 failed: {e}")
        return False


def _stage_3_ask_senior(event):
    """300s — push notification to senior device: 'Mám zavolat 155?'"""
    try:
        from notification_helpers import notify
        notify(
            to_user_id=event["senior_id"],
            type="sos",
            severity="crisis",
            title="🚑 Mám zavolat záchranku 155?",
            body=("Nikdo z rodiny se neozval už 5 minut. Jste v pořádku? "
                  "Pokud ano, stiskněte \u201eJsem OK\u201c v notifikaci."),
            data={
                "sos_event_id": event["id"],
                "escalation_stage": 3,
                "offer_call_155": True,
            },
        )
        logger.info(f"🆘 [escalator] stage 3 (ask about 155) fired for sos#{event['id']}")
        return True
    except Exception as e:
        logger.error(f"SOS stage 3 failed: {e}")
        return False


STAGE_HANDLERS = {
    1: _stage_1_remind,
    2: _stage_2_call_priority,
    3: _stage_3_ask_senior,
}


# ──────────────────────────────────────────────────────────────────────────
# Main tick — runs every 10 s
# ──────────────────────────────────────────────────────────────────────────

def run_escalator_tick(app=None):
    """One pass through unresolved sos_events. Safe to call from scheduler.

    v8.19.106 hardening:
    - statement_timeout=5s + lock_timeout=2s on PG session — caps tick time
      so a hung query can never block subsequent ticks. Previously a slow
      tick caused APScheduler to skip every 10s in a tight loop, piling up
      DB connections until Postgres OOMed.
    - Stage handlers run OUTSIDE the DB transaction. They do TTS / Twilio /
      push, which can be slow — keeping the DB connection short means the
      pool stays available even when an external service is degraded.
    """
    try:
        from database import db_context, is_postgres
        advanced = 0
        events_to_handle = []  # (event, next_stage) collected inside tx, fired outside

        with db_context(commit=True) as db:
            # PG: cap query/lock time so a single bad tick can't snowball.
            if is_postgres():
                try:
                    db.execute("SET LOCAL statement_timeout = '5s'")
                    db.execute("SET LOCAL lock_timeout = '2s'")
                except Exception:
                    pass  # fall through — best-effort

            rows = db.execute(
                "SELECT id, senior_id, source, message, escalation_stage, created_at "
                "FROM sos_events "
                "WHERE resolved_at IS NULL AND ack_by_user_id IS NULL "
                "ORDER BY id ASC LIMIT 50"
            ).fetchall() or []

            for r in rows:
                event = {
                    "id": r[0], "senior_id": r[1], "source": r[2],
                    "message": r[3], "escalation_stage": r[4] or 0,
                    "created_at": r[5],
                }
                age = _age_seconds(event["created_at"])

                # Determine target stage based on age
                target_stage = event["escalation_stage"]
                for stage, age_threshold in STAGE_AGE_SEC.items():
                    if age >= age_threshold and stage > target_stage:
                        target_stage = stage

                # Advance one stage at a time
                next_stage = event["escalation_stage"] + 1
                if next_stage <= target_stage and next_stage in STAGE_HANDLERS:
                    # Advance atomically — prevents double-fire if two ticks overlap
                    if _advance_stage(db, event["id"], next_stage):
                        events_to_handle.append((event, next_stage))

        # Fire handlers AFTER transaction closes — handlers do external I/O
        # (Twilio, push, TTS) that must not hold a DB connection.
        for event, next_stage in events_to_handle:
            handler = STAGE_HANDLERS[next_stage]
            try:
                handler(event)
                advanced += 1
            except Exception as e:
                logger.error(f"SOS escalator stage {next_stage} handler failed: {e}")

        if advanced:
            logger.info(f"🆘 [escalator] tick: advanced {advanced} event(s)")
    except Exception as e:
        logger.error(f"SOS escalator tick error: {e}")


# ──────────────────────────────────────────────────────────────────────────
# Kill switch + feature flag
# ──────────────────────────────────────────────────────────────────────────

def is_enabled():
    """SOS_ESCALATION env flag — default ON unless explicitly off."""
    return os.environ.get("SOS_ESCALATION", "true").lower() != "false"
