"""
RTCF Coherence Engine — The central equation
================================================
Computes Psi_RTCF(t) — the unified coherence value that drives
all downstream modulation (voice, proactive, alerting).

Psi_RTCF(t) = w_h * H_n + w_r * R_n + w_c * P_n + w_t * T_radim(t)

State interpretation via growth ratio:
  r_t = Psi_RTCF(t) / Psi_RTCF(t-1)
  r_t < 1.8           → recovery
  1.8 <= r_t <= 2.15  → optimal_conscious
  r_t > 2.15          → escalation
"""

from rtcf_constants import (
    W_H, W_R, W_C, W_T,
    N_MIN, N_MAX,
    RATIO_RECOVERY_UPPER, RATIO_OPTIMAL_UPPER,
    harmonic_n, radim_sequence, pell_n,
)
from rtcf_temporal import t_radim


def _clamp_n(n):
    return max(N_MIN, min(N_MAX, int(n)))


def compute_psi_rtcf(t, n, beat_period=5.0, flow_period=600.0):
    """Core RTCF equation.

    Args:
        t: timestamp in seconds (for temporal oscillator)
        n: sequence index, derived from consciousness level C
        beat_period: beat oscillator period (seconds)
        flow_period: flow oscillator period (seconds)

    Returns:
        float — Psi_RTCF value (positive, grows with n)
    """
    n = _clamp_n(n)

    h_n = harmonic_n(n)           # Fibonacci(n) + Lucas(n)
    r_n = radim_sequence(n)       # RadimSequence(n)
    p_n = pell_n(n)               # Pell(n)
    t_val = t_radim(t, beat_period, flow_period)  # [0, 1]

    return W_H * h_n + W_R * r_n + W_C * p_n + W_T * t_val


def compute_ratio(psi_current, psi_previous):
    """Growth ratio between consecutive Psi_RTCF values.

    Returns:
        float — r_t. Returns 2.0 (neutral/optimal) on zero division.
    """
    if psi_previous is None or psi_previous == 0:
        return 2.0  # Neutral default — in optimal_conscious range
    return psi_current / psi_previous


def interpret_state(ratio):
    """Classify RTCF state from growth ratio.

    Returns:
        str — 'recovery', 'optimal_conscious', or 'escalation'
    """
    if ratio < RATIO_RECOVERY_UPPER:
        return "recovery"
    elif ratio <= RATIO_OPTIMAL_UPPER:
        return "optimal_conscious"
    else:
        return "escalation"


def compute_coherence_full(t, n, psi_previous=None, beat_period=5.0, flow_period=600.0):
    """Full coherence computation in one call.

    Args:
        t: timestamp
        n: sequence index
        psi_previous: Psi_RTCF(t-1) for ratio computation
        beat_period: beat period
        flow_period: flow period

    Returns:
        dict with psi_rtcf, ratio, state, components (for debugging)
    """
    n = _clamp_n(n)

    h_n = harmonic_n(n)
    r_n = radim_sequence(n)
    p_n = pell_n(n)
    t_val = t_radim(t, beat_period, flow_period)

    psi = W_H * h_n + W_R * r_n + W_C * p_n + W_T * t_val
    ratio = compute_ratio(psi, psi_previous)
    state = interpret_state(ratio)

    return {
        "psi_rtcf": round(psi, 6),
        "ratio": round(ratio, 6),
        "state": state,
        "components": {
            "harmony": round(W_H * h_n, 6),
            "radim": round(W_R * r_n, 6),
            "crisis": round(W_C * p_n, 6),
            "temporal": round(W_T * t_val, 6),
        },
        "n": n,
    }
