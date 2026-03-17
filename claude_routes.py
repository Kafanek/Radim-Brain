"""
🤖 CLAUDE AI ROUTES v2.1.0 — Flask Blueprint
Chat, dashboard, memory endpoints.
Config + helpers in claude_helpers.py.
Emotion endpoints in claude_emotion_routes.py.
Content endpoints in claude_content_routes.py.

Routes:
  GET  /api/claude/health
  GET  /api/claude/nameday
  POST /api/claude/chat
  GET  /api/claude/dashboard-data
  POST /api/claude/memory/save
  POST /api/claude/memory/recall
"""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

# Flask Blueprint
claude_bp = Blueprint('claude', __name__, url_prefix='/api/claude')

# ============================================================================
# IMPORTS FROM HELPERS (+ re-exports for backward compat)
# ============================================================================

from claude_helpers import (
    # Config
    ANTHROPIC_API_KEY, CLAUDE_MODEL, GEMINI_API_KEY,
    ANTHROPIC_AVAILABLE, NAMEDAY_CALENDAR,
    # Feature flags
    CL_INTENT_RESOLVER, CL_ANT_AVAILABLE, CL_MEMORY_AVAILABLE,
    CL_TEXT_RHYTHM, CL_DB_AVAILABLE, CL_BRAIN_AVAILABLE,
    # Feature flag imports (for use in routes)
    cl_resolve_intent, cl_detect_mood,
    cl_tr_estimate, cl_tr_calc, cl_tr_prompt, cl_tr_meta, cl_tr_gen_config,
    cl_brain_psi, cl_brain_proxies, cl_brain_decision,
    # Memory functions
    record_interaction, get_conversation_messages,
    get_user_context, get_personalized_system_prompt,
    # Helper functions
    get_claude_client, call_gemini_fallback, is_credit_error,
    get_today_info, extract_text_from_response, get_greeting,
)

# Backward compat aliases (used by other modules)
_CL_INTENT_RESOLVER = CL_INTENT_RESOLVER
_CL_ANT_AVAILABLE = CL_ANT_AVAILABLE
_CL_MEMORY_AVAILABLE = CL_MEMORY_AVAILABLE
_CL_TEXT_RHYTHM = CL_TEXT_RHYTHM
_CL_DB_AVAILABLE = CL_DB_AVAILABLE
_CL_BRAIN_AVAILABLE = CL_BRAIN_AVAILABLE

# System prompt
from radim_system_prompt import get_radim_prompt, RADIM_SYSTEM_PROMPT_CS
from radim_shared import build_time_context_string


# ============================================================================
# ROUTES
# ============================================================================

@claude_bp.route('/health', methods=['GET'])
def health_check():
    """Health check for Claude AI service"""
    return jsonify({
        "status": "healthy" if ANTHROPIC_API_KEY else "degraded",
        "service": "claude-ai",
        "timestamp": datetime.utcnow().isoformat()
    })


@claude_bp.route('/nameday', methods=['GET'])
def get_nameday():
    """Ziskat dnesni svatek"""
    info = get_today_info()
    return jsonify({
        "success": True,
        "date": info["date"],
        "nameday": info["nameday"],
        "timestamp": datetime.utcnow().isoformat()
    })


@claude_bp.route('/chat', methods=['POST'])
@require_auth
@rate_limit(max_requests=30, window_seconds=60, key_func='user')
def chat_with_radim():
    """Hlavni chat endpoint s Claude + Web Search"""
    try:
        data = request.get_json() or {}
        message = data.get('message', '')
        auth_user = getattr(g, 'auth_user', None) or {}
        user_id = str(auth_user.get('id', '')) or data.get('user_id', 'anonymous')
        use_search = data.get('use_search', True)
        emotional_context = data.get('emotional_context', '')

        if not message:
            return jsonify({
                "success": False,
                "response": "Prosim, napiste mi nejakou zpravu.",
                "timestamp": datetime.utcnow().isoformat()
            })

        client = get_claude_client()

        if not client:
            return jsonify({
                "success": True,
                "response": f"Prominte, AI sluzba je momentalne nedostupna. Zkuste to prosim pozdeji. Dnes ma svatek {get_today_info()['nameday']}.",
                "intent": "fallback",
                "timestamp": datetime.utcnow().isoformat()
            })

        # System prompt
        time_ctx = build_time_context_string()
        system = get_radim_prompt(mode='full', user_type='senior', time_context=time_ctx)

        # Personalize from learning data
        if CL_MEMORY_AVAILABLE:
            try:
                system = get_personalized_system_prompt(user_id, system)
            except Exception as pers_err:
                logger.warning(f"Personalization failed (non-fatal): {pers_err}")

        # Emotional context from frontend
        if emotional_context:
            system += f"\n\n═══ EMOCNI KONTEXT ═══\n{emotional_context}"

        # Neuron context from frontend
        neuron_ctx = data.get('neuron_context')
        if neuron_ctx and isinstance(neuron_ctx, dict):
            ntype = neuron_ctx.get('type', 'unknown')
            ntone = neuron_ctx.get('tone', 'patient')
            nhint = neuron_ctx.get('hint', '')
            system += f"\n\n═══ NEURONOVA INTERVENCE ({ntype}) ═══\n"
            system += f"Ton odpovedi: {ntone}.\n"
            if nhint:
                system += f"Doporucena odpoved neuronu: {nhint}\n"
            system += "Prizpusob svou odpoved tomuto kontextu."

        # Text Rhythm
        anticipation_meta = None
        gen_config_override = None
        C = 5.0
        alpha = 0.2
        if CL_TEXT_RHYTHM:
            try:
                C_val = data.get('C')
                alpha_val = data.get('alpha')

                if C_val is not None and alpha_val is not None:
                    C = float(C_val)
                    alpha = float(alpha_val)
                else:
                    mood = cl_detect_mood(message) if CL_MEMORY_AVAILABLE else "neutral"
                    C, alpha = cl_tr_estimate(message, mood)

                text_result = cl_tr_calc(C, alpha)
                system += cl_tr_prompt(text_result)
                anticipation_meta = cl_tr_meta(text_result)
                gen_config_override = cl_tr_gen_config(text_result)
            except Exception as tr_err:
                logger.warning(f"Text rhythm in claude chat (non-fatal): {tr_err}")

        # Build messages with conversation history
        messages = []
        if CL_MEMORY_AVAILABLE:
            try:
                history_msgs = get_conversation_messages(user_id, limit=10)
                messages.extend(history_msgs)
            except Exception as hist_err:
                logger.warning(f"History load failed (non-fatal): {hist_err}")
        messages.append({"role": "user", "content": message})

        # Intent Resolver: short-circuit simple queries locally
        if CL_INTENT_RESOLVER:
            try:
                _ir_text, _ir_intent, _ir_meta = cl_resolve_intent(message, user_id)
                if _ir_text:
                    logger.info(f"Intent '{_ir_intent}' resolved locally for user={user_id}")
                    result = {
                        "success": True,
                        "response": _ir_text,
                        "intent": _ir_intent,
                        "source": "local",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    if anticipation_meta:
                        result["anticipation"] = anticipation_meta
                    return jsonify(result)
            except Exception as ir_err:
                logger.warning(f"Intent resolver warning (non-fatal): {ir_err}")

        # Claude API call
        max_tokens = gen_config_override["max_tokens"] if gen_config_override else 1024
        api_kwargs = {
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages
        }

        if use_search:
            api_kwargs["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3
            }]

        response = client.messages.create(**api_kwargs)
        text = extract_text_from_response(response)

        # Brain Engine — compute Psi(t) for this interaction
        brain_meta = None
        brain_C_val = None
        brain_mode_val = None
        if CL_BRAIN_AVAILABLE:
            try:
                mood_for_brain = cl_detect_mood(message) if CL_MEMORY_AVAILABLE else "neutral"
                try:
                    C_brain, alpha_brain = float(C), float(alpha)
                except Exception:
                    C_brain, alpha_brain = cl_tr_estimate(message, mood_for_brain) if CL_TEXT_RHYTHM else (5.0, 0.2)
                proxies = cl_brain_proxies(message, mood_for_brain, alpha_brain)
                psi_state = cl_brain_psi(
                    C_brain, alpha_brain,
                    proxies["voice_tone"], proxies["hrv"], proxies["speech_tempo"],
                    user_id=user_id
                )
                decision = cl_brain_decision(
                    C_brain, psi_state["psi"]["E"], psi_state["psi"]["R"], psi_state["psi"]["S"]
                )
                brain_meta = {
                    "psi": psi_state["psi"],
                    "mode": psi_state["mode"],
                    "decision": decision["level"],
                    "coherence": psi_state["coherence"]
                }
                brain_C_val = C_brain
                brain_mode_val = psi_state["mode"]
            except Exception as brain_err:
                logger.warning(f"Brain in claude chat (non-fatal): {brain_err}")

        # Record interaction to memory
        if CL_MEMORY_AVAILABLE:
            try:
                record_interaction(user_id, message, text, brain_C=brain_C_val, brain_mode=brain_mode_val)
            except Exception as mem_err:
                logger.warning(f"Memory record failed (non-fatal): {mem_err}")

        # Detect intent
        intent = "general"
        msg_lower = message.lower()
        if any(w in msg_lower for w in ["pocasi", "teplota", "prsi"]):
            intent = "weather"
        elif any(w in msg_lower for w in ["zpravy", "novinky"]):
            intent = "news"
        elif any(w in msg_lower for w in ["kviz", "otazky"]):
            intent = "quiz"
        elif any(w in msg_lower for w in ["pribeh", "povidka"]):
            intent = "story"

        logger.info(f"Chat | User: {user_id} | Intent: {intent} | Memory: {CL_MEMORY_AVAILABLE}")

        result = {
            "success": True,
            "response": text,
            "intent": intent,
            "timestamp": datetime.utcnow().isoformat()
        }
        if anticipation_meta:
            result["anticipation"] = anticipation_meta
        if brain_meta:
            result["brain"] = brain_meta
        return jsonify(result)

    except Exception as e:
        logger.error(f"Chat error: {e}")
        if is_credit_error(e):
            info = get_today_info()
            time_ctx = f"Dnes je {info['day_name']} {info['date']}. Svatek ma {info['nameday']}."
            system = get_radim_prompt(mode='full', user_type='senior', time_context=time_ctx)
            gemini_text = call_gemini_fallback(message, system)
            if gemini_text:
                if CL_MEMORY_AVAILABLE:
                    try:
                        record_interaction(user_id, message, gemini_text)
                    except Exception:
                        pass
                return jsonify({
                    "success": True,
                    "response": gemini_text,
                    "intent": "general",
                    "source": "gemini_fallback",
                    "timestamp": datetime.utcnow().isoformat()
                })
        return jsonify({
            "success": False,
            "response": "Prominte, neco se pokazilo. Zkuste to prosim znovu.",
            "intent": "error",
            "timestamp": datetime.utcnow().isoformat()
        })


@claude_bp.route('/dashboard-data', methods=['GET'])
@optional_auth
def get_dashboard_data():
    """Vsechna data pro dashboard"""
    info = get_today_info()

    result = {
        "success": True,
        "date": info["date"],
        "day_name": info["day_name"],
        "nameday": info["nameday"],
        "weather": None,
        "greeting": get_greeting(),
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        from claude_content_routes import get_fallback_weather
        fallback = get_fallback_weather("Praha")
        result["weather"] = {
            "temperature": fallback.get("temperature"),
            "condition": fallback.get("condition"),
            "humidity": fallback.get("humidity"),
            "wind": fallback.get("wind")
        }
    except Exception:
        pass

    return jsonify(result)


# Emotion analysis + consciousness state — re-export for backward compat
from claude_emotion_routes import analyze_emotions_local, calculate_harmony


@claude_bp.route('/memory/save', methods=['POST'])
@require_auth
def save_memory_note():
    """Ulozit poznamku do pameti (persisted to PostgreSQL)"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id', 'anonymous')
        note_type = data.get('type', 'observation')
        content = data.get('content', '')

        if not content:
            return jsonify({"success": False, "error": "Empty content"}), 400

        if CL_MEMORY_AVAILABLE:
            record_interaction(user_id, f"[{note_type}] {content[:500]}", "Poznamka ulozena.")

        logger.info(f"Memory note saved | User: {user_id} | Type: {note_type}")

        return jsonify({
            "success": True,
            "persisted": CL_MEMORY_AVAILABLE,
            "note_id": f"note_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "message": "Poznamka ulozena",
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Memory save error: {e}")
        return jsonify({"success": False, "error": "Nepodarilo se ulozit vzpominku"})


@claude_bp.route('/memory/recall', methods=['POST'])
@require_auth
def recall_memory():
    """Vybavit si vzpominky (from PostgreSQL)"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id', 'anonymous')
        limit = data.get('limit', 20)

        memories = []
        context = {}

        if CL_MEMORY_AVAILABLE:
            memories = get_conversation_messages(user_id, limit=limit)
            context = get_user_context(user_id)

        return jsonify({
            "success": True,
            "memories": memories,
            "context": context,
            "count": len(memories),
            "message": f"{len(memories)} vzpominek nalezeno" if memories else "Pamet zatim prazdna",
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Memory recall error: {e}")
        return jsonify({"success": False, "error": "Nepodarilo se vybavit vzpominky", "memories": []})


# Content functions — re-export for backward compat
from claude_content_routes import get_fallback_news, get_fallback_weather, get_fallback_quiz


# ============================================================================
# STARTUP
# ============================================================================
logger.info("🤖 Claude AI Routes v2.1.0 loaded — /api/claude/*")
logger.info("   Helpers module: claude_helpers.py")
