"""
🎵 RHYTHM RETURN ENGINE — Návrat Rytmu pro Parkinsonovu chorobu
================================================================
Adaptivní rytmická terapie mapovaná na Anticipation Engine matematiku.

Matematický model:
- Motor Load: M (0-40), analogicky k C (consciousness)
- Tremor/Rigidity Index: τ (0-1), analogicky k α (stress)
- Stavy: FLOW (<12), STRUGGLE (12-27), FREEZE (>=27)

Klíčový princip:
  R_φ(t) = sin(ωt) + sin(φωt)  — kvaziperiodický rytmus
  Pokud ω₂/ω₁ = φ, synchronizace je matematicky nemožná (mode-locking).
  Tím rozbíjíme patologickou beta synchronizaci (13–30 Hz) v bazálních gangliích.

Bypass: Sluch → Mozeček → Thalamus → Motorická kůra (obchází poškozené bazální ganglie)

Version: 1.0.0
Author: Radim Brain Team
"""

import os
import json
import math
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify

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

# --- Database ---
try:
    from database import get_connection, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


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
# Každé pásmo = předchozí × φ, a f(n-1) + f(n) = f(n+1)
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

# Pauzy per stav (ms): ψ : 1 : φ proporce
PAUSE_FLOW_MS = int(1000 * PSI)     # 618 ms
PAUSE_STRUGGLE_MS = 1000            # 1000 ms
PAUSE_FREEZE_MS = int(1000 * PHI)   # 1618 ms

# Rate per stav
RATE_FLOW = 1.0
RATE_STRUGGLE = 0.85
RATE_FREEZE = 0.7

# Pitch range per stav (semitones)
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


def now_iso():
    """ISO timestamp"""
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'


# ============================================
# CORE MATHEMATICAL FUNCTIONS
# ============================================

def predict_M(M_current, trend_M, tau_current):
    """
    Predikce motorické zátěže: M̂_{t+1} = M_t + K1·T^M_t + K2·(τ_t - 0.5)

    Analogie k predict_C v Anticipation Engine:
    - Když τ > 0.5 (silný tremor/rigidita) → M roste
    - Když τ < 0.5 (klidný stav) → M klesá

    Args:
        M_current: aktuální motor load (0-40)
        trend_M: EMA trend motorické zátěže
        tau_current: aktuální tremor/rigidity index (0-1)

    Returns:
        float: predikované M, clamped [0, M_MAX]
    """
    predicted = M_current + K1_MOTOR * trend_M + K2_MOTOR * (tau_current - 0.5)
    return clamp(predicted, 0, M_MAX)


def predict_tau(tau_current, trend_tau):
    """
    Predikce tremoru: τ̂_{t+1} = τ_t + γ·T^τ_t

    Analogie k predict_alpha v Anticipation Engine.

    Args:
        tau_current: aktuální tremor/rigidity index (0-1)
        trend_tau: EMA trend tremoru

    Returns:
        float: predikované τ, clamped [0, 1]
    """
    predicted = tau_current + GAMMA_MOTOR * trend_tau
    return clamp(predicted, 0, 1)


def classify_motor_state(M):
    """
    Klasifikace motorického stavu (analogie k classify_state).

    FLOW     (M < 12):  Plynulý pohyb, stabilní chůze, normální řeč
    STRUGGLE (12 ≤ M < 27): Zpomalení, zmenšení kroků, tišší hlas
    FREEZE   (M ≥ 27):  Zamrznutí (FOG), blokáda pohybu

    Returns:
        str: "FLOW", "STRUGGLE", or "FREEZE"
    """
    if M < M_FLOW:
        return "FLOW"
    elif M < M_STRUGGLE:
        return "STRUGGLE"
    else:
        return "FREEZE"


def calculate_therapy_bpm(M_predicted, tau, preferred_bpm=BPM_PREFERRED):
    """
    Adaptivní terapeutický BPM odvozený z φ (zlatého řezu).

    FLOW:     preferred × 1.05   — tréninkové zvýšení (+5%)
    STRUGGLE: preferred × ψ      — golden ratio zpomalení (×0.618)
    FREEZE:   BPM_REST × φ ≈ 97  — anti-freeze φ-cueing

    Klinický základ:
    - RAS (Rhythmic Auditory Stimulation): efektivní rozsah 90-125% preferované kadence
    - Postupné zvyšování 5-10% týdně
    - Maximum 130 BPM

    Args:
        M_predicted: predikovaná motorická zátěž
        tau: tremor/rigidity index
        preferred_bpm: preferovaná kadence pacienta

    Returns:
        dict: {bpm, state, accent_pattern, beat_duration_ms, phi_ratio}
    """
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
    """
    Fibonacci akcentový vzor — přirozené důrazy odvozené z Fibonacci sekvence.

    FLOW:     [1,1,2,3,5] — plný Fibonacci, bohatý rytmus
    STRUGGLE: [1,1,2]     — zjednodušený, snáze sledovatelný
    FREEZE:   [1]         — jediný silný beat: "KROK!"

    Vzor se expanduje tak, že první beat každé skupiny je SILNÝ (1.0),
    ostatní jsou slabé (×ψ = ×0.618).

    Returns:
        list[dict]: [{position, intensity, is_accent}, ...]
    """
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
    """
    Řečový rytmus pro Parkinson — návrat prozodie.

    Parkinson zabíjí prozodii:
    - Monotónní hlas (snížená F0 variabilita)
    - Hypofonie (tichý hlas)
    - Zrychlená/nepravidelná řeč

    Náš model vrací řeč do φ-proporčního rytmu:
    - Pauzy: ψ : 1 : φ (618 : 1000 : 1618 ms)
    - Rate: plynulé zpomalení
    - Pitch range: progresivní zúžení

    Returns:
        dict: {pause_ms, rate, pitch_range_st, volume_modulation, phrasing}
    """
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
    """
    6D Confidence Vector — motivační profil pacienta.

    Analogie k calculate_emotions() v Anticipation Engine.
    Místo tension/fear/hope/calm/joy/sadness:
    flow / frustration / fatigue / motivation / focus / pride

    Všechny dimenze používají sigmoid() pro hladké přechody.

    Args:
        M: motor load (0-40)
        tau: tremor/rigidity index (0-1)
        session_progress: postup v session (0-1)

    Returns:
        dict: {flow, frustration, fatigue, motivation, focus, pride}
    """
    M_norm = M / M_MAX  # Normalizace na 0-1

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
    """
    Detekce stavových přechodů (analogie k detect_breakpoints).

    B_12 ↑: FLOW → STRUGGLE   — "Pohyb se zpomaluje"
    B_12 ↓: STRUGGLE → FLOW   — "Návrat do flow!"
    B_27 ↑: STRUGGLE → FREEZE — "FREEZE detekován — φ-cueing"
    B_27 ↓: FREEZE → STRUGGLE — "Fibonacci ramp: 55→89→97→100"

    Returns:
        list[dict]: breakpoints with type, direction, message, action
    """
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
    """
    φ-desynchronizace — rozbití patologické oscilace zlatým řezem.

    Princip: Pokud dva oscilátory vibrují ve frekvencích jejichž
    poměr je přesně φ, NIKDY se nemohou synchronizovat.
    Mode-locking je matematicky nemožný při iracionálním poměru φ.

    Formula:
      ω_stim = φ · ω_pathological
      R_φ(t) = sin(ω·t) + sin(φ·ω·t)   — kvaziperiodický signál

    Příklad: beta patologická = 20 Hz → ω_stim = 32.36 Hz (gamma pásmo)

    Args:
        omega_pathological_hz: patologická frekvence (Hz)

    Returns:
        dict: {omega_stim_hz, period_ms, desync_ratio, waveform_description}
    """
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
    """
    Instrukce pro AI orchestrátora (Radima) — jak mluvit k pacientovi.

    Returns:
        str: human-readable directives
    """
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


# ============================================
# DATABASE FUNCTIONS
# ============================================

def _db_save_session(session_id, user_id, preferred_bpm, hy_stage, notes):
    """Create new therapy session in DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_sessions (id, user_id, preferred_bpm, hy_stage, notes)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, user_id, preferred_bpm, hy_stage, notes)
        )
        db.commit()
        return True
    except Exception as e:
        print(f"⚠️ rhythm session save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_save_state(session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json):
    """Save rhythm state snapshot to DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_states
               (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_pattern, confidence)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json)
        )
        db.commit()
        return True
    except Exception as e:
        print(f"⚠️ rhythm state save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_save_breakpoint(session_id, bp_type, direction, M_before, M_after, action):
    """Save motor breakpoint event to DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_breakpoints (session_id, breakpoint_type, direction, M_before, M_after, action_taken)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, bp_type, direction, M_before, M_after, action)
        )
        db.commit()
        return True
    except Exception as e:
        print(f"⚠️ rhythm breakpoint save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_get_session(session_id):
    """Load session with full state history"""
    if not _DB_AVAILABLE:
        return None
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'

        session = db.execute(
            f'SELECT * FROM rhythm_sessions WHERE id = {ph}', (session_id,)
        ).fetchone()
        if not session:
            return None

        states = db.execute(
            f'SELECT * FROM rhythm_states WHERE session_id = {ph} ORDER BY timestamp ASC LIMIT 1000', (session_id,)
        ).fetchall()

        breakpoints = db.execute(
            f'SELECT * FROM rhythm_breakpoints WHERE session_id = {ph} ORDER BY timestamp ASC LIMIT 500', (session_id,)
        ).fetchall()

        return {
            "session": dict(session),
            "states": [dict(s) for s in states],
            "breakpoints": [dict(b) for b in breakpoints]
        }
    except Exception as e:
        print(f"⚠️ rhythm session load error: {e}")
        return None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


# ============================================
# FLASK BLUEPRINT & ROUTES
# ============================================

rhythm_return_bp = Blueprint('rhythm_return', __name__, url_prefix='/api/rhythm-return')


@rhythm_return_bp.route('/health', methods=['GET'])
def health():
    """Health check — engine status + key constants"""
    return jsonify({
        "success": True,
        "engine": "Rhythm Return Engine v1.0.0",
        "description": "Adaptivni rytmicka terapie pro Parkinsonovu chorobu",
        "phi": PHI,
        "thresholds": {
            "FLOW": f"M < {M_FLOW}",
            "STRUGGLE": f"{M_FLOW} <= M < {M_STRUGGLE}",
            "FREEZE": f"M >= {M_STRUGGLE}"
        },
        "bpm_phi_freeze": BPM_PHI_FREEZE,
        "anticipation_engine": _ANT_AVAILABLE,
        "database": _DB_AVAILABLE,
        "timestamp": now_iso()
    })


@rhythm_return_bp.route('/constants', methods=['GET'])
def get_constants():
    """All mathematical constants, clinical data, and φ-derived values"""
    return jsonify({
        "success": True,
        "golden_ratio": {
            "phi": PHI,
            "psi": PSI,
            "phi_squared": round(PHI_SQ, 6),
            "property": "phi^2 = phi + 1"
        },
        "motor_thresholds": {
            "M_FLOW": M_FLOW,
            "M_STRUGGLE": M_STRUGGLE,
            "M_MAX": M_MAX,
            "M_TARGET": M_TARGET,
            "TAU_TARGET": TAU_TARGET
        },
        "prediction_coefficients": {
            "K1_MOTOR": K1_MOTOR,
            "K2_MOTOR": K2_MOTOR,
            "GAMMA_MOTOR": GAMMA_MOTOR,
            "LAMBDA_M": LAMBDA_M,
            "LAMBDA_TAU": LAMBDA_TAU
        },
        "therapeutic_bpm": {
            "BPM_REST": BPM_REST,
            "BPM_PREFERRED": BPM_PREFERRED,
            "BPM_HEALTHY": BPM_HEALTHY,
            "BPM_MAX": BPM_MAX,
            "BPM_PHI_FREEZE": BPM_PHI_FREEZE,
            "formula": f"BPM_FREEZE = BPM_REST({BPM_REST}) x phi({PHI:.3f}) = {BPM_PHI_FREEZE}"
        },
        "speech_rhythm": {
            "pause_flow_ms": PAUSE_FLOW_MS,
            "pause_struggle_ms": PAUSE_STRUGGLE_MS,
            "pause_freeze_ms": PAUSE_FREEZE_MS,
            "ratio": f"psi:1:phi = {PSI:.3f}:1:{PHI:.3f}"
        },
        "clinical_frequencies": {
            "tremor_rest_hz": list(TREMOR_REST_HZ),
            "tremor_fog_hz": list(TREMOR_FOG_HZ),
            "beta_pathological_hz": list(BETA_PATHOLOGICAL_HZ),
            "phi_bands_hz": PHI_BANDS_HZ
        },
        "fibonacci": FIBONACCI[:11],
        "hoehn_yahr_gait": HY_GAIT,
        "phi_desync_examples": {
            "beta_20hz": calculate_phi_desync(20.0),
            "tremor_5hz": calculate_phi_desync(5.0),
            "fog_6hz": calculate_phi_desync(6.0)
        },
        "timestamp": now_iso()
    })


@rhythm_return_bp.route('/predict', methods=['POST'])
def predict():
    """
    Main prediction endpoint — the heart of Rhythm Return Engine.

    Input JSON:
    {
        "M": 15.5,                   # Current motor load (required)
        "tau": 0.45,                 # Current tremor/rigidity index (required)
        "M_prev": 14.0,             # Previous M (optional)
        "tau_prev": 0.4,            # Previous τ (optional)
        "trend_M": 0.5,             # Previous trend M (optional)
        "trend_tau": 0.1,           # Previous trend τ (optional)
        "preferred_bpm": 100,       # Patient's preferred cadence (optional)
        "session_id": "uuid",       # Session to log to (optional)
        "session_progress": 0.5     # Progress in session 0-1 (optional)
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    M_current = float(data.get('M', 10))
    tau_current = float(data.get('tau', 0.3))
    M_prev = float(data.get('M_prev', M_current))
    tau_prev = float(data.get('tau_prev', tau_current))
    trend_M_prev = float(data.get('trend_M', 0))
    trend_tau_prev = float(data.get('trend_tau', 0))
    preferred_bpm = int(data.get('preferred_bpm', BPM_PREFERRED))
    session_id = data.get('session_id')
    session_progress = float(data.get('session_progress', 0))

    # Trends (EMA)
    trend_M = calculate_trend(M_current, M_prev, trend_M_prev, LAMBDA_M)
    trend_tau = calculate_trend(tau_current, tau_prev, trend_tau_prev, LAMBDA_TAU)

    # Predictions
    M_predicted = predict_M(M_current, trend_M, tau_current)
    tau_predicted = predict_tau(tau_current, trend_tau)

    # State classification
    current_state = classify_motor_state(M_current)
    predicted_state = classify_motor_state(M_predicted)

    # Therapy BPM
    therapy = calculate_therapy_bpm(M_predicted, tau_predicted, preferred_bpm)

    # Speech rhythm
    speech = calculate_speech_rhythm(M_predicted, tau_predicted)

    # Confidence vector
    confidence = calculate_confidence(M_predicted, tau_predicted, session_progress)

    # Breakpoints
    breakpoints = detect_motor_breakpoints(M_current, M_predicted)

    # φ-desynchronization (using mid-beta as reference)
    beta_mid = (BETA_PATHOLOGICAL_HZ[0] + BETA_PATHOLOGICAL_HZ[1]) / 2  # ~21.5 Hz
    phi_desync = calculate_phi_desync(beta_mid)

    # Orchestrator instructions
    orchestrator = get_motor_orchestrator_instructions(predicted_state, M_predicted, confidence)

    # Save to DB if session provided
    if session_id and _DB_AVAILABLE:
        _db_save_state(
            session_id, M_current, tau_current, M_predicted, tau_predicted,
            predicted_state, therapy['bpm'],
            json.dumps(therapy['accent_pattern']),
            json.dumps(confidence)
        )
        for bp in breakpoints:
            _db_save_breakpoint(
                session_id, bp['type'], bp['direction'],
                bp['M_before'], bp['M_after'], bp['action']
            )

    return jsonify({
        "success": True,
        "current": {
            "M": round(M_current, 2),
            "tau": round(tau_current, 4),
            "state": current_state
        },
        "predicted": {
            "M": round(M_predicted, 2),
            "tau": round(tau_predicted, 4),
            "state": predicted_state
        },
        "trends": {
            "M": round(trend_M, 4),
            "tau": round(trend_tau, 4)
        },
        "therapy_bpm": therapy,
        "speech_rhythm": speech,
        "confidence": confidence,
        "breakpoints": breakpoints,
        "phi_desync": phi_desync,
        "orchestrator_instructions": orchestrator,
        "phi": PHI,
        "timestamp": now_iso()
    })


@rhythm_return_bp.route('/session', methods=['POST'])
def create_session():
    """
    Create a new therapy session.

    Input JSON:
    {
        "user_id": "patient-123",       # Required
        "preferred_bpm": 96,            # Optional (default 100)
        "hy_stage": "moderate",         # Optional: mild/moderate/severe
        "notes": "Ranní session"        # Optional
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    user_id = data.get('user_id', 'anonymous')
    preferred_bpm = int(data.get('preferred_bpm', BPM_PREFERRED))
    hy_stage = data.get('hy_stage', 'moderate')
    notes = data.get('notes', '')

    session_id = str(uuid.uuid4())[:8]

    # Initial state — assume calm start
    M_initial = 5.0
    tau_initial = 0.2
    initial_state = classify_motor_state(M_initial)
    initial_therapy = calculate_therapy_bpm(M_initial, tau_initial, preferred_bpm)
    initial_confidence = calculate_confidence(M_initial, tau_initial, 0)

    # HY gait reference
    hy_ref = HY_GAIT.get(hy_stage, HY_GAIT["moderate"])

    # Save to DB
    _db_save_session(session_id, user_id, preferred_bpm, hy_stage, notes)

    return jsonify({
        "success": True,
        "session_id": session_id,
        "user_id": user_id,
        "preferred_bpm": preferred_bpm,
        "hy_stage": hy_stage,
        "hy_reference": hy_ref,
        "initial": {
            "M": M_initial,
            "tau": tau_initial,
            "state": initial_state,
            "therapy_bpm": initial_therapy,
            "confidence": initial_confidence
        },
        "instructions": "Use POST /api/rhythm-return/session/{id}/update to send real-time sensor data",
        "timestamp": now_iso()
    })


@rhythm_return_bp.route('/session/<session_id>/update', methods=['POST'])
def update_session(session_id):
    """
    Real-time update during therapy session.

    Input JSON:
    {
        "M": 15,                    # Current motor load (required)
        "tau": 0.5,                 # Current tremor index (required)
        "M_prev": 12,              # Previous M (optional)
        "tau_prev": 0.4,           # Previous τ (optional)
        "preferred_bpm": 96,       # Override preferred BPM (optional)
        "session_progress": 0.3    # Progress 0-1 (optional)
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    data['session_id'] = session_id

    # Delegate to predict endpoint logic
    M_current = float(data.get('M', 10))
    tau_current = float(data.get('tau', 0.3))
    M_prev = float(data.get('M_prev', M_current))
    tau_prev = float(data.get('tau_prev', tau_current))
    preferred_bpm = int(data.get('preferred_bpm', BPM_PREFERRED))
    session_progress = float(data.get('session_progress', 0))

    trend_M = calculate_trend(M_current, M_prev, 0, LAMBDA_M)
    trend_tau = calculate_trend(tau_current, tau_prev, 0, LAMBDA_TAU)

    M_predicted = predict_M(M_current, trend_M, tau_current)
    tau_predicted = predict_tau(tau_current, trend_tau)
    state = classify_motor_state(M_predicted)

    therapy = calculate_therapy_bpm(M_predicted, tau_predicted, preferred_bpm)
    speech = calculate_speech_rhythm(M_predicted, tau_predicted)
    confidence = calculate_confidence(M_predicted, tau_predicted, session_progress)
    breakpoints = detect_motor_breakpoints(M_current, M_predicted)
    orchestrator = get_motor_orchestrator_instructions(state, M_predicted, confidence)

    # Save state
    _db_save_state(
        session_id, M_current, tau_current, M_predicted, tau_predicted,
        state, therapy['bpm'],
        json.dumps(therapy['accent_pattern']),
        json.dumps(confidence)
    )
    for bp in breakpoints:
        _db_save_breakpoint(
            session_id, bp['type'], bp['direction'],
            bp['M_before'], bp['M_after'], bp['action']
        )

    return jsonify({
        "success": True,
        "session_id": session_id,
        "state": state,
        "M": round(M_predicted, 2),
        "tau": round(tau_predicted, 4),
        "therapy_bpm": therapy,
        "speech_rhythm": speech,
        "confidence": confidence,
        "breakpoints": breakpoints,
        "orchestrator_instructions": orchestrator,
        "timestamp": now_iso()
    })


@rhythm_return_bp.route('/session/<session_id>', methods=['GET'])
def get_session(session_id):
    """
    Get session detail with full state history and statistics.
    """
    session_data = _db_get_session(session_id)

    if not session_data:
        return jsonify({
            "success": False,
            "error": f"Session '{session_id}' not found"
        }), 404

    states = session_data.get('states', [])
    bps = session_data.get('breakpoints', [])

    # Calculate session statistics
    total_states = len(states)
    flow_count = sum(1 for s in states if s.get('state') == 'FLOW')
    struggle_count = sum(1 for s in states if s.get('state') == 'STRUGGLE')
    freeze_count = sum(1 for s in states if s.get('state') == 'FREEZE')
    avg_bpm = round(sum(s.get('bpm', 0) for s in states) / total_states, 1) if total_states else 0
    avg_M = round(sum(s.get('M', 0) for s in states) / total_states, 2) if total_states else 0

    stats = {
        "total_updates": total_states,
        "flow_count": flow_count,
        "struggle_count": struggle_count,
        "freeze_count": freeze_count,
        "flow_pct": round(100 * flow_count / total_states, 1) if total_states else 0,
        "avg_bpm": avg_bpm,
        "avg_M": avg_M,
        "breakpoint_count": len(bps),
        "freeze_events": sum(1 for b in bps if b.get('breakpoint_type') == 'B_27' and b.get('direction') == 'up')
    }

    # Serialize timestamps
    session_info = session_data['session']
    for key in ['started_at', 'ended_at']:
        if session_info.get(key) and hasattr(session_info[key], 'isoformat'):
            session_info[key] = session_info[key].isoformat()

    for s in states:
        if s.get('timestamp') and hasattr(s['timestamp'], 'isoformat'):
            s['timestamp'] = s['timestamp'].isoformat()

    for b in bps:
        if b.get('timestamp') and hasattr(b['timestamp'], 'isoformat'):
            b['timestamp'] = b['timestamp'].isoformat()

    return jsonify({
        "success": True,
        "session": session_info,
        "statistics": stats,
        "states": states,
        "breakpoints": bps,
        "timestamp": now_iso()
    })


# ============================================
# STARTUP MESSAGE
# ============================================

print("🎵 Rhythm Return Engine loaded — /api/rhythm-return/* endpoints ready")
print(f"   Predict:   POST /api/rhythm-return/predict")
print(f"   Session:   POST /api/rhythm-return/session")
print(f"   Update:    POST /api/rhythm-return/session/<id>/update")
print(f"   History:   GET  /api/rhythm-return/session/<id>")
print(f"   Constants: GET  /api/rhythm-return/constants")
print(f"   Health:    GET  /api/rhythm-return/health")
print(f"   φ = {PHI}, M thresholds: FLOW<{M_FLOW}, STRUGGLE<{M_STRUGGLE}, FREEZE>={M_STRUGGLE}")
print(f"   BPM: FLOW={BPM_PREFERRED}x1.05, STRUGGLE={BPM_PREFERRED}xψ({PSI:.3f}), FREEZE={BPM_REST}xφ={BPM_PHI_FREEZE}")
