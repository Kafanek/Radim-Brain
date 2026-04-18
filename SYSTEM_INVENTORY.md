# 📋 RADIM Care — System Inventory

**Stav**: produkční, v10.41.3 · **Datum**: 2026-04-18 · **Zdroj**: automatický audit codebase + prod DB

Kompletní referenční seznam. Pro **jak** systém funguje viz [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 📊 High-level metriky

| | |
|---|---|
| **Python modulů** | 145 |
| **Celkem řádků Python** | 64,888 |
| **Flask blueprintů** | 47 registrovaných |
| **DB tabulek (prod PG)** | 43 |
| **APScheduler jobů** | 11 aktivních |
| **Pytest testů** | 288 (všechny pass) |
| **Frontend section modulů** | 29 |
| **Frontend top-level servisů** | 68 |
| **Feature flags** | 6 env proměnných |
| **SQL indexů** | 60+ |
| **Marketing stránek (Astro)** | 15 |

---

## 1. Backend Python moduly (145 souborů)

### 1.1 Core (5 souborů)
| Soubor | Řádky | Účel |
|---|---:|---|
| `app.py` | 2137 | Flask app, 47 BP registrací, APScheduler setup, SocketIO |
| `database.py` | 414 | PG/SQLite dual-mode, connection pooling, db_context, db_insert |
| `database_schema.py` | 1450 | CREATE TABLE + indexy + PG_MIGRATIONS + SQLITE_MIGRATIONS |
| `auth_middleware.py` | 211 | `@require_auth`, `@require_premium`, `@optional_auth` dekorátory |
| `auth_routes.py` | 833 | `/api/auth/*` — register, login, verify, forgot-password, delete-account |

### 1.2 Blueprints (47 souborů) — seřazeno podle URL prefixu

| Blueprint | URL prefix | Soubor | Popis |
|---|---|---|---|
| auth_bp | `/api/auth` | auth_routes.py | JWT login/register |
| admin_bp | `/api/admin` | admin_routes.py | Admin panel endpointy |
| agent_bridge_bp | `/api/agents` | agent_bridge.py | Reactive↔proactive most |
| agents_bp | `/api/agents-adv` | advanced_agents.py | Specializovaní agenti |
| anticipation_bp | `/api/anticipate` | anticipation_routes.py | Behavioral prediction |
| audit_bp | `/api/audit` | audit_log.py | GDPR audit log |
| radim_brain_bp | `/api/brain` | radim_brain_routes.py | Brain adaptation |
| calendar_bp | `/api/calendar` | calendar_routes.py | Kalendář + Google sync |
| care_plan_bp | `/api/care-plan` | care_plan.py | Plány péče |
| chat_bp | `/api/chat` | chat_routes.py | Konverzace, zprávy |
| circadian_bp | `/api/circadian` | circadian_engine.py | 24h cyklus |
| claude_bp | `/api/claude` | claude_routes.py | AI odpovědi |
| claude_content_bp | `/api/claude-content` | claude_content_routes.py | News/weather přes Claude |
| claude_emotion_bp | `/api/claude-emotion` | claude_emotion_routes.py | Emoční analýza |
| contacts_bp | `/api/contacts` | contacts_routes.py | **v10.38** Telefonní seznam |
| dashboard_bp | `/api/dashboard` | dashboard_routes.py | Dashboardy |
| education_bp | `/api/education` | education_routes.py | Kurzy, lekce |
| education_assessment_bp | `/api/edu-assess` | education_assessment_routes.py | Kvízy |
| education_scenario_bp | `/api/edu-scenario` | education_scenario_routes.py | Scénáře |
| education_task_bp | `/api/edu-task` | education_task_routes.py | Domácí úkoly |
| education_teacher_bp | `/api/edu-teacher` | education_teacher_routes.py | Učitelský panel |
| email_bp | `/api/email` | email_routes.py | SMTP odesílání |
| family_bp | `/api/family` | family_routes.py | Rodinný dashboard |
| family_link_bp | `/api/family/link` | family_link_routes.py | **v10.37** Senior↔rodina účty |
| festive_greeting_ep | `/api/festive-greeting` | notification_routes.py | **v10.40** Sváteční pozdrav |
| fhir_bp | `/api/fhir` | fhir_adapter.py | HL7 FHIR R4 |
| gdpr_bp | `/api/gdpr` | gdpr_routes.py | Export, výmaz |
| growth_bp | `/api/growth` | personal_growth.py | Personal growth |
| ha_bp | `/api/ha` | home_assistant.py | Home Assistant integrace |
| health_agent_bp | `/api/health-agent` | radim_health_agent.py | Health monitoring |
| iot_bp | `/api/iot` | iot_routes.py | IoT zařízení |
| iot_bridge_bp | `/api/iot-bridge` | iot_bridge_routes.py | Krizové události |
| iot_dashboard_bp | `/api/iot-dash` | iot_dashboard_routes.py | Pečovatel UI |
| kal_bp | `/api/kal` | kal_routes.py | Čeština/slovenština |
| library_bp | `/api/library` | library_routes.py | E-knihy |
| media_push_bp | `/api/media` | media_push_routes.py | Media + push |
| medical_bp | `/api/medical` | medical_team.py | Zdravotní tým |
| memory_bp | `/api/memory` | memory_routes.py | Historie chatu |
| news_api_bp | `/api/news` | news_routes.py | News feed |
| notification_bp | `/api/notifications` + `/api/sos` | notification_routes.py | **v10.37** In-app notifikace + SOS |
| onboarding_bp | `/api/onboarding` | onboarding_routes.py | **v10.41** First-run wizard + welcome email |
| ops_bp | `/api/ops` | ops_quality.py | Operační KPIs |
| orchestrator_bp | `/api/orchestrate` | orchestrator_blueprint.py | Multi-agent koordinace |
| pilot_bp | `/api/pilot` | pilot_mode.py | Pilotní režim |
| predict_bp | `/api/predict` | predict_routes.py | Crisis prediction |
| prediction_bp | `/api/prediction` | predictive_agent.py | Predictive agent |
| radim_bp | `/api/radim` | radim_orchestrator.py | Hlavní chat orchestrátor |
| radim_service_bp | `/api/radim-service` | radim_service_routes.py | Task management |
| rhythm_bp | `/api/rhythm` | rhythm_routes.py | Rhythm state |
| rhythm_return_bp | `/api/rhythm-return` | rhythm_return_routes.py | Parkinson terapie |
| safe_web_bp | `/api/safe-web` | browser_agent_safe_routes.py | **v10.36** Senior web |
| browser_agent_bp | `/api/browser` | browser_agent_routes.py | Web agent interní |
| scenario_bp | `/api/scenario` | scenario_engine.py | Scénáře |
| seniors_bp | `/api/seniors` | seniors_routes.py | Senior profily |
| skill_bp | `/api/skills` | skill_map.py | Skill registry |
| soul_bp | `/api/soul` | soul_routes.py | Radim personality |
| speech_bp | `/api/speech` | speech_routes.py | Speech I/O |
| survey_bp | `/api/survey` | survey_routes.py | Dotazníky |
| survey_engine_bp | `/api/survey-engine` | survey_engine.py | Survey engine |
| survey_telemetry_bp | `/api/survey-telemetry` | survey_telemetry.py | Survey analytics |
| system_status_bp | `/api/system/status` | system_status_routes.py | **v10.41** Live health dashboard |
| telemedicine_bp | `/api/telemedicine` | telemedicine_routes.py | Telemedicína |
| telemedicine_teacher_bp | `/api/telemed-teacher` | telemedicine_teacher_routes.py | Teacher scheduling |
| telemedicine_multiparty_bp | `/api/telemed-multi` | telemedicine_multiparty_routes.py | Multi-specialista |
| tts_proxy_bp | `/api/tts`, `/api/azure/tts`, `/api/elevenlabs/tts` | tts_proxy_routes.py | TTS proxy |
| tv_proxy_bp | `/api/tv` | tv_proxy_routes.py | TV guide |
| twilio_bp | `/api/voice` | twilio_voice_routes.py | Phone calls |
| voice_runtime_bp | `/api/voice-runtime` | voice_runtime_routes.py | Voice session |

### 1.3 Business logic (19 helperů)

| Modul | Účel |
|---|---|
| `notification_helpers.py` | `notify()`, `notify_senior_family()`, opt-in filtering |
| `memory_helpers.py` | `db_load_profile`, `db_save_profile`, chat history |
| `speech_helpers.py` | Speech rate, pause timing, voice profile matching |
| `telemedicine_helpers.py` | Participant validation, consultation queries |
| `iot_helpers.py` | Sensor aggregation, alert evaluation |
| `action_system.py` | Action registry, risk levels 0-4, approval flow |
| `behavior_baseline.py` | Per-user baseline (7-day window), deviation detection |
| `conversation_memory.py` | Fact extraction z chatu |
| `context_builder.py` | φ/ρ/δ konstanty, Claude context assembly |
| `cognitive_assessment.py` | Cognitive score 0-100 |
| `communication_needs.py` | Alzheimer → communication strategy mapping |
| `feedback_loop.py` | Agent recommendation recording, reward |
| `ops_quality.py` | Operational KPI tracking |
| `rate_limiter.py` | Per-user sliding window rate limit |
| `relationship_engine.py` | Trust scoring, permission delegation |
| `response_composer.py` | Unified Radim response assembly |
| `self_healing.py` | Auto error recovery, fallback routing |
| `task_service.py` | Task/reminder/medication scheduling |
| `festive_greeting.py` | **v10.40** Holiday + nameday greeting builder |

### 1.4 AI + speech (32 modulů)

**Brain model:**
- `brain_core.py` — Ψ(t) = (C, E, R, S) konzistentní model
- `brain_math.py` — φ-based equations, coherence calculation
- `brain_speech.py` — Speech parameter mapping ↔ brain state
- `brain_feedback.py` — Rating → adaptation

**Voice + speech:**
- `voice_filter.py` — **Core TTS SSML builder**, VOICE_PROFILES (HARMONY/ALERT/CRISIS/FESTIVE/…), φ-pauzy
- `voice_melody.py`, `voice_music.py`, `voice_profile_engine.py`, `voice_runtime_engine.py`, `voice_learning.py`
- `speech_understanding.py` — Fuzzy matching pro speech-impaired
- `text_rhythm.py` — Text → rhythm, prosody synthesis

**NLU:**
- `intent_data.py` (646 řádků) — 1000+ patterns, česky + slovensky
- `intent_resolver.py` — Lightweight local NLU před AI call
- `anticipation_engine.py`, `anticipation_math.py`, `anticipation_routes.py`

**RTCF (Radim Temporal Coherence Framework):**
- `rtcf_beat.py` — Vital beat (BPM, HRV, autonomic)
- `rtcf_bridge.py` — Integrace s externími clocks
- `rtcf_coherence.py` — φ-based coherence equation
- `rtcf_constants.py` — Matematické konstanty, sequences
- `rtcf_policy.py` — Heartbeat → action translation
- `rtcf_temporal.py` — Živý pulz — beat × flow × circadian

**Rhythm:**
- `rhythm_state.py`, `rhythm_return_db.py`, `rhythm_return_math.py`, `rhythm_return_routes.py`

**AI engines:**
- `adaptive_learning.py` (1190 řádků) — Core Radim v2.0
- `radim_ai_engine.py` — Gemini API calls, WhatsApp personalization
- `radim_system_prompt.py` — Domácí asistent system prompt v3.0
- `radim_helpers.py` — Radim persona utilities

### 1.5 Safety + GDPR (11 modulů)

| Modul | Účel |
|---|---|
| `browser_agent.py` | v10.34 web-browsing orchestrátor |
| `browser_agent_safe.py` | **v10.36** GDPR-first senior agent |
| `browser_agent_safe_config.py` | Privacy patterns, blocked domains |
| `browser_agent_safe_routes.py` | `/api/safe-web/*` endpointy |
| `browser_agent_extractor.py` | HTML → structured content |
| `browser_agent_fetcher.py` | Safe HTTP (timeout, size limits) |
| `browser_agent_routes.py` | `/api/browser/*` |
| `browser_agent_safety.py` | URL validation, SSRF prevention |
| `input_sanitizer.py` | XSS + SQL injection protection |
| `audit_log.py` | GDPR audit trail |
| `gdpr_routes.py` | Data export (čl. 20), erasure (čl. 17) |

### 1.6 IoT + smart home (7)

| Modul | Účel |
|---|---|
| `iot_routes.py` | Sensor values, alert rules, caregiver |
| `iot_simulator.py` | Simulovaná sensor data |
| `iot_bridge_routes.py` | Krizové události, senzor aggregation |
| `iot_dashboard_routes.py` | Pečovatel UI |
| `iot_helpers.py` | Device state, threshold evaluation |
| `home_assistant.py` (1208) | HA integrace, YAML config, automation |
| `circadian_engine.py` | 24h circadian state |

### 1.7 Medical (8)

| Modul | Účel |
|---|---|
| `medical_team.py` (1353) | Multi-specialist (doctor, nurse, therapist, pharmacist) |
| `radim_health_agent.py` (1223) | Autonomous vitals, drug interactions, escalation |
| `care_plan.py` | Plány péče (interventions, goals, KPIs) |
| `drug_interactions.py` | Drug database lookup |
| `fhir_adapter.py` | HL7 FHIR R4 mapping |
| `cognitive_assessment.py` | Cognitive score aggregation |
| `telemedicine_audit.py` (604) | Auditable event logging |
| `sos_escalator.py` | **v10.40** SOS escalation ladder |

### 1.8 Education (12)

| Modul | Účel |
|---|---|
| `education_data.py` (4562) | 100+ vzácných chorob, symptoms, treatments |
| `education_routes.py` | Catalog + lessons |
| `education_assessment_routes.py` | Kvízy |
| `education_helpers.py` | Progress events, xp/badges |
| `education_task_routes.py` | Domácí úkoly |
| `education_teacher_routes.py` | Učitelský panel |
| `education_scenario_routes.py` | Scenarios |
| `adaptive_learning.py` | User learning model, difficulty adjust |
| `personal_growth.py` (764) | Goal tracking, milestones |
| `survey_engine.py` (705) | Survey delivery, scoring |
| `survey_telemetry.py` | Analytics |

### 1.9 Integrations (11)

| Modul | Účel |
|---|---|
| `twilio_voice_routes.py` (934) | Phone calls, IVR, webhooks |
| `twilio_voice_helpers.py` (724) | Call state, DTMF, speech bridge |
| `email_routes.py` | SMTP Wedos, welcome/consult/alert emaily |
| `tts_proxy_routes.py` | Azure TTS + ElevenLabs, cache |
| `tv_proxy_routes.py` | TV guide whitelist |
| `claude_routes.py` | Claude konverzace |
| `claude_content_routes.py` | News/weather/stories |
| `radim_ai_engine.py` | Gemini |
| `ai_bridge.py` | Gemini bridge |
| `kal_routes.py` (581) | Czechoslovak language |

### 1.10 Agents + advanced (12)

| Modul | Účel |
|---|---|
| `agent_loop.py` (1919) | **Proactive agent loop v2.0** — observations → actions → escalation |
| `agent_coordinator.py` | Agent base class |
| `agent_bridge.py` | Reactive↔proactive bridging |
| `advanced_agents.py` (834) | Specializovaní agenti |
| `predictive_agent.py` | Behavioral prediction |
| `scenario_engine.py` | Scénáře (if-then) |
| `skill_map.py` (670) | Skill registry |
| `socketio_handlers.py` | SocketIO eventy (message, typing, presence) |
| `admin_routes.py` | Admin panel |
| `system_status_routes.py` | **v10.41** Live health dashboard |
| `action_system.py` | Action registry |
| `feedback_loop.py` | Agent recommendation recording |

### 1.11 Family + social (9)

| Modul | Účel |
|---|---|
| `family_routes.py` | Rodinný dashboard |
| `family_link_routes.py` | **v10.37** Senior↔family linking |
| `contacts_routes.py` | **v10.38** Telefonní seznam + FamilyLink pairing |
| `chat_routes.py` | Konverzace, zprávy, media |
| `communication_needs.py` | Alzheimer → strategy |
| `media_push_routes.py` | Media upload, push |
| `notification_routes.py` | **v10.37+** In-app notif + SOS |
| `notification_helpers.py` | API implementation |
| `festive_greeting.py` | **v10.40** Greeting builder |

### 1.12 Onboarding + UX (8)

| Modul | Účel |
|---|---|
| `onboarding_routes.py` | **v10.41** First-run wizard tracking + welcome email |
| `soul_routes.py` | Radim soul |
| `soul_data.py` | Soul data |
| `seed_demo.py` | Demo senior data |
| `pilot_mode.py` | Pilot deployment |
| `relationship_engine.py` | Trust, permissions |
| `dashboard_aggregators.py` | Dashboard metric aggregation |
| `dashboard_routes.py` | Admin/family dashboards |

### 1.13 Utilities (6)

| Modul | Účel |
|---|---|
| `library_data.py` | E-book catalog |
| `library_routes.py` | E-book endpointy |
| `news_routes.py` | News feed |
| `memory_logic.py` | Claude context assembly |
| `scaling_optimizations.py` | LRU cache pro TTS |
| `radim_shared.py` | Czech nameday lookup |
| `utils.py` | UUID, timestamps |

---

## 2. Databázové tabulky (43)

### 2.1 Core (20)

| Tabulka | Klíčové sloupce | Použití |
|---|---|---|
| `auth_users` | id, email, password_hash, name, role | Přihlášení |
| `chat_conversations` | id, participants, type, name | Konverzace |
| `chat_messages` | id, conversation_id, sender_id, content | Zprávy |
| `chat_contacts` | id, user_id, contact_id, name, phone, role, sos_priority | (starší) Phone book |
| `chat_users` | id, name, email, avatar, role, online | Chat users |
| `chat_media` | id, message_id, user_id, type, url | Media přílohy |
| `push_subscriptions` | id, user_id, endpoint, keys | WebPush VAPID |
| `admin_stats` | id, date, total_messages, ai_messages | Denní metriky |
| `memory_profiles` | user_id (PK), data (JSONB) | **Profile + onboarding + festive_greeting template** |
| `memory_history` | id, user_id, role, content, created_at | Chat history |
| `memory_learning` | user_id (PK), data (JSONB) | Learning analytics |
| `radim_tasks` | id, user_id, title, task_type, status, scheduled_time | Úkoly/reminders |
| `radim_medication_log` | id, user_id, medication_name, taken_at | Med adherence |
| `education_progress` | id, user_id, course_id, lesson_id, score | Pokrok v kurzech |
| `education_profiles` | user_id (PK), level, data (JSONB) | Student profil |
| `education_assignments` | id, student_id, teacher_id, status | Student↔teacher |
| `education_lesson_progress` | id, user_id, lesson_id, score, completed | Per-lesson pokrok |
| `voice_sessions` | session_id, state, C, kappa, alpha | Voice session state |
| `education_teacher_tasks` | id, teacher_id, student_id, title, due_date | Domácí úkoly |
| `telemedicine_consultations` | id, teacher_id, student_id, scheduled_date, status | Konzultace |

### 2.2 Telemedicína (5)

| Tabulka | Popis |
|---|---|
| `telemedicine_availability` | Disponibilita lékařů, slot_duration |
| `telemedicine_participants` | Multiparty účastníci, role, join_token |
| `telemedicine_events` | GDPR audit trail (event_type, old_status, new_status) |
| `telemedicine_quality_log` | Quality metrics |

### 2.3 Rhythm + brain (5)

| Tabulka | Popis |
|---|---|
| `rhythm_sessions` | Parkinson terapie sessions |
| `rhythm_states` | Math state snapshots (M, tau) |
| `rhythm_breakpoints` | Inflection points |
| `brain_adaptation` | Per-user reward, adaptace |
| `brain_states` | Consciousness snapshots (C, E, R, S, alpha, mode) |
| `brain_feedback` | Speech feedback (rating, action) |

### 2.4 IoT + crisis (5)

| Tabulka | Popis |
|---|---|
| `crisis_events` | Crisis detection log |
| `iot_devices` | Zigbee/Kasa zařízení |
| `iot_sensor_data` | Sensor readings (timestamped) |
| `iot_alert_rules` | Alert config (threshold, condition) |
| `iot_alerts` | Alert instances (acknowledged) |
| `iot_caregivers` | Caregiver registry per room |

### 2.5 Family + notifications (v10.37-41) (5)

| Tabulka | Klíčové sloupce | Verze |
|---|---|---|
| `user_notifications` | id, to_user_id, from_user_id, type, severity, title, body, data (JSONB), read_at | v10.37 |
| `senior_family_links` | id, senior_id, family_user_id, family_email, relation, invite_token, confirmed_at, sos_priority, notify_on_sos/crisis/daily | v10.37 |
| `contacts` | id, senior_id, name, phone, email, relation, sos_priority, is_primary, is_emergency, can_call, can_sms, linked_family_link_id | v10.38 |
| `sos_events` | id, senior_id, source, message, ack_by_user_id, ack_at, escalation_stage, resolved_at | v10.40 |

### 2.6 Audit (3)

| Tabulka | Popis |
|---|---|
| `audit_log` | GDPR compliance (action, resource, ip, timestamp), 36m retention |
| `agent_observations` | Agent findings (observation_type, severity, details JSONB) |

---

## 3. APScheduler joby (11)

| Job ID | Interval | Handler | Purpose |
|---|---|---|---|
| `radim_reminders` | 5 min | `_check_reminders` | Task reminder delivery |
| `telemed_reminders` | 5 min | `_check_consultation_reminders` | Consultation reminders |
| `agent_loop` | 5 min | `run_agent_cycle` | Proactive agent observations |
| `sos_escalator` | **10 s** | `run_escalator_tick` | **v10.40** SOS escalation ladder |
| `morning_checkin` | cron 08:00 | `run_morning_checkin` | Ranní pozdrav + léky |
| `daily_cleanup` | cron 03:00 | `run_daily_cleanup` | Archiv starých dat |
| `daily_engagement` | cron 14:00 | `run_daily_engagement` | Engagement prompts |
| `daily_summary` | cron 20:00 | `run_daily_summary` | Denní souhrn rodině |
| `weekly_reports` | cron Mon/Wed/Fri 9:00 | `run_weekly_reports` | Family dashboard update |
| `health_agent` | 15 min | `_run_health_agent` | Vitals + drug interactions |
| `summary_report` | cron Mon/Wed/Fri 9:00 | `_run_summary_report` | Summary gen |

---

## 4. Feature flags (6 env vars)

| Flag | Default | Controls |
|---|---|---|
| `ENABLE_BROWSER_AGENT` | `false` | v10.34 web-browsing orchestrator |
| `ENABLE_SAFE_WEB_AGENT` | `false` | **prod: `true`** — v10.36 senior web agent |
| `ENABLE_RTCF` | `false` | Radim Temporal Coherence Framework |
| `FAKE_SMS_MODE` | `false` | **prod: `true`** — Simuluje SMS (Twilio blokován) |
| `SOS_ESCALATION` | `true` | **prod: `true`** — v10.40 escalator engine |
| `FRONTEND_URL` | `https://app.radimcare.cz` | Pro emaily, invite linky |

Další env: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_SECRET`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `AZURE_SPEECH_KEY`+`AZURE_SPEECH_REGION`, `TWILIO_ACCOUNT_SID`+`TWILIO_AUTH_TOKEN`+`TWILIO_PHONE_NUMBER`, `SMTP_HOST`+`SMTP_USER`+`SMTP_PASSWORD`+`SMTP_FROM`, `VAPID_PUBLIC_KEY`+`VAPID_PRIVATE_KEY`+`VAPID_CLAIMS_EMAIL`, `WP_JWT_SECRET`, `IOT_GATEWAY_TOKEN`, `HA_URL`+`HA_TOKEN`, `FRONTEND_URL`.

---

## 5. Testy (288 celkem)

| Soubor | Testy | Oblast |
|---|---|---|
| `tests/test_smoke.py` | ~50 | Startup, health, auth basics |
| `tests/test_agent_loop.py` | ~40 | Proactive agent, observations, escalation |
| `tests/test_brain_and_chat.py` | ~35 | Brain model, chat flow |
| `tests/test_browser_agent.py` | ~30 | Web scraping, URL fetching |
| `tests/test_browser_agent_safe.py` | ~35 | GDPR agent, allowlist, SSRF |
| `tests/test_rtcf.py` | ~30 | Coherence feedback, beat |
| `tests/test_telemedicine_audit.py` | ~68 | Audit, GDPR consent |
| `tests/conftest.py` | — | Fixtures, DB setup/teardown |

Run: `ENABLE_SAFE_WEB_AGENT=true python3 -m pytest tests/ -q`

---

## 6. Frontend (mykolibri-academy-project/)

### 6.1 Section modules (`js/sections/`, 29 souborů)

| Modul | Účel |
|---|---|
| `admin-module.js` | **6 tabů**: Přehled, Uživatelé, Systém (v10.41), Demo (v10.40), Reporty, Orchestrátor |
| `browser-module.js` | v10.34 legacy web browsing |
| `calendar-module.js` | Kalendář + Google sync |
| `calls-module.js` | Jitsi video calls |
| `caregiver-module.js` | Pečovatelský dashboard |
| `contacts-module.js` | **v10.38** Telefonní seznam (3 taby: Rychlé, Všichni, Rodina) |
| `education-module.js` | Kurzy |
| `email-module.js` | Email klient |
| `exercises-module.js` | Cvičení (81KB — největší) |
| `help-module.js` | Nápověda |
| `internet-module.js` | **v10.37.3** Unifikovaný browser + safe-web |
| `learning-module.js` | Vzdělávání |
| `lessons-module.js` | Lekce |
| `library-module.js` | Knihovna (básně, příběhy, přísloví) |
| `medical-module.js` | Zdravotní tým |
| `music-module.js` | Hudba + rhythm |
| `news-module-v2.js` | Zprávy |
| `quiz-module.js` | Kvízy |
| `safe-web-module.js` | v10.36 legacy (nahrazen internet-module) |
| `settings-module.js` | **Nastavení** — Profil, Rodina, **Pozdrav** (v10.40), Hlas, Vzhled, … |
| `skillmap-module.js` | Skill map |
| `smart-home-module.js` | Chytrá domácnost |
| `soul-module.js` | Radim personality |
| `stories-module.js` | Příběhy |
| `survey-module.js` | Dotazníky |
| `tasks-module.js` | Úkoly |
| `trend-module.js` | Trend zdraví |
| `tv-module.js` | TV + rádio |

### 6.2 Top-level services (68 v `js/`)

**Auth + client:**
- `RadimAuthService.js` — JWT uložení v `radim_jwt` (localStorage + sessionStorage)
- `RadimClientManager.js`, `RadimAssistant.js`

**Core UI:**
- `radim-core.js` — **showModule()** se self-healing dispatcher (v10.37.1)
- `RadimMobileNav.js` — Mobile bottom nav

**Notifications + SOS + Family:**
- `NotificationBell.js` — **v10.37** Zvoneček + Ack/Resolve tlačítka (v10.40)
- `SosButton.js` — v10.37.2 Fixed bottom-right, 3-s podržení
- `FamilyInviteHandler.js` — v10.37 accept-invite z URL param
- `FestiveGreetingService.js` — **v10.40** Daily greeting + WakeWord hook
- `OnboardingWizard.js` — **v10.41** 4-step modal
- `ViewSwitcher.js` — **v10.39** Admin/Senior/Rodina perspective

**Speech pipeline:**
- `VoiceGateway.js` — unified TTS + STT entry (v10.27)
- `SpeechPipeline.js` — low-level pipeline
- `SpeechQueue.js`, `SpeechOrchestrator.js`
- `AudioUnlockManager.js` — autoplay policy fix
- `WakeWordManager.js` — "Radime" detekce, festive greeting hook
- `WakeBargeIn.js` — přerušení při uživatelově mluvě
- `UnifiedVoiceManager.js`
- `SimpleWebSpeechTTS.js`, `SecureTTSProxy.js`
- `ElevenLabsProxy.js`
- `HumanTimingConfig.js`, `HumanTimingIntegration.js`

**AI + brain:**
- `RadimAI.js`, `RadimConsciousnessEngine.js`
- `BrainBridge.js`
- `RadimEmpathyBridge.js`
- `RadimModuleRouter.js`, `RadimAgentRouter.js`
- `RadimEmergencySystem.js`, `RadimNotificationCenter.js`
- `ConsciousnessPanel.js`
- `QuantumInteractionLayer.js`, `QuantumMetricsDisplay.js`
- `GeminiProxy.js`

**Offline + sync:**
- `RadimOfflineStore.js`, `OfflineEngine.js`, `OfflineManager.js`
- `OfflineCommandHandler.js`
- `EducationSyncService.js`, `NeuronSyncService.js`
- `SecureStorage.js`

**Other:**
- `ModuleLoader.js` — lazy-load sekcí
- `PhoneCallManager.js`
- `KalService.js`, `NameDayService.js`, `DailyInfoService.js`
- `EbookLibrary.js`
- `HealthCheckService.js`
- `PersonalizationService.js`
- `PerfMonitor.js`
- `GoogleCalendarBackendService.js`
- `ConversationManager.js`, `VideoCallManager.js`, `TurnManager.js`
- `RadimSimpleChat.js` — Chat UI (v10.38.1 textarea)
- `RadimVoiceCommands.js`, `RadimVoiceUI.js`
- `RadimMessengerV3.js`, `RadimDashboardWidgets.js`
- `AdvancedNoiseFilter.js`

### 6.3 CSS (33 souborů)

Bundle `radim-all.css` (~385 KB před compressem), hash-busted. Moduly:
- `radim-branding.css`, `radim-inline.css` — brand tokens
- `home-radim.css`, `settings-radim.css`, `library-radim.css`, `help-radim.css`
- `exercises-radim.css`, `quiz-radim.css`, `medical-radim.css`, `tasks-radim.css`
- `learning-radim.css`, `skillmap-radim.css`, `smart-home-radim.css`
- `tv-radim.css`, `survey-radim.css`
- `browser-radim.css`, `safe-web-radim.css`, `internet-module.css`, `contacts-module.css`
- `calls-module.css`, `video-call.css`, `phone-call.css`
- `radim-chat.css`, `radim-messenger.css`, `radim-simple-chat.css`, `radim-widgets.css`
- `consciousness-panel.css`, `radim-math-panel.css`
- `notification-bell.css`, `onboarding-wizard.css`, `view-switcher.css`, `sos-button.css`
- `kolibri-dashboard-v2.css`, `sidebar-fix.css`, `radim-responsive.css`, `radim-client-manager.css`

### 6.4 Service Worker

Current: `v32.5.0`. Strategy:
- **JS + CSS**: network-first (3 s timeout), fallback cache
- **Images/fonts**: cache-first
- **HTML**: network-first with offline fallback
- **API calls**: network-first cached 4 s

Precache seznam: 53 core files (HTML, kritické JS, assety).

---

## 7. Marketing web (radimcare.cz)

**Lokace**: `radimcare-web/` (samostatný Astro projekt)
**Tech**: Astro 5 + MDX + Cloudflare Pages
**URL (staging)**: https://radimcare-web.pages.dev
**Build**: `npm run build` → 15 HTML stránek za ~4 s

**Stránky** (15):
| URL | Obsah |
|---|---|
| `/` | Hero + 3 persony + 12 featur + srovnávací tabulka + FAQ |
| `/jak-to-funguje/` | AI + sensory + HA + timeline dne |
| `/pro-seniory/`, `/pro-rodinu/`, `/pro-pecovatele/` | 3 persona landing pages |
| `/bezpecnost/` | GDPR, SafeWeb, EU data, práva |
| `/cena/` | 3 tarify (0/249/890 Kč) + FAQ |
| `/kontakt/` | Email + telefon + formulář |
| `/demo/` | Pilot signup 3 kroky + formulář |
| `/o-nas/` | Origin story |
| `/pribehy/` | 4 anonymizované rodiny |
| `/gdpr/`, `/podminky/`, `/cookies/` | Právní |
| `/404` | Friendly CZ not-found |

**Komponenty**:
- `Base.astro` — HTML shell s OG/JSON-LD
- `Nav.astro` — sticky nav s mobilním hamburgerem
- `Footer.astro` — 4-sloupce, legal links
- `ChatWidget.astro` — plovoucí "Zeptat se Radima" (volá `/api/radim/chat` demo mode)

**Brand**: `src/styles/brand.css` s identickými tokeny jako app (#5BA8A0 teal, Georgia serif, 12-20px radius).

---

## 8. Dokumentace (10+ .md souborů)

| Soubor | Obsah |
|---|---|
| `ARCHITECTURE.md` | Jak systém funguje (tento dokument) |
| `SYSTEM_INVENTORY.md` | Exhaustivní seznam (tento dokument) |
| `CLAUDE.md` | Historický kontext vývoje |
| `HA_SETUP.md` | Home Assistant setup (Lenovo mini PC, Zigbee2MQTT, HAOS) |
| `README.md` | Quick start |
| Ostatní | Historical commits, design notes |

---

## 9. Externí závislosti

### 9.1 Python (requirements.txt)
Flask, psycopg2-binary, gunicorn, eventlet, flask-socketio, flask-cors, flask-compress, apscheduler, bcrypt, pyjwt, requests, pywebpush, twilio, openai, google-generativeai, anthropic, azure-cognitiveservices-speech, trafilatura, beautifulsoup4, python-kasa, yeelight, paho-mqtt, homeassistant_api — atd. Viz `requirements.txt`.

### 9.2 Frontend
Aplikace (`mykolibri-academy-project/`): vanilla JS, žádné framework dep.
Marketing web (`radimcare-web/`): `astro`, `@astrojs/mdx`, `@astrojs/sitemap`, `wrangler`.

### 9.3 External API (SaaS)
- **Gemini 2.0 Flash** (Google AI Studio) — primary LLM
- **Claude Opus** (Anthropic) — fallback LLM
- **Azure Speech Services** (Microsoft, West Europe) — TTS s Antonín Neural
- **Twilio** — Voice + SMS (SMS blokován, FAKE_SMS_MODE)
- **Jitsi Meet** (public) — video hovory
- **Cloudflare Pages** — hosting front (free tier)
- **Heroku** — backend (Eco dyno)
- **PostgreSQL Essential-0** (Heroku) — databáze
- **Wedos SMTP** (`mail.radimcare.cz:465`) — email

---

## 10. Endpoints quick reference (nejpoužívanější)

### 10.1 Auth
- `POST /api/auth/register` — registrace + welcome email
- `POST /api/auth/login` — JWT login
- `GET /api/auth/verify` — ověření tokenu
- `POST /api/auth/forgot-password` — reset email

### 10.2 Notifikace + SOS (v10.37-40)
- `GET /api/notifications/list` / `/unread-count`
- `POST /api/notifications/<id>/read` / `/read-all`
- `POST /api/sos/trigger` — spustit SOS
- `POST /api/sos/<id>/ack` — "Už řeším"
- `POST /api/sos/<id>/resolve` — uzavřít
- `GET /api/sos/active` — moje aktivní
- `GET /api/festive-greeting` — dnešní pozdrav
- `PUT /api/festive-greeting/template` — nastavit

### 10.3 Family + kontakty (v10.37-38)
- `POST /api/family/link/invite` — pozvat rodinu
- `GET /api/family/link/my-links` / `my-seniors`
- `POST /api/family/link/accept` — přijmout pozvánku
- `PATCH /api/family/link/<id>/settings` — priority + opt-in flags
- `DELETE /api/family/link/<id>` — revoke
- `GET|POST|PATCH|DELETE /api/contacts[/<id>]`
- `POST /api/contacts/<id>/call` — log + tel: URI
- `POST /api/contacts/<id>/sms` — Twilio SMS (nebo fake)
- `POST /api/contacts/<id>/message` — in-app notif

### 10.4 Onboarding (v10.41)
- `GET /api/onboarding/status`
- `POST /api/onboarding/step` — {step: profile|family|festive|sos_test}
- `POST /api/onboarding/skip`
- `POST /api/onboarding/welcome-email` — re-send

### 10.5 Ostatní
- `GET /api/system/status` — admin health dashboard (X-Admin-Secret nebo admin JWT)
- `GET /health` — public health check
- `POST /api/safe-web/open` — bezpečně otevřít URL
- `GET /api/safe-web/modes` — public, transparentní módy
- `GET /api/gdpr/export/<uid>` — Article 20 export
- `DELETE /api/gdpr/erase/<uid>` — Article 17 erasure

---

## 11. Verze a changelog (poslední)

| Verze | Datum | Hlavní |
|---|---|---|
| v10.41.3 | 2026-04-18 | Fix DictRow tuple-unpacking (PG bug) |
| v10.41.2 | 2026-04-18 | Fix contacts INSERT PG boolean |
| v10.41.1 | 2026-04-18 | OnboardingWizard UI komponent |
| v10.41 | 2026-04-18 | Production readiness: welcome email + onboarding API + system status |
| v10.40.2 | 2026-04-18 | Admin → Demo runbook |
| v10.40.1 | 2026-04-18 | Settings → Pozdrav UI |
| v10.40 | 2026-04-18 | SOS eskalace + FESTIVE voice + φ-pauzy + festive greeting |
| v10.39 | 2026-04-18 | ViewSwitcher Admin/Senior/Rodina |
| v10.38.1 | 2026-04-18 | Critical JWT key fix (radim_jwt) |
| v10.38 | 2026-04-18 | Contacts (telefonní seznam) + opt-in flags |
| v10.37.6+ | 2026-04-18 | Self-healing showModule, razprávky |
| v10.37 | 2026-04-18 | In-app notifikace + family linking + SOS |
| v10.36 | 2026-04-17 | Safe Web Agent GDPR-first |

---

*Dokument aktualizován: 2026-04-18 po kompletní inventuře + stabilizaci v10.41.3*
