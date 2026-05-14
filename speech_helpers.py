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


# X21.29: radim_speak() retired — last caller was speech_routes.synthesize,
# which was removed in X21.28. Production TTS now goes exclusively through
# tts_proxy_routes.azure_tts_proxy → voice_filter.build_radim_ssml.
# Helper is preserved in git history (commit pre-X21.29) if ever needed.


# ============================================================================
# TOKEN CACHE
# ============================================================================

_token_cache = {'token': None, 'expires': 0}


def get_cached_token():
    """Return cached token dict"""
    return _token_cache


logger.info("✅ Speech Helpers loaded — Azure config, voices, anticipation TTS, radim_speak")
