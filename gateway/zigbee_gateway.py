#!/usr/bin/env python3
"""
Zigbee Gateway for Radim IoT Bridge
====================================
Runs on Raspberry Pi. Reads Zigbee sensor data via zigbee2mqtt MQTT broker
and forwards to Radim's /api/iot-bridge/data endpoint.

Requirements:
  pip install paho-mqtt requests

Configuration (env vars or .env file):
  RADIM_API_URL=https://radim-brain-2025-be1cd52b04dc.herokuapp.com
  IOT_GATEWAY_TOKEN=<your-token>
  MQTT_HOST=localhost
  MQTT_PORT=1883
  MQTT_TOPIC=zigbee2mqtt/#
  ROOM_ID=bedroom_1
  USER_ID=demo_senior_1

Usage:
  python3 zigbee_gateway.py

Supported Zigbee devices (zigbee2mqtt JSON payloads):
  - Aqara motion sensor: {"occupancy": true, "illuminance": 42}
  - Aqara temp/humidity: {"temperature": 22.5, "humidity": 45.2}
  - Aqara door sensor:   {"contact": false}
  - Withings BPM Core:   {"systolic": 120, "diastolic": 80, "heart_rate": 72}
"""

import os
import json
import time
import logging
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('zigbee-gateway')

# Configuration
RADIM_API_URL = os.environ.get('RADIM_API_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
IOT_GATEWAY_TOKEN = os.environ.get('IOT_GATEWAY_TOKEN', '')
MQTT_HOST = os.environ.get('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_TOPIC = os.environ.get('MQTT_TOPIC', 'zigbee2mqtt/#')
ROOM_ID = os.environ.get('ROOM_ID', 'bedroom_1')
USER_ID = os.environ.get('USER_ID', 'demo_senior_1')

# Rate limiting: max 1 POST per sensor per 30 seconds
_last_sent = {}
MIN_INTERVAL_SEC = 30

INGEST_URL = f"{RADIM_API_URL}/api/iot-bridge/data"
HEADERS = {
    'Content-Type': 'application/json',
    'X-IoT-Token': IOT_GATEWAY_TOKEN
}


def send_reading(device_id, sensor_type, value, unit=None):
    """Send a single sensor reading to Radim API."""
    key = f"{device_id}:{sensor_type}"
    now = time.time()
    if key in _last_sent and now - _last_sent[key] < MIN_INTERVAL_SEC:
        return  # rate limited

    payload = {
        'device_id': device_id,
        'room_id': ROOM_ID,
        'sensor_type': sensor_type,
        'value': value,
    }
    if unit:
        payload['unit'] = unit

    try:
        resp = requests.post(INGEST_URL, json=payload, headers=HEADERS, timeout=10)
        if resp.status_code == 201:
            _last_sent[key] = now
            logger.info(f"✅ {device_id}/{sensor_type}: {value}{unit or ''}")
        else:
            logger.warning(f"⚠️ API {resp.status_code}: {resp.text[:100]}")
    except requests.RequestException as e:
        logger.error(f"❌ Send failed: {e}")


def on_message(client, userdata, msg):
    """Handle incoming MQTT message from zigbee2mqtt."""
    try:
        topic = msg.topic
        # zigbee2mqtt publishes to: zigbee2mqtt/<friendly_name>
        parts = topic.split('/')
        if len(parts) < 2 or parts[0] != 'zigbee2mqtt':
            return
        device_name = parts[1]

        # Skip bridge messages and availability
        if device_name in ('bridge', ) or topic.endswith('/availability'):
            return

        payload = json.loads(msg.payload.decode())
        device_id = f"zigbee_{device_name}"

        # Motion sensor (Aqara RTCGQ11LM, Sonoff SNZB-03)
        if 'occupancy' in payload:
            if payload['occupancy']:
                send_reading(device_id, 'motion', 1.0)

        # Temperature + humidity (Aqara WSDCGQ11LM, Sonoff SNZB-02)
        if 'temperature' in payload:
            send_reading(device_id, 'temperature', round(payload['temperature'], 1), 'C')
        if 'humidity' in payload:
            send_reading(device_id, 'humidity', round(payload['humidity'], 1), '%')

        # Door/window sensor (Aqara MCCGQ11LM)
        if 'contact' in payload:
            send_reading(device_id, 'door', 0.0 if payload['contact'] else 1.0)

        # Heart rate (Withings BPM, or custom wearable)
        if 'heart_rate' in payload:
            send_reading(device_id, 'heart_rate', payload['heart_rate'], 'bpm')
        if 'spo2' in payload:
            send_reading(device_id, 'spo2', payload['spo2'], '%')
        if 'systolic' in payload:
            send_reading(device_id, 'blood_pressure_sys', payload['systolic'], 'mmHg')
        if 'diastolic' in payload:
            send_reading(device_id, 'blood_pressure_dia', payload['diastolic'], 'mmHg')

        # Battery level
        if 'battery' in payload and isinstance(payload['battery'], (int, float)):
            if payload['battery'] < 15:
                logger.warning(f"🔋 Low battery: {device_name} = {payload['battery']}%")

    except json.JSONDecodeError:
        pass
    except Exception as e:
        logger.error(f"Message handling error: {e}")


def main():
    """Main loop: connect to MQTT and forward to Radim."""
    if not IOT_GATEWAY_TOKEN:
        logger.error("❌ IOT_GATEWAY_TOKEN not set. Get it from Heroku config.")
        return

    logger.info(f"🏠 Zigbee Gateway starting")
    logger.info(f"   MQTT: {MQTT_HOST}:{MQTT_PORT} topic={MQTT_TOPIC}")
    logger.info(f"   API:  {INGEST_URL}")
    logger.info(f"   Room: {ROOM_ID}, User: {USER_ID}")

    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.error("❌ paho-mqtt not installed. Run: pip install paho-mqtt")
        return

    client = mqtt.Client(client_id="radim-gateway")
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.subscribe(MQTT_TOPIC)
        logger.info("✅ Connected to MQTT broker")
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Gateway stopped by user")
    except Exception as e:
        logger.error(f"MQTT connection error: {e}")
    finally:
        client.disconnect()


if __name__ == '__main__':
    main()
