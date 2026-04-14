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
    msg = (kwargs.get('message', '') or '').lower().strip()
    # Mirror senior's greeting style
    if any(w in msg for w in ['ahoj', 'cau', 'čau', 'nazdar', 'zdar']):
        return random.choice(["Ahoj! Jak se máte?", "Ahoj! Rád vás slyším.", "Ahoj! Co je nového?"])
    elif any(w in msg for w in ['dobrý den', 'dobry den', 'zdravím']):
        return random.choice(["Dobrý den! Co pro vás mohu udělat?", "Dobrý den! Jak vám mohu pomoci?", "Dobrý den! Jsem tu pro vás."])
    elif any(w in msg for w in ['dobré ráno', 'dobre rano']):
        return random.choice(["Dobré ráno! Jak jste se vyspal/a?", "Dobré ráno! Přeji vám krásný den."])
    elif any(w in msg for w in ['dobrý večer', 'dobry vecer']):
        return random.choice(["Dobrý večer! Jak se máte?", "Dobrý večer! Už se chystáte ke spánku?"])
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


def _handle_music(**kwargs):
    """Handle music-related commands: play notes, teach song, analyze."""
    message = kwargs.get('message', '')
    user_id = kwargs.get('user_id')
    lower = message.lower()

    try:
        from voice_music import (
            note_to_hz, parse_notation, analyze_melody,
            teach_radim_song, fibonacci_melody, phi_interval
        )

        # "zahraj C D E F G" / "přehraj noty do re mi"
        note_match = re.search(r'(?:zahraj|přehraj|hraj)\s+(?:noty?\s+)?(.+)', lower)
        if note_match:
            notation = note_match.group(1).strip()
            notes = parse_notation(notation)
            if notes and len(notes) >= 2:
                analysis = analyze_melody(notation)
                return (f"🎼 Slyším {len(notes)} not! Rozsah {analysis.get('range_cents', 0)} centů "
                        f"({analysis.get('range_octaves', 0)} oktáv). "
                        f"Fibonacci intervaly: {analysis.get('fibonacci_intervals', '?')}. "
                        f"Přehrávám...")

        # "nauč se píseň X: C4 D4 E4..."
        teach_match = re.search(r'(?:nauč\s+se|nauc\s+se|zapamatuj)\s+(?:píseň|pisnicku|melodii)?\s*[:\-]?\s*(.+)', lower)
        if teach_match:
            parts = teach_match.group(1).split(':')
            if len(parts) >= 2:
                title = parts[0].strip()
                notation = parts[1].strip()
                if teach_radim_song(title, notation, user_id=user_id):
                    notes = parse_notation(notation)
                    return f"🎵 Naučil jsem se '{title}'! Má {len(notes)} not. Příště řekněte 'zazpívej {title}' a zahraju."
            return "Řekněte: nauč se píseň Název: C4 D4 E4 F4 G4"

        # "co je nota C4" / "jaká frekvence má A"
        note_q = re.search(r'(?:co je|jaká|kolik)\s+(?:nota|frekvenc|tón)\s+(\w+)', lower)
        if note_q:
            note = note_q.group(1)
            hz = note_to_hz(note)
            if hz:
                return f"🎵 Nota {note.upper()} má frekvenci {hz} Hz."

        # "Fibonacci melodie"
        if 'fibonacci' in lower or 'zlatý řez' in lower or 'zlaty rez' in lower:
            melody = fibonacci_melody('C4', 8, 'pentatonic')
            notes_str = ", ".join(f"{n[0]}={n[1]}Hz" for n in melody)
            return f"🎼 Fibonacci melodie (pentatonická): {notes_str}. Krásná, že? Fibonacci čísla na stupnici vytvářejí přirozeně znějící melodii."

        # "φ interval" / "zlatý interval"
        if 'interval' in lower and ('phi' in lower or 'φ' in lower or 'zlat' in lower):
            phi = phi_interval()
            return (f"🎼 Zlatý interval (φ = {PHI:.3f}) odpovídá {phi['phi_cents']} centů — "
                    f"leží mezi {phi['nearest_below']['name']} a {phi['nearest_above']['name']}. "
                    f"Je to nejpříjemnější interval v přírodě!")

    except (ImportError, Exception) as e:
        logger.debug(f"Music intent: {e}")

    return None  # Let AI handle it


def _handle_calendar(**kwargs):
    """Handle calendar queries — today's events, upcoming, what's planned."""
    user_id = kwargs.get('user_id')
    if not user_id:
        return None  # Let AI handle

    try:
        from database import db_context
        from datetime import datetime, timedelta
        today = datetime.utcnow().strftime('%Y-%m-%d')
        week = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d')

        with db_context() as db:
            today_events = db.execute(
                "SELECT title, time, type, location FROM calendar_events WHERE user_id = ? AND date = ? ORDER BY time",
                (user_id, today)
            ).fetchall()
            upcoming = db.execute(
                "SELECT title, date, time, type FROM calendar_events WHERE user_id = ? AND date > ? AND date <= ? ORDER BY date, time LIMIT 5",
                (user_id, today, week)
            ).fetchall()

        parts = []
        if today_events:
            parts.append("Dnes máte:")
            for e in today_events:
                time_str = e[1] if e[1] else "celý den"
                loc = f" v {e[3]}" if e[3] else ""
                parts.append(f"  {time_str} — {e[0]}{loc}")
        else:
            parts.append("Dnes nemáte žádné události v kalendáři.")

        if upcoming:
            parts.append("Příští dny:")
            for e in upcoming:
                parts.append(f"  {e[1]} {e[2] or ''} — {e[0]}")

        if not today_events and not upcoming:
            return "Váš kalendář je prázdný. Chcete přidat nějakou událost?"

        return "\n".join(parts)

    except Exception as e:
        logger.debug(f"Calendar intent: {e}")
        return None


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


# ============================================================================
# 🏠 HOME ASSISTANT HANDLERS
# ============================================================================

def _handle_ha_light_on(**kwargs):
    """Turn on lights."""
    try:
        from home_assistant import ha
        msg = kwargs.get('message', '').lower()
        # Detect room from message
        room = _detect_room(msg)
        entity_id = None
        if room:
            result = ha().execute_agent_action('light_on', {'room': room, 'device_type': 'light'})
        else:
            # Turn on all lights or first found
            devices = ha().get_devices_by_type('light')
            lights = devices.get('light', [])
            if lights:
                off_lights = [l for l in lights if l['state'] == 'off']
                target = off_lights[0] if off_lights else lights[0]
                result = ha().execute_agent_action('light_on', {'entity_id': target['entity_id']})
            else:
                return "Nemám žádná světla k ovládání."
        return result.get('message', 'Světlo zapnuto.')
    except Exception as e:
        return f"Bohužel se mi nepodařilo zapnout světlo: {e}"

def _handle_ha_light_off(**kwargs):
    try:
        from home_assistant import ha
        msg = kwargs.get('message', '').lower()
        room = _detect_room(msg)
        if room:
            result = ha().execute_agent_action('light_off', {'room': room, 'device_type': 'light'})
        else:
            devices = ha().get_devices_by_type('light')
            lights = devices.get('light', [])
            on_lights = [l for l in lights if l['state'] == 'on']
            if on_lights:
                result = ha().execute_agent_action('light_off', {'entity_id': on_lights[0]['entity_id']})
            else:
                return "Všechna světla jsou už zhasnutá."
        return result.get('message', 'Světlo vypnuto.')
    except Exception as e:
        return f"Nepodařilo se vypnout světlo: {e}"

def _handle_ha_temperature(**kwargs):
    try:
        from home_assistant import ha
        result = ha().execute_agent_action('get_temperature')
        return result.get('message', 'Nemám data o teplotě.')
    except Exception:
        return None  # Pass to AI

def _handle_ha_home_status(**kwargs):
    try:
        from home_assistant import ha
        result = ha().execute_agent_action('get_status')
        return result.get('message', 'Stav domácnosti není dostupný.')
    except Exception:
        return None

def _handle_ha_lock(**kwargs):
    try:
        from home_assistant import ha
        msg = kwargs.get('message', '').lower()
        if any(w in msg for w in ['odemkni', 'odemknout', 'otevři zámek', 'otevrit zamek']):
            devices = ha().get_devices_by_type('lock')
            locks = devices.get('lock', [])
            if locks:
                result = ha().execute_agent_action('unlock', {'entity_id': locks[0]['entity_id']})
                return result.get('message', 'Odemčeno.')
        else:
            devices = ha().get_devices_by_type('lock')
            locks = devices.get('lock', [])
            if locks:
                result = ha().execute_agent_action('lock', {'entity_id': locks[0]['entity_id']})
                return result.get('message', 'Zamčeno.')
        return "Nemám žádný zámek k ovládání."
    except Exception:
        return None

def _handle_ha_climate(**kwargs):
    try:
        from home_assistant import ha
        import re
        msg = kwargs.get('message', '').lower()
        # Extract temperature number
        temp_match = re.search(r'(\d{1,2})\s*(?:°|stup[nň]|°C)', msg)
        if temp_match:
            temp = int(temp_match.group(1))
            temp = max(15, min(30, temp))  # Safety limits
            devices = ha().get_devices_by_type('climate')
            climates = devices.get('climate', [])
            if climates:
                result = ha().execute_agent_action('climate_set', {
                    'entity_id': climates[0]['entity_id'],
                    'temperature': temp
                })
                return result.get('message', f'Teplota nastavena na {temp}°C.')
        # No specific temp — adjust based on request
        if any(w in msg for w in ['zima', 'studeno', 'chladno', 'přitop', 'pritop', 'zatop']):
            # Raise by 2°C
            devices = ha().get_devices_by_type('climate')
            climates = devices.get('climate', [])
            if climates:
                current = climates[0].get('attributes', {}).get('temperature', 20)
                new_temp = min(25, current + 2)
                result = ha().execute_agent_action('climate_set', {
                    'entity_id': climates[0]['entity_id'], 'temperature': new_temp
                })
                return f"🌡️ Zvýšil jsem topení na {new_temp}°C."
        elif any(w in msg for w in ['teplo', 'horko', 'moc topí']):
            devices = ha().get_devices_by_type('climate')
            climates = devices.get('climate', [])
            if climates:
                current = climates[0].get('attributes', {}).get('temperature', 22)
                new_temp = max(18, current - 2)
                result = ha().execute_agent_action('climate_set', {
                    'entity_id': climates[0]['entity_id'], 'temperature': new_temp
                })
                return f"🌡️ Snížil jsem topení na {new_temp}°C."
        return None  # Pass to AI
    except Exception:
        return None

def _handle_ha_cover(**kwargs):
    try:
        from home_assistant import ha
        msg = kwargs.get('message', '').lower()
        devices = ha().get_devices_by_type('cover')
        covers = devices.get('cover', [])
        if not covers:
            return "Nemám žádné rolety k ovládání."
        if any(w in msg for w in ['otevři', 'otevrit', 'nahoru', 'vytas', 'vytáhni']):
            result = ha().execute_agent_action('cover_open', {'entity_id': covers[0]['entity_id']})
        else:
            result = ha().execute_agent_action('cover_close', {'entity_id': covers[0]['entity_id']})
        return result.get('message', 'Hotovo.')
    except Exception:
        return None

def _detect_room(text):
    """Detect room name from Czech text."""
    room_map = {
        'living_room': ['obývák', 'obyvak', 'obývací', 'obyvaci', 'obýváku', 'obyvaku'],
        'bedroom': ['ložnice', 'loznice', 'ložnici', 'loznici', 'spaní', 'spani'],
        'kitchen': ['kuchyň', 'kuchyn', 'kuchyně', 'kuchyne', 'kuchyni'],
        'bathroom': ['koupelna', 'koupelně', 'koupelne', 'záchod', 'zachod'],
        'hallway': ['chodba', 'chodbě', 'chodbe', 'předsíň', 'predsín', 'predsini'],
        'balcony': ['balkón', 'balkon', 'balkoně', 'balkone'],
        'garden': ['zahrada', 'zahradě', 'zahrade'],
        'garage': ['garáž', 'garaz', 'garáži'],
        'office': ['pracovna', 'pracovně', 'pracovne', 'kancelář', 'kancelar'],
    }
    for room, keywords in room_map.items():
        for kw in keywords:
            if kw in text:
                return room
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
    # 📅 Calendar
    "calendar": _handle_calendar,
    # 🎼 Music
    "music": _handle_music,
    # 🏠 Home Assistant
    "ha_light_on": _handle_ha_light_on,
    "ha_light_off": _handle_ha_light_off,
    "ha_temperature": _handle_ha_temperature,
    "ha_home_status": _handle_ha_home_status,
    "ha_lock": _handle_ha_lock,
    "ha_climate": _handle_ha_climate,
    "ha_cover": _handle_ha_cover,
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
