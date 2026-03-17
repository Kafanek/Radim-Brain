"""
🎵 RHYTHM RETURN ROUTES — API endpoints for Parkinson's rhythm therapy
=====================================================================
Version: 2.0.0 (modular)

Architecture:
  rhythm_return_math.py  — constants, predictions, φ-desync, confidence
  rhythm_return_db.py    — DB persistence (sessions, states, breakpoints)
  rhythm_return_routes.py (this file) — Blueprint + route handlers

Routes:
  GET  /api/rhythm-return/health                   — Engine status
  GET  /api/rhythm-return/constants                — All φ constants
  POST /api/rhythm-return/predict                  — Main prediction
  POST /api/rhythm-return/session                  — Create session
  POST /api/rhythm-return/session/<id>/update       — Real-time update
  GET  /api/rhythm-return/session/<id>             — Session history
"""

import json
import uuid
from flask import Blueprint, request, jsonify
from utils import now_iso
import logging

# Import math engine
from rhythm_return_math import (
    # Constants
    PHI, PSI, PHI_SQ,
    M_FLOW, M_STRUGGLE, M_MAX, M_TARGET, TAU_TARGET,
    K1_MOTOR, K2_MOTOR, GAMMA_MOTOR, LAMBDA_M, LAMBDA_TAU,
    BPM_REST, BPM_PREFERRED, BPM_HEALTHY, BPM_MAX, BPM_MIN,
    BPM_PHI_FREEZE, BPM_PHI_FLOW,
    TREMOR_REST_HZ, TREMOR_FOG_HZ, BETA_PATHOLOGICAL_HZ,
    PHI_BANDS_HZ, FIBONACCI, HY_GAIT,
    PAUSE_FLOW_MS, PAUSE_STRUGGLE_MS, PAUSE_FREEZE_MS,
    # Helpers
    calculate_trend,
    # Core functions
    predict_M, predict_tau, classify_motor_state,
    calculate_therapy_bpm, calculate_speech_rhythm,
    calculate_confidence, detect_motor_breakpoints,
    calculate_phi_desync, get_motor_orchestrator_instructions,
    # Availability flag
    _ANT_AVAILABLE
)

# Import DB layer
from rhythm_return_db import (
    _DB_AVAILABLE,
    _db_save_session, _db_save_state, _db_save_breakpoint, _db_get_session
)

logger = logging.getLogger(__name__)


# ============================================
# FLASK BLUEPRINT & ROUTES
# ============================================

rhythm_return_bp = Blueprint('rhythm_return', __name__, url_prefix='/api/rhythm-return')


@rhythm_return_bp.route('/health', methods=['GET'])
def health():
    """Health check — engine status + key constants"""
    return jsonify({
        "success": True,
        "engine": "Rhythm Return Engine v2.0.0",
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
    """Create a new therapy session."""
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
    """Real-time update during therapy session."""
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}

    data['session_id'] = session_id

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
    """Get session detail with full state history and statistics."""
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

logger.info("🎵 Rhythm Return Engine loaded — /api/rhythm-return/* endpoints ready")
logger.info(f"   φ = {PHI}, M thresholds: FLOW<{M_FLOW}, STRUGGLE<{M_STRUGGLE}, FREEZE>={M_STRUGGLE}")
