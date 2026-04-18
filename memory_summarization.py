"""
🧠 memory_summarization — long-term memory compression (v10.45)
=============================================================================
Every N messages (or weekly), AI compresses the user's chat history into a
2-3 paragraph "long-term context". This paragraph is injected into every
subsequent chat's system prompt so Radim truly remembers the user.

Triggers:
    1. Cron weekly (Sunday 4:00 AM) — run for all active users via agent_loop
    2. Per-user on every 100th chat message (hot path trigger)
    3. Manual via POST /api/memory/summarize-now (admin + self)

Storage:
    memory_profiles.data.long_term_context = {
        "text": "Valerie má 82 let, žije v Praze...",
        "updated_at": "2026-04-18T12:00:00",
        "message_count_at_update": 247,
        "model": "gemini-2.0-flash-exp"
    }

Injection:
    build_personalized_prompt() reads long_term_context.text and appends
    it as "DLOUHODOBÁ PAMĚŤ" section in system prompt.

Privacy:
    - Summarization prompt explicitly instructs the model NOT to include
      direct quotes or sensitive medical details verbatim — only gist.
    - Summary NEVER goes to third parties; stays in memory_profiles only.
    - User can delete via GDPR /api/gdpr/erase (cascade).
"""

import logging
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# How many messages between automatic re-summarizations (per user)
SUMMARIZE_EVERY_N_MESSAGES = 100

# How many recent messages to include in each summarization
MAX_HISTORY_FOR_SUMMARY = 200

# Minimum messages before we bother summarizing
MIN_MESSAGES_BEFORE_FIRST_SUMMARY = 10


SUMMARIZATION_PROMPT_TEMPLATE = """Jsi shrnující asistent. Tvým úkolem je vytvořit stručný osobnostní profil uživatele tak, aby si ho AI asistent Radim mohl připomenout v budoucích konverzacích.

{previous_summary_section}KONVERZACE S UŽIVATELEM (nejnovější na dně):

{conversation_dump}

════════════════════════════════════════════════════════════════
ÚKOL:
Napiš 2-3 krátké odstavce (celkem max 450 slov) v češtině, které obsahují:

1. **Základní fakta** — věk (pokud zmíněno), kde žije, s kým žije, profese/minulost, rodinní členové (jména + vztah).

2. **Osobnost a zájmy** — co má rád/a, koníčky, oblíbená hudba/jídlo/knihy, témata, ke kterým se vrací.

3. **Zdravotní a životní situace** — zdravotní obtíže (obecně, bez diagnóz), rutina dne, starosti, radosti. Ale VYHNI SE explicitním zdravotním záznamům, které nejsou výslovně sděleny — nevymýšlej diagnózy.

DŮLEŽITÉ:
- Piš ve 3. osobě: „Marie je...", ne „Jsi...".
- NEVYMÝŠLEJ fakta která nezazněla. Pokud něco nevíš, vynech.
- Žádné markdown, žádné odrážky, jen plynulý text.
- Piš jako dopis sobě: co by sis potřeboval pamatovat, aby ses k ní vrátil za měsíc.
- Neukládej citlivá zdravotní data doslovně (léky, diagnózy) — popiš obecně („občas má potíže s chůzí").
- Zdržuj se kritiky — neutrální, přátelský tón.

Začni rovnou textem shrnutí. Žádný úvod.
"""


def _load_history_for_summary(user_id):
    """Load recent messages ordered oldest→newest."""
    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (str(user_id), MAX_HISTORY_FOR_SUMMARY)
            ).fetchall() or []
        # Reverse to chronological
        return list(reversed([
            {"role": r[0] if hasattr(r, '__getitem__') else r['role'],
             "content": r[1] if hasattr(r, '__getitem__') else r['content'],
             "ts": r[2] if hasattr(r, '__getitem__') else r['created_at']}
            for r in rows
        ]))
    except Exception as e:
        logger.error(f"load_history_for_summary: {e}")
        return []


def _count_messages(user_id):
    """Return total message count in memory_history for this user."""
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM memory_history WHERE user_id = ?",
                (str(user_id),)
            ).fetchone()
            if row is None: return 0
            if hasattr(row, 'values'):
                vals = list(row.values())
                return int(vals[0]) if vals else 0
            return int(row[0])
    except Exception:
        return 0


def _load_previous_summary(user_id):
    """Return existing summary dict or None."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        ltc = profile.get("long_term_context")
        if isinstance(ltc, dict):
            return ltc
        if isinstance(ltc, str) and ltc:
            return {"text": ltc, "updated_at": None, "message_count_at_update": 0}
        return None
    except Exception:
        return None


def _save_summary(user_id, summary_text, model_name, message_count):
    """Persist summary into memory_profiles.data.long_term_context."""
    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(str(user_id)) or {}
        profile["long_term_context"] = {
            "text": summary_text.strip(),
            "updated_at": datetime.utcnow().isoformat(),
            "message_count_at_update": int(message_count),
            "model": model_name,
        }
        db_save_profile(str(user_id), profile)
        return True
    except Exception as e:
        logger.error(f"_save_summary: {e}")
        return False


def _format_conversation(messages):
    """Turn list of dicts into plain transcript for the LLM."""
    lines = []
    for m in messages:
        role = m.get('role', '').strip()
        content = str(m.get('content') or '').strip()
        if not content:
            continue
        # Map roles to readable labels
        if role in ('user', 'senior'):
            lines.append(f"UŽIVATEL: {content}")
        elif role in ('assistant', 'radim'):
            lines.append(f"RADIM: {content}")
        elif role == 'system':
            continue  # Skip system entries
        else:
            lines.append(f"{role.upper()}: {content}")
    # Keep within ~8000 chars budget
    text = "\n".join(lines)
    if len(text) > 12000:
        text = text[-12000:]
    return text


def _call_gemini_for_summary(prompt):
    """Call Gemini 2.0 Flash. Returns summary text or None."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        resp = model.generate_content(prompt,
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 1200,
                "top_p": 0.9,
            })
        if resp and getattr(resp, 'text', None):
            return resp.text.strip()
    except Exception as e:
        logger.warning(f"Gemini summary failed: {e}")
    return None


def _call_claude_for_summary(prompt):
    """Fallback to Claude if Gemini unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1200,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        if resp and resp.content:
            return "".join(b.text for b in resp.content if hasattr(b, 'text')).strip()
    except Exception as e:
        logger.warning(f"Claude summary failed: {e}")
    return None


# ──────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────

def summarize_user_memory(user_id, force=False):
    """Compress user's chat history into long-term context.

    Args:
        user_id: str
        force: skip the "enough messages" threshold check

    Returns dict:
        {
            "success": bool,
            "text": str (if success),
            "message_count": int,
            "model": str,
            "skipped_reason": str (if skipped),
        }
    """
    if not user_id:
        return {"success": False, "error": "no user_id"}

    total_messages = _count_messages(user_id)
    prev = _load_previous_summary(user_id)

    if not force:
        # Skip if too few messages
        if total_messages < MIN_MESSAGES_BEFORE_FIRST_SUMMARY:
            return {"success": False, "skipped_reason": "too_few_messages",
                    "message_count": total_messages}
        # Skip if we already summarized recently
        if prev:
            last_count = prev.get("message_count_at_update", 0)
            if total_messages - last_count < SUMMARIZE_EVERY_N_MESSAGES:
                return {"success": False, "skipped_reason": "already_fresh",
                        "message_count": total_messages,
                        "last_update_at": prev.get("updated_at")}

    history = _load_history_for_summary(user_id)
    if not history:
        return {"success": False, "skipped_reason": "empty_history"}

    conversation_dump = _format_conversation(history)
    previous_summary_section = ""
    if prev and prev.get("text"):
        previous_summary_section = (
            f"PŘEDCHOZÍ SHRNUTÍ (z {prev.get('updated_at', 'dříve')}):\n"
            f"{prev['text']}\n\n"
            f"Využij ho jako základ, ale AKTUALIZUJ ho podle nové konverzace.\n\n"
        )

    prompt = SUMMARIZATION_PROMPT_TEMPLATE.format(
        previous_summary_section=previous_summary_section,
        conversation_dump=conversation_dump,
    )

    # Try Gemini first, fallback to Claude
    summary = _call_gemini_for_summary(prompt)
    model_used = "gemini-2.0-flash-exp"
    if not summary:
        summary = _call_claude_for_summary(prompt)
        model_used = "claude-opus-4-5"
    if not summary:
        return {"success": False, "error": "no AI provider available"}

    # Trim if excessively long
    if len(summary) > 3500:
        summary = summary[:3500] + "…"

    ok = _save_summary(user_id, summary, model_used, total_messages)
    if not ok:
        return {"success": False, "error": "db save failed"}

    logger.info(f"🧠 summarize_user_memory user={user_id} "
                f"messages={total_messages} model={model_used} len={len(summary)}")
    return {
        "success": True,
        "text": summary,
        "message_count": total_messages,
        "model": model_used,
    }


def run_weekly_summarization(app=None):
    """Weekly cron — summarize all users with enough recent activity."""
    try:
        from database import db_context
        targets = []
        with db_context() as db:
            # Users with at least 50 messages in last 7 days
            from database import is_postgres
            interval = "NOW() - INTERVAL '7 days'" if is_postgres() else "datetime('now', '-7 days')"
            rows = db.execute(
                f"SELECT user_id, COUNT(*) FROM memory_history "
                f"WHERE created_at > {interval} "
                f"GROUP BY user_id HAVING COUNT(*) >= 50"
            ).fetchall() or []
            for r in rows:
                uid = r[0] if hasattr(r, '__getitem__') else r.get('user_id')
                targets.append(str(uid))

        summarized = 0
        skipped = 0
        for uid in targets:
            result = summarize_user_memory(uid)
            if result.get("success"):
                summarized += 1
            else:
                skipped += 1

        logger.info(f"🧠 weekly summarization: {summarized} updated, {skipped} skipped, "
                    f"total_active={len(targets)}")
        return {"summarized": summarized, "skipped": skipped,
                "total_active": len(targets)}
    except Exception as e:
        logger.error(f"weekly summarization error: {e}")
        return {"error": str(e)[:200]}


def maybe_summarize_on_message(user_id):
    """Called from hot path after each chat message. Triggers summary
    only when SUMMARIZE_EVERY_N_MESSAGES boundary is hit. Non-blocking."""
    if not user_id:
        return
    total = _count_messages(user_id)
    if total < MIN_MESSAGES_BEFORE_FIRST_SUMMARY:
        return
    prev = _load_previous_summary(user_id)
    last_count = prev.get("message_count_at_update", 0) if prev else 0
    if total - last_count < SUMMARIZE_EVERY_N_MESSAGES:
        return

    # Fire async
    import threading
    threading.Thread(
        target=summarize_user_memory,
        args=(user_id,),
        daemon=True,
    ).start()
