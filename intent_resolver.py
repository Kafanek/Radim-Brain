"""
Intent Resolver v1.1 — Lightweight local NLU for Radim assistant.

Resolves simple intents (time, date, greeting, nameday, etc.) locally
without calling Claude/Gemini API. Saves costs and reduces latency.

Data + patterns in intent_data.py.
"""

import re
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# IMPORTS FROM DATA MODULE (+ re-exports for backward compat)
# ============================================================================

from intent_data import (
    # Word sets
    CRISIS_WORDS as _CRISIS_WORDS_NEW,
    STRESS_WORDS as _STRESS_WORDS_NEW,
    CALM_WORDS as _CALM_WORDS_NEW,
    # Namedays
    CZ_NAMEDAYS,
    # Intent patterns
    INTENTS as _INTENTS,
    # Response templates
    CZ_DAYS as _CZ_DAYS,
    CZ_MONTHS as _CZ_MONTHS,
    GREETINGS as _GREETINGS,
    GOODBYES as _GOODBYES,
    THANKS_REPLIES as _THANKS_REPLIES,
    CZ_JOKES as _CZ_JOKES,
    COMPLIMENT_REPLIES as _COMPLIMENT_REPLIES,
    HOW_ARE_YOU_REPLIES as _HOW_ARE_YOU_REPLIES,
    IDENTITY_REPLY as _IDENTITY_REPLY,
)

# Backward compat: expose with underscore prefix (used by kal_routes etc.)
_CRISIS_WORDS = _CRISIS_WORDS_NEW
_STRESS_WORDS = _STRESS_WORDS_NEW
_CALM_WORDS = _CALM_WORDS_NEW


# ============================================================================
# QUICK C/ALPHA ESTIMATION
# ============================================================================

def _word_in_text(word, text):
    """Check if word appears in text. For numeric words (155, 112),
    use word-boundary matching to avoid false positives."""
    if word.isdigit():
        return bool(re.search(r'\b' + re.escape(word) + r'\b', text))
    return word in text


def quick_estimate_from_text(text):
    """Quick C/alpha estimation from text for streaming STT -> Brain.
    Returns (C_estimate, alpha_estimate).
    """
    if not text:
        return (5.0, 0.2)

    text_lower = text.lower()
    crisis_hits = sum(1 for w in _CRISIS_WORDS if _word_in_text(w, text_lower))
    stress_hits = sum(1 for w in _STRESS_WORDS if _word_in_text(w, text_lower))
    calm_hits = sum(1 for w in _CALM_WORDS if _word_in_text(w, text_lower))

    C = 5.0
    C += crisis_hits * 12.0
    C += stress_hits * 4.0
    C -= calm_hits * 2.0
    C = max(0.0, min(50.0, C))

    alpha = 0.2
    alpha += crisis_hits * 0.3
    alpha += stress_hits * 0.15
    alpha -= calm_hits * 0.05
    alpha = max(0.0, min(1.0, alpha))

    return (C, alpha)


# ============================================================================
# RESPONSE HANDLERS
# ============================================================================

def _handle_time(**kwargs):
    now = datetime.now()
    h, m = now.hour, now.minute
    return f"Je {h}:{m:02d}."


def _handle_date(**kwargs):
    now = datetime.now()
    day_name = _CZ_DAYS[now.weekday()]
    return f"Dnes je {day_name} {now.day}. {_CZ_MONTHS[now.month - 1]} {now.year}."


def _handle_nameday(**kwargs):
    key = datetime.now().strftime("%m-%d")
    name = CZ_NAMEDAYS.get(key, "neznamy")
    return f"Dnes ma svatek {name}."


def _handle_greeting(**kwargs):
    return random.choice(_GREETINGS)


def _handle_goodbye(**kwargs):
    return random.choice(_GOODBYES)


def _handle_thanks(**kwargs):
    return random.choice(_THANKS_REPLIES)


def _handle_identity(**kwargs):
    return _IDENTITY_REPLY


def _handle_day_of_week(**kwargs):
    now = datetime.now()
    day_name = _CZ_DAYS[now.weekday()]
    return f"Dnes je {day_name}."


def _handle_year(**kwargs):
    return f"Mame rok {datetime.now().year}."


def _handle_joke(**kwargs):
    return random.choice(_CZ_JOKES)


def _handle_compliment(**kwargs):
    return random.choice(_COMPLIMENT_REPLIES)


def _handle_how_are_you(**kwargs):
    return random.choice(_HOW_ARE_YOU_REPLIES)


_HANDLERS = {
    "time": _handle_time,
    "date": _handle_date,
    "nameday": _handle_nameday,
    "greeting": _handle_greeting,
    "goodbye": _handle_goodbye,
    "thanks": _handle_thanks,
    "identity": _handle_identity,
    "day_of_week": _handle_day_of_week,
    "year": _handle_year,
    "joke": _handle_joke,
    "compliment": _handle_compliment,
    "how_are_you": _handle_how_are_you,
}


# ============================================================================
# MAIN RESOLVE FUNCTION
# ============================================================================

def resolve_intent(message, user_id=None, mode="HARMONY"):
    """Resolve intent from user message.

    Returns:
        (response_text, intent_label, metadata)
        - response_text: str if resolved locally, None if should pass to AI
        - intent_label: str (e.g. "time", "greeting", "safety")
        - metadata: dict or None (e.g. {"priority": "high"} for safety)
    """
    if not message or not message.strip():
        return (None, "empty", None)

    text = message.strip()

    for intent in _INTENTS:
        for pattern in intent["_compiled"]:
            if pattern.search(text):
                name = intent["name"]
                handler_key = intent["handler"]

                if handler_key is None:
                    meta = None
                    if name == "safety":
                        meta = {"priority": "high"}
                    logger.info(f"Intent '{name}' detected for user={user_id}, passing to AI")
                    return (None, name, meta)

                handler = _HANDLERS.get(handler_key)
                if handler:
                    try:
                        response = handler(user_id=user_id, mode=mode)
                        logger.info(f"Intent '{name}' resolved locally for user={user_id}")
                        return (response, name, {"source": "local"})
                    except Exception as e:
                        logger.warning(f"Intent handler '{name}' failed: {e}")
                        return (None, name, None)

    return (None, "chat", None)
