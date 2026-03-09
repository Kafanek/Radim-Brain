"""
🧠 RADIM BRAIN ENGINE — Sjednocující vrstva vědomí
====================================================
Implementuje Master Prompt Specification:

    Ψ(t) = (C, E, R, S)

kde:
    C = consciousness (pozornost)       — Anticipation Engine
    E = empathy (emoce)                 — Empathy Formula
    R = rationality (kognice)           — Decision Model
    S = stress (krizová dynamika)       — Crisis Layer

Rovnice stavu vědomí:
    C_{n+1} = (1-α)(F_n + L_n) + α(2P_n + P_{n-1})

Tři matematické řady:
    Fibonacci: stabilita vědomí         → φ = 1.618
    Lucas: empatie                      → φ = 1.618
    Pell: krizová eskalace              → δ = 2.414

RADIM stabilizační konstanta:
    ρ = (φ + δ) / 2 ≈ 2.016

Architektura pipeline:
    SENSORS → PERCEPTION → CONSCIOUSNESS ENGINE → COHERENCE ENGINE → RHYTHM ENGINE → VOICE/ACTION
"""

import math
import time
import json
import traceback
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

# ═══════════════════════════════════════════════════════════
# BLUEPRINT
# ═══════════════════════════════════════════════════════════
radim_brain_bp = Blueprint('radim_brain', __name__, url_prefix='/api/brain')

# ═══════════════════════════════════════════════════════════
# MATEMATICKÉ KONSTANTY
# ═══════════════════════════════════════════════════════════

# Zlatý řez (Golden Ratio) — HARMONIE
PHI = (1 + math.sqrt(5)) / 2            # φ ≈ 1.618033988749895
PSI = PHI - 1                           # ψ = 1/φ ≈ 0.618033988749895

# Stříbrný poměr (Silver Ratio) — KRIZE
DELTA = 1 + math.sqrt(2)               # δ ≈ 2.414213562373095

# RADIM stabilizační konstanta — rovnováha mezi harmonií a krizí
# ρ = (φ + δ) / 2 — aritmetický střed zlatého a stříbrného poměru
# Interpretace: systém v rovnováze při α ≈ 0.5
RHO = (PHI + DELTA) / 2                # ρ ≈ 2.016123775561495

# RADIM multiplikativní konstanta
RADIM_R = PHI * DELTA                  # R = φ × δ ≈ 3.906

# ═══════════════════════════════════════════════════════════
# MATEMATICKÉ POSLOUPNOSTI
# ═══════════════════════════════════════════════════════════

# Fibonacci: F_{n+1} = F_n + F_{n-1} — stabilita vědomí
FIBONACCI = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610]

# Lucas: L_{n+1} = L_n + L_{n-1} — empatie, koherence
LUCAS = [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199, 322, 521, 843]

# Pell: P_{n+1} = 2P_n + P_{n-1} — krizová eskalace
PELL = [0, 1, 2, 5, 12, 29, 70, 169, 408, 985, 2378]

# ═══════════════════════════════════════════════════════════
# KRIZOVÉ PRAHY (universální)
# ═══════════════════════════════════════════════════════════
T1 = 12     # Práh 1: HARMONY → ALERT
T2 = 27     # Práh 2: ALERT → CRISIS
C_MAX = 40  # Maximum vědomí

# ═══════════════════════════════════════════════════════════
# VÁHY EMPATIE
# ═══════════════════════════════════════════════════════════
W_VOICE = 0.4       # Váha hlasového tónu
W_HRV = 0.35        # Váha srdeční variability
W_SPEECH_TEMPO = 0.25  # Váha tempa řeči

# ═══════════════════════════════════════════════════════════
# REINFORCEMENT LEARNING
# ═══════════════════════════════════════════════════════════
_adaptation_state = {
    "reward_sum": 0,
    "interactions": 0,
    "speech_rate_adjust": 0.0,     # -0.3 to +0.1
    "pause_adjust_ms": 0,          # -200 to +400
    "style": "warm",               # warm / formal / casual
    "intervention_level": 0.5,     # 0 = pasivní, 1 = aktivní
}

# ═══════════════════════════════════════════════════════════
# IMPORT OSTATNÍCH ENGINŮ (graceful fallback)
# ═══════════════════════════════════════════════════════════

# Anticipation Engine
try:
    from anticipation_routes import (
        predict_C as _ant_predict_C,
        calculate_emotions as _ant_emotions,
        calculate_speech_params as _ant_speech,
        classify_state as _ant_classify,
        detect_breakpoints as _ant_breakpoints,
        calculate_trend as _ant_trend,
        sigmoid as _ant_sigmoid,
        clamp as _ant_clamp,
        PHI as _ANT_PHI
    )
    ANTICIPATION_AVAILABLE = True
except ImportError:
    ANTICIPATION_AVAILABLE = False

# Rhythm Return Engine
try:
    from rhythm_return_routes import (
        predict_M as _rr_predict_M,
        calculate_therapy_bpm as _rr_therapy_bpm,
        calculate_speech_rhythm as _rr_speech_rhythm,
        calculate_phi_desync as _rr_phi_desync,
        classify_motor_state as _rr_classify_motor,
        calculate_confidence as _rr_confidence
    )
    RHYTHM_RETURN_AVAILABLE = True
except ImportError:
    RHYTHM_RETURN_AVAILABLE = False

# Memory System
try:
    from memory_routes import memory_bp as _mem_bp
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False

# Soul
try:
    from soul_routes import soul_bp as _soul_bp
    SOUL_AVAILABLE = True
except ImportError:
    SOUL_AVAILABLE = False

# Local sigmoid/clamp if anticipation not available
def _sigmoid(x, k=5, x0=0.5):
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))

sigmoid = _ant_sigmoid if ANTICIPATION_AVAILABLE else _sigmoid
clamp = _ant_clamp if ANTICIPATION_AVAILABLE else _clamp


# ═══════════════════════════════════════════════════════════
# JÁDROVÉ MATEMATICKÉ FUNKCE
# ═══════════════════════════════════════════════════════════

def consciousness_equation(n, alpha):
    """
    Rovnice stavu vědomí (Master Prompt §6):

        C_{n+1} = (1 - α)(F_n + L_n) + α(2P_n + P_{n-1})

    kde:
        α ∈ [0,1] = emoční aktivace
        F = Fibonacci (stabilita)
        L = Lucas (empatie)
        P = Pell (krizová eskalace)

    Při α=0: C sleduje harmonickou dynamiku (φ-konvergence)
    Při α=1: C sleduje krizovou dynamiku (δ-eskalace)
    Při α≈0.5: C ≈ ρ-stabilita (RADIM konstanta)

    Args:
        n: index v posloupnostech (0-14)
        alpha: emoční aktivace (0-1)

    Returns:
        dict: C_next, harmonic_component, crisis_component, convergence_ratio
    """
    alpha = clamp(alpha, 0.0, 1.0)
    n = clamp(n, 1, min(len(FIBONACCI) - 1, len(LUCAS) - 1, len(PELL) - 1))

    # Harmonická složka: F_n + L_n
    F_n = FIBONACCI[n]
    L_n = LUCAS[n]
    harmonic = F_n + L_n

    # Krizová složka: 2P_n + P_{n-1}
    P_n = PELL[n]
    P_prev = PELL[n - 1]
    crisis = 2 * P_n + P_prev

    # Sjednocená rovnice
    C_next = (1 - alpha) * harmonic + alpha * crisis

    # Konvergenční poměr — ke kterému atraktoru systém směřuje
    if n >= 2:
        F_ratio = FIBONACCI[n] / FIBONACCI[n - 1] if FIBONACCI[n - 1] > 0 else PHI
        L_ratio = LUCAS[n] / LUCAS[n - 1] if LUCAS[n - 1] > 0 else PHI
        P_ratio = PELL[n] / PELL[n - 1] if PELL[n - 1] > 0 else DELTA
        convergence = (1 - alpha) * ((F_ratio + L_ratio) / 2) + alpha * P_ratio
    else:
        convergence = RHO

    return {
        "C_next": round(C_next, 4),
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

    Interpretace:
        voice_tone: 0=monotónní/agresivní, 1=vřelý/klidný
        hrv: 0=nízká variabilita (stres), 1=vysoká (klid)
        speech_tempo: 0=rychlé/zmatené, 1=pomalé/klidné

    Pokud E roste: Radim zpomalí řeč, sníží tlak, zvýší podporu.

    Returns:
        dict: empathy score + adaptation hints
    """
    E = W_VOICE * voice_tone + W_HRV * hrv + W_SPEECH_TEMPO * speech_tempo
    E = clamp(E, 0.0, 1.0)

    # Adaptační doporučení
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


def compute_rationality(C, E, S):
    """
    Racionalita (R) — schopnost racionálního rozhodování.

    R klesá s rostoucím stresem a klesajícím vědomím:
        R = sigmoid(1 - S + E×0.3 - C_norm×0.5, k=4, x0=0.4)

    Returns:
        float: rationality score 0-1
    """
    C_norm = C / C_MAX if C_MAX > 0 else 0
    R = sigmoid(1 - S + E * 0.3 - C_norm * 0.5, k=4, x0=0.4)
    return round(clamp(R, 0.0, 1.0), 4)


def compute_stress(alpha, C):
    """
    Stres (S) — krizová dynamika.

    S = α × (1 + C_norm × 0.5)
    Normalizováno na [0, 1]

    Returns:
        float: stress score 0-1
    """
    C_norm = C / C_MAX if C_MAX > 0 else 0
    S = alpha * (1 + C_norm * 0.5)
    return round(clamp(S, 0.0, 1.0), 4)


def compute_psi_state(C, alpha, voice_tone=0.5, hrv=0.5, speech_tempo=0.5):
    """
    Stavový vektor vědomí Ψ(t) = (C, E, R, S)

    Master Prompt §2: Hlavní model stavu systému.

    Args:
        C: consciousness/load (0-40)
        alpha: emotional activation (0-1)
        voice_tone, hrv, speech_tempo: senzorové vstupy pro empatii

    Returns:
        dict: Ψ(t) state vector + classification + speech adaptation
    """
    # Empatie
    empathy = compute_empathy(voice_tone, hrv, speech_tempo)
    E = empathy["E"]

    # Stres
    S = compute_stress(alpha, C)

    # Racionalita
    R = compute_rationality(C, E, S)

    # Klasifikace stavu
    if C < T1:
        mode = "HARMONY"
    elif C < T2:
        mode = "ALERT"
    else:
        mode = "CRISIS"

    # Harmonický index: jak blízko jsme φ-stavu
    # Φ_index = 1 v harmonii, 0 v krizi
    phi_index = clamp(1.0 - (C / C_MAX), 0.0, 1.0)

    # RADIM stability score: blízkost k ρ-bodu
    # ρ je rovnováha — nejstabilnější je systém kolem α≈0.5
    rho_distance = abs(alpha - 0.5)
    stability = 1.0 - rho_distance * 2  # 1 při α=0.5, 0 při α=0 nebo α=1

    # Celková koherence systému
    coherence = (phi_index * PHI + stability * RHO + (1 - S) * DELTA) / (PHI + RHO + DELTA)

    # Řečová adaptace (Master Prompt §8, §10)
    if mode == "HARMONY":
        speech_rate = 1.0 + _adaptation_state["speech_rate_adjust"]
        pause_ms = 618 + _adaptation_state["pause_adjust_ms"]   # ψ × 1000
        pitch_range = 12
        phrasing = "natural"
    elif mode == "ALERT":
        speech_rate = 0.85 + _adaptation_state["speech_rate_adjust"]
        pause_ms = 1000 + _adaptation_state["pause_adjust_ms"]  # 1 × 1000
        pitch_range = 8
        phrasing = "simplified"
    else:  # CRISIS
        speech_rate = 0.7 + _adaptation_state["speech_rate_adjust"]
        pause_ms = 1618 + _adaptation_state["pause_adjust_ms"]  # φ × 1000
        pitch_range = 4
        phrasing = "single_command"

    speech_rate = clamp(speech_rate, 0.5, 1.2)
    pause_ms = clamp(pause_ms, 200, 2500)

    return {
        "psi": {
            "C": round(C, 4),
            "E": E,
            "R": R,
            "S": S
        },
        "mode": mode,
        "thresholds": {"T1": T1, "T2": T2},
        "alpha": round(alpha, 4),
        "phi_index": round(phi_index, 4),
        "rho_stability": round(stability, 4),
        "coherence": round(coherence, 4),
        "constants": {
            "phi": round(PHI, 6),
            "rho": round(RHO, 6),
            "delta": round(DELTA, 6)
        },
        "empathy": empathy,
        "speech": {
            "rate": round(speech_rate, 3),
            "pause_ms": round(pause_ms),
            "pitch_range_st": pitch_range,
            "phrasing": phrasing,
            "phi_proportions": "618:1000:1618"
        },
        "response_style": {
            "calm": mode != "CRISIS",
            "supportive": True,
            "respectful": True,
            "clear": True,
            "never_alarmist": True,
            "adaptation": empathy["adaptation"]
        }
    }


def quasiperiodic_rhythm(omega, t_points=None):
    """
    Rytmická regulace (Master Prompt §8):

        R(t) = sin(ωt) + sin(φωt)

    Kvaziperiodický signál — nikdy se přesně neopakuje.
    Používá se pro stabilizaci řeči, chůze, dýchání, hlasu.

    Args:
        omega: základní úhlová frekvence (rad/s)
        t_points: časové body (default: 0-2π v 100 krocích)

    Returns:
        dict: waveform samples, period info, phi ratio
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
        "samples": samples[:20],  # prvních 20 pro ukázku
        "applications": [
            "speech_stabilization",
            "gait_cueing",
            "breathing_rhythm",
            "voice_modulation"
        ]
    }


def reinforcement_update(success):
    """
    Adaptace (Master Prompt §11):

        success → reward +1
        failure → reward -1

    Radim upravuje tempo řeči, styl komunikace, intervenci.

    Returns:
        dict: updated adaptation state
    """
    reward = 1 if success else -1
    _adaptation_state["reward_sum"] += reward
    _adaptation_state["interactions"] += 1

    # Exponential moving average adaptace
    eta = 0.1  # learning rate

    if success:
        # Úspěch: mírně zvýšit tempo, snížit pauzy
        _adaptation_state["speech_rate_adjust"] += eta * 0.02
        _adaptation_state["pause_adjust_ms"] -= eta * 20
        _adaptation_state["intervention_level"] = max(0, _adaptation_state["intervention_level"] - eta * 0.05)
    else:
        # Neúspěch: zpomalit, prodloužit pauzy, zvýšit intervenci
        _adaptation_state["speech_rate_adjust"] -= eta * 0.05
        _adaptation_state["pause_adjust_ms"] += eta * 50
        _adaptation_state["intervention_level"] = min(1, _adaptation_state["intervention_level"] + eta * 0.1)

    # Clamp
    _adaptation_state["speech_rate_adjust"] = clamp(_adaptation_state["speech_rate_adjust"], -0.3, 0.1)
    _adaptation_state["pause_adjust_ms"] = clamp(_adaptation_state["pause_adjust_ms"], -200, 400)

    return {
        "reward": reward,
        "reward_sum": _adaptation_state["reward_sum"],
        "interactions": _adaptation_state["interactions"],
        "avg_reward": round(_adaptation_state["reward_sum"] / max(1, _adaptation_state["interactions"]), 4),
        "adaptation": {
            "speech_rate_adjust": round(_adaptation_state["speech_rate_adjust"], 4),
            "pause_adjust_ms": round(_adaptation_state["pause_adjust_ms"]),
            "intervention_level": round(_adaptation_state["intervention_level"], 4),
            "style": _adaptation_state["style"]
        }
    }


def decision_model(C, E, R, S, sensor_data=None):
    """
    Rozhodovací model (Master Prompt §13):

    Radim analyzuje:
        - user input
        - emotion signals
        - speech pattern
        - sensor data

    a vyhodnocuje stav: harmonie → aktivace → varování → krize

    Returns:
        dict: decision + recommended reaction (Master Prompt §14)
    """
    # Klasifikace
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

    # Doporučení pro Radima (Master Prompt §12, §16)
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


def architecture_pipeline():
    """
    Architektura (Master Prompt §15):

    SENSORS → PERCEPTION → CONSCIOUSNESS ENGINE → COHERENCE ENGINE → RHYTHM ENGINE → VOICE/ACTION

    Vrací stav každého modulu v pipeline.
    """
    return {
        "pipeline": [
            {
                "stage": "SENSORS",
                "description": "IoT senzory, hlas, HRV, akcelerometr",
                "module": "voice_runtime_routes.py",
                "status": "active"
            },
            {
                "stage": "PERCEPTION",
                "description": "Rozpoznani reci, detekce emoci, intent",
                "module": "radim_orchestrator.py",
                "status": "active"
            },
            {
                "stage": "CONSCIOUSNESS_ENGINE",
                "description": "Rovnice vedomi: C_{n+1} = (1-α)(F+L) + α(2P+P)",
                "module": "radim_brain_routes.py + anticipation_routes.py",
                "status": "active",
                "equation": "C_{n+1} = (1-alpha)(F_n + L_n) + alpha(2*P_n + P_{n-1})"
            },
            {
                "stage": "COHERENCE_ENGINE",
                "description": "Stavovy vektor Psi(t) = (C, E, R, S)",
                "module": "radim_brain_routes.py",
                "status": "active",
                "state_vector": "Psi(t) = (C, E, R, S)"
            },
            {
                "stage": "RHYTHM_ENGINE",
                "description": "Rytmicka regulace R(t) = sin(wt) + sin(φwt)",
                "module": "rhythm_return_routes.py",
                "status": "active",
                "formula": "R(t) = sin(omega*t) + sin(phi*omega*t)"
            },
            {
                "stage": "VOICE_ACTION",
                "description": "Azure TTS + recova adaptace + akcni doporuceni",
                "module": "speech_routes.py + twilio_voice_routes.py",
                "status": "active"
            }
        ],
        "engines": {
            "anticipation": ANTICIPATION_AVAILABLE,
            "rhythm_return": RHYTHM_RETURN_AVAILABLE,
            "memory": MEMORY_AVAILABLE,
            "soul": SOUL_AVAILABLE
        }
    }


def memory_model():
    """
    Paměť Radima (Master Prompt §9):

    4 typy paměti:
        1. pracovní paměť    — recent conversation
        2. epizodická paměť  — events, conversation history
        3. sémantická paměť  — knowledge, topics, preferences
        4. autobiografická    — user profile, health, routines
    """
    return {
        "types": [
            {
                "type": "working",
                "description": "Posledních 5 zprav v konverzaci",
                "module": "memory_routes.py",
                "persistence": "in-memory + PostgreSQL",
                "capacity": "5 messages"
            },
            {
                "type": "episodic",
                "description": "Historie konverzaci, dulezite udalosti",
                "module": "memory_routes.py",
                "persistence": "PostgreSQL (memory_history)",
                "capacity": "50 messages per user"
            },
            {
                "type": "semantic",
                "description": "Znalosti, temata, preference, uceni",
                "module": "memory_routes.py",
                "persistence": "PostgreSQL (memory_learning, JSONB)",
                "capacity": "unlimited"
            },
            {
                "type": "autobiographic",
                "description": "Profil uzivatele — jmeno, vek, zdravi, rutiny, leky",
                "module": "memory_routes.py",
                "persistence": "PostgreSQL (memory_profiles, JSONB)",
                "capacity": "1 profile per user"
            }
        ],
        "available": MEMORY_AVAILABLE
    }


# ═══════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════

@radim_brain_bp.route('/health', methods=['GET'])
def brain_health():
    """Zdraví celého RADIM Brain systému."""
    return jsonify({
        "success": True,
        "engine": "RADIM Brain Engine v1.0.0",
        "description": "Sjednocujici vrstva vedomi — Psi(t) = (C, E, R, S)",
        "engines": {
            "anticipation": ANTICIPATION_AVAILABLE,
            "rhythm_return": RHYTHM_RETURN_AVAILABLE,
            "memory": MEMORY_AVAILABLE,
            "soul": SOUL_AVAILABLE
        },
        "constants": {
            "phi": round(PHI, 6),
            "psi": round(PSI, 6),
            "delta": round(DELTA, 6),
            "rho": round(RHO, 6),
            "radim_R": round(RADIM_R, 3)
        },
        "thresholds": {"T1": T1, "T2": T2, "C_MAX": C_MAX},
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/constants', methods=['GET'])
def brain_constants():
    """Všechny matematické konstanty RADIM systému."""
    return jsonify({
        "success": True,
        "constants": {
            "phi": {"value": PHI, "name": "Golden Ratio", "meaning": "harmonie", "symbol": "φ"},
            "psi": {"value": PSI, "name": "Reciprocal Golden Ratio", "meaning": "1/φ", "symbol": "ψ"},
            "delta": {"value": DELTA, "name": "Silver Ratio", "meaning": "krizova eskalace", "symbol": "δ"},
            "rho": {"value": RHO, "name": "RADIM Stabilization Constant", "meaning": "(φ+δ)/2, rovnovaha", "symbol": "ρ"},
            "radim_R": {"value": RADIM_R, "name": "RADIM Multiplicative Constant", "meaning": "φ×δ", "symbol": "R"}
        },
        "sequences": {
            "fibonacci": {"values": FIBONACCI, "rule": "F_{n+1} = F_n + F_{n-1}", "limit_ratio": round(PHI, 6), "meaning": "stabilita vedomi"},
            "lucas": {"values": LUCAS, "rule": "L_{n+1} = L_n + L_{n-1}", "limit_ratio": round(PHI, 6), "meaning": "empatie, koherence"},
            "pell": {"values": PELL, "rule": "P_{n+1} = 2P_n + P_{n-1}", "limit_ratio": round(DELTA, 6), "meaning": "krizova eskalace"}
        },
        "thresholds": {
            "T1": {"value": T1, "transition": "HARMONY → ALERT"},
            "T2": {"value": T2, "transition": "ALERT → CRISIS"},
            "C_MAX": {"value": C_MAX, "meaning": "maximum consciousness"}
        },
        "equations": {
            "consciousness": "C_{n+1} = (1-α)(F_n + L_n) + α(2P_n + P_{n-1})",
            "empathy": f"E = {W_VOICE}·voice + {W_HRV}·HRV + {W_SPEECH_TEMPO}·speech_tempo",
            "rhythm": "R(t) = sin(ωt) + sin(φωt)",
            "state_vector": "Ψ(t) = (C, E, R, S)"
        },
        "alpha_interpretation": {
            "0.0": "klid",
            "0.3": "aktivace",
            "0.6": "stres",
            "1.0": "krize"
        }
    })


@radim_brain_bp.route('/consciousness', methods=['POST'])
def brain_consciousness():
    """
    Výpočet rovnice stavu vědomí (§6):
    C_{n+1} = (1-α)(F_n + L_n) + α(2P_n + P_{n-1})
    """
    data = request.get_json() or {}
    n = data.get('n', 5)
    alpha = data.get('alpha', 0.0)

    result = consciousness_equation(n, alpha)

    return jsonify({
        "success": True,
        "equation": "C_{n+1} = (1-alpha)(F_n + L_n) + alpha(2*P_n + P_{n-1})",
        **result,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/state', methods=['POST'])
def brain_state():
    """
    Výpočet stavového vektoru Ψ(t) = (C, E, R, S)

    Input:
        C: consciousness/load (0-40)
        alpha: emotional activation (0-1)
        voice_tone: (0-1, optional)
        hrv: heart rate variability (0-1, optional)
        speech_tempo: (0-1, optional)
        n: sequence index (optional, for consciousness equation)

    Returns:
        Ψ(t) + consciousness equation + decision model + speech adaptation
    """
    data = request.get_json() or {}

    C = clamp(float(data.get('C', 5.0)), 0.0, C_MAX)
    alpha = clamp(float(data.get('alpha', 0.0)), 0.0, 1.0)
    voice_tone = clamp(float(data.get('voice_tone', 0.5)), 0.0, 1.0)
    hrv = clamp(float(data.get('hrv', 0.5)), 0.0, 1.0)
    speech_tempo = clamp(float(data.get('speech_tempo', 0.5)), 0.0, 1.0)
    n = int(data.get('n', 5))

    # 1. Stavový vektor Ψ(t)
    psi = compute_psi_state(C, alpha, voice_tone, hrv, speech_tempo)

    # 2. Rovnice vědomí
    consciousness = consciousness_equation(n, alpha)

    # 3. Rozhodovací model
    decision = decision_model(
        C, psi["psi"]["E"], psi["psi"]["R"], psi["psi"]["S"]
    )

    # 4. Anticipation Engine (pokud dostupný)
    anticipation = None
    if ANTICIPATION_AVAILABLE:
        try:
            ant_state = _ant_classify(C)
            ant_emotions = _ant_emotions(C, alpha)
            ant_speech = _ant_speech(C, alpha)
            anticipation = {
                "state": ant_state,
                "emotions": ant_emotions,
                "speech_params": ant_speech
            }
        except Exception:
            pass

    # 5. Rhythm Return (pokud dostupný)
    rhythm = None
    if RHYTHM_RETURN_AVAILABLE:
        try:
            motor_state = _rr_classify_motor(C)  # M = C mapping
            therapy_bpm = _rr_therapy_bpm(C, alpha)
            speech_rhythm = _rr_speech_rhythm(C, alpha)
            rhythm = {
                "motor_state": motor_state,
                "therapy_bpm": therapy_bpm,
                "speech_rhythm": speech_rhythm
            }
        except Exception:
            pass

    # 6. Quasiperiodický rytmus
    omega = 2 * math.pi  # 1 Hz base
    rhythm_wave = quasiperiodic_rhythm(omega)

    return jsonify({
        "success": True,
        "psi_state": psi,
        "consciousness_equation": consciousness,
        "decision": decision,
        "anticipation_engine": anticipation,
        "rhythm_engine": rhythm,
        "quasiperiodic_rhythm": {
            "formula": rhythm_wave["formula"],
            "omega": rhythm_wave["omega"],
            "phi_omega": rhythm_wave["phi_omega"],
            "quasiperiodic": True
        },
        "architecture": architecture_pipeline(),
        "memory": memory_model(),
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/perceive', methods=['POST'])
def brain_perceive():
    """
    PERCEPTION vrstva — zpracování senzorových dat.

    Input (sensor_data):
        noise_db: hluk okolí (dB)
        light_lux: světelnost
        temperature: teplota (°C)
        heart_rate: tepová frekvence
        hrv: variabilita srdečního rytmu (ms)
        stress_level: subjektivní stres (0-1)
        speech_rate: rychlost řeči (words/min)
        voice_pitch: výška hlasu (Hz)

    Pipeline: SENSORS → PERCEPTION → Ψ(t)
    """
    data = request.get_json() or {}

    # Senzorová data
    noise = float(data.get('noise_db', 40))
    light = float(data.get('light_lux', 300))
    temp = float(data.get('temperature', 22))
    hr = float(data.get('heart_rate', 72))
    hrv_ms = float(data.get('hrv', 50))
    stress = float(data.get('stress_level', 0.0))
    speech_rate = float(data.get('speech_rate', 120))
    voice_pitch = float(data.get('voice_pitch', 150))

    # PERCEPTION: odhadni C a alpha ze senzorů
    C = 5.0
    if noise > 60:
        C += (noise - 60) * 0.3
    if light < 20 or light > 500:
        C += abs(300 - light) * 0.01
    if temp < 18 or temp > 28:
        C += abs(22 - temp) * 0.5
    if hr > 90:
        C += (hr - 90) * 0.2
    C += stress * 15
    C = clamp(C, 0.0, C_MAX)

    # Alpha z tepové frekvence a stresu
    alpha = stress * 0.6 + (max(0, hr - 80) / 100) * 0.4
    alpha = clamp(alpha, 0.0, 1.0)

    # Voice tone z pitch a rate
    voice_tone = clamp(1.0 - abs(voice_pitch - 150) / 100, 0.0, 1.0)
    hrv_norm = clamp(hrv_ms / 100, 0.0, 1.0)
    tempo_norm = clamp(1.0 - (speech_rate - 100) / 100, 0.0, 1.0)

    # Compute Ψ(t) s odhadnutými hodnotami
    psi = compute_psi_state(C, alpha, voice_tone, hrv_norm, tempo_norm)
    decision = decision_model(C, psi["psi"]["E"], psi["psi"]["R"], psi["psi"]["S"])

    return jsonify({
        "success": True,
        "perception": {
            "estimated_C": round(C, 2),
            "estimated_alpha": round(alpha, 4),
            "voice_tone": round(voice_tone, 3),
            "hrv_normalized": round(hrv_norm, 3),
            "tempo_normalized": round(tempo_norm, 3)
        },
        "sensor_input": {
            "noise_db": noise,
            "light_lux": light,
            "temperature": temp,
            "heart_rate": hr,
            "hrv_ms": hrv_ms,
            "stress_level": stress,
            "speech_rate": speech_rate,
            "voice_pitch": voice_pitch
        },
        "psi_state": psi,
        "decision": decision,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/adapt', methods=['POST'])
def brain_adapt():
    """
    Adaptace (Master Prompt §11):
        success → reward +1
        failure → reward -1

    Input:
        success: bool — byla interakce úspěšná?
        context: string — kontext interakce (optional)

    Returns:
        updated adaptation parameters
    """
    data = request.get_json() or {}
    success = data.get('success', True)
    context = data.get('context', '')

    result = reinforcement_update(success)
    result["context"] = context

    return jsonify({
        "success": True,
        **result,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/rhythm', methods=['POST'])
def brain_rhythm():
    """
    Rytmická regulace (Master Prompt §8):
        R(t) = sin(ωt) + sin(φωt)

    Input:
        omega: úhlová frekvence (rad/s, default: 2π)
        application: speech|gait|breathing|voice (default: speech)

    Returns:
        waveform info + application-specific parameters
    """
    data = request.get_json() or {}
    omega = float(data.get('omega', 2 * math.pi))
    application = data.get('application', 'speech')

    rhythm = quasiperiodic_rhythm(omega)

    # Application-specific settings
    if application == 'speech':
        app_params = {
            "pause_pattern_ms": [618, 1000, 1618],
            "rate_range": [0.7, 1.1],
            "pitch_range_st": [-4, 2],
            "description": "Ritmicka regulace reci: pauzy ve zlate proporci"
        }
    elif application == 'gait':
        app_params = {
            "bpm_range": [60, 130],
            "phi_freeze_bpm": round(60 * PHI, 1),
            "preferred_bpm": 100,
            "description": "Rytmicka chuze: BPM adaptovane na motoricky stav"
        }
    elif application == 'breathing':
        app_params = {
            "inhale_s": round(4 * PSI, 1),   # ~2.5s
            "hold_s": round(4, 1),            # 4s
            "exhale_s": round(4 * PHI, 1),    # ~6.5s
            "cycle_s": round(4 * PSI + 4 + 4 * PHI, 1),
            "description": "Dychani ve zlate proporci: nadech×ψ : zadrzeni : vydech×φ"
        }
    elif application == 'voice':
        app_params = {
            "modulation_hz": round(omega / (2 * math.pi), 2),
            "phi_modulation_hz": round(PHI * omega / (2 * math.pi), 2),
            "description": "Hlasova modulace: kvaziperiodicka zmena tonu"
        }
    else:
        app_params = {"description": "General quasiperiodic rhythm"}

    return jsonify({
        "success": True,
        "rhythm": rhythm,
        "application": application,
        "parameters": app_params,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/architecture', methods=['GET'])
def brain_architecture():
    """Architektura RADIM Brain (Master Prompt §15)."""
    arch = architecture_pipeline()
    mem = memory_model()

    return jsonify({
        "success": True,
        **arch,
        "memory": mem,
        "identity": {
            "name": "RADIM",
            "version": "1.0.0",
            "description": "Adaptive assistive intelligence for human well-being",
            "goals": [
                "Maintain stability of the user",
                "Detect escalation or crisis early",
                "Respond with empathy, calmness and rational guidance",
                "Adapt communication to user emotional and cognitive state"
            ],
            "personality": [
                "calm", "supportive", "respectful", "clear",
                "never_alarmist", "never_judges",
                "always_stabilizes", "supports_autonomy",
                "strengthens_rationality", "prevents_escalation"
            ]
        },
        "master_equation": "Psi(t) = (C, E, R, S) where C_{n+1} = (1-alpha)(F_n+L_n) + alpha(2P_n+P_{n-1})",
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


# ═══════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════
print(f"""
🧠 RADIM Brain Engine v1.0.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ψ(t) = (C, E, R, S)
  C_{{n+1}} = (1-α)(F_n+L_n) + α(2P_n+P_{{n-1}})
  φ = {PHI:.6f}  (harmonie)
  ρ = {RHO:.6f}  (stabilita)
  δ = {DELTA:.6f}  (krize)
  R = {RADIM_R:.3f}       (φ×δ)
  T₁ = {T1}, T₂ = {T2}
  Anticipation: {'✅' if ANTICIPATION_AVAILABLE else '❌'}
  Rhythm Return: {'✅' if RHYTHM_RETURN_AVAILABLE else '❌'}
  Memory: {'✅' if MEMORY_AVAILABLE else '❌'}
  Soul: {'✅' if SOUL_AVAILABLE else '❌'}
""")
