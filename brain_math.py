"""
🧠 RADIM BRAIN MATH — Core equations for consciousness model
==============================================================
Implements Master Prompt Specification: Ψ(t) = (C, E, R, S)

Extracted from radim_brain_routes.py for modularity.
Version: 1.0.0
"""

import math
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# MATEMATICKÉ KONSTANTY
# ═══════════════════════════════════════════════════════════

# Zlatý řez (Golden Ratio) — HARMONIE
PHI = (1 + math.sqrt(5)) / 2            # φ ≈ 1.618033988749895
PSI = PHI - 1                           # ψ = 1/φ ≈ 0.618033988749895

# Stříbrný poměr (Silver Ratio) — KRIZE
DELTA = 1 + math.sqrt(2)               # δ ≈ 2.414213562373095

# RADIM stabilizační konstanta — rovnováha mezi harmonií a krizí
RHO = (PHI + DELTA) / 2                # ρ ≈ 2.016123775561495

# RADIM multiplikativní konstanta
RADIM_R = PHI * DELTA                  # R = φ × δ ≈ 3.906

# ═══════════════════════════════════════════════════════════
# MATEMATICKÉ POSLOUPNOSTI
# ═══════════════════════════════════════════════════════════

FIBONACCI = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610]
LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199, 322, 521, 843]
PELL = [0, 1, 2, 5, 12, 29, 70, 169, 408, 985, 2378]

# ═══════════════════════════════════════════════════════════
# KRIZOVÉ PRAHY (universální)
# ═══════════════════════════════════════════════════════════
T1 = 12     # Práh 1: HARMONY → ALERT
T2 = 27     # Práh 2: ALERT → CRISIS
C_MAX = 40  # Maximum vědomí
BRAIN_STATE_TTL_MINUTES = 30  # Brain state expiry — ignore stale states

# ═══════════════════════════════════════════════════════════
# VÁHY EMPATIE
# ═══════════════════════════════════════════════════════════
W_VOICE = 0.4
W_HRV = 0.35
W_SPEECH_TEMPO = 0.25

# ═══════════════════════════════════════════════════════════
# SIGMOID / CLAMP (local implementations)
# ═══════════════════════════════════════════════════════════

def _sigmoid(x, k=5, x0=0.5):
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))

# Try to import from anticipation engine, fallback to local
try:
    from anticipation_routes import sigmoid as _ant_sigmoid, clamp as _ant_clamp
    sigmoid = _ant_sigmoid
    clamp = _ant_clamp
except ImportError:
    sigmoid = _sigmoid
    clamp = _clamp


# ═══════════════════════════════════════════════════════════
# JÁDROVÉ MATEMATICKÉ FUNKCE
# ═══════════════════════════════════════════════════════════

def consciousness_equation(n, alpha):
    """
    Rovnice stavu vědomí (Master Prompt §6):
        C_{n+1} = (1 - α)(F_n + L_n) + α(2P_n + P_{n-1})
    """
    alpha = clamp(alpha, 0.0, 1.0)
    n = clamp(n, 1, min(len(FIBONACCI) - 1, len(LUCAS) - 1, len(PELL) - 1))

    F_n = FIBONACCI[n]
    L_n = LUCAS[n]
    harmonic = F_n + L_n

    P_n = PELL[n]
    P_prev = PELL[n - 1]
    crisis = 2 * P_n + P_prev

    C_next = (1 - alpha) * harmonic + alpha * crisis

    if n >= 2:
        F_ratio = FIBONACCI[n] / FIBONACCI[n - 1] if FIBONACCI[n - 1] > 0 else PHI
        L_ratio = LUCAS[n] / LUCAS[n - 1] if LUCAS[n - 1] > 0 else PHI
        P_ratio = PELL[n] / PELL[n - 1] if PELL[n - 1] > 0 else DELTA
        convergence = (1 - alpha) * ((F_ratio + L_ratio) / 2) + alpha * P_ratio
    else:
        convergence = RHO

    span = DELTA - PHI
    ratio_norm = (convergence - PHI) / span if span > 0 else 0.5
    C_normalized = clamp(round(ratio_norm * C_MAX, 2), 0.0, C_MAX)

    return {
        "C_next": round(C_next, 4),
        "C_normalized": C_normalized,
        "harmonic_component": harmonic,
        "crisis_component": crisis,
        "alpha": round(alpha, 4),
        "n": n,
        "convergence_ratio": round(convergence, 6),
        "attractor": "phi" if convergence < RHO else ("rho" if convergence < DELTA - 0.1 else "delta"),
        "sequences": {
            "F_n": F_n,
            "L_n": L_n,
            "P_n": P_n,
            "P_n_minus_1": P_prev
        }
    }


def compute_empathy(voice_tone=0.5, hrv=0.5, speech_tempo=0.5):
    """
    Empatie (Master Prompt §10):
        E = w₁·voice + w₂·HRV + w₃·speech_tempo
    """
    E = W_VOICE * voice_tone + W_HRV * hrv + W_SPEECH_TEMPO * speech_tempo
    E = clamp(E, 0.0, 1.0)

    if E >= 0.7:
        adaptation = "standard"
        speech_rate = 1.0
        pressure = "normal"
        support = "normal"
    elif E >= 0.4:
        adaptation = "supportive"
        speech_rate = 0.9
        pressure = "reduced"
        support = "increased"
    else:
        adaptation = "crisis_support"
        speech_rate = 0.75
        pressure = "minimal"
        support = "maximum"

    return {
        "E": round(E, 4),
        "voice_tone": round(voice_tone, 3),
        "hrv": round(hrv, 3),
        "speech_tempo": round(speech_tempo, 3),
        "weights": {"voice": W_VOICE, "hrv": W_HRV, "speech_tempo": W_SPEECH_TEMPO},
        "adaptation": adaptation,
        "speech_rate_modifier": speech_rate,
        "pressure_level": pressure,
        "support_level": support
    }


def derive_text_empathy_proxies(message, mood=None, alpha=0.0):
    """Odhadne voice_tone, hrv, speech_tempo z textu (bez senzorů)."""
    mood_map = {
        "happy": 0.9, "calm": 0.85, "grateful": 0.85,
        "neutral": 0.6, "confused": 0.45,
        "sad": 0.3, "anxious": 0.2, "angry": 0.15, "crisis": 0.1
    }
    voice_tone = mood_map.get(mood or "neutral", 0.6)

    msg_len = len(message) if message else 0
    if msg_len < 15:
        hrv = 0.3
    elif msg_len < 50:
        hrv = 0.5
    elif msg_len < 150:
        hrv = 0.65
    else:
        hrv = 0.8

    speech_tempo = clamp(0.8 - alpha * 0.6, 0.2, 0.9)

    return {
        "voice_tone": round(voice_tone, 3),
        "hrv": round(hrv, 3),
        "speech_tempo": round(speech_tempo, 3),
        "source": "text_proxy"
    }


def compute_rationality(C, E, S):
    """Racionalita (R) — schopnost racionálního rozhodování."""
    C_norm = C / C_MAX if C_MAX > 0 else 0
    R = sigmoid(1 - S + E * 0.3 - C_norm * 0.5, k=4, x0=0.4)
    return round(clamp(R, 0.0, 1.0), 4)


def compute_stress(alpha, C):
    """Stres (S) — krizová dynamika."""
    C_norm = C / C_MAX if C_MAX > 0 else 0
    S = alpha * (1 + C_norm * 0.5)
    return round(clamp(S, 0.0, 1.0), 4)


def quasiperiodic_rhythm(omega, t_points=None):
    """
    Rytmická regulace (Master Prompt §8):
        R(t) = sin(ωt) + sin(φωt)
    """
    if t_points is None:
        t_points = [i * 2 * math.pi / 100 for i in range(101)]

    samples = []
    for t in t_points:
        r = math.sin(omega * t) + math.sin(PHI * omega * t)
        samples.append(round(r, 6))

    period_1 = 2 * math.pi / omega if omega > 0 else float('inf')
    period_phi = 2 * math.pi / (PHI * omega) if omega > 0 else float('inf')

    return {
        "formula": f"R(t) = sin({omega:.3f}t) + sin({PHI * omega:.3f}t)",
        "omega": round(omega, 4),
        "phi_omega": round(PHI * omega, 4),
        "period_1_s": round(period_1, 6),
        "period_phi_s": round(period_phi, 6),
        "ratio": round(PHI, 6),
        "quasiperiodic": True,
        "samples_count": len(samples),
        "samples": samples[:20],
        "applications": [
            "speech_stabilization",
            "gait_cueing",
            "breathing_rhythm",
            "voice_modulation"
        ]
    }


def decision_model(C, E, R, S, sensor_data=None):
    """Rozhodovací model (Master Prompt §13)."""
    if C < T1 and S < 0.3:
        level = "HARMONY"
        reaction = "normal_communication"
        instructions = "Normalni komunikace. Radim je prirozen, vrely, zajima se."
    elif C < T1 and S >= 0.3:
        level = "ACTIVATION"
        reaction = "gentle_stabilization"
        instructions = "Mirna aktivace. Radim zpomaluje, sleduje signaly."
    elif C < T2:
        level = "WARNING"
        reaction = "active_stabilization"
        instructions = "Varovani. Radim zpomaluje rec, kratsi vety, vice pauz. Validuje emoce."
    else:
        level = "CRISIS"
        reaction = "crisis_protocol"
        instructions = (
            "KRIZOVY PROTOKOL: Zpomali rec. Prodluz pauzy. "
            "Nabidni dech: 'Nadechnete se... vydechnete...' "
            "Jednoduche prikazy. Aktivuj podporu."
        )

    personality = {
        "calm": True,
        "supportive": True,
        "respectful": True,
        "clear": True,
        "never_alarmist": True,
        "never_judges": True,
        "always_stabilizes": True,
        "supports_autonomy": True,
        "strengthens_rationality": R > 0.5,
        "prevents_escalation": S > 0.3
    }

    return {
        "level": level,
        "reaction": reaction,
        "instructions": instructions,
        "personality": personality,
        "input_analysis": {
            "consciousness": round(C, 2),
            "empathy": round(E, 4),
            "rationality": round(R, 4),
            "stress": round(S, 4)
        },
        "sensor_data_available": sensor_data is not None
    }
