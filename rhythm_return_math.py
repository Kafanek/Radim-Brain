"""
🎵 RHYTHM RETURN MATH — Pure math for Parkinson's rhythm therapy
================================================================
Extracted from rhythm_return_routes.py for modularity.

Mathematical model:
- Motor Load: M (0-40), analogicky k C (consciousness)
- Tremor/Rigidity Index: τ (0-1), analogicky k α (stress)
- Stavy: FLOW (<12), STRUGGLE (12-27), FREEZE (>=27)

Key principle:
  R_φ(t) = sin(ωt) + sin(φωt)  — quasi-periodic rhythm
  If ω₂/ω₁ = φ, synchronization is mathematically impossible (mode-locking).

Version: 1.0.0
"""

import math
import logging

logger = logging.getLogger(__name__)

# --- Shared math from Anticipation Engine ---
try:
    from anticipation_routes import (
        sigmoid as _ant_sigmoid,
        clamp as _ant_clamp,
        calculate_trend as _ant_calculate_trend,
        PHI as _ANT_PHI,
        PSI as _ANT_PSI
    )
    _ANT_AVAILABLE = True
except ImportError:
    _ANT_AVAILABLE = False


# ============================================
# GOLDEN RATIO CONSTANTS
# ============================================

PHI = _ANT_PHI if _ANT_AVAILABLE else 1.618033988749895
PSI = _ANT_PSI if _ANT_AVAILABLE else 0.618033988749895
PHI_SQ = PHI * PHI  # φ² = 2.618...


# ============================================
# MOTOR STATE THRESHOLDS (analogie k C_HARMONY/C_ALERT)
# ============================================

M_FLOW = 12        # M < 12 = plynulý pohyb
M_STRUGGLE = 27    # 12 ≤ M < 27 = obtíže, zpomalení
M_MAX = 40         # Maximum motor load
M_TARGET = 18      # Optimální cílové M*
TAU_TARGET = 0.4   # Optimální cílové τ*


# ============================================
# PREDICTION COEFFICIENTS
# ============================================

K1_MOTOR = 1.2     # Váha motorického trendu na M
K2_MOTOR = 8.0     # Váha tremoru (τ) na M
GAMMA_MOTOR = 0.5  # Amplifikace τ trendu
LAMBDA_M = 0.3     # EMA faktor pro trend M
LAMBDA_TAU = 0.3   # EMA faktor pro trend τ


# ============================================
# THERAPEUTIC BPM CONSTANTS
# ============================================

BPM_REST = 60       # Klidové tempo
BPM_PREFERRED = 100 # Typická PD kadence (steps/min)
BPM_HEALTHY = 114   # Zdravá kadence elderly
BPM_MAX = 130       # Maximum pro RAS terapii
BPM_MIN = 56        # Minimum bezpečné

# φ-odvozené BPM hodnoty
BPM_PHI_FREEZE = round(BPM_REST * PHI)    # 60 × φ ≈ 97 — anti-freeze cueing
BPM_PHI_FLOW = round(BPM_REST * PHI_SQ)   # 60 × φ² ≈ 157 (theoretical max)


# ============================================
# CLINICAL FREQUENCY DATA
# ============================================

TREMOR_REST_HZ = (4, 6)          # Klidový tremor
TREMOR_FOG_HZ = (3, 8)           # Freezing oscilace
BETA_PATHOLOGICAL_HZ = (13, 30)  # Patologická beta synchronizace

# Golden Ratio Rhythm Sequence (z 40 Hz generátoru)
PHI_BANDS_HZ = [2.2, 5.8, 9.4, 15.3, 24.7, 40.0, 64.7, 104.7]

# Fibonacci sekvence — základ akcentových vzorů
FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]

# Hoehn-Yahr normativní data chůze
HY_GAIT = {
    "mild":     {"velocity_ms": 0.92, "cadence_spm": 100, "stride_m": 1.10, "hy_stages": "1-1.5"},
    "moderate": {"velocity_ms": 0.97, "cadence_spm": 104, "stride_m": 1.12, "hy_stages": "2-2.5"},
    "severe":   {"velocity_ms": 0.76, "cadence_spm": 97,  "stride_m": 1.04, "hy_stages": "3-4"}
}


# ============================================
# SPEECH RHYTHM CONSTANTS (φ-based)
# ============================================

PAUSE_FLOW_MS = int(1000 * PSI)     # 618 ms
PAUSE_STRUGGLE_MS = 1000            # 1000 ms
PAUSE_FREEZE_MS = int(1000 * PHI)   # 1618 ms

RATE_FLOW = 1.0
RATE_STRUGGLE = 0.85
RATE_FREEZE = 0.7

PITCH_FLOW_ST = 12
PITCH_STRUGGLE_ST = 8
PITCH_FREEZE_ST = 4


# ============================================
# HELPER FUNCTIONS
# ============================================

def sigmoid(x, k=1, x0=0):
    """Sigmoida σ(x) = 1 / (1 + e^(-k(x-x0)))"""
    if _ANT_AVAILABLE:
        return _ant_sigmoid(x, k, x0)
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if k * (x - x0) < 0 else 1.0


def clamp(value, min_val, max_val):
    """Ohraničení hodnoty do intervalu [min, max]"""
    if _ANT_AVAILABLE:
        return _ant_clamp(value, min_val, max_val)
    return max(min_val, min(max_val, value))


def calculate_trend(current, previous, trend_prev, lambda_factor):
    """EMA trend: T_t = λ(x_t - x_{t-1}) + (1-λ)T_{t-1}"""
    if _ANT_AVAILABLE:
        return _ant_calculate_trend(current, previous, trend_prev, lambda_factor)
    delta = current - previous
    return lambda_factor * delta + (1 - lambda_factor) * trend_prev


# ============================================
# CORE MATHEMATICAL FUNCTIONS
# ============================================

def predict_M(M_current, trend_M, tau_current):
    """Predikce motorické zátěže: M̂_{t+1} = M_t + K1·T^M_t + K2·(τ_t - 0.5)"""
    predicted = M_current + K1_MOTOR * trend_M + K2_MOTOR * (tau_current - 0.5)
    return clamp(predicted, 0, M_MAX)


def predict_tau(tau_current, trend_tau):
    """Predikce tremoru: τ̂_{t+1} = τ_t + γ·T^τ_t"""
    predicted = tau_current + GAMMA_MOTOR * trend_tau
    return clamp(predicted, 0, 1)


def classify_motor_state(M):
    """Klasifikace: FLOW (<12), STRUGGLE (12-27), FREEZE (>=27)"""
    if M < M_FLOW:
        return "FLOW"
    elif M < M_STRUGGLE:
        return "STRUGGLE"
    else:
        return "FREEZE"


def calculate_therapy_bpm(M_predicted, tau, preferred_bpm=BPM_PREFERRED):
    """Adaptivní terapeutický BPM odvozený z φ (zlatého řezu)."""
    state = classify_motor_state(M_predicted)

    if state == "FLOW":
        bpm = preferred_bpm * 1.05
        accent = fibonacci_accent_pattern("FLOW")
        phi_ratio = 1.05

    elif state == "STRUGGLE":
        bpm = preferred_bpm * PSI
        accent = fibonacci_accent_pattern("STRUGGLE")
        phi_ratio = PSI

    else:  # FREEZE
        bpm = BPM_REST * PHI
        accent = fibonacci_accent_pattern("FREEZE")
        phi_ratio = PHI

    bpm = clamp(round(bpm, 1), BPM_MIN, BPM_MAX)
    beat_duration_ms = round(60000 / bpm) if bpm > 0 else 1000

    return {
        "bpm": bpm,
        "state": state,
        "accent_pattern": accent,
        "beat_duration_ms": beat_duration_ms,
        "phi_ratio": round(phi_ratio, 4),
        "preferred_bpm": preferred_bpm
    }


def fibonacci_accent_pattern(state):
    """Fibonacci akcentový vzor — přirozené důrazy odvozené z Fibonacci sekvence."""
    if state == "FREEZE":
        return [{"position": 0, "intensity": 1.0, "is_accent": True}]

    if state == "STRUGGLE":
        fib_groups = [1, 1, 2]
    else:  # FLOW
        fib_groups = [1, 1, 2, 3, 5]

    pattern = []
    position = 0
    for group_size in fib_groups:
        for i in range(group_size):
            is_accent = (i == 0)
            intensity = 1.0 if is_accent else round(PSI, 3)
            pattern.append({
                "position": position,
                "intensity": intensity,
                "is_accent": is_accent
            })
            position += 1
    return pattern


def calculate_speech_rhythm(M_predicted, tau):
    """Řečový rytmus pro Parkinson — návrat prozodie."""
    state = classify_motor_state(M_predicted)

    if state == "FLOW":
        pause_ms = PAUSE_FLOW_MS
        rate = RATE_FLOW
        pitch_range = PITCH_FLOW_ST
        volume_mod = "phi_curve"
        phrasing = "fibonacci_full"

    elif state == "STRUGGLE":
        pause_ms = PAUSE_STRUGGLE_MS
        rate = RATE_STRUGGLE
        pitch_range = PITCH_STRUGGLE_ST
        volume_mod = "linear"
        phrasing = "fibonacci_simple"

    else:  # FREEZE
        pause_ms = PAUSE_FREEZE_MS
        rate = RATE_FREEZE
        pitch_range = PITCH_FREEZE_ST
        volume_mod = "step"
        phrasing = "single_command"

    # Jemné škálování podle τ
    tau_factor = 1.0 - 0.3 * tau
    rate = round(rate * tau_factor, 3)
    rate = clamp(rate, 0.5, 1.1)

    return {
        "pause_ms": pause_ms,
        "rate": rate,
        "pitch_range_st": pitch_range,
        "volume_modulation": volume_mod,
        "phrasing": phrasing,
        "state": state,
        "phi_proportions": {
            "psi": round(PSI, 4),
            "one": 1.0,
            "phi": round(PHI, 4),
            "ratio": f"{PAUSE_FLOW_MS}:{PAUSE_STRUGGLE_MS}:{PAUSE_FREEZE_MS}"
        }
    }


def calculate_confidence(M, tau, session_progress=0.0):
    """6D Confidence Vector — motivační profil pacienta."""
    M_norm = M / M_MAX

    flow = sigmoid(1 - M_norm - 0.5 * tau, k=3, x0=0.3)
    frustration = sigmoid(M_norm + tau, k=3, x0=0.5)
    fatigue = sigmoid(session_progress + 0.3 * tau, k=2, x0=0.6)
    motivation = sigmoid(1 - 1.2 * M_norm - 0.8 * tau, k=4, x0=0.4)
    focus = 1.0 - frustration
    pride = sigmoid(session_progress * (1 - M_norm), k=3, x0=0.3)

    return {
        "flow": round(flow, 4),
        "frustration": round(frustration, 4),
        "fatigue": round(fatigue, 4),
        "motivation": round(motivation, 4),
        "focus": round(focus, 4),
        "pride": round(pride, 4)
    }


def detect_motor_breakpoints(M_current, M_predicted):
    """Detekce stavových přechodů (FLOW↔STRUGGLE↔FREEZE)."""
    breakpoints = []

    # B_12: FLOW ↔ STRUGGLE
    if M_current < M_FLOW <= M_predicted:
        breakpoints.append({
            "type": "B_12",
            "direction": "up",
            "M_before": round(M_current, 2),
            "M_after": round(M_predicted, 2),
            "message": "Pohyb se zpomaluje — prepinám na podpurny rytmus",
            "action": "switch_to_struggle_bpm",
            "bpm_change": f"preferred x PSI ({PSI:.3f})"
        })
    elif M_current >= M_FLOW > M_predicted:
        breakpoints.append({
            "type": "B_12",
            "direction": "down",
            "M_before": round(M_current, 2),
            "M_after": round(M_predicted, 2),
            "message": "Navrat do flow — plynuly pohyb!",
            "action": "increase_tempo_gradually",
            "bpm_change": "preferred x 1.05 (trenink)"
        })

    # B_27: STRUGGLE ↔ FREEZE
    if M_current < M_STRUGGLE <= M_predicted:
        breakpoints.append({
            "type": "B_27",
            "direction": "up",
            "M_before": round(M_current, 2),
            "M_after": round(M_predicted, 2),
            "message": "FREEZE detekovan — aktivuji phi-cueing protokol",
            "action": "phi_cueing_protocol",
            "bpm_change": f"BPM_REST x PHI = {BPM_PHI_FREEZE}, single strong beat"
        })
    elif M_current >= M_STRUGGLE > M_predicted:
        breakpoints.append({
            "type": "B_27",
            "direction": "down",
            "M_before": round(M_current, 2),
            "M_after": round(M_predicted, 2),
            "message": "Odchazime z freeze — Fibonacci ramp zpet",
            "action": "fibonacci_ramp_restore",
            "bpm_change": "Fibonacci: 55 -> 89 -> 97 -> preferred"
        })

    return breakpoints


def calculate_phi_desync(omega_pathological_hz):
    """φ-desynchronizace — rozbití patologické oscilace zlatým řezem."""
    omega_stim = omega_pathological_hz * PHI
    period_ms = round(1000.0 / omega_stim, 2) if omega_stim > 0 else 0

    return {
        "omega_pathological_hz": omega_pathological_hz,
        "omega_stim_hz": round(omega_stim, 2),
        "period_ms": period_ms,
        "desync_ratio": round(PHI, 6),
        "formula": f"R_phi(t) = sin({omega_pathological_hz:.1f}*t) + sin({omega_stim:.2f}*t)",
        "principle": "phi-ratio prevents mode-locking (mathematical impossibility of synchronization)",
        "waveform": "quasi-periodic (never repeats exactly)"
    }


def get_motor_orchestrator_instructions(state, M_predicted, confidence):
    """Instrukce pro AI orchestrátora — jak mluvit k pacientovi."""
    if state == "FLOW":
        base = "Pacient je v FLOW stavu. Mluv povzbudive, udrzuj tempo."
        if confidence.get("pride", 0) > 0.6:
            base += " Pochval pokrok!"
        return base

    elif state == "STRUGGLE":
        base = "Pacient je ve STRUGGLE — zpomal rec, kratsi vety, vice pauz."
        if confidence.get("frustration", 0) > 0.5:
            base += " Validuj frustraci: 'Rozumim, neni to snadne.'"
        return base

    else:  # FREEZE
        base = "FREEZE PROTOKOL: Jednoduche prikazy. 'KROK.' Pauza. 'DALSI KROK.'"
        base += " Bez otazek, bez slozitych vet. Klidny, jisty hlas."
        return base


logger.info("✅ Rhythm Return Math loaded — constants, predictions, φ-desync")
