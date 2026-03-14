# ============================================
# RADIM WHATSAPP ORCHESTRATOR
# ============================================
# Version: 1.0.0
# WhatsApp styl chat s action JSON

from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit
import requests
import json
import re
import os
import base64
import time as _time
from datetime import datetime, timedelta, date
from xml.sax.saxutils import escape as xml_escape
import logging

logger = logging.getLogger(__name__)

radim_bp = Blueprint('radim', __name__)

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _orch_predict_C, calculate_emotions as _orch_emotions,
        calculate_speech_params as _orch_speech_params, classify_state as _orch_classify
    )
    _ORCH_ANT_AVAILABLE = True
except ImportError:
    _ORCH_ANT_AVAILABLE = False

# Intent Resolver (v272 — local NLU)
try:
    from intent_resolver import resolve_intent as _resolve_intent
    _INTENT_RESOLVER = True
except ImportError:
    _INTENT_RESOLVER = False

# Memory system integration
try:
    from memory_routes import (
        build_personalized_prompt as _orch_build_prompt,
        get_conversation_messages as _orch_get_history,
        record_interaction as _orch_record,
        detect_mood as _orch_detect_mood
    )
    _ORCH_MEMORY_AVAILABLE = True
except ImportError:
    _ORCH_MEMORY_AVAILABLE = False

# 🧠 Brain Engine — Ψ(t) = (C, E, R, S)
try:
    from radim_brain_routes import (
        compute_psi_state as _brain_psi,
        reinforcement_update as _brain_reinforce,
        decision_model as _brain_decision,
        derive_text_empathy_proxies as _brain_proxies,
        get_brain_speech_for_user as _brain_speech_for_user
    )
    _ORCH_BRAIN_AVAILABLE = True
except ImportError:
    _ORCH_BRAIN_AVAILABLE = False

# 🎵 Text Rhythm Engine — matematika řídí styl textu
try:
    from text_rhythm import (
        estimate_C_alpha_from_text as _tr_estimate,
        calculate_text_params as _tr_calc,
        build_anticipation_prompt as _tr_prompt,
        get_anticipation_metadata as _tr_meta,
        get_adjusted_generation_config as _tr_gen_config,
        enforce_crisis_limits as _tr_enforce
    )
    _ORCH_TEXT_RHYTHM = True
except ImportError:
    _ORCH_TEXT_RHYTHM = False

# 🏠 System Prompt v3.0 — domácí asistent s časovým kontextem
try:
    from radim_system_prompt import get_radim_prompt as _sys_get_prompt
    _ORCH_SYS_PROMPT = True
except ImportError:
    _ORCH_SYS_PROMPT = False

# 📋 Task Service — úkoly a léky s persistencí
try:
    from task_service import (
        create_task as _ts_create,
        get_tasks as _ts_get,
        complete_task as _ts_complete,
        log_medication as _ts_log_med,
        get_medication_history as _ts_med_history,
        build_tasks_context as _ts_context
    )
    _ORCH_TASK_SERVICE = True
except ImportError:
    _ORCH_TASK_SERVICE = False

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

# Orchestrator-specific action hint (appended to system prompt)
_ORCH_ACTION_HINT = """

TECHNICKÁ POZNÁMKA (ignoruj ji v konverzaci, slouží jen pro systém):
Pokud uživatel žádá konkrétní akci (připomínka, úkol, záznam), přidej na konec:
---RADIM_ACTION---
{"type": "create_task|update_task|log_health|safety_alert|none", "payload": {}, "ui": {"suggested_buttons": []}}
---END_ACTION---
Pokud akce není potřeba, nepřidávej nic."""

# ============================================
# INTENT DETECTION
# ============================================
TASK_KEYWORDS = ['připomeň', 'nastav', 'úkol', 'připomínka', 'nezapomeň', 'zapiš', 'naplánuj']
MEDICATION_KEYWORDS = ['lék', 'léky', 'tableta', 'tablety', 'prášek', 'prášky', 'prednison',
                       'vzal jsem', 'bral jsem', 'zapomněl', 'medikace', 'dávka', 'dávku',
                       'ibuprofen', 'paralen', 'aspirin', 'inzulín']
HEALTH_KEYWORDS = ['bolí', 'nemohu', 'špatně', 'doktor', 'nemocnice', 'unavený']
SAFETY_KEYWORDS = ['spadl', 'pád', 'nemohu dýchat', 'bolest na hrudi', 'záchranka', '155', '112', 'panika']
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

# ============================================
# GEMINI AI CALL
# ============================================
def call_gemini_whatsapp(message, context=None, mode='senior', personalized_prompt='', history=None, anticipation_prompt='', gen_config=None):
    """Volání Gemini s WhatsApp promptem + personalizace + historie + rytmus"""
    if not GEMINI_API_KEY:
        return None, None

    try:
        # 🏠 Dynamický system prompt s časem, rolí, kontextem
        system = _get_dynamic_system_prompt(mode)

        # 🧠 Add personalized prompt from memory (name, interests, style, mood)
        if personalized_prompt:
            system += personalized_prompt

        # 🎵 Add anticipation-driven text rhythm instructions
        if anticipation_prompt:
            system += anticipation_prompt

        context_text = ""
        if context:
            context_text = f"\n\nKontext:\n{json.dumps(context, ensure_ascii=False)}"

        # 📜 Add conversation history for continuity
        history_text = ""
        if history:
            history_text = "\n\nPředchozí konverzace:\n"
            for msg in history[-6:]:  # Last 6 messages (3 turns)
                role_label = "Uživatel" if msg["role"] == "user" else "Radim"
                history_text += f"{role_label}: {msg['content']}\n"

        full_prompt = f"{system}{context_text}{history_text}\n\nUživatel: {message}\nRadim:"

        # Generation config — adjusted by Anticipation Engine
        temperature = gen_config["temperature"] if gen_config else 0.7
        max_tokens = gen_config["max_tokens"] if gen_config else 500

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "topP": 0.9
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'candidates' in data and data['candidates']:
                full_response = data['candidates'][0]['content']['parts'][0]['text'].strip()
                return parse_radim_response(full_response)
        
        return None, None
        
    except Exception as e:
        logger.error(f"Gemini WhatsApp error: {e}")
        return None, None

def parse_radim_response(full_response):
    """Parsovat odpověď Radima"""
    text_response = full_response
    action_json = None
    
    action_match = re.search(r'---RADIM_ACTION---\s*(\{.*?\})\s*---END_ACTION---', full_response, re.DOTALL)
    
    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            text_response = full_response[:action_match.start()].strip()
        except json.JSONDecodeError:
            pass
    
    return text_response, action_json

# ============================================
# STORY TEMPLATES
# ============================================
STORY_TEMPLATES = [
    {
        'id': 'kolibri_plus_one_01',
        'title': 'Plus One – pozvánka',
        'description': 'Pozvánka na akci s filozofií Plus One',
        'platform': ['instagram', 'facebook'],
        'fields': {'hook': 'Úvodní věta', 'value': 'Co člověk získá', 'cta': 'Výzva k akci'},
        'prompt_hint': 'Krátké věty, Kolibri tón, plus jedna.',
        'emoji': '☕'
    },
    {
        'id': 'kolibri_tip_01',
        'title': 'Tip od Kafánka',
        'description': 'Krátký užitečný tip pro seniory',
        'platform': ['instagram', 'facebook', 'tiktok'],
        'fields': {'tip_title': 'Název tipu', 'tip_content': 'Obsah tipu', 'benefit': 'Proč to pomůže'},
        'prompt_hint': 'Senior-friendly, jednoduché slova.',
        'emoji': '💡'
    },
    {
        'id': 'kolibri_story_01',
        'title': 'Příběh z kavárny',
        'description': 'Krátký příběh z Kavárny Kolibri',
        'platform': ['instagram', 'facebook'],
        'fields': {'situation': 'Co se stalo', 'emotion': 'Jak se cítili', 'lesson': 'Co jsme se naučili'},
        'prompt_hint': 'Autentický, lidský, bez přehánění.',
        'emoji': '📖'
    }
]

# ============================================
# ENDPOINTS
# ============================================

@radim_bp.route('/api/radim/chat', methods=['POST', 'OPTIONS'])
@optional_auth
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def radim_chat():
    """Hlavní WhatsApp-styl chat endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        message = data.get('message', '')
        # Prefer JWT user_id, fallback to request body (v231: unique per-session)
        user_id = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
        mode = data.get('mode', 'senior')
        context = data.get('context', {})
        emotional_context = data.get('emotional_context', '')

        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400

        # Add emotional context from frontend (RadimEmpathyBridge)
        if emotional_context:
            context['emotional_state'] = emotional_context

        # v321: Neuron context from frontend KafanekNeurons
        neuron_ctx = data.get('neuron_context')
        if neuron_ctx and isinstance(neuron_ctx, dict):
            ntype = neuron_ctx.get('type', 'unknown')
            ntone = neuron_ctx.get('tone', 'patient')
            nhint = neuron_ctx.get('hint', '')
            context['neuron_intervention'] = neuron_ctx

        intent = detect_intent(message)
        
        if intent == 'task':
            context['extracted_time'] = extract_time(message)
            context['extracted_date'] = extract_date(message)
        
        if intent == 'safety':
            severity = 'critical' if any(w in message.lower() for w in ['155', '112', 'záchranka']) else 'high'
            return jsonify({
                'success': True,
                'response': '🚨 Zůstaňte v klidu! Volám pomoc a informuji rodinu.',
                'radim_action': {
                    'type': 'safety_alert',
                    'payload': {'user_id': user_id, 'severity': severity, 'message': message},
                    'ui': {'suggested_buttons': ['Zavolat 155', 'Kontaktovat rodinu', 'Jsem v pořádku']}
                },
                'intent': 'safety',
                'mode': mode
            })
        
        # 🧠 Load personalization and history from memory
        personalized = ''
        history = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                personalized = _orch_build_prompt(user_id)
                history = _orch_get_history(user_id, limit=6)
            except Exception as mem_err:
                logger.warning(f"Memory load warning: {mem_err}")

        # 📋 Load pending tasks context for AI awareness
        if _ORCH_TASK_SERVICE:
            try:
                tasks_ctx = _ts_context(user_id)
                if tasks_ctx:
                    personalized += tasks_ctx
            except Exception as tc_err:
                logger.warning(f"Tasks context warning: {tc_err}")

        # 🎵 Text Rhythm: matematika → styl textu
        anticipation_prompt = ''
        anticipation_meta = None
        gen_config = None
        C = 5.0      # default: klidný stav
        alpha = 0.0   # default: bez aktivace
        mood = "neutral"
        if _ORCH_TEXT_RHYTHM:
            try:
                C_val = data.get('C')
                alpha_val = data.get('alpha')

                if C_val is not None and alpha_val is not None:
                    C = float(C_val)
                    alpha = float(alpha_val)
                else:
                    # Derive from message text + mood + personalized baseline
                    mood = _orch_detect_mood(message) if _ORCH_MEMORY_AVAILABLE else "neutral"
                    baseline_C = None
                    if _ORCH_MEMORY_AVAILABLE:
                        try:
                            from memory_routes import _db_load_profile
                            _prof = _db_load_profile(user_id)
                            baseline_C = _prof.get('baseline_C')
                            if baseline_C is not None:
                                baseline_C = float(baseline_C)
                        except Exception:
                            pass
                    C, alpha = _tr_estimate(message, mood, user_baseline_C=baseline_C)

                text_result = _tr_calc(C, alpha)
                anticipation_prompt = _tr_prompt(text_result)
                anticipation_meta = _tr_meta(text_result)
                gen_config = _tr_gen_config(text_result)
            except Exception as tr_err:
                logger.warning(f"Text rhythm warning (non-fatal): {tr_err}")

        # 🧠 Brain Engine: Ψ(t) = (C, E, R, S) — stavový vektor vědomí
        brain_meta = None
        if _ORCH_BRAIN_AVAILABLE:
            try:
                proxies = _brain_proxies(message, mood, alpha)
                psi_state = _brain_psi(
                    C, alpha,
                    proxies["voice_tone"], proxies["hrv"], proxies["speech_tempo"],
                    user_id=user_id
                )
                decision = _brain_decision(
                    C, psi_state["psi"]["E"], psi_state["psi"]["R"], psi_state["psi"]["S"]
                )
                brain_meta = {
                    "psi": psi_state["psi"],
                    "mode": psi_state["mode"],
                    "decision": decision["level"],
                    "coherence": psi_state["coherence"],
                    "phi_index": psi_state.get("phi_index"),
                    "rho_stability": psi_state.get("rho_stability")
                }
                # v282: Include rhythm return data if available
                if psi_state.get("rhythm_return"):
                    brain_meta["rhythm_return"] = psi_state["rhythm_return"]
                personalized += f"\n\n[RADIM Brain: mode={psi_state['mode']}, coherence={psi_state['coherence']:.2f}]\n{decision['instructions']}"
            except Exception as brain_err:
                logger.warning(f"Brain warning (non-fatal): {brain_err}")

        # 🎯 Intent Resolver: short-circuit simple queries locally (v272)
        action_json = None
        text_response = None
        _resolved_intent = intent  # from detect_intent() above
        if _INTENT_RESOLVER:
            try:
                _brain_mode = brain_meta.get("mode", "HARMONY") if brain_meta else "HARMONY"
                _resolved_text, _resolved_intent, _resolved_meta = _resolve_intent(message, user_id, _brain_mode)
                if _resolved_text:
                    text_response = _resolved_text
                    logger.info(f"🎯 Intent '{_resolved_intent}' resolved locally for {user_id}")
            except Exception as ir_err:
                logger.warning(f"Intent resolver warning (non-fatal): {ir_err}")

        # v321+v3: Inject neuron intervention + rhythm into AI prompt
        if neuron_ctx:
            ntype = neuron_ctx.get('type', 'unknown')
            ntone = neuron_ctx.get('tone', 'patient')
            nhint = neuron_ctx.get('hint', '')
            nrhythm = neuron_ctx.get('rhythm')
            personalized += f"\n\n═══ NEURONOVÁ INTERVENCE ({ntype}) ═══\n"
            personalized += f"Tón: {ntone}. "
            if nhint:
                personalized += f"Nápověda: {nhint}\n"
            if nrhythm:
                rmode = nrhythm.get('mode', 'HARMONY')
                personalized += f"[Ψ-rytmus: {rmode}, koherence: {nrhythm.get('coherence', 0.8):.1f}] "
            personalized += "Přizpůsob odpověď — buď extra trpělivý, klidný a empatický."

        if text_response is None:
            text_response, action_json = call_gemini_whatsapp(
                message, context, mode, personalized, history,
                anticipation_prompt, gen_config
            )

        if not text_response:
            text_response = "Promiňte, zkuste to za chvíli. 🙏"

        # ✂️ Crisis enforcement: hard limit na počet vět (ALERT/CRISIS)
        if _ORCH_TEXT_RHYTHM and anticipation_meta and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                text_response = _tr_enforce(text_response, {
                    'state': anticipation_meta.get('state', 'HARMONY'),
                    'params': anticipation_meta.get('text_params', {})
                })
            except Exception:
                pass  # Non-fatal — AI instrukce stačí jako fallback

        # 📋 Process AI actions (create_task, log_health from ---RADIM_ACTION---)
        if action_json and _ORCH_TASK_SERVICE:
            try:
                action_type = action_json.get('type', 'none')
                payload = action_json.get('payload', {})

                if action_type == 'create_task':
                    task = _ts_create(
                        user_id=user_id,
                        title=payload.get('title', 'Připomínka od Radima'),
                        task_type=payload.get('task_type', 'reminder'),
                        scheduled_time=payload.get('time') or extract_time(message),
                        scheduled_date=payload.get('date') or extract_date(message),
                        description=payload.get('description')
                    )
                    if task:
                        action_json['created_task'] = task
                        logger.info(f"📋 AI created task: #{task['id']} '{task['title']}'")

                elif action_type == 'log_health':
                    _ts_log_med(
                        user_id=user_id,
                        medication_name=payload.get('medication', payload.get('name', 'nespecifikováno')),
                        dosage=payload.get('dosage'),
                        notes=payload.get('notes', message[:200])
                    )
                    logger.info(f"💊 AI logged medication for {user_id}")
            except Exception as act_err:
                logger.warning(f"Action processing warning: {act_err}")

        # 🧠 Record interaction to memory (v283: + brain state for baseline_C learning)
        if _ORCH_MEMORY_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                _brain_C_val = brain_meta["psi"]["C"] if brain_meta else None
                _brain_mode_val = brain_meta["mode"] if brain_meta else None
                _orch_record(user_id, message, text_response, brain_C=_brain_C_val, brain_mode=_brain_mode_val)
            except Exception as rec_err:
                logger.warning(f"Memory record warning: {rec_err}")

        # 🧠 Brain reinforcement: adapt per-user after response (v282: richer signal)
        if _ORCH_BRAIN_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                success = intent != "safety" and bool(text_response)
                _brain_reinforce(success, user_id=user_id)
            except Exception:
                pass

        result = {
            'success': True,
            'response': text_response,
            'radim_action': action_json,
            'intent': _resolved_intent if _INTENT_RESOLVER else intent,
            'mode': mode,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        if anticipation_meta:
            result['anticipation'] = anticipation_meta
        if brain_meta:
            result['brain'] = brain_meta
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@radim_bp.route('/api/radim/tasks', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def radim_tasks():
    """📋 Task management endpoint — reálná persistentní implementace"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _ORCH_TASK_SERVICE:
        return jsonify({'success': False, 'error': 'Task service unavailable'}), 503

    if request.method == 'GET':
        status = request.args.get('status')
        task_type = request.args.get('type')
        date_filter = request.args.get('date')
        tasks = _ts_get(user_id, status=status, task_type=task_type, date_filter=date_filter)
        return jsonify({'success': True, 'tasks': tasks, 'count': len(tasks), 'user_id': user_id})

    elif request.method == 'POST':
        data = request.json or {}
        task = _ts_create(
            user_id=user_id,
            title=data.get('title', 'Nový úkol'),
            task_type=data.get('type', 'reminder'),
            scheduled_time=data.get('time'),
            scheduled_date=data.get('date'),
            recurrence=data.get('recurrence', 'once'),
            priority=data.get('priority', 'normal'),
            description=data.get('description'),
            metadata=data.get('metadata')
        )
        if task:
            return jsonify({'success': True, 'task': task, 'message': 'Úkol vytvořen ✅'})
        return jsonify({'success': False, 'error': 'Nepodařilo se vytvořit úkol'}), 500

    elif request.method == 'PUT':
        data = request.json or {}
        task_id = data.get('task_id') or data.get('id')
        if not task_id:
            return jsonify({'success': False, 'error': 'task_id je povinné'}), 400
        ok = _ts_complete(task_id, user_id)
        return jsonify({'success': ok, 'message': 'Úkol splněn ✅' if ok else 'Chyba při splnění'})

    elif request.method == 'DELETE':
        data = request.json or {}
        task_id = data.get('task_id') or data.get('id')
        if not task_id:
            return jsonify({'success': False, 'error': 'task_id je povinné'}), 400
        from task_service import delete_task as _ts_delete
        ok = _ts_delete(task_id, user_id)
        return jsonify({'success': ok, 'message': 'Úkol smazán' if ok else 'Chyba'})


@radim_bp.route('/api/radim/medications', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def radim_medications():
    """💊 Medication tracking endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _ORCH_TASK_SERVICE:
        return jsonify({'success': False, 'error': 'Task service unavailable'}), 503

    if request.method == 'GET':
        days = request.args.get('days', 7, type=int)
        history = _ts_med_history(user_id, days=days)
        med_tasks = _ts_get(user_id, task_type='medication')
        return jsonify({
            'success': True,
            'medications': med_tasks,
            'history': history,
            'count': len(med_tasks),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    elif request.method == 'POST':
        data = request.json or {}
        name = data.get('name', data.get('medication_name', ''))
        if not name:
            return jsonify({'success': False, 'error': 'Název léku je povinný'}), 400
        ok = _ts_log_med(
            user_id=user_id,
            medication_name=name,
            task_id=data.get('task_id'),
            dosage=data.get('dosage'),
            notes=data.get('notes')
        )
        return jsonify({
            'success': ok,
            'message': f'Lék {name} zaznamenán ✅' if ok else 'Chyba při záznamu'
        })

@radim_bp.route('/api/radim/stories/templates', methods=['GET', 'OPTIONS'])
def radim_story_templates():
    """Story templates endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    platform = request.args.get('platform')
    templates = STORY_TEMPLATES
    
    if platform:
        templates = [t for t in templates if platform in t['platform']]
    
    return jsonify({
        'success': True,
        'templates': templates,
        'count': len(templates)
    })

@radim_bp.route('/api/radim/stories/generate', methods=['POST', 'OPTIONS'])
@require_auth
def radim_story_generate():
    """Generování story obsahu"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        template_id = data.get('template_id')
        fields = data.get('fields', {})
        platform = data.get('platform', 'instagram')
        
        prompt = f"""Vytvoř krátký příspěvek pro {platform}.
Šablona: {template_id}
Pole: {json.dumps(fields, ensure_ascii=False)}

Pravidla: Max 3 věty, senior-friendly, Kolibri tón.
Odpověz POUZE textem příspěvku:"""
        
        if GEMINI_API_KEY:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 200}
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result:
                    story_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
                    return jsonify({
                        'success': True,
                        'story': {
                            'text': story_text,
                            'platform': platform,
                            'template_id': template_id,
                            'hashtags': ['#KavárnaKolibri', '#Senioři', '#PlusOne']
                        }
                    })
        
        return jsonify({'success': False, 'error': 'AI nedostupné'}), 503
        
    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@radim_bp.route('/api/radim/voice/speak', methods=['POST', 'OPTIONS'])
@optional_auth
def radim_voice_speak():
    """Azure TTS endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    AZURE_KEY = os.environ.get('AZURE_SPEECH_KEY')
    AZURE_REGION = os.environ.get('AZURE_SPEECH_REGION', 'westeurope')
    
    if not AZURE_KEY:
        return jsonify({'success': False, 'error': 'Azure Speech není nakonfigurován'}), 503
    
    try:
        data = request.json
        text = data.get('text', '')
        voice = data.get('voice', 'cs-CZ-AntoninNeural')
        emotion = data.get('emotion', 'friendly')
        
        if not text:
            return jsonify({'success': False, 'error': 'Text je povinný'}), 400

        # Sanitize inputs to prevent SSML injection
        safe_text = xml_escape(text)
        if not re.match(r'^[a-zA-Z]{2}-[A-Z]{2}-[a-zA-Z]+Neural$', voice):
            voice = 'cs-CZ-AntoninNeural'

        emotion_settings = {
            'friendly': {'pitch': '-5%', 'rate': '0.85'},
            'calm': {'pitch': '-8%', 'rate': '0.8'},
            'warm': {'pitch': '-3%', 'rate': '0.9'}
        }
        settings = emotion_settings.get(emotion, emotion_settings['friendly'])

        # Anticipation Engine: adaptive params from C/α
        ant_state = None
        C_val = data.get('C')
        alpha_val = data.get('alpha')
        if C_val is not None and alpha_val is not None and _ORCH_ANT_AVAILABLE:
            try:
                C_pred = _orch_predict_C(float(C_val), 0, float(alpha_val))
                emo = _orch_emotions(C_pred, float(alpha_val))
                ant_params = _orch_speech_params(C_pred, float(alpha_val), emo)
                ant_state = _orch_classify(C_pred)
                settings = {
                    'rate': str(ant_params['rate']),
                    'pitch': f"{ant_params['pitch']:+.0f}%"
                }
            except Exception:
                pass  # Fall back to emotion_settings

        # 🧠 Brain Engine: override with per-user Ψ(t) speech adaptation
        brain_speech = None
        if _ORCH_BRAIN_AVAILABLE:
            try:
                uid = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
                brain_speech = _brain_speech_for_user(uid)
                if brain_speech:
                    settings = {
                        'rate': str(brain_speech['rate']),
                        'pitch': f"{brain_speech['pitch_pct']:+d}%"
                    }
                    ant_state = brain_speech['mode']
            except Exception:
                pass  # Fall back to previous settings

        # v2.1: express-as for emotional style (style/styledegree from Brain Engine)
        _style = brain_speech.get('style', 'friendly') if brain_speech else 'friendly'
        _styledegree = brain_speech.get('styledegree', '1.2') if brain_speech else '1.2'

        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="{voice}">
                <mstts:express-as style="{_style}" styledegree="{_styledegree}">
                    <prosody rate="{settings['rate']}" pitch="{settings['pitch']}" volume="loud">{safe_text}</prosody>
                </mstts:express-as>
            </voice>
        </speak>'''

        response = requests.post(
            f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                'Ocp-Apim-Subscription-Key': AZURE_KEY,
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3'
            },
            data=ssml.encode('utf-8'),
            timeout=15
        )

        if response.status_code == 200:
            audio_base64 = base64.b64encode(response.content).decode('utf-8')
            resp_data = {
                'success': True,
                'audio': audio_base64,
                'format': 'mp3',
                'voice': voice,
                'emotion': emotion
            }
            if ant_state:
                resp_data['anticipation_state'] = ant_state
            if brain_speech:
                resp_data['brain_speech'] = brain_speech
            return jsonify(resp_data)
        
        return jsonify({'success': False, 'error': f'Azure TTS error: {response.status_code}'}), 500
        
    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@radim_bp.route('/api/radim/greeting', methods=['GET'])
def radim_greeting():
    """Time-based greeting — single source of truth for all frontends"""
    try:
        from radim_shared import get_greeting, get_nameday, build_time_context_string
        greeting_emoji = get_greeting(with_emoji=True)
        greeting_plain = get_greeting(with_emoji=False)
        nameday = get_nameday()
        time_ctx = build_time_context_string()

        return jsonify({
            'success': True,
            'greeting': greeting_emoji,
            'greeting_plain': greeting_plain,
            'nameday': nameday or None,
            'time_context': time_ctx,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        # Minimal fallback
        hour = datetime.now().hour
        if 5 <= hour < 12:
            g_text = "Dobré ráno! ☀️"
        elif 12 <= hour < 18:
            g_text = "Dobré odpoledne! 🌤️"
        elif 18 <= hour < 22:
            g_text = "Dobrý večer! 🌙"
        else:
            g_text = "Dobrou noc! 🌟"
        return jsonify({'success': True, 'greeting': g_text, 'timestamp': datetime.utcnow().isoformat() + 'Z'})


@radim_bp.route('/api/radim/health', methods=['GET'])
def radim_health():
    """Health check"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'service': 'Radim WhatsApp Orchestrator',
        'version': '1.1.0',
        'features': {
            'whatsapp_chat': True,
            'task_management': True,
            'story_templates': True,
            'voice_synthesis': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'anticipation_engine': _ORCH_ANT_AVAILABLE,
            'ai_provider': 'gemini' if GEMINI_API_KEY else 'none'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })
