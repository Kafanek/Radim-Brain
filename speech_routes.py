# ============================================
# RADIM SPEECH ROUTES v2.1.0
# ============================================
# API endpoints for Azure Speech TTS/STT.
# Config + helpers in speech_helpers.py.
#
# Routes:
#   POST /api/speech/synthesize
#   POST /api/speech/synthesize/stream
#   POST /api/speech/transcribe
#   GET  /api/speech/voices
#   GET  /api/speech/health
#   GET  /api/speech/azure-token
#   GET  /api/speech/azure-config (deprecated)
# ============================================

import re as _re
import uuid
import base64
import time
import requests
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify, Response, g
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit
import logging

logger = logging.getLogger(__name__)

speech_bp = Blueprint('speech', __name__, url_prefix='/api/speech')

# ============================================================================
# IMPORTS FROM HELPERS MODULE (+ re-exports for backward compat)
# ============================================================================

from speech_helpers import (
    # Config
    AZURE_SPEECH_KEY, AZURE_SPEECH_REGION,
    CZECH_VOICES, SENIOR_DEFAULTS, EMOTION_STYLES,
    # Flags
    SPEECH_ANT_AVAILABLE, SPEECH_BRAIN_AVAILABLE,
    # Functions
    get_tts_url, get_tts_headers,
    get_anticipation_tts, apply_state_style,
    get_brain_speech, radim_speak,
    get_cached_token,
)

# Backward compat aliases
_SPEECH_ANT_AVAILABLE = SPEECH_ANT_AVAILABLE
_SPEECH_BRAIN_AVAILABLE = SPEECH_BRAIN_AVAILABLE
_get_anticipation_tts = get_anticipation_tts


# ============================================================================
# TEXT-TO-SPEECH (REST API)
# ============================================================================

@speech_bp.route('/synthesize', methods=['POST'])
@require_auth
@rate_limit(30, 60, 'ip')
def synthesize_speech():
    """Prevod text na rec pomoci Azure REST API"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'AZURE_SPEECH_KEY neni nastaven'}), 500

    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'Chybi telo pozadavku (JSON)'}), 400
        text = data.get('text', '')
        voice_name = data.get('voice', 'radim').lower()
        rate = data.get('rate', SENIOR_DEFAULTS['rate'])
        pitch = data.get('pitch', SENIOR_DEFAULTS['pitch'])
        senior_mode = data.get('senior_mode', True)
        return_base64 = data.get('return_base64', True)

        if not text:
            return jsonify({'success': False, 'error': 'Text je povinny'}), 400

        azure_voice = CZECH_VOICES.get(voice_name, CZECH_VOICES['antonin'])

        # Emotion -> SSML style mapping
        emotion = data.get('emotion', 'friendly')
        style, styledegree = EMOTION_STYLES.get(emotion, ('friendly', '1.2'))

        # Anticipation Engine: if C and alpha provided, compute adaptive params
        C_val = data.get('C')
        alpha_val = data.get('alpha')
        ant_state = None
        if C_val is not None and alpha_val is not None and SPEECH_ANT_AVAILABLE:
            ant_result = get_anticipation_tts(float(C_val), float(alpha_val))
            if ant_result:
                rate, pitch, ant_state, _ = ant_result
                senior_mode = False
                s, d = apply_state_style(ant_state)
                if s:
                    style, styledegree = s, d

        # Brain Engine: override with per-user Psi(t) speech adaptation
        brain_speech = None
        auth_user = getattr(g, 'auth_user', None) or {}
        uid = str(auth_user.get('id', '')).strip()
        if not uid or uid == '0':
            uid = data.get('user_id', '')
        if uid:
            brain_speech = get_brain_speech(uid)
            if brain_speech:
                rate = str(brain_speech['rate'])
                pitch = f"{brain_speech['pitch_pct']:+d}%"
                senior_mode = False
                ant_state = brain_speech['mode']
                s, d = apply_state_style(brain_speech['mode'])
                if s:
                    style, styledegree = s, d

        if senior_mode:
            rate = SENIOR_DEFAULTS['rate']
            pitch = SENIOR_DEFAULTS['pitch']

        # Sanitize inputs to prevent SSML injection
        safe_text = xml_escape(text)
        if not _re.match(r'^[0-9.]+$', str(rate).replace('%', '')):
            rate = SENIOR_DEFAULTS['rate']
        if not _re.match(r'^[+-]?[0-9]+%?$', str(pitch).replace('Hz', '')):
            pitch = SENIOR_DEFAULTS['pitch']

        # SSML pro Azure REST API
        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="{azure_voice}">
                <mstts:express-as style="{style}" styledegree="{styledegree}">
                    <prosody rate="{rate}" pitch="{pitch}" volume="{SENIOR_DEFAULTS['volume']}">
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>'''

        response = requests.post(
            get_tts_url(), headers=get_tts_headers(),
            data=ssml.encode('utf-8'), timeout=30
        )

        if response.status_code == 200:
            audio_data = response.content

            if return_base64:
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                resp_data = {
                    'success': True,
                    'audio': audio_base64,
                    'format': 'mp3',
                    'voice': azure_voice,
                    'text': text
                }
                if ant_state:
                    resp_data['anticipation_state'] = ant_state
                if brain_speech:
                    resp_data['brain_speech'] = brain_speech
                return jsonify(resp_data)
            else:
                return Response(
                    audio_data,
                    mimetype='audio/mpeg',
                    headers={
                        'Content-Disposition': f'attachment; filename=radim_{uuid.uuid4().hex[:8]}.mp3'
                    }
                )
        else:
            logger.error(f"Azure TTS error: {response.status_code} — {response.text[:200] if response.text else 'no body'}")
            return jsonify({
                'success': False,
                'error': f'Azure TTS chyba (kod {response.status_code})'
            }), 500

    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Azure TTS timeout'}), 504
    except Exception as e:
        logger.error(f"speech_routes.py error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


@speech_bp.route('/synthesize/stream', methods=['POST'])
@require_auth
def synthesize_stream():
    """Streamovana synteza pro okamzite prehravani"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Speech service not available'}), 500

    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'Chybi telo pozadavku (JSON)'}), 400
        text = data.get('text', '')
        voice_name = data.get('voice', 'radim').lower()

        if not text:
            return jsonify({'success': False, 'error': 'Text je povinny'}), 400

        azure_voice = CZECH_VOICES.get(voice_name, CZECH_VOICES['antonin'])

        # Emotion -> SSML style mapping
        emotion = data.get('emotion', 'friendly') if data else 'friendly'
        style, styledegree = EMOTION_STYLES.get(emotion, ('friendly', '1.2'))

        # Anticipation Engine adaptive params
        rate = SENIOR_DEFAULTS['rate']
        pitch = SENIOR_DEFAULTS['pitch']
        C_val = data.get('C') if data else None
        alpha_val = data.get('alpha') if data else None
        if C_val is not None and alpha_val is not None and SPEECH_ANT_AVAILABLE:
            ant_result = get_anticipation_tts(float(C_val), float(alpha_val))
            if ant_result:
                rate, pitch, ant_state, _ = ant_result
                s, d = apply_state_style(ant_state)
                if s:
                    style, styledegree = s, d

        safe_text = xml_escape(text)
        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="{azure_voice}">
                <mstts:express-as style="{style}" styledegree="{styledegree}">
                    <prosody rate="{rate}" pitch="{pitch}">
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>'''

        response = requests.post(
            get_tts_url(), headers=get_tts_headers(),
            data=ssml.encode('utf-8'), timeout=30
        )

        if response.status_code == 200:
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers={
                    'Content-Disposition': 'inline',
                    'Content-Length': str(len(response.content))
                }
            )

        return jsonify({'success': False, 'error': 'TTS synthesis failed'}), 500

    except Exception as e:
        logger.error(f"speech_routes.py error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# ============================================================================
# SPEECH-TO-TEXT (REST API)
# ============================================================================

@speech_bp.route('/transcribe', methods=['POST'])
@require_auth
@rate_limit(20, 60, 'ip')
def transcribe_speech():
    """Prevod rec na text pomoci Azure REST API"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Speech service not available'}), 500

    try:
        audio_data = None
        content_type = 'audio/wav'

        if 'audio' in request.files:
            audio_file = request.files['audio']
            audio_data = audio_file.read()
            if audio_file.filename:
                if audio_file.filename.endswith('.webm'):
                    content_type = 'audio/webm'
                elif audio_file.filename.endswith('.mp3'):
                    content_type = 'audio/mp3'
                elif audio_file.filename.endswith('.ogg'):
                    content_type = 'audio/ogg'
        elif request.is_json and 'audio_base64' in request.json:
            audio_data = base64.b64decode(request.json['audio_base64'])
            content_type = request.json.get('content_type', 'audio/wav')
        else:
            return jsonify({'success': False, 'error': 'Neni poskytnuto zadne audio'}), 400

        stt_url = f"https://{AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"

        params = {'language': 'cs-CZ', 'format': 'detailed'}

        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': content_type,
            'Accept': 'application/json'
        }

        response = requests.post(stt_url, params=params, headers=headers, data=audio_data, timeout=30)

        if response.status_code == 200:
            result = response.json()

            if result.get('RecognitionStatus') == 'Success':
                if 'NBest' in result and result['NBest']:
                    best = result['NBest'][0]
                    return jsonify({
                        'success': True,
                        'text': best.get('Display', best.get('Lexical', '')),
                        'confidence': best.get('Confidence', 0.9)
                    })
                else:
                    return jsonify({
                        'success': True,
                        'text': result.get('DisplayText', ''),
                        'confidence': 0.9
                    })
            elif result.get('RecognitionStatus') == 'NoMatch':
                return jsonify({
                    'success': True,
                    'text': '',
                    'message': 'Rec nebyla rozpoznana'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f"Recognition status: {result.get('RecognitionStatus')}"
                }), 400
        else:
            logger.error(f"Azure STT error: {response.status_code} — {response.text[:200]}")
            return jsonify({
                'success': False,
                'error': f'Azure STT chyba (kod {response.status_code})'
            }), 500

    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Azure STT timeout'}), 504
    except Exception as e:
        logger.error(f"speech_routes.py error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# ============================================================================
# VOICE INFO
# ============================================================================

@speech_bp.route('/voices', methods=['GET'])
def get_voices():
    """Seznam dostupnych hlasu"""
    return jsonify({
        'success': True,
        'voices': [
            {
                'id': 'radim',
                'name': 'Radim (Antonin)',
                'azure_name': 'cs-CZ-AntoninNeural',
                'gender': 'male',
                'description': 'Klidny muzsky hlas pro Radima',
                'recommended': True
            },
            {
                'id': 'antonin',
                'name': 'Antonin',
                'azure_name': 'cs-CZ-AntoninNeural',
                'gender': 'male',
                'description': 'Standardni muzsky cesky hlas'
            },
            {
                'id': 'vlasta',
                'name': 'Vlasta',
                'azure_name': 'cs-CZ-VlastaNeural',
                'gender': 'female',
                'description': 'Pratelsky zensky hlas'
            }
        ],
        'senior_settings': SENIOR_DEFAULTS,
        'note': 'Pro seniory doporucujeme pomalejsi tempo (0.85)',
        'api_type': 'REST'
    })


@speech_bp.route('/health', methods=['GET'])
def speech_health():
    """Stav Azure Speech sluzby"""
    if not AZURE_SPEECH_KEY:
        return jsonify({
            'success': False,
            'status': 'not_configured',
            'error': 'AZURE_SPEECH_KEY neni nastaven'
        }), 500

    try:
        test_url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        headers = {'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY}
        response = requests.get(test_url, headers=headers, timeout=10)

        if response.status_code == 200:
            return jsonify({
                'success': True,
                'status': 'healthy',
                'region': AZURE_SPEECH_REGION,
                'tts_ready': True,
                'stt_ready': True,
                'api_type': 'REST',
                'anticipation_engine': SPEECH_ANT_AVAILABLE,
                'voices_available': list(CZECH_VOICES.keys())
            })
        else:
            return jsonify({
                'success': False,
                'status': 'error',
                'error': f'Azure API returned {response.status_code}'
            }), 500

    except Exception as e:
        logger.error(f"speech_health error: {e}")
        return jsonify({
            'success': False,
            'status': 'error',
            'error': 'Speech service nedostupny'
        }), 500


# ============================================================================
# AZURE SPEECH TOKEN FOR FRONTEND SDK
# ============================================================================

@speech_bp.route('/azure-token', methods=['GET'])
@optional_auth
def get_azure_token():
    """Vrati kratkodoby Azure Speech token pro frontend SDK (STT/TTS).
    Uses optional_auth — token proxy is rate-limited, no API key exposed."""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Azure not configured'}), 500

    now = time.time()
    _token_cache = get_cached_token()

    # Return cached token if still valid (refresh 1 min before expiry)
    if _token_cache['token'] and _token_cache['expires'] > now + 60:
        return jsonify({
            'success': True,
            'token': _token_cache['token'],
            'region': AZURE_SPEECH_REGION,
            'expiresIn': int(_token_cache['expires'] - now)
        })

    # Fetch new token from Azure (valid for 10 minutes)
    try:
        token_url = f"https://{AZURE_SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Length': '0'
        }
        response = requests.post(token_url, headers=headers, timeout=10)

        if response.status_code == 200:
            token = response.text
            _token_cache['token'] = token
            _token_cache['expires'] = now + 600  # 10 minutes

            return jsonify({
                'success': True,
                'token': token,
                'region': AZURE_SPEECH_REGION,
                'expiresIn': 600
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Azure token error: {response.status_code}'
            }), 500

    except Exception as e:
        logger.error(f"azure_token error: {e}")
        return jsonify({
            'success': False,
            'error': 'Nepodarilo se ziskat Azure token'
        }), 500


@speech_bp.route('/azure-config', methods=['GET'])
@require_auth
def get_azure_config():
    """DEPRECATED: Use /azure-token instead. Returns region only (no key)."""
    return jsonify({
        'success': True,
        'region': AZURE_SPEECH_REGION,
        'note': 'API key no longer exposed. Use /api/speech/azure-token for token-based auth.',
        'token_endpoint': '/api/speech/azure-token'
    })


# ============================================================================
# STARTUP
# ============================================================================
logger.info("🗣️ Speech Routes v2.1.0 loaded — /api/speech/*")
logger.info(f"   Anticipation Engine: {SPEECH_ANT_AVAILABLE}, Brain Engine: {SPEECH_BRAIN_AVAILABLE}")
logger.info("   Helpers module: speech_helpers.py")
