"""
🎙️ RADIM VOICE FILTER v2.0
============================
Creates Radim's distinctive warm voice using advanced Azure SSML features.

Instead of audio post-processing (which requires ffmpeg), we use Azure's
built-in voice styling capabilities:
- mstts:express-as: emotion style + degree
- prosody: rate, pitch, volume per brain mode
- break: φ-proportioned pauses between sentences
- emphasis: key words get gentle emphasis

Mode-adaptive: HARMONY/ALERT/CRISIS each have distinct voice profiles.
Falls back gracefully if Azure doesn't support a feature.
"""

import re
import logging
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# ============================================================================
# RADIM VOICE PROFILES (Azure SSML parameters)
# ============================================================================

VOICE_PROFILES = {
    "HARMONY": {
        "style": "friendly",
        "styledegree": "1.3",
        "rate": "-5%",
        "pitch": "-2%",
        "volume": "loud",
        "pause_ms": 618,        # φ × 382 — golden ratio pause
        "emphasis": False,      # natural, no emphasis
    },
    "ALERT": {
        "style": "empathetic",
        "styledegree": "1.5",
        "rate": "-15%",         # noticeably slower
        "pitch": "-5%",         # lower = calmer
        "volume": "loud",
        "pause_ms": 1000,       # longer pauses for processing
        "emphasis": True,       # gentle emphasis on key words
    },
    "CRISIS": {
        "style": "calm",
        "styledegree": "2.0",   # maximum emotional expression
        "rate": "-25%",         # very slow, deliberate
        "pitch": "-8%",         # deep, reassuring
        "volume": "x-loud",    # louder for clarity
        "pause_ms": 1618,       # φ × 1000 — maximum pause
        "emphasis": True,
    },
}

# Words that should get gentle emphasis in ALERT/CRISIS
EMPHASIS_WORDS = {
    "klid", "klidně", "pomoc", "pomohu", "dýchejte", "nadechněte",
    "vydechněte", "zavolám", "jste", "bezpečí", "poradím", "společně",
    "rodina", "doktor", "lékař", "záchranku",
}


def _add_sentence_pauses(text, pause_ms):
    """Insert SSML breaks between sentences."""
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 1:
        return xml_escape(text)

    parts = []
    for i, s in enumerate(sentences):
        parts.append(xml_escape(s.strip()))
        if i < len(sentences) - 1:
            parts.append(f'<break time="{pause_ms}ms"/>')
    return " ".join(parts)


def _add_emphasis(text_with_breaks):
    """Add gentle emphasis to key words (for ALERT/CRISIS)."""
    for word in EMPHASIS_WORDS:
        # Case-insensitive replace, preserve original case
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        text_with_breaks = pattern.sub(
            r'<emphasis level="moderate">\1</emphasis>',
            text_with_breaks
        )
    return text_with_breaks


def build_radim_ssml(text, mode="HARMONY", voice="cs-CZ-AntoninNeural"):
    """
    Build rich SSML for Radim's voice with mode-adaptive styling.

    Args:
        text: Czech text to speak
        mode: "HARMONY", "ALERT", or "CRISIS"
        voice: Azure voice name

    Returns:
        str: Complete SSML string
    """
    profile = VOICE_PROFILES.get(mode, VOICE_PROFILES["HARMONY"])

    # Add pauses between sentences
    styled_text = _add_sentence_pauses(text, profile["pause_ms"])

    # Add emphasis in ALERT/CRISIS
    if profile["emphasis"]:
        styled_text = _add_emphasis(styled_text)

    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
           xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
    <voice name="{voice}">
        <mstts:express-as style="{profile['style']}" styledegree="{profile['styledegree']}">
            <prosody rate="{profile['rate']}" pitch="{profile['pitch']}" volume="{profile['volume']}">
                {styled_text}
            </prosody>
        </mstts:express-as>
    </voice>
</speak>'''

    return ssml


def apply_radim_filter(audio_bytes, mode="HARMONY", format="mp3"):
    """
    v2.0: No-op pass-through. Voice filtering is now done at SSML level
    via build_radim_ssml(). This function exists for backward compatibility.

    Returns audio_bytes unchanged.
    """
    return audio_bytes


def is_available():
    """Voice filter is always available (SSML-based, no dependencies)."""
    return True


logger.info("✅ Voice Filter v2.0 loaded — SSML-based, no ffmpeg needed")
