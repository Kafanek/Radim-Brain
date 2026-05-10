"""
Goal Evaluator (Planner)
=========================

Reads active goals for a user, measures current state, compares to target,
emits observations on drift. The proactive layer above detectors.

  agent_loop._evaluate_user(user_id)
       │
       ├─ detectors (reactive: "is there a problem RIGHT NOW?")
       │
       └─ planner.evaluate(user_id)
            │
            ├─ load active goals from agent_user_goals
            │
            ├─ for each goal:
            │     measure(goal_type, user_id, target, horizon)
            │     → record measurement in agent_goal_progress
            │     → if not met: emit observation type goal_drift_<type>
            │
            └─ collect observations for caller to dispatch

Observation severity:
  drift first time            → INFO     (just noting)
  drift 2 consecutive cycles  → WARNING  (pattern)
  drift 3+ consecutive cycles → ALERT    (sustained)
  social/medication drift     → ALERT direct (these are critical)

Sprint X20.1 / Fix 6
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Severity escalation curve (consecutive drift cycles → severity)
SEVERITY_CURVE = {
    1: 'INFO',
    2: 'WARNING',
    3: 'ALERT',
}


# ─── DB helpers ────────────────────────────────────────────────────────────


def list_active_goals(user_id: str) -> list[dict]:
    """Read agent_user_goals for this user."""
    try:
        from database import db_context
    except ImportError:
        return []
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT id, goal_type, target, horizon_hours, "
                "consecutive_drift_count "
                "FROM agent_user_goals "
                "WHERE user_id = ? AND active = ? "
                "ORDER BY id",
                (str(user_id), True)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[planner] list_active_goals({user_id}) failed: {e}")
        return []

    out = []
    for r in rows:
        try:
            target_raw = r[2] if isinstance(r, (list, tuple)) else r['target']
            target = json.loads(target_raw) if isinstance(target_raw, str) else (target_raw or {})
            out.append({
                'id':             r[0] if isinstance(r, (list, tuple)) else r['id'],
                'goal_type':      r[1] if isinstance(r, (list, tuple)) else r['goal_type'],
                'target':         target,
                'horizon_hours':  r[3] if isinstance(r, (list, tuple)) else r['horizon_hours'],
                'consecutive_drift_count':
                                  r[4] if isinstance(r, (list, tuple)) else r['consecutive_drift_count'],
            })
        except Exception:
            continue
    return out


def upsert_goal(user_id: str, goal_type: str, target: dict,
                horizon_hours: int = 24) -> int | None:
    """Insert or update a goal — one (user_id, goal_type) is unique."""
    try:
        from database import db_context, db_insert
    except ImportError:
        return None
    target_json = json.dumps(target or {}, ensure_ascii=False)
    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM agent_user_goals "
                "WHERE user_id = ? AND goal_type = ?",
                (str(user_id), goal_type)
            ).fetchone()
            if existing:
                gid = existing[0] if isinstance(existing, (list, tuple)) else existing['id']
                db.execute(
                    "UPDATE agent_user_goals SET target = ?, horizon_hours = ?, "
                    "active = ?, updated_at = ? WHERE id = ?",
                    (target_json, int(horizon_hours), True,
                     datetime.now(timezone.utc).isoformat(), gid)
                )
                return gid
            return db_insert(db, 'agent_user_goals',
                ['user_id', 'goal_type', 'target', 'horizon_hours',
                 'active', 'consecutive_drift_count'],
                (str(user_id), goal_type, target_json, int(horizon_hours),
                 True, 0))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[planner] upsert_goal failed: {e}")
        return None


def deactivate_goal(user_id: str, goal_id: int) -> bool:
    try:
        from database import db_context
    except ImportError:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE agent_user_goals SET active = ?, updated_at = ? "
                "WHERE user_id = ? AND id = ?",
                (False, datetime.now(timezone.utc).isoformat(),
                 str(user_id), int(goal_id))
            )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[planner] deactivate_goal failed: {e}")
        return False


def _record_measurement(goal_id: int, measurement: dict) -> None:
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO agent_goal_progress "
                "(goal_id, value, met, detail, measured_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    int(goal_id),
                    str(measurement.get('value')) if measurement.get('value') is not None else None,
                    measurement.get('met'),
                    json.dumps(measurement.get('detail', {}), ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[planner] record_measurement failed: {e}")


def _bump_drift_counter(goal_id: int, met: bool | None) -> int:
    """Increment consecutive_drift_count on miss; reset to 0 on hit.
    None (unknown) = don't change. Returns new count."""
    try:
        from database import db_context
    except ImportError:
        return 0
    if met is None:
        return 0
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "SELECT consecutive_drift_count FROM agent_user_goals WHERE id = ?",
                (int(goal_id),)
            )
            row = cur.fetchone()
            current = (row[0] if isinstance(row, (list, tuple))
                       else (row['consecutive_drift_count'] if row else 0)) or 0

            new_count = (current + 1) if not met else 0
            db.execute(
                "UPDATE agent_user_goals SET consecutive_drift_count = ?, "
                "updated_at = ? WHERE id = ?",
                (int(new_count), datetime.now(timezone.utc).isoformat(),
                 int(goal_id))
            )
            return new_count
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[planner] bump_drift failed: {e}")
        return 0


# ─── Severity & messaging ───────────────────────────────────────────────────


def _severity_from_curve(consecutive: int, goal_type: str) -> str:
    # Critical goal types skip the curve and go straight to ALERT
    if goal_type in ('medication_compliance',):
        return 'ALERT' if consecutive >= 1 else 'INFO'
    if consecutive >= 3:
        return SEVERITY_CURVE[3]
    if consecutive == 2:
        return SEVERITY_CURVE[2]
    if consecutive == 1:
        return SEVERITY_CURVE[1]
    return 'INFO'


def _message_for_drift(goal_type: str, measurement: dict, severity: str) -> str:
    val = measurement.get('value')
    detail = measurement.get('detail', {})
    if goal_type == 'daily_social_contact':
        return (f"Senior za posledních {measurement.get('horizon_hours')} hodin "
                f"měl jen {val} interakcí — doporučte hovor s rodinou nebo "
                f"krátký chat s Radimem.")
    if goal_type == 'sleep_quality':
        return (f"V noci bylo zaznamenáno {detail.get('motion_events', val)} "
                f"událostí pohybu — spánek mohl být přerušovaný. "
                f"Dotazte se na únavu.")
    if goal_type == 'environment_comfort':
        return (f"Komfort prostředí jen {val} % v doporučených pásmech "
                f"(cíl ≥ {detail.get('min_in_band_pct')} %). Vyvětrejte / upravte "
                f"teplotu nebo vlhkost.")
    if goal_type == 'medication_compliance':
        return (f"Compliance léků: {val} % (cíl ≥ {detail.get('min_required')} %). "
                f"Připomeňte vzít léky.")
    # Sprint X20.6 — caregiver-defined custom goal
    if goal_type == 'custom':
        label = detail.get('label') or 'Vlastní cíl'
        op = detail.get('op')
        threshold = detail.get('threshold')
        op_human = {'gte': '≥', 'lte': '≤', 'eq': '=', 'between': 'mezi'}.get(op, op)
        return (f"Vlastní cíl '{label}' není plněn: {detail.get('actual', val)} "
                f"{op_human} {threshold} (zdroj: {detail.get('source')}).")
    return f"Cíl {goal_type} není plněn (hodnota={val})."


# ─── Public API: evaluate goals for one user ────────────────────────────────


def evaluate(user_id: str) -> list[dict]:
    """Evaluate all active goals for `user_id`.

    Returns observations (same shape as detectors). Caller is responsible
    for cooldown checks + _save_observation dispatch.
    """
    from .goals import measure_goal

    goals = list_active_goals(user_id)
    if not goals:
        return []

    observations = []
    for g in goals:
        m = measure_goal(g['goal_type'], user_id, g['target'], g['horizon_hours'])
        _record_measurement(g['id'], m)
        new_drift = _bump_drift_counter(g['id'], m.get('met'))

        if m.get('met') is False:
            severity = _severity_from_curve(new_drift, g['goal_type'])
            obs_type = f"goal_drift_{g['goal_type']}"
            observations.append({
                'type':     obs_type,
                'severity': severity,
                'message':  _message_for_drift(g['goal_type'], m, severity),
                'details': {
                    'goal_id':           g['id'],
                    'goal_type':         g['goal_type'],
                    'measurement':       m,
                    'consecutive_drift': new_drift,
                    'source':            'planner',
                },
            })
        # met=True → drift counter reset to 0; nothing to emit
        # met=None → unknown (no data) — silent

    return observations


def get_goal_progress(user_id: str, limit: int = 50) -> list[dict]:
    """Last N progress measurements across all goals for inspection / UI."""
    try:
        from database import db_context
    except ImportError:
        return []
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT g.goal_type, p.value, p.met, p.detail, p.measured_at "
                "FROM agent_goal_progress p "
                "JOIN agent_user_goals g ON g.id = p.goal_id "
                "WHERE g.user_id = ? "
                "ORDER BY p.measured_at DESC LIMIT ?",
                (str(user_id), int(limit))
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[planner] get_goal_progress failed: {e}")
        return []

    out = []
    for r in rows:
        ts = r[4] if isinstance(r, (list, tuple)) else r['measured_at']
        try:
            detail_raw = r[3] if isinstance(r, (list, tuple)) else r['detail']
            detail = json.loads(detail_raw) if isinstance(detail_raw, str) else (detail_raw or {})
        except Exception:
            detail = {}
        out.append({
            'goal_type':   r[0] if isinstance(r, (list, tuple)) else r['goal_type'],
            'value':       r[1] if isinstance(r, (list, tuple)) else r['value'],
            'met':         r[2] if isinstance(r, (list, tuple)) else r['met'],
            'detail':      detail,
            'measured_at': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
        })
    return out


def initialize_default_goals(user_id: str, persona_id: str = 'senior') -> int:
    """Auto-create the default goal set for the given persona.
    Idempotent — uses upsert_goal (only inserts when no row exists for
    (user_id, goal_type) pair). Returns count created."""
    from .goals import default_goals_for_persona
    defaults = default_goals_for_persona(persona_id)
    created = 0
    for g in defaults:
        gid = upsert_goal(
            user_id=user_id,
            goal_type=g['goal_type'],
            target=g['target'],
            horizon_hours=g.get('horizon_hours', 24),
        )
        if gid:
            created += 1
    return created
