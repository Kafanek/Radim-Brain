# RadimCare Tapo Gateway

Local poller pro TP-Link Tapo zařízení v bytě seniora. Běží na mini PC
(Windows nebo Linux), čte stavy přes Tapo cloud + lokální API, posílá HTTP
POST na Heroku backend.

## Co Tapo API skutečně umí monitorovat (důležité!)

| Zařízení | Co můžeme vyčítat | Frekvence | Spolehlivost |
|----------|-------------------|-----------|--------------|
| **P115 zásuvka** | on/off state, current power (W), today energy (Wh), schedule | každých 30s | ★★★★★ |
| **L510E žárovka** | on/off, brightness 0–100%, color temp, schedule | každých 30s | ★★★★★ |
| **H110 hub** | online/offline, child device list, signal strength | každých 30s | ★★★★★ |
| **T100 motion** | last_motion_time (Unix), battery, signal | poll přes hub | ★★★★ pokud poll <60s |
| **T110 contact** | open/closed (live), last_change_time, battery | poll přes hub | ★★★★ pokud poll <60s |

### Co API NEUMÍ samo o sobě

- **Real-time push event stream** — Tapo cloud nemá veřejné webhooky pro tato
  zařízení. Vše musíme **pollovat** (default 30s).
- **Sub-30s detekce pohybu** — T100 to fyzicky pošle hubu okamžitě, ale do
  Tapo cloudu to teče s lagem 5–60 s + náš poll 30 s = average **45s latence**.
  Pro presence detection OK, pro real-time security ne.
- **Battery low push** — vidíme přes polling battery_level, alert si vyrobíme sami.
- **Firmware update** — můžeme detekovat změnu, ale ne intervenovat.

### Co můžeme z toho **odvodit** (Radim detektory)

| Detektor | Z jakých dat | Akce |
|----------|--------------|------|
| **Žádný pohyb 6+ h ve dne** | T100 last_motion_time | check-in alert sestře |
| **Otevřené dveře >30 min** | T110 contact_state long-on | safety check |
| **Světlo svítí 02:00–05:00** | L510E bulb_state + čas | nespí dobře, agent_loop observation |
| **Rychlovarka anomálie** | P115 power_w trend | nezvyklé chování / pád |
| **Žádný plug usage 24 h** | P115 power_w = 0 | senior nevařil → check-in |
| **Hub offline** | H110 online_state = 0 | technický alert (Wi-Fi výpadek?) |
| **Battery low** | T100/T110 battery <20% | maintenance alert pečujícímu |

Všechny tyto detektory jdou do `agent_observations` tabulky se severity →
caregiver_routes je vidí v dashboardu, popř. push notifikace při WARNING+.

## Architektura

```
   ┌─── Byt seniora (Háje) ─────────────────────────┐
   │                                                 │
   │   Wi-Fi router (192.168.1.1)                    │
   │        │                                        │
   │        ├── H110 hub (.53) ◄─Sub-1GHz─┬─T100     │
   │        │                              └─T110     │
   │        │                                        │
   │        ├── P115 #1 .50 (rychlovarka)            │
   │        ├── P115 #2 .51 (mikrovlnka)             │
   │        ├── L510E .52 (lampa ložnice)            │
   │        │                                        │
   │        ├── Mini PC Windows (tento gateway)      │
   │        │     └── tapo_gateway.py polluje 30s    │
   │        │                                        │
   │        └── Tablet seniora (PWA Radim)           │
   │             └── Bluetooth → Canyon OnMove 11    │
   └────────────────┬────────────────────────────────┘
                    │ HTTPS POST every 30s
                    │ /api/iot-bridge/data/batch
                    │ X-IoT-Token: ***
                    ▼
              ┌─────────────────────┐
              │  Heroku radim-brain │
              │  iot_sensor_data    │
              │  agent_loop detect. │
              │  caregiver dashboard│
              └─────────────────────┘
```

## Setup na Windows mini PC

### 1. Spárování zařízení (přes Tapo app na mobilu)

1. Stáhni **Tapo** z Google Play / App Store
2. Vytvoř účet `iot@radimcare.cz` (nebo použij existující)
3. **H110 hub** spáruj jako první (přidej do Wi-Fi 2.4 GHz, ne 5 GHz!)
4. **T100, T110** přidej **přes hub** (Tapo app → hub → "Add device")
5. **P115, L510E** přidej do Wi-Fi (ne přes hub)
6. **Pojmenuj zařízení** podle konvence:
   - „Pohyb obývák" (T100)
   - „Dveře vstup" (T110)
   - „Rychlovarka" (P115 #1)
   - „Mikrovlnka" (P115 #2)
   - „Lampa u postele" (L510E)
   - „Hub" (H110)

   Pojmenování má smysl — gateway parsuje keywords (`obyvak`, `kuchyne`,
   `loznice`, `chodba`) na room_id v naší databázi.

### 2. Static IP v routeru

Tapo přiřazuje IP přes DHCP — můžou se měnit. V routeru nastavit
**DHCP reservation** podle MAC pro každé Wi-Fi zařízení (5 kusů: H110,
2× P115, L510E + tablet). Bez toho by gateway po výpadku routeru hledal
zařízení na špatných IP.

### 3. Instalace gateway na mini PC

```cmd
REM jako Administrator:
mkdir C:\RadimCare
cd C:\RadimCare

REM Python 3.11+ z https://python.org (Add to PATH ✓)
pip install tapo aiohttp

copy tapo_gateway.py .
copy tapo_gateway.bat .
copy .env.example .env
notepad .env
REM ↑ vyplň TAPO_EMAIL, TAPO_PASSWORD, IOT_GATEWAY_TOKEN, RADIM_SENIOR_ID,
REM    a IP adresy zařízení
```

### 4. Task Scheduler (auto-start)

```
Trigger:  At system startup (čekat 30s pro Wi-Fi)
Action:   C:\RadimCare\tapo_gateway.bat
User:     SYSTEM (běží i bez přihlášení)
Settings:
  • If task fails, restart every 1 minute
  • Attempt to restart up to 999 times
  • Run task as soon as possible after a scheduled start is missed
```

### 5. Smoke test

```cmd
cd C:\RadimCare
tapo_gateway.bat
REM Otevři gateway.log, hledej "POSTed N readings → 200"
```

## Bezpečnost

- `IOT_GATEWAY_TOKEN` je shared secret mezi gateway a Heroku. Při kompromitaci
  rotovat: `heroku config:set IOT_GATEWAY_TOKEN=<new>` + update všech `.env`
- `.env` soubor s heslem **nikdy** v gitu (`.gitignore`)
- TP-Link účet by měl mít **2FA enabled** v Tapo app
- Na mini PC: BitLocker disk encryption + Windows password
- Senior tablet: PIN/PIN-pattern, bez admin práv

## Pokud TP-Link cloud spadne

Gateway se pokusí lokální API (přímý TCP na IP zařízení) — to funguje
i bez internetu pro P115, L510E, H110. T100/T110 jsou stále závislé na hubu.

Z Heroku to ale neuvidíme dokud internet nebude zpět. **Upgrade**: lokální
SQLite cache + replay-on-reconnect (TODO v2.1).

## Údržba

- Logy: `C:\RadimCare\gateway.log` (rotuj manuálně každý měsíc)
- Update gateway: kopíruj nový `tapo_gateway.py` + restart Task Scheduler
- Battery T100/T110: vyměň při <20% (alert přijde do dashboardu)
- Test SOS path: 1× měsíčně otevři dveře, zkontroluj že observation projde
  do dashboardu sestry do 60 s
