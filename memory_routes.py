# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY ROUTES - Adaptivní učící se komunikace
Conversation history + User profiles + Learning
PostgreSQL persistence with in-memory cache

Version: 2.1.0 — refactored: helpers in memory_helpers.py, GDPR in gdpr_routes.py
"""

import json
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

logger = logging.getLogger(__name__)

# Flask Blueprint
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

# DB availability check
try:
    from database import get_connection, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_user_context(user_id: str) -> dict:
    """Získat kontext pro Claude system prompt"""
    profile = db_load_profile(user_id)
    learning = db_load_learning(user_id)
    history = db_load_history(user_id, limit=5)

    # Top 3 témata zájmu
    topics = learning.get("topics", {})
    top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]

    context = {
        "has_profile": bool(profile),
        "name": profile.get("name", ""),
        "age_group": profile.get("age_group", ""),
        "hearing": profile.get("hearing", "normal"),
        "vision": profile.get("vision", "normal"),
        "memory_support": profile.get("memory_support", False),
        "communication_needs": profile.get("communication_needs", ""),
        "mobility": profile.get("mobility", "normal"),
        "communication_style": learning.get("communication_style", "warm"),
        "preferred_length": learning.get("preferred_length", "medium"),
        "top_interests": [t[0] for t in top_topics],
        "interaction_count": learning.get("interaction_count", 0),
        "last_mood": learning.get("last_mood", "neutral"),
        "recent_history": history,
        "_raw_profile": profile  # v230: plný profil pro léky, kontakty, rutinu
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

    # Komunikační potřeby (demence, afázie, dysfázie, aj.)
    comm_needs = ctx.get("communication_needs", "")
    if comm_needs:
        needs_instructions = get_communication_instructions(comm_needs)
        if needs_instructions:
            parts.append(needs_instructions)

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

    # v230: Léky a denní rutina
    profile = ctx.get("_raw_profile", {})
    meds_list = profile.get("medications_list")
    if meds_list and isinstance(meds_list, list) and len(meds_list) > 0:
        parts.append(f"- Léky: {', '.join(meds_list)}")
        med_times = profile.get("medication_times")
        if med_times and isinstance(med_times, dict):
            for period, meds in med_times.items():
                if meds:
                    parts.append(f"  - {period}: {', '.join(meds) if isinstance(meds, list) else meds}")
        parts.append("  → Pokud se uživatel ptá na léky, znáš jeho medikaci.")

    routine = profile.get("daily_routine_notes")
    if routine:
        parts.append(f"- Denní rutina: {routine}")

    emergency = profile.get("emergency_contacts")
    if emergency and isinstance(emergency, list) and len(emergency) > 0:
        contacts_str = ", ".join(
            f"{c.get('name', '?')} ({c.get('phone', '?')})" for c in emergency[:3]
        )
        parts.append(f"- Nouzové kontakty: {contacts_str}")

    # v283: Brain state context — learned baseline a trend
    learning_raw = db_load_learning(user_id)
    avg_C = learning_raw.get("avg_C")
    crisis_count = learning_raw.get("crisis_count", 0)
    last_brain = learning_raw.get("last_brain_mode")
    if avg_C is not None:
        if avg_C < 8:
            parts.append(f"- 🧠 Mozek: Uživatel je typicky klidný (avg C={avg_C:.1f})")
        elif avg_C < 18:
            parts.append(f"- 🧠 Mozek: Uživatel má střední zátěž (avg C={avg_C:.1f})")
        else:
            parts.append(f"- 🧠 Mozek: Uživatel bývá ve stresu (avg C={avg_C:.1f}) → buď extra klidný")
    if crisis_count >= 3:
        parts.append(f"- ⚠️ Historicky {crisis_count}× krizový stav → zvýšená opatrnost")

    parts.append("═══════════════════════════════════════════════════════════════")

    return "\n".join(parts)


# ============================================================================
# ROUTES
# ============================================================================

@memory_bp.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "service": "RADIM Memory & Learning",
        "version": "2.1.0",
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
    # Auth check: user can only access own data
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

@memory_bp.route('/profile/<user_id>', methods=['POST'])
@require_auth
def save_profile(user_id):
    """Uložit/aktualizovat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    # Validace
    allowed_fields = ["name", "age_group", "hearing", "vision", "memory_support",
                      "communication_style", "preferred_length", "character", "tone",
                      "communication_needs", "mobility",
                      # v230: Domácí asistent — léky, kontakty, rutina
                      "medications_list",       # ["Prednison 5mg", "Vasoretic"]
                      "medication_times",       # {"ráno": ["Prednison"], "večer": ["Vasoretic"]}
                      "emergency_contacts",     # [{"name": "Eva", "phone": "+420..."}]
                      "daily_routine_notes",    # "Vstává v 7, obědvá v 12, spát ve 22"
                      "baseline_C"]             # Personalizované C baseline (float)

    profile = db_load_profile(user_id)

    for field in allowed_fields:
        if field in data:
            profile[field] = data[field]

    profile["updated_at"] = datetime.utcnow().isoformat()
    db_save_profile(user_id, profile)

    # Update learning preferences
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

    # Persist to DB
    db_add_history(user_id, role, content)

    # Update learning for user messages
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

    # Build messages array for Claude
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
    """v284: Rozšířený feedback s brain RL propojením (optional_auth pro frontend)"""
    data = request.get_json() or {}

    feedback_type = data.get("type", "neutral")  # positive/negative/neutral
    comment = data.get("comment", "")
    message_id = data.get("message_id")  # v284: optional message reference

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

    # v284: Propojení na brain RL — thumbs feedback ovlivní adaptaci
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
# v284: CRISIS ESCALATION SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def _crisis_escalate(user_id: str, brain_C: float = None, message: str = ""):
    """
    v284: Eskalace krize — notifikace pečovatele.
    Volá se automaticky při brain_mode == CRISIS.
    """
    try:
        profile = db_load_profile(user_id)
        caregiver_id = profile.get("caregiver_id")

        if not caregiver_id:
            logger.warning(f"🚨 [v284] CRISIS for {user_id} but no caregiver configured!")
            return

        # Ulož krizovou událost do DB
        if _DB_AVAILABLE:
            db = None
            try:
                db = get_connection()
                if is_postgres():
                    db.execute(
                        "INSERT INTO crisis_events (user_id, caregiver_id, brain_c, message_excerpt, created_at) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (user_id, caregiver_id, brain_C, (message or "")[:100], datetime.utcnow().isoformat())
                    )
                else:
                    db.execute(
                        "INSERT INTO crisis_events (user_id, caregiver_id, brain_c, message_excerpt, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, caregiver_id, brain_C, (message or "")[:100], datetime.utcnow().isoformat())
                    )
                db.commit()
            except Exception as db_err:
                logger.debug(f"Crisis event DB save non-fatal: {db_err}")
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

        # Push notifikace pečovateli (fire & forget)
        try:
            from app import send_push_notification
            send_push_notification(
                caregiver_id,
                "🚨 Krizová situace",
                f"Senior {user_id} potřebuje pomoc. Mozek detekoval krizový stav.",
                data={"type": "crisis", "senior_id": user_id, "brain_C": brain_C}
            )
            logger.info(f"🚨 [v284] Crisis notification sent to caregiver {caregiver_id} for {user_id}")
        except Exception as push_err:
            logger.warning(f"🚨 [v284] Push notification failed: {push_err}")

    except Exception as e:
        logger.error(f"🚨 [v284] Crisis escalation error: {e}")


@memory_bp.route('/caregiver/<user_id>', methods=['POST'])
@optional_auth
def set_caregiver(user_id):
    """v284: Nastavit pečovatele pro seniora (pro krizové notifikace)"""

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
    """v284: Historie krizových událostí pro daného seniora"""
    if not _DB_AVAILABLE:
        return jsonify({"success": True, "events": []})

    events = []
    db = None
    try:
        db = get_connection()
        if is_postgres():
            cursor = db.execute(
                "SELECT * FROM crisis_events WHERE user_id = %s ORDER BY created_at DESC LIMIT 20", (user_id,)
            )
        else:
            cursor = db.execute(
                "SELECT * FROM crisis_events WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (user_id,)
            )
        rows = cursor.fetchall() if cursor else []
        for row in rows:
            events.append({
                "user_id": row[1] if isinstance(row, (list, tuple)) else row.get("user_id", user_id),
                "brain_c": row[3] if isinstance(row, (list, tuple)) else row.get("brain_c"),
                "message_excerpt": row[4] if isinstance(row, (list, tuple)) else row.get("message_excerpt", ""),
                "created_at": row[5] if isinstance(row, (list, tuple)) else row.get("created_at", "")
            })
    except Exception as e:
        logger.debug(f"Crisis history fetch non-fatal: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    return jsonify({"success": True, "events": events})


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT FUNCTIONS FOR CLAUDE_ROUTES
# ─────────────────────────────────────────────────────────────────────────────

def get_personalized_system_prompt(user_id: str, base_prompt: str) -> str:
    """Vrátit personalizovaný system prompt"""
    addition = build_personalized_prompt(user_id)
    return base_prompt + addition

def get_conversation_messages(user_id: str, limit: int = 10) -> list:
    """Vrátit konverzační historii pro Claude"""
    history = db_load_history(user_id, limit=limit)
    return [{"role": m["role"], "content": m["content"]} for m in history]

def _update_learning_stats(user_id: str, user_message: str, brain_C: float = None, brain_mode: str = None):
    """Aktualizuj anonymizované learning stats BEZ ukládání obsahu zpráv.
    Používá se i bez GDPR chat_history souhlasu."""
    try:
        learning = db_load_learning(user_id)
        topic = detect_topic(user_message)
        mood = detect_mood(user_message)

        topics = learning.get("topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        learning["topics"] = topics
        learning["last_mood"] = mood
        learning["interaction_count"] = learning.get("interaction_count", 0) + 1
        learning["last_interaction"] = datetime.utcnow().isoformat()

        if brain_C is not None:
            c_history = learning.get("C_history", [])
            c_history.append(round(float(brain_C), 2))
            if len(c_history) > 20:
                c_history = c_history[-20:]
            learning["C_history"] = c_history
            learning["avg_C"] = round(sum(c_history) / len(c_history), 2)

        if brain_mode:
            learning["last_brain_mode"] = brain_mode
            if brain_mode == "CRISIS":
                learning["crisis_count"] = learning.get("crisis_count", 0) + 1
                _crisis_escalate(user_id, brain_C, user_message)

        db_save_learning(user_id, learning)
    except Exception as e:
        logger.warning(f"Learning stats update error (non-fatal): {e}")


def record_interaction(user_id: str, user_message: str, assistant_response: str, brain_C: float = None, brain_mode: str = None):
    """Zaznamenat interakci (v283: + brain state tracking, v290: + GDPR consent check)"""
    # GDPR enforcement — ukládej chat historii POUZE pokud uživatel souhlasil
    consent = get_gdpr_consent(user_id)
    if not consent.get("chat_history", False):
        logger.info(f"🔒 [GDPR] Skipping chat history save for user={user_id} (no chat_history consent)")
        # Stále aktualizuj learning stats (anonymizované), ale ne obsah zpráv
        _update_learning_stats(user_id, user_message, brain_C, brain_mode)
        return

    db_add_history(user_id, "user", user_message)
    db_add_history(user_id, "assistant", assistant_response)

    # Update learning
    learning = db_load_learning(user_id)
    topic = detect_topic(user_message)
    mood = detect_mood(user_message)

    topics = learning.get("topics", {})
    topics[topic] = topics.get(topic, 0) + 1
    learning["topics"] = topics
    learning["last_mood"] = mood
    learning["interaction_count"] = learning.get("interaction_count", 0) + 1
    learning["last_interaction"] = datetime.utcnow().isoformat()

    # v283: Brain state learning — track C history and compute rolling baseline
    if brain_C is not None:
        c_history = learning.get("C_history", [])
        c_history.append(round(float(brain_C), 2))
        # Udržuj posledních 20 hodnot
        if len(c_history) > 20:
            c_history = c_history[-20:]
        learning["C_history"] = c_history
        # Klouzavý průměr = learned baseline_C
        learning["avg_C"] = round(sum(c_history) / len(c_history), 2)

    if brain_mode:
        learning["last_brain_mode"] = brain_mode
        if brain_mode == "CRISIS":
            learning["crisis_count"] = learning.get("crisis_count", 0) + 1
            # v284: Crisis escalation — notifikace pečovatele
            _crisis_escalate(user_id, brain_C, user_message)

    db_save_learning(user_id, learning)

    # v283: Auto-update baseline_C v profilu pokud máme dostatek dat (5+ interakcí)
    avg_C = learning.get("avg_C")
    if avg_C is not None and learning.get("interaction_count", 0) >= 5:
        try:
            profile = db_load_profile(user_id)
            old_baseline = profile.get("baseline_C")
            # Aktualizuj pouze pokud se výrazně liší (>1.0 rozdíl) nebo nebyl nastaven
            if old_baseline is None or abs(float(old_baseline) - avg_C) > 1.0:
                profile["baseline_C"] = avg_C
                db_save_profile(user_id, profile)
                logger.info(f"🧠 [v283] baseline_C updated for {user_id}: {old_baseline} → {avg_C}")
        except Exception as e:
            logger.debug(f"baseline_C auto-update non-fatal: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# BACKWARD COMPATIBILITY — re-export helpers with old names
# Other modules import these from memory_routes (kal_routes, claude_routes, etc.)
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
    # Backward compat
    '_db_load_profile', '_db_save_profile', '_db_delete_profile',
    '_db_load_history', '_db_add_history', '_db_clear_history',
    '_db_load_learning', '_db_save_learning', '_default_learning',
    'get_gdpr_consent', 'audit_log', 'detect_mood', 'detect_topic',
    'build_personalized_prompt'
]
