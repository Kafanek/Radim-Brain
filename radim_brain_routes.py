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

Modular structure (v345):
    brain_math.py   — constants + pure math equations
    brain_speech.py — speech params + early Ψ cache
    this file       — routes + DB persistence + compute_psi_state + re-exports
"""

import math
import time
import json
import traceback
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
import logging
from auth_middleware import require_auth, optional_auth

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# IMPORTS FROM MODULAR FILES
# ═══════════════════════════════════════════════════════════

# Math constants & equations
from brain_math import (
    PHI, PSI, DELTA, RHO, RADIM_R,
    FIBONACCI, LUCAS, PELL,
    T1, T2, C_MAX, BRAIN_STATE_TTL_MINUTES,
    W_VOICE, W_HRV, W_SPEECH_TEMPO,
    sigmoid, clamp,
    consciousness_equation, compute_empathy, derive_text_empathy_proxies,
    compute_rationality, compute_stress, quasiperiodic_rhythm, decision_model
)

# Speech & Early Ψ cache
from brain_speech import (
    update_early_psi, get_early_psi,
    compute_unified_speech as _raw_compute_unified_speech,
    get_brain_speech_for_user as _raw_get_brain_speech_for_user
)

# ═══════════════════════════════════════════════════════════
# BLUEPRINT
# ═══════════════════════════════════════════════════════════
radim_brain_bp = Blueprint('radim_brain', __name__, url_prefix='/api/brain')

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
    db = None
    try:
        db = get_connection()
        ph = "%s" if is_postgres() else "?"
        row = db.execute(
            f"SELECT reward_sum, interactions, speech_rate_adjust, pause_adjust_ms, style, intervention_level FROM brain_adaptation WHERE user_id = {ph}",
            (user_id,)
        ).fetchone()
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
        logger.warning(f"Brain DB load warning: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return dict(_ADAPTATION_DEFAULTS)


def _db_save_adaptation(user_id, state):
    """Upsert per-user adaptation state to PostgreSQL."""
    if not DB_AVAILABLE or not user_id:
        return
    db = None
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
    except Exception as e:
        logger.warning(f"Brain DB save warning: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_save_brain_state(user_id, psi, alpha, mode, coherence, source="chat"):
    """Save Psi(t) snapshot to brain_states table."""
    if not DB_AVAILABLE or not user_id:
        return
    db = None
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
    except Exception as e:
        logger.warning(f"Brain state save warning: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


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
# CORE FUNCTIONS (kept here — they use DB + multiple engines)
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
@optional_auth
def brain_consciousness():
    """Výpočet rovnice stavu vědomí (§6)."""
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


@radim_brain_bp.route('/state', methods=['GET'])
def brain_state_get():
    """GET varianta — vrátí výchozí Ψ(t) stav + Janečkovy hodnoty."""
    try:
        psi = compute_psi_state(5.0, 0.2)
    except Exception:
        psi = {"mode": "HARMONY", "phi_index": 0.85, "psi": {"C": 5.0, "E": 0.7, "R": 0.5, "S": 0.1}}

    try:
        from predict_routes import JANECKUV_VALUES
        values = JANECKUV_VALUES
    except Exception:
        values = [
            "MYŠLENKA", "CÍTĚNÍ", "RESPEKT", "ODVAHA", "HRAVOST", "DŮVĚRA",
            "ODPOVĚDNOST", "RACIONALITA", "EMPATIE", "NADĚJE", "POKORA", "SVOBODA"
        ]

    return jsonify({
        "success": True,
        "psi_state": psi,
        "janecek_values": values,
        "values": [{"name": v, "weight": round(1.0 / len(values), 3)} for v in values],
        "mode": psi.get("mode", "HARMONY"),
        "constants": {
            "phi": round(PHI, 6),
            "delta": round(DELTA, 6),
            "rho": round(RHO, 6)
        },
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/state', methods=['POST'])
@optional_auth
def brain_state():
    """Výpočet stavového vektoru Ψ(t) = (C, E, R, S)."""
    data = request.get_json() or {}

    C = clamp(float(data.get('C', 5.0)), 0.0, C_MAX)
    alpha = clamp(float(data.get('alpha', 0.0)), 0.0, 1.0)

    _vt_raw = data.get('voice_tone', 0.5)
    _TONE_MAP = {'calm': 0.3, 'happy': 0.2, 'sad': 0.6, 'distressed': 0.8, 'angry': 0.9}
    try:
        voice_tone = clamp(float(_vt_raw), 0.0, 1.0)
    except (ValueError, TypeError):
        voice_tone = _TONE_MAP.get(str(_vt_raw).lower(), 0.5)

    hrv = clamp(float(data.get('hrv', 0.5)), 0.0, 1.0)
    speech_tempo = clamp(float(data.get('speech_tempo', 0.5)), 0.0, 1.0)
    n = int(data.get('n', 5))
    user_id = data.get('user_id')

    psi = compute_psi_state(C, alpha, voice_tone, hrv, speech_tempo, user_id=user_id)
    consciousness = consciousness_equation(n, alpha)
    decision = decision_model(C, psi["psi"]["E"], psi["psi"]["R"], psi["psi"]["S"])

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

    rhythm = None
    if RHYTHM_RETURN_AVAILABLE:
        try:
            motor_state = _rr_classify_motor(C)
            therapy_bpm = _rr_therapy_bpm(C, alpha)
            speech_rhythm = _rr_speech_rhythm(C, alpha)
            rhythm = {
                "motor_state": motor_state,
                "therapy_bpm": therapy_bpm,
                "speech_rhythm": speech_rhythm
            }
        except Exception:
            pass

    omega = 2 * math.pi
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
@optional_auth
def brain_perceive():
    """PERCEPTION vrstva — zpracování senzorových dat."""
    data = request.get_json() or {}

    noise = float(data.get('noise_db', 40))
    light = float(data.get('light_lux', 300))
    temp = float(data.get('temperature', 22))
    hr = float(data.get('heart_rate', 72))
    hrv_ms = float(data.get('hrv', 50))
    stress = float(data.get('stress_level', 0.0))
    speech_rate = float(data.get('speech_rate', 120))
    voice_pitch = float(data.get('voice_pitch', 150))

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

    alpha = stress * 0.6 + (max(0, hr - 80) / 100) * 0.4
    alpha = clamp(alpha, 0.0, 1.0)

    voice_tone = clamp(1.0 - abs(voice_pitch - 150) / 100, 0.0, 1.0)
    hrv_norm = clamp(hrv_ms / 100, 0.0, 1.0)
    tempo_norm = clamp(1.0 - (speech_rate - 100) / 100, 0.0, 1.0)

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
            "noise_db": noise, "light_lux": light, "temperature": temp,
            "heart_rate": hr, "hrv_ms": hrv_ms, "stress_level": stress,
            "speech_rate": speech_rate, "voice_pitch": voice_pitch
        },
        "psi_state": psi,
        "decision": decision,
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    })


@radim_brain_bp.route('/adapt', methods=['POST'])
@optional_auth
def brain_adapt():
    """Adaptace (Master Prompt §11)."""
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
@optional_auth
def brain_feedback():
    """Speech feedback from frontend (v2.1)."""
    data = request.get_json() or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "user_id is required"}), 400

    rating = data.get('rating')
    action = data.get('action', '')
    response_time_ms = data.get('response_time_ms')
    context = data.get('context', '')

    if action in ('thumbs_up',) or (rating and int(rating) >= 4):
        signal = "success"
    elif action in ('thumbs_down', 'replay') or (rating and int(rating) <= 2):
        signal = "failure"
    else:
        signal = "neutral"

    if DB_AVAILABLE:
        db = None
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
        except Exception as e:
            logger.warning(f"Brain feedback save warning: {e}")
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

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
    """Rytmická regulace (Master Prompt §8)."""
    data = request.get_json() or {}
    omega = float(data.get('omega', 2 * math.pi))
    application = data.get('application', 'speech')

    rhythm = quasiperiodic_rhythm(omega)

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
            "inhale_s": round(4 * PSI, 1),
            "hold_s": round(4, 1),
            "exhale_s": round(4 * PHI, 1),
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
logger.info(f"""
🧠 RADIM Brain Engine v2.0.0 (modular)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ψ(t) = (C, E, R, S)
  C_{{n+1}} = (1-α)(F_n+L_n) + α(2P_n+P_{{n-1}})
  φ = {PHI:.6f}  (harmonie)
  ρ = {RHO:.6f}  (stabilita)
  δ = {DELTA:.6f}  (krize)
  R = {RADIM_R:.3f}       (φ×δ)
  T₁ = {T1}, T₂ = {T2}
  Modules: brain_math.py + brain_speech.py
  Anticipation: {'✅' if ANTICIPATION_AVAILABLE else '❌'}
  Rhythm Return: {'✅' if RHYTHM_RETURN_AVAILABLE else '❌'}
  Memory: {'✅' if MEMORY_AVAILABLE else '❌'}
  Soul: {'✅' if SOUL_AVAILABLE else '❌'}
""")
