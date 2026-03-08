# ============================================
# 🔊 RADIM AZURE TTS CONFIG v1.0
# Single source of truth for Azure Speech settings
# Used by: speech_routes, twilio_voice_routes,
#          radim_orchestrator, anticipation_routes, app.py
# ============================================

import os

# Azure Speech Service credentials
AZURE_SPEECH_KEY = os.environ.get('AZURE_SPEECH_KEY', '')
AZURE_SPEECH_REGION = os.environ.get('AZURE_SPEECH_REGION', 'westeurope')

# Default Czech voice
RADIM_AZURE_VOICE = 'cs-CZ-AntoninNeural'

# Available Czech voices
CZECH_VOICES = {
    'radim': {
        'azure_name': 'cs-CZ-AntoninNeural',
        'description': 'Klidný mužský hlas pro Radima',
        'gender': 'male',
        'recommended': True,
    },
    'antonin': {
        'azure_name': 'cs-CZ-AntoninNeural',
        'description': 'Standardní mužský český hlas',
        'gender': 'male',
    },
    'vlasta': {
        'azure_name': 'cs-CZ-VlastaNeural',
        'description': 'Přátelský ženský hlas',
        'gender': 'female',
    },
}

# Senior-optimized TTS settings
SENIOR_TTS_SETTINGS = {
    'rate': '0.85',
    'pitch': '-5%',
    'volume': 'loud',
}


def get_azure_voice(voice_id='radim'):
    """Get Azure voice name by short ID.

    Args:
        voice_id: 'radim', 'antonin', or 'vlasta'

    Returns:
        str: Azure voice name (e.g., 'cs-CZ-AntoninNeural')
    """
    voice = CZECH_VOICES.get(voice_id, CZECH_VOICES['radim'])
    return voice['azure_name']


def is_azure_configured():
    """Check if Azure Speech credentials are set."""
    return bool(AZURE_SPEECH_KEY)
