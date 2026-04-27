# ============================================
# CLAUDE HELPERS v1.0.0
# ============================================
# Configuration, helper functions, and nameday
# calendar for Claude AI routes.
# Extracted from claude_routes.py for modularity.
# ============================================

import os
import logging
from datetime import datetime
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)

# ============================================================================
# SDK AVAILABILITY
# ============================================================================

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# ============================================================================
# CONFIGURATION
# ============================================================================

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
# Sprint AA hotfix: 'claude-sonnet-4-6-20250514' was a typo (extra "-6") and
# returns 404 from Anthropic API on every News fetch. Correct name is
# 'claude-sonnet-4-20250514'. Override via CLAUDE_MODEL env var on Heroku
# if a newer model becomes available.
CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# ============================================================================
# OPTIONAL IMPORTS — feature flags
# ============================================================================

# Intent Resolver (v272 — local NLU)
try:
    from intent_resolver import resolve_intent as cl_resolve_intent
    CL_INTENT_RESOLVER = True
except ImportError:
    CL_INTENT_RESOLVER = False
    cl_resolve_intent = None

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as cl_predict_C, calculate_emotions as cl_ant_emotions,
        calculate_speech_params as cl_ant_speech, classify_state as cl_classify,
        C_HARMONY as CL_C_HARMONY, C_ALERT as CL_C_ALERT, C_MAX as CL_C_MAX
    )
    CL_ANT_AVAILABLE = True
except ImportError:
    CL_ANT_AVAILABLE = False
    cl_predict_C = cl_ant_emotions = cl_ant_speech = cl_classify = None
    CL_C_HARMONY = CL_C_ALERT = CL_C_MAX = None

# Memory persistence
try:
    from memory_routes import (
        record_interaction, get_conversation_messages,
        get_user_context, get_personalized_system_prompt,
        detect_mood as cl_detect_mood
    )
    CL_MEMORY_AVAILABLE = True
except ImportError:
    CL_MEMORY_AVAILABLE = False
    record_interaction = get_conversation_messages = None
    get_user_context = get_personalized_system_prompt = None
    cl_detect_mood = None

# Text Rhythm Engine
try:
    from text_rhythm import (
        estimate_C_alpha_from_text as cl_tr_estimate,
        calculate_text_params as cl_tr_calc,
        build_anticipation_prompt as cl_tr_prompt,
        get_anticipation_metadata as cl_tr_meta,
        get_adjusted_generation_config as cl_tr_gen_config
    )
    CL_TEXT_RHYTHM = True
except ImportError:
    CL_TEXT_RHYTHM = False
    cl_tr_estimate = cl_tr_calc = cl_tr_prompt = cl_tr_meta = cl_tr_gen_config = None

# DB access for memory notes
try:
    from database import db_context  # noqa: F401
    CL_DB_AVAILABLE = True
except ImportError:
    CL_DB_AVAILABLE = False

# Brain Engine integration
try:
    from radim_brain_routes import (
        compute_psi_state as cl_brain_psi,
        derive_text_empathy_proxies as cl_brain_proxies,
        decision_model as cl_brain_decision
    )
    CL_BRAIN_AVAILABLE = True
except ImportError:
    CL_BRAIN_AVAILABLE = False
    cl_brain_psi = cl_brain_proxies = cl_brain_decision = None

# ============================================================================
# NAMEDAY CALENDAR
# ============================================================================

NAMEDAY_CALENDAR = {
    1: {1: 'Novy rok', 2: 'Karina', 3: 'Radmila', 4: 'Diana', 5: 'Dalimil', 6: 'Tri kralove', 7: 'Vilma', 8: 'Cestmir', 9: 'Vladan', 10: 'Bretislav', 11: 'Bohdana', 12: 'Pravoslav', 13: 'Edita', 14: 'Radovan', 15: 'Alice', 16: 'Ctirad', 17: 'Drahoslav', 18: 'Vladislav', 19: 'Doubravka', 20: 'Ilona', 21: 'Bela', 22: 'Slavomir', 23: 'Zdenek', 24: 'Milena', 25: 'Milos', 26: 'Zora', 27: 'Ingrid', 28: 'Otylie', 29: 'Zdislava', 30: 'Robin', 31: 'Marika'},
    2: {1: 'Hynek', 2: 'Nela', 3: 'Blazej', 4: 'Jarmila', 5: 'Dobromila', 6: 'Vanda', 7: 'Veronika', 8: 'Milada', 9: 'Apolena', 10: 'Mojmir', 11: 'Bozena', 12: 'Slavena', 13: 'Venceslav', 14: 'Valentyn', 15: 'Jirina', 16: 'Ljuba', 17: 'Miloslava', 18: 'Gizela', 19: 'Patrik', 20: 'Oldrich', 21: 'Lenka', 22: 'Petr', 23: 'Svatopluk', 24: 'Matej', 25: 'Liliana', 26: 'Dorota', 27: 'Alexandr', 28: 'Lumir', 29: 'Horymir'},
    3: {1: 'Bedrich', 2: 'Anezka', 3: 'Kamil', 4: 'Stela', 5: 'Kazimir', 6: 'Miroslav', 7: 'Tomas', 8: 'Gabriela', 9: 'Frantiska', 10: 'Viktorie', 11: 'Andela', 12: 'Rehor', 13: 'Ruzena', 14: 'Rut', 15: 'Ida', 16: 'Elena', 17: 'Vlastimil', 18: 'Eduard', 19: 'Josef', 20: 'Svetlana', 21: 'Radek', 22: 'Leona', 23: 'Ivona', 24: 'Gabriel', 25: 'Marian', 26: 'Emanuel', 27: 'Dita', 28: 'Sona', 29: 'Tatana', 30: 'Arnost', 31: 'Kvido'},
    4: {1: 'Hugo', 2: 'Erika', 3: 'Richard', 4: 'Ivana', 5: 'Miroslava', 6: 'Vendula', 7: 'Herman', 8: 'Ema', 9: 'Dusan', 10: 'Darja', 11: 'Izabela', 12: 'Julius', 13: 'Ales', 14: 'Vincenc', 15: 'Anastazie', 16: 'Irena', 17: 'Rudolf', 18: 'Valerie', 19: 'Rostislav', 20: 'Marcela', 21: 'Alexandra', 22: 'Evzenie', 23: 'Vojtech', 24: 'Jiri', 25: 'Marek', 26: 'Oto', 27: 'Jaroslav', 28: 'Vlastislav', 29: 'Robert', 30: 'Blahoslav'},
    5: {1: 'Svatek prace', 2: 'Zikmund', 3: 'Alexej', 4: 'Kvetoslav', 5: 'Klaudie', 6: 'Radoslav', 7: 'Stanislav', 8: 'Den vitezstvi', 9: 'Ctibor', 10: 'Blazena', 11: 'Svatava', 12: 'Pankrac', 13: 'Servac', 14: 'Bonifac', 15: 'Zofie', 16: 'Premysl', 17: 'Aneta', 18: 'Natasa', 19: 'Ivo', 20: 'Zbysek', 21: 'Monika', 22: 'Emil', 23: 'Vladimir', 24: 'Jana', 25: 'Viola', 26: 'Filip', 27: 'Valdemar', 28: 'Vilem', 29: 'Maxim', 30: 'Ferdinand', 31: 'Kamila'},
    6: {1: 'Laura', 2: 'Jarmil', 3: 'Tamara', 4: 'Dalibor', 5: 'Dobroslav', 6: 'Norbert', 7: 'Iveta', 8: 'Medard', 9: 'Stanislava', 10: 'Gita', 11: 'Bruno', 12: 'Antonie', 13: 'Antonin', 14: 'Roland', 15: 'Vit', 16: 'Zbynek', 17: 'Adolf', 18: 'Milan', 19: 'Leos', 20: 'Kveta', 21: 'Alois', 22: 'Pavla', 23: 'Zdenka', 24: 'Jan', 25: 'Ivan', 26: 'Adriana', 27: 'Ladislav', 28: 'Lubomir', 29: 'Petr a Pavel', 30: 'Sarka'},
    7: {1: 'Jaroslava', 2: 'Patricie', 3: 'Radomir', 4: 'Prokop', 5: 'Cyril a Metodej', 6: 'Jan Hus', 7: 'Bohuslava', 8: 'Nora', 9: 'Drahoslava', 10: 'Libuse', 11: 'Olga', 12: 'Borek', 13: 'Marketa', 14: 'Karolina', 15: 'Jindrich', 16: 'Lubos', 17: 'Martina', 18: 'Drahomira', 19: 'Cenek', 20: 'Ilja', 21: 'Vitezslav', 22: 'Magdalena', 23: 'Libor', 24: 'Kristyna', 25: 'Jakub', 26: 'Anna', 27: 'Veroslav', 28: 'Viktor', 29: 'Marta', 30: 'Borivoj', 31: 'Ignac'},
    8: {1: 'Oskar', 2: 'Gustav', 3: 'Miluse', 4: 'Dominik', 5: 'Kristian', 6: 'Oldriska', 7: 'Lada', 8: 'Sobeslav', 9: 'Roman', 10: 'Vavrinec', 11: 'Zuzana', 12: 'Klara', 13: 'Alena', 14: 'Alan', 15: 'Hana', 16: 'Jachym', 17: 'Petra', 18: 'Helena', 19: 'Ludvik', 20: 'Bernard', 21: 'Johana', 22: 'Bohuslav', 23: 'Sandra', 24: 'Bartolomej', 25: 'Radim', 26: 'Ludek', 27: 'Otakar', 28: 'Augustyn', 29: 'Evelina', 30: 'Vladena', 31: 'Pavlina'},
    9: {1: 'Linda', 2: 'Adela', 3: 'Bronislav', 4: 'Jindriska', 5: 'Boris', 6: 'Boleslav', 7: 'Regina', 8: 'Mariana', 9: 'Daniela', 10: 'Irma', 11: 'Denisa', 12: 'Marie', 13: 'Lubor', 14: 'Radka', 15: 'Jolana', 16: 'Ludmila', 17: 'Nadezda', 18: 'Krystof', 19: 'Zita', 20: 'Oleg', 21: 'Matous', 22: 'Darina', 23: 'Berta', 24: 'Jaromir', 25: 'Zlata', 26: 'Andrea', 27: 'Jonas', 28: 'Vaclav', 29: 'Michal', 30: 'Jeronym'},
    10: {1: 'Igor', 2: 'Olivie', 3: 'Bohumil', 4: 'Frantisek', 5: 'Eliska', 6: 'Hanus', 7: 'Justyna', 8: 'Vera', 9: 'Stefan', 10: 'Marina', 11: 'Andrej', 12: 'Marcel', 13: 'Renata', 14: 'Agata', 15: 'Tereza', 16: 'Havel', 17: 'Hedvika', 18: 'Lukas', 19: 'Michaela', 20: 'Vendelin', 21: 'Brigita', 22: 'Sabina', 23: 'Teodor', 24: 'Nina', 25: 'Beata', 26: 'Erik', 27: 'Sarlota', 28: 'Den vzniku CSR', 29: 'Silvie', 30: 'Tadeas', 31: 'Stepanka'},
    11: {1: 'Felix', 2: 'Pamatka zesnulych', 3: 'Hubert', 4: 'Karel', 5: 'Miriam', 6: 'Libena', 7: 'Saskie', 8: 'Bohumir', 9: 'Bohdan', 10: 'Evzen', 11: 'Martin', 12: 'Benedikt', 13: 'Tibor', 14: 'Sava', 15: 'Leopold', 16: 'Otmar', 17: 'Den svobody', 18: 'Romana', 19: 'Alzbeta', 20: 'Nikola', 21: 'Albert', 22: 'Cecilie', 23: 'Klement', 24: 'Emilie', 25: 'Katerina', 26: 'Artur', 27: 'Xenie', 28: 'Rene', 29: 'Zina', 30: 'Ondrej'},
    12: {1: 'Iva', 2: 'Blanka', 3: 'Svatoslav', 4: 'Barbora', 5: 'Jitka', 6: 'Mikulas', 7: 'Ambroz', 8: 'Kvetoslava', 9: 'Vratislav', 10: 'Julie', 11: 'Dana', 12: 'Simona', 13: 'Lucie', 14: 'Lydie', 15: 'Radana', 16: 'Albina', 17: 'Daniel', 18: 'Miloslav', 19: 'Ester', 20: 'Dagmar', 21: 'Natalie', 22: 'Simon', 23: 'Vlasta', 24: 'Stedry den', 25: 'Bozi hod', 26: 'Stepan', 27: 'Zaneta', 28: 'Bohumila', 29: 'Judita', 30: 'David', 31: 'Silvestr'}
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_claude_client():
    """Get Anthropic client with 25s timeout (under Heroku 30s limit)"""
    if not ANTHROPIC_AVAILABLE:
        return None
    if not ANTHROPIC_API_KEY:
        return None
    return Anthropic(api_key=ANTHROPIC_API_KEY, timeout=25.0)


def call_gemini_fallback(prompt, system_prompt="", max_tokens=1024):
    """Gemini fallback when Claude API is unavailable (e.g. credits exhausted).

    Hotfix: timeout 30→22s — Heroku router cuts at 30s, we need buffer for
    response transmission. If Gemini exceeds 22s, caller falls to static
    fallback rather than 503-ing the whole request.
    """
    if not GEMINI_API_KEY:
        return None
    try:
        import requests as req
        parts = [{"text": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt}]
        resp = req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": max_tokens,
                    "topP": 0.9
                }
            },
            timeout=22
        )
        if resp.status_code == 200:
            data = resp.json()
            if 'candidates' in data and data['candidates']:
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
        logger.warning(f"Gemini fallback error: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Gemini fallback exception: {e}")
        return None


def is_credit_error(error):
    """Check if the error is an Anthropic credit balance error"""
    error_str = str(error).lower()
    return 'credit balance' in error_str or 'billing' in error_str


def get_today_info():
    """Get today's date info — delegates to radim_shared."""
    from radim_shared import build_time_context, get_nameday
    tc = build_time_context()
    return {
        "date": f"{tc['date_str']} {tc['year']}",
        "day_name": tc["day_name"].capitalize(),
        "nameday": tc["nameday"] or "Neznamy",
        "iso_date": datetime.now().strftime("%Y-%m-%d")
    }


def extract_text_from_response(response):
    """Extract text from Claude response"""
    text_parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            text_parts.append(block.text)
    return "\n".join(text_parts)


def get_greeting():
    """Ziskat pozdrav podle denni doby — delegates to radim_shared"""
    from radim_shared import get_greeting as _shared_greeting
    return _shared_greeting(with_emoji=True)


logger.info("✅ Claude Helpers loaded — config, SDK, nameday, helpers")
