"""
Proactive Agent Loop v1.0
=========================
Scheduled job (every 5 min) that makes Radim a proactive AI agent.

For each active senior:
1. Gather state (brain_states, IoT, memory_learning)
2. Detect anomalies (statistical, no ML)
3. Graduated actions: INFO → WARNING → ALERT → CRISIS
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile, audit_log
    from behavior_baseline import get_baselines, _time_window, _mean_std
    _AVAILABLE = True
except ImportError as e:
    _AVAILABLE = False
    logger.warning(f"agent_loop: dependencies not available: {e}")

# Severity levels
INFO = "INFO"
WARNING = "WARNING"
ALERT = "ALERT"
CRISIS = "CRISIS"

# Brain thresholds (from brain_math.py)
T1 = 12  # HARMONY → ALERT
T2 = 27  # ALERT → CRISIS

OBSERVATION_COOLDOWN_MINUTES = 60


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def run_agent_cycle(app):
    """Main agent loop — called every 5 minutes by APScheduler."""
    if not _AVAILABLE:
        return

    with app.app_context():
        try:
            active = _get_active_users()
            if not active:
                return
            logger.info(f"Agent loop: evaluating {len(active)} active users")

            for user_id in active:
                try:
                    _evaluate_user(user_id, app)
                except Exception as e:
                    logger.debug(f"Agent loop skip {user_id}: {e}")

        except Exception as e:
            logger.error(f"Agent loop cycle error: {e}")


# ============================================================================
# USER DISCOVERY
# ============================================================================

def _get_active_users():
    """Find users with recent brain_states or IoT data (last 24h)."""
    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute("""
                    SELECT DISTINCT user_id FROM (
                        SELECT user_id FROM brain_states WHERE created_at > NOW() - INTERVAL '24 hours'
                        UNION
                        SELECT DISTINCT d.user_id FROM iot_devices d
                        JOIN iot_sensor_data s ON s.device_id = d.device_id
                        WHERE s.recorded_at > NOW() - INTERVAL '24 hours' AND d.user_id IS NOT NULL
                    ) sub LIMIT 100
                """).fetchall()
            else:
                rows = db.execute("""
                    SELECT DISTINCT user_id FROM (
                        SELECT user_id FROM brain_states WHERE created_at > datetime('now', '-24 hours')
                        UNION
                        SELECT DISTINCT d.user_id FROM iot_devices d
                        JOIN iot_sensor_data s ON s.device_id = d.device_id
                        WHERE s.recorded_at > datetime('now', '-24 hours') AND d.user_id IS NOT NULL
                    ) LIMIT 100
                """).fetchall()
            return [r['user_id'] or r[0] for r in rows if (r.get('user_id') or r[0])]
    except Exception as e:
        logger.debug(f"get_active_users error: {e}")
        return []


# ============================================================================
# PER-USER EVALUATION
# ============================================================================

def _evaluate_user(user_id, app):
    """Evaluate one user: detect anomalies, take actions."""
    baselines = get_baselines(user_id)
    observations = []

    for check in (_check_c_trend, _check_activity_drop, _check_vitals, _check_interaction_silence):
        obs = check(user_id, baselines)
        if obs and not _is_in_cooldown(user_id, obs["type"]):
            observations.append(obs)

    for obs in observations:
        _save_observation(user_id, obs)
        _execute_action(user_id, obs, app)


# ============================================================================
# ANOMALY DETECTORS
# ============================================================================

def _check_c_trend(user_id, baselines):
    """Detect rising C trend: recent avg vs baseline."""
    learning = db_load_learning(user_id)
    c_history = [float(v) for v in learning.get("C_history", []) if v is not None]
    if len(c_history) < 5:
        return None

    recent_avg, _ = _mean_std(c_history[-5:])
    baseline_avg = baselines.get("avg_C", 5.0)
    baseline_std = baselines.get("std_C", 3.0)

    if baseline_std < 0.5:
        baseline_std = 0.5  # minimum to avoid false positives

    if recent_avg > T2:
        return {"type": "c_trend_rising", "severity": CRISIS,
                "message": "Uživatel je ve velmi silném stresu a potřebuje okamžitou pomoc.",
                "details": {"recent_avg": recent_avg, "baseline_avg": baseline_avg}}
    elif recent_avg > T1:
        return {"type": "c_trend_rising", "severity": ALERT,
                "message": "Uživatel je ve zvýšeném stresu — buďte extra klidný a empatický.",
                "details": {"recent_avg": recent_avg, "baseline_avg": baseline_avg}}
    elif recent_avg > baseline_avg + 1.5 * baseline_std:
        return {"type": "c_trend_rising", "severity": WARNING,
                "message": "Všimli jsme si, že jste v posledních rozhovorech napjatější než obvykle. Je vše v pořádku?",
                "details": {"recent_avg": recent_avg, "baseline_avg": baseline_avg, "std": baseline_std}}
    return None


def _check_activity_drop(user_id, baselines):
    """Detect motion activity drop vs baseline."""
    motion_bl = baselines.get("motion_by_window", {})
    window = _time_window()
    bl = motion_bl.get(window)
    if not bl or bl.get("avg", 0) < 2:
        return None  # no baseline or too low to be meaningful

    # Count recent motion events
    try:
        with db_context() as db:
            rooms = db.execute("SELECT DISTINCT room_id FROM iot_devices WHERE user_id = ?", (user_id,)).fetchall()
            if not rooms:
                return None
            room_ids = [r['room_id'] or r[0] for r in rooms]
            ph = ",".join(["?"] * len(room_ids))

            if is_postgres():
                row = db.execute(
                    f"SELECT COUNT(*) as cnt FROM iot_sensor_data WHERE room_id IN ({ph}) "
                    f"AND sensor_type = 'motion' AND recorded_at > NOW() - INTERVAL '6 hours'",
                    tuple(room_ids)
                ).fetchone()
            else:
                row = db.execute(
                    f"SELECT COUNT(*) as cnt FROM iot_sensor_data WHERE room_id IN ({ph}) "
                    f"AND sensor_type = 'motion' AND recorded_at > datetime('now', '-6 hours')",
                    tuple(room_ids)
                ).fetchone()

            current = row['cnt'] or row[0] or 0
    except Exception:
        return None

    avg = bl["avg"]
    std = max(bl.get("std", 1.0), 1.0)

    if current == 0 and avg > 3:
        return {"type": "activity_drop", "severity": ALERT,
                "message": "Za posledních 6 hodin jsme nezaznamenali žádný pohyb. Zeptejte se, jestli je vše v pořádku.",
                "details": {"current": current, "baseline_avg": avg, "window": window}}
    elif current < avg - 2 * std or current < avg * 0.5:
        return {"type": "activity_drop", "severity": WARNING,
                "message": "Dnes jste méně aktivní než obvykle. Jak se cítíte?",
                "details": {"current": current, "baseline_avg": avg, "window": window}}
    return None


def _check_vitals(user_id, baselines):
    """Detect vital signs outside personal baseline."""
    vitals_bl = baselines.get("vitals", {})
    if not vitals_bl:
        return None

    try:
        with db_context() as db:
            rooms = db.execute("SELECT DISTINCT room_id FROM iot_devices WHERE user_id = ?", (user_id,)).fetchall()
            if not rooms:
                return None
            room_ids = [r['room_id'] or r[0] for r in rooms]
            ph = ",".join(["?"] * len(room_ids))

            for sensor, bl in vitals_bl.items():
                if is_postgres():
                    row = db.execute(
                        f"SELECT value FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = ? "
                        f"AND recorded_at > NOW() - INTERVAL '30 minutes' ORDER BY recorded_at DESC LIMIT 1",
                        tuple(room_ids) + (sensor,)
                    ).fetchone()
                else:
                    row = db.execute(
                        f"SELECT value FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = ? "
                        f"AND recorded_at > datetime('now', '-30 minutes') ORDER BY recorded_at DESC LIMIT 1",
                        tuple(room_ids) + (sensor,)
                    ).fetchone()

                if not row:
                    continue

                val = float(row['value'] or row[0])
                avg = bl["avg"]
                std = max(bl.get("std", 1.0), 0.5)
                deviation = abs(val - avg) / std

                # SpO2 < 90 is always crisis
                if sensor == 'spo2' and val < 90:
                    return {"type": "vital_anomaly", "severity": CRISIS,
                            "message": f"Hladina kyslíku v krvi je nebezpečně nízká ({val:.0f}%). Je třeba zavolat pomoc.",
                            "details": {"sensor": sensor, "value": val, "baseline_avg": avg}}

                sensor_name = "tepová frekvence" if sensor == "heart_rate" else "hladina kyslíku"
                if deviation > 3:
                    return {"type": "vital_anomaly", "severity": ALERT,
                            "message": f"Vaše {sensor_name} ({val:.0f}) je výrazně mimo obvyklý rozsah. Informujeme pečovatele.",
                            "details": {"sensor": sensor, "value": val, "baseline_avg": avg, "deviation_sigma": round(deviation, 1)}}
                elif deviation > 2:
                    return {"type": "vital_anomaly", "severity": WARNING,
                            "message": f"Vaše {sensor_name} ({val:.0f}) je mírně mimo obvyklý rozsah. Jak se cítíte?",
                            "details": {"sensor": sensor, "value": val, "baseline_avg": avg, "deviation_sigma": round(deviation, 1)}}
    except Exception:
        pass
    return None


def _check_interaction_silence(user_id, baselines):
    """Detect prolonged silence (no interactions)."""
    learning = db_load_learning(user_id)
    last = learning.get("last_interaction")
    if not last:
        return None

    try:
        last_dt = datetime.fromisoformat(str(last).replace('Z', '+00:00').split('+')[0])
        hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None

    if hours_since > 48:
        return {"type": "no_interaction", "severity": ALERT,
                "message": f"Uživatel se neozval už {hours_since:.0f} hodin. Zeptejte se, jak se má, a nabídněte pomoc.",
                "details": {"hours_since": round(hours_since, 1), "last": str(last)}}
    elif hours_since > 24:
        return {"type": "no_interaction", "severity": WARNING,
                "message": "Nebyli jsme spolu v kontaktu celý den. Rád bych věděl, jak se vám daří.",
                "details": {"hours_since": round(hours_since, 1)}}
    elif hours_since > 12:
        return {"type": "no_interaction", "severity": INFO,
                "message": "Uživatel se delší dobu neozval. Při příštím rozhovoru se zeptejte, jak se má.",
                "details": {"hours_since": round(hours_since, 1)}}
    return None


# ============================================================================
# COOLDOWN + PERSISTENCE
# ============================================================================

def _is_in_cooldown(user_id, observation_type):
    """Check if same observation was logged recently."""
    try:
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT 1 FROM agent_observations WHERE user_id = ? AND observation_type = ? "
                    f"AND created_at > NOW() - INTERVAL '{OBSERVATION_COOLDOWN_MINUTES} minutes' LIMIT 1",
                    (user_id, observation_type)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT 1 FROM agent_observations WHERE user_id = ? AND observation_type = ? "
                    f"AND created_at > datetime('now', '-{OBSERVATION_COOLDOWN_MINUTES} minutes') LIMIT 1",
                    (user_id, observation_type)
                ).fetchone()
            return row is not None
    except Exception:
        return False


def _save_observation(user_id, obs):
    """Insert into agent_observations + audit_log."""
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO agent_observations (user_id, observation_type, severity, message, details, action_taken) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, obs["type"], obs["severity"], obs["message"],
                 json.dumps(obs.get("details", {})), obs["severity"].lower())
            )
        audit_log(user_id, "agent_observation", "agent_loop",
                  f"[{obs['severity']}] {obs['type']}: {obs['message']}")
    except Exception as e:
        logger.debug(f"save_observation error: {e}")


def _inject_into_memory(user_id, obs):
    """Add observation to memory_learning for next chat context."""
    try:
        learning = db_load_learning(user_id)
        agent_obs = learning.get("agent_observations", [])
        agent_obs.append({
            "type": obs["type"],
            "severity": obs["severity"],
            "message": obs["message"],
            "at": datetime.utcnow().isoformat()
        })
        learning["agent_observations"] = agent_obs[-5:]  # keep last 5
        db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f"inject_into_memory error: {e}")


# ============================================================================
# ACTION EXECUTOR
# ============================================================================

def _execute_action(user_id, obs, app):
    """Graduated action based on severity."""
    severity = obs["severity"]

    # Always inject into memory (so Radim mentions it in next chat)
    _inject_into_memory(user_id, obs)

    if severity == INFO:
        return  # logged only

    if severity in (WARNING, ALERT, CRISIS):
        _push_to_senior(user_id, obs, app)

    if severity in (ALERT, CRISIS):
        _alert_caregiver(user_id, obs, app)
        _call_senior(user_id, obs)  # v387: proactive phone call

    if severity == CRISIS:
        _crisis_escalate(user_id, obs, app)


def _push_to_senior(user_id, obs, app):
    """Push notification to senior."""
    try:
        send_push = app.config.get('SEND_PUSH_FN')
        if send_push:
            send_push(user_id, "Radim — pozornost",
                      obs["message"],
                      data={"type": "agent_observation", "severity": obs["severity"]})
    except Exception as e:
        logger.debug(f"push_to_senior error: {e}")


def _alert_caregiver(user_id, obs, app):
    """Notify caregiver via push + SocketIO."""
    try:
        profile = db_load_profile(user_id)
        caregiver_id = profile.get("caregiver_id")
        if not caregiver_id:
            return

        send_push = app.config.get('SEND_PUSH_FN')
        if send_push:
            send_push(caregiver_id,
                      f"Radim — {obs['severity']}",
                      f"Senior {user_id}: {obs['message']}",
                      data={"type": "agent_alert", "senior_id": user_id, "severity": obs["severity"]})

        socketio = app.extensions.get('socketio')
        if socketio:
            socketio.emit('agent_alert', {
                'senior_id': user_id, 'severity': obs['severity'],
                'message': obs['message'], 'type': obs['type']
            }, room=f'user_{caregiver_id}')
    except Exception as e:
        logger.debug(f"alert_caregiver error: {e}")


def _crisis_escalate(user_id, obs, app):
    """SMS to caregiver + crisis_event record."""
    try:
        # Save crisis event (reuse existing table)
        profile = db_load_profile(user_id)
        caregiver_id = profile.get("caregiver_id")

        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO crisis_events (user_id, caregiver_id, brain_c, message_excerpt, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, caregiver_id, obs["details"].get("recent_avg", 0),
                 obs["message"][:100], datetime.utcnow().isoformat())
            )

        # SMS via IoT helpers
        try:
            from iot_helpers import _send_sms_alert
            _send_sms_alert(
                {"severity": "critical", "message": obs["message"], "channels": "sms"},
                user_id  # room_id = user_id for personal alerts
            )
        except Exception:
            pass

    except Exception as e:
        logger.debug(f"crisis_escalate error: {e}")


def _call_senior(user_id, obs):
    """Proactive phone call to senior (v387)."""
    try:
        from twilio_voice_helpers import initiate_proactive_call, get_senior_phone
        phone = get_senior_phone(user_id)
        if not phone:
            logger.debug(f"No phone for {user_id}, skipping proactive call")
            return

        # Build greeting based on observation type
        greetings = {
            "c_trend_rising": "Dobrý den, tady Radim. Všiml jsem si, že v posledních rozhovorech jste byl trochu napjatější. Chtěl jsem se zeptat, jestli je vše v pořádku.",
            "activity_drop": "Dobrý den, tady Radim. Dnes jste byl méně aktivní než obvykle, tak jsem vám chtěl zavolat a zeptat se, jak se máte.",
            "vital_anomaly": "Dobrý den, tady Radim. Zaznamenal jsem neobvyklou hodnotu vašich životních funkcí. Jak se cítíte?",
            "no_interaction": "Dobrý den, tady Radim. Už jsme spolu delší dobu nemluvili, tak jsem vám chtěl zavolat. Jak se vám daří?",
        }
        greeting = greetings.get(obs["type"], "Dobrý den, tady Radim. Chtěl jsem se zeptat, jak se máte.")

        result = initiate_proactive_call(phone, greeting, user_id=user_id, reason=obs["type"])
        if result.get("success"):
            logger.info(f"📞 Proactive call to {user_id}: {result['call_sid']}")
        else:
            logger.debug(f"Proactive call failed for {user_id}: {result.get('error')}")
    except ImportError:
        logger.debug("Twilio not available for proactive calls")
    except Exception as e:
        logger.debug(f"call_senior error: {e}")


# ============================================================================
# MORNING CHECK-IN (v390 — scheduled daily call)
# ============================================================================

def run_morning_checkin(app):
    """Daily morning check-in: call seniors with medication reminders.

    Called by APScheduler cron job at 8:00 AM.
    For each senior with medications in profile:
    1. Build personalized morning greeting with today's meds
    2. Call them on phone (if phone number in profile)
    3. Or push notification (if no phone)
    """
    if not _AVAILABLE:
        return

    with app.app_context():
        try:
            seniors = _get_seniors_with_medications()
            if not seniors:
                return
            logger.info(f"☀️ Morning check-in: {len(seniors)} seniors with medications")

            for user_id, meds_info in seniors:
                try:
                    _morning_call_or_push(user_id, meds_info, app)
                except Exception as e:
                    logger.debug(f"Morning check-in skip {user_id}: {e}")

        except Exception as e:
            logger.error(f"Morning check-in error: {e}")


def _get_seniors_with_medications():
    """Find seniors who have morning medications configured."""
    results = []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, data FROM memory_profiles WHERE data IS NOT NULL"
            ).fetchall()

            for row in rows:
                user_id = row.get('user_id') or row[0]
                data = row.get('data') or row[1]
                if isinstance(data, str):
                    import json
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        continue

                if not isinstance(data, dict):
                    continue

                meds = data.get("medications_list", [])
                med_times = data.get("medication_times", {})
                morning_meds = med_times.get("rano") or med_times.get("morning") or []

                if meds or morning_meds:
                    results.append((user_id, {
                        "meds": meds,
                        "morning": morning_meds,
                        "name": data.get("name", ""),
                    }))
    except Exception as e:
        logger.debug(f"get_seniors_with_medications error: {e}")
    return results


def _morning_call_or_push(user_id, meds_info, app):
    """Call senior with morning greeting + meds, or fallback to push."""
    name = meds_info.get("name", "")
    morning_meds = meds_info.get("morning", [])
    all_meds = meds_info.get("meds", [])

    # Build greeting
    greeting_name = f", {name}" if name else ""
    if morning_meds and isinstance(morning_meds, list):
        meds_str = ", ".join(morning_meds[:3])
        greeting = (
            f"Dobré ráno{greeting_name}! Tady Radim. "
            f"Nezapomeňte na ranní léky: {meds_str}. "
            f"Jak se dnes cítíte?"
        )
    elif all_meds and isinstance(all_meds, list):
        greeting = (
            f"Dobré ráno{greeting_name}! Tady Radim. "
            f"Připomínám ranní léky. Jak se dnes cítíte?"
        )
    else:
        greeting = (
            f"Dobré ráno{greeting_name}! Tady Radim. "
            f"Jak se dnes cítíte?"
        )

    # Try phone call first
    try:
        from twilio_voice_helpers import initiate_proactive_call, get_senior_phone
        phone = get_senior_phone(user_id)
        if phone:
            result = initiate_proactive_call(phone, greeting, user_id=user_id, reason="morning_checkin")
            if result.get("success"):
                logger.info(f"☀️ Morning call to {name or user_id}: {result['call_sid']}")
                return
    except ImportError:
        pass

    # Fallback: push notification
    try:
        send_push = app.config.get('SEND_PUSH_FN')
        if send_push:
            push_body = greeting.replace("Tady Radim. ", "")
            send_push(user_id, "☀️ Dobré ráno od Radima", push_body,
                      data={"type": "morning_checkin"})
            logger.info(f"☀️ Morning push to {name or user_id}")
    except Exception as e:
        logger.debug(f"Morning push error: {e}")


# ============================================================================
# DAILY CLEANUP (v392 — scheduled at 3:00 AM)
# ============================================================================

def run_daily_cleanup(app):
    """Clean up old data: observations >30d, brain_states >90d.

    Called by APScheduler cron job at 3:00 AM.
    """
    if not _AVAILABLE:
        return

    with app.app_context():
        try:
            with db_context(commit=True) as db:
                if is_postgres():
                    # Observations older than 30 days
                    r1 = db.execute(
                        "DELETE FROM agent_observations WHERE created_at < NOW() - INTERVAL '30 days'"
                    )
                    # Brain states older than 90 days
                    r2 = db.execute(
                        "DELETE FROM brain_states WHERE created_at < NOW() - INTERVAL '90 days'"
                    )
                else:
                    r1 = db.execute(
                        "DELETE FROM agent_observations WHERE created_at < datetime('now', '-30 days')"
                    )
                    r2 = db.execute(
                        "DELETE FROM brain_states WHERE created_at < datetime('now', '-90 days')"
                    )

                obs_deleted = r1.rowcount if r1 else 0
                brain_deleted = r2.rowcount if r2 else 0

                if obs_deleted > 0 or brain_deleted > 0:
                    logger.info(f"🧹 Daily cleanup: {obs_deleted} old observations, {brain_deleted} old brain_states deleted")
                else:
                    logger.debug("🧹 Daily cleanup: nothing to delete")

        except Exception as e:
            logger.error(f"Daily cleanup error: {e}")


logger.info("Agent Loop v1.3 loaded — monitoring + calls + morning check-in + cleanup")
