"""
RTCF Constants & Sequences — The heartbeat's mathematical foundation
=====================================================================
Central constants, the RadimSequence, and helpers for the
RADIM Temporal Coherence Framework.

Reuses Fibonacci/Lucas/Pell from brain_math.py — no duplication.
"""

import math
from functools import lru_cache

# ═══════════════════════════════════════════════════════════
# TRIADIC CONSTANTS
# ═══════════════════════════════════════════════════════════

PHI = 1.61803398875          # Harmony / Recovery constant
DELTA = 2.41421356237        # Crisis / Escalation constant
RHO = 2.0134621242           # Optimal Consciousness / Active Balance

# ═══════════════════════════════════════════════════════════
# WEIGHTS (must sum to 1.0)
# ═══════════════════════════════════════════════════════════

W_H = 0.30   # Harmony component (Fibonacci + Lucas)
W_R = 0.35   # Radim component (RadimSequence)
W_C = 0.20   # Crisis component (Pell)
W_T = 0.15   # Temporal component (T_radim)

assert abs(W_H + W_R + W_C + W_T - 1.0) < 1e-9, "RTCF weights must sum to 1.0"

# ═══════════════════════════════════════════════════════════
# TEMPORAL PERIODS
# ═══════════════════════════════════════════════════════════

BEAT_PERIOD_MIN = 3.0       # seconds
BEAT_PERIOD_MAX = 8.0       # seconds
BEAT_PERIOD_DEFAULT = 5.0   # seconds

FLOW_PERIOD_MIN = 300.0     # 5 minutes
FLOW_PERIOD_MAX = 900.0     # 15 minutes
FLOW_PERIOD_DEFAULT = 600.0 # 10 minutes

CIRCADIAN_PERIOD = 86400.0  # 24 hours in seconds

# ═══════════════════════════════════════════════════════════
# BEAT ENGINE CONSTANTS
# ═══════════════════════════════════════════════════════════

BPM_BASE = 68
BPM_MIN = 50
BPM_MAX = 110

# BPM formula coefficients
BPM_RISK = 12
BPM_PAIN = 10
BPM_INTUITION = 8
BPM_LOAD = 6
BPM_RECOVERY = -10

# ═══════════════════════════════════════════════════════════
# STATE INTERPRETATION THRESHOLDS
# ═══════════════════════════════════════════════════════════

RATIO_RECOVERY_UPPER = 1.8      # below → recovery
RATIO_OPTIMAL_UPPER = 2.15      # above → escalation

# ═══════════════════════════════════════════════════════════
# SEQUENCE INDEX RANGE
# ═══════════════════════════════════════════════════════════

N_MIN = 1
N_MAX = 14  # Safe range for all arrays in brain_math

# ═══════════════════════════════════════════════════════════
# SEQUENCES — Reuse from brain_math, extend with RadimSequence
# ═══════════════════════════════════════════════════════════

try:
    from brain_math import FIBONACCI, LUCAS, PELL
except ImportError:
    # Standalone fallback for testing without brain_math
    FIBONACCI = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610]
    LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199, 322, 521, 843]
    PELL = [0, 1, 2, 5, 12, 29, 70, 169, 408, 985, 2378]


def _clamp_n(n):
    """Clamp sequence index to safe range."""
    return max(N_MIN, min(N_MAX, int(n)))


@lru_cache(maxsize=64)
def radim_sequence(n):
    """RadimSequence: R(0)=1, R(1)=PHI, R(n)=PHI*R(n-1)+(DELTA-PHI)*R(n-2)"""
    if n <= 0:
        return 1.0
    if n == 1:
        return PHI
    return PHI * radim_sequence(n - 1) + (DELTA - PHI) * radim_sequence(n - 2)


def harmonic_n(n):
    """H_n = Fibonacci(n) + Lucas(n) — the harmony component."""
    idx = _clamp_n(n)
    fib = FIBONACCI[min(idx, len(FIBONACCI) - 1)]
    luc = LUCAS[min(idx, len(LUCAS) - 1)]
    return float(fib + luc)


def pell_n(n):
    """P_n = Pell(n) — the crisis component."""
    idx = _clamp_n(n)
    return float(PELL[min(idx, len(PELL) - 1)])
