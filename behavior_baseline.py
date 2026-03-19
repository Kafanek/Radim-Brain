"""
Behavior Baseline v1.0
======================
Computes per-user behavioral baselines from brain_states and iot_sensor_data.
Baselines stored in memory_learning JSONB under "baselines" key.
Recomputed every 24h (or on first agent_loop run).
"""

import math
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    _DB = True
except ImportError:
    _DB = False

BASELINE_STALE_HOURS = 24


def _mean_std(values):
    """Compute mean and std dev for a list of numbers."""
    if not values:
        return 0.0, 0.0
    n = len(values)
    avg = sum(values) / n
    if n < 2:
        return avg, 0.0
    variance = sum((x - avg) ** 2 for x in values) / (n - 1)
    return avg, math.sqrt(variance)


def _time_window():
    """Return current 6h window name: morning/afternoon/evening/night."""
    h = datetime.now().hour
    if 6 <= h < 12:
        return "morning"
    elif 12 <= h < 18:
        return "afternoon"
    elif 18 <= h < 24:
        return "evening"
    return "night"


def needs_update(learning: dict) -> bool:
    """Check if baselines are stale or missing."""
    bl = learning.get("baselines")
    if not bl or not bl.get("updated_at"):
        return True
    try:
        updated = datetime.fromisoformat(bl["updated_at"])
        return (datetime.utcnow() - updated).total_seconds() > BASELINE_STALE_HOURS * 3600
    except (ValueError, TypeError):
        return True


def compute_c_baseline(user_id: str) -> dict:
    """Compute avg_C and std_C from brain_states (last 7 days)."""
    if not _DB:
        return {}
    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT \"C\" FROM brain_states WHERE user_id = ? AND created_at > NOW() - INTERVAL '7 days'",
                    (user_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT C FROM brain_states WHERE user_id = ? AND created_at > datetime('now', '-7 days')",
                    (user_id,)
                ).fetchall()

            values = []
            for r in rows:
                val = r.get('C') or r.get('c')
                if val is not None:
                    values.append(float(val))

            if len(values) < 3:
                # Fall back to memory_learning C_history
                from memory_helpers import db_load_learning
                learning = db_load_learning(user_id)
                values = [float(v) for v in learning.get("C_history", []) if v is not None]

            if not values:
                return {}

            avg, std = _mean_std(values)
            return {"avg_C": round(avg, 2), "std_C": round(std, 2), "sample_count": len(values)}
    except Exception as e:
        logger.debug(f"compute_c_baseline error: {e}")
        return {}


def compute_motion_baseline(user_id: str) -> dict:
    """Compute average motion count per 6h window from iot_sensor_data (last 7 days)."""
    if not _DB:
        return {}
    try:
        with db_context() as db:
            # Get room_ids for user
            rooms = db.execute(
                "SELECT DISTINCT room_id FROM iot_devices WHERE user_id = ?", (user_id,)
            ).fetchall()
            if not rooms:
                return {}

            room_ids = [r['room_id'] or r[0] for r in rooms]
            ph = ",".join(["?"] * len(room_ids))

            if is_postgres():
                rows = db.execute(
                    f"SELECT EXTRACT(HOUR FROM recorded_at)::int as h, DATE(recorded_at) as d "
                    f"FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = 'motion' "
                    f"AND recorded_at > NOW() - INTERVAL '7 days'",
                    tuple(room_ids)
                ).fetchall()
            else:
                rows = db.execute(
                    f"SELECT CAST(strftime('%H', recorded_at) AS INTEGER) as h, DATE(recorded_at) as d "
                    f"FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = 'motion' "
                    f"AND recorded_at > datetime('now', '-7 days')",
                    tuple(room_ids)
                ).fetchall()

            # Group by day + window
            windows = {"morning": [], "afternoon": [], "evening": [], "night": []}
            day_window_counts = {}  # (date, window) → count

            for r in rows:
                h = int(r.get('h') or r[0] or 0)
                d = str(r.get('d') or r[1] or '')
                if 6 <= h < 12:
                    w = "morning"
                elif 12 <= h < 18:
                    w = "afternoon"
                elif 18 <= h < 24:
                    w = "evening"
                else:
                    w = "night"
                key = (d, w)
                day_window_counts[key] = day_window_counts.get(key, 0) + 1

            for (d, w), cnt in day_window_counts.items():
                windows[w].append(cnt)

            result = {}
            for w, counts in windows.items():
                if counts:
                    avg, std = _mean_std(counts)
                    result[w] = {"avg": round(avg, 1), "std": round(std, 1)}
            return result
    except Exception as e:
        logger.debug(f"compute_motion_baseline error: {e}")
        return {}


def compute_vitals_baseline(user_id: str) -> dict:
    """Compute avg + std for heart_rate and spo2 (last 7 days)."""
    if not _DB:
        return {}
    try:
        with db_context() as db:
            rooms = db.execute(
                "SELECT DISTINCT room_id FROM iot_devices WHERE user_id = ?", (user_id,)
            ).fetchall()
            if not rooms:
                return {}

            room_ids = [r['room_id'] or r[0] for r in rooms]
            ph = ",".join(["?"] * len(room_ids))

            result = {}
            for sensor in ('heart_rate', 'spo2'):
                if is_postgres():
                    rows = db.execute(
                        f"SELECT value FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = ? "
                        f"AND recorded_at > NOW() - INTERVAL '7 days'",
                        tuple(room_ids) + (sensor,)
                    ).fetchall()
                else:
                    rows = db.execute(
                        f"SELECT value FROM iot_sensor_data WHERE room_id IN ({ph}) AND sensor_type = ? "
                        f"AND recorded_at > datetime('now', '-7 days')",
                        tuple(room_ids) + (sensor,)
                    ).fetchall()

                values = [float(r['value'] or r[0]) for r in rows if (r.get('value') or r[0]) is not None]
                if values:
                    avg, std = _mean_std(values)
                    result[sensor] = {"avg": round(avg, 1), "std": round(std, 1)}
            return result
    except Exception as e:
        logger.debug(f"compute_vitals_baseline error: {e}")
        return {}


def update_baselines(user_id: str) -> dict:
    """Compute all baselines and store in memory_learning JSONB."""
    from memory_helpers import db_load_learning, db_save_learning

    learning = db_load_learning(user_id)
    baselines = {
        "updated_at": datetime.utcnow().isoformat(),
        **compute_c_baseline(user_id),
        "motion_by_window": compute_motion_baseline(user_id),
        "vitals": compute_vitals_baseline(user_id),
    }
    learning["baselines"] = baselines
    db_save_learning(user_id, learning)
    return baselines


def get_baselines(user_id: str) -> dict:
    """Load baselines, recompute if stale."""
    from memory_helpers import db_load_learning
    learning = db_load_learning(user_id)
    if needs_update(learning):
        return update_baselines(user_id)
    return learning.get("baselines", {})
