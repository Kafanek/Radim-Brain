# Home Assistant setup — Radim konference 14.5.

Rychlý setup guide pro napojení Radima na Home Assistant až dorazí hardware
(Lenovo mini PC, Raspberry Pi, Zigbee senzory).

## Per-user / per-home (v395+)

Od verze 395 každý uživatel registruje **svůj vlastní Home Assistant** —
URL + long-lived token jsou uloženy v tabulce `user_ha_homes`, token je
šifrovaný Fernet klíčem. Jeden uživatel může mít víc domovů (hlavní byt
+ chata + ...). Webhook secret se generuje **per-home**, takže HA hlásí
události na `/api/ha/webhook/<home_id>` a každý dům má vlastní credentials.

**Heroku config (jednou pro celou aplikaci):**

```bash
# Šifrovací klíč — povinný v produkci
heroku config:set HA_TOKEN_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" -a radim-brain-2025
```

> Bez `HA_TOKEN_ENCRYPTION_KEY` aplikace odvodí dev klíč z `HA_WEBHOOK_SECRET` /
> `FLASK_SECRET_KEY`. To je OK na localhostu, ale **v produkci musí být explicit**,
> jinak se klíč při změně odvozeného secretu odpojí od šifrovaných tokenů a
> všichni uživatelé musí token znovu vložit.

**Per-user setup (volá frontend / admin):**

```bash
# Uživatel přidá svůj domov (vyžaduje JWT z loginu)
curl -X POST https://app.radimcare.cz/api/ha/config \
  -H "Authorization: Bearer <user-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Babiččin byt v Brně",
    "ha_url": "https://radim-ha-babicka.vlastni-doména.cz",
    "ha_token": "<long-lived-token-z-HA>",
    "is_default": true
  }'
# → 201 {"success": true, "home": {"home_id": "...", "ha_webhook_secret": "..."}}
```

Vrácený `home_id` + `ha_webhook_secret` použij v `configuration.yaml` HA:

```yaml
rest_command:
  radim_webhook:
    url: "https://app.radimcare.cz/api/ha/webhook/<home_id>"
    method: POST
    headers:
      X-HA-Secret: "<ha_webhook_secret-z-create-response>"
    payload: '{"event_type":"{{ trigger.event }}","entity_id":"{{ trigger.entity_id }}","new_state":"{{ states(trigger.entity_id) }}"}'
```

**Endpointy (per-user):**

| Endpoint | Popis |
|---|---|
| `GET /api/ha/config` | Seznam mých domovů (bez tokenů) |
| `GET /api/ha/config/<home_id>` | Detail domova (bez tokenu) |
| `POST /api/ha/config` | Přidat domov (auto-test connection před save) |
| `PUT /api/ha/config/<home_id>` | Upravit (label / url / token / default) |
| `DELETE /api/ha/config/<home_id>` | Smazat domov |
| `POST /api/ha/config/<home_id>/test` | Otestovat spojení |
| `POST /api/ha/config/<home_id>/default` | Nastavit jako výchozí |

**Akce + status (per-user):**
Standardní endpointy `/api/ha/status`, `/devices`, `/action`, `/sensors`, `/rooms`
nyní automaticky používají **přihlášený uživatel → jeho výchozí domov**. Volitelně
`?home=<home_id>` pro konkrétní dům, pokud má jich víc.

Když uživatel nemá žádný domov nakonfigurovaný, endpointy fallback-ují na
globální env-var klient (`HA_URL`/`HA_TOKEN` — admin / dev mode).

---

## Hardware plán — STARTER KIT (proforma O36312996)

První várka, na které doděláváme Domácnost do plné funkčnosti:

| Položka | SKU | Role | ks |
|---|---|---|---|
| **TP-Link Tapo H110** | TPL000016 | 📡 **Hub** — gateway pro Tapo senzory (musí být přidaný PRVNÍ) | 1 |
| **TP-Link Tapo P115** | TPL000269 | 🔌 Mini smart zásuvka (Wi-Fi, energie monitor) | 2 |
| **TP-Link Tapo T100** | TPL000199 | 🚶 Pohybový senzor (přes Hub) | 1 |
| **TP-Link Tapo T110** | TPL000200 | 🚪 Senzor dveří/okna (přes Hub) | 1 |
| **TP-Link Tapo L510E** | SKTLNTapoL510E | 💡 Stmívatelná Wi-Fi žárovka E27 | 1 |
| **Canyon OnMove 11** | HA1CNECBTSP11 | 🔊 Bluetooth speaker 20W IPX6 (TWS) | 1 |

**Celkem ~2 873 Kč** (cena s DPH).

### Klíčové důsledky pro setup

- **Žádný Zigbee2MQTT není potřeba** — Tapo H110 mluví Wi-Fi/proprietárním protokolem,
  HA má vestavěnou `tplink` integration, která auto-discovery udělá přes mDNS na portu 9999.
- **Žádný Sonoff dongle ani Raspberry Pi** v této etapě — stačí mini PC s HAOS (volitelné),
  nebo dokonce jen Tapo aplikace + Radim cloud.
- **Pořadí párování JE důležité**:
  1. **Tapo H110 Hub** ⇒ musí být první, sub-senzory bez něj nepojedou
  2. Tapo P115 plugs (×2)
  3. Tapo T100 motion ⇒ páruje se přes Hub
  4. Tapo T110 contact ⇒ páruje se přes Hub
  5. Tapo L510E bulb ⇒ samostatně, Wi-Fi
  6. Canyon OnMove ⇒ Bluetooth k zařízení s Radimem (telefon / tablet / NUC)

  Backend tohle vynucuje: pokud uživatel zkusí přidat T100 bez Hubu, vrátí
  **HTTP 412 Precondition Failed** s hláškou *„Než přidáte senzor pohybu, musíte
  nejdřív přidat Tapo Hub."*

### Volitelné rozšíření (mimo starter kit)

| Zařízení | Kdy přidat |
|---|---|
| **Lenovo TinyPC / Intel NUC** | Až budeš chtít automatizace bez cloudu (HA OS) |
| **Detektor kouře** (Tapo S200B nebo Heiman) | Brzy — CRISIS protokol pro hašení |
| **SOS knoflík** (Tapo S200B konfigurace) | Pro seniora, který si zapomíná telefon |
| **Wearable** (Withings / Fitbit) | Když je třeba sledování tepu/pádu |
| **BT teploměr** (Xiaomi LYWSD03MMC ~150 Kč) | Levný způsob měřit teplotu/vlhkost |
| **BT vážka / tlakoměr** (Withings, Xiaomi) | Pravidelné zdravotní měření |

### 🌐 Síťové požadavky — KRITICKÉ pro Tapo

Tapo zařízení komunikují s HA přes **mDNS multicast (port 5353)**, který
**neprojde přes router** mezi sítěmi. Plus Tapo lokální API běží na
portech **9999** (legacy) a **80** (KLAP).

**Co musí platit:**
1. **Stejná Wi-Fi** — Tapo Hub i HA musí být ve stejné fyzické síti.
   Nepoužívejte guest Wi-Fi pro Tapo, ta většinou izoluje klienty.
2. **Stejný subnet** — typicky `192.168.1.0/24` nebo `192.168.0.0/24`.
   Pokud máš víc Wi-Fi (5 GHz vs 2.4 GHz) na stejném routeru, většinou
   sdílí subnet — zkontroluj v admin UI routeru.
3. **DHCP rezervace** pro Tapo zařízení — najdi MAC adresu Tapo Hubu
   v admin UI routeru a přiřaď mu **fixní IP** (např. 192.168.1.50).
   Bez rezervace se IP po čase změní a Radim zařízení ztratí.
4. **Tapo H110 musí být na 2.4 GHz** — H110 nepodporuje 5 GHz Wi-Fi.
   Pokud máš jen 5 GHz, povol na routeru kombinovaný 2.4+5 GHz mód.

**Diagnostika v Radim aplikaci:**
- Domácnost → ➕ Přidat zařízení → klepni na Tapo zařízení
- Wizard ti ukáže preflight obrazovku s IP HA + subnetem + reachability
- `GET /api/ha/network/info` (vyžaduje JWT) vrátí JSON se vším:
  ```json
  {
    "ha_ip": "192.168.1.10",
    "ha_port": 8123,
    "subnet_human": "192.168.1.x",
    "is_private": true,
    "ha_reachable": true,
    "warnings": [...]
  }
  ```

### 🔵 Bluetooth podpora

HA má vestavěnou `bluetooth` integration, která auto-discoveruje BLE
zařízení v dosahu (~10 m vnitřek, méně přes zdi). Wizard má 3 BT typy:

| Typ | Co umí | Příklad zařízení |
|---|---|---|
| **Bluetooth zařízení (auto-scan)** | 60s scan, ukáže seznam | jakýkoliv BTHome 2.0, Xiaomi BLE, Govee, Switchbot |
| **BT teploměr** | Pre-konfigurovaný flow | Xiaomi LYWSD03MMC (~150 Kč) |
| **BT vážka / tlakoměr** | Pre-konfigurovaný flow | Xiaomi Body Composition, Withings BPM Core |

**Jak BT scan funguje pod kapotou:**
1. Snapshot existujících `sensor.*` + `binary_sensor.*` v HA
2. Spustí se 60s polling (každé 3s znovu fetch states)
3. Hledá nové entity, které vypadají jako BT (entity_id obsahuje
   `xiaomi_`, `govee_`, `switchbot_`, `bthome_`, atributy mají MAC)
4. Pokud najde **1**: auto-pair, vyplní `device_assignments`
5. Pokud najde **víc**: status `choose_candidate`, frontend ukáže
   seznam k výběru
6. Po 60s bez nálezu: `timeout`, uživatel zkusí znovu

**Hardware pro BT na NUC / RPi:**
- Lenovo TinyPC / Intel NUC mají vestavěné BT
- Raspberry Pi 4/5 mají vestavěné BT (BCM43455)
- Pro lepší dosah: USB BT 5.0 dongle (~200 Kč)
- Pro pokrytí celého bytu: ESPHome **bluetooth_proxy** na ESP32 v každé místnosti

### 🔗 Quick link na HA dashboard

V wizardu na konci výběru zařízení a v preflight obrazovce je tlačítko
**🔗 Otevřít HA dashboard**, které otevře `<ha_url>/lovelace/home/overview`
v novém okně. Užitečné pro technika při finálním ladění.

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
