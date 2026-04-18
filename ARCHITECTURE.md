# 🏛️ RADIM Care — Architektura systému

**Stav**: produkční, v10.41 · **Heroku v632+** · **Frontend CF Pages v32.5.0+** · **Datum**: 2026-04-18

Tento dokument popisuje **jak** systém funguje. Pro **co** v systému je, viz [SYSTEM_INVENTORY.md](./SYSTEM_INVENTORY.md).

---

## 1. Vrstvy

```
┌─────────────────────────────────────────────────────────────────┐
│  KLIENT — Senior / Rodina / Pečovatel / Admin                   │
│  Browser (Chrome, Safari) → PWA / mobilní Safari                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MARKETING WEB (radimcare.cz)                                   │
│  Cloudflare Pages · Astro 5 + MDX · static-first, SEO           │
│  14 stránek · "Zeptat se Radima" chat widget                    │
└────────────────────────────┬────────────────────────────────────┘
                             │  CTA "Přihlásit se / Vyzkoušet"
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  APLIKACE (app.radimcare.cz)                                    │
│  Cloudflare Pages · Vanilla JS + Service Worker                 │
│  29 section modulů · 68 top-level services · PWA offline        │
└────────────────────────────┬────────────────────────────────────┘
                             │  JWT Bearer + XHR/fetch + SocketIO
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  BACKEND (radim-brain-2025.herokuapp.com)                       │
│  Flask 2.x · Python 3.13 · gunicorn + eventlet                  │
│  47 blueprintů · 145 Python modulů                              │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┬───────┘
   │          │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌────────┐ ┌────────┐ ┌─────────┐ ┌───────┐ ┌────────┐
│  PG  │ │ Azure  │ │ Gemini │ │Anthropic│ │Twilio │ │ SMTP   │
│ 1GB  │ │  TTS   │ │  API   │ │  Claude │ │ voice │ │ Wedos  │
│ EU   │ │ WE-EU  │ │ Google │ │   AI    │ │ + SMS │ │ EU     │
└──────┘ └────────┘ └────────┘ └─────────┘ └───────┘ └────────┘
```

---

## 2. Hlavní datové toky

### 2.1 Registrace → onboarding → první den

```
Senior (browser) ──POST /api/auth/register──▶ Backend
                                                 │
                                                 ├─▶ auth_users INSERT
                                                 ├─▶ JWT HS256 vygenerováno (30 dní)
                                                 ├─▶ onboarding_routes.send_welcome_email()
                                                 │       └─▶ SMTP Wedos (info@radimcare.cz)
                                                 └─▶ 200 { token, user, onboarding:{show_wizard} }

Senior načte app.radimcare.cz
        │
        ├─▶ OnboardingWizard.init() po 1.5 s
        │       ├─▶ GET /api/onboarding/status
        │       └─▶ otevře modál s 4 kroky
        │
        ├─ krok 1 Profile  ──POST /api/memory/profile──▶ memory_profiles INSERT
        │                  ──POST /api/onboarding/step──▶ mark 'profile' done
        │
        ├─ krok 2 Family   ──POST /api/family/link/invite──▶ senior_family_links row
        │                                                   └─▶ SMTP invite email
        │                  ──POST /api/onboarding/step──▶ mark 'family' done
        │
        ├─ krok 3 Festive  ──PUT /api/festive-greeting/template──▶ save + preview
        │                  ──POST /api/onboarding/step──▶ mark 'festive' done
        │
        └─ krok 4 SOS      (vysvětlující karta, žádný call)
                           ──POST /api/onboarding/step──▶ mark 'sos_test' done
                           └─▶ finale: window.festiveGreeting.speak() (FESTIVE TTS)
```

### 2.2 Denní chod — typický den

```
08:00 │ WakeWordManager.wakeUp()
      │     ├─▶ window.festiveGreeting.greetOnWake()
      │     │       └─▶ GET /api/festive-greeting (cache 1 h)
      │     │       └─▶ window.speak(text, {mode: 'FESTIVE'})
      │     │            └─▶ /api/azure/tts proxy → Azure Speech Services
      │     └─▶ markLastGreetedToday() (localStorage, 1×/den)
      │
08:00 │ APScheduler cron "morning_checkin"
      │     └─▶ agent_loop.run_morning_checkin()
      │            └─▶ připomenutí léků, check na vitální v profilu
      │
10:30 │ Senior jde ven, IoT motion senzor v chodbě detekuje
      │     └─▶ POST /api/iot-bridge/sensor → iot_sensor_data
      │
14:00 │ APScheduler cron "daily_engagement"
      │     └─▶ návrh aktivity podle profilu (kvíz / cvičení / hudba)
      │
KAŽDÝCH 5 min │ agent_cycle — behavior_baseline.check_deviations()
KAŽDÝCH 5 min │ radim_reminders (úkoly, léky)
KAŽDÝCH 5 min │ telemed_reminders (konzultace)
KAŽDÝCH 10 s  │ sos_escalator_tick (jen pokud nějaký sos_event bez ack)
KAŽDÝCH 15 min│ health_agent (vitální + drug interactions)
KAŽDÝ DEN 20h │ daily_summary (rodina dostane in-app souhrn dne)
KAŽDÝ DEN 03h │ daily_cleanup (stará data, observations >30 d, brain_states >90 d)
```

### 2.3 SOS flow (konferenční demo + produkce)

```
Senior stiskne SOS (3-s podržení na SosButton.js)
    │
    ├─▶ POST /api/sos/trigger {source, message}
    │      │
    │      ├─▶ sos_events INSERT (stage=0)
    │      ├─▶ notify_senior_family(type='sos', severity='crisis')
    │      │       │
    │      │       ├─▶ Load senior_family_links (confirmed, opt-in notify_on_sos=true)
    │      │       ├─▶ Pro každého linked family:
    │      │       │     ├─▶ user_notifications INSERT
    │      │       │     ├─▶ SocketIO emit 'notification:new' → user_{id} room
    │      │       │     └─▶ WebPush (pokud má push_subscriptions)
    │      │       └─▶ Fallback: memory_profiles.caregiver_id (legacy 1-to-1)
    │      │
    │      ├─▶ agent_observations INSERT (audit stopa)
    │      └─▶ _ha_crisis_actions() — světla, rolety, dveře (HA nebo mock)
    │
    ▼ Po 30 s, pokud žádný ack:
    │
    ├─▶ sos_escalator_tick (stage 1)
    │      └─▶ notify_senior_family(title="STÁLE SOS — bez reakce 30 s")
    │
    ▼ Po 120 s, pokud žádný ack:
    │
    ├─▶ sos_escalator_tick (stage 2)
    │      ├─▶ SELECT contacts WHERE sos_priority=1 ORDER BY ASC LIMIT 1
    │      ├─▶ twilio_voice_helpers.initiate_proactive_call() → Twilio call
    │      └─▶ Fallback pokud Twilio blokován: další in-app wave
    │
    ▼ Po 300 s, pokud stále nic:
    │
    └─▶ sos_escalator_tick (stage 3)
           └─▶ notify(senior_id, "🚑 Mám zavolat 155?")


Rodinný člen klikne ✅ "Už řeším" v NotificationBell:
    │
    └─▶ POST /api/sos/<id>/ack
           ├─▶ sos_events UPDATE ack_by_user_id = me, ack_at = NOW()
           ├─▶ Eskalace se zastaví (escalator_tick vidí ack_by_user_id NOT NULL)
           ├─▶ Notifikace všem ostatním family: "{kdo} už to řeší"
           └─▶ Notifikace seniorovi: "Rodina reaguje"
```

### 2.4 Chat flow (senior ↔ Radim AI)

```
Senior napíše zprávu v chatu
    │
    ├─▶ POST /api/radim/chat {message, user_id}
    │      │
    │      ├─▶ intent_resolver.try_local_intent()
    │      │      └─▶ Pokud match (nameday, weather, time, …) → okamžitá odpověď bez AI
    │      │
    │      ├─▶ memory_helpers.load_history(user_id, last=15)
    │      ├─▶ context_builder.assemble() — profil, φ konstanty, brain_state
    │      ├─▶ brain_math.compute_psi_state(user_id) → C, E, R, S
    │      ├─▶ Gemini 2.0 Flash API (primary)
    │      │      └─▶ Fallback: Claude Opus (radim_ai_engine)
    │      │
    │      ├─▶ voice_filter.build_radim_ssml(text, mode=brain_mode)
    │      │      ├─▶ VOICE_PROFILES[mode] (HARMONY/ALERT/CRISIS/FESTIVE/…)
    │      │      ├─▶ rtcf_voice modifiers (rate, pauses podle BPM)
    │      │      └─▶ _add_pause_variability(mode=phi/random/breath)
    │      │
    │      ├─▶ brain_states INSERT (C, E, R, S, alpha, mode, coherence)
    │      └─▶ 200 { reply, ssml, voice_mode, brain_state }
    │
    └─▶ Frontend: RadimSimpleChat
           ├─▶ append message bubble
           └─▶ window.speak(text, {ssml, mode}) → TTS
```

---

## 3. Deploy + infrastruktura

### 3.1 Backend — Heroku

```
radim-brain-2025 (Eco dyno, PostgreSQL Essential-0)
  Procfile: web: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT --timeout 120 app:app
  Stack: heroku-24, Python 3.13
  Region: EU Dublin (GDPR compliance)
  
  DB: DATABASE_URL → postgres://…eu.heroku.com
      18.7 MB / 1 GB (1.8%) — >500× rezerva pro prvních 100 userů
      Connections: 2/20 baseline
      PG 17.6, WAL continuous protection
  
  Deploy:
    git push heroku heroku-deploy-fix:main
    → Heroku buildpack (Python requirements.txt)
    → Release phase (DB migrations via database_schema.init_db)
    → 11 APScheduler jobs startují v app.py __main__
  
  Env config: ~30 vars (DATABASE_URL, SECRET_KEY, JWT_SECRET, API keys,
                          feature flags, SMTP creds)
```

### 3.2 Frontend — Cloudflare Pages

```
radimcare-app (app.radimcare.cz)
  Build: vanilla JS, npm run build → dist/
         PurgeCSS → minify JS → bundle 3 chunks (head/services/app)
         CSS: 33 files → radim-all.css (s ?h= hash cache-bust)
  SW: service-worker.js s CACHE_VERSION (aktuálně v32.5.0)
      Network-first JS/CSS (3s timeout), cache-first images
      Precache: 53 core files
  
  Deploy: wrangler pages deploy dist --project-name=radimcare-app
  
radimcare-web (radimcare.cz marketing)
  Build: Astro 5 + MDX → 15 statických stránek
  Features: hero landing, 3 persony, srovnávací tabulka, FAQ,
            plovoucí "Zeptat se Radima" chat widget (volá /api/radim/chat demo mode)
  
  Deploy: npm run deploy (Astro build + wrangler)
```

### 3.3 External services

| Služba | Použití | Region | Poznámka |
|---|---|---|---|
| **Azure Speech Services** | TTS — český hlas Antonín Neural | West Europe | Primary TTS provider, SSML podporuje φ-pauzy |
| **Gemini 2.0 Flash** | AI chat, intent handling | Google Cloud | Primary LLM, ~1s latence |
| **Anthropic Claude** | Fallback LLM při Gemini rate-limit | Anthropic cloud | Secondary, používá se jen když Gemini selže |
| **Twilio Voice + SMS** | Proactive calls + fallback SMS | EU | Ale: aktuálně `FAKE_SMS_MODE=true` flag |
| **SMTP Wedos** | `mail.radimcare.cz:465` SSL, odesílatel `info@radimcare.cz` | ČR | Welcome/reset/invite emaily |
| **Jitsi Meet** | Video hovory v calls-module | meet.jit.si public | WebRTC, bez nutnosti instalace |
| **Cloudflare Pages** | Hosting frontu (app + marketing) | Global CDN | Free tier |

---

## 4. Bezpečnost + GDPR

### 4.1 Vrstvy obrany

```
┌─────────────────────────────────────────────────────────────┐
│ 1. TLS 1.3 end-to-end                                       │
│    - Cloudflare terminates, Heroku terminates                │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 2. CORS whitelist                                           │
│    - Allowed origins: app.radimcare.cz, localhost dev        │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 3. JWT auth                                                 │
│    - HS256, 30d expiry, signed with SECRET_KEY               │
│    - Stored in localStorage[radim_jwt] + sessionStorage      │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 4. Role-based access                                        │
│    - require_auth / require_premium / require_admin          │
│    - X-Admin-Secret bypass for ops endpoints                 │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 5. Rate limiting                                            │
│    - Per user, per endpoint, sliding window                  │
│    - SOS 5/min, Family invite 10/hour, Chat 60/min          │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 6. Input validation + SQL injection protection              │
│    - Parametrized queries (?), db_insert() helper            │
│    - input_sanitizer.py for XSS prevention                   │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 7. Safe Web Agent                                           │
│    - Allowlist domains (trusted Czech media, Wikipedia, …)   │
│    - SSRF defense (block private IPs, metadata endpoints)    │
│    - Content-type filter (no binary, no download)            │
│    - Sensitive page detection (login / payment / banking)    │
│    - Privacy-minimal audit (host-only, never full URL)       │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│ 8. GDPR compliance layer                                    │
│    - Article 20: /api/gdpr/export/<uid> → complete JSON      │
│    - Article 17: /api/gdpr/erase/<uid> → cascade delete      │
│    - Audit log: 36 months retention (legal proof)            │
│    - Retention policies per data class (brain_states 90d, …) │
│    - No data outside EU                                      │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Data retention schedule

| Data class | Retention | Auto-cleanup job |
|---|---|---|
| brain_states | 90 dnů | daily_cleanup (3:00 AM) |
| agent_observations | 30 dnů | daily_cleanup |
| memory_history | 90 dnů | daily_cleanup |
| iot_sensor_data | 30 dnů | daily_cleanup |
| safe_web sessions | 15 min TTL (in-memory only) | every-access + daily |
| user_notifications | forever (user-controlled delete) | — |
| contacts, senior_family_links | forever (user-controlled) | — |
| audit_log | 365 dnů (GDPR), 36 měsíců po erase | manual |
| sos_events | 365 dnů | manual |

---

## 5. Klíčová rozhodnutí (decision records)

### 5.1 Proč Flask monolith místo mikroslužeb
- **1 tým, 1 deploy** = nižší operační náklady
- Všech 47 blueprintů sdílí stejný DB connection pool, stejný JWT kontext
- Deploy atomický — rollback = revert commit
- **Náklady**: 1 Heroku dyno místo 10+
- Budoucnost: pokud některý BP zatíží CPU / paměť, lze vydělit (např. AI pipeline)

### 5.2 Proč PostgreSQL + SQLite dual-mode
- Lokální vývoj + pytest běží na SQLite (rychlé, zero config)
- Produkce na PostgreSQL (ACID, JSONB, fulltext)
- `database.py` abstraction: PgCursorWrapper + DictRow
- **Nuance**: PostgreSQL je přísnější s boolean (int 1/0 vs bool) — v v10.41.2-3 opraveno

### 5.3 Proč vanilla JS místo React/Vue na aplikaci
- **Žádný build step** pro vývoj jednotlivých section modulů
- Starší prohlížeče (iPad seniora 2018) = kompatibilita
- Service Worker + PWA = offline-capable
- **Cena**: každý modul si píše vlastní render (žádný framework state)
- Kompromis: konvence `window.xxxModule.init()` + self-healing dispatcher v radim-core.js

### 5.4 Proč APScheduler místo Celery/Redis
- Jedno dyno, žádný separátní worker potřeba
- 11 jobů stačí — všechny < 1 s práce
- **Limit**: při výpadku dyna se joby neprovedou (missed fires)
- Řešení: `misfire_grace_time` parameter + manuální trigger `run_escalator_tick(app)` z appky

### 5.5 Proč SocketIO + WebPush dvě vrstvy
- **SocketIO** — když je senior/rodina online, okamžitá notifikace bez polling
- **WebPush (VAPID)** — když jsou offline / app zavřená, notifikace dorazí přes OS
- Obě vrstvy v `notification_helpers.notify()` — jedna hluchá, druhá slyší

### 5.6 Proč "in-app" notifikace místo SMS
- Twilio SMS byl blokován pro tento účet → vznik `FAKE_SMS_MODE`
- **In-app je lepší i jinak**:
  - Žádný prostředník (operátor, Twilio, spam filtry)
  - Okamžité (SocketIO latency < 1 s)
  - Rich UI: Ack / Resolve tlačítka přímo v notifikaci
  - GDPR-čistší: zůstává uvnitř Radim Care
- SMS zůstává jako fallback pro non-Radim uživatele (staré kontakty v telefonu)

---

## 6. Pozorované výkonnostní charakteristiky (ověřeno na prod, 2026-04-18)

| Metrika | Hodnota | Poznámka |
|---|---|---|
| Latence `SELECT 1` (prod PG) | **1 ms** | Via /api/system/status |
| Cold start Eco dynu | ~6 s | Po 30 min nečinnosti |
| `/api/auth/register` total | ~400 ms | Včetně SMTP welcome email |
| `/api/sos/trigger` total | ~300 ms | Vč. notify_senior_family (SocketIO broadcast) |
| `/api/festive-greeting` | ~50 ms | Bez AI, jen lookup + render |
| `/api/radim/chat` (Gemini) | ~1-1.5 s | AI round-trip |
| Azure TTS synthesis | ~800 ms | 50-word sentence, SSML |
| SocketIO notif delivery | < 500 ms | Browser-to-browser |
| Service worker install | ~2 s | 53 files precache |
| Initial page load (cold) | ~3.5 s | HTML + critical CSS + head bundle |
| Subsequent page loads | ~250 ms | Cached |

---

## 7. Známé limity + risky

| Risk | Pravděpodobnost | Dopad | Mitigace |
|---|---|---|---|
| Eco dyno usne → cold start | Vysoká (po 30 min) | Střední (6s čekání) | **Upgrade na Basic** ($7/měs) — nespíme |
| Twilio zablokovaný SMS | Vysoká (existující) | Nízký | FAKE_SMS_MODE + in-app jako primary |
| Gemini rate limit | Střední | Střední | Fallback na Claude Opus |
| Heroku PG Essential limit (1GB, 10k řádků/h) | Nízká pro 100 userů | Vysoký | Monitor via /api/system/status, upgrade Standard-0 před 500 userů |
| Service Worker stale cache | Střední | Nízký | CACHE_VERSION bump při každém deploy |
| Azure TTS outage | Nízká | Střední | Fallback na browser SpeechSynthesis (horší kvalita) |
| JWT secret leak | Velmi nízká | Kritický | SECRET_KEY jen v Heroku config, rotace roční |
| DB migrations failure | Nízká | Vysoký | Testovat na lokální PG před push |

---

## 8. Další čtení

- [SYSTEM_INVENTORY.md](./SYSTEM_INVENTORY.md) — **co** všechno je v systému (moduly, tabulky, blueprinty, joby)
- [HA_SETUP.md](./HA_SETUP.md) — integrace s Home Assistant
- [CLAUDE.md](./CLAUDE.md) — historický kontext vývoje
- `tests/` — 288 automatických testů pokrývá core flows
- `mykolibri-academy-project/scripts/build.sh` — detailní build proces pro frontend

---

*Dokument aktualizován: 2026-04-18 po kompletní inventuře + stabilizaci v10.41.3*
