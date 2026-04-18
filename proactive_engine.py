"""
💡 proactive_engine — recall-based conversation starters (v10.45)
=============================================================================
Reads user's long-term memory + recent chat topics and generates warm,
natural opening prompts that Radim uses when initiating contact.

Triggers:
    - morning_checkin (8:00 AM daily)
    - daily_engagement (14:00 afternoon)
    - manually via /api/proactive/recall

Examples:
    Yesterday: user mentioned knee pain → "Dobré ráno. Jak je na
        koleno dneska lepší?"
    Last week: mentioned daughter Marie visit planned → "Už jsi
        se slyšela s Marií? Říkala jsi, že ti měla volat."
    Three days of silence + unusual → "Dlouho jsem tě neviděl.
        Vše v pořádku?"

Uses Gemini / Claude to compose a single warm Czech sentence.
Falls back to time-of-day greeting if AI unavailable.
"""

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


RECALL_PROMPT = """Jsi Radim — český AI společník pro seniora. Tvůj úkol: vymyslet JEDNU krátkou vřelou větu nebo otázku, kterou dnes ráno oslovíš {name}, aby navazovala na to, co jste spolu v posledních dnech řešili.

{long_term_context_section}

POSLEDNÍ TÉMATA Z NEDÁVNÉ KONVERZACE:
{recent_topics}

DNEŠNÍ KONTEXT:
- Datum: {today}
- Jmeniny: {nameday}
- Čas: {time_of_day}

PRAVIDLA:
- MAX 2 věty, česky, bez emoji, bez markdown.
- Přirozené, jako když se tě ptá souseda u kávy.
- NAVAŽ na něco konkrétního z nedávného rozhovoru (zdraví, rodina, plány, koníček).
- Pokud není na co navázat, pozdrav teple a otevřeně („Dobré ráno. Jak jsi spala?").
- Zrcadli styl seniora (ty/vy).
- NEDIAGNOSTIKUJ, nevymýšlej, nepoučuj.
- Začni rovnou textem. Bez úvodu.

Napiš jen tu jednu větu/otázku. Nic víc.
"""


def _load_recent_messages(user_id, days=3):
    """Load user's messages from last N days — for topic extraction."""
    try:
        from database import db_context, is_postgres
        interval = f"NOW() - INTERVAL '{days} days'" if is_postgres() else f"datetime('now', '-{days} days')"
        with db_context() as db:
            rows = db.execute(
                f"SELECT role, content FROM memory_history "
                f"WHERE user_id = ? AND created_at > {interval} "
                f"ORDER BY id ASC LIMIT 60",
                (str(user_id),)
            ).fetchall() or []
        items = []
        for r in rows:
            role = r[0] if hasattr(r, '__getitem__') else r.get('role', '')
            content = r[1] if hasattr(r, '__getitem__') else r.get('content', '')
            items.append({"role": role, "content": str(content or '')})
        return items
    except Exception as e:
        logger.error(f"_load_recent_messages: {e}")
        return []


def _extract_recent_topics(messages):
    """Simple topic extraction — user messages only, most recent first."""
    user_msgs = [m for m in messages if m.get('role') == 'user' and m.get('content')]
    # Keep last 8 user messages, trimmed
    snippets = []
    for m in user_msgs[-8:]:
        text = m['content'].strip()
        if len(text) > 180:
            text = text[:180] + "…"
        snippets.append(f"- {text}")
    if not snippets:
        return "(žádné nedávné zprávy)"
    return "\n".join(snippets)


def _load_long_term_context(user_id):
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        ltc = profile.get("long_term_context")
        if isinstance(ltc, dict):
            return ltc.get("text") or ""
        if isinstance(ltc, str):
            return ltc
    except Exception:
        pass
    return ""


def _get_addressee(user_id):
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        fg = profile.get("festive_greeting") or {}
        if fg.get("addressee"):
            return fg["addressee"]
        return profile.get("name") or profile.get("first_name") or ""
    except Exception:
        return ""


def _time_of_day_label(hour):
    if 5 <= hour < 11: return "ráno"
    if 11 <= hour < 17: return "den"
    if 17 <= hour < 22: return "večer"
    return "noc"


def _call_gemini_proactive(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(prompt, generation_config={
            "temperature": 0.8, "max_output_tokens": 150,
        })
        if resp and getattr(resp, 'text', None):
            return resp.text.strip().strip('"').strip("'")
    except Exception as e:
        logger.debug(f"Gemini proactive failed: {e}")
    return None


def _fallback_greeting(hour, name):
    label = "babičko" if not name else name
    if 5 <= hour < 11:
        return f"Dobré ráno, {label}. Jak ses vyspala?"
    if 11 <= hour < 17:
        return f"Dobrý den, {label}. Jak se daří?"
    return f"Dobrý večer, {label}. Měla jsi dnes hezký den?"


# ──────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────

def generate_proactive_prompt(user_id):
    """Generate a warm opening line for the given user based on memory+recent."""
    if not user_id:
        return None

    name = _get_addressee(user_id)
    long_term = _load_long_term_context(user_id)
    recent = _load_recent_messages(user_id, days=4)
    topics = _extract_recent_topics(recent)

    now = datetime.now()
    hour = now.hour

    # Try nameday
    nameday = ""
    try:
        from radim_shared import get_nameday
        nd = get_nameday(now.month, now.day)
        if nd: nameday = nd
    except Exception:
        pass

    long_term_section = ""
    if long_term and len(long_term.strip()) > 20:
        long_term_section = f"DLOUHODOBÁ PAMĚŤ:\n{long_term}\n"

    prompt = RECALL_PROMPT.format(
        name=name or "senior",
        long_term_context_section=long_term_section,
        recent_topics=topics,
        today=now.strftime("%d. %B %Y"),
        nameday=nameday or "—",
        time_of_day=_time_of_day_label(hour),
    )

    text = _call_gemini_proactive(prompt)
    if not text:
        text = _fallback_greeting(hour, name)

    # Safety: trim to 2 sentences max
    parts = text.replace('\n', ' ').split('.')
    trimmed = '.'.join(parts[:2]).strip()
    if trimmed and not trimmed.endswith(('.', '?', '!')):
        trimmed += '.'
    if not trimmed:
        trimmed = _fallback_greeting(hour, name)

    return {
        "text": trimmed,
        "user_id": str(user_id),
        "addressee": name,
        "nameday": nameday,
        "context_used": bool(long_term),
        "recent_messages_count": len(recent),
        "generated_at": now.isoformat(),
    }


def send_proactive_message(user_id, app=None):
    """Generate + send proactive prompt via in-app notification + TTS hint.

    Used by morning_checkin and daily_engagement crons.
    """
    result = generate_proactive_prompt(user_id)
    if not result:
        return None

    text = result["text"]

    # Save as a virtual "radim" message into history so it shows in chat log
    try:
        from memory_helpers import db_add_history
        db_add_history(str(user_id), "assistant", text)
    except Exception as e:
        logger.debug(f"save proactive to history: {e}")

    # Push as in-app notification
    try:
        from notification_helpers import notify
        notify(
            to_user_id=str(user_id),
            type="info",
            severity="info",
            title="Radim se ptá",
            body=text,
            from_user_id=None,
            data={"proactive": True, "context_used": result["context_used"]},
        )
    except Exception as e:
        logger.debug(f"notify proactive: {e}")

    logger.info(f"💡 proactive message sent → user={user_id} "
                f"ctx_used={result['context_used']} text={text!r}")
    return result


def run_daily_recall(app=None):
    """Morning check-in recall — called from agent_loop.run_morning_checkin
    as a sibling step. Only for users with at least one message in the
    last 14 days (active users)."""
    try:
        from database import db_context, is_postgres
        interval = "NOW() - INTERVAL '14 days'" if is_postgres() else "datetime('now', '-14 days')"
        with db_context() as db:
            rows = db.execute(
                f"SELECT DISTINCT user_id FROM memory_history "
                f"WHERE created_at > {interval} LIMIT 200"
            ).fetchall() or []
        users = []
        for r in rows:
            uid = r[0] if hasattr(r, '__getitem__') else r.get('user_id')
            if uid: users.append(str(uid))

        sent = 0
        for uid in users:
            try:
                send_proactive_message(uid)
                sent += 1
            except Exception as e:
                logger.debug(f"proactive fail for {uid}: {e}")

        logger.info(f"💡 daily recall sent to {sent}/{len(users)} active users")
        return {"sent": sent, "total_active": len(users)}
    except Exception as e:
        logger.error(f"run_daily_recall: {e}")
        return {"error": str(e)[:200]}
