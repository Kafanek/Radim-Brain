# ============================================
# RADIM CHAT - AZURE SPEECH MODULE (REST API)
# speech_routes.py
# ============================================
# Používá Azure Speech REST API místo SDK (kompatibilní s Heroku)

import os
import re as _re
import uuid
import base64
import requests
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify, Response, g
from auth_middleware import require_auth

speech_bp = Blueprint('speech', __name__, url_prefix='/api/speech')

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _ant_predict_C, calculate_emotions as _ant_emotions,
        calculate_speech_params as _ant_speech_params, classify_state as _ant_classify
    )
    _SPEECH_ANT_AVAILABLE = True
except ImportError:
    _SPEECH_ANT_AVAILABLE = False

# Azure Speech konfigurace
AZURE_SPEECH_KEY = os.environ.get('AZURE_SPEECH_KEY')
AZURE_SPEECH_REGION = os.environ.get('AZURE_SPEECH_REGION', 'westeurope')

# České neurální hlasy
CZECH_VOICES = {
    'antonin': 'cs-CZ-AntoninNeural',
    'vlasta': 'cs-CZ-VlastaNeural',
    'radim': 'cs-CZ-AntoninNeural',
}

SENIOR_DEFAULTS = {
    'rate': '0.85',
    'pitch': '-5%',
    'volume': 'loud',
}


def _get_anticipation_tts(C, alpha):
    """Get adaptive rate/pitch from Anticipation Engine. Returns (rate_str, pitch_str) or None."""
    if not _SPEECH_ANT_AVAILABLE:
        return None
    try:
        C_pred = _ant_predict_C(C, 0, alpha)
        emotions = _ant_emotions(C_pred, alpha)
        params = _ant_speech_params(C_pred, alpha, emotions)
        rate_str = str(params['rate'])
        pitch_str = f"{params['pitch']:+.0f}%" if params['pitch'] != 0 else "-0%"
        return rate_str, pitch_str, _ant_classify(C_pred), params
    except Exception:
        return None

# ============================================
# TEXT-TO-SPEECH (REST API)
# ============================================
@speech_bp.route('/synthesize', methods=['POST'])
@require_auth
def synthesize_speech():
    """Převeď text na řeč pomocí Azure REST API"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'AZURE_SPEECH_KEY není nastaven'}), 500
    
    try:
        data = request.json
        text = data.get('text', '')
        voice_name = data.get('voice', 'radim').lower()
        rate = data.get('rate', SENIOR_DEFAULTS['rate'])
        pitch = data.get('pitch', SENIOR_DEFAULTS['pitch'])
        senior_mode = data.get('senior_mode', True)
        return_base64 = data.get('return_base64', True)
        
        if not text:
            return jsonify({'success': False, 'error': 'Text je povinný'}), 400
        
        azure_voice = CZECH_VOICES.get(voice_name, CZECH_VOICES['antonin'])

        # Anticipation Engine: if C and alpha provided, compute adaptive params
        C_val = data.get('C')
        alpha_val = data.get('alpha')
        ant_state = None
        if C_val is not None and alpha_val is not None and _SPEECH_ANT_AVAILABLE:
            ant_result = _get_anticipation_tts(float(C_val), float(alpha_val))
            if ant_result:
                rate, pitch, ant_state, _ = ant_result
                senior_mode = False  # Don't override with defaults

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
                <mstts:express-as style="friendly" styledegree="1.2">
                    <prosody rate="{rate}" pitch="{pitch}" volume="{SENIOR_DEFAULTS['volume']}">
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>'''
        
        # Azure TTS REST API endpoint
        tts_url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
            'User-Agent': 'RadimBrain/3.0'
        }
        
        response = requests.post(tts_url, headers=headers, data=ssml.encode('utf-8'), timeout=30)
        
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
            error_msg = response.text if response.text else f"HTTP {response.status_code}"
            return jsonify({
                'success': False, 
                'error': f'Azure TTS error: {error_msg}',
                'status_code': response.status_code
            }), 500
        
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Azure TTS timeout'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@speech_bp.route('/synthesize/stream', methods=['POST'])
@require_auth
def synthesize_stream():
    """Streamovaná syntéza pro okamžité přehrávání"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Speech service not available'}), 500
    
    try:
        data = request.json
        text = data.get('text', '')
        voice_name = data.get('voice', 'radim').lower()
        
        if not text:
            return jsonify({'success': False, 'error': 'Text je povinný'}), 400
        
        azure_voice = CZECH_VOICES.get(voice_name, CZECH_VOICES['antonin'])
        
        # Anticipation Engine adaptive params
        rate = SENIOR_DEFAULTS['rate']
        pitch = SENIOR_DEFAULTS['pitch']
        C_val = data.get('C') if data else None
        alpha_val = data.get('alpha') if data else None
        if C_val is not None and alpha_val is not None and _SPEECH_ANT_AVAILABLE:
            ant_result = _get_anticipation_tts(float(C_val), float(alpha_val))
            if ant_result:
                rate, pitch, _, _ = ant_result

        safe_text = xml_escape(text)
        ssml = f'''<speak version="1.0" xml:lang="cs-CZ">
            <voice name="{azure_voice}">
                <prosody rate="{rate}" pitch="{pitch}">
                    {safe_text}
                </prosody>
            </voice>
        </speak>'''

        tts_url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
            'User-Agent': 'RadimBrain/3.0'
        }
        
        response = requests.post(tts_url, headers=headers, data=ssml.encode('utf-8'), timeout=30)
        
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
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# SPEECH-TO-TEXT (REST API)
# ============================================
@speech_bp.route('/transcribe', methods=['POST'])
@require_auth
def transcribe_speech():
    """Převeď řeč na text pomocí Azure REST API"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Speech service not available'}), 500
    
    try:
        audio_data = None
        content_type = 'audio/wav'
        
        if 'audio' in request.files:
            audio_file = request.files['audio']
            audio_data = audio_file.read()
            # Detekce typu
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
            return jsonify({'success': False, 'error': 'Není poskytnuto žádné audio'}), 400
        
        # Azure STT REST API endpoint
        stt_url = f"https://{AZURE_SPEECH_REGION}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        
        params = {
            'language': 'cs-CZ',
            'format': 'detailed'
        }
        
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': content_type,
            'Accept': 'application/json'
        }
        
        response = requests.post(stt_url, params=params, headers=headers, data=audio_data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('RecognitionStatus') == 'Success':
                # Get best result
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
                    'message': 'Řeč nebyla rozpoznána'
                })
            
            else:
                return jsonify({
                    'success': False,
                    'error': f"Recognition status: {result.get('RecognitionStatus')}"
                }), 400
        
        else:
            return jsonify({
                'success': False,
                'error': f'Azure STT error: {response.status_code}',
                'details': response.text
            }), 500
        
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'error': 'Azure STT timeout'}), 504
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# VOICE INFO
# ============================================
@speech_bp.route('/voices', methods=['GET'])
def get_voices():
    """Seznam dostupných hlasů"""
    return jsonify({
        'success': True,
        'voices': [
            {
                'id': 'radim',
                'name': 'Radim (Antonín)',
                'azure_name': 'cs-CZ-AntoninNeural',
                'gender': 'male',
                'description': 'Klidný mužský hlas pro Radima',
                'recommended': True
            },
            {
                'id': 'antonin',
                'name': 'Antonín',
                'azure_name': 'cs-CZ-AntoninNeural',
                'gender': 'male',
                'description': 'Standardní mužský český hlas'
            },
            {
                'id': 'vlasta',
                'name': 'Vlasta',
                'azure_name': 'cs-CZ-VlastaNeural',
                'gender': 'female',
                'description': 'Přátelský ženský hlas'
            }
        ],
        'senior_settings': SENIOR_DEFAULTS,
        'note': 'Pro seniory doporučujeme pomalejší tempo (0.85)',
        'api_type': 'REST'  # Indicates we're using REST API, not SDK
    })

@speech_bp.route('/health', methods=['GET'])
def speech_health():
    """Stav Azure Speech služby"""
    if not AZURE_SPEECH_KEY:
        return jsonify({
            'success': False,
            'status': 'not_configured',
            'error': 'AZURE_SPEECH_KEY není nastaven'
        }), 500
    
    # Test connection to Azure
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
                'anticipation_engine': _SPEECH_ANT_AVAILABLE,
                'voices_available': list(CZECH_VOICES.keys())
            })
        else:
            return jsonify({
                'success': False,
                'status': 'error',
                'error': f'Azure API returned {response.status_code}'
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'status': 'error',
            'error': str(e)
        }), 500

# ============================================
# AZURE SPEECH TOKEN FOR FRONTEND SDK
# ============================================
# Token-based auth: backend holds the key, frontend gets a 10-min token.
# This prevents API key exposure in browser devtools/network tab.

_token_cache = {'token': None, 'expires': 0}

@speech_bp.route('/azure-token', methods=['GET'])
@require_auth
def get_azure_token():
    """Vrátí krátkodobý Azure Speech token pro frontend SDK (STT/TTS)"""
    if not AZURE_SPEECH_KEY:
        return jsonify({'success': False, 'error': 'Azure not configured'}), 500

    import time
    now = time.time()

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
        return jsonify({
            'success': False,
            'error': f'Token fetch error: {str(e)}'
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

# ============================================
# RADIM HELPER FUNCTION
# ============================================
def radim_speak(text, emotion='friendly', C=None, alpha=None):
    """
    Helper funkce pro Radima - převede text na audio data.
    Accepts optional C/α from Anticipation Engine for adaptive speech.
    Vrací bytes audio data nebo None při chybě.
    """
    if not AZURE_SPEECH_KEY or not text:
        return None

    try:
        emotion_styles = {
            'friendly': ('friendly', '1.2'),
            'calm': ('calm', '1.0'),
            'cheerful': ('cheerful', '1.3'),
            'empathetic': ('empathetic', '1.1'),
            'serious': ('serious', '0.9')
        }

        style, degree = emotion_styles.get(emotion, ('friendly', '1.2'))

        # Adaptive params from Anticipation Engine
        rate = SENIOR_DEFAULTS['rate']
        pitch = SENIOR_DEFAULTS['pitch']
        if C is not None and alpha is not None and _SPEECH_ANT_AVAILABLE:
            ant_result = _get_anticipation_tts(float(C), float(alpha))
            if ant_result:
                rate, pitch, ant_state, ant_params = ant_result
                # Also adapt style based on anticipation state
                if ant_state == 'CRISIS':
                    style, degree = 'calm', '1.0'
                elif ant_state == 'ALERT':
                    style, degree = 'empathetic', '1.1'

        safe_text = xml_escape(text)

        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="cs-CZ-AntoninNeural">
                <mstts:express-as style="{style}" styledegree="{degree}">
                    <prosody rate="{rate}" pitch="{pitch}">
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>'''
        
        tts_url = f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
            'User-Agent': 'RadimBrain/3.0'
        }
        
        response = requests.post(tts_url, headers=headers, data=ssml.encode('utf-8'), timeout=30)
        
        if response.status_code == 200:
            return response.content
        
        return None
        
    except Exception as e:
        print(f"Radim speak error: {e}")
        return None
