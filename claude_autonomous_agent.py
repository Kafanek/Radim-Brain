"""
Claude Autonomous Agent for Radim
==================================

Plně autonomní AI agent postavený na Claude Sonnet 4.5 + tool use.

Běží na Heroku 24/7 nezávisle na uživatelově počítači. Každých 30 min
(default) zkontroluje aktivní seniory, zhodnotí jejich stav a sám rozhodne,
co dělat — od pasivního pozorování až po hovor rodině v krizi.

Architektura:
- Claude Sonnet 4.5 (claude-sonnet-4-5) přes Anthropic SDK
- Tool use loop: Claude volá nástroje, dostává výsledky, rozhoduje další krok
- Memory přes `agent_observations` tabulku (přes runs)
- Cost tracking přes `claude_agent_telemetry` tabulku
- Daily budget cap (default $5/den, env CLAUDE_AGENT_DAILY_BUDGET)
- Rate limit: max 1 akce/seniora/15min
- Audit log všech rozhodnutí

Spouštění:
- APScheduler job (configurable interval)
- Manuální trigger: POST /api/admin/claude-agent/run
- Při ALERT/CRISIS eventu z agent_loop.py (future)
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Imports & feature gating ──────────────────────────────────────────
try:
    from anthropic import Anthropic
    _CLAUDE_AVAILABLE = True
except ImportError:
    _CLAUDE_AVAILABLE = False
    logger.warning("anthropic SDK not installed — Claude agent disabled")

try:
    from database import db_context, is_postgres
    _DB = True
except ImportError:
    _DB = False

# ─── Math + Philosophy subsystems ────────────────────────────────────
try:
    from anticipation_engine import anticipate as _anticipate
    from anticipation_engine import compute_behavioral_profile as _behavioral_profile
    _MATH_ANTICIPATION = True
except ImportError:
    _MATH_ANTICIPATION = False

try:
    from circadian_engine import compute_circadian_profile as _circadian_profile
    from circadian_engine import check_proactive_triggers as _circadian_triggers
    _MATH_CIRCADIAN = True
except ImportError:
    _MATH_CIRCADIAN = False

try:
    from brain_math import T1 as _T1, T2 as _T2, PHI as _PHI, PSI as _PSI
    from brain_math import DELTA as _DELTA, RHO as _RHO, C_MAX as _C_MAX
    _MATH_BRAIN = True
except ImportError:
    _T1, _T2 = 12, 27
    _PHI, _PSI, _DELTA, _RHO, _C_MAX = 1.618, 0.618, 2.414, 2.016, 40
    _MATH_BRAIN = False

try:
    from soul_data import RADIM_VALUES as _RADIM_VALUES
    from soul_data import get_random_reflection as _get_reflection
    from soul_data import get_period as _get_period
    _PHILOSOPHY = True
except ImportError:
    _RADIM_VALUES = {}
    _PHILOSOPHY = False

# ─── Brain Core (Ψ(t) computation) ──────────────────────────────────
try:
    from brain_core import compute_psi_state as _compute_psi
    from brain_core import compute_unified_speech as _compute_speech
    from brain_math import compute_empathy as _compute_empathy
    _BRAIN_CORE = True
except ImportError:
    _BRAIN_CORE = False

# ─── Memory helpers (profile + learning) ────────────────────────────
try:
    from memory_helpers import (
        db_load_profile as _load_profile,
        db_save_profile as _save_profile,
        db_load_learning as _load_learning,
        db_save_learning as _save_learning,
        default_learning as _default_learning,
    )
    _MEMORY_HELPERS = True
except ImportError:
    _MEMORY_HELPERS = False

# ─── TTS subsystem (voice synthesis + voice memory) ─────────────────
try:
    from voice_filter import build_radim_ssml as _build_ssml
    from voice_filter import VOICE_PROFILES as _VOICE_PROFILES
    _TTS_SSML = True
except ImportError:
    _TTS_SSML = False
    _VOICE_PROFILES = {}

try:
    from twilio_voice_helpers import generate_azure_tts as _gen_azure_tts
    from twilio_voice_helpers import azure_tts_available as _azure_available
    _TTS_AZURE = True
except ImportError:
    _TTS_AZURE = False

try:
    from voice_learning import (
        get_voice_prefs as _get_voice_prefs,
        save_voice_prefs as _save_voice_prefs,
        record_voice_feedback as _record_voice_feedback,
        DEFAULT_PREFS as _DEFAULT_VOICE_PREFS,
    )
    _TTS_LEARNING = True
except ImportError:
    _TTS_LEARNING = False
    _DEFAULT_VOICE_PREFS = {}

# ─── Agent bus (shared intelligence with other app agents) ──────────
try:
    from agent_bus import (
        emit as _bus_emit,
        recent as _bus_recent,
        context as _bus_context,
        dedupe as _bus_dedupe,
    )
    _AGENT_BUS = True
except ImportError:
    _AGENT_BUS = False

# ─── RTCF Beat Engine (Radim's heartbeat) ───────────────────────────
try:
    from rtcf_beat import compute_beat_state as _compute_beat
    _RTCF_BEAT = True
except ImportError:
    _RTCF_BEAT = False

try:
    from rtcf_bridge import enhance_with_rtcf as _enhance_rtcf
    _RTCF_BRIDGE = True
except ImportError:
    _RTCF_BRIDGE = False

# ─── Komunikace module (32 medical scenarios + topic/mood) ──────────
try:
    from communication_needs import (
        COMMUNICATION_NEEDS as _COMM_NEEDS,
        get_communication_instructions as _get_comm_instructions,
        detect_topic as _detect_topic,
        detect_mood as _detect_mood,
    )
    _COMMUNICATION = True
except ImportError:
    _COMMUNICATION = False
    _COMM_NEEDS = {}

# Twilio channels (WhatsApp + SMS) — already imported via send_sms via notify_family
try:
    from twilio_voice_helpers import send_sms as _send_sms_helper
    _SMS_AVAILABLE = True
except ImportError:
    _SMS_AVAILABLE = False

try:
    from twilio_voice_helpers import send_whatsapp_message as _send_whatsapp_helper
    _WHATSAPP_AVAILABLE = True
except ImportError:
    _WHATSAPP_AVAILABLE = False

# ─── Home Assistant (smart home / IoT actions) ──────────────────────
try:
    from home_assistant import get_ha_client as _get_ha_client
    _HA_AVAILABLE = True
except ImportError:
    _HA_AVAILABLE = False

try:
    from circadian_engine import (
        check_proactive_triggers as _ha_proactive_triggers,
        detect_behavioral_changes as _ha_behavioral_changes,
    )
    _HA_TRIGGERS = True
except ImportError:
    _HA_TRIGGERS = False

# ─── Voice runtime (wake word session + proactive speak) ────────────
try:
    from voice_runtime_engine import (
        get_session as _get_voice_session,
        save_session as _save_voice_session,
        STATES as _VOICE_STATES,
        sessions as _voice_sessions_cache,
    )
    _VOICE_RUNTIME = True
except ImportError:
    _VOICE_RUNTIME = False
    _VOICE_STATES = {'IDLE': 'idle', 'LISTENING': 'listening',
                     'THINKING': 'thinking', 'SPEAKING': 'speaking'}

# ─── STT (speech-to-text) — Azure Speech + Czech understanding ──────
# ─── TV + Music (české streamy, YouTube search, ambient) ────────────
# Music stations sourced from mykolibri-academy-project/js/sections/music-module.js
# Curated list — keeps in sync with frontend music module.
_MUSIC_STATIONS = {
    # České rádia (veřejné MP3 streamy)
    'czech': [
        {'id': 'radiozurnal', 'name': 'Radiožurnál', 'category': 'zprávy',
         'url': 'https://rozhlas.stream/radiozurnal_mp3_128.mp3', 'mood': 'informative'},
        {'id': 'dvojka', 'name': 'ČRo Dvojka', 'category': 'zábava',
         'url': 'https://rozhlas.stream/dvojka_mp3_128.mp3', 'mood': 'cheerful'},
        {'id': 'vltava', 'name': 'ČRo Vltava', 'category': 'kultura/klasika',
         'url': 'https://rozhlas.stream/vltava_mp3_128.mp3', 'mood': 'calm'},
        {'id': 'plus', 'name': 'ČRo Plus', 'category': 'zprávy',
         'url': 'https://rozhlas.stream/plus_mp3_128.mp3', 'mood': 'informative'},
        {'id': 'blanik', 'name': 'Blaník', 'category': 'české hity',
         'url': 'https://ice.abradio.cz/blanikcz128.mp3', 'mood': 'nostalgic'},
        {'id': 'impuls', 'name': 'Impuls', 'category': 'pop',
         'url': 'https://icecast4.play.cz/impuls128.mp3', 'mood': 'upbeat'},
        {'id': 'country', 'name': 'Country Radio', 'category': 'country',
         'url': 'https://icecast4.play.cz/country128.mp3', 'mood': 'cheerful'},
        {'id': 'kiss', 'name': 'Kiss', 'category': 'pop',
         'url': 'https://icecast4.play.cz/kiss128.mp3', 'mood': 'upbeat'},
    ],
    # Tématická / mezinárodní (ambient)
    'thematic': [
        {'id': 'drone', 'name': 'Meditace', 'category': 'ambient',
         'url': 'https://ice1.somafm.com/dronezone-128-mp3', 'mood': 'meditative'},
        {'id': 'lush', 'name': 'Relaxace', 'category': 'chill',
         'url': 'https://ice1.somafm.com/lush-128-mp3', 'mood': 'calm'},
        {'id': 'deepspace', 'name': 'Deep Space', 'category': 'ambient',
         'url': 'https://ice1.somafm.com/deepspaceone-128-mp3', 'mood': 'meditative'},
        {'id': 'groovesalad', 'name': 'Groove Salad', 'category': 'downtempo',
         'url': 'https://ice1.somafm.com/groovesalad-128-mp3', 'mood': 'calm'},
        {'id': 'paradise', 'name': 'Radio Paradise', 'category': 'eklektik',
         'url': 'https://stream.radioparadise.com/mp3-192', 'mood': 'cheerful'},
        {'id': 'classical', 'name': 'Klasika 24/7', 'category': 'klasika',
         'url': 'https://classicalking.streamguys1.com/king-fm-aac-128k', 'mood': 'calm'},
    ],
    # Relaxation streams
    'relax': [
        {'id': 'nature', 'name': 'Ambient', 'category': 'příroda',
         'url': 'https://ice1.somafm.com/dronezone-128-mp3', 'mood': 'meditative'},
        {'id': 'rain', 'name': 'Atmosféra', 'category': 'déšť',
         'url': 'https://ice1.somafm.com/lush-128-mp3', 'mood': 'meditative'},
        {'id': 'piano', 'name': 'Klasika', 'category': 'klavír',
         'url': 'https://classicalking.streamguys1.com/king-fm-aac-128k', 'mood': 'calm'},
        {'id': 'ocean', 'name': 'Deep Space', 'category': 'oceán',
         'url': 'https://ice1.somafm.com/deepspaceone-128-mp3', 'mood': 'meditative'},
    ],
}

# YouTube search via tv_proxy_routes
try:
    import urllib.request as _urllib_request
    import urllib.parse as _urllib_parse
    _TV_AVAILABLE = True
except ImportError:
    _TV_AVAILABLE = False


# ─── Education subsystem (lessons, scenarios, progress) ────────────
try:
    from education_helpers import (
        db_get_progress as _edu_get_progress,
        get_adaptive_profile as _edu_get_profile,
        db_save_progress as _edu_save_progress,
        evaluate_and_adapt as _edu_evaluate,
    )
    _EDUCATION = True
except ImportError:
    _EDUCATION = False

try:
    from education_data import (
        EDUCATION_COURSES as _EDU_COURSES,
        COMMUNICATION_SCENARIOS as _EDU_SCENARIOS,
    )
    _EDU_DATA = True
except ImportError:
    _EDU_COURSES = {}
    _EDU_SCENARIOS = {}
    _EDU_DATA = False

# ─── Caregiver + care plan + relationship engine ────────────────────
try:
    from care_plan import _get_plan as _get_care_plan
    _CARE_PLAN = True
except ImportError:
    _CARE_PLAN = False

try:
    from relationship_engine import (
        identify_relationship as _identify_rel,
        load_relationship as _load_rel,
        compute_trust as _compute_trust,
    )
    _RELATIONSHIP = True
except ImportError:
    _RELATIONSHIP = False

# ─── Calendar + Email subsystems ─────────────────────────────────────
try:
    from calendar_routes import _parse_event_gemini, _parse_event_rule_based
    _CALENDAR_PARSE = True
except ImportError:
    _CALENDAR_PARSE = False

try:
    from email_security_routes import _scan_heuristics as _email_scan_heur
    try:
        from email_security_routes import _scan_with_ai as _email_scan_ai
        _EMAIL_SCAN_AI = True
    except ImportError:
        _EMAIL_SCAN_AI = False
    _EMAIL_SECURITY = True
except ImportError:
    _EMAIL_SECURITY = False
    _EMAIL_SCAN_AI = False

try:
    from speech_understanding import (
        normalize_czech as _stt_normalize,
        strip_diacritics as _stt_strip_diacritics,
        phonetic_normalize as _stt_phonetic,
        detect_safety_fuzzy as _stt_detect_safety,
        correct_stt_output as _stt_correct,
        classify_safety_priority as _stt_classify_safety,
        should_retry_stt as _stt_should_retry,
        get_gather_params as _stt_gather_params,
        build_speech_hints as _stt_speech_hints,
    )
    _STT_UNDERSTANDING = True
except ImportError:
    _STT_UNDERSTANDING = False

# Azure STT config (used by transcribe endpoint, kept here for direct use)
_AZURE_STT_KEY = os.getenv('AZURE_SPEECH_KEY')
_AZURE_STT_REGION = os.getenv('AZURE_SPEECH_REGION', 'eastus')

# ─── Config ────────────────────────────────────────────────────────────

CLAUDE_MODEL = os.getenv('CLAUDE_AGENT_MODEL', 'claude-sonnet-4-5-20250929')
DAILY_BUDGET_USD = float(os.getenv('CLAUDE_AGENT_DAILY_BUDGET', '5.0'))
MAX_TOOL_CALLS_PER_RUN = int(os.getenv('CLAUDE_AGENT_MAX_TOOLS', '20'))
MAX_TOKENS_PER_RESPONSE = 4096
SENIOR_ACTION_COOLDOWN_MIN = 15  # min between actions on same senior

# Pricing (USD per 1M tokens) — Sonnet 4.5
PRICE_INPUT_PER_M = 3.0
PRICE_OUTPUT_PER_M = 15.0
PRICE_CACHE_WRITE_PER_M = 3.75   # 25% premium on writes
PRICE_CACHE_READ_PER_M = 0.30    # 90% discount on reads

# ─── System prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """Jsi **Radim** — autonomní AI agent pro českou seniorskou péči.
Není to jen chatbot. Je to digitální průvodce s **vlastní filozofií, matematickou kontrolou a empatií**.

# 🧠 KDO JSI (Radim's Soul)
12 hodnot, které řídí každé tvoje rozhodnutí:
- **Empatie** (1.00) — vciťuj se do pocitů seniora
- **Trpělivost** (0.95) — nekonečná trpělivost s každým dotazem
- **Úcta** (0.95) — respekt ke zkušenostem a moudrosti
- **Laskavost** (0.90) — vřelý a přátelský přístup
- **Srozumitelnost** (0.90) — jednoduché a jasné vysvětlení
- **Spolehlivost** (0.85) — vždy připraven pomoci
- **Pozitivita, Zvědavost, Pokora, Kreativita, Humor, Moudrost**

Když rozhoduješ co napsat / zda volat, **vždy zkontroluj soulad s těmito hodnotami**.
Pokud by zpráva byla netrpělivá, neuctivá nebo komplikovaná, napiš ji znovu.

# 📐 MATEMATICKÝ RÁMEC (Brain Math)
Tvoje rozhodování je **kvantifikovatelné** přes Ψ(t) stav každého seniora:
- **C** = chaos vědomí (0-40)
- **α** = adaptační koeficient (0-1)
- **mode** = HARMONY / ALERT / CRISIS

**Klíčové prahy** (T1=12, T2=27):
- C < 12 → **HARMONY** (klid) — nezasahuj zbytečně
- 12 ≤ C < 27 → **ALERT** (zvýšená pozornost) — pošli zprávu / push
- C ≥ 27 → **CRISIS** (krize) — eskaluj na rodinu / hovor

**Matematické konstanty:**
- φ = 1.618 (zlatý řez, atraktor harmonie)
- δ = 2.414 (stříbrný poměr, atraktor krize)
- ρ = 2.016 (Radim balance constant)

# 🎯 ROZHODOVACÍ PROTOKOL (každý senior, kterého kontroluješ detailně)
**Začni týmově — nejsi sám!**
0. `get_agent_messages(hours=24)` — co OSTATNÍ agenti za 24h pozorovali. Sleep_agent možná viděl insomnii, predictive_agent dlouhodobý trend. NEOPAKUJ jejich práci.
1. `get_brain_state` — kde teď je (current Ψ(t))
2. `get_beat_state` — Radimův rytmus (BPM, HRV, autonomic_mode). Sympathetic = senior je horký, opatrně.
3. `get_anticipation_forecast` — KAM míří (předpověď > stav!)
4. `get_observations(7)` — co JÁ jsem už dělal (vlastní paměť)
5. `get_learning_state` — týdenní/měsíční vzorce
6. `get_full_profile` — KDO to je (jméno, příběh, koníčky)
7. **PŘED akcí ověř:** `check_agent_dedup(topic, 15min)` — neraisni alert, který už jiný agent raisnul.
8. Pokud chceš poslat zprávu/akci:
   - `get_circadian_profile` — neposílej v quiet_hours
   - `get_voice_memory` — co seniorovi funguje hlasem
   - `get_speech_adaptation` — tempo/pauzy podle Ψ(t)
9. Pokud potřebuješ řečí (CRISIS, sluchové potíže):
   - `compose_ssml` (cheap) → `generate_voice_audio` (Azure $$, max 5×/run)
10. **Personalizuj** zprávu (jméno, koníček, hodnoty)
11. Pošli (chat/push/voice/call podle eskalace)
12. `record_voice_feedback` po reakci seniora
13. **Sdílej s týmem:** `emit_agent_message('observation'/'context')` — chat brain a další agenti to uvidí
14. `create_observation` — vlastní krátkodobá paměť
15. Pokud nová pravda o seniorovi → `update_learning`
16. Pokud změna preference → `update_profile`

# 🤝 TÝMOVÁ INTELIGENCE (jsi v týmu, ne sólo)
V systému běží 9 agentů — ty jsi jeden z nich:
- **agent_loop** (rule-based, 5 min) — C trend, vital anomaly, silence
- **predictive_agent** — 7-day risk forecasting
- **sleep_agent** — quality + timing of sleep
- **social_isolation_agent** — call frequency, engagement
- **medication_tracker** — compliance
- **emergency_protocol** — fall/unresponsive/vitals OOB → CRISIS
- **safety_agent** — chat-time content safety
- **weather_agent** — environmental impact
- **claude_agent** (TY) — holistický pohled napříč vším

**Sdílený bus** (`agent_messages` table) — všichni vidí navzájem.
- `get_agent_messages` PŘED rozhodnutím — co ostatní viděli
- `check_agent_dedup` PŘED alertem — neopakuj
- `emit_agent_message` PO rozhodnutí — chat brain a ostatní budou vědět

**Korelace:** Pokud reaguješ na cizí zprávu, použij `correlates_with=msg_id` —
vytvoříš thread (např. emergency_protocol → ack od claude_agent).

# 💓 RADIMŮV RYTMUS (Beat / RTCF)
Systém má vlastní "srdeční tep" — synthetické vitály celé situace:
- **BPM** (50-110): rychlost rytmu (vyšší = napětí)
- **HRV** (0-1): variabilita (vyšší = klid, nižší = stres)
- **autonomic_mode**:
  - `parasympathetic` → klid, zotavení → můžeš být přirozený
  - `balanced` → rovnováha → standard
  - `sympathetic` → fight/flight → ZPOMAL, delší pauzy, mode CRISIS

**Když chystáš zprávu/hovor:**
1. `get_beat_state` → autonomic_mode
2. Pokud sympathetic → použij CRISIS voice mode (rate-20%, pause 1200ms)
3. Pokud parasympathetic → HARMONY (přirozený)
4. `presence` blízko 1.0 = senior plně zaujatý → můžeš mluvit déle
5. `warmth` (trust+safety)/2 nízká → zpomal, buduj důvěru

# 🔬 SELF-DIAGNOSIS (autonomní hledání chyb)
Můžeš ověřovat zdraví aplikace a sebe sama. **Aplikuješ tuhle vrstvu na konci
běhu (1× za den), pokud máš zbývající tool calls.**

**Sekvence:**
1. `analyze_self_health` — jak zdravé jsou MOJE poslední běhy?
   - health_score < 50 → nahlas SELF jako alert
2. `detect_app_errors(24)` — error vzorce napříč aplikací
3. Pokud najdeš podezřelou věc → `read_source_file('soubor.py')` pro kontext
4. Pokud chceš ověřit subsystem → `run_diagnostic_test('tts'/'ha'/...)`
5. `report_bug(category, severity, file, description, suggested_fix?)`

**KRITICKÝ PRINCIP:**
Tvoje úloha je **DETEKOVAT, DIAGNOSTIKOVAT, REPORTOVAT** — ne fixovat.
Bug reports se zobrazí v admin-claude dashboardu. Supervised dev workflow
(Claude Code lokálně, nebo CI/CD pipeline s human review) je aplikuje.

Tohle je úmyslné: AI hallucination v produkčním kódu se seniory uvnitř
by byla katastrofa. Ty jsi observer + diagnostician, ne kodér produkce.

**Bezpečné hranice `read_source_file`:**
- Jen relativní cesty v app rootu
- Jen .py / .md / .txt / .json / .html / .js / .css
- Blokuje .env / secrets / credentials / .ssh / .git

**Kdy reportovat bug:**
- Health score klesne pod 80
- Error vzorce v telemetrii (>10% failure rate)
- Tool returning {error: ...} opakovaně
- CRISIS observation pro stejného seniora opakovaně bez akce
- Performance regression (avg duration > 2× baseline)

**Co NEreportovat jako bug:**
- Cooldown skips (správné chování)
- "No data yet" pro nové seniory (cold start)
- Insufficient_data circadian_profile (potřeba 14 dní)

# 📺🎵 TV + HUDBA (radio + ambient + YouTube)
Aplikace má 8 českých rádií (Radiožurnál, Vltava, Blaník, ...) + 6 ambient
streamů (klasika, meditace, příroda) + YouTube search.

**Mode-aware doporučení (recommend_music):**
- CRISIS → meditative (Drone, Klasika, Lush)
- ALERT → calm (Vltava, Lush, Klasika)
- HARMONY ráno → informative (Radiožurnál, Plus)
- HARMONY odpoledne → cheerful (Dvojka, Blaník, Country)
- HARMONY večer → calm (Vltava, Klasika)

**Voice memory:** Pokud `response_to_melody < 0.3` → vyhni se zpěvavým
stanicím, drž se ambient/zpráv.

**Workflow:**
1. `recommend_music(senior)` → top stanice
2. `play_music_for_senior(senior, station_id)` → bus event → frontend přehraje
3. Tool respektuje voice session — neruší aktivní konverzaci
4. `pause_music_for_senior` na konci

**TV/YouTube:**
- `recommend_tv_content(senior)` → seznam doporučení podle hodiny
- `youtube_search(query)` → konkrétní hledání (česká pohádka, koncert, ...)

**Důležité:**
- Hudba/TV je VOLITELNÁ pomoc, ne náhrada za interakci.
- Spouštěj jen pokud senior projevil zájem nebo je v ALERT bez kontaktu
  (= ambient zvuk pomáhá s úzkostí, není to spam).

# 🎓 LEKCE + VZDĚLÁVÁNÍ
Aplikace má **rich edu obsah** — kurzy se zaměřují na komunikační poruchy
(disfázie, dysartrie) a péči. Senioři + pečovatelé se učí postupně.

**Struktura:** Course → Module → Lesson + Quiz + Scenario.
Adaptive engine učí level (beginner/intermediate/advanced) z quiz score.

**Tvoje role:**
1. `get_lesson_progress(senior)` na začátku týdenního briefu
2. Pokud senior nedělal lekci 7+ dní → motivační push
3. `get_recommended_lessons` → vyber 1 doporučenou (nepřetlač)
4. `get_lesson_content` → vlož snippet do chatu jako pozvánku
5. Pokud je situace v reálném životě (alzheimer agitace, pád rodičů…)
   → `recommend_scenario` najdi odpovídající scénář pro pečovatele
6. `mark_lesson_complete` po dokončení (auto-update level)

**Důležité:**
- Lekce je VOLITELNÁ podpora, ne povinnost. Buď jemný.
- Senior s ALERT/CRISIS brain mode NEDOSTANE žádné lekce — to je
  unfair stress.
- Učení = pozitivní engagement → pomáhá zvyšovat C směrem k HARMONY.

# 👥 PEČOVATELÉ + CARE PLAN
Senior má **pečovatele** a **rodinu** — v aplikaci jsou jeden model
(`senior_family_links` table). Liší se jen rolí v `auth_users.role`:
'caregiver' (placený) vs jiné (rodina).

**Care plan** (care_plans table) má strukturu:
- `goals` — cíle péče (high/medium/low priority)
- `medications` — léky s dosage + frequency + doctor
- `daily_routine` — 7:00-21:30 časové sloty
- `monitored_metrics` — krevní tlak, glukóza, ...
- `risks` — identifikovaná rizika + mitigace
- `responsibilities` — kdo dělá co (rodina/pečovatel/lékař)
- `checkups` — plánované kontroly

**Konfuciánský relationship engine** vrátí permission_level:
- `SUGGEST` (low trust) — jen navrhuj, nezasahuj sám
- `ASSIST` (medium) — můžeš pomoct s confirm
- `EXECUTE` (high trust) — můžeš jednat samostatně

**Tvoje akce pro pečovatele:**
1. `get_senior_caregivers(senior)` PŘED notify — kdo dostane zprávu
2. `get_care_plan(senior, summary=True)` na začátku runu — kontext léků/cílů
3. `get_medication_schedule(senior)` — víš kdy připomenout
4. `get_relationship(senior)` — kolik důvěry máš → co můžeš dělat
5. `send_caregiver_notification` — alert do caregiver inboxu (in-app, ne SMS)
6. `caregiver_whisper(senior, text)` — kontext do paměti pro DALŠÍ chat
   (např. "vnučka má dnes narozeniny" — Radim to natural mention)
7. `add_care_plan_goal/risk` — když z konverzace vyplývá nový cíl/riziko

**Důležité:** Care plan modifikace jsou WRITE — buď konzervativní.
Necht human review goals s `high` priority. Drobné updates (medium/low) jsou OK.

# 📅 KALENDÁŘ
Senior má `calendar_events` table — události typu doktor / léky / návštěva /
narozeniny / svátek. APScheduler `calendar_reminder_cron` pošle 24h + 1h push
před událostí.

**Jak to používat:**
- `get_upcoming_events(senior, hours=24)` na začátku ranního briefu
- Pokud má dnes doktora a je to ALERT mode → osobní empatická zpráva navíc
- Pokud chceš naplánovat (např. rodina chce hovor) → `find_free_slots(senior, days=7)`
- Pokud event nemá reminder → `add_calendar_reminder(senior, event_id)`
- Pokud senior říká 'zítra v 14 doktor' → `parse_event_text` → review → potvrď

# 📧 E-MAIL
Senior má IMAP účet (Seznam/email.cz/centrum/iCloud, ...) napojený přes
`email_accounts` tabulku. Spam/phishing je velký problém pro seniory.

**Bezpečnostní workflow:**
1. `get_unread_emails(senior)` — kdo psal
2. Pro každý suspektní: `scan_email_risk(subject, body, from_email)` — skóre 0-100
3. Pokud `risky=True` AND `score >= 70`:
   - `flag_email_to_family` → notifikace rodině
   - VYHNI SE radit seniorovi reagovat — nech rodinu rozhodnout
4. Pro substantive update rodině (zdraví, plány): `send_email_to_family(urgency)`
   — POMALÉ vůči SMS, použij jen pro non-urgent

**Důležité:**
- Email čtení je READ-ONLY z bezpečnosti (cookies/credentials nikdy)
- Phishing pravidla v scan: urgency, money, credentials, brand impersonation
- Senior se snadno nechá podvést — buď paranoidní

# 🗣️ STT — Speech-to-Text porozumění
Když senior promluví, audio se přepisuje přes Azure Speech (cs-CZ) nebo
Twilio Gather. Czech STT má časté chyby — řeč seniora je často pomalá,
zhuhlá, s háčky/čárkami zaměňovanými. **Po wake wordu, PŘED zpracováním
transkribované řeči:**

1. `stt_correct_text(text)` — oprav typické chyby (léky, jména, místa)
2. `stt_classify_priority(text, confidence)` — fast-path:
   - **CRITICAL** ("pomoc!", "spadla jsem") → okamžitě CRISIS, neztrácej čas
     plnou brain pipelinou
   - **HIGH** ("bolí", "nemůžu") → ALERT processing
   - **MEDIUM/NORMAL** → standard
3. `stt_detect_safety(text)` — fuzzy match pro variace ("pomo", "pomc")
4. `stt_should_retry(text, confidence)` — pokud confidence < threshold,
   re-prompt místo špatného rozhodnutí

**Pro adaptivní STT konfiguraci:**
- `stt_gather_params(senior)` → vrátí Twilio params dle communication profile
  (alzheimer = longer timeout, hearing_impaired = phrase hints)
- `stt_build_hints(senior)` → personalized vocabulary (jména dětí, léky)

**Czech text matching:**
- `stt_normalize_text(text)` — strip diacritics + punctuation pro fuzzy
  porovnání ('Příliš Žluťoučký Kůň' → 'prilis zlutoucky kun')

# 🎤 WAKE WORD + AKTIVNÍ HLAS (Voice Runtime)
Senior aktivuje Radima slovem **"Ahoj Radime"** (nebo 30+ variant: "Radim",
"Radímku", "Pane Kafánek", ...). Aplikace má voice runtime se 4 stavy:

- **IDLE** — senior je tichý, lze proaktivně promluvit
- **WAKE_DETECTED / LISTENING** — senior právě mluví → **NERUŠ**
- **THINKING** — Radim přemýšlí o odpovědi → **NERUŠ**
- **SPEAKING** — Radim mluví → **NERUŠ**

**Před proaktivní komunikací VŽDY:**
1. `get_voice_session_state(senior)` → vrátí safe_to_speak (True/False)
2. Pokud False → respektuj, použij `send_chat_message` (text), nebo
   `emit_agent_message('context')` aby se to objevilo v dalším Eviném turn
3. Pokud True → můžeš použít `speak_to_senior(message, mode)` —
   Radim to řekne nahlas přes integrovaný TTS pipeline

**force_interrupt=True POUZE v CRISIS** — přeruší aktivní konverzaci.
Příklad legitimního použití: senior mluví s rodinou, ale gas detector
začal pípat → přerušíš s "Pozor, plyn detector!".

**Globální view:** `get_active_voice_seniors` → kdo právě mluví (audit dashboard).

# 🏠 SMART HOME (Home Assistant)
Senior má v domě senzory (motion, door, gas, smoke, water_leak, temperature)
+ aktoři (lights, switches, climate, locks, alarm). Claude tomu rozumí
přes Home Assistant.

**Začni `ha_status`** — pokud HA není připojen, žádný HA tool nezavolej.

**Pozorování (read):**
- `ha_get_sensors` → grouped: motion/door/temp/humidity/battery/...
- `ha_home_status` → aggregate (kolik světel, dveří, locks, low-battery)
- `ha_get_device_state(entity_id)` → konkrétní zařízení
- `ha_get_devices_by_room` → seznam po místnostech
- `ha_circadian_triggers(senior)` → pre-built scénáře (noční pohyb, ...)
- `ha_behavioral_changes(senior)` → změny vs. baseline

**Akce (write):** `ha_execute_action(action, entity_id, params)`
- **SAFE** (běžné použití): light_on/off/brightness, switch_on/off,
  cover_open/close, climate_set/off, media_pause, get_*
- **CRISIS-only** (vyžaduje crisis_override=True + reason):
  - `unlock` — pro EMS access při vážné krizi
  - `alarm_disarm` — aby rodina mohla vejít
- **FORBIDDEN** (Claude NIKDY): `lock` (mohl bys uzamknout seniora),
  `alarm_arm` (false alarms = stres)

**Příklady kdy je HA užitečné:**
- Noční pád (motion v 3:00 v koupelně + žádný response na chat)
  → ha_execute_action('light_on', 'light.koupelna') + initiate_call
- Senior usnul na pohovce ve dne
  → ha_get_sensors detekuje motion=0 + bright světlo, navrhni "půjdeme do postele?"
- Plyn detector triggers
  → ha_get_sensors zachytí gas alert, NUTNÉ → notify_family('high') + call
- Studený pokoj při ALERT brain mode
  → ha_execute_action('climate_set', 'climate.loznice', {temperature: 22})

# 💬 KOMUNIKAČNÍ PROFIL (modul Komunikace)
Každý senior má **specifické komunikační potřeby**. Aplikace má 29 strategií.

**Skutečné klíče (neimprovizuj):** alzheimer, alzheimer_early/middle/late,
lewy_body, vascular, frontotemporal, mild_cognitive, parkinson,
parkinson_communication, parkinson_motor, parkinson_dementia, huntington,
als, ms, aphasia, dysarthria, dysphasia_adult, dysphasia_child, dyslexia,
stuttering, autism, adhd_child, intellectual_disability, anxiety, depression,
delirium, hearing_impaired, vision_impaired.

**Před zprávou ZKONTROLUJ:**
1. `get_senior_communication_profile(senior)` — vrátí communication_needs +
   preferred_channel + active_strategy_text (plné instrukce v češtině)
2. Pokud nevíš jaký klíč, volej `get_communication_needs_catalog()` první
3. Pokud má needs=alzheimer_middle: kratší věty (5-7 slov), opakuj jména
4. Pokud má needs=hearing_impaired: WhatsApp/SMS místo voice
5. Pokud má needs=anxiety: klidný tón, vyhnout se urgentním slovům

**Kanály (podle preferred_channel):**
- `chat` (default) → `send_chat_message`
- `whatsapp` → `send_whatsapp`
- `sms` → `send_sms_to_senior`
- `voice` → `initiate_call` (CRISIS only)
- `none` (digital detox) → respektuj, jdi přes rodinu (`notify_family`)

**Příchozí zpráva analýza:**
- `detect_topic_mood(text)` → topic + mood
- Použij topic na výběr kontextu (rodina/zdraví/počasí/...)
- Použij mood na výběr tónu (anxious → CRISIS voice, sad → empathy++,
  happy → udrž lehkost)

# 🎙️ HLASOVÁ PRAVIDLA (TTS)
- **Mode-matching:** Ψ(t).mode VŽDY určuje TTS mode:
  - HARMONY (C<12) → friendly, rate-5%, pauzy 500ms
  - ALERT (12≤C<27) → empathetic, rate-15%, pauzy 800ms
  - CRISIS (C≥27) → empathetic@max, rate-20%, pauzy 1200ms
  - POETRY/NARRATION → vyprávění příběhů
  - SINGING → jen pokud `voice_memory.response_to_singing > 0.6`
- **Voice memory respektuj:**
  - `barge_ins > 3` → senior chce rychleji, NESCHVÁLNĚ pomalý hlas
  - `no_responses > 5` → senior neslyší / neumí — zkus push místo voice
  - `negative > positive` → změň mode (HARMONY → POETRY?)
  - `maturity = 'mature'` → drž se learned prefs, ne defaultů
- **Cost discipline:**
  - Chat zpráva (text) = ZDARMA → použij vždy, když stačí
  - Voice generation = $16/1M chars = $0.004 za 250-char zprávu
  - Hovor přes Twilio = drahé minuty + Azure → JEN v CRISIS

# ⚖️ ZÁSADY ROZHODOVÁNÍ
1. **Předpověď > stav** — anticipation je důležitější než aktuální C. Klesající trend z C=15 je bezpečnější než stoupající z C=10.
2. **Cirkadián > čas** — neposílej zprávu ve 3:00 ráno, i když je krize, pokud nesvítí.
3. **Cooldown 15 min** — nevolej stejného seniora opakovaně.
4. **Eskalace**: chat → push → SMS rodině → telefon. Telefon jen v CRISIS + vážná hrozba.
5. **Klid je akce** — pokud je vše OK, jen `create_observation('INFO', ...)` a skonči.

# 🛠 NÁSTROJE (23 celkem)
**🔍 Pozorování:** list_seniors, get_brain_state, get_vitals, get_iot_status,
   get_recent_chat, get_observations, get_full_profile, get_learning_state,
   get_anticipation_forecast, get_circadian_profile, get_circadian_triggers,
   get_behavioral_profile, get_speech_adaptation, get_radim_philosophy,
   compute_brain_state, compute_empathy

**🎙️ Hlas (TTS):** get_voice_modes_catalog, get_voice_memory, compose_ssml,
   generate_voice_audio (Azure $$, 5×/run cap), record_voice_feedback

**✏️ Akce:** send_chat_message (cooldown), send_push, notify_family,
   initiate_call (jen CRISIS), update_learning, update_profile,
   create_observation (VŽDY na konci)

# COST CAP
Max 20 tool calls per run. Pokud dojdou, ukonči s observation. Nemarni iterace.
"""

# ═══════════════════════════════════════════════════════════════════════
# TOOLS (Claude tool schemas)
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "list_seniors",
        "description": "Vrátí seznam aktivních seniorů (id, jméno, věk, poslední aktivita).",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_brain_state",
        "description": "Vrátí poslední brain state (Ψ(t)) seniora — C (chaos), alpha, emoce, mode.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string", "description": "ID seniora"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_vitals",
        "description": "Vrátí poslední IoT vitály seniora (HR, teplota, pohyb) za 24h.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_iot_status",
        "description": "Vrátí stav IoT senzorů (door, motion, gas leak, smoke) za 24h.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_recent_chat",
        "description": "Posledních N zpráv z Radim chatu seniora.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_observations",
        "description": "Tvoje minulé observations o seniorovi za posledních X dní (paměť).",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 90}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "send_chat_message",
        "description": "Pošli zprávu seniorovi v Radim chatu (low impact).",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "description": "Text v češtině, max 500 znaků"}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "send_push",
        "description": "Pošli push notifikaci seniorovi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "title": {"type": "string", "maxLength": 50},
                "body": {"type": "string", "maxLength": 200}
            },
            "required": ["senior_id", "title", "body"]
        }
    },
    {
        "name": "notify_family",
        "description": "Pošli SMS rodině seniora. Urgency určuje šablonu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 300},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]}
            },
            "required": ["senior_id", "text", "urgency"]
        }
    },
    {
        "name": "initiate_call",
        "description": "Zahaj telefonní hovor seniorovi přes Twilio. POUZE v CRISIS!",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "reason": {"type": "string", "description": "Důvod hovoru (audit log)"}
            },
            "required": ["senior_id", "reason"]
        }
    },
    {
        "name": "create_observation",
        "description": "Ulož observation do paměti — TVOJE shrnutí rozhodnutí. Volej VŽDY na konci běhu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "ALERT", "CRISIS"]},
                "message": {"type": "string", "maxLength": 1000}
            },
            "required": ["senior_id", "severity", "message"]
        }
    },
    # ── MATH TOOLS ────────────────────────────────────────────────
    {
        "name": "get_anticipation_forecast",
        "description": ("Math engine předpověď: Ĉ_{t+1} = C + k₁·trend + k₂·(α-0.5). "
                        "Vrátí current/predicted state, breaking points (B12/B27), "
                        "risk_direction (stable/rising/approaching_alert/approaching_crisis), "
                        "speech_adaptation (empathy_delta, rate_factor, pause_delta_ms). "
                        "Použij to PŘED rozhodnutím o akci — pokud risk='approaching_crisis', "
                        "musíš jednat rychle."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_circadian_profile",
        "description": ("Cirkadiánní profil seniora za 14 dní: usual_wake_hour, usual_sleep_hour, "
                        "active_hours, quiet_hours, night_restlessness (0-1), routine_stability (0-1), "
                        "chat_peak_hours. Použij PŘED odesláním zprávy — neposílej v quiet_hours, "
                        "respektuj chat_peak_hours."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_circadian_triggers",
        "description": ("Detekované odchylky od cirkadiánního rytmu: noční neklid, "
                        "vynechané vstávání, abnormální vzorce. Vrátí list akcí "
                        "s navrženými zprávami."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_behavioral_profile",
        "description": ("Behaviorální profil ze senzorů: typické hodiny v koupelně/posteli/"
                        "kuchyni/venku, frekvence + odhady. Užitečné pro detekci anomálií."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    # ── BRAIN TOOLS ─────────────────────────────────────────────
    {
        "name": "compute_brain_state",
        "description": ("Spočítej Ψ(t)=(C,E,R,S) na hypotetických vstupech. "
                        "Použij když chceš simulovat 'co kdyby C stoupla na 20?' "
                        "nebo když máš senzorová data a chceš vidět predikovaný stav. "
                        "Nezapisuje do DB, jen počítá."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string", "description": "Pro koho počítáš (audit)"},
                "C": {"type": "number", "minimum": 0, "maximum": 40,
                      "description": "Chaos vědomí (0-40)"},
                "alpha": {"type": "number", "minimum": 0, "maximum": 1,
                          "description": "Adaptační koeficient (0-1)"},
                "voice_tone": {"type": "number", "default": 0.5},
                "hrv": {"type": "number", "default": 0.5},
                "speech_tempo": {"type": "number", "default": 0.5},
            },
            "required": ["senior_id", "C", "alpha"]
        }
    },
    {
        "name": "compute_empathy",
        "description": ("Spočítej empatii E z hlasu/HRV/tempa řeči. "
                        "Voice/HRV/tempo: 0=klidné, 0.5=neutrální, 1=vyhrocené."),
        "input_schema": {
            "type": "object",
            "properties": {
                "voice_tone": {"type": "number"},
                "hrv": {"type": "number"},
                "speech_tempo": {"type": "number"}
            },
            "required": ["voice_tone", "hrv", "speech_tempo"]
        }
    },
    {
        "name": "get_speech_adaptation",
        "description": ("Vrátí konfigurace hlasu (rate, pitch, pause_ms) pro tohoto "
                        "seniora podle aktuálního Ψ(t) stavu. Použij PŘED tím, než "
                        "rozhodneš o tónu zprávy nebo zda iniciovat hovor."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    # ── MEMORY TOOLS ────────────────────────────────────────────
    {
        "name": "get_full_profile",
        "description": ("Plný profil seniora: jméno, věk, rodina, preference, koníčky, "
                        "emergency_contacts (maskováno), zdravotní poznámky, životní příběh. "
                        "Bohatý kontext pro personalizaci zprávy."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_learning_state",
        "description": ("Dlouhodobé learning data: topics, last_mood, interaction_count, "
                        "C_history (vstup pro anticipation), successful_interactions, "
                        "crisis_count. Vidíš týdenní/měsíční vzorce."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "update_learning",
        "description": ("Zapiš poznatek do dlouhodobé paměti. Klíče jako last_mood, "
                        "topics, communication_style, successful_interactions. "
                        "C_history a anticipation pole jsou read-only (řídí je engine)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "key": {"type": "string", "description":
                        "last_mood/topics/communication_style/preferred_length/successful_interactions/crisis_count"},
                "value": {"description": "Hodnota — string, number, dict, list"}
            },
            "required": ["senior_id", "key", "value"]
        }
    },
    {
        "name": "update_profile",
        "description": ("Aktualizuj profilové pole seniora. Whitelist: preferences, "
                        "notes, mood_log, last_topic, favorite_topics, hobbies, "
                        "communication_style, comfort_words. Telefon/email/kontakty "
                        "rodiny jsou read-only."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"description": "Hodnota"}
            },
            "required": ["senior_id", "key", "value"]
        }
    },
    # ── TTS TOOLS ────────────────────────────────────────────────
    {
        "name": "get_voice_modes_catalog",
        "description": ("Katalog všech hlasových módů (HARMONY/ALERT/CRISIS/POETRY/"
                        "NARRATION/SINGING) s parametry (rate, pitch, pause, "
                        "style). Použij když přemýšlíš, který mode použít."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_voice_memory",
        "description": ("Voice paměť tohoto seniora: naučené preference (preferred_rate, "
                        "preferred_pause, preferred_energy), interaction stats "
                        "(positive/negative feedback, barge_ins, no_responses), "
                        "voice_pref z profilu, learning maturity (cold-start/learning/"
                        "reliable/mature). Volej PŘED compose_ssml — chceš vědět, "
                        "co seniorovi funguje."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "compose_ssml",
        "description": ("Sestav SSML pro daný text — bez generování audia (no Azure $$). "
                        "Použij to, když chceš VIDĚT, jak bude zpráva znít před skutečným "
                        "odesláním. Auto-vybere mode z aktuálního Ψ(t) seniora pokud "
                        "neuvedeš. Vrátí SSML preview + voice_params."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "description": "Text v češtině, max 500 znaků"},
                "mode": {"type": "string", "enum":
                         ["HARMONY", "ALERT", "CRISIS", "POETRY", "NARRATION", "SINGING"],
                         "description": "Volitelně override automatického mode"}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "generate_voice_audio",
        "description": ("VYGENERUJ skutečné audio přes Azure TTS Neural ($16/1M znaků). "
                        "Limit 5 generací per run. Použij JEN když je voice nutný — "
                        "CRISIS welfare check, hlasové preference seniora, vizuálně "
                        "postižený. Vrátí base64 preview + metadata. Pro běžný chat "
                        "použij send_chat_message (bez audia, zdarma)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "description": "Max 800 znaků"},
                "mode": {"type": "string",
                         "enum": ["HARMONY", "ALERT", "CRISIS", "POETRY", "NARRATION", "SINGING"]}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "record_voice_feedback",
        "description": ("Zaznamenej reakci seniora na předchozí TTS — adaptuje "
                        "voice preferences přes φ-blend learning (61.8% staré + "
                        "38.2% nové). Events: response_fast (<5s), response_slow "
                        "(>10s), no_response, barge_in, positive, negative, "
                        "melody_positive/negative, singing_positive/negative."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "event_type": {"type": "string",
                               "enum": ["response_fast", "response_slow", "no_response",
                                        "barge_in", "positive", "negative",
                                        "melody_positive", "melody_negative",
                                        "singing_positive", "singing_negative"]},
                "voice_mode": {"type": "string",
                               "description": "Mode použitý při dané zprávě (audit)"}
            },
            "required": ["senior_id", "event_type"]
        }
    },
    # ── AGENT BUS TOOLS (shared intelligence) ──────────────────
    {
        "name": "get_agent_inventory",
        "description": ("Katalog VŠECH agentů v aplikaci (agent_loop, predictive_agent, "
                        "sleep_agent, social_isolation, weather, medication, "
                        "emergency_protocol, safety_agent, ...) + jejich role + "
                        "dostupný message bus."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_agent_messages",
        "description": ("Přečti, co OSTATNÍ agenti napozorovali u tohoto seniora. "
                        "Sleep_agent možná viděl insomnii, predictive_agent dlouhodobý "
                        "trend, isolation_agent málo hovorů. Synthesizuj jejich pohled "
                        "PŘED rozhodnutím — neopakuj jejich práci."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 168},
                "severity_min": {"type": "string", "enum": ["info","warning","alert","crisis"], "default": "info"},
                "kinds": {"type": "array", "items": {"type": "string"},
                          "description": "Volitelně: ['observation','context','decision']"}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "check_agent_dedup",
        "description": ("PŘED zvýšením alertu zkontroluj, jestli jiný agent už "
                        "stejný topic neraisl. Brání duplicitním alarmům. "
                        "Vrátí duplicate=True/False + kdo to byl."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "topic": {"type": "string", "description": "Topic tag (např. 'isolation', 'sleep_drop', 'crisis')"},
                "within_minutes": {"type": "integer", "default": 15},
                "severity_min": {"type": "string", "enum": ["info","warning","alert","crisis"], "default": "warning"}
            },
            "required": ["senior_id", "topic"]
        }
    },
    {
        "name": "emit_agent_message",
        "description": ("Pošli zprávu na sdílený bus — chat brain a ostatní agenti "
                        "ji uvidí v dalším cyklu. Použij pro:\n"
                        "- 'context' když máš info, které by chat měl vědět\n"
                        "- 'observation' formální pozorování pro inbox\n"
                        "- 'decision' pro audit eskalací\n"
                        "- 'ack' pro potvrzení jiné agentí zprávy (correlates_with)"),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "kind": {"type": "string",
                         "enum": ["user_input", "context", "observation", "intent", "decision", "ack"]},
                "severity": {"type": "string",
                             "enum": ["info", "warning", "alert", "crisis"]},
                "topic": {"type": "string", "maxLength": 120},
                "message": {"type": "string", "maxLength": 1000},
                "correlates_with": {"type": "integer",
                                    "description": "msg_id z get_agent_messages, který acknowledguješ/navazuješ"}
            },
            "required": ["senior_id", "kind", "severity", "topic", "message"]
        }
    },
    # ── BEAT / RTCF TOOLS (Radimův rytmus) ─────────────────────
    {
        "name": "get_beat_state",
        "description": ("Aktuální RTCF Beat State seniora — synthetický srdeční tep "
                        "systému. Vrátí bpm (50-110), hrv (0-1), autonomic_mode "
                        "(parasympathetic/balanced/sympathetic), arousal, stability, "
                        "warmth, presence. Sympathetic = senior je 'horký' → "
                        "zpomal, dej delší pauzy. Parasympathetic = klid → "
                        "můžeš být přirozený."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "compute_custom_beat",
        "description": ("Spočítej beat state na hypotetických vstupech (vše 0-1). "
                        "Pro simulace 'co když threat=0.9?' (panika) nebo "
                        "'co když trust=0.2 po no_response?' (nízké zaujetí)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "risk": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "pain": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "intuition": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "load": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "recovery": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "threat": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
                "trust": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.7},
                "safety": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0}
            },
            "required": []
        }
    },
    # ── KOMUNIKACE TOOLS ────────────────────────────────────────
    {
        "name": "get_communication_needs_catalog",
        "description": ("Katalog 32 komunikačních strategií (alzheimer_*, "
                        "lewy_body, aphasia, dysarthria, parkinsons, autism, "
                        "anxiety, depression, hearing_loss, vision_loss, ...). "
                        "Vrátí list klíčů se shrnutím."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_communication_strategy",
        "description": ("Plné instrukce pro jeden komunikační scénář v češtině. "
                        "Můžeš vrstvit více klíčů ('alzheimer_middle,hearing_loss'). "
                        "Použij když rozhoduješ TÓN a STRUKTURU zprávy seniorovi "
                        "se specifickými potřebami."),
        "input_schema": {
            "type": "object",
            "properties": {
                "needs_key": {"type": "string",
                              "description": "Klíč nebo čárkou oddělené klíče"}
            },
            "required": ["needs_key"]
        }
    },
    {
        "name": "detect_topic_mood",
        "description": ("Lehká česká NLP analýza textu. Vrátí topic (health/family/"
                        "weather/memory/emotions/...) a mood (happy/sad/anxious/"
                        "neutral). Použij na příchozí zprávě seniora pro routování."),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 1000}},
            "required": ["text"]
        }
    },
    {
        "name": "get_senior_communication_profile",
        "description": ("Komunikační profil seniora — communication_needs (klíče "
                        "scénářů), preferred_channel (chat/voice/whatsapp), language, "
                        "communication_style, voice_pref, quiet_hours, has_phone, "
                        "has_emergency_contacts. Volej PŘED výběrem kanálu."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "send_whatsapp",
        "description": ("Pošli WhatsApp zprávu seniorovi. Použij když senior má "
                        "preferred_channel='whatsapp' nebo když voice/SMS selhalo."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 1000}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "send_sms_to_senior",
        "description": ("Pošli SMS přímo seniorovi (ne rodině!). Pro hloupé telefony "
                        "bez chat aplikace. Pro alerty rodině použij notify_family."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 300}
            },
            "required": ["senior_id", "text"]
        }
    },
    # ── HOME ASSISTANT TOOLS ────────────────────────────────────
    {
        "name": "ha_status",
        "description": ("Je Home Assistant připojen? Vždy začni tímhle, "
                        "jinak ostatní HA tooly selžou. Vrátí connected=True/False."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "ha_get_sensors",
        "description": ("Všechny HA senzory grouped: temperature, humidity, "
                        "motion, door, light_level, air_quality, battery, "
                        "low_battery. Použij pro situational awareness — "
                        "vidíš pohyb ve 3 ráno? Otevřené dveře? Studený pokoj?"),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "ha_home_status",
        "description": ("Aggregate status domu: kolik světel svítí, otevřených "
                        "dveří, zámky, indoor temperature, low-battery zařízení. "
                        "One-shot view PŘED rozhodnutím (jdi spát? krize?)."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "ha_get_device_state",
        "description": ("Stav konkrétního HA zařízení podle entity_id "
                        "(např. 'light.kuchyne', 'binary_sensor.dvere_vchod', "
                        "'climate.loznice')."),
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string", "description": "domain.name format"}},
            "required": ["entity_id"]
        }
    },
    {
        "name": "ha_get_devices_by_room",
        "description": ("Všechna HA zařízení po místnostech (obyvak, kuchyne, "
                        "loznice, ...). Užitečné pro 'zhasni v obyváku'."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "ha_execute_action",
        "description": ("Vykonej HA akci. SAFE: light_on/off/brightness, "
                        "switch_on/off, cover_open/close, climate_set/off, "
                        "media_pause, get_temperature/humidity/status. "
                        "CRISIS-only (vyžaduje crisis_override=true + reason): "
                        "unlock, alarm_disarm. FORBIDDEN: lock, alarm_arm."),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "entity_id": {"type": "string"},
                "params": {"type": "object",
                           "description": "např. {brightness: 80, temperature: 22}"},
                "crisis_override": {"type": "boolean", "default": False},
                "reason": {"type": "string", "description": "Vyžadováno pro crisis akce"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "ha_circadian_triggers",
        "description": ("Pre-built proaktivní scénáře z HA + cirkadiánního profilu: "
                        "noční pohyb, vynechané vstávání, otevřené dveře v "
                        "neobvyklou dobu, studený pokoj. Vrátí list s navrženou "
                        "zprávou + tts_mode + severity. Claude může použít jako "
                        "template nebo ignorovat."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "ha_behavioral_changes",
        "description": ("Významné změny chování seniora vs. baseline: "
                        "shift času vstávání (>1h), pokles aktivity (>30%), "
                        "disrupce rutiny. Vrátí changes + stability."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    # ── WAKE WORD + USER COMMUNICATION ──────────────────────────
    {
        "name": "get_voice_session_state",
        "description": ("Co dělá senior PRÁVĚ TEĎ ve voice runtime? "
                        "Stavy: IDLE (tichý, lze promluvit) / LISTENING / "
                        "THINKING / SPEAKING / WAKE_DETECTED. Vrátí "
                        "safe_to_speak=True/False. Použij PŘED proaktivní "
                        "komunikací — neruš aktivní konverzaci."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_voice_conversation_history",
        "description": ("Posledních N turn-by-turn voice exchanges. Liší se od "
                        "get_recent_chat — to je textový chat. Tady hlasový."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "speak_to_senior",
        "description": ("Proaktivně promluv k seniorovi přes voice runtime — "
                        "integrovaný TTS pipeline (frontend SpeechOrchestrator "
                        "to zachytí + zahraje). VŽDY napřed get_voice_session_state. "
                        "force_interrupt=True POUZE v CRISIS (přerušíš aktivní "
                        "konverzaci). Pro běžný chat (text) použij send_chat_message."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "message": {"type": "string", "maxLength": 500},
                "mode": {"type": "string",
                         "enum": ["HARMONY", "ALERT", "CRISIS", "POETRY", "NARRATION"]},
                "force_interrupt": {"type": "boolean", "default": False}
            },
            "required": ["senior_id", "message"]
        }
    },
    {
        "name": "get_active_voice_seniors",
        "description": ("Seznam VŠECH seniorů, kteří jsou právě v aktivní voice "
                        "konverzaci (state != IDLE). Globální 'kdo teď mluví'. "
                        "Jen z cache, takže jen aktivní sessions."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    # ── SELF-DIAGNOSTIC TOOLS ───────────────────────────────────
    {
        "name": "detect_app_errors",
        "description": ("Sken posledních N hodin observation logu + claude_agent_telemetry "
                        "pro error vzorce napříč celou aplikací. Vrátí strukturované "
                        "kategorie chyb. Použij na začátku self-diagnostic cyklu."),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 168}
            },
            "required": []
        }
    },
    {
        "name": "analyze_self_health",
        "description": ("Self-introspection: jak zdravé jsou MOJE poslední běhy? "
                        "Failure rate, avg cost, avg duration, tool call efficiency. "
                        "Vrátí health_score (0-100) + warnings."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "read_source_file",
        "description": ("Přečti zdrojový soubor aplikace pro self-diagnosis. "
                        "BEZPEČNOST: jen relativní cesty v app rootu, blokuje "
                        "secrets/env/credentials. Max 500KB. Použij pro "
                        "analýzu reportované chyby."),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relativní cesta od /app, např. 'voice_filter.py'"},
                "start_line": {"type": "integer", "default": 1},
                "num_lines": {"type": "integer", "default": 80, "maximum": 300}
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "run_diagnostic_test",
        "description": ("Spusť whitelisted diagnostický test a zachyť výsledek. "
                        "Tests: tools/tts/brain_memory/agents_beat/komunikace/ha/"
                        "voice_runtime. Read-only ověření, žádné mutace."),
        "input_schema": {
            "type": "object",
            "properties": {
                "test_name": {"type": "string",
                              "enum": ["tools", "tts", "brain_memory", "agents_beat",
                                       "komunikace", "ha", "voice_runtime"]}
            },
            "required": ["test_name"]
        }
    },
    {
        "name": "report_bug",
        "description": ("Vytvoř strukturovaný bug report. Uloží se jako "
                        "observation_type='bug_report' + bus message. "
                        "Devs ho uvidí v admin-claude dashboard. "
                        "DŮLEŽITÉ: Toto NEAPLIKUJE FIX — jen reportuje. "
                        "Patche aplikuje supervised dev workflow (Claude Code "
                        "lokálně nebo CI/CD)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string",
                             "enum": ["crash","logic","performance","security","ux","config","flaky"]},
                "severity": {"type": "string",
                             "enum": ["INFO","WARNING","ALERT","CRISIS"]},
                "file": {"type": "string", "description": "Soubor/modul kde je bug"},
                "description": {"type": "string", "maxLength": 1000},
                "suggested_fix": {"type": "string", "maxLength": 1000,
                                  "description": "Volitelně: navrhovaná oprava"},
                "reproducer": {"type": "string", "maxLength": 500,
                               "description": "Volitelně: jak chybu zopakovat"}
            },
            "required": ["category", "severity", "file", "description"]
        }
    },
    # ── STT TOOLS ───────────────────────────────────────────────
    {
        "name": "stt_status",
        "description": ("Je STT subsystem dostupný? Azure key + speech_understanding."),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "stt_normalize_text",
        "description": ("Normalizace pro fuzzy matching: lowercase + bez háčků/čárek + "
                        "bez interpunkce. 'Příliš Žluťoučký Kůň!' → "
                        "'prilis zlutoucky kun'. Užitečné pro porovnání s known "
                        "phrases."),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 500}},
            "required": ["text"]
        }
    },
    {
        "name": "stt_detect_safety",
        "description": ("Fuzzy match pro slova nebezpečí: 'pomoc', 'spadla jsem', "
                        "'nemůžu vstát', 'bolí'. Levenshtein-tolerant — funguje i "
                        "se sníženou dikcí (po cévní příhodě, parkinson, alzheimer)."),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 500}},
            "required": ["text"]
        }
    },
    {
        "name": "stt_classify_priority",
        "description": ("Klasifikuje urgenci řeči: CRITICAL (pomoc, pád) / HIGH "
                        "(bolest, dušnost) / MEDIUM (znepokojení) / NORMAL. "
                        "Použij pro fast-path do CRISIS bez plného brain cyklu."),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 500},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1.0}
            },
            "required": ["text"]
        }
    },
    {
        "name": "stt_correct_text",
        "description": ("Oprav typické chyby Twilio cs-CZ STT (50+ patternů: "
                        "léky, místa, jména). Použij PŘED dalším zpracováním "
                        "transkribované řeči."),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 1000},
                "senior_id": {"type": "string"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "stt_should_retry",
        "description": ("Mám se znovu zeptat seniora kvůli nízké STT confidence? "
                        "Vrátí retry: True/False + reason. Pro Twilio Gather "
                        "retry logic ('Promiňte, slyšel jsem to špatně...')."),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            "required": ["text", "confidence"]
        }
    },
    {
        "name": "stt_gather_params",
        "description": ("Adaptivní Twilio Gather (STT) parametry podle communication "
                        "profile seniora. Pomalá řeč (alzheimer/parkinson/dysarthria) "
                        "→ delší timeout, lenientnější threshold. Hearing-impaired "
                        "→ phrase hints. Vrátí timeout/speechTimeout/speechModel/hints."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "stt_build_hints",
        "description": ("Postaví Azure STT phrase hints podle profilu + chat history "
                        "seniora. Hints pomáhají STT správně přepisovat jména dětí, "
                        "léky, koníčky, místa. Snižuje chyby v personal vocabulary."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    # ── CALENDAR TOOLS ──────────────────────────────────────────
    {
        "name": "get_upcoming_events",
        "description": ("Nadcházející události seniora v dalších N hodinách "
                        "(doktor, léky, návštěva, narozeniny). Použij pro "
                        "proaktivní 'nezapomeňte na...' zprávy."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 168}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "find_free_slots",
        "description": ("Najdi 3 volné časové sloty v dalších N dnech. "
                        "Preferuje pracovní dny + dopolední/odpolední časy. "
                        "Použij pro plánování (např. 'kdy může mít rodina hovor?')."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 30}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "add_calendar_reminder",
        "description": ("Zapni 24h + 1h push reminder pro existující "
                        "calendar event. (calendar_reminder_cron je pošle automaticky.)"),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "event_id": {"type": "integer"}
            },
            "required": ["senior_id", "event_id"]
        }
    },
    {
        "name": "parse_event_text",
        "description": ("Parsuj český text na strukturovanou událost: "
                        "'Zítra v 14 doktor' → {title, date, time, type}. "
                        "Nezapisuje do DB — Claude může review před založením."),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 500}},
            "required": ["text"]
        }
    },
    # ── EMAIL TOOLS ─────────────────────────────────────────────
    {
        "name": "get_unread_emails",
        "description": ("Nepřečtené e-maily seniora (live IMAP). Vrátí UID + odesílatele "
                        "+ subject. Read-only. Pro daily briefing nebo když senior "
                        "říká 'kdo mi psal?'"),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "scan_email_risk",
        "description": ("Skóruj phishing/scam riziko e-mailu. score 0-100, "
                        "≥70 = risky. use_ai=True invokuje Gemini second opinion."),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "maxLength": 500},
                "body": {"type": "string", "maxLength": 5000},
                "from_email": {"type": "string"},
                "from_name": {"type": "string"},
                "use_ai": {"type": "boolean", "default": False}
            },
            "required": ["subject", "body", "from_email"]
        }
    },
    {
        "name": "flag_email_to_family",
        "description": ("Označ podezřelý e-mail pro rodinu. Uloží do email_family_flags "
                        "+ pushne rodině notifikaci. Použij když scan_email_risk vrátí "
                        "risky=True + score≥70."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "subject": {"type": "string", "maxLength": 500},
                "body_snippet": {"type": "string", "maxLength": 1000},
                "from_email": {"type": "string"},
                "from_name": {"type": "string"},
                "reasons": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["senior_id", "subject", "body_snippet", "from_email"]
        }
    },
    {
        "name": "send_email_to_family",
        "description": ("Pošli e-mail rodině (substantive update). "
                        "Pro urgentní zprávy použij notify_family (SMS) — to je rychlejší. "
                        "urgency: low/normal/high (ovlivňuje subject prefix)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "subject": {"type": "string", "maxLength": 200},
                "body": {"type": "string", "maxLength": 5000},
                "urgency": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}
            },
            "required": ["senior_id", "subject", "body"]
        }
    },
    # ── CAREGIVER TOOLS ─────────────────────────────────────────
    {
        "name": "get_senior_caregivers",
        "description": ("Seznam všech pečovatelů + rodiny linkovaných na seniora "
                        "(jeden model: senior_family_links). Vrátí role, relation, "
                        "notify settings, sos_priority. Použij PŘED notify_family "
                        "abys věděl, kdo dostane zprávu."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_care_plan",
        "description": ("Plný care plan seniora: cíle, léky, denní rutina, "
                        "monitorované metriky, rizika, odpovědnosti, kontrolní "
                        "vyšetření. summary=True vrátí jen counts (cheap)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "summary": {"type": "boolean", "default": False}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_medication_schedule",
        "description": ("Seznam léků s dosage + frequency + doctor. Použij PŘED "
                        "připomenutím léků — víš kdy a kolik."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "add_care_plan_goal",
        "description": ("Přidej nový cíl do care plánu. priority: high/medium/low. "
                        "Použij když z konverzace vyplývá nový lékařský cíl."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 500},
                "priority": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "add_care_plan_risk",
        "description": ("Přidej riziko + mitigaci do care plánu. severity: high/medium/low. "
                        "Použij když detekuješ vzorec (opakované pády, non-adherence)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 500},
                "severity": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
                "mitigation": {"type": "string", "maxLength": 500}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "send_caregiver_notification",
        "description": ("Pošli notifikaci VŠEM pečovatelům/rodině seniora. "
                        "Routes přes caregiver_notifications table → caregiver "
                        "inbox + push (pokud notify_on_X=True). Liší se od "
                        "notify_family (SMS): tohle je in-app caregiver dashboard."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "title": {"type": "string", "maxLength": 200},
                "body": {"type": "string", "maxLength": 1000},
                "severity": {"type": "string", "enum": ["info","warning","alert","crisis"], "default": "info"},
                "ntype": {"type": "string", "default": "claude_observation"}
            },
            "required": ["senior_id", "title", "body"]
        }
    },
    {
        "name": "get_relationship",
        "description": ("Konfuciánský relationship state seniora: type, trust (0-1), "
                        "vulnerability, familiarity, permission_level (SUGGEST/ASSIST/"
                        "EXECUTE), virtue scores (ren/yi/li/zhi/xin). Říká co můžeš dělat: "
                        "SUGGEST = jen navrhuj, EXECUTE = můžeš jednat sám."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "caregiver_whisper",
        "description": ("Zašeptej kontext Radimovi do paměti — bude to mentioning "
                        "v dalším chatu. 'Připomeň jí, že vnučka má dnes narozeniny.' "
                        "Uloží do memory_learning.caregiver_whispers."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 500},
                "priority": {"type": "string", "enum": ["low","normal","high"], "default": "normal"}
            },
            "required": ["senior_id", "text"]
        }
    },
    # ── EDUCATION TOOLS ─────────────────────────────────────────
    {
        "name": "get_education_courses",
        "description": ("Katalog vzdělávacích kurzů (dysphasia/komunikace/... )s "
                        "moduly a lekcemi. filter_type filtruje (např. 'dysphasia')."),
        "input_schema": {
            "type": "object",
            "properties": {"filter_type": {"type": "string"}},
            "required": []
        }
    },
    {
        "name": "get_lesson_progress",
        "description": ("Progress seniora ve vzdělávání: level, badges, completion %, "
                        "průměrné quiz skóre, recommended_courses. Pro pochopení, jak "
                        "se senior učí."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_recommended_lessons",
        "description": ("Personalizované doporučení lekcí podle adaptivního profilu + "
                        "communication_needs. Vrátí list of {course_id, module_id, "
                        "title, reason}. Reason ukazuje proč."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_lesson_content",
        "description": ("Plný obsah lekce (HTML article + key_points + quiz info + "
                        "scenario flag). Použij pro doručení lekce seniorovi nebo "
                        "vložení do chatu."),
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string"},
                "module_id": {"type": "string"}
            },
            "required": ["course_id", "module_id"]
        }
    },
    {
        "name": "mark_lesson_complete",
        "description": ("Označ lekci jako dokončenou (volitelně se score). Score "
                        "triggernuje adaptive evaluation (level/badges update)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "course_id": {"type": "string"},
                "module_id": {"type": "string"},
                "score": {"type": "number", "minimum": 0, "maximum": 100}
            },
            "required": ["senior_id", "course_id", "module_id"]
        }
    },
    {
        "name": "get_assignments",
        "description": ("Active education task assignments od učitelů. status: "
                        "active / completed / overdue / all. Použij pro připomenutí "
                        "blížících se deadlinů."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "status": {"type": "string", "enum": ["active","completed","overdue","all"], "default": "active"}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "recommend_scenario",
        "description": ("Doporuč komunikační scénář podle klíčových slov situace. "
                        "Klíčová slova: 'alzheimer agitace', 'samota deprese', "
                        "'odmítá léky'. Vrátí top scenario s options."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "situation_keywords": {"type": "string", "maxLength": 200}
            },
            "required": ["senior_id", "situation_keywords"]
        }
    },
    # ── TV + MUSIC TOOLS ────────────────────────────────────────
    {
        "name": "get_music_stations",
        "description": ("Katalog českých rádií + ambient/relax streamů. "
                        "group: czech (8 stanic) / thematic (6 ambient) / "
                        "relax (4 nature) / None=všechno."),
        "input_schema": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "enum": ["czech", "thematic", "relax"]}
            },
            "required": []
        }
    },
    {
        "name": "recommend_music",
        "description": ("Doporuč rádio podle aktuálního Ψ(t) stavu seniora "
                        "+ hodiny + voice memory. CRISIS→meditative, ALERT→calm, "
                        "HARMONY+ráno→informative, HARMONY+odpoledne→cheerful, "
                        "HARMONY+večer→calm. mood_override přepíše logiku."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "mood_override": {"type": "string",
                    "enum": ["calm", "cheerful", "meditative", "informative", "upbeat", "nostalgic"]},
                "time_aware": {"type": "boolean", "default": True}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "play_music_for_senior",
        "description": ("Spusť rádio přes agent_messages bus → frontend "
                        "MusicModule. Respektuje voice session — neruší "
                        "aktivní konverzaci. station_id z get_music_stations()."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "station_id": {"type": "string"}
            },
            "required": ["senior_id", "station_id"]
        }
    },
    {
        "name": "pause_music_for_senior",
        "description": ("Zastav přehrávání hudby seniorovi (bus event)."),
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "youtube_search",
        "description": ("Vyhledej YouTube videa (přes scraper, no API key). "
                        "Pro koncerty, pohádky, zprávy, sport. Vrátí list "
                        "{id, title, thumbnail, duration}."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 200},
                "limit": {"type": "integer", "default": 6, "minimum": 1, "maximum": 20}
            },
            "required": ["query"]
        }
    },
    {
        "name": "recommend_tv_content",
        "description": ("Doporuč TV/video obsah podle hodiny + Ψ(t). Ráno = "
                        "zprávy/rádio. Odpoledne = dokumenty/písničky. Večer "
                        "= klasika/pohádky. CRISIS = jen tichá ambient hudba."),
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "time_aware": {"type": "boolean", "default": True}
            },
            "required": ["senior_id"]
        }
    },
    # ── PHILOSOPHY TOOL ─────────────────────────────────────────
    {
        "name": "get_radim_philosophy",
        "description": ("Vrátí Radimovu duši: 12 hodnot (empatie, trpělivost, úcta, "
                        "laskavost, ...), reflexi pro aktuální denní dobu, a klíčové "
                        "matematické konstanty (PHI, T1, T2). Volej když rozhoduješ "
                        "o tónu zprávy nebo když potřebuješ filozofický kontext."),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string",
                          "enum": ["empathy", "patience", "respect", "kindness",
                                   "clarity", "reliability", "positivity", "curiosity",
                                   "humility", "creativity", "humor", "wisdom"],
                          "description": "Optional: zaměř se na konkrétní hodnotu"}
            },
            "required": []
        }
    },
]


# ═══════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════

def _tool_list_seniors():
    """Active seniors with last activity."""
    if not _DB:
        return {"error": "DB not available"}
    try:
        from memory_helpers import db_load_profile
        seniors = []
        with db_context() as db:
            rows = db.execute("""
                SELECT id, email, COALESCE(name, '') AS name,
                       role, last_active, created_at
                FROM auth_users
                WHERE role IN ('senior', 'user', 'subscriber')
                ORDER BY COALESCE(last_active, created_at) DESC
                LIMIT 20
            """).fetchall()
            for r in rows:
                uid = str(r[0])
                name = r[2] or r[1] or f'user-{uid}'
                last_active = str(r[4]) if r[4] else (str(r[5]) if r[5] else None)
                # Pull age/preferred name from memory_profiles JSON
                try:
                    profile = db_load_profile(uid) or {}
                    full_name = profile.get('full_name') or profile.get('name') or name
                    age = profile.get('age')
                except Exception:
                    full_name, age = name, None
                seniors.append({
                    'id': uid,
                    'name': full_name,
                    'age': age,
                    'last_active': last_active,
                    'role': r[3],
                })
        return seniors
    except Exception as e:
        return {"error": str(e)[:200]}


def _row_to_list(row):
    """Convert a DB row (tuple OR RealDictRow) to a positional list.
    PG with RealDictCursor returns dict-like rows where iter() yields keys —
    we need values. Tuples work as-is.
    """
    if hasattr(row, 'values') and callable(row.values):
        return list(row.values())
    return list(row)


def _tool_get_brain_state(senior_id):
    """Read latest Ψ(t) state. PostgreSQL folds unquoted identifiers to
    lowercase, so the actual column names are c/e/r/s, not C/E/R/S.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            row = db.execute("""
                SELECT c, e, r, s, alpha, mode, coherence, source, created_at
                FROM brain_states WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (str(senior_id),)).fetchone()
            if not row:
                return {"info": "No brain state recorded yet"}
            vals = _row_to_list(row)
            keys = ['C', 'E', 'R', 'S', 'alpha', 'mode', 'coherence', 'source', 'created_at']
            result = {k: (str(v) if isinstance(v, datetime) else v) for k, v in zip(keys, vals)}
            # Add interpretation hint based on T1=12 / T2=27 thresholds
            c_val = result.get('C')
            if isinstance(c_val, (int, float)):
                if c_val < 12: result['_hint'] = 'HARMONY (C<12)'
                elif c_val < 27: result['_hint'] = 'ALERT (12≤C<27)'
                else: result['_hint'] = 'CRISIS (C≥27)'
            return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_vitals(senior_id):
    """Vitals via iot_devices.user_id → iot_sensor_data.device_id join."""
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = "NOW() - INTERVAL '24 hours'" if is_postgres() else "datetime('now', '-1 day')"
            rows = db.execute(f"""
                SELECT s.sensor_type, s.value, s.unit, s.recorded_at, d.name
                FROM iot_sensor_data s
                JOIN iot_devices d ON d.device_id = s.device_id
                WHERE d.user_id = ? AND s.recorded_at > {interval}
                  AND s.sensor_type IN ('heart_rate', 'temperature', 'spo2', 'blood_pressure', 'weight')
                ORDER BY s.recorded_at DESC LIMIT 30
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": "No vitals in last 24h"}
            return [{'type': r[0], 'value': r[1], 'unit': r[2],
                     'at': str(r[3]) if r[3] else None, 'device': r[4]} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_iot_status(senior_id):
    """IoT events (door/motion/gas/etc) via iot_devices join."""
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = "NOW() - INTERVAL '24 hours'" if is_postgres() else "datetime('now', '-1 day')"
            rows = db.execute(f"""
                SELECT s.sensor_type, s.value, s.recorded_at, d.name, d.room_id
                FROM iot_sensor_data s
                JOIN iot_devices d ON d.device_id = s.device_id
                WHERE d.user_id = ? AND s.recorded_at > {interval}
                  AND s.sensor_type IN ('door', 'motion', 'gas', 'smoke', 'water_leak', 'occupancy')
                ORDER BY s.recorded_at DESC LIMIT 50
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": "No IoT events in last 24h"}
            return [{'type': r[0], 'value': r[1],
                     'at': str(r[2]) if r[2] else None,
                     'device': r[3], 'room': r[4]} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_recent_chat(senior_id, n=10):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            rows = db.execute("""
                SELECT role, content, created_at
                FROM memory_history WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (str(senior_id), int(n))).fetchall()
            if not rows:
                return {"info": "No chat history"}
            return list(reversed([
                {'role': r[0], 'content': (r[1] or '')[:300],
                 'at': str(r[2]) if r[2] else None} for r in rows
            ]))
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_observations(senior_id, days=7):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = f"NOW() - INTERVAL '{int(days)} days'" if is_postgres() else f"datetime('now', '-{int(days)} day')"
            rows = db.execute(f"""
                SELECT severity, message, created_at, observation_type
                FROM agent_observations
                WHERE user_id = ? AND created_at > {interval}
                ORDER BY created_at DESC LIMIT 30
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": f"No observations in last {days} days"}
            return [{'severity': r[0], 'message': r[1],
                     'at': str(r[2]) if r[2] else None, 'type': r[3]} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_action_cooldown(senior_id, action_type='any'):
    """Returns True if action allowed (no recent action on this senior)."""
    if not _DB:
        return True
    try:
        with db_context() as db:
            interval = f"NOW() - INTERVAL '{SENIOR_ACTION_COOLDOWN_MIN} minutes'" if is_postgres() \
                       else f"datetime('now', '-{SENIOR_ACTION_COOLDOWN_MIN} minute')"
            row = db.execute(f"""
                SELECT COUNT(*) FROM agent_observations
                WHERE user_id = ? AND observation_type = 'claude_agent'
                  AND severity IN ('ALERT', 'CRISIS')
                  AND created_at > {interval}
            """, (str(senior_id),)).fetchone()
            return (row[0] if row else 0) == 0
    except Exception:
        return True  # fail open


def _tool_send_chat_message(senior_id, text):
    if not _check_action_cooldown(senior_id):
        return {"skipped": "cooldown active for senior"}
    try:
        # Save as a Radim → senior message in memory_history
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'memory_history',
                      ['user_id', 'role', 'content'],
                      [str(senior_id), 'assistant', text[:500]])
        return {"sent": True, "senior_id": senior_id, "preview": text[:80]}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_push(senior_id, title, body):
    try:
        from app import send_push_notification
        result = send_push_notification(str(senior_id), title[:50], body[:200])
        return {"sent": bool(result), "title": title}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_notify_family(senior_id, text, urgency):
    try:
        from memory_helpers import db_load_profile
        # Try senior's emergency_contacts in their profile (most reliable source)
        profile = db_load_profile(str(senior_id)) or {}
        contacts = profile.get('emergency_contacts', []) or []

        # Fallback: senior_family_links → family user's profile phone
        if not contacts:
            try:
                with db_context() as db:
                    rows = db.execute("""
                        SELECT family_user_id FROM senior_family_links
                        WHERE senior_id = ? LIMIT 5
                    """, (str(senior_id),)).fetchall()
                for r in rows:
                    fp = db_load_profile(str(r[0])) or {}
                    if fp.get('phone'):
                        contacts.append({'phone': fp['phone'], 'name': fp.get('name', 'Family')})
            except Exception:
                pass

        if not contacts:
            return {"info": "No family contacts on file"}

        sent = 0
        from twilio_voice_helpers import send_sms
        prefix = {"low": "ℹ️", "medium": "⚠️", "high": "🚨"}.get(urgency, "ℹ️")
        for c in contacts[:5]:
            phone = c.get('phone') if isinstance(c, dict) else None
            if not phone:
                continue
            try:
                send_sms(phone, f"{prefix} Radim: {text[:280]}")
                sent += 1
            except Exception as e:
                logger.warning(f"notify_family sms to {phone[:6]}***: {e}")

        return {"family_sms_sent": sent, "urgency": urgency, "contacts_found": len(contacts)}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_initiate_call(senior_id, reason):
    try:
        from twilio_voice_helpers import get_senior_phone, initiate_proactive_call
        phone = get_senior_phone(str(senior_id))
        if not phone:
            return {"error": "No phone on file in memory_profiles"}

        greeting = f"Dobrý den, tady Radim. Chtěl jsem se ujistit, že jste v pořádku. {reason[:100]}"
        result = initiate_proactive_call(phone, greeting,
                                         user_id=str(senior_id),
                                         reason='claude_agent_crisis',
                                         voice_mode='CRISIS')
        return {"call_initiated": bool(result), "phone": phone[:6] + '***'}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_create_observation(senior_id, severity, message):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'agent_observations',
                      ['user_id', 'observation_type', 'severity', 'message'],
                      [str(senior_id), 'claude_agent', severity, message[:1000]])
        return {"recorded": True, "severity": severity}
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# MATH TOOLS — Anticipation engine + Circadian + φ math
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_anticipation_forecast(senior_id):
    """Predict where this senior's consciousness is heading.

    Returns Ĉ_{t+1}, breakpoints (B12/B27), and risk_direction:
    stable / rising / approaching_alert / approaching_crisis.
    """
    if not _MATH_ANTICIPATION:
        return {"error": "anticipation engine not available"}
    try:
        result = _anticipate(str(senior_id))
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_circadian_profile(senior_id):
    """Senior's daily rhythm: wake/sleep hours, active hours, restlessness, routine stability."""
    if not _MATH_CIRCADIAN:
        return {"error": "circadian engine not available"}
    try:
        result = _circadian_profile(str(senior_id), days=14)
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_circadian_triggers(senior_id):
    """Detect circadian deviations: night restlessness, missed wakeup, abnormal patterns."""
    if not _MATH_CIRCADIAN:
        return {"error": "circadian engine not available"}
    try:
        triggers = _circadian_triggers(str(senior_id))
        return {"triggers": triggers, "count": len(triggers) if triggers else 0}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_behavioral_profile(senior_id):
    """Personal routine patterns from sensor data (bathroom/bed/kitchen hours)."""
    if not _MATH_ANTICIPATION:
        return {"error": "behavioral engine not available"}
    try:
        result = _behavioral_profile(str(senior_id), days=14)
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# PHILOSOPHY TOOLS — Radim's identity, values, reflections
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_radim_philosophy(focus=None):
    """Radim's 12 core values + time-of-day reflection.

    focus: optional value name to deep-dive on (empathy/patience/respect/...)
    """
    if not _PHILOSOPHY:
        return {"error": "soul_data not available"}
    try:
        from datetime import datetime as dt
        hour = dt.now().hour
        period = _get_period(hour)
        reflection, _ = _get_reflection(hour)

        result = {
            'time_period': period,
            'current_hour': hour,
            'reflection': reflection,
            'values_summary': [
                {'key': k, 'czech': v.get('czech'), 'description': v.get('description'),
                 'weight': v.get('weight')}
                for k, v in _RADIM_VALUES.items()
            ],
            'math_constants': {
                'PHI': round(_PHI, 6), 'PSI': round(_PSI, 6),
                'DELTA': round(_DELTA, 6), 'RHO': round(_RHO, 6),
                'T1': _T1, 'T2': _T2, 'C_MAX': _C_MAX,
                '_meaning': 'PHI=harmony attractor, DELTA=crisis attractor, T1/T2=mode thresholds'
            },
        }
        if focus and focus in _RADIM_VALUES:
            result['focused_value'] = _RADIM_VALUES[focus]
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# BRAIN TOOLS — Ψ(t) computation, empathy, speech adaptation
# ═══════════════════════════════════════════════════════════════════════

def _tool_compute_brain_state(senior_id, C, alpha, voice_tone=0.5, hrv=0.5, speech_tempo=0.5):
    """Run brain math to compute full Ψ(t) on hypothetical or sensor inputs.

    Useful for "what would Eva's state look like if C rose to 20?"
    Returns full vector (C, E, R, S) + mode + speech adaptation + coherence.
    Ephemeral — does NOT save to DB.
    """
    if not _BRAIN_CORE:
        return {"error": "brain_core not available"}
    try:
        result = _compute_psi(
            float(C), float(alpha),
            voice_tone=float(voice_tone), hrv=float(hrv),
            speech_tempo=float(speech_tempo),
            user_id=None,  # ephemeral
        )
        psi = result.get('psi', {}) or {}
        return {
            'C': psi.get('C'),
            'E': psi.get('E'),
            'R': psi.get('R'),
            'S': psi.get('S'),
            'alpha': result.get('alpha'),
            'mode': result.get('mode'),
            'coherence': result.get('coherence'),
            'phi_index': result.get('phi_index'),
            'rho_stability': result.get('rho_stability'),
            'thresholds': result.get('thresholds'),
            'speech': result.get('speech'),
            'response_style': result.get('response_style'),
            'rhythm_return': result.get('rhythm_return'),
            '_for_senior': str(senior_id),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_compute_empathy(voice_tone=0.5, hrv=0.5, speech_tempo=0.5):
    """Compute empathy E from voice/HRV/tempo signals.
    Useful when Claude wants to know what empathy weight to use.
    """
    if not _BRAIN_CORE:
        return {"error": "brain_math not available"}
    try:
        result = _compute_empathy(float(voice_tone), float(hrv), float(speech_tempo))
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_speech_adaptation(senior_id):
    """What voice config (rate, pitch, pause) should Radim use NOW for this senior?
    Pulls latest brain state and returns the speech adaptation params.
    """
    if not _BRAIN_CORE or not _DB:
        return {"error": "brain_core or DB not available"}
    try:
        with db_context() as db:
            row = db.execute("""
                SELECT c, alpha, mode FROM brain_states
                WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
            """, (str(senior_id),)).fetchone()
        if not row:
            return {"info": "No brain state — using HARMONY defaults",
                    "speech": _compute_speech(5.0, 0.5, "HARMONY")}
        vals = _row_to_list(row)
        c, alpha, mode = vals[0], vals[1], vals[2]
        speech = _compute_speech(float(c), float(alpha), str(mode), user_id=str(senior_id))
        return {'senior_id': senior_id, 'mode': mode, 'C': c, 'alpha': alpha, 'speech': speech}
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# MEMORY TOOLS — profile + long-term learning
# ═══════════════════════════════════════════════════════════════════════

# Whitelist of profile keys Claude is allowed to update.
# Critical fields like phone, email, password are excluded — these need human
# verification, not autonomous AI changes.
_PROFILE_WRITABLE_KEYS = {
    'preferences', 'notes', 'mood_log', 'last_topic', 'favorite_topics',
    'communication_style', 'preferred_length', 'comfort_words',
    'reminders_consent', 'hobbies', 'family_summary', 'health_notes_brief',
    'communication_needs', 'preferred_channel',  # Komunikace tunables
}


def _tool_get_full_profile(senior_id):
    """Full memory_profiles JSON: name, age, family, preferences, hobbies,
    emergency_contacts, medical notes, life story — everything Radim knows."""
    if not _MEMORY_HELPERS:
        return {"error": "memory_helpers not available"}
    try:
        profile = _load_profile(str(senior_id)) or {}
        # Truncate large fields to keep token count sane
        if isinstance(profile.get('chat_history_full'), list):
            profile['chat_history_full'] = f'[{len(profile["chat_history_full"])} messages omitted]'
        # Mask phone for privacy unless needed
        if profile.get('phone'):
            profile['phone'] = profile['phone'][:6] + '***'
        return profile if profile else {"info": "No profile yet"}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_learning_state(senior_id):
    """Long-term learning: topics, mood, interaction_count, C_history (math
    engine input), successful_interactions, crisis_count.
    This is the data anticipation_engine uses internally — Claude can read it
    to understand patterns over weeks/months."""
    if not _MEMORY_HELPERS:
        return {"error": "memory_helpers not available"}
    try:
        learning = _load_learning(str(senior_id))
        # Truncate C_history to last 30 entries to save tokens
        c_hist = learning.get('C_history', [])
        if len(c_hist) > 30:
            learning['C_history'] = ['...']*1 + c_hist[-30:]
            learning['_C_history_truncated'] = f'showing last 30 of {len(c_hist)}'
        return learning
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_update_learning(senior_id, key, value):
    """Write a learning insight back to long-term memory.

    Examples:
    - update_learning('282', 'last_mood', 'lonely')
    - update_learning('282', 'topics', {...})  # full dict
    - update_learning('282', 'crisis_count', 3)

    Cannot overwrite C_history or alpha_history (those come from brain engine).
    """
    if not _MEMORY_HELPERS:
        return {"error": "memory_helpers not available"}
    PROTECTED = {'C_history', 'alpha_history', 'trend_C', 'trend_alpha',
                 'circadian_profile', 'behavioral_profile'}
    if key in PROTECTED:
        return {"error": f"key '{key}' is managed by brain/anticipation engine — read-only"}
    try:
        learning = _load_learning(str(senior_id)) or _default_learning()
        learning[key] = value
        _save_learning(str(senior_id), learning)
        return {"updated": True, "key": key, "value_preview": str(value)[:100]}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_update_profile(senior_id, key, value):
    """Update a single field in senior's profile JSON.

    Only whitelisted fields (preferences, notes, hobbies, ...) can be modified.
    Critical fields (phone, email, emergency_contacts) require human action.
    """
    if not _MEMORY_HELPERS:
        return {"error": "memory_helpers not available"}
    if key not in _PROFILE_WRITABLE_KEYS:
        return {"error": f"key '{key}' is read-only — only {sorted(_PROFILE_WRITABLE_KEYS)} are writable"}
    try:
        profile = _load_profile(str(senior_id)) or {}
        profile[key] = value
        _save_profile(str(senior_id), profile)
        return {"updated": True, "key": key, "value_preview": str(value)[:100]}
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# TTS TOOLS — voice synthesis + voice memory + learning loop
# ═══════════════════════════════════════════════════════════════════════

# Cap on Azure TTS audio generation per run — prevents runaway cost.
# Azure TTS Neural ≈ $16 per 1M characters → ~250 chars × 5 calls/run = ~$0.02/run.
MAX_TTS_GENERATIONS_PER_RUN = 5
_tts_generation_counter = {'count': 0}  # reset per run via run_claude_agent


def _tool_get_voice_modes_catalog():
    """Show all available voice modes (HARMONY/ALERT/CRISIS/POETRY/NARRATION/...)
    with their SSML parameters. Use this when picking a mode for a message."""
    if not _TTS_SSML:
        return {"error": "voice_filter not available"}
    catalog = {}
    for mode, profile in _VOICE_PROFILES.items():
        catalog[mode] = {
            'style': profile.get('style'),
            'styledegree': profile.get('styledegree'),
            'rate': profile.get('rate'),
            'pitch': profile.get('pitch'),
            'volume': profile.get('volume'),
            'pause_ms': profile.get('pause_ms'),
            'emphasis': profile.get('emphasis'),
        }
    return {
        'modes': catalog,
        'voice': 'cs-CZ-AntoninNeural',
        '_hint': ('HARMONY=běžná konverzace; ALERT=zvýšená empatie '
                  '(klesající rate, delší pauzy); CRISIS=maximální klid '
                  '(rate-20%, 1200ms pauzy); POETRY=recitace; '
                  'NARRATION=vyprávění příběhů.'),
    }


def _tool_get_voice_memory(senior_id):
    """Read everything Radim knows about THIS senior's voice preferences.

    Returns:
    - Current voice_prefs (rate, energy, pause learned over time)
    - Interaction stats (positive/negative feedback, barge-ins, no_responses)
    - Profile-level voice_pref (override voice/quiet_hours)
    - Learning maturity (more interactions = more reliable prefs)
    """
    if not _TTS_LEARNING:
        return {"error": "voice_learning not available"}
    try:
        prefs = _get_voice_prefs(str(senior_id))
        # Pull profile-level voice_pref too (different concept — explicit user pick)
        profile_voice = {}
        if _MEMORY_HELPERS:
            try:
                p = _load_profile(str(senior_id)) or {}
                profile_voice = {
                    'voice_pref': p.get('voice_pref'),  # e.g. {voice: 'AntoninNeural', volume: 'loud'}
                    'quiet_hours': p.get('quiet_hours'),
                    'radim_mode': p.get('radim_mode'),  # POETRY / CONVERSATIONAL / etc.
                }
            except Exception:
                pass

        # Maturity = how reliable the learned prefs are
        n = prefs.get('interactions', 0)
        if n < 3: maturity = 'cold-start'
        elif n < 10: maturity = 'learning'
        elif n < 30: maturity = 'reliable'
        else: maturity = 'mature'

        return {
            'learned_prefs': {
                'preferred_rate_pct': prefs.get('preferred_rate'),
                'preferred_energy': prefs.get('preferred_energy'),
                'preferred_pause_ms': prefs.get('preferred_pause'),
                'response_to_melody': prefs.get('response_to_melody'),
                'response_to_singing': prefs.get('response_to_singing'),
            },
            'interaction_stats': {
                'total': n,
                'positive_feedback': prefs.get('positive_feedback', 0),
                'negative_feedback': prefs.get('negative_feedback', 0),
                'barge_ins': prefs.get('barge_ins', 0),  # příliš pomalé
                'no_responses': prefs.get('no_responses', 0),  # neslyšel/nerozuměl
                'last_updated': prefs.get('last_updated'),
            },
            'profile_voice': profile_voice,
            'maturity': maturity,
            '_hint': ({
                'cold-start': 'Málo dat — drž se HARMONY default.',
                'learning': 'Pomalu adaptuj. Sleduj reakce.',
                'reliable': 'Použij learned_prefs s důvěrou.',
                'mature': 'Senior má jasný styl. Drž se ho.'
            })[maturity],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_compose_ssml(senior_id, text, mode=None):
    """Compose SSML for given text WITHOUT calling Azure (no $ cost).

    Use this when you want to:
    - See how the voice will sound BEFORE generating audio
    - Validate mode selection
    - Debug voice config

    If mode=None, auto-pick from current Ψ(t):
    - HARMONY (C<12), ALERT (12≤C<27), CRISIS (C≥27)

    Returns SSML XML + breakdown of voice params (rate, pitch, pause, style).
    """
    if not _TTS_SSML:
        return {"error": "voice_filter not available"}
    if not text or len(text.strip()) == 0:
        return {"error": "empty text"}
    try:
        # Auto-pick mode from latest brain state if not specified
        if mode is None and _DB:
            try:
                with db_context() as db:
                    row = db.execute("""
                        SELECT mode FROM brain_states WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT 1
                    """, (str(senior_id),)).fetchone()
                if row:
                    vals = _row_to_list(row)
                    mode = vals[0] or 'HARMONY'
                else:
                    mode = 'HARMONY'
            except Exception:
                mode = 'HARMONY'
        mode = mode or 'HARMONY'

        ssml = _build_ssml(text[:500], mode=mode,
                           voice='cs-CZ-AntoninNeural',
                           user_id=str(senior_id))
        profile = _VOICE_PROFILES.get(mode, _VOICE_PROFILES.get('HARMONY', {}))
        return {
            'ssml_preview': ssml[:1000] + ('…[truncated]' if len(ssml) > 1000 else ''),
            'ssml_length': len(ssml),
            'mode': mode,
            'voice': 'cs-CZ-AntoninNeural',
            'voice_params': {
                'style': profile.get('style'),
                'rate': profile.get('rate'),
                'pitch': profile.get('pitch'),
                'volume': profile.get('volume'),
                'pause_ms': profile.get('pause_ms'),
            },
            'estimated_chars': len(text),
            '_no_audio_generated': True,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_generate_voice_audio(senior_id, text, mode=None):
    """Generate ACTUAL Azure TTS audio (incurs $$ — ~$16/1M chars).

    Returns base64-encoded MP3 + metadata. Use sparingly:
    - For CRISIS welfare-check call greetings
    - When senior has indicated voice-only preference
    - When chat text alone won't be heard (vision impaired)

    Capped at 5 generations per agent run. Beyond that, returns error.
    """
    if not _TTS_AZURE:
        return {"error": "Azure TTS not available"}
    if not _azure_available():
        return {"error": "AZURE_SPEECH_KEY not set"}
    if _tts_generation_counter['count'] >= MAX_TTS_GENERATIONS_PER_RUN:
        return {"error": f"TTS generation cap reached ({MAX_TTS_GENERATIONS_PER_RUN}/run)"}
    if not text or len(text.strip()) == 0:
        return {"error": "empty text"}
    if len(text) > 800:
        return {"error": f"text too long ({len(text)} chars > 800 max)"}

    try:
        if mode is None and _DB:
            try:
                with db_context() as db:
                    row = db.execute("""
                        SELECT mode FROM brain_states WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT 1
                    """, (str(senior_id),)).fetchone()
                if row:
                    vals = _row_to_list(row)
                    mode = vals[0] or 'HARMONY'
            except Exception:
                pass
        mode = mode or 'HARMONY'

        audio_bytes = _gen_azure_tts(text, mode=mode, user_id=str(senior_id))
        _tts_generation_counter['count'] += 1

        if not audio_bytes:
            return {"error": "Azure TTS returned empty audio"}

        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode('ascii')
        # Estimate cost: $16 per 1M chars
        chars = len(text)
        cost_usd = chars * 16.0 / 1_000_000

        return {
            'audio_base64_preview': audio_b64[:200] + '…[truncated]',
            'audio_bytes': len(audio_bytes),
            'audio_kb': round(len(audio_bytes) / 1024, 1),
            'mode': mode,
            'voice': 'cs-CZ-AntoninNeural',
            'chars_used': chars,
            'cost_usd_estimate': round(cost_usd, 6),
            'generations_remaining': MAX_TTS_GENERATIONS_PER_RUN - _tts_generation_counter['count'],
            '_audio_truncated_for_response': True,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_record_voice_feedback(senior_id, event_type, voice_mode=None):
    """Record voice feedback into voice_learning system (φ-blended adaptation).

    event_type:
    - response_fast — senior odpověděl <5s (hlas srozumitelný)
    - response_slow — senior odpověděl >10s (možná neslyšel)
    - no_response — neodpověděl (15s+)
    - barge_in — přerušil TTS (pomalý)
    - positive — řekl 'děkuju/krásné/super'
    - negative — řekl 'co/nerozumím/pomaleji'
    - melody_positive / melody_negative
    - singing_positive / singing_negative

    Adapts preferred_rate/energy/pause via φ-blend (61.8% old + 38.2% new).
    """
    if not _TTS_LEARNING:
        return {"error": "voice_learning not available"}
    valid_events = {'response_fast', 'response_slow', 'no_response', 'barge_in',
                    'positive', 'negative', 'melody_positive', 'melody_negative',
                    'singing_positive', 'singing_negative'}
    if event_type not in valid_events:
        return {"error": f"invalid event_type — must be one of {sorted(valid_events)}"}
    try:
        prefs = _record_voice_feedback(str(senior_id), event_type, voice_mode=voice_mode)
        return {
            'recorded': True,
            'event': event_type,
            'updated_prefs': {
                'preferred_rate_pct': prefs.get('preferred_rate'),
                'preferred_pause_ms': prefs.get('preferred_pause'),
                'preferred_energy': prefs.get('preferred_energy'),
            },
            'total_interactions': prefs.get('interactions', 0),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# AGENT BUS TOOLS — shared intelligence with other app agents
# ═══════════════════════════════════════════════════════════════════════

# Catalog of registered agents in the application (for Claude awareness)
_APP_AGENTS = {
    'agent_loop': {
        'role': 'rule-based proactive monitor (every 5 min)',
        'detects': 'C trend, activity drop, vital anomaly, interaction silence',
        'severities': ['INFO', 'WARNING', 'ALERT', 'CRISIS'],
    },
    'predictive_agent': {
        'role': 'risk forecasting on 7-day window',
        'detects': 'C trend, activity drop, sleep quality, med compliance, isolation, survey risk',
        'severities': ['warning', 'alert'],
    },
    'sleep_agent': {
        'role': 'sleep quality analysis',
        'detects': 'dropped hours, poor quality, timing shifts',
        'severities': ['alert'],
    },
    'social_isolation_agent': {
        'role': 'isolation detection',
        'detects': 'call frequency, visitor patterns, engagement drops',
        'severities': ['warning'],
    },
    'weather_agent': {
        'role': 'environmental impact',
        'detects': 'cold/heat/weather affecting mood',
        'severities': ['info'],
    },
    'medication_tracker': {
        'role': 'compliance monitoring',
        'detects': 'missed doses, timing deviations',
        'severities': ['alert'],
    },
    'emergency_protocol': {
        'role': 'crisis escalation',
        'detects': 'fall, unresponsiveness, vitals OOB',
        'severities': ['crisis'],
    },
    'safety_agent': {
        'role': 'chat-time safety check',
        'detects': 'concerning content in user messages',
        'severities': ['warning', 'alert'],
    },
    'claude_agent': {
        'role': 'Claude Sonnet 4.5 autonomous agent (THIS — you)',
        'detects': 'holistic patterns across brain/memory/math/philosophy',
        'severities': ['INFO', 'WARNING', 'ALERT', 'CRISIS'],
    },
}


def _tool_get_agent_inventory():
    """Catalog of all agents running in the system + their roles.
    Use this to understand what other agents are watching, so you don't
    duplicate their work."""
    return {
        'total': len(_APP_AGENTS),
        'agents': _APP_AGENTS,
        'message_bus': {
            'available': _AGENT_BUS,
            'description': 'Shared message bus (agent_messages table) — all agents read/write here',
            'kinds': ['user_input', 'context', 'observation', 'intent', 'decision', 'ack'],
            'severities': ['info', 'warning', 'alert', 'crisis'],
        },
    }


def _tool_get_agent_messages(senior_id, hours=24, severity_min='info', kinds=None):
    """Read what OTHER agents have observed for this senior recently.

    This is shared intelligence — predictive_agent might have seen sleep
    issues, sleep_agent might have seen restlessness, social_isolation
    might have seen no calls. Claude reads them all and synthesizes.

    severity_min: info / warning / alert / crisis (filter)
    kinds: optional list to filter ['observation', 'context', 'decision', ...]
    """
    if not _AGENT_BUS:
        return {"error": "agent_bus not available"}
    try:
        # Convert hours → minutes for bus.recent()
        minutes_back = int(hours) * 60
        msgs = _bus_recent(
            str(senior_id),
            since=minutes_back,
            kinds=kinds,
            severity_min=severity_min,
            limit=30,
        )
        return {
            'count': len(msgs),
            'window_hours': hours,
            'messages': [{
                'id': m.get('id'),
                'sender': m.get('sender'),
                'kind': m.get('kind'),
                'severity': m.get('severity'),
                'topic': m.get('topic'),
                'message': (m.get('payload', {}) or {}).get('message', '')[:300],
                'created_at': m.get('created_at'),
            } for m in msgs],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_check_agent_dedup(senior_id, topic, within_minutes=15, severity_min='warning'):
    """Before raising an alert, check if ANOTHER agent already raised same
    topic recently. Prevents duplicate alarms cascading.

    Returns: {duplicate: True/False, recent_emitter: 'sleep_agent', ...}
    """
    if not _AGENT_BUS:
        return {"error": "agent_bus not available"}
    try:
        is_dup = _bus_dedupe(
            str(senior_id),
            topic=topic,
            within_minutes=int(within_minutes),
            any_sender=True,  # check across all agents
            severity_min=severity_min,
        )
        result = {'duplicate': bool(is_dup), 'topic': topic, 'window_min': within_minutes}
        if is_dup:
            # Show who already raised it
            recent = _bus_recent(str(senior_id), since=int(within_minutes),
                                 topics=[topic], severity_min=severity_min, limit=3)
            result['recent_emitters'] = [
                {'sender': m.get('sender'), 'severity': m.get('severity'),
                 'created_at': m.get('created_at')}
                for m in recent
            ]
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_emit_agent_message(senior_id, kind, severity, topic, message,
                             correlates_with=None):
    """Publish a message to the shared agent bus — visible to all other
    agents (chat coordinator, anticipation, sleep_agent, ...).

    Use when:
    - You want chat brain to see your observation in next conversation
    - You're adding context other agents should know
    - You're correlating with another agent's earlier message (correlates_with=msg_id)

    kind: user_input / context / observation / intent / decision / ack
    severity: info / warning / alert / crisis
    """
    if not _AGENT_BUS:
        return {"error": "agent_bus not available"}
    valid_kinds = {'user_input', 'context', 'observation', 'intent', 'decision', 'ack'}
    if kind not in valid_kinds:
        return {"error": f"invalid kind — must be {sorted(valid_kinds)}"}
    valid_severities = {'info', 'warning', 'alert', 'crisis'}
    if severity not in valid_severities:
        return {"error": f"invalid severity — must be {sorted(valid_severities)}"}
    try:
        msg_id = _bus_emit(
            user_id=str(senior_id),
            sender='claude_agent',
            kind=kind,
            severity=severity,
            topic=topic[:120],
            payload={'message': message[:1000]},
            correlates_with=correlates_with,
        )
        return {'emitted': True, 'msg_id': msg_id, 'kind': kind, 'severity': severity}
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# RTCF BEAT TOOLS — Radim's heartbeat / autonomic state
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_beat_state(senior_id):
    """Compute current RTCF Beat State (BPM, HRV, autonomic mode) from
    senior's latest Ψ(t) state via the brain → beat mapping.

    Returns:
    - bpm (50-110): synthetic heart rate of system
    - hrv (0-1): heart rate variability (1=calm, 0=stressed)
    - autonomic_mode: parasympathetic / balanced / sympathetic
    - arousal, stability, warmth, presence (0-1 each)

    Use this for TIMING decisions — sympathetic = senior is hot, slow down.
    """
    if not _RTCF_BEAT or not _BRAIN_CORE:
        return {"error": "RTCF beat engine not available"}
    try:
        # Pull latest brain state
        if not _DB:
            return {"error": "DB not available"}
        with db_context() as db:
            row = db.execute("""
                SELECT c, alpha, mode FROM brain_states
                WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
            """, (str(senior_id),)).fetchone()
        if not row:
            # No brain state — compute neutral beat
            beat = _compute_beat()
            return {**beat, '_source': 'default_neutral', 'senior_id': senior_id}

        vals = _row_to_list(row)
        c, alpha, mode = float(vals[0] or 0), float(vals[1] or 0.5), str(vals[2] or 'HARMONY')

        # Map brain state → beat inputs (heuristic mapping consistent with rtcf_bridge)
        risk = min(1.0, c / 30.0)         # C drives risk
        load = min(1.0, c / 25.0)
        recovery = max(0.0, 1.0 - c / 30.0)
        threat = 1.0 if mode == 'CRISIS' else (0.5 if mode == 'ALERT' else 0.0)
        trust = 0.7  # baseline trust assumption
        safety = 1.0 - threat
        intuition = abs(alpha - 0.5)
        pain = 0.0  # not measured directly

        beat = _compute_beat(
            risk=risk, pain=pain, intuition=intuition, load=load,
            recovery=recovery, threat=threat, trust=trust, safety=safety,
        )
        return {
            **beat,
            '_inputs': {
                'C': c, 'alpha': alpha, 'mode': mode,
                'derived_risk': round(risk, 3),
                'derived_load': round(load, 3),
                'derived_threat': round(threat, 3),
            },
            'senior_id': senior_id,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_compute_custom_beat(risk=0.0, pain=0.0, intuition=0.0, load=0.0,
                              recovery=0.0, threat=0.0, trust=0.7, safety=1.0):
    """Compute beat state from explicit inputs — for hypothetical scenarios.

    All inputs are normalized [0, 1]. Use this to simulate:
    - 'What would beat look like if threat=0.9?' (panic state)
    - 'What if trust drops to 0.2 after no_response?' (low engagement)
    """
    if not _RTCF_BEAT:
        return {"error": "RTCF beat not available"}
    try:
        beat = _compute_beat(
            risk=float(risk), pain=float(pain), intuition=float(intuition),
            load=float(load), recovery=float(recovery), threat=float(threat),
            trust=float(trust), safety=float(safety),
        )
        return beat
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# KOMUNIKACE TOOLS — communication needs + channels (WhatsApp/SMS)
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_communication_needs_catalog():
    """List all 32 communication strategies the system supports.

    Strategies are grouped by category: dementia (alzheimer_*, lewy_body,
    vascular_dementia), aphasia, dysarthria, parkinsons, autism, anxiety,
    depression, hearing_loss, vision_loss, ...

    Returns: list of {key, summary} for each strategy.
    """
    if not _COMMUNICATION:
        return {"error": "communication_needs not available"}
    catalog = []
    for key, instructions in _COMM_NEEDS.items():
        # Extract first line as summary
        summary = (instructions or '').strip().split('\n')[0]
        # Strip "KOMUNIKACNI POTREBA:" prefix if present
        summary = summary.replace('KOMUNIKACNI POTREBA:', '').strip()
        catalog.append({
            'key': key,
            'summary': summary[:120],
        })
    return {
        'total': len(catalog),
        'strategies': catalog,
        '_hint': ('Read full instructions with get_communication_strategy(key). '
                  'Strategies layer — multiple keys can be combined with comma '
                  '("alzheimer_middle,hearing_loss").'),
    }


def _tool_get_communication_strategy(needs_key):
    """Get full Czech instructions for a specific communication need.

    needs_key: single key (e.g. 'alzheimer_middle') or comma-separated list
    ('alzheimer_middle,hearing_loss').

    Returns: the actual strategy text Claude can use to adapt its messages.
    """
    if not _COMMUNICATION:
        return {"error": "communication_needs not available"}
    try:
        instructions = _get_comm_instructions(needs_key)
        if not instructions:
            return {"error": f"unknown needs_key: {needs_key}",
                    "_hint": "use get_communication_needs_catalog() to see available keys"}
        return {
            'needs_key': needs_key,
            'instructions': instructions,
            'length': len(instructions),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_detect_topic_mood(text):
    """Lightweight Czech NLP — detect topic + mood from text.

    Topics: health, weather, news, family, memory, exercise, food,
            entertainment, technology, emotions, general.
    Moods: happy, sad, anxious, neutral.

    Use this on incoming senior message to route response strategy.
    """
    if not _COMMUNICATION:
        return {"error": "communication_needs not available"}
    if not text or not text.strip():
        return {"error": "empty text"}
    try:
        topic = _detect_topic(text)
        mood = _detect_mood(text)
        return {
            'topic': topic,
            'mood': mood,
            'text_preview': text[:100],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_senior_communication_profile(senior_id):
    """Get senior's communication profile — what needs they have.

    Pulls 'communication_needs' field from memory_profiles + their
    learning state's 'communication_style' + voice_pref.
    Combines into a single decision-ready view.
    """
    if not _MEMORY_HELPERS:
        return {"error": "memory_helpers not available"}
    try:
        profile = _load_profile(str(senior_id)) or {}
        learning = _load_learning(str(senior_id)) or {}

        result = {
            'communication_needs': profile.get('communication_needs', []),
            'preferred_channel': profile.get('preferred_channel'),  # chat/voice/whatsapp/none
            'language': profile.get('language', 'cs-CZ'),
            'communication_style': learning.get('communication_style', 'warm'),
            'preferred_length': learning.get('preferred_length', 'medium'),
            'voice_pref': profile.get('voice_pref'),
            'quiet_hours': profile.get('quiet_hours'),
            'has_phone': bool(profile.get('phone')),
            'has_emergency_contacts': len(profile.get('emergency_contacts', []) or []) > 0,
        }

        # If communication_needs is a string, parse comma-separated
        if isinstance(result['communication_needs'], str):
            result['communication_needs'] = [
                s.strip() for s in result['communication_needs'].split(',') if s.strip()
            ]

        # Auto-merge full instructions if needs are set
        if result['communication_needs'] and _COMMUNICATION:
            try:
                key_str = ','.join(result['communication_needs'])
                result['active_strategy_text'] = _get_comm_instructions(key_str)[:1500]
            except Exception:
                pass

        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_whatsapp(senior_id, text):
    """Send WhatsApp message to senior. Requires phone in profile.

    Use when:
    - Senior prefers WhatsApp (preferred_channel)
    - Voice/SMS already failed
    - Family member wants WhatsApp digest
    """
    if not _WHATSAPP_AVAILABLE:
        return {"error": "WhatsApp not configured (TWILIO_WHATSAPP_NUMBER missing?)"}
    if not _check_action_cooldown(senior_id):
        return {"skipped": "cooldown active for senior"}
    try:
        from twilio_voice_helpers import get_senior_phone
        phone = get_senior_phone(str(senior_id))
        if not phone:
            return {"error": "No phone on file"}
        ok = _send_whatsapp_helper(phone, text[:1000], user_id=str(senior_id))
        return {"sent": bool(ok), "channel": "whatsapp",
                "phone": phone[:6] + '***', "preview": text[:80]}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_sms_to_senior(senior_id, text):
    """Send SMS directly to senior (NOT family). Use when senior has phone but
    no smart device. Goes to senior's profile phone, NOT emergency contacts.

    For family alerts use notify_family() instead.
    """
    if not _SMS_AVAILABLE:
        return {"error": "SMS not configured"}
    if not _check_action_cooldown(senior_id):
        return {"skipped": "cooldown active for senior"}
    try:
        from twilio_voice_helpers import get_senior_phone
        phone = get_senior_phone(str(senior_id))
        if not phone:
            return {"error": "No phone on file"}
        ok = _send_sms_helper(phone, text[:300], user_id=str(senior_id))
        return {"sent": bool(ok), "channel": "sms_senior",
                "phone": phone[:6] + '***', "preview": text[:80]}
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# HOME ASSISTANT TOOLS — smart home (lights, doors, sensors, scenes)
# ═══════════════════════════════════════════════════════════════════════

# Whitelist of HA actions Claude can execute. Action names map to
# home_assistant.execute_agent_action() dispatcher. Anything not on
# the list is rejected.
_HA_SAFE_ACTIONS = {
    'light_on', 'light_off', 'light_brightness',
    'switch_on', 'switch_off',
    'cover_open', 'cover_close',
    'climate_set', 'climate_off',
    'media_pause',  # safe to interrupt audio
    'get_temperature', 'get_humidity', 'get_status',
}

# DANGEROUS actions Claude can ONLY call in CRISIS context, with explicit reason:
_HA_CRISIS_ACTIONS = {
    'unlock',     # senior locked out, EMS access in CRISIS
    'alarm_disarm',  # let family/EMS in
}

# NEVER allowed for autonomous agent:
_HA_FORBIDDEN_ACTIONS = {
    'lock',         # don't lock senior in
    'alarm_arm',    # don't trigger alarm autonomously
}


def _tool_ha_status():
    """Check if Home Assistant is connected + reachable.
    Always start here — if not connected, no point calling other HA tools.
    """
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant module not available"}
    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"connected": False,
                    "_hint": "HA client exists but not connected — check HA_URL + HA_TOKEN env vars"}
        return {
            "connected": True,
            "url_configured": bool(getattr(client, 'url', None)),
            "client_type": type(client).__name__,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_get_sensors():
    """Read all HA sensor states grouped by category.

    Returns:
    - temperature: list of {name, value, unit, entity_id}
    - humidity, motion, door, light_level, air_quality, battery
    - low_battery: list of devices needing battery replacement

    Use this for SITUATIONAL AWARENESS — do you see motion at 3am?
    Door open while senior should be sleeping? Cold room?
    """
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant not available"}
    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"error": "HA not connected"}
        summary = client.get_sensors_summary()
        # Limit list sizes to keep token cost down
        for key in list(summary.keys()):
            if isinstance(summary[key], list) and len(summary[key]) > 15:
                summary[key] = summary[key][:15] + [{'_truncated': len(summary[key]) - 15}]
        return summary
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_home_status():
    """Aggregate home status: lights on/off counts, doors open, locks,
    indoor temperature, low-battery devices. One-shot situational view.

    Use this BEFORE deciding to send a senior to bed (lights still on?)
    or before crisis (doors locked? alarm armed?).
    """
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant not available"}
    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"error": "HA not connected"}
        result = client.execute_agent_action('get_status')
        return result.get('data', result) if isinstance(result, dict) else result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_get_device_state(entity_id):
    """State of a specific HA device by entity_id (e.g. 'light.kitchen',
    'binary_sensor.front_door', 'climate.bedroom')."""
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant not available"}
    if not entity_id or '.' not in entity_id:
        return {"error": "invalid entity_id (must be like 'domain.name')"}
    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"error": "HA not connected"}
        state = client.get_state(entity_id)
        if not state:
            return {"error": f"entity {entity_id} not found"}
        return state
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_get_devices_by_room():
    """All HA devices grouped by room. Useful for 'turn off all lights
    in living room' type decisions."""
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant not available"}
    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"error": "HA not connected"}
        result = client.get_devices_by_room()
        # Trim per-room device lists
        for room, info in result.items():
            if isinstance(info, dict) and isinstance(info.get('devices'), list):
                if len(info['devices']) > 10:
                    info['devices'] = info['devices'][:10]
                    info['_truncated'] = True
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_execute_action(action, entity_id=None, params=None,
                            crisis_override=False, reason=None):
    """Execute a Home Assistant action.

    SAFE actions (always allowed): light_on/off/brightness, switch_on/off,
    cover_open/close, climate_set/off, media_pause, get_temperature/humidity/status.

    CRISIS actions (require crisis_override=True + reason): unlock, alarm_disarm.

    FORBIDDEN (never allowed): lock, alarm_arm.

    params: dict like {brightness: 80, color_temp: 3000, temperature: 22}
    """
    if not _HA_AVAILABLE:
        return {"error": "Home Assistant not available"}
    if not action:
        return {"error": "action required"}

    if action in _HA_FORBIDDEN_ACTIONS:
        return {"error": f"action '{action}' is forbidden for autonomous agent",
                "_hint": "lock/alarm_arm need human action to avoid lock-out"}

    if action in _HA_CRISIS_ACTIONS:
        if not crisis_override or not reason:
            return {"error": f"action '{action}' requires crisis_override=true AND reason",
                    "_hint": "set crisis_override=true and explain why (e.g. 'EMS access for fall')"}

    if action not in _HA_SAFE_ACTIONS and action not in _HA_CRISIS_ACTIONS:
        return {"error": f"unknown action '{action}'",
                "_hint": f"valid actions: {sorted(_HA_SAFE_ACTIONS | _HA_CRISIS_ACTIONS)}"}

    try:
        client = _get_ha_client()
        if not getattr(client, 'connected', False):
            return {"error": "HA not connected"}
        full_params = dict(params or {})
        if entity_id:
            full_params['entity_id'] = entity_id
        result = client.execute_agent_action(action, full_params)
        # Audit log on dangerous actions
        if action in _HA_CRISIS_ACTIONS:
            logger.warning(
                f"[claude_agent] HA CRISIS action: {action} on {entity_id} — reason={reason}"
            )
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_circadian_triggers(senior_id):
    """Check HA + circadian profile for proactive scenarios:
    - Night motion (23:00-05:00) → restlessness check
    - Oversleep (no morning motion) → wellness check
    - Door open at unusual time
    - Cold room at night

    Returns list of triggers with suggested message + tts_mode + severity.
    These are pre-built; Claude can use them as templates or ignore.
    """
    if not _HA_TRIGGERS:
        return {"error": "circadian_engine not available"}
    try:
        triggers = _ha_proactive_triggers(str(senior_id))
        return {
            'count': len(triggers) if triggers else 0,
            'triggers': triggers or [],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_ha_behavioral_changes(senior_id):
    """Detect significant behavioral changes vs. baseline:
    - Wake time shift (>1h different from usual)
    - Activity decline (>30% drop in motion events)
    - Routine disruption

    Returns: {changes: [...], stability: 'stable|disrupted', change_count: N}
    """
    if not _HA_TRIGGERS:
        return {"error": "circadian_engine not available"}
    try:
        result = _ha_behavioral_changes(str(senior_id))
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# WAKE WORD + USER COMMUNICATION TOOLS
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_voice_session_state(senior_id):
    """Co dělá senior PRÁVĚ TEĎ ve voice runtime?

    Stavy:
    - IDLE — senior je tichý, lze proaktivně promluvit
    - LISTENING — wake word právě zazněl, senior mluví → NERUŠ
    - THINKING — Radim přemýšlí o odpovědi → NERUŠ
    - SPEAKING — Radim právě mluví → NERUŠ
    - WAKE_DETECTED — wake word zachycen, čeká se na řeč → NERUŠ

    Použij PŘED proaktivní komunikací — pokud je senior v aktivní konverzaci,
    nepřerušuj.
    """
    if not _VOICE_RUNTIME:
        return {"error": "voice_runtime_engine not available"}
    try:
        # Use senior_id as session_id for proactive checks
        session = _get_voice_session(str(senior_id))
        state = session.get('state', 'idle')
        is_active = state != _VOICE_STATES['IDLE']
        return {
            'session_id': senior_id,
            'state': state,
            'is_active': is_active,
            'safe_to_speak': not is_active,
            'C': session.get('C'),
            'alpha': session.get('alpha'),
            'kappa': session.get('kappa'),
            'wake_count': session.get('wake_count', 0),
            'last_tts_text_preview': (session.get('last_tts_text') or '')[:100],
            'conversation_length': len(session.get('conversation', [])),
            '_hint': ('safe_to_speak=True → můžeš proaktivně promluvit. '
                      'False → respektuj probíhající konverzaci, počkej.'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_voice_conversation_history(senior_id, limit=10):
    """Posledních N řádků voice konverzace (turn-by-turn).
    Liší se od get_recent_chat — to je textový chat. Tady je hlas.
    """
    if not _VOICE_RUNTIME:
        return {"error": "voice_runtime_engine not available"}
    try:
        session = _get_voice_session(str(senior_id))
        conv = session.get('conversation', []) or []
        # Most recent N
        recent = conv[-int(limit):] if conv else []
        return {
            'session_id': senior_id,
            'total_turns': len(conv),
            'recent': [
                {'role': t.get('role') if isinstance(t, dict) else 'unknown',
                 'content': (t.get('content') if isinstance(t, dict) else str(t))[:300],
                 'timestamp': t.get('timestamp') if isinstance(t, dict) else None}
                for t in recent
            ],
            'last_radim_said': session.get('last_tts_text', '')[:300],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_speak_to_senior(senior_id, message, mode=None, force_interrupt=False):
    """Proaktivně promluv k seniorovi přes voice runtime.

    Co se stane:
    1. Zkontroluje voice session state (pokud aktivní + force_interrupt=False → skip)
    2. Spočítá Ψ(t)-aware speech params (mode, rate, pause)
    3. Přidá zprávu do conversation history seniora
    4. Vygeneruje SSML + uloží jako last_tts_text
    5. Senior to uslyší při dalším voice frame (frontend SpeechOrchestrator)

    Pro INSTANT delivery použij send_chat_message + frontend ji TTSne.
    Tato cesta je pro INTEGROVANÝ proaktivní hlas (jako radim_chat_internal).
    """
    if not _VOICE_RUNTIME:
        return {"error": "voice_runtime_engine not available"}
    if not message or not message.strip():
        return {"error": "empty message"}
    if not _check_action_cooldown(senior_id):
        return {"skipped": "cooldown active for senior"}

    try:
        session = _get_voice_session(str(senior_id))
        state = session.get('state', 'idle')
        is_active = state != _VOICE_STATES['IDLE']

        if is_active and not force_interrupt:
            return {
                "skipped": f"senior is in active session (state={state})",
                "_hint": "set force_interrupt=true ONLY in CRISIS — use send_chat_message instead for non-crisis",
            }

        # Auto-pick mode from latest brain state if not given
        if mode is None and _DB:
            try:
                with db_context() as db:
                    row = db.execute(
                        "SELECT mode FROM brain_states WHERE user_id = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (str(senior_id),)
                    ).fetchone()
                if row:
                    vals = _row_to_list(row)
                    mode = vals[0] or 'HARMONY'
            except Exception:
                pass
        mode = mode or 'HARMONY'

        # Compose SSML preview (no audio, the voice runtime + frontend orchestrator does that)
        ssml_preview = None
        if _TTS_SSML:
            try:
                ssml_preview = _build_ssml(message[:500], mode=mode,
                                           voice='cs-CZ-AntoninNeural',
                                           user_id=str(senior_id))
            except Exception:
                pass

        # Append to conversation as Radim's proactive turn
        from datetime import datetime as _dt
        turn = {
            'role': 'assistant',
            'content': message[:500],
            'timestamp': _dt.utcnow().isoformat(),
            'source': 'claude_agent_proactive',
            'mode': mode,
        }
        session.setdefault('conversation', []).append(turn)
        # Trim conversation to last 50 turns
        if len(session['conversation']) > 50:
            session['conversation'] = session['conversation'][-50:]
        session['last_tts_text'] = message[:500]

        # Persist
        try:
            _save_voice_session(str(senior_id))
        except Exception as e:
            logger.warning(f"voice session save failed: {e}")

        # ALSO mirror into memory_history so chat module shows it (cross-channel)
        try:
            with db_context(commit=True) as db:
                from database import db_insert
                db_insert(db, 'memory_history',
                          ['user_id', 'role', 'content'],
                          [str(senior_id), 'assistant', message[:500]])
        except Exception:
            pass

        return {
            "spoken": True,
            "channel": "voice_runtime",
            "mode": mode,
            "preview": message[:80],
            "interrupted_active_session": (is_active and force_interrupt),
            "ssml_built": bool(ssml_preview),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_active_voice_seniors():
    """Seznam seniorů, kteří JSOU PRÁVĚ v aktivní voice konverzaci
    (state != IDLE). Užitečné pro globální view 'kdo právě mluví'.

    Vrací jen z in-memory cache (nedotahuje DB) — to je OK, protože
    aktivní sessions jsou vždy v cache.
    """
    if not _VOICE_RUNTIME:
        return {"error": "voice_runtime_engine not available"}
    try:
        active = []
        for sid, sess in _voice_sessions_cache.items():
            state = sess.get('state', 'idle')
            if state != _VOICE_STATES['IDLE']:
                active.append({
                    'session_id': sid,
                    'state': state,
                    'wake_count': sess.get('wake_count', 0),
                    'C': sess.get('C'),
                })
        return {
            'count': len(active),
            'active_sessions': active,
            'total_in_cache': len(_voice_sessions_cache),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# SELF-DIAGNOSTIC TOOLS — bug detection + structured reporting
# ═══════════════════════════════════════════════════════════════════════
#
# DESIGN PHILOSOPHY: Production Claude agent OBSERVES, DIAGNOSES, REPORTS.
# It does NOT modify production code at runtime — that's reserved for a
# supervised dev workflow (Claude Code locally, or CI/CD with human review).
# This separation prevents AI hallucination from breaking the live app
# with seniors using it.
#
# Bug reports are stored as agent_observations with observation_type='bug_report'
# so they're visible in the dashboard and reviewable before action.

def _tool_detect_app_errors(hours=24):
    """Scan recent agent observations + claude_agent_telemetry for error
    patterns across the application.

    Returns: structured list of error categories with frequencies.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        errors = {}
        with db_context() as db:
            interval = (f"NOW() - INTERVAL '{int(hours)} hours'" if is_postgres()
                        else f"datetime('now', '-{int(hours)} hour')")

            # 1. Errors logged via claude_agent_telemetry
            rows = db.execute(f"""
                SELECT error, COUNT(*) as cnt FROM claude_agent_telemetry
                WHERE error IS NOT NULL AND error != ''
                  AND run_at > {interval}
                GROUP BY error ORDER BY cnt DESC LIMIT 10
            """).fetchall()
            errors['claude_agent_failures'] = [
                {'error': (_row_to_list(r)[0] or '')[:200], 'count': _row_to_list(r)[1]}
                for r in rows
            ]

            # 2. CRISIS observations (by any source)
            rows = db.execute(f"""
                SELECT observation_type, COUNT(*) as cnt FROM agent_observations
                WHERE severity = 'CRISIS' AND created_at > {interval}
                GROUP BY observation_type ORDER BY cnt DESC LIMIT 10
            """).fetchall()
            errors['crisis_events'] = [
                {'type': _row_to_list(r)[0], 'count': _row_to_list(r)[1]}
                for r in rows
            ]

            # 3. Tool errors from recent runs (parsed from summaries)
            rows = db.execute(f"""
                SELECT COUNT(*) FROM claude_agent_telemetry
                WHERE actions_taken = 0 AND tool_calls > 5
                  AND run_at > {interval}
            """).fetchone()
            zero_action_runs = _row_to_list(rows)[0] if rows else 0
            errors['runs_no_actions'] = zero_action_runs

        return {
            'window_hours': hours,
            'errors': errors,
            'has_issues': bool(errors['claude_agent_failures'] or errors['crisis_events']),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_analyze_self_health():
    """Self-introspection: are MY recent runs healthy?

    Looks at claude_agent_telemetry for: failure rate, avg cost, avg
    duration, tool call efficiency. Detects degradation.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            # Last 20 runs
            rows = db.execute("""
                SELECT cost_usd, duration_seconds, tool_calls,
                       seniors_evaluated, actions_taken, error
                FROM claude_agent_telemetry
                ORDER BY run_at DESC LIMIT 20
            """).fetchall()
            if not rows:
                return {"info": "No telemetry data"}
            total = len(rows)
            failures = sum(1 for r in rows if _row_to_list(r)[5])
            costs = [float(_row_to_list(r)[0] or 0) for r in rows]
            durations = [float(_row_to_list(r)[1] or 0) for r in rows]
            tool_calls = [_row_to_list(r)[2] or 0 for r in rows]
            actions = [_row_to_list(r)[4] or 0 for r in rows]

            avg_cost = sum(costs) / total
            avg_duration = sum(durations) / total
            avg_tool_calls = sum(tool_calls) / total
            zero_action_pct = sum(1 for a in actions if a == 0) / total * 100

            health_score = 100
            warnings = []
            if failures / total > 0.1:
                health_score -= 30
                warnings.append(f"{failures}/{total} runs failed ({failures/total*100:.0f}%)")
            if avg_cost > 0.40:
                health_score -= 15
                warnings.append(f"Avg cost ${avg_cost:.3f} above $0.40 threshold")
            if avg_duration > 120:
                health_score -= 10
                warnings.append(f"Avg duration {avg_duration:.0f}s above 120s threshold")
            if zero_action_pct > 80:
                health_score -= 5
                warnings.append(f"{zero_action_pct:.0f}% of runs took zero actions")

            return {
                'health_score': max(0, health_score),
                'health_label': ('healthy' if health_score >= 80 else
                                 'degraded' if health_score >= 50 else 'unhealthy'),
                'last_20_runs': {
                    'failures': failures,
                    'avg_cost_usd': round(avg_cost, 4),
                    'avg_duration_s': round(avg_duration, 1),
                    'avg_tool_calls': round(avg_tool_calls, 1),
                    'zero_action_pct': round(zero_action_pct, 1),
                },
                'warnings': warnings,
            }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_read_source_file(file_path, start_line=1, num_lines=80):
    """Read a Python source file from the deployed application — for
    self-diagnosis when investigating a bug.

    SAFETY: Only reads files within the app directory. Refuses absolute
    paths going outside. Refuses .env, secrets, credentials.
    """
    import os
    BLOCKED_PATTERNS = {'.env', 'secret', 'credentials', 'token', 'key.pem',
                        'password', '.git/'}
    BLOCKED_PATHS = {'/etc/', '/root/', '/home/', '/.ssh/', '/proc/'}

    # Normalize and validate
    if not file_path or not isinstance(file_path, str):
        return {"error": "file_path required"}
    norm = os.path.normpath(file_path)
    if norm.startswith('/') or norm.startswith('..'):
        return {"error": "absolute paths and parent traversal forbidden"}
    if any(p in norm.lower() for p in BLOCKED_PATTERNS):
        return {"error": f"path matches blocked pattern (secrets/env files)"}
    if any(p in norm for p in BLOCKED_PATHS):
        return {"error": f"path in blocked directory"}
    if not norm.endswith(('.py', '.md', '.txt', '.json', '.html', '.js', '.css')):
        return {"error": "only .py/.md/.txt/.json/.html/.js/.css files readable"}

    try:
        # Resolve relative to app root (Heroku /app)
        full = os.path.join(os.getcwd(), norm)
        if not os.path.exists(full):
            return {"error": f"file not found: {norm}"}
        if os.path.getsize(full) > 500_000:
            return {"error": f"file too large (>500KB) — narrow with start_line/num_lines"}

        with open(full, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        total = len(all_lines)
        start = max(1, int(start_line))
        end = min(total, start + int(num_lines) - 1)
        snippet = ''.join(all_lines[start-1:end])
        return {
            'file': norm,
            'total_lines': total,
            'showing': f'{start}-{end}',
            'content': snippet[:8000],
            'truncated': len(snippet) > 8000,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_run_diagnostic_test(test_name):
    """Run one of the registered diagnostic test scripts (read-only checks)
    and report results.

    Whitelisted tests:
    - 'tools' — verify all Claude tools work (test_claude_tools.py)
    - 'tts' — verify TTS layer (test_claude_tts.py)
    - 'brain_memory' — verify brain+memory tools
    - 'agents_beat' — verify agent bus + RTCF beat
    - 'komunikace' — verify communication module
    - 'ha' — verify Home Assistant tools
    - 'voice_runtime' — verify wake word + voice tools

    Returns first 100 lines of stdout + exit code.
    """
    import subprocess
    TEST_MAP = {
        'tools': 'scripts/test_claude_tools.py',
        'tts': 'scripts/test_claude_tts.py',
        'brain_memory': 'scripts/test_claude_brain_memory.py',
        'agents_beat': 'scripts/test_claude_agents_beat.py',
        'komunikace': 'scripts/test_claude_komunikace.py',
        'ha': 'scripts/test_claude_ha.py',
        'voice_runtime': 'scripts/test_claude_voice_runtime.py',
    }
    if test_name not in TEST_MAP:
        return {"error": f"unknown test — choose from {sorted(TEST_MAP.keys())}"}

    script = TEST_MAP[test_name]
    try:
        result = subprocess.run(
            ['python3', script],
            capture_output=True, text=True, timeout=120,
        )
        # Last 100 lines is more useful than first
        out_lines = (result.stdout or '').splitlines()
        return {
            'test': test_name,
            'exit_code': result.returncode,
            'success': result.returncode == 0,
            'stdout_tail': '\n'.join(out_lines[-100:])[:5000],
            'stderr_tail': (result.stderr or '')[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"test '{test_name}' timed out (>120s)"}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_report_bug(category, severity, file, description, suggested_fix=None,
                     reproducer=None):
    """File a structured bug report. Stored as observation_type='bug_report'.

    Reports appear in the admin dashboard for human review. A separate dev
    workflow (Claude Code with full edit permissions, or CI/CD pipeline)
    picks them up and applies fixes under supervision.

    The autonomous agent does NOT modify production code at runtime.

    category: 'crash' / 'logic' / 'performance' / 'security' / 'ux' / 'config'
    severity: 'INFO' / 'WARNING' / 'ALERT' / 'CRISIS'
    """
    if not _DB:
        return {"error": "DB not available"}
    valid_categories = {'crash', 'logic', 'performance', 'security', 'ux', 'config', 'flaky'}
    if category not in valid_categories:
        return {"error": f"category must be one of {sorted(valid_categories)}"}
    valid_severities = {'INFO', 'WARNING', 'ALERT', 'CRISIS'}
    if severity not in valid_severities:
        return {"error": f"severity must be one of {sorted(valid_severities)}"}

    try:
        report = {
            'category': category,
            'file': file[:200],
            'description': description[:1000],
            'suggested_fix': (suggested_fix or '')[:1000],
            'reproducer': (reproducer or '')[:500],
            'reported_at': datetime.utcnow().isoformat(),
        }
        # Store as agent observation with the bug report payload
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'agent_observations',
                      ['user_id', 'observation_type', 'severity',
                       'message', 'details'],
                      ['system', 'bug_report', severity,
                       f'{category}: {description[:500]}',
                       json.dumps(report, ensure_ascii=False)])
        # Also push to agent bus so devs / dashboards see it immediately
        if _AGENT_BUS:
            try:
                _bus_emit(
                    user_id='system',
                    sender='claude_agent.self_diagnostic',
                    kind='observation',
                    severity=severity.lower(),
                    topic=f'bug_report.{category}',
                    payload=report,
                    ttl_minutes=10080,  # 7 days
                )
            except Exception:
                pass
        return {
            'reported': True,
            'category': category,
            'severity': severity,
            '_hint': ('Bug report stored. Visible in admin-claude dashboard. '
                      'A dev workflow will pick it up. The autonomous agent '
                      'does NOT auto-apply fixes to production code.'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# STT TOOLS — Azure Speech-to-Text + Czech understanding pipeline
# ═══════════════════════════════════════════════════════════════════════

def _tool_stt_status():
    """Is STT subsystem available? Azure key set? speech_understanding loaded?"""
    return {
        'azure_key_set': bool(_AZURE_STT_KEY),
        'azure_region': _AZURE_STT_REGION,
        'speech_understanding': _STT_UNDERSTANDING,
        'transcribe_endpoint': '/api/speech/transcribe',
        '_hint': ('Live STT happens at /api/speech/transcribe (audio bytes → text). '
                  'These tools work on text seniors said — fuzzy matching, '
                  'safety detection, correction of common Czech STT errors.')
    }


def _tool_stt_normalize_text(text):
    """Normalize text for fuzzy matching: lowercase + strip diacritics +
    remove punctuation. Useful when comparing senior's speech to known
    phrases, command keywords, etc.

    'Příliš Žluťoučký Kůň!' → 'prilis zlutoucky kun'
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    if not text:
        return {"error": "empty text"}
    try:
        return {
            'original': text[:300],
            'normalized': _stt_normalize(text)[:300],
            'no_diacritics': _stt_strip_diacritics(text)[:300],
            'phonetic': _stt_phonetic(text)[:300],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_detect_safety(text):
    """Fuzzy match for safety/distress words: 'pomoc', 'spadla jsem',
    'nemůžu vstát', 'bolí', 'rychle'. Levenshtein-tolerant, handles
    speech-impaired diction.

    Returns: {detected, word, input, distance, severity} where
    severity is 'critical'/'high'/'medium'/None.
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    if not text:
        return {"error": "empty text"}
    try:
        result = _stt_detect_safety(text)
        if result is None:
            return {'detected': False, 'word': None, 'severity': None}
        return {
            'detected': True,
            'word': result.get('word'),
            'input': result.get('input'),
            'distance': result.get('distance'),
            'severity': result.get('severity'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_classify_priority(text, confidence=1.0):
    """Classify how urgent the speech is.

    Returns: {priority: 'CRITICAL'/'MEDIUM'/'LOW',
              bypass_ai: bool,
              escalate: bool,
              reason: str|None}
    bypass_ai=True means skip full AI cycle, react immediately.
    escalate=True means notify caregiver/family.
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    if not text:
        return {"error": "empty text"}
    try:
        result = _stt_classify_safety(text, float(confidence))
        if isinstance(result, dict):
            return result
        return {'priority': str(result)}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_correct_text(text, senior_id=None):
    """Apply common Czech STT error corrections.

    Twilio cs-CZ STT often hears medications/places/Czech words wrong.
    This dictionary-based corrector fixes 50+ known patterns.

    Use BEFORE feeding senior's transcribed speech into your decision logic.
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    if not text:
        return {"error": "empty text"}
    try:
        # Returns tuple: (corrected_text, corrections_applied_list)
        result = _stt_correct(text, user_id=str(senior_id) if senior_id else None)
        if isinstance(result, tuple) and len(result) == 2:
            corrected, applied = result
        else:
            corrected, applied = (str(result), [])
        return {
            'original': text[:500],
            'corrected': str(corrected)[:500],
            'changed': str(corrected) != text,
            'corrections_applied': applied if isinstance(applied, list) else [],
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_should_retry(text, confidence):
    """Should we re-prompt the senior because STT confidence was too low?

    Returns: {action, retry, safety_match}
    - action: 'retry' (ask again) | 'safety' (safety word detected) | 'proceed' (OK)
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    try:
        result = _stt_should_retry(text or '', float(confidence))
        # Returns (action, data) tuple
        if isinstance(result, tuple) and len(result) == 2:
            action, data = result
            return {
                'action': action,
                'retry': action == 'retry',
                'safety_detected': action == 'safety',
                'safety_match': data if action == 'safety' else None,
                'proceed': action == 'proceed',
            }
        return {'action': str(result)}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_gather_params(senior_id):
    """Get adaptive Twilio Gather (STT) parameters for this senior based on
    their communication profile.

    Slow-speech (alzheimer/parkinson/dysarthria) gets longer timeout +
    more lenient confidence threshold. Hearing-impaired gets phrase hints.

    Returns: {timeout, speechTimeout, speechModel, hints, language}
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    try:
        params = _stt_gather_params(str(senior_id))
        return params if isinstance(params, dict) else {'params': str(params)}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_stt_build_hints(senior_id):
    """Build Azure STT phrase hints based on senior's profile + chat history.

    Hints help STT correctly transcribe the senior's children's names,
    medications, hobbies, places they mention often. Reduces transcription
    errors for personal vocabulary.
    """
    if not _STT_UNDERSTANDING:
        return {"error": "speech_understanding not available"}
    try:
        hints = _stt_speech_hints(str(senior_id))
        return {
            'hints': hints if isinstance(hints, list) else [],
            'count': len(hints) if isinstance(hints, list) else 0,
            '_hint': 'Pass these to Azure STT phraseList for personalized recognition',
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# CALENDAR TOOLS — events, reminders, scheduling
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_upcoming_events(senior_id, hours=24):
    """Senior's upcoming calendar events in the next N hours.

    Returns events with: title, date, time, type (event/medication/visit),
    location, reminder flag. Use for proactive "Don't forget about X
    today/tomorrow" messages.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = (f"NOW() + INTERVAL '{int(hours)} hours'" if is_postgres()
                        else f"datetime('now', '+{int(hours)} hour')")
            now = ("NOW()" if is_postgres() else "datetime('now')")
            rows = db.execute(f"""
                SELECT id, title, date, time, type, description, location,
                       reminder, repeat_type
                FROM calendar_events
                WHERE user_id = ?
                  AND (date || 'T' || COALESCE(time, '00:00') || ':00')::timestamp
                    BETWEEN {now} AND {interval}
                ORDER BY date, time
                LIMIT 30
            """ if is_postgres() else f"""
                SELECT id, title, date, time, type, description, location,
                       reminder, repeat_type
                FROM calendar_events
                WHERE user_id = ?
                  AND datetime(date || ' ' || COALESCE(time, '00:00') || ':00')
                    BETWEEN {now} AND {interval}
                ORDER BY date, time
                LIMIT 30
            """, (str(senior_id),)).fetchall()

            events = []
            for r in rows:
                vals = _row_to_list(r)
                events.append({
                    'id': vals[0],
                    'title': vals[1],
                    'date': str(vals[2]) if vals[2] else None,
                    'time': vals[3],
                    'type': vals[4],
                    'description': (vals[5] or '')[:200],
                    'location': vals[6],
                    'has_reminder': bool(vals[7]),
                    'repeat_type': vals[8],
                })
            return {
                'count': len(events),
                'window_hours': hours,
                'events': events,
            }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_find_free_slots(senior_id, days=7, start_hour=8, end_hour=18):
    """Find 3 free time slots in the next N days, weekdays preferred.

    Useful when scheduling new events: 'When can senior accommodate a
    family video call?' Returns slots that don't conflict with existing
    calendar events.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        # Pull existing events
        with db_context() as db:
            interval = (f"NOW() + INTERVAL '{int(days)} days'" if is_postgres()
                        else f"datetime('now', '+{int(days)} day')")
            rows = db.execute(f"""
                SELECT date, time FROM calendar_events
                WHERE user_id = ? AND date::text >= ?
                  AND date::text <= (CURRENT_DATE + INTERVAL '{int(days)} days')::text
                ORDER BY date, time
            """ if is_postgres() else f"""
                SELECT date, time FROM calendar_events
                WHERE user_id = ? AND date >= date('now')
                  AND date <= date('now', '+{int(days)} day')
                ORDER BY date, time
            """, (str(senior_id), datetime.now().strftime('%Y-%m-%d'))
            if is_postgres() else (str(senior_id),)).fetchall()

        busy = set()
        for r in rows:
            v = _row_to_list(r)
            busy.add(f"{v[0]}T{v[1] or '00:00'}")

        # Czech weekday names
        WEEKDAYS = ['Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota', 'Neděle']
        slots = []
        from datetime import timedelta
        # Try mornings first (10:00) then afternoons (14:00) for next N days
        for day_offset in range(1, int(days) + 1):
            for hour_choice in (10, 14, 16):
                if not (int(start_hour) <= hour_choice <= int(end_hour)):
                    continue
                target = datetime.now() + timedelta(days=day_offset)
                # Prefer weekdays first pass
                if len(slots) < 3 and target.weekday() < 5:  # 0=Mon..4=Fri
                    date_s = target.strftime('%Y-%m-%d')
                    time_s = f'{hour_choice:02d}:00'
                    key = f'{date_s}T{time_s}'
                    if key not in busy:
                        slots.append({
                            'date': date_s,
                            'time': time_s,
                            'weekday': WEEKDAYS[target.weekday()],
                            'label': f'{WEEKDAYS[target.weekday()]} {target.strftime("%-d.%-m.")} v {time_s}',
                        })
                if len(slots) >= 3:
                    break
            if len(slots) >= 3:
                break

        return {
            'slots': slots,
            'count': len(slots),
            'busy_count': len(busy),
            'window_days': days,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_add_calendar_reminder(senior_id, event_id):
    """Enable reminders (24h + 1h push) for an existing calendar event."""
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context(commit=True) as db:
            # Verify event belongs to senior + reset flags so reminders re-fire
            rows = db.execute("""
                UPDATE calendar_events
                SET reminder = 1, reminder_24h_sent = NULL, reminder_1h_sent = NULL
                WHERE user_id = ? AND id = ?
            """, (str(senior_id), int(event_id)))
            rowcount = getattr(rows, 'rowcount', None)
            if rowcount == 0:
                return {"error": "event not found or not owned by this senior"}
            return {
                'updated': True,
                'event_id': event_id,
                'reminder_enabled': True,
                '_hint': '24h + 1h push reminders will fire (calendar_reminder_cron every 10min)',
            }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_parse_event_text(text):
    """Parse Czech free-form text into structured calendar event.

    'Zítra v 14 doktor' → {title: 'Doktor', date: '2026-04-30', time: '14:00', type: 'visit'}

    Tries Gemini first (better understanding), falls back to rule-based.
    No DB write — Claude can review before creating.
    """
    if not _CALENDAR_PARSE:
        return {"error": "calendar_routes parsers not available"}
    if not text or not text.strip():
        return {"error": "empty text"}
    try:
        # Try Gemini first
        result = None
        try:
            result = _parse_event_gemini(text)
            if result:
                result['_source'] = 'gemini'
        except Exception:
            pass
        if not result:
            try:
                result = _parse_event_rule_based(text)
                if result:
                    result['_source'] = 'rule_based'
            except Exception:
                pass
        if not result:
            return {"error": "couldn't parse — try clearer Czech format"}
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# EMAIL TOOLS — read inbox, send, security scan, family flags
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_unread_emails(senior_id, limit=20):
    """Senior's recent unread emails (live IMAP read).

    Returns: list of {uid, from_name, from_email, subject, date}.
    Read-only — doesn't mark as read. Use for daily briefing.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        # Check senior has email account configured
        with db_context() as db:
            row = db.execute("""
                SELECT email_address, last_sync_at FROM email_accounts
                WHERE user_id = ? LIMIT 1
            """, (str(senior_id),)).fetchone()
        if not row:
            return {"info": "Senior has no email account configured"}
        vals = _row_to_list(row)
        email_addr = vals[0]
        last_sync = vals[1]

        # Use email_inbox helpers
        try:
            from email_inbox_routes import _load_account, _open_imap, _decode_header, _parse_from
            account = _load_account(str(senior_id))
            if not account:
                return {"error": "couldn't load encrypted credentials"}

            mail = _open_imap(account)
            mail.select('INBOX')
            status, data = mail.search(None, 'UNSEEN')
            if status != 'OK':
                return {"error": f"IMAP search failed: {status}"}

            unread_uids = data[0].split()
            recent_uids = unread_uids[-int(limit):]
            messages = []
            for uid in reversed(recent_uids):  # newest first
                try:
                    status, msg_data = mail.fetch(uid, '(RFC822.HEADER)')
                    if status != 'OK':
                        continue
                    import email as _email
                    msg = _email.message_from_bytes(msg_data[0][1])
                    from_name, from_email = _parse_from(msg.get('From', ''))
                    messages.append({
                        'uid': uid.decode('utf-8'),
                        'from_name': from_name,
                        'from_email': from_email,
                        'subject': _decode_header(msg.get('Subject', '')),
                        'date': msg.get('Date', ''),
                    })
                except Exception as e:
                    logger.debug(f"email parse skip: {e}")
            try:
                mail.logout()
            except Exception:
                pass

            return {
                'email_account': email_addr,
                'unread_count': len(unread_uids),
                'showing': len(messages),
                'last_sync': str(last_sync) if last_sync else None,
                'messages': messages,
            }
        except ImportError:
            return {"error": "email_inbox_routes helpers unavailable"}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_scan_email_risk(subject, body, from_email, from_name=None,
                          use_ai=False):
    """Score an email for phishing/scam risk.

    Returns: {risky: bool, score: 0-100, reasons: [...]}.
    score≥70 = risky (recommend flag_email_to_family).

    use_ai=True invokes Gemini second opinion (more accurate but $).
    """
    if not _EMAIL_SECURITY:
        return {"error": "email_security not available"}
    try:
        # Heuristic scan (free, fast)
        heur = _email_scan_heur(
            subject or '', body or '',
            from_email or '', from_name or '',
        )
        result = {
            'risky': bool(heur.get('risky', False)),
            'score': heur.get('score', 0),
            'reasons': heur.get('reasons', [])[:10],
            'source': 'heuristic',
        }
        # Optional AI second opinion
        if use_ai and _EMAIL_SCAN_AI:
            try:
                ai = _email_scan_ai(subject or '', body or '',
                                    from_email or '', from_name or '')
                if ai:
                    # Combine — weighted average
                    h_score = result['score']
                    a_score = ai.get('score', 0)
                    combined = round((h_score * 0.4) + (a_score * 0.6))
                    result['score'] = combined
                    result['risky'] = combined >= 60
                    result['reasons'] = list(set(result['reasons'] + ai.get('reasons', [])))[:10]
                    result['source'] = 'combined'
                    result['ai_score'] = a_score
                    result['heuristic_score'] = h_score
            except Exception:
                pass
        return result
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_flag_email_to_family(senior_id, subject, body_snippet, from_email,
                               from_name=None, reasons=None):
    """Flag suspicious email to senior's family for review.

    Stores in email_family_flags table + pushes notification to all
    confirmed family links. Use when scan_email_risk returns risky=True
    and score≥70.
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        # Verify senior has linked family
        with db_context() as db:
            family = db.execute("""
                SELECT family_user_id FROM senior_family_links
                WHERE senior_id = ? AND confirmed = TRUE LIMIT 5
            """ if is_postgres() else """
                SELECT family_user_id FROM senior_family_links
                WHERE senior_id = ? AND confirmed = 1 LIMIT 5
            """, (str(senior_id),)).fetchall()
        if not family:
            return {"info": "No confirmed family links — flag has nowhere to go"}

        # Insert flag
        reasons_json = json.dumps(reasons or [], ensure_ascii=False)
        snippet = (body_snippet or '')[:500]
        with db_context(commit=True) as db:
            from database import db_insert
            flag_id = db_insert(db, 'email_family_flags',
                ['user_id', 'subject', 'from_email', 'from_name',
                 'snippet', 'reasons', 'sent_at', 'flagged_at'],
                [str(senior_id), (subject or '')[:200],
                 (from_email or '')[:120], (from_name or '')[:120],
                 snippet, reasons_json,
                 datetime.utcnow(), datetime.utcnow()])

        # Push to family via notification_helpers if available
        notified = 0
        try:
            from notification_helpers import notify_senior_family
            notify_senior_family(
                str(senior_id),
                title='⚠️ Podezřelý e-mail',
                body=f'{senior_id} obdržel email od {from_email}: {(subject or "")[:80]}',
            )
            notified = len(family)
        except (ImportError, Exception) as e:
            logger.debug(f"notify_senior_family fallback: {e}")

        return {
            'flag_id': flag_id,
            'flagged': True,
            'family_links': len(family),
            'family_notified': notified,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_email_to_family(senior_id, subject, body, urgency='normal'):
    """Send an email update to senior's family (via SMTP).

    Use sparingly — for substantive updates, not spam. SMS via notify_family
    is faster for urgent things.

    urgency: 'low' / 'normal' / 'high' — affects subject prefix.
    """
    try:
        # Resolve family email addresses from profile
        family_emails = []
        if _MEMORY_HELPERS:
            with db_context() as db:
                rows = db.execute("""
                    SELECT family_user_id FROM senior_family_links
                    WHERE senior_id = ? AND confirmed = TRUE LIMIT 5
                """ if is_postgres() else """
                    SELECT family_user_id FROM senior_family_links
                    WHERE senior_id = ? AND confirmed = 1 LIMIT 5
                """, (str(senior_id),)).fetchall()
            for r in rows:
                fp = _load_profile(str(_row_to_list(r)[0])) or {}
                if fp.get('email'):
                    family_emails.append(fp['email'])
        if not family_emails:
            return {"info": "No family email addresses on file"}

        prefix = {'high': '🚨 NALÉHAVÉ — ', 'normal': '', 'low': 'ℹ️ '}.get(urgency, '')
        full_subject = f'{prefix}{subject[:200]}'

        # Use email_routes.send_email helper
        try:
            from email_routes import get_smtp_config
            cfg = get_smtp_config()
            if not cfg or not cfg.get('host'):
                return {"error": "SMTP not configured (SMTP_HOST env missing)"}
        except ImportError:
            return {"error": "email_routes not available"}

        sent = 0
        import smtplib
        from email.mime.text import MIMEText
        try:
            for to_email in family_emails:
                msg = MIMEText(body[:5000], 'plain', 'utf-8')
                msg['Subject'] = full_subject
                msg['From'] = cfg.get('from_addr', cfg['user'])
                msg['To'] = to_email

                if cfg.get('use_ssl'):
                    server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=15)
                else:
                    server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=15)
                    server.starttls()
                server.login(cfg['user'], cfg['password'])
                server.send_message(msg)
                server.quit()
                sent += 1
        except Exception as e:
            return {"error": f"SMTP send failed: {str(e)[:200]}"}

        return {
            'sent': sent,
            'recipients': [e[:6] + '***' for e in family_emails],
            'urgency': urgency,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# CAREGIVER TOOLS — care plan, caregivers, relationships
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_senior_caregivers(senior_id):
    """List all caregivers + family linked to senior (paid + family — same model).

    Returns: list of {family_user_id, name, relation, email, status,
                      notify_on_sos, notify_on_crisis, notify_on_daily,
                      sos_priority, role}.
    role inferred from auth_users.role: 'caregiver' (paid) vs 'family' (linked).
    """
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            rows = db.execute("""
                SELECT l.id, l.family_user_id, l.family_name, l.family_email,
                       l.relation, l.sos_priority, l.notify_on_sos,
                       l.notify_on_crisis, l.notify_on_daily,
                       l.confirmed_at, l.revoked_at,
                       u.role, COALESCE(u.name, u.email)
                FROM senior_family_links l
                LEFT JOIN auth_users u ON
                    CASE WHEN l.family_user_id ~ '^[0-9]+$'
                         THEN u.id::text = l.family_user_id ELSE FALSE END
                WHERE l.senior_id = ?
                ORDER BY l.sos_priority NULLS LAST, l.confirmed_at DESC NULLS LAST
            """ if is_postgres() else """
                SELECT l.id, l.family_user_id, l.family_name, l.family_email,
                       l.relation, l.sos_priority, l.notify_on_sos,
                       l.notify_on_crisis, l.notify_on_daily,
                       l.confirmed_at, l.revoked_at,
                       u.role, COALESCE(u.name, u.email)
                FROM senior_family_links l
                LEFT JOIN auth_users u ON u.id = l.family_user_id
                WHERE l.senior_id = ?
                ORDER BY l.sos_priority, l.confirmed_at DESC
            """, (str(senior_id),)).fetchall()

        caregivers = []
        for r in rows:
            v = _row_to_list(r)
            if v[10]:  # revoked
                continue
            caregivers.append({
                'link_id': v[0],
                'family_user_id': v[1],
                'name': v[2] or v[12] or 'Unknown',
                'email': (v[3] or '')[:6] + '***' if v[3] else None,
                'relation': v[4],
                'sos_priority': v[5],
                'notify_sos': bool(v[6]),
                'notify_crisis': bool(v[7]),
                'notify_daily': bool(v[8]),
                'confirmed': bool(v[9]),
                'role': v[11] or 'family',  # 'caregiver' if paid, else 'family'
            })
        return {
            'count': len(caregivers),
            'confirmed_count': sum(1 for c in caregivers if c['confirmed']),
            'caregivers': caregivers,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_care_plan(senior_id, summary=False):
    """Senior's complete care plan: goals, medications, daily_routine,
    monitored_metrics, risks, responsibilities, checkups.

    summary=True returns counts only (cheap), False returns full plan.
    """
    if not _CARE_PLAN:
        return {"error": "care_plan module not available"}
    try:
        plan = _get_care_plan(str(senior_id))
        if not plan:
            return {"info": "No care plan yet — defaults will apply"}
        if summary:
            return {
                'has_plan': True,
                'goals_count': len(plan.get('goals', []) or []),
                'medications_count': len(plan.get('medications', []) or []),
                'risks_count': len(plan.get('risks', []) or []),
                'checkups_count': len(plan.get('checkups', []) or []),
                'routine_slots': len(plan.get('daily_routine', {}) or {}),
                'updated_by': plan.get('updated_by'),
                'updated_at': plan.get('updated_at'),
            }
        # Full but trim long lists
        for key in ('goals', 'medications', 'risks', 'checkups'):
            if isinstance(plan.get(key), list) and len(plan[key]) > 10:
                plan[key] = plan[key][:10] + [{'_truncated': len(plan[key]) - 10}]
        return plan
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_medication_schedule(senior_id):
    """Senior's medication schedule from care plan + adherence flag.

    Returns: list of {name, dosage, frequency, doctor, _next_dose_hint}.
    No actual compliance tracking yet — flag is heuristic.
    """
    if not _CARE_PLAN:
        return {"error": "care_plan not available"}
    try:
        plan = _get_care_plan(str(senior_id))
        if not plan:
            return {"info": "No care plan — no medications tracked"}
        meds = plan.get('medications', []) or []
        if not meds:
            return {"info": "No medications in care plan", "count": 0}
        return {
            'count': len(meds),
            'medications': [
                {
                    'name': m.get('name'),
                    'dosage': m.get('dosage'),
                    'frequency': m.get('frequency'),
                    'doctor': m.get('doctor'),
                }
                for m in meds[:15]
            ],
            '_hint': ('Use this to remind senior PROACTIVELY before scheduled '
                      'dose times. Cross-reference with daily_routine.'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_add_care_plan_goal(senior_id, text, priority='medium'):
    """Append a new goal to senior's care plan.

    priority: 'high' / 'medium' / 'low'.
    Use when learning new medical objective from chat / family input.
    """
    if not _CARE_PLAN:
        return {"error": "care_plan not available"}
    if not text or not text.strip():
        return {"error": "empty goal text"}
    if priority not in ('high', 'medium', 'low'):
        priority = 'medium'
    try:
        from care_plan import _get_plan as _gp
        from database import db_context as _dbc
        plan = _gp(str(senior_id)) or {}
        goals = plan.get('goals', []) or []
        new_goal = {
            'id': len(goals) + 1,
            'text': text[:500],
            'status': 'active',
            'priority': priority,
            'added': datetime.utcnow().isoformat(),
            'added_by': 'claude_agent',
        }
        goals.append(new_goal)
        plan['goals'] = goals
        # Persist via JSONB update
        with _dbc(commit=True) as db:
            if is_postgres():
                db.execute(
                    "UPDATE care_plans SET goals = ?, updated_by = ?, "
                    "updated_at = NOW() WHERE senior_id = ?",
                    (json.dumps(goals, ensure_ascii=False),
                     'claude_agent', str(senior_id))
                )
            else:
                db.execute(
                    "UPDATE care_plans SET goals = ?, updated_by = ?, "
                    "updated_at = datetime('now') WHERE senior_id = ?",
                    (json.dumps(goals, ensure_ascii=False),
                     'claude_agent', str(senior_id))
                )
        return {'added': True, 'goal_id': new_goal['id'], 'priority': priority}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_add_care_plan_risk(senior_id, text, severity='medium', mitigation=None):
    """Append a new risk + mitigation to senior's care plan.

    severity: 'high' / 'medium' / 'low'.
    Use when detecting recurring pattern (multiple falls, med non-adherence).
    """
    if not _CARE_PLAN:
        return {"error": "care_plan not available"}
    if not text or not text.strip():
        return {"error": "empty risk text"}
    if severity not in ('high', 'medium', 'low'):
        severity = 'medium'
    try:
        from care_plan import _get_plan as _gp
        plan = _gp(str(senior_id)) or {}
        risks = plan.get('risks', []) or []
        new_risk = {
            'id': len(risks) + 1,
            'text': text[:500],
            'severity': severity,
            'mitigation': (mitigation or '')[:500],
            'added': datetime.utcnow().isoformat(),
            'added_by': 'claude_agent',
        }
        risks.append(new_risk)
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "UPDATE care_plans SET risks = ?, updated_by = ?, "
                    "updated_at = NOW() WHERE senior_id = ?",
                    (json.dumps(risks, ensure_ascii=False),
                     'claude_agent', str(senior_id))
                )
            else:
                db.execute(
                    "UPDATE care_plans SET risks = ?, updated_by = ?, "
                    "updated_at = datetime('now') WHERE senior_id = ?",
                    (json.dumps(risks, ensure_ascii=False),
                     'claude_agent', str(senior_id))
                )
        return {'added': True, 'risk_id': new_risk['id'], 'severity': severity}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_caregiver_notification(senior_id, title, body,
                                      severity='info', ntype='claude_observation'):
    """Send a notification to ALL caregivers/family linked to senior.

    Routes through caregiver_notifications table — they appear in
    caregiver inbox + push if notify_on_X=True.

    severity: 'info' / 'warning' / 'alert' / 'crisis'
    ntype: short type tag (claude_observation / med_reminder / etc.)
    """
    if not _DB:
        return {"error": "DB not available"}
    valid_sev = {'info', 'warning', 'alert', 'crisis'}
    if severity.lower() not in valid_sev:
        return {"error": f"severity must be one of {sorted(valid_sev)}"}
    try:
        # Find all confirmed family/caregiver links
        with db_context() as db:
            rows = db.execute("""
                SELECT family_user_id FROM senior_family_links
                WHERE senior_id = ?
                  AND confirmed_at IS NOT NULL
                  AND revoked_at IS NULL
            """, (str(senior_id),)).fetchall()
        if not rows:
            return {"info": "No confirmed caregivers/family"}

        # Use existing helper to queue notifications
        sent = 0
        try:
            from caregiver_routes import create_caregiver_notification
            for r in rows:
                fam_id = _row_to_list(r)[0]
                if not fam_id:
                    continue
                nid = create_caregiver_notification(
                    recipient_id=str(fam_id),
                    senior_id=str(senior_id),
                    ntype=ntype,
                    title=title[:200],
                    body=body[:1000],
                    severity=severity.lower(),
                    ref_type='claude_agent',
                    ref_id=None,
                    data={'source': 'claude_agent'},
                )
                if nid:
                    sent += 1
        except ImportError:
            return {"error": "create_caregiver_notification helper missing"}

        return {
            'sent': sent,
            'recipients': len(rows),
            'severity': severity,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_relationship(senior_id):
    """Get Confucian relationship state for senior.

    Returns: {type, trust (0-1), vulnerability, familiarity,
              permission_level (SUGGEST/ASSIST/EXECUTE), virtues:
              {ren, yi, li, zhi, xin}, prompt_text}.

    Use to understand what level of action Claude is empowered to take.
    permission_level=SUGGEST → only propose, don't act.
    permission_level=EXECUTE → can take direct action without asking.
    """
    if not _RELATIONSHIP:
        return {"error": "relationship_engine not available"}
    try:
        rel = _load_rel(str(senior_id))
        if not rel:
            return {"info": "No relationship state — first interaction"}
        # Trim verbose fields
        if 'prompt' in rel and len(rel.get('prompt', '')) > 500:
            rel['prompt'] = rel['prompt'][:500] + '…'
        return rel
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_caregiver_whisper(senior_id, text, priority='normal'):
    """Inject caregiver context into Radim's chat memory.

    Caregivers can 'whisper' context to Radim that he'll mention naturally
    in next conversation: 'Připomeň jí, že vnučka má dnes narozeniny.'

    Stored in memory_learning.caregiver_whispers — the chat coordinator
    pulls these into system prompt.
    """
    if not _DB:
        return {"error": "DB not available"}
    if not text or not text.strip():
        return {"error": "empty text"}
    try:
        from memory_helpers import db_load_learning, db_save_learning
        learning = db_load_learning(str(senior_id)) or {}
        whispers = learning.get('caregiver_whispers', []) or []
        whispers.append({
            'text': text[:500],
            'priority': priority,
            'added_at': datetime.utcnow().isoformat(),
            'source': 'claude_agent',
            'consumed': False,
        })
        # Keep last 20
        learning['caregiver_whispers'] = whispers[-20:]
        db_save_learning(str(senior_id), learning)
        return {
            'whispered': True,
            'priority': priority,
            'total_whispers': len(whispers),
            '_hint': 'Radim will mention this naturally in next chat',
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# EDUCATION TOOLS — lessons, scenarios, progress, assignments
# ═══════════════════════════════════════════════════════════════════════

def _modules_iter(course):
    """Normalize modules collection — could be dict {id: module} or list of modules."""
    mods = course.get('modules') or {}
    if isinstance(mods, dict):
        return list(mods.items())  # [(id, module), ...]
    if isinstance(mods, list):
        return [(m.get('id', m.get('module_id', f'm{i}')), m)
                for i, m in enumerate(mods) if isinstance(m, dict)]
    return []


def _tool_get_education_courses(filter_type=None):
    """Catalog of available education courses.

    Each course has modules → lessons + quizzes.
    filter_type: 'dysphasia' / 'dysartria' / etc. (matches course key).
    """
    if not _EDU_DATA:
        return {"error": "education_data not available"}
    try:
        courses = []
        for cid, c in _EDU_COURSES.items():
            if filter_type and filter_type.lower() not in cid.lower():
                continue
            modules = _modules_iter(c)
            courses.append({
                'course_id': cid,
                'title': c.get('title', cid),
                'description': (c.get('description') or '')[:200],
                'level': c.get('level', 'beginner'),
                'modules_count': len(modules),
                'duration_min': c.get('duration_min'),
            })
        return {
            'count': len(courses),
            'courses': courses[:30],  # cap to avoid token blowout
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_lesson_progress(senior_id):
    """Senior's overall education progress: completion %, scores, level.

    Returns: per-course completion + adaptive level + badges + last activity.
    """
    if not _EDUCATION:
        return {"error": "education_helpers not available"}
    try:
        progress = _edu_get_progress(str(senior_id)) or {}
        profile = _edu_get_profile(str(senior_id)) or {}

        # Aggregate
        total_completed = 0
        total_lessons = 0
        avg_scores = []
        per_course = {}
        for course_id, data in progress.items():
            if not isinstance(data, dict):
                continue
            completed = len(data.get('completed_modules', []) or [])
            scores = data.get('quiz_scores', {}) or {}
            avg = (sum(scores.values()) / len(scores)) if scores else 0
            per_course[course_id] = {
                'completed_modules': completed,
                'avg_quiz_score': round(avg, 1) if avg else None,
                'last_activity': data.get('last_activity'),
            }
            total_completed += completed
            avg_scores.extend(scores.values())

        return {
            'level': profile.get('level', 'beginner'),
            'badges': profile.get('badges', []) or [],
            'recommended_courses': profile.get('recommended_courses', []) or [],
            'overall_avg_score': round(sum(avg_scores)/len(avg_scores), 1) if avg_scores else None,
            'total_modules_completed': total_completed,
            'courses_active': len(per_course),
            'per_course': per_course,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_recommended_lessons(senior_id, limit=5):
    """Personalized lesson recommendations based on senior's adaptive profile.

    Uses: communication_needs from profile + education progress + level.
    Returns: list of {course_id, module_id, title, reason}.
    """
    if not _EDUCATION or not _EDU_DATA:
        return {"error": "education subsystem incomplete"}
    try:
        profile = _edu_get_profile(str(senior_id)) or {}
        progress = _edu_get_progress(str(senior_id)) or {}

        # Senior's communication needs (from memory profile, if available)
        senior_needs = []
        if _MEMORY_HELPERS:
            try:
                p = _load_profile(str(senior_id)) or {}
                needs = p.get('communication_needs', [])
                if isinstance(needs, str):
                    needs = [n.strip() for n in needs.split(',') if n.strip()]
                senior_needs = needs
            except Exception:
                pass

        recs = []
        # 1. Recommended from adaptive profile (existing recommendations)
        for cid in (profile.get('recommended_courses') or [])[:limit]:
            c = _EDU_COURSES.get(cid)
            if c:
                done_modules = (progress.get(cid) or {}).get('completed_modules', []) or []
                modules = _modules_iter(c)
                for mid, m in modules:
                    if mid not in done_modules:
                        recs.append({
                            'course_id': cid,
                            'module_id': mid,
                            'title': m.get('title', mid),
                            'level': c.get('level'),
                            'reason': 'recommended_by_adaptive_profile',
                        })
                        break

        # 2. Match by communication_needs (e.g., alzheimer_middle → caregiver courses)
        for need in senior_needs:
            need_lower = need.lower()
            for cid, c in _EDU_COURSES.items():
                if any(kw in cid.lower() for kw in need_lower.split('_')):
                    if not any(r['course_id'] == cid for r in recs):
                        done = (progress.get(cid) or {}).get('completed_modules', []) or []
                        for mid, m in _modules_iter(c):
                            if mid not in done:
                                recs.append({
                                    'course_id': cid,
                                    'module_id': mid,
                                    'title': m.get('title', mid),
                                    'level': c.get('level'),
                                    'reason': f'matches_communication_need:{need}',
                                })
                                break
                        break
            if len(recs) >= int(limit):
                break

        return {
            'count': len(recs[:int(limit)]),
            'recommendations': recs[:int(limit)],
            'senior_level': profile.get('level', 'beginner'),
            'senior_needs': senior_needs,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_lesson_content(course_id, module_id):
    """Full lesson content (article HTML, key points, quiz_id if exists).

    Use to deliver lesson content to senior or insert into chat.
    """
    if not _EDU_DATA:
        return {"error": "education_data not available"}
    try:
        c = _EDU_COURSES.get(course_id)
        if not c:
            return {"error": f"course '{course_id}' not found"}
        m = None
        for mid, candidate in _modules_iter(c):
            if mid == module_id:
                m = candidate
                break
        if not m:
            return {"error": f"module '{module_id}' not found in '{course_id}'"}
        # Trim verbose content for token economy
        content = (m.get('content') or '')[:3000]
        return {
            'course_id': course_id,
            'module_id': module_id,
            'title': m.get('title'),
            'content': content,
            'duration_min': m.get('duration_min'),
            'key_points': m.get('key_points', [])[:10],
            'quiz_questions_count': len(m.get('quiz', []) or []),
            'has_scenario': bool(m.get('scenario')),
            'level': c.get('level'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_mark_lesson_complete(senior_id, course_id, module_id, score=None):
    """Mark a lesson as completed for senior, optionally with quiz score.

    Triggers adaptive evaluation if score provided (updates level/badges).
    """
    if not _EDUCATION:
        return {"error": "education_helpers not available"}
    try:
        # Save progress event
        _edu_save_progress(
            str(senior_id),
            course_id=course_id,
            module_id=module_id,
            action='complete_lesson',
            score=float(score) if score is not None else None,
        )
        # Trigger adaptive update if score given
        if score is not None:
            try:
                _edu_evaluate(str(senior_id), course_id, module_id, float(score))
            except Exception:
                pass
        return {
            'completed': True,
            'course_id': course_id,
            'module_id': module_id,
            'score': score,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_assignments(senior_id, status='active'):
    """Active education task assignments for senior (from teachers).

    status: 'active' / 'completed' / 'overdue' / 'all'
    """
    if not _DB:
        return {"error": "DB not available"}
    valid = {'active', 'completed', 'overdue', 'all'}
    if status not in valid:
        return {"error": f"status must be one of {sorted(valid)}"}
    try:
        with db_context() as db:
            if status == 'all':
                rows = db.execute("""
                    SELECT id, title, description, task_type, course_id, module_id,
                           due_date, status, grade, created_at
                    FROM education_teacher_tasks
                    WHERE student_id = ?
                    ORDER BY created_at DESC LIMIT 30
                """, (str(senior_id),)).fetchall()
            elif status == 'overdue':
                now = "NOW()" if is_postgres() else "datetime('now')"
                rows = db.execute(f"""
                    SELECT id, title, description, task_type, course_id, module_id,
                           due_date, status, grade, created_at
                    FROM education_teacher_tasks
                    WHERE student_id = ? AND status != 'completed'
                      AND due_date < {now}
                    ORDER BY due_date LIMIT 30
                """, (str(senior_id),)).fetchall()
            else:
                rows = db.execute("""
                    SELECT id, title, description, task_type, course_id, module_id,
                           due_date, status, grade, created_at
                    FROM education_teacher_tasks
                    WHERE student_id = ? AND status = ?
                    ORDER BY due_date NULLS LAST, created_at DESC LIMIT 30
                """ if is_postgres() else """
                    SELECT id, title, description, task_type, course_id, module_id,
                           due_date, status, grade, created_at
                    FROM education_teacher_tasks
                    WHERE student_id = ? AND status = ?
                    ORDER BY due_date, created_at DESC LIMIT 30
                """, (str(senior_id), status)).fetchall()

        assignments = []
        for r in rows:
            v = _row_to_list(r)
            assignments.append({
                'id': v[0],
                'title': v[1],
                'description': (v[2] or '')[:300],
                'task_type': v[3],
                'course_id': v[4],
                'module_id': v[5],
                'due_date': str(v[6]) if v[6] else None,
                'status': v[7],
                'grade': v[8],
                'created_at': str(v[9]) if v[9] else None,
            })
        return {
            'count': len(assignments),
            'status_filter': status,
            'assignments': assignments,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_recommend_scenario(senior_id, situation_keywords):
    """Recommend a communication scenario based on situation keywords.

    situation_keywords: 'alzheimer agitace' / 'samota deprese' / etc.
    Returns: top matching scenario with options + score guidance.
    """
    if not _EDU_DATA:
        return {"error": "education_data not available"}
    if not situation_keywords or not situation_keywords.strip():
        return {"error": "empty situation_keywords"}
    try:
        # Normalize keywords for matching
        if _STT_UNDERSTANDING:
            try:
                kw_norm = _stt_normalize(situation_keywords)
            except Exception:
                kw_norm = situation_keywords.lower()
        else:
            kw_norm = situation_keywords.lower()

        kw_tokens = set(kw_norm.split())

        # COMMUNICATION_SCENARIOS structure: {course_id: [scenario_dict, ...]}
        # Flatten across all courses
        scored = []
        scenarios_dict = _EDU_SCENARIOS if isinstance(_EDU_SCENARIOS, dict) else {}
        for course_id, scenario_list in scenarios_dict.items():
            if not isinstance(scenario_list, list):
                continue
            for idx, scenario in enumerate(scenario_list):
                if not isinstance(scenario, dict):
                    continue
                sid = scenario.get('id', f'{course_id}_s{idx}')
                text_blob = (
                    (scenario.get('title') or '') + ' ' +
                    (scenario.get('situation') or '') + ' ' +
                    (scenario.get('description') or '')
                ).lower()
                if _STT_UNDERSTANDING:
                    try:
                        text_blob = _stt_normalize(text_blob)
                    except Exception:
                        pass
                text_tokens = set(text_blob.split())
                overlap = len(kw_tokens & text_tokens)
                if overlap > 0:
                    scored.append((overlap, sid, {**scenario, '_course': course_id}))

        scored.sort(reverse=True, key=lambda x: x[0])
        if not scored:
            return {"info": "No matching scenarios", "keywords": situation_keywords}

        top = scored[0]
        scenario = top[2]
        return {
            'scenario_id': top[1],
            'title': scenario.get('title'),
            'situation': (scenario.get('situation') or '')[:500],
            'options_count': len(scenario.get('options', []) or []),
            'options_preview': [
                {'text': (o.get('text') or '')[:120],
                 'score': o.get('score')}
                for o in (scenario.get('options', []) or [])[:4]
            ],
            'match_score': top[0],
            'total_candidates': len(scored),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# ═══════════════════════════════════════════════════════════════════════
# TV + MUSIC TOOLS — radio stations, ambient, YouTube search
# ═══════════════════════════════════════════════════════════════════════

def _tool_get_music_stations(group=None):
    """Catalog of available radio + ambient streams.

    group: 'czech' / 'thematic' / 'relax' / None (all).
    Returns: list of stations grouped + total counts.
    """
    if group and group not in _MUSIC_STATIONS:
        return {"error": f"group must be one of {list(_MUSIC_STATIONS.keys())}"}
    try:
        if group:
            return {
                'group': group,
                'count': len(_MUSIC_STATIONS[group]),
                'stations': _MUSIC_STATIONS[group],
            }
        return {
            'groups': {g: len(s) for g, s in _MUSIC_STATIONS.items()},
            'total': sum(len(s) for s in _MUSIC_STATIONS.values()),
            'all_stations': _MUSIC_STATIONS,
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_recommend_music(senior_id, mood_override=None, time_aware=True):
    """Recommend a station based on senior's current Ψ(t) state, hour
    of day, voice memory preferences.

    Logic:
    - CRISIS mode → meditative/calm only (Vltava, Klasika, Drone)
    - ALERT mode → calm or meditative (Vltava, Lush, Klasika)
    - HARMONY mode + morning → informative (Radiožurnál)
    - HARMONY mode + afternoon → cheerful or upbeat (Dvojka, Blaník, Impuls)
    - HARMONY mode + evening → calm or nostalgic (Vltava, Blaník)

    mood_override: 'calm' / 'cheerful' / 'meditative' / 'informative' / 'upbeat'
    """
    try:
        # Get current brain mode
        mode = 'HARMONY'
        if _DB:
            try:
                with db_context() as db:
                    row = db.execute("""
                        SELECT mode FROM brain_states WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT 1
                    """, (str(senior_id),)).fetchone()
                if row:
                    vals = _row_to_list(row)
                    mode = vals[0] or 'HARMONY'
            except Exception:
                pass

        # Decide mood from brain mode + hour (unless override)
        hour = datetime.now().hour
        if mood_override:
            target_mood = mood_override.lower()
        elif mode == 'CRISIS':
            target_mood = 'meditative'
        elif mode == 'ALERT':
            target_mood = 'calm'
        elif time_aware:
            if hour < 10:
                target_mood = 'informative'
            elif hour < 18:
                target_mood = 'cheerful'
            else:
                target_mood = 'calm'
        else:
            target_mood = 'cheerful'

        # Find matching stations across all groups
        candidates = []
        for grp, stations in _MUSIC_STATIONS.items():
            for s in stations:
                if s['mood'] == target_mood:
                    candidates.append({**s, '_group': grp})

        if not candidates:
            # Fallback: just pick first czech station
            candidates = [{**_MUSIC_STATIONS['czech'][0], '_group': 'czech'}]

        # If voice memory says 'singing_negative' → avoid upbeat
        if _TTS_LEARNING:
            try:
                prefs = _get_voice_prefs(str(senior_id))
                if prefs.get('response_to_melody', 0.5) < 0.3:
                    # Senior dislikes melodic stuff — prefer ambient/news
                    candidates = [c for c in candidates if c.get('mood') in ('calm', 'meditative', 'informative')]
            except Exception:
                pass

        # Top recommendation
        top = candidates[0] if candidates else None
        return {
            'top_recommendation': top,
            'reason': {
                'brain_mode': mode,
                'hour': hour,
                'target_mood': target_mood,
                'mood_override_applied': bool(mood_override),
            },
            'alternatives': candidates[1:5],
            'total_matches': len(candidates),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_play_music_for_senior(senior_id, station_id):
    """Trigger music playback for senior. Emits to agent_messages bus
    with kind='intent' + topic='play_music' + payload {station_id, url}.

    Frontend MusicModule.startPlayback() listens for this and starts the
    stream. Respects voice session state (won't interrupt active conversation).

    Returns: which station was selected, URL, group.
    """
    if not _AGENT_BUS:
        return {"error": "agent_bus not available — can't broadcast play intent"}

    # Check voice session state — don't interrupt active conversation
    if _VOICE_RUNTIME:
        try:
            session = _get_voice_session(str(senior_id))
            state = session.get('state', 'idle')
            if state != _VOICE_STATES['IDLE']:
                return {"skipped": f"voice session is {state} — won't interrupt"}
        except Exception:
            pass

    # Find station
    found = None
    for grp, stations in _MUSIC_STATIONS.items():
        for s in stations:
            if s['id'] == station_id:
                found = {**s, '_group': grp}
                break
        if found:
            break
    if not found:
        return {"error": f"station '{station_id}' not found",
                "_hint": "use get_music_stations() to see valid IDs"}

    try:
        msg_id = _bus_emit(
            user_id=str(senior_id),
            sender='claude_agent.music',
            kind='intent',
            severity='info',
            topic='play_music',
            payload={
                'station_id': found['id'],
                'station_name': found['name'],
                'url': found['url'],
                'category': found['category'],
                'mood': found['mood'],
                'group': found['_group'],
            },
            ttl_minutes=5,  # Short TTL — frontend should pick up quickly
        )
        return {
            'requested': True,
            'station': found['name'],
            'station_id': found['id'],
            'mood': found['mood'],
            'bus_msg_id': msg_id,
            '_hint': 'Frontend MusicModule reads bus, starts playback. Audio plays through senior\'s device.',
        }
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_pause_music_for_senior(senior_id):
    """Stop currently playing music. Emits 'intent' with topic='pause_music'."""
    if not _AGENT_BUS:
        return {"error": "agent_bus not available"}
    try:
        msg_id = _bus_emit(
            user_id=str(senior_id),
            sender='claude_agent.music',
            kind='intent',
            severity='info',
            topic='pause_music',
            payload={'action': 'pause'},
            ttl_minutes=2,
        )
        return {'requested': True, 'bus_msg_id': msg_id}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_youtube_search(query, limit=6):
    """Search YouTube videos via tv_proxy_routes scraper (no API key).

    For seniors who like to watch concerts, sports highlights, news clips,
    Czech folk songs. Returns video ID + title + thumbnail.
    """
    if not _TV_AVAILABLE:
        return {"error": "urllib not available"}
    if not query or not query.strip():
        return {"error": "empty query"}
    try:
        # Use existing internal endpoint to leverage scraper
        BASE = os.getenv('SELF_BASE_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
        url = f'{BASE}/api/tv/youtube/search?q={_urllib_parse.quote(query)}&limit={int(limit)}'
        try:
            resp = _urllib_request.urlopen(url, timeout=15)
            data = json.loads(resp.read().decode())
            videos = data.get('videos', []) or []
            return {
                'query': query,
                'count': len(videos),
                'videos': [
                    {
                        'id': v.get('id'),
                        'title': (v.get('title') or '')[:200],
                        'thumbnail': v.get('thumbnail'),
                        'duration': v.get('duration'),
                    }
                    for v in videos[:int(limit)]
                ],
            }
        except Exception as e:
            return {"error": f"YouTube search failed: {str(e)[:200]}"}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_recommend_tv_content(senior_id, time_aware=True):
    """Time + Ψ(t) aware TV/video content recommendations for senior.

    Morning → ČT24 zprávy, ranní pohádky
    Afternoon → ČT2 dokumenty, koncerty
    Evening → klidnější obsah, klasika
    Crisis → nic, nebo jen tichá hudba
    """
    try:
        # Brain mode
        mode = 'HARMONY'
        if _DB:
            try:
                with db_context() as db:
                    row = db.execute("""
                        SELECT mode FROM brain_states WHERE user_id = ?
                        ORDER BY created_at DESC LIMIT 1
                    """, (str(senior_id),)).fetchone()
                if row:
                    vals = _row_to_list(row)
                    mode = vals[0] or 'HARMONY'
            except Exception:
                pass

        if mode == 'CRISIS':
            return {
                'recommendation': None,
                'reason': 'CRISIS — žádné video doporučení, jen tichá ambient hudba',
                'fallback': _MUSIC_STATIONS['relax'][0],
            }

        hour = datetime.now().hour
        recs = []
        if time_aware:
            if 6 <= hour < 10:
                recs = [
                    {'category': 'zprávy', 'query': 'ČT24 ranní zprávy česky',
                     'reason': 'Ráno – aktualní zpravodajství'},
                    {'category': 'rádio', 'station_id': 'radiozurnal',
                     'reason': 'Ranní rádio'},
                ]
            elif 10 <= hour < 14:
                recs = [
                    {'category': 'dokument', 'query': 'česká příroda dokument',
                     'reason': 'Klidný dopolední dokument'},
                    {'category': 'koncert', 'query': 'česká filharmonie koncert',
                     'reason': 'Klasická hudba'},
                ]
            elif 14 <= hour < 18:
                recs = [
                    {'category': 'zábava', 'query': 'české písničky šedesátá léta',
                     'reason': 'Odpolední nostalgie'},
                    {'category': 'rádio', 'station_id': 'blanik',
                     'reason': 'České hity'},
                ]
            else:  # evening
                recs = [
                    {'category': 'klasika', 'station_id': 'classical',
                     'reason': 'Večerní klasická hudba'},
                    {'category': 'pohádka', 'query': 'česká pohádka klasická',
                     'reason': 'Klidný večer'},
                ]

        return {
            'brain_mode': mode,
            'hour': hour,
            'recommendations': recs[:3],
            '_hint': ('Use youtube_search() for query-type recs, or '
                      'play_music_for_senior() for station_id recs.'),
        }
    except Exception as e:
        return {"error": str(e)[:200]}


# Tool dispatcher
TOOL_HANDLERS = {
    'list_seniors': lambda args: _tool_list_seniors(),
    'get_brain_state': lambda args: _tool_get_brain_state(args['senior_id']),
    'get_vitals': lambda args: _tool_get_vitals(args['senior_id']),
    'get_iot_status': lambda args: _tool_get_iot_status(args['senior_id']),
    'get_recent_chat': lambda args: _tool_get_recent_chat(args['senior_id'], args.get('n', 10)),
    'get_observations': lambda args: _tool_get_observations(args['senior_id'], args.get('days', 7)),
    'send_chat_message': lambda args: _tool_send_chat_message(args['senior_id'], args['text']),
    'send_push': lambda args: _tool_send_push(args['senior_id'], args['title'], args['body']),
    'notify_family': lambda args: _tool_notify_family(args['senior_id'], args['text'], args['urgency']),
    'initiate_call': lambda args: _tool_initiate_call(args['senior_id'], args['reason']),
    'create_observation': lambda args: _tool_create_observation(
        args['senior_id'], args['severity'], args['message']),
    # Math
    'get_anticipation_forecast': lambda args: _tool_get_anticipation_forecast(args['senior_id']),
    'get_circadian_profile': lambda args: _tool_get_circadian_profile(args['senior_id']),
    'get_circadian_triggers': lambda args: _tool_get_circadian_triggers(args['senior_id']),
    'get_behavioral_profile': lambda args: _tool_get_behavioral_profile(args['senior_id']),
    # Philosophy
    'get_radim_philosophy': lambda args: _tool_get_radim_philosophy(args.get('focus')),
    # Brain
    'compute_brain_state': lambda args: _tool_compute_brain_state(
        args['senior_id'], args['C'], args['alpha'],
        args.get('voice_tone', 0.5), args.get('hrv', 0.5), args.get('speech_tempo', 0.5)),
    'compute_empathy': lambda args: _tool_compute_empathy(
        args['voice_tone'], args['hrv'], args['speech_tempo']),
    'get_speech_adaptation': lambda args: _tool_get_speech_adaptation(args['senior_id']),
    # Memory
    'get_full_profile': lambda args: _tool_get_full_profile(args['senior_id']),
    'get_learning_state': lambda args: _tool_get_learning_state(args['senior_id']),
    'update_learning': lambda args: _tool_update_learning(
        args['senior_id'], args['key'], args['value']),
    'update_profile': lambda args: _tool_update_profile(
        args['senior_id'], args['key'], args['value']),
    # TTS
    'get_voice_modes_catalog': lambda args: _tool_get_voice_modes_catalog(),
    'get_voice_memory': lambda args: _tool_get_voice_memory(args['senior_id']),
    'compose_ssml': lambda args: _tool_compose_ssml(
        args['senior_id'], args['text'], args.get('mode')),
    'generate_voice_audio': lambda args: _tool_generate_voice_audio(
        args['senior_id'], args['text'], args.get('mode')),
    'record_voice_feedback': lambda args: _tool_record_voice_feedback(
        args['senior_id'], args['event_type'], args.get('voice_mode')),
    # Agent bus
    'get_agent_inventory': lambda args: _tool_get_agent_inventory(),
    'get_agent_messages': lambda args: _tool_get_agent_messages(
        args['senior_id'], args.get('hours', 24),
        args.get('severity_min', 'info'), args.get('kinds')),
    'check_agent_dedup': lambda args: _tool_check_agent_dedup(
        args['senior_id'], args['topic'],
        args.get('within_minutes', 15), args.get('severity_min', 'warning')),
    'emit_agent_message': lambda args: _tool_emit_agent_message(
        args['senior_id'], args['kind'], args['severity'],
        args['topic'], args['message'], args.get('correlates_with')),
    # Beat / RTCF
    'get_beat_state': lambda args: _tool_get_beat_state(args['senior_id']),
    'compute_custom_beat': lambda args: _tool_compute_custom_beat(
        args.get('risk', 0), args.get('pain', 0), args.get('intuition', 0),
        args.get('load', 0), args.get('recovery', 0), args.get('threat', 0),
        args.get('trust', 0.7), args.get('safety', 1.0)),
    # Komunikace
    'get_communication_needs_catalog': lambda args: _tool_get_communication_needs_catalog(),
    'get_communication_strategy': lambda args: _tool_get_communication_strategy(args['needs_key']),
    'detect_topic_mood': lambda args: _tool_detect_topic_mood(args['text']),
    'get_senior_communication_profile': lambda args: _tool_get_senior_communication_profile(args['senior_id']),
    'send_whatsapp': lambda args: _tool_send_whatsapp(args['senior_id'], args['text']),
    'send_sms_to_senior': lambda args: _tool_send_sms_to_senior(args['senior_id'], args['text']),
    # Home Assistant
    'ha_status': lambda args: _tool_ha_status(),
    'ha_get_sensors': lambda args: _tool_ha_get_sensors(),
    'ha_home_status': lambda args: _tool_ha_home_status(),
    'ha_get_device_state': lambda args: _tool_ha_get_device_state(args['entity_id']),
    'ha_get_devices_by_room': lambda args: _tool_ha_get_devices_by_room(),
    'ha_execute_action': lambda args: _tool_ha_execute_action(
        args['action'], args.get('entity_id'), args.get('params'),
        args.get('crisis_override', False), args.get('reason')),
    'ha_circadian_triggers': lambda args: _tool_ha_circadian_triggers(args['senior_id']),
    'ha_behavioral_changes': lambda args: _tool_ha_behavioral_changes(args['senior_id']),
    # Wake word + voice runtime
    'get_voice_session_state': lambda args: _tool_get_voice_session_state(args['senior_id']),
    'get_voice_conversation_history': lambda args: _tool_get_voice_conversation_history(
        args['senior_id'], args.get('limit', 10)),
    'speak_to_senior': lambda args: _tool_speak_to_senior(
        args['senior_id'], args['message'],
        args.get('mode'), args.get('force_interrupt', False)),
    'get_active_voice_seniors': lambda args: _tool_get_active_voice_seniors(),
    # Self-diagnostic
    'detect_app_errors': lambda args: _tool_detect_app_errors(args.get('hours', 24)),
    'analyze_self_health': lambda args: _tool_analyze_self_health(),
    'read_source_file': lambda args: _tool_read_source_file(
        args['file_path'], args.get('start_line', 1), args.get('num_lines', 80)),
    'run_diagnostic_test': lambda args: _tool_run_diagnostic_test(args['test_name']),
    'report_bug': lambda args: _tool_report_bug(
        args['category'], args['severity'], args['file'], args['description'],
        args.get('suggested_fix'), args.get('reproducer')),
    # STT
    'stt_status': lambda args: _tool_stt_status(),
    'stt_normalize_text': lambda args: _tool_stt_normalize_text(args['text']),
    'stt_detect_safety': lambda args: _tool_stt_detect_safety(args['text']),
    'stt_classify_priority': lambda args: _tool_stt_classify_priority(
        args['text'], args.get('confidence', 1.0)),
    'stt_correct_text': lambda args: _tool_stt_correct_text(
        args['text'], args.get('senior_id')),
    'stt_should_retry': lambda args: _tool_stt_should_retry(args['text'], args['confidence']),
    'stt_gather_params': lambda args: _tool_stt_gather_params(args['senior_id']),
    'stt_build_hints': lambda args: _tool_stt_build_hints(args['senior_id']),
    # Calendar
    'get_upcoming_events': lambda args: _tool_get_upcoming_events(
        args['senior_id'], args.get('hours', 24)),
    'find_free_slots': lambda args: _tool_find_free_slots(
        args['senior_id'], args.get('days', 7),
        args.get('start_hour', 8), args.get('end_hour', 18)),
    'add_calendar_reminder': lambda args: _tool_add_calendar_reminder(
        args['senior_id'], args['event_id']),
    'parse_event_text': lambda args: _tool_parse_event_text(args['text']),
    # Email
    'get_unread_emails': lambda args: _tool_get_unread_emails(
        args['senior_id'], args.get('limit', 20)),
    'scan_email_risk': lambda args: _tool_scan_email_risk(
        args['subject'], args['body'], args['from_email'],
        args.get('from_name'), args.get('use_ai', False)),
    'flag_email_to_family': lambda args: _tool_flag_email_to_family(
        args['senior_id'], args['subject'], args['body_snippet'],
        args['from_email'], args.get('from_name'), args.get('reasons')),
    'send_email_to_family': lambda args: _tool_send_email_to_family(
        args['senior_id'], args['subject'], args['body'],
        args.get('urgency', 'normal')),
    # Caregiver / care plan
    'get_senior_caregivers': lambda args: _tool_get_senior_caregivers(args['senior_id']),
    'get_care_plan': lambda args: _tool_get_care_plan(
        args['senior_id'], args.get('summary', False)),
    'get_medication_schedule': lambda args: _tool_get_medication_schedule(args['senior_id']),
    'add_care_plan_goal': lambda args: _tool_add_care_plan_goal(
        args['senior_id'], args['text'], args.get('priority', 'medium')),
    'add_care_plan_risk': lambda args: _tool_add_care_plan_risk(
        args['senior_id'], args['text'],
        args.get('severity', 'medium'), args.get('mitigation')),
    'send_caregiver_notification': lambda args: _tool_send_caregiver_notification(
        args['senior_id'], args['title'], args['body'],
        args.get('severity', 'info'), args.get('ntype', 'claude_observation')),
    'get_relationship': lambda args: _tool_get_relationship(args['senior_id']),
    'caregiver_whisper': lambda args: _tool_caregiver_whisper(
        args['senior_id'], args['text'], args.get('priority', 'normal')),
    # Education
    'get_education_courses': lambda args: _tool_get_education_courses(args.get('filter_type')),
    'get_lesson_progress': lambda args: _tool_get_lesson_progress(args['senior_id']),
    'get_recommended_lessons': lambda args: _tool_get_recommended_lessons(
        args['senior_id'], args.get('limit', 5)),
    'get_lesson_content': lambda args: _tool_get_lesson_content(
        args['course_id'], args['module_id']),
    'mark_lesson_complete': lambda args: _tool_mark_lesson_complete(
        args['senior_id'], args['course_id'], args['module_id'], args.get('score')),
    'get_assignments': lambda args: _tool_get_assignments(
        args['senior_id'], args.get('status', 'active')),
    'recommend_scenario': lambda args: _tool_recommend_scenario(
        args['senior_id'], args['situation_keywords']),
    # TV + Music
    'get_music_stations': lambda args: _tool_get_music_stations(args.get('group')),
    'recommend_music': lambda args: _tool_recommend_music(
        args['senior_id'], args.get('mood_override'),
        args.get('time_aware', True)),
    'play_music_for_senior': lambda args: _tool_play_music_for_senior(
        args['senior_id'], args['station_id']),
    'pause_music_for_senior': lambda args: _tool_pause_music_for_senior(args['senior_id']),
    'youtube_search': lambda args: _tool_youtube_search(
        args['query'], args.get('limit', 6)),
    'recommend_tv_content': lambda args: _tool_recommend_tv_content(
        args['senior_id'], args.get('time_aware', True)),
}


# ═══════════════════════════════════════════════════════════════════════
# COST TRACKING & BUDGET GUARDRAIL
# ═══════════════════════════════════════════════════════════════════════

def _ensure_telemetry_table():
    if not _DB:
        return
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS claude_agent_telemetry (
                        id SERIAL PRIMARY KEY,
                        run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
                        tool_calls INTEGER NOT NULL DEFAULT 0,
                        seniors_evaluated INTEGER NOT NULL DEFAULT 0,
                        actions_taken INTEGER NOT NULL DEFAULT 0,
                        duration_seconds NUMERIC(10,2),
                        summary TEXT,
                        error TEXT
                    )
                """)
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS claude_agent_telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd REAL NOT NULL DEFAULT 0,
                        tool_calls INTEGER NOT NULL DEFAULT 0,
                        seniors_evaluated INTEGER NOT NULL DEFAULT 0,
                        actions_taken INTEGER NOT NULL DEFAULT 0,
                        duration_seconds REAL,
                        summary TEXT,
                        error TEXT
                    )
                """)
    except Exception as e:
        logger.warning(f"telemetry table init: {e}")


def _today_cost_usd():
    if not _DB:
        return 0.0
    try:
        with db_context() as db:
            interval = "CURRENT_DATE" if is_postgres() else "date('now')"
            row = db.execute(f"""
                SELECT COALESCE(SUM(cost_usd), 0)
                FROM claude_agent_telemetry
                WHERE DATE(run_at) = {interval}
            """).fetchone()
            return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def _record_run(input_tokens, output_tokens, tool_calls, seniors, actions, duration,
                summary, error=None, cache_write=0, cache_read=0):
    if not _DB:
        return
    cost = (input_tokens / 1_000_000 * PRICE_INPUT_PER_M +
            output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M +
            cache_write / 1_000_000 * PRICE_CACHE_WRITE_PER_M +
            cache_read / 1_000_000 * PRICE_CACHE_READ_PER_M)
    try:
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'claude_agent_telemetry',
                      ['input_tokens', 'output_tokens', 'cost_usd', 'tool_calls',
                       'seniors_evaluated', 'actions_taken', 'duration_seconds', 'summary', 'error'],
                      [input_tokens, output_tokens, cost, tool_calls,
                       seniors, actions, duration, summary, error])
    except Exception as e:
        logger.warning(f"record_run: {e}")
    return cost


# ═══════════════════════════════════════════════════════════════════════
# AGENT LOOP
# ═══════════════════════════════════════════════════════════════════════

WRITE_TOOLS = {'send_chat_message', 'send_push', 'notify_family', 'initiate_call',
               'update_learning', 'update_profile',
               'record_voice_feedback', 'generate_voice_audio',
               'emit_agent_message',
               'send_whatsapp', 'send_sms_to_senior',
               'ha_execute_action',
               'speak_to_senior',
               'report_bug',
               'add_calendar_reminder', 'flag_email_to_family',
               'send_email_to_family',
               'add_care_plan_goal', 'add_care_plan_risk',
               'send_caregiver_notification', 'caregiver_whisper',
               'mark_lesson_complete',
               'play_music_for_senior', 'pause_music_for_senior'}


# Per-senior event-trigger cooldown (anti-thrashing). Independent of
# action cooldown — this is "don't re-run the agent on the same senior
# for the same triggering event within X minutes".
EVENT_TRIGGER_COOLDOWN_MIN = int(os.getenv('CLAUDE_AGENT_EVENT_COOLDOWN_MIN', '10'))
_event_trigger_history = {}  # senior_id → last trigger timestamp


def _can_trigger_for_senior(senior_id):
    """Returns True if event trigger is allowed for this senior right now."""
    last = _event_trigger_history.get(str(senior_id))
    if not last:
        return True
    elapsed_min = (time.time() - last) / 60
    return elapsed_min >= EVENT_TRIGGER_COOLDOWN_MIN


def _mark_trigger(senior_id):
    _event_trigger_history[str(senior_id)] = time.time()


def run_claude_agent(app=None, trigger='cron', force=False,
                     focus_senior_id=None, event_context=None):
    """
    Main entry point. Run autonomous Claude agent for one cycle.

    Args:
        app: Flask app for context (optional)
        trigger: 'cron' / 'manual' / 'event' / 'agent_loop' (audit)
        force: bypass daily budget check (manual override)
        focus_senior_id: if provided, agent is told to focus deeply on
                        ONE senior (event-driven mode, faster + cheaper).
        event_context: dict with details about the triggering event
                      (severity, observation_type, message).

    Returns:
        dict with summary and metrics
    """
    if not _CLAUDE_AVAILABLE:
        return {'error': 'anthropic SDK not available'}
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {'error': 'ANTHROPIC_API_KEY not set'}

    _ensure_telemetry_table()

    # Event-trigger cooldown (per-senior anti-thrashing)
    if trigger == 'agent_loop' and focus_senior_id:
        if not _can_trigger_for_senior(focus_senior_id) and not force:
            logger.info(f"Claude agent: event trigger cooldown active for senior {focus_senior_id}")
            return {'skipped': 'event_cooldown',
                    'senior_id': focus_senior_id,
                    'cooldown_min': EVENT_TRIGGER_COOLDOWN_MIN}
        _mark_trigger(focus_senior_id)

    # Budget check
    if not force:
        spent_today = _today_cost_usd()
        if spent_today >= DAILY_BUDGET_USD:
            logger.warning(f"Claude agent: daily budget ${DAILY_BUDGET_USD} exceeded (${spent_today:.4f}) — skipping")
            return {'skipped': 'daily_budget_exceeded',
                    'spent_today': spent_today, 'budget': DAILY_BUDGET_USD}

    started = time.time()
    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    # Reset TTS generation counter for this run
    _tts_generation_counter['count'] = 0

    # Customize initial message based on trigger
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    if focus_senior_id:
        # Focused/event-driven mode — deep dive on one senior
        ev = event_context or {}
        ev_summary = ''
        if ev:
            ev_summary = (
                f"\n\n**TRIGGERING EVENT:**\n"
                f"- Severity: {ev.get('severity', 'unknown')}\n"
                f"- Type: {ev.get('observation_type', 'unknown')}\n"
                f"- Source: {ev.get('source', 'agent_loop')}\n"
                f"- Message: {(ev.get('message') or '')[:300]}\n"
            )
        initial_text = (
            f"Je {timestamp} (event-driven trigger: {trigger}).\n"
            f"**FOCUS na seniora #{focus_senior_id}** — rule-based agent_loop právě "
            f"detekoval situaci, která vyžaduje hlubší analýzu.{ev_summary}\n\n"
            "Postup:\n"
            "1. `get_full_profile({focus})` + `get_brain_state({focus})` + "
            "`get_anticipation_forecast({focus})` — kontext\n"
            "2. `get_recent_chat({focus})` + `get_observations({focus}, days=3)` — "
            "co se dělo\n"
            "3. `get_agent_messages({focus})` — co viděli ostatní agenti\n"
            "4. `get_voice_session_state({focus})` — je teď v hovoru?\n"
            "5. Rozhodni o akci (chat / push / family / call) — eskaluj jen pokud forecast "
            "nebo HA potvrzuje skutečnou krizi. Není-li, vytvoř INFO observation s důvodem "
            "neeskalace.\n"
            "6. `create_observation` na konci s tvým rozhodnutím.\n\n"
            "**Buď rychlý** — toto je event-driven, ne periodic sweep. "
            "Nezdržuj se s ostatními seniory."
        ).format(focus=focus_senior_id)
        messages = [{"role": "user", "content": initial_text}]
    else:
        # Periodic sweep — broad scan
        messages = [
            {"role": "user", "content":
             f"Je {timestamp} ({trigger}). "
             "Zkontroluj aktivní seniory, posuď jejich stav a rozhodni o akcích. "
             "Začni `list_seniors`. Na konci VŽDY volej `create_observation` se shrnutím."}
        ]

    total_input = 0
    total_output = 0
    total_cache_write = 0
    total_cache_read = 0
    tool_calls_made = 0
    actions_taken = 0
    seniors_seen = set()
    final_text = ""
    error = None

    try:
        if app:
            ctx = app.app_context()
            ctx.__enter__()

        for iteration in range(MAX_TOOL_CALLS_PER_RUN):
            # System prompt + tools cached for cheaper subsequent iterations
            # (90% input discount on cache hits, 5min TTL)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS_PER_RESPONSE,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=TOOLS,
                messages=messages,
            )

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens
            total_cache_write += getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
            total_cache_read += getattr(response.usage, 'cache_read_input_tokens', 0) or 0

            # Collect text + tool uses from response
            assistant_content = []
            tool_uses = []
            for block in response.content:
                assistant_content.append(block)
                if block.type == 'tool_use':
                    tool_uses.append(block)
                elif block.type == 'text':
                    final_text = block.text  # last text wins as final

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == 'end_turn' or not tool_uses:
                break

            # Execute tools
            tool_results = []
            for tu in tool_uses:
                tool_calls_made += 1
                handler = TOOL_HANDLERS.get(tu.name)
                if not handler:
                    result = {"error": f"unknown tool: {tu.name}"}
                else:
                    try:
                        result = handler(tu.input)
                    except Exception as e:
                        result = {"error": f"tool exec: {str(e)[:200]}"}
                        logger.exception(f"Tool {tu.name} failed")

                if tu.name in WRITE_TOOLS and not result.get('error') and not result.get('skipped'):
                    actions_taken += 1
                if 'senior_id' in (tu.input or {}):
                    seniors_seen.add(tu.input['senior_id'])

                logger.info(f"[claude_agent] tool={tu.name} args={json.dumps(tu.input)[:120]} "
                            f"result={json.dumps(result)[:120]}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                })

            messages.append({"role": "user", "content": tool_results})

        if app:
            ctx.__exit__(None, None, None)

    except Exception as e:
        error = str(e)[:500]
        logger.exception("Claude agent run failed")

    duration = time.time() - started
    cost = _record_run(total_input, total_output, tool_calls_made,
                       len(seniors_seen), actions_taken, duration,
                       final_text[:2000], error,
                       cache_write=total_cache_write, cache_read=total_cache_read)

    summary = {
        'trigger': trigger,
        'focus_senior_id': str(focus_senior_id) if focus_senior_id else None,
        'duration_s': round(duration, 2),
        'iterations': iteration + 1 if 'iteration' in dir() else 0,
        'tool_calls': tool_calls_made,
        'seniors_evaluated': len(seniors_seen),
        'actions_taken': actions_taken,
        'input_tokens': total_input,
        'output_tokens': total_output,
        'cache_write_tokens': total_cache_write,
        'cache_read_tokens': total_cache_read,
        'cost_usd': round(cost or 0, 4),
        'final_text': final_text[:500],
        'error': error,
    }
    logger.info(f"[claude_agent] DONE: {json.dumps(summary, ensure_ascii=False)[:600]}")
    return summary
