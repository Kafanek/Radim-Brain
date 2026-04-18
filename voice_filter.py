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
    # ── Brain-state modes ──
    # v10.22: PŘIROZENÝ HLAS — Antonín má vlastní intonaci, contour ji přepisuje
    # Proto: contour POUZE pro SINGING (písně). Vše ostatní = Antonínova přirozená řeč
    # + rate/pitch/pauzy pro charakter. Jednodušší = přirozenější.
    "HARMONY": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-5%",           # mírně pomalejší než přirozený
        "pitch": "+0%",          # v10.23: neutrální přirozený
        "volume": "loud",
        "pause_ms": 500,         # přirozené pauzy
        "emphasis": False,
        # NO contour — Antonínova vlastní intonace je nejpřirozenější
    },
    "ALERT": {
        "style": "empathetic",
        "styledegree": "1.5",
        "rate": "-15%",          # pomalejší pro pochopení
        "pitch": "+0%",          # v10.23: mírně hlubší
        "volume": "loud",
        "pause_ms": 800,
        "emphasis": True,
    },
    "CRISIS": {
        "style": "calm",
        "styledegree": "2.0",
        "rate": "-20%",          # výrazně pomalejší
        "pitch": "+0%",          # v10.23: hlubší pro klid
        "volume": "x-loud",
        "pause_ms": 1200,        # dlouhé pauzy
        "emphasis": True,
    },
    "POETRY": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-10%",          # recitační tempo
        "pitch": "+0%",          # v10.23: neutrální
        "volume": "loud",
        "pause_ms": 800,         # dramatické pauzy
        "emphasis": False,
        "poetry_mode": True,
    },
    "NARRATION": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-12%",          # vypravěčské tempo
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 700,
        "emphasis": False,
    },
    "NEWS": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-3%",           # skoro přirozené
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 400,
        "emphasis": False,
    },
    "EDUCATION": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-12%",          # pomalejší pro učení
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 700,
        "emphasis": True,
    },
    # v10.40: FESTIVE — sváteční pozdrav, jmeniny, narozeniny
    # Mírně pomalejší než HARMONY, s teplejším tónem a delší pauzou po jmenu
    "FESTIVE": {
        "style": "friendly",
        "styledegree": "2.0",    # maximální "friendly" styling
        "rate": "-8%",           # mírně pomaleji než běžný chat
        "pitch": "+0%",          # Antonínův přirozený tón
        "volume": "loud",
        "pause_ms": 600,         # φ * 371 ≈ 600 — teplejší rytmus
        "emphasis": True,        # zdůrazní slova jako "jmeniny", "krásný"
    },
    "SINGING": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-15%",          # v10.22: mezi řečí a zpěvem — hravé tempo
        "pitch": "+0%",          # v10.23: neutrální
        "volume": "loud",
        "pause_ms": 400,
        "emphasis": False,
        "contour": "song",       # melodie z databáze písní — Radim si hraje s jazykem
        "contour_scale": 1.5,    # v10.22: 1.5× intenzivnější melodie
    },
    "RHYTHMIC": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-8%",
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 500,
        "emphasis": False,
        # NO contour — Antonínova přirozená intonace + pomalejší tempo
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

# v10.20: Czech pronunciation fixes for Azure cs-CZ-AntoninNeural
# Applied AFTER xml_escape so SSML tags are preserved
# Azure mispronounces "ch" /x/ as "č" /tʃ/ in some words
_CZECH_PHONEME_FIXES = [
    # (escaped_word_regex, ipa, display_text)
    (r'\b[Dd]ýchejte\b', 'diːxɛjtɛ', None),
    (r'\b[Nn]adechněte\b', 'nadɛxɲɛtɛ', None),
    (r'\b[Vv]ydechněte\b', 'vidɛxɲɛtɛ', None),
    (r'\b[Dd]ýchat\b', 'diːxat', None),
    (r'\b[Dd]ýchání\b', 'diːxaɲiː', None),
    (r'\b[Dd]ýchej\b', 'diːxɛj', None),
]

def _fix_czech_pronunciation(text):
    """Fix Azure mispronunciations using IPA phoneme tags.

    Must be called AFTER xml_escape() so the SSML tags are not escaped.
    """
    for pattern, ipa, display in _CZECH_PHONEME_FIXES:
        match = re.search(pattern, text)
        if match:
            word = match.group(0)
            display_text = display or word
            replacement = f'<phoneme alphabet="ipa" ph="{ipa}">{display_text}</phoneme>'
            text = text[:match.start()] + replacement + text[match.end():]
    return text


# Numbers and medicine names get emphasis automatically
EMPHASIS_PATTERNS = [
    r'\b\d{3}\b',             # 3-digit numbers (155, 112)
    r'\b\d{1,2}:\d{2}\b',    # times (8:30, 14:00)
]



def _add_sentence_pauses(text, pause_ms, poetry_mode=False):
    """Insert SSML breaks between sentences.

    v10.17: poetry_mode uses verse-aware pausing:
    - Period/exclamation/question at end → full pause (verse end)
    - Comma, semicolon, dash → short breath pause (200-300ms)
    - Within a verse line (no punctuation) → no pause (flow)
    """
    if not text:
        return ""

    if poetry_mode:
        return _add_poetry_pauses(text, pause_ms)

    # Standard prose pausing
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 1:
        return xml_escape(text)

    parts = []
    for i, s in enumerate(sentences):
        parts.append(xml_escape(s.strip()))
        if i < len(sentences) - 1:
            parts.append(f'<break time="{pause_ms}ms"/>')
    return " ".join(parts)


def _add_poetry_pauses(text, base_pause_ms):
    """Verse-aware SSML pausing for poetry recitation.

    Rules:
    - Period (.) → medium pause (verse/stanza end)
    - Comma (,) → breath pause (250ms) — keeps flow within verse
    - Semicolon (;) → short pause (350ms)
    - Dash (—/-) → dramatic pause (400ms)
    - Line break (already converted to '. ') → verse pause
    - No punctuation between words → continuous flow
    """
    escaped = xml_escape(text)

    # Replace punctuation with SSML breaks
    # Comma → tiny breath (keeps verse flowing)
    escaped = re.sub(r',\s*', f', <break time="250ms"/> ', escaped)

    # Semicolon → slightly longer
    escaped = re.sub(r';\s*', f'; <break time="350ms"/> ', escaped)

    # Dash (em-dash or en-dash) → dramatic pause
    escaped = re.sub(r'\s*[—–-]\s*', f' <break time="400ms"/> ', escaped)

    # Period/exclamation/question → verse end pause
    escaped = re.sub(r'([.!?])\s+', rf'\1 <break time="{base_pause_ms}ms"/> ', escaped)

    return escaped


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


def _add_pause_variability(pause_ms, mode="random"):
    """Add variability to pauses for natural speech rhythm.

    Modes:
        'random'  → ±50 ms uniform noise (default — chat, info, news)
        'phi'     → golden-ratio alternation (poetry, festive, narration)
                    pauses alternate between base*1 and base/φ (≈0.618)
        'breath'  → ±15% gaussian around base (calm, crisis)
    """
    import random, math
    PHI = 1.6180339887

    if mode == "phi":
        # Alternate longer / shorter by golden ratio → more musical
        if not hasattr(_add_pause_variability, "_phi_toggle"):
            _add_pause_variability._phi_toggle = 0
        _add_pause_variability._phi_toggle += 1
        if _add_pause_variability._phi_toggle % 2 == 0:
            return max(200, int(pause_ms * (1 / PHI)))
        return max(200, int(pause_ms))
    elif mode == "breath":
        variation = int(random.gauss(0, pause_ms * 0.15))
        return max(200, pause_ms + variation)
    else:  # random
        variation = random.randint(-50, 50)
        return max(200, pause_ms + variation)


def build_radim_ssml(text, mode="HARMONY", voice="cs-CZ-AntoninNeural", user_id=None, rtcf_voice=None):
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

    # v10.19: Apply voice learning (per-user adaptation)
    if user_id:
        try:
            from voice_learning import apply_voice_learning
            profile = apply_voice_learning(profile, user_id)
            overrides.append("learned")
        except ImportError:
            pass  # voice_learning not installed
        except Exception as e:
            logger.info(f"⚠️ Voice learning failed for {user_id}: {e}")

    # v10.25: RTCF heartbeat voice modifiers
    if rtcf_voice:
        rate_adj = rtcf_voice.get('rate_adjust', 0)
        if rate_adj:
            current = int(profile['rate'].replace('%', '').replace('+', ''))
            profile['rate'] = f"{current + int(rate_adj)}%"
        pause_adj = rtcf_voice.get('pause_adjust_ms', 0)
        if pause_adj:
            profile['pause_ms'] = max(200, profile['pause_ms'] + pause_adj)
        style_hint = rtcf_voice.get('style_hint')
        if style_hint:
            profile['style'] = style_hint
        sd_hint = rtcf_voice.get('styledegree_hint')
        if sd_hint:
            profile['styledegree'] = sd_hint
        overrides.append("rtcf")

    # v10.20: PER-SENTENCE prosody with individual φ-contour
    # Each sentence gets its own pitch curve → natural intonation
    # v10.40: pause variability mode by profile
    _pause_var_mode = "random"
    if mode in ("POETRY", "FESTIVE", "NARRATION", "SINGING"):
        _pause_var_mode = "phi"
    elif mode in ("CRISIS", "ALERT"):
        _pause_var_mode = "breath"
    pause_ms = _add_pause_variability(profile["pause_ms"], mode=_pause_var_mode)
    is_poetry = profile.get("poetry_mode", False)
    contour_type = profile.get("contour")
    # v10.20: Profile-specific energy → learned energy → default
    _energy = profile.get('learned_energy', profile.get('contour_energy', 0.5))

    # Split text into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        sentences = [text]

    # Build per-sentence SSML blocks
    sentence_blocks = []
    contour_used = False

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue

        safe_sentence = xml_escape(sentence)

        # v10.20: Pronunciation fixes AFTER xml_escape (SSML tags won't be escaped)
        # Azure cs-CZ-AntoninNeural says "dýčejte" instead of "dýchejte"
        # Fix: use IPA phoneme tag to force correct "ch" /x/ pronunciation
        safe_sentence = _fix_czech_pronunciation(safe_sentence)

        # Emphasis for ALERT/CRISIS
        if profile["emphasis"]:
            safe_sentence = _add_emphasis(safe_sentence)

        # Poetry: verse-aware pauses within sentence
        if is_poetry:
            safe_sentence = _add_poetry_pauses(safe_sentence, pause_ms)

        # Per-sentence contour (each sentence has its own melodic curve)
        contour_attr = ""
        if contour_type:
            try:
                from voice_melody import get_voice_contour
                contour = get_voice_contour(sentence, mode=contour_type, energy=_energy, user_id=user_id)
                if contour:
                    # v10.22: Scale contour intensity
                    _scale = profile.get('contour_scale', 1.0)
                    if _scale != 1.0:
                        import re as _re
                        def _scale_hz(m):
                            val = int(int(m.group(1)) * _scale)
                            return f'{val:+d}Hz'
                        contour = _re.sub(r'([+-]?\d+)Hz', _scale_hz, contour)
                    contour_attr = f' contour="{contour}"'
                    contour_used = True
            except (ImportError, Exception):
                pass

        # Slight pitch variation per sentence position (natural declination)
        pitch_mod = profile['pitch']
        if len(sentences) > 1:
            base_pitch = int(pitch_mod.replace('%', '').replace('+', ''))
            if i == 0:
                # Opening — slightly higher pitch
                val = base_pitch + 2
            elif i == len(sentences) - 1:
                # Closing — slightly lower
                val = base_pitch - 1
            else:
                val = base_pitch
            pitch_mod = f"{val:+d}%"  # Correct format: "+2%" or "-3%"

        sentence_blocks.append(
            f'<prosody rate="{profile["rate"]}" pitch="{pitch_mod}" volume="{profile["volume"]}"{contour_attr}>'
            f'{safe_sentence}</prosody>'
        )

        # Add pause between sentences (not after last)
        if i < len(sentences) - 1:
            sentence_blocks.append(f'<break time="{pause_ms}ms"/>')

    if contour_used:
        overrides.append(f"φ-contour:{contour_type}:e{_energy:.1f}:s{len(sentences)}")

    if overrides:
        logger.info(f"TTS [{mode}] {len(text)}ch overrides=[{','.join(overrides)}]")

    inner_ssml = "\n            ".join(sentence_blocks)
    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
           xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
    <voice name="{voice}">
        <mstts:express-as style="{profile['style']}" styledegree="{profile['styledegree']}">
            {inner_ssml}
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
