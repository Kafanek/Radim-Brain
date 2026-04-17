"""
Proactive Agent Loop v2.0
=========================
Scheduled job (every 5 min) that makes Radim a proactive AI agent.

For each active senior:
1. Gather state (brain_states, IoT, memory_learning, Home Assistant)
2. Detect anomalies (statistical, no ML)
3. Graduated actions: INFO → WARNING → ALERT → CRISIS
4. Crisis → Home Assistant actions (lights on, door unlock)
5. HA sensor sync → iot_sensor_data DB
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

# Home Assistant integration (optional)
try:
    from home_assistant import ha as _get_ha
    _HAS_HA = True
except ImportError:
    _HAS_HA = False

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
        # v10.33: Reset per-cycle telemetry counters
        global _CYCLE_TELEMETRY
        _CYCLE_TELEMETRY = {
            'started_at': datetime.utcnow().isoformat(),
            'users_active': 0,
            'users_evaluated': 0,
            'users_skipped': 0,
            'observations_generated': 0,
            'agents_called': {},  # agent_name → call count
            'agents_observations': {},  # agent_name → obs count
        }

        try:
            _sync_ha_sensors()

            active = _get_active_users()
            if not active:
                return
            _CYCLE_TELEMETRY['users_active'] = len(active)
            logger.info(f"Agent loop: evaluating {len(active)} active users")

            evaluated = 0
            skipped = 0
            for user_id in active:
                try:
                    from scaling_optimizations import should_evaluate_user, get_user_risk_level
                    risk = get_user_risk_level(user_id)
                    if not should_evaluate_user(user_id, risk):
                        skipped += 1
                        continue
                except ImportError:
                    pass

                try:
                    _evaluate_user(user_id, app)
                    evaluated += 1
                except Exception as e:
                    logger.debug(f"Agent loop skip {user_id}: {e}")

            _CYCLE_TELEMETRY['users_evaluated'] = evaluated
            _CYCLE_TELEMETRY['users_skipped'] = skipped

            if skipped > 0:
                logger.info(f"Agent loop: evaluated {evaluated}, skipped {skipped} (low-risk adaptive)")

            # v10.33: End-of-cycle telemetry summary
            ag_calls = _CYCLE_TELEMETRY['agents_called']
            ag_obs = _CYCLE_TELEMETRY['agents_observations']
            if ag_calls:
                top_agents = sorted(ag_calls.items(), key=lambda x: -x[1])[:5]
                summary = ', '.join(f"{a}:{c}" for a, c in top_agents)
                total_obs = sum(ag_obs.values())
                logger.info(f"📊 Cycle telemetry: {evaluated} users × agents=[{summary}] → {total_obs} observations")

        except Exception as e:
            logger.error(f"Agent loop cycle error: {e}")


# Global per-cycle telemetry (reset each cycle)
_CYCLE_TELEMETRY = {}


def _track_agent(agent_name, generated_obs=False):
    """Called by agents to record they ran (and optionally generated an observation)."""
    try:
        if not _CYCLE_TELEMETRY:
            return
        _CYCLE_TELEMETRY['agents_called'][agent_name] = \
            _CYCLE_TELEMETRY['agents_called'].get(agent_name, 0) + 1
        if generated_obs:
            _CYCLE_TELEMETRY['agents_observations'][agent_name] = \
                _CYCLE_TELEMETRY['agents_observations'].get(agent_name, 0) + 1
    except Exception:
        pass


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
    """Evaluate one user: detect anomalies, take actions, run advanced agents."""
    baselines = get_baselines(user_id)
    observations = []

    # ── v3.1: Get adaptive sensitivity from Learning Agent ──
    sensitivity = _get_user_sensitivity(user_id)

    # ── Core detectors ──
    for check in (_check_c_trend, _check_activity_drop, _check_vitals, _check_interaction_silence, _check_fall_detection):
        obs = check(user_id, baselines)
        if obs and not _is_in_cooldown(user_id, obs["type"]):
            # Apply sensitivity filter: if sensitivity < 1.0, skip low-severity
            if sensitivity < 0.8 and obs["severity"] == INFO:
                continue  # Too many false alarms → skip INFO
            if sensitivity < 0.6 and obs["severity"] == WARNING:
                continue  # Very low sensitivity → skip WARNING too
            observations.append(obs)

    # ── HA environment check ──
    ha_obs = _ha_check_environment(user_id)
    if ha_obs and not _is_in_cooldown(user_id, ha_obs["type"]):
        observations.append(ha_obs)

    # ── v3.0: Advanced agents integration ──
    _run_advanced_agents(user_id, baselines, observations)

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


def _check_fall_detection(user_id, baselines):
    """Detect potential falls from IoT accelerometer/motion data.

    Patterns:
    1. Sudden high acceleration spike → impact
    2. No motion after spike → person on floor
    3. Motion sensor active at unusual hour (2-5 AM) + no interaction → night fall
    """
    try:
        with db_context(commit=False) as db:
            # Get recent accelerometer data (last 10 min)
            recent = db.execute("""
                SELECT sensor_type, value, recorded_at
                FROM iot_sensor_data
                WHERE user_id = ? AND recorded_at > ?
                AND sensor_type IN ('accelerometer', 'motion', 'fall_sensor')
                ORDER BY recorded_at DESC LIMIT 20
            """, (user_id, (datetime.utcnow() - timedelta(minutes=10)).isoformat())).fetchall()

            if not recent:
                return None

            # Pattern 1: High acceleration spike (fall impact)
            for row in recent:
                sensor_type, value, recorded_at = row[0], row[1], row[2]
                try:
                    val = float(value) if not isinstance(value, (int, float)) else value
                except (ValueError, TypeError):
                    continue

                # Fall sensor direct trigger
                if sensor_type == 'fall_sensor' and val > 0:
                    return {"type": "fall_detected", "severity": CRISIS,
                            "message": "⚠️ Senzor pádu aktivován! Zkontrolujte seniora IHNED.",
                            "details": {"sensor": sensor_type, "value": val, "time": str(recorded_at)}}

                # Accelerometer spike > 3G = likely fall
                if sensor_type == 'accelerometer' and val > 3.0:
                    return {"type": "fall_suspected", "severity": ALERT,
                            "message": "Podezření na pád — vysoká akcelerace detekována. Ověřte stav seniora.",
                            "details": {"acceleration_g": round(val, 1), "time": str(recorded_at)}}

            # Pattern 2: Night motion (2-5 AM) without interaction
            hour = datetime.utcnow().hour
            if 2 <= hour <= 5:
                motion_count = sum(1 for r in recent if r[0] == 'motion')
                if motion_count > 3:
                    return {"type": "night_activity", "severity": WARNING,
                            "message": "Noční aktivita detekována (pohyb v " + str(hour) + ":00). Může to být nespavost nebo problém.",
                            "details": {"motion_events": motion_count, "hour": hour}}

    except Exception as e:
        logger.debug(f"Fall detection check error: {e}")

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
    """Graduated action based on severity + user's chosen Radim mode."""
    severity = obs["severity"]

    # Always inject into memory (so Radim mentions it in next chat)
    _inject_into_memory(user_id, obs)

    # v478: Respect user's chosen mode (observer/guide/guardian)
    profile = db_load_profile(user_id)
    radim_mode = profile.get('radim_mode', 'guide')

    # OBSERVER mode: only act on CRISIS, skip everything else
    if radim_mode == 'observer' and severity != CRISIS:
        logger.debug(f"Observer mode: skipping {severity} for {user_id}")
        return

    if severity == INFO:
        return  # logged only

    # GUIDE mode: push + memory, no calls unless CRISIS
    # GUARDIAN mode: full escalation
    if severity in (WARNING, ALERT, CRISIS):
        _push_to_senior(user_id, obs, app)

    if severity in (ALERT, CRISIS):
        _alert_caregiver(user_id, obs, app)
        _call_senior(user_id, obs)  # v387: proactive phone call

    if severity == CRISIS:
        # v10.7: Emergency with retry logic (bridge)
        try:
            from agent_bridge import emergency_with_retry
            emergency_with_retry(user_id, obs.get('message', 'Crisis'), app)
        except (ImportError, Exception) as bridge_err:
            logger.debug(f"Bridge emergency fallback: {bridge_err}")
            _crisis_escalate(user_id, obs, app)

    # v2.0: Home Assistant emergency actions
    if severity in (WARNING, ALERT, CRISIS):
        _ha_crisis_actions(user_id, obs)

    # v485: Route to medical team — filtered by observation type
    # v4.1: Now also sends push notifications to team members
    _route_to_medical_team(user_id, obs, app)


def _route_to_medical_team(user_id, obs, app=None):
    """Save alert to medical_alerts, route to relevant doctors, and push notify them."""
    try:
        import json as _json
        from database import db_context
        obs_type = obs.get('type', '')
        severity = obs.get('severity', 'info')

        # Map observation type → relevant medical roles
        ALERT_ROLE_MAP = {
            'c_trend_rising': ['coordinator', 'caregiver'],
            'activity_drop': ['coordinator', 'caregiver', 'vascular'],
            'vital_anomaly': ['coordinator', 'cardiologist'],
            'no_interaction': ['coordinator', 'caregiver', 'family'],
            'heart_rate': ['cardiologist'],
            'blood_pressure': ['cardiologist'],
            'skin_change': ['dermatologist'],
            'fall_detected': ['coordinator', 'caregiver', 'family'],
        }
        routed = ALERT_ROLE_MAP.get(obs_type, ['coordinator'])

        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_alerts (senior_id, alert_type, severity, message, data, routed_to) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, obs_type, severity, obs.get('message', ''),
                 _json.dumps(obs.get('details', {})),
                 _json.dumps(routed))
            )

        # v4.1: Push notify all team members with matching roles
        if app and severity in ('warning', 'alert', 'crisis'):
            _push_to_medical_team(user_id, obs, routed, app)

    except Exception as e:
        logger.debug(f"Medical alert routing: {e}")


def _push_to_medical_team(user_id, obs, routed_roles, app):
    """Push notification to all medical team members with matching roles."""
    try:
        import json as _json
        from database import db_context
        send_push = app.config.get('SEND_PUSH_FN')
        if not send_push:
            return

        severity = obs.get('severity', 'info')
        sev_icons = {'warning': '⚠️', 'alert': '🔴', 'crisis': '🚨'}
        icon = sev_icons.get(severity, '🔔')
        title = f"{icon} Radim Medical — {severity.upper()}"
        body = obs.get('message', 'Nový alert')

        # Find team members with matching roles
        with db_context(commit=False) as db:
            placeholders = ','.join(['?' for _ in routed_roles])
            db.execute(
                f"SELECT DISTINCT user_id FROM medical_team "
                f"WHERE senior_id = ? AND role IN ({placeholders}) AND active = 1 AND user_id IS NOT NULL",
                [user_id] + routed_roles
            )
            members = db.fetchall()

        for row in (members or []):
            member_id = row[0]
            if member_id:
                try:
                    send_push(member_id, title, body, data={
                        "type": "medical_alert",
                        "senior_id": user_id,
                        "severity": severity,
                        "alert_type": obs.get('type', '')
                    })
                    logger.debug(f"Push sent to team member {member_id} for {severity}")
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Push to medical team: {e}")


def _push_to_senior(user_id, obs, app):
    """Push notification to senior — rhythm-adapted via Text Rhythm."""
    try:
        # v10.7: Adapt message to brain state via agent_bridge
        message = obs["message"]
        try:
            from agent_bridge import compose_proactive_message
            adapted = compose_proactive_message(user_id, message, obs.get("severity", "INFO"))
            message = adapted.get('text', message)
        except (ImportError, Exception):
            pass

        send_push = app.config.get('SEND_PUSH_FN')
        if send_push:
            send_push(user_id, "Radim — pozornost",
                      message,
                      data={"type": "agent_observation", "severity": obs["severity"]})
    except Exception as e:
        logger.debug(f"push_to_senior error: {e}")


def _alert_caregiver(user_id, obs, app):
    """Notify caregiver via push + SocketIO + in-app notification (v10.37).

    In-app notification goes to every confirmed family member linked via
    senior_family_links + the legacy single caregiver_id from memory_profiles.
    """
    try:
        # v10.37: In-app notification to all linked family + legacy caregiver
        try:
            from notification_helpers import notify_senior_family
            severity_map = {"WARNING": "warning", "ALERT": "alert", "CRISIS": "crisis"}
            nice_sev = severity_map.get(obs.get("severity", "").upper(), "alert")
            notif_type = "crisis_alert" if nice_sev == "crisis" else "health_alert"
            notify_senior_family(
                senior_id=user_id, type=notif_type,
                title=f"Radim upozorňuje — {obs.get('severity', 'alert')}",
                body=obs.get("message", ""),
                severity=nice_sev,
                data={"obs_type": obs.get("type") or obs.get("observation_type")},
                include_caregiver=True,
            )
        except Exception as e:
            logger.debug(f"alert_caregiver in-app notify: {e}")

        # Legacy push + SocketIO paths (keep for backward compat)
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
    # v460: Skip SMS for demo/seeded users (prevent Twilio daily limit exhaustion)
    if str(user_id).startswith('senior-') or str(user_id).startswith('test-'):
        logger.debug(f"Skipping crisis SMS for demo user {user_id}")
        return
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

        # v3.1: Auto-initiate video call with emergency contact on CRISIS
        _initiate_crisis_video_call(user_id, obs, app)

    except Exception as e:
        logger.debug(f"crisis_escalate error: {e}")


def _initiate_crisis_video_call(user_id, obs, app):
    """Auto-initiate video call to emergency contact on CRISIS."""
    try:
        profile = db_load_profile(user_id)
        contacts = profile.get("emergency_contacts", [])
        name = profile.get("name", "Senior")

        if not contacts:
            return

        # Find first contact with phone
        contact = next((c for c in contacts if c.get("phone")), None)
        if not contact:
            return

        import time
        room_code = f"radim-crisis-{int(time.time())}"
        jitsi_url = f"https://meet.jit.si/{room_code}"

        # 1. Notify senior's frontend to open video call
        try:
            from app import socketio
            socketio.emit('incoming_call', {
                'room_code': room_code,
                'jitsi_url': jitsi_url,
                'caller_name': f"Nouzový hovor ({contact.get('name', 'Kontakt')})",
                'call_type': 'video',
                'reason': 'agent_crisis',
                'auto_accept': True,  # Frontend auto-accepts crisis calls
                'senior_id': user_id,
            }, room=user_id)
        except Exception:
            pass

        # 2. Send SMS/WhatsApp to emergency contact with join link
        try:
            from twilio_voice_helpers import get_twilio_client
            client = get_twilio_client()
            phone = contact.get("phone", "").strip()
            if not phone.startswith('+'):
                phone = '+420' + phone.lstrip('0')
            if client:
                msg = (f"🚨 KRIZE: {name} potřebuje pomoc!\n"
                       f"Připojte se na video hovor: {jitsi_url}\n"
                       f"Důvod: {obs.get('message', '')[:80]}")
                client.messages.create(to=phone, from_=os.environ.get('TWILIO_PHONE_NUMBER', ''), body=msg)
                logger.info(f"📹 Crisis video call initiated: {name} ↔ {contact.get('name')} (room={room_code})")
        except Exception as e:
            logger.debug(f"Crisis video SMS error: {e}")

        audit_log(user_id, "crisis_video_call", "agent_loop",
                  f"Video call room={room_code} with {contact.get('name', '?')}")

    except Exception as e:
        logger.debug(f"Crisis video call error: {e}")


def _call_senior(user_id, obs):
    """Proactive phone call to senior (v387)."""
    # v460: Skip calls to demo/seeded users
    if str(user_id).startswith('senior-') or str(user_id).startswith('test-'):
        return
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

        # v10.20: Compute brain Ψ(t) → voice_mode for proactive call
        _call_mode = 'ALERT'  # default for proactive calls
        try:
            from brain_core import compute_psi_state
            from intent_resolver import quick_estimate_from_text
            C_est, alpha_est = quick_estimate_from_text(greeting)
            psi = compute_psi_state(C_est, alpha_est, user_id=user_id)
            _call_mode = psi.get('mode', 'ALERT')
            logger.info(f"📞 Proactive call brain: mode={_call_mode} for {user_id}")
        except Exception:
            pass

        result = initiate_proactive_call(phone, greeting, user_id=user_id, reason=obs["type"], voice_mode=_call_mode)
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

        # v10.10: Subscription cleanup — expired/inactive accounts
        try:
            _cleanup_subscriptions(db=None)
        except Exception as e:
            logger.debug(f"Subscription cleanup error: {e}")

        # v10.36: Safe Web Agent — cleanup stale in-memory sessions (15-min TTL)
        try:
            from browser_agent_safe import cleanup_safe_web_sessions
            removed = cleanup_safe_web_sessions()
            if removed:
                logger.info(f"🧹 Safe Web Agent cleanup: {removed} stale sessions removed")
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Safe Web cleanup error: {e}")


def _cleanup_subscriptions(db=None):
    """Auto-manage expired subscriptions and inactive accounts.

    Rules:
    - Trial > 14 days → set to 'expired'
    - Expired > 30 days → suspend (limited functionality)
    - Suspended > 60 days with no activity → anonymize data (GDPR)
    - No interaction > 90 days + not 'active' → flag for deletion

    Runs daily at 3:00 AM (inside run_daily_cleanup).
    """
    from datetime import datetime, timedelta
    now = datetime.utcnow()

    try:
        with db_context(commit=True) as db:
            if not is_postgres():
                return  # SQLite doesn't need this

            # 1. Trial expired (>14 days)
            r1 = db.execute("""
                UPDATE auth_users
                SET subscription_status = 'expired'
                WHERE subscription_status = 'trial'
                AND trial_started < NOW() - INTERVAL '14 days'
            """)
            if r1 and r1.rowcount > 0:
                logger.info(f"📋 Subscription: {r1.rowcount} trial(s) expired")

            # 2. Expired > 30 days → suspend
            r2 = db.execute("""
                UPDATE auth_users
                SET subscription_status = 'suspended'
                WHERE subscription_status = 'expired'
                AND subscription_expires IS NOT NULL
                AND subscription_expires < NOW() - INTERVAL '30 days'
            """)
            if r2 and r2.rowcount > 0:
                logger.info(f"📋 Subscription: {r2.rowcount} account(s) suspended (30d expired)")

            # 3. Find accounts to flag for deletion (suspended > 60d, no activity 90d)
            flagged = db.execute("""
                SELECT id, email, name, subscription_status, last_active
                FROM auth_users
                WHERE subscription_status = 'suspended'
                AND (last_active IS NULL OR last_active < NOW() - INTERVAL '90 days')
            """).fetchall()

            for row in (flagged or []):
                uid, email, name = row[0], row[1], row[2]
                # Log observation for admin visibility
                try:
                    db.execute("""
                        INSERT INTO agent_observations
                        (user_id, type, severity, message, created_at)
                        VALUES (?, 'account_cleanup', 'WARNING', ?, ?)
                    """, (
                        str(uid),
                        f"Účet {name or email} je neaktivní >90 dní a suspended. Doporučeno smazání.",
                        now.isoformat()
                    ))
                except Exception:
                    pass

                logger.info(f"📋 Flagged for deletion: {email} (id={uid}, suspended, inactive >90d)")

    except Exception as e:
        logger.debug(f"Subscription cleanup: {e}")



# ============================================================================
# ACTIVITY SUGGESTION — push UI actions to inactive seniors (v431)
# ============================================================================

_activity_cooldown = {}  # user_id → last suggestion timestamp

def suggest_activity(user_id, app):
    """Suggest an activity to a senior via SocketIO agent_action.
    Respects 2-hour cooldown per user. Called from run_agent_cycle()
    when interaction_silence detected at INFO level."""
    import time, random
    now = time.time()

    # Cooldown: max 1 suggestion per 2 hours
    if now - _activity_cooldown.get(user_id, 0) < 7200:
        return

    # v478: Respect Radim mode — observer gets no suggestions
    profile = db_load_profile(user_id)
    radim_mode = profile.get('radim_mode', 'guide')
    if radim_mode == 'observer':
        return

    # v477: Personalized suggestions based on interests, time, weather
    activities = [
        {'module': 'quiz', 'speak': 'Co takhle malý kvíz na trénink paměti?'},
        {'module': 'exercises', 'speak': 'Pojďme si trochu zacvičit, co říkáte?'},
        {'module': 'stories', 'speak': 'Mám pro vás hezký příběh. Chcete si poslechnout?'},
        {'module': 'news', 'speak': 'Podívejme se, co je nového ve zprávách.'},
        {'module': 'music', 'speak': 'Co takhle pustit si příjemnou hudbu?'},
    ]

    # Personalize based on interests
    try:
        profile = db_load_profile(user_id)
        learning = db_load_learning(user_id)
        interests = learning.get('detected_interests', {})
        personal = profile.get('personal', {})
        hour = __import__('datetime').datetime.now().hour

        # Morning → news, exercises
        if hour < 11:
            activities.append({'module': 'news', 'speak': 'Dobré ráno! Podíváme se na ranní zprávy?'})
            activities.append({'module': 'exercises', 'speak': 'Dobré ráno! Co takhle ranní rozcvička?'})
        # Afternoon → walks, music
        elif hour < 17:
            activities.append({'module': 'music', 'speak': 'Krásné odpoledne. Pustit si rádio?'})
        # Evening → stories, relax
        else:
            activities.append({'module': 'stories', 'speak': 'Hezký večer. Co takhle příběh na dobrou noc?'})
            activities.append({'module': 'music', 'speak': 'Večerní klid. Pustit relaxační hudbu?'})

        # Interest-based
        if interests.get('garden', 0) > 2:
            activities.append({'module': 'chat', 'speak': 'Jak vám roste zahrádka? Potřebujete poradit?'})
        if interests.get('music', 0) > 2 and personal.get('favorite_music'):
            fav = personal['favorite_music'][0] if personal['favorite_music'] else 'hudbu'
            activities.append({'module': 'music', 'speak': f'Pustit vám {fav}?'})
        if interests.get('family', 0) > 2:
            activities.append({'module': 'calls', 'speak': 'Nechcete zavolat rodině?'})

    except Exception:
        pass

    activity = random.choice(activities)

    try:
        with app.app_context():
            from app import socketio
            socketio.emit('agent_action', {
                'user_id': user_id,
                'action': 'showModule',
                'module': activity['module'],
                'speak': activity['speak']
            }, room=f'user_{user_id}')
            _activity_cooldown[user_id] = now
            logger.info(f"🎯 Activity suggested to {user_id}: {activity['module']}")
    except Exception as e:
        logger.debug(f"Activity suggestion error: {e}")


# ============================================================================
# DAILY ENGAGEMENT (v445 — positive proactive interaction)
# ============================================================================

def run_daily_engagement(app):
    """Afternoon engagement: positive suggestions based on weather, interests, nameday.

    Called by APScheduler at 14:00.
    Sends push notification with encouraging activity suggestion.
    """
    if not _AVAILABLE:
        return

    import random
    from datetime import datetime

    with app.app_context():
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT DISTINCT user_id FROM memory_profiles"
                ).fetchall()

            if not rows:
                return

            # Get weather for context
            weather_text = ""
            try:
                import urllib.request, json
                w = json.loads(urllib.request.urlopen("https://wttr.in/Prague?format=j1", timeout=5).read())
                temp = w['current_condition'][0]['temp_C']
                desc = w['current_condition'][0].get('lang_cs', [{}])
                desc_text = desc[0].get('value', '') if desc else ''
                weather_text = f"{temp}°C, {desc_text}"
            except Exception:
                weather_text = "příjemný den"

            # Engagement templates
            templates = [
                f"☀️ Venku je {weather_text}. Co takhle krátká procházka?",
                "🧠 Máme připravený nový kvíz! Chcete si zatrénovat paměť?",
                "📖 Mám pro vás nový příběh. Chcete si poslechnout?",
                f"🌤️ Dnes je {weather_text}. Zkuste si udělat chvilku jen pro sebe.",
                "🎵 Co takhle pustit si něco příjemného a relaxovat?",
                "💪 Připravil jsem pro vás krátké cvičení. Zacvičíme si?",
                "📰 Mám čerstvé zprávy. Chcete vědět co je nového?",
            ]

            for row in rows:
                user_id = row[0] if isinstance(row, (list, tuple)) else row['user_id']
                try:
                    # Check if user had recent interaction (< 4h) → skip
                    with db_context() as db:
                        recent = db.execute(
                            "SELECT COUNT(*) FROM memory_history WHERE user_id = ? AND created_at > NOW() - INTERVAL '4 hours'",
                            (user_id,)
                        ).fetchone()
                        if recent and recent[0] > 0:
                            continue  # User is active, don't bother

                    message = random.choice(templates)

                    # Try push notification
                    try:
                        from push_helpers import send_push
                        send_push(user_id, "Radim 💬", message)
                    except Exception:
                        pass

                    # SocketIO
                    try:
                        from flask_socketio import emit
                        emit('engagement', {
                            'message': message,
                            'type': 'positive'
                        }, room=f'user_{user_id}', namespace='/')
                    except Exception:
                        pass

                    logger.debug(f"🌟 Engagement sent to {user_id}: {message[:50]}")

                except Exception as e:
                    logger.debug(f"Engagement skip {user_id}: {e}")

            logger.info(f"🌟 Daily engagement: {len(rows)} users processed")

        except Exception as e:
            logger.error(f"Daily engagement error: {e}")


# ============================================================================
# DAILY SUMMARY EMAIL for caregivers (v446 — 20:00)
# ============================================================================

def run_daily_summary(app):
    """Send daily summary email to caregivers about their seniors.

    Called by APScheduler at 20:00.
    Aggregates: messages, brain states, observations, last activity.
    """
    if not _AVAILABLE:
        return

    import json
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import os

    with app.app_context():
        try:
            # Find caregivers with email
            caregivers = []
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, email, name FROM auth_users WHERE role IN ('caregiver', 'teacher', 'administrator')"
                ).fetchall()
                caregivers = [dict(r) for r in rows]

            if not caregivers:
                return

            # Aggregate today's data
            with db_context() as db:
                # Messages today
                msg_counts = {}
                rows = db.execute(
                    "SELECT user_id, COUNT(*) as cnt FROM memory_history WHERE created_at > CURRENT_DATE GROUP BY user_id"
                ).fetchall()
                for r in rows:
                    msg_counts[r[0] if isinstance(r, (list, tuple)) else r['user_id']] = r[1] if isinstance(r, (list, tuple)) else r['cnt']

                # Brain states today
                brain_avg = {}
                rows = db.execute(
                    "SELECT user_id, AVG(c) as avg_c, MAX(mode) as last_mode FROM brain_states WHERE created_at > CURRENT_DATE GROUP BY user_id"
                ).fetchall()
                for r in rows:
                    uid = r[0] if isinstance(r, (list, tuple)) else r['user_id']
                    brain_avg[uid] = {
                        'avg_c': round(float(r[1] if isinstance(r, (list, tuple)) else r['avg_c']), 1),
                        'mode': r[2] if isinstance(r, (list, tuple)) else r['last_mode']
                    }

                # Observations today
                obs_today = []
                rows = db.execute(
                    "SELECT user_id, severity, message FROM agent_observations WHERE created_at > CURRENT_DATE ORDER BY created_at DESC"
                ).fetchall()
                for r in rows:
                    obs_today.append({
                        'user_id': r[0] if isinstance(r, (list, tuple)) else r['user_id'],
                        'severity': r[1] if isinstance(r, (list, tuple)) else r['severity'],
                        'message': r[2] if isinstance(r, (list, tuple)) else r['message']
                    })

                # Seniors list
                seniors = []
                rows = db.execute("SELECT id, data FROM memory_profiles").fetchall()
                for r in rows:
                    uid = r[0] if isinstance(r, (list, tuple)) else r['user_id']
                    data = r[1] if isinstance(r, (list, tuple)) else r['data']
                    if isinstance(data, str):
                        data = json.loads(data)
                    name = data.get('name', uid[:12])
                    seniors.append({'id': uid, 'name': name})

            # Build email
            from datetime import datetime
            today = datetime.now().strftime('%d.%m.%Y')

            warnings = [o for o in obs_today if o['severity'] in ('WARNING', 'ALERT', 'CRISIS')]
            total_msgs = sum(msg_counts.values())

            body_lines = [
                f"<h2>📊 Denní přehled — {today}</h2>",
                f"<p><strong>{len(seniors)} seniorů</strong> · <strong>{total_msgs} zpráv</strong> · <strong>{len(warnings)} upozornění</strong></p>",
            ]

            if warnings:
                body_lines.append("<h3>⚠️ Upozornění</h3><ul>")
                for w in warnings[:10]:
                    name = next((s['name'] for s in seniors if s['id'] == w['user_id']), w['user_id'][:12])
                    body_lines.append(f"<li><strong>{name}</strong> ({w['severity']}): {w['message']}</li>")
                body_lines.append("</ul>")

            body_lines.append("<h3>👥 Senioři</h3><table style='width:100%;border-collapse:collapse;'>")
            body_lines.append("<tr style='background:#f7fafc;'><th style='padding:8px;text-align:left;'>Jméno</th><th>Zprávy</th><th>Brain C</th><th>Mode</th></tr>")
            for s in seniors[:20]:
                msgs = msg_counts.get(s['id'], 0)
                brain = brain_avg.get(s['id'], {})
                avg_c = brain.get('avg_c', '—')
                mode = brain.get('mode', '—')
                body_lines.append(
                    f"<tr><td style='padding:6px;'>{s['name']}</td>"
                    f"<td style='text-align:center;'>{msgs}</td>"
                    f"<td style='text-align:center;'>{avg_c}</td>"
                    f"<td style='text-align:center;'>{mode}</td></tr>"
                )
            body_lines.append("</table>")
            body_lines.append("<hr><p style='color:#a0aec0;font-size:12px;'>Radim Care — denní automatický přehled</p>")

            html = f"""<div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
                {''.join(body_lines)}
            </div>"""

            # Send to each caregiver
            smtp_host = os.environ.get('SMTP_HOST', '')
            smtp_port = int(os.environ.get('SMTP_PORT', '465'))
            smtp_user = os.environ.get('SMTP_USER', '')
            smtp_pass = os.environ.get('SMTP_PASS', '')
            smtp_from = os.environ.get('SMTP_FROM', smtp_user)

            if not smtp_host or not smtp_user or not smtp_pass:
                logger.warning("SMTP not configured for daily summary")
                return

            for cg in caregivers:
                if not cg.get('email'):
                    continue
                try:
                    msg = MIMEMultipart('alternative')
                    msg['From'] = f"Radim Care <{smtp_from}>"
                    msg['To'] = cg['email']
                    msg['Subject'] = f"📊 Denní přehled seniorů — {today}"
                    msg.attach(MIMEText(html, 'html', 'utf-8'))

                    if smtp_port == 465:
                        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(smtp_from, cg['email'], msg.as_string())
                    else:
                        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                            server.starttls()
                            server.login(smtp_user, smtp_pass)
                            server.sendmail(smtp_from, cg['email'], msg.as_string())

                    logger.info(f"📧 Daily summary sent to {cg['email']}")
                except Exception as e:
                    logger.warning(f"Daily summary email error for {cg['email']}: {e}")

        except Exception as e:
            logger.error(f"Daily summary error: {e}")


# ============================================================================
# WEEKLY REPORTS (v10.32 — activate WeeklyReportAgent)
# ============================================================================

def run_weekly_reports(app):
    """Generate + send weekly reports for each active senior's family.

    Called by APScheduler cron at Sunday 18:00.
    Produces rich 7-day summary (interactions, mood trend, observations,
    sleep quality, medication compliance, social isolation, highlights).
    """
    if not _AVAILABLE:
        return

    with app.app_context():
        try:
            from advanced_agents import WeeklyReportAgent
        except ImportError:
            logger.warning("advanced_agents not available — skipping weekly reports")
            return

        try:
            with db_context() as db:
                if is_postgres():
                    rows = db.execute(
                        "SELECT DISTINCT user_id FROM brain_states "
                        "WHERE created_at > NOW() - INTERVAL '7 days'"
                    ).fetchall()
                else:
                    rows = db.execute(
                        "SELECT DISTINCT user_id FROM brain_states "
                        "WHERE created_at > datetime('now', '-7 days')"
                    ).fetchall()
        except Exception as e:
            logger.warning(f"Weekly reports user list error: {e}")
            return

        if not rows:
            logger.info("📊 Weekly reports: no active seniors in last 7 days")
            return

        sent = 0
        for row in rows:
            user_id = row[0] if isinstance(row, (list, tuple)) else row['user_id']
            if not user_id:
                continue
            if str(user_id).startswith('demo_') or str(user_id).startswith('test_'):
                continue
            try:
                report = WeeklyReportAgent.generate_report(user_id, days=7)
                if report and not report.get('error'):
                    # Try to email family/caregiver if configured
                    try:
                        _send_weekly_report_email(user_id, report, app)
                        sent += 1
                    except Exception as e:
                        logger.debug(f"Weekly report email {user_id}: {e}")
                    # Also save to learning so chat can reference it
                    try:
                        learning = db_load_learning(user_id)
                        learning['last_weekly_report'] = {
                            'date': datetime.utcnow().strftime('%Y-%m-%d'),
                            'summary': report.get('sections', {}).get('summary', ''),
                        }
                        db_save_learning(user_id, learning)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Weekly report for {user_id}: {e}")

        if sent > 0:
            logger.info(f"📊 Weekly reports: sent {sent} family emails")


def _send_weekly_report_email(user_id, report, app):
    """Email the report to family / primary caregiver if configured."""
    try:
        import os, smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        profile = db_load_profile(user_id)
        recipients = []
        # Primary caregiver
        caregiver_id = profile.get('caregiver_id')
        if caregiver_id:
            with db_context() as db:
                r = db.execute(
                    "SELECT email FROM auth_users WHERE id = ? AND email IS NOT NULL",
                    (caregiver_id,)
                ).fetchone()
                if r:
                    email = r.get('email') if isinstance(r, dict) else r[0]
                    if email:
                        recipients.append(email)
        # Emergency contacts
        for ec in (profile.get('emergency_contacts') or []):
            ce = ec.get('email') if isinstance(ec, dict) else None
            if ce:
                recipients.append(ce)

        if not recipients:
            return

        SMTP_HOST = os.environ.get('SMTP_HOST')
        SMTP_USER = os.environ.get('SMTP_USER')
        SMTP_PASS = os.environ.get('SMTP_PASS')
        SMTP_FROM = os.environ.get('SMTP_FROM', 'radim@radimcare.cz')
        if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
            return

        name = report.get('name', 'Senior')
        sections = report.get('sections', {})
        body_parts = [f"Týdenní report — {name}", f"Období: {report.get('period')}", ""]
        for key, val in sections.items():
            body_parts.append(f"── {key.upper()} ──")
            if isinstance(val, dict):
                for k, v in val.items():
                    body_parts.append(f"  {k}: {v}")
            else:
                body_parts.append(f"  {val}")
            body_parts.append("")
        body = "\n".join(body_parts)

        for to_email in set(recipients):
            msg = MIMEMultipart()
            msg['From'] = SMTP_FROM
            msg['To'] = to_email
            msg['Subject'] = f"📊 Radim — týdenní report ({name})"
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            with smtplib.SMTP(SMTP_HOST, int(os.environ.get('SMTP_PORT', 587))) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.sendmail(SMTP_FROM, [to_email], msg.as_string())
    except Exception as e:
        logger.debug(f"Weekly email send error: {e}")


def _get_user_sensitivity(user_id):
    """Get adaptive sensitivity from Learning Agent (0.5-1.5, default 1.0)."""
    try:
        learning = db_load_learning(user_id)
        return learning.get("agent_sensitivity", 1.0)
    except Exception:
        return 1.0


# ============================================================================
# 🤖 ADVANCED AGENTS INTEGRATION (v3.0)
# ============================================================================

def _run_advanced_agents(user_id, baselines, observations):
    """Run all advanced agents and add their observations.

    Called once per user per agent cycle (every 5 min).
    Each agent is try/excepted independently — one failure doesn't block others.
    """

    # 1. Predictive Agent — 24h risk prediction
    try:
        from predictive_agent import predict_risk
        prediction = predict_risk(user_id)
        risk_score = prediction.get('risk_score', 0)
        risk_level = prediction.get('risk_level', 'low')
        _gen = False

        if risk_level == 'critical' and not _is_in_cooldown(user_id, 'prediction_critical'):
            observations.append({
                "type": "prediction_critical",
                "severity": CRISIS,
                "message": f"Prediktivní model detekoval kritické riziko (skóre {risk_score}/100). {prediction.get('prediction', '')}",
                "details": {"risk_score": risk_score, "actions": prediction.get('recommended_actions', [])}
            })
            _gen = True
        elif risk_level == 'high' and not _is_in_cooldown(user_id, 'prediction_high'):
            observations.append({
                "type": "prediction_high",
                "severity": ALERT,
                "message": f"Predikce ukazuje vysoké riziko (skóre {risk_score}/100). Doporučujeme zvýšený dohled.",
                "details": {"risk_score": risk_score}
            })
            _gen = True
        _track_agent('PredictiveAgent', _gen)
    except Exception as e:
        logger.debug(f"Predictive agent error for {user_id}: {e}")

    # 2. Sleep Agent — analyze last night
    try:
        from advanced_agents import SleepAgent
        sleep = SleepAgent.analyze_sleep(user_id)
        SleepAgent.save_sleep_analysis(user_id, sleep)
        _gen = False

        if sleep.get('quality') == 'very_poor' and not _is_in_cooldown(user_id, 'sleep_poor'):
            observations.append({
                "type": "sleep_poor",
                "severity": WARNING,
                "message": f"Poslední noc byl špatný spánek ({sleep.get('motion_events', '?')} pohybových událostí). Jak se cítíte?",
                "details": sleep
            })
            _gen = True
        _track_agent('SleepAgent', _gen)
    except Exception as e:
        logger.debug(f"Sleep agent error for {user_id}: {e}")

    # 3. Social Isolation — weekly check (only run once per day)
    try:
        from advanced_agents import SocialIsolationAgent
        isolation = SocialIsolationAgent.compute_score(user_id)
        _gen = False

        if isolation.get('level') == 'critical' and not _is_in_cooldown(user_id, 'isolation_critical'):
            observations.append({
                "type": "isolation_critical",
                "severity": ALERT,
                "message": "Senior vykazuje vysokou míru izolace. Doporučujeme sociální aktivitu nebo kontakt s rodinou.",
                "details": isolation
            })
            _gen = True
        elif isolation.get('level') == 'high' and not _is_in_cooldown(user_id, 'isolation_high'):
            observations.append({
                "type": "isolation_high",
                "severity": WARNING,
                "message": "Všimli jsme si, že jste méně komunikoval/a. Chcete si popovídat nebo zavolat rodině?",
                "details": isolation
            })
            _gen = True
        _track_agent('SocialIsolationAgent', _gen)
    except Exception as e:
        logger.debug(f"Isolation agent error for {user_id}: {e}")

    # 4. Medication compliance — check if missed recently
    try:
        from advanced_agents import MedicationTracker
        compliance = MedicationTracker.get_compliance(user_id, days=7)
        _gen = False

        pct = compliance.get('compliance_pct')
        if pct is not None and pct < 50 and not _is_in_cooldown(user_id, 'medication_low'):
            observations.append({
                "type": "medication_low",
                "severity": WARNING,
                "message": f"Za posledních 7 dní jste potvrdil/a léky jen v {pct:.0f}% případů. Nezapomínejte na pravidelné užívání.",
                "details": compliance
            })
            _gen = True
        _track_agent('MedicationTracker', _gen)
    except Exception as e:
        logger.debug(f"Medication agent error for {user_id}: {e}")

    # 5. Learning Agent — adapt thresholds (once per cycle, no observation)
    try:
        from advanced_agents import LearningAgent
        LearningAgent.update_thresholds(user_id)
        _track_agent('LearningAgent', False)
    except Exception as e:
        logger.debug(f"Learning agent error for {user_id}: {e}")

    # 5b. Anticipation Engine — predict Ĉ_{t+1}, detect anomalies
    try:
        from anticipation_engine import run_anticipation_cycle
        obs_before = len(observations)
        run_anticipation_cycle(user_id, observations)
        _track_agent('AnticipationEngine', len(observations) > obs_before)
    except Exception as e:
        logger.debug(f"Anticipation engine error for {user_id}: {e}")

    # 5c. Circadian proactive triggers — HA → Radim speaks at right time
    try:
        from circadian_engine import check_proactive_triggers, execute_proactive_trigger
        triggers = check_proactive_triggers(user_id, app)
        for trigger in triggers:
            execute_proactive_trigger(trigger, user_id, app)
        _track_agent('CircadianEngine', bool(triggers))
    except Exception as e:
        logger.debug(f"Circadian triggers error for {user_id}: {e}")

    # 6. Weather suggestions — inject into memory for next chat (once per day)
    try:
        from advanced_agents import WeatherAgent
        from memory_helpers import db_load_learning, db_save_learning
        learning = db_load_learning(user_id)
        last_weather = learning.get('last_weather_check', '')
        today = datetime.utcnow().strftime('%Y-%m-%d')
        _gen = False
        if last_weather != today:
            weather = WeatherAgent.get_suggestions()
            if weather.get('suggestions'):
                learning['weather_suggestions'] = weather['suggestions'][:2]
                learning['last_weather_check'] = today
                db_save_learning(user_id, learning)
                _gen = True
        _track_agent('WeatherAgent', _gen)
    except Exception as e:
        logger.debug(f"Weather agent error for {user_id}: {e}")

    # 7. Survey Engine — multi-signal risk assessment (replaces simple mood check)
    try:
        from survey_engine import compute_survey_risk, create_memory_hint
        risk = compute_survey_risk(user_id)
        severity_map = {'URGENT': CRISIS, 'WARNING': WARNING, 'WATCH': INFO}

        if risk['severity'] in ('WARNING', 'URGENT') and not _is_in_cooldown(user_id, 'survey_risk'):
            observations.append({
                "type": "survey_risk",
                "severity": severity_map.get(risk['severity'], WARNING),
                "message": risk['summary'],
                "details": {
                    "score": risk['score'],
                    "severity": risk['severity'],
                    "confidence": risk['confidence'],
                    "reasons": risk['reasons'][:3]
                }
            })
            # Create gentle memory hint for next chat
            create_memory_hint(user_id, risk)

        elif risk['severity'] == 'WATCH' and not _is_in_cooldown(user_id, 'survey_watch'):
            # Softer: just inject hint, no formal observation
            create_memory_hint(user_id, risk)

        _track_agent('SurveyEngine', risk['severity'] in ('WARNING', 'URGENT'))
    except Exception as e:
        logger.debug(f"Survey risk engine error for {user_id}: {e}")


# ============================================================================
# 🏠 HOME ASSISTANT INTEGRATION
# ============================================================================

def _sync_ha_sensors():
    """Sync Home Assistant sensors → iot_sensor_data DB.

    Called every 5 min at start of agent cycle.
    Writes temperature, humidity, motion, door data from HA to DB
    so all existing detectors (_check_activity, _check_vitals) work.
    """
    if not _HAS_HA:
        return

    try:
        ha_client = _get_ha()
        if not ha_client.connected:
            return

        sensors = ha_client.get_sensors_summary()
        if not sensors:
            return

        synced = 0
        with db_context(commit=True) as db:
            # Sync temperature sensors
            for s in sensors.get('temperature', []):
                _upsert_sensor(db, s['entity_id'], 'temperature', s['value'], s.get('name', ''))
                synced += 1

            # Sync humidity sensors
            for s in sensors.get('humidity', []):
                _upsert_sensor(db, s['entity_id'], 'humidity', s['value'], s.get('name', ''))
                synced += 1

            # Sync motion sensors
            for s in sensors.get('motion', []):
                val = 1.0 if s['state'] == 'on' else 0.0
                _upsert_sensor(db, s['entity_id'], 'motion', val, s.get('name', ''))
                synced += 1

            # Sync door sensors
            for s in sensors.get('door', []):
                val = 1.0 if s['state'] == 'on' else 0.0
                _upsert_sensor(db, s['entity_id'], 'door', val, s.get('name', ''))
                synced += 1

            # Sync battery (for low battery alerts)
            for s in sensors.get('battery', []):
                _upsert_sensor(db, s['entity_id'], 'battery', s['value'], s.get('name', ''))
                synced += 1

        if synced > 0:
            logger.debug(f"HA sync: {synced} sensors → DB")

    except Exception as e:
        logger.debug(f"HA sensor sync error: {e}")


def _upsert_sensor(db, entity_id, sensor_type, value, name=''):
    """Insert or update sensor data in iot_sensor_data."""
    try:
        # Extract room from entity_id (e.g., sensor.living_room_temperature → living_room)
        parts = entity_id.split('.')
        room_id = parts[1].rsplit('_', 1)[0] if len(parts) > 1 else 'unknown'

        # Ensure device exists
        if is_postgres():
            db.execute(
                "INSERT INTO iot_devices (device_id, device_type, room_id, device_name) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (device_id) DO UPDATE SET device_name = ?",
                (entity_id, sensor_type, room_id, name, name)
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO iot_devices (device_id, device_type, room_id, device_name) "
                "VALUES (?, ?, ?, ?)",
                (entity_id, sensor_type, room_id, name)
            )

        # Insert sensor reading
        db.execute(
            "INSERT INTO iot_sensor_data (device_id, sensor_type, value, room_id) VALUES (?, ?, ?, ?)",
            (entity_id, sensor_type, float(value), room_id)
        )
    except Exception as e:
        logger.debug(f"upsert_sensor {entity_id}: {e}")


def _ha_crisis_actions(user_id, obs):
    """Execute Home Assistant emergency actions on CRISIS/ALERT.

    - CRISIS: Turn on ALL lights, unlock front door (for paramedics)
    - ALERT: Turn on lights in user's room, flash hallway light
    """
    if not _HAS_HA:
        return

    try:
        ha_client = _get_ha()
        if not ha_client.connected:
            return

        severity = obs.get("severity", "")
        obs_type = obs.get("type", "")

        if severity == CRISIS:
            # 🚨 CRISIS: All lights ON + unlock door
            logger.info(f"🏠 HA CRISIS ACTIONS for {user_id}: lights ON, door UNLOCK")
            devices = ha_client.get_devices_by_type()

            # Turn on ALL lights at maximum brightness
            for light in devices.get('light', []):
                ha_client.light_on(light['entity_id'], brightness=100)

            # Unlock front door for paramedics
            for lock_dev in devices.get('lock', []):
                ha_client.unlock(lock_dev['entity_id'])

            # Open all covers/blinds
            for cover in devices.get('cover', []):
                ha_client.cover_open(cover['entity_id'])

            audit_log(user_id, "ha_crisis_action", "agent_loop",
                      "CRISIS: All lights ON, doors unlocked, covers opened")

        elif severity == ALERT:
            # ⚠️ ALERT: Lights on in main rooms
            logger.info(f"🏠 HA ALERT ACTIONS for {user_id}: lights ON")
            devices = ha_client.get_devices_by_type('light')
            for light in devices.get('light', []):
                if light['state'] == 'off':
                    ha_client.light_on(light['entity_id'], brightness=80)

            audit_log(user_id, "ha_alert_action", "agent_loop",
                      "ALERT: Lights turned on")

        elif severity == WARNING and obs_type == 'activity_drop':
            # 💡 WARNING + no activity: subtle light pulse
            logger.info(f"🏠 HA WARNING for {user_id}: checking lights")
            devices = ha_client.get_devices_by_type('light')
            # Ensure at least one light is on
            any_on = any(l['state'] == 'on' for l in devices.get('light', []))
            if not any_on:
                for light in devices.get('light', [])[:1]:
                    ha_client.light_on(light['entity_id'], brightness=40)

    except Exception as e:
        logger.warning(f"HA crisis actions error: {e}")


def _ha_check_environment(user_id):
    """Check HA environment sensors for potential issues.

    Returns observation or None.
    Called as part of _evaluate_user.
    """
    if not _HAS_HA:
        return None

    try:
        ha_client = _get_ha()
        if not ha_client.connected:
            return None

        sensors = ha_client.get_sensors_summary()

        # Check temperature extremes
        for t in sensors.get('temperature', []):
            if t['value'] < 16:
                return {"type": "environment_cold", "severity": WARNING,
                        "message": f"V místnosti {t['name']} je příliš chladno ({t['value']}°C). Zkontrolujte topení.",
                        "details": {"sensor": t['name'], "value": t['value'], "entity_id": t['entity_id']}}
            elif t['value'] > 30:
                return {"type": "environment_hot", "severity": WARNING,
                        "message": f"V místnosti {t['name']} je příliš horko ({t['value']}°C). Otevřete okna nebo zapněte ventilátor.",
                        "details": {"sensor": t['name'], "value": t['value'], "entity_id": t['entity_id']}}

        # Check low battery devices
        low = [s for s in sensors.get('battery', []) if s['value'] < 10]
        if low:
            names = ', '.join(s['name'] for s in low)
            return {"type": "low_battery", "severity": INFO,
                    "message": f"Nízká baterie u: {names}. Vyměňte baterie.",
                    "details": {"devices": [{'name': s['name'], 'level': s['value']} for s in low]}}

        # Check door open too long (would need tracking, skip for now)

    except Exception as e:
        logger.debug(f"HA environment check error: {e}")

    return None


logger.info("Agent Loop v2.0 loaded — monitoring + HA integration + calls + morning + cleanup + engagement + summary")
