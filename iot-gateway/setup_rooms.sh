#!/bin/bash
# ==============================================
# Radim Care — Setup 5 rooms with sensors + alert rules
# ==============================================
# Run once to register all devices and create alert rules
# Usage: bash setup_rooms.sh

BASE="https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/iot-bridge"
TOKEN="y7ZhSCEcHFuzk3g5gdAfQZJuqhO1G7sfxGFEHeR1oH0"
HDR="-H Content-Type:application/json -H X-IoT-Token:$TOKEN"

echo "🏠 Registering devices for 5 rooms..."
echo ""

# ============================================
# ROOM A-12: Marie Novotná (senior-001)
# Sensors: temp, humidity, motion, door, SOS
# ============================================
echo "=== Room A-12 (Marie Novotná) ==="
for dev in \
  '{"device_id":"zigbee_temp_A12","room_id":"room_A12","user_id":"senior-001","device_type":"temperature_sensor","name":"Teploměr - Ložnice A12","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_hum_A12","room_id":"room_A12","user_id":"senior-001","device_type":"humidity_sensor","name":"Vlhkoměr - Ložnice A12","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_motion_A12","room_id":"room_A12","user_id":"senior-001","device_type":"motion_sensor","name":"Pohybový senzor - Ložnice A12","model":"Aqara RTCGQ11LM"}' \
  '{"device_id":"zigbee_door_A12","room_id":"room_A12","user_id":"senior-001","device_type":"door_sensor","name":"Dveřní kontakt - Vstup A12","model":"Aqara MCCGQ11LM"}' \
  '{"device_id":"zigbee_sos_A12","room_id":"room_A12","user_id":"senior-001","device_type":"sos_button","name":"SOS tlačítko - A12","model":"Aqara WXKG11LM"}'
do
  curl -s -X POST "$BASE/devices" -H "Content-Type: application/json" -H "X-IoT-Token: $TOKEN" -d "$dev" > /dev/null
  echo "  ✓ $(echo $dev | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])')"
done

# ============================================
# ROOM A-15: Josef Dvořák (senior-002)
# Sensors: temp, humidity, motion, door, fall, SOS
# ============================================
echo "=== Room A-15 (Josef Dvořák) ==="
for dev in \
  '{"device_id":"zigbee_temp_A15","room_id":"room_A15","user_id":"senior-002","device_type":"temperature_sensor","name":"Teploměr - Ložnice A15","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_hum_A15","room_id":"room_A15","user_id":"senior-002","device_type":"humidity_sensor","name":"Vlhkoměr - Ložnice A15","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_motion_A15","room_id":"room_A15","user_id":"senior-002","device_type":"motion_sensor","name":"Pohybový senzor - A15","model":"Aqara RTCGQ11LM"}' \
  '{"device_id":"zigbee_door_A15","room_id":"room_A15","user_id":"senior-002","device_type":"door_sensor","name":"Dveřní kontakt - A15","model":"Aqara MCCGQ11LM"}' \
  '{"device_id":"zigbee_fall_A15","room_id":"room_A15","user_id":"senior-002","device_type":"fall_sensor","name":"Detekce pádu - A15","model":"Aqara FP1"}' \
  '{"device_id":"zigbee_sos_A15","room_id":"room_A15","user_id":"senior-002","device_type":"sos_button","name":"SOS tlačítko - A15","model":"Aqara WXKG11LM"}'
do
  curl -s -X POST "$BASE/devices" -H "Content-Type: application/json" -H "X-IoT-Token: $TOKEN" -d "$dev" > /dev/null
  echo "  ✓ $(echo $dev | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])')"
done

# ============================================
# ROOM B-03: Božena Černá (senior-003)
# Sensors: temp, humidity, motion, SOS
# ============================================
echo "=== Room B-03 (Božena Černá) ==="
for dev in \
  '{"device_id":"zigbee_temp_B03","room_id":"room_B03","user_id":"senior-003","device_type":"temperature_sensor","name":"Teploměr - Ložnice B03","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_hum_B03","room_id":"room_B03","user_id":"senior-003","device_type":"humidity_sensor","name":"Vlhkoměr - Ložnice B03","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_motion_B03","room_id":"room_B03","user_id":"senior-003","device_type":"motion_sensor","name":"Pohybový senzor - B03","model":"Aqara RTCGQ11LM"}' \
  '{"device_id":"zigbee_sos_B03","room_id":"room_B03","user_id":"senior-003","device_type":"sos_button","name":"SOS tlačítko - B03","model":"Aqara WXKG11LM"}'
do
  curl -s -X POST "$BASE/devices" -H "Content-Type: application/json" -H "X-IoT-Token: $TOKEN" -d "$dev" > /dev/null
  echo "  ✓ $(echo $dev | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])')"
done

# ============================================
# ROOM B-07: František Procházka (senior-004)
# Sensors: temp, humidity, motion, door, fall, SOS (demence risk)
# ============================================
echo "=== Room B-07 (František Procházka) ==="
for dev in \
  '{"device_id":"zigbee_temp_B07","room_id":"room_B07","user_id":"senior-004","device_type":"temperature_sensor","name":"Teploměr - Ložnice B07","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_hum_B07","room_id":"room_B07","user_id":"senior-004","device_type":"humidity_sensor","name":"Vlhkoměr - B07","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_motion_B07","room_id":"room_B07","user_id":"senior-004","device_type":"motion_sensor","name":"Pohybový senzor - B07","model":"Aqara RTCGQ11LM"}' \
  '{"device_id":"zigbee_door_B07","room_id":"room_B07","user_id":"senior-004","device_type":"door_sensor","name":"Dveřní kontakt - B07","model":"Aqara MCCGQ11LM"}' \
  '{"device_id":"zigbee_fall_B07","room_id":"room_B07","user_id":"senior-004","device_type":"fall_sensor","name":"Detekce pádu - B07","model":"Aqara FP1"}' \
  '{"device_id":"zigbee_sos_B07","room_id":"room_B07","user_id":"senior-004","device_type":"sos_button","name":"SOS tlačítko - B07","model":"Aqara WXKG11LM"}'
do
  curl -s -X POST "$BASE/devices" -H "Content-Type: application/json" -H "X-IoT-Token: $TOKEN" -d "$dev" > /dev/null
  echo "  ✓ $(echo $dev | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])')"
done

# ============================================
# ROOM C-01: Vlasta Horáková (senior-005)
# Sensors: temp, humidity, motion, SOS
# ============================================
echo "=== Room C-01 (Vlasta Horáková) ==="
for dev in \
  '{"device_id":"zigbee_temp_C01","room_id":"room_C01","user_id":"senior-005","device_type":"temperature_sensor","name":"Teploměr - C01","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_hum_C01","room_id":"room_C01","user_id":"senior-005","device_type":"humidity_sensor","name":"Vlhkoměr - C01","model":"Aqara WSDCGQ11LM"}' \
  '{"device_id":"zigbee_motion_C01","room_id":"room_C01","user_id":"senior-005","device_type":"motion_sensor","name":"Pohybový senzor - C01","model":"Aqara RTCGQ11LM"}' \
  '{"device_id":"zigbee_sos_C01","room_id":"room_C01","user_id":"senior-005","device_type":"sos_button","name":"SOS tlačítko - C01","model":"Aqara WXKG11LM"}'
do
  curl -s -X POST "$BASE/devices" -H "Content-Type: application/json" -H "X-IoT-Token: $TOKEN" -d "$dev" > /dev/null
  echo "  ✓ $(echo $dev | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])')"
done

echo ""
echo "📊 Creating alert rules..."
echo ""

# ============================================
# ALERT RULES — applied to ALL 5 rooms
# ============================================
for ROOM in room_A12 room_A15 room_B03 room_B07 room_C01; do
  echo "--- Rules for $ROOM ---"

  # Temperature too high (>28°C)
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"temperature\",\"condition\":\"above\",\"threshold\":28.0,\"severity\":\"warning\",\"notify_channels\":\"push\",\"cooldown_minutes\":30}" > /dev/null
  echo "  ✓ Teplota > 28°C → warning"

  # Temperature too low (<16°C)
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"temperature\",\"condition\":\"below\",\"threshold\":16.0,\"severity\":\"warning\",\"notify_channels\":\"push,sms\",\"cooldown_minutes\":30}" > /dev/null
  echo "  ✓ Teplota < 16°C → warning + SMS"

  # Humidity too high (>70%)
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"humidity\",\"condition\":\"above\",\"threshold\":70.0,\"severity\":\"info\",\"notify_channels\":\"push\",\"cooldown_minutes\":60}" > /dev/null
  echo "  ✓ Vlhkost > 70% → info"

  # SOS button pressed
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"sos\",\"condition\":\"above\",\"threshold\":0.5,\"severity\":\"critical\",\"notify_channels\":\"push,sms\",\"cooldown_minutes\":5}" > /dev/null
  echo "  ✓ SOS stisknuto → CRITICAL + SMS"

  # No motion for 2+ hours (watchdog sends value=0)
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"no_motion\",\"condition\":\"equals\",\"threshold\":0.0,\"severity\":\"warning\",\"notify_channels\":\"push,sms\",\"cooldown_minutes\":120}" > /dev/null
  echo "  ✓ Žádný pohyb 2h → warning + SMS"
done

# Fall detection — only rooms with fall sensors
for ROOM in room_A15 room_B07; do
  curl -s -X POST "$BASE/alert-rules" -H "Content-Type: application/json" \
    -d "{\"room_id\":\"$ROOM\",\"sensor_type\":\"fall\",\"condition\":\"above\",\"threshold\":0.5,\"severity\":\"critical\",\"notify_channels\":\"push,sms\",\"cooldown_minutes\":5}" > /dev/null
  echo "  ✓ $ROOM: Pád detekován → CRITICAL + SMS"
done

echo ""
echo "✅ Setup complete!"
echo ""

# Final check
echo "📊 Dashboard status:"
curl -s "$BASE/health" | python3 -m json.tool
