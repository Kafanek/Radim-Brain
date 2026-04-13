"""
TTS Proxy Routes — Azure TTS + ElevenLabs TTS
Extracted from app.py for cleaner architecture.
"""

import os
import re
import logging
import requests as http_requests
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify, Response
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

tts_proxy_bp = Blueprint('tts_proxy', __name__)

# ── Config from environment ──────────────────────────────────────────
# v409: Unified config — use same env vars as speech_helpers.py
AZURE_TTS_KEY = os.environ.get('AZURE_TTS_KEY') or os.environ.get('AZURE_SPEECH_KEY')
AZURE_TTS_REGION = os.environ.get('AZURE_TTS_REGION') or os.environ.get('AZURE_SPEECH_REGION', 'germanywestcentral')
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')

# ── Anticipation + Brain engine refs (set by init_tts_proxy_routes) ──
_ant_available = False
_ant_predict_C = None
_ant_emotions = None
_ant_speech = None
_ant_classify = None
_brain_available = False
_brain_speech_fn = None


def init_tts_proxy_routes(ant_available=False, predict_C=None, emotions=None,
                          speech=None, classify=None, brain_available=False,
                          brain_speech=None):
    """Inject anticipation-engine and brain-engine function references."""
    global _ant_available, _ant_predict_C, _ant_emotions, _ant_speech, _ant_classify
    global _brain_available, _brain_speech_fn
    _ant_available = ant_available
    _ant_predict_C = predict_C
    _ant_emotions = emotions
    _ant_speech = speech
    _ant_classify = classify
    _brain_available = brain_available
    _brain_speech_fn = brain_speech


# ── Valid SSML express-as styles ─────────────────────────────────────
_VALID_STYLES = {
    'friendly', 'cheerful', 'sad', 'angry', 'excited', 'gentle', 'serious',
    'empathetic', 'calm', 'newscast', 'customerservice', 'chat', 'assistant',
    'newscast-casual', 'newscast-formal', 'advertisement_upbeat',
    'documentary-narration', 'narration-professional', 'narration-relaxed',
    'poetry-reading', 'shouting', 'whispering', 'terrified', 'unfriendly',
    'depressed', 'disgruntled', 'embarrassed', 'fearful', 'hopeful',
    'lyrical', 'envious', 'sports_commentary', 'sports_commentary_excited',
}


# =====================================================================
#  Azure TTS Proxy
# =====================================================================

@tts_proxy_bp.route('/api/azure/tts', methods=['OPTIONS'])
def azure_tts_preflight():
    """CORS preflight for Azure TTS"""
    response = jsonify({'status': 'ok'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Max-Age', '3600')
    return response, 200


@tts_proxy_bp.route('/api/azure/tts', methods=['POST'])
@rate_limit(max_requests=60, window_seconds=60, key_func='ip')
def azure_tts_proxy():
    """Azure TTS Proxy - Antonin voice"""
    if not AZURE_TTS_KEY:
        return jsonify({'error': 'Azure TTS not configured (AZURE_TTS_KEY missing)'}), 503
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Chybi telo pozadavku (JSON)'}), 400
        text = data.get('text', '')
        voice = data.get('voice', 'cs-CZ-AntoninNeural')
        uid = data.get('user_id', '')
        ant_state = None

        # 1. Get brain mode for voice adaptation
        brain_speech = None
        if uid and _brain_available:
            try:
                brain_speech = _brain_speech_fn(str(uid))
                if brain_speech:
                    ant_state = brain_speech.get('mode')
            except Exception:
                pass

        if not text:
            return jsonify({'error': 'Text is required'}), 400

        # ⚡ TTS Cache — check before Azure API call
        # v10.15: Include context in cache key (poetry ≠ harmony for same text)
        rate = float(data.get('rate', 0.9))
        _cache_ctx = data.get('context', '') or data.get('style', '') or ''
        _cache_rate = str(rate) + ':' + _cache_ctx
        try:
            from scaling_optimizations import tts_cache
            cached_audio = tts_cache.get(text, voice, _cache_rate)
            if cached_audio:
                logger.debug(f"TTS cache HIT: {text[:30]}...")
                return Response(
                    cached_audio,
                    mimetype='audio/mpeg',
                    headers={'X-Voice-Name': voice, 'X-Cache': 'HIT', 'Cache-Control': 'no-cache'}
                )
        except ImportError:
            pass

        # Sanitize voice name
        if not re.match(r'^[a-zA-Z]{2}-[A-Z]{2}-[a-zA-Z]+$', voice):
            voice = 'cs-CZ-AntoninNeural'

        # ═══ SINGLE SOURCE OF TRUTH: voice_filter.build_radim_ssml() ═══
        # Mode priority: context → frontend style → brain state → default
        # v10.11: Context modes for per-module styling (poetry, narration, news, education)
        _context = data.get('context', '')
        _context_to_mode = {
            'poetry': 'POETRY', 'poem': 'POETRY', 'recitation': 'POETRY',
            'narration': 'NARRATION', 'story': 'NARRATION', 'library': 'NARRATION',
            'news': 'NEWS', 'newscast': 'NEWS',
            'education': 'EDUCATION', 'learning': 'EDUCATION', 'quiz': 'EDUCATION',
        }
        _frontend_style = data.get('style', '')
        _style_to_mode = {
            'calm': 'CRISIS', 'empathetic': 'ALERT', 'cheerful': 'HARMONY', 'friendly': 'HARMONY',
            'poetry-reading': 'POETRY', 'narration-relaxed': 'NARRATION', 'newscast': 'NEWS',
        }
        _context_mode = _context_to_mode.get(_context)
        _frontend_mode = _style_to_mode.get(_frontend_style)
        _mode = _context_mode or _frontend_mode or ant_state or (brain_speech.get('mode') if brain_speech else None) or 'HARMONY'
        try:
            from voice_filter import build_radim_ssml
            ssml = build_radim_ssml(text, mode=_mode, voice=voice, user_id=uid or None)
        except Exception as e:
            logger.warning(f"voice_filter failed, using simple SSML: {e}")
            safe_text = xml_escape(text)
            ssml = f"""<speak version='1.0' xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='cs-CZ'>
                <voice name='{voice}'>
                    <mstts:express-as style='friendly' styledegree='1.2'>
                        <prosody rate='-5%' pitch='-2%'>
                            {safe_text}
                        </prosody>
                    </mstts:express-as>
                </voice>
            </speak>"""

        url = f"https://{AZURE_TTS_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_TTS_KEY,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-24khz-160kbitrate-mono-mp3'
        }

        # v449: TTS with circuit breaker + retry
        try:
            from self_healing import get_breaker, log_healing_event
            tts_breaker = get_breaker('azure_tts')
            if not tts_breaker.can_proceed():
                log_healing_event('circuit_open', 'azure_tts')
                return jsonify({'error': 'TTS service temporarily unavailable', 'fallback': 'browser'}), 503
        except ImportError:
            tts_breaker = None

        response = None
        for _attempt in range(2):  # max 1 retry
            try:
                response = http_requests.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=15)
                if response.status_code == 200:
                    if tts_breaker: tts_breaker.record_success()
                    break
                else:
                    if tts_breaker: tts_breaker.record_failure()
            except http_requests.exceptions.Timeout:
                if tts_breaker: tts_breaker.record_failure()
                if _attempt == 0:
                    continue  # retry once
                try: log_healing_event('timeout', 'azure_tts')
                except: pass
                return jsonify({'error': 'Azure TTS timeout', 'fallback': 'browser'}), 504
            except http_requests.exceptions.RequestException as e:
                if tts_breaker: tts_breaker.record_failure()
                logger.error(f"TTS proxy error: {e}")
                try: log_healing_event('exception', 'azure_tts', {'error': str(e)[:80]})
                except: pass
                return jsonify({'error': 'TTS error', 'fallback': 'browser'}), 503

        if response is None or response.status_code != 200:
            return jsonify({'error': f'Azure TTS error: {response.status_code if response else "no response"}', 'fallback': 'browser'}), 503

        if response.status_code == 200:
            # ⚡ Cache the audio for future requests
            try:
                from scaling_optimizations import tts_cache
                tts_cache.put(text, response.content, voice, _cache_rate)
            except Exception:
                pass

            resp_headers = {
                'X-Voice-Name': voice,
                'X-Voice-Mode': _mode,
                'Cache-Control': 'no-cache',
                'X-Cache': 'MISS'
            }
            if ant_state:
                resp_headers['X-Anticipation-State'] = ant_state
            if brain_speech:
                resp_headers['X-Brain-Mode'] = brain_speech['mode']
                resp_headers['X-Brain-Coherence'] = str(brain_speech['coherence'])
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers=resp_headers
            )
        else:
            return jsonify({'error': f'Azure TTS error: {response.status_code}'}), response.status_code

    except Exception as e:
        logger.error(f"TTS proxy error: {e}")
        return jsonify({'error': 'Interni chyba serveru'}), 500


# =====================================================================
#  ElevenLabs TTS Proxy
# =====================================================================

@tts_proxy_bp.route('/api/elevenlabs/tts', methods=['OPTIONS'])
def elevenlabs_tts_preflight():
    """CORS preflight for ElevenLabs TTS"""
    response = jsonify({'status': 'ok'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Max-Age', '3600')
    return response, 200


@tts_proxy_bp.route('/api/elevenlabs/tts', methods=['POST'])
@rate_limit(max_requests=40, window_seconds=60, key_func='ip')
def elevenlabs_tts_proxy():
    """ElevenLabs TTS Proxy"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Chybi telo pozadavku (JSON)'}), 400
        text = data.get('text', '')
        voice_id = data.get('voice_id', 'JBFqnCBsd6RMkjVDRZzb')

        if not text:
            return jsonify({'error': 'Text is required'}), 400
        if not ELEVENLABS_API_KEY:
            return jsonify({'error': 'ElevenLabs API key not configured'}), 500

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            'xi-api-key': ELEVENLABS_API_KEY,
            'Content-Type': 'application/json'
        }
        payload = {
            'text': text,
            'model_id': 'eleven_multilingual_v2',
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75
            }
        }

        try:
            response = http_requests.post(url, headers=headers, json=payload, timeout=30)
        except http_requests.exceptions.Timeout:
            return jsonify({'error': 'ElevenLabs API timeout'}), 504
        except http_requests.exceptions.RequestException as e:
            logger.error(f"ElevenLabs error: {e}")
            return jsonify({'error': 'Interni chyba serveru'}), 503

        if response.status_code == 200:
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers={'X-Voice-ID': voice_id, 'Cache-Control': 'no-cache'}
            )
        else:
            logger.error(f"ElevenLabs error {response.status_code}: {response.text[:200]}")
            return jsonify({'error': 'Chyba syntezy hlasu'}), response.status_code

    except Exception as e:
        logger.error(f"ElevenLabs error: {e}")
        return jsonify({'error': 'Interni chyba serveru'}), 500


# =====================================================================
#  TTS Health Check
# =====================================================================

@tts_proxy_bp.route('/api/tts/health', methods=['GET'])
def tts_health():
    """Health check for TTS proxy services"""
    return jsonify({
        'status': 'healthy',
        'service': 'TTS Proxy (Azure + ElevenLabs - Flask)',
        'endpoints': {
            'azure': '/api/azure/tts',
            'elevenlabs': '/api/elevenlabs/tts'
        }
    })
