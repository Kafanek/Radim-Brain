# ============================================
# RADIM CHAT - AZURE SPEECH MODULE (REST API)
# speech_routes.py
# ============================================
# Používá Azure Speech REST API místo SDK (kompatibilní s Heroku)

import os
import uuid
import base64
import requests
from flask import Blueprint, request, jsonify, Response

speech_bp = Blueprint('speech', __name__, url_prefix='/api/speech')

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

# ============================================
# TEXT-TO-SPEECH (REST API)
# ============================================
@speech_bp.route('/synthesize', methods=['POST'])
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
        
        if senior_mode:
            rate = SENIOR_DEFAULTS['rate']
            pitch = SENIOR_DEFAULTS['pitch']
        
        # SSML pro Azure REST API
        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" 
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="{azure_voice}">
                <mstts:express-as style="friendly" styledegree="1.2">
                    <prosody rate="{rate}" pitch="{pitch}" volume="{SENIOR_DEFAULTS['volume']}">
                        {text}
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
                return jsonify({
                    'success': True,
                    'audio': audio_base64,
                    'format': 'mp3',
                    'voice': azure_voice,
                    'text': text
                })
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
        
        ssml = f'''<speak version="1.0" xml:lang="cs-CZ">
            <voice name="{azure_voice}">
                <prosody rate="{SENIOR_DEFAULTS['rate']}" pitch="{SENIOR_DEFAULTS['pitch']}">
                    {text}
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
# RADIM HELPER FUNCTION
# ============================================
def radim_speak(text, emotion='friendly'):
    """
    Helper funkce pro Radima - převede text na audio data
    Vrací bytes audio data nebo None při chybě
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
        
        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" 
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="cs-CZ-AntoninNeural">
                <mstts:express-as style="{style}" styledegree="{degree}">
                    <prosody rate="{SENIOR_DEFAULTS['rate']}" pitch="{SENIOR_DEFAULTS['pitch']}">
                        {text}
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
