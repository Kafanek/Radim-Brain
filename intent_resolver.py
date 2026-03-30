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


def _handle_my_medications(**kwargs):
    """Return senior's medication list from profile."""
    user_id = kwargs.get("user_id")
    message = kwargs.get("message", "").lower()
    if not user_id:
        return None  # pass to AI
    # "zapomněl jsem léky" → let AI handle with empathy
    if any(w in message for w in ["zapomněl", "zapomnel", "nevím", "nevim", "nepamatuj"]):
        return None  # pass to AI for empathetic response
    # v483: "vzal jsem léky" → confirmation, not query — pass to AI for praise
    if any(w in message for w in ["vzal", "vzala", "bral", "brala", "splnil", "splnila"]):
        return None  # pass to AI — it will praise the user
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)
        meds = profile.get("medications_list", [])
        med_times = profile.get("medication_times", {})

        if not meds and not med_times:
            return "Nemám zatím uložené žádné léky. Řekněte mi, jaké léky berete, a zapamatuji si je."

        parts = ["Vaše léky:"]
        if med_times:
            for period, period_meds in med_times.items():
                period_cz = {"rano": "Ráno", "morning": "Ráno", "poledne": "Poledne",
                             "noon": "Poledne", "vecer": "Večer", "evening": "Večer"}.get(period, period)
                if period_meds and isinstance(period_meds, list):
                    parts.append(f"  {period_cz}: {', '.join(period_meds)}")
        elif meds and isinstance(meds, list):
            parts.append(f"  {', '.join(meds)}")

        return "\n".join(parts)
    except Exception:
        return None  # pass to AI


def _handle_weather(**kwargs):
    """Simple weather response — redirect to AI with context."""
    # We can't fetch weather without API key, so we give a helpful response
    # that acknowledges the question and suggests alternatives
    now = datetime.now()
    h = now.hour
    if h < 10:
        time_ctx = "Dobré ráno!"
    elif h < 18:
        time_ctx = ""
    else:
        time_ctx = "Dobrý večer!"

    # Return None to pass to AI — Gemini can answer weather questions
    return None


def _handle_who_am_i(**kwargs):
    """Return senior's profile info."""
    user_id = kwargs.get("user_id")
    if not user_id:
        return None
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)
        name = profile.get("name", "")
        age = profile.get("age_group", "")

        if not name:
            return "Zatím mi neřekl vaše jméno. Jak se jmenujete?"

        parts = [f"Jmenujete se {name}."]
        if age:
            parts.append(f"Věková skupina: {age}.")

        ec = profile.get("emergency_contacts", [])
        if ec and isinstance(ec, list):
            for c in ec[:2]:
                rel = c.get("relation", "kontakt")
                cname = c.get("name", "")
                if cname:
                    parts.append(f"Nouzový kontakt: {cname} ({rel}).")

        return " ".join(parts)
    except Exception:
        return None


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
    "my_medications": _handle_my_medications,
    "weather": _handle_weather,
    "who_am_i": _handle_who_am_i,
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

    # v396: Fuzzy safety check FIRST — catches "pomo", "pomc", "zachrnku" etc.
    # Critical for speech-impaired seniors (dysarthria, aphasia, Parkinson's)
    try:
        from speech_understanding import detect_safety_fuzzy, correct_stt_output, normalize_czech
        safety_match = detect_safety_fuzzy(text)
        if safety_match and safety_match["severity"] == "critical":
            logger.info(f"FUZZY SAFETY: '{safety_match['input']}' → '{safety_match['word']}' "
                        f"(dist={safety_match['distance']}) for user={user_id}")
            return (None, "safety", {"priority": "high", "fuzzy_match": safety_match})
        # v397: Apply STT correction to text before regex matching
        text, _ = correct_stt_output(text)
    except ImportError:
        pass

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
                        response = handler(user_id=user_id, mode=mode, message=message)
                        if response is not None:
                            logger.info(f"Intent '{name}' resolved locally for user={user_id}")
                            return (response, name, {"source": "local"})
                        else:
                            # v407: Handler returned None → pass to AI (e.g. no profile data)
                            logger.info(f"Intent '{name}' detected but handler returned None, passing to AI")
                            return (None, name, None)
                    except Exception as e:
                        logger.warning(f"Intent handler '{name}' failed: {e}")
                        return (None, name, None)

    return (None, "chat", None)
