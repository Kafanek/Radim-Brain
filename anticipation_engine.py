"""
🔮 ANTICIPATION ENGINE v1.0
==============================
Predicts senior's behavior, detects routine changes, anticipates crises.

3 layers:
    1. BEHAVIORAL PATTERNS — learns personal routine from sensors
       (bathroom visits, bed restlessness, outdoor activity, meals)
    2. ANTICIPATION — predicts Ĉ_{t+1}, α̂_{t+1}, Ê_{t+1}
       (where consciousness/stress is heading BEFORE it gets there)
    3. ANOMALY DETECTION — flags deviations from personal baseline
       (bathroom at 3AM when usual is never, no bed exit by 10AM)

Sensor mapping:
    motion_bathroom  → bathroom visits (frequency, timing, duration)
    motion_bedroom   → sleep quality (restlessness, wake events)
    motion_hallway   → indoor movement patterns
    motion_kitchen   → meal preparation activity
    door_front       → outdoor activity (leaving/returning)
    bed_pressure     → in-bed status (lying, restless, empty)
    temperature_*    → room comfort

Math:
    Ĉ_{t+1} = C_t + k₁·T^C_t + k₂·(α_t - 0.5)
    T^C_t = (1-λ)·T^C_{t-1} + λ·ΔC_t
    B₁₂ = 1 if C_t < 12 and Ĉ_{t+1} ≥ 12 (approaching ALERT)
    B₂₇ = 1 if C_t < 27 and Ĉ_{t+1} ≥ 27 (approaching CRISIS)
"""

import json
import logging
import math
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

# Constants
PHI = 1.618034
T1 = 12   # HARMONY → ALERT threshold
T2 = 27   # ALERT → CRISIS threshold
LAMBDA_C = 0.3     # Trend smoothing for C
LAMBDA_ALPHA = 0.3  # Trend smoothing for α
K1 = 1.0   # Trend influence on prediction
K2 = 7.0   # Alpha influence on C prediction
K_EMP = 0.15  # Empathy adjustment rate
K_RATE = 0.02 # Speech rate adjustment
K_PAUSE = 50  # Pause adjustment (ms per unit)


# ═══════════════════════════════════════════════════════════════════
# 1. BEHAVIORAL PATTERN RECOGNITION
# ═══════════════════════════════════════════════════════════════════

# Sensor → activity mapping
ACTIVITY_SENSORS = {
    'bathroom': {
        'sensor_patterns': ['bathroom', 'wc', 'toilet', 'koupelna', 'zachod'],
        'label': 'Koupelna',
        'icon': '🚿',
        'normal_daily': (4, 8),     # 4-8 visits/day is normal for seniors
        'night_normal': (0, 2),     # 0-2 bathroom visits at night
        'concern_threshold': 12,    # >12/day might indicate UTI or other issues
    },
    'bed': {
        'sensor_patterns': ['bedroom', 'bed', 'postel', 'loznice', 'sleep'],
        'label': 'Postel',
        'icon': '🛏️',
        'night_restless_threshold': 15,  # >15 motion events at night = restless
    },
    'kitchen': {
        'sensor_patterns': ['kitchen', 'kuchyn', 'kuchyne'],
        'label': 'Kuchyně',
        'icon': '🍳',
        'meal_hours': [7, 12, 18],  # Expected meal times
        'no_activity_concern_hours': 5,  # No kitchen for 5h during day = skipped meal?
    },
    'outdoor': {
        'sensor_patterns': ['front_door', 'door', 'dvere', 'entrance', 'vchod'],
        'label': 'Venku',
        'icon': '🚶',
        'normal_outings': (0, 3),   # 0-3 outings per day
    },
    'hallway': {
        'sensor_patterns': ['hallway', 'chodba', 'corridor', 'predsini'],
        'label': 'Chodba',
        'icon': '🚪',
    },
    'living': {
        'sensor_patterns': ['living', 'obyvak', 'obyvaci'],
        'label': 'Obývák',
        'icon': '🛋️',
    },
}


def build_activity_timeline(user_id, hours=24):
    """Build timeline of activities from HA sensors.

    Returns per-hour activity counts by location:
    {
        'bathroom': {0: 0, 1: 1, 2: 0, ... 23: 0},
        'bedroom': {0: 5, 1: 2, ...},
        'kitchen': {7: 3, 12: 2, 18: 4, ...},
        'outdoor': {10: 1, 16: 1},  # door events
        'total_by_hour': {0: 5, 1: 3, ...},
        'timeline': [{'hour': 0, 'activities': {...}}, ...]
    }
    """
    if not _AVAILABLE:
        return {}

    result = {loc: {} for loc in ACTIVITY_SENSORS}
    result['total_by_hour'] = {}

    try:
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT EXTRACT(HOUR FROM s.recorded_at) as hr, s.room_id, "
                    "s.sensor_type, COUNT(*) as cnt "
                    "FROM iot_sensor_data s "
                    "WHERE s.recorded_at > NOW() - INTERVAL '%s hours' "
                    "AND s.value > 0 "
                    "GROUP BY hr, s.room_id, s.sensor_type ORDER BY hr" % hours
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT CAST(strftime('%%H', s.recorded_at) AS INTEGER) as hr, "
                    "s.room_id, s.sensor_type, COUNT(*) as cnt "
                    "FROM iot_sensor_data s "
                    "WHERE s.recorded_at > datetime('now', '-%d hours') "
                    "AND s.value > 0 "
                    "GROUP BY hr, s.room_id, s.sensor_type ORDER BY hr" % hours
                ).fetchall()

            for r in rows:
                hr = int(r[0])
                room = str(r[1] or '').lower()
                sensor = str(r[2] or '').lower()
                cnt = int(r[3])

                # Map room to activity location
                for loc_id, loc_info in ACTIVITY_SENSORS.items():
                    if any(p in room for p in loc_info['sensor_patterns']):
                        result[loc_id][hr] = result[loc_id].get(hr, 0) + cnt
                        break

                result['total_by_hour'][hr] = result['total_by_hour'].get(hr, 0) + cnt

    except Exception as e:
        logger.debug(f"Activity timeline error: {e}")

    return result


def compute_behavioral_profile(user_id, days=14):
    """Build complete behavioral profile from sensor data.

    Returns personal routine patterns per activity type.
    """
    if not _AVAILABLE:
        return {}

    profile = {}

    try:
        with db_context() as db:
            for loc_id, loc_info in ACTIVITY_SENSORS.items():
                patterns = loc_info['sensor_patterns']
                room_filter = ' OR '.join(f"s.room_id LIKE '%{p}%'" for p in patterns)

                if is_postgres():
                    rows = db.execute(
                        f"SELECT EXTRACT(HOUR FROM s.recorded_at) as hr, "
                        f"DATE(s.recorded_at) as day, COUNT(*) as cnt "
                        f"FROM iot_sensor_data s "
                        f"WHERE ({room_filter}) AND s.value > 0 "
                        f"AND s.recorded_at > NOW() - INTERVAL '{days} days' "
                        f"GROUP BY hr, day ORDER BY hr"
                    ).fetchall()
                else:
                    rows = db.execute(
                        f"SELECT CAST(strftime('%H', s.recorded_at) AS INTEGER) as hr, "
                        f"DATE(s.recorded_at) as day, COUNT(*) as cnt "
                        f"FROM iot_sensor_data s "
                        f"WHERE ({room_filter}) AND s.value > 0 "
                        f"AND s.recorded_at > datetime('now', '-{days} days') "
                        f"GROUP BY hr, day ORDER BY hr"
                    ).fetchall()

                if not rows:
                    profile[loc_id] = {'has_data': False}
                    continue

                # Compute per-hour averages
                hourly = {}
                daily_totals = {}
                for r in rows:
                    hr = int(r[0])
                    day = str(r[1])
                    cnt = int(r[2])
                    hourly.setdefault(hr, []).append(cnt)
                    daily_totals[day] = daily_totals.get(day, 0) + cnt

                avg_by_hour = {h: round(sum(v)/len(v), 1) for h, v in hourly.items()}
                peak_hours = sorted(avg_by_hour, key=avg_by_hour.get, reverse=True)[:3]
                daily_avg = round(sum(daily_totals.values()) / max(len(daily_totals), 1), 1)

                # Night activity (23:00-05:00)
                night_avg = sum(avg_by_hour.get(h, 0) for h in list(range(23, 24)) + list(range(0, 6)))

                profile[loc_id] = {
                    'has_data': True,
                    'daily_avg': daily_avg,
                    'night_avg': round(night_avg, 1),
                    'peak_hours': peak_hours,
                    'avg_by_hour': avg_by_hour,
                    'days_with_data': len(daily_totals),
                }

        # Save
        learning = db_load_learning(user_id)
        learning['behavioral_profile'] = {
            **profile,
            'computed_at': datetime.utcnow().isoformat(),
            'days': days,
        }
        db_save_learning(user_id, learning)

    except Exception as e:
        logger.debug(f"Behavioral profile error: {e}")

    return profile


# ═══════════════════════════════════════════════════════════════════
# 2. ANTICIPATION — predict Ĉ_{t+1}, detect breaking points
# ═══════════════════════════════════════════════════════════════════

def anticipate(user_id):
    """Compute anticipation: where is consciousness heading?

    Uses:
        Ĉ_{t+1} = C_t + k₁·T^C + k₂·(α_t - 0.5)
        T^C_t = (1-λ)·T^C_{t-1} + λ·ΔC_t

    Returns:
        {
            current: {C, alpha, mode},
            predicted: {C_hat, alpha_hat, mode_predicted},
            breaking_points: {B12: bool, B27: bool},
            speech_adaptation: {empathy_delta, rate_factor, pause_delta_ms},
            risk_direction: "stable" | "rising" | "approaching_alert" | "approaching_crisis"
        }
    """
    if not _AVAILABLE:
        return {'error': 'not available'}

    learning = db_load_learning(user_id)

    # Get C history
    c_history = [float(v) for v in learning.get('C_history', []) if v is not None]
    if len(c_history) < 3:
        return {
            'current': {'C': c_history[-1] if c_history else 5.0, 'alpha': 0.5, 'mode': 'HARMONY'},
            'predicted': {'C_hat': c_history[-1] if c_history else 5.0, 'alpha_hat': 0.5, 'mode_predicted': 'HARMONY'},
            'breaking_points': {'B12': False, 'B27': False},
            'speech_adaptation': {'empathy_delta': 0, 'rate_factor': 1.0, 'pause_delta_ms': 0},
            'risk_direction': 'insufficient_data',
        }

    # Current values
    C_t = c_history[-1]
    C_prev = c_history[-2]
    alpha_t = learning.get('alpha_history', [0.5])[-1] if learning.get('alpha_history') else 0.5

    # Compute trend (exponential moving average of deltas)
    trend_C = learning.get('trend_C', 0)
    delta_C = C_t - C_prev
    trend_C = (1 - LAMBDA_C) * trend_C + LAMBDA_C * delta_C

    # Save trend
    learning['trend_C'] = trend_C

    # ── Predict Ĉ_{t+1} ──
    C_hat = C_t + K1 * trend_C + K2 * (alpha_t - 0.5)
    C_hat = max(0, min(40, C_hat))  # Clamp

    # Predict α̂_{t+1}
    trend_alpha = learning.get('trend_alpha', 0)
    alpha_history = learning.get('alpha_history', [])
    if len(alpha_history) >= 2:
        delta_alpha = alpha_history[-1] - alpha_history[-2]
        trend_alpha = (1 - LAMBDA_ALPHA) * trend_alpha + LAMBDA_ALPHA * delta_alpha
    learning['trend_alpha'] = trend_alpha

    alpha_hat = alpha_t + 0.5 * trend_alpha
    alpha_hat = max(0, min(1, alpha_hat))

    # ── Predicted mode ──
    if C_hat >= T2:
        mode_predicted = 'CRISIS'
    elif C_hat >= T1:
        mode_predicted = 'ALERT'
    else:
        mode_predicted = 'HARMONY'

    # Current mode
    if C_t >= T2:
        mode_current = 'CRISIS'
    elif C_t >= T1:
        mode_current = 'ALERT'
    else:
        mode_current = 'HARMONY'

    # ── Breaking points B₁₂, B₂₇ ──
    B12 = C_t < T1 and C_hat >= T1
    B27 = C_t < T2 and C_hat >= T2

    # ── Risk direction ──
    if B27:
        risk_direction = 'approaching_crisis'
    elif B12:
        risk_direction = 'approaching_alert'
    elif trend_C > 0.5:
        risk_direction = 'rising'
    elif trend_C < -0.5:
        risk_direction = 'improving'
    else:
        risk_direction = 'stable'

    # ── Speech adaptation (control algorithm) ──
    C_target = 18  # Target: stay well below ALERT
    alpha_target = 0.4

    # Empathy boost when approaching threshold
    empathy_delta = K_EMP * max(0, C_hat - T1)

    # Speech rate reduction (slower when stressed)
    rate_factor = 1.0 - K_RATE * max(0, C_hat - C_target)
    rate_factor = max(0.7, min(1.0, rate_factor))

    # Pause extension
    pause_delta = int(K_PAUSE * max(0, C_hat - C_target))
    pause_delta = min(500, pause_delta)

    # ── Predicted emotion vector ──
    e_tension = 1 / (1 + math.exp(-(C_hat - 15) / 5))
    e_fear = 1 / (1 + math.exp(-(C_hat - 22) / 4))
    e_calm = 1 - e_tension
    e_hope = 1 / (1 + math.exp((alpha_hat - 0.6) * 5))

    # Save anticipation state
    learning['anticipation'] = {
        'C_hat': round(C_hat, 2),
        'alpha_hat': round(alpha_hat, 3),
        'trend_C': round(trend_C, 3),
        'trend_alpha': round(trend_alpha, 4),
        'B12': B12,
        'B27': B27,
        'risk_direction': risk_direction,
        'predicted_emotions': {
            'tension': round(e_tension, 3),
            'fear': round(e_fear, 3),
            'calm': round(e_calm, 3),
            'hope': round(e_hope, 3),
        },
        'at': datetime.utcnow().isoformat(),
    }
    db_save_learning(user_id, learning)

    return {
        'current': {
            'C': round(C_t, 2),
            'alpha': round(alpha_t, 3),
            'mode': mode_current,
        },
        'predicted': {
            'C_hat': round(C_hat, 2),
            'alpha_hat': round(alpha_hat, 3),
            'mode_predicted': mode_predicted,
        },
        'breaking_points': {
            'B12': B12,
            'B27': B27,
            'B12_description': 'Přechod k ALERT — zvýšit empatii' if B12 else None,
            'B27_description': 'Přechod ke CRISIS — aktivovat krizový protokol' if B27 else None,
        },
        'speech_adaptation': {
            'empathy_delta': round(empathy_delta, 3),
            'rate_factor': round(rate_factor, 3),
            'pause_delta_ms': pause_delta,
        },
        'predicted_emotions': {
            'tension': round(e_tension, 3),
            'fear': round(e_fear, 3),
            'calm': round(e_calm, 3),
            'hope': round(e_hope, 3),
        },
        'trend': {
            'C_trend': round(trend_C, 3),
            'alpha_trend': round(trend_alpha, 4),
        },
        'risk_direction': risk_direction,
    }


# ═══════════════════════════════════════════════════════════════════
# 3. ANOMALY DETECTION — deviations from personal normal
# ═══════════════════════════════════════════════════════════════════

def detect_anomalies(user_id):
    """Compare today's behavior to personal baseline.

    Detects:
        - Unusual bathroom frequency (UTI?)
        - Night bathroom increase
        - Bed restlessness increase
        - No kitchen activity (skipped meals?)
        - Unusual outdoor time (wandering?)
        - No movement at all (fall? emergency?)
        - Activity at unusual hours
    """
    if not _AVAILABLE:
        return {'anomalies': []}

    learning = db_load_learning(user_id)
    profile = learning.get('behavioral_profile', {})
    anomalies = []
    now = datetime.utcnow()
    hour = now.hour

    # Get today's timeline
    timeline = build_activity_timeline(user_id, hours=24)

    for loc_id, loc_info in ACTIVITY_SENSORS.items():
        baseline = profile.get(loc_id, {})
        if not baseline.get('has_data'):
            continue

        today_total = sum(timeline.get(loc_id, {}).values())
        baseline_avg = baseline.get('daily_avg', 0)
        night_today = sum(timeline.get(loc_id, {}).get(h, 0) for h in list(range(23, 24)) + list(range(0, 6)))
        night_avg = baseline.get('night_avg', 0)

        # ── Bathroom anomalies ──
        if loc_id == 'bathroom':
            concern = loc_info.get('concern_threshold', 12)
            if today_total > concern:
                anomalies.append({
                    'type': 'bathroom_high_frequency',
                    'location': 'bathroom',
                    'severity': 'warning',
                    'value': today_total,
                    'baseline': baseline_avg,
                    'message': f'Dnes {today_total} návštěv koupelny (obvykle {baseline_avg:.0f}). Možný zdravotní problém.',
                })
            if night_today > 3 and night_today > night_avg * 2:
                anomalies.append({
                    'type': 'bathroom_night_increase',
                    'location': 'bathroom',
                    'severity': 'watch',
                    'value': night_today,
                    'baseline': night_avg,
                    'message': f'{night_today} noční návštěvy koupelny (obvykle {night_avg:.0f}). Sledujeme.',
                })

        # ── Bed restlessness ──
        elif loc_id == 'bed':
            threshold = loc_info.get('night_restless_threshold', 15)
            if night_today > threshold and night_today > night_avg * 1.5:
                anomalies.append({
                    'type': 'bed_restless',
                    'location': 'bedroom',
                    'severity': 'watch',
                    'value': night_today,
                    'baseline': night_avg,
                    'message': f'Zvýšený noční neklid ({night_today} vs obvyklých {night_avg:.0f} pohybů).',
                })

        # ── Kitchen (meals) ──
        elif loc_id == 'kitchen':
            no_concern = loc_info.get('no_activity_concern_hours', 5)
            if 8 <= hour <= 20:
                # Check if kitchen was used in last N hours
                recent_kitchen = sum(timeline.get('kitchen', {}).get(h, 0) for h in range(max(0, hour - no_concern), hour + 1))
                if recent_kitchen == 0 and baseline_avg > 3:
                    anomalies.append({
                        'type': 'no_kitchen_activity',
                        'location': 'kitchen',
                        'severity': 'watch',
                        'value': 0,
                        'baseline': baseline_avg,
                        'message': f'Žádná aktivita v kuchyni za posledních {no_concern} hodin. Vynechal/a oběd?',
                    })

        # ── Outdoor ──
        elif loc_id == 'outdoor':
            normal_max = loc_info.get('normal_outings', (0, 3))[1]
            if today_total > normal_max * 2:
                anomalies.append({
                    'type': 'outdoor_excessive',
                    'location': 'door',
                    'severity': 'watch',
                    'value': today_total,
                    'baseline': baseline_avg,
                    'message': f'{today_total} odchodů z bytu (obvykle max {normal_max}). Neobvyklé.',
                })

    # ── Global: no movement at all ──
    total_today = sum(timeline.get('total_by_hour', {}).values())
    if total_today == 0 and hour >= 10 and profile.get('bathroom', {}).get('daily_avg', 0) > 0:
        anomalies.append({
            'type': 'no_movement',
            'location': 'all',
            'severity': 'urgent',
            'value': 0,
            'message': 'Žádný pohyb detekován od půlnoci. Zkontrolujte seniora!',
        })

    # ── Activity at unusual hour ──
    for loc_id in ['bathroom', 'kitchen']:
        loc_data = timeline.get(loc_id, {})
        baseline_hours = profile.get(loc_id, {}).get('avg_by_hour', {})
        for hr, cnt in loc_data.items():
            if cnt > 0 and baseline_hours.get(hr, 0) == 0 and cnt >= 3:
                anomalies.append({
                    'type': 'unusual_hour_activity',
                    'location': loc_id,
                    'severity': 'watch',
                    'hour': hr,
                    'value': cnt,
                    'message': f'Neobvyklá aktivita v {ACTIVITY_SENSORS[loc_id]["label"]} v {hr}:00 ({cnt}x, obvykle 0).',
                })

    # Save anomalies
    try:
        learning['today_anomalies'] = {
            'anomalies': anomalies,
            'detected_at': now.isoformat(),
            'total_today_motion': total_today,
        }
        db_save_learning(user_id, learning)
    except Exception:
        pass

    return {
        'anomalies': anomalies,
        'count': len(anomalies),
        'total_motion_today': total_today,
    }


# ═══════════════════════════════════════════════════════════════════
# AGENT LOOP INTEGRATION — called every 5 min
# ═══════════════════════════════════════════════════════════════════

def run_anticipation_cycle(user_id, observations, app=None):
    """Run full anticipation cycle for one user.

    Called from agent_loop._run_advanced_agents().
    Adds observations if breaking points or anomalies detected.
    """
    # 1. Anticipation (Ĉ prediction)
    try:
        antic = anticipate(user_id)

        if antic.get('breaking_points', {}).get('B27'):
            observations.append({
                'type': 'anticipation_crisis',
                'severity': 'CRISIS',
                'message': f"Anticipace: vědomí směřuje ke KRIZI (Ĉ={antic['predicted']['C_hat']}). Preventivní akce.",
                'details': antic,
            })
        elif antic.get('breaking_points', {}).get('B12'):
            observations.append({
                'type': 'anticipation_alert',
                'severity': 'WARNING',
                'message': f"Anticipace: stres roste směrem k ALERT (Ĉ={antic['predicted']['C_hat']}). Zvyšuji empatii.",
                'details': antic,
            })
    except Exception as e:
        logger.debug(f"Anticipation error for {user_id}: {e}")

    # 2. Behavioral anomalies
    try:
        anomaly_result = detect_anomalies(user_id)
        for anom in anomaly_result.get('anomalies', []):
            if anom['severity'] == 'urgent':
                observations.append({
                    'type': 'behavioral_anomaly',
                    'severity': 'ALERT',
                    'message': anom['message'],
                    'details': anom,
                })
            elif anom['severity'] == 'warning':
                observations.append({
                    'type': 'behavioral_anomaly',
                    'severity': 'WARNING',
                    'message': anom['message'],
                    'details': anom,
                })
    except Exception as e:
        logger.debug(f"Anomaly detection error for {user_id}: {e}")


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

anticipation_bp = Blueprint('anticipation_engine', __name__)


@anticipation_bp.route('/api/anticipate/<user_id>', methods=['GET'])
def api_anticipate(user_id):
    """Get anticipation: predicted C, breaking points, speech adaptation."""
    result = anticipate(user_id)
    return jsonify({'success': True, **result})


@anticipation_bp.route('/api/behavior/profile/<user_id>', methods=['GET'])
def api_behavioral_profile(user_id):
    """Get behavioral pattern profile."""
    days = int(request.args.get('days', 14))
    profile = compute_behavioral_profile(user_id, days)
    return jsonify({'success': True, 'profile': profile})


@anticipation_bp.route('/api/behavior/timeline/<user_id>', methods=['GET'])
def api_activity_timeline(user_id):
    """Get activity timeline (last 24h)."""
    hours = int(request.args.get('hours', 24))
    timeline = build_activity_timeline(user_id, hours)
    return jsonify({'success': True, 'timeline': timeline})


@anticipation_bp.route('/api/behavior/anomalies/<user_id>', methods=['GET'])
def api_anomalies(user_id):
    """Detect behavioral anomalies."""
    result = detect_anomalies(user_id)
    return jsonify({'success': True, **result})


logger.info("🔮 Anticipation Engine v1.0 loaded — behavior patterns, Ĉ prediction, anomaly detection")
