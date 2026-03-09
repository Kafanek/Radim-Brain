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
BRAIN_STATE_TTL_MINUTES = 30  # Brain state expiry — ignore stale states

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

# Database (for brain persistence)
try:
    from database import get_connection, is_postgres
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

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
# DATABASE PERSISTENCE
# ═══════════════════════════════════════════════════════════

_ADAPTATION_DEFAULTS = {
    "reward_sum": 0,
    "interactions": 0,
    "speech_rate_adjust": 0.0,
    "pause_adjust_ms": 0.0,
    "style": "warm",
    "intervention_level": 0.5,
}


def _db_load_adaptation(user_id):
    """Load per-user adaptation state from PostgreSQL, or return defaults."""
    if not DB_AVAILABLE or not user_id:
        return dict(_ADAPTATION_DEFAULTS)
    try:
        db = get_connection()
        ph = "%s" if is_postgres() else "?"
        row = db.execute(
            f"SELECT reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level FROM brain_adaptation WHERE user_id = {ph}",
            (user_id,)
        ).fetchone()
        db.close()
        if row:
            return {
                "reward_sum": row[0],
                "interactions": row[1],
                "speech_rate_adjust": float(row[2]),
                "pause_adjust_ms": float(row[3]),
                "style": row[4] or "warm",
                "intervention_level": float(row[5]),
            }
    except Exception as e:
        print(f"Brain DB load warning: {e}")
    return dict(_ADAPTATION_DEFAULTS)


def _db_save_adaptation(user_id, state):
    """Upsert per-user adaptation state to PostgreSQL."""
    if not DB_AVAILABLE or not user_id:
        return
    try:
        db = get_connection()
        if is_postgres():
            db.execute('''
                INSERT INTO brain_adaptation (user_id, reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    reward_sum = EXCLUDED.reward_sum,
                    interactions = EXCLUDED.interactions,
                    speech_rate_adjust = EXCLUDED.speech_rate_adjust,
                    pause_adjust_ms = EXCLUDED.pause_adjust_ms,
                    style = EXCLUDED.style,
                    intervention_level = EXCLUDED.intervention_level,
                    updated_at = NOW()
            ''', (user_id, state["reward_sum"], state["interactions"],
                  state["speech_rate_adjust"], state["pause_adjust_ms"],
                  state["style"], state["intervention_level"]))
        else:
            db.execute('''
                INSERT OR REPLACE INTO brain_adaptation (user_id, reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (user_id, state["reward_sum"], state["interactions"],
                  state["speech_rate_adjust"], state["pause_adjust_ms"],
                  state["style"], state["intervention_level"]))
        db.commit()
        db.close()
    except Exception as e:
        print(f"Brain DB save warning: {e}")


def _db_save_brain_state(user_id, psi, alpha, mode, coherence, source="chat"):
    """Save Psi(t) snapshot to brain_states table."""
    if not DB_AVAILABLE or not user_id:
        return
    try:
        db = get_connection()
        if is_postgres():
            db.execute('''
                INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ''', (user_id, psi["C"], psi["E"], psi["R"], psi["S"],
                  alpha, mode, coherence, source))
        else:
            db.execute('''
                INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ''', (user_id, psi["C"], psi["E"], psi["R"], psi["S"],
                  alpha, mode, coherence, source))
        db.commit()
        db.close()
    except Exception as e:
        print(f"Brain state save warning: {e}")


# ═══════════════════════════════════════════════════════════
# EARLY Ψ CACHE — Streaming STT → Brain (v272)
# ═══════════════════════════════════════════════════════════
import time as _time_module

_early_psi_cache = {}
_EARLY_PSI_TTL = 300  # 5 minutes


def update_early_psi(user_id, C_estimate, alpha_estimate, is_final=False):
    """Update brain state from interim STT — lightweight, no DB write for interim.

    For interim results: only update in-memory cache (no DB overhead).
    For final results: save to DB via existing compute_psi_state().
    """
    # Clean stale entries (> 5 min)
    now = _time_module.time()
    stale_keys = [k for k, v in _early_psi_cache.items() if now - v['ts'] > _EARLY_PSI_TTL]
    for k in stale_keys:
        del _early_psi_cache[k]

    if not is_final:
        _early_psi_cache[user_id] = {
            'C': C_estimate,
            'alpha': alpha_estimate,
            'ts': now
        }
        return

    # On final: delegate to full Ψ computation
    try:
        mode = "HARMONY" if C_estimate < T1 else ("ALERT" if C_estimate < T2 else "CRISIS")
        compute_psi_state(C_estimate, 0.5, 0.5, 0.5, alpha_estimate, user_id=user_id)
    except Exception as e:
        print(f"Early Ψ final save warning: {e}")
    finally:
        # Clear interim cache for this user
        _early_psi_cache.pop(user_id, None)


def get_early_psi(user_id):
    """Get cached early Ψ estimate for a user (from streaming STT)."""
    entry = _early_psi_cache.get(user_id)
    if entry and (_time_module.time() - entry['ts']) < _EARLY_PSI_TTL:
        return entry
    return None


def compute_unified_speech(C, alpha, mode, user_id=None, ant_params=None):
    """
    Unified speech parameter computation — single source of truth.

    Layer 1: Brain mode-based baseline (φ-proportioned pauses)
    Layer 2: Anticipation Engine fine-tuning (30% blend if ant_params provided)
    Layer 3: Per-user adaptation from brain_adaptation DB
    Layer 4: Pitch mapping with wider range (v2.1: +2% to -10%)

    Args:
        C: consciousness level (0-40)
        alpha: emotional activation (0-1)
        mode: "HARMONY" | "ALERT" | "CRISIS"
        user_id: if set, loads per-user adaptation from DB
        ant_params: dict from Anticipation Engine {rate, pitch, pause_ms} (optional)

    Returns:
        dict: {rate, pitch_pct, pause_ms, phrasing, style, styledegree, mode}
    """
    # Load per-user adaptation
    if user_id:
        adapt = _db_load_adaptation(user_id)
    else:
        adapt = _adaptation_state

    # === Layer 1: Brain mode-based baseline ===
    if mode == "HARMONY":
        rate = 1.0
        pause_ms = 618      # φ × 382
        pitch_st = 12
        phrasing = "natural"
        style = "friendly"
        styledegree = "1.2"
    elif mode == "ALERT":
        rate = 0.85
        pause_ms = 1000     # φ midpoint
        pitch_st = 8
        phrasing = "simplified"
        style = "empathetic"
        styledegree = "1.1"
    else:  # CRISIS
        rate = 0.7
        pause_ms = 1618     # φ × 1000
        pitch_st = 4
        phrasing = "single_command"
        style = "calm"
        styledegree = "1.0"

    # === Layer 2: Anticipation Engine fine-tuning (30% blend) ===
    if ant_params:
        ant_rate = float(ant_params.get('rate', 0.9))
        ant_pause = float(ant_params.get('pause_ms', 300))
        ant_pitch = float(ant_params.get('pitch', 0))
        rate += (ant_rate - 0.9) * 0.3
        pause_ms += (ant_pause - 300) * 0.3
        pitch_st += int(ant_pitch * 0.3)

    # === Layer 3: Per-user adaptation ===
    rate += adapt["speech_rate_adjust"]
    pause_ms += adapt["pause_adjust_ms"]

    # Clamp
    rate = clamp(rate, 0.5, 1.2)
    pause_ms = clamp(pause_ms, 200, 2500)
    pitch_st = clamp(pitch_st, 0, 16)

    # === Layer 4: Wider pitch mapping (v2.1) ===
    # 12st (HARMONY) → +2%, 8st (ALERT) → ~-5%, 4st (CRISIS) → ~-10%
    pitch_pct = round(2 - (12 - pitch_st) * 1.2)

    return {
        "rate": round(rate, 3),
        "pitch_pct": pitch_pct,
        "pause_ms": round(pause_ms),
        "phrasing": phrasing,
        "style": style,
        "styledegree": styledegree,
        "mode": mode,
    }


def get_brain_speech_for_user(user_id):
    """
    Load latest Ψ(t) from brain_states and compute speech params for TTS.

    Returns dict with rate, pitch, pause_ms, phrasing, style, mode, coherence
    or None if no fresh brain state exists (TTL: 30 min).
    """
    if not DB_AVAILABLE or not user_id:
        return None
    try:
        db = get_connection()
        if is_postgres():
            row = db.execute(
                "SELECT C, E, R, S, alpha, mode, coherence FROM brain_states WHERE user_id = %s AND created_at > NOW() - INTERVAL '%s minutes' ORDER BY created_at DESC LIMIT 1",
                (user_id, BRAIN_STATE_TTL_MINUTES)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT C, E, R, S, alpha, mode, coherence FROM brain_states WHERE user_id = ? AND created_at > datetime('now', '-' || ? || ' minutes') ORDER BY created_at DESC LIMIT 1",
                (user_id, BRAIN_STATE_TTL_MINUTES)
            ).fetchone()
        db.close()
        if not row:
            return None

        # RealDictCursor returns dict with lowercase keys
        C_val = float(row.get('c', row.get('C', 5.0)) or 5.0)
        alpha_val = float(row.get('alpha', 0.0) or 0.0)
        mode = row.get('mode', 'HARMONY') or "HARMONY"
        coherence = row.get('coherence', 0.5)

        # Use unified speech computation
        speech = compute_unified_speech(C_val, alpha_val, mode, user_id=user_id)
        speech["coherence"] = round(float(coherence or 0.5), 4)
        speech["user_id"] = user_id
        speech["source"] = "brain_states"
        return speech
    except Exception as e:
        print(f"Brain speech lookup warning: {e}")
        return None


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

    # Normalizace na 0-C_MAX (40) — mapujeme convergence ratio z [φ, δ] na [0, 40]
    # φ=1.618 → C_norm=0 (harmonie), δ=2.414 → C_norm=40 (krize), ρ=2.016 → ~20 (alert)
    span = DELTA - PHI  # ≈ 0.796
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


def derive_text_empathy_proxies(message, mood=None, alpha=0.0):
    """
    Odhadne voice_tone, hrv, speech_tempo z textu (bez senzorů).

    Pravidla:
        voice_tone: od mood (happy→0.9, sad→0.3, angry→0.1, neutral→0.6)
        hrv: od délky zprávy (krátké=stres→0.3, normální→0.6, dlouhé=klid→0.8)
        speech_tempo: od alpha (nízké α→pomalé=0.7, vysoké α→rychlé=0.3)

    Returns:
        dict: voice_tone, hrv, speech_tempo proxy values
    """
    # Mood → voice_tone
    mood_map = {
        "happy": 0.9, "calm": 0.85, "grateful": 0.85,
        "neutral": 0.6, "confused": 0.45,
        "sad": 0.3, "anxious": 0.2, "angry": 0.15, "crisis": 0.1
    }
    voice_tone = mood_map.get(mood or "neutral", 0.6)

    # Message length → HRV proxy (short=stress, long=calm)
    msg_len = len(message) if message else 0
    if msg_len < 15:
        hrv = 0.3       # very short = stress
    elif msg_len < 50:
        hrv = 0.5       # short
    elif msg_len < 150:
        hrv = 0.65      # normal
    else:
        hrv = 0.8       # long = calm elaboration

    # Alpha → speech_tempo (high alpha = fast/agitated = low tempo score)
    speech_tempo = clamp(0.8 - alpha * 0.6, 0.2, 0.9)

    return {
        "voice_tone": round(voice_tone, 3),
        "hrv": round(hrv, 3),
        "speech_tempo": round(speech_tempo, 3),
        "source": "text_proxy"
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


def compute_psi_state(C, alpha, voice_tone=0.5, hrv=0.5, speech_tempo=0.5, user_id=None):
    """
    Stavový vektor vědomí Ψ(t) = (C, E, R, S)

    Master Prompt §2: Hlavní model stavu systému.

    Args:
        C: consciousness/load (0-40)
        alpha: emotional activation (0-1)
        voice_tone, hrv, speech_tempo: senzorové vstupy pro empatii
        user_id: pokud zadáno, načte adaptaci z DB a uloží Ψ(t) snapshot

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
    phi_index = clamp(1.0 - (C / C_MAX), 0.0, 1.0)

    # RADIM stability score: blízkost k ρ-bodu
    rho_distance = abs(alpha - 0.5)
    stability = 1.0 - rho_distance * 2

    # Celková koherence systému
    coherence = (phi_index * PHI + stability * RHO + (1 - S) * DELTA) / (PHI + RHO + DELTA)

    # Unified speech computation (v2.1: single source of truth)
    speech = compute_unified_speech(C, alpha, mode, user_id=user_id)

    # Save Ψ(t) snapshot to DB
    psi_vec = {"C": round(C, 4), "E": E, "R": R, "S": S}
    if user_id:
        _db_save_brain_state(user_id, psi_vec, alpha, mode, coherence)

    return {
        "psi": psi_vec,
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
            "rate": speech["rate"],
            "pause_ms": speech["pause_ms"],
            "pitch_range_st": clamp(12 - round((2 - speech["pitch_pct"]) / 1.2), 0, 16),
            "pitch_pct": speech["pitch_pct"],
            "phrasing": speech["phrasing"],
            "style": speech["style"],
            "styledegree": speech["styledegree"],
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


def reinforcement_update(success, user_id=None, signal_type="interaction"):
    """
    Adaptace (Master Prompt §11):

        success → reward +1
        failure → reward -1

    Radim upravuje tempo řeči, styl komunikace, intervenci.
    Pokud user_id je zadáno, persistuje stav do PostgreSQL.

    signal_type:
        "interaction" — standard (1× multiplier)
        "speech_feedback" — from user feedback buttons (2× multiplier)

    Returns:
        dict: updated adaptation state
    """
    # Load state: per-user from DB, or global fallback
    if user_id:
        state = _db_load_adaptation(user_id)
    else:
        state = _adaptation_state

    reward = 1 if success else -1
    state["reward_sum"] += reward
    state["interactions"] += 1

    # Exponential moving average adaptace
    eta = 0.15  # learning rate (v2.1: was 0.1)

    # Speech feedback from user is 2× stronger signal
    multiplier = 2.0 if signal_type == "speech_feedback" else 1.0

    if success:
        state["speech_rate_adjust"] += eta * 0.05 * multiplier   # v2.1: was 0.02
        state["pause_adjust_ms"] -= eta * 50 * multiplier        # v2.1: was 20 → -5ms base
        state["intervention_level"] = max(0, state["intervention_level"] - eta * 0.05)
    else:
        state["speech_rate_adjust"] -= eta * 0.10 * multiplier   # v2.1: was 0.05
        state["pause_adjust_ms"] += eta * 100 * multiplier       # v2.1: was 50 → +10ms base
        state["intervention_level"] = min(1, state["intervention_level"] + eta * 0.1)

    # Clamp (v2.1: wider positive range, wider pause range)
    state["speech_rate_adjust"] = clamp(state["speech_rate_adjust"], -0.3, 0.15)
    state["pause_adjust_ms"] = clamp(state["pause_adjust_ms"], -300, 600)

    # Save to DB if user_id provided
    if user_id:
        _db_save_adaptation(user_id, state)

    return {
        "reward": reward,
        "reward_sum": state["reward_sum"],
        "interactions": state["interactions"],
        "avg_reward": round(state["reward_sum"] / max(1, state["interactions"]), 4),
        "persisted": bool(user_id),
        "adaptation": {
            "speech_rate_adjust": round(state["speech_rate_adjust"], 4),
            "pause_adjust_ms": round(state["pause_adjust_ms"]),
            "intervention_level": round(state["intervention_level"], 4),
            "style": state["style"]
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
        "engine": "RADIM Brain Engine v2.0.0",
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
    user_id = data.get('user_id')

    # 1. Stavový vektor Ψ(t)
    psi = compute_psi_state(C, alpha, voice_tone, hrv, speech_tempo, user_id=user_id)

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
            ant_speech = _ant_speech(C, alpha, ant_emotions)
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
    user_id = data.get('user_id')

    result = reinforcement_update(success, user_id=user_id)
    result["context"] = context

    return jsonify({
        "success": True,
        **result,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/feedback', methods=['POST'])
def brain_feedback():
    """
    Speech feedback from frontend (v2.1).

    Input:
        user_id: string (required)
        rating: int 1-5 (optional)
        action: "thumbs_up" | "thumbs_down" | "replay" | "skip" (optional)
        response_time_ms: int (optional)
        context: string (optional)

    Signal mapping:
        thumbs_up / rating >= 4 → success (2× RL via speech_feedback)
        thumbs_down / rating <= 2 → failure (2× RL via speech_feedback)
        replay → failure
        skip / rating == 3 → neutral (no RL update)
    """
    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "user_id is required"}), 400

    rating = data.get('rating')
    action = data.get('action', '')
    response_time_ms = data.get('response_time_ms')
    context = data.get('context', '')

    # Determine signal from action / rating
    if action in ('thumbs_up',) or (rating and int(rating) >= 4):
        signal = "success"
    elif action in ('thumbs_down', 'replay') or (rating and int(rating) <= 2):
        signal = "failure"
    else:
        signal = "neutral"

    # Save feedback to DB
    if DB_AVAILABLE:
        try:
            db = get_connection()
            if is_postgres():
                db.execute(
                    "INSERT INTO brain_feedback (user_id, rating, action, response_time_ms, signal, context) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, rating, action, response_time_ms, signal, context)
                )
            else:
                db.execute(
                    "INSERT INTO brain_feedback (user_id, rating, action, response_time_ms, signal, context) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, rating, action, response_time_ms, signal, context)
                )
            db.commit()
            db.close()
        except Exception as e:
            print(f"Brain feedback save warning: {e}")

    # Apply RL update (2× multiplier for speech_feedback)
    rl_result = None
    if signal != "neutral":
        rl_result = reinforcement_update(
            success=(signal == "success"),
            user_id=user_id,
            signal_type="speech_feedback"
        )

    return jsonify({
        "success": True,
        "signal": signal,
        "rl_update": rl_result,
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
🧠 RADIM Brain Engine v2.0.0
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
