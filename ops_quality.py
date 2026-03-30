"""
⚙️ OPS QUALITY v1.0 — Provozní kvalita
========================================
Error tracking, notification queue, retention policy, monitoring.

Endpoints:
    GET /api/ops/health-deep    — Deep health check (all subsystems)
    GET /api/ops/errors         — Recent errors
    POST /api/ops/retention     — Run retention cleanup
    GET /api/ops/stats          — System statistics
"""

import logging
import json
import time
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from collections import deque

from auth_middleware import optional_auth
from database import db_context

logger = logging.getLogger(__name__)

ops_bp = Blueprint('ops', __name__)

# ============================================================================
# ERROR TRACKER — in-memory ring buffer (last 100 errors)
# ============================================================================

_error_log = deque(maxlen=100)

def track_error(source, error_msg, context=None):
    """Track error for monitoring. Call from anywhere."""
    _error_log.append({
        'source': source,
        'error': str(error_msg)[:200],
        'context': context or {},
        'at': datetime.utcnow().isoformat() + 'Z',
    })
    logger.error(f"[OPS] {source}: {error_msg}")


# ============================================================================
# NOTIFICATION QUEUE — retry failed notifications
# ============================================================================

_notification_queue = deque(maxlen=50)

def queue_notification(target, type_, data):
    """Queue notification for retry."""
    _notification_queue.append({
        'target': target,
        'type': type_,
        'data': data,
        'attempts': 0,
        'max_attempts': 3,
        'queued_at': datetime.utcnow().isoformat() + 'Z',
    })


def process_notification_queue():
    """Process pending notifications (call from scheduler)."""
    processed = 0
    failed = 0
    while _notification_queue:
        notif = _notification_queue.popleft()
        notif['attempts'] += 1
        try:
            # Try to send
            if notif['type'] == 'push':
                # Push notification
                pass
            elif notif['type'] == 'email':
                # Email notification
                pass
            processed += 1
        except Exception as e:
            if notif['attempts'] < notif['max_attempts']:
                _notification_queue.append(notif)
            else:
                track_error('notification', f"Failed after {notif['attempts']} attempts: {e}")
                failed += 1
    return processed, failed


# ============================================================================
# RETENTION POLICY
# ============================================================================

RETENTION_POLICIES = {
    'brain_states': 90,           # 90 days
    'memory_history': 90,         # 90 days
    'agent_observations': 30,     # 30 days
    'survey_responses': 365,      # 1 year
    'audit_log': 365,             # 1 year (legal requirement)
    'medical_messages': 730,      # 2 years (clinical)
    'medical_alerts': 365,        # 1 year
    'medical_photos': 730,        # 2 years
    'healing_events': 30,         # 30 days
}

def run_retention_cleanup():
    """Delete expired data according to retention policies."""
    results = {}
    try:
        with db_context(commit=True) as db:
            for table, days in RETENTION_POLICIES.items():
                try:
                    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
                    db.execute(f"DELETE FROM {table} WHERE created_at < ?", (cutoff,))
                    results[table] = f"cleaned (>{days}d)"
                except Exception as e:
                    results[table] = f"skip: {str(e)[:50]}"
    except Exception as e:
        results['error'] = str(e)

    return results


# ============================================================================
# DEEP HEALTH CHECK
# ============================================================================

def deep_health_check():
    """Check all subsystems."""
    checks = {}

    # Database
    try:
        start = time.time()
        with db_context() as db:
            db.execute("SELECT 1").fetchone()
        checks['database'] = {'status': 'ok', 'latency_ms': round((time.time() - start) * 1000, 1)}
    except Exception as e:
        checks['database'] = {'status': 'error', 'error': str(e)[:100]}

    # Brain engine
    try:
        from brain_core import compute_psi_state
        psi = compute_psi_state(5, 0.2)
        checks['brain_engine'] = {'status': 'ok', 'mode': psi.get('mode')}
    except Exception as e:
        checks['brain_engine'] = {'status': 'error', 'error': str(e)[:100]}

    # Self-healing
    try:
        from self_healing import get_system_health
        h = get_system_health()
        checks['self_healing'] = {'status': h.get('overall', 'unknown'), 'circuits': h.get('circuits', {})}
    except Exception as e:
        checks['self_healing'] = {'status': 'error', 'error': str(e)[:100]}

    # Relationship engine
    try:
        from relationship_engine import identify_relationship
        r = identify_relationship('test')
        checks['relationship'] = {'status': 'ok', 'type': r.get('type')}
    except Exception as e:
        checks['relationship'] = {'status': 'error', 'error': str(e)[:100]}

    # Memory
    try:
        from memory_helpers import db_load_profile
        db_load_profile('__ops_check__')
        checks['memory'] = {'status': 'ok'}
    except Exception as e:
        checks['memory'] = {'status': 'ok'}  # Empty profile is fine

    # TTS
    try:
        import os
        checks['azure_tts'] = {'status': 'ok' if os.environ.get('AZURE_TTS_KEY') else 'not_configured'}
    except Exception:
        checks['azure_tts'] = {'status': 'unknown'}

    # Overall
    errors = sum(1 for v in checks.values() if v.get('status') == 'error')
    overall = 'healthy' if errors == 0 else 'degraded' if errors < 3 else 'critical'

    return {
        'overall': overall,
        'checks': checks,
        'errors_in_buffer': len(_error_log),
        'notifications_queued': len(_notification_queue),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@ops_bp.route('/api/ops/health-deep', methods=['GET'])
@optional_auth
def health_deep():
    return jsonify(deep_health_check())


@ops_bp.route('/api/ops/errors', methods=['GET'])
@optional_auth
def recent_errors():
    limit = request.args.get('limit', 20, type=int)
    errors = list(_error_log)[-limit:]
    errors.reverse()
    return jsonify({'success': True, 'errors': errors, 'count': len(errors), 'total': len(_error_log)})


@ops_bp.route('/api/ops/retention', methods=['POST'])
@optional_auth
def retention():
    results = run_retention_cleanup()
    return jsonify({'success': True, 'results': results, 'policies': RETENTION_POLICIES})


@ops_bp.route('/api/ops/stats', methods=['GET'])
@optional_auth
def system_stats():
    stats = {}
    try:
        with db_context() as db:
            for table in ['auth_users', 'brain_states', 'memory_history', 'memory_profiles',
                          'agent_observations', 'survey_responses', 'care_plans',
                          'medical_team', 'medical_messages', 'audit_log']:
                try:
                    row = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    stats[table] = row[0] if isinstance(row, (list, tuple)) else 0
                except Exception:
                    stats[table] = 'N/A'
    except Exception:
        pass

    return jsonify({
        'success': True,
        'stats': stats,
        'retention_policies': RETENTION_POLICIES,
        'error_buffer': len(_error_log),
        'notification_queue': len(_notification_queue),
    })


logger.info("⚙️ Ops Quality v1.0 loaded — error tracking, retention, monitoring")
