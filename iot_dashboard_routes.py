"""
IoT Dashboard & Caregiver Routes v1.0
======================================
Extracted from iot_bridge_routes.py for modularity.

Endpoints:
  GET  /api/iot-bridge/dashboard            — Caregiver overview (all rooms)
  POST /api/iot-bridge/alert-rules          — Create/update alert rule
  GET  /api/iot-bridge/alert-rules          — List alert rules
  GET  /api/iot-bridge/alerts               — List triggered alerts
  POST /api/iot-bridge/alerts/<id>/ack      — Acknowledge alert
  GET  /api/iot-bridge/health               — Health check
  GET  /api/iot-bridge/caregivers           — List caregivers
  POST /api/iot-bridge/caregivers           — Assign caregiver to room
  PUT/DELETE /api/iot-bridge/caregivers/<id> — Update/deactivate
  POST /api/iot-bridge/caregivers/test-sms  — Test SMS
"""

import os
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from utils import now_iso
from iot_helpers import _get_db, _ph, IOT_GATEWAY_TOKEN

logger = logging.getLogger(__name__)

iot_dashboard_bp = Blueprint('iot_dashboard', __name__, url_prefix='/api/iot-bridge')


# ============================================
# DASHBOARD (Caregiver view)
# ============================================

@iot_dashboard_bp.route('/dashboard', methods=['GET'])
def dashboard():
    """Caregiver dashboard — overview of all rooms with latest sensor values and alerts."""
    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        rooms_raw = db.execute('''
            SELECT DISTINCT room_id, user_id FROM iot_devices WHERE status = 'active'
        ''').fetchall()

        rooms = []
        for room_row in rooms_raw:
            room_id = room_row['room_id']

            latest_sql = f'''
                SELECT DISTINCT ON (sensor_type) sensor_type, value, unit, recorded_at, device_id
                FROM iot_sensor_data
                WHERE room_id = {ph}
                ORDER BY sensor_type, recorded_at DESC
            ''' if is_pg else f'''
                SELECT sensor_type, value, unit, recorded_at, device_id
                FROM iot_sensor_data
                WHERE room_id = {ph}
                AND id IN (
                    SELECT MAX(id) FROM iot_sensor_data
                    WHERE room_id = {ph}
                    GROUP BY sensor_type
                )
            '''

            params = (room_id,) if is_pg else (room_id, room_id)
            latest_rows = db.execute(latest_sql, params).fetchall()

            sensors = {}
            for sr in latest_rows:
                sensors[sr['sensor_type']] = {
                    'value': sr['value'],
                    'unit': sr['unit'],
                    'recorded_at': str(sr['recorded_at']),
                    'device_id': sr['device_id']
                }

            alerts_rows = db.execute(f'''
                SELECT id, severity, message, created_at
                FROM iot_alerts
                WHERE room_id = {ph} AND acknowledged_at IS NULL
                ORDER BY created_at DESC LIMIT 5
            ''', (room_id,)).fetchall()

            alerts = [{
                'id': a['id'],
                'severity': a['severity'],
                'message': a['message'],
                'created_at': str(a['created_at'])
            } for a in alerts_rows]

            dev_count = db.execute(f'''
                SELECT COUNT(*) as cnt FROM iot_devices
                WHERE room_id = {ph} AND status = 'active'
            ''', (room_id,)).fetchone()

            rooms.append({
                'room_id': room_id,
                'user_id': room_row['user_id'],
                'sensors': sensors,
                'active_alerts': alerts,
                'device_count': dev_count['cnt'] if dev_count else 0,
                'status': 'alert' if alerts else 'ok'
            })

        return jsonify({
            'rooms': rooms,
            'room_count': len(rooms),
            'timestamp': now_iso()
        }), 200

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# ALERT RULES
# ============================================

@iot_dashboard_bp.route('/alert-rules', methods=['POST', 'OPTIONS'])
def create_alert_rule():
    """Create or update an alert rule."""
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['room_id', 'sensor_type', 'condition', 'threshold']
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({'error': f'Missing: {", ".join(missing)}'}), 400

    if data['condition'] not in ('above', 'below', 'equals'):
        return jsonify({'error': 'condition must be above|below|equals'}), 400

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        db.execute(f'''
            INSERT INTO iot_alert_rules (room_id, sensor_type, condition, threshold, severity, notify_channels, cooldown_minutes)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        ''', (
            data['room_id'], data['sensor_type'], data['condition'],
            float(data['threshold']),
            data.get('severity', 'warning'),
            data.get('notify_channels', 'push'),
            int(data.get('cooldown_minutes', 15))
        ))
        db.commit()

        return jsonify({
            'success': True,
            'message': f"Alert rule created: {data['sensor_type']} {data['condition']} {data['threshold']} in {data['room_id']}",
            'timestamp': now_iso()
        }), 201

    except Exception as e:
        logger.error(f"Alert rule error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_dashboard_bp.route('/alert-rules', methods=['GET'])
def list_alert_rules():
    """List all alert rules, optionally filtered by room_id."""
    room_id = request.args.get('room_id')
    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        if room_id:
            rows = db.execute(f'''
                SELECT id, room_id, sensor_type, condition, threshold, severity, notify_channels, cooldown_minutes, enabled
                FROM iot_alert_rules WHERE room_id = {ph} ORDER BY sensor_type
            ''', (room_id,)).fetchall()
        else:
            rows = db.execute('''
                SELECT id, room_id, sensor_type, condition, threshold, severity, notify_channels, cooldown_minutes, enabled
                FROM iot_alert_rules ORDER BY room_id, sensor_type
            ''').fetchall()

        rules = [{
            'id': r['id'],
            'room_id': r['room_id'],
            'sensor_type': r['sensor_type'],
            'condition': r['condition'],
            'threshold': r['threshold'],
            'severity': r['severity'],
            'notify_channels': r['notify_channels'],
            'cooldown_minutes': r['cooldown_minutes'],
            'enabled': bool(r['enabled'])
        } for r in rows]

        return jsonify({'rules': rules, 'count': len(rules)}), 200

    except Exception as e:
        logger.error(f"Alert rules list error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# ALERTS
# ============================================

@iot_dashboard_bp.route('/alerts', methods=['GET'])
def list_alerts():
    """List triggered alerts with filters."""
    room_id = request.args.get('room_id')
    severity = request.args.get('severity')
    unack = request.args.get('unacknowledged', 'false').lower() == 'true'
    hours = min(int(request.args.get('hours', 24)), 168)
    limit = min(int(request.args.get('limit', 50)), 200)

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        since = datetime.utcnow() - timedelta(hours=hours)
        conditions = [f"created_at > {ph}"]
        params = [since]

        if room_id:
            conditions.append(f"room_id = {ph}")
            params.append(room_id)
        if severity:
            conditions.append(f"severity = {ph}")
            params.append(severity)
        if unack:
            conditions.append("acknowledged_at IS NULL")

        where = " AND ".join(conditions)
        rows = db.execute(f'''
            SELECT id, rule_id, room_id, user_id, sensor_type, value, threshold, severity,
                   message, acknowledged_at, acknowledged_by, created_at
            FROM iot_alerts
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT {ph}
        ''', (*params, limit)).fetchall()

        alerts = [{
            'id': a['id'],
            'rule_id': a['rule_id'],
            'room_id': a['room_id'],
            'user_id': a['user_id'],
            'sensor_type': a['sensor_type'],
            'value': a['value'],
            'threshold': a['threshold'],
            'severity': a['severity'],
            'message': a['message'],
            'acknowledged_at': str(a['acknowledged_at']) if a['acknowledged_at'] else None,
            'acknowledged_by': a['acknowledged_by'],
            'created_at': str(a['created_at'])
        } for a in rows]

        return jsonify({'alerts': alerts, 'count': len(alerts)}), 200

    except Exception as e:
        logger.error(f"Alert list error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_dashboard_bp.route('/alerts/<int:alert_id>/ack', methods=['POST', 'OPTIONS'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert."""
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    ack_by = data.get('acknowledged_by', 'caregiver')

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        db.execute(f'''
            UPDATE iot_alerts
            SET acknowledged_at = {ph}, acknowledged_by = {ph}
            WHERE id = {ph}
        ''', (datetime.utcnow(), ack_by, alert_id))
        db.commit()

        return jsonify({
            'success': True,
            'alert_id': alert_id,
            'acknowledged_at': now_iso()
        }), 200

    except Exception as e:
        logger.error(f"Alert ack error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# HEALTH CHECK
# ============================================

@iot_dashboard_bp.route('/health', methods=['GET'])
def iot_health():
    """IoT Bridge health check."""
    db, is_pg = _get_db()
    try:
        dev_count = db.execute('SELECT COUNT(*) as cnt FROM iot_devices').fetchone()
        since = datetime.utcnow() - timedelta(hours=1)
        ph = _ph(is_pg)
        data_count = db.execute(
            f'SELECT COUNT(*) as cnt FROM iot_sensor_data WHERE recorded_at > {ph}',
            (since,)
        ).fetchone()
        alert_count = db.execute(
            'SELECT COUNT(*) as cnt FROM iot_alerts WHERE acknowledged_at IS NULL'
        ).fetchone()

        return jsonify({
            'status': 'ok',
            'gateway_token_configured': bool(IOT_GATEWAY_TOKEN),
            'devices_registered': dev_count['cnt'] if dev_count else 0,
            'readings_last_hour': data_count['cnt'] if data_count else 0,
            'unacknowledged_alerts': alert_count['cnt'] if alert_count else 0,
            'version': '5.2',
            'timestamp': now_iso()
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# CAREGIVER MANAGEMENT
# ============================================

@iot_dashboard_bp.route('/caregivers', methods=['GET'])
def list_caregivers():
    """List all caregivers, optionally filtered by room_id."""
    room_id = request.args.get('room_id')
    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        if room_id:
            rows = db.execute(f'''
                SELECT id, room_id, name, phone, email, role, notify_sms, notify_push, active, created_at
                FROM iot_caregivers WHERE room_id = {ph} ORDER BY name
            ''', (room_id,)).fetchall()
        else:
            rows = db.execute('''
                SELECT id, room_id, name, phone, email, role, notify_sms, notify_push, active, created_at
                FROM iot_caregivers ORDER BY room_id, name
            ''').fetchall()

        caregivers = [{
            'id': r['id'],
            'room_id': r['room_id'],
            'name': r['name'],
            'phone': r['phone'],
            'email': r.get('email'),
            'role': r['role'],
            'notify_sms': bool(r['notify_sms']),
            'notify_push': bool(r['notify_push']),
            'active': bool(r['active'])
        } for r in rows]

        return jsonify({'caregivers': caregivers, 'count': len(caregivers)}), 200
    except Exception as e:
        logger.error(f"List caregivers error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_dashboard_bp.route('/caregivers', methods=['POST', 'OPTIONS'])
def add_caregiver():
    """Assign a caregiver to a room."""
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    if not data or not data.get('room_id') or not data.get('name') or not data.get('phone'):
        return jsonify({'error': 'room_id, name, phone required'}), 400

    phone = data['phone'].strip()
    if not phone.startswith('+'):
        phone = '+420' + phone

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        existing = db.execute(f'''
            SELECT id FROM iot_caregivers WHERE room_id = {ph} AND phone = {ph}
        ''', (data['room_id'], phone)).fetchone()

        if existing:
            db.execute(f'''
                UPDATE iot_caregivers
                SET name = {ph}, email = {ph}, role = {ph}, active = {ph}, updated_at = {ph}
                WHERE id = {ph}
            ''', (
                data['name'], data.get('email'), data.get('role', 'caregiver'),
                True if is_pg else 1, datetime.utcnow(), existing['id']
            ))
            db.commit()
            return jsonify({'success': True, 'caregiver_id': existing['id'], 'action': 'updated'}), 200
        else:
            if is_pg:
                row = db.execute(f'''
                    INSERT INTO iot_caregivers (room_id, name, phone, email, role)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                    RETURNING id
                ''', (data['room_id'], data['name'], phone, data.get('email'), data.get('role', 'caregiver'))).fetchone()
                db.commit()
                cg_id = row['id'] if row else None
            else:
                db.execute(f'''
                    INSERT INTO iot_caregivers (room_id, name, phone, email, role)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph})
                ''', (data['room_id'], data['name'], phone, data.get('email'), data.get('role', 'caregiver')))
                db.commit()
                cg_id = db.execute('SELECT last_insert_rowid() as id').fetchone()['id']

            logger.info(f"👤 Caregiver added: {data['name']} → {data['room_id']}")
            return jsonify({'success': True, 'caregiver_id': cg_id, 'action': 'created'}), 201

    except Exception as e:
        logger.error(f"Add caregiver error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_dashboard_bp.route('/caregivers/<int:caregiver_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
def manage_caregiver(caregiver_id):
    """Update or deactivate a caregiver."""
    if request.method == 'OPTIONS':
        return '', 204

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        if request.method == 'DELETE':
            db.execute(f'UPDATE iot_caregivers SET active = {ph}, updated_at = {ph} WHERE id = {ph}',
                       (False if is_pg else 0, datetime.utcnow(), caregiver_id))
            db.commit()
            return jsonify({'success': True, 'action': 'deactivated'}), 200

        data = request.get_json() or {}
        updates = []
        params = []
        for field in ['name', 'phone', 'email', 'role']:
            if field in data:
                updates.append(f"{field} = {ph}")
                params.append(data[field])
        for field in ['notify_sms', 'notify_push', 'active']:
            if field in data:
                updates.append(f"{field} = {ph}")
                params.append(data[field] if is_pg else (1 if data[field] else 0))

        if not updates:
            return jsonify({'error': 'No fields to update'}), 400

        updates.append(f"updated_at = {ph}")
        params.append(datetime.utcnow())
        params.append(caregiver_id)

        db.execute(f"UPDATE iot_caregivers SET {', '.join(updates)} WHERE id = {ph}", params)
        db.commit()

        return jsonify({'success': True, 'action': 'updated'}), 200

    except Exception as e:
        logger.error(f"Manage caregiver error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_dashboard_bp.route('/caregivers/test-sms', methods=['POST', 'OPTIONS'])
def test_sms():
    """Send a test SMS to verify Twilio configuration."""
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json() or {}
    phone = data.get('phone')

    if not phone:
        try:
            db, is_pg = _get_db()
            ph = _ph(is_pg)
            row = db.execute(f'''
                SELECT phone FROM iot_caregivers WHERE active = {ph} AND notify_sms = {ph} LIMIT 1
            ''', (True if is_pg else 1, True if is_pg else 1)).fetchone()
            db.close()
            if row:
                phone = row['phone']
        except Exception:
            pass

    if not phone:
        fallback = os.environ.get('CAREGIVER_PHONE_NUMBER')
        if fallback:
            phone = fallback
        else:
            return jsonify({'error': 'No phone number provided and no caregivers registered'}), 400

    try:
        from twilio.rest import Client
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')

        if not all([account_sid, auth_token, from_number]):
            return jsonify({'error': 'Twilio not configured (missing env vars)'}), 503

        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=f"✅ Radim Care — Testovací SMS\nČas: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\nSystém funguje správně.",
            from_=from_number,
            to=phone
        )

        logger.info(f"📱 Test SMS sent: {msg.sid}")
        return jsonify({
            'success': True,
            'message_sid': msg.sid,
            'to': phone[-4:].rjust(len(phone), '*'),
            'status': msg.status
        }), 200

    except ImportError:
        return jsonify({'error': 'Twilio SDK not installed'}), 503
    except Exception as e:
        logger.error(f"Test SMS error: {e}")
        return jsonify({'error': str(e)}), 500


logger.info("✅ IoT Dashboard Blueprint loaded — dashboard/alerts/caregivers")
