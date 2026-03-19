# ============================================
# RADIM ORCHESTRATOR HELPERS
# ============================================
# Extracted from radim_orchestrator.py for modularity.
#
# Contains:
#   - Config constants (API keys, WP settings)
#   - User ID extraction (_extract_user_id)
#   - Weather context (_fetch_weather_context, _build_time_context)
#   - Dynamic system prompt (_get_dynamic_system_prompt, _ORCH_ACTION_HINT)
#   - Intent detection (keywords, detect_intent)
#   - Safety handlers (_safety_notify_caregivers, _safety_log_crisis_event)
#   - Czech time/date extractors (extract_time, extract_date)
#
# Version: 1.0.0

import os
import re
import json
import time as _time
import logging
from datetime import datetime, timedelta, date

import requests

logger = logging.getLogger(__name__)

# ============================================
# OPTIONAL IMPORTS (graceful fallback)
# ============================================

# 🏠 System Prompt v3.0 — domácí asistent s časovým kontextem
try:
    from radim_system_prompt import get_radim_prompt as _sys_get_prompt
    _ORCH_SYS_PROMPT = True
except ImportError:
    _ORCH_SYS_PROMPT = False

# ============================================
# KONFIGURACE
# ============================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')


# ============================================
# USER ID EXTRACTION (v231 — žádný sdílený default-senior)
# ============================================
def _extract_user_id(auth_user_from_g, fallback_from_data=None):
    """Bezpečná extrakce user_id. Nikdy nevrátí sdílený 'default-senior'."""
    auth_user = auth_user_from_g or {}
    uid = str(auth_user.get('id', '')).strip()
    if uid and uid != '0':
        return uid
    # Fallback z request body
    if fallback_from_data:
        body_uid = str(fallback_from_data).strip()
        if body_uid and body_uid not in ('', 'default-senior', '0'):
            return body_uid
    # Unikátní anonymous ID — žádné sdílení dat
    return f'anon-{int(datetime.utcnow().timestamp())}'


# Czech holidays — centralized in radim_shared.py
from radim_shared import CZECH_HOLIDAYS as _CZECH_HOLIDAYS


# ============================================
# WEATHER CONTEXT (open-meteo.com, free, no API key)
# ============================================
_weather_cache = {'data': None, 'ts': 0}


def _fetch_weather_context():
    """Počasí z open-meteo.com. Cache 30 min, timeout 3s, tichý fail."""
    if _weather_cache['data'] and (_time.time() - _weather_cache['ts']) < 1800:
        return _weather_cache['data']
    try:
        resp = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': 50.08, 'longitude': 14.42,
            'current': 'temperature_2m,weather_code,wind_speed_10m',
            'timezone': 'Europe/Prague', 'forecast_days': 1
        }, timeout=3)
        if resp.status_code == 200:
            cur = resp.json().get('current', {})
            temp = cur.get('temperature_2m')
            wind = cur.get('wind_speed_10m')
            code = cur.get('weather_code', 0)
            wmo = {0: 'jasno', 1: 'převážně jasno', 2: 'polojasno', 3: 'zataženo',
                   45: 'mlha', 48: 'mrznoucí mlha',
                   51: 'mrholení', 53: 'mrholení', 55: 'silné mrholení',
                   61: 'slabý déšť', 63: 'déšť', 65: 'silný déšť',
                   71: 'slabé sněžení', 73: 'sněžení', 75: 'silné sněžení',
                   80: 'přeháňky', 81: 'přeháňky', 82: 'silné přeháňky',
                   95: 'bouřka', 96: 'bouřka s krupobitím'}
            cond = wmo.get(code, '')
            wind_str = f", vítr {wind} km/h" if wind and wind > 5 else ""
            result = f"\nPočasí v Praze: {temp}°C, {cond}{wind_str}."
            _weather_cache.update(data=result, ts=_time.time())
            return result
    except Exception:
        pass
    return ""


def _build_time_context():
    """Sestaví časový kontext pro system prompt — delegates to radim_shared + adds weather."""
    try:
        from radim_shared import build_time_context_string
        base = build_time_context_string()
        # Orchestrator adds weather context on top
        weather = _fetch_weather_context()
        return f"{base}{weather}"
    except Exception as e:
        logger.warning(f"Time context warning: {e}")
        return ""


# Orchestrator-specific action hint (appended to system prompt)
_ORCH_ACTION_HINT = """

TECHNICKÁ POZNÁMKA (ignoruj ji v konverzaci, slouží jen pro systém):
Pokud uživatel žádá konkrétní akci (připomínka, úkol, záznam), přidej na konec:
---RADIM_ACTION---
{"type": "create_task|update_task|log_health|safety_alert|none", "payload": {}, "ui": {"suggested_buttons": []}}
---END_ACTION---
Pokud akce není potřeba, nepřidávej nic."""


def _get_dynamic_system_prompt(mode='senior'):
    """Dynamický system prompt s časovým kontextem a rolí asistenta."""
    if _ORCH_SYS_PROMPT:
        try:
            user_type = 'senior' if mode == 'senior' else mode
            if mode == 'rodina':
                user_type = 'caregiver'
            elif mode == 'technik':
                user_type = 'academic'
            prompt = _sys_get_prompt(
                mode='full',
                user_type=user_type,
                time_context=_build_time_context()
            )
            return prompt + _ORCH_ACTION_HINT
        except Exception as e:
            logger.warning(f"Dynamic prompt warning: {e}")
    # Fallback: short centralized prompt from radim_system_prompt.py
    from radim_system_prompt import RADIM_SYSTEM_PROMPT_SHORT
    return RADIM_SYSTEM_PROMPT_SHORT + _ORCH_ACTION_HINT


# ============================================
# INTENT DETECTION
# ============================================
TASK_KEYWORDS = ['připomeň', 'nastav', 'úkol', 'připomínka', 'nezapomeň', 'zapiš', 'naplánuj']
MEDICATION_KEYWORDS = ['lék', 'léky', 'tableta', 'tablety', 'prášek', 'prášky', 'prednison',
                       'vzal jsem', 'bral jsem', 'zapomněl', 'medikace', 'dávka', 'dávku',
                       'ibuprofen', 'paralen', 'aspirin', 'inzulín']
HEALTH_KEYWORDS = ['bolí', 'nemohu', 'špatně', 'doktor', 'nemocnice', 'unavený']
SAFETY_KEYWORDS = [
    # Falls
    'spadl', 'spadla', 'pád', 'upadl', 'upadla', 'padl', 'padla',
    # Breathing/cardiac
    'nemohu dýchat', 'nemůžu dýchat', 'nemazu dychat', 'bolest na hrudi', 'infarkt', 'mrtvice',
    # Emergency services
    'záchranka', 'zachranka', '155', '112',
    # Panic/distress
    'panika', 'pomoc',
    # Suicidal ideation (v327: C3 fix)
    'chci umřít', 'chci umrit', 'chci zemřít', 'chci zemrit',
    'nechci žít', 'nechci zit', 'sebevražd', 'sebevrazd',
    'oběsit', 'obesit', 'skočit z', 'skocit z', 'předávkov', 'predavkov',
    # Wandering/disorientation (v327: C4 fix)
    'ztratil jsem se', 'ztratila jsem se', 'nevím kde jsem', 'nevim kde jsem',
    'kde to jsem', 'kde jsem', 'zabloudil', 'zabloudila',
    # Choking/aspiration (v327: C5 fix)
    'dusím se', 'dusim se', 'nemůžu polykat', 'nemuzu polykat', 'nemůžu polknout',
    'dávím se', 'davim se',
    # Immobility
    'nehýbu se', 'nehybu se', 'nehýbám', 'nehybam', 'nemůžu vstát', 'nemuzu vstat',
    # Unconsciousness
    'bezvědomí', 'bezvedomi', 'omdlel', 'omdlela', 'mdloba',
    # Medication emergency
    'vzal jsem dvakrát', 'vzala jsem dvakrát', 'moc prášků', 'moc prasek',
]
STORY_KEYWORDS = ['příběh', 'story', 'instagram', 'facebook', 'pozvánka']


def detect_intent(message):
    """Detekce záměru ze zprávy — safety > medication > health > task > story > chat"""
    msg_lower = message.lower()

    for word in SAFETY_KEYWORDS:
        if word in msg_lower:
            return 'safety'

    for word in MEDICATION_KEYWORDS:
        if word in msg_lower:
            return 'medication'

    for word in HEALTH_KEYWORDS:
        if word in msg_lower:
            return 'health'

    for word in TASK_KEYWORDS:
        if word in msg_lower:
            return 'task'

    for word in STORY_KEYWORDS:
        if word in msg_lower:
            return 'story'

    return 'chat'


# ============================================
# v327: SAFETY NOTIFICATION & AUDIT TRAIL
# ============================================

def _safety_notify_caregivers(user_id, message, severity):
    """Send push + SMS notifications to caregivers (runs async from v398).
    This is the CRITICAL C1 fix — previously the system said 'calling help'
    but never actually sent anything.
    """
    try:
        from database import db_context

        with db_context() as db:
            # 1. Find caregivers
            caregivers = db.execute(
                "SELECT name, phone, email, notify_push, notify_sms FROM iot_caregivers WHERE active = ?",
                (True,)
            ).fetchall()

            # 2. Push to admins/caregivers/family
            try:
                from app import send_push_notification
                admins = db.execute(
                    "SELECT id FROM chat_users WHERE role IN ('admin', 'caregiver', 'family') AND id != ?",
                    (user_id,)
                ).fetchall()
                for admin in admins:
                    admin_id = admin.get('id') or admin[0]
                    send_push_notification(
                        admin_id,
                        f"KRIZOVA SITUACE — {severity.upper()}",
                        f"Uzivatel {user_id} potrebuje pomoc: {message[:100]}",
                        data={'type': 'safety_alert', 'severity': severity, 'user_id': user_id}
                    )
                    logger.info(f"SAFETY: Push sent to {admin_id}")
            except ImportError:
                logger.warning("SAFETY: Cannot import send_push_notification")

        # 3. SMS (outside db_context — Twilio HTTP call can be slow)
        try:
            twilio_sid = os.environ.get('TWILIO_ACCOUNT_SID')
            twilio_token = os.environ.get('TWILIO_AUTH_TOKEN')
            twilio_from = os.environ.get('TWILIO_PHONE_NUMBER')

            if twilio_sid and twilio_token and twilio_from:
                from twilio.rest import Client as TwilioClient
                twilio_client = TwilioClient(twilio_sid, twilio_token)

                for cg in caregivers:
                    cg_phone = cg.get('phone') or cg[1]
                    cg_sms = cg.get('notify_sms') or cg[4]
                    cg_name = cg.get('name') or cg[0]
                    if cg_sms and cg_phone:
                        try:
                            twilio_client.messages.create(
                                body=f"RADIM KRIZOVY ALERT [{severity.upper()}]: Uzivatel {user_id} - {message[:120]}",
                                from_=twilio_from,
                                to=cg_phone
                            )
                            logger.info(f"SAFETY: SMS sent to {cg_name} at {cg_phone}")
                        except Exception as sms_err:
                            logger.error(f"SAFETY: SMS failed to {cg_phone}: {sms_err}")
        except ImportError:
            logger.warning("SAFETY: Twilio library not available for SMS")

    except Exception as e:
        logger.error(f"CRITICAL SAFETY NOTIFICATION FAILURE for user {user_id}: {e}")


def _safety_log_crisis_event(user_id, message, severity):
    """Log crisis event to audit trail (runs async from v398).
    Records in both crisis_events and audit_log tables.
    """
    try:
        from database import db_context

        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO crisis_events (user_id, message_excerpt, brain_c) VALUES (?, ?, ?)",
                (user_id, message[:300], 30.0 if severity == 'critical' else 20.0)
            )
            db.execute(
                "INSERT INTO audit_log (user_id, action, resource, detail) VALUES (?, ?, ?, ?)",
                (user_id, 'crisis_alert', 'safety',
                 json.dumps({'severity': severity, 'message': message[:200]}, ensure_ascii=False))
            )
        logger.info(f"SAFETY: Crisis event logged for user {user_id}, severity={severity}")

    except Exception as e:
        logger.error(f"SAFETY: Failed to log crisis event: {e}")


# ============================================
# CZECH TIME/DATE EXTRACTORS
# ============================================

def extract_time(message):
    """Robustní extrakce času z české zprávy (v231).
    Zvládá: '15:30', 'v 15 hodin', 'za 2 hodiny', 'za půl hodiny',
    'za 30 minut', 'ráno', 'odpoledne', 'večer', 'v noci'.
    """
    msg = message.lower()
    now = datetime.now()

    # 1. Relativní: "za N hodin/hodiny/hodinu"
    m = re.search(r'za\s+(\d+)\s+hodin[yua]?', msg)
    if m:
        future = now + timedelta(hours=int(m.group(1)))
        return f"{future.hour:02d}:{future.minute:02d}"

    # 2. Relativní: "za půl hodiny"
    if re.search(r'za\s+p[uů]l\s+hodin', msg):
        future = now + timedelta(minutes=30)
        return f"{future.hour:02d}:{future.minute:02d}"

    # 3. Relativní: "za N minut"
    m = re.search(r'za\s+(\d+)\s+minut', msg)
    if m:
        future = now + timedelta(minutes=int(m.group(1)))
        return f"{future.hour:02d}:{future.minute:02d}"

    # 4. Absolutní: "v 15 hodin", "ve 3 hodiny"
    m = re.search(r'v[e]?\s+(\d{1,2})\s+hodin', msg)
    if m:
        hour = int(m.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"

    # 5. Absolutní: "15:30", "15.30", "8:00"
    m = re.search(r'(\d{1,2})[:\.](\d{2})', msg)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # 6. Pojmenované: "ráno", "dopoledne", "v poledne", "odpoledne", "večer", "v noci"
    if 'ráno' in msg or 'dopoledne' in msg:
        return '08:00'
    if 'poledne' in msg:
        return '12:00'
    if 'odpoledne' in msg:
        return '14:00'
    if 'večer' in msg:
        return '18:00'
    if 'noci' in msg or 'v noc' in msg:
        return '22:00'

    return None


def extract_date(message):
    """Extrakce data z české zprávy (v231).
    Zvládá: 'zítra', 'pozítří', 'dnes', české dny v týdnu ('v pondělí').
    Vrací YYYY-MM-DD nebo None.
    """
    msg = message.lower()
    today = date.today()

    if 'pozítří' in msg:
        return (today + timedelta(days=2)).isoformat()
    if 'zítra' in msg or 'zejtra' in msg:
        return (today + timedelta(days=1)).isoformat()
    if 'dnes' in msg or 'dneska' in msg:
        return today.isoformat()

    # České dny v týdnu → nejbližší budoucí výskyt
    _cz_days = {
        'pondělí': 0, 'úterý': 1, 'střed': 2, 'čtvrtek': 3,
        'pátek': 4, 'sobot': 5, 'neděl': 6
    }
    for name, weekday in _cz_days.items():
        if name in msg:
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # příští týden pokud je dnes ten den
            return (today + timedelta(days=days_ahead)).isoformat()

    return None


logger.info("✅ Radim Helpers loaded — config, intent, safety, time/date")
