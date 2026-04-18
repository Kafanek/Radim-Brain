"""
🎉 Festive greeting builder (v10.40)
=============================================================================
Composes warm daily greeting for seniors using:
  - time of day (morning/afternoon/evening)
  - nameday (today's Czech calendar name)
  - custom template from user profile (optional)
  - festive holidays (Easter, Christmas, Velikonoce, New Year)

Used by:
  - wake word handler (morning wake-up greeting)
  - intent_resolver greeting intent
  - frontend FestiveGreetingService (via /api/festive-greeting)

The template is stored per-user in memory_profiles.data.festive_greeting:
  {
    "salutation": "Dobré ráno babičko",
    "suffix": "přeji ti krásný den",
    "use_nameday": true,
    "use_holiday": true
  }

If no template is stored, a sensible default is used that adapts to time of day.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Holiday detection (priority over normal greeting)
# ──────────────────────────────────────────────────────────────────────────

def _detect_czech_holiday(now=None):
    """Return (holiday_key, holiday_message) or (None, None)."""
    now = now or datetime.now()
    m, d = now.month, now.day

    # Fixed-date holidays
    holidays = {
        (1, 1):   ("novy_rok",      "šťastný a požehnaný nový rok"),
        (5, 1):   ("svatek_prace",  "krásný svátek práce"),
        (5, 8):   ("osvobozeni",    "klidný Den vítězství"),
        (7, 5):   ("cyril_metodej", "krásný svátek Cyrila a Metoděje"),
        (7, 6):   ("mistr_jan",     "klidný svátek Mistra Jana Husa"),
        (9, 28):  ("sv_vaclav",     "krásný svátek svatého Václava"),
        (10, 28): ("vznik_csr",     "hezký státní svátek"),
        (11, 17): ("den_boje",      "klidný Den boje za svobodu"),
        (12, 24): ("stedry_den",    "krásný štědrý den"),
        (12, 25): ("bozi_hod",      "klidný Boží hod vánoční"),
        (12, 26): ("stepan",        "hezký svátek svatého Štěpána"),
        (12, 31): ("silvestr",      "veselý Silvestr"),
    }
    if (m, d) in holidays:
        return holidays[(m, d)]
    return (None, None)


def _time_of_day(now=None):
    """Return 'ráno' / 'dobrý den' / 'dobrý večer'."""
    now = now or datetime.now()
    h = now.hour
    if 5 <= h < 11:
        return "Dobré ráno"
    if 11 <= h < 17:
        return "Dobrý den"
    return "Dobrý večer"


# ──────────────────────────────────────────────────────────────────────────
# Template loading per senior
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_TEMPLATE = {
    "salutation": None,       # auto time-of-day
    "addressee": "",          # e.g. "babičko" / "dědečku" / "Valerie"
    "suffix": "přeji ti krásný den",
    "use_nameday": True,
    "use_holiday": True,
}


def load_user_template(user_id):
    """Load festive greeting template from memory_profiles. Falls back to default."""
    if not user_id:
        return dict(DEFAULT_TEMPLATE)
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        tmpl = profile.get("festive_greeting") or {}
        if not isinstance(tmpl, dict):
            tmpl = {}
        merged = dict(DEFAULT_TEMPLATE)
        merged.update({k: v for k, v in tmpl.items() if v is not None})
        # Auto-detect addressee from profile if not set
        if not merged["addressee"]:
            name = profile.get("name") or profile.get("first_name")
            if name:
                merged["addressee"] = str(name)
        return merged
    except Exception as e:
        logger.debug(f"load_user_template fallback: {e}")
        return dict(DEFAULT_TEMPLATE)


def save_user_template(user_id, template):
    """Persist festive greeting template into memory_profiles.data.festive_greeting."""
    if not user_id:
        return False
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        # Keep only known keys
        clean = {k: template.get(k) for k in DEFAULT_TEMPLATE.keys() if k in template}
        profile["festive_greeting"] = clean
        db_save_profile(str(user_id), profile)
        return True
    except Exception as e:
        logger.error(f"save_user_template: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────

def build_greeting(user_id=None, now=None, template=None):
    """Build the full festive greeting sentence in Czech.

    Returns dict:
      {
        'text': "Dobré ráno, Valerie. Dnes máš jmeniny Rudolf — přeji ti krásný den.",
        'parts': { salutation, addressee, holiday, nameday, suffix },
        'voice_mode': 'FESTIVE',
        'context': 'festive'
      }
    """
    now = now or datetime.now()
    tmpl = template or load_user_template(user_id)

    salutation = tmpl.get("salutation") or _time_of_day(now)
    addressee = (tmpl.get("addressee") or "").strip()
    suffix = (tmpl.get("suffix") or "").strip()

    # Holiday detection first — takes priority over nameday
    # (on a holiday, we celebrate the holiday, not the nameday)
    holiday_fragment = ""
    is_holiday = False
    if tmpl.get("use_holiday", True):
        hol_key, hol_msg = _detect_czech_holiday(now)
        if hol_msg:
            holiday_fragment = hol_msg
            is_holiday = True
            # Holiday suffix replaces normal suffix
            suffix = f"přeji ti {hol_msg}"

    # Nameday — skip on holiday (would sound odd: "dnes má svátek Štědrý den")
    nameday_fragment = ""
    if tmpl.get("use_nameday", True) and not is_holiday:
        try:
            from radim_shared import get_nameday
            nm = get_nameday(now.month, now.day)
            # Only use real personal names, not holiday placeholders like "Stedry den"
            if nm and not any(bad in nm.lower() for bad in
                              ["stedry", "silvest", "boží hod", "bozi hod",
                               "mistr jan", "svat", "nový rok", "novy rok"]):
                nameday_fragment = f"Dnes má svátek {nm}"
        except Exception:
            pass

    # Compose text
    pieces = []
    if addressee:
        pieces.append(f"{salutation}, {addressee}.")
    else:
        pieces.append(f"{salutation}.")

    if nameday_fragment:
        pieces.append(f"{nameday_fragment}.")

    if suffix:
        # Capitalize first letter
        s = suffix[0].upper() + suffix[1:] if suffix else suffix
        pieces.append(f"{s}.")

    text = " ".join(pieces)

    return {
        "text": text,
        "parts": {
            "salutation": salutation,
            "addressee": addressee,
            "nameday": nameday_fragment,
            "holiday": holiday_fragment,
            "suffix": suffix,
        },
        "voice_mode": "FESTIVE",
        "context": "festive",
        "timestamp": now.isoformat(),
    }
