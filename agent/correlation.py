"""
Per-user live correlation analysis
====================================

Computes Pearson correlation matrix across the 6 agent domains over a
rolling window (default 7 days). Surfaces caregiver insights like:

  "Emoční pohoda silně koreluje s pohybovou aktivitou (r=0.62)"
  "Sociální kontakt přechází zhoršení emocí (r=-0.45)"
  "CO2 a kognitivní výkonnost: žádný vztah (r=0.05)"

Approach:
  1. Bucket time into 1h bins over the last N days (default 168 bins for 7d)
  2. For each bin, derive a value for each of the 6 domains:
        emotional      avg brain_states.C in that hour
        environmental  avg(|temp − 22°|) + avg(|co2 − 800|) deviation
        social         chat message count
        physical       IoT motion events count + heart_rate avg deviation
        cognitive      msg_rate × distinct_conversations
        circadian      compute_circadian_c(persona, bucket_t)
  3. Compute Pearson r between each pair of domains.
  4. Extract caregiver-readable insights (|r| > 0.3 AND samples > 20).
  5. Cache result in agent_correlation_matrix (one row per user).

Privacy: per-user only. No cross-user comparison. No PII in cached rows
(just user_id + matrix). Matrix values reveal individual patterns — gate
caregiver access through the same self-or-admin auth as goals/audit.

Sprint X20.8
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Pearson primitive ─────────────────────────────────────────────────────


def pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Pure Python, no numpy.

    Returns None when:
      - sequences differ in length
      - fewer than 3 samples
      - either sequence has zero variance (constant)
    """
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 3:
        return None
    n = len(xs)
    sx = sum(xs);  sy = sum(ys)
    sxx = sum(x * x for x in xs); syy = sum(y * y for y in ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    nx_var = n * sxx - sx * sx
    ny_var = n * syy - sy * sy
    denom = nx_var * ny_var
    if denom <= 0:
        return None  # constant sequence(s) → undefined
    return (n * sxy - sx * sy) / math.sqrt(denom)


# ─── Hourly bucket loaders ─────────────────────────────────────────────────


def _hour_bucket(ts: datetime) -> datetime:
    """Round to the start of the hour, UTC-naive for matching."""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except ValueError:
            return datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts.replace(minute=0, second=0, microsecond=0)


def _load_emotional_buckets(user_id: str, since: datetime) -> dict:
    """Hourly avg of brain_states.C → emotional proxy."""
    try:
        from database import db_context
    except ImportError:
        return {}
    out: dict[datetime, list[float]] = {}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT C, created_at FROM brain_states "
                "WHERE user_id = ? AND created_at > ? "
                "ORDER BY created_at",
                (str(user_id), since.isoformat())
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] emot load failed: {e}")
        return {}
    for r in rows:
        c = r[0] if isinstance(r, (list, tuple)) else r['c']
        ts = r[1] if isinstance(r, (list, tuple)) else r['created_at']
        if c is None:
            continue
        b = _hour_bucket(ts)
        out.setdefault(b, []).append(float(c))
    return {b: sum(vs) / len(vs) for b, vs in out.items()}


def _load_environmental_buckets(user_id: str, since: datetime) -> dict:
    """Hourly env-stress proxy: |temp − 22°| + (co2 / 100). Lower = more comfort."""
    try:
        from database import db_context
    except ImportError:
        return {}
    out: dict[datetime, dict] = {}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT sensor_type, value, recorded_at FROM iot_sensor_data "
                "WHERE sensor_type IN ('temperature', 'co2') "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "AND recorded_at > ? "
                "ORDER BY recorded_at",
                (str(user_id), since.isoformat())
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] env load failed: {e}")
        return {}
    for r in rows:
        if isinstance(r, (list, tuple)):
            stype, val, ts = r[0], r[1], r[2]
        else:
            stype, val, ts = r['sensor_type'], r['value'], r['recorded_at']
        if val is None:
            continue
        b = _hour_bucket(ts)
        if b not in out:
            out[b] = {'temp': [], 'co2': []}
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if stype == 'temperature':
            out[b]['temp'].append(v)
        elif stype == 'co2':
            out[b]['co2'].append(v)

    result = {}
    for b, d in out.items():
        score = 0.0
        if d['temp']:
            score += abs(sum(d['temp']) / len(d['temp']) - 22.0)
        if d['co2']:
            score += max(0, sum(d['co2']) / len(d['co2']) - 800.0) / 100.0
        result[b] = score
    return result


def _load_social_buckets(user_id: str, since: datetime) -> dict:
    """Hourly chat message count → social signal."""
    try:
        from database import db_context
    except ImportError:
        return {}
    out: dict[datetime, int] = {}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT created_at FROM chat_messages "
                "WHERE conversation_id IN ("
                "  SELECT id FROM chat_conversations WHERE participants LIKE ?"
                ") AND created_at > ? "
                "ORDER BY created_at",
                (f'%{user_id}%', since.isoformat())
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] social load failed: {e}")
        return {}
    for r in rows:
        ts = r[0] if isinstance(r, (list, tuple)) else r['created_at']
        b = _hour_bucket(ts)
        out[b] = out.get(b, 0) + 1
    return {b: float(n) for b, n in out.items()}


def _load_physical_buckets(user_id: str, since: datetime) -> dict:
    """Hourly motion events count → physical activity proxy."""
    try:
        from database import db_context
    except ImportError:
        return {}
    out: dict[datetime, int] = {}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT recorded_at FROM iot_sensor_data "
                "WHERE sensor_type = 'motion' AND value > 0 "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "AND recorded_at > ? "
                "ORDER BY recorded_at",
                (str(user_id), since.isoformat())
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] physical load failed: {e}")
        return {}
    for r in rows:
        ts = r[0] if isinstance(r, (list, tuple)) else r['recorded_at']
        b = _hour_bucket(ts)
        out[b] = out.get(b, 0) + 1
    return {b: float(n) for b, n in out.items()}


def _load_cognitive_buckets(user_id: str, since: datetime) -> dict:
    """Hourly: msg_count × distinct_conversation_count → cognitive load proxy.
    More chats across more conversations in 1h = higher task switching."""
    try:
        from database import db_context
    except ImportError:
        return {}
    out: dict[datetime, dict] = {}
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT conversation_id, created_at FROM chat_messages "
                "WHERE conversation_id IN ("
                "  SELECT id FROM chat_conversations WHERE participants LIKE ?"
                ") AND created_at > ? "
                "ORDER BY created_at",
                (f'%{user_id}%', since.isoformat())
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] cognitive load failed: {e}")
        return {}
    for r in rows:
        cid = r[0] if isinstance(r, (list, tuple)) else r['conversation_id']
        ts  = r[1] if isinstance(r, (list, tuple)) else r['created_at']
        b = _hour_bucket(ts)
        if b not in out:
            out[b] = {'msgs': 0, 'convs': set()}
        out[b]['msgs'] += 1
        out[b]['convs'].add(cid)
    return {b: float(d['msgs']) * len(d['convs']) for b, d in out.items()}


def _load_circadian_buckets(persona_id: str, since: datetime,
                             until: datetime) -> dict:
    """Synthetic per-hour circadian C from persona curve. No DB read —
    deterministic from time."""
    try:
        from .circadian import compute_circadian_c
    except ImportError:
        return {}
    out: dict[datetime, float] = {}
    cur = _hour_bucket(since)
    end = _hour_bucket(until)
    while cur <= end:
        out[cur] = compute_circadian_c(persona_id, cur)
        cur = cur + timedelta(hours=1)
    return out


# ─── Compute matrix ────────────────────────────────────────────────────────


DOMAINS = ['emotional', 'environmental', 'social', 'physical', 'cognitive', 'circadian']


def compute_correlation_matrix(user_id: str,
                                 window_days: int = 7,
                                 persona_id: str = 'senior') -> dict:
    """Compute 6×6 Pearson matrix for one user over the last `window_days`.

    Returns:
      {
        'user_id':     uid,
        'persona_id':  persona_id,
        'window_days': window_days,
        'samples':     N (matched buckets across all dims),
        'matrix':      {a: {b: r_or_None, ...}, ...}
        'computed_at': ISO ts
      }
    """
    since = datetime.utcnow() - timedelta(days=window_days)
    until = datetime.utcnow()

    loaders = {
        'emotional':      _load_emotional_buckets(user_id, since),
        'environmental':  _load_environmental_buckets(user_id, since),
        'social':         _load_social_buckets(user_id, since),
        'physical':       _load_physical_buckets(user_id, since),
        'cognitive':      _load_cognitive_buckets(user_id, since),
        'circadian':      _load_circadian_buckets(persona_id, since, until),
    }

    # Find common buckets where at least 2 dims have data — but for a
    # consistent matrix we use only buckets where ALL dims are present.
    # That's strict; for sparse data we fall back to "where pair has data".
    all_buckets = set()
    for d in loaders.values():
        all_buckets |= set(d.keys())
    sorted_buckets = sorted(all_buckets)

    # Build aligned series: for each domain, list of values aligned with
    # sorted_buckets; missing → None
    series = {dom: [loaders[dom].get(b) for b in sorted_buckets] for dom in DOMAINS}

    matrix: dict[str, dict] = {}
    matched_samples_by_pair: dict[str, dict] = {}

    for a in DOMAINS:
        matrix[a] = {}
        matched_samples_by_pair[a] = {}
        for b in DOMAINS:
            if a == b:
                matrix[a][b] = 1.0
                matched_samples_by_pair[a][b] = sum(1 for v in series[a] if v is not None)
                continue
            xs, ys = [], []
            for va, vb in zip(series[a], series[b]):
                if va is not None and vb is not None:
                    xs.append(float(va))
                    ys.append(float(vb))
            r = pearson(xs, ys) if len(xs) >= 3 else None
            matrix[a][b] = round(r, 3) if r is not None else None
            matched_samples_by_pair[a][b] = len(xs)

    return {
        'user_id':     str(user_id),
        'persona_id':  persona_id,
        'window_days': window_days,
        'matrix':      matrix,
        'samples':     {a: matched_samples_by_pair[a] for a in DOMAINS},
        'computed_at': datetime.now(timezone.utc).isoformat(),
    }


# ─── Insight extraction ────────────────────────────────────────────────────


def _strength_label(r: float) -> str:
    a = abs(r)
    if a >= 0.7: return 'silná'
    if a >= 0.5: return 'střední'
    if a >= 0.3: return 'mírná'
    return 'slabá'


_DOMAIN_LABELS = {
    'emotional':     'emoční pohoda',
    'environmental': 'kvalita prostředí',
    'social':        'sociální kontakt',
    'physical':      'pohybová aktivita',
    'cognitive':     'kognitivní zátěž',
    'circadian':     'cirkadiální rytmus',
}


def extract_insights(matrix_result: dict,
                     threshold: float = 0.3,
                     min_samples: int = 20,
                     top_n: int = 5) -> list[dict]:
    """Turn matrix into ranked, caregiver-readable insights.

    Returns top-N insights sorted by |r|, filtered by:
      - |r| ≥ threshold (default 0.3 = at least mild)
      - matched samples ≥ min_samples (default 20)
      - upper triangle only (no duplicates)
    """
    if not matrix_result or 'matrix' not in matrix_result:
        return []
    m = matrix_result['matrix']
    samples = matrix_result.get('samples', {})

    insights = []
    seen_pairs = set()
    for a in DOMAINS:
        for b in DOMAINS:
            if a == b:
                continue
            pair = tuple(sorted([a, b]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            r = m.get(a, {}).get(b)
            n = samples.get(a, {}).get(b, 0)
            if r is None or n < min_samples or abs(r) < threshold:
                continue
            insights.append({
                'a':         a,
                'b':         b,
                'r':         r,
                'samples':   n,
                'strength':  _strength_label(r),
                'direction': 'positive' if r > 0 else 'negative',
                'label':     _make_insight_label(a, b, r),
            })
    insights.sort(key=lambda x: -abs(x['r']))
    return insights[:top_n]


def _make_insight_label(a: str, b: str, r: float) -> str:
    """Czech caregiver-readable description."""
    label_a = _DOMAIN_LABELS.get(a, a)
    label_b = _DOMAIN_LABELS.get(b, b)
    strength = _strength_label(r)
    if r > 0:
        return (f"{label_a.capitalize()} a {label_b} se {strength} pohybují společně "
                f"(r={r:+.2f}) — když roste jedno, roste i druhé.")
    else:
        return (f"{label_a.capitalize()} a {label_b} jsou v {strength} opačném vztahu "
                f"(r={r:+.2f}) — když jedno roste, druhé klesá.")


# ─── Persistence ───────────────────────────────────────────────────────────


def save_correlation_matrix(matrix_result: dict, insights: list[dict]) -> bool:
    """Cache result in agent_correlation_matrix (one row per user, upsert)."""
    try:
        from database import db_context, is_postgres
    except ImportError:
        return False
    user_id = matrix_result.get('user_id')
    if not user_id:
        return False
    try:
        with db_context(commit=True) as db:
            payload_matrix = json.dumps(matrix_result.get('matrix', {}),
                                          ensure_ascii=False)
            payload_insights = json.dumps(insights, ensure_ascii=False)
            payload_samples = json.dumps(matrix_result.get('samples', {}),
                                          ensure_ascii=False)
            if is_postgres():
                db.execute(
                    "INSERT INTO agent_correlation_matrix "
                    "(user_id, persona_id, window_days, matrix, samples, "
                    " insights, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "persona_id = EXCLUDED.persona_id, "
                    "window_days = EXCLUDED.window_days, "
                    "matrix = EXCLUDED.matrix, samples = EXCLUDED.samples, "
                    "insights = EXCLUDED.insights, updated_at = NOW()",
                    (user_id, matrix_result.get('persona_id', 'senior'),
                     matrix_result.get('window_days', 7),
                     payload_matrix, payload_samples, payload_insights)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO agent_correlation_matrix "
                    "(user_id, persona_id, window_days, matrix, samples, "
                    " insights, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, matrix_result.get('persona_id', 'senior'),
                     matrix_result.get('window_days', 7),
                     payload_matrix, payload_samples, payload_insights,
                     datetime.now(timezone.utc).isoformat())
                )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[corr] save failed for {user_id}: {e}")
        return False


def get_correlation_matrix(user_id: str) -> Optional[dict]:
    """Read cached result. None if never computed."""
    try:
        from database import db_context
    except ImportError:
        return None
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT persona_id, window_days, matrix, samples, insights, updated_at "
                "FROM agent_correlation_matrix WHERE user_id = ?",
                (str(user_id),)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[corr] get failed: {e}")
        return None
    if not row:
        return None
    if isinstance(row, (list, tuple)):
        persona, window, matrix, samples, insights, ts = row[0], row[1], row[2], row[3], row[4], row[5]
    else:
        persona = row['persona_id']; window = row['window_days']
        matrix = row['matrix']; samples = row['samples']; insights = row['insights']
        ts = row['updated_at']
    if isinstance(matrix, str):
        try: matrix = json.loads(matrix)
        except Exception: matrix = {}
    if isinstance(samples, str):
        try: samples = json.loads(samples)
        except Exception: samples = {}
    if isinstance(insights, str):
        try: insights = json.loads(insights)
        except Exception: insights = []
    return {
        'user_id':     str(user_id),
        'persona_id':  persona,
        'window_days': window,
        'matrix':      matrix,
        'samples':     samples,
        'insights':    insights,
        'computed_at': ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
    }


def recompute_for_user(user_id: str, persona_id: str = 'senior',
                        window_days: int = 7) -> dict:
    """End-to-end: compute matrix → extract insights → save → return."""
    result = compute_correlation_matrix(user_id, window_days=window_days,
                                          persona_id=persona_id)
    insights = extract_insights(result)
    save_correlation_matrix(result, insights)
    result['insights'] = insights
    return result
