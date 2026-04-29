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
               'send_whatsapp', 'send_sms_to_senior'}


def run_claude_agent(app=None, trigger='cron', force=False):
    """
    Main entry point. Run autonomous Claude agent for one cycle.

    Args:
        app: Flask app for context (optional)
        trigger: 'cron' / 'manual' / 'event' (audit)
        force: bypass daily budget check (manual override)

    Returns:
        dict with summary and metrics
    """
    if not _CLAUDE_AVAILABLE:
        return {'error': 'anthropic SDK not available'}
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {'error': 'ANTHROPIC_API_KEY not set'}

    _ensure_telemetry_table()

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

    messages = [
        {"role": "user", "content":
         f"Je {datetime.now().strftime('%Y-%m-%d %H:%M')} ({trigger}). "
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
