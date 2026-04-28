# ============================================
# RADIM VOICE RUNTIME ROUTES v2.0.0
# ============================================
# API endpoints for voice runtime.
# Math engine + sessions in voice_runtime_engine.py
# ============================================

import os
import logging
import requests
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify
from auth_middleware import require_auth

logger = logging.getLogger(__name__)

# Import engine
from voice_runtime_engine import (
    # Constants
    PHI, DELTA, RADIM_R, FIBONACCI,
    THRESHOLD_HARMONY, THRESHOLD_ALERT,
    STATES,
    # Session management
    get_session, save_session, sessions,
    # Math functions
    compute_C, compute_kappa, compute_alpha,
    get_system_state, get_tts_params,
    # Relevance & echo
    compute_relevance, compute_echo_similarity,
    # TTS cleaner
    clean_for_tts,
)

# Intent Resolver (v272 — local NLU)
try:
    from intent_resolver import resolve_intent as _vr_resolve_intent
    _VR_INTENT_RESOLVER = True
except ImportError:
    _VR_INTENT_RESOLVER = False

# Anticipation Engine
try:
    from anticipation_routes import (
        predict_C as ant_predict_C, calculate_emotions as ant_calculate_emotions,
        calculate_speech_params as ant_calculate_speech_params,
        classify_state as ant_classify_state
    )
    _ANT_AVAILABLE = True
except ImportError:
    _ANT_AVAILABLE = False

# Voice system prompt
from radim_system_prompt import get_voice_prompt as _build_voice_prompt
from radim_shared import build_time_context as _shared_time_context
from ai_config import GEMINI_MODEL

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

voice_runtime_bp = Blueprint('voice_runtime', __name__, url_prefix='/api/voice')


# ============================================
# AI RESPONSE
# ============================================

def get_voice_ai_response(messages, context=None):
    """Získat AI odpověď optimalizovanou pro hlasový výstup"""
    tc = _shared_time_context()
    date_str = f"{tc['day_name']}, {tc['date_str']} {tc['year']}"
    nameday = tc['nameday'] or 'Neznámý'

    system_prompt = _build_voice_prompt(date=date_str, nameday=nameday)

    # Zkusit Gemini
    if GEMINI_API_KEY:
        try:
            conversation = "\n".join([f"{'Uživatel' if m.get('role') == 'user' else 'Radim'}: {m.get('content', '')}" for m in messages[-6:]])
            prompt = f"{system_prompt}\n\nKonverzace:\n{conversation}\n\nRadim:"

            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 100,
                        "topP": 0.9
                    }
                },
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('candidates'):
                    parts = data['candidates'][0].get('content', {}).get('parts', [])
                    text = parts[0]['text'].strip() if parts and parts[0].get('text') else None
                    if text:
                        text = clean_for_tts(text)
                        return {'response': text, 'provider': 'gemini', 'success': True}
        except Exception as e:
            logger.error(f"Gemini voice error: {e}")

    # Fallback na Claude
    if ANTHROPIC_API_KEY:
        try:
            api_messages = [{"role": m.get('role', 'user'), "content": m.get('content', '')} for m in messages[-6:]]

            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 100,
                    "system": system_prompt,
                    "messages": api_messages
                },
                timeout=15
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('content') and data['content'][0].get('text'):
                    text = data['content'][0]['text'].strip()
                    text = clean_for_tts(text)
                    return {'response': text, 'provider': 'claude', 'success': True}
        except Exception as e:
            logger.error(f"Claude voice error: {e}")

    return {'response': 'Omlouvám se, zkuste to prosím znovu.', 'provider': 'fallback', 'success': False}


# ============================================
# API ENDPOINTS
# ============================================

@voice_runtime_bp.route('/health', methods=['GET'])
def voice_health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'RADIM Voice Runtime v2.0.0',
        'anticipation_engine': _ANT_AVAILABLE,
        'constants': {
            'phi': PHI,
            'delta': DELTA,
            'radim_r': RADIM_R
        },
        'thresholds': {
            'harmony': THRESHOLD_HARMONY,
            'alert': THRESHOLD_ALERT
        }
    })


@voice_runtime_bp.route('/metrics', methods=['POST'])
@require_auth
def compute_metrics():
    """
    Hlavní endpoint pro výpočet metrik

    Input: {session_id, sensors, bio, user_text}
    Output: {C, kappa, alpha, system_state, relevance, should_respond, tts_params}
    """
    try:
        data = request.get_json(silent=True) or {}

        session_id = data.get('session_id', 'default')
        sensors = data.get('sensors', {})
        bio = data.get('bio', {})
        user_text = data.get('user_text', '')

        session = get_session(session_id)

        # Výpočet metrik
        C = compute_C(sensors, bio)
        system_state = get_system_state(C)
        alpha = compute_alpha(system_state, user_text)
        kappa = compute_kappa(C, alpha, session['kappa'])

        # Relevance
        relevance = compute_relevance(user_text)

        # Echo check
        echo_sim = compute_echo_similarity(user_text, session['last_tts_text'])
        is_echo = echo_sim > 0.75

        # Rozhodnutí o odpovědi
        should_respond = relevance >= 0.6 and not is_echo

        # TTS parametry
        tts_params = get_tts_params(system_state)

        # Update session
        session['C'] = C
        session['kappa'] = kappa
        session['alpha'] = alpha

        # Persist to DB on significant state changes
        if should_respond or system_state != 'HARMONIE':
            save_session(session_id)

        return jsonify({
            'C': round(C, 2),
            'kappa': round(kappa, 3),
            'alpha': round(alpha, 2),
            'system_state': system_state,
            'relevance': round(relevance, 2),
            'echo_similarity': round(echo_sim, 2),
            'is_echo': is_echo,
            'should_respond': should_respond,
            'tts_params': tts_params,
            'fibonacci_pause_ms': FIBONACCI[5] * 100  # 500ms base
        })

    except Exception as e:
        logger.error(f"voice metrics error: {e}")
        return jsonify({'error': 'Interní chyba serveru'}), 500


@voice_runtime_bp.route('/state', methods=['POST'])
@require_auth
def update_state():
    """
    Update stavového automatu

    Input: {session_id, event, data}
    Events: wake_detected, voice_valid, voice_invalid, timeout, speech_end, response_ready, tts_done
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get('session_id', 'default')
        event = data.get('event', '')
        event_data = data.get('data', {})

        session = get_session(session_id)
        current_state = session['state']
        new_state = current_state

        # Stavový automat přechody
        if current_state == STATES['IDLE']:
            if event == 'wake_detected':
                new_state = STATES['WAKE_DETECTED']
                session['wake_count'] += 1

        elif current_state == STATES['WAKE_DETECTED']:
            if event == 'voice_valid':
                new_state = STATES['LISTENING']
            elif event == 'voice_invalid' or event == 'timeout':
                new_state = STATES['IDLE']

        elif current_state == STATES['LISTENING']:
            if event == 'speech_end':
                new_state = STATES['THINKING']
            elif event == 'timeout':
                new_state = STATES['IDLE']

        elif current_state == STATES['THINKING']:
            if event == 'response_ready':
                new_state = STATES['SPEAKING']
                session['last_tts_text'] = event_data.get('text', '')

        elif current_state == STATES['SPEAKING']:
            if event == 'tts_done':
                new_state = STATES['IDLE']

        session['state'] = new_state

        if current_state != new_state:
            save_session(session_id)

        return jsonify({
            'previous_state': current_state,
            'current_state': new_state,
            'event': event,
            'session': {
                'C': session['C'],
                'kappa': session['kappa'],
                'wake_count': session['wake_count']
            }
        })

    except Exception as e:
        logger.error(f"voice state error: {e}")
        return jsonify({'error': 'Interní chyba serveru'}), 500


@voice_runtime_bp.route('/session/<session_id>', methods=['GET'])
@require_auth
def get_session_info(session_id):
    """Získat informace o session"""
    session = get_session(session_id)
    return jsonify({
        'session_id': session_id,
        'state': session['state'],
        'metrics': {
            'C': session['C'],
            'kappa': session['kappa'],
            'alpha': session['alpha']
        },
        'system_state': get_system_state(session['C']),
        'wake_count': session['wake_count'],
        'created': session['created']
    })


@voice_runtime_bp.route('/prompt', methods=['GET'])
@require_auth
def get_claude_prompt():
    """Vrátí system prompt pro Claude Voice Runtime"""
    prompt = """Jsi RADIM, hlasový agent pro seniory a chytré prostředí.
Odpovídáš pouze na dotazy, které prošly wakewordem „Radime?" a relevance filtrem.
Nikdy neodpovídáš na televizi ani cizí rozhovor.
Máš k dispozici stavové metriky z matematického enginu: C(t), κ(t), α(t), stav {HARMONIE, ALERT, KRIZE}.
Tyto metriky jsou pravda. Nikdy si je nevymýšlíš a nikdy je neupravuješ.
Tvůj úkol: vytvořit krátkou, lidskou a bezpečnou odpověď.

* HARMONIE (C<12): přátelsky, normálně dlouhé věty.
* ALERT (12≤C<27): zpomal, zkrať věty, navrhni mikro-intervenci (30–90 s).
* KRIZE (C≥27): 1 instrukce, pauza, opakuj, možnost eskalace (pečující/SOS).

Pokud dotaz není o uživateli, jeho prostředí, bezpečí nebo Radim systému, odpověď je: mlčet (RETURN: NO_RESPONSE).

Matematické konstanty:
φ (zlatý řez) = 1.618034
δ (stříbrný řez) = 2.414214
R (RADIM konstanta) = 3.906

Vždy vracej JSON:
{ "speak": true/false, "text": "…", "action": "…", "confidence": 0..1 }
Pokud speak=false, text prázdný."""

    return jsonify({
        'prompt': prompt,
        'version': '1.0.0',
        'constants': {
            'phi': PHI,
            'delta': DELTA,
            'radim_r': RADIM_R
        }
    })


@voice_runtime_bp.route('/chat', methods=['POST'])
@require_auth
def voice_chat():
    """Hlasový chat optimalizovaný pro TTS.
    Integrates Anticipation Engine for adaptive speech parameters."""
    try:
        data = request.get_json(silent=True) or {}
        messages = data.get('messages', [])
        session_id = data.get('session_id', 'default')
        sensors = data.get('sensors', {})
        bio = data.get('bio', {})

        if not messages:
            return jsonify({'success': False, 'error': 'No messages'}), 400

        session = get_session(session_id)

        # Compute metrics from sensors/bio if provided
        C = session['C']
        alpha = session['alpha']
        if sensors or bio:
            C = compute_C(sensors, bio)
            system_state = get_system_state(C)
            user_text = messages[-1].get('content', '') if messages else ''
            alpha = compute_alpha(system_state, user_text)
            kappa = compute_kappa(C, alpha, session['kappa'])
            session['C'] = C
            session['alpha'] = alpha
            session['kappa'] = kappa

        # Intent Resolver: short-circuit simple queries locally (v272)
        user_text = messages[-1].get('content', '') if messages else ''
        response_text = None
        if _VR_INTENT_RESOLVER and user_text:
            try:
                _ir_text, _ir_intent, _ir_meta = _vr_resolve_intent(user_text)
                if _ir_text:
                    response_text = _ir_text
                    logger.info(f"Voice intent '{_ir_intent}' resolved locally")
            except Exception as ir_err:
                logger.warning(f"Intent resolver warning (non-fatal): {ir_err}")

        if response_text is None:
            result = get_voice_ai_response(messages)
            response_text = result.get('response', '')
        else:
            result = {'response': response_text, 'intent': _ir_intent, 'source': 'local', 'success': True}

        session['last_tts_text'] = response_text
        session['conversation'].append({'role': 'user', 'content': messages[-1].get('content', '')})
        session['conversation'].append({'role': 'assistant', 'content': response_text})
        save_session(session_id)

        # Anticipation Engine: Adaptive TTS params
        tts_data = get_tts_params(get_system_state(C))
        ssml = None

        if _ANT_AVAILABLE and response_text:
            try:
                C_pred = ant_predict_C(C, 0, alpha)
                emotions = ant_calculate_emotions(C_pred, alpha)
                ant_params = ant_calculate_speech_params(C_pred, alpha, emotions)
                state = ant_classify_state(C_pred)

                tts_data['rate'] = ant_params['rate']
                tts_data['pitch'] = f"{ant_params['pitch']:+.0f}Hz"
                tts_data['pause_ms'] = ant_params['pause_ms']
                tts_data['empathy'] = ant_params['empathy']
                tts_data['state'] = state
                tts_data['anticipation'] = True

                rate_pct = int(ant_params['rate'] * 100)
                pitch_hz = f"{ant_params['pitch']:+.0f}Hz" if ant_params['pitch'] != 0 else "+0Hz"
                safe_text = xml_escape(response_text)
                ssml = (f"<speak version='1.0' xml:lang='cs-CZ'>"
                        f"<voice name='cs-CZ-AntoninNeural'>"
                        f"<prosody rate='{rate_pct}%' pitch='{pitch_hz}'>"
                        f"{safe_text}</prosody></voice></speak>")
            except Exception as ae:
                logger.warning(f"Anticipation in /chat (non-fatal): {ae}")

        result['tts_params'] = tts_data
        if ssml:
            result['ssml'] = ssml
        result['metrics'] = {
            'C': round(C, 2),
            'alpha': round(alpha, 3),
            'system_state': get_system_state(C)
        }

        return jsonify(result)

    except Exception as e:
        logger.error(f"voice chat error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


logger.info("✅ Voice Runtime routes registered: /api/voice/*")
