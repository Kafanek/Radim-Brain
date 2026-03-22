# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY ROUTES v2.2.0
API endpoints for memory system.
Business logic in memory_logic.py, DB helpers in memory_helpers.py, GDPR in gdpr_routes.py.
"""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth

from memory_helpers import (
    db_available, db_load_profile, db_save_profile, db_delete_profile,
    db_load_history, db_add_history, db_clear_history,
    db_load_learning, db_save_learning, default_learning,
    get_gdpr_consent, save_gdpr_consent, audit_log,
    get_communication_instructions, detect_topic, detect_mood
)

# Business logic (re-export for backward compat)
from memory_logic import (
    get_user_context, build_personalized_prompt,
    get_personalized_system_prompt, get_conversation_messages,
    record_interaction, _update_learning_stats, _crisis_escalate
)

logger = logging.getLogger(__name__)

# Flask Blueprint
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

# DB availability check
try:
    from database import is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ============================================================================
# ROUTES
# ============================================================================

@memory_bp.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "service": "RADIM Memory & Learning",
        "version": "2.2.0",
        "persistence": "postgresql" if (_DB_AVAILABLE and is_postgres()) else "sqlite" if _DB_AVAILABLE else "none",
        "db_available": _DB_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    })


# ─────────────────────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/profile/<user_id>', methods=['GET'])
@require_auth
def get_profile(user_id):
    """Získat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    profile = db_load_profile(user_id)
    learning = db_load_learning(user_id)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "learning": {
            "interaction_count": learning.get("interaction_count", 0),
            "top_topics": dict(sorted(learning.get("topics", {}).items(), key=lambda x: x[1], reverse=True)[:5]),
            "preferred_length": learning.get("preferred_length", "medium"),
            "communication_style": learning.get("communication_style", "warm"),
            "last_mood": learning.get("last_mood", "neutral")
        },
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['POST', 'PUT'])
@require_auth
def save_profile(user_id):
    """Uložit/aktualizovat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    allowed_fields = ["name", "age_group", "hearing", "vision", "memory_support",
                      "communication_style", "preferred_length", "character", "tone",
                      "communication_needs", "mobility",
                      "medications", "medications_list", "medication_times",
                      "emergency_contacts", "daily_routine_notes", "baseline_C",
                      "onboarding_completed", "phone"]

    profile = db_load_profile(user_id)

    for field in allowed_fields:
        if field in data:
            profile[field] = data[field]

    profile["updated_at"] = datetime.utcnow().isoformat()
    db_save_profile(user_id, profile)

    if "communication_style" in data or "preferred_length" in data:
        learning = db_load_learning(user_id)
        if "communication_style" in data:
            learning["communication_style"] = data["communication_style"]
        if "preferred_length" in data:
            learning["preferred_length"] = data["preferred_length"]
        db_save_learning(user_id, learning)

    logger.info(f"Profile saved for user: {user_id}")

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "message": "Profil uložen",
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['DELETE'])
@require_auth
def delete_profile(user_id):
    """Smazat profil uživatele (GDPR)"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    db_delete_profile(user_id)
    audit_log(user_id, "data_delete", "all_user_data", "GDPR profile deletion", request.remote_addr)

    logger.info(f"Profile deleted for user: {user_id}")

    return jsonify({
        "success": True,
        "message": "Všechna data smazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/history/<user_id>', methods=['GET'])
@require_auth
def get_history(user_id):
    """Získat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    limit = request.args.get('limit', 20, type=int)
    history = db_load_history(user_id, limit=limit)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "messages": history,
        "total_count": len(history),
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['POST'])
@require_auth
def add_to_history(user_id):
    """Přidat zprávu do historie"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    role = data.get("role", "user")
    content = data.get("content", "")

    if not content:
        return jsonify({"success": False, "error": "Empty message"}), 400

    db_add_history(user_id, role, content)

    if role == "user":
        learning = db_load_learning(user_id)
        topic = detect_topic(content)
        mood = detect_mood(content)

        topics = learning.get("topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        learning["topics"] = topics
        learning["last_mood"] = mood
        learning["interaction_count"] = learning.get("interaction_count", 0) + 1
        learning["last_interaction"] = datetime.utcnow().isoformat()
        db_save_learning(user_id, learning)

    return jsonify({
        "success": True,
        "message_added": {"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()},
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['DELETE'])
@require_auth
def clear_history(user_id):
    """Vymazat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    db_clear_history(user_id)

    return jsonify({
        "success": True,
        "message": "Historie vymazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT FOR CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/context/<user_id>', methods=['GET'])
@require_auth
def get_context(user_id):
    """Získat kontext pro Claude API volání"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    context = get_user_context(user_id)
    personalized_prompt = build_personalized_prompt(user_id)

    history = db_load_history(user_id, limit=10)
    claude_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    return jsonify({
        "success": True,
        "user_id": user_id,
        "context": context,
        "personalized_prompt_addition": personalized_prompt,
        "conversation_messages": claude_messages,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# FEEDBACK & LEARNING
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/feedback/<user_id>', methods=['POST'])
@optional_auth
def submit_feedback(user_id):
    """Feedback with brain RL integration"""
    data = request.get_json() or {}

    feedback_type = data.get("type", "neutral")
    comment = data.get("comment", "")

    learning = db_load_learning(user_id)

    if feedback_type == "positive":
        learning["successful_interactions"] = learning.get("successful_interactions", 0) + 1
    elif feedback_type == "negative":
        learning["negative_feedback_count"] = learning.get("negative_feedback_count", 0) + 1
        if "příliš dlouhé" in comment.lower():
            learning["preferred_length"] = "short"
        elif "příliš krátké" in comment.lower():
            learning["preferred_length"] = "long"

    db_save_learning(user_id, learning)

    # Brain RL integration
    rl_result = None
    try:
        from radim_brain_routes import reinforcement_update as _rl_update
        if feedback_type in ("positive", "negative"):
            rl_result = _rl_update(
                success=(feedback_type == "positive"),
                user_id=user_id,
                signal_type="chat_feedback"
            )
    except Exception as rl_err:
        logger.debug(f"v284 RL feedback non-fatal: {rl_err}")

    logger.info(f"Feedback from {user_id}: {feedback_type} (RL: {rl_result is not None})")

    return jsonify({
        "success": True,
        "message": "Děkuji za zpětnou vazbu!",
        "rl_update": rl_result,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CAREGIVER & CRISIS
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/caregiver/<user_id>', methods=['POST'])
@optional_auth
def set_caregiver(user_id):
    """Set caregiver for crisis notifications"""
    data = request.get_json() or {}
    caregiver_id = data.get("caregiver_id")

    if not caregiver_id:
        return jsonify({"success": False, "error": "caregiver_id is required"}), 400

    profile = db_load_profile(user_id)
    profile["caregiver_id"] = caregiver_id
    db_save_profile(user_id, profile)

    logger.info(f"🛡️ [v284] Caregiver set: {user_id} → {caregiver_id}")

    return jsonify({
        "success": True,
        "message": f"Pečovatel {caregiver_id} nastaven pro {user_id}",
        "timestamp": datetime.utcnow().isoformat()
    })


@memory_bp.route('/crisis-history/<user_id>', methods=['GET'])
@optional_auth
def get_crisis_history(user_id):
    """Crisis event history"""
    if not _DB_AVAILABLE:
        return jsonify({"success": True, "events": []})

    events = []
    try:
        with db_context() as db:
            cursor = db.execute(
                "SELECT * FROM crisis_events WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,)
            )
            for row in (cursor.fetchall() if cursor else []):
                events.append({
                    "user_id": row[1] if isinstance(row, (list, tuple)) else row.get("user_id", user_id),
                    "brain_c": row[3] if isinstance(row, (list, tuple)) else row.get("brain_c"),
                    "message_excerpt": row[4] if isinstance(row, (list, tuple)) else row.get("message_excerpt", ""),
                    "created_at": row[5] if isinstance(row, (list, tuple)) else row.get("created_at", "")
                })
    except Exception as e:
        logger.debug(f"Crisis history fetch non-fatal: {e}")

    return jsonify({"success": True, "events": events})


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD COMPATIBILITY — re-export helpers with old names
# ─────────────────────────────────────────────────────────────────────────────
_db_load_profile = db_load_profile
_db_save_profile = db_save_profile
_db_delete_profile = db_delete_profile
_db_load_history = db_load_history
_db_add_history = db_add_history
_db_clear_history = db_clear_history
_db_load_learning = db_load_learning
_db_save_learning = db_save_learning
_default_learning = default_learning
_get_communication_instructions = get_communication_instructions

# Export
__all__ = [
    'memory_bp',
    'get_personalized_system_prompt',
    'get_conversation_messages',
    'record_interaction',
    'get_user_context',
    'build_personalized_prompt',
    '_db_load_profile', '_db_save_profile', '_db_delete_profile',
    '_db_load_history', '_db_add_history', '_db_clear_history',
    '_db_load_learning', '_db_save_learning', '_default_learning',
    'get_gdpr_consent', 'audit_log', 'detect_mood', 'detect_topic',
]
