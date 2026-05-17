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

SYSTÉMOVÉ INSTRUKCE PRO AKCE:
Když uživatel žádá akci, VŽDY přidej blok na konec odpovědi (za text pro uživatele):
---RADIM_ACTION---
{"type": "TYP", "payload": {"title": "...", "date": "YYYY-MM-DD", "time": "HH:MM"}}
---END_ACTION---

AKCE:
1. create_event — schůzka, návštěva, narozeniny, událost do kalendáře
   Příklad: "Přidej schůzku s doktorem na zítra v 10"
   → {"type":"create_event","payload":{"title":"Schůzka s doktorem","date":"2026-04-15","time":"10:00","type":"appointment"}}

2. create_task — připomínka, úkol (NE schůzka)
   Příklad: "Připomni mi zavolat dceři"
   → {"type":"create_task","payload":{"title":"Zavolat dceři","task_type":"reminder"}}

3. log_health — záznam léků/zdraví
   → {"type":"log_health","payload":{"medication":"warfarin","dosage":"5mg"}}

PRAVIDLA:
- Schůzky, návštěvy, narozeniny = VŽDY create_event
- Připomínky = create_task
- NEPTAT SE na detaily pokud jsou v textu — rovnou vytvořit
- Datum "zítra" = spočítej konkrétní YYYY-MM-DD
- Pokud akce není potřeba, nepřidávej blok"""


def _get_dynamic_system_prompt(mode='senior', voice_mode='HARMONY'):
    """Dynamický system prompt s časovým kontextem a rolí asistenta.

    v8.19.32 (Sprint 3-B): voice_mode propaguje k identity layeru —
    HARMONY = full vkus, ALERT = jemný, CRISIS = ztichlý.
    """
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
                time_context=_build_time_context(),
                voice_mode=voice_mode
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


def _safety_word_match(word, msg_lower):
    """Match safety keyword in message.

    For digit-only keywords (e.g. '155', '112'), use word-boundary regex
    so that phone numbers like '603111222' don't accidentally match '112'
    via substring containment. For text keywords, plain substring match is
    fine (we want 'spadl' to match 'spadl jsem v koupelně').
    """
    if word.isdigit():
        return bool(re.search(r'\b' + re.escape(word) + r'\b', msg_lower))
    return word in msg_lower


def detect_intent(message):
    """Detekce záměru ze zprávy — safety > medication > health > task > story > chat"""
    msg_lower = message.lower()

    for word in SAFETY_KEYWORDS:
        if _safety_word_match(word, msg_lower):
            return 'safety'

    # v398: Fuzzy safety for speech-impaired seniors ("pomo" → "pomoc")
    try:
        from speech_understanding import detect_safety_fuzzy
        match = detect_safety_fuzzy(message)
        if match and match["severity"] == "critical":
            return 'safety'
    except ImportError:
        pass

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

    v8.19.103: Wrap entire body in eventlet.spawn_n() — předtím SMS smyčka
    BLOKOVALA eventlet pool (každá Twilio HTTP call ~100ms × 10 caregivers
    = 1+s blokace), což shazovalo concurrent TTS requests s 503 (Service
    Unavailable). Plus SMS broken cache — pokud Twilio FROM není SMS-capable,
    cache fail po prvním pokusu a skip pro celou session.
    """
    try:
        import eventlet
        eventlet.spawn_n(_safety_notify_caregivers_async, user_id, message, severity)
    except ImportError:
        # eventlet not available, run sync (legacy)
        _safety_notify_caregivers_async(user_id, message, severity)


# v8.19.103: cache pro Twilio SMS-capability check
# X21.39: was permanent-latch (module global never reset). One Twilio config
# glitch disabled SMS for the entire dyno lifetime — heroku ps:restart was
# the only way to recover. Now: latch with 1-hour TTL so transient failures
# don't permanently disable the SMS safety path.
_TWILIO_SMS_BROKEN_UNTIL = 0.0  # epoch seconds; 0 = working


def _safety_notify_caregivers_async(user_id, message, severity):
    """Actual implementation of caregiver notification — called via eventlet.spawn_n.

    X21.39 SAFETY-CRITICAL FIX: caregiver SMS + admin push were NOT filtered
    by senior_id. Senior A's crisis SMS was sent to every active caregiver
    in iot_caregivers (across ALL seniors) → GDPR violation + alert fatigue.
    Admin push went to every admin/caregiver/family in chat_users system-wide.
    Now: caregivers filtered by room_id = str(user_id) (the convention used
    by iot_dashboard_routes when caregivers are added). Admin push filtered
    through senior_family_links + legacy caregiver_id from memory_profiles.
    """
    global _TWILIO_SMS_BROKEN_UNTIL
    try:
        from database import db_context
        import time

        caregivers = []
        with db_context() as db:
            # 1. Find caregivers FOR THIS SENIOR ONLY (X21.39 privacy fix)
            try:
                caregivers = db.execute(
                    "SELECT name, phone, email, notify_push, notify_sms FROM iot_caregivers "
                    "WHERE active = ? AND room_id = ?",
                    (True, str(user_id))
                ).fetchall()
            except Exception as e:
                logger.warning(f"SAFETY: caregiver lookup failed: {e}")

            # 2. Push to people LINKED TO THIS SENIOR — confirmed family links
            #    + legacy memory_profiles.caregiver_id. Plus SYSTEM admins
            #    (role='admin' only) so platform operators see crisis events
            #    cluster-wide for incident response.
            recipient_ids = set()

            # 2a. senior_family_links (modern)
            try:
                rows = db.execute(
                    "SELECT family_user_id FROM senior_family_links "
                    "WHERE senior_id = ? AND confirmed_at IS NOT NULL "
                    "AND revoked_at IS NULL AND notify_on_sos = ?",
                    (str(user_id), True)
                ).fetchall()
                for r in rows:
                    fid = r['family_user_id'] if 'family_user_id' in r.keys() else r[0]
                    if fid:
                        recipient_ids.add(fid)
            except Exception as e:
                logger.debug(f"SAFETY: senior_family_links lookup: {e}")

            # 2b. Legacy memory_profiles.caregiver_id
            try:
                from memory_helpers import db_load_profile
                profile = db_load_profile(str(user_id)) or {}
                legacy_cg = profile.get('caregiver_id')
                if legacy_cg:
                    recipient_ids.add(legacy_cg)
            except Exception:
                pass

            # 2c. System admins (operators) — NOT all caregivers/family
            try:
                rows = db.execute(
                    "SELECT id FROM chat_users WHERE role = 'admin' AND id != ?",
                    (user_id,)
                ).fetchall()
                for r in rows:
                    aid = r['id'] if 'id' in r.keys() else r[0]
                    if aid:
                        recipient_ids.add(aid)
            except Exception as e:
                logger.debug(f"SAFETY: admin lookup: {e}")

            try:
                from app import send_push_notification
                for rid in recipient_ids:
                    try:
                        send_push_notification(
                            rid,
                            f"KRIZOVA SITUACE — {severity.upper()}",
                            f"Uzivatel {user_id} potrebuje pomoc: {message[:100]}",
                            data={'type': 'safety_alert', 'severity': severity, 'user_id': user_id}
                        )
                        logger.info(f"SAFETY: Push sent to {rid}")
                    except Exception as e:
                        logger.debug(f"SAFETY: push to {rid} failed: {e}")
            except ImportError:
                logger.warning("SAFETY: Cannot import send_push_notification")

        # 3. SMS (outside db_context — Twilio HTTP call can be slow)
        # X21.39: was permanent latch; now 1-hour TTL on the SMS-broken flag
        # so a transient Twilio outage doesn't disable SMS until dyno restart.
        if time.time() < _TWILIO_SMS_BROKEN_UNTIL:
            logger.debug(
                f"SAFETY: SMS skipped — TWILIO unhealthy for "
                f"{int(_TWILIO_SMS_BROKEN_UNTIL - time.time())}s more"
            )
            return

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
                            err_str = str(sms_err)
                            logger.error(f"SAFETY: SMS failed to {cg_phone}: {err_str}")
                            # X21.39: was `_TWILIO_SMS_BROKEN = True` (permanent
                            # latch — only reset by dyno restart). Now a 1-hour
                            # TTL so a transient Twilio config glitch doesn't
                            # permanently disable the SMS safety path.
                            if 'not SMS-capable' in err_str or "is not a valid SMS" in err_str:
                                logger.warning(f"SAFETY: TWILIO_PHONE_NUMBER {twilio_from} is not SMS-capable — disabling SMS for 1 hour")
                                _TWILIO_SMS_BROKEN_UNTIL = time.time() + 3600
                                return  # stop iteration — won't work for any number
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

        # v8.19.108: audit log nyní přes hash chain audit() místo přímého INSERT.
        try:
            from audit_log import audit
            audit(
                'safety.crisis_alert',
                actor_user_id=user_id,
                resource_type='safety',
                severity='critical' if severity == 'critical' else 'warning',
                outcome='success',
                metadata={'severity': severity, 'message_excerpt': message[:200]},
            )
        except Exception as audit_err:
            logger.warning(f"SAFETY audit log failed: {audit_err}")

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
