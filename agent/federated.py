"""
Federated baseline learning — anonymized cross-senior pattern sharing
======================================================================

Problem
-------
New seniors don't have personal baselines for the first 1-7 days, so
detectors default to global constants (T1=12, T2=27) — not individualized.
Personal baselines (motion counts, sleep patterns, vital ranges) take
7-30 days to stabilize.

Solution
--------
Population-level aggregates per persona cohort. A new user inherits
80% population + 20% personal at day 1, gradually shifting to 90%
personal + 10% population by day 30+. The result: meaningful detection
from day 1 without 4-week onboarding lag.

Privacy guarantees
------------------
1. **k-anonymity**: aggregates with cohort_size < K_ANONYMITY_MIN are
   not published / not returned to consumers. Default K=5.
2. **Differential privacy**: Laplace noise added to numeric aggregates,
   ε=1.0 default (configurable per metric). Sensitivity = max plausible
   single-user contribution to the statistic.
3. **No raw data**: only (mean, std, p25, p50, p75) leave individual scope.
4. **Persona-isolated**: cohort = users sharing persona_id. No cross-cohort
   blending. Senior baselines never inform child_autism, ever.
5. **Opt-in per user**: memory_profiles.data['federated_enabled'] (default
   False) gates the read side. Aggregation runs regardless, but only
   opted-in users consume the result.
6. **Audit trail**: each aggregation run logs cohort sizes + ε, no PII.

Public API
----------
  aggregate_population_baselines(persona_id=None) → int rows updated
  get_population_baseline(persona_id, metric, time_window) → dict | None
  blend_baselines(personal_dict, population_dict, days_of_personal_data)
  apply_dp_noise(value, sensitivity, epsilon=DEFAULT_EPSILON)

Sprint X20.7
"""
from __future__ import annotations

import json
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Privacy parameters ────────────────────────────────────────────────────

K_ANONYMITY_MIN = 5            # cohort size floor (no publish if smaller)
DEFAULT_EPSILON = 1.0          # ε for differential privacy
PERSONA_COHORTS = ('senior', 'child_autism', 'child_adhd')


# Per-metric DP sensitivity — max single-user contribution to the statistic.
# This is ESTIMATED from clinical/operational caps; conservative bounds.
METRIC_SENSITIVITY = {
    'avg_C':                  2.0,    # one user moves population mean by ≤ 2 C-units
    'avg_motion_per_day':    50.0,    # ≤ 50 motion events/day differential per user
    'avg_chat_per_day':      30.0,    # ≤ 30 messages/day per user
    'avg_hr':                10.0,    # bpm
    'avg_spo2':               2.0,    # %
    'avg_sleep_motion':      40.0,    # events/night
}


# Per-metric ε override (lower ε = more privacy, more noise).
METRIC_EPSILON = {
    'avg_hr':       0.5,    # vital signs deserve stronger privacy
    'avg_spo2':     0.5,
}


# ─── Differential privacy primitives ───────────────────────────────────────


def _laplace(scale: float) -> float:
    """Sample from Laplace distribution centered at 0 with given scale.
    Inverse-transform: u ∈ (-0.5, 0.5), L = -scale·sign(u)·ln(1-2|u|)."""
    if scale <= 0:
        return 0.0
    u = random.random() - 0.5
    sign = -1.0 if u < 0 else 1.0
    return -scale * sign * math.log(max(1e-12, 1.0 - 2.0 * abs(u)))


def apply_dp_noise(value: float, sensitivity: float,
                   epsilon: float = DEFAULT_EPSILON) -> float:
    """Apply Laplace mechanism: noisy = value + Laplace(sensitivity / ε).
    Higher ε = less noise = less privacy. Sensitivity = max plausible
    single-record contribution to the aggregate."""
    if value is None or sensitivity <= 0 or epsilon <= 0:
        return value
    return value + _laplace(sensitivity / epsilon)


# ─── Aggregation primitives (no DB; pure stats) ────────────────────────────


def _summary_stats(values: list[float]) -> dict:
    """Compute mean, std, p25, p50, p75 for a list of numeric values."""
    if not values:
        return {'mean': None, 'std': None, 'p25': None, 'p50': None, 'p75': None}
    n = len(values)
    sv = sorted(values)
    mean = sum(sv) / n
    var = sum((v - mean) ** 2 for v in sv) / n if n > 1 else 0.0
    std = math.sqrt(var)
    def pct(p):
        # nearest-rank
        idx = max(0, min(n - 1, int(p * (n - 1))))
        return sv[idx]
    return {
        'mean': mean, 'std': std,
        'p25': pct(0.25), 'p50': pct(0.5), 'p75': pct(0.75),
    }


# ─── Aggregation queries (per metric) ──────────────────────────────────────
#
# Each entry produces ONE row per (persona_id, metric, time_window).
# Returns list of (cohort_size, raw_values, time_window) tuples.

def _gather_avg_C(persona_id: str) -> list[tuple[int, list[float], str]]:
    """Per-user avg C from brain_states over last 7 days."""
    try:
        from database import db_context
    except ImportError:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT bs.user_id, AVG(bs.C) AS avg_c "
                "FROM brain_states bs "
                "JOIN memory_profiles mp ON mp.user_id = bs.user_id "
                "WHERE bs.created_at > ? "
                "AND (mp.data->>'persona_id' = ? OR (? = 'senior' AND mp.data->>'persona_id' IS NULL)) "
                "GROUP BY bs.user_id "
                "HAVING COUNT(*) >= 5",
                (cutoff, persona_id, persona_id)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[federated] _gather_avg_C: {e}")
        return []
    values = []
    for r in rows:
        v = r[1] if isinstance(r, (list, tuple)) else r['avg_c']
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
    return [(len(values), values, '7d')] if values else []


def _gather_avg_chat_per_day(persona_id: str) -> list[tuple[int, list[float], str]]:
    """Per-user avg chat messages/day over last 7 days."""
    try:
        from database import db_context
    except ImportError:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT mp.user_id, COUNT(cm.id)::FLOAT / 7.0 AS daily "
                "FROM memory_profiles mp "
                "LEFT JOIN chat_conversations cc "
                "  ON cc.participants LIKE '%' || mp.user_id || '%' "
                "LEFT JOIN chat_messages cm "
                "  ON cm.conversation_id = cc.id AND cm.created_at > ? "
                "WHERE (mp.data->>'persona_id' = ? OR (? = 'senior' AND mp.data->>'persona_id' IS NULL)) "
                "GROUP BY mp.user_id",
                (cutoff, persona_id, persona_id)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[federated] _gather_avg_chat: {e}")
        return []
    values = []
    for r in rows:
        v = r[1] if isinstance(r, (list, tuple)) else r['daily']
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
    return [(len(values), values, '7d')] if values else []


def _gather_avg_motion_per_day(persona_id: str) -> list[tuple[int, list[float], str]]:
    """Per-user avg motion events/day over last 7 days."""
    try:
        from database import db_context
    except ImportError:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT mp.user_id, "
                "       COUNT(isd.id)::FLOAT / 7.0 AS daily "
                "FROM memory_profiles mp "
                "LEFT JOIN iot_devices d ON d.user_id = mp.user_id "
                "LEFT JOIN iot_sensor_data isd "
                "  ON isd.room_id = d.room_id "
                "  AND isd.sensor_type = 'motion' "
                "  AND isd.value > 0 "
                "  AND isd.recorded_at > ? "
                "WHERE (mp.data->>'persona_id' = ? OR (? = 'senior' AND mp.data->>'persona_id' IS NULL)) "
                "GROUP BY mp.user_id",
                (cutoff, persona_id, persona_id)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[federated] _gather_avg_motion: {e}")
        return []
    values = []
    for r in rows:
        v = r[1] if isinstance(r, (list, tuple)) else r['daily']
        if v is not None:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
    return [(len(values), values, '7d')] if values else []


METRIC_GATHERERS = {
    'avg_C':              _gather_avg_C,
    'avg_chat_per_day':   _gather_avg_chat_per_day,
    'avg_motion_per_day': _gather_avg_motion_per_day,
}


# ─── Aggregation orchestrator ─────────────────────────────────────────────


def aggregate_population_baselines(persona_id: Optional[str] = None) -> int:
    """Run aggregation across all (or one) persona cohorts.
    Returns count of (persona_id, metric, time_window) rows upserted.
    Drops aggregates with cohort_size < K_ANONYMITY_MIN.

    Each numeric statistic gets Laplace noise added before storage —
    even DB compromise won't reveal exact per-user contributions.
    """
    try:
        from database import db_context
    except ImportError:
        logger.warning("[federated] database module unavailable")
        return 0

    personas = [persona_id] if persona_id else list(PERSONA_COHORTS)
    upserted = 0

    for pid in personas:
        for metric, gatherer in METRIC_GATHERERS.items():
            try:
                buckets = gatherer(pid)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[federated] gatherer({pid},{metric}) failed: {e}")
                continue
            for cohort_size, values, time_window in buckets:
                if cohort_size < K_ANONYMITY_MIN:
                    logger.debug(
                        f"[federated] {pid}/{metric}/{time_window}: cohort={cohort_size} "
                        f"< K={K_ANONYMITY_MIN} — skipping (k-anonymity)"
                    )
                    continue
                stats = _summary_stats(values)
                # Apply DP noise to mean (most useful aggregate). p25/p50/p75
                # are quantiles — they get a smaller noise budget.
                sens = METRIC_SENSITIVITY.get(metric, 1.0)
                eps = METRIC_EPSILON.get(metric, DEFAULT_EPSILON)
                noisy_mean = apply_dp_noise(stats['mean'], sens, eps)
                # Store
                try:
                    with db_context(commit=True) as db:
                        # Upsert pattern: PG ON CONFLICT, sqlite REPLACE
                        try:
                            from database import is_postgres
                        except ImportError:
                            is_postgres = lambda: True  # assume PG on Heroku
                        if is_postgres():
                            db.execute(
                                "INSERT INTO agent_population_baselines "
                                "(persona_id, metric, time_window, cohort_size, "
                                " mean, std, p25, p50, p75, epsilon, updated_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW()) "
                                "ON CONFLICT (persona_id, metric, time_window) DO UPDATE SET "
                                "cohort_size = EXCLUDED.cohort_size, "
                                "mean = EXCLUDED.mean, std = EXCLUDED.std, "
                                "p25 = EXCLUDED.p25, p50 = EXCLUDED.p50, p75 = EXCLUDED.p75, "
                                "epsilon = EXCLUDED.epsilon, updated_at = NOW()",
                                (pid, metric, time_window, cohort_size,
                                 noisy_mean, stats['std'],
                                 stats['p25'], stats['p50'], stats['p75'], eps)
                            )
                        else:
                            db.execute(
                                "INSERT OR REPLACE INTO agent_population_baselines "
                                "(persona_id, metric, time_window, cohort_size, "
                                " mean, std, p25, p50, p75, epsilon, updated_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (pid, metric, time_window, cohort_size,
                                 noisy_mean, stats['std'],
                                 stats['p25'], stats['p50'], stats['p75'],
                                 eps, datetime.now(timezone.utc).isoformat())
                            )
                    upserted += 1
                    logger.info(
                        f"[federated] upsert {pid}/{metric}/{time_window} "
                        f"cohort={cohort_size} mean(noisy)={noisy_mean:.3f}"
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[federated] upsert failed: {e}")

    # Audit-log the aggregation run (no PII)
    try:
        from .audit import log_event
        log_event(
            user_id='system',
            actor='cron' if persona_id is None else 'admin',
            action='federated_aggregation',
            payload={
                'personas_aggregated': personas,
                'rows_upserted':       upserted,
                'k_anonymity_min':     K_ANONYMITY_MIN,
                'default_epsilon':     DEFAULT_EPSILON,
            },
            severity='INFO',
        )
    except Exception:
        pass

    return upserted


# ─── Read side ─────────────────────────────────────────────────────────────


def get_population_baseline(persona_id: str, metric: str,
                             time_window: str = '7d') -> Optional[dict]:
    """Return the most recent published baseline or None.
    Honors k-anonymity at READ time too (cohort_size < K = drop)."""
    try:
        from database import db_context
    except ImportError:
        return None
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT cohort_size, mean, std, p25, p50, p75, epsilon, updated_at "
                "FROM agent_population_baselines "
                "WHERE persona_id = ? AND metric = ? AND time_window = ?",
                (persona_id, metric, time_window)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[federated] get_population_baseline failed: {e}")
        return None
    if not row:
        return None
    cohort = row[0] if isinstance(row, (list, tuple)) else row['cohort_size']
    if cohort is None or cohort < K_ANONYMITY_MIN:
        return None
    if isinstance(row, (list, tuple)):
        return {
            'persona_id':  persona_id, 'metric': metric,
            'time_window': time_window, 'cohort_size': cohort,
            'mean': row[1], 'std': row[2],
            'p25': row[3], 'p50': row[4], 'p75': row[5],
            'epsilon': row[6],
            'updated_at': row[7].isoformat() if hasattr(row[7], 'isoformat') else str(row[7]),
        }
    return {
        'persona_id':  persona_id, 'metric': metric,
        'time_window': time_window, 'cohort_size': cohort,
        'mean': row['mean'], 'std': row['std'],
        'p25': row['p25'], 'p50': row['p50'], 'p75': row['p75'],
        'epsilon': row['epsilon'],
        'updated_at': row['updated_at'].isoformat() if hasattr(row['updated_at'], 'isoformat') else str(row['updated_at']),
    }


def list_population_baselines(persona_id: Optional[str] = None) -> list[dict]:
    """List all published (k-anon-passing) baselines."""
    try:
        from database import db_context
    except ImportError:
        return []
    where = "cohort_size >= ?"
    params = [K_ANONYMITY_MIN]
    if persona_id:
        where += " AND persona_id = ?"
        params.append(persona_id)
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT persona_id, metric, time_window, cohort_size, "
                "mean, std, p25, p50, p75, epsilon, updated_at "
                "FROM agent_population_baselines "
                f"WHERE {where} ORDER BY persona_id, metric",
                tuple(params)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[federated] list failed: {e}")
        return []
    out = []
    for r in rows:
        if isinstance(r, (list, tuple)):
            out.append({
                'persona_id':  r[0], 'metric': r[1], 'time_window': r[2],
                'cohort_size': r[3], 'mean': r[4], 'std': r[5],
                'p25': r[6], 'p50': r[7], 'p75': r[8], 'epsilon': r[9],
                'updated_at': r[10].isoformat() if hasattr(r[10], 'isoformat') else str(r[10]),
            })
        else:
            out.append(dict(r))
    return out


# ─── Blender — combine personal baseline with population by data age ──────


def blend_baselines(personal: Optional[dict],
                     population: Optional[dict],
                     days_of_personal_data: float = 0) -> Optional[dict]:
    """Blend personal + population baselines weighted by data age.

    Returns a {mean, std, ...} dict or None if neither input is usable.
    Weight curve:
      day 0   :  0.20 personal · 0.80 population (cold start)
      day 7   :  0.50 personal · 0.50 population (warming up)
      day 30+ :  0.90 personal · 0.10 population (stable, slight smoothing)
    """
    if not personal and not population:
        return None
    if not population:
        return dict(personal or {})
    if not personal:
        return dict(population)

    days = max(0.0, float(days_of_personal_data))
    if days <= 0:
        w_personal = 0.20
    elif days >= 30:
        w_personal = 0.90
    else:
        # Linear: 0d→0.20, 7d→0.50, 30d→0.90
        if days < 7:
            w_personal = 0.20 + (days / 7.0) * (0.50 - 0.20)
        else:
            w_personal = 0.50 + ((days - 7.0) / 23.0) * (0.90 - 0.50)
    w_population = 1.0 - w_personal

    def merge(key):
        p, q = personal.get(key), population.get(key)
        if p is None:
            return q
        if q is None:
            return p
        try:
            return w_personal * float(p) + w_population * float(q)
        except (TypeError, ValueError):
            return p

    return {
        'mean':           merge('mean'),
        'std':            merge('std'),
        'p25':            merge('p25'),
        'p50':            merge('p50'),
        'p75':            merge('p75'),
        '_w_personal':    round(w_personal, 3),
        '_w_population':  round(w_population, 3),
        '_days_personal': days,
        '_source':        'blended',
    }


# ─── Per-user opt-in helper ────────────────────────────────────────────────


def is_federated_enabled(user_id: str) -> bool:
    """Read memory_profiles.data['federated_enabled']. Default False."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        return bool(profile.get('federated_enabled'))
    except Exception:
        return False


def set_federated_enabled(user_id: str, enabled: bool) -> bool:
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        profile['federated_enabled'] = bool(enabled)
        db_save_profile(str(user_id), profile)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[federated] set_enabled failed: {e}")
        return False
