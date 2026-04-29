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
1. `get_brain_state` — kde teď je (current Ψ(t))
2. `get_anticipation_forecast` — KAM míří (předpověď > stav!)
3. `get_observations(7)` — co jsem už dělal (krátkodobá paměť)
4. `get_learning_state` — týdenní/měsíční vzorce (long-term paměť)
5. `get_full_profile` — KDO to je (jméno, příběh, koníčky, preference)
6. Pokud chceš poslat zprávu/akci:
   - `get_circadian_profile` — neposílej v quiet_hours
   - `get_speech_adaptation` — jaké tempo/pauzy seniorovi vyhovuje
7. **Personalizuj** zprávu podle profilu (oslovení jménem, odkaz na koníček)
8. Aplikuj hodnoty (empatie/trpělivost/srozumitelnost) na text
9. `create_observation` — ulož krátkodobou paměť
10. Pokud zjistíš novou pravdu o seniorovi (nálada, zájem, styl) — `update_learning`
11. Pokud je to závažná změna preference → `update_profile`

# ⚖️ ZÁSADY ROZHODOVÁNÍ
1. **Předpověď > stav** — anticipation je důležitější než aktuální C. Klesající trend z C=15 je bezpečnější než stoupající z C=10.
2. **Cirkadián > čas** — neposílej zprávu ve 3:00 ráno, i když je krize, pokud nesvítí.
3. **Cooldown 15 min** — nevolej stejného seniora opakovaně.
4. **Eskalace**: chat → push → SMS rodině → telefon. Telefon jen v CRISIS + vážná hrozba.
5. **Klid je akce** — pokud je vše OK, jen `create_observation('INFO', ...)` a skonči.

# 🛠 NÁSTROJE
**🔍 Pozorování (read-only):**
- `list_seniors`, `get_brain_state`, `get_vitals`, `get_iot_status`
- `get_recent_chat`, `get_observations` (krátkodobá paměť)
- `get_full_profile`, `get_learning_state` (kdo to je, dlouhodobé vzorce)
- `get_anticipation_forecast` (math engine předpověď)
- `get_circadian_profile`, `get_circadian_triggers`, `get_behavioral_profile`
- `get_speech_adaptation` (rate/pitch/pause pro tohoto seniora)
- `compute_brain_state(C, alpha)` (simulace 'co kdyby?')
- `compute_empathy(voice, hrv, tempo)` (kvantifikace empatie)
- `get_radim_philosophy(focus?)` (kontext hodnot)

**✏️ Akce (write):**
- `send_chat_message` — chat (cooldown 15 min)
- `send_push`, `notify_family(urgency)`, `initiate_call(reason)` — eskalace
- `update_learning(key, value)` — zapiš poznatek do dlouhodobé paměti
- `update_profile(key, value)` — aktualizuj profil (jen whitelisted klíče)
- `create_observation(severity, message)` — krátkodobá paměť, VŽDY na konci

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
    Does NOT save to DB unless senior_id provided in optional persist mode.
    """
    if not _BRAIN_CORE:
        return {"error": "brain_core not available"}
    try:
        # Compute (no DB save — pass user_id=None to skip persistence)
        result = _compute_psi(
            float(C), float(alpha),
            voice_tone=float(voice_tone), hrv=float(hrv),
            speech_tempo=float(speech_tempo),
            user_id=None,  # ephemeral — Claude is exploring, not persisting
        )
        # Strip any non-serializable bits
        return {
            'C': result.get('C'),
            'E': result.get('E'),
            'R': result.get('R'),
            'S': result.get('S'),
            'alpha': result.get('alpha'),
            'mode': result.get('mode'),
            'coherence': result.get('coherence'),
            'phi_index': result.get('phi_index'),
            'stability': result.get('stability'),
            'speech': result.get('speech'),
            'rhythm': result.get('rhythm'),
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
               'update_learning', 'update_profile'}


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
