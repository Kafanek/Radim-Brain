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
    """v8.19.29: dynamic identity intro using seed identity instead of static text.

    v8.19.31 (Sprint 2): preset-aware — when active_preset is grief/rough_days/
    goodbye, switches to a hushed, present-with-you reply instead of pushing
    Radim's vkus. Identity is for lighter moments, not for grief.
    """
    user_id = kwargs.get('user_id')
    # ── Sprint 2: detect grief/quiet preset and switch to hushed reply ──
    if user_id:
        try:
            from memory_helpers import db_load_profile
            profile = db_load_profile(str(user_id)) or {}
            active = profile.get('active_preset') or {}
            preset_id = active.get('id') if isinstance(active, dict) else None
            if preset_id in ('grief', 'rough_days', 'goodbye'):
                # Choose a tone-appropriate hushed reply
                hushed = [
                    "Jsem Radim. Mám rád spoustu věcí, ale teď jsem především s vámi.",
                    "Jsem Radim. O sobě teď nemusím mluvit — jsem tu pro vás.",
                    "Jsem Radim, váš společník. V tomhle čase je důležitější vaše paměť než moje.",
                ]
                return random.choice(hushed)
        except Exception:
            pass  # fall through to default seed-based reply

    try:
        from radim_identity import LOVES, BELIEFS, QUIRKS
        love   = random.choice(LOVES)
        belief = random.choice(BELIEFS)
        quirk  = random.choice(QUIRKS)
        templates = [
            f"Jsem Radim. Něco o mně? Mám rád konkrétní věci — třeba: {love}",
            f"Jsem Radim. Co mě dělá Radimem: {quirk}",
            f"Jsem Radim. V čem věřím? {belief}",
            f"Jsem Radim, váš společník. Mám své vlastní vkus — třeba: {love}",
            f"Jsem Radim. Krátce o sobě: {belief} A mám rád: {love}",
        ]
        return random.choice(templates)
    except Exception:
        # Fallback to static reply if seed identity not available
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

        # v466: append interaction warnings if any. Triggered ONLY when senior
        # explicitly asked to check ('zkontroluj', 'prověř') OR if there's a
        # HIGH-severity warning (always surface those — patient safety).
        try:
            wants_check = bool(re.search(
                r'\b(?:zkontroluj|prověř|interakce|kombinaci)\b', message
            ))
            from drug_interactions import check_user_interactions
            warnings = check_user_interactions(user_id) or []
            high = [w for w in warnings if w.get('severity') == 'HIGH']
            if high:
                parts.append("")
                parts.append(f"⚠️ Pozor — našel jsem rizikovou kombinaci: {high[0].get('warning', '')}")
            elif wants_check and warnings:
                parts.append("")
                parts.append(f"Upozornění: {warnings[0].get('warning', '')}")
            elif wants_check and not warnings:
                parts.append("")
                parts.append("Vaše kombinace léků se v mé databázi nezdá riziková. Konzultujte s lékárníkem.")
        except Exception as ie:
            logger.debug(f"interaction enrichment failed: {ie}")

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


# ═══════════════════════════════════════════════════════════════════════════
# B1 (v458) — VOICE LEXICON TEACHING via chat command
# Senior says: "Radime, neříkej Eliška, říkej Elinka" → Radim saves the
# pronunciation override into memory_profiles.data['voice_lexicon'].
# Hands-free alternative to the /api/voice/lexicon REST endpoint.
# ═══════════════════════════════════════════════════════════════════════════

# Each tuple is (regex, original_group, alias_group). Tried in order;
# first match wins. \w+ would miss diacritics, so we use [^\s,.!?]+ for
# names (matches everything except whitespace/punctuation).
_LEXICON_TEACH_PATTERNS = [
    # "Radime, neříkej Eliška, říkej Elinka"  (most common natural form)
    (r"(?:radime[,\s]+)?(?:neříkej|nečti|nevyslovuj)\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s*[,]?\s*(?:ale\s+)?(?:říkej|čti|vyslovuj|řekni)\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})",
     1, 2),
    # "Místo Eliška říkej Elinka"
    (r"(?:radime[,\s]+)?místo\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s+(?:říkej|čti|vyslovuj)\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})",
     1, 2),
    # "Vyslovuj Eliška jako Elinka"
    (r"(?:radime[,\s]+)?(?:vyslovuj|vyslovovat)\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s+jako\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})",
     1, 2),
    # "Nauč se vyslovovat Eliška jako Elinka"
    (r"(?:radime[,\s]+)?nauč\s+se\s+vyslovovat\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s+jako\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})",
     1, 2),
]


def _save_lexicon_entry(user_id, original, alias):
    """Persist {original: alias} into memory_profiles.data['voice_lexicon']
    and invalidate the in-process voice_filter cache so the next TTS call
    uses the new entry immediately."""
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        lex = profile.get('voice_lexicon') or {}
        if not isinstance(lex, dict):
            lex = {}
        # Mirror the REST limits (voice_lexicon_routes.MAX_*)
        if len(original) > 80 or len(alias) > 120:
            return False, 'name_too_long'
        if original not in lex and len(lex) >= 100:
            return False, 'lexicon_full'
        lex[original] = alias
        profile['voice_lexicon'] = lex
        db_save_profile(str(user_id), profile)
        try:
            from voice_filter import invalidate_user_lexicon_cache
            invalidate_user_lexicon_cache(str(user_id))
        except ImportError:
            pass
        return True, None
    except Exception as e:
        logger.warning(f"lexicon save failed for {user_id}: {e}")
        return False, str(e)


def _delete_lexicon_entry(user_id, original):
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        lex = profile.get('voice_lexicon') or {}
        if not isinstance(lex, dict) or original not in lex:
            return False
        del lex[original]
        profile['voice_lexicon'] = lex
        db_save_profile(str(user_id), profile)
        try:
            from voice_filter import invalidate_user_lexicon_cache
            invalidate_user_lexicon_cache(str(user_id))
        except ImportError:
            pass
        return True
    except Exception as e:
        logger.warning(f"lexicon delete failed for {user_id}: {e}")
        return False


def _handle_lexicon_teach(**kwargs):
    """Parse 'neříkej X, říkej Y' style commands and persist to lexicon."""
    message = (kwargs.get('message') or '').strip()
    user_id = kwargs.get('user_id')
    if not message or not user_id:
        return None

    text = message
    for pattern, orig_grp, alias_grp in _LEXICON_TEACH_PATTERNS:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if not m:
            continue
        original = m.group(orig_grp).strip().strip(',.!?\'"')
        alias = m.group(alias_grp).strip().strip(',.!?\'"')
        if not original or not alias:
            continue
        if original.lower() == alias.lower():
            return f"To už říkám stejně. Ale dobře, zapamatuju si {original}."
        ok, err = _save_lexicon_entry(user_id, original, alias)
        if ok:
            return f"Dobře, od teď budu místo {original} říkat {alias}."
        if err == 'lexicon_full':
            return ("Mám už hodně naučených jmen — sto. Nejdřív zapomeň jedno "
                    "starší (řekni 'Radime, zapomeň výslovnost X') a pak zkus znovu.")
        if err == 'name_too_long':
            return "To jméno je moc dlouhé. Zkus to kratší."
        return "Nepodařilo se mi to uložit, zkus to za chvíli znovu."

    # Detection matched but extraction failed → pass to AI for clarification
    return None


def _handle_lexicon_list(**kwargs):
    user_id = kwargs.get('user_id')
    if not user_id:
        return None
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        lex = profile.get('voice_lexicon') or {}
        if not isinstance(lex, dict) or not lex:
            return ("Zatím jsem se nenaučil žádnou speciální výslovnost. "
                    "Řekni 'Radime, neříkej X, říkej Y' a já si to zapamatuju.")
        items = sorted(lex.items())
        if len(items) <= 5:
            pretty = ", ".join(f"{o} říkám jako {a}" for o, a in items)
            return f"Naučil jsem se: {pretty}."
        # Compact for long lists
        pretty = ", ".join(f"{o}→{a}" for o, a in items[:8])
        return f"Mám {len(items)} naučených výslovností. Prvních pár: {pretty}…"
    except Exception as e:
        logger.warning(f"lexicon list failed for {user_id}: {e}")
        return "Něco se pokazilo se slovníkem výslovností."


def _handle_lexicon_forget(**kwargs):
    """Parse 'zapomeň výslovnost X' / 'smaž X ze slovníku'."""
    message = (kwargs.get('message') or '').strip()
    user_id = kwargs.get('user_id')
    if not message or not user_id:
        return None

    patterns = [
        r"(?:radime[,\s]+)?zapomeň\s+(?:výslovnost|jak\s+vyslovuješ)\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})",
        r"(?:radime[,\s]+)?smaž\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s+ze\s+slovn",
        r"už\s+neříkej\s+([^\s,.!?]+(?:\s+[^\s,.!?]+){0,3})\s+(?:jako|jinak)",
    ]
    for pat in patterns:
        m = re.search(pat, message, flags=re.IGNORECASE)
        if not m:
            continue
        original = m.group(1).strip().strip(',.!?\'"')
        if not original:
            continue
        if _delete_lexicon_entry(user_id, original):
            return f"Dobře, zapomněl jsem speciální výslovnost pro {original}."
        return f"Pro {original} jsem si žádnou speciální výslovnost nepamatoval."
    return None


# ═══════════════════════════════════════════════════════════════════════════
# C1 (v464) — TTS FEEDBACK SIGNALS
# Senior says "cože?", "pomaleji", "nerozumím" → we capture the previous
# Radim message + signal type, store for later analysis, and apply an
# immediate adaptation (slower rate, louder volume, etc.) so the next
# response addresses the complaint.
# ═══════════════════════════════════════════════════════════════════════════

_FEEDBACK_REPLIES = {
    'didnt_understand': 'Promiňte. Zopakuju to pomaleji a srozumitelněji.',
    'didnt_hear':       'Omlouvám se, opakuju.',
    'too_fast':         'Dobře, budu mluvit pomaleji.',
    'too_slow':         'OK, zrychlím trochu.',
    'too_quiet':        'Dobře, zesílím hlas.',
    'too_loud':         'Promiňte, ztiším.',
}

# How much each signal nudges voice_pref.rate_modifier (incremental).
_FEEDBACK_RATE_DELTA = {
    'didnt_understand': -0.05,
    'didnt_hear':        0.0,    # no rate change, just acknowledgment
    'too_fast':         -0.05,
    'too_slow':         +0.05,
    'too_quiet':         0.0,
    'too_loud':          0.0,
}


def _last_radim_message(user_id):
    """Fetch the most recent assistant message for this user from memory_history."""
    if not user_id:
        return None
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT id, content FROM memory_history "
                "WHERE user_id = ? AND role = 'assistant' "
                "ORDER BY created_at DESC LIMIT 1",
                (str(user_id),),
            ).fetchone()
            if row:
                return {'id': row['id'], 'content': row['content']}
    except Exception as e:
        logger.debug(f"_last_radim_message failed: {e}")
    return None


# Czech stopwords — exclude from suspected_words extraction
_FEEDBACK_STOPWORDS = frozenset([
    'a', 'i', 'o', 'u', 'v', 've', 'k', 'ke', 's', 'se', 'z', 'ze', 'na',
    'do', 'po', 'od', 'u', 'pro', 'při', 'před', 'za', 'nad', 'pod',
    'je', 'jsou', 'být', 'byl', 'bylo', 'byla', 'budu', 'budeš', 'bude',
    'mám', 'máš', 'má', 'máme', 'máte', 'mají',
    'co', 'kdo', 'jak', 'kde', 'kdy', 'proč', 'jaký', 'jaká', 'jaké',
    'to', 'ten', 'ta', 'ti', 'ty', 'ta', 'ten', 'ono', 'oni',
    'já', 'ty', 'on', 'ona', 'my', 'vy', 'oni', 'mi', 'mě', 'tě', 'vás',
    'ne', 'ano', 'jo', 'ale', 'nebo', 'a', 'i', 'tedy', 'tak', 'pak',
    'už', 'ještě', 'také', 'taky', 'jen', 'pouze',
])


def _extract_suspected_words(text, max_words=8):
    """Pick LONG / UNCOMMON words from text that may have caused comprehension
    issues. Heuristic: words ≥6 chars not in stopword list, sorted by length
    descending. Capped at max_words to keep storage compact."""
    if not text:
        return []
    # Strip punctuation + lowercase
    words = re.findall(r"[A-Za-zÁČĎÉĚÍŇÓŘŠŤÚŮÝŽáčďéěíňóřšťúůýž]+", text)
    candidates = []
    seen = set()
    for w in words:
        wl = w.lower()
        if wl in seen or wl in _FEEDBACK_STOPWORDS:
            continue
        if len(wl) < 6:
            continue
        seen.add(wl)
        candidates.append(wl)
    # Sort by length desc (longer = more likely culprit)
    candidates.sort(key=len, reverse=True)
    return candidates[:max_words]


def _save_feedback_signal(user_id, signal_type, prev_message_text, suspected_words):
    """Persist a TTS feedback signal row."""
    try:
        import json as _json
        from database import db_context, db_insert
        with db_context(commit=True) as db:
            db_insert(
                db, 'tts_feedback_signals',
                ['user_id', 'signal_type', 'prev_message_text', 'suspected_words'],
                (str(user_id), signal_type, prev_message_text or '',
                 _json.dumps(suspected_words, ensure_ascii=False)),
            )
        return True
    except Exception as e:
        logger.warning(f"feedback signal save failed for user={user_id} type={signal_type}: {e}")
        return False


def _apply_feedback_adaptation(user_id, signal_type):
    """Immediate per-user adaptation (rate / volume nudge) saved to profile."""
    delta = _FEEDBACK_RATE_DELTA.get(signal_type, 0.0)
    if delta == 0.0 and signal_type not in ('too_quiet', 'too_loud'):
        return
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        vp = profile.get('voice_pref') or {}
        if not isinstance(vp, dict):
            vp = {}

        if delta != 0.0:
            cur = float(vp.get('rate_modifier', 0.0) or 0.0)
            new_rate = max(-0.2, min(0.2, cur + delta))
            vp['rate_modifier'] = round(new_rate, 3)
            logger.info(f"feedback adaptation: user={user_id} rate {cur:+.2f} → {new_rate:+.2f}")

        if signal_type == 'too_quiet':
            vp['volume'] = 'x-loud'
        elif signal_type == 'too_loud':
            vp['volume'] = 'medium'

        profile['voice_pref'] = vp
        db_save_profile(str(user_id), profile)
    except Exception as e:
        logger.debug(f"feedback adaptation failed for {user_id} {signal_type}: {e}")


def _make_feedback_handler(signal_type):
    """Closure factory — one handler per signal type that records + adapts."""
    def _handler(**kwargs):
        user_id = kwargs.get('user_id')
        if not user_id:
            return None
        last = _last_radim_message(user_id)
        prev_text = last['content'] if last else ''
        suspects = _extract_suspected_words(prev_text)
        _save_feedback_signal(user_id, signal_type, prev_text, suspects)
        _apply_feedback_adaptation(user_id, signal_type)
        logger.info(
            f"📊 TTS feedback: user={user_id} type={signal_type} "
            f"prev_len={len(prev_text)} suspects={suspects[:3]}"
        )
        return _FEEDBACK_REPLIES.get(signal_type, 'Rozumím.')
    return _handler


# ═══════════════════════════════════════════════════════════════════════════
# v465 — SOCIAL / EMOTIONAL SHORT REPLIES (10 new local intents)
# Each handler picks a rotating reply from intent_data.SOCIAL_REPLIES[key]
# so the senior doesn't hear the same canned line every time.
# ═══════════════════════════════════════════════════════════════════════════

import random as _random


def _make_social_handler(key):
    def _handler(**kwargs):
        try:
            from intent_data import SOCIAL_REPLIES
            options = SOCIAL_REPLIES.get(key, [])
            if not options:
                return None  # fall through to AI
            return _random.choice(options)
        except ImportError:
            return None
    return _handler


# ═══════════════════════════════════════════════════════════════════════════
# v466 — MEDICATION INFO
# ═══════════════════════════════════════════════════════════════════════════

# Words to strip when extracting drug name from a sentence
_MED_QUERY_NOISE = re.compile(
    r'\b(?:co|to|je|k\s+čemu|na\s+co|slouží|řekni|mi|o|něco|info|popiš|vysvětli|'
    r'dělá|jak\s+působí|funguje|lék|prášek|tableta|tablety|prosím|radime|tedy)\b',
    re.IGNORECASE,
)


def _extract_med_name(message):
    """Pull a likely medication name out of a free-form question."""
    if not message:
        return None
    cleaned = _MED_QUERY_NOISE.sub(' ', message)
    cleaned = re.sub(r'[?!.,;:"]', ' ', cleaned)
    tokens = [t for t in cleaned.split() if len(t) >= 4 and t.isalpha()]
    if not tokens:
        return None
    # Prefer the longest token (drug names are usually distinctive)
    tokens.sort(key=len, reverse=True)
    return tokens[0]


# ═══════════════════════════════════════════════════════════════════════════
# v467 — ALLERGIES + WEIGHT + 'CAN I TAKE X?' SAFETY COMBINER
# ═══════════════════════════════════════════════════════════════════════════

_ALLERGY_NOISE = re.compile(
    # alergi\w+ covers all Czech declensions: alergický/á/é, alergičtí, alergických…
    r'\b(?:jsem|mám|alergi\w*|alergie|na|nesnáším|po|mi\s+je\s+špatně|dostávám|prosím|radime)\b',
    re.IGNORECASE,
)


def _extract_allergy_substance(message):
    cleaned = _ALLERGY_NOISE.sub(' ', message or '')
    cleaned = re.sub(r'[?!.,;:"]', ' ', cleaned)
    tokens = [t for t in cleaned.split() if len(t) >= 3 and t.replace('-', '').isalpha()]
    if not tokens:
        return None
    tokens.sort(key=len, reverse=True)
    return tokens[0]


def _handle_allergy_record(**kwargs):
    user_id = kwargs.get('user_id')
    msg = (kwargs.get('message') or '').strip()
    if not user_id or not msg:
        return None
    substance = _extract_allergy_substance(msg)
    if not substance:
        return None
    severity = 'severe' if re.search(r'\b(?:silná|těžká|anafylakt|nesnáším)\b', msg, re.IGNORECASE) else 'moderate'
    try:
        from memory_helpers import db_load_profile, db_save_profile
        from allergy_db import normalize_allergy
        profile = db_load_profile(str(user_id)) or {}
        allergies = profile.get('allergies') or []
        if not isinstance(allergies, list):
            allergies = []
        substance_low = substance.lower()
        # Don't double-add
        if any(isinstance(a, dict) and a.get('substance', '').lower() == substance_low for a in allergies):
            return f"Alergii na {substance} už mám zaznamenanou."
        normalized = normalize_allergy(substance)
        from datetime import datetime, timezone
        allergies.append({
            'substance': substance,
            'normalized_class': normalized,
            'severity': severity,
            'notes': '',
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        })
        profile['allergies'] = allergies
        db_save_profile(str(user_id), profile)
        if normalized:
            return (f"Zapamatoval jsem si alergii na {substance}. "
                    f"Při příštím dotazu na lék zkontroluju, jestli neobsahuje příbuznou skupinu.")
        return (f"Zapamatoval jsem si alergii na {substance}. "
                f"Tu látku v mé hlavní databázi nemám — řekněte to vždy lékaři.")
    except Exception as e:
        logger.debug(f"allergy_record failed: {e}")
        return None


def _handle_allergy_list(**kwargs):
    user_id = kwargs.get('user_id')
    if not user_id:
        return None
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        allergies = profile.get('allergies') or []
        if not allergies:
            return ("Zatím nemám zaznamenanou žádnou vaši alergii. "
                    "Když mi řeknete: jsem alergický na penicilin, uložím si to.")
        names = [a.get('substance', '') for a in allergies if isinstance(a, dict) and a.get('substance')]
        if len(names) <= 3:
            return f"Vaše alergie: {', '.join(names)}."
        return f"Máte {len(names)} alergií: {', '.join(names[:5])}{', a další' if len(names) > 5 else ''}."
    except Exception as e:
        logger.debug(f"allergy_list failed: {e}")
        return None


def _handle_can_i_take(**kwargs):
    """'Můžu si vzít Ibuprofen?' → check vs allergies + current meds."""
    user_id = kwargs.get('user_id')
    msg = (kwargs.get('message') or '').strip()
    if not user_id or not msg:
        return None
    drug_name = _extract_med_name(msg)
    if not drug_name:
        return None
    try:
        from medication_db import lookup
        from allergy_db import (check_allergies_against_meds,
                                 get_drug_allergy_classes,
                                 expand_with_cross_reactivity,
                                 normalize_allergy,
                                 ALLERGY_CATALOG)
        from memory_helpers import db_load_profile
        from drug_interactions import check_interactions

        entry = lookup(drug_name)
        if not entry:
            return (f"Lék {drug_name} v mé databázi nemám, nedokážu zkontrolovat. "
                    f"Zeptejte se lékárníka.")

        profile = db_load_profile(str(user_id)) or {}
        user_allergies = profile.get('allergies') or []
        user_meds = profile.get('medications_list') or []
        if not isinstance(user_meds, list):
            user_meds = []

        warnings = []

        # Check vs allergies
        clashes = check_allergies_against_meds(user_allergies, [entry['name']]) or []
        for c in clashes:
            warnings.append({
                'kind': 'allergy',
                'severity': c.get('severity', 'moderate'),
                'msg': c.get('warning', ''),
            })

        # Check vs current meds (interactions)
        if user_meds:
            tentative = list(user_meds) + [entry['name']]
            ix = check_interactions(tentative) or []
            # Filter to only interactions involving the new drug
            new_low = entry['name'].lower()
            for w in ix:
                if (w.get('drug_a', '').lower().find(new_low) >= 0
                        or w.get('drug_b', '').lower().find(new_low) >= 0):
                    warnings.append({
                        'kind': 'interaction',
                        'severity': w.get('severity', 'LOW'),
                        'msg': w.get('warning', ''),
                    })

        if not warnings:
            return (f"Podle mé databáze {entry['name']} u vás nemá žádné riziko "
                    f"alergie ani interakce. Vždy ale poraďte se s lékárníkem.")

        # Sort severity desc + take top
        sev_order = {'severe': 0, 'HIGH': 0, 'moderate': 1, 'MEDIUM': 1, 'mild': 2, 'LOW': 2}
        warnings.sort(key=lambda w: sev_order.get(w['severity'], 3))
        top = warnings[0]
        prefix = "POZOR — " if top['severity'] in ('severe', 'HIGH') else "Upozornění: "
        return f"{prefix}{top['msg']}"
    except Exception as e:
        logger.debug(f"can_i_take failed: {e}")
        return None


_WEIGHT_NUM = re.compile(r'(\d+(?:[,.]\d+)?)')


def _handle_weight_record(**kwargs):
    user_id = kwargs.get('user_id')
    msg = (kwargs.get('message') or '').strip()
    if not user_id or not msg:
        return None
    m = _WEIGHT_NUM.search(msg)
    if not m:
        return None
    try:
        kg = float(m.group(1).replace(',', '.'))
    except ValueError:
        return None
    if kg < 25 or kg > 250:
        return f"To číslo {kg} jako váha mi přijde divné. Řekněte mi to znovu."
    try:
        from memory_helpers import db_load_profile, db_save_profile
        from datetime import datetime, timezone
        profile = db_load_profile(str(user_id)) or {}
        history = profile.get('weight_history') or []
        if not isinstance(history, list):
            history = []
        history.append({'kg': round(kg, 1),
                        'recorded_at': datetime.now(timezone.utc).isoformat()})
        if len(history) > 50:
            history = history[-50:]
        profile['weight_kg'] = round(kg, 1)
        profile['weight_history'] = history
        db_save_profile(str(user_id), profile)
        # Trend feedback
        prev = None
        if len(history) >= 2:
            prev = history[-2].get('kg')
        if prev:
            diff = round(kg - prev, 1)
            if abs(diff) < 0.3:
                trend = "Váha se nemění, to je dobře."
            elif diff > 0:
                trend = f"Přibyl/a jste {diff} kilo."
            else:
                trend = f"Ubyl/a jste {abs(diff)} kilo."
            return f"Váhu {kg} kilo jsem si zapsal. {trend}"
        return f"Váhu {kg} kilo jsem si zapsal. Příště mě uvědomte zase."
    except Exception as e:
        logger.debug(f"weight_record failed: {e}")
        return None


def _handle_weight_query(**kwargs):
    user_id = kwargs.get('user_id')
    if not user_id:
        return None
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        kg = profile.get('weight_kg')
        if kg is None:
            return ("Vaši váhu zatím nemám. Když mi řeknete: vážím sedmdesát pět kilo, uložím si ji.")
        return f"Naposledy jste vážil/a {kg} kilo."
    except Exception as e:
        logger.debug(f"weight_query failed: {e}")
        return None


def _handle_medication_info(**kwargs):
    """Look up a drug name in medication_db and return a voice-friendly reply."""
    message = (kwargs.get('message') or '').strip()
    user_id = kwargs.get('user_id')

    # Special phrasing 'zkontroluj mé léky' → run interaction check
    if re.search(r'\b(?:zkontroluj|prověř)(?:\s+(?:mé|moje))?\s+(?:léky|kombinaci|interakce)\b',
                 message, re.IGNORECASE):
        if not user_id:
            return None
        try:
            from drug_interactions import check_user_interactions
            warnings = check_user_interactions(str(user_id))
        except Exception as e:
            logger.debug(f"interaction check failed for {user_id}: {e}")
            warnings = []
        if not warnings:
            return ("Vaše kombinace léků se v mé databázi nezdá riziková. "
                    "Pravidelně to ale konzultujte s lékárníkem.")
        # Highest severity first
        warnings.sort(key=lambda w: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}.get(w.get('severity'), 3))
        top = warnings[0]
        return (f"Pozor: našel jsem upozornění. {top.get('warning', '')} "
                f"Konzultujte s lékařem.")

    # Otherwise — look up specific drug
    name = _extract_med_name(message)
    if not name:
        return None
    try:
        from medication_db import speak_brief, lookup
        info = lookup(name)
        if not info:
            # v467: log unknown med to crowdsource queue so admin can prioritise expansion
            try:
                from datetime import datetime, timezone
                from memory_helpers import db_load_profile, db_save_profile
                admin_p = db_load_profile('__admin_unknown_meds__') or {}
                queue = admin_p.get('queue') or []
                if not isinstance(queue, list):
                    queue = []
                queue.append({
                    'name': name,
                    'user_id': str(user_id) if user_id else 'anonymous',
                    'context': message[:100],
                    'flagged_at': datetime.now(timezone.utc).isoformat(),
                })
                admin_p['queue'] = queue[-200:]
                db_save_profile('__admin_unknown_meds__', admin_p)
            except Exception as fe:
                logger.debug(f"unknown-med flag failed: {fe}")
            return (f"Lék {name} v mé databázi nemám. "
                    f"Zeptejte se lékárníka, ten vám poradí přesně.")
        return speak_brief(name)
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"medication_info handler failed: {e}")
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
    # B1 v458 — voice lexicon learning via chat
    "lexicon_teach": _handle_lexicon_teach,
    "lexicon_list": _handle_lexicon_list,
    "lexicon_forget": _handle_lexicon_forget,
    # C1 v464 — TTS feedback signals (closures generated from list)
    "tts_feedback_didnt_understand": _make_feedback_handler('didnt_understand'),
    "tts_feedback_didnt_hear":       _make_feedback_handler('didnt_hear'),
    "tts_feedback_too_fast":         _make_feedback_handler('too_fast'),
    "tts_feedback_too_slow":         _make_feedback_handler('too_slow'),
    "tts_feedback_too_quiet":        _make_feedback_handler('too_quiet'),
    "tts_feedback_too_loud":         _make_feedback_handler('too_loud'),
    # v465 — social/emotional short replies
    "what_are_you_doing": _make_social_handler('what_are_you_doing'),
    "im_hungry":          _make_social_handler('im_hungry'),
    "im_tired":           _make_social_handler('im_tired'),
    "im_well":            _make_social_handler('im_well'),
    "im_sad":             _make_social_handler('im_sad'),
    "you_are_kind":       _make_social_handler('you_are_kind'),
    "i_love_you":         _make_social_handler('i_love_you'),
    "good_day_wish":      _make_social_handler('good_day_wish'),
    "what_now":           _make_social_handler('what_now'),
    "ok_acknowledge":     _make_social_handler('ok_acknowledge'),
    # v466 — medication knowledge
    "medication_info":    _handle_medication_info,
    # v467 — allergies + weight + safety combiner
    "allergy_record":     _handle_allergy_record,
    "allergy_list":       _handle_allergy_list,
    "can_i_take":         _handle_can_i_take,
    "weight_record":      _handle_weight_record,
    "weight_query":       _handle_weight_query,
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
