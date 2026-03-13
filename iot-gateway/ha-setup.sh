#!/bin/bash
# ============================================================
# Radim Care — Home Assistant Quick Setup
# ============================================================
# Spusť na PC/Macu po prvním přístupu k HA.
# Tento skript nahraje konfigurační soubory do Home Assistant
# přes HA REST API (Supervisor).
#
# Prerekvizity:
#   1. HA běží na RPi a je přístupný
#   2. Máš admin účet + Long-Lived Access Token
#      (HA → Profile → Long-Lived Access Tokens → Create)
#
# Použití:
#   bash ha-setup.sh http://homeassistant.local:8123 YOUR_TOKEN [ROOM_IDS]
#
# Příklady:
#   bash ha-setup.sh http://192.168.1.50:8123 eyJ0eX... room_A12
#   bash ha-setup.sh http://homeassistant.local:8123 eyJ0eX... room_A12,room_A15,room_B03
#   bash ha-setup.sh http://homeassistant.local:8123 eyJ0eX... all
# ============================================================

set -euo pipefail

HA_URL="${1:-}"
HA_TOKEN="${2:-}"
ROOMS="${3:-all}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}ℹ️  $*${NC}"; }
ok()    { echo -e "${GREEN}✅ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}"; exit 1; }

if [[ -z "$HA_URL" || -z "$HA_TOKEN" ]]; then
    echo "============================================================"
    echo "  Radim Care — HA Quick Setup"
    echo "============================================================"
    echo ""
    echo "Použití:"
    echo "  bash ha-setup.sh <HA_URL> <HA_TOKEN> [ROOMS]"
    echo ""
    echo "Příklady:"
    echo "  bash ha-setup.sh http://homeassistant.local:8123 eyJ0eX... room_A12"
    echo "  bash ha-setup.sh http://192.168.1.50:8123 eyJ0eX... all"
    echo ""
    echo "Kde získat token:"
    echo "  1. Otevři HA v prohlížeči"
    echo "  2. Profil (vlevo dole) → Long-Lived Access Tokens"
    echo "  3. Create Token → pojmenuj 'radim-setup' → zkopíruj"
    echo ""
    exit 1
fi

# ============================================================
info "Testuji připojení k Home Assistant..."
HA_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $HA_TOKEN" \
    "$HA_URL/api/")

if [[ "$HA_STATUS" != "200" ]]; then
    error "Nelze se připojit k HA ($HA_URL) — HTTP $HA_STATUS
    Zkontroluj URL a token."
fi
ok "HA připojení OK"

# ============================================================
info "Zjišťuji verzi HA..."
HA_VERSION=$(curl -s -H "Authorization: Bearer $HA_TOKEN" \
    "$HA_URL/api/" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))")
ok "Home Assistant $HA_VERSION"

# ============================================================
# STEP 1: Ověř Zigbee2MQTT
# ============================================================
info "Kontroluji Zigbee2MQTT..."
Z2M_CHECK=$(curl -s -o /dev/null -w "%{http_code}" "http://$(echo $HA_URL | sed 's|http://||;s|:8123||'):8080/api/health" 2>/dev/null || echo "000")

if [[ "$Z2M_CHECK" == "200" ]]; then
    ok "Zigbee2MQTT běží"
else
    warn "Zigbee2MQTT nedostupný na portu 8080"
    echo "  → Nainstaluj přes: Settings → Add-ons → Zigbee2MQTT"
    echo "  → Pokračuji s konfigurací HA..."
fi

# ============================================================
# STEP 2: Vyber pokoje
# ============================================================
ALL_ROOMS="room_A12 room_A15 room_B03 room_B07 room_C01"

if [[ "$ROOMS" == "all" ]]; then
    SELECTED_ROOMS="$ALL_ROOMS"
else
    SELECTED_ROOMS=$(echo "$ROOMS" | tr ',' ' ')
fi

info "Pokoje k instalaci: $SELECTED_ROOMS"

# ============================================================
# STEP 3: Generuj automatizace pro vybrané pokoje
# ============================================================
info "Generuji automatizace..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Generuj per-room automatizace
generate_room_automations() {
    local ROOM=$1
    local ROOM_SHORT=$(echo $ROOM | sed 's/room_//')

    cat <<YAML

# ============================================
# $ROOM — Temperature (every 5 min)
# ============================================
- id: radim_temp_${ROOM_SHORT}
  alias: "Radim: Teplota ${ROOM_SHORT} → Backend"
  mode: single
  trigger:
    - platform: time_pattern
      minutes: "/5"
  condition:
    - condition: state
      entity_id: sensor.zigbee_temp_${ROOM_SHORT}
      state: "unavailable"
      match: false
  action:
    - service: rest_command.radim_iot_ingest
      data:
        device_id: "zigbee_temp_${ROOM_SHORT}"
        room_id: "${ROOM}"
        sensor_type: "temperature"
        value: "{{ states('sensor.zigbee_temp_${ROOM_SHORT}') | float }}"
        unit: "°C"

# $ROOM — Humidity (every 5 min)
- id: radim_humidity_${ROOM_SHORT}
  alias: "Radim: Vlhkost ${ROOM_SHORT} → Backend"
  mode: single
  trigger:
    - platform: time_pattern
      minutes: "/5"
  action:
    - service: rest_command.radim_iot_ingest
      data:
        device_id: "zigbee_hum_${ROOM_SHORT}"
        room_id: "${ROOM}"
        sensor_type: "humidity"
        value: "{{ states('sensor.zigbee_humidity_${ROOM_SHORT}') | float }}"
        unit: "%"

# $ROOM — Motion (event-driven)
- id: radim_motion_${ROOM_SHORT}
  alias: "Radim: Pohyb ${ROOM_SHORT} → Backend"
  mode: single
  trigger:
    - platform: state
      entity_id: binary_sensor.zigbee_motion_${ROOM_SHORT}
  action:
    - service: rest_command.radim_iot_ingest
      data:
        device_id: "zigbee_motion_${ROOM_SHORT}"
        room_id: "${ROOM}"
        sensor_type: "motion"
        value: "{{ 1 if is_state('binary_sensor.zigbee_motion_${ROOM_SHORT}', 'on') else 0 }}"
        unit: "boolean"

# $ROOM — SOS Button (CRITICAL)
- id: radim_sos_${ROOM_SHORT}
  alias: "Radim: SOS ${ROOM_SHORT} → Backend (CRITICAL)"
  mode: single
  trigger:
    - platform: state
      entity_id: binary_sensor.zigbee_sos_${ROOM_SHORT}
      to: "on"
  action:
    - service: rest_command.radim_iot_ingest
      data:
        device_id: "zigbee_sos_${ROOM_SHORT}"
        room_id: "${ROOM}"
        sensor_type: "sos"
        value: "1"
        unit: "boolean"
YAML
}

# Build full automations file
AUTOMATIONS_YAML="# Auto-generated by Radim Care ha-setup.sh\n# $(date -u +%Y-%m-%dT%H:%M:%SZ)\n"

for ROOM in $SELECTED_ROOMS; do
    AUTOMATIONS_YAML+=$(generate_room_automations "$ROOM")
    ok "Automatizace pro $ROOM vygenerovány"
done

# ============================================================
# STEP 4: Upload secrets.yaml
# ============================================================
info "Nahrávám secrets.yaml..."

IOT_TOKEN="y7ZhSCEcHFuzk3g5gdAfQZJuqhO1G7sfxGFEHeR1oH0"
RADIM_API="https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/iot-bridge/data"

# Append to secrets.yaml (don't overwrite existing)
cat <<EOF > /tmp/radim_secrets_append.yaml

# Radim Care IoT Bridge (added by ha-setup.sh)
radim_api_url: "${RADIM_API}"
radim_iot_token: "${IOT_TOKEN}"
EOF

ok "Secrets připraveny (přidej manuálně do /config/secrets.yaml)"
echo "  Obsah:"
cat /tmp/radim_secrets_append.yaml

# ============================================================
# STEP 5: Upload rest_commands.yaml
# ============================================================
info "Připravuji rest_commands.yaml..."

cat <<'EOF' > /tmp/radim_rest_commands.yaml
# Radim Care IoT Bridge — REST Commands
# Added by ha-setup.sh

radim_iot_ingest:
  url: !secret radim_api_url
  method: POST
  headers:
    Content-Type: "application/json"
    X-IoT-Token: !secret radim_iot_token
  payload: >
    {
      "device_id": "{{ device_id }}",
      "room_id": "{{ room_id }}",
      "sensor_type": "{{ sensor_type }}",
      "value": {{ value }},
      "unit": "{{ unit | default('') }}",
      "recorded_at": "{{ utcnow().isoformat() }}Z"
    }
  timeout: 10
  verify_ssl: true
EOF

ok "rest_commands.yaml připraven"

# ============================================================
# STEP 6: Save automations
# ============================================================
echo -e "$AUTOMATIONS_YAML" > /tmp/radim_automations.yaml
ok "Automatizace uloženy do /tmp/radim_automations.yaml"

# ============================================================
# STEP 7: Print instructions
# ============================================================
echo ""
echo "============================================================"
echo -e "${GREEN}  ✅ Konfigurační soubory připraveny!${NC}"
echo "============================================================"
echo ""
echo "Nyní manuálně nahraj do Home Assistant (File Editor addon):"
echo ""
echo "  1. Otevři: $HA_URL → Sidebar → File editor"
echo ""
echo "  2. /config/secrets.yaml — přidej na konec:"
echo "     $(cat /tmp/radim_secrets_append.yaml | head -4)"
echo ""
echo "  3. /config/rest_commands.yaml — vytvoř nový soubor:"
echo "     zkopíruj z: /tmp/radim_rest_commands.yaml"
echo ""
echo "  4. /config/configuration.yaml — přidej řádek:"
echo "     rest_command: !include rest_commands.yaml"
echo ""
echo "  5. /config/automations.yaml — přidej:"
echo "     zkopíruj z: /tmp/radim_automations.yaml"
echo ""
echo "  6. Restartuj HA: Settings → System → Restart"
echo ""
echo "  7. Ověř: Developer Tools → Services → rest_command.radim_iot_ingest"
echo ""
echo "Soubory k nahrání:"
echo "  /tmp/radim_secrets_append.yaml"
echo "  /tmp/radim_rest_commands.yaml"
echo "  /tmp/radim_automations.yaml"
echo ""
echo "============================================================"
echo -e "${BLUE}  Pak spáruj senzory v Zigbee2MQTT: $(echo $HA_URL | sed 's|:8123|:8080|')${NC}"
echo "============================================================"
