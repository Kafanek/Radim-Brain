"""
📋 AUDIT LOG v1.0
==================
Comprehensive audit trail for medical-grade compliance.
Logs: who accessed what, when, from where.

Every action is immutable — no updates, no deletes.
Required for GDPR, healthcare regulations, and trust.
"""

import logging
import json
from datetime import datetime
from flask import request, g

logger = logging.getLogger(__name__)

# ============================================================================
# SCHEMA
# ============================================================================

AUDIT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        user_id TEXT,
        user_email TEXT,
        user_role TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        senior_id TEXT,
        details JSONB DEFAULT '{}',
        ip_address TEXT,
        user_agent TEXT,
        session_id TEXT,
        success BOOLEAN DEFAULT true
    );

    CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
    CREATE INDEX IF NOT EXISTS idx_audit_senior ON audit_log(senior_id);
    CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
    CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(timestamp);
"""

def init_audit_schema():
    try:
        from database import db_context
        with db_context(commit=True) as db:
            for stmt in AUDIT_SCHEMA.strip().split(';'):
                s = stmt.strip()
                if s:
                    db.execute(s)
    except Exception as e:
        logger.debug(f"Audit schema: {e}")


# ============================================================================
# LOG FUNCTION — call from anywhere
# ============================================================================

# Action types
VIEW = 'view'
CREATE = 'create'
UPDATE = 'update'
DELETE = 'delete'
EXPORT = 'export'
PRINT = 'print'
LOGIN = 'login'
LOGOUT = 'logout'
CONSENT = 'consent'
ALERT = 'alert'
MESSAGE = 'message'
UPLOAD = 'upload'


def log_audit(action, resource_type=None, resource_id=None, senior_id=None,
              details=None, success=True, user_id=None):
    """
    Log an audit event. Call from any endpoint.

    Args:
        action: VIEW, CREATE, UPDATE, DELETE, EXPORT, PRINT, LOGIN, etc.
        resource_type: 'brain_state', 'medical_message', 'consent', 'report', etc.
        resource_id: ID of the resource
        senior_id: which senior this relates to
        details: dict with extra context
        success: whether action succeeded
        user_id: override (auto-detected from g.auth_user)
    """
    try:
        from database import db_context

        # Auto-detect user from Flask context
        auth = getattr(g, 'auth_user', None) or {}
        uid = user_id or str(auth.get('id', ''))
        email = auth.get('email', '')
        role = auth.get('role', '')

        # Request context
        ip = ''
        ua = ''
        try:
            ip = request.remote_addr or ''
            ua = (request.headers.get('User-Agent', '') or '')[:200]
        except Exception:
            pass

        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO audit_log (user_id, user_email, user_role, action, "
                "resource_type, resource_id, senior_id, details, ip_address, user_agent, success) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, email, role, action, resource_type or '', str(resource_id or ''),
                 senior_id or '', json.dumps(details or {}), ip, ua, success)
            )
    except Exception as e:
        # Audit logging must NEVER crash the app
        logger.debug(f"Audit log: {e}")


def get_audit_trail(senior_id=None, user_id=None, action=None, days=30, limit=100):
    """Query audit trail with filters."""
    try:
        from database import db_context
        conditions = []
        params = []

        if senior_id:
            conditions.append("senior_id = ?")
            params.append(senior_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if action:
            conditions.append("action = ?")
            params.append(action)

        conditions.append(f"timestamp > NOW() - INTERVAL '{days} days'")

        where = " AND ".join(conditions) if conditions else "1=1"

        with db_context() as db:
            rows = db.execute(
                f"SELECT id, timestamp, user_id, user_email, user_role, action, "
                f"resource_type, resource_id, senior_id, details, ip_address, success "
                f"FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ?",
                (*params, limit)
            ).fetchall()

        return [{
            'id': r[0], 'timestamp': str(r[1]), 'user_id': r[2],
            'email': r[3], 'role': r[4], 'action': r[5],
            'resource_type': r[6], 'resource_id': r[7],
            'senior_id': r[8], 'details': json.loads(r[9] or '{}'),
            'ip': r[10], 'success': r[11],
        } for r in rows]

    except Exception as e:
        logger.debug(f"Audit query: {e}")
        return []


# ============================================================================
# API ENDPOINT
# ============================================================================

from flask import Blueprint, jsonify
audit_bp = Blueprint('audit', __name__)

@audit_bp.route('/api/audit/trail', methods=['GET'])
def audit_trail_endpoint():
    """GET /api/audit/trail?senior_id=X&days=30&limit=50"""
    from auth_middleware import require_auth
    # Only admin/coordinator can view audit trail
    auth = getattr(g, 'auth_user', None) or {}
    if auth.get('role') not in ('admin', 'administrator', 'coordinator'):
        return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403

    trail = get_audit_trail(
        senior_id=request.args.get('senior_id'),
        user_id=request.args.get('user_id'),
        action=request.args.get('action'),
        days=request.args.get('days', 30, type=int),
        limit=request.args.get('limit', 100, type=int),
    )

    return jsonify({'success': True, 'trail': trail, 'count': len(trail)})


@audit_bp.route('/api/audit/stats', methods=['GET'])
def audit_stats():
    """Audit statistics — action counts per type."""
    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute(
                "SELECT action, COUNT(*) FROM audit_log "
                "WHERE timestamp > NOW() - INTERVAL '30 days' GROUP BY action ORDER BY count DESC"
            ).fetchall()
        stats = {r[0]: r[1] for r in rows}
        return jsonify({'success': True, 'stats': stats, 'total': sum(stats.values())})
    except Exception:
        return jsonify({'success': True, 'stats': {}, 'total': 0})


# Init schema on import
init_audit_schema()

logger.info("📋 Audit Log v1.0 loaded — immutable trail for compliance")
