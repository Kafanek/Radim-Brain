# ============================================
# RADIM DASHBOARD API BLUEPRINT — v2.0
# ============================================
# Consolidated dashboard: one endpoint for ALL subsystems
# Sections: seniors, iot, consciousness, risk, education, telemedicine, ai, context

from flask import Blueprint, request, jsonify, make_response
from datetime import datetime, date
import math
import os
import time
import logging
from auth_middleware import optional_auth

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

PHI = (1 + math.sqrt(5)) / 2
FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199]


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


# ============================================
# DATA AGGREGATION FUNCTIONS
# ============================================

def _get_seniors():
    """Seniors summary from DEMO_SENIORS (future: DB)"""
    try:
        from seniors_routes import DEMO_SENIORS
        active = [s for s in DEMO_SENIORS.values() if s['status'] == 'active']
        if not active:
            return {'total': 0, 'data_source': 'demo', 'residents': []}

        care_levels = {}
        for s in active:
            cl = s['care_level']
            care_levels[cl] = care_levels.get(cl, 0) + 1

        return {
            'total': len(active),
            'avg_age': round(sum(s['age'] for s in active) / len(active), 1),
            'avg_care_level': round(sum(s['care_level'] for s in active) / len(active), 1),
            'high_care': sum(1 for s in active if s.get('care_level', 0) >= 3),
            'care_level_distribution': care_levels,
            'data_source': 'demo',
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


def _get_iot():
    """IoT summary — real PostgreSQL data with fallback to in-memory ROOM_SENSORS"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        ph = '%s' if is_postgres() else '?'

        # Real DB: device/room counts
        rooms_row = db.execute(
            "SELECT COUNT(DISTINCT room_id) as rooms, COUNT(*) as devices "
            "FROM iot_devices WHERE status = 'active'"
        ).fetchone()

        rooms_online = rooms_row['rooms'] if rooms_row else 0
        devices_total = rooms_row['devices'] if rooms_row else 0

        # Unacknowledged alerts
        alerts_row = db.execute(
            "SELECT COUNT(*) as cnt FROM iot_alerts WHERE acknowledged_at IS NULL"
        ).fetchone()
        alerts_count = alerts_row['cnt'] if alerts_row else 0

        # Latest sensor reading timestamp
        latest_row = db.execute(
            "SELECT MAX(recorded_at) as latest FROM iot_sensor_data"
        ).fetchone()
        latest_reading = str(latest_row['latest']) if latest_row and latest_row['latest'] else None

        db.close()

        if rooms_online > 0:
            return {
                'rooms_online': rooms_online,
                'devices_active': devices_total,
                'alerts_count': alerts_count,
                'latest_reading': latest_reading,
                'data_source': 'postgresql',
                'gateway': 'online'
            }
    except Exception:
        pass

    # Fallback: in-memory ROOM_SENSORS
    try:
        from iot_routes import ROOM_SENSORS
        sensors_total = sum(len(r['sensors']) for r in ROOM_SENSORS.values())
        return {
            'rooms_online': len(ROOM_SENSORS),
            'devices_active': sensors_total,
            'alerts_count': 0,
            'latest_reading': None,
            'data_source': 'demo',
            'gateway': 'online'
        }
    except Exception as e:
        return {'error': str(e), 'rooms_online': 0}


def _get_consciousness():
    """Consciousness state — Fibonacci Neural Network with phi weighting"""
    try:
        from predict_routes import JANECKUV_VALUES

        neuron_counts = [1, 1, 2, 3, 5, 8, 13]
        total_neurons = sum(c * 13 for c in neuron_counts)

        t = time.time()
        layer_activations = []
        for i, count in enumerate(neuron_counts):
            activation = 0.6 + 0.4 * abs(math.sin(t / (100 * (i + 1)) + i * PHI))
            layer_activations.append(round(activation, 3))

        lucas_sum = sum(LUCAS)
        value_activations = []
        for i, val in enumerate(JANECKUV_VALUES):
            weight = LUCAS[i] / lucas_sum
            base = 0.6 + weight
            activation = min(1.0, base + 0.05 * math.sin(t / 300 + i))
            value_activations.append(round(activation, 3))

        avg_neural = sum(layer_activations) / len(layer_activations)
        avg_values = sum(value_activations) / len(value_activations)
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
            'resonating_values': resonating
        }
    except Exception as e:
        return {'error': str(e), 'state': 'unknown'}


def _get_risk():
    """Risk overview from predict_routes.RISK_PROFILES"""
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


def _get_education():
    """Education summary — facility-wide stats from PostgreSQL"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        ph = '%s' if is_postgres() else '?'

        # Enrolled students
        enrolled = db.execute(
            "SELECT COUNT(DISTINCT student_id) as cnt FROM education_progress"
        ).fetchone()

        # Completed lessons
        completed = db.execute(
            "SELECT COUNT(*) as cnt FROM education_progress WHERE completed = TRUE"
        ).fetchone()

        # Total quizzes taken
        quizzes = db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(AVG(score), 0) as avg_score "
            "FROM education_progress WHERE score IS NOT NULL"
        ).fetchone()

        # Pending teacher tasks
        pending_tasks = 0
        try:
            pt = db.execute(
                "SELECT COUNT(*) as cnt FROM education_teacher_tasks WHERE status = 'submitted'"
            ).fetchone()
            pending_tasks = pt['cnt'] if pt else 0
        except Exception:
            pass

        db.close()

        return {
            'enrolled_students': enrolled['cnt'] if enrolled else 0,
            'completed_lessons': completed['cnt'] if completed else 0,
            'total_quizzes': quizzes['cnt'] if quizzes else 0,
            'avg_quiz_score': round(float(quizzes['avg_score']), 1) if quizzes and quizzes['avg_score'] else 0,
            'pending_tasks_to_grade': pending_tasks,
            'data_source': 'postgresql'
        }
    except Exception as e:
        return {'error': str(e), 'enrolled_students': 0}


def _get_telemedicine():
    """Telemedicine summary — facility-wide consultation stats"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        # Today's consultations
        today_row = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations "
            f"WHERE scheduled_date = {ph} AND status != 'cancelled'",
            (today,)
        ).fetchone()

        # Pending requests
        pending = db.execute(
            "SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE status = 'requested'"
        ).fetchone()

        # Completed this month
        monthly = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations "
            f"WHERE scheduled_date >= {ph} AND status = 'completed'",
            (month_start,)
        ).fetchone()

        db.close()

        return {
            'today_count': today_row['cnt'] if today_row else 0,
            'pending_requests': pending['cnt'] if pending else 0,
            'completed_this_month': monthly['cnt'] if monthly else 0,
            'date': today
        }
    except Exception as e:
        return {'error': str(e), 'today_count': 0}


def _get_ai_status():
    """AI provider availability"""
    gemini = bool(os.environ.get('GEMINI_API_KEY'))
    claude = bool(os.environ.get('ANTHROPIC_API_KEY'))
    return {
        'gemini': gemini,
        'claude': claude,
        'primary': 'gemini' if gemini else ('claude' if claude else 'none'),
        'providers_active': sum([gemini, claude])
    }


def _get_context():
    """Contextual data — date, nameday, weather, greeting"""
    try:
        from claude_routes import get_today_info, get_greeting, get_fallback_weather
        info = get_today_info()
        result = {
            'date': info.get('date'),
            'day_name': info.get('day_name'),
            'nameday': info.get('nameday'),
            'greeting': get_greeting()
        }
        try:
            weather = get_fallback_weather('Praha')
            result['weather'] = {
                'temperature': weather.get('temperature'),
                'condition': weather.get('condition'),
                'humidity': weather.get('humidity'),
                'wind': weather.get('wind')
            }
        except Exception:
            result['weather'] = None
        return result
    except Exception as e:
        return {'error': str(e)}


# ============================================
# SECTION REGISTRY
# ============================================
SECTION_HANDLERS = {
    'seniors': _get_seniors,
    'iot': _get_iot,
    'consciousness': _get_consciousness,
    'risk': _get_risk,
    'education': _get_education,
    'telemedicine': _get_telemedicine,
    'ai': _get_ai_status,
    'context': _get_context,
}


# ============================================
# V2 ENDPOINTS (consolidated)
# ============================================

@dashboard_bp.route('/api/dashboard/v2', methods=['GET'])
@optional_auth
def get_dashboard_v2():
    """
    Consolidated dashboard — all subsystems in one request.

    Query params:
        sections: comma-separated (seniors,iot,consciousness,risk,education,telemedicine,ai,context,all)
                  default: all
    """
    sections_param = request.args.get('sections', 'all')
    requested = set(sections_param.split(','))
    include_all = 'all' in requested

    result = {
        'success': True,
        'facility': 'Dům seniorů Háje',
        'version': '4.0.0',
        'timestamp': _now_iso(),
        'phi': PHI
    }

    for name, handler in SECTION_HANDLERS.items():
        if include_all or name in requested:
            result[name] = handler()

    # Health indicator
    errors = [k for k, v in result.items() if isinstance(v, dict) and 'error' in v]
    result['health'] = 'healthy' if not errors else 'degraded'
    if errors:
        result['errors'] = errors

    return jsonify(result)


@dashboard_bp.route('/api/dashboard/v2/quick', methods=['GET'])
@optional_auth
def get_dashboard_v2_quick():
    """
    Lightweight v2 dashboard — counts and statuses only.
    For polling, status bars, and mobile widgets.
    """
    seniors = _get_seniors()
    iot = _get_iot()
    consciousness = _get_consciousness()
    risk = _get_risk()
    education = _get_education()
    telemedicine = _get_telemedicine()
    ai = _get_ai_status()

    sections = [seniors, iot, consciousness, risk, education, telemedicine]

    return jsonify({
        'success': True,
        'timestamp': _now_iso(),
        # Seniors
        'seniors_count': seniors.get('total', 0),
        # IoT
        'rooms_online': iot.get('rooms_online', 0),
        'devices_active': iot.get('devices_active', 0),
        'iot_alerts': iot.get('alerts_count', 0),
        'iot_source': iot.get('data_source', 'unknown'),
        # Consciousness
        'consciousness_state': consciousness.get('state', 'unknown'),
        'consciousness_score': consciousness.get('overall_score', 0),
        # Risk
        'high_risk_count': risk.get('high_risk_count', 0),
        'top_risk': risk.get('top_risk_senior'),
        # Education
        'education_enrolled': education.get('enrolled_students', 0),
        'education_pending_tasks': education.get('pending_tasks_to_grade', 0),
        # Telemedicine
        'telemedicine_today': telemedicine.get('today_count', 0),
        'telemedicine_pending': telemedicine.get('pending_requests', 0),
        # AI
        'ai_primary': ai.get('primary', 'none'),
        'ai_providers_active': ai.get('providers_active', 0),
        # Health
        'health': 'healthy' if not any(
            isinstance(v, dict) and 'error' in v for v in sections
        ) else 'degraded'
    })


# ============================================
# V1 ENDPOINTS (deprecated — kept for backward compatibility)
# ============================================

@dashboard_bp.route('/api/dashboard', methods=['GET'])
@optional_auth
def get_dashboard_v1():
    """DEPRECATED: Use /api/dashboard/v2 instead."""
    sections_param = request.args.get('sections', 'all')
    requested = set(sections_param.split(','))
    include_all = 'all' in requested

    result = {
        'success': True,
        'facility': 'Dům seniorů Háje',
        'version': '3.1.0',
        'timestamp': _now_iso(),
        'phi': PHI,
        '_deprecated': 'Use /api/dashboard/v2 for the consolidated version'
    }

    if include_all or 'seniors' in requested:
        result['seniors'] = _get_seniors()
    if include_all or 'iot' in requested:
        result['iot'] = _get_iot()
    if include_all or 'consciousness' in requested:
        result['consciousness'] = _get_consciousness()
    if include_all or 'risk' in requested:
        result['risk'] = _get_risk()

    errors = [k for k, v in result.items() if isinstance(v, dict) and 'error' in v]
    result['health'] = 'healthy' if not errors else 'degraded'
    if errors:
        result['errors'] = errors

    resp = make_response(jsonify(result))
    resp.headers['X-Deprecated'] = 'Use /api/dashboard/v2'
    return resp


@dashboard_bp.route('/api/dashboard/quick', methods=['GET'])
@optional_auth
def get_dashboard_v1_quick():
    """DEPRECATED: Use /api/dashboard/v2/quick instead."""
    seniors = _get_seniors()
    iot = _get_iot()
    consciousness = _get_consciousness()
    risk = _get_risk()

    resp = make_response(jsonify({
        'success': True,
        'timestamp': _now_iso(),
        'seniors_count': seniors.get('total', 0),
        'sensors_online': iot.get('devices_active', 0),
        'sensors_total': iot.get('devices_active', 0),
        'alerts_count': iot.get('alerts_count', 0),
        'consciousness_state': consciousness.get('state', 'unknown'),
        'consciousness_score': consciousness.get('overall_score', 0),
        'high_risk_count': risk.get('high_risk_count', 0),
        'top_risk': risk.get('top_risk_senior'),
        'health': 'healthy' if not any(
            isinstance(v, dict) and 'error' in v
            for v in [seniors, iot, consciousness, risk]
        ) else 'degraded',
        '_deprecated': 'Use /api/dashboard/v2/quick'
    }))
    resp.headers['X-Deprecated'] = 'Use /api/dashboard/v2/quick'
    return resp
