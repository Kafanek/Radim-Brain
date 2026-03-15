"""
📞 TWILIO VOICE ROUTES - Flask Blueprint
RadimCare Phone Integration: Incoming calls, STT→AI→TTS, transfers, conferences

Senior volá +420 číslo → Twilio → webhook → Claude AI → TwiML response

Version: 1.0.0
"""

import os
import re
import time
import json
import logging
import requests as http_requests
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
from functools import wraps
from flask import Blueprint, request, jsonify, Response, abort
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)


def validate_twilio_signature(f):
    """Decorator to validate incoming Twilio webhook requests.
    Verifies the X-Twilio-Signature header using TWILIO_AUTH_TOKEN.
    Skips validation if TWILIO_AUTH_TOKEN is not set (dev mode).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
        if not auth_token:
            # Dev mode — no validation
            return f(*args, **kwargs)

        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            logger.warning("⚠️ Twilio webhook call without X-Twilio-Signature header")
            abort(403)

        try:
            from twilio.request_validator import RequestValidator
            validator = RequestValidator(auth_token)

            # Build the full URL Twilio signed against
            url = request.url
            # Twilio signs against form data for POST
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

# Centralized utilities — no more duplicated nameday/time/greeting code
from radim_shared import get_nameday as _get_nameday, build_time_context as _shared_build_time_context, get_greeting as _shared_get_greeting
from radim_system_prompt import get_phone_prompt as _build_phone_prompt

# _build_voice_time_context → now delegated to radim_shared.build_time_context()
def _build_voice_time_context():
    """Build time context for phone calls — delegates to radim_shared."""
    return _shared_build_time_context()

# Flask Blueprint
twilio_bp = Blueprint('twilio_voice', __name__, url_prefix='/api/twilio')

# ============================================================================
# ANTICIPATION ENGINE INTEGRATION
# ============================================================================
# Import math functions from Anticipation Engine (same process)
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

# Task Service integration (v231 — voice knows about tasks & medications)
try:
    from task_service import (
        build_tasks_context as _voice_tasks_context,
        get_tasks as _voice_get_tasks
    )
    _VOICE_TASK_SERVICE = True
except ImportError:
    _VOICE_TASK_SERVICE = False

# Memory system (v231 — personalized voice prompts)
try:
    from memory_routes import build_personalized_prompt as _voice_build_prompt
    _VOICE_MEMORY = True
except ImportError:
    _VOICE_MEMORY = False


# Emotional keyword sets for C/α estimation from speech
_CRISIS_WORDS = {'pomoc', 'help', 'bolest', 'pain', 'spadl', 'fell', 'sos',
                 'nouzové', 'emergency', 'nemůžu', 'špatně', 'umírám', 'záchranku'}
_STRESS_WORDS = {'strach', 'afraid', 'bojím', 'nervous', 'nemocný', 'sick',
                 'unavený', 'tired', 'problém', 'bolí', 'nespím', 'samota', 'sám'}
_CALM_WORDS = {'děkuji', 'díky', 'hezky', 'nice', 'dobře', 'good', 'krásně',
               'fajn', 'prima', 'skvěle', 'výborně', 'pohoda'}


def estimate_call_C_alpha(call_sid, speech_result, confidence):
    """
    Estimate C (consciousness load 0-40) and α (stress 0-1) from phone call context.
    Uses: speech content keywords, STT confidence, conversation turn count.
    Smoothed via EMA with previous call state.
    """
    call_data = active_calls.get(call_sid, {})
    history = call_data.get("history", [])
    turn_count = len(history) // 2

    # Base C
    C = 5.0

    # Turn count factor (longer calls → slight increase)
    C += min(turn_count * 0.5, 5)

    # STT confidence factor (low confidence → stress/unclear speech)
    try:
        conf_val = float(confidence)
    except (ValueError, TypeError):
        conf_val = 0.5
    if conf_val < 0.5:
        C += (0.5 - conf_val) * 10  # up to +5

    # Keyword detection
    text_lower = speech_result.lower()
    words = set(text_lower.split())

    crisis_hits = len(words & _CRISIS_WORDS)
    stress_hits = len(words & _STRESS_WORDS)
    calm_hits = len(words & _CALM_WORDS)

    C += crisis_hits * 8
    C += stress_hits * 3
    C -= calm_hits * 2
    C = max(0, min(C, 40))

    # Alpha estimation
    alpha = 0.2
    if crisis_hits > 0:
        alpha = 0.8
    elif stress_hits > 0:
        alpha = 0.5
    elif calm_hits > 0:
        alpha = 0.1

    # EMA smoothing with previous state
    if call_sid in active_calls:
        prev_C = active_calls[call_sid].get("C", 5.0)
        prev_alpha = active_calls[call_sid].get("alpha", 0.2)
        C = 0.7 * C + 0.3 * prev_C
        alpha = 0.7 * alpha + 0.3 * prev_alpha
        active_calls[call_sid]["C"] = round(C, 2)
        active_calls[call_sid]["alpha"] = round(alpha, 3)

    return C, alpha


def get_adaptive_speech_params(C, alpha):
    """
    Get adaptive speech parameters from Anticipation Engine.
    Falls back to hardcoded defaults if engine not available.

    Returns: {"rate_pct": "90%", "pitch_hz": "-2Hz", "state": "HARMONY", ...}
    """
    if not ANTICIPATION_AVAILABLE:
        return {"rate_pct": "-5%", "pitch_hz": "-2%", "state": "UNKNOWN"}

    try:
        C_pred = predict_C(C, 0, alpha)  # No trend for quick estimate
        emotions = calculate_emotions(C_pred, alpha)
        params = calculate_speech_params(C_pred, alpha, emotions)
        state = classify_state(C_pred)

        # Convert to Azure SSML format
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
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")  # +420 XXX XXX XXX
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Azure TTS for Radim's voice (male Czech - AntoninNeural)
AZURE_SPEECH_KEY = os.environ.get("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.environ.get("AZURE_SPEECH_REGION", "germanywestcentral")

# Voice configuration - Radim is MALE
# Priority: Azure TTS (cs-CZ-AntoninNeural) → Google male → basic man
RADIM_VOICE_GOOGLE = "Google.cs-CZ-Standard-A"  # fallback (female, but best quality)
RADIM_VOICE_BASIC = "man"  # basic male voice
RADIM_LANG = "cs-CZ"
RADIM_AZURE_VOICE = "cs-CZ-AntoninNeural"  # THE Radim voice - male Czech

# Twilio client (lazy init)
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


def generate_azure_tts(text, rate_pct=None, pitch_hz=None):
    """
    Generate audio bytes using Azure TTS (AntoninNeural - Radim's voice).
    Now accepts adaptive speech parameters from Anticipation Engine.

    Args:
        text: Text to synthesize
        rate_pct: Prosody rate (e.g. "90%", "-5%"). Default: "95%" (= -5%)
        pitch_hz: Prosody pitch (e.g. "-2Hz", "+0Hz"). Default: "-2Hz"
    """
    if not azure_tts_available():
        return None

    # Defaults (original hardcoded values) if no adaptive params
    if rate_pct is None:
        rate_pct = "-5%"
    if pitch_hz is None:
        pitch_hz = "-2%"

    try:
        url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        safe_text = xml_escape(text)
        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='cs-CZ'>
            <voice name='{RADIM_AZURE_VOICE}'>
                <prosody rate='{rate_pct}' pitch='{pitch_hz}'>{safe_text}</prosody>
            </voice>
        </speak>"""

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
        if resp.status_code == 200:
            return resp.content
        else:
            logger.error(f"Azure TTS error: {resp.status_code} {resp.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Azure TTS exception: {e}")
        return None


def twiml_say(text, speech_params=None):
    """
    Generate TwiML for Radim speaking - uses Azure TTS <Play> or fallback <Say>.
    Now accepts adaptive speech_params from Anticipation Engine.

    Args:
        text: Text to speak
        speech_params: dict with rate_pct, pitch_hz from get_adaptive_speech_params()
    """
    if azure_tts_available():
        # Use Azure TTS via /api/twilio/tts endpoint
        from urllib.parse import quote, urlencode
        encoded = quote(text, safe='')
        backend_url = os.environ.get('BACKEND_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
        url = f'{backend_url}/api/twilio/tts?text={encoded}'
        # Append adaptive speech params to URL
        if speech_params and isinstance(speech_params, dict):
            if speech_params.get("rate_pct"):
                url += f'&rate={quote(str(speech_params["rate_pct"]), safe="")}'
            if speech_params.get("pitch_hz"):
                url += f'&pitch={quote(str(speech_params["pitch_hz"]), safe="")}'
        return f'<Play>{url}</Play>'
    else:
        # Fallback: basic male voice - escape XML to prevent TwiML injection
        safe_text = xml_escape(text)
        return f'<Say voice="{RADIM_VOICE_BASIC}" language="{RADIM_LANG}">{safe_text}</Say>'


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

# Active calls: { call_sid: { from, to, started, history[], caller_name, status } }
active_calls = {}
_ACTIVE_CALLS_MAX = 100  # Prevent unbounded growth

# Known callers: { phone: { name, formality, contacts } }
known_callers = {}
_KNOWN_CALLERS_MAX = 500  # Prevent unbounded growth


def _cleanup_active_calls():
    """Remove calls older than 2h, enforce max size."""
    cutoff = time.time() - 7200
    expired = [sid for sid, d in active_calls.items() if d.get("started", 0) < cutoff]
    for sid in expired:
        del active_calls[sid]
    # If still over limit, remove oldest
    if len(active_calls) > _ACTIVE_CALLS_MAX:
        sorted_sids = sorted(active_calls.keys(), key=lambda s: active_calls[s].get("started", 0))
        for sid in sorted_sids[:len(active_calls) - _ACTIVE_CALLS_MAX]:
            del active_calls[sid]

# Intent patterns (Czech)
TRANSFER_PATTERNS = re.compile(
    r'(zavolej|přepoj|spojte|přepojte|zavolejte)\s*(na\s+)?(dce[rř]|syn|doktor|lékař|mari[ie]|pet[rř]|rodinu|vnuč)',
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
    """Get Claude AI response for phone conversation (synchronous for Flask).
    v231: user_id enables task/medication/profile awareness during calls.
    """
    if not ANTHROPIC_API_KEY:
        return "Omlouvám se, právě mám technické potíže. Zkuste to prosím za chvíli."

    call_data = active_calls.get(call_sid, {})
    history = call_data.get("history", [])
    caller_name = call_data.get("caller_name", "")
    # v231: prefer stored user_id from active_calls, then parameter
    uid = call_data.get("user_id") or user_id

    # Build messages
    messages = []
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # caller_name passed directly to _build_phone_prompt()

    # v231: Load task context + personalized profile for voice
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

    # Phone prompt — centralized in radim_system_prompt.py
    tc = _build_voice_time_context()
    system_prompt = _build_phone_prompt(
        time_context=tc,
        caller_name=caller_name,
        extra_ctx=extra_ctx
    )

    try:
        # Try Anthropic SDK first
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
            # Fallback to requests
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

        # Save to call history
        if call_sid in active_calls:
            active_calls[call_sid]["history"].append({"role": "user", "content": user_text})
            active_calls[call_sid]["history"].append({"role": "assistant", "content": ai_text})

        return ai_text

    except Exception as e:
        logger.error(f"Twilio AI error: {e}")
        return "Promiňte, měl jsem technický problém. Jsem tu pro vás, zkuste to prosím znovu."


def detect_transfer_intent(text):
    """Detect if user wants to transfer call"""
    if TRANSFER_PATTERNS.search(text):
        text_lower = text.lower()
        if any(w in text_lower for w in ['dcer', 'mari']):
            return {"target": "dcera", "name": "dcera"}
        elif any(w in text_lower for w in ['syn', 'petr']):
            return {"target": "syn", "name": "syn"}
        elif any(w in text_lower for w in ['doktor', 'lékař']):
            return {"target": "doktor", "name": "lékař"}
        elif 'rodinu' in text_lower or 'vnuč' in text_lower:
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
# TWILIO WEBHOOK ENDPOINTS
# ============================================================================

@twilio_bp.route('/voice', methods=['POST'])
@validate_twilio_signature
def twilio_voice_webhook():
    """Incoming call handler — Twilio webhook"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        caller = request.form.get("From", "unknown")
        called = request.form.get("To", "")

        logger.info(f"📞 Incoming call: {caller} → {called} (SID: {call_sid})")
        logger.info(f"📞 Incoming call: {caller} → {called} (SID: {call_sid})")

        # Register active call (with C/α tracking for Anticipation Engine)
        # Use shared baseline from Anticipation Engine
        try:
            from anticipation_routes import BASELINE_PHONE
            _bl = BASELINE_PHONE
        except ImportError:
            _bl = {'C': 5.0, 'alpha': 0.2}
        caller_data = known_callers.get(caller, {})
        active_calls[call_sid] = {
            "from": caller,
            "to": called,
            "started": time.time(),
            "history": [],
            "caller_name": "",
            "status": "active",
            "C": _bl['C'],
            "alpha": _bl['alpha'],
            "user_id": caller_data.get("user_id")  # v231: link to task/profile data
        }

        # Build time-aware, consistent greeting
        caller_name = caller_data.get("name", "")
        if caller_name:
            active_calls[call_sid]["caller_name"] = caller_name

        tc = _build_voice_time_context()

        # Time-appropriate greeting — centralized in radim_shared
        greet_word = _shared_get_greeting(with_emoji=False)

        # Build one natural greeting with date + nameday (no overlap later)
        name_part = f", {caller_name}" if caller_name else ""
        date_part = f"Dnes je {tc['day_name']} {tc['date_str']}."
        nameday_part = f" Svátek má {tc['nameday']}." if tc["nameday"] else ""
        greeting = f"{greet_word}{name_part}, tady Radim. {date_part}{nameday_part} Jak se máte?"

        # Save greeting to history so Claude knows what was already said
        active_calls[call_sid]["history"].append({
            "role": "assistant", "content": greeting
        })

        say_greeting = twiml_say(greeting)
        say_listen = twiml_say("Poslouchám vás.")
        say_noheard = twiml_say("Neslyšel jsem vás. Pokud potřebujete pomoc, zavolejte znovu.")

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_greeting}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3" timeout="10">
        {say_listen}
    </Gather>
    {say_noheard}
</Response>"""
        return twiml_response(twiml)

    except Exception as e:
        logger.error(f"Twilio voice error: {e}")
        say_err = twiml_say("Omlouvám se, mám technické potíže. Zkuste zavolat znovu.")
        return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_err}
</Response>""")


@twilio_bp.route('/gather', methods=['POST'])
@validate_twilio_signature
def twilio_gather_webhook():
    """Speech recognized — Twilio STT webhook"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        speech_result = request.form.get("SpeechResult", "")
        confidence = request.form.get("Confidence", "0")
        caller = request.form.get("From", "unknown")

        logger.info(f"🎤 Speech: '{speech_result}' (confidence: {confidence}, SID: {call_sid})")
        logger.info(f"🎤 Speech: '{speech_result}' (confidence: {confidence})")

        if not speech_result.strip():
            say_retry = twiml_say("Promiňte, neslyšel jsem vás. Můžete to zopakovat?")
            say_here = twiml_say("Jsem tu pro vás.")
            return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_retry}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3" timeout="10">
        {say_here}
    </Gather>
</Response>""")

        # Check transfer intent
        transfer = detect_transfer_intent(speech_result)
        if transfer:
            want_conference = bool(CONFERENCE_PATTERNS.search(speech_result))
            target_phone = lookup_contact_phone(transfer["target"], caller)

            if target_phone:
                if want_conference:
                    # 3-way conference
                    conf_name = f"radim-{call_sid[:8]}"
                    say_conf = twiml_say(f"Přidávám vaši {transfer['name']} do hovoru. Zůstanu s vámi.")
                    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_conf}
    <Dial>
        <Conference startConferenceOnEnter="true" endConferenceOnExit="false">{conf_name}</Conference>
    </Dial>
</Response>"""
                    # Initiate outgoing leg
                    twilio_client = get_twilio_client()
                    if twilio_client and TWILIO_PHONE_NUMBER:
                        try:
                            say_outgoing = twiml_say(f"{_shared_get_greeting(with_emoji=False)}, volá vám Radim v zastoupení vašeho blízkého.")
                            twilio_client.calls.create(
                                to=target_phone,
                                from_=TWILIO_PHONE_NUMBER,
                                twiml=f'<Response>{say_outgoing}<Dial><Conference>{conf_name}</Conference></Dial></Response>'
                            )
                        except Exception as e:
                            logger.error(f"Conference call error: {e}")
                    return twiml_response(twiml)
                else:
                    # Direct transfer
                    say_transfer = twiml_say(f"Přepojuji vás na vaši {transfer['name']}. Moment prosím.")
                    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_transfer}
    <Dial callerId="{TWILIO_PHONE_NUMBER or ''}" action="/api/twilio/dial-status" method="POST">
        <Number>{target_phone}</Number>
    </Dial>
</Response>"""
                    if call_sid in active_calls:
                        active_calls[call_sid]["status"] = "transferring"
                    return twiml_response(twiml)
            else:
                ai_resp = f"Bohužel nemám uložené číslo na vaši {transfer['name']}. Chcete mi ho nadiktovat?"
                say_no_num = twiml_say(ai_resp)
                say_here2 = twiml_say("Jsem tu pro vás.")
                return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_no_num}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3" timeout="10">
        {say_here2}
    </Gather>
</Response>""")

        # Check goodbye
        goodbye_words = ['nashledanou', 'sbohem', 'ahoj', 'na shledanou', 'děkuji', 'díky', 'konec']
        if any(w in speech_result.lower() for w in goodbye_words) and len(speech_result) < 30:
            if call_sid in active_calls:
                active_calls[call_sid]["status"] = "ended"
            say_bye = twiml_say("Na shledanou! Bylo mi potěšením. Kdykoliv potřebujete, zavolejte znovu. Mějte se krásně!")
            return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_bye}
</Response>""")

        # ================================================================
        # ANTICIPATION ENGINE INTEGRATION
        # Estimate C/α from speech → get adaptive TTS params
        # ================================================================
        speech_params = None
        if ANTICIPATION_AVAILABLE:
            try:
                C, alpha = estimate_call_C_alpha(call_sid, speech_result, confidence)
                speech_params = get_adaptive_speech_params(C, alpha)
                state = speech_params.get("state", "?")
                logger.info(f"🧮 Anticipation: C={C:.1f} α={alpha:.2f} → {state} "
                            f"rate={speech_params.get('rate_pct')} pitch={speech_params.get('pitch_hz')}")
            except Exception as ae:
                logger.error(f"Anticipation error (non-fatal): {ae}")

        # Normal AI conversation (v231: pass user_id for task/profile awareness)
        _call_uid = active_calls.get(call_sid, {}).get("user_id")
        ai_response = get_ai_response_for_call(speech_result, call_sid, user_id=_call_uid)
        ai_safe = ai_response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        # Pass adaptive speech_params to TTS
        say_ai = twiml_say(ai_safe if not azure_tts_available() else ai_response, speech_params)
        say_here3 = twiml_say("Jsem tu pro vás.", speech_params)
        say_end = twiml_say("Pokud nepotřebujete nic dalšího, přeji vám krásný den!", speech_params)

        return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_ai}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3" timeout="10">
        {say_here3}
    </Gather>
    {say_end}
</Response>""")

    except Exception as e:
        logger.error(f"Twilio gather error: {e}", exc_info=True)
        say_err2 = twiml_say("Promiňte, měl jsem krátký výpadek. Zkuste to prosím znovu.")
        say_listen2 = twiml_say("Poslouchám.")
        return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_err2}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3">
        {say_listen2}
    </Gather>
</Response>""")


@twilio_bp.route('/status', methods=['POST'])
@validate_twilio_signature
def twilio_status_webhook():
    """Call status callback"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        call_status = request.form.get("CallStatus", "unknown")
        duration = request.form.get("CallDuration", "0")
        logger.info(f"📊 Call status: {call_sid} → {call_status} (duration: {duration}s)")
        logger.info(f"📊 Call status: {call_sid} → {call_status} (duration: {duration}s)")
        if call_sid in active_calls:
            active_calls[call_sid]["status"] = call_status
            if call_status in ("completed", "failed", "busy", "no-answer"):
                active_calls[call_sid]["ended"] = time.time()
                active_calls[call_sid]["duration"] = int(duration)
    except Exception as e:
        logger.warning(f"Status webhook error: {e}")
    return '', 204


@twilio_bp.route('/dial-status', methods=['POST'])
@validate_twilio_signature
def twilio_dial_status_webhook():
    """Transfer result handler"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        dial_status = request.form.get("DialCallStatus", "unknown")
        logger.info(f"📞 Dial status: {call_sid} → {dial_status}")
        if dial_status in ("busy", "no-answer", "failed", "canceled"):
            say_fail = twiml_say("Bohužel se mi nepodařilo spojit hovor. Můžu pro vás udělat něco jiného?")
            say_here4 = twiml_say("Jsem tu pro vás.")
            return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_fail}
    <Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3" timeout="10">
        {say_here4}
    </Gather>
</Response>""")
        if call_sid in active_calls:
            active_calls[call_sid]["status"] = "transfer_completed"
        return '', 204
    except Exception as e:
        logger.warning(f"Dial status error: {e}")
        return '', 204


# ============================================================================
# FRONTEND-FACING ENDPOINTS
# ============================================================================

@twilio_bp.route('/call', methods=['POST', 'OPTIONS'])
@require_auth
@rate_limit(5, 60, 'ip')  # v328: Rate limit outgoing calls (Twilio costs)
def initiate_outgoing_call():
    """Initiate outgoing call from frontend"""
    if request.method == 'OPTIONS':
        return '', 204

    twilio_client = get_twilio_client()
    if not twilio_client or not TWILIO_PHONE_NUMBER:
        return jsonify({"success": False, "error": "Twilio není nakonfigurováno"}), 503

    try:
        data = request.json or {}
        to = data.get("to", "")
        caller_name = data.get("caller_name", "")
        greeting = data.get("greeting") or f"{_shared_get_greeting(with_emoji=False)}, volá vám Radim, asistent pro seniory."

        if not to:
            return jsonify({"success": False, "error": "Chybí telefonní číslo"}), 400

        say_greet_out = twiml_say(greeting)
        say_listen_out = twiml_say("Poslouchám vás.")
        call = twilio_client.calls.create(
            to=to,
            from_=TWILIO_PHONE_NUMBER,
            twiml=f'<Response>{say_greet_out}<Gather input="speech" language="cs-CZ" action="/api/twilio/gather" method="POST" speechTimeout="3">{say_listen_out}</Gather></Response>',
            status_callback="/api/twilio/status",
            status_callback_method="POST"
        )
        active_calls[call.sid] = {
            "from": TWILIO_PHONE_NUMBER,
            "to": to,
            "started": time.time(),
            "history": [],
            "caller_name": caller_name,
            "status": "initiated",
            "direction": "outgoing"
        }
        return jsonify({"success": True, "call_sid": call.sid, "status": call.status, "to": to})

    except Exception as e:
        logger.error(f"Outgoing call error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500


@twilio_bp.route('/active-calls', methods=['GET'])
def get_active_calls():
    """List active phone calls"""
    _cleanup_active_calls()

    return jsonify({
        "success": True,
        "calls": [
            {
                "call_sid": sid,
                "from": d.get("from", ""),
                "to": d.get("to", ""),
                "status": d.get("status", "unknown"),
                "duration": int(time.time() - d.get("started", time.time())),
                "caller_name": d.get("caller_name", ""),
                "direction": d.get("direction", "incoming")
            }
            for sid, d in active_calls.items()
            if d.get("status") not in ("completed", "ended", "failed")
        ],
        "total_active": sum(1 for d in active_calls.values() if d.get("status") not in ("completed", "ended", "failed"))
    })


@twilio_bp.route('/register-caller', methods=['POST', 'OPTIONS'])
@require_auth
def register_known_caller():
    """Register caller for personalized greetings"""
    if request.method == 'OPTIONS':
        return '', 204

    data = request.json or {}
    phone = data.get("phone", "")
    name = data.get("name", "")

    if not phone or not name:
        return jsonify({"success": False, "error": "Chybí phone nebo name"}), 400

    known_callers[phone] = {
        "name": name,
        "formality": data.get("formality", "formal"),
        "contacts": data.get("contacts", {}),
        "user_id": data.get("user_id"),  # v231: link phone to user profile
        "registered_at": time.time()
    }
    return jsonify({
        "success": True,
        "message": f"Volající {name} ({phone}) registrován"
    })


@twilio_bp.route('/invite', methods=['POST', 'OPTIONS'])
@optional_auth
@rate_limit(10, 60, 'ip')  # v328: Rate limit SMS/WhatsApp invitations (Twilio costs)
def send_call_invitation():
    """Send SMS/WhatsApp invitation with Jitsi join link.
    v300: removed require_auth (seniors don't have JWT), added WhatsApp fallback."""
    if request.method == 'OPTIONS':
        return '', 204

    twilio_client = get_twilio_client()
    if not twilio_client or not TWILIO_PHONE_NUMBER:
        return jsonify({"success": False, "error": "Twilio není nakonfigurováno"}), 503

    try:
        data = request.json or {}
        to = data.get("to", "")
        caller_name = data.get("caller_name", "Váš blízký")
        room_code = data.get("room_code", "")
        call_type = data.get("call_type", "video")
        join_url = data.get("join_url", "")

        if not to or not room_code:
            return jsonify({"success": False, "error": "Chybí telefonní číslo nebo kód místnosti"}), 400

        # Normalize phone number
        to_clean = to.strip()
        if to_clean.startswith('00420'):
            to_clean = '+420' + to_clean[5:]
        elif not to_clean.startswith('+'):
            to_clean = '+420' + to_clean.lstrip('0')

        # Build join URL with parameters
        if not join_url:
            join_url = f"https://meet.jit.si/{room_code}"

        # Frontend join page URL (with nice UI)
        frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
        import urllib.parse
        caller_encoded = urllib.parse.quote(caller_name)
        nice_url = f"{frontend_url}/call.html?room={room_code}&from={caller_encoded}&type={call_type}"

        # Build message
        type_label = "video hovor" if call_type == "video" else "hlasový hovor"
        msg_body = f"📞 {caller_name} vás zve na {type_label} přes Radim.\n\nPřipojte se: {nice_url}\n\n(Stačí kliknout na odkaz, nic neinstalujete.)"

        # Try SMS first, fallback to WhatsApp, fallback to voice call announcement
        sent_via = None
        message_sid = None
        error_detail = None

        # Attempt 1: SMS
        try:
            message = twilio_client.messages.create(
                to=to_clean,
                from_=TWILIO_PHONE_NUMBER,
                body=msg_body
            )
            sent_via = 'sms'
            message_sid = message.sid
            logger.info(f"📱 SMS invite sent to {to_clean} (room: {room_code})")
        except Exception as sms_err:
            error_detail = str(sms_err)
            logger.warning(f"SMS invite failed: {sms_err}")

            # Attempt 2: WhatsApp (if SMS fails)
            try:
                message = twilio_client.messages.create(
                    to=f"whatsapp:{to_clean}",
                    from_=f"whatsapp:{TWILIO_PHONE_NUMBER}",
                    body=msg_body
                )
                sent_via = 'whatsapp'
                message_sid = message.sid
                logger.info(f"📲 WhatsApp invite sent to {to_clean} (room: {room_code})")
            except Exception as wa_err:
                logger.warning(f"WhatsApp invite also failed: {wa_err}")

                # Attempt 3: Twilio voice call with TTS announcement
                try:
                    tts_text = f"Máte pozvánku na {type_label} od {caller_name} přes Radim. Otevřete SMS nebo WhatsApp pro připojení."
                    call = twilio_client.calls.create(
                        to=to_clean,
                        from_=TWILIO_PHONE_NUMBER,
                        twiml=f'<Response><Say language="cs-CZ" voice="Polly.Jitka">{tts_text}</Say><Pause length="2"/><Say language="cs-CZ" voice="Polly.Jitka">Odkaz najdete ve zprávě. Na shledanou.</Say></Response>'
                    )
                    sent_via = 'voice_announcement'
                    message_sid = call.sid
                    logger.info(f"📞 Voice announcement sent to {to_clean} (room: {room_code})")
                except Exception as call_err:
                    logger.error(f"All invite methods failed for {to_clean}: SMS={sms_err}, WA={wa_err}, Voice={call_err}")

        return jsonify({
            "success": sent_via is not None,
            "sent_via": sent_via or "none",
            "message_sid": message_sid,
            "join_url": nice_url,
            "direct_jitsi_url": join_url,
            "room_code": room_code,
            "error": error_detail if not sent_via else None
        }), 200 if sent_via else 503

    except Exception as e:
        logger.error(f"Invite error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500


@twilio_bp.route('/tts', methods=['GET'])
@rate_limit(60, 60, 'ip')  # v328: Rate limit TTS generation (Azure costs)
def twilio_tts():
    """Azure TTS endpoint - returns MP3 audio of Radim's voice.
    Now reads adaptive rate/pitch params from Anticipation Engine via query string."""
    text = request.args.get('text', '')
    if not text:
        return Response(b'', content_type='audio/mpeg', status=400)

    # Read adaptive speech params (from Anticipation Engine via twiml_say URL)
    rate_pct = request.args.get('rate')    # e.g. "90%" or "-5%"
    pitch_hz = request.args.get('pitch')   # e.g. "-2Hz" or "+0Hz"

    audio = generate_azure_tts(text, rate_pct=rate_pct, pitch_hz=pitch_hz)
    if audio:
        return Response(audio, content_type='audio/mpeg', headers={
            'Cache-Control': 'public, max-age=3600',
            'Content-Length': str(len(audio))
        })
    else:
        # Azure TTS failed — return empty (Twilio will skip <Play> and continue)
        logger.error(f"TTS failed for: {text[:50]}")
        return Response(b'', content_type='audio/mpeg', status=500)


@twilio_bp.route('/health', methods=['GET'])
def twilio_health():
    """Twilio Voice health check"""
    return jsonify({
        "status": "healthy",
        "service": "Twilio Voice",
        "version": "1.2.0",
        "configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "phone_number": TWILIO_PHONE_NUMBER or "not set",
        "ai_available": bool(ANTHROPIC_API_KEY),
        "azure_tts": azure_tts_available(),
        "voice": RADIM_AZURE_VOICE if azure_tts_available() else RADIM_VOICE_BASIC,
        "anticipation_engine": ANTICIPATION_AVAILABLE,
        "active_calls": len([d for d in active_calls.values() if d.get("status") not in ("completed", "ended", "failed")]),
        "known_callers": len(known_callers)
    })
