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
        "rate": "-10%",          # v455: pomalejší = jasnější pro seniory
        "pitch": "+2%",          # v455: mírně vyšší = jasnější artikulace
        "volume": "loud",
        "pause_ms": 618,         # φ × 382 — golden ratio pause
        "emphasis": False,       # natural, no emphasis
    },
    "ALERT": {
        "style": "empathetic",
        "styledegree": "1.5",
        "rate": "-18%",          # v455: pomalejší pro jasnost
        "pitch": "+0%",          # neutrální
        "volume": "loud",
        "pause_ms": 1000,        # longer pauses for processing
        "emphasis": True,        # gentle emphasis on key words
    },
    "CRISIS": {
        "style": "calm",
        "styledegree": "2.0",    # maximum emotional expression
        "rate": "-25%",          # very slow, deliberate
        "pitch": "-3%",          # v455: méně hluboký = srozumitelnější
        "volume": "x-loud",     # louder for clarity
        "pause_ms": 1618,        # φ × 1000 — maximum pause
        "emphasis": True,
    },
}

# Words that should get gentle emphasis in ALERT/CRISIS
EMPHASIS_WORDS = {
    # Uklidnění
    "klid", "klidně", "pomoc", "pomohu", "dýchejte", "nadechněte",
    "vydechněte", "zavolám", "jste", "bezpečí", "poradím", "společně",
    # Zdraví
    "rodina", "doktor", "lékař", "záchranku", "nemocnice",
    # Čísla — tísňová volání
    "155", "158", "112",
    # Léky
    "léky", "lék", "tabletu", "prášek",
}

# Numbers and medicine names get emphasis automatically
EMPHASIS_PATTERNS = [
    r'\b\d{3}\b',             # 3-digit numbers (155, 112)
    r'\b\d{1,2}:\d{2}\b',    # times (8:30, 14:00)
]


def _add_sentence_pauses(text, pause_ms):
    """Insert SSML breaks between sentences."""
    if not text:
        return ""
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
    """Add gentle emphasis to key words, numbers, medicine names.
    v473: Prevents double-nesting (<emphasis><emphasis>).
    """
    # Word emphasis
    for word in EMPHASIS_WORDS:
        pattern = re.compile(rf'(?<!<emphasis level="moderate">)\b({re.escape(word)})\b', re.IGNORECASE)
        text_with_breaks = pattern.sub(
            r'<emphasis level="moderate">\1</emphasis>',
            text_with_breaks
        )
    # Pattern emphasis (numbers, times) — skip if already wrapped
    for pat in EMPHASIS_PATTERNS:
        text_with_breaks = re.sub(
            rf'(?<!<emphasis level="moderate">)({pat})(?!</emphasis>)',
            r'<emphasis level="moderate">\1</emphasis>',
            text_with_breaks
        )
    return text_with_breaks


# v405: Response length limit — prevent long TTS output (seniors lose focus)
MAX_TTS_CHARS = 200

# v405: Fatigue hysteresis — prevent mode switching instability
_FATIGUE_ACTIVATE = 0.65
_FATIGUE_DEACTIVATE = 0.55
_FATIGUE_MAX_ENTRIES = 500  # v407: prevent memory leak — evict oldest when full
_fatigue_slow_active = {}  # user_id → bool


def _truncate_for_tts(text, max_chars=MAX_TTS_CHARS):
    """Shorten text for TTS while preserving meaning.
    Cuts at sentence boundary, adds continuation hint.
    Guarantees: len(result) <= max_chars + 1 (for trailing period).
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Find last sentence boundary before limit
    truncated = text[:max_chars]
    last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_period > max_chars * 0.4:  # at least 40% of text
        return truncated[:last_period + 1]
    # No good sentence boundary — cut at last space
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space] + "."
    # v407: Guarantee max length even for single long word
    return truncated[:max_chars - 1] + "."


def _add_pause_variability(pause_ms):
    """Add slight random variability to pauses for natural speech.
    ±50ms (small enough to not notice, big enough to sound human).
    """
    import random
    variation = random.randint(-50, 50)
    return max(200, pause_ms + variation)  # minimum 200ms


def build_radim_ssml(text, mode="HARMONY", voice="cs-CZ-AntoninNeural", user_id=None):
    """Build rich SSML for Radim's voice with mode-adaptive styling.

    v405 hardening:
    - MAX_TTS_CHARS truncation (seniors lose focus on long speech)
    - Fatigue hysteresis (prevent mode switching instability)
    - Pause variability (±50ms for natural rhythm)
    - Logging: mode, overrides applied, text length
    """
    if mode not in VOICE_PROFILES:
        logger.warning(f"Invalid voice mode '{mode}' — falling back to HARMONY")
    profile = dict(VOICE_PROFILES.get(mode, VOICE_PROFILES["HARMONY"]))
    overrides = []

    # v405: Truncate long text
    original_len = len(text)
    text = _truncate_for_tts(text)
    if len(text) < original_len:
        overrides.append(f"truncated:{original_len}→{len(text)}")

    # v403: Per-user adaptive overrides
    if user_id:
        try:
            from adaptive_learning import get_adaptive_state
            state = get_adaptive_state(user_id)
            if state:
                comm = state.get("communication", {})
                if comm.get("speech_speed") == "slow" and mode == "HARMONY":
                    profile["rate"] = "-15%"
                    profile["pause_ms"] = 1000
                    overrides.append("slow_speech")

                # v405: Fatigue with hysteresis
                fatigue = state.get("fatigue_level", 0)
                was_slow = _fatigue_slow_active.get(user_id, False)
                if fatigue > _FATIGUE_ACTIVATE or (was_slow and fatigue > _FATIGUE_DEACTIVATE):
                    # v407: Evict oldest entries to prevent memory leak
                    if len(_fatigue_slow_active) > _FATIGUE_MAX_ENTRIES:
                        oldest = next(iter(_fatigue_slow_active))
                        del _fatigue_slow_active[oldest]
                    _fatigue_slow_active[user_id] = True
                    current_rate = int(profile["rate"].replace("%", "").replace("+", ""))
                    profile["rate"] = f"{min(current_rate, -15)}%"
                    profile["pause_ms"] = max(profile["pause_ms"], 1200)
                    overrides.append(f"fatigue:{fatigue}")
                else:
                    _fatigue_slow_active[user_id] = False

                recovery = state.get("recovery", {})
                if recovery.get("active") and recovery.get("level", 0) >= 2:
                    # v407: Don't speed up if already slower (e.g. CRISIS at -25%)
                    current_rate = int(profile["rate"].replace("%", "").replace("+", ""))
                    profile["rate"] = f"{min(current_rate, -20)}%"
                    profile["volume"] = "x-loud"
                    profile["pause_ms"] = max(profile["pause_ms"], 1500)
                    overrides.append(f"recovery:L{recovery['level']}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Adaptive voice failed for {user_id}: {e}")

    # Add pauses between sentences (with variability)
    pause = _add_pause_variability(profile["pause_ms"])
    styled_text = _add_sentence_pauses(text, pause)

    # Add emphasis in ALERT/CRISIS
    if profile["emphasis"]:
        styled_text = _add_emphasis(styled_text)

    if overrides:
        logger.info(f"TTS [{mode}] {len(text)}ch overrides=[{','.join(overrides)}]")

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
