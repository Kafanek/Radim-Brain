"""
📞 TWILIO VOICE HELPERS — Shared utilities for phone call handling
=================================================================
Extracted from twilio_voice_routes.py for modularity.

Contains:
  - Twilio signature validation decorator
  - Anticipation Engine helpers (C/α estimation, adaptive speech)
  - Configuration (env vars, voice constants)
  - Azure TTS functions (generate_azure_tts, twiml_say)
  - State management (active_calls, known_callers)
  - AI response helper (get_ai_response_for_call)
  - Intent detection (transfer/conference patterns)
  - Contact lookup

Version: 1.0.0
"""

import os
import re
import time
import logging
import threading
import requests as http_requests
from xml.sax.saxutils import escape as xml_escape
from functools import wraps
from flask import request, Response, abort

logger = logging.getLogger(__name__)


# ============================================================================
# SIGNATURE VALIDATION DECORATOR
# ============================================================================

def validate_twilio_signature(f):
    """Decorator to validate incoming Twilio webhook requests."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        if not auth_token:
            return f(*args, **kwargs)

        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            logger.warning("⚠️ Twilio webhook call without X-Twilio-Signature header")
            abort(403)

        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(auth_token)
            url = request.url
            post_vars = request.form.to_dict() if request.method == "POST" else {}
            if not validator.validate(url, post_vars, signature):
                logger.warning(f"⚠️ Twilio signature validation failed for {request.path}")
                abort(403)
        except ImportError:
            logger.warning("⚠️ twilio package not installed — skipping signature validation")
        except Exception as e:
            logger.error(f"❌ Twilio signature validation error: {e}")
            abort(403)

        return f(*args, **kwargs)
    return decorated


# ============================================================================
# CENTRALIZED IMPORTS
# ============================================================================

from radim_shared import get_nameday as _get_nameday, build_time_context as _shared_build_time_context, get_greeting as _shared_get_greeting
from radim_system_prompt import get_phone_prompt as _build_phone_prompt


def _build_voice_time_context():
    """Build time context for phone calls — delegates to radim_shared."""
    return _shared_build_time_context()


# ============================================================================
# ANTICIPATION ENGINE INTEGRATION
# ============================================================================

try:
    from anticipation_routes import (
        predict_C, calculate_emotions, calculate_speech_params,
        classify_state, PHI as ANT_PHI, C_HARMONY, C_ALERT
    )
    ANTICIPATION_AVAILABLE = True
    logger.info("✅ Anticipation Engine connected to Twilio Voice")
except ImportError:
    ANTICIPATION_AVAILABLE = False
    logger.warning("⚠️ Anticipation Engine not available - using hardcoded TTS params")

# Task Service integration (v231)
try:
    from task_service import (
        build_tasks_context as _voice_tasks_context,
        get_tasks as _voice_get_tasks
    )
    _VOICE_TASK_SERVICE = True
except ImportError:
    _VOICE_TASK_SERVICE = False

# Memory system (v231)
try:
    from memory_routes import build_personalized_prompt as _voice_build_prompt
    _VOICE_MEMORY = True
except ImportError:
    _VOICE_MEMORY = False


# v408: Import word sets from single source of truth (was duplicated & incomplete)
try:
    from intent_data import CRISIS_WORDS as _CRISIS_WORDS_ALL, STRESS_WORDS as _STRESS_WORDS, CALM_WORDS as _CALM_WORDS
    # Use full CRISIS_WORDS (46 words) instead of local subset (was 12 words!)
    _CRISIS_WORDS = _CRISIS_WORDS_ALL
except ImportError:
    # Fallback if intent_data not available (shouldn't happen in production)
    _CRISIS_WORDS = {'pomoc', 'help', 'bolest', 'spadl', 'sos', 'nemůžu', 'záchranku'}
    _STRESS_WORDS = {'strach', 'bojím', 'nemocný', 'unavený', 'problém', 'bolí'}
    _CALM_WORDS = {'děkuji', 'díky', 'dobře', 'fajn', 'skvěle', 'pohoda'}


def estimate_call_C_alpha(call_sid, speech_result, confidence):
    """Estimate C and α from phone call context.

    v408: Unified coefficients with intent_resolver.quick_estimate_from_text()
    + fuzzy safety detection for speech-impaired seniors on calls.
    """
    call_data = active_calls.get(call_sid, {})
    history = call_data.get("history", [])
    turn_count = len(history) // 2

    C = 5.0
    C += min(turn_count * 0.5, 5)

    try:
        conf_val = float(confidence)
    except (ValueError, TypeError):
        conf_val = 0.5
    if conf_val < 0.5:
        C += (0.5 - conf_val) * 10

    text_lower = (speech_result or "").lower()
    words = set(text_lower.split())

    crisis_hits = len(words & _CRISIS_WORDS)
    stress_hits = len(words & _STRESS_WORDS)
    calm_hits = len(words & _CALM_WORDS)

    # v408: Fuzzy safety check — catches "pomo", "pomc", "infrkt" etc.
    # Critical for dysarthria/aphasia seniors on phone
    try:
        from speech_understanding import detect_safety_fuzzy
        fuzzy = detect_safety_fuzzy(speech_result or "")
        if fuzzy and fuzzy["severity"] == "critical":
            crisis_hits = max(crisis_hits, 2)  # ensure strong C response
        elif fuzzy and fuzzy["severity"] == "high":
            crisis_hits = max(crisis_hits, 1)
    except ImportError:
        pass

    # v408: Unified coefficients — same as intent_resolver.quick_estimate_from_text
    C += crisis_hits * 12.0
    C += stress_hits * 4.0
    C -= calm_hits * 2.0
    C = max(0, min(C, 50))

    # v408: Incremental alpha (was binary jump — inconsistent with chat)
    alpha = 0.2
    alpha += crisis_hits * 0.3
    alpha += stress_hits * 0.15
    alpha -= calm_hits * 0.05
    alpha = max(0.0, min(1.0, alpha))

    if call_sid in active_calls:
        prev_C = active_calls[call_sid].get("C", 5.0)
        prev_alpha = active_calls[call_sid].get("alpha", 0.2)
        C = 0.7 * C + 0.3 * prev_C
        alpha = 0.7 * alpha + 0.3 * prev_alpha
        active_calls[call_sid]["C"] = round(C, 2)
        active_calls[call_sid]["alpha"] = round(alpha, 3)

    return C, alpha


def get_adaptive_speech_params(C, alpha):
    """Get adaptive speech parameters from Anticipation Engine."""
    if not ANTICIPATION_AVAILABLE:
        return {"rate_pct": "-5%", "pitch_hz": "-2%", "state": "UNKNOWN"}

    try:
        C_pred = predict_C(C, 0, alpha)
        emotions = calculate_emotions(C_pred, alpha)
        params = calculate_speech_params(C_pred, alpha, emotions)
        state = classify_state(C_pred)

        rate_pct = f"{int(params['rate'] * 100)}%"
        pitch_hz = f"{params['pitch']:+.0f}Hz" if params['pitch'] != 0 else "+0Hz"

        return {
            "rate_pct": rate_pct,
            "pitch_hz": pitch_hz,
            "state": state,
            "empathy": params["empathy"],
            "pause_ms": params["pause_ms"],
            "raw": params
        }
    except Exception as e:
        logger.error(f"Anticipation fallback: {e}")
        return {"rate_pct": "-5%", "pitch_hz": "-2%", "state": "FALLBACK"}


# ============================================================================
# CONFIGURATION
# ============================================================================

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# v408: Import shared Azure config (single source of truth)
try:
    from speech_helpers import AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
except ImportError:
    AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY")
    AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "germanywestcentral")

RADIM_VOICE_GOOGLE = "Google.cs-CZ-Standard-A"
RADIM_VOICE_BASIC = "man"
RADIM_LANG = "cs-CZ"
RADIM_AZURE_VOICE = "cs-CZ-AntoninNeural"

_twilio_client = None


def get_twilio_client():
    """Get or create Twilio REST client"""
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        except ImportError:
            logger.warning("twilio package not installed")
    return _twilio_client


def azure_tts_available():
    """Check if Azure TTS is configured"""
    return bool(AZURE_SPEECH_KEY and AZURE_SPEECH_REGION)


# ============================================================================
# TTS FUNCTIONS
# ============================================================================

def generate_azure_tts(text, rate_pct=None, pitch_hz=None, mode="HARMONY", user_id=None):
    """Generate audio bytes using Azure TTS (AntoninNeural).

    v403: Accepts mode + user_id for adaptive voice styling.
    """
    if not azure_tts_available():
        return None

    if rate_pct is None:
        rate_pct = "-5%"
    if pitch_hz is None:
        pitch_hz = "-2%"

    try:
        url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"

        # v389: Use rich SSML from voice_filter (emotion + pauses + emphasis)
        # v403: Pass user_id for per-user adaptive voice (fatigue, recovery, pace)
        try:
            from voice_filter import build_radim_ssml
            ssml = build_radim_ssml(text, mode=mode, voice=RADIM_AZURE_VOICE, user_id=user_id)
        except ImportError:
            safe_text = xml_escape(text)
            ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='cs-CZ'>
                <voice name='{RADIM_AZURE_VOICE}'>
                    <prosody rate='{rate_pct}' pitch='{pitch_hz}'>{safe_text}</prosody>
                </voice>
            </speak>"""

        import time as _time
        _t0 = _time.time()
        resp = http_requests.post(
            url,
            headers={
                'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': 'audio-16khz-32kbitrate-mono-mp3',
            },
            data=ssml.encode('utf-8'),
            timeout=8
        )
        _latency = round((_time.time() - _t0) * 1000)
        if resp.status_code == 200:
            _size = len(resp.content)
            logger.info(f"TTS OK: {_latency}ms {_size}bytes mode={mode} chars={len(text)}")
            return resp.content
        else:
            logger.error(f"Azure TTS error: {resp.status_code} {_latency}ms {resp.text[:100]}")
            return None
    except Exception as e:
        logger.error(f"Azure TTS exception: {e}")
        return None


def twiml_say(text, speech_params=None):
    """Generate TwiML for Radim speaking - Azure TTS <Play> or fallback <Say>."""
    if azure_tts_available():
        from urllib.parse import quote
        encoded = quote(text, safe='')
        backend_url = os.environ.get('BACKEND_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
        url = f'{backend_url}/api/twilio/tts?text={encoded}'
        if speech_params and isinstance(speech_params, dict):
            if speech_params.get("rate_pct"):
                url += f'&rate={quote(str(speech_params["rate_pct"]), safe="")}'
            if speech_params.get("pitch_hz"):
                url += f'&pitch={quote(str(speech_params["pitch_hz"]), safe="")}'
            # v10.20: Pass brain voice_mode to TTS endpoint
            if speech_params.get("mode"):
                url += f'&mode={quote(str(speech_params["mode"]), safe="")}'
            if speech_params.get("user_id"):
                url += f'&user_id={quote(str(speech_params["user_id"]), safe="")}'
        return f'<Play>{url}</Play>'
    else:
        safe_text = xml_escape(text)
        return f'<Say voice="{RADIM_VOICE_BASIC}" language="{RADIM_LANG}">{safe_text}</Say>'


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

active_calls = {}
_ACTIVE_CALLS_MAX = 100
_calls_lock = threading.Lock()  # v407: thread safety for concurrent Twilio webhooks

known_callers = {}
_KNOWN_CALLERS_MAX = 500


def _cleanup_active_calls():
    """Remove calls older than 2h, enforce max size. Thread-safe."""
    with _calls_lock:
        cutoff = time.time() - 7200
        expired = [sid for sid, d in active_calls.items() if d.get("started", 0) < cutoff]
        for sid in expired:
            del active_calls[sid]
        if len(active_calls) > _ACTIVE_CALLS_MAX:
            sorted_sids = sorted(active_calls.keys(), key=lambda s: active_calls[s].get("started", 0))
            for sid in sorted_sids[:len(active_calls) - _ACTIVE_CALLS_MAX]:
                del active_calls[sid]


def _cleanup_known_callers():
    """Remove oldest known_callers entries when over limit."""
    if len(known_callers) <= _KNOWN_CALLERS_MAX:
        return
    sorted_phones = sorted(known_callers.keys(), key=lambda p: known_callers[p].get("registered_at", 0))
    for phone in sorted_phones[:len(known_callers) - _KNOWN_CALLERS_MAX]:
        del known_callers[phone]


# Intent patterns (Czech) — v407: expanded for casual senior speech
TRANSFER_PATTERNS = re.compile(
    r'(zavolej|přepoj|spojte|přepojte|zavolejte|chci\s+mluvit\s+s|chci\s+volat|dej\s+mi|zavolej\s+domů)'
    r'(\s+na\s+|\s+s\s+|\s+)?'
    r'(dce[rř]|syn[aůuem]?|doktor[aůuem]?|lékař[aůuem]?|mari[ie]|pet[rř]|rodinu|vnuč|domů)?',
    re.IGNORECASE
)

CONFERENCE_PATTERNS = re.compile(
    r'(zůstaň|zůstaňte|buď|buďte)\s*(s\s+námi|mezi\s*(námi|hovorem))',
    re.IGNORECASE
)


# ============================================================================
# HELPERS
# ============================================================================

def twiml_response(twiml_xml):
    """Return TwiML XML response"""
    return Response(twiml_xml, content_type="text/xml")


def get_ai_response_for_call(user_text, call_sid, user_id=None):
    """Get AI response for phone conversation — through full orchestrator pipeline.

    v10.20: Routes through radim_chat_internal() for brain Ψ(t) + voice_mode.
    Falls back to direct Claude if orchestrator fails.
    """
    call_data = active_calls.get(call_sid, {})
    uid = call_data.get("user_id") or user_id

    # v10.20: Use orchestrator pipeline (brain Ψ, voice_mode, memory, learning)
    try:
        from radim_orchestrator import radim_chat_internal
        result = radim_chat_internal(user_text, user_id=uid, mode="senior")
        ai_text = result.get("response", "")
        voice_mode = result.get("voice_mode", "HARMONY")

        if ai_text:
            # Record in call history
            if call_sid in active_calls:
                active_calls[call_sid]["history"].append({"role": "user", "content": user_text})
                active_calls[call_sid]["history"].append({"role": "assistant", "content": ai_text})
                active_calls[call_sid]["voice_mode"] = voice_mode

            logger.info(f"📞 Call AI via orchestrator: voice_mode={voice_mode} user={uid}")
            return ai_text
    except Exception as orch_err:
        logger.warning(f"📞 Orchestrator fallback: {orch_err}")

    # Fallback: direct Claude (if orchestrator fails)
    if not ANTHROPIC_API_KEY:
        return "Omlouvám se, právě mám technické potíže. Zkuste to prosím za chvíli."

    call_data = active_calls.get(call_sid, {})
    history = call_data.get("history", [])
    caller_name = call_data.get("caller_name", "")

    messages = []
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    extra_ctx = ""
    if uid:
        if _VOICE_TASK_SERVICE:
            try:
                tasks_ctx = _voice_tasks_context(uid)
                if tasks_ctx:
                    extra_ctx += f"\n{tasks_ctx}"
            except Exception:
                pass
        if _VOICE_MEMORY:
            try:
                profile_ctx = _voice_build_prompt(uid)
                if profile_ctx:
                    extra_ctx += f"\n{profile_ctx}"
            except Exception:
                pass

    tc = _build_voice_time_context()
    system_prompt = _build_phone_prompt(
        time_context=tc,
        caller_name=caller_name,
        extra_ctx=extra_ctx
    )

    try:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=25.0)
            response = client.messages.create(
                model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
                max_tokens=200,
                system=system_prompt,
                messages=messages
            )
            ai_text = response.content[0].text
        except ImportError:
            resp = http_requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "temperature": 0.7,
                    "system": system_prompt,
                    "messages": messages
                },
                timeout=25
            )
            if resp.status_code == 200:
                data = resp.json()
                ai_text = data.get("content", [{}])[0].get("text", "")
            else:
                return "Omlouvám se, mám krátký výpadek. Můžete to zkusit znovu?"

        if call_sid in active_calls:
            active_calls[call_sid]["history"].append({"role": "user", "content": user_text})
            active_calls[call_sid]["history"].append({"role": "assistant", "content": ai_text})

        return ai_text

    except Exception as e:
        logger.error(f"Twilio AI error: {e}")
        return "Promiňte, měl jsem technický problém. Jsem tu pro vás, zkuste to prosím znovu."


def detect_transfer_intent(text):
    """Detect if user wants to transfer call.
    v407: expanded patterns — "chci mluvit s...", "zavolej domů" etc.
    """
    if not text:
        return None
    if TRANSFER_PATTERNS.search(text):
        text_lower = text.lower()
        if any(w in text_lower for w in ['dcer', 'mari']):
            return {"target": "dcera", "name": "dcera"}
        elif any(w in text_lower for w in ['syn', 'petr']):
            return {"target": "syn", "name": "syn"}
        elif any(w in text_lower for w in ['doktor', 'lékař', 'lekar']):
            return {"target": "doktor", "name": "lékař"}
        elif any(w in text_lower for w in ['rodinu', 'vnuč', 'domů', 'domu']):
            return {"target": "rodina", "name": "rodina"}
        return {"target": "unknown", "name": "kontakt"}
    return None


def lookup_contact_phone(target, caller_phone):
    """Look up contact phone from known callers"""
    caller_data = known_callers.get(caller_phone, {})
    contacts = caller_data.get("contacts", {})
    if target in contacts:
        return contacts[target]
    return None


# ============================================================================
# PROACTIVE OUTBOUND CALLS (v387 — agent loop integration)
# ============================================================================

def initiate_proactive_call(phone_number, greeting, user_id=None, reason="check_in", voice_mode=None):
    """
    Initiate outbound call from Radim to a senior or caregiver.

    Called by agent_loop when severity >= ALERT, or for scheduled check-ins.

    Args:
        phone_number: E.164 format (+420...)
        greeting: Czech text Radim will say when call connects
        user_id: senior's user_id (for tracking)
        reason: 'check_in', 'alert', 'crisis', 'medication_reminder'

    Returns:
        dict: {success, call_sid, error}
    """
    client = get_twilio_client()
    if not client or not TWILIO_PHONE_NUMBER:
        logger.warning("Proactive call skipped — Twilio not configured")
        return {"success": False, "error": "Twilio not configured"}

    # v407: E.164 validation (must be +countrycode + digits, 8-15 total)
    if not phone_number or not re.match(r'^\+[1-9]\d{7,14}$', phone_number):
        return {"success": False, "error": f"Invalid E.164 phone: {phone_number}"}

    # v450: Circuit breaker for Twilio
    try:
        from self_healing import get_breaker, log_healing_event
        twilio_breaker = get_breaker('twilio')
        if not twilio_breaker.can_proceed():
            log_healing_event('circuit_open', 'twilio', {'phone': phone_number[-4:]})
            return {"success": False, "error": "Twilio circuit open — too many failures"}
    except ImportError:
        twilio_breaker = None

    try:
        # v10.20: Use Azure TTS with brain voice_mode (not Polly.Adela)
        _mode = voice_mode or 'ALERT'
        _greeting_say = twiml_say(greeting, {"mode": _mode, "user_id": user_id})
        _listen_say = twiml_say("Poslouchám vás.", {"mode": _mode, "user_id": user_id})
        _bye_say = twiml_say("Neslyšel jsem vás. Zkusím zavolat později.", {"mode": _mode, "user_id": user_id})

        twiml = (
            f'<Response>'
            f'{_greeting_say}'
            f'<Gather input="speech" language="cs-CZ" '
            f'action="/api/twilio/gather" method="POST" speechTimeout="auto" timeout="10">'
            f'{_listen_say}'
            f'</Gather>'
            f'{_bye_say}'
            f'</Response>'
        )

        call = client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            twiml=twiml,
            status_callback="/api/twilio/status",
            status_callback_method="POST",
            timeout=30,  # ring for 30s max
        )

        active_calls[call.sid] = {
            "from": TWILIO_PHONE_NUMBER,
            "to": phone_number,
            "started": time.time(),
            "history": [],
            "caller_name": "Radim",
            "status": "initiated",
            "direction": "proactive",
            "reason": reason,
            "user_id": user_id,
        }

        logger.info(f"📞 Proactive call initiated: {call.sid} → {phone_number} (reason={reason})")
        if twilio_breaker: twilio_breaker.record_success()
        return {"success": True, "call_sid": call.sid}

    except Exception as e:
        logger.error(f"Proactive call error: {e}")
        if twilio_breaker: twilio_breaker.record_failure()
        try: log_healing_event('call_failed', 'twilio', {'error': str(e)[:80], 'phone': phone_number[-4:]})
        except: pass
        return {"success": False, "error": str(e)}


def get_senior_phone(user_id):
    """Get senior's phone number from memory_profiles."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)
        # Direct phone number
        phone = profile.get("phone")
        if phone and phone.startswith('+'):
            return phone
        # Fallback: first emergency contact
        ec = profile.get("emergency_contacts", [])
        if ec and isinstance(ec, list) and len(ec) > 0:
            return ec[0].get("phone")
    except Exception:
        pass
    return None


logger.info("✅ Twilio Voice Helpers loaded — auth, TTS, state, AI, intent, proactive calls")
