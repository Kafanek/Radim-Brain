# ============================================
# 🧠 BRAIN CORE v1.0.0
# ============================================
# Core logic for RADIM Brain Engine:
# - DB persistence (adaptation, brain states)
# - Engine availability flags
# - Speech wrappers (inject DB into brain_speech)
# - compute_psi_state, reinforcement_update
# - architecture_pipeline, memory_model
# Extracted from radim_brain_routes.py for modularity.
# ============================================

import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# IMPORTS FROM MODULAR FILES
# ═══════════════════════════════════════════════════════════

from brain_math import (
    PHI, PSI, DELTA, RHO, RADIM_R,
    FIBONACCI, LUCAS, PELL,
    T1, T2, C_MAX, BRAIN_STATE_TTL_MINUTES,
    W_VOICE, W_HRV, W_SPEECH_TEMPO,
    sigmoid, clamp,
    consciousness_equation, compute_empathy, derive_text_empathy_proxies,
    compute_rationality, compute_stress, quasiperiodic_rhythm, decision_model
)

from brain_speech import (
    update_early_psi, get_early_psi,
    compute_unified_speech as _raw_compute_unified_speech,
    get_brain_speech_for_user as _raw_get_brain_speech_for_user
)


# ═══════════════════════════════════════════════════════════
# REINFORCEMENT LEARNING STATE
# ═══════════════════════════════════════════════════════════

_adaptation_state = {
    "reward_sum": 0,
    "interactions": 0,
    "speech_rate_adjust": 0.0,     # -0.3 to +0.1
    "pause_adjust_ms": 0,          # -200 to +400
    "style": "warm",               # warm / formal / casual
    "intervention_level": 0.5,     # 0 = pasivní, 1 = aktivní
}

_ADAPTATION_DEFAULTS = {
    "reward_sum": 0,
    "interactions": 0,
    "speech_rate_adjust": 0.0,
    "pause_adjust_ms": 0.0,
    "style": "warm",
    "intervention_level": 0.5,
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
    from database import get_connection, is_postgres, db_context
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


# ═══════════════════════════════════════════════════════════
# DATABASE PERSISTENCE
# ═══════════════════════════════════════════════════════════

def _db_load_adaptation(user_id):
    """Load per-user adaptation state from PostgreSQL, or return defaults."""
    if not DB_AVAILABLE or not user_id:
        return dict(_ADAPTATION_DEFAULTS)
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level "
                "FROM brain_adaptation WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                return {
                    "reward_sum": row[0], "interactions": row[1],
                    "speech_rate_adjust": float(row[2]), "pause_adjust_ms": float(row[3]),
                    "style": row[4] or "warm", "intervention_level": float(row[5]),
                }
    except Exception as e:
        logger.warning(f"Brain DB load warning: {e}")
    return dict(_ADAPTATION_DEFAULTS)


def _db_save_adaptation(user_id, state):
    """Upsert per-user adaptation state to PostgreSQL."""
    if not DB_AVAILABLE or not user_id:
        return
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO brain_adaptation (user_id, reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, NOW()) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "reward_sum=EXCLUDED.reward_sum, interactions=EXCLUDED.interactions, speech_rate_adjust=EXCLUDED.speech_rate_adjust, "
                    "pause_adjust_ms=EXCLUDED.pause_adjust_ms, style=EXCLUDED.style, intervention_level=EXCLUDED.intervention_level, updated_at=NOW()",
                    (user_id, state["reward_sum"], state["interactions"],
                     state["speech_rate_adjust"], state["pause_adjust_ms"],
                     state["style"], state["intervention_level"]))
            else:
                db.execute(
                    "INSERT OR REPLACE INTO brain_adaptation (user_id, reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (user_id, state["reward_sum"], state["interactions"],
                     state["speech_rate_adjust"], state["pause_adjust_ms"],
                     state["style"], state["intervention_level"]))
    except Exception as e:
        logger.warning(f"Brain DB save warning: {e}")


def _db_save_brain_state(user_id, psi, alpha, mode, coherence, source="chat"):
    """Save Psi(t) snapshot to brain_states table."""
    if not DB_AVAILABLE or not user_id:
        return
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())",
                    (user_id, psi["C"], psi["E"], psi["R"], psi["S"], alpha, mode, coherence, source))
            else:
                db.execute(
                    "INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (user_id, psi["C"], psi["E"], psi["R"], psi["S"], alpha, mode, coherence, source))
    except Exception as e:
        logger.warning(f"Brain state save warning: {e}")


# ═══════════════════════════════════════════════════════════
# SPEECH WRAPPERS — inject DB dependencies into brain_speech
# ═══════════════════════════════════════════════════════════

def compute_unified_speech(C, alpha, mode, user_id=None, ant_params=None):
    """Wrapper that injects DB adaptation loader into brain_speech."""
    return _raw_compute_unified_speech(
        C, alpha, mode, user_id=user_id, ant_params=ant_params,
        _load_adaptation=_db_load_adaptation,
        _adaptation_fallback=_adaptation_state
    )


def get_brain_speech_for_user(user_id):
    """Wrapper that injects DB adaptation loader into brain_speech."""
    return _raw_get_brain_speech_for_user(
        user_id,
        _load_adaptation=_db_load_adaptation,
        _adaptation_fallback=_adaptation_state
    )


# ═══════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════

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

    # v282: Rhythm Return Engine integration — enrich speech with motor/therapy data
    rhythm_data = None
    if RHYTHM_RETURN_AVAILABLE:
        try:
            motor_state = _rr_classify_motor(C)
            therapy_bpm = _rr_therapy_bpm(C, alpha)
            speech_rhythm = _rr_speech_rhythm(C, alpha)
            rhythm_data = {
                "motor_state": motor_state,
                "therapy_bpm": therapy_bpm,
                "speech_rhythm": speech_rhythm
            }
            # Blend RR speech rhythm into pause_ms if available
            if speech_rhythm and isinstance(speech_rhythm, dict):
                rr_pause = speech_rhythm.get("pause_ms")
                if rr_pause and isinstance(rr_pause, (int, float)):
                    # Weighted blend: 70% unified + 30% rhythm return
                    speech["pause_ms"] = round(0.7 * speech["pause_ms"] + 0.3 * rr_pause)
        except Exception as rr_err:
            logger.debug(f"Rhythm Return in psi_state (non-fatal): {rr_err}")

    # Save Ψ(t) snapshot to DB
    psi_vec = {"C": round(C, 4), "E": E, "R": R, "S": S}
    if user_id:
        _db_save_brain_state(user_id, psi_vec, alpha, mode, coherence)

    result = {
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
            "mode": mode,
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
    if rhythm_data:
        result["rhythm_return"] = rhythm_data
    return result


def reinforcement_update(success, user_id=None, signal_type="interaction"):
    """
    Adaptace (Master Prompt §11):
        success → reward +1, failure → reward -1
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
        state["speech_rate_adjust"] += eta * 0.05 * multiplier
        state["pause_adjust_ms"] -= eta * 50 * multiplier
        state["intervention_level"] = max(0, state["intervention_level"] - eta * 0.05)
    else:
        state["speech_rate_adjust"] -= eta * 0.10 * multiplier
        state["pause_adjust_ms"] += eta * 100 * multiplier
        state["intervention_level"] = min(1, state["intervention_level"] + eta * 0.1)

    # Clamp
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


def architecture_pipeline():
    """Architektura (Master Prompt §15)."""
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
                "module": "brain_math.py",
                "status": "active",
                "equation": "C_{n+1} = (1-alpha)(F_n + L_n) + alpha(2*P_n + P_{n-1})"
            },
            {
                "stage": "COHERENCE_ENGINE",
                "description": "Stavovy vektor Psi(t) = (C, E, R, S)",
                "module": "brain_core.py",
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
                "module": "brain_speech.py + speech_routes.py",
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
    """Paměť Radima (Master Prompt §9)."""
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


logger.info("✅ Brain Core loaded — DB persistence, compute_psi_state, reinforcement_update, architecture")
