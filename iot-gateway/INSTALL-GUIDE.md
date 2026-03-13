# Radim Care — Kompletní instalační manuál pokoje

> Čas instalace: ~2 hodiny na první pokoj, ~45 min na další

---

## 📦 FÁZE 0: Co potřebuješ na stůl před instalací

### Hardware (1 pokoj):

| # | Položka | Model | Cena (Kč) | Kde koupit |
|---|---------|-------|-----------|------------|
| 1 | Tablet | Samsung Galaxy Tab A9 10.5" | ~5 500 | Alza, CZC |
| 2 | Tablet stojan | Nastavitelný na stůl/zeď | ~400 | Amazon CZ |
| 3 | Teploměr + vlhkoměr | Aqara WSDCGQ11LM (Zigbee) | ~450 | Alza |
| 4 | Pohybový senzor | Aqara RTCGQ11LM (Zigbee) | ~400 | Alza |
| 5 | Dveřní kontakt | Aqara MCCGQ11LM (Zigbee) | ~350 | Alza |
| 6 | SOS tlačítko | Aqara WXKG11LM (Zigbee) | ~300 | Alza |
| 7 | (volitelně) Senzor pádu | Aqara FP1 (Zigbee, mmWave) | ~1 200 | Alza |
| 8 | Napájecí adaptér tablet | USB-C 15W | (v balení) | — |
| 9 | Oboustranná lepicí páska | 3M Command Strips | ~150 | Bauhaus |

### Centrální gateway (1× pro celý objekt / patro):

| # | Položka | Model | Cena (Kč) |
|---|---------|-------|-----------|
| 1 | Raspberry Pi 5 (4GB) | RPi 5 Model B | ~2 200 |
| 2 | Zigbee USB koordinátor | SONOFF ZBDongle-E (EFR32MG21) | ~600 |
| 3 | microSD karta 32GB+ | SanDisk Endurance | ~300 |
| 4 | Napájecí zdroj RPi | USB-C 27W oficální | ~350 |
| 5 | Ethernet kabel | CAT6 (RPi → router) | ~100 |
| 6 | Plastová krabička RPi | oficiální case | ~250 |

### Software (zdarma):
- Home Assistant OS (image pro RPi 5)
- Zigbee2MQTT (addon)
- File Editor (addon)

### Nářadí:
- [ ] Notebook/PC pro konfiguraci
- [ ] Šroubovák (montáž stojanu)
- [ ] Žebřík (pohybový senzor pod strop)
- [ ] Telefon s QR čtečkou (párování senzorů)
- [ ] Wi-Fi heslo objektu

---

## 🔧 FÁZE 1: Příprava Raspberry Pi Gateway
> Jednorázově pro celý objekt (15-30 min)

### Krok 1.1 — Flash Home Assistant OS

```bash
# Na PC/Macu:
# 1. Stáhni Raspberry Pi Imager z https://www.raspberrypi.com/software/
# 2. Vlož microSD kartu do čtečky
# 3. V Imager:
#    - OS: "Other specific-purpose OS" → "Home assistants" → "Home Assistant" → "Home Assistant OS 14.x (RPi 5)"
#    - Storage: tvoje microSD karta
#    - Klikni "Write"
# 4. Po zápisu vyjmi kartu
```

### Krok 1.2 — Fyzická instalace RPi

```
1. Vlož microSD kartu do Raspberry Pi 5
2. Připoj Ethernet kabel (RPi → router/switch)
3. Zasuň Zigbee USB dongle (SONOFF ZBDongle-E) do USB portu
4. Připoj napájecí zdroj → RPi se zapne
5. Počkej 5-10 minut (první boot je pomalý)
```

**Umístění RPi:**
- Ideálně v technické místnosti / rozvaděči
- Zigbee dosah: ~10-15m přes zeď, ~30m přímá viditelnost
- Pro větší objekty: přidat Zigbee router (např. IKEA Tradfri zásuvka ~200 Kč)

### Krok 1.3 — První přístup k Home Assistant

```
1. Na PC otevři prohlížeč: http://homeassistant.local:8123
   (nebo http://IP_ADRESA_RPI:8123)

2. Vytvoř admin účet:
   Jméno: radim-admin
   Heslo: [bezpečné heslo — zapiš do trezoru hesel!]

3. Vyber lokaci (pro časové zóny)
   → Czech Republic, Prague

4. Přeskoč integrace (nastavíme manuálně)
```

### Krok 1.4 — Instalace Zigbee2MQTT

```
1. Settings → Add-ons → Add-on Store
2. Vpravo nahoře ⋮ → Repositories
3. Přidej: https://github.com/zigbee2mqtt/hassio-zigbee2mqtt
4. Refreshni stránku
5. Najdi "Zigbee2MQTT" → Install
6. Po instalaci → Configuration tab:
```

**Zigbee2MQTT konfigurace:**
```yaml
# V Configuration tabu add-onu:
data_path: /config/zigbee2mqtt
socat:
  enabled: false
mqtt:
  server: mqtt://core-mosquitto:1883
  user: ""
  password: ""
serial:
  port: /dev/ttyUSB0    # nebo /dev/ttyACM0 pro ZBDongle-E
  adapter: ember         # pro EFR32MG21 (ZBDongle-E)
advanced:
  network_key: GENERATE  # automaticky vygeneruje klíč
  pan_id: GENERATE
frontend:
  port: 8080
```

```
7. Nejdřív nainstaluj Mosquitto Broker:
   Settings → Add-ons → Mosquitto broker → Install → Start

8. Pak Start Zigbee2MQTT
9. Ověř: http://homeassistant.local:8080 (Zigbee2MQTT frontend)
   → Měl bys vidět "Coordinator" jako jediné zařízení
```

### Krok 1.5 — Instalace File Editor

```
1. Settings → Add-ons → File editor → Install → Start
2. Zapni "Show in sidebar"
   → Budeme potřebovat pro YAML konfigurace
```

---

## 📡 FÁZE 2: Párování senzorů (per pokoj, ~15 min)

### Obecný postup párování:

```
1. Otevři Zigbee2MQTT frontend: http://homeassistant.local:8080
2. Klikni "Permit join (All)" vpravo nahoře
3. Na senzoru stiskni párování (viz níže per typ)
4. Do 30 sekund se senzor objeví v seznamu
5. Přejmenuj zařízení podle konvence (viz tabulka)
```

### Konvence pojmenování:

```
zigbee_[typ]_[pokoj]
Příklady:
  zigbee_temp_A12        — teploměr v pokoji A-12
  zigbee_motion_A12      — pohybový senzor A-12
  zigbee_door_A12        — dveřní kontakt A-12
  zigbee_sos_A12         — SOS tlačítko A-12
  zigbee_fall_A15        — senzor pádu A-15
  zigbee_hum_A12         — vlhkoměr A-12
```

### 2.1 — Aqara Teploměr + Vlhkoměr (WSDCGQ11LM)

```
Párování:
  1. Najdi malý reset otvor na boku
  2. Drž reset jehličkou 5 sekund → LED blikne 3×
  3. V Zigbee2MQTT se objeví "0x00158d0..."
  4. Přejmenuj na: zigbee_temp_A12

Umístění:
  - Na noční stolek nebo komodu
  - Výška: ~1m od podlahy
  - NE u okna, topení, nebo přímého slunce
  - Přilep oboustrannou páskou

Ověření:
  - V HA: States → sensor.zigbee_temp_A12 → zobrazí teplotu
  - Automaticky reportuje každých 60 minut nebo při změně >0.5°C
```

### 2.2 — Aqara Pohybový senzor (RTCGQ11LM)

```
Párování:
  1. Drž reset jehličkou 5 sekund → LED blikne
  2. Přejmenuj na: zigbee_motion_A12

Umístění:
  ⭐ KRITICKÉ — toto je nejdůležitější senzor!
  - Pod strop, v rohu místnosti
  - Směrem k lůžku + cestě na WC
  - Detekční úhel: 170°, dosah: 7m
  - NE směrem k oknu (falešné triggery od slunce)

  Ideální pozice:
  ┌─────────────────────┐
  │  🛏️ postel          │
  │                     │
  │         [senzor]→📡 │  ← v rohu pod stropem
  │                     │
  │  cesta na WC →  🚪  │
  └─────────────────────┘

Ověření:
  - Projdi se před senzorem
  - V HA: States → binary_sensor.zigbee_motion_A12 → "on"
  - Reset na "off" po 60s bez pohybu

Baterie:
  - CR2450, vydrží ~2 roky
```

### 2.3 — Aqara Dveřní kontakt (MCCGQ11LM)

```
Párování:
  1. Drž reset 5s → LED blikne
  2. Přejmenuj na: zigbee_door_A12

Umístění:
  - Hlavní vstupní dveře pokoje
  - Magnet na dveře, senzor na zárubeň
  - Přilep 3M páskou
  - Mezera max 15mm

  Schéma:
  ╔═══╗
  ║   ║ zárubeň → [senzor]
  ║   ║ dveře   → [magnet]
  ╚═══╝

Ověření:
  - Otevři/zavři dveře
  - HA: binary_sensor.zigbee_door_A12 → on/off
```

### 2.4 — Aqara SOS Tlačítko (WXKG11LM)

```
Párování:
  1. Drž tlačítko 5s → LED blikne
  2. Přejmenuj na: zigbee_sos_A12

Umístění:
  ⭐ KRITICKÉ — musí být snadno dostupné!
  - Varianta A: Na nočním stolku (oboustranná páska)
  - Varianta B: Na stěně u postele (výška ~80cm)
  - Varianta C: Na stolku u křesla

  ⚠️ Senior MUSÍ vědět kde je a jak ho zmáčknout!
  → Přilep výrazný štítek: "SOS 🆘 NOUZOVÉ TLAČÍTKO"

Ověření:
  - Stiskni tlačítko → LED blikne
  - HA: sensor.zigbee_sos_A12 → event triggered
  - Backend: měl by přijít CRITICAL alert

Baterie:
  - CR2032, vydrží ~2 roky
```

### 2.5 — Aqara FP1 Senzor přítomnosti/pádu (volitelně)

```
Párování:
  1. Drž reset 5s → LED blikne
  2. Přejmenuj na: zigbee_fall_A15

Umístění:
  - Na stěně ve výšce 1.2-1.5m
  - Směrem k oblasti kde senior chodí
  - mmWave radar — detekuje i bez pohybu (sedí v křesle)

  ⚠️ POZOR: FP1 má občas false positives
  → Nakalibruj zóny v Zigbee2MQTT (10 min navíc)

Napájení:
  - USB-C (není bateriový!) → potřebuješ zásuvku
  - Kabel: 2-3m USB-C → přilep po stěně lištou
```

---

## ⚙️ FÁZE 3: Konfigurace Home Assistant (per instalace, ~20 min)

### Krok 3.1 — Nahrát konfigurační soubory

```
1. Otevři File Editor (sidebar → File editor)
2. Otevři /config/configuration.yaml
3. Na konec přidej:

rest_command: !include rest_commands.yaml
```

### Krok 3.2 — Vytvořit rest_commands.yaml

```
1. File Editor → New file → rest_commands.yaml
2. Zkopíruj obsah z: iot-gateway/rest_commands.yaml
```

### Krok 3.3 — Nastavit secrets

```
1. File Editor → /config/secrets.yaml (vytvoř pokud neexistuje)
2. Přidej:

radim_api_url: "https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/iot-bridge/data"
radim_iot_token: "y7ZhSCEcHFuzk3g5gdAfQZJuqhO1G7sfxGFEHeR1oH0"
```

### Krok 3.4 — Nahrát automatizace

```
1. File Editor → /config/automations.yaml
2. Zkopíruj automatizace pro DANÝ POKOJ z: iot-gateway/automations.yaml
   (nekopíruj všech 5 pokojů najednou — jen ty co jsi fyzicky nainstaloval)
3. Uprav entity_id podle skutečných jmen z Zigbee2MQTT
```

### Krok 3.5 — Restart a ověření

```
1. Settings → System → Restart
2. Počkej ~2 minuty
3. Developer Tools → Services:
   Service: rest_command.radim_iot_ingest
   Data:
     device_id: "test_manual"
     room_id: "room_A12"
     sensor_type: "temperature"
     value: "21.5"
     unit: "°C"
   → Call Service
4. Ověř na dashboardu: https://[frontend-url]/iot-dashboard.html
```

---

## 📱 FÁZE 4: Instalace tabletu (per pokoj, ~15 min)

### Krok 4.1 — Příprava tabletu

```
1. Rozbal Samsung Galaxy Tab A9
2. Zapni → projdi počáteční nastavení
3. Připoj na Wi-Fi objektu
4. Aktualizuj systém (Settings → Software update)
5. Nastav:
   - Display → Brightness: 60-70%
   - Display → Screen timeout: 30 minut (budeme overridovat)
   - Sound → Volume: 80%
   - Accessibility → Font size: Extra Large
```

### Krok 4.2 — Nainstaluj aplikaci

```
1. Otevři Chrome
2. Jdi na: https://[frontend-url]
3. Chrome nabídne "Add to Home screen" → Přidej
4. NEBO: ⋮ → "Install app" → Install
5. Vznikne ikona "Radim" na ploše
```

### Krok 4.3 — Kiosk mode (zamknutí na aplikaci)

```
1. Settings → Lock screen → Screen lock type → None
2. Settings → Digital Wellbeing → Screen time → OFF
3. Settings → Apps → Chrome → Permissions → vše Allow
4. Settings → Display → Screen timeout → 30 min

Pro plný kiosk (volitelně):
- Nainstaluj "Fully Kiosk Browser" (Play Store, ~6€ licence)
- URL: https://[frontend-url]
- Zapni: Stay Awake, Autostart, Lock task
```

### Krok 4.4 — Fyzická instalace

```
1. Připevni stojan na noční stolek nebo stěnu
2. Vlož tablet do stojanu
3. Připoj nabíjecí kabel (USB-C)
   → Kabel veď po stěně lištou, aby senior nezakopl
4. Nastav úhel: ~30° náklon pro čtení z postele

Ideální pozice:
  ┌─────────┐
  │ 📱      │  ← tablet na stojanu
  │ stojan  │
  └────┬────┘
       │
  ═════╧═════  ← noční stolek
```

---

## ✅ FÁZE 5: Verifikace celého pokoje (~10 min)

### Checklist per pokoj:

```
Pokoj: _______ (např. A-12)
Senior: _______ (např. Marie Novotná)
Datum: _______
Instaloval: _______

SENZORY:
[ ] Teploměr — zobrazuje teplotu v HA + dashboard
[ ] Vlhkoměr — zobrazuje vlhkost v HA + dashboard
[ ] Pohybový senzor — reaguje na pohyb (projdi se)
[ ] Dveřní kontakt — reaguje na otevření/zavření
[ ] SOS tlačítko — stisk → CRITICAL alert na dashboardu
[ ] (Senzor pádu — pokud instalován)

TABLET:
[ ] Zapnutý, nabitý, na stojanu
[ ] Radim aplikace se otevírá
[ ] Hlas Antonín funguje (Settings → Test hlasu)
[ ] Velké písmo, dobrý kontrast
[ ] Nabíjecí kabel bezpečně veden

BACKEND:
[ ] Senzorová data přicházejí na IoT Dashboard
[ ] Teplota se aktualizuje každých 5 min
[ ] SOS test → alert na dashboardu
[ ] Pečovatel přiřazen k pokoji v systému

BEZPEČNOST:
[ ] Kabely bezpečně vedeny (žádné riziko zakopnutí)
[ ] SOS tlačítko snadno dostupné z postele
[ ] Senior ví jak zmáčknout SOS
[ ] Senior ví jak ovládat tablet (základy)
[ ] Wi-Fi signal silný (min -70 dBm)
[ ] Zigbee signal OK (zkontroluj v Z2M → map)

KONTAKTY:
[ ] Pečovatel přiřazen: _________ (tel: _________)
[ ] Rodinný příslušník: _________ (tel: _________)
```

---

## 🔧 FÁZE 6: Registrace pokoje v backendu

### Automaticky (přes skript):

```bash
# Uprav setup_rooms.sh — přidej nový pokoj
# Nebo manuálně přes curl:

BASE="https://radim-brain-2025-be1cd52b04dc.herokuapp.com/api/iot-bridge"
TOKEN="y7ZhSCEcHFuzk3g5gdAfQZJuqhO1G7sfxGFEHeR1oH0"

# 1. Registruj zařízení
curl -X POST "$BASE/devices" \
  -H "Content-Type: application/json" \
  -H "X-IoT-Token: $TOKEN" \
  -d '{
    "device_id": "zigbee_temp_A12",
    "room_id": "room_A12",
    "user_id": "senior-001",
    "device_type": "temperature_sensor",
    "name": "Teploměr - Ložnice A12",
    "model": "Aqara WSDCGQ11LM"
  }'

# ... opakuj pro každý senzor v pokoji

# 2. Přiřaď pečovatele
curl -X POST "$BASE/caregivers" \
  -H "Content-Type: application/json" \
  -d '{
    "room_id": "room_A12",
    "name": "Jana Nováková",
    "phone": "+420777123456",
    "role": "caregiver"
  }'

# 3. Ověř dashboard
curl -s "$BASE/dashboard" | python3 -m json.tool
```

---

## ⚠️ TROUBLESHOOTING

### Senzor se nepáruje:
```
1. Zkontroluj baterii (nové baterie!)
2. Buď blíž ke koordinátoru (<3m pro párování)
3. Resetuj senzor (10s držení reset tlačítka)
4. Restartuj Zigbee2MQTT addon
5. Zkontroluj USB dongle — zkus jiný USB port
```

### Data nepřicházejí na backend:
```
1. HA → Developer Tools → Services → volej rest_command manuálně
2. Pokud 401: zkontroluj token v secrets.yaml
3. Pokud timeout: zkontroluj internet RPi (ping google.com)
4. Logy: Settings → System → Logs → hledej "rest_command"
```

### Zigbee signal slabý:
```
1. Přidej Zigbee router (IKEA Tradfri zásuvka ~200 Kč)
   → Zapoj do zásuvky mezi RPi a vzdálený pokoj
   → Zigbee mesh se automaticky posílí
2. Maximální vzdálenost: 10m přes 1 zeď, 5m přes 2 zdi
3. V Z2M: klikni na "Map" → vizualizace mesh sítě
```

### Tablet se nevypíná / screensaver:
```
1. Samsung: Settings → Display → Screen timeout → 30 min
2. Fully Kiosk: Settings → Screen → Screensaver timer
3. Vývojářský režim: Settings → About → 7× tap Build number
   → Developer options → Stay awake (when charging)
```

### SOS alert nepřijde SMS:
```
1. Zkontroluj: pečovatel přiřazen k pokoji?
   curl "$BASE/caregivers?room_id=room_A12"
2. Twilio číslo SMS-capable?
   → Twilio Console → Phone Numbers → ověř SMS capability
3. Test SMS: curl -X POST "$BASE/caregivers/test-sms"
4. Heroku logy: heroku logs -t -a radim-brain-2025 | grep SMS
```

---

## 📊 ČASOVÝ ODHAD

| Fáze | První pokoj | Další pokoje |
|------|-------------|-------------|
| Gateway (RPi + HA) | 30 min | 0 (jednorázově) |
| Párování senzorů | 20 min | 15 min |
| HA konfigurace | 20 min | 10 min |
| Tablet instalace | 15 min | 15 min |
| Verifikace | 10 min | 10 min |
| Backend registrace | 5 min | 5 min |
| **CELKEM** | **~100 min** | **~55 min** |

Pro 5 pokojů: ~100 + 4×55 = **~320 min (5.5 hodiny)**

---

## 🔐 BEZPEČNOSTNÍ POZNÁMKY

1. **IoT token** — nikdy nesdílej, rotuj každých 6 měsíců
2. **HA admin heslo** — uložit do správce hesel (Bitwarden)
3. **Wi-Fi** — WPA3 pokud možno, oddělený VLAN pro IoT
4. **Zigbee** — šifrovaný protokol (AES-128), bezpečný
5. **GDPR** — senzory nesbírají osobní data (jen teplota, pohyb)
6. **Fyzická bezpečnost** — RPi v uzamčené místnosti
