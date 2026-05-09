"""
Goal-driven agent — measure functions for each goal type
=========================================================

Goals = "is the senior trending toward a desired state over a HORIZON?"
This is the proactive layer above detectors (which answer "is there a
problem RIGHT NOW?"). Each goal has a measure() function that returns
the current value over the goal's horizon, plus a `met` boolean.

Goal types (v1 — extend per persona later):
  daily_social_contact      ≥1 chat/call interaction/day
  sleep_quality             ≥6h continuous overnight motion-quiet
  environment_comfort       temp/humidity/CO2 in comfort bands ≥80% of time
  medication_compliance     prescribed doses logged on time

Each measure(user_id, target, horizon_hours) returns:
  {
    'value':         current measured value (numeric or %)
    'target':        echo of target spec
    'met':           bool — is the goal currently being met?
    'samples':       count of data points considered
    'horizon_hours': echo of horizon
    'detail':        type-specific extra info
  }

Sprint X20.1 / Fix 6 — goal-driven planner foundation
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _hours_ago_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _safe_count(rows) -> int:
    if rows is None:
        return 0
    if isinstance(rows, (list, tuple)):
        return len(rows)
    try:
        return int(rows)
    except (TypeError, ValueError):
        return 0


# ─── Goal: daily_social_contact ────────────────────────────────────────────


def measure_daily_social_contact(user_id: str, target: dict,
                                  horizon_hours: int = 24) -> dict:
    """Count distinct interaction days within the horizon. Target:
       {'min_per_day': 1}  → met when each day in horizon has ≥ N interactions."""
    min_per_day = int(target.get('min_per_day', 1))
    try:
        from database import db_context
    except ImportError:
        return _empty_measure(target, horizon_hours, reason='db_unavailable')

    cutoff = _hours_ago_iso(horizon_hours)
    try:
        with db_context() as db:
            # Chat-based interactions count toward this goal.
            cur = db.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE conversation_id IN ("
                "  SELECT id FROM chat_conversations WHERE participants LIKE ?"
                ") AND created_at > ?",
                (f'%{user_id}%', cutoff)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[goals] social measure failed: {e}")
        return _empty_measure(target, horizon_hours, reason=str(e))

    cnt = _safe_count(row[0] if row else 0)
    days = max(1, horizon_hours / 24)
    avg_per_day = cnt / days
    return {
        'value':         round(avg_per_day, 2),
        'target':        target,
        'met':           avg_per_day >= min_per_day,
        'samples':       cnt,
        'horizon_hours': horizon_hours,
        'detail': {
            'avg_per_day': round(avg_per_day, 2),
            'min_per_day': min_per_day,
            'window_h':    horizon_hours,
        },
    }


# ─── Goal: sleep_quality ────────────────────────────────────────────────────


def measure_sleep_quality(user_id: str, target: dict,
                           horizon_hours: int = 24) -> dict:
    """Sleep ≈ continuous motion-quiet hours overnight. Target:
       {'min_quiet_hours': 6, 'window': '22:00-08:00'}.

    Naive v1: count motion events in the night-window. Few events = sleep ok.
    Empty motion data → 'unknown' (met=None counted as met for now)."""
    min_quiet = int(target.get('min_quiet_hours', 6))
    motion_threshold = int(target.get('motion_events_max', 30))

    try:
        from database import db_context
    except ImportError:
        return _empty_measure(target, horizon_hours, reason='db_unavailable')

    # 24h horizon for daily sleep — find the most recent night window
    cutoff = _hours_ago_iso(horizon_hours)
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT COUNT(*) FROM iot_sensor_data "
                "WHERE sensor_type = 'motion' AND value > 0 "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "AND recorded_at > ?",
                (str(user_id), cutoff)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[goals] sleep measure failed: {e}")
        return _empty_measure(target, horizon_hours, reason=str(e))

    motion_events = _safe_count(row[0] if row else 0)
    # Crude proxy: fewer motion events overnight = better sleep
    met = motion_events <= motion_threshold

    return {
        'value':         motion_events,
        'target':        target,
        'met':           met,
        'samples':       motion_events,
        'horizon_hours': horizon_hours,
        'detail': {
            'motion_events':       motion_events,
            'motion_events_max':   motion_threshold,
            'min_quiet_hours':     min_quiet,
            'note':                'naive_motion_proxy',
        },
    }


# ─── Goal: environment_comfort ──────────────────────────────────────────────


def measure_environment_comfort(user_id: str, target: dict,
                                 horizon_hours: int = 24) -> dict:
    """Fraction of measurements where each tracked sensor is in comfort band.
    Target: {'temp': [19, 25], 'humidity': [40, 65], 'co2_max': 1000,
             'min_in_band_pct': 80}."""
    temp_band     = target.get('temp', [19, 25])
    hum_band      = target.get('humidity', [40, 65])
    co2_max       = target.get('co2_max', 1000)
    min_in_band   = target.get('min_in_band_pct', 80) / 100.0

    try:
        from database import db_context
    except ImportError:
        return _empty_measure(target, horizon_hours, reason='db_unavailable')

    cutoff = _hours_ago_iso(horizon_hours)
    in_band = 0
    total = 0
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT sensor_type, value FROM iot_sensor_data "
                "WHERE sensor_type IN ('temperature','humidity','co2') "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "AND recorded_at > ? "
                "ORDER BY recorded_at DESC LIMIT 500",
                (str(user_id), cutoff)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[goals] env measure failed: {e}")
        return _empty_measure(target, horizon_hours, reason=str(e))

    for r in rows:
        total += 1
        sensor = r[0] if isinstance(r, (list, tuple)) else r['sensor_type']
        try:
            v = float(r[1] if isinstance(r, (list, tuple)) else r['value'])
        except (TypeError, ValueError):
            continue
        if sensor == 'temperature' and temp_band[0] <= v <= temp_band[1]:
            in_band += 1
        elif sensor == 'humidity' and hum_band[0] <= v <= hum_band[1]:
            in_band += 1
        elif sensor == 'co2' and v <= co2_max:
            in_band += 1

    pct = (in_band / total) if total else 1.0  # no data = treat as met
    return {
        'value':         round(pct * 100, 1),
        'target':        target,
        'met':           pct >= min_in_band,
        'samples':       total,
        'horizon_hours': horizon_hours,
        'detail': {
            'in_band':            in_band,
            'total':              total,
            'in_band_pct':        round(pct * 100, 1),
            'min_in_band_pct':    round(min_in_band * 100, 1),
        },
    }


# ─── Goal: medication_compliance ────────────────────────────────────────────


def measure_medication_compliance(user_id: str, target: dict,
                                    horizon_hours: int = 168) -> dict:
    """Count logged medication doses vs. expected (per day × days in horizon).
    Target: {'doses_per_day_expected': 2, 'min_compliance_pct': 80}."""
    expected_per_day = int(target.get('doses_per_day_expected', 2))
    min_compliance = target.get('min_compliance_pct', 80) / 100.0
    days = max(1, horizon_hours / 24)

    try:
        from database import db_context
    except ImportError:
        return _empty_measure(target, horizon_hours, reason='db_unavailable')

    cutoff = _hours_ago_iso(horizon_hours)
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT COUNT(*) FROM radim_medication_log "
                "WHERE user_id = ? AND taken_at > ?",
                (str(user_id), cutoff)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[goals] med measure failed: {e}")
        return _empty_measure(target, horizon_hours, reason=str(e))

    taken = _safe_count(row[0] if row else 0)
    expected = expected_per_day * days
    pct = (taken / expected) if expected > 0 else 1.0
    return {
        'value':         round(min(pct * 100, 999), 1),
        'target':        target,
        'met':           pct >= min_compliance,
        'samples':       taken,
        'horizon_hours': horizon_hours,
        'detail': {
            'taken':           taken,
            'expected':        round(expected, 1),
            'compliance_pct':  round(min(pct * 100, 999), 1),
            'min_required':    round(min_compliance * 100, 0),
        },
    }


# ─── Registry ───────────────────────────────────────────────────────────────


GOAL_MEASURES: dict[str, Callable[[str, dict, int], dict]] = {
    'daily_social_contact':   measure_daily_social_contact,
    'sleep_quality':          measure_sleep_quality,
    'environment_comfort':    measure_environment_comfort,
    'medication_compliance':  measure_medication_compliance,
}


def list_goal_types() -> list[str]:
    return sorted(GOAL_MEASURES.keys())


def measure_goal(goal_type: str, user_id: str, target: dict,
                 horizon_hours: int) -> dict:
    """Dispatch to the right measure function. Unknown type → empty result."""
    fn = GOAL_MEASURES.get(goal_type)
    if not fn:
        return _empty_measure(target, horizon_hours, reason=f'unknown_goal_type:{goal_type}')
    try:
        return fn(user_id, target, horizon_hours)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[goals] measure({goal_type}) for {user_id} failed: {e}")
        return _empty_measure(target, horizon_hours, reason=str(e))


def _empty_measure(target: dict, horizon_hours: int, reason: str) -> dict:
    return {
        'value':         None,
        'target':        target,
        'met':           None,
        'samples':       0,
        'horizon_hours': horizon_hours,
        'detail':        {'error': reason},
    }


# ─── Persona-aware default goals ────────────────────────────────────────────


PERSONA_DEFAULT_GOALS = {
    'senior': [
        {
            'goal_type':     'daily_social_contact',
            'target':        {'min_per_day': 1},
            'horizon_hours': 24,
        },
        {
            'goal_type':     'sleep_quality',
            'target':        {'min_quiet_hours': 6, 'motion_events_max': 30},
            'horizon_hours': 24,
        },
        {
            'goal_type':     'environment_comfort',
            'target':        {'temp': [19, 25], 'humidity': [40, 65],
                              'co2_max': 1000, 'min_in_band_pct': 80},
            'horizon_hours': 24,
        },
        {
            'goal_type':     'medication_compliance',
            'target':        {'doses_per_day_expected': 2, 'min_compliance_pct': 80},
            'horizon_hours': 168,  # 7 days
        },
    ],
    'child_autism': [
        {
            # Higher in-band requirement for sensory-sensitive children
            'goal_type':     'environment_comfort',
            'target':        {'temp': [20, 24], 'humidity': [40, 60],
                              'co2_max': 900, 'min_in_band_pct': 90},
            'horizon_hours': 24,
        },
        {
            'goal_type':     'sleep_quality',
            'target':        {'min_quiet_hours': 8, 'motion_events_max': 25},
            'horizon_hours': 24,
        },
        {
            # Routine consistency — same as social but smaller min
            'goal_type':     'daily_social_contact',
            'target':        {'min_per_day': 2},  # caregiver + family
            'horizon_hours': 24,
        },
    ],
    'child_adhd': [
        {
            'goal_type':     'sleep_quality',
            'target':        {'min_quiet_hours': 7, 'motion_events_max': 35},
            'horizon_hours': 24,
        },
        {
            'goal_type':     'daily_social_contact',
            'target':        {'min_per_day': 3},  # engagement is therapeutic
            'horizon_hours': 24,
        },
    ],
}


def default_goals_for_persona(persona_id: str) -> list[dict]:
    """Return a defensive copy of default goals for a persona."""
    import copy
    return copy.deepcopy(PERSONA_DEFAULT_GOALS.get(persona_id, PERSONA_DEFAULT_GOALS['senior']))
