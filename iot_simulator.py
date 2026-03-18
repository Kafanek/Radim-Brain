"""
IoT Simulator v1.0
===================
Generates realistic sensor data for demo_senior_1 to test:
- Activity drop detection (motion sensor)
- Vital anomaly detection (heart_rate, spo2)
- Temperature monitoring

Simulates a Zigbee gateway pushing to /api/iot-bridge/data.

Usage:
  POST /api/admin/iot-simulate (creates 7 days of sensor data)
  python3 iot_simulator.py (standalone)
"""

import json
import math
import random
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEMO_USER = "demo_senior_1"
DEMO_ROOM = "bedroom_1"
DEMO_DEVICE_MOTION = "zigbee_motion_001"
DEMO_DEVICE_HR = "zigbee_hr_001"
DEMO_DEVICE_TEMP = "zigbee_temp_001"


def seed_iot_devices():
    """Register demo IoT devices in iot_devices table."""
    from database import db_context, is_postgres

    devices = [
        (DEMO_DEVICE_MOTION, DEMO_ROOM, "motion", "Zigbee motion sensor", DEMO_USER),
        (DEMO_DEVICE_HR, DEMO_ROOM, "heart_rate", "Zigbee HR/SpO2 wristband", DEMO_USER),
        (DEMO_DEVICE_TEMP, DEMO_ROOM, "temperature", "Zigbee temp sensor", DEMO_USER),
    ]

    with db_context(commit=True) as db:
        for dev_id, room_id, sensor_type, name, user_id in devices:
            if is_postgres():
                db.execute("""
                    INSERT INTO iot_devices (device_id, room_id, sensor_type, name, user_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'active', NOW())
                    ON CONFLICT (device_id) DO UPDATE SET
                        room_id = EXCLUDED.room_id, user_id = EXCLUDED.user_id,
                        status = 'active'
                """, (dev_id, room_id, sensor_type, name, user_id))
            else:
                db.execute("""
                    INSERT OR REPLACE INTO iot_devices (device_id, room_id, sensor_type, name, user_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'active', datetime('now'))
                """, (dev_id, room_id, sensor_type, name, user_id))

    logger.info(f"IoT: {len(devices)} devices registered for {DEMO_USER}")
    return len(devices)


def seed_sensor_data(days=7):
    """Generate realistic sensor data for last N days."""
    from database import db_context, is_postgres

    now = datetime.utcnow()
    records = []

    for day_offset in range(days, 0, -1):
        base = now - timedelta(days=day_offset)

        # Motion: more in morning/afternoon, less at night
        for hour in range(24):
            # Probability of motion events per hour
            if 0 <= hour < 6:
                motion_count = random.randint(0, 1)  # sleeping
            elif 6 <= hour < 8:
                motion_count = random.randint(2, 5)   # waking up
            elif 8 <= hour < 12:
                motion_count = random.randint(3, 8)   # morning activity
            elif 12 <= hour < 14:
                motion_count = random.randint(2, 5)   # lunch
            elif 14 <= hour < 16:
                motion_count = random.randint(0, 2)   # afternoon nap
            elif 16 <= hour < 20:
                motion_count = random.randint(2, 6)   # evening
            else:
                motion_count = random.randint(0, 2)   # settling down

            for _ in range(motion_count):
                t = base + timedelta(hours=hour, minutes=random.randint(0, 59))
                records.append((DEMO_DEVICE_MOTION, DEMO_ROOM, "motion", 1.0, None, t.isoformat()))

        # Heart rate: measured every 30 min during waking hours
        for hour in range(7, 22):
            for half in (0, 30):
                t = base + timedelta(hours=hour, minutes=half)
                # Normal resting HR for senior: 60-80, occasional spikes
                hr = random.gauss(72, 5)
                if random.random() < 0.05:  # 5% chance of elevated HR
                    hr = random.gauss(95, 8)
                hr = max(45, min(140, hr))
                records.append((DEMO_DEVICE_HR, DEMO_ROOM, "heart_rate", round(hr, 1), "bpm", t.isoformat()))

        # SpO2: measured every 30 min
        for hour in range(7, 22):
            for half in (0, 30):
                t = base + timedelta(hours=hour, minutes=half)
                spo2 = random.gauss(97, 1.0)
                if random.random() < 0.02:  # 2% chance of low SpO2
                    spo2 = random.gauss(92, 2)
                spo2 = max(85, min(100, spo2))
                records.append((DEMO_DEVICE_HR, DEMO_ROOM, "spo2", round(spo2, 1), "%", t.isoformat()))

        # Temperature: every hour
        for hour in range(24):
            t = base + timedelta(hours=hour, minutes=random.randint(0, 10))
            # Room temp: 20-23°C normally
            temp = random.gauss(21.5, 0.8)
            records.append((DEMO_DEVICE_TEMP, DEMO_ROOM, "temperature", round(temp, 1), "C", t.isoformat()))

    # Insert all records
    with db_context(commit=True) as db:
        # Clear old demo data
        db.execute("DELETE FROM iot_sensor_data WHERE device_id IN (?, ?, ?)",
                   (DEMO_DEVICE_MOTION, DEMO_DEVICE_HR, DEMO_DEVICE_TEMP))

        for rec in records:
            device_id, room_id, sensor_type, value, unit, recorded_at = rec
            if is_postgres():
                db.execute(
                    "INSERT INTO iot_sensor_data (device_id, room_id, sensor_type, value, unit, recorded_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?::timestamp, NOW())",
                    (device_id, room_id, sensor_type, value, unit, recorded_at))
            else:
                db.execute(
                    "INSERT INTO iot_sensor_data (device_id, room_id, sensor_type, value, unit, recorded_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                    (device_id, room_id, sensor_type, value, unit, recorded_at))

    # Count by type
    motion_count = sum(1 for r in records if r[2] == "motion")
    hr_count = sum(1 for r in records if r[2] == "heart_rate")
    spo2_count = sum(1 for r in records if r[2] == "spo2")
    temp_count = sum(1 for r in records if r[2] == "temperature")

    logger.info(f"IoT: {len(records)} sensor records created ({motion_count} motion, {hr_count} HR, {spo2_count} SpO2, {temp_count} temp)")

    return {
        "total_records": len(records),
        "motion": motion_count,
        "heart_rate": hr_count,
        "spo2": spo2_count,
        "temperature": temp_count,
        "days": days,
        "room": DEMO_ROOM,
        "user_id": DEMO_USER
    }


def seed_alert_rules():
    """Create basic alert rules for demo room."""
    from database import db_context, is_postgres

    rules = [
        (DEMO_ROOM, "heart_rate", "above", 120.0, "critical", '["push","sms"]', 30),
        (DEMO_ROOM, "heart_rate", "below", 50.0, "critical", '["push","sms"]', 30),
        (DEMO_ROOM, "spo2", "below", 90.0, "critical", '["push","sms"]', 15),
        (DEMO_ROOM, "temperature", "above", 28.0, "warning", '["push"]', 60),
        (DEMO_ROOM, "temperature", "below", 16.0, "warning", '["push"]', 60),
    ]

    with db_context(commit=True) as db:
        db.execute("DELETE FROM iot_alert_rules WHERE room_id = ?", (DEMO_ROOM,))
        for room_id, sensor_type, condition, threshold, severity, channels, cooldown in rules:
            db.execute(
                "INSERT INTO iot_alert_rules (room_id, sensor_type, condition, threshold, severity, notify_channels, cooldown_minutes, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (room_id, sensor_type, condition, threshold, severity, channels, cooldown, True))

    logger.info(f"IoT: {len(rules)} alert rules created for {DEMO_ROOM}")
    return len(rules)


def run_full_iot_seed():
    """Seed everything: devices + 7 days sensor data + alert rules."""
    devices = seed_iot_devices()
    data = seed_sensor_data(days=7)
    rules = seed_alert_rules()
    return {
        "devices": devices,
        "alert_rules": rules,
        **data
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_full_iot_seed()
    print(f"\nIoT data seeded: {json.dumps(result, indent=2)}")
