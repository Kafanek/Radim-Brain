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
from flask import Blueprint, request, jsonify, Response

logger = logging.getLogger(__name__)

# Flask Blueprint
twilio_bp = Blueprint('twilio_voice', __name__, url_prefix='/api/twilio')

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


def generate_azure_tts(text):
    """Generate audio bytes using Azure TTS (AntoninNeural - Radim's voice)"""
    if not azure_tts_available():
        return None

    try:
        url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='cs-CZ'>
            <voice name='{RADIM_AZURE_VOICE}'>
                <prosody rate='-5%' pitch='-2%'>{text}</prosody>
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


def twiml_say(text):
    """Generate TwiML for Radim speaking - uses Azure TTS <Play> or fallback <Say>"""
    if azure_tts_available():
        # Use Azure TTS via /api/twilio/tts endpoint
        from urllib.parse import quote
        encoded = quote(text, safe='')
        backend_url = os.environ.get('BACKEND_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
        return f'<Play>{backend_url}/api/twilio/tts?text={encoded}</Play>'
    else:
        # Fallback: basic male voice
        return f'<Say voice="{RADIM_VOICE_BASIC}" language="{RADIM_LANG}">{text}</Say>'


# ============================================================================
# STATE MANAGEMENT
# ============================================================================

# Active calls: { call_sid: { from, to, started, history[], caller_name, status } }
active_calls = {}

# Known callers: { phone: { name, formality, contacts } }
known_callers = {}

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


def get_ai_response_for_call(user_text, call_sid):
    """Get Claude AI response for phone conversation (synchronous for Flask)"""
    if not ANTHROPIC_API_KEY:
        return "Omlouvám se, právě mám technické potíže. Zkuste to prosím za chvíli."

    call_data = active_calls.get(call_sid, {})
    history = call_data.get("history", [])
    caller_name = call_data.get("caller_name", "")

    # Build messages
    messages = []
    for msg in history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    name_ctx = f"Voláš se seniorem jménem {caller_name}. " if caller_name else ""
    system_prompt = f"""Jsi RADIM - AI asistent pro seniory. {name_ctx}Právě vedeš telefonní hovor.

PRAVIDLA PRO TELEFONNÍ HOVOR:
- Odpovídej KRÁTCE (max 2-3 věty), protože to je telefonní hovor, ne chat
- Mluv jednoduše, jasně a s respektem
- Vykej (Pan/Paní), pokud uživatel nepřejde na tykání
- Buď empatický a trpělivý
- Pokud senior chce zavolat někomu (dcera, syn, doktor), řekni "Rozumím, přepojím vás."
- NIKDY neříkej "jako AI" nebo "jako chatbot" — jsi Radim, asistent

12 hodnot: empatie, respekt, trpělivost, důstojnost, naslouchání, konkrétní pomoc.
Smlouva: "Jsem zde, abych naslouchal, ne abych soudil." """

    try:
        # Try Anthropic SDK first
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_API_KEY)
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
def twilio_voice_webhook():
    """Incoming call handler — Twilio webhook"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        caller = request.form.get("From", "unknown")
        called = request.form.get("To", "")

        logger.info(f"📞 Incoming call: {caller} → {called} (SID: {call_sid})")
        print(f"📞 Incoming call: {caller} → {called} (SID: {call_sid})")

        # Register active call
        active_calls[call_sid] = {
            "from": caller,
            "to": called,
            "started": time.time(),
            "history": [],
            "caller_name": "",
            "status": "active"
        }

        # Personalized greeting
        caller_data = known_callers.get(caller, {})
        caller_name = caller_data.get("name", "")
        if caller_name:
            active_calls[call_sid]["caller_name"] = caller_name
            greeting = f"Dobrý den, {caller_name}! Tady Radim. Jak vám mohu pomoci?"
        else:
            greeting = "Dobrý den, tady Radim. Jsem váš asistent. Jak vám mohu pomoci?"

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
def twilio_gather_webhook():
    """Speech recognized — Twilio STT webhook"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        speech_result = request.form.get("SpeechResult", "")
        confidence = request.form.get("Confidence", "0")
        caller = request.form.get("From", "unknown")

        logger.info(f"🎤 Speech: '{speech_result}' (confidence: {confidence}, SID: {call_sid})")
        print(f"🎤 Speech: '{speech_result}' (confidence: {confidence})")

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
                            say_outgoing = twiml_say("Dobrý den, volá vám Radim v zastoupení vašeho blízkého.")
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

        # Normal AI conversation
        ai_response = get_ai_response_for_call(speech_result, call_sid)
        ai_safe = ai_response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

        say_ai = twiml_say(ai_safe if not azure_tts_available() else ai_response)
        say_here3 = twiml_say("Jsem tu pro vás.")
        say_end = twiml_say("Pokud nepotřebujete nic dalšího, přeji vám krásný den!")

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
def twilio_status_webhook():
    """Call status callback"""
    try:
        call_sid = request.form.get("CallSid", "unknown")
        call_status = request.form.get("CallStatus", "unknown")
        duration = request.form.get("CallDuration", "0")
        logger.info(f"📊 Call status: {call_sid} → {call_status} (duration: {duration}s)")
        print(f"📊 Call status: {call_sid} → {call_status} (duration: {duration}s)")
        if call_sid in active_calls:
            active_calls[call_sid]["status"] = call_status
            if call_status in ("completed", "failed", "busy", "no-answer"):
                active_calls[call_sid]["ended"] = time.time()
                active_calls[call_sid]["duration"] = int(duration)
    except Exception as e:
        logger.warning(f"Status webhook error: {e}")
    return '', 204


@twilio_bp.route('/dial-status', methods=['POST'])
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
        greeting = data.get("greeting") or "Dobrý den, volá vám Radim, asistent pro seniory."

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
        return jsonify({"success": False, "error": f"Nepodařilo se zahájit hovor: {str(e)}"}), 500


@twilio_bp.route('/active-calls', methods=['GET'])
def get_active_calls():
    """List active phone calls"""
    # Cleanup old calls (2h+)
    cutoff = time.time() - 7200
    expired = [sid for sid, d in active_calls.items() if d.get("started", 0) < cutoff]
    for sid in expired:
        del active_calls[sid]

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
        "registered_at": time.time()
    }
    return jsonify({
        "success": True,
        "message": f"Volající {name} ({phone}) registrován"
    })


@twilio_bp.route('/tts', methods=['GET'])
def twilio_tts():
    """Azure TTS endpoint - returns MP3 audio of Radim's voice"""
    text = request.args.get('text', '')
    if not text:
        return Response(b'', content_type='audio/mpeg', status=400)

    audio = generate_azure_tts(text)
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
        "version": "1.1.0",
        "configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "phone_number": TWILIO_PHONE_NUMBER or "not set",
        "ai_available": bool(ANTHROPIC_API_KEY),
        "azure_tts": azure_tts_available(),
        "voice": RADIM_AZURE_VOICE if azure_tts_available() else RADIM_VOICE_BASIC,
        "active_calls": len([d for d in active_calls.values() if d.get("status") not in ("completed", "ended", "failed")]),
        "known_callers": len(known_callers)
    })
