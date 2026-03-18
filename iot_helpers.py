"""
IoT Bridge Helpers v1.0
=======================
Shared helpers for IoT Bridge routes:
- Gateway auth decorator
- DB helpers (_get_db, _ph, _parse_timestamp)
- Alert engine (check rules, send notifications, SMS)
- Room helpers (caregivers, display name)

Extracted from iot_bridge_routes.py for modularity.
"""

import os
import logging
from datetime import datetime
from functools import wraps

from flask import request, jsonify

logger = logging.getLogger(__name__)

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
            logger.warning("⚠️ IoT: No IOT_GATEWAY_TOKEN configured — accepting all requests")
            return f(*args, **kwargs)
        if token != IOT_GATEWAY_TOKEN:
            return jsonify({'error': 'Invalid IoT gateway token'}), 401
        return f(*args, **kwargs)
    return decorated


# ============================================
# DB HELPERS
# ============================================

def _get_db():
    """Get database connection."""
    from database import get_connection, is_postgres, db_context
    return get_connection(), is_postgres()


def _ph(is_pg):
    """Placeholder — always ? (PgCursorWrapper converts to %s automatically)."""
    return '?'


def _parse_timestamp(ts_str):
    """Parse ISO timestamp or return now."""
    if not ts_str:
        return datetime.utcnow()
    try:
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

            match = False
            if condition == 'above' and value > threshold:
                match = True
            elif condition == 'below' and value < threshold:
                match = True
            elif condition == 'equals' and abs(value - threshold) < 0.01:
                match = True

            if not match:
                continue

            cooldown = rule['cooldown_minutes'] or 15
            last_alert = _alert_cooldowns.get(rule_id)
            if last_alert and (datetime.utcnow() - last_alert).total_seconds() < cooldown * 60:
                continue

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

        if 'sms' in channels:
            try:
                _send_sms_alert(alert, room_id)
            except Exception as e:
                logger.warning(f"SMS alert error: {e}")


def _send_sms_alert(alert, room_id):
    """Send SMS alert to all caregivers assigned to this room via Twilio."""
    try:
        from twilio.rest import Client
        account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
        auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
        from_number = os.environ.get('TWILIO_PHONE_NUMBER')

        if not all([account_sid, auth_token, from_number]):
            logger.warning("SMS alert: Twilio not configured (missing SID/token/number)")
            return

        caregiver_numbers = _get_room_caregivers(room_id)

        if not caregiver_numbers:
            fallback = os.environ.get('CAREGIVER_PHONE_NUMBER')
            if fallback:
                caregiver_numbers = [{'name': 'Default', 'phone': fallback}]
            else:
                logger.warning(f"SMS alert: No caregivers for {room_id} and no CAREGIVER_PHONE_NUMBER set")
                return

        client = Client(account_sid, auth_token)
        room_name = _get_room_display_name(room_id)

        body = f"🚨 Radim Care Alert\n" \
               f"Místnost: {room_name}\n" \
               f"Závažnost: {alert['severity'].upper()}\n" \
               f"{alert['message']}\n" \
               f"---\n" \
               f"Čas: {datetime.utcnow().strftime('%H:%M:%S')} UTC"

        sent_count = 0
        for cg in caregiver_numbers:
            try:
                client.messages.create(body=body, from_=from_number, to=cg['phone'])
                sent_count += 1
                logger.info(f"📱 SMS sent to {cg['name']} ({cg['phone'][-4:]})")
            except Exception as sms_err:
                logger.warning(f"SMS failed to {cg['name']}: {sms_err}")
                if 'not SMS-capable' in str(sms_err) or 'not a valid' in str(sms_err):
                    try:
                        client.messages.create(
                            body=body,
                            from_=f"whatsapp:{from_number}",
                            to=f"whatsapp:{cg['phone']}"
                        )
                        sent_count += 1
                        logger.info(f"📲 WhatsApp sent to {cg['name']} ({cg['phone'][-4:]})")
                    except Exception as wa_err:
                        logger.error(f"WhatsApp also failed to {cg['name']}: {wa_err}")
                else:
                    logger.error(f"SMS send error to {cg['name']}: {sms_err}")

        logger.info(f"📱 Alerts sent: {sent_count}/{len(caregiver_numbers)} for {room_id}")

    except ImportError:
        logger.warning("Twilio SDK not available for SMS alerts")
    except Exception as e:
        logger.error(f"SMS send error: {e}")


# ============================================
# ROOM HELPERS
# ============================================

def _get_room_caregivers(room_id):
    """Get active caregivers with SMS enabled for a room."""
    try:
        active_val = True if is_postgres() else 1
        with db_context() as db:
            rows = db.execute(
                "SELECT name, phone FROM iot_caregivers WHERE room_id = ? AND active = ? AND notify_sms = ?",
                (room_id, active_val, active_val)
            ).fetchall()
            return [{'name': r['name'], 'phone': r['phone']} for r in rows]
    except Exception as e:
        logger.warning(f"Caregiver lookup error: {e}")
        return []


def _get_room_display_name(room_id):
    """Get user-friendly room name from device registry."""
    try:
        with db_context() as db:
            row = db.execute("SELECT user_id FROM iot_devices WHERE room_id = ? LIMIT 1", (room_id,)).fetchone()
            if row and row['user_id']:
                return f"{room_id} ({row['user_id']})"
            return room_id
    except Exception:
        return room_id


logger.info("✅ IoT Helpers loaded — auth, DB, alert engine, room helpers")
