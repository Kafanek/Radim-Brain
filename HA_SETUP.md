# Home Assistant setup — Radim konference 14.5.

Rychlý setup guide pro napojení Radima na Home Assistant až dorazí hardware
(Lenovo mini PC, Raspberry Pi, Zigbee senzory).

## Hardware plán

| Zařízení | Role |
|---|---|
| **Lenovo mini PC** | Home Assistant OS (HAOS) — hlavní server |
| **Raspberry Pi** | Zigbee2MQTT gateway + Sonoff Dongle Plus |
| **Aqara / Sonoff senzory** | Motion, door, temperature, accelerometer |
| **Wifi světla** (TP-Link Kasa / Yeelight) | Přímé ovládání přes Radim (bez HA) |

## 1. Instalace HAOS na Lenovo

```bash
# Stáhnout HAOS image
curl -L https://github.com/home-assistant/operating-system/releases/latest/download/haos_generic-x86-64.img.xz -o haos.img.xz
xz -d haos.img.xz

# Zapsat na disk (UPOZORNĚNÍ: smaže disk)
sudo dd if=haos.img of=/dev/sdX bs=4M status=progress
```

Po bootu:
1. Otevřít `http://<lenovo-ip>:8123`
2. Vytvořit admin účet
3. Konfigurovat lokaci / timezone

## 2. Long-lived token

V HA UI:
1. Kliknout na profilové jméno (levý dolní roh)
2. Scrollni dolů → **Long-Lived Access Tokens** → **Create Token**
3. Název: `Radim-Brain-Prod`
4. **Zkopírovat token** (zobrazí se jednou, po zavření už ne)

## 3. Heroku konfigurace

```bash
# Nastavit Radima aby věděl kde HA běží
heroku config:set HA_URL="http://<lenovo-ip>:8123" -a radim-brain-2025
heroku config:set HA_TOKEN="<long-lived-token>" -a radim-brain-2025
heroku config:set HA_WEBHOOK_SECRET="<random-32-char-string>" -a radim-brain-2025
```

**Pozor**: Pokud je Lenovo za NATem (domácí síť), potřebuješ:
- **Option A**: Nginx reverse proxy + veřejná doména (doporučené)
- **Option B**: Cloudflare Tunnel (zdarma, bezpečné)
- **Option C**: VPN (Tailscale) — Heroku musí být v stejné VPN síti

Doporučuji **Cloudflare Tunnel**:
```bash
# Na Lenovo
docker run -d --name cf-tunnel cloudflare/cloudflared:latest \
  tunnel --no-autoupdate run --token <cf-tunnel-token>
```
Dostaneš `https://radim-ha.<tvoje-doména>.com` — použij jako `HA_URL`.

## 4. Zigbee2MQTT na Raspberry Pi

```bash
# Na RPi
sudo apt update && sudo apt install -y nodejs npm
git clone https://github.com/Koenkk/zigbee2mqtt.git /opt/zigbee2mqtt
cd /opt/zigbee2mqtt && npm ci

# Konfigurace
cat > data/configuration.yaml <<EOF
mqtt:
  server: mqtt://<lenovo-ip>:1883
serial:
  port: /dev/ttyUSB0  # Sonoff dongle
frontend:
  port: 8080
homeassistant: true
permit_join: false  # povolit jen při párování
EOF

# Spustit
node index.js
```

V HA → Settings → Devices → **Add Integration** → MQTT → auto-discovery najde všechna Zigbee zařízení.

## 5. Doporučené senzory (nákupní list)

| Zařízení | Cena (CZK) | Použití |
|---|---|---|
| **Aqara Motion Sensor P1** | ~750 | Detekce pohybu v místnostech |
| **Aqara Door Sensor** | ~450 | Otevření vchodových dveří |
| **Aqara Vibration Sensor** | ~750 | Detekce pádu (akcelerometr) |
| **Xiaomi Temperature/Humidity** | ~300 | Environmentální monitoring |
| **Aqara Smart Button** | ~600 | SOS tlačítko pro seniora |
| **Sonoff ZBDongle-E** | ~800 | Zigbee koordinátor (do RPi) |

Celkem **~3,650 CZK** za základní senzorovou sadu pro 1 byt.

## 6. Entity ID konvence

Aby Radim uměl zařízení najít v crisis akcích, pojmenuj je takto:

```
light.obyvak_svetlo          # obývák
light.kuchyn_svetlo          # kuchyň
light.loznice_svetlo         # ložnice
light.chodba_svetlo          # chodba
lock.vchodove_dvere          # vchodové dveře
cover.obyvak_rolety          # rolety obývák
binary_sensor.pad_akcelerometr   # pád senzor
binary_sensor.vchod_dvere        # dveřní senzor
sensor.obyvak_teplota            # teplota
```

Radim automaticky vyhledá zařízení podle roomu + typu. Když detekuje krizi, zavolá:
- `light_on(brightness=100)` na všechny světla
- `unlock()` na `lock.vchodove_dvere`
- `cover_open()` na všechny rolety

## 7. Webhook — HA → Radim

Pro proaktivní upozornění (HA detekuje pád → Radim reaguje):

V HA `configuration.yaml`:
```yaml
automation:
  - alias: "Radim — pád detekován"
    trigger:
      - platform: state
        entity_id: binary_sensor.pad_akcelerometr
        to: "on"
    action:
      - service: rest_command.radim_webhook
        data:
          event: "fall_detected"
          sensor: "pad_akcelerometr"
          value: "{{ states('sensor.akcelerometr_g').state }}"

rest_command:
  radim_webhook:
    url: "https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/ha/webhook/crisis"
    method: POST
    headers:
      X-HA-Secret: "!secret ha_webhook_secret"
    payload: '{"event": "{{ event }}", "sensor": "{{ sensor }}", "value": "{{ value }}"}'
```

## 8. Ověření napojení

```bash
# 1. Health check — HA musí být dostupné z Heroku
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/admin/status \
  -H "X-Admin-Secret: <admin-secret>" | jq .ha

# 2. Seznam zařízení
curl https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/ha/devices \
  -H "X-Admin-Secret: <admin-secret>"

# 3. Spustit krizové demo s REÁLNÝM HA
curl -X POST https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/admin/crisis-demo \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: <admin-secret>" \
  -d '{"scenario":"fall","ha_actions":true}'
# → všechna světla se rozsvítí, dveře odemknou
```

## 9. Rollback

Pokud HA přestane fungovat (výpadek, update), Radim automaticky padne na **mock mode**:
- `_ha_crisis_actions()` v `agent_loop.py` kontroluje `ha_client.connected`
- Když není připojen, vrací se bez akcí (žádná výjimka, tichý fallback)
- `crisis-demo` endpoint s `ha_mock=true` funguje vždy (scripted response)

Takže i kdyby HA během konference selhal, demo funguje z mocku.

## 10. Checklist před konferencí

- [ ] HAOS běží na Lenovo, dostupné z internetu (CF Tunnel)
- [ ] Long-lived token vygenerován, `HA_URL` + `HA_TOKEN` na Heroku
- [ ] Minimálně 4 světla + 1 zámek v HA (i kdyby jen simulované `template` entity)
- [ ] Radim připojený: `/api/admin/status` vrací `ha.connected=true`
- [ ] `/api/admin/crisis-demo` s `ha_actions=true` funguje end-to-end
- [ ] `demo.html` otestováno s `ha_mock=true` (záložní mode)
- [ ] Vyzkoušet 3× scripted crisis flow na laptopu (pro jistotu offline)

## 11. Konferenční tipy

- **Před prezentací** spusť demo 1-2× aby se cache "nahřála" (Azure TTS warmup ~1.5s první volání, pak rychlejší)
- Pokud WiFi na konferenci selže, demo běží i z **localhost** (Heroku CLI `heroku local`)
- `ha_mock=true` je **bezpečnější defaultně** — vizualizace v UI je stejně přesvědčivá jako reálné rozsvícení
- Kombinace: **první demo mock (rychlé, jisté), druhé live** (pokud je publikum zaujaté)

---

**Kontakt / debug**: `/api/admin/status`, logs na `heroku logs --tail -a radim-brain-2025`.
