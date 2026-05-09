"""
Radim Multi-Domain Anticipation Engine
======================================

Pure-Python mathematical core for proactive senior/child agent.
Standalone — no Flask, no DB, no external deps. Fully unit-testable.

State vector:
    C = (C_emotional, C_environmental, C_social, C_physical)   ∈ [0, 40]^4
    α = stress factor                                          ∈ [0, 1]
    E = emotional valence                                      ∈ [-1, 1]

Composite consciousness (per persona):
    C_total = Σ wᵢ · Cᵢ      with Σ wᵢ = 1

EMA trends (λ = 0.3, time-normalized to 5-min units):
    T^X_t = λ · ΔX/Δt + (1 − λ) · T^X_{t−1}

Single-step prediction (Δt = 5 min):
    Ĉᵢ_{t+1} = Cᵢ_t + k₁·T^Cᵢ + ½·k₂·(α − α*)/4   for emotional, physical
    α̂_{t+1} = α_t + γ·T^α
(environmental and social drift only by their own trend; alpha couples
 to emotional + physical because stress manifests there.)

Multi-step prediction (Δt = 30 min, 6 steps with trend damping ζ = 0.85):
    Tᵢ_{n+1} = ζ · Tᵢ_n             # trends revert toward zero
    Sᵢ_{n+1} = predict_step(Sᵢ_n, Tᵢ_n)

Mode classification:
    HARMONY  if C_total <  12
    ALERT    if 12 ≤ C_total < 27
    CRISIS   if C_total ≥  27

Preemptive trigger:
    if max(C_total over horizon) reaches a higher mode than current
    → preemptive_action_required = True   (act now, not after onset)

Speech parameter derivation (φ-proportioned, only when above target):
    excess  = max(0, C_total − C*)        with C* = 18
    empathy = clamp(0.5 + K_EMP·(C/40 + α),    [0.3, 1.0])
    rate    = clamp(1.0 − K_RATE·excess,       [0.7, 1.1])
    pitch   = clamp(−K_PITCH·excess,           [−4, +2])
    pause   = clamp(300 + K_PAUSE·excess,      [100, 800])

φ-proportioned pause defaults: 300ms (~base) → 500ms (alert) → 800ms (crisis)
follow Fibonacci-adjacent ratios used by voice_filter SSML elsewhere.

Author: Sprint X20.1 — Foundation
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

# ─── Constants ──────────────────────────────────────────────────────────────

PHI = 1.6180339887498949
PSI = 1.0 / PHI

# Mode thresholds on composite C ∈ [0, 40]
C_HARMONY = 12.0
C_ALERT = 27.0
C_MAX = 40.0

# Targets
C_TARGET = 18.0
ALPHA_TARGET = 0.4

# Prediction coefficients
LAMBDA_EMA = 0.3
K1 = 1.0    # weight of trend in next-state prediction
K2 = 7.5    # weight of stress (alpha vs target) on emotional/physical C
GAMMA = 0.5  # weight of trend in next-alpha prediction
DAMPING_30MIN = 0.85
PREDICT_STEPS_30MIN = 6  # 6 × 5 min = 30 min

# Speech / prosody coefficients.
# Tuned so a high-CRISIS state (C≈35, α≈0.9) hits the upper clamp on pause
# and the lower clamp on rate/pitch — Radim becomes maximally calm.
K_EMP        = 0.15
K_RATE_C     = 0.02
K_RATE_ALPHA = 0.10
K_PITCH      = 0.5
K_PAUSE_C    = 25     # ms per unit of C above target
K_PAUSE_ALPHA = 200   # ms per unit of α above target
RATE_BOUNDS    = (0.7, 1.1)
PITCH_BOUNDS   = (-4.0, 2.0)
PAUSE_BOUNDS   = (100, 800)
EMPATHY_BOUNDS = (0.3, 1.0)


# ─── Helpers ────────────────────────────────────────────────────────────────


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def classify(c_total: float) -> str:
    if c_total < C_HARMONY:
        return "HARMONY"
    if c_total < C_ALERT:
        return "ALERT"
    return "CRISIS"


def mode_severity(mode: str) -> int:
    return {"HARMONY": 0, "ALERT": 1, "CRISIS": 2}.get(mode, 0)


# ─── Domain weights (per persona) ───────────────────────────────────────────


@dataclass
class DomainWeights:
    emotional: float = 0.4
    environmental: float = 0.2
    social: float = 0.2
    physical: float = 0.2

    def normalized(self) -> "DomainWeights":
        s = self.emotional + self.environmental + self.social + self.physical
        if s == 0:
            return DomainWeights()
        return DomainWeights(
            emotional=self.emotional / s,
            environmental=self.environmental / s,
            social=self.social / s,
            physical=self.physical / s,
        )


# Pre-canned persona weight presets (also live in personas/*.yaml later)
PERSONA_WEIGHTS = {
    "senior":       DomainWeights(0.40, 0.20, 0.20, 0.20),
    "child_autism": DomainWeights(0.30, 0.40, 0.10, 0.20),
    "child_adhd":   DomainWeights(0.40, 0.20, 0.20, 0.20),
}


# ─── State + Trend ──────────────────────────────────────────────────────────


@dataclass
class State:
    """A single point-in-time sample."""
    t: datetime
    c_emotional: float
    c_environmental: float
    c_social: float
    c_physical: float
    alpha: float
    e_valence: float = 0.0  # informational; not currently in prediction loop

    def total(self, weights: DomainWeights) -> float:
        w = weights.normalized()
        return (w.emotional      * self.c_emotional
                + w.environmental * self.c_environmental
                + w.social        * self.c_social
                + w.physical      * self.c_physical)


@dataclass
class Trend:
    """EMA-smoothed change-rate per dimension, in units per 5-min step."""
    c_emotional: float = 0.0
    c_environmental: float = 0.0
    c_social: float = 0.0
    c_physical: float = 0.0
    alpha: float = 0.0


# ─── Trend update ───────────────────────────────────────────────────────────


def update_trend(prev_trend: Trend,
                 prev_state: State,
                 curr_state: State,
                 lam: float = LAMBDA_EMA) -> Trend:
    """Exponentially smooth per-dimension delta, normalized to 5-min step."""
    dt_min = max(1.0, (curr_state.t - prev_state.t).total_seconds() / 60.0)
    norm = dt_min / 5.0  # delta is "per 5 min"

    def ema(prev_t, prev_v, curr_v):
        return lam * (curr_v - prev_v) / norm + (1 - lam) * prev_t

    return Trend(
        c_emotional   = ema(prev_trend.c_emotional,   prev_state.c_emotional,   curr_state.c_emotional),
        c_environmental = ema(prev_trend.c_environmental, prev_state.c_environmental, curr_state.c_environmental),
        c_social      = ema(prev_trend.c_social,      prev_state.c_social,      curr_state.c_social),
        c_physical    = ema(prev_trend.c_physical,    prev_state.c_physical,    curr_state.c_physical),
        alpha         = ema(prev_trend.alpha,         prev_state.alpha,         curr_state.alpha),
    )


# ─── Single-step prediction ─────────────────────────────────────────────────


def predict_step(state: State, trend: Trend) -> State:
    """Project one 5-minute step forward."""
    # Stress coupling on emotional + physical (each gets ¼ of the K2 push,
    # because we split the legacy single-domain K2 across two coupled
    # dimensions instead of dumping it all on emotional).
    stress_kick = K2 * (state.alpha - ALPHA_TARGET) / 4.0
    return State(
        t = state.t + timedelta(minutes=5),
        c_emotional   = clamp(state.c_emotional   + K1 * trend.c_emotional   + stress_kick, 0.0, C_MAX),
        c_environmental = clamp(state.c_environmental + K1 * trend.c_environmental,             0.0, C_MAX),
        c_social      = clamp(state.c_social      + K1 * trend.c_social,                       0.0, C_MAX),
        c_physical    = clamp(state.c_physical    + K1 * trend.c_physical    + stress_kick,    0.0, C_MAX),
        alpha         = clamp(state.alpha         + GAMMA * trend.alpha,                       0.0, 1.0),
        e_valence     = state.e_valence,
    )


def predict_horizon(state: State,
                    trend: Trend,
                    steps: int = PREDICT_STEPS_30MIN,
                    damping: float = DAMPING_30MIN) -> list[State]:
    """Multi-step prediction with trend reversion toward 0 (damping)."""
    out: list[State] = []
    cur_state = state
    cur_trend = trend
    for _ in range(steps):
        cur_state = predict_step(cur_state, cur_trend)
        cur_trend = Trend(
            c_emotional   = cur_trend.c_emotional   * damping,
            c_environmental = cur_trend.c_environmental * damping,
            c_social      = cur_trend.c_social      * damping,
            c_physical    = cur_trend.c_physical    * damping,
            alpha         = cur_trend.alpha         * damping,
        )
        out.append(cur_state)
    return out


# ─── Speech params ──────────────────────────────────────────────────────────


@dataclass
class SpeechParams:
    empathy: float
    rate: float
    pitch: float
    pause_ms: int
    mode: str

    def to_ssml_prosody(self) -> str:
        """Azure-friendly prosody attributes."""
        rate_pct = int(round((self.rate - 1.0) * 100))
        return f'rate="{rate_pct:+d}%" pitch="{self.pitch:+.1f}st"'


def derive_speech(state: State, weights: DomainWeights) -> SpeechParams:
    """Map current (C_total, α) → prosody parameters for Azure SSML."""
    c_total  = state.total(weights)
    excess_c = max(0.0, c_total      - C_TARGET)
    excess_a = max(0.0, state.alpha  - ALPHA_TARGET)
    return SpeechParams(
        empathy  = clamp(0.5 + K_EMP * (c_total / C_MAX + state.alpha),     *EMPATHY_BOUNDS),
        rate     = clamp(1.0 - K_RATE_C * excess_c - K_RATE_ALPHA * excess_a, *RATE_BOUNDS),
        pitch    = clamp(-K_PITCH * excess_c,                                 *PITCH_BOUNDS),
        pause_ms = int(clamp(300 + K_PAUSE_C * excess_c + K_PAUSE_ALPHA * excess_a,
                             *PAUSE_BOUNDS)),
        mode     = classify(c_total),
    )


# ─── Preemptive check (will C cross a threshold within horizon?) ───────────


@dataclass
class PreemptiveCheck:
    current_mode: str
    predicted_mode: str   # mode at peak of horizon
    crosses_up: bool       # any horizon point in higher mode than current
    crosses_down: bool     # any horizon point in lower mode (recovery)
    peak_c: float
    peak_at_minute: int    # minutes after t=now when peak occurs
    horizon_totals: list[float]


def preemptive_check(current: State,
                     horizon: list[State],
                     weights: DomainWeights) -> PreemptiveCheck:
    cur_total = current.total(weights)
    cur_mode = classify(cur_total)
    if not horizon:
        return PreemptiveCheck(cur_mode, cur_mode, False, False,
                               cur_total, 0, [])

    totals = [s.total(weights) for s in horizon]
    peak_idx = max(range(len(totals)), key=lambda i: totals[i])
    peak_c = totals[peak_idx]
    trough_c = min(totals)

    return PreemptiveCheck(
        current_mode=cur_mode,
        predicted_mode=classify(peak_c),
        crosses_up=mode_severity(classify(peak_c)) > mode_severity(cur_mode),
        crosses_down=mode_severity(classify(trough_c)) < mode_severity(cur_mode),
        peak_c=peak_c,
        peak_at_minute=(peak_idx + 1) * 5,
        horizon_totals=totals,
    )


# ─── Engine snapshot (public API) ───────────────────────────────────────────


@dataclass
class EngineSnapshot:
    state: State
    trend: Trend
    c_total: float
    mode: str
    speech: SpeechParams
    horizon_30min: list[State]
    preemptive: PreemptiveCheck


def run_engine(history: Sequence[State],
               weights: DomainWeights | None = None) -> EngineSnapshot:
    """Compute full anticipation snapshot from a state history.

    history must contain at least 1 state. With only 1 state, trend is zero
    (cold start). With ≥ 2 states, trend is built by EMA across consecutive
    pairs.
    """
    if not history:
        raise ValueError("history must contain at least 1 state")
    if weights is None:
        weights = DomainWeights()
    history = list(history)

    trend = Trend()
    for i in range(1, len(history)):
        trend = update_trend(trend, history[i - 1], history[i])

    current = history[-1]
    horizon = predict_horizon(current, trend)
    speech = derive_speech(current, weights)
    pre = preemptive_check(current, horizon, weights)
    c_total = current.total(weights)

    return EngineSnapshot(
        state=current,
        trend=trend,
        c_total=c_total,
        mode=classify(c_total),
        speech=speech,
        horizon_30min=horizon,
        preemptive=pre,
    )
