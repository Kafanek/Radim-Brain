# ============================================
# DASHBOARD AGGREGATORS v1.0.0
# ============================================
# Data aggregation functions for dashboard endpoints.
# Each function fetches data from a subsystem.
# Extracted from dashboard_routes.py for modularity.
# ============================================

import math
import os
import time
import logging
from datetime import date

logger = logging.getLogger(__name__)

PHI = (1 + math.sqrt(5)) / 2
FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144]
LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199]


# ============================================================================
# AGGREGATOR FUNCTIONS
# ============================================================================

def get_seniors():
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


def get_iot():
    """IoT summary — real PostgreSQL data with fallback to in-memory ROOM_SENSORS"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()

        rooms_row = db.execute(
            "SELECT COUNT(DISTINCT room_id) as rooms, COUNT(*) as devices "
            "FROM iot_devices WHERE status = 'active'"
        ).fetchone()

        rooms_online = rooms_row['rooms'] if rooms_row else 0
        devices_total = rooms_row['devices'] if rooms_row else 0

        alerts_row = db.execute(
            "SELECT COUNT(*) as cnt FROM iot_alerts WHERE acknowledged_at IS NULL"
        ).fetchone()
        alerts_count = alerts_row['cnt'] if alerts_row else 0

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


def get_consciousness():
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


def get_risk():
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


def get_education():
    """Education summary — facility-wide stats from PostgreSQL"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        ph = '%s' if is_postgres() else '?'

        enrolled = db.execute(
            "SELECT COUNT(DISTINCT user_id) as cnt FROM education_progress"
        ).fetchone()

        completed = db.execute(
            "SELECT COUNT(*) as cnt FROM education_progress WHERE action LIKE 'complete%'"
        ).fetchone()

        quizzes = db.execute(
            "SELECT COUNT(*) as cnt, COALESCE(AVG(score), 0) as avg_score "
            "FROM education_progress WHERE score IS NOT NULL"
        ).fetchone()

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


def get_telemedicine():
    """Telemedicine summary — facility-wide consultation stats"""
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        today_row = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations "
            f"WHERE scheduled_date = {ph} AND status != 'cancelled'",
            (today,)
        ).fetchone()

        pending = db.execute(
            "SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE status = 'requested'"
        ).fetchone()

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


def get_ai_status():
    """AI provider availability"""
    gemini = bool(os.environ.get('GEMINI_API_KEY'))
    claude = bool(os.environ.get('ANTHROPIC_API_KEY'))
    return {
        'gemini': gemini,
        'claude': claude,
        'primary': 'gemini' if gemini else ('claude' if claude else 'none'),
        'providers_active': sum([gemini, claude])
    }


def get_context():
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


# ============================================================================
# SECTION REGISTRY
# ============================================================================

SECTION_HANDLERS = {
    'seniors': get_seniors,
    'iot': get_iot,
    'consciousness': get_consciousness,
    'risk': get_risk,
    'education': get_education,
    'telemedicine': get_telemedicine,
    'ai': get_ai_status,
    'context': get_context,
}

# ============================================================================
# HEALTH MODULES
# ============================================================================

HEALTH_MODULES = {
    'claude': '/api/claude/health',
    'speech': '/api/speech/health',
    'twilio': '/api/twilio/health',
    'iot_bridge': '/api/iot-bridge/health',
    'brain': '/api/brain/health',
    'memory': '/api/memory/health',
    'orchestrator': '/api/orchestrator/health',
    'anticipation': '/api/anticipation/health',
    'education': '/api/education/courses',
    'telemedicine': '/api/telemedicine/health',
    'voice': '/api/voice/health',
    'soul': '/api/soul/health',
    'rhythm': '/api/rhythm-return/health',
    'email': '/api/email/health',
}


logger.info("Dashboard Aggregators loaded — 8 sections, 14 health modules")
