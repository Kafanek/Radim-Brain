"""
🔮 PREDICTIVE AGENT v1.0
=========================
Predicts senior crises 24h ahead using trend analysis.
No ML needed — uses statistical signals + φ-weighted scoring.

Signals:
    1. C trend direction (rising = danger)
    2. Activity pattern deviation
    3. Sleep quality degradation
    4. Interaction frequency change
    5. Medication compliance
    6. Environmental factors (temperature, humidity)
    7. Social isolation score

Output: risk_score 0-100, risk_level (low/medium/high/critical)
"""

import json
import logging
import math
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

PHI = 1.618034  # Golden ratio — used for weight decay

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    from behavior_baseline import get_baselines, _mean_std
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# SIGNAL EXTRACTORS — each returns 0.0-1.0 (0=normal, 1=danger)
# ═══════════════════════════════════════════════════════════════════

def _signal_c_trend(user_id, baselines):
    """Rising stress trend signal."""
    learning = db_load_learning(user_id)
    c_history = [float(v) for v in learning.get("C_history", []) if v is not None]
    if len(c_history) < 5:
        return 0.0

    recent = c_history[-5:]
    baseline_avg = baselines.get("avg_C", 5.0)
    baseline_std = max(baselines.get("std_C", 3.0), 1.0)

    # Trend direction: linear regression slope
    n = len(recent)
    x_mean = (n - 1) / 2.0
    slope = sum((i - x_mean) * (v - sum(recent) / n) for i, v in enumerate(recent))
    slope /= max(sum((i - x_mean) ** 2 for i in range(n)), 0.01)

    # Current level relative to baseline
    current_avg = sum(recent) / n
    deviation = (current_avg - baseline_avg) / baseline_std

    # Combine: rising slope + high level = danger
    trend_signal = min(1.0, max(0.0, slope / 3.0))  # slope >3 = max
    level_signal = min(1.0, max(0.0, deviation / 3.0))  # 3σ = max

    return min(1.0, (trend_signal * 0.6 + level_signal * 0.4))


def _signal_activity_drop(user_id, baselines):
    """Activity drop signal from IoT motion data or HA."""
    motion_bl = baselines.get("motion_by_window", {})

    # Try DB first
    current = None
    try:
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM iot_sensor_data "
                    "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                    "AND sensor_type = 'motion' AND recorded_at > NOW() - INTERVAL '12 hours'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM iot_sensor_data "
                    "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                    "AND sensor_type = 'motion' AND recorded_at > datetime('now', '-12 hours')",
                    (user_id,)
                ).fetchone()
            current = row['cnt'] or row[0] or 0
    except Exception:
        pass

    # Fallback: HA sensors
    if current is None or current == 0:
        try:
            from home_assistant import ha as _get_ha
            client = _get_ha()
            if client.connected:
                sensors = client.get_sensors_summary()
                active_motion = sum(1 for m in sensors.get('motion', []) if m.get('state') == 'on')
                current = active_motion
        except Exception:
            pass

    if current is None:
        return 0.0

    if not motion_bl:
        # No baseline — use simple heuristic
        return 0.0 if current > 0 else 0.3

    # Average across all windows
    all_avgs = [v.get("avg", 0) for v in motion_bl.values() if v.get("avg", 0) > 0]
    if not all_avgs:
        return 0.0
    expected = sum(all_avgs) / len(all_avgs) * 2  # 12h = 2 windows

    if expected < 2:
        return 0.0

    ratio = current / expected
    if ratio >= 0.8:
        return 0.0
    elif ratio >= 0.5:
        return 0.3
    elif ratio >= 0.2:
        return 0.6
    else:
        return 0.9


def _signal_interaction_silence(user_id, baselines):
    """Interaction silence signal."""
    try:
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT MAX(created_at) as last_ts FROM memory_history WHERE user_id = ? AND role = 'user'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT MAX(created_at) as last_ts FROM memory_history WHERE user_id = ? AND role = 'user'",
                    (user_id,)
                ).fetchone()

            if not row or not row[0]:
                return 0.5  # Unknown → moderate concern

            last_ts = row['last_ts'] if isinstance(row, dict) else row[0]
            if isinstance(last_ts, str):
                last_ts = datetime.fromisoformat(last_ts.replace('Z', '+00:00').replace('+00:00', ''))

            hours_silent = (datetime.utcnow() - last_ts).total_seconds() / 3600

            if hours_silent < 8:
                return 0.0
            elif hours_silent < 16:
                return 0.2
            elif hours_silent < 24:
                return 0.5
            elif hours_silent < 48:
                return 0.8
            else:
                return 1.0
    except Exception:
        return 0.0


def _signal_sleep_quality(user_id, baselines):
    """Sleep quality signal from overnight motion patterns.

    Good sleep = minimal motion between 23:00-06:00
    Bad sleep = frequent motion events (restlessness, insomnia)
    """
    try:
        with db_context() as db:
            if is_postgres():
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM iot_sensor_data "
                    "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                    "AND sensor_type = 'motion' AND value > 0 "
                    "AND EXTRACT(HOUR FROM recorded_at) BETWEEN 23 AND 6 "
                    "AND recorded_at > NOW() - INTERVAL '24 hours'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM iot_sensor_data "
                    "WHERE device_id IN (SELECT device_id FROM iot_devices WHERE user_id = ?) "
                    "AND sensor_type = 'motion' AND value > 0 "
                    "AND (CAST(strftime('%H', recorded_at) AS INTEGER) >= 23 "
                    "  OR CAST(strftime('%H', recorded_at) AS INTEGER) <= 6) "
                    "AND recorded_at > datetime('now', '-24 hours')",
                    (user_id,)
                ).fetchone()

            nighttime_motion = row['cnt'] or row[0] or 0

            # Normal: 0-5 events (bathroom visits)
            # Concerning: 6-15 (restless)
            # Bad: 15+ (insomnia / distress)
            if nighttime_motion <= 5:
                return 0.0
            elif nighttime_motion <= 10:
                return 0.2
            elif nighttime_motion <= 15:
                return 0.5
            elif nighttime_motion <= 25:
                return 0.7
            else:
                return 0.9
    except Exception:
        return 0.0


def _signal_medication_compliance(user_id, baselines):
    """Medication compliance from profile + morning checkin response."""
    learning = db_load_learning(user_id)
    med_history = learning.get("medication_responses", [])

    if not med_history or len(med_history) < 3:
        return 0.0  # Insufficient data

    # Check last 7 days compliance
    recent = med_history[-7:]
    missed = sum(1 for r in recent if not r.get("confirmed", False))
    total = len(recent)

    if total == 0:
        return 0.0

    miss_rate = missed / total
    if miss_rate <= 0.1:
        return 0.0
    elif miss_rate <= 0.3:
        return 0.3
    elif miss_rate <= 0.5:
        return 0.6
    else:
        return 0.9


def _signal_social_isolation(user_id, baselines):
    """Social isolation score from interaction patterns."""
    try:
        with db_context() as db:
            # Count interactions in last 7 days
            if is_postgres():
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM memory_history "
                    "WHERE user_id = ? AND role = 'user' AND created_at > NOW() - INTERVAL '7 days'",
                    (user_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT COUNT(*) as cnt FROM memory_history "
                    "WHERE user_id = ? AND role = 'user' AND created_at > datetime('now', '-7 days')",
                    (user_id,)
                ).fetchone()

            weekly_interactions = row['cnt'] or row[0] or 0

            # Normal for seniors: 5-20 interactions/week
            if weekly_interactions >= 15:
                return 0.0
            elif weekly_interactions >= 10:
                return 0.1
            elif weekly_interactions >= 5:
                return 0.3
            elif weekly_interactions >= 2:
                return 0.6
            elif weekly_interactions >= 1:
                return 0.8
            else:
                return 1.0
    except Exception:
        return 0.0


def _signal_survey_risk(user_id, baselines):
    """Survey-based risk signal from survey_engine."""
    try:
        from survey_engine import compute_survey_risk
        risk = compute_survey_risk(user_id)
        return risk.get('score', 0) / 100.0  # normalize to 0-1
    except Exception:
        return 0.0


def _signal_environment(user_id):
    """Environmental risk from HA sensors."""
    try:
        from home_assistant import ha
        client = ha()
        if not client.connected:
            return 0.0

        sensors = client.get_sensors_summary()
        risk = 0.0

        # Temperature extremes
        for t in sensors.get('temperature', []):
            if t['value'] < 16 or t['value'] > 30:
                risk = max(risk, 0.5)
            if t['value'] < 12 or t['value'] > 35:
                risk = max(risk, 0.8)

        # Low battery → sensor failure risk
        low_bat = [s for s in sensors.get('battery', []) if s['value'] < 15]
        if low_bat:
            risk = max(risk, 0.3)

        return risk
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════
# PREDICTION ENGINE — φ-weighted composite score
# ═══════════════════════════════════════════════════════════════════

# Weights (φ-proportioned: most critical gets highest weight)
SIGNAL_WEIGHTS = {
    'c_trend':       PHI ** 3,    # 4.236 — brain state most critical
    'activity':      PHI ** 2,    # 2.618
    'silence':       PHI ** 2,    # 2.618
    'sleep':         PHI,         # 1.618
    'medication':    PHI,         # 1.618
    'survey':        PHI,         # 1.618 — survey risk signal (NEW)
    'social':        1.0,         # 1.000
    'environment':   1.0,         # 1.000
}

# Normalize weights to sum to 1
_WEIGHT_SUM = sum(SIGNAL_WEIGHTS.values())
NORMALIZED_WEIGHTS = {k: v / _WEIGHT_SUM for k, v in SIGNAL_WEIGHTS.items()}


def predict_risk(user_id):
    """Predict 24h crisis risk for a senior.

    Returns:
        {
            "risk_score": 0-100,
            "risk_level": "low" / "medium" / "high" / "critical",
            "signals": { name: {value, weight, contribution} },
            "prediction": "Slovní popis rizika",
            "recommended_actions": ["..."],
            "timestamp": "ISO"
        }
    """
    if not _AVAILABLE:
        return {"risk_score": 0, "risk_level": "unknown", "error": "Dependencies unavailable"}

    baselines = get_baselines(user_id)

    # Collect all signals
    signals = {
        'c_trend': _signal_c_trend(user_id, baselines),
        'activity': _signal_activity_drop(user_id, baselines),
        'silence': _signal_interaction_silence(user_id, baselines),
        'sleep': _signal_sleep_quality(user_id, baselines),
        'medication': _signal_medication_compliance(user_id, baselines),
        'social': _signal_social_isolation(user_id, baselines),
        'survey': _signal_survey_risk(user_id, baselines),
        'environment': _signal_environment(user_id),
    }

    # Compute weighted score
    score = 0.0
    signal_details = {}
    for name, value in signals.items():
        weight = NORMALIZED_WEIGHTS[name]
        contribution = value * weight * 100
        score += contribution
        signal_details[name] = {
            'value': round(value, 3),
            'weight': round(weight, 3),
            'contribution': round(contribution, 1)
        }

    score = min(100, round(score))

    # Risk level
    if score < 20:
        level = "low"
        prediction = "Nízké riziko. Senior se zdá být v pořádku."
    elif score < 45:
        level = "medium"
        prediction = "Střední riziko. Doporučujeme častější kontrolu."
    elif score < 70:
        level = "high"
        prediction = "Vysoké riziko! Senior vykazuje několik varovných signálů."
    else:
        level = "critical"
        prediction = "Kritické riziko! Okamžitá pozornost je nutná."

    # Recommended actions based on top signals
    actions = _recommend_actions(signals, level)

    result = {
        "risk_score": score,
        "risk_level": level,
        "signals": signal_details,
        "prediction": prediction,
        "recommended_actions": actions,
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
    }

    # Save to learning memory
    _save_prediction(user_id, result)

    return result


def _recommend_actions(signals, level):
    """Generate recommended actions based on dominant signals."""
    actions = []

    if signals['c_trend'] > 0.5:
        actions.append("🧠 Zahájit uklidňující rozhovor, nabídnout relaxační cvičení")
    if signals['activity'] > 0.5:
        actions.append("🚶 Zkontrolovat pohyb seniora, zavolat mu")
    if signals['silence'] > 0.5:
        actions.append("📞 Proaktivně zavolat seniorovi")
    if signals['sleep'] > 0.5:
        actions.append("😴 Dotázat se na kvalitu spánku, nabídnout meditaci před spaním")
    if signals['medication'] > 0.5:
        actions.append("💊 Připomenout léky, zkontrolovat dodržování")
    if signals['social'] > 0.5:
        actions.append("👥 Navrhnout sociální aktivitu, zavolat rodinu")
    if signals['environment'] > 0.3:
        actions.append("🌡️ Zkontrolovat domácí prostředí (teplota, baterie senzorů)")

    if level == "critical":
        actions.insert(0, "🚨 OKAMŽITĚ kontaktovat pečovatele a rodinu")
    elif level == "high":
        actions.insert(0, "⚠️ Zvýšit frekvenci monitoringu na každých 15 min")

    if not actions:
        actions.append("✅ Pokračovat v běžném monitoringu")

    return actions


def _save_prediction(user_id, prediction):
    """Save prediction to memory for trend analysis."""
    try:
        learning = db_load_learning(user_id)
        predictions = learning.get("risk_predictions", [])
        predictions.append({
            "score": prediction["risk_score"],
            "level": prediction["risk_level"],
            "at": prediction["timestamp"],
            "top_signals": sorted(
                prediction["signals"].items(),
                key=lambda x: x[1]["contribution"], reverse=True
            )[:3]
        })
        learning["risk_predictions"] = predictions[-30:]  # Keep 30 days
        db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f"save_prediction error: {e}")


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

from flask import Blueprint, request, jsonify

prediction_bp = Blueprint('prediction', __name__)


@prediction_bp.route('/api/predict/risk/<user_id>', methods=['GET'])
def api_predict_risk(user_id):
    """Get 24h crisis prediction for a senior."""
    result = predict_risk(user_id)
    return jsonify({'success': True, **result})


@prediction_bp.route('/api/predict/history/<user_id>', methods=['GET'])
def api_predict_history(user_id):
    """Get prediction history for trend visualization."""
    days = int(request.args.get('days', 7))
    try:
        learning = db_load_learning(user_id)
        predictions = learning.get("risk_predictions", [])
        # Filter by days
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        recent = [p for p in predictions if p.get("at", "") >= cutoff]
        return jsonify({
            'success': True,
            'predictions': recent,
            'count': len(recent),
            'user_id': user_id
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@prediction_bp.route('/api/predict/all', methods=['GET'])
def api_predict_all():
    """Get risk predictions for all active seniors (caregiver dashboard)."""
    try:
        from agent_loop import _get_active_users
        users = _get_active_users()
        results = []
        for uid in users[:20]:  # Max 20
            pred = predict_risk(uid)
            results.append(pred)
        # Sort by risk score descending
        results.sort(key=lambda x: x['risk_score'], reverse=True)
        return jsonify({'success': True, 'predictions': results, 'count': len(results)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


logger.info("🔮 Predictive Agent v1.0 loaded — 7 signals, φ-weighted scoring")
