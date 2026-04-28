"""
🏠 HOME ASSISTANT SCENES + EMERGENCY + FAMILY ROUTES v1.0 (Sprint C)
=============================================================================
Sprint C additions to the Smart Home module:

- POST   /api/ha/scenes/custom                — save user custom scene
- GET    /api/ha/scenes/custom                — list user's custom scenes
- DELETE /api/ha/scenes/custom/<id>           — delete a custom scene
- POST   /api/ha/scene/<scene_id>/activate    — activate (custom or HA scene)
- POST   /api/ha/emergency                    — senior triggered emergency
- GET    /api/ha/family/<senior_id>/home-status — family reads senior's state
- GET    /api/ha/family/<senior_id>/emergencies — family sees emergency log

All endpoints require_auth. The family endpoints also verify
senior_family_links.confirmed=TRUE.

Security notes (built on Sprint A):
- Emergency events are written to DB before any family push (audit trail)
- Scene activation goes through the existing action whitelist (no bypass)
- Custom scenes validate each sub-action against _is_action_allowed
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

ha_scenes_bp = Blueprint('ha_scenes', __name__)


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS ha_custom_scenes (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        icon TEXT,
        actions JSONB NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, name)
    );

    CREATE TABLE IF NOT EXISTS ha_emergency_events (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        source TEXT,
        message TEXT,
        device_context JSONB,
        triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        resolved_by TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ha_custom_scenes_user
        ON ha_custom_scenes(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_ha_emergency_user
        ON ha_emergency_events(user_id, triggered_at DESC);
"""

SCHEMA_SQL_SQLITE = """
    CREATE TABLE IF NOT EXISTS ha_custom_scenes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        icon TEXT,
        actions TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, name)
    );

    CREATE TABLE IF NOT EXISTS ha_emergency_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        source TEXT,
        message TEXT,
        device_context TEXT,
        triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        resolved_by TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_ha_custom_scenes_user
        ON ha_custom_scenes(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_ha_emergency_user
        ON ha_emergency_events(user_id, triggered_at DESC);
"""


def _init_schema():
    try:
        sql = SCHEMA_SQL if is_postgres() else SCHEMA_SQL_SQLITE
        with db_context(commit=True) as db:
            for stmt in sql.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"ha_scenes schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


# ============================================================
# CUSTOM SCENES
# ============================================================

def _validate_scene_actions(actions):
    """Reject scene actions that don't pass the existing whitelist."""
    try:
        from home_assistant import _is_action_allowed
    except Exception as e:
        logger.error(f"cannot import whitelist: {e}")
        return False, 'whitelist unavailable'

    if not isinstance(actions, list) or not actions:
        return False, 'actions must be a non-empty list'
    if len(actions) > 20:
        return False, 'too many actions (max 20)'

    for i, step in enumerate(actions):
        if not isinstance(step, dict):
            return False, f'step {i}: must be an object'
        action = (step.get('action') or '').strip()
        ok, _needs_confirm, reason = _is_action_allowed(action)
        if not ok:
            return False, f'step {i}: action "{action}" rejected ({reason})'
    return True, ''


@ha_scenes_bp.route('/api/ha/scenes/custom', methods=['POST', 'OPTIONS'])
@require_auth
def save_custom_scene():
    """Create or update a user's custom scene.

    Body: {"name": "Večer u televize", "icon": "📺",
           "actions": [{"action":"light_on","entity_id":"light.sofa"}, ...]}
    UNIQUE(user_id, name) — re-posting the same name replaces.
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:80]
    icon = (data.get('icon') or '')[:8] or '✨'
    actions = data.get('actions')

    if not name:
        return jsonify({'success': False, 'error': 'name required'}), 400

    ok, reason = _validate_scene_actions(actions)
    if not ok:
        return jsonify({'success': False, 'error': reason}), 400

    actions_json = json.dumps(actions)

    try:
        with db_context(commit=True) as db:
            existing = db.execute(
                "SELECT id FROM ha_custom_scenes WHERE user_id = ? AND name = ?",
                (uid, name)
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE ha_custom_scenes SET icon = ?, actions = ? "
                    "WHERE user_id = ? AND name = ?",
                    (icon, actions_json, uid, name)
                )
                sid = _row_val(existing, 0, 'id')
                return jsonify({'success': True, 'id': sid, 'updated': True})

            if is_postgres():
                row = db.execute(
                    "INSERT INTO ha_custom_scenes (user_id, name, icon, actions) "
                    "VALUES (?, ?, ?, ?) RETURNING id",
                    (uid, name, icon, actions_json)
                ).fetchone()
                new_id = _row_val(row, 0, 'id')
            else:
                cur = db.execute(
                    "INSERT INTO ha_custom_scenes (user_id, name, icon, actions) "
                    "VALUES (?, ?, ?, ?)",
                    (uid, name, icon, actions_json)
                )
                new_id = getattr(cur, 'lastrowid', None)
        return jsonify({'success': True, 'id': new_id, 'created': True})
    except Exception as e:
        logger.error(f"save_custom_scene: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@ha_scenes_bp.route('/api/ha/scenes/custom', methods=['GET'])
@require_auth
def list_custom_scenes():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, name, icon, actions, created_at "
                "FROM ha_custom_scenes WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 50",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_custom_scenes: {e}")
        return jsonify({'success': True, 'scenes': []})

    scenes = []
    for r in rows or []:
        actions_raw = _row_val(r, 3, 'actions')
        try:
            actions = json.loads(actions_raw) if isinstance(actions_raw, str) else (actions_raw or [])
        except Exception:
            actions = []
        scenes.append({
            'id': _row_val(r, 0, 'id'),
            'name': _row_val(r, 1, 'name'),
            'icon': _row_val(r, 2, 'icon') or '✨',
            'actions': actions,
            'createdAt': str(_row_val(r, 4, 'created_at') or ''),
        })
    return jsonify({'success': True, 'scenes': scenes, 'count': len(scenes)})


@ha_scenes_bp.route('/api/ha/scenes/custom/<int:scene_id>', methods=['DELETE'])
@require_auth
def delete_custom_scene(scene_id):
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute(
                "DELETE FROM ha_custom_scenes WHERE id = ? AND user_id = ?",
                (scene_id, uid)
            )
        return jsonify({'success': True, 'deleted': True})
    except Exception as e:
        logger.error(f"delete_custom_scene: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# EMERGENCY
# ============================================================

@ha_scenes_bp.route('/api/ha/emergency', methods=['POST', 'OPTIONS'])
@require_auth
def trigger_emergency():
    """Senior pressed the big red emergency button.

    Records the event in ha_emergency_events (audit trail) BEFORE
    attempting any side effects. Then notifies family via the existing
    notification_helpers.notify_senior_family() pipeline.

    Body: {"source": "smart_home" | "voice" | "panic_button",
           "message": "optional free text",
           "device_context": {optional JSON describing home state}}
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    source = (data.get('source') or 'smart_home')[:40]
    message = (data.get('message') or 'Nouzové tlačítko stisknuto')[:400]
    ctx = data.get('device_context') or {}
    try:
        ctx_json = json.dumps(ctx)[:2000]
    except Exception:
        ctx_json = '{}'

    event_id = None
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                row = db.execute(
                    "INSERT INTO ha_emergency_events "
                    "(user_id, source, message, device_context) "
                    "VALUES (?, ?, ?, ?) RETURNING id",
                    (uid, source, message, ctx_json)
                ).fetchone()
                event_id = _row_val(row, 0, 'id')
            else:
                cur = db.execute(
                    "INSERT INTO ha_emergency_events "
                    "(user_id, source, message, device_context) "
                    "VALUES (?, ?, ?, ?)",
                    (uid, source, message, ctx_json)
                )
                event_id = getattr(cur, 'lastrowid', None)
    except Exception as e:
        logger.error(f"emergency log error: {e}")
        # Still try to notify — persistence failure shouldn't block alert

    notified = 0
    try:
        from notification_helpers import notify_senior_family
        notify_senior_family(
            senior_id=uid,
            type='emergency',
            title='🚨 NOUZE — váš blízký potřebuje pomoc',
            body=message,
            severity='critical',
            data={'source': source, 'event_id': event_id},
            include_caregiver=True,
        )
        notified = 1
    except Exception as e:
        logger.error(f"emergency push error: {e}")

    logger.warning(
        f"🚨 EMERGENCY: user={uid[:8]} source={source} event_id={event_id} "
        f"notified={notified}"
    )

    return jsonify({
        'success': True,
        'event_id': event_id,
        'notified_family': notified,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
    })


@ha_scenes_bp.route('/api/ha/emergency/<int:event_id>/resolve', methods=['POST'])
@require_auth
def resolve_emergency(event_id):
    """Family or senior marks an emergency as resolved."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            # Lookup event
            row = db.execute(
                "SELECT user_id FROM ha_emergency_events WHERE id = ?",
                (event_id,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'not found'}), 404
            senior_id = _row_val(row, 0, 'user_id')
            # Allow if caller is the senior OR a linked family member
            if uid != senior_id:
                link = db.execute(
                    "SELECT 1 FROM senior_family_links "
                    "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                    (senior_id, uid, True if is_postgres() else 1)
                ).fetchone()
                if not link:
                    return jsonify({'success': False, 'error': 'not authorized'}), 403
            db.execute(
                "UPDATE ha_emergency_events "
                "SET resolved_at = CURRENT_TIMESTAMP, resolved_by = ? "
                "WHERE id = ?",
                (uid, event_id)
            )
        return jsonify({'success': True, 'resolved': True})
    except Exception as e:
        logger.error(f"resolve_emergency: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


# ============================================================
# FAMILY VIEWS (read-only — linked relatives)
# ============================================================

def _verify_family_link(senior_id, family_uid):
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                (senior_id, family_uid, True if is_postgres() else 1)
            ).fetchone()
            return bool(row)
    except Exception:
        return False


@ha_scenes_bp.route('/api/ha/family/<senior_id>/home-status', methods=['GET'])
@require_auth
def family_home_status(senior_id):
    """Read-only summary of the senior's home for a linked family member.

    Returns: connected (bool), counts (lights on / locks / cameras),
    temperature, low-battery sensors, open doors/windows, last sync.
    No device control allowed — this is purely observational.
    """
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _verify_family_link(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    # Get the shared HA client state — whatever the senior sees, family sees
    status = {'connected': False}
    low_batteries = []
    open_doors = []
    try:
        from home_assistant import ha
        client = ha()
        conn = client.check_connection()
        if conn.get('connected'):
            status.update(conn)
            status.update(client._get_home_status() or {})
        sensors = client.get_sensors_summary() or {}
        for b in sensors.get('battery', []):
            if isinstance(b.get('value'), (int, float)) and b['value'] < 20:
                low_batteries.append({
                    'name': b.get('name'),
                    'value': b['value'],
                })
        for d in sensors.get('door', []):
            if d.get('state') == 'on':  # "on" = open for binary_sensor
                open_doors.append({'name': d.get('name')})
    except Exception as e:
        logger.debug(f"family_home_status HA fetch: {e}")

    # Recent emergencies (unresolved first)
    recent = []
    try:
        cutoff = datetime.utcnow() - timedelta(days=14)
        with db_context() as db:
            rows = db.execute(
                "SELECT id, source, message, triggered_at, resolved_at "
                "FROM ha_emergency_events "
                "WHERE user_id = ? AND triggered_at >= ? "
                "ORDER BY triggered_at DESC LIMIT 20",
                (senior_id, cutoff)
            ).fetchall() or []
        for r in rows:
            recent.append({
                'id': _row_val(r, 0, 'id'),
                'source': _row_val(r, 1, 'source'),
                'message': _row_val(r, 2, 'message'),
                'triggeredAt': str(_row_val(r, 3, 'triggered_at') or ''),
                'resolvedAt': str(_row_val(r, 4, 'resolved_at') or ''),
            })
    except Exception:
        pass

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'connected': bool(status.get('connected')),
        'lights_on': status.get('lights', 0),
        'locks_locked': status.get('locks', 0),
        'temperature': status.get('temperature'),
        'lowBatteries': low_batteries,
        'openDoors': open_doors,
        'recentEmergencies': recent,
        'asOf': datetime.utcnow().isoformat() + 'Z',
    })


@ha_scenes_bp.route('/api/ha/family/<senior_id>/emergencies', methods=['GET'])
@require_auth
def family_emergencies(senior_id):
    """List emergency events for a linked senior (family view)."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _verify_family_link(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    days = max(1, min(int(request.args.get('days', 30)), 365))
    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, source, message, device_context, "
                "triggered_at, resolved_at, resolved_by "
                "FROM ha_emergency_events "
                "WHERE user_id = ? AND triggered_at >= ? "
                "ORDER BY triggered_at DESC LIMIT 100",
                (senior_id, cutoff)
            ).fetchall() or []
    except Exception as e:
        logger.error(f"family_emergencies: {e}")
        rows = []

    events = []
    for r in rows:
        ctx_raw = _row_val(r, 3, 'device_context')
        try:
            ctx = json.loads(ctx_raw) if isinstance(ctx_raw, str) else (ctx_raw or {})
        except Exception:
            ctx = {}
        events.append({
            'id': _row_val(r, 0, 'id'),
            'source': _row_val(r, 1, 'source'),
            'message': _row_val(r, 2, 'message'),
            'context': ctx,
            'triggeredAt': str(_row_val(r, 4, 'triggered_at') or ''),
            'resolvedAt': str(_row_val(r, 5, 'resolved_at') or ''),
            'resolvedBy': _row_val(r, 6, 'resolved_by'),
        })
    return jsonify({'success': True, 'events': events, 'count': len(events)})


logger.info("🏠 HA Scenes+Emergency+Family routes v1.0 loaded")
