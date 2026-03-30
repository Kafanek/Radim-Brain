"""
🧠 RADIM BRAIN ENGINE — Routes v2.1.0
====================================================
API endpoints for the RADIM Brain Engine.
Core logic in brain_core.py, math in brain_math.py, speech in brain_speech.py.

    Ψ(t) = (C, E, R, S)

Modular structure (v357):
    brain_math.py   — constants + pure math equations
    brain_speech.py — speech params + early Ψ cache
    brain_core.py   — DB persistence + compute_psi_state + reinforcement + architecture
    this file       — routes + re-exports for backward compatibility
"""

import math
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
import logging
from auth_middleware import require_auth, optional_auth

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# IMPORTS FROM MODULAR FILES
# ═══════════════════════════════════════════════════════════

# Math constants & equations (re-export for backward compat)
from brain_math import (
    PHI, PSI, DELTA, RHO, RADIM_R,
    FIBONACCI, LUCAS, PELL,
    T1, T2, C_MAX, BRAIN_STATE_TTL_MINUTES,
    W_VOICE, W_HRV, W_SPEECH_TEMPO,
    sigmoid, clamp,
    consciousness_equation, compute_empathy, derive_text_empathy_proxies,
    compute_rationality, compute_stress, quasiperiodic_rhythm, decision_model
)

# Speech & Early Ψ cache (re-export for backward compat)
from brain_speech import (
    update_early_psi, get_early_psi,
)

# Core logic (re-export for backward compat)
from brain_core import (
    # Engine availability flags
    ANTICIPATION_AVAILABLE, RHYTHM_RETURN_AVAILABLE,
    MEMORY_AVAILABLE, SOUL_AVAILABLE, DB_AVAILABLE,
    # DB persistence
    _db_load_adaptation, _db_save_adaptation, _db_save_brain_state,
    # RL state
    _adaptation_state,
    # Speech wrappers
    compute_unified_speech, get_brain_speech_for_user,
    # Core functions
    compute_psi_state, reinforcement_update,
    architecture_pipeline, memory_model,
)

# Anticipation Engine (for route handlers)
try:
    from anticipation_routes import (
        classify_state as _ant_classify,
        calculate_emotions as _ant_emotions,
        calculate_speech_params as _ant_speech,
    )
except ImportError:
    pass

# Rhythm Return Engine (for route handlers)
try:
    from rhythm_return_routes import (
        classify_motor_state as _rr_classify_motor,
        calculate_therapy_bpm as _rr_therapy_bpm,
        calculate_speech_rhythm as _rr_speech_rhythm,
    )
except ImportError:
    pass

# Database (for feedback route)
try:
    from database import db_context
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════
# BLUEPRINT
# ═══════════════════════════════════════════════════════════
radim_brain_bp = Blueprint('radim_brain', __name__, url_prefix='/api/brain')


# ═══════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════

@radim_brain_bp.route('/health', methods=['GET'])
def brain_health():
    """Zdraví celého RADIM Brain systému."""
    return jsonify({
        "success": True,
        "engine": "RADIM Brain Engine v2.1.0",
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
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO brain_feedback (user_id, rating, action, response_time_ms, signal, context) VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, rating, action, response_time_ms, signal, context)
                )
        except Exception as e:
            logger.warning(f"Brain feedback save warning: {e}")

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
🧠 RADIM Brain Engine v2.1.0 (modular)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Ψ(t) = (C, E, R, S)
  C_{{n+1}} = (1-α)(F_n+L_n) + α(2P_n+P_{{n-1}})
  φ = {PHI:.6f}  (harmonie)
  ρ = {RHO:.6f}  (stabilita)
  δ = {DELTA:.6f}  (krize)
  R = {RADIM_R:.3f}       (φ×δ)
  T₁ = {T1}, T₂ = {T2}
  Modules: brain_math.py + brain_speech.py + brain_core.py
  Anticipation: {'✅' if ANTICIPATION_AVAILABLE else '❌'}
  Rhythm Return: {'✅' if RHYTHM_RETURN_AVAILABLE else '❌'}
  Memory: {'✅' if MEMORY_AVAILABLE else '❌'}
  Soul: {'✅' if SOUL_AVAILABLE else '❌'}
""")


# ============================================================================
# TREND API (v476) — brain_states aggregated by day
# ============================================================================

@radim_brain_bp.route('/trend/<user_id>', methods=['GET'])
@optional_auth
def brain_trend(user_id):
    """
    GET /api/brain/trend/<user_id>?days=30

    Returns daily aggregated brain states for trend visualization.
    Each day: avg C, E, R, S, dominant mode, message count.
    Color coding: green (C<12), orange (12-27), red (C>27).
    """
    days = request.args.get('days', 30, type=int)
    days = min(days, 90)  # Max 90 days

    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute("""
                SELECT
                    created_at::date as day,
                    ROUND(AVG(c)::numeric, 1) as avg_c,
                    ROUND(AVG(e)::numeric, 2) as avg_e,
                    ROUND(AVG(r)::numeric, 2) as avg_r,
                    ROUND(AVG(s)::numeric, 2) as avg_s,
                    ROUND(AVG(coherence)::numeric, 2) as avg_coherence,
                    MODE() WITHIN GROUP (ORDER BY mode) as dominant_mode,
                    COUNT(*) as interactions
                FROM brain_states
                WHERE user_id = ?
                  AND created_at > NOW() - INTERVAL '? days'
                GROUP BY created_at::date
                ORDER BY day ASC
            """.replace('? days', f'{days} days'), (str(user_id),)).fetchall()

            trend = []
            for row in rows:
                avg_c = float(row[1]) if row[1] else 0
                color = 'green' if avg_c < 12 else 'orange' if avg_c < 27 else 'red'
                trend.append({
                    'date': str(row[0]),
                    'avg_c': avg_c,
                    'avg_e': float(row[2]) if row[2] else 0,
                    'avg_r': float(row[3]) if row[3] else 0,
                    'avg_s': float(row[4]) if row[4] else 0,
                    'coherence': float(row[5]) if row[5] else 0,
                    'mode': row[6] or 'HARMONY',
                    'interactions': int(row[7]),
                    'color': color,
                })

            # Compute overall trend direction
            if len(trend) >= 3:
                recent_c = sum(d['avg_c'] for d in trend[-3:]) / 3
                older_c = sum(d['avg_c'] for d in trend[:3]) / 3
                if recent_c > older_c + 2:
                    direction = 'rising'
                    warning = 'Stres se zvyšuje'
                elif recent_c < older_c - 2:
                    direction = 'falling'
                    warning = 'Stav se zlepšuje'
                else:
                    direction = 'stable'
                    warning = None
            else:
                direction = 'insufficient_data'
                warning = None

            return jsonify({
                'success': True,
                'user_id': user_id,
                'days': days,
                'trend': trend,
                'summary': {
                    'direction': direction,
                    'warning': warning,
                    'total_interactions': sum(d['interactions'] for d in trend),
                    'avg_c_overall': round(sum(d['avg_c'] for d in trend) / max(1, len(trend)), 1),
                    'days_with_data': len(trend),
                }
            })

    except Exception as e:
        logger.error(f"Brain trend error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
