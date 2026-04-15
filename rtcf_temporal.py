"""
RTCF Temporal Engine — The living pulse
=========================================
Three-layer deterministic oscillation system that produces T_radim(t).

Beat oscillator  (3-8s)    — moment-to-moment rhythm, like breathing
Flow oscillator  (5-15min) — conversational waves, engagement cycles
Circadian        (24h)     — daily arc, peak at ~14:00

Combined into a single normalized [0, 1] temporal signal.
All functions are pure — no state, no side effects, trivially testable.
"""

import math
from rtcf_constants import (
    BEAT_PERIOD_MIN, BEAT_PERIOD_MAX, BEAT_PERIOD_DEFAULT,
    FLOW_PERIOD_MIN, FLOW_PERIOD_MAX, FLOW_PERIOD_DEFAULT,
    CIRCADIAN_PERIOD,
)

TWO_PI = 2.0 * math.pi

# Circadian phase offset: peak at 14:00 (50400s from midnight)
# sin peaks at π/2 → shift by (period/4 - 50400) but simpler:
# sin(2π(t - 50400)/86400) peaks when t = 50400 + 86400/4 = 50400 + 21600 = 72000
# Actually we want peak at 50400, so: sin(2π(t - 50400)/86400 + π/2)
# = cos(2π(t - 50400)/86400)
_CIRCADIAN_PEAK_OFFSET = 50400.0  # 14:00 in seconds from midnight


def beat_oscillator(t, period=BEAT_PERIOD_DEFAULT):
    """Moment-to-moment pulse. Returns [-1, 1].

    Args:
        t: timestamp in seconds (absolute or relative)
        period: oscillation period, clamped to [3, 8] seconds
    """
    p = max(BEAT_PERIOD_MIN, min(BEAT_PERIOD_MAX, period))
    return math.sin(TWO_PI * t / p)


def flow_oscillator(t, period=FLOW_PERIOD_DEFAULT):
    """Conversational wave. Returns [-1, 1].

    Args:
        t: timestamp in seconds
        period: oscillation period, clamped to [300, 900] seconds
    """
    p = max(FLOW_PERIOD_MIN, min(FLOW_PERIOD_MAX, period))
    return math.sin(TWO_PI * t / p)


def circadian_oscillator(t):
    """Daily rhythm arc. Returns [-1, 1].

    Peak at ~14:00 local time. Input t should be seconds-since-midnight
    for local time awareness, or POSIX timestamp for UTC.

    Args:
        t: seconds since midnight (or POSIX timestamp — only fractional day matters)
    """
    # Use cosine so peak is at offset point
    return math.cos(TWO_PI * (t - _CIRCADIAN_PEAK_OFFSET) / CIRCADIAN_PERIOD)


def t_radim(t, beat_period=BEAT_PERIOD_DEFAULT, flow_period=FLOW_PERIOD_DEFAULT):
    """Combined temporal signal — the living pulse. Returns [0, 1].

    Three oscillators summed and normalized from [-3, +3] → [0, 1].

    Args:
        t: timestamp in seconds
        beat_period: beat oscillator period
        flow_period: flow oscillator period

    Returns:
        float in [0, 1] — temporal modulation value
    """
    b = beat_oscillator(t, beat_period)
    f = flow_oscillator(t, flow_period)
    c = circadian_oscillator(t)
    # Sum range: [-3, +3] → normalize to [0, 1]
    return (b + f + c + 3.0) / 6.0
