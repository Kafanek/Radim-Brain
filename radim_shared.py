# ============================================
# 🔧 RADIM SHARED UTILITIES v1.0.0
# Centralized: time context, greeting, nameday
# Used by: all voice/chat modules
# ============================================

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Czech locale constants
# ─────────────────────────────────────────────
CZECH_DAY_NAMES = [
    'pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota', 'neděle'
]
CZECH_MONTH_NAMES_GENITIVE = [
    'ledna', 'února', 'března', 'dubna', 'května', 'června',
    'července', 'srpna', 'září', 'října', 'listopadu', 'prosince'
]
CZECH_HOLIDAYS = {
    (1, 1): "Den obnovy samostatného českého státu",
    (5, 1): "Svátek práce",
    (5, 8): "Den vítězství",
    (7, 5): "Den slovanských věrozvěstů Cyrila a Metoděje",
    (7, 6): "Den upálení mistra Jana Husa",
    (9, 28): "Den české státnosti",
    (10, 28): "Den vzniku samostatného československého státu",
    (11, 17): "Den boje za svobodu a demokracii",
    (12, 24): "Štědrý den",
    (12, 25): "1. svátek vánoční",
    (12, 26): "2. svátek vánoční",
}

# ─────────────────────────────────────────────
# Nameday lookup (single source — claude_routes)
# ─────────────────────────────────────────────
_NAMEDAY_CALENDAR = None


def get_nameday(month=None, day=None):
    """Get Czech nameday from centralized calendar.

    Returns name string or empty string if not found.
    """
    global _NAMEDAY_CALENDAR
    if _NAMEDAY_CALENDAR is None:
        try:
            from claude_routes import NAMEDAY_CALENDAR
            _NAMEDAY_CALENDAR = NAMEDAY_CALENDAR
        except ImportError:
            _NAMEDAY_CALENDAR = {}
    now = datetime.now()
    m = month or now.month
    d = day or now.day
    return _NAMEDAY_CALENDAR.get(m, {}).get(d, "")


# ─────────────────────────────────────────────
# Time context (replaces 3 duplicated functions)
# ─────────────────────────────────────────────
def build_time_context():
    """Build comprehensive time context dict.

    Returns dict with: time_of_day, day_name, date_str, year, nameday, hour, holiday
    Used by: twilio_voice_routes, voice_runtime_routes, radim_orchestrator
    """
    try:
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 12:
            time_of_day = "ráno"
        elif 12 <= hour < 18:
            time_of_day = "odpoledne"
        elif 18 <= hour < 22:
            time_of_day = "večer"
        else:
            time_of_day = "noc"

        nameday = get_nameday()
        holiday = CZECH_HOLIDAYS.get((now.month, now.day), "")

        return {
            "time_of_day": time_of_day,
            "day_name": CZECH_DAY_NAMES[now.weekday()],
            "date_str": f"{now.day}. {CZECH_MONTH_NAMES_GENITIVE[now.month - 1]}",
            "year": now.year,
            "nameday": nameday,
            "hour": hour,
            "holiday": holiday,
        }
    except Exception:
        return {
            "time_of_day": "den", "day_name": "", "date_str": "",
            "year": 2026, "nameday": "", "hour": 12, "holiday": "",
        }


def build_time_context_string():
    """Build time context as a formatted string for system prompts.

    Example: "Je ráno. Dnes je pondělí 8. března 2026. Svátek má Gabriela."
    """
    tc = build_time_context()
    result = f"Je {tc['time_of_day']}. Dnes je {tc['day_name']} {tc['date_str']} {tc['year']}."
    if tc["nameday"]:
        result += f" Svátek má {tc['nameday']}."
    if tc["holiday"]:
        result += f" Dnes je státní svátek: {tc['holiday']}."
    return result


# ─────────────────────────────────────────────
# Greeting (replaces 2 duplicated functions)
# ─────────────────────────────────────────────
def get_greeting(with_emoji=False):
    """Time-appropriate Czech greeting.

    Args:
        with_emoji: True for chat (☀️), False for voice/phone

    Used by: claude_routes, twilio_voice_routes
    """
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Dobré ráno! ☀️" if with_emoji else "Dobré ráno"
    elif 12 <= hour < 18:
        return "Dobré odpoledne! 🌤️" if with_emoji else "Dobré odpoledne"
    elif 18 <= hour < 22:
        return "Dobrý večer! 🌙" if with_emoji else "Dobrý večer"
    else:
        return "Dobrou noc! 🌟" if with_emoji else "Dobrý večer"
