"""
Radim Multi-Domain Anticipation Engine
======================================

Pure-Python mathematical core for proactive senior/child agent.
Standalone — no Flask, no DB, no external deps. Fully unit-testable.

State vector (Sprint X20.5: extended to 6 domains):
    C = (C_emotional, C_environmental, C_social, C_physical,
         C_cognitive, C_circadian)                            ∈ [0, 40]^6
    α = stress factor                                          ∈ [0, 1]
    E = emotional valence                                      ∈ [-1, 1]

Domain semantics:
    emotional     — current affect / mood from chat sentiment
    environmental — sensory load (noise/light/CO2/temp deviation)
    social        — connection/isolation signal (chat freq vs baseline)
    physical      — heart rate / SpO2 / motion anomaly
    cognitive     — task switching / attention regulation (ADHD-relevant,
                    autism transition struggle, senior word-finding)
    circadian     — time-of-day driven baseline (senior sundowning,
                    ADHD morning fog, autism schedule predictability)

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
    """Per-persona dimension weights for composite C. Sprint X20.5: 6 dims.

    Default = senior baseline. cognitive + circadian default to 0 for
    backward compat (any caller passing 4-arg DomainWeights still works).
    """
    emotional: float = 0.40
    environmental: float = 0.20
    social: float = 0.20
    physical: float = 0.20
    cognitive: float = 0.00
    circadian: float = 0.00

    def normalized(self) -> "DomainWeights":
        s = (self.emotional + self.environmental + self.social
             + self.physical + self.cognitive + self.circadian)
        if s == 0:
            return DomainWeights()
        return DomainWeights(
            emotional     = self.emotional     / s,
            environmental = self.environmental / s,
            social        = self.social        / s,
            physical      = self.physical      / s,
            cognitive     = self.cognitive     / s,
            circadian     = self.circadian     / s,
        )


# Pre-canned persona weight presets — Sprint X20.5: 6-dim per persona.
# Each row sums to 1.0. Tuned for the persona's primary risk axes:
#   senior:       circadian non-zero (sundowning); cognitive moderate
#   child_autism: env-heavy + cognitive (transitions); circadian low
#   child_adhd:   cognitive HIGH (task switching is the core challenge)
PERSONA_WEIGHTS = {
    "senior":       DomainWeights(0.30, 0.15, 0.15, 0.15, 0.10, 0.15),
    "child_autism": DomainWeights(0.25, 0.30, 0.10, 0.15, 0.15, 0.05),
    "child_adhd":   DomainWeights(0.25, 0.15, 0.15, 0.15, 0.25, 0.05),
}


# ─── State + Trend ──────────────────────────────────────────────────────────


@dataclass
class State:
    """A single point-in-time sample. Sprint X20.5: 6 dimensions.

    cognitive + circadian default to 10 (neutral) so existing callers that
    construct State without those args still get a valid 6-dim sample.
    """
    t: datetime
    c_emotional: float
    c_environmental: float
    c_social: float
    c_physical: float
    alpha: float
    c_cognitive: float = 10.0
    c_circadian: float = 10.0
    e_valence: float = 0.0  # informational; not currently in prediction loop

    def total(self, weights: DomainWeights) -> float:
        w = weights.normalized()
        return (w.emotional      * self.c_emotional
                + w.environmental * self.c_environmental
                + w.social        * self.c_social
                + w.physical      * self.c_physical
                + w.cognitive     * self.c_cognitive
                + w.circadian     * self.c_circadian)


@dataclass
class Trend:
    """EMA-smoothed change-rate per dimension, in units per 5-min step.
    Sprint X20.5: cognitive + circadian dimensions added (default 0.0)."""
    c_emotional: float = 0.0
    c_environmental: float = 0.0
    c_social: float = 0.0
    c_physical: float = 0.0
    c_cognitive: float = 0.0
    c_circadian: float = 0.0
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
        c_emotional     = ema(prev_trend.c_emotional,     prev_state.c_emotional,     curr_state.c_emotional),
        c_environmental = ema(prev_trend.c_environmental, prev_state.c_environmental, curr_state.c_environmental),
        c_social        = ema(prev_trend.c_social,        prev_state.c_social,        curr_state.c_social),
        c_physical      = ema(prev_trend.c_physical,      prev_state.c_physical,      curr_state.c_physical),
        c_cognitive     = ema(prev_trend.c_cognitive,     prev_state.c_cognitive,     curr_state.c_cognitive),
        c_circadian     = ema(prev_trend.c_circadian,     prev_state.c_circadian,     curr_state.c_circadian),
        alpha           = ema(prev_trend.alpha,           prev_state.alpha,           curr_state.alpha),
    )


# ─── Single-step prediction ─────────────────────────────────────────────────


def predict_step(state: State, trend: Trend) -> State:
    """Project one 5-minute step forward.

    Stress coupling (alpha above target) pushes:
      emotional + physical : K2/4   (legacy split — most direct mapping)
      cognitive            : K2/6   (smaller — cognition degrades but slower)
    Environmental + social + circadian : trend only (no alpha coupling).

    Sprint X20.5: circadian extrapolated via trend during horizon. A
    higher-fidelity caller can overwrite c_circadian via compute_circadian_c
    after each step (see runtime layer). For 30-min horizons trend-based
    extrapolation tracks the curve closely enough.
    """
    stress_kick     = K2 * (state.alpha - ALPHA_TARGET) / 4.0
    cog_stress_kick = K2 * (state.alpha - ALPHA_TARGET) / 6.0
    return State(
        t = state.t + timedelta(minutes=5),
        c_emotional     = clamp(state.c_emotional     + K1 * trend.c_emotional     + stress_kick,     0.0, C_MAX),
        c_environmental = clamp(state.c_environmental + K1 * trend.c_environmental,                   0.0, C_MAX),
        c_social        = clamp(state.c_social        + K1 * trend.c_social,                          0.0, C_MAX),
        c_physical      = clamp(state.c_physical      + K1 * trend.c_physical      + stress_kick,     0.0, C_MAX),
        c_cognitive     = clamp(state.c_cognitive     + K1 * trend.c_cognitive     + cog_stress_kick, 0.0, C_MAX),
        c_circadian     = clamp(state.c_circadian     + K1 * trend.c_circadian,                       0.0, C_MAX),
        alpha           = clamp(state.alpha           + GAMMA * trend.alpha,                          0.0, 1.0),
        e_valence       = state.e_valence,
    )


def predict_horizon(state: State,
                    trend: Trend,
                    steps: int = PREDICT_STEPS_30MIN,
                    damping: float = DAMPING_30MIN) -> list[State]:
    """Multi-step prediction with trend reversion toward 0 (damping).
    Sprint X20.5: damping applied to all 6 dimensions + alpha."""
    out: list[State] = []
    cur_state = state
    cur_trend = trend
    for _ in range(steps):
        cur_state = predict_step(cur_state, cur_trend)
        cur_trend = Trend(
            c_emotional     = cur_trend.c_emotional     * damping,
            c_environmental = cur_trend.c_environmental * damping,
            c_social        = cur_trend.c_social        * damping,
            c_physical      = cur_trend.c_physical      * damping,
            c_cognitive     = cur_trend.c_cognitive     * damping,
            c_circadian     = cur_trend.c_circadian     * damping,
            alpha           = cur_trend.alpha           * damping,
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
