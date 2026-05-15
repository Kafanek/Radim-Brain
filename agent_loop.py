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
import os
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

# Sprint AA: brain_math is the single source of truth for T1/T2.
try:
    from brain_math import T1, T2
except ImportError:
    T1 = 12  # HARMONY → ALERT
    T2 = 27  # ALERT → CRISIS

OBSERVATION_COOLDOWN_MINUTES = 60


# ============================================================================
# Sprint X20.1 — Heartbeat snapshot integration
# ============================================================================
# The math-engine heartbeat (agent/heartbeat.py + agent/runtime.py) is the
# single source of truth for live user state (C, α, mode, 30-min predicted
# horizon, preemptive trigger). agent_loop reads its snapshot once per cycle
# and detectors consume it instead of recomputing C themselves.
#
# Backward-compatible: if runtime / snapshot is unavailable, detectors fall
# back to the legacy learning.C_history path.

def _get_heartbeat_snapshot(user_id):
    """Force a fresh tick of the per-user heartbeat and return the snapshot.

    Returns None if the runtime isn't initialized (e.g. agent module failed
    to load, or in an isolated unit-test environment). Detectors must
    gracefully handle this.
    """
    try:
        from agent.runtime import get_runtime
    except ImportError:
        return None
    rt = get_runtime()
    if not rt:
        return None
    try:
        # force_tick is idempotent — it computes a snapshot from real DB
        # data and stores it in the per-user heartbeat. This means:
        #   1) agent_loop refreshes the snapshot for ALL active seniors,
        #      including those without an open browser tab.
        #   2) Subsequent /api/agent/heartbeat reads return fresh data.
        return rt.force_tick(user_id)
    except Exception as e:
        logger.debug(f"[agent_loop] heartbeat tick failed for {user_id}: {e}")
        return None


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
    """Find users with recent brain_states or IoT data (last 24h).

    v8.19.109: vylučuje role IN ('administrator', 'admin') — admini jsou
    operátoři systému, ne pacienti. Bez filtru spustil admin user 1
    32× emergency_protocol CRISIS / 24h ('Žádný dotazník za 16 dní'),
    bezvýznamné pro real monitoring. LEFT JOIN: pokud user_id nematchuje
    auth_users (např. UUID-style senior z mobile registrace), přesto
    zahrnut (default-allow).
    """
    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute("""
                    SELECT DISTINCT sub.user_id FROM (
                        SELECT user_id FROM brain_states WHERE created_at > NOW() - INTERVAL '24 hours'
                        UNION
                        SELECT DISTINCT d.user_id FROM iot_devices d
                        JOIN iot_sensor_data s ON s.device_id = d.device_id
                        WHERE s.recorded_at > NOW() - INTERVAL '24 hours' AND d.user_id IS NOT NULL
                    ) sub
                    LEFT JOIN auth_users au ON au.id::text = sub.user_id
                    WHERE au.role IS NULL OR au.role NOT IN ('administrator', 'admin')
                    LIMIT 100
                """).fetchall()
            else:
                rows = db.execute("""
                    SELECT DISTINCT sub.user_id FROM (
                        SELECT user_id FROM brain_states WHERE created_at > datetime('now', '-24 hours')
                        UNION
                        SELECT DISTINCT d.user_id FROM iot_devices d
                        JOIN iot_sensor_data s ON s.device_id = d.device_id
                        WHERE s.recorded_at > datetime('now', '-24 hours') AND d.user_id IS NOT NULL
                    ) sub
                    LEFT JOIN auth_users au ON CAST(au.id AS TEXT) = sub.user_id
                    WHERE au.role IS NULL OR au.role NOT IN ('administrator', 'admin')
                    LIMIT 100
                """).fetchall()
            uids = []
            for r in rows:
                # DictRow vs tuple safe access
                uid = r['user_id'] if hasattr(r, 'get') and r.get('user_id') is not None else r[0]
                if uid:
                    uids.append(uid)
            return uids
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

    # ── Sprint X20.1: refresh heartbeat snapshot once per cycle ──
    # All detectors below read from this single snapshot instead of
    # recomputing C/alpha/mode independently. Snapshot may be None if the
    # math-engine runtime isn't loaded — detectors fall back gracefully.
    snap = _get_heartbeat_snapshot(user_id)

    # ── Sprint X20.1/Fix 3: persona-aware thresholds ──
    # Each detector reads from per-user persona thresholds (senior /
    # child_autism / child_adhd) instead of hardcoded T1/T2 globals.
    # Stored once per cycle so all detectors share the same view.
    try:
        from agent.personas import get_thresholds_for_user
        thresholds = get_thresholds_for_user(user_id)
    except Exception as e:
        logger.debug(f"persona thresholds unavailable for {user_id}: {e}")
        thresholds = None  # detectors fall back to legacy T1/T2

    # ── v3.1: Get adaptive sensitivity from Learning Agent ──
    sensitivity = _get_user_sensitivity(user_id)

    # ── Core detectors ──
    # Sprint AF: _check_recent_chat_crisis added FIRST so a single safety
    # event (fall, pain, suicide-talk) triggers caregiver notification within
    # one 5-min cycle, not blocked by avg-of-5 in _check_c_trend.
    # Sprint X20.1: _check_heartbeat_preemptive added AFTER _check_c_trend so
    # rising trends get caught proactively (30-min lookahead).
    for check in (_check_recent_chat_crisis, _check_c_trend, _check_heartbeat_preemptive,
                  _check_activity_drop, _check_vitals, _check_interaction_silence,
                  _check_fall_detection, _check_smoke):
        # Detectors that opt-in to snapshot/thresholds use kwargs; legacy
        # detectors keep the (user_id, baselines) signature.
        try:
            import inspect
            sig = inspect.signature(check)
            params = sig.parameters
            kwargs = {}
            if 'snap' in params:        kwargs['snap'] = snap
            if 'thresholds' in params:  kwargs['thresholds'] = thresholds
        except (ValueError, TypeError):
            kwargs = {}
        obs = check(user_id, baselines, **kwargs) if kwargs else check(user_id, baselines)
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

    # ── Sprint X20.9: Automation triggers — time_of_day cycle tick ──
    # Run BEFORE goal evaluation so a "daily 22:00 → lock all doors" rule
    # fires before any new observations would conflict.
    try:
        from agent.automations import evaluate_for_user as _automation_eval
        _automation_eval(user_id, ctx={
            'event': 'cycle_tick',
            'now': datetime.now(),
            'current_mode': (snap.mode if snap else None),
        })
    except Exception as e:
        logger.debug(f"automations cycle_tick failed for {user_id}: {e}")

    # ── Sprint X20.1/Fix 6: Goal-driven planner ──
    # Proactive layer above detectors. Reads agent_user_goals for this user,
    # measures current state vs target over each goal's horizon, emits
    # observations when drift is detected (with severity escalation curve).
    try:
        from agent.planner import evaluate as _plan_evaluate
        goal_obs = _plan_evaluate(user_id) or []
        for gobs in goal_obs:
            # Skip INFO observations to avoid cluttering caregiver inbox —
            # they're recorded in agent_goal_progress for analytics. Only
            # WARNING+ surface as observations.
            if gobs.get('severity') == 'INFO':
                continue
            if not _is_in_cooldown(user_id, gobs['type']):
                if sensitivity < 0.6 and gobs['severity'] == 'WARNING':
                    continue
                observations.append(gobs)
    except Exception as e:
        logger.debug(f"planner evaluate failed for {user_id}: {e}")

    # ── v8.19.107: Tapo IoT detektory ──
    # T100 motion, T110 contact, P115 plug, L510E bulb, H110 hub
    for tapo_check in TAPO_DETECTORS:
        try:
            tobs = tapo_check(user_id)
            if tobs and not _is_in_cooldown(user_id, tobs["type"]):
                if sensitivity < 0.8 and tobs["severity"] == INFO:
                    continue
                observations.append(tobs)
        except Exception as e:
            logger.debug(f"Tapo detector {tapo_check.__name__}: {e}")

    # ── v3.0: Advanced agents integration ──
    _run_advanced_agents(user_id, baselines, observations)

    for obs in observations:
        _save_observation(user_id, obs)
        _execute_action(user_id, obs, app)


# ============================================================================
# ANOMALY DETECTORS
# ============================================================================

def _check_recent_chat_crisis(user_id, baselines, thresholds=None):
    """Sprint AF: detect a fresh CRISIS row in brain_states (chat-induced).

    Why this exists separately from _check_c_trend:
    The trend detector takes the average of the last 5 C values to filter
    out single noise spikes. But that's exactly the wrong behaviour for an
    actual emergency: if a senior with 4 prior calm chats says "spadl jsem"
    once, Sprint AD writes one C=30 row → the avg-of-5 stays ~10 → no
    alert → caregivers never notified, even though the chat path responded
    in CRISIS mode.

    This detector reads the latest brain_states row directly (last 30 min,
    same TTL as brain_speech_for_user) and fires CRISIS severity on any
    row with C >= T2 or mode='CRISIS'. Cooldown (60 min) still prevents
    duplicate notifications when the senior re-confirms the crisis.

    Returns the standard observation dict (type/severity/message/details).
    """
    try:
        with db_context() as db:
            # 30-min window matches brain_speech TTL — fresh = relevant.
            if is_postgres():
                row = db.execute(
                    "SELECT C, mode, created_at FROM brain_states "
                    "WHERE user_id = ? AND created_at > NOW() - INTERVAL '30 minutes' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT C, mode, created_at FROM brain_states "
                    "WHERE user_id = ? AND created_at > datetime('now', '-30 minutes') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id,)
                ).fetchone()
        if not row:
            return None

        # DictRow / tuple-safe access. PG RealDictRow lowercases identifiers,
        # SQLite Row uses original case.
        try:
            C_val = float(row.get('c', row.get('C', 0)) or 0)
            mode = (row.get('mode') or '').upper()
        except AttributeError:
            # plain tuple
            C_val = float(row[0] or 0)
            mode = (row[1] or '').upper()

        # Sprint X20.1/Fix 3 — persona-aware thresholds (fallback to T1/T2)
        t_crisis = (thresholds or {}).get('c_crisis', T2)
        t_alert  = (thresholds or {}).get('c_alert',  T1)

        if mode == 'CRISIS' or C_val >= t_crisis:
            # Sprint AG.4 dedupe: if any sender already emitted a recent
            # CRISIS observation for this user under the SAME topic in the
            # last 15 min (e.g. safety branch from Sprint AD already wrote
            # one), skip — caregiver was already notified.
            try:
                from agent_bus import dedupe as _bus_dedupe
                if _bus_dedupe(user_id, sender=None, topic='recent_chat_crisis',
                               within_minutes=15, any_sender=True,
                               severity_min='alert'):
                    return None
            except Exception:
                pass
            # Sprint AF: log only when actually triggering
            print(f"💢 recent_chat_crisis FIRE uid={user_id} C={C_val} mode={mode}", flush=True)
            return {
                "type": "recent_chat_crisis",
                "severity": CRISIS,
                "message": f"Uživatel právě hlásil krizovou situaci v rozhovoru (C={C_val:.0f}, mode={mode}). Okamžitá kontrola doporučena.",
                "details": {"C": C_val, "mode": mode, "source": "brain_states_recent"},
            }
        elif mode == 'ALERT' or C_val >= t_alert:
            try:
                from agent_bus import dedupe as _bus_dedupe
                if _bus_dedupe(user_id, sender=None, topic='recent_chat_alert',
                               within_minutes=15, any_sender=True,
                               severity_min='warning'):
                    return None
            except Exception:
                pass
            print(f"💢 recent_chat_alert FIRE uid={user_id} C={C_val} mode={mode}", flush=True)
            return {
                "type": "recent_chat_alert",
                "severity": ALERT,
                "message": f"Uživatel má zvýšený stres v rozhovoru (C={C_val:.0f}, mode={mode}).",
                "details": {"C": C_val, "mode": mode, "source": "brain_states_recent"},
            }
    except Exception as e:
        print(f"💢 recent_chat_crisis ERROR uid={user_id}: {type(e).__name__}: {e}", flush=True)
        logger.debug(f"_check_recent_chat_crisis non-fatal: {e}")
    return None


def _check_c_trend(user_id, baselines, snap=None, thresholds=None):
    """Detect rising C trend: recent avg vs baseline.

    Sprint X20.1: prefer the heartbeat snapshot's c_total (if available)
    over the legacy learning.C_history path. The snapshot is computed
    fresh at the start of each cycle by _get_heartbeat_snapshot, so it
    reflects current state across all 4 domains weighted by persona —
    not just the chat-derived C of the legacy code.

    Sprint X20.1/Fix 3: persona-aware thresholds (c_alert / c_crisis)
    replace global T1/T2 when available.

    Falls back to the legacy path when no snapshot is available (runtime
    not loaded, cold start, etc.).
    """
    # Determine `recent_value` — the "C right now" we'll compare to baseline.
    source = "legacy"
    if snap is not None:
        # snap.c_total is the persona-weighted composite C; use it directly.
        recent_value = float(snap.c_total)
        source = "heartbeat"
    else:
        learning = db_load_learning(user_id)
        c_history = [float(v) for v in learning.get("C_history", []) if v is not None]
        if len(c_history) < 5:
            return None
        recent_value, _ = _mean_std(c_history[-5:])

    baseline_avg = baselines.get("avg_C", 5.0)
    baseline_std = baselines.get("std_C", 3.0)
    if baseline_std < 0.5:
        baseline_std = 0.5  # minimum to avoid false positives

    # Sprint X20.1/Fix 3 — per-persona alert/crisis thresholds
    t_crisis = (thresholds or {}).get('c_crisis', T2)
    t_alert  = (thresholds or {}).get('c_alert',  T1)
    persona_id = (thresholds or {}).get('_persona_id')  # informational

    common_details = {"recent_value": recent_value, "baseline_avg": baseline_avg,
                      "source": source, "t_alert": t_alert, "t_crisis": t_crisis}

    if recent_value > t_crisis:
        return {"type": "c_trend_rising", "severity": CRISIS,
                "message": "Uživatel je ve velmi silném stresu a potřebuje okamžitou pomoc.",
                "details": common_details}
    elif recent_value > t_alert:
        return {"type": "c_trend_rising", "severity": ALERT,
                "message": "Uživatel je ve zvýšeném stresu — buďte extra klidný a empatický.",
                "details": common_details}
    elif recent_value > baseline_avg + 1.5 * baseline_std:
        return {"type": "c_trend_rising", "severity": WARNING,
                "message": "Všimli jsme si, že jste v posledních rozhovorech napjatější než obvykle. Je vše v pořádku?",
                "details": {**common_details, "std": baseline_std}}
    return None


def _check_heartbeat_preemptive(user_id, baselines, snap=None):
    """Sprint X20.1: act BEFORE the senior's state crosses into CRISIS.

    The math engine produces a 30-min predicted horizon based on EMA-smoothed
    trends + alpha coupling. When that horizon predicts an upward mode
    crossing (e.g. currently HARMONY but predicted to hit ALERT or CRISIS
    within 30 minutes), we fire a WARNING observation. This is the core
    proactive behavior — Radim acts ~5 minutes before legacy threshold-only
    detectors would catch it.

    Severity rules:
      HARMONY → CRISIS predicted   = ALERT
      HARMONY → ALERT  predicted   = WARNING
      ALERT   → CRISIS predicted   = ALERT
      ALERT   → ALERT  predicted   = (no obs — already covered by c_trend)
      CRISIS  → anything           = (no obs — c_trend already fires CRISIS)

    Cooldown of 60 min prevents repeated preemptive observations during a
    sustained climb.
    """
    if snap is None or not snap.preemptive.crosses_up:
        return None

    current_mode = snap.preemptive.current_mode
    predicted_mode = snap.preemptive.predicted_mode
    peak_c = snap.preemptive.peak_c
    peak_min = snap.preemptive.peak_at_minute

    if current_mode == "CRISIS":
        return None  # already in crisis — c_trend fires CRISIS
    if current_mode == "ALERT" and predicted_mode == "ALERT":
        return None  # no escalation predicted

    severity = ALERT if predicted_mode == "CRISIS" else WARNING
    msg = (f"Stav by se mohl během {peak_min} minut zhoršit "
           f"({current_mode} → {predicted_mode}). Reagujte preventivně.")
    return {
        "type": "heartbeat_preemptive",
        "severity": severity,
        "message": msg,
        "details": {
            "current_mode": current_mode,
            "predicted_mode": predicted_mode,
            "peak_c": round(peak_c, 2),
            "peak_at_minute": peak_min,
            "current_c": round(snap.c_total, 2),
            "alpha": round(snap.state.alpha, 3),
        },
    }


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


def _check_vitals(user_id, baselines, thresholds=None):
    """Detect vital signs outside personal baseline.

    Sprint X20.1/Fix 3: persona-tuned absolute thresholds for HR and SpO2
    (in addition to baseline-deviation logic which stays the same).
    """
    vitals_bl = baselines.get("vitals", {})
    if not vitals_bl:
        return None

    t = thresholds or {}
    hr_high   = t.get('hr_high', 100)
    hr_low    = t.get('hr_low',   50)
    spo2_low  = t.get('spo2_low', 95)

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

                # SpO2 < 90 is always CRISIS regardless of baseline (life safety).
                if sensor == 'spo2' and val < 90:
                    return {"type": "vital_anomaly", "severity": CRISIS,
                            "message": f"Hladina kyslíku v krvi je nebezpečně nízká ({val:.0f}%). Je třeba zavolat pomoc.",
                            "details": {"sensor": sensor, "value": val, "baseline_avg": avg}}

                # Sprint X20.1/Fix 3 — persona-tuned ABSOLUTE thresholds.
                # SpO2 below persona's spo2_low triggers ALERT (e.g. 95 senior,
                # 95 child — same in current presets but tunable).
                if sensor == 'spo2' and val < spo2_low:
                    return {"type": "vital_anomaly", "severity": ALERT,
                            "message": f"Hladina kyslíku ({val:.0f}%) je pod doporučenou hranicí ({spo2_low}%). Zkontrolujte, jak se cítí.",
                            "details": {"sensor": sensor, "value": val, "threshold": spo2_low,
                                        "kind": "persona_absolute"}}
                # HR outside persona band → WARNING (baseline σ check below
                # may upgrade to ALERT for sustained anomaly).
                if sensor == 'heart_rate' and (val > hr_high or val < hr_low):
                    return {"type": "vital_anomaly", "severity": WARNING,
                            "message": f"Tepová frekvence ({val:.0f}) je mimo obvyklý rozsah ({hr_low}–{hr_high}). Jak se cítíte?",
                            "details": {"sensor": sensor, "value": val,
                                        "band": [hr_low, hr_high],
                                        "kind": "persona_absolute"}}

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


def _check_interaction_silence(user_id, baselines, thresholds=None):
    """Detect prolonged silence (no interactions).

    Sprint X20.1/Fix 3: silence windows are persona-tuned —
    child_adhd has 6h warning / 12h alert (engagement matters),
    senior has 24h / 48h (default), child_autism has 12h / 24h.
    """
    learning = db_load_learning(user_id)
    last = learning.get("last_interaction")
    if not last:
        return None

    try:
        last_dt = datetime.fromisoformat(str(last).replace('Z', '+00:00').split('+')[0])
        hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return None

    t = thresholds or {}
    h_warn   = t.get('silence_warning_hours', 24)
    h_alert  = t.get('silence_alert_hours',   48)
    h_crisis = t.get('silence_crisis_hours',  72)

    if hours_since > h_crisis:
        return {"type": "no_interaction", "severity": CRISIS,
                "message": f"Uživatel se neozval už {hours_since:.0f} hodin. Doporučujeme okamžitou kontrolu.",
                "details": {"hours_since": round(hours_since, 1), "last": str(last),
                            "threshold_h": h_crisis}}
    elif hours_since > h_alert:
        return {"type": "no_interaction", "severity": ALERT,
                "message": f"Uživatel se neozval už {hours_since:.0f} hodin. Zeptejte se, jak se má, a nabídněte pomoc.",
                "details": {"hours_since": round(hours_since, 1), "last": str(last),
                            "threshold_h": h_alert}}
    elif hours_since > h_warn:
        return {"type": "no_interaction", "severity": WARNING,
                "message": "Nebyli jsme spolu v kontaktu celý den. Rád bych věděl, jak se vám daří.",
                "details": {"hours_since": round(hours_since, 1),
                            "threshold_h": h_warn}}
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


def _check_smoke(user_id, baselines):
    """Detect smoke alarm triggers — CRISIS severity (calls 150 fire dept).

    Reads from two sources:
      1. iot_sensor_data with sensor_type='smoke' (custom Zigbee gateway)
      2. HA per-user binary_sensor with device_class='smoke' (live state)

    Smoke alarm is the highest-severity event we handle: triggers crisis
    protocol immediately (lights ON, doors UNLOCKED, voice call to senior,
    SMS to family, push to caregiver).
    """
    # Path 1: IoT sensor table
    try:
        with db_context(commit=False) as db:
            row = db.execute("""
                SELECT s.device_id, s.value, s.recorded_at, d.device_name, da.room
                FROM iot_sensor_data s
                LEFT JOIN iot_devices d ON s.device_id = d.device_id
                LEFT JOIN device_assignments da
                  ON da.entity_id = d.device_id AND da.user_id = ?
                WHERE d.user_id = ? AND s.sensor_type = 'smoke'
                  AND s.recorded_at > ?
                  AND s.value > 0
                ORDER BY s.recorded_at DESC LIMIT 1
            """, (user_id, user_id,
                  (datetime.utcnow() - timedelta(minutes=10)).isoformat())).fetchone()
            if row:
                device_name = row[3] or row[0]
                room = row[4] or 'neznámá místnost'
                return {
                    "type": "smoke_detected",
                    "severity": CRISIS,
                    "message": f"🔥 KOUŘ DETEKOVÁN — {device_name} ({room}). Volám 150.",
                    "details": {
                        "device_id": row[0], "value": row[1],
                        "time": str(row[2]), "room": room,
                    },
                }
    except Exception as e:
        logger.debug(f"Smoke check (DB) error: {e}")

    # Path 2: Live HA state via per-user client
    try:
        from home_assistant import ha_for
        client = ha_for(user_id)
        if client and client.connected:
            for s in client.get_all_states() or []:
                eid = s.get('entity_id', '')
                attrs = s.get('attributes', {}) or {}
                if (attrs.get('device_class') == 'smoke'
                        and s.get('state') == 'on'):
                    name = attrs.get('friendly_name', eid)
                    return {
                        "type": "smoke_detected",
                        "severity": CRISIS,
                        "message": f"🔥 KOUŘ DETEKOVÁN — {name}. Volám 150.",
                        "details": {"entity_id": eid, "name": name},
                    }
    except Exception as e:
        logger.debug(f"Smoke check (HA) error: {e}")

    return None


# ============================================================================
# TAPO IoT DETECTORS (v8.19.107)
# ============================================================================
# Detektory specifické pro TP-Link Tapo zařízení (T100, T110, P115, L510E, H110).
# Volány z run_agent_cycle pro každého aktivního seniora. Každý vrací buď
# observation dict {type, severity, message, details} nebo None.
#
# Cooldown: každý observation_type má vlastní cooldown (60 min default), takže
# se neopakuje příliš často.

def _get_recent_iot(user_id, sensor_types, minutes=60):
    """Helper — fetch recent iot_sensor_data for user's rooms."""
    try:
        with db_context(commit=False) as db:
            # Map user_id → room_ids via iot_devices.user_id (set during enrollment)
            ph_list = ','.join(['?'] * len(sensor_types))
            cutoff = (datetime.utcnow() - timedelta(minutes=int(minutes))).isoformat()
            if is_postgres():
                rows = db.execute(
                    f"SELECT s.device_id, s.room_id, s.sensor_type, s.value, s.metadata, s.recorded_at "
                    f"FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = ? AND s.sensor_type IN ({ph_list}) "
                    f"AND s.recorded_at > ? "
                    f"ORDER BY s.recorded_at DESC LIMIT 200",
                    (user_id, *sensor_types, cutoff)
                ).fetchall()
            else:
                rows = db.execute(
                    f"SELECT s.device_id, s.room_id, s.sensor_type, s.value, s.metadata, s.recorded_at "
                    f"FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = ? AND s.sensor_type IN ({ph_list}) "
                    f"AND s.recorded_at > ? "
                    f"ORDER BY s.recorded_at DESC LIMIT 200",
                    (user_id, *sensor_types, cutoff)
                ).fetchall()
            return rows or []
    except Exception as e:
        logger.debug(f"_get_recent_iot error: {e}")
        return []


def _detect_no_motion_during_day(user_id):
    """T100 motion_detected — žádný pohyb 6+ hodin v aktivní době (8-22h).

    Pohyb se loguje event-style (1 = právě detekován, 0 = klid). Detektor
    hledá poslední row s value=1 napříč všemi T100 senzory. Pokud >6h
    a jsme v 8-22h → INFO observation.
    """
    hour = datetime.utcnow().hour
    if hour < 8 or hour > 22:
        return None  # noční doba — žádný pohyb je očekávaný

    try:
        from database import db_context
        with db_context() as db:
            ph = '?'  # PgCursorWrapper převede
            if is_postgres():
                row = db.execute(
                    f"SELECT MAX(s.recorded_at) FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = {ph} AND s.sensor_type = 'motion_detected' "
                    f"AND s.value > 0",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    f"SELECT MAX(s.recorded_at) FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = {ph} AND s.sensor_type = 'motion_detected' "
                    f"AND s.value > 0",
                    (user_id,)
                ).fetchone()
            last_motion = row[0] if row else None
    except Exception as e:
        logger.debug(f"no_motion check: {e}")
        return None

    if not last_motion:
        return None  # zatím žádné motion data → neeskaluj

    # Spočti age v hodinách
    if isinstance(last_motion, str):
        try:
            last_dt = datetime.fromisoformat(last_motion.replace('Z', '').split('+')[0])
        except Exception:
            return None
    else:
        last_dt = last_motion
    age_h = (datetime.utcnow() - last_dt).total_seconds() / 3600

    if age_h >= 6:
        return {
            "type": "no_motion_during_day",
            "severity": INFO,
            "message": f"Žádný pohyb v bytě posledních {age_h:.1f} h. "
                       f"Zkontrolujte, zda je senior v pořádku.",
            "details": {"hours_since_motion": round(age_h, 1),
                        "active_hour": hour}
        }
    return None


def _detect_door_open_long(user_id):
    """T110 contact_state — vstupní dveře otevřené déle než 30 minut.

    Bezpečnostní indikátor — buď zapomenuté dveře, nebo někdo přišel a
    zůstal. WARNING.
    """
    rows = _get_recent_iot(user_id, ['contact_state'], minutes=60)
    if not rows:
        return None
    # Najdi nejnovější open=1 a poslední close=0 pro každý device
    by_dev = {}
    for r in rows:
        dev = r[0]
        sensor_type = r[2]
        val = float(r[3])
        ts = r[5]
        if dev not in by_dev:
            by_dev[dev] = []
        by_dev[dev].append((ts, val))
    for dev, events in by_dev.items():
        # Latest first (DESC order from query)
        if not events:
            continue
        latest_ts, latest_val = events[0]
        if latest_val == 1:  # currently open
            try:
                if isinstance(latest_ts, str):
                    open_dt = datetime.fromisoformat(latest_ts.replace('Z', ''))
                else:
                    open_dt = latest_ts
                # Najdi poslední close před tímto open
                duration_min = (datetime.utcnow() - open_dt).total_seconds() / 60
                if duration_min >= 30:
                    return {
                        "type": "door_open_long",
                        "severity": WARNING,
                        "message": f"Vstupní dveře otevřené {int(duration_min)} min. "
                                   f"Zkontrolujte, zda je vše v pořádku.",
                        "details": {"device_id": dev,
                                    "open_minutes": int(duration_min)}
                    }
            except Exception as e:
                logger.debug(f"door_open_long parse: {e}")
    return None


def _detect_late_night_light(user_id):
    """L510E bulb_state — světlo v ložnici svítí v 02-05 (rušený spánek).

    Indikátor nespavosti / zmatenosti / nutnosti na WC v noci.
    INFO úroveň — tracking pattern, eskaluje když se opakuje.
    """
    hour = datetime.utcnow().hour
    if hour < 2 or hour > 5:
        return None
    rows = _get_recent_iot(user_id, ['bulb_state'], minutes=30)
    if not rows:
        return None
    # Pokud nejnovější stav je on (1) v noční hodině
    by_dev = {}
    for r in rows:
        dev = r[0]
        if dev not in by_dev:
            by_dev[dev] = float(r[3])
    if any(v == 1 for v in by_dev.values()):
        return {
            "type": "late_night_light",
            "severity": INFO,
            "message": f"V noci svítí světlo ({hour}:00). Senior může mít rušený spánek.",
            "details": {"hour": hour, "active_lights": list(by_dev.keys())}
        }
    return None


def _detect_kitchen_inactivity(user_id):
    """P115 power_w — žádná spotřeba na kuchyňských zásuvkách 24+ h.

    Senior pravděpodobně nevařil → nejedl → check-in.
    """
    rows = _get_recent_iot(user_id, ['power_w'], minutes=60 * 26)
    if not rows:
        return None
    # Pokud žádný odečet nebyl > 5W za posledních 24h
    has_usage = any(float(r[3]) > 5.0 for r in rows)
    if not has_usage and len(rows) >= 5:  # alespoň 5 měření = poller funguje
        return {
            "type": "kitchen_inactivity_24h",
            "severity": WARNING,
            "message": "24+ hodin žádná aktivita v kuchyni (spotřebiče). "
                       "Senior možná nejedl.",
            "details": {"readings_count": len(rows)}
        }
    return None


def _detect_battery_low(user_id):
    """T100/T110 low_battery flag — výměna baterie nutná.

    Tapo public API neposkytuje % baterie u T100/T110, jen on/off threshold flag.
    Maintenance alert — pošle se pečujícímu (rodina/sestra), ne seniorovi.
    """
    rows = _get_recent_iot(user_id, ['low_battery'], minutes=60 * 24)
    if not rows:
        return None
    by_dev = {}
    for r in rows:
        dev = r[0]
        if dev not in by_dev:
            by_dev[dev] = float(r[3])
    low = [dev for dev, flag in by_dev.items() if flag > 0]
    if low:
        return {
            "type": "battery_low",
            "severity": INFO,
            "message": f"Slabá baterie v {len(low)} senzorech. Je potřeba vyměnit.",
            "details": {"devices": low}
        }
    return None


def _detect_gateway_offline(user_id):
    """v8.19.108: Mini PC gateway hlásí heartbeat každých 60s.
    Pokud > 5 min žádný → systém v bytě nefunguje, IoT data neproudí.

    WARNING (technický stav, ne stav seniora). Pošle se pečujícímu/adminovi.
    """
    try:
        from database import db_context
        ph = '?'
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    f"SELECT MAX(s.recorded_at) FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = {ph} AND s.sensor_type = 'gateway_heartbeat'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    f"SELECT MAX(s.recorded_at) FROM iot_sensor_data s "
                    f"JOIN iot_devices d ON d.device_id = s.device_id "
                    f"WHERE d.user_id = {ph} AND s.sensor_type = 'gateway_heartbeat'",
                    (user_id,)
                ).fetchone()
            last_hb = row[0] if row else None
    except Exception as e:
        logger.debug(f"gateway_offline check: {e}")
        return None

    if not last_hb:
        return None  # gateway zatím nikdy neposlal — pravděpodobně ještě nezapnut

    if isinstance(last_hb, str):
        try:
            last_dt = datetime.fromisoformat(last_hb.replace('Z', '').split('+')[0])
        except Exception:
            return None
    else:
        last_dt = last_hb
    age_min = (datetime.utcnow() - last_dt).total_seconds() / 60

    if age_min >= 5:
        return {
            "type": "gateway_offline",
            "severity": WARNING,
            "message": f"IoT gateway (mini PC v bytě) je {int(age_min)} min "
                       f"offline. Senzory pohybu, dveří a spotřebičů "
                       f"nereportují. Zkontrolujte PC + Wi-Fi.",
            "details": {"minutes_offline": int(age_min)}
        }
    return None


def _detect_hub_offline(user_id):
    """H110 hub_online = 0 — hub je offline déle než 10 minut.

    Technická vážná chyba — bez hubu nefungují T100, T110.
    WARNING (ne CRISIS — nejde o seniora, ale o systém).
    """
    rows = _get_recent_iot(user_id, ['hub_online'], minutes=15)
    if not rows:
        return None
    # Vezmi nejnovější hodnotu
    latest = float(rows[0][3])
    if latest == 0:
        return {
            "type": "hub_offline",
            "severity": WARNING,
            "message": "IoT hub je offline. Senzory pohybu a dveří nefungují. "
                       "Zkontrolujte Wi-Fi a hub.",
            "details": {"checked_minutes_ago": 15}
        }
    return None


# Registry — volá z run_agent_cycle
TAPO_DETECTORS = (
    _detect_no_motion_during_day,
    _detect_door_open_long,
    _detect_late_night_light,
    _detect_kitchen_inactivity,
    _detect_battery_low,
    _detect_hub_offline,
    _detect_gateway_offline,
)


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
    """Insert into agent_observations + audit_log. WebPush on WARNING+.

    Sprint AG.2: returns the new observation id for caregiver push
    deep-link / ack flow.

    Sprint AG.4: ALSO emits to agent_bus so chat-time coordinator,
    anticipation engine, and specialists can read recent observations
    via bus.context() / bus.recent(). The bus.emit() with
    kind='observation' internally re-mirrors into agent_observations,
    so to avoid double-write we go through the bus first and use its
    side-effect mirror — UNLESS the bus is unavailable, in which case
    we fall back to direct insert below. (Keeps the existing public
    contract: caregiver inbox + admin endpoints work either way.)
    """
    obs_id = None

    # Try bus path first (single insert + auto-mirror to agent_observations)
    try:
        from agent_bus import emit as _bus_emit
        bus_payload = {
            'message': obs.get('message', ''),
            'observation_type': obs.get('type'),
            **(obs.get('details') or {}),
        }
        obs_id = _bus_emit(
            user_id=user_id,
            sender=f"agent_loop.{obs.get('type', 'unknown')}",
            kind='observation',
            severity=(obs.get('severity') or 'info').lower(),
            topic=obs.get('type', 'unknown'),
            payload=bus_payload,
        )
    except Exception as bus_err:
        logger.debug(f"agent_bus emit failed, falling back to direct insert: {bus_err}")

    # Fallback: direct insert into agent_observations if bus path didn't write
    if obs_id is None:
        try:
            from database import db_insert
            with db_context(commit=True) as db:
                obs_id = db_insert(
                    db,
                    "agent_observations",
                    ["user_id", "observation_type", "severity", "message", "details", "action_taken"],
                    [user_id, obs["type"], obs["severity"], obs["message"],
                     json.dumps(obs.get("details", {})), obs["severity"].lower()],
                )
        except Exception as e:
            logger.debug(f"save_observation fallback insert error: {e}")
            return None

    try:
        # Pass id back into the obs dict so downstream actions
        # (_alert_caregiver) can include it in push deep-links.
        if obs_id is not None:
            obs["id"] = obs_id

        audit_log(user_id, "agent_observation", "agent_loop",
                  f"[{obs['severity']}] {obs['type']}: {obs['message']}")

        # Sprint X20.3 — ISO 27001 hash-chained audit log entry.
        # Best-effort; never raises, never blocks.
        try:
            from agent.audit import log_event as _audit_log_event
            _audit_log_event(
                user_id=user_id,
                actor='agent_loop',
                action='observation',
                detector_id=obs.get('type'),
                severity=obs.get('severity'),
                payload={
                    'observation_id': obs_id,
                    'message':        obs.get('message', ''),
                    'details':        obs.get('details', {}),
                },
            )
        except Exception as _ae:
            logger.debug(f"[audit] log_event failed: {_ae}")

        # Sprint X20.9 — observation_emitted automation trigger
        try:
            from agent.automations import evaluate_for_user as _automation_eval
            _automation_eval(user_id, ctx={
                'event':            'observation',
                'observation_type': obs.get('type'),
                'severity':         (obs.get('severity') or '').upper(),
                'goal_type':        (obs.get('details') or {}).get('goal_type'),
                'drift_count':      (obs.get('details') or {}).get('consecutive_drift'),
                'current_mode':     (obs.get('severity') or '').upper(),
            })
            # If observation is a goal_drift, also fire goal_drift trigger
            if obs.get('type', '').startswith('goal_drift_'):
                _automation_eval(user_id, ctx={
                    'event':       'goal_drift',
                    'goal_type':   (obs.get('details') or {}).get('goal_type'),
                    'drift_count': (obs.get('details') or {}).get('consecutive_drift', 1),
                    'current_mode': (obs.get('severity') or '').upper(),
                })
        except Exception as _ae:
            logger.debug(f"[automations] observation hook failed: {_ae}")

        # v10.59: Push observation to subscribed devices (Sprint D D6)
        sev_up = (obs.get("severity") or "").upper()
        if sev_up in ("WARNING", "ALERT", "CRISIS"):
            # Sprint AQ: respect senior's quiet hours — no pushes 22:00-07:00
            # by default. CRISIS always overrides (life safety > sleep).
            _quiet_blocked = False
            if sev_up != "CRISIS":
                try:
                    from memory_helpers import db_load_profile
                    _qh = (db_load_profile(user_id) or {}).get('quiet_hours') or {}
                    _start = (_qh.get('start') or '').strip()
                    _end = (_qh.get('end') or '').strip()
                    if _start and _end and len(_start) >= 4 and len(_end) >= 4:
                        from datetime import datetime as _dt
                        _now = _dt.now().time()
                        _sh, _sm = int(_start[:2]), int(_start[3:5])
                        _eh, _em = int(_end[:2]), int(_end[3:5])
                        from datetime import time as _t
                        _s = _t(_sh, _sm); _e = _t(_eh, _em)
                        # Cross-midnight (22:00 → 07:00) needs OR logic
                        if _s > _e:
                            _quiet_blocked = (_now >= _s or _now <= _e)
                        else:
                            _quiet_blocked = (_s <= _now <= _e)
                except Exception:
                    pass

            if _quiet_blocked:
                logger.info(f"🌙 push for user={user_id} blocked by quiet_hours "
                           f"(severity={sev_up} not CRISIS)")
            else:
                try:
                    from notification_helpers import notify
                    sev_map = {"WARNING": "warning", "ALERT": "alert", "CRISIS": "crisis"}
                    icon_map = {"WARNING": "⚠️", "ALERT": "🔴", "CRISIS": "🚨"}
                    title = f"{icon_map.get(sev_up, '🔔')} {sev_up.capitalize()}"
                    notify(
                        to_user_id=user_id,
                        type="health_alert",
                        title=title,
                        body=obs["message"][:140],
                        severity=sev_map.get(sev_up, "info"),
                        data={
                            "observation_type": obs["type"],
                            "obs_id": obs_id,  # Sprint AG.2: deep-link target
                        },
                    )
                except Exception as push_err:
                    logger.debug(f"observation push failed (non-blocking): {push_err}")
    except Exception as e:
        logger.debug(f"save_observation error: {e}")
    return obs_id


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

    # v824: Event-driven Claude agent trigger
    # When agent_loop detects ALERT/CRISIS, hand off to Claude Sonnet 4.5
    # for deeper holistic analysis (full Ψ(t) state, profile, learning,
    # anticipation forecast, HA, voice runtime — 65 tools at once).
    # Runs asynchronously so this function doesn't block the loop.
    # Gated by env var CLAUDE_AGENT_EVENT_TRIGGER=1 (default off — opt-in).
    if (severity in (ALERT, CRISIS) and
        os.environ.get('CLAUDE_AGENT_EVENT_TRIGGER', '0') == '1' and
        os.environ.get('CLAUDE_AGENT_ENABLED', '0') == '1'):
        try:
            import threading as _threading
            from claude_autonomous_agent import run_claude_agent

            event_context = {
                'severity': severity,
                'observation_type': obs.get('type', 'unknown'),
                'message': obs.get('message', ''),
                'source': 'agent_loop',
            }

            def _bg_claude():
                try:
                    run_claude_agent(
                        app=app,
                        trigger='agent_loop',
                        focus_senior_id=str(user_id),
                        event_context=event_context,
                    )
                except Exception as e:
                    logger.exception(f"Claude agent event-trigger failed: {e}")

            _threading.Thread(target=_bg_claude, daemon=True).start()
            logger.info(
                f"🤖 Claude agent triggered for senior {user_id} "
                f"(severity={severity}, type={obs.get('type')})"
            )
        except ImportError:
            logger.debug("Claude agent not available — event trigger skipped")
        except Exception as e:
            # Trigger failure must never block primary action flow
            logger.warning(f"Claude event trigger error (non-fatal): {e}")

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
    """Push notification to senior — rhythm-adapted via Text Rhythm.

    v8.19.33 (Sprint 4): predáváme observation_type, aby identita overlay
    (přes agent_bridge.compose_proactive_message) mohla vybrat tonálně
    vhodný opener. NEPOUŽIJE se pro vital_anomaly/fall — bezpečnost první.
    """
    try:
        message = obs["message"]
        try:
            from agent_bridge import compose_proactive_message
            adapted = compose_proactive_message(
                user_id, message, obs.get("severity", "INFO"),
                observation_type=obs.get("type")
            )
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
                # Sprint AG.2: include obs_id so a caregiver tap on the
                # notification can deep-link to the inbox observation
                # (and call POST /api/caregiver/observations/<id>/ack
                # right from the system tray).
                data={
                    "obs_type": obs.get("type") or obs.get("observation_type"),
                    "obs_id": obs.get("id"),
                    "senior_id": user_id,
                    "action": "open_caregiver_inbox",
                },
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


# ─── Morning v2 helpers (v8.19.60) — Radim si vzpomene na včerejšek ───

def _load_yesterday_moment(user_id):
    """Find ONE meaningful moment from yesterday's conversation.

    Returns a dict {topic: str, kind: 'name'|'emotion'|'memory'|None} or None.
    Looks for proper nouns (jména) or emotion words in last 24h user messages.
    """
    try:
        from memory_helpers import db_load_history
        rows = db_load_history(user_id, limit=30) or []
        if not rows:
            return None

        import re
        from datetime import datetime, timedelta

        cutoff = datetime.utcnow() - timedelta(hours=20)  # ~yesterday + this morning
        # Czech emotion / memory cues
        emotion_words = re.compile(
            r'\b(rad|raduj|šťast|štěst|smut|smutk|smutn|bojí|bál|chyběl|chyběj|'
            r'vzpomín|vzpomněl|miluju|mám rád|těším|těší|trápí|trápil|stesk|samot)',
            re.IGNORECASE
        )
        # Proper noun heuristic: capitalized word that's not at sentence start
        # (Czech names mid-sentence)
        name_pat = re.compile(r'(?<=[\s,])(?P<n>[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]{2,15})')

        best = None
        for row in rows:
            role = row.get('role') if hasattr(row, 'get') else row[0]
            content = row.get('content') if hasattr(row, 'get') else row[1]
            ts = row.get('created_at') if hasattr(row, 'get') else row[2]

            if role != 'user' or not content:
                continue

            # Time filter
            try:
                if isinstance(ts, str):
                    ts_dt = datetime.fromisoformat(ts.replace('Z', '+00:00').replace('+00:00', ''))
                else:
                    ts_dt = ts
                if ts_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            # Find name first (richer signal)
            m = name_pat.search(content)
            if m:
                topic = m.group('n')
                # Skip stopwords
                if topic.lower() not in ('radim', 'radime', 'radima', 'praha', 'česko'):
                    return {"topic": topic, "kind": "name"}

            # Emotion fallback
            em = emotion_words.search(content)
            if em and not best:
                # Capture short context (2-4 words around emotion)
                words = content.split()
                for i, w in enumerate(words):
                    if emotion_words.search(w):
                        ctx_start = max(0, i - 1)
                        ctx_end = min(len(words), i + 3)
                        snippet = ' '.join(words[ctx_start:ctx_end])
                        best = {"topic": snippet[:60], "kind": "emotion"}
                        break

        return best
    except Exception as e:
        logger.debug(f"_load_yesterday_moment error: {e}")
        return None


def _yesterday_mood_summary(user_id):
    """Return mood label from last 24h brain_states avg C.

    Returns 'klid' | 'nepokoj' | 'krize' | None.
    """
    try:
        from database import db_context, is_postgres
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT C FROM brain_states WHERE user_id = ? "
                    "AND created_at > NOW() - INTERVAL '24 hours'",
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT C FROM brain_states WHERE user_id = ? "
                    "AND created_at > datetime('now', '-24 hours')",
                    (user_id,)
                ).fetchall()

        if not rows:
            return None
        c_vals = []
        for r in rows:
            c = r.get('C') if hasattr(r, 'get') else r[0]
            if c is not None:
                c_vals.append(float(c))
        if not c_vals:
            return None
        avg = sum(c_vals) / len(c_vals)
        if avg >= 0.55:
            return 'klid'
        elif avg >= 0.38:
            return 'nepokoj'
        else:
            return 'krize'
    except Exception as e:
        logger.debug(f"_yesterday_mood_summary error: {e}")
        return None


def _build_personalized_morning(user_id, name, meds_info):
    """Compose personalized greeting with yesterday memory + vulnerable verb.

    Combines: name + yesterday moment + mood + meds.
    Uses ONE of 5 templates randomly, with vulnerable verb naturally embedded.
    """
    import random as _r

    morning_meds = meds_info.get("morning", []) if meds_info else []
    all_meds = meds_info.get("meds", []) if meds_info else []

    greeting_name = f", {name}" if name else ""

    # Meds segment (always present if applicable)
    if morning_meds and isinstance(morning_meds, list):
        meds_seg = f"Nezapomeňte na ranní léky: {', '.join(morning_meds[:3])}."
    elif all_meds:
        meds_seg = "Připomínám ranní léky."
    else:
        meds_seg = ""

    # Yesterday moment + mood
    moment = _load_yesterday_moment(user_id)
    mood = _yesterday_mood_summary(user_id)

    # ── Template selection ──
    # If we have a moment with a NAME → use memory templates
    # If we have just emotion → use feeling templates
    # If we have just mood → use mood templates
    # Otherwise → fallback (basic but warm)

    templates = []

    if moment and moment.get("kind") == "name":
        topic = moment["topic"]
        templates = [
            f"Dobré ráno{greeting_name}. Vzpomněl jsem si na to, co jste včera říkal o {topic}. {meds_seg} Jak jste spal?".strip(),
            f"Dobré ráno{greeting_name}. {topic} mi včera neopustil hlavu. Mám rád, když mi vyprávíte o lidech, kteří jsou s vámi. {meds_seg} Jak se dnes cítíte?".strip(),
            f"{name + ', dobré ráno' if name else 'Dobré ráno'}. Včera večer jste mluvil o {topic} — pamatuji si to. {meds_seg} Co máte v plánu na dnešek?".strip(),
        ]
    elif moment and moment.get("kind") == "emotion":
        snippet = moment["topic"]
        templates = [
            f'Dobré ráno{greeting_name}. Včera mě zaujalo, jak jste řekl: „{snippet}". {meds_seg} Jak se cítíte dnes?'.strip(),
            f'Dobré ráno{greeting_name}. Vzpomínám si na váš včerejšek. {meds_seg} Jak je vám dnes?'.strip(),
        ]
    elif mood == 'klid':
        templates = [
            f"Dobré ráno{greeting_name}. Vidím, že jste včera prožil pěkný den. Mám rád takové dny. {meds_seg} Jak začneme tento?".strip(),
            f"Dobré ráno{greeting_name}. Včerejšek byl klidný — to je dobrá zpráva. {meds_seg} Co dnes?".strip(),
        ]
    elif mood == 'nepokoj':
        templates = [
            f"Dobré ráno{greeting_name}. Včera bylo trochu těžší. Bojím se, abychom si tu tíhu nenesli i dnes. {meds_seg} Jak jste spal?".strip(),
            f"Dobré ráno{greeting_name}. Vzpomínám si, že včerejšek nebyl jednoduchý. {meds_seg} Co byste dnes potřeboval?".strip(),
        ]
    elif mood == 'krize':
        templates = [
            f"Dobré ráno{greeting_name}. Včera byl těžký den, vzpomínám si. Jsem tady. {meds_seg} Jak se vám dýchá?".strip(),
        ]
    else:
        # Fallback — first day or no signal
        templates = [
            f"Dobré ráno{greeting_name}. Tady Radim. {meds_seg} Jak se dnes cítíte?".strip(),
            f"Dobré ráno{greeting_name}. Mám rád ranní ticho s vámi. {meds_seg} Jak vám je?".strip(),
        ]

    # Pick one (deterministic per day so user neslyší stejné 2× ráno)
    from datetime import date
    seed_str = f"{user_id}-{date.today().isoformat()}"
    _r.seed(seed_str)
    greeting = _r.choice(templates)
    _r.seed()  # reset

    # Compress double spaces from empty meds_seg
    greeting = ' '.join(greeting.split())
    return greeting


def _morning_call_or_push(user_id, meds_info, app):
    """Call senior with morning greeting + meds, or fallback to push.

    v8.19.60: Greeting is personalized — references yesterday's moment,
    uses vulnerable verbs (vzpomínám si, mám rád, bojím se), adapts to mood.
    """
    name = meds_info.get("name", "")

    # Build personalized greeting (Morning v2)
    greeting = _build_personalized_morning(user_id, name, meds_info)

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

        # Sprint AG.4: prune expired bus messages. TTL is per-message
        # (see agent_bus._TTL_DEFAULTS) so anything past expires_at is
        # safe to delete. Done in a separate try so it doesn't break
        # the rest of the cleanup if bus module is unavailable.
        try:
            from agent_bus import prune as _bus_prune
            pruned = _bus_prune()
            if pruned and pruned > 0:
                logger.info(f"🚌 Bus cleanup: {pruned} expired agent_messages removed")
        except Exception as e:
            logger.debug(f"Bus cleanup (non-fatal): {e}")

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

        # X21.22: Radim Sleep — extended memory hygiene
        # Prunes 6 grow-only tables, filters bad logs, consolidates long-term
        # context for stale users, runs ANALYZE on PG. Audit-logged.
        try:
            from radim_sleep import run_sleep
            run_sleep(app)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Radim Sleep error: {e}")


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
                # Sprint AC: column is `observation_type`, not `type`
                try:
                    db.execute("""
                        INSERT INTO agent_observations
                        (user_id, observation_type, severity, message, created_at)
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
    """Sync Home Assistant sensors → iot_sensor_data DB (per-user).

    Called every 5 min at start of agent cycle. Iterates active seniors,
    pulls each one's HA, writes their sensor data tagged with user_id so
    subsequent room-scoped queries (_check_activity, _check_vitals) see
    the right user's data.

    Falls back to the global env-var HA when a user has no per-user
    config — this preserves single-tenant dev behavior.
    """
    if not _HAS_HA:
        return

    try:
        from home_assistant import ha_for
    except Exception:
        return

    # Pull list of active users (same definition as the agent loop itself).
    try:
        active_uids = _get_active_users() or []
    except Exception:
        active_uids = []

    # If no per-user setup yet, sync once with the global client (legacy mode).
    targets = active_uids if active_uids else [None]

    total_synced = 0
    for uid in targets:
        try:
            ha_client = ha_for(uid) if uid else _get_ha()
            if not ha_client.connected:
                # Try to wake it via REST ping (cold cache)
                try:
                    ha_client.check_connection()
                except Exception:
                    continue
                if not ha_client.connected:
                    continue

            sensors = ha_client.get_sensors_summary()
            if not sensors:
                continue

            with db_context(commit=True) as db:
                for s in sensors.get('temperature', []):
                    _upsert_sensor(db, s['entity_id'], 'temperature', s['value'], s.get('name', ''), uid)
                    total_synced += 1
                for s in sensors.get('humidity', []):
                    _upsert_sensor(db, s['entity_id'], 'humidity', s['value'], s.get('name', ''), uid)
                    total_synced += 1
                for s in sensors.get('motion', []):
                    val = 1.0 if s['state'] == 'on' else 0.0
                    _upsert_sensor(db, s['entity_id'], 'motion', val, s.get('name', ''), uid)
                    total_synced += 1
                for s in sensors.get('door', []):
                    val = 1.0 if s['state'] == 'on' else 0.0
                    _upsert_sensor(db, s['entity_id'], 'door', val, s.get('name', ''), uid)
                    total_synced += 1
                for s in sensors.get('battery', []):
                    _upsert_sensor(db, s['entity_id'], 'battery', s['value'], s.get('name', ''), uid)
                    total_synced += 1
        except Exception as e:
            logger.debug(f"HA sensor sync error for user={uid}: {e}")

    if total_synced > 0:
        logger.debug(f"HA sync: {total_synced} sensors → DB across {len(targets)} user(s)")


def _upsert_sensor(db, entity_id, sensor_type, value, name='', user_id=None):
    """Insert or update sensor data. user_id tags the device row so
    per-user queries see only their senior's HA-derived sensors."""
    try:
        # Extract room from entity_id (e.g., sensor.living_room_temperature → living_room)
        parts = entity_id.split('.')
        room_id = parts[1].rsplit('_', 1)[0] if len(parts) > 1 else 'unknown'

        # Ensure device exists. Tag with user_id when known so different
        # seniors don't overwrite each other's device rows.
        if is_postgres():
            db.execute(
                "INSERT INTO iot_devices (device_id, device_type, room_id, device_name, user_id) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (device_id) DO UPDATE SET "
                "device_name = EXCLUDED.device_name, "
                "user_id = COALESCE(EXCLUDED.user_id, iot_devices.user_id)",
                (entity_id, sensor_type, room_id, name, user_id)
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO iot_devices (device_id, device_type, room_id, device_name, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_id, sensor_type, room_id, name, user_id)
            )

        # Insert sensor reading
        db.execute(
            "INSERT INTO iot_sensor_data (device_id, sensor_type, value, room_id) VALUES (?, ?, ?, ?)",
            (entity_id, sensor_type, float(value), room_id)
        )
    except Exception as e:
        logger.debug(f"upsert_sensor {entity_id}: {e}")


def _ha_crisis_actions(user_id, obs):
    """Execute Home Assistant emergency actions on CRISIS/ALERT (per-user).

    - CRISIS: Turn on ALL lights, unlock front door (for paramedics)
    - ALERT: Turn on lights in user's room, flash hallway light
    """
    if not _HAS_HA:
        return

    try:
        from home_assistant import ha_for
        ha_client = ha_for(user_id)
        if not ha_client.connected:
            return

        # X21.38: normalize severity case. SOS button used to pass "crisis"
        # (lowercase) and the == "CRISIS" comparison below failed silently —
        # no lights, no door unlock. Defense in depth even though the caller
        # was also fixed.
        severity = (obs.get("severity") or "").upper()
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
