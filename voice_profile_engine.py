"""
🎙️ VOICE PROFILE ENGINE v1.0
================================
Per-user adaptive voice system.

Learns from interactions:
- User says "pomaleji" → decrease rate
- User says "hlasitěji" → note preference
- Evening interactions → slower pace
- Stressed user → remember calm preference

Stored in memory_learning['voice_profile'] JSONB.
Integrates with: brain_core speech, context_builder coherence, TTS proxy.

Philosophy: Voice should feel like a familiar person, not a machine.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_PROFILE = {
    'preferred_rate': 0.9,      # 0.6-1.2 (1.0=normal)
    'preferred_pause_ms': 618,  # φ-pause default
    'preferred_pitch_pct': 0,   # -10 to +10
    'preferred_style': 'friendly',
    'sensitivity': 'normal',    # low/normal/high (hearing)
    'time_adaptations': {
        'morning': {'rate_adjust': 0.0, 'style': 'friendly'},
        'afternoon': {'rate_adjust': 0.0, 'style': 'friendly'},
        'evening': {'rate_adjust': -0.05, 'style': 'calm'},
        'night': {'rate_adjust': -0.1, 'style': 'calm'},
    },
    'adjustments_count': 0,
    'last_adjustment': None,
}

# Voice commands that trigger profile learning
_SLOWER_SIGNALS = ['pomaleji', 'zpomal', 'mluv pomaleji', 'moc rychle', 'nerozumím']
_FASTER_SIGNALS = ['rychleji', 'zrychli', 'mluv rychleji']
_LOUDER_SIGNALS = ['hlasitěji', 'neslyším', 'špatně slyším', 'hlasitěji prosím']
_CALMER_SIGNALS = ['klidněji', 'tiše', 'potichu']


def get_voice_profile(user_id):
    """Load voice profile from memory_learning."""
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(user_id)
        profile = learning.get('voice_profile', {})
        # Merge with defaults
        result = dict(DEFAULT_PROFILE)
        result.update(profile)
        return result
    except Exception:
        return dict(DEFAULT_PROFILE)


def save_voice_profile(user_id, profile):
    """Save voice profile to memory_learning."""
    try:
        from memory_helpers import db_load_learning, db_save_learning
        learning = db_load_learning(user_id)
        learning['voice_profile'] = profile
        db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f"Voice profile save error: {e}")


def learn_from_message(user_id, message):
    """
    Detect voice adjustment signals in user message.
    Updates voice profile based on explicit user feedback.

    Returns: dict of adjustments made (or empty)
    """
    if not message:
        return {}

    msg = message.lower().strip()
    profile = get_voice_profile(user_id)
    adjustments = {}

    # Slower
    if any(sig in msg for sig in _SLOWER_SIGNALS):
        profile['preferred_rate'] = max(0.6, profile.get('preferred_rate', 0.9) - 0.05)
        profile['preferred_pause_ms'] = min(1618, profile.get('preferred_pause_ms', 618) + 100)
        adjustments['rate'] = profile['preferred_rate']
        adjustments['reason'] = 'user_requested_slower'

    # Faster
    elif any(sig in msg for sig in _FASTER_SIGNALS):
        profile['preferred_rate'] = min(1.2, profile.get('preferred_rate', 0.9) + 0.05)
        profile['preferred_pause_ms'] = max(300, profile.get('preferred_pause_ms', 618) - 100)
        adjustments['rate'] = profile['preferred_rate']
        adjustments['reason'] = 'user_requested_faster'

    # Louder / hearing
    if any(sig in msg for sig in _LOUDER_SIGNALS):
        profile['sensitivity'] = 'high'
        adjustments['sensitivity'] = 'high'

    # Calmer
    if any(sig in msg for sig in _CALMER_SIGNALS):
        profile['preferred_style'] = 'calm'
        adjustments['style'] = 'calm'

    if adjustments:
        profile['adjustments_count'] = profile.get('adjustments_count', 0) + 1
        profile['last_adjustment'] = datetime.utcnow().isoformat()
        save_voice_profile(user_id, profile)
        logger.info(f"🎙️ Voice profile updated for {user_id}: {adjustments}")

    return adjustments


def get_adapted_voice_params(user_id, coherence_state='rho', brain_speech=None, time_context='afternoon'):
    """
    Build final voice parameters by combining ALL sources:
    1. User's voice profile (learned preferences)
    2. Coherence state (φ–ρ–δ)
    3. Brain engine speech params
    4. Time-of-day adaptation

    Returns:
        dict: {rate, pitch_pct, pause_ms, style, styledegree}
    """
    profile = get_voice_profile(user_id)

    # Start with profile base
    rate = profile.get('preferred_rate', 0.9)
    pause_ms = profile.get('preferred_pause_ms', 618)
    pitch_pct = profile.get('preferred_pitch_pct', 0)
    style = profile.get('preferred_style', 'friendly')
    styledegree = '1.2'

    # Layer 2: Coherence state (φ–ρ–δ)
    if coherence_state == 'delta':
        rate = min(rate, 0.8)
        pause_ms = max(pause_ms, 1000)
        style = 'empathetic'
        styledegree = '1.5'
    elif coherence_state == 'phi':
        pause_ms = max(pause_ms, 618)
        style = 'friendly'
        styledegree = '1.3'

    # Layer 3: Brain engine override (most specific)
    if brain_speech:
        rate = brain_speech.get('rate', rate)
        pitch_pct = brain_speech.get('pitch_pct', pitch_pct)
        if brain_speech.get('style'):
            style = brain_speech['style']
        if brain_speech.get('styledegree'):
            styledegree = brain_speech['styledegree']
        if brain_speech.get('pause_ms'):
            pause_ms = brain_speech['pause_ms']

    # Layer 4: Time-of-day
    time_adj = profile.get('time_adaptations', {}).get(time_context, {})
    rate += time_adj.get('rate_adjust', 0)
    if time_adj.get('style') == 'calm' and coherence_state != 'delta':
        style = 'calm'

    # Sensitivity: hearing impaired → louder, slower
    if profile.get('sensitivity') == 'high':
        rate = min(rate, 0.85)
        pause_ms = max(pause_ms, 800)

    # Clamp values
    rate = round(max(0.6, min(1.2, rate)), 2)
    pause_ms = max(300, min(1618, int(pause_ms)))
    pitch_pct = max(-10, min(10, int(pitch_pct)))

    return {
        'rate': rate,
        'pitch_pct': pitch_pct,
        'pause_ms': pause_ms,
        'style': style,
        'styledegree': styledegree,
    }


def voice_params_to_prompt(params):
    """Convert voice params to prompt hint for LLM context."""
    return (f"Hlas: rate={params['rate']}, pause={params['pause_ms']}ms, "
            f"style={params['style']}, pitch={params['pitch_pct']}%")


logger.info("🎙️ Voice Profile Engine v1.0 loaded — per-user adaptive voice")
