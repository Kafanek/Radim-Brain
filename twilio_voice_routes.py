"""
📞 TWILIO VOICE ROUTES — Flask Blueprint for phone call handling
================================================================
Version: 2.0.0 (modular)

Architecture:
  twilio_voice_helpers.py  — auth, TTS, state, AI, intent detection
  twilio_voice_routes.py (this file) — Blueprint + route handlers

Routes:
  POST /api/twilio/voice       — Incoming call webhook
  POST /api/twilio/gather      — Speech recognized webhook
  POST /api/twilio/status      — Call status callback
  POST /api/twilio/dial-status — Transfer result handler
  POST /api/twilio/call        — Initiate outgoing call
  GET  /api/twilio/active-calls — List active calls
  POST /api/twilio/register-caller — Register known caller
  POST /api/twilio/invite      — Send SMS/WhatsApp invitation
  GET  /api/twilio/tts         — Azure TTS endpoint
  GET  /api/twilio/health      — Health check
"""

import os
import time
import logging
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify, Response
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit

# Import all helpers
from twilio_voice_helpers import (
    # Decorators
    validate_twilio_signature,
    # Shared utils
    _build_voice_time_context, _shared_get_greeting,
    # Anticipation Engine
    ANTICIPATION_AVAILABLE, estimate_call_C_alpha, get_adaptive_speech_params,
    # Config
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, ANTHROPIC_API_KEY,
    RADIM_AZURE_VOICE, RADIM_VOICE_BASIC,
    get_twilio_client, azure_tts_available, generate_azure_tts,
    # TTS
    twiml_say, twiml_response,
    # State
    active_calls, known_callers, _cleanup_active_calls, _cleanup_known_callers,
    # Intent
    CONFERENCE_PATTERNS,
    # Helpers
    get_ai_response_for_call, detect_transfer_intent, lookup_contact_phone
)

logger = logging.getLogger(__name__)

# Flask Blueprint
twilio_bp = Blueprint('twilio_voice', __name__, url_prefix='/api/twilio')


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

        # Register active call
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
            "user_id": caller_data.get("user_id")
        }

        caller_name = caller_data.get("name", "")
        if caller_name:
            active_calls[call_sid]["caller_name"] = caller_name

        tc = _build_voice_time_context()
        greet_word = _shared_get_greeting(with_emoji=False)

        name_part = f", {caller_name}" if caller_name else ""
        date_part = f"Dnes je {tc['day_name']} {tc['date_str']}."
        nameday_part = f" Svátek má {tc['nameday']}." if tc["nameday"] else ""
        greeting = f"{greet_word}{name_part}, tady Radim. {date_part}{nameday_part} Jak se máte?"

        active_calls[call_sid]["history"].append({
            "role": "assistant", "content": greeting
        })

        say_greeting = twiml_say(greeting)
        say_listen = twiml_say("Poslouchám vás.")
        say_noheard = twiml_say("Neslyšel jsem vás. Pokud potřebujete pomoc, zavolejte znovu.")

        # v396: Adaptive gather params per user profile (aphasia, dysarthria → longer timeout)
        # v397: Speech hints from profile (medications, names) improve STT accuracy
        try:
            from speech_understanding import get_gather_params, build_speech_hints
            _caller_uid = caller_data.get("user_id")
            gp = get_gather_params(_caller_uid)
            gp["hints"] = build_speech_hints(_caller_uid)
        except ImportError:
            gp = {"speech_timeout": 3, "timeout": 10, "language": "cs-CZ", "hints": ""}
        hints_attr = f' hints="{gp["hints"]}"' if gp.get("hints") else ""

        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_greeting}
    <Gather input="speech" language="{gp['language']}" action="/api/twilio/gather" method="POST" speechTimeout="{gp['speech_timeout']}" timeout="{gp['timeout']}"{hints_attr}>
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

        logger.info(f"🎤 Speech: '{speech_result}' (confidence: {confidence})")

        # v396: Get adaptive params for this user
        call_data = active_calls.get(call_sid, {})
        _user_id = call_data.get("user_id")
        try:
            from speech_understanding import get_gather_params, should_retry_stt, correct_stt_output
            gp = get_gather_params(_user_id)
            # v397: STT post-processing — fix common Czech recognition errors
            # v401: Pass user_id for per-user learned corrections
            if speech_result:
                speech_result, _corrections = correct_stt_output(speech_result, user_id=_user_id)
                if _corrections:
                    logger.info(f"🔧 STT corrected: {_corrections}")
        except ImportError:
            gp = {"speech_timeout": 3, "timeout": 10, "language": "cs-CZ", "hints": ""}

        if not speech_result.strip():
            # v407: Track consecutive silence — after 2 silences, escalate
            silence_count = call_data.get("silence_count", 0) + 1
            if call_sid in active_calls:
                active_calls[call_sid]["silence_count"] = silence_count

            if silence_count >= 3:
                # Senior unresponsive 3× — possible emergency (fall, stroke, unconscious)
                logger.warning(f"🚨 SILENT EMERGENCY: {call_sid} — {silence_count}× no response, escalating")
                say_help = twiml_say("Neslyším vás už delší dobu. Pro jistotu informuji vaši rodinu. Zůstaňte v klidu.")
                try:
                    from agent_loop import _alert_caregiver
                    obs = {"type": "silent_emergency", "severity": "ALERT",
                           "message": f"Senior neodpovídá na telefonu ({silence_count}× mlčení)",
                           "details": {"call_sid": call_sid, "silence_count": silence_count}}
                    _alert_caregiver(_user_id, obs, None)
                except Exception:
                    pass
                return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_help}
    <Pause length="3"/>
    <Say language="cs-CZ" voice="Polly.Adela">Pokud potřebujete záchrannou službu, zavěste a zavolejte jedna pět pět.</Say>
</Response>""")

            say_retry = twiml_say("Promiňte, neslyšel jsem vás. Můžete to zopakovat?")
            say_here = twiml_say("Jsem tu pro vás.")
            return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_retry}
    <Gather input="speech" language="{gp['language']}" action="/api/twilio/gather" method="POST" speechTimeout="{gp['speech_timeout']}" timeout="{gp['timeout']}">
        {say_here}
    </Gather>
</Response>""")

        # v402: CRITICAL PATH BYPASS — safety-first, skip AI delay
        try:
            from speech_understanding import classify_safety_priority
            priority = classify_safety_priority(speech_result, confidence)
            if priority["priority"] == "CRITICAL" and priority["bypass_ai"]:
                logger.warning(f"🚨 CRITICAL SAFETY: '{speech_result}' → bypass AI [{priority['reason']}]")
                say_help = twiml_say("Rozumím, potřebujete pomoc. Zůstaňte v klidu, volám pomoc a informuji rodinu.")
                # Trigger escalation in background
                try:
                    from agent_loop import _alert_caregiver, _crisis_escalate
                    obs = {"type": "voice_crisis", "severity": "CRISIS",
                           "message": f"Hlasová krize: '{speech_result}'", "details": {"confidence": confidence}}
                    _alert_caregiver(_user_id, obs, None)
                except Exception:
                    pass
                return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_help}
    <Pause length="2"/>
    <Say language="cs-CZ" voice="Polly.Adela">Pokud potřebujete záchrannou službu, zavěste a zavolejte jedna pět pět.</Say>
</Response>""")
        except ImportError:
            pass

        # v396: Low confidence → retry or safety escalation
        try:
            action, data = should_retry_stt(speech_result, confidence, _user_id)
            if action == "retry":
                logger.info(f"🔄 Low confidence ({confidence}), asking to repeat")
                say_again = twiml_say("Promiňte, nerozuměl jsem dobře. Řekněte to prosím ještě jednou, pomaleji.")
                say_here = twiml_say("Poslouchám.")
                return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_again}
    <Gather input="speech" language="{gp['language']}" action="/api/twilio/gather" method="POST" speechTimeout="{gp['speech_timeout']}" timeout="{gp['timeout']}">
        {say_here}
    </Gather>
</Response>""")
            elif action == "safety":
                logger.warning(f"🚨 FUZZY SAFETY detected: '{data['input']}' → '{data['word']}' (conf={confidence})")
                say_confirm = twiml_say("Slyšel jsem, že potřebujete pomoc. Je to tak? Řekněte ano, nebo stiskněte jedničku.")
                return twiml_response(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_confirm}
    <Gather input="speech dtmf" numDigits="1" language="{gp['language']}" action="/api/twilio/gather" method="POST" speechTimeout="5" timeout="10">
    </Gather>
</Response>""")
        except ImportError:
            pass

        # v407: Reset silence counter — senior is speaking normally
        if call_sid in active_calls:
            active_calls[call_sid]["silence_count"] = 0

        # Check transfer intent
        transfer = detect_transfer_intent(speech_result)
        if transfer:
            want_conference = bool(CONFERENCE_PATTERNS.search(speech_result))
            target_phone = lookup_contact_phone(transfer["target"], caller)

            if target_phone:
                if want_conference:
                    conf_name = f"radim-{call_sid[:8]}"
                    say_conf = twiml_say(f"Přidávám vaši {transfer['name']} do hovoru. Zůstanu s vámi.")
                    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    {say_conf}
    <Dial>
        <Conference startConferenceOnEnter="true" endConferenceOnExit="false">{conf_name}</Conference>
    </Dial>
</Response>"""
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

        # Anticipation Engine: C/α → adaptive TTS
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

        # Normal AI conversation
        _call_uid = active_calls.get(call_sid, {}).get("user_id")
        ai_response = get_ai_response_for_call(speech_result, call_sid, user_id=_call_uid)
        ai_safe = ai_response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

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
@rate_limit(5, 60, 'ip')
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

    _cleanup_known_callers()
    known_callers[phone] = {
        "name": name,
        "formality": data.get("formality", "formal"),
        "contacts": data.get("contacts", {}),
        "user_id": data.get("user_id"),
        "registered_at": time.time()
    }
    return jsonify({
        "success": True,
        "message": f"Volající {name} ({phone}) registrován"
    })


@twilio_bp.route('/invite', methods=['POST', 'OPTIONS'])
@optional_auth
@rate_limit(10, 60, 'ip')
def send_call_invitation():
    """Send SMS/WhatsApp invitation with Jitsi join link."""
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

        if not join_url:
            join_url = f"https://meet.jit.si/{room_code}"

        frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
        import urllib.parse
        caller_encoded = urllib.parse.quote(caller_name)
        nice_url = f"{frontend_url}/call.html?room={room_code}&from={caller_encoded}&type={call_type}"

        type_label = "video hovor" if call_type == "video" else "hlasový hovor"
        msg_body = f"📞 {caller_name} vás zve na {type_label} přes Radim.\n\nPřipojte se: {nice_url}\n\n(Stačí kliknout na odkaz, nic neinstalujete.)"

        sent_via = None
        message_sid = None
        error_detail = None

        # Attempt 1: SMS
        try:
            message = twilio_client.messages.create(
                to=to_clean, from_=TWILIO_PHONE_NUMBER, body=msg_body
            )
            sent_via = 'sms'
            message_sid = message.sid
            logger.info(f"📱 SMS invite sent to {to_clean} (room: {room_code})")
        except Exception as sms_err:
            error_detail = str(sms_err)
            logger.warning(f"SMS invite failed: {sms_err}")

            # Attempt 2: WhatsApp
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

                # Attempt 3: Voice call announcement
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


# ============================================================================
# 📹 VIDEO CALL SIGNALING — incoming calls + agent auto-call
# ============================================================================

# In-memory store for pending calls (room_code → call info)
_pending_calls = {}

@twilio_bp.route('/video/request', methods=['POST', 'OPTIONS'])
@optional_auth
def video_call_request():
    """Request a video call TO a senior (from family, doctor, or agent).

    Creates a pending call that the senior's frontend polls for.
    Also sends push notification + SocketIO event to senior.

    Body: {
        "senior_id": "user-123",
        "caller_name": "Dcera Marie",
        "caller_phone": "+420...",
        "call_type": "video" | "audio",
        "reason": "family" | "medical" | "agent_crisis" | "agent_alert"
    }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.json or {}
    senior_id = data.get('senior_id', '')
    caller_name = data.get('caller_name', 'Někdo')
    call_type = data.get('call_type', 'video')
    reason = data.get('reason', 'family')

    if not senior_id:
        return jsonify({'success': False, 'error': 'senior_id required'}), 400

    import time
    room_code = f"radim-{reason}-{int(time.time())}"
    jitsi_url = f"https://meet.jit.si/{room_code}"

    call_info = {
        'room_code': room_code,
        'jitsi_url': jitsi_url,
        'caller_name': caller_name,
        'call_type': call_type,
        'reason': reason,
        'senior_id': senior_id,
        'created_at': datetime.utcnow().isoformat(),
        'status': 'ringing',  # ringing → accepted → ended → expired
    }
    _pending_calls[senior_id] = call_info

    # Push notification to senior
    try:
        from push_helpers import send_push_to_user
        icon = '📹' if call_type == 'video' else '📞'
        send_push_to_user(senior_id, f'{icon} {caller_name} vám volá!', 'Klikněte pro přijetí hovoru')
    except Exception as e:
        logger.debug(f"Push for video call failed: {e}")

    # SocketIO notification to senior's frontend
    try:
        from app import socketio
        socketio.emit('incoming_call', call_info, room=senior_id)
    except Exception as e:
        logger.debug(f"SocketIO incoming_call failed: {e}")

    logger.info(f"📹 Video call request: {caller_name} → {senior_id} (room={room_code})")

    return jsonify({
        'success': True,
        'room_code': room_code,
        'jitsi_url': jitsi_url,
        **call_info
    })


@twilio_bp.route('/app/call', methods=['POST', 'OPTIONS'])
@optional_auth
def app_to_app_call():
    """App-to-app call — no SMS, just SocketIO popup.

    Used for in-house calling (e.g., senior home → café).
    Reuses _pending_calls + incoming_call SocketIO event.

    Body: {
        "to_user_id": "kavarna-haje",
        "caller_name": "Václav Novák",
        "call_type": "video" | "audio"
    }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.json or {}
    to_user_id = data.get('to_user_id', '')
    # Duplicate call prevention
    existing = _pending_calls.get(to_user_id)
    if existing and existing.get('status') == 'ringing':
        created = datetime.fromisoformat(existing['created_at'])
        if (datetime.utcnow() - created).total_seconds() < 60:
            return jsonify({'success': False, 'error': 'Hovor již probíhá'}), 409
    caller_name = data.get('caller_name', 'Někdo')
    call_type = data.get('call_type', 'video')

    if not to_user_id:
        return jsonify({'success': False, 'error': 'to_user_id required'}), 400

    import time
    room_code = f"radim-app-{int(time.time())}"
    jitsi_url = f"https://meet.jit.si/{room_code}"

    call_info = {
        'room_code': room_code,
        'jitsi_url': jitsi_url,
        'caller_name': caller_name,
        'call_type': call_type,
        'reason': 'app',
        'senior_id': to_user_id,
        'created_at': datetime.utcnow().isoformat(),
        'status': 'ringing',
    }
    _pending_calls[to_user_id] = call_info

    # Push notification
    try:
        from push_helpers import send_push_to_user
        icon = '📹' if call_type == 'video' else '📞'
        send_push_to_user(to_user_id, f'{icon} {caller_name} volá!', 'Klikněte pro přijetí')
    except Exception as e:
        logger.debug(f"Push for app call failed: {e}")

    # SocketIO — real-time popup
    try:
        from app import socketio
        socketio.emit('incoming_call', call_info, room=to_user_id)
    except Exception as e:
        logger.debug(f"SocketIO app call failed: {e}")

    logger.info(f"📱 App call: {caller_name} → {to_user_id} (room={room_code})")

    return jsonify({
        'success': True,
        'room_code': room_code,
        'jitsi_url': jitsi_url,
    })


@twilio_bp.route('/video/pending/<senior_id>', methods=['GET'])
def video_call_pending(senior_id):
    """Check if there's a pending incoming call for this senior.
    Frontend polls this every 5 seconds.
    """
    call = _pending_calls.get(senior_id)
    if call and call.get('status') == 'ringing':
        # Auto-expire after 60s
        created = datetime.fromisoformat(call['created_at'])
        if (datetime.utcnow() - created).total_seconds() > 60:
            call['status'] = 'expired'
            return jsonify({'pending': False, 'expired': True})
        return jsonify({'pending': True, **call})
    return jsonify({'pending': False})


@twilio_bp.route('/video/accept/<senior_id>', methods=['POST'])
def video_call_accept(senior_id):
    """Senior accepts the incoming call."""
    call = _pending_calls.get(senior_id)
    if not call or call.get('status') != 'ringing':
        return jsonify({'success': False, 'error': 'No pending call'}), 404

    call['status'] = 'accepted'

    # Notify caller via SocketIO
    try:
        from app import socketio
        socketio.emit('call_accepted', call, room=call.get('caller_id', ''))
    except Exception:
        pass

    return jsonify({'success': True, **call})


@twilio_bp.route('/video/reject/<senior_id>', methods=['POST'])
def video_call_reject(senior_id):
    """Senior rejects or is busy for the incoming call."""
    data = request.json or {}
    reason = data.get('reason', 'rejected')  # 'rejected' or 'busy'

    call = _pending_calls.pop(senior_id, None)
    if call:
        call['status'] = reason

        # Notify caller that call was rejected/busy
        try:
            from app import socketio
            socketio.emit('call_rejected', {
                'senior_id': senior_id,
                'reason': reason,
                'caller_name': call.get('caller_name', ''),
            }, room=call.get('caller_id', ''))
        except Exception:
            pass

    return jsonify({'success': True, 'reason': reason})


@twilio_bp.route('/video/end/<senior_id>', methods=['POST'])
def video_call_end(senior_id):
    """End active video call."""
    call = _pending_calls.pop(senior_id, None)
    if call:
        call['status'] = 'ended'
    return jsonify({'success': True})


@twilio_bp.route('/tts', methods=['GET'])
@rate_limit(60, 60, 'ip')
def twilio_tts():
    """Azure TTS endpoint - returns MP3 audio"""
    text = request.args.get('text', '')
    if not text:
        return Response(b'', content_type='audio/mpeg', status=400)

    rate_pct = request.args.get('rate')
    pitch_hz = request.args.get('pitch')
    mode = request.args.get('mode', 'HARMONY')
    user_id = request.args.get('user_id')

    audio = generate_azure_tts(text, rate_pct=rate_pct, pitch_hz=pitch_hz, mode=mode, user_id=user_id)
    if audio:
        return Response(audio, content_type='audio/mpeg', headers={
            'Cache-Control': 'public, max-age=3600',
            'Content-Length': str(len(audio))
        })
    else:
        logger.error(f"TTS failed for: {text[:50]}")
        return Response(b'', content_type='audio/mpeg', status=500)


# ============================================================================
# WHATSAPP INCOMING MESSAGE WEBHOOK (v387)
# ============================================================================

@twilio_bp.route('/whatsapp', methods=['POST'])
def whatsapp_incoming():
    """Handle incoming WhatsApp messages from seniors.

    Twilio sends POST with: Body, From (whatsapp:+420...), To, MessageSid
    We respond with Radim's AI response via TwiML <Message>.
    """
    body = request.form.get('Body', '').strip()
    from_number = request.form.get('From', '')  # whatsapp:+420123456789
    message_sid = request.form.get('MessageSid', '')

    if not body:
        return '<Response></Response>', 200, {'Content-Type': 'text/xml'}

    # Extract phone number
    phone = from_number.replace('whatsapp:', '')

    # Look up user_id by phone
    user_id = _lookup_user_by_phone(phone)

    logger.info(f"💬 WhatsApp from {phone}: {body[:50]}...")

    try:
        # Use same pipeline as /api/radim/chat
        from radim_orchestrator import radim_chat_internal
        result = radim_chat_internal(body, user_id=user_id, mode="senior")
        response_text = result.get("response", "Omlouvám se, zkuste to znovu.")
    except ImportError:
        # Fallback: direct Gemini call
        try:
            from radim_ai_engine import call_gemini_whatsapp
            response_text, _ = call_gemini_whatsapp(body, {}, "senior", "", None, "", None)
        except Exception:
            response_text = "Dobrý den, momentálně nejsem dostupný. Zkuste to prosím později."
    except Exception as e:
        logger.error(f"WhatsApp AI error: {e}")
        response_text = "Omlouvám se, nastala chyba. Zkuste to prosím znovu."

    # Truncate for SMS limits (1600 chars for WhatsApp)
    if len(response_text) > 1500:
        response_text = response_text[:1497] + "..."

    # TwiML response
    twiml = f'<Response><Message>{xml_escape(response_text)}</Message></Response>'
    return twiml, 200, {'Content-Type': 'text/xml'}


def _lookup_user_by_phone(phone):
    """Find user_id by phone number in memory_profiles."""
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT user_id FROM memory_profiles WHERE data->>'phone' = ?",
                (phone,)
            ).fetchone()
            if row:
                return row['user_id'] or row[0]
    except Exception:
        pass
    return None


@twilio_bp.route('/health', methods=['GET'])
def twilio_health():
    """Twilio Voice health check"""
    return jsonify({
        "status": "healthy",
        "service": "Twilio Voice",
        "version": "2.0.0",
        "configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "phone_number": TWILIO_PHONE_NUMBER or "not set",
        "ai_available": bool(ANTHROPIC_API_KEY),
        "azure_tts": azure_tts_available(),
        "voice": RADIM_AZURE_VOICE if azure_tts_available() else RADIM_VOICE_BASIC,
        "anticipation_engine": ANTICIPATION_AVAILABLE,
        "active_calls": len([d for d in active_calls.values() if d.get("status") not in ("completed", "ended", "failed")]),
        "known_callers": len(known_callers)
    })
