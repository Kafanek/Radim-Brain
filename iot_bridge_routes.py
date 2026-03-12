"""
IoT Bridge Routes v5.0
======================
REST API for Zigbee sensor data ingestion from Raspberry Pi gateways.

Architecture:
  Zigbee 3.0 sensors → Raspberry Pi 5 (Home Assistant) → MQTT →
  HA automation → HTTP POST → This API → PostgreSQL → Alert engine

Endpoints:
  POST /api/iot/data           — Ingest sensor reading(s)
  POST /api/iot/data/batch     — Batch ingest (up to 100 readings)
  GET  /api/iot/data/<room_id> — Get recent readings for room
  POST /api/iot/devices        — Register/update device
  GET  /api/iot/devices        — List all devices
  GET  /api/iot/dashboard      — Caregiver overview (all rooms)
  POST /api/iot/alert-rules    — Create/update alert rule
  GET  /api/iot/alert-rules    — List alert rules
  GET  /api/iot/alerts         — List triggered alerts
  POST /api/iot/alerts/<id>/ack — Acknowledge alert

Security:
  - Gateway auth via X-IoT-Token header (shared secret)
  - Dashboard/rules via @optional_auth (JWT)
  - Rate limited: 120 req/60s for data ingestion

@author RadimCare Team
@version 5.0
"""

import json
import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, g

logger = logging.getLogger(__name__)

iot_bridge_bp = Blueprint('iot_bridge', __name__, url_prefix='/api/iot-bridge')

# ============================================
# AUTH: Gateway token validation
# ============================================

IOT_GATEWAY_TOKEN = os.environ.get('IOT_GATEWAY_TOKEN', '')


def require_iot_auth(f):
    """Validate gateway token from X-IoT-Token header or query param."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-IoT-Token') or request.args.get('token')
        if not IOT_GATEWAY_TOKEN:
            # No token configured — allow (development mode)
            logger.warning("⚠️ IoT: No IOT_GATEWAY_TOKEN configured — accepting all requests")
            return f(*args, **kwargs)
        if token != IOT_GATEWAY_TOKEN:
            return jsonify({'error': 'Invalid IoT gateway token'}), 401
        return f(*args, **kwargs)
    return decorated


# ============================================
# HELPERS
# ============================================

def _get_db():
    """Get database connection."""
    from database import get_connection, is_postgres
    return get_connection(), is_postgres()


def _ph(is_pg):
    """Placeholder: %s for PostgreSQL, ? for SQLite."""
    return '%s' if is_pg else '?'


def _now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _parse_timestamp(ts_str):
    """Parse ISO timestamp or return now."""
    if not ts_str:
        return datetime.utcnow()
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str.replace('+00:00', ''))
    except (ValueError, TypeError):
        return datetime.utcnow()


# ============================================
# ALERT ENGINE
# ============================================

# In-memory cooldown tracker (rule_id → last_alert_time)
_alert_cooldowns = {}


def _check_alert_rules(db, is_pg, room_id, sensor_type, value):
    """Check if value triggers any alert rules. Returns list of triggered alerts."""
    ph = _ph(is_pg)
    triggered = []

    try:
        rows = db.execute(f'''
            SELECT id, condition, threshold, severity, notify_channels, cooldown_minutes
            FROM iot_alert_rules
            WHERE room_id = {ph} AND sensor_type = {ph} AND enabled = {ph}
        ''', (room_id, sensor_type, True if is_pg else 1)).fetchall()

        for rule in rows:
            rule_id = rule['id']
            condition = rule['condition']
            threshold = rule['threshold']

            # Check condition
            match = False
            if condition == 'above' and value > threshold:
                match = True
            elif condition == 'below' and value < threshold:
                match = True
            elif condition == 'equals' and abs(value - threshold) < 0.01:
                match = True

            if not match:
                continue

            # Check cooldown
            cooldown = rule['cooldown_minutes'] or 15
            last_alert = _alert_cooldowns.get(rule_id)
            if last_alert and (datetime.utcnow() - last_alert).total_seconds() < cooldown * 60:
                continue

            # Create alert
            severity = rule['severity'] or 'warning'
            message = f"[{severity.upper()}] {sensor_type} v místnosti {room_id}: " \
                      f"hodnota {value} {'>' if condition == 'above' else '<'} {threshold}"

            db.execute(f'''
                INSERT INTO iot_alerts (rule_id, room_id, sensor_type, value, threshold, severity, message)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            ''', (rule_id, room_id, sensor_type, value, threshold, severity, message))

            _alert_cooldowns[rule_id] = datetime.utcnow()
            triggered.append({
                'rule_id': rule_id,
                'severity': severity,
                'message': message,
                'channels': rule['notify_channels'] or 'push'
            })

            logger.warning(f"🚨 IoT Alert: {message}")

    except Exception as e:
        logger.error(f"Alert check error: {e}")

    return triggered


def _send_alert_notifications(alerts, room_id, user_id=None):
    """Send notifications for triggered alerts (push, SMS)."""
    for alert in alerts:
        channels = alert.get('channels', 'push').split(',')

        # Push notification
        if 'push' in channels and user_id:
            try:
                from app import send_push_notification
                send_push_notification(
                    user_id,
                    f"⚠️ Alert: {alert['severity']}",
                    alert['message'],
                    {'type': 'iot_alert', 'room_id': room_id}
                )
            except Exception as e:
                logger.warning(f"Push notification error: {e}")

        # SMS via Twilio
        if 'sms' in channels:
            try:
                _send_sms_alert(alert, room_id)
            except Exception as e:
                logger.warning(f"SMS alert error: {e}")


def _send_sms_alert(alert, room_id):
    """Send SMS alert to caregiver via Twilio."""
    try:
        from twilio.rest import Client
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')
        caregiver_number = os.environ.get('CAREGIVER_PHONE_NUMBER')

        if not all([account_sid, auth_token, from_number, caregiver_number]):
            logger.warning("SMS alert: Twilio not configured")
            return

        client = Client(account_sid, auth_token)
        body = f"🚨 Radim Care Alert\n" \
               f"Místnost: {room_id}\n" \
               f"Závažnost: {alert['severity']}\n" \
               f"{alert['message']}"

        client.messages.create(
            body=body,
            from_=from_number,
            to=caregiver_number
        )
        logger.info(f"📱 SMS alert sent to {caregiver_number[-4:]}")
    except ImportError:
        logger.warning("Twilio SDK not available for SMS alerts")
    except Exception as e:
        logger.error(f"SMS send error: {e}")


# ============================================
# ENDPOINTS: Data Ingestion
# ============================================

@iot_bridge_bp.route('/data', methods=['POST', 'OPTIONS'])
@require_iot_auth
def ingest_data():
    """
    Ingest single sensor reading from gateway.

    Body: {
        "device_id": "zigbee_motion_01",
        "room_id": "room_101",
        "sensor_type": "motion",         # motion|temperature|humidity|door|sos|fall|light
        "value": 1.0,
        "unit": "boolean",               # optional
        "metadata": {"battery": 85},      # optional
        "recorded_at": "2026-03-12T..."   # optional, defaults to now
    }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['device_id', 'room_id', 'sensor_type', 'value']
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        recorded_at = _parse_timestamp(data.get('recorded_at'))
        metadata = json.dumps(data.get('metadata', {}))

        # Insert reading
        db.execute(f'''
            INSERT INTO iot_sensor_data (device_id, room_id, sensor_type, value, unit, metadata, recorded_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        ''', (
            data['device_id'], data['room_id'], data['sensor_type'],
            float(data['value']), data.get('unit', ''),
            metadata, recorded_at
        ))

        # Update device last_seen
        db.execute(f'''
            UPDATE iot_devices SET last_seen = {ph} WHERE device_id = {ph}
        ''', (datetime.utcnow(), data['device_id']))

        # Check alert rules
        alerts = _check_alert_rules(db, is_pg, data['room_id'], data['sensor_type'], float(data['value']))

        db.commit()

        # Send notifications outside transaction
        if alerts:
            # Find user_id for this room
            row = db.execute(f'SELECT user_id FROM iot_devices WHERE room_id = {ph} LIMIT 1',
                             (data['room_id'],)).fetchone()
            user_id = row['user_id'] if row else None
            _send_alert_notifications(alerts, data['room_id'], user_id)

        return jsonify({
            'success': True,
            'alerts_triggered': len(alerts),
            'alerts': [a['message'] for a in alerts] if alerts else [],
            'timestamp': _now_iso()
        }), 201

    except Exception as e:
        logger.error(f"IoT ingest error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_bridge_bp.route('/data/batch', methods=['POST', 'OPTIONS'])
@require_iot_auth
def ingest_batch():
    """
    Batch ingest up to 100 sensor readings.

    Body: { "readings": [ {device_id, room_id, sensor_type, value, ...}, ... ] }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    readings = data.get('readings', []) if data else []

    if not readings:
        return jsonify({'error': 'No readings provided'}), 400
    if len(readings) > 100:
        return jsonify({'error': 'Max 100 readings per batch'}), 400

    db, is_pg = _get_db()
    ph = _ph(is_pg)
    inserted = 0
    errors = []
    all_alerts = []

    try:
        for i, r in enumerate(readings):
            try:
                required = ['device_id', 'room_id', 'sensor_type', 'value']
                missing = [k for k in required if k not in r]
                if missing:
                    errors.append(f"Reading {i}: missing {', '.join(missing)}")
                    continue

                recorded_at = _parse_timestamp(r.get('recorded_at'))
                metadata = json.dumps(r.get('metadata', {}))

                db.execute(f'''
                    INSERT INTO iot_sensor_data (device_id, room_id, sensor_type, value, unit, metadata, recorded_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ''', (
                    r['device_id'], r['room_id'], r['sensor_type'],
                    float(r['value']), r.get('unit', ''),
                    metadata, recorded_at
                ))

                # Check alerts for each reading
                alerts = _check_alert_rules(db, is_pg, r['room_id'], r['sensor_type'], float(r['value']))
                all_alerts.extend(alerts)
                inserted += 1

            except Exception as e:
                errors.append(f"Reading {i}: {str(e)}")

        db.commit()

        return jsonify({
            'success': True,
            'inserted': inserted,
            'errors': errors[:10],  # max 10 error messages
            'alerts_triggered': len(all_alerts),
            'timestamp': _now_iso()
        }), 201

    except Exception as e:
        logger.error(f"IoT batch error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# ENDPOINTS: Data Query
# ============================================

@iot_bridge_bp.route('/data/<room_id>', methods=['GET'])
def get_room_data(room_id):
    """
    Get recent sensor data for a room.

    Query params:
      - sensor_type: filter by type (optional)
      - hours: lookback hours (default 24, max 168)
      - limit: max rows (default 100, max 1000)
    """
    sensor_type = request.args.get('sensor_type')
    hours = min(int(request.args.get('hours', 24)), 168)
    limit = min(int(request.args.get('limit', 100)), 1000)

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        since = datetime.utcnow() - timedelta(hours=hours)

        if sensor_type:
            rows = db.execute(f'''
                SELECT device_id, sensor_type, value, unit, metadata, recorded_at
                FROM iot_sensor_data
                WHERE room_id = {ph} AND sensor_type = {ph} AND recorded_at > {ph}
                ORDER BY recorded_at DESC
                LIMIT {ph}
            ''', (room_id, sensor_type, since, limit)).fetchall()
        else:
            rows = db.execute(f'''
                SELECT device_id, sensor_type, value, unit, metadata, recorded_at
                FROM iot_sensor_data
                WHERE room_id = {ph} AND recorded_at > {ph}
                ORDER BY recorded_at DESC
                LIMIT {ph}
            ''', (room_id, since, limit)).fetchall()

        readings = []
        for row in rows:
            meta = row['metadata']
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            readings.append({
                'device_id': row['device_id'],
                'sensor_type': row['sensor_type'],
                'value': row['value'],
                'unit': row['unit'],
                'metadata': meta,
                'recorded_at': str(row['recorded_at'])
            })

        return jsonify({
            'room_id': room_id,
            'readings': readings,
            'count': len(readings),
            'hours': hours,
            'timestamp': _now_iso()
        }), 200

    except Exception as e:
        logger.error(f"IoT query error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# ENDPOINTS: Device Management
# ============================================

@iot_bridge_bp.route('/devices', methods=['POST', 'OPTIONS'])
@require_iot_auth
def register_device():
    """
    Register or update a sensor device.

    Body: {
        "device_id": "zigbee_motion_01",
        "room_id": "room_101",
        "user_id": "senior_001",
        "device_type": "motion_sensor",
        "name": "Pohybový senzor - Ložnice",
        "model": "Aqara RTCGQ11LM",
        "firmware": "1.2.3",
        "config": {"sensitivity": "high"}
    }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    if not data or not data.get('device_id') or not data.get('room_id') or not data.get('device_type'):
        return jsonify({'error': 'device_id, room_id, device_type required'}), 400

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        config = json.dumps(data.get('config', {}))
        now = datetime.utcnow()

        if is_pg:
            db.execute(f'''
                INSERT INTO iot_devices (device_id, room_id, user_id, device_type, name, model, firmware, config, last_seen)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                ON CONFLICT (device_id) DO UPDATE SET
                    room_id = EXCLUDED.room_id,
                    user_id = EXCLUDED.user_id,
                    device_type = EXCLUDED.device_type,
                    name = EXCLUDED.name,
                    model = EXCLUDED.model,
                    firmware = EXCLUDED.firmware,
                    config = EXCLUDED.config,
                    last_seen = EXCLUDED.last_seen
            ''', (
                data['device_id'], data['room_id'], data.get('user_id'),
                data['device_type'], data.get('name', ''),
                data.get('model', ''), data.get('firmware', ''),
                config, now
            ))
        else:
            db.execute(f'''
                INSERT OR REPLACE INTO iot_devices (device_id, room_id, user_id, device_type, name, model, firmware, config, last_seen)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            ''', (
                data['device_id'], data['room_id'], data.get('user_id'),
                data['device_type'], data.get('name', ''),
                data.get('model', ''), data.get('firmware', ''),
                config, now
            ))

        db.commit()

        return jsonify({
            'success': True,
            'device_id': data['device_id'],
            'message': f"Device {data['device_id']} registered in room {data['room_id']}",
            'timestamp': _now_iso()
        }), 201

    except Exception as e:
        logger.error(f"Device register error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_bridge_bp.route('/devices', methods=['GET'])
def list_devices():
    """List all registered IoT devices, optionally filtered by room_id."""
    room_id = request.args.get('room_id')

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        if room_id:
            rows = db.execute(f'''
                SELECT device_id, room_id, user_id, device_type, name, model, firmware, status, last_seen, config
                FROM iot_devices WHERE room_id = {ph} ORDER BY device_type
            ''', (room_id,)).fetchall()
        else:
            rows = db.execute('''
                SELECT device_id, room_id, user_id, device_type, name, model, firmware, status, last_seen, config
                FROM iot_devices ORDER BY room_id, device_type
            ''').fetchall()

        devices = []
        for row in rows:
            cfg = row['config']
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except (json.JSONDecodeError, TypeError):
                    cfg = {}
            devices.append({
                'device_id': row['device_id'],
                'room_id': row['room_id'],
                'user_id': row['user_id'],
                'device_type': row['device_type'],
                'name': row['name'],
                'model': row['model'],
                'firmware': row['firmware'],
                'status': row['status'],
                'last_seen': str(row['last_seen']) if row['last_seen'] else None,
                'config': cfg
            })

        return jsonify({'devices': devices, 'count': len(devices)}), 200

    except Exception as e:
        logger.error(f"Device list error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================
# ENDPOINTS: Dashboard (Caregiver view)
# ============================================

@iot_bridge_bp.route('/dashboard', methods=['GET'])
def dashboard():
    """
    Caregiver dashboard — overview of all rooms with latest sensor values
    and recent alerts.
    """
    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        # Get all rooms with their devices
        rooms_raw = db.execute('''
            SELECT DISTINCT room_id, user_id FROM iot_devices WHERE status = 'active'
        ''').fetchall()

        rooms = []
        for room_row in rooms_raw:
            room_id = room_row['room_id']

            # Latest reading per sensor type in this room
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

            # Recent unacknowledged alerts
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

            # Device count
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
            'timestamp': _now_iso()
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
# ENDPOINTS: Alert Rules
# ============================================

@iot_bridge_bp.route('/alert-rules', methods=['POST', 'OPTIONS'])
def create_alert_rule():
    """
    Create or update an alert rule.

    Body: {
        "room_id": "room_101",
        "sensor_type": "temperature",
        "condition": "above",          # above|below|equals
        "threshold": 28.0,
        "severity": "warning",         # info|warning|critical
        "notify_channels": "push,sms", # push|sms|push,sms
        "cooldown_minutes": 15
    }
    """
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
            'timestamp': _now_iso()
        }), 201

    except Exception as e:
        logger.error(f"Alert rule error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass


@iot_bridge_bp.route('/alert-rules', methods=['GET'])
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
# ENDPOINTS: Alerts
# ============================================

@iot_bridge_bp.route('/alerts', methods=['GET'])
def list_alerts():
    """
    List triggered alerts.
    Query params:
      - room_id: filter by room
      - severity: filter by severity (info|warning|critical)
      - unacknowledged: if "true", only unacknowledged alerts
      - hours: lookback (default 24)
      - limit: max results (default 50, max 200)
    """
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


@iot_bridge_bp.route('/alerts/<int:alert_id>/ack', methods=['POST', 'OPTIONS'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert (mark as handled by caregiver)."""
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
            'acknowledged_at': _now_iso()
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

@iot_bridge_bp.route('/health', methods=['GET'])
def iot_health():
    """IoT Bridge health check."""
    db, is_pg = _get_db()
    try:
        # Count devices and recent readings
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
            'version': '5.0',
            'timestamp': _now_iso()
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
    finally:
        try:
            db.close()
        except Exception:
            pass
