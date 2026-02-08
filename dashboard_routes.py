# ============================================
# 📊 RADIM DASHBOARD API BLUEPRINT
# ============================================
# Version: 1.0.0
# Agregační endpoint pro frontend dashboard a investorské demo
# Jeden GET request = kompletní přehled celého systému

from flask import Blueprint, request, jsonify
from datetime import datetime
import math

dashboard_bp = Blueprint('dashboard', __name__)

PHI = (1 + math.sqrt(5)) / 2  # 1.618033988749895


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _get_seniors_summary():
    """Import a volání seniors dat"""
    try:
        from seniors_routes import SENIORS_DB
        active = [s for s in SENIORS_DB.values() if s['status'] == 'active']
        care_levels = {}
        for s in active:
            cl = s['care_level']
            care_levels[cl] = care_levels.get(cl, 0) + 1

        return {
            'total': len(active),
            'avg_age': round(sum(s['age'] for s in active) / len(active), 1) if active else 0,
            'avg_care_level': round(sum(s['care_level'] for s in active) / len(active), 1) if active else 0,
            'care_level_distribution': care_levels,
            'residents': [
                {
                    'id': s['id'],
                    'name': s['name'],
                    'age': s['age'],
                    'room': s['room'],
                    'care_level': s['care_level'],
                    'diagnoses_count': len(s.get('diagnoses', []))
                }
                for s in active
            ]
        }
    except Exception as e:
        return {'error': str(e), 'total': 0}


def _get_iot_summary():
    """Import a volání IoT dat"""
    try:
        from iot_routes import ROOMS_CONFIG, _generate_vitals, _generate_room_environment

        rooms_online = 0
        sensors_total = 0
        sensors_online = 0
        alerts = []
        room_statuses = []

        for senior_id, config in ROOMS_CONFIG.items():
            rooms_online += 1
            room_sensors = len(config['sensors'])
            sensors_total += room_sensors

            # Simulate sensor check (same logic as iot_routes)
            import hashlib
            h = int(hashlib.md5(f"{senior_id}{datetime.utcnow().hour}".encode()).hexdigest(), 16)
            offline_count = 1 if (h % 7 == 0) else 0
            sensors_online += room_sensors - offline_count

            if offline_count > 0:
                alerts.append({
                    'room': config['room'],
                    'senior_id': senior_id,
                    'type': 'sensor_offline',
                    'severity': 'warning'
                })

            room_statuses.append({
                'room': config['room'],
                'senior_id': senior_id,
                'sensors': room_sensors,
                'status': 'degraded' if offline_count > 0 else 'online'
            })

        return {
            'rooms_online': rooms_online,
            'rooms_total': len(ROOMS_CONFIG),
            'sensors_online': sensors_online,
            'sensors_total': sensors_total,
            'alerts_count': len(alerts),
            'alerts': alerts,
            'rooms': room_statuses,
            'gateway': 'online',
            'phi_calibration': True
        }
    except Exception as e:
        return {'error': str(e), 'rooms_online': 0, 'sensors_online': 0}


def _get_consciousness_summary():
    """Import a volání consciousness dat"""
    try:
        from predict_routes import JANECKOVY_HODNOTY, FIBONACCI_LAYERS
        import time

        # Compute consciousness score (same φ-based logic as predict_routes)
        t = time.time()
        layer_activations = []
        for i, layer in enumerate(FIBONACCI_LAYERS):
            activation = 0.6 + 0.4 * abs(math.sin(t / (100 * (i + 1)) + i * PHI))
            layer_activations.append(round(activation, 3))

        value_activations = []
        for i, val in enumerate(JANECKOVY_HODNOTY):
            fib_resonance = (PHI ** i) / (PHI ** 11)
            activation = 0.4 + 0.6 * fib_resonance
            value_activations.append(round(min(activation, 1.0), 3))

        avg_neural = sum(layer_activations) / len(layer_activations)
        avg_values = sum(value_activations) / len(value_activations)
        overall = round((2 * avg_neural * avg_values) / (avg_neural + avg_values), 3) if (avg_neural + avg_values) > 0 else 0

        # Resonating values (activation > 0.7)
        resonating = [JANECKOVY_HODNOTY[i] for i, a in enumerate(value_activations) if a > 0.7]

        return {
            'state': 'aware' if overall > 0.6 else 'dormant',
            'overall_score': overall,
            'neural_avg': round(avg_neural, 3),
            'values_avg': round(avg_values, 3),
            'layers': len(FIBONACCI_LAYERS),
            'total_neurons': sum(l['neurons'] for l in FIBONACCI_LAYERS),
            'values_count': len(JANECKOVY_HODNOTY),
            'resonating_values': resonating,
            'motto': 'Pojďme si mezigeneračně hrát a tvořit lepší svět'
        }
    except Exception as e:
        return {'error': str(e), 'state': 'unknown'}


def _get_risk_overview():
    """Přehled rizik všech seniorů"""
    try:
        from predict_routes import RISK_PROFILES

        high_risk = []
        moderate_risk = []
        low_risk = []

        for senior_id, profile in RISK_PROFILES.items():
            risk_score = profile['base_risk']
            entry = {
                'senior_id': senior_id,
                'name': profile.get('name', senior_id),
                'risk_score': round(risk_score, 2),
                'primary_concerns': profile.get('primary_concerns', [])[:2],
                'risk_factors_count': len(profile.get('risk_factors', []))
            }

            if risk_score >= 0.7:
                high_risk.append(entry)
            elif risk_score >= 0.4:
                moderate_risk.append(entry)
            else:
                low_risk.append(entry)

        return {
            'high_risk_count': len(high_risk),
            'moderate_risk_count': len(moderate_risk),
            'low_risk_count': len(low_risk),
            'high_risk': sorted(high_risk, key=lambda x: x['risk_score'], reverse=True),
            'moderate_risk': sorted(moderate_risk, key=lambda x: x['risk_score'], reverse=True),
            'top_risk_senior': high_risk[0] if high_risk else (moderate_risk[0] if moderate_risk else None)
        }
    except Exception as e:
        return {'error': str(e), 'high_risk_count': 0}


# ============================================
# DASHBOARD ENDPOINT
# ============================================
@dashboard_bp.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    """
    Agregační dashboard endpoint.
    
    Query params:
        sections: čárkou oddělené sekce (seniors,iot,consciousness,risk,all)
                  default: all
    
    Returns: Kompletní přehled systému v jednom requestu.
    """
    sections_param = request.args.get('sections', 'all')
    requested = set(sections_param.split(','))
    include_all = 'all' in requested

    result = {
        'success': True,
        'facility': 'Dům seniorů Háje',
        'version': '3.1.0',
        'timestamp': now_iso(),
        'phi': PHI
    }

    if include_all or 'seniors' in requested:
        result['seniors'] = _get_seniors_summary()

    if include_all or 'iot' in requested:
        result['iot'] = _get_iot_summary()

    if include_all or 'consciousness' in requested:
        result['consciousness'] = _get_consciousness_summary()

    if include_all or 'risk' in requested:
        result['risk'] = _get_risk_overview()

    # Quick health indicator
    errors = [k for k, v in result.items() if isinstance(v, dict) and 'error' in v]
    result['health'] = 'healthy' if not errors else 'degraded'
    if errors:
        result['errors'] = errors

    return jsonify(result)


@dashboard_bp.route('/api/dashboard/quick', methods=['GET'])
def get_dashboard_quick():
    """
    Lightweight dashboard – jen počty a stavy, žádné detaily.
    Pro polling a status bary.
    """
    seniors = _get_seniors_summary()
    iot = _get_iot_summary()
    consciousness = _get_consciousness_summary()
    risk = _get_risk_overview()

    return jsonify({
        'success': True,
        'timestamp': now_iso(),
        'seniors_count': seniors.get('total', 0),
        'sensors_online': iot.get('sensors_online', 0),
        'sensors_total': iot.get('sensors_total', 0),
        'alerts_count': iot.get('alerts_count', 0),
        'consciousness_state': consciousness.get('state', 'unknown'),
        'consciousness_score': consciousness.get('overall_score', 0),
        'high_risk_count': risk.get('high_risk_count', 0),
        'top_risk': risk.get('top_risk_senior'),
        'health': 'healthy' if not any(
            isinstance(v, dict) and 'error' in v 
            for v in [seniors, iot, consciousness, risk]
        ) else 'degraded'
    })
