# ============================================
# RADIM SPEECH HELPERS v1.0.0
# ============================================
# Configuration, constants, and helper functions
# for Azure Speech TTS/STT.
# Extracted from speech_routes.py for modularity.
# ============================================

import os
import logging
import requests
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# ============================================================================
# AZURE CONFIGURATION
# ============================================================================

AZURE_SPEECH_KEY = os.environ.get('AZURE_SPEECH_KEY')
AZURE_SPEECH_REGION = os.environ.get('AZURE_SPEECH_REGION', 'germanywestcentral')  # v407: consistent with twilio_voice_helpers

# ============================================================================
# VOICE CONFIGURATION
# ============================================================================

CZECH_VOICES = {
    'antonin': 'cs-CZ-AntoninNeural',
    'vlasta': 'cs-CZ-VlastaNeural',
    'radim': 'cs-CZ-AntoninNeural',
}

SENIOR_DEFAULTS = {
    'rate': '0.82',     # v888: 0.85 → 0.82 — user feedback "extrémně rychle"
    'pitch': '-5%',
    'volume': 'loud',
}

EMOTION_STYLES = {
    'friendly': ('friendly', '1.2'),
    # X21.26: 'calm' is NOT supported by cs-CZ-AntoninNeural (Azure silently
    # drops it). Map it to 'empathetic' so the override actually takes effect.
    'calm': ('empathetic', '1.5'),
    'cheerful': ('cheerful', '1.3'),
    'empathetic': ('empathetic', '1.1'),
    'serious': ('serious', '0.9'),
}

# ============================================================================
# OPTIONAL IMPORTS
# ============================================================================

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _ant_predict_C, calculate_emotions as _ant_emotions,
        calculate_speech_params as _ant_speech_params, classify_state as _ant_classify
    )
    SPEECH_ANT_AVAILABLE = True
except ImportError:
    SPEECH_ANT_AVAILABLE = False

# Brain Engine — per-user Psi(t) speech adaptation
try:
    from radim_brain_routes import get_brain_speech_for_user as _speech_brain_lookup
    SPEECH_BRAIN_AVAILABLE = True
except ImportError:
    SPEECH_BRAIN_AVAILABLE = False

# ============================================================================
# TTS URL BUILDER
# ============================================================================

def get_tts_url():
    """Azure TTS REST API endpoint URL"""
    return f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"


def get_tts_headers():
    """Standard headers for Azure TTS requests"""
    return {
        'Ocp-Apim-Subscription-Key': AZURE_SPEECH_KEY,
        'Content-Type': 'application/ssml+xml',
        'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3',
        'User-Agent': 'RadimBrain/3.0'
    }


# ============================================================================
# ANTICIPATION ENGINE HELPER
# ============================================================================

def get_anticipation_tts(C, alpha):
    """Get adaptive rate/pitch from Anticipation Engine. Returns (rate_str, pitch_str, state, params) or None."""
    if not SPEECH_ANT_AVAILABLE:
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


def apply_state_style(state):
    """Return (style, styledegree) overrides based on anticipation/brain state.

    X21.26: CRISIS used to return 'calm' / '1.0' — but Azure cs-CZ-AntoninNeural
    silently drops that style, so CRISIS audio came out as the neutral default
    instead of the intended slow-and-empathetic rendering. Now mirrors
    voice_filter.VOICE_PROFILES.CRISIS: 'empathetic' / '1.5'.
    """
    if state == 'CRISIS':
        return 'empathetic', '1.5'
    elif state == 'ALERT':
        return 'empathetic', '1.1'
    return None, None


# ============================================================================
# BRAIN ENGINE SPEECH LOOKUP
# ============================================================================

def get_brain_speech(user_id):
    """Get per-user brain speech params. Returns dict or None."""
    if not user_id or not SPEECH_BRAIN_AVAILABLE:
        return None
    try:
        return _speech_brain_lookup(str(user_id))
    except Exception:
        return None


# ============================================================================
# RADIM SPEAK (helper function)
# ============================================================================

def radim_speak(text, emotion='friendly', C=None, alpha=None, user_id=None):
    """
    Helper funkce pro Radima - prevede text na audio data.
    Accepts optional C/alpha from Anticipation Engine for adaptive speech.
    If user_id provided, loads Brain Engine Psi(t) speech params from DB.
    Vraci bytes audio data nebo None pri chybe.
    """
    if not AZURE_SPEECH_KEY or not text:
        return None

    try:
        style, degree = EMOTION_STYLES.get(emotion, ('friendly', '1.2'))

        # Adaptive params from Anticipation Engine
        rate = SENIOR_DEFAULTS['rate']
        pitch = SENIOR_DEFAULTS['pitch']
        if C is not None and alpha is not None:
            ant_result = get_anticipation_tts(float(C), float(alpha))
            if ant_result:
                rate, pitch, ant_state, _ = ant_result
                s, d = apply_state_style(ant_state)
                if s:
                    style, degree = s, d

        # Brain Engine: override with per-user Psi(t) if available
        brain_speech = get_brain_speech(user_id)
        if brain_speech:
            rate = str(brain_speech['rate'])
            pitch = f"{brain_speech['pitch_pct']:+d}%"
            s, d = apply_state_style(brain_speech['mode'])
            if s:
                style, degree = s, d

        # v389: Use rich SSML from voice_filter (emotion + pauses + emphasis)
        # v403: Pass user_id for per-user adaptive voice (fatigue, recovery, pace)
        _mode = brain_speech.get("mode", "HARMONY") if brain_speech else "HARMONY"
        try:
            from voice_filter import build_radim_ssml
            # v10.29: Pass RTCF Beat Engine voice modifiers if available
            _rtcf_voice = brain_speech.get('rtcf_voice') if brain_speech else None
            # Sprint AA: pass full brain_speech so SSML uses Ψ(t)-driven
            # rate/pitch/pause from compute_unified_speech (4-layer output).
            ssml = build_radim_ssml(text, mode=_mode, user_id=user_id,
                                    rtcf_voice=_rtcf_voice, brain_speech=brain_speech)
        except ImportError:
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

        response = requests.post(
            get_tts_url(), headers=get_tts_headers(),
            data=ssml.encode('utf-8'), timeout=30
        )

        if response.status_code == 200:
            return response.content

        return None

    except Exception as e:
        logger.error(f"Radim speak error: {e}")
        return None


# ============================================================================
# TOKEN CACHE
# ============================================================================

_token_cache = {'token': None, 'expires': 0}


def get_cached_token():
    """Return cached token dict"""
    return _token_cache


logger.info("✅ Speech Helpers loaded — Azure config, voices, anticipation TTS, radim_speak")
