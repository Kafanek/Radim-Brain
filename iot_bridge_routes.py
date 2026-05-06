"""
IoT Bridge Routes v5.2 (modular)
=================================
REST API for Zigbee sensor data ingestion from Raspberry Pi gateways.

Architecture:
  Zigbee 3.0 sensors → Raspberry Pi 5 (Home Assistant) → MQTT →
  HA automation → HTTP POST → This API → PostgreSQL → Alert engine → SMS/Push

Core endpoints (this file):
  POST /api/iot-bridge/data           — Ingest sensor reading(s)
  POST /api/iot-bridge/data/batch     — Batch ingest (up to 100 readings)
  GET  /api/iot-bridge/data/<room_id> — Get recent readings for room
  POST /api/iot-bridge/devices        — Register/update device
  GET  /api/iot-bridge/devices        — List all devices

Dashboard/caregivers/alerts: see iot_dashboard_routes.py
Shared helpers: see iot_helpers.py

Security:
  - Gateway auth via X-IoT-Token header (shared secret)
  - Rate limited: 120 req/60s for data ingestion
"""

import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from utils import now_iso
from iot_helpers import (
    require_iot_auth, _get_db, _ph, _parse_timestamp,
    _check_alert_rules, _send_alert_notifications,
    IOT_GATEWAY_TOKEN
)

logger = logging.getLogger(__name__)

iot_bridge_bp = Blueprint('iot_bridge', __name__, url_prefix='/api/iot-bridge')


# ============================================
# ENDPOINTS: Data Ingestion
# ============================================

@iot_bridge_bp.route('/data', methods=['POST', 'OPTIONS'])
@require_iot_auth
def ingest_data():
    """Ingest single sensor reading from gateway."""
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

        db.execute(f'''
            INSERT INTO iot_sensor_data (device_id, room_id, sensor_type, value, unit, metadata, recorded_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        ''', (
            data['device_id'], data['room_id'], data['sensor_type'],
            float(data['value']), data.get('unit', ''),
            metadata, recorded_at
        ))

        db.execute(f'''
            UPDATE iot_devices SET last_seen = {ph} WHERE device_id = {ph}
        ''', (datetime.utcnow(), data['device_id']))

        alerts = _check_alert_rules(db, is_pg, data['room_id'], data['sensor_type'], float(data['value']))

        db.commit()

        if alerts:
            row = db.execute(f'SELECT user_id FROM iot_devices WHERE room_id = {ph} LIMIT 1',
                             (data['room_id'],)).fetchone()
            user_id = row['user_id'] if row else None
            _send_alert_notifications(alerts, data['room_id'], user_id)

        return jsonify({
            'success': True,
            'alerts_triggered': len(alerts),
            'alerts': [a['message'] for a in alerts] if alerts else [],
            'timestamp': now_iso()
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
    """Batch ingest up to 100 sensor readings."""
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

                alerts = _check_alert_rules(db, is_pg, r['room_id'], r['sensor_type'], float(r['value']))
                all_alerts.extend(alerts)
                inserted += 1

            except Exception as e:
                errors.append(f"Reading {i}: {str(e)}")

        db.commit()

        return jsonify({
            'success': True,
            'inserted': inserted,
            'errors': errors[:10],
            'alerts_triggered': len(all_alerts),
            'timestamp': now_iso()
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
    """Get recent sensor data for a room."""
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
            'timestamp': now_iso()
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
    """Register or update a sensor device."""
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
            'timestamp': now_iso()
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


@iot_bridge_bp.route('/heartbeat', methods=['POST', 'OPTIONS'])
@require_iot_auth
def gateway_heartbeat():
    """v8.19.108: Gateway heartbeat — mini PC v bytě seniora hlásí, že žije.

    Body: {senior_id, gateway_id?, version?, uptime_s?}
    Zápis: iot_sensor_data sensor_type='gateway_heartbeat' value=1.
    Detektor _detect_gateway_offline hlídá > 5 min stáří → WARNING.
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json(silent=True) or {}
    senior_id = data.get('senior_id') or ''
    gateway_id = data.get('gateway_id') or 'tapo_gateway'
    version = str(data.get('version') or '1.0')
    uptime_s = data.get('uptime_s') or 0

    if not senior_id:
        return jsonify({'error': 'senior_id required'}), 400

    db, is_pg = _get_db()
    ph = _ph(is_pg)

    try:
        meta = json.dumps({'gateway_id': gateway_id, 'version': version,
                           'uptime_s': uptime_s})
        room_id = data.get('room_id') or 'gateway'
        db.execute(f'''
            INSERT INTO iot_sensor_data
                (device_id, room_id, sensor_type, value, unit, metadata, recorded_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        ''', (gateway_id, room_id, 'gateway_heartbeat', 1.0, 'bool',
              meta, datetime.utcnow()))
        db.execute(f'UPDATE iot_devices SET last_seen = {ph} WHERE device_id = {ph}',
                   (datetime.utcnow(), gateway_id))
        db.commit()  # ⚠ _get_db() vrací raw connection — explicit commit MUSÍ
        return jsonify({'success': True,
                        'received_at': datetime.utcnow().isoformat()}), 201
    except Exception as e:
        logger.warning(f"Heartbeat ingest error: {e}")
        try: db.rollback()
        except Exception: pass
        return jsonify({'error': 'ingest_failed'}), 500
    finally:
        try: db.close()
        except Exception: pass


logger.info("✅ IoT Bridge Blueprint loaded — data ingestion + devices + heartbeat")
