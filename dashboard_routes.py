# ============================================
# 📊 RADIM DASHBOARD API BLUEPRINT
# ============================================
# Version: 1.0.0
# Agregační endpoint pro frontend dashboard a investorské demo
# Jeden GET request = kompletní přehled celého systému

from flask import Blueprint, request, jsonify
from datetime import datetime
import math
import hashlib
import time

dashboard_bp = Blueprint('dashboard', __name__)

PHI = (1 + math.sqrt(5)) / 2  # 1.618033988749895
FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199]


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _get_seniors_summary():
    """Sumarizace dat seniorů z seniors_routes.DEMO_SENIORS"""
    try:
        from seniors_routes import DEMO_SENIORS
        active = [s for s in DEMO_SENIORS.values() if s['status'] == 'active']
        if not active:
            return {'total': 0, 'residents': []}

        care_levels = {}
        for s in active:
            cl = s['care_level']
            care_levels[cl] = care_levels.get(cl, 0) + 1

        return {
            'total': len(active),
            'avg_age': round(sum(s['age'] for s in active) / len(active), 1),
            'avg_care_level': round(sum(s['care_level'] for s in active) / len(active), 1),
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
    """Sumarizace IoT senzorů z iot_routes.ROOM_SENSORS"""
    try:
        from iot_routes import ROOM_SENSORS

        rooms_online = 0
        sensors_total = 0
        sensors_online = 0
        alerts = []
        room_statuses = []

        for senior_id, config in ROOM_SENSORS.items():
            rooms_online += 1
            room_sensors = len(config['sensors'])
            sensors_total += room_sensors

            # Deterministická simulace offline senzoru (shodná logika s iot_routes)
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
            'rooms_total': len(ROOM_SENSORS),
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
    """Sumarizace stavu vědomí – stejná φ logika jako predict_routes.compute_consciousness_state"""
    try:
        from predict_routes import JANECKUV_VALUES

        # 7 vrstev Fibonacci Neural Network
        neuron_counts = [1, 1, 2, 3, 5, 8, 13]
        total_neurons = sum(c * 13 for c in neuron_counts)  # 527

        t = time.time()
        layer_activations = []
        for i, count in enumerate(neuron_counts):
            activation = 0.6 + 0.4 * abs(math.sin(t / (100 * (i + 1)) + i * PHI))
            layer_activations.append(round(activation, 3))

        value_activations = []
        for i, val in enumerate(JANECKUV_VALUES):
            weight = LUCAS[i] / sum(LUCAS)
            base = 0.6 + weight
            # Stabilní aktivace s mírnou časovou variací
            activation = min(1.0, base + 0.05 * math.sin(t / 300 + i))
            value_activations.append(round(activation, 3))

        avg_neural = sum(layer_activations) / len(layer_activations)
        avg_values = sum(value_activations) / len(value_activations)

        # Harmonický průměr vážený φ (shodný s predict_routes)
        overall = round((avg_neural * PHI + avg_values) / (PHI + 1), 3)

        if overall >= 0.8:
            state = "transcendent"
        elif overall >= 0.65:
            state = "aware"
        elif overall >= 0.5:
            state = "processing"
        elif overall >= 0.3:
            state = "resting"
        else:
            state = "dormant"

        resonating = [JANECKUV_VALUES[i] for i, a in enumerate(value_activations) if a > 0.7]

        return {
            'state': state,
            'overall_score': overall,
            'neural_avg': round(avg_neural, 3),
            'values_avg': round(avg_values, 3),
            'layers': 7,
            'total_neurons': total_neurons,
            'values_count': len(JANECKUV_VALUES),
            'resonating_values': resonating,
            'motto': 'Pojďme si mezigeneračně hrát a tvořit lepší svět'
        }
    except Exception as e:
        return {'error': str(e), 'state': 'unknown'}


def _get_risk_overview():
    """Přehled rizik z predict_routes.RISK_PROFILES"""
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
# DASHBOARD ENDPOINTS
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
