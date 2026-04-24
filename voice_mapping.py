"""
Voice Mapping — single source of truth for voice_mode ↔ emotion/style conversion.
=============================================================================

Audit (2026-04-24) found 5 parallel naming systems in the backend:
    voice_mode:   'HARMONY' | 'FESTIVE' | 'ALERT' | 'CRISIS' | 'NARRATION'
    mode (FSM):   'normal' | 'calm'
    emotion:      'friendly' | 'calm' | 'cheerful' | 'empathetic' | 'serious'
    style (SSML): Azure express-as styles
    rtcf_voice:   Brain state → voice param

This module is the ONE place where mapping happens. All TTS code (Azure TTS,
Twilio IVR, speech_helpers, brain_speech) MUST import from here, not define
their own mapping.

Usage:
    from voice_mapping import resolve_voice_params, VOICE_MODES

    params = resolve_voice_params('HARMONY', user_id='abc', age=78)
    # {'voice': 'cs-CZ-AntoninNeural', 'rate': '0.85',
    #  'pitch': '-3%', 'style': 'friendly', 'styledegree': '1.2'}

Design principles:
    - Czech (cs-CZ) as the ONLY language; voice options limited
    - Senior-friendly defaults: slower rate, slightly lower pitch
    - Deterministic: same input always produces same params
    - Safe fallback: unknown mode → HARMONY (never crashes)
"""

from typing import Dict, Optional, Any

# ─────────────────────────────────────────────────────────────────────────────
# CANONICAL VOICE MODES — the ONLY accepted voice_mode values
# ─────────────────────────────────────────────────────────────────────────────

VOICE_MODES = {
    # Normal companion chat — warm, calm, slightly slower for seniors
    'HARMONY': {
        'style':       'friendly',
        'styledegree': '1.2',
        'rate':        '0.85',   # 85% of base (senior-friendly)
        'pitch':       '-3%',    # slightly lower, warmer
        'description': 'Klidný, přátelský tón — běžná konverzace',
    },
    # Holiday / celebration / greeting — warmer, more expressive
    'FESTIVE': {
        'style':       'cheerful',
        'styledegree': '1.5',
        'rate':        '0.88',
        'pitch':       '0%',
        'description': 'Sváteční, radostný — pozdravy, oslavy',
    },
    # Reading stories / narrating — even slower, more articulate
    'NARRATION': {
        'style':       'narration-professional',
        'styledegree': '1.0',
        'rate':        '0.80',
        'pitch':       '-2%',
        'description': 'Vypravěčský — čtení příběhů, kvízy',
    },
    # Concerned / vigilant — slower, empathetic, checking in
    'ALERT': {
        'style':       'empathetic',
        'styledegree': '1.4',
        'rate':        '0.78',   # slower when something's off
        'pitch':       '-5%',
        'description': 'Zvýšená pozornost — kontrola, upozornění',
    },
    # Emergency — very slow, calm authoritative, overrides everything
    'CRISIS': {
        'style':       'serious',
        'styledegree': '1.8',
        'rate':        '0.72',   # slowest — max clarity in emergency
        'pitch':       '-8%',
        'description': 'Nouzová situace — klidný autoritativní hlas',
    },
}

# Fallback if caller passes junk
DEFAULT_MODE = 'HARMONY'

# Canonical voice names (Azure Neural cs-CZ)
# Radim = male voice. Add alternates only if senior profile explicitly requests.
RADIM_VOICE = 'cs-CZ-AntoninNeural'
FALLBACK_VOICE = 'cs-CZ-VlastaNeural'   # female fallback if Antonin errors

# Legacy alias map (normalize older string variants → canonical mode)
_ALIASES = {
    # Frontend/DB variants
    'harmony':  'HARMONY',
    'calm':     'HARMONY',
    'normal':   'HARMONY',
    'neutral':  'HARMONY',
    'festive':  'FESTIVE',
    'greeting': 'FESTIVE',
    'happy':    'FESTIVE',
    'cheerful': 'FESTIVE',
    'narration':'NARRATION',
    'reading':  'NARRATION',
    'story':    'NARRATION',
    'alert':    'ALERT',
    'warning':  'ALERT',
    'concerned':'ALERT',
    'crisis':   'CRISIS',
    'emergency':'CRISIS',
    'critical': 'CRISIS',
    # Emotion → mode (reverse lookups)
    'friendly':    'HARMONY',
    'empathetic':  'ALERT',
    'serious':     'CRISIS',
}


def normalize_mode(mode: Optional[str]) -> str:
    """Accept any mode string (case/variant) → canonical mode name.
    Safe against None/empty/unknown: always returns a valid mode."""
    if not mode:
        return DEFAULT_MODE
    m = str(mode).strip().upper()
    if m in VOICE_MODES:
        return m
    # Try alias lookup (case-insensitive)
    alias = _ALIASES.get(str(mode).strip().lower())
    if alias and alias in VOICE_MODES:
        return alias
    return DEFAULT_MODE


def resolve_voice_params(
    mode: Optional[str] = None,
    user_id: Optional[str] = None,
    age: Optional[int] = None,
    voice: Optional[str] = None,
    rate_override: Optional[str] = None,
    pitch_override: Optional[str] = None,
    anticipation: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Resolve final voice parameters for a TTS request.

    Args:
        mode:          voice_mode string (any variant, normalized internally)
        user_id:       for future per-user voice preferences (not used yet)
        age:           if >= 75, extra slowdown for comprehension
        voice:         override default Czech voice
        rate_override: override computed rate (e.g. '0.9')
        pitch_override: override computed pitch (e.g. '-5%')
        anticipation:  {'C': float, 'alpha': float, ...} — brain state
                       adjusts rate/pitch for cognitive load compensation

    Returns:
        dict with keys: voice, rate, pitch, style, styledegree, mode
    """
    canonical = normalize_mode(mode)
    spec = VOICE_MODES[canonical]

    params = {
        'mode':        canonical,
        'voice':       voice or RADIM_VOICE,
        'style':       spec['style'],
        'styledegree': spec['styledegree'],
        'rate':        rate_override or spec['rate'],
        'pitch':       pitch_override or spec['pitch'],
    }

    # Age-aware adjustment (extra 5% slowdown for 75+)
    if age is not None:
        try:
            if int(age) >= 75 and not rate_override:
                # rate is a string like '0.85' — adjust 5% slower
                base_rate = float(params['rate'])
                params['rate'] = f"{max(0.6, base_rate * 0.95):.2f}"
        except (ValueError, TypeError):
            pass

    # Anticipation-based adjustment (if brain engine provides state)
    # Lower C (cognitive coherence) → slower rate (compensation)
    if anticipation and isinstance(anticipation, dict):
        try:
            C = anticipation.get('C')
            if C is not None and not rate_override:
                C_f = float(C)
                # C in [0, 50]; scale rate down if below 30
                if C_f < 30:
                    slowdown = 1.0 - (30 - C_f) / 100.0  # e.g. C=10 → rate*0.80
                    base_rate = float(params['rate'])
                    params['rate'] = f"{max(0.6, base_rate * slowdown):.2f}"
        except (ValueError, TypeError):
            pass

    return params


def mode_to_emotion(mode: Optional[str]) -> str:
    """Shortcut: get just the Azure emotion/style for a mode."""
    return VOICE_MODES[normalize_mode(mode)]['style']


def describe_mode(mode: Optional[str]) -> str:
    """Human-readable description (for debugging / admin UI)."""
    return VOICE_MODES[normalize_mode(mode)]['description']


def all_modes() -> list:
    """For dropdown UIs: return list of canonical mode names."""
    return list(VOICE_MODES.keys())
