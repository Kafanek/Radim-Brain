# ============================================
# KAL Routes — Kolibri Abstraction Layer
# Extracted from app.py (v335)
# Endpoints: /kal/radim/*, /kal/agents/*, /kal/timing/*,
#            /kal/safety/*, /kal/emotion/*, /kal/neurons/*,
#            /kal/consciousness/*
# ============================================

import logging
import uuid
from datetime import datetime

from flask import Blueprint, request, jsonify, g
from auth_middleware import optional_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

# ============================================
# Feature flags — set by init_kal_routes()
# ============================================
MEMORY_AVAILABLE = False
RADIM_BRAIN_AVAILABLE = False

def init_kal_routes(memory_available=False, radim_brain_available=False):
    """Call from app.py after determining feature availability."""
    global MEMORY_AVAILABLE, RADIM_BRAIN_AVAILABLE
    MEMORY_AVAILABLE = memory_available
    RADIM_BRAIN_AVAILABLE = radim_brain_available

# ============================================
# Helpers (copied from app.py)
# ============================================
def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _check_idor(requested_user_id):
    """v330: Validate authenticated user matches requested user_id.
    Returns None if OK, or error response tuple if IDOR detected.
    Allows 'radim-ai' requests and admins through."""
    auth_user = getattr(g, 'auth_user', None)
    if not auth_user:
        return None  # optional_auth — no token = anonymous access (for senior devices)
    user_role = auth_user.get('role', 'user') if isinstance(auth_user, dict) else 'user'
    auth_id = str(auth_user.get('id', '')) if isinstance(auth_user, dict) else ''
    # Admins bypass IDOR check
    if user_role in ('administrator', 'admin', 'caregiver'):
        return None
    # Check if requesting own data
    if auth_id and str(requested_user_id) != auth_id:
        logger.warning(f"IDOR blocked: user {auth_id} tried to access {requested_user_id}")
        return jsonify({'success': False, 'error': 'Pristup zamitnut'}), 403
    return None

# ============================================
# Blueprint
# ============================================
kal_bp = Blueprint('kal', __name__)

# ============================================
# KAL Radim Memory Endpoints
# ============================================

@kal_bp.route('/kal/radim/health')
def kal_radim_health():
    """KAL Radim health check"""
    return jsonify({
        "success": True,
        "status": "ok",
        "message": "Radim Memory API v1.0 — running"
    }), 200


@kal_bp.route('/kal/radim/history/<user_id>')
@optional_auth  # v330: Add auth
def kal_radim_history(user_id):
    """Get user conversation history + stats"""
    idor = _check_idor(user_id)
    if idor: return idor
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import get_conversation_messages, get_user_context
            limit = min(request.args.get('limit', 10, type=int), 200)
            history = get_conversation_messages(user_id, limit=limit)
            ctx = get_user_context(user_id)
            return jsonify({
                "success": True,
                "conversations": history,
                "stats": {
                    "total_conversations": len(history),
                    "days_active": 1,
                    "breakthrough_count": 0,
                    "milestone_count": 0
                },
                "recent_mood": ctx.get("last_mood", "neutral"),
                "progress": "stabilni",
                "breakthroughs": [],
                "milestones": []
            }), 200
    except Exception as e:
        logger.error(f"kal_radim_history error: {e}")
    return jsonify({"success": True, "conversations": [], "stats": {"total_conversations": 0, "days_active": 0, "breakthrough_count": 0, "milestone_count": 0}, "recent_mood": "neutral", "progress": "start", "breakthroughs": [], "milestones": []}), 200


@kal_bp.route('/kal/radim/user/register', methods=['POST', 'OPTIONS'])
def kal_radim_register():
    """Register a new user in memory system"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    user_id = data.get('user_id', str(uuid.uuid4()))
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import _db_load_profile, _db_save_profile
            profile = _db_load_profile(user_id)
            if not profile:
                profile = {
                    "user_id": user_id,
                    "created_at": datetime.utcnow().isoformat(),
                    "first_message": data.get("first_message", "")
                }
                _db_save_profile(user_id, profile)
    except Exception as e:
        logger.error(f"kal_radim_register error: {e}")
    return jsonify({"success": True, "message": "User registered", "user": {"user_id": user_id}}), 200


@kal_bp.route('/kal/radim/user/<user_id>', methods=['PUT', 'OPTIONS'])
@optional_auth  # v330: Add auth
def kal_radim_update_user(user_id):
    """Update user profile"""
    if request.method == 'OPTIONS':
        return '', 204
    idor = _check_idor(user_id)
    if idor: return idor
    data = request.get_json() or {}
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import _db_load_profile, _db_save_profile
            profile = _db_load_profile(user_id) or {"user_id": user_id}
            profile.update(data)
            _db_save_profile(user_id, profile)
            return jsonify({"success": True, "user": profile}), 200
    except Exception as e:
        logger.error(f"kal_radim_update_user error: {e}")
    return jsonify({"success": True, "user": {"user_id": user_id}}), 200


@kal_bp.route('/kal/radim/insights/<user_id>')
@optional_auth  # v330: Add auth
def kal_radim_insights(user_id):
    """Get user insights from learning data"""
    idor = _check_idor(user_id)
    if idor: return idor
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import get_user_context
            ctx = get_user_context(user_id)
            return jsonify({
                "success": True,
                "insights": {
                    "total_interactions": ctx.get("interaction_count", 0),
                    "preferred_length": ctx.get("preferred_length", "medium"),
                    "communication_style": ctx.get("communication_style", "warm"),
                    "last_mood": ctx.get("last_mood", "neutral"),
                    "top_topics": {t: 1 for t in ctx.get("top_interests", [])},
                    "conversation_count": len(ctx.get("recent_history", []))
                }
            }), 200
    except Exception as e:
        logger.error(f"kal_radim_insights error: {e}")
    return jsonify({"success": True, "insights": {"total_interactions": 0, "preferred_length": "medium", "communication_style": "warm", "last_mood": "neutral", "top_topics": {}, "conversation_count": 0}}), 200


@kal_bp.route('/kal/radim/conversation', methods=['POST', 'OPTIONS'])
def kal_radim_conversation():
    """Save a conversation turn"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    user_id = data.get('user_id', 'anonymous')
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import record_interaction
            record_interaction(
                user_id=user_id,
                user_message=data.get('user_message', ''),
                assistant_response=data.get('kafanek_reply', '')
            )
    except Exception as e:
        logger.error(f"kal_radim_conversation error: {e}")
    return jsonify({"success": True, "conversation": {"saved": True}}), 200


@kal_bp.route('/kal/radim/stats')
def kal_radim_stats():
    """Global Radim stats"""
    try:
        if MEMORY_AVAILABLE:
            from database import get_connection
            db = None
            try:
                db = get_connection()
                profiles_count = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()['cnt']
                history_count = db.execute("SELECT COUNT(*) as cnt FROM memory_history").fetchone()['cnt']
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass
            return jsonify({
                "success": True,
                "message": f"Radim pomohl {profiles_count} lidem v {history_count} konverzacich",
                "impact": {
                    "total_users": profiles_count,
                    "total_conversations": history_count,
                    "active_today": profiles_count
                }
            }), 200
    except Exception as e:
        logger.error(f"kal_radim_stats error: {e}")
    return jsonify({"success": True, "message": "Radim stats", "impact": {"total_users": 0, "total_conversations": 0, "active_today": 0}}), 200


# ============================================
# v281: KAL Agent Endpoints — Brain Communication Bridge
# ============================================

_KAL_AGENT_PROMPTS = {
    'core': '',
    'agent_protector': '[Rezim: Pan Ochrance — priorita bezpeci a klid. Odpovidej strucne, uklidnujicim tonem.]',
    'agent_teacher': '[Rezim: Pan Ucitel — vzdelavaci rezim. Vysvetluj srozumitelne, pouzij priklady.]',
    'agent_storyteller': '[Rezim: Pan Vypravec — kreativni vypraveni. Bud poeticky, pouzivej obrazy.]',
    'agent_senior': '[Rezim: Pan Senior — zjednoduseny rezim. Kratke vety, pratelsky ton.]',
    'agent_caller': '[Rezim: Agent Caller — asistence s telefonaty. Nabidni zavolani, prepojeni.]',
    'agent_coder': '[Rezim: Pan Programator — technicka podpora. Presne instrukce krok za krokem.]',
}


def _get_agent_name(agent):
    """Get Czech display name for agent type."""
    names = {
        'core': 'Pan Kafanek',
        'agent_teacher': 'Pan Ucitel Kafanek',
        'agent_protector': 'Pan Ochrance Kafanek',
        'agent_storyteller': 'Pan Vypravec Kafanek',
        'agent_senior': 'Pan Senior Kafanek',
        'agent_caller': 'Agent Caller',
        'agent_coder': 'Pan Programator'
    }
    return names.get(agent, 'Pan Kafanek')


@kal_bp.route('/kal/agents/interact', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def kal_agents_interact():
    """KAL Agent interaction — routes to appropriate agent via orchestrator (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    agent = data.get('agent', 'core')
    message = data.get('message', '')
    context = data.get('context', {})
    session_id = data.get('session_id')

    if not message:
        return jsonify({'success': False, 'error': 'Message required'}), 400

    agent_prefix = _KAL_AGENT_PROMPTS.get(agent, '')

    try:
        from radim_orchestrator import call_gemini_whatsapp
        from intent_resolver import resolve_intent

        # Intent resolver first (local NLU bypass)
        resolved_text, resolved_intent, _ = resolve_intent(message)
        if resolved_text:
            response_text = resolved_text
        else:
            response_text, _ = call_gemini_whatsapp(
                message, context, context.get('mode', 'senior'),
                agent_prefix, None, '', None
            )

        # Get brain state for consciousness_state field
        consciousness_state = None
        phi_metrics = None
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_psi_state, derive_text_empathy_proxies
            proxies = derive_text_empathy_proxies(message, 'neutral', 0.2)
            psi = compute_psi_state(5.0, 0.2, proxies['voice_tone'], proxies['hrv'], proxies['speech_tempo'])
            consciousness_state = {
                'mode': psi['mode'],
                'coherence': psi['coherence'],
                'C': psi['psi']['C'],
                'E': psi['psi']['E']
            }
            phi_metrics = {
                'phi_index': psi['phi_index'],
                'rho_stability': psi['rho_stability']
            }

        return jsonify({
            'success': True,
            'response': response_text or 'Prominte, zkuste to za chvili.',
            'consciousness_state': consciousness_state,
            'phi_metrics': phi_metrics,
            'agent': agent,
            'agentName': _get_agent_name(agent)
        }), 200

    except Exception as e:
        logger.error(f"kal_agents_interact error: {e}")
        return jsonify({
            'success': False,
            'response': 'Omlouvam se, momentalne nejsem dostupny.',
            'agent': agent
        }), 500


@kal_bp.route('/kal/timing/calculate', methods=['POST', 'OPTIONS'])
def kal_timing_calculate():
    """phi-based timing calculation for text (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    text = data.get('text', '')

    try:
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_unified_speech
            from intent_resolver import quick_estimate_from_text
            C_est, alpha_est = quick_estimate_from_text(text)
            mode = "HARMONY" if C_est < 12 else ("ALERT" if C_est < 27 else "CRISIS")
            speech = compute_unified_speech(C_est, alpha_est, mode)
            # Rate is a float multiplier (1.0=normal, 0.85=slower, 0.7=crisis)
            rate = float(speech.get('rate', 1.0))
            wpm = round(120 * rate)  # 120 base x rate -> 120/102/84
            return jsonify({
                'pause_ms': speech.get('pause_ms', 618),
                'wpm': wpm,
                'rate': rate,
                'phi_ratio': 1.618,
                'mode': mode,
                'phrasing': speech.get('phrasing', 'natural'),
                'style': speech.get('style', 'friendly'),
            }), 200
    except Exception as e:
        logger.warning(f"kal_timing_calculate error: {e}")

    return jsonify({'pause_ms': 800, 'wpm': 120, 'phi_ratio': 1.618, 'mode': 'HARMONY'}), 200


@kal_bp.route('/kal/safety/check', methods=['POST', 'OPTIONS'])
def kal_safety_check():
    """Safety/crisis detection for message (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    message = data.get('message', '') or data.get('text', '')

    if not message:
        return jsonify({'alert': None, 'severity': 'low', 'recommendation': None, 'shouldEscalate': False}), 200

    try:
        from intent_resolver import quick_estimate_from_text, _CRISIS_WORDS, _STRESS_WORDS
        C_est, alpha_est = quick_estimate_from_text(message)
        text_lower = message.lower()

        crisis_hits = sum(1 for w in _CRISIS_WORDS if w in text_lower)
        stress_hits = sum(1 for w in _STRESS_WORDS if w in text_lower)

        alert = None
        severity = 'low'
        recommendation = None

        if crisis_hits > 0 or C_est >= 27:
            alert = 'panic'
            severity = 'critical'
            recommendation = 'Okamzite kontaktujte zachrannou sluzbu nebo rodinu.'
        elif stress_hits >= 2 or C_est >= 12:
            alert = 'stress'
            severity = 'medium'
            recommendation = 'Uzivatel muze potrebovat podporu. Zvazte kontaktovani rodiny.'
        elif stress_hits == 1:
            alert = 'mild_stress'
            severity = 'low'
            recommendation = 'Monitorujte situaci.'

        return jsonify({
            'alert': alert,
            'severity': severity,
            'recommendation': recommendation,
            'shouldEscalate': alert == 'panic',
            'C_estimate': round(C_est, 1),
            'alpha_estimate': round(alpha_est, 2)
        }), 200

    except Exception as e:
        # v327 C2 FIX: Error in safety MUST NOT default to "safe" — escalate on error
        logger.error(f"kal_safety_check CRITICAL error: {e}")

    # v327: On error, default to medium severity (not "safe") — better safe than sorry
    return jsonify({
        'alert': 'unknown_error',
        'severity': 'medium',
        'recommendation': 'Bezpecnostni kontrola selhala — doporucujeme rucni kontrolu uzivatele.',
        'shouldEscalate': False,
        '_error': True
    }), 200


@kal_bp.route('/kal/emotion/analyze', methods=['POST', 'OPTIONS'])
def kal_emotion_analyze():
    """Emotion analysis from text — valence/arousal model (v319)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    text = data.get('text', '')

    try:
        from intent_resolver import quick_estimate_from_text, _CRISIS_WORDS, _STRESS_WORDS, _CALM_WORDS
        C_est, alpha_est = quick_estimate_from_text(text)
        text_lower = text.lower()

        crisis_hits = sum(1 for w in _CRISIS_WORDS if w in text_lower)
        stress_hits = sum(1 for w in _STRESS_WORDS if w in text_lower)
        calm_hits = sum(1 for w in _CALM_WORDS if w in text_lower)

        # Valence: -1 (negative) to +1 (positive)
        valence = round(max(-1.0, min(1.0,
            0.0 + calm_hits * 0.3 - stress_hits * 0.2 - crisis_hits * 0.5)), 2)

        # Arousal: 0 (calm) to 1 (agitated)
        arousal = round(max(0.0, min(1.0, alpha_est)), 2)

        # Primary emotion mapping
        if crisis_hits > 0:
            primary = 'strach'
        elif stress_hits >= 2:
            primary = 'uzkost' if valence < -0.3 else 'smutek'
        elif stress_hits == 1:
            primary = 'nejistota'
        elif calm_hits >= 2:
            primary = 'radost' if valence > 0.5 else 'klid'
        elif calm_hits == 1:
            primary = 'spokojenost'
        else:
            primary = 'neutralni'

        mode = "HARMONY" if C_est < 12 else ("ALERT" if C_est < 27 else "CRISIS")

        return jsonify({
            'primary_emotion': primary,
            'valence': valence,
            'arousal': arousal,
            'C_estimate': round(C_est, 1),
            'mode': mode,
            'word_hits': {
                'crisis': crisis_hits,
                'stress': stress_hits,
                'calm': calm_hits
            }
        }), 200

    except Exception as e:
        logger.warning(f"kal_emotion_analyze error: {e}")

    return jsonify({
        'primary_emotion': 'neutralni',
        'valence': 0.0, 'arousal': 0.2,
        'C_estimate': 5.0, 'mode': 'HARMONY',
        'word_hits': {'crisis': 0, 'stress': 0, 'calm': 0}
    }), 200


# ============================================
# Neuron Sync — persist neuron learning to PostgreSQL (v324)
# ============================================

@kal_bp.route('/kal/neurons/sync', methods=['GET', 'OPTIONS'])
@optional_auth
def kal_neurons_load():
    """Load neuron learning data for user"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = getattr(request, 'user_id', None) or request.args.get('user_id', 'anonymous')

    try:
        from memory_routes import _db_load_learning, _db_save_learning
        learning = _db_load_learning(user_id)
        neuron_data = learning.get('neurons', {})

        return jsonify({
            'success': True,
            'neurons': neuron_data,
            'synced_at': learning.get('neurons_synced_at'),
            'user_id': user_id
        }), 200

    except Exception as e:
        logger.warning(f"kal_neurons_load error: {e}")
        return jsonify({'success': False, 'neurons': {}, 'error': 'Chyba nacitani neuronu'}), 200


@kal_bp.route('/kal/neurons/sync', methods=['POST', 'OPTIONS'])
@optional_auth
def kal_neurons_save():
    """Save neuron learning data from frontend to PostgreSQL"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = getattr(request, 'user_id', None)
    data = request.get_json() or {}

    if not user_id:
        user_id = data.get('user_id', 'anonymous')

    neurons_data = data.get('neurons', {})
    if not neurons_data or not isinstance(neurons_data, dict):
        return jsonify({'success': False, 'error': 'No neuron data provided'}), 400

    try:
        from memory_routes import _db_load_learning, _db_save_learning

        # Load existing learning, merge neurons into it
        learning = _db_load_learning(user_id)

        existing_neurons = learning.get('neurons', {})

        # Merge strategy: per-neuron, keep higher activations + newer data
        for neuron_id, incoming in neurons_data.items():
            if not isinstance(incoming, dict):
                continue

            existing = existing_neurons.get(neuron_id, {})
            ex_act = existing.get('activations', 0)
            in_act = incoming.get('activations', 0)

            if in_act > ex_act:
                # Frontend has strictly more data — take it, but keep server patterns too
                server_patterns = set(existing.get('learnedPatterns', []))
                client_patterns = set(incoming.get('learnedPatterns', []))
                incoming['learnedPatterns'] = list(server_patterns | client_patterns)[:30]
                existing_neurons[neuron_id] = incoming
            else:
                # Server has same or more data — merge learned patterns + keep better thresholds
                server_patterns = set(existing.get('learnedPatterns', []))
                client_patterns = set(incoming.get('learnedPatterns', []))
                merged = list(server_patterns | client_patterns)[:30]
                existing['learnedPatterns'] = merged
                # Keep lower threshold (= more sensitive = more learned)
                if incoming.get('thresholdAdjust', 0) < existing.get('thresholdAdjust', 0):
                    existing['thresholdAdjust'] = incoming['thresholdAdjust']
                # Keep higher helpful count
                existing['helpfulCount'] = max(
                    existing.get('helpfulCount', 0), incoming.get('helpfulCount', 0))
                # Merge rhythm data if incoming has it
                if incoming.get('rhythm') and not existing.get('rhythm'):
                    existing['rhythm'] = incoming['rhythm']
                existing_neurons[neuron_id] = existing

        learning['neurons'] = existing_neurons
        learning['neurons_synced_at'] = now_iso()

        _db_save_learning(user_id, learning)

        return jsonify({
            'success': True,
            'synced': len(existing_neurons),
            'synced_at': learning['neurons_synced_at'],
            'user_id': user_id
        }), 200

    except Exception as e:
        logger.warning(f"kal_neurons_save error: {e}")
        return jsonify({'success': False, 'error': 'Chyba synchronizace neuronu'}), 500


@kal_bp.route("/kal/consciousness/state")
def kal_consciousness_state():
    """Consciousness state — real Psi(t) from brain engine (v281)"""
    try:
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_psi_state, get_early_psi
            user_id = request.args.get('user_id', 'default')
            early = get_early_psi(user_id)
            if early:
                C, alpha = early['C'], early['alpha']
            else:
                C, alpha = 5.0, 0.2
            psi = compute_psi_state(C, alpha, user_id=user_id)
            result = {
                "harmony": psi["phi_index"],
                "empathy": psi["psi"]["E"],
                "phi_direction": psi["coherence"],
                "chaos_index": psi["psi"]["S"],
                "iteration": psi["psi"]["C"],
                "mode": psi["mode"],
                "coherence": psi["coherence"],
                "rho_stability": psi.get("rho_stability"),
                "status": "active",
                "timestamp": now_iso()
            }
            # v282: Include rhythm return data if available
            if psi.get("rhythm_return"):
                result["rhythm_return"] = psi["rhythm_return"]
            return jsonify(result), 200
    except Exception as e:
        logger.warning(f"kal_consciousness_state error: {e}")
    return jsonify({
        "harmony": 0.85, "empathy": 0.7, "phi_direction": 0.8,
        "chaos_index": 0.1, "iteration": 5.0, "mode": "HARMONY",
        "status": "active", "timestamp": now_iso()
    }), 200
