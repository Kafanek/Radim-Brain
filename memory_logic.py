# ============================================
# 🧠 MEMORY LOGIC v1.0.0
# ============================================
# Business logic for RADIM Memory system:
# - get_user_context, build_personalized_prompt
# - record_interaction, _update_learning_stats
# - _crisis_escalate, get_personalized_system_prompt
# - get_conversation_messages
# Extracted from memory_routes.py for modularity.
# ============================================

import logging
from datetime import datetime

from memory_helpers import (
    db_load_profile, db_save_profile,
    db_load_history, db_add_history,
    db_load_learning, db_save_learning,
    get_gdpr_consent, get_communication_instructions,
    detect_topic, detect_mood
)

logger = logging.getLogger(__name__)

# DB availability check
try:
    from database import get_connection, is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ============================================================================
# CONTEXT & PROMPT HELPERS
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

    # v283: Brain state context
    learning_raw = db_load_learning(user_id)
    avg_C = learning_raw.get("avg_C")
    crisis_count = learning_raw.get("crisis_count", 0)
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


def get_personalized_system_prompt(user_id: str, base_prompt: str) -> str:
    """Vrátit personalizovaný system prompt"""
    addition = build_personalized_prompt(user_id)
    return base_prompt + addition


def get_conversation_messages(user_id: str, limit: int = 10) -> list:
    """Vrátit konverzační historii pro Claude"""
    history = db_load_history(user_id, limit=limit)
    return [{"role": m["role"], "content": m["content"]} for m in history]


# ============================================================================
# CRISIS ESCALATION
# ============================================================================

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
            try:
                with db_context(commit=True) as db:
                    db.execute(
                        "INSERT INTO crisis_events (user_id, caregiver_id, brain_c, message_excerpt, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, caregiver_id, brain_C, (message or "")[:100], datetime.utcnow().isoformat())
                    )
            except Exception as db_err:
                logger.debug(f"Crisis event DB save non-fatal: {db_err}")

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


# ============================================================================
# RECORD INTERACTION
# ============================================================================

def _update_learning_stats(user_id: str, user_message: str, brain_C: float = None, brain_mode: str = None):
    """Aktualizuj anonymizované learning stats BEZ ukládání obsahu zpráv."""
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
    # GDPR enforcement
    consent = get_gdpr_consent(user_id)
    if not consent.get("chat_history", False):
        logger.info(f"🔒 [GDPR] Skipping chat history save for user={user_id} (no chat_history consent)")
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

    # v283: Brain state learning
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

    # v283: Auto-update baseline_C v profilu
    avg_C = learning.get("avg_C")
    if avg_C is not None and learning.get("interaction_count", 0) >= 5:
        try:
            profile = db_load_profile(user_id)
            old_baseline = profile.get("baseline_C")
            if old_baseline is None or abs(float(old_baseline) - avg_C) > 1.0:
                profile["baseline_C"] = avg_C
                db_save_profile(user_id, profile)
                logger.info(f"🧠 [v283] baseline_C updated for {user_id}: {old_baseline} → {avg_C}")
        except Exception as e:
            logger.debug(f"baseline_C auto-update non-fatal: {e}")


logger.info("✅ Memory Logic loaded — personalization, recording, crisis escalation")
