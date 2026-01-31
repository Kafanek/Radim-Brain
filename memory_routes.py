# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY ROUTES - Adaptivní učící se komunikace
Conversation history + User profiles + Learning

Version: 1.0.0
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from collections import defaultdict

logger = logging.getLogger(__name__)

# Flask Blueprint
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

# ============================================================================
# IN-MEMORY STORAGE (Pro produkci použít Redis/PostgreSQL)
# ============================================================================

# Conversation history per user (last N messages)
CONVERSATION_HISTORY = defaultdict(list)
MAX_HISTORY = 20  # Posledních 20 zpráv

# User profiles
USER_PROFILES = {}

# Learning data - témata zájmu, preference
USER_LEARNING = defaultdict(lambda: {
    "topics": defaultdict(int),      # Počet dotazů na téma
    "preferred_length": "medium",    # short/medium/long
    "communication_style": "warm",   # warm/formal/casual
    "last_mood": "neutral",          # happy/neutral/sad/anxious
    "interaction_count": 0,
    "successful_interactions": 0,
    "last_interaction": None
})

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_context(user_id: str) -> dict:
    """Získat kontext pro Claude system prompt"""
    profile = USER_PROFILES.get(user_id, {})
    learning = USER_LEARNING[user_id]
    history = CONVERSATION_HISTORY.get(user_id, [])
    
    # Top 3 témata zájmu
    top_topics = sorted(learning["topics"].items(), key=lambda x: x[1], reverse=True)[:3]
    
    context = {
        "has_profile": bool(profile),
        "name": profile.get("name", ""),
        "age_group": profile.get("age_group", ""),
        "hearing": profile.get("hearing", "normal"),
        "vision": profile.get("vision", "normal"),
        "memory_support": profile.get("memory_support", False),
        "communication_style": learning.get("communication_style", "warm"),
        "preferred_length": learning.get("preferred_length", "medium"),
        "top_interests": [t[0] for t in top_topics],
        "interaction_count": learning.get("interaction_count", 0),
        "last_mood": learning.get("last_mood", "neutral"),
        "recent_history": history[-5:] if history else []  # Posledních 5 zpráv pro kontext
    }
    
    return context

def build_personalized_prompt(user_id: str) -> str:
    """Vytvořit personalizovaný system prompt addition"""
    ctx = get_user_context(user_id)
    
    if not ctx["has_profile"] and ctx["interaction_count"] == 0:
        return ""  # Nový uživatel - žádná personalizace
    
    parts = ["\n\n═══════════════════════════════════════════════════════════════"]
    parts.append("👤 PERSONALIZACE PRO TOHOTO UŽIVATELE")
    parts.append("═══════════════════════════════════════════════════════════════")
    
    if ctx["name"]:
        parts.append(f"- Jméno: {ctx['name']} (oslovuj jménem)")
    
    if ctx["age_group"]:
        parts.append(f"- Věková skupina: {ctx['age_group']}")
    
    # Zdravotní potřeby
    if ctx["hearing"] != "normal":
        parts.append(f"- Sluch: {ctx['hearing']} → Používej JASNÉ, KRÁTKÉ věty")
    
    if ctx["vision"] != "normal":
        parts.append(f"- Zrak: {ctx['vision']} → Zmíň že může zapnout větší text")
    
    if ctx["memory_support"]:
        parts.append("- Podpora paměti: ANO → Opakuj klíčové informace, buď trpělivý")
    
    # Komunikační styl
    style_map = {
        "warm": "Buď vřelý a empatický, používej přátelský tón",
        "formal": "Buď profesionální ale stále přátelský",
        "casual": "Buď neformální, používej humor"
    }
    parts.append(f"- Styl: {style_map.get(ctx['communication_style'], style_map['warm'])}")
    
    # Délka odpovědí
    length_map = {
        "short": "Odpovídej STRUČNĚ (max 2-3 věty)",
        "medium": "Odpovídej středně dlouze (4-6 vět)",
        "long": "Můžeš odpovídat podrobněji"
    }
    parts.append(f"- Délka: {length_map.get(ctx['preferred_length'], length_map['medium'])}")
    
    # Témata zájmu
    if ctx["top_interests"]:
        interests_str = ", ".join(ctx["top_interests"])
        parts.append(f"- Oblíbená témata: {interests_str} → Můžeš na ně navázat")
    
    # Nálada
    mood_map = {
        "happy": "Uživatel je v dobré náladě",
        "neutral": "Neutrální nálada",
        "sad": "Uživatel může být smutný - buď extra empatický",
        "anxious": "Uživatel může být úzkostný - buď uklidňující"
    }
    if ctx["last_mood"] != "neutral":
        parts.append(f"- Nálada: {mood_map.get(ctx['last_mood'], '')}")
    
    # Počet interakcí
    if ctx["interaction_count"] > 10:
        parts.append(f"- Známý uživatel ({ctx['interaction_count']} interakcí) - můžeš odkazovat na předchozí konverzace")
    
    parts.append("═══════════════════════════════════════════════════════════════")
    
    return "\n".join(parts)

def detect_topic(message: str) -> str:
    """Detekovat téma zprávy"""
    msg = message.lower()
    
    topic_keywords = {
        "health": ["zdraví", "lék", "doktor", "bolest", "nemoc", "léčba"],
        "weather": ["počasí", "teplota", "déšť", "slunce", "vítr"],
        "news": ["zprávy", "novinky", "politik", "svět"],
        "family": ["rodina", "děti", "vnuci", "manžel", "manželka"],
        "memory": ["paměť", "vzpomínk", "zapomn"],
        "exercise": ["cvičení", "pohyb", "procházka", "sport"],
        "food": ["jídlo", "vaření", "recept", "oběd", "večeře"],
        "entertainment": ["film", "seriál", "kniha", "hudba", "televize"],
        "technology": ["počítač", "telefon", "internet", "aplikace"],
        "emotions": ["cítím", "smutný", "šťastný", "osamělý", "strach"]
    }
    
    for topic, keywords in topic_keywords.items():
        if any(kw in msg for kw in keywords):
            return topic
    
    return "general"

def detect_mood(message: str) -> str:
    """Detekovat náladu z zprávy"""
    msg = message.lower()
    
    happy_words = ["rád", "šťastný", "skvělé", "super", "děkuji", "výborně", "hezky"]
    sad_words = ["smutný", "osamělý", "chybí mi", "bolí", "unavený", "špatně"]
    anxious_words = ["strach", "bojím", "nervózní", "úzkost", "stres", "nemůžu spát"]
    
    if any(w in msg for w in anxious_words):
        return "anxious"
    elif any(w in msg for w in sad_words):
        return "sad"
    elif any(w in msg for w in happy_words):
        return "happy"
    
    return "neutral"

# ============================================================================
# ROUTES
# ============================================================================

@memory_bp.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "service": "RADIM Memory & Learning",
        "users_tracked": len(USER_PROFILES),
        "conversations_active": len(CONVERSATION_HISTORY),
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/profile/<user_id>', methods=['GET'])
def get_profile(user_id):
    """Získat profil uživatele"""
    profile = USER_PROFILES.get(user_id, {})
    learning = USER_LEARNING[user_id]
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "learning": {
            "interaction_count": learning["interaction_count"],
            "top_topics": dict(sorted(learning["topics"].items(), key=lambda x: x[1], reverse=True)[:5]),
            "preferred_length": learning["preferred_length"],
            "communication_style": learning["communication_style"],
            "last_mood": learning["last_mood"]
        },
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['POST'])
def save_profile(user_id):
    """Uložit/aktualizovat profil uživatele"""
    data = request.get_json() or {}
    
    # Validace
    allowed_fields = ["name", "age_group", "hearing", "vision", "memory_support", 
                      "communication_style", "preferred_length", "character", "tone"]
    
    profile = USER_PROFILES.get(user_id, {})
    
    for field in allowed_fields:
        if field in data:
            profile[field] = data[field]
    
    profile["updated_at"] = datetime.utcnow().isoformat()
    USER_PROFILES[user_id] = profile
    
    # Update learning preferences
    if "communication_style" in data:
        USER_LEARNING[user_id]["communication_style"] = data["communication_style"]
    if "preferred_length" in data:
        USER_LEARNING[user_id]["preferred_length"] = data["preferred_length"]
    
    logger.info(f"Profile saved for user: {user_id}")
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "message": "Profil uložen",
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['DELETE'])
def delete_profile(user_id):
    """Smazat profil uživatele (GDPR)"""
    if user_id in USER_PROFILES:
        del USER_PROFILES[user_id]
    if user_id in USER_LEARNING:
        del USER_LEARNING[user_id]
    if user_id in CONVERSATION_HISTORY:
        del CONVERSATION_HISTORY[user_id]
    
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
def get_history(user_id):
    """Získat historii konverzací"""
    history = CONVERSATION_HISTORY.get(user_id, [])
    limit = request.args.get('limit', 20, type=int)
    
    return jsonify({
        "success": True,
        "user_id": user_id,
        "messages": history[-limit:],
        "total_count": len(history),
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['POST'])
def add_to_history(user_id):
    """Přidat zprávu do historie"""
    data = request.get_json() or {}
    
    message = {
        "role": data.get("role", "user"),  # user/assistant
        "content": data.get("content", ""),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if not message["content"]:
        return jsonify({"success": False, "error": "Empty message"}), 400
    
    # Add to history
    CONVERSATION_HISTORY[user_id].append(message)
    
    # Keep only last N messages
    if len(CONVERSATION_HISTORY[user_id]) > MAX_HISTORY:
        CONVERSATION_HISTORY[user_id] = CONVERSATION_HISTORY[user_id][-MAX_HISTORY:]
    
    # Update learning
    if message["role"] == "user":
        topic = detect_topic(message["content"])
        mood = detect_mood(message["content"])
        
        USER_LEARNING[user_id]["topics"][topic] += 1
        USER_LEARNING[user_id]["last_mood"] = mood
        USER_LEARNING[user_id]["interaction_count"] += 1
        USER_LEARNING[user_id]["last_interaction"] = datetime.utcnow().isoformat()
    
    return jsonify({
        "success": True,
        "message_added": message,
        "history_length": len(CONVERSATION_HISTORY[user_id]),
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['DELETE'])
def clear_history(user_id):
    """Vymazat historii konverzací"""
    if user_id in CONVERSATION_HISTORY:
        CONVERSATION_HISTORY[user_id] = []
    
    return jsonify({
        "success": True,
        "message": "Historie vymazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT FOR CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/context/<user_id>', methods=['GET'])
def get_context(user_id):
    """Získat kontext pro Claude API volání"""
    context = get_user_context(user_id)
    personalized_prompt = build_personalized_prompt(user_id)
    
    # Build messages array for Claude
    history = CONVERSATION_HISTORY.get(user_id, [])
    claude_messages = []
    
    for msg in history[-10:]:  # Last 10 messages
        claude_messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    
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
def submit_feedback(user_id):
    """Uložit feedback pro učení"""
    data = request.get_json() or {}
    
    feedback_type = data.get("type", "neutral")  # positive/negative/neutral
    message_id = data.get("message_id")
    comment = data.get("comment", "")
    
    # Update learning based on feedback
    if feedback_type == "positive":
        USER_LEARNING[user_id]["successful_interactions"] += 1
    elif feedback_type == "negative":
        # Můžeme upravit styl komunikace
        if "příliš dlouhé" in comment.lower():
            USER_LEARNING[user_id]["preferred_length"] = "short"
        elif "příliš krátké" in comment.lower():
            USER_LEARNING[user_id]["preferred_length"] = "long"
    
    logger.info(f"Feedback from {user_id}: {feedback_type}")
    
    return jsonify({
        "success": True,
        "message": "Děkuji za zpětnou vazbu!",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT FUNCTIONS FOR CLAUDE_ROUTES
# ─────────────────────────────────────────────────────────────────────────────

def get_personalized_system_prompt(user_id: str, base_prompt: str) -> str:
    """Vrátit personalizovaný system prompt"""
    addition = build_personalized_prompt(user_id)
    return base_prompt + addition

def get_conversation_messages(user_id: str, limit: int = 10) -> list:
    """Vrátit konverzační historii pro Claude"""
    history = CONVERSATION_HISTORY.get(user_id, [])
    return [{"role": m["role"], "content": m["content"]} for m in history[-limit:]]

def record_interaction(user_id: str, user_message: str, assistant_response: str):
    """Zaznamenat interakci"""
    # Add user message
    CONVERSATION_HISTORY[user_id].append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # Add assistant response
    CONVERSATION_HISTORY[user_id].append({
        "role": "assistant", 
        "content": assistant_response,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # Keep only last N
    if len(CONVERSATION_HISTORY[user_id]) > MAX_HISTORY:
        CONVERSATION_HISTORY[user_id] = CONVERSATION_HISTORY[user_id][-MAX_HISTORY:]
    
    # Update learning
    topic = detect_topic(user_message)
    mood = detect_mood(user_message)
    
    USER_LEARNING[user_id]["topics"][topic] += 1
    USER_LEARNING[user_id]["last_mood"] = mood
    USER_LEARNING[user_id]["interaction_count"] += 1
    USER_LEARNING[user_id]["last_interaction"] = datetime.utcnow().isoformat()

# Export
__all__ = [
    'memory_bp',
    'get_personalized_system_prompt',
    'get_conversation_messages', 
    'record_interaction',
    'get_user_context'
]
