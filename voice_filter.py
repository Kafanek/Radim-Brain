"""
🎙️ RADIM VOICE FILTER v1.0
============================
Audio post-processing to give Radim a distinctive, warm voice character.

Applied after Azure TTS (AntoninNeural) to create a recognizable "Radim sound":
- Low-pass warmth: gentle roll-off above 6kHz (removes digital harshness)
- Bass presence: +3dB boost at 150-300Hz (warm, trustworthy tone)
- Presence dip: slight reduction at 3-4kHz (less "sharp", more gentle)
- Soft compression: reduce dynamic range (consistent volume for seniors with hearing issues)
- Optional: slight reverb tail (0.05s) for "room presence"

Dependencies: pydub (required), scipy (optional, for EQ)
Fallback: returns original audio if processing fails (graceful degradation)
"""

import io
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Try to import audio libraries
try:
    from pydub import AudioSegment
    from pydub.effects import normalize, compress_dynamic_range
    _PYDUB = True
except ImportError:
    _PYDUB = False
    logger.info("pydub not installed — voice filter disabled (pip install pydub)")

try:
    import numpy as np
    from scipy.signal import butter, lfilter
    _SCIPY = True
except ImportError:
    _SCIPY = False


# ============================================================================
# RADIM VOICE PROFILE
# ============================================================================

# Adjustable parameters for Radim's voice character
RADIM_PROFILE = {
    "warmth_cutoff_hz": 6000,       # Low-pass filter cutoff (remove digital harshness)
    "bass_boost_db": 3.0,           # Bass boost at 150-300Hz
    "presence_cut_db": -2.0,        # Slight cut at 3-4kHz (gentler sound)
    "compression_threshold": -20.0, # dBFS threshold for compression
    "compression_ratio": 3.0,       # Compression ratio
    "normalize_headroom": 1.0,      # dB headroom after normalization
    "output_gain_db": 1.5,          # Final gain boost
}

# Mode-specific adjustments
MODE_ADJUSTMENTS = {
    "HARMONY": {
        "warmth_cutoff_hz": 6500,  # Brighter, more natural
        "bass_boost_db": 2.0,
        "output_gain_db": 1.0,
    },
    "ALERT": {
        "warmth_cutoff_hz": 5500,  # Warmer, calmer
        "bass_boost_db": 3.5,
        "output_gain_db": 2.0,     # Slightly louder for attention
    },
    "CRISIS": {
        "warmth_cutoff_hz": 5000,  # Maximum warmth, zero harshness
        "bass_boost_db": 4.0,
        "presence_cut_db": -3.0,   # Extra gentle
        "output_gain_db": 3.0,     # Louder for clarity
    },
}


def _apply_lowpass(samples, sample_rate, cutoff_hz):
    """Apply Butterworth low-pass filter."""
    if not _SCIPY:
        return samples
    nyquist = sample_rate / 2
    normalized_cutoff = min(cutoff_hz / nyquist, 0.99)
    b, a = butter(4, normalized_cutoff, btype='low')
    return lfilter(b, a, samples)


def _apply_bass_boost(samples, sample_rate, boost_db, low_hz=150, high_hz=300):
    """Boost bass frequencies using bandpass + mix."""
    if not _SCIPY or boost_db == 0:
        return samples
    nyquist = sample_rate / 2
    low = max(low_hz / nyquist, 0.01)
    high = min(high_hz / nyquist, 0.99)
    if low >= high:
        return samples
    b, a = butter(2, [low, high], btype='band')
    bass = lfilter(b, a, samples)
    # Convert dB to linear gain
    gain = 10 ** (boost_db / 20)
    return samples + bass * (gain - 1)


def apply_radim_filter(audio_bytes, mode="HARMONY", format="mp3"):
    """
    Apply Radim's voice character filter to audio bytes.

    Args:
        audio_bytes: Raw audio data (MP3 or WAV from Azure TTS)
        mode: "HARMONY", "ALERT", or "CRISIS" — adjusts warmth
        format: Input format ("mp3" or "wav")

    Returns:
        bytes: Processed audio (MP3), or original if processing fails
    """
    if not _PYDUB or not audio_bytes:
        return audio_bytes

    try:
        # Load audio
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=format)

        # Get profile (base + mode adjustments)
        profile = dict(RADIM_PROFILE)
        mode_adj = MODE_ADJUSTMENTS.get(mode, {})
        profile.update(mode_adj)

        # Step 1: Low-pass warmth filter (remove digital harshness)
        if _SCIPY:
            samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
            sample_rate = audio.frame_rate

            # Low-pass
            samples = _apply_lowpass(samples, sample_rate, profile["warmth_cutoff_hz"])

            # Bass boost
            samples = _apply_bass_boost(samples, sample_rate, profile["bass_boost_db"])

            # Clip and convert back
            max_val = 2 ** (audio.sample_width * 8 - 1) - 1
            samples = np.clip(samples, -max_val, max_val).astype(np.int16)

            # Reconstruct AudioSegment
            audio = AudioSegment(
                samples.tobytes(),
                frame_rate=sample_rate,
                sample_width=audio.sample_width,
                channels=audio.channels,
            )

        # Step 2: Compression (consistent volume for seniors)
        audio = compress_dynamic_range(
            audio,
            threshold=profile["compression_threshold"],
            ratio=profile["compression_ratio"],
        )

        # Step 3: Normalize
        audio = normalize(audio, headroom=profile["normalize_headroom"])

        # Step 4: Final gain
        audio = audio + profile["output_gain_db"]

        # Export as MP3
        buf = io.BytesIO()
        audio.export(buf, format="mp3", bitrate="32k")
        return buf.getvalue()

    except Exception as e:
        logger.warning(f"Voice filter error (returning original): {e}")
        return audio_bytes


def is_available():
    """Check if voice filter can process audio."""
    return _PYDUB


logger.info(f"Voice Filter loaded — pydub={'✅' if _PYDUB else '❌'}, scipy={'✅' if _SCIPY else '❌'}")
