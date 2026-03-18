# Zigbee Gateway for Radim

Runs on **Raspberry Pi 4/5** with a Zigbee USB coordinator (CC2652P, SLZB-06, etc.).

## Quick Start

```bash
# 1. Install zigbee2mqtt (on Raspberry Pi)
# https://www.zigbee2mqtt.io/guide/installation/

# 2. Install Python dependencies
pip install paho-mqtt requests

# 3. Configure
export RADIM_API_URL=https://radim-brain-2025-be1cd52b04dc.herokuapp.com
export IOT_GATEWAY_TOKEN=mkobNw57gEC1LsTHe5G5O5Dqw31u-9r2
export ROOM_ID=bedroom_1
export USER_ID=demo_senior_1

# 4. Run
python3 zigbee_gateway.py
```

## Supported Devices

| Device | Zigbee Model | Data |
|--------|-------------|------|
| Aqara Motion Sensor | RTCGQ11LM | motion, illuminance |
| Aqara Temp/Humidity | WSDCGQ11LM | temperature, humidity |
| Aqara Door Sensor | MCCGQ11LM | door open/close |
| Sonoff Motion | SNZB-03 | motion |
| Sonoff Temp | SNZB-02 | temperature, humidity |

## Architecture

```
Zigbee sensors → CC2652P USB → zigbee2mqtt → MQTT broker
                                                ↓
                              zigbee_gateway.py (this script)
                                                ↓
                              POST /api/iot-bridge/data (Heroku)
                                                ↓
                              PostgreSQL → Agent Loop → Notifications
```

## Matter/Thread Ready

When transitioning to Matter/Thread:
1. Replace zigbee2mqtt with matter-server
2. Update MQTT topics in this script
3. Same API endpoint, same data format
