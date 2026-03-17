# ============================================
# RADIM DASHBOARD ROUTES v2.1.0
# ============================================
# Consolidated dashboard: one endpoint for ALL subsystems.
# Data aggregation in dashboard_aggregators.py.
#
# Routes:
#   GET /api/dashboard/v2
#   GET /api/dashboard/v2/quick
#   GET /api/health/all
#   GET /api/dashboard       (deprecated v1)
#   GET /api/dashboard/quick (deprecated v1)
# ============================================

from flask import Blueprint, request, jsonify, make_response
import logging
from auth_middleware import optional_auth
from utils import now_iso

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__)

# ============================================================================
# IMPORTS FROM AGGREGATORS (+ re-exports for backward compat)
# ============================================================================

from dashboard_aggregators import (
    PHI, FIBONACCI, LUCAS,
    get_seniors, get_iot, get_consciousness, get_risk,
    get_education, get_telemedicine, get_ai_status, get_context,
    SECTION_HANDLERS, HEALTH_MODULES,
)

# Backward compat aliases (underscore-prefixed names)
_get_seniors = get_seniors
_get_iot = get_iot
_get_consciousness = get_consciousness
_get_risk = get_risk
_get_education = get_education
_get_telemedicine = get_telemedicine
_get_ai_status = get_ai_status
_get_context = get_context


# ============================================================================
# V2 ENDPOINTS (consolidated)
# ============================================================================

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
        'facility': 'Dum senioru Haje',
        'version': '4.0.0',
        'timestamp': now_iso(),
        'phi': PHI
    }

    for name, handler in SECTION_HANDLERS.items():
        if include_all or name in requested:
            result[name] = handler()

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
    seniors = get_seniors()
    iot = get_iot()
    consciousness = get_consciousness()
    risk = get_risk()
    education = get_education()
    telemedicine = get_telemedicine()
    ai = get_ai_status()

    sections = [seniors, iot, consciousness, risk, education, telemedicine]

    return jsonify({
        'success': True,
        'timestamp': now_iso(),
        'seniors_count': seniors.get('total', 0),
        'rooms_online': iot.get('rooms_online', 0),
        'devices_active': iot.get('devices_active', 0),
        'iot_alerts': iot.get('alerts_count', 0),
        'iot_source': iot.get('data_source', 'unknown'),
        'consciousness_state': consciousness.get('state', 'unknown'),
        'consciousness_score': consciousness.get('overall_score', 0),
        'high_risk_count': risk.get('high_risk_count', 0),
        'top_risk': risk.get('top_risk_senior'),
        'education_enrolled': education.get('enrolled_students', 0),
        'education_pending_tasks': education.get('pending_tasks_to_grade', 0),
        'telemedicine_today': telemedicine.get('today_count', 0),
        'telemedicine_pending': telemedicine.get('pending_requests', 0),
        'ai_primary': ai.get('primary', 'none'),
        'ai_providers_active': ai.get('providers_active', 0),
        'health': 'healthy' if not any(
            isinstance(v, dict) and 'error' in v for v in sections
        ) else 'degraded'
    })


# ============================================================================
# UNIFIED HEALTH CHECK
# ============================================================================

@dashboard_bp.route('/api/health/all', methods=['GET'])
@optional_auth
def unified_health():
    """
    Unified health check — aggregates status of all modules.
    Calls each module's health endpoint internally via Flask test client.
    """
    from flask import current_app

    modules = {}
    healthy_count = 0
    total_count = 0

    for name, path in HEALTH_MODULES.items():
        total_count += 1
        try:
            with current_app.test_client() as client:
                resp = client.get(path, headers={'X-Internal-Health': '1'})
                if resp.status_code == 200:
                    modules[name] = {'status': 'ok', 'code': 200}
                    healthy_count += 1
                else:
                    modules[name] = {'status': 'error', 'code': resp.status_code}
        except Exception as e:
            modules[name] = {'status': 'unavailable', 'error': str(e)}

    # Database check
    try:
        from database import get_connection, is_postgres
        db = get_connection()
        db.execute("SELECT 1").fetchone()
        db.close()
        modules['database'] = {
            'status': 'ok',
            'type': 'postgresql' if is_postgres() else 'sqlite'
        }
        healthy_count += 1
        total_count += 1
    except Exception as e:
        modules['database'] = {'status': 'error', 'error': str(e)}
        total_count += 1

    ai = get_ai_status()
    modules['ai'] = {
        'status': 'ok' if ai['providers_active'] > 0 else 'warning',
        'gemini': ai['gemini'],
        'claude_api': ai['claude'],
        'primary': ai['primary']
    }

    overall = 'healthy' if healthy_count >= total_count * 0.8 else (
        'degraded' if healthy_count >= total_count * 0.5 else 'critical'
    )

    return jsonify({
        'success': True,
        'status': overall,
        'healthy': healthy_count,
        'total': total_count,
        'modules': modules,
        'timestamp': now_iso(),
        'version': '4.0.0'
    })


# ============================================================================
# V1 ENDPOINTS (deprecated — kept for backward compatibility)
# ============================================================================

@dashboard_bp.route('/api/dashboard', methods=['GET'])
@optional_auth
def get_dashboard_v1():
    """DEPRECATED: Use /api/dashboard/v2 instead."""
    sections_param = request.args.get('sections', 'all')
    requested = set(sections_param.split(','))
    include_all = 'all' in requested

    result = {
        'success': True,
        'facility': 'Dum senioru Haje',
        'version': '3.1.0',
        'timestamp': now_iso(),
        'phi': PHI,
        '_deprecated': 'Use /api/dashboard/v2 for the consolidated version'
    }

    if include_all or 'seniors' in requested:
        result['seniors'] = get_seniors()
    if include_all or 'iot' in requested:
        result['iot'] = get_iot()
    if include_all or 'consciousness' in requested:
        result['consciousness'] = get_consciousness()
    if include_all or 'risk' in requested:
        result['risk'] = get_risk()

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
    seniors = get_seniors()
    iot = get_iot()
    consciousness = get_consciousness()
    risk = get_risk()

    resp = make_response(jsonify({
        'success': True,
        'timestamp': now_iso(),
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


# ============================================================================
# STARTUP
# ============================================================================
logger.info("Dashboard Routes v2.1.0 loaded — /api/dashboard/*")
logger.info("   Aggregators module: dashboard_aggregators.py")
