# X21.28: 4 dead routes retired from speech_routes — /synthesize,
# /synthesize/stream, /voices, /azure-config. All zero callers.
# Surviving: /transcribe (used by chat-module + smart-home),
# /azure-token (used by frontend SDK), /health (admin probe).

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
    get_brain_speech,
    # X21.29: radim_speak removed from imports — re-exported here but never
    # called by any route after X21.28 removed /synthesize and /voices.
    get_cached_token,
)

# Backward compat aliases
_SPEECH_ANT_AVAILABLE = SPEECH_ANT_AVAILABLE
_SPEECH_BRAIN_AVAILABLE = SPEECH_BRAIN_AVAILABLE
_get_anticipation_tts = get_anticipation_tts


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
            # v8.19.67: Determine content_type for Azure REST.
            # MediaRecorder almost always uses opus inside webm/ogg containers.
            # Browser-supplied mimetype usually omits the codec param ("audio/webm"
            # instead of "audio/webm;codecs=opus") — Azure then can't decode.
            # Strategy: take browser hint, but ALWAYS ensure codec is present
            # for webm/ogg containers.
            up_ct = (audio_file.mimetype or '').strip().lower()
            fn = (audio_file.filename or '').lower()
            if up_ct.startswith('audio/webm') or fn.endswith('.webm'):
                content_type = 'audio/webm; codecs=opus'  # always force codec
            elif up_ct.startswith('audio/ogg') or fn.endswith('.ogg'):
                content_type = 'audio/ogg; codecs=opus'
            elif up_ct.startswith('audio/mp4') or fn.endswith('.mp4'):
                content_type = 'audio/mp4'
            elif up_ct.startswith('audio/mpeg') or fn.endswith('.mp3'):
                content_type = 'audio/mpeg'
            elif up_ct.startswith('audio/wav') or up_ct.startswith('audio/x-wav') or fn.endswith('.wav'):
                content_type = 'audio/wav'
            elif up_ct.startswith('audio/'):
                content_type = up_ct  # trust browser as last resort
            logger.warning(f"🎙️ STT upload: {len(audio_data)} bytes, content_type={content_type}, browser_ct={up_ct}, fn={fn}")
        elif request.is_json and 'audio_base64' in request.json:
            audio_data = base64.b64decode(request.json['audio_base64'])
            content_type = request.json.get('content_type', 'audio/wav')
        else:
            return jsonify({'success': False, 'error': 'Neni poskytnuto zadne audio'}), 400

        stt_url = f"https://{AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"

        # X21.35: respect app language. X21.15 made the frontend webkit STT
        # locale-aware (UnifiedVoiceManager), but Azure-server STT was still
        # hard-pinned to cs-CZ — so Slovak/Polish/Hungarian/English users got
        # Czech transcription on voice-notes and smart-home commands. Now
        # accepts `lang` from form/JSON body or Accept-Language header,
        # mapped to BCP-47, allowlist-validated.
        _BCP47 = {'cs': 'cs-CZ', 'sk': 'sk-SK', 'pl': 'pl-PL', 'hu': 'hu-HU', 'en': 'en-US'}
        _raw_lang = None
        if request.is_json and isinstance(request.json, dict):
            _raw_lang = request.json.get('lang')
        if not _raw_lang and 'audio' in request.files:
            _raw_lang = request.form.get('lang')
        if not _raw_lang:
            _raw_lang = (request.headers.get('Accept-Language') or '').split(',')[0].split('-')[0].strip().lower()
        stt_lang = _BCP47.get((_raw_lang or '').lower(), 'cs-CZ')
        params = {'language': stt_lang, 'format': 'detailed'}

        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': content_type,
            'Accept': 'application/json'
        }

        response = requests.post(stt_url, params=params, headers=headers, data=audio_data, timeout=30)

        if response.status_code == 200:
            result = response.json()
            # v8.19.65: log full Azure response on empty/failed → easier debug
            rec_status = result.get('RecognitionStatus')
            logger.warning(f"🎙️ STT Azure response: status={rec_status} ct={content_type} bytes={len(audio_data)} resp_size={len(response.text)}")

            if rec_status == 'Success':
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
            elif rec_status == 'NoMatch':
                return jsonify({
                    'success': True,
                    'text': '',
                    'message': 'Řeč nebyla rozpoznána (mlčení nebo nesrozumitelné).'
                })
            elif rec_status == 'InitialSilenceTimeout':
                return jsonify({
                    'success': True,
                    'text': '',
                    'message': 'Žádný zvuk na začátku — zkontrolujte mikrofon.'
                })
            elif rec_status == 'BabbleTimeout':
                return jsonify({
                    'success': True,
                    'text': '',
                    'message': 'Hluk nebo nesrozumitelná řeč.'
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

    # Bug-fix (TTS audit #7): refresh margin zvýšen z 60s na 300s.
    # Důvod: Azure SDK STT/TTS call typicky trvá 5-20 sekund (streaming
    # transcription). Pokud klient dostal token s 60s do expirace a SDK
    # call běží přes hranici → Azure 401 + STT/TTS prasklo bez fallbacku.
    # 300s margin = 5 minut zaručí, že nejdelší rozumné session doběhne.
    # Trade-off: token cache hit rate klesne (refresh každých 5 min místo
    # 9 min), ale Azure issueToken endpoint je rychlý (~50-100ms) + zdarma.
    if _token_cache['token'] and _token_cache['expires'] > now + 300:
        return jsonify({
            'success': True,
            'token': _token_cache['token'],
            'region': AZURE_SPEECH_REGION,
            'expiresIn': int(_token_cache['expires'] - now)
        })

    # v450: Circuit breaker for Azure STT
    try:
        from self_healing import get_breaker
        stt_breaker = get_breaker('azure_stt')
        if not stt_breaker.can_proceed():
            return jsonify({'success': False, 'error': 'Azure STT temporarily unavailable', 'fallback': 'browser'}), 503
    except ImportError:
        stt_breaker = None

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
            if stt_breaker: stt_breaker.record_success()

            return jsonify({
                'success': True,
                'token': token,
                'region': AZURE_SPEECH_REGION,
                'expiresIn': 600
            })
        else:
            if stt_breaker: stt_breaker.record_failure()
            return jsonify({
                'success': False,
                'error': f'Azure token error: {response.status_code}',
                'fallback': 'browser'
            }), 500

    except Exception as e:
        logger.error(f"azure_token error: {e}")
        if stt_breaker: stt_breaker.record_failure()
        return jsonify({
            'success': False,
            'error': 'Nepodarilo se ziskat Azure token'
        }), 500


# ============================================================================
# STARTUP
# ============================================================================
logger.info("🗣️ Speech Routes v2.1.0 loaded — /api/speech/*")
logger.info(f"   Anticipation Engine: {SPEECH_ANT_AVAILABLE}, Brain Engine: {SPEECH_BRAIN_AVAILABLE}")
logger.info("   Helpers module: speech_helpers.py")
