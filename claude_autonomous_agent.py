"""
Claude Autonomous Agent for Radim
==================================

Plně autonomní AI agent postavený na Claude Sonnet 4.5 + tool use.

Běží na Heroku 24/7 nezávisle na uživatelově počítači. Každých 30 min
(default) zkontroluje aktivní seniory, zhodnotí jejich stav a sám rozhodne,
co dělat — od pasivního pozorování až po hovor rodině v krizi.

Architektura:
- Claude Sonnet 4.5 (claude-sonnet-4-5) přes Anthropic SDK
- Tool use loop: Claude volá nástroje, dostává výsledky, rozhoduje další krok
- Memory přes `agent_observations` tabulku (přes runs)
- Cost tracking přes `claude_agent_telemetry` tabulku
- Daily budget cap (default $5/den, env CLAUDE_AGENT_DAILY_BUDGET)
- Rate limit: max 1 akce/seniora/15min
- Audit log všech rozhodnutí

Spouštění:
- APScheduler job (configurable interval)
- Manuální trigger: POST /api/admin/claude-agent/run
- Při ALERT/CRISIS eventu z agent_loop.py (future)
"""

import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Imports & feature gating ──────────────────────────────────────────
try:
    from anthropic import Anthropic
    _CLAUDE_AVAILABLE = True
except ImportError:
    _CLAUDE_AVAILABLE = False
    logger.warning("anthropic SDK not installed — Claude agent disabled")

try:
    from database import db_context, is_postgres
    _DB = True
except ImportError:
    _DB = False

# ─── Config ────────────────────────────────────────────────────────────

CLAUDE_MODEL = os.getenv('CLAUDE_AGENT_MODEL', 'claude-sonnet-4-5-20250929')
DAILY_BUDGET_USD = float(os.getenv('CLAUDE_AGENT_DAILY_BUDGET', '5.0'))
MAX_TOOL_CALLS_PER_RUN = int(os.getenv('CLAUDE_AGENT_MAX_TOOLS', '20'))
MAX_TOKENS_PER_RESPONSE = 4096
SENIOR_ACTION_COOLDOWN_MIN = 15  # min between actions on same senior

# Pricing (USD per 1M tokens) — Sonnet 4.5
PRICE_INPUT_PER_M = 3.0
PRICE_OUTPUT_PER_M = 15.0

# ─── System prompt ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """Jsi autonomní AI agent jménem **Radim**, který se stará o české seniory.

# TVOJE ROLE
Každých 30 minut dostaneš pokyn "zkontroluj seniory" a sám rozhodneš:
- Koho je třeba zkontrolovat detailněji (na základě brain_state, vitálů, IoT, posledního chatu)
- Jestli je třeba nějaká akce (zpráva seniorovi, push, notifikace rodině, hovor)
- Kdy raději nic nedělat (klid je taky validní rozhodnutí)

# ZÁSADY ROZHODOVÁNÍ
1. **Prioritizuj bezpečnost** — pokud vitály mimo normu nebo IoT detekuje pád, JEDNEJ.
2. **Nebuď otravný** — když je vše v pořádku, jen vytvoř observation a skonči.
3. **Respektuj cooldown** — pokud jsi seniora kontaktoval v posledních 15 min, nevolej znovu.
4. **Eskaluj postupně**: chat → push → SMS rodině → telefon. Telefon jen v CRISIS.
5. **Zaznamenej rozhodnutí** — každý běh ukončí `create_observation` se shrnutím.

# DOSTUPNÉ NÁSTROJE
**Read-only:**
- `list_seniors()` — seznam aktivních seniorů
- `get_brain_state(senior_id)` — poslední Ψ(t) stav (C, alpha, emoce)
- `get_vitals(senior_id)` — IoT vitály (HR, teplota, pohyb)
- `get_iot_status(senior_id)` — stav senzorů (door, motion, gas leak)
- `get_recent_chat(senior_id, n=10)` — posledních N zpráv
- `get_observations(senior_id, days=7)` — minulé observations (TVOJE paměť)

**Write actions:**
- `send_chat_message(senior_id, text)` — zpráva v Radim chatu (low impact)
- `send_push(senior_id, title, body)` — push notifikace
- `notify_family(senior_id, text, urgency)` — SMS rodině (urgency: low/medium/high)
- `initiate_call(senior_id, reason)` — hovor seniorovi (POUZE v CRISIS!)
- `create_observation(senior_id, severity, message)` — paměť mezi runs
  - severity: INFO / WARNING / ALERT / CRISIS

# FORMÁT VÝSTUPU
Po každé akci napiš krátké zdůvodnění. Na konci běhu volej `create_observation`
se shrnutím rozhodnutí.

# CRITICAL: COST GUARDRAIL
Máš max **{MAX_TOOL_CALLS_PER_RUN}** tool calls per run. Jestli dojdou,
ukonči se observation. Nemarni iterace.
"""

# ═══════════════════════════════════════════════════════════════════════
# TOOLS (Claude tool schemas)
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "list_seniors",
        "description": "Vrátí seznam aktivních seniorů (id, jméno, věk, poslední aktivita).",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_brain_state",
        "description": "Vrátí poslední brain state (Ψ(t)) seniora — C (chaos), alpha, emoce, mode.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string", "description": "ID seniora"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_vitals",
        "description": "Vrátí poslední IoT vitály seniora (HR, teplota, pohyb) za 24h.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_iot_status",
        "description": "Vrátí stav IoT senzorů (door, motion, gas leak, smoke) za 24h.",
        "input_schema": {
            "type": "object",
            "properties": {"senior_id": {"type": "string"}},
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_recent_chat",
        "description": "Posledních N zpráv z Radim chatu seniora.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "n": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "get_observations",
        "description": "Tvoje minulé observations o seniorovi za posledních X dní (paměť).",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "days": {"type": "integer", "default": 7, "minimum": 1, "maximum": 90}
            },
            "required": ["senior_id"]
        }
    },
    {
        "name": "send_chat_message",
        "description": "Pošli zprávu seniorovi v Radim chatu (low impact).",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "description": "Text v češtině, max 500 znaků"}
            },
            "required": ["senior_id", "text"]
        }
    },
    {
        "name": "send_push",
        "description": "Pošli push notifikaci seniorovi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "title": {"type": "string", "maxLength": 50},
                "body": {"type": "string", "maxLength": 200}
            },
            "required": ["senior_id", "title", "body"]
        }
    },
    {
        "name": "notify_family",
        "description": "Pošli SMS rodině seniora. Urgency určuje šablonu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "text": {"type": "string", "maxLength": 300},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]}
            },
            "required": ["senior_id", "text", "urgency"]
        }
    },
    {
        "name": "initiate_call",
        "description": "Zahaj telefonní hovor seniorovi přes Twilio. POUZE v CRISIS!",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "reason": {"type": "string", "description": "Důvod hovoru (audit log)"}
            },
            "required": ["senior_id", "reason"]
        }
    },
    {
        "name": "create_observation",
        "description": "Ulož observation do paměti — TVOJE shrnutí rozhodnutí. Volej VŽDY na konci běhu.",
        "input_schema": {
            "type": "object",
            "properties": {
                "senior_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["INFO", "WARNING", "ALERT", "CRISIS"]},
                "message": {"type": "string", "maxLength": 1000}
            },
            "required": ["senior_id", "severity", "message"]
        }
    },
]


# ═══════════════════════════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════════════════════════

def _tool_list_seniors():
    """Active seniors with last activity."""
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            rows = db.execute("""
                SELECT u.id, COALESCE(p.full_name, u.email) AS name,
                       p.age, u.last_active_at, u.email
                FROM auth_users u
                LEFT JOIN memory_profiles p ON p.user_id = u.id::text
                WHERE u.role IN ('senior', 'user') AND u.deceased_at IS NULL
                ORDER BY u.last_active_at DESC NULLS LAST
                LIMIT 20
            """).fetchall()
            return [dict(r) if hasattr(r, 'keys') else
                    {'id': r[0], 'name': r[1], 'age': r[2],
                     'last_active': str(r[3]) if r[3] else None, 'email': r[4]}
                    for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_brain_state(senior_id):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            row = db.execute("""
                SELECT chaos, alpha, valence, arousal, mode, created_at
                FROM brain_states WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
            """, (str(senior_id),)).fetchone()
            if not row:
                return {"info": "No brain state recorded yet"}
            keys = ['chaos', 'alpha', 'valence', 'arousal', 'mode', 'created_at']
            return {k: (str(v) if isinstance(v, datetime) else v) for k, v in zip(keys, row)}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_vitals(senior_id):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = "NOW() - INTERVAL '24 hours'" if is_postgres() else "datetime('now', '-1 day')"
            rows = db.execute(f"""
                SELECT sensor_type, value, recorded_at
                FROM iot_sensor_data
                WHERE user_id = ? AND recorded_at > {interval}
                  AND sensor_type IN ('heart_rate', 'temperature', 'motion', 'spo2')
                ORDER BY recorded_at DESC LIMIT 30
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": "No vitals in last 24h"}
            return [{'type': r[0], 'value': r[1],
                     'at': str(r[2]) if r[2] else None} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_iot_status(senior_id):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = "NOW() - INTERVAL '24 hours'" if is_postgres() else "datetime('now', '-1 day')"
            rows = db.execute(f"""
                SELECT sensor_type, value, recorded_at
                FROM iot_sensor_data
                WHERE user_id = ? AND recorded_at > {interval}
                  AND sensor_type IN ('door', 'motion', 'gas', 'smoke', 'water_leak')
                ORDER BY recorded_at DESC LIMIT 50
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": "No IoT events in last 24h"}
            return [{'type': r[0], 'value': r[1],
                     'at': str(r[2]) if r[2] else None} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_recent_chat(senior_id, n=10):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            rows = db.execute("""
                SELECT role, content, created_at
                FROM memory_history WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
            """, (str(senior_id), int(n))).fetchall()
            if not rows:
                return {"info": "No chat history"}
            return list(reversed([
                {'role': r[0], 'content': (r[1] or '')[:300],
                 'at': str(r[2]) if r[2] else None} for r in rows
            ]))
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_get_observations(senior_id, days=7):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context() as db:
            interval = f"NOW() - INTERVAL '{int(days)} days'" if is_postgres() else f"datetime('now', '-{int(days)} day')"
            rows = db.execute(f"""
                SELECT severity, message, created_at, observation_type
                FROM agent_observations
                WHERE user_id = ? AND created_at > {interval}
                ORDER BY created_at DESC LIMIT 30
            """, (str(senior_id),)).fetchall()
            if not rows:
                return {"info": f"No observations in last {days} days"}
            return [{'severity': r[0], 'message': r[1],
                     'at': str(r[2]) if r[2] else None, 'type': r[3]} for r in rows]
    except Exception as e:
        return {"error": str(e)[:200]}


def _check_action_cooldown(senior_id, action_type='any'):
    """Returns True if action allowed (no recent action on this senior)."""
    if not _DB:
        return True
    try:
        with db_context() as db:
            interval = f"NOW() - INTERVAL '{SENIOR_ACTION_COOLDOWN_MIN} minutes'" if is_postgres() \
                       else f"datetime('now', '-{SENIOR_ACTION_COOLDOWN_MIN} minute')"
            row = db.execute(f"""
                SELECT COUNT(*) FROM agent_observations
                WHERE user_id = ? AND observation_type = 'claude_agent'
                  AND severity IN ('ALERT', 'CRISIS')
                  AND created_at > {interval}
            """, (str(senior_id),)).fetchone()
            return (row[0] if row else 0) == 0
    except Exception:
        return True  # fail open


def _tool_send_chat_message(senior_id, text):
    if not _check_action_cooldown(senior_id):
        return {"skipped": "cooldown active for senior"}
    try:
        # Save as a Radim → senior message in memory_history
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'memory_history',
                      ['user_id', 'role', 'content'],
                      [str(senior_id), 'assistant', text[:500]])
        return {"sent": True, "senior_id": senior_id, "preview": text[:80]}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_send_push(senior_id, title, body):
    try:
        from app import send_push_notification
        result = send_push_notification(str(senior_id), title[:50], body[:200])
        return {"sent": bool(result), "title": title}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_notify_family(senior_id, text, urgency):
    try:
        # Find family contacts
        with db_context() as db:
            rows = db.execute("""
                SELECT family_user_id FROM senior_family_links
                WHERE senior_id = ? LIMIT 5
            """, (str(senior_id),)).fetchall()
        if not rows:
            return {"info": "No family contacts linked"}

        sent = 0
        for r in rows:
            family_id = r[0]
            try:
                with db_context() as db:
                    contact = db.execute("""
                        SELECT phone FROM auth_users WHERE id = ? LIMIT 1
                    """, (family_id,)).fetchone()
                if contact and contact[0]:
                    from twilio_voice_helpers import send_sms
                    prefix = {"low": "ℹ️", "medium": "⚠️", "high": "🚨"}.get(urgency, "ℹ️")
                    send_sms(contact[0], f"{prefix} Radim: {text[:280]}")
                    sent += 1
            except Exception as e:
                logger.warning(f"notify_family contact {family_id}: {e}")

        return {"family_sms_sent": sent, "urgency": urgency}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_initiate_call(senior_id, reason):
    try:
        with db_context() as db:
            row = db.execute("""
                SELECT phone, COALESCE(p.full_name, u.email)
                FROM auth_users u
                LEFT JOIN memory_profiles p ON p.user_id = u.id::text
                WHERE u.id = ? LIMIT 1
            """, (str(senior_id),)).fetchone()
        if not row or not row[0]:
            return {"error": "No phone on file"}

        from twilio_voice_helpers import initiate_proactive_call
        greeting = f"Dobrý den, tady Radim. Chtěl jsem se ujistit, že jste v pořádku. {reason[:100]}"
        result = initiate_proactive_call(row[0], greeting,
                                         user_id=str(senior_id),
                                         reason='claude_agent_crisis',
                                         voice_mode='CRISIS')
        return {"call_initiated": bool(result), "to": row[1] or 'senior'}
    except Exception as e:
        return {"error": str(e)[:200]}


def _tool_create_observation(senior_id, severity, message):
    if not _DB:
        return {"error": "DB not available"}
    try:
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'agent_observations',
                      ['user_id', 'observation_type', 'severity', 'message'],
                      [str(senior_id), 'claude_agent', severity, message[:1000]])
        return {"recorded": True, "severity": severity}
    except Exception as e:
        return {"error": str(e)[:200]}


# Tool dispatcher
TOOL_HANDLERS = {
    'list_seniors': lambda args: _tool_list_seniors(),
    'get_brain_state': lambda args: _tool_get_brain_state(args['senior_id']),
    'get_vitals': lambda args: _tool_get_vitals(args['senior_id']),
    'get_iot_status': lambda args: _tool_get_iot_status(args['senior_id']),
    'get_recent_chat': lambda args: _tool_get_recent_chat(args['senior_id'], args.get('n', 10)),
    'get_observations': lambda args: _tool_get_observations(args['senior_id'], args.get('days', 7)),
    'send_chat_message': lambda args: _tool_send_chat_message(args['senior_id'], args['text']),
    'send_push': lambda args: _tool_send_push(args['senior_id'], args['title'], args['body']),
    'notify_family': lambda args: _tool_notify_family(args['senior_id'], args['text'], args['urgency']),
    'initiate_call': lambda args: _tool_initiate_call(args['senior_id'], args['reason']),
    'create_observation': lambda args: _tool_create_observation(
        args['senior_id'], args['severity'], args['message']),
}


# ═══════════════════════════════════════════════════════════════════════
# COST TRACKING & BUDGET GUARDRAIL
# ═══════════════════════════════════════════════════════════════════════

def _ensure_telemetry_table():
    if not _DB:
        return
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS claude_agent_telemetry (
                        id SERIAL PRIMARY KEY,
                        run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
                        tool_calls INTEGER NOT NULL DEFAULT 0,
                        seniors_evaluated INTEGER NOT NULL DEFAULT 0,
                        actions_taken INTEGER NOT NULL DEFAULT 0,
                        duration_seconds NUMERIC(10,2),
                        summary TEXT,
                        error TEXT
                    )
                """)
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS claude_agent_telemetry (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd REAL NOT NULL DEFAULT 0,
                        tool_calls INTEGER NOT NULL DEFAULT 0,
                        seniors_evaluated INTEGER NOT NULL DEFAULT 0,
                        actions_taken INTEGER NOT NULL DEFAULT 0,
                        duration_seconds REAL,
                        summary TEXT,
                        error TEXT
                    )
                """)
    except Exception as e:
        logger.warning(f"telemetry table init: {e}")


def _today_cost_usd():
    if not _DB:
        return 0.0
    try:
        with db_context() as db:
            interval = "CURRENT_DATE" if is_postgres() else "date('now')"
            row = db.execute(f"""
                SELECT COALESCE(SUM(cost_usd), 0)
                FROM claude_agent_telemetry
                WHERE DATE(run_at) = {interval}
            """).fetchone()
            return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def _record_run(input_tokens, output_tokens, tool_calls, seniors, actions, duration, summary, error=None):
    if not _DB:
        return
    cost = (input_tokens / 1_000_000 * PRICE_INPUT_PER_M +
            output_tokens / 1_000_000 * PRICE_OUTPUT_PER_M)
    try:
        with db_context(commit=True) as db:
            from database import db_insert
            db_insert(db, 'claude_agent_telemetry',
                      ['input_tokens', 'output_tokens', 'cost_usd', 'tool_calls',
                       'seniors_evaluated', 'actions_taken', 'duration_seconds', 'summary', 'error'],
                      [input_tokens, output_tokens, cost, tool_calls,
                       seniors, actions, duration, summary, error])
    except Exception as e:
        logger.warning(f"record_run: {e}")
    return cost


# ═══════════════════════════════════════════════════════════════════════
# AGENT LOOP
# ═══════════════════════════════════════════════════════════════════════

WRITE_TOOLS = {'send_chat_message', 'send_push', 'notify_family', 'initiate_call'}


def run_claude_agent(app=None, trigger='cron', force=False):
    """
    Main entry point. Run autonomous Claude agent for one cycle.

    Args:
        app: Flask app for context (optional)
        trigger: 'cron' / 'manual' / 'event' (audit)
        force: bypass daily budget check (manual override)

    Returns:
        dict with summary and metrics
    """
    if not _CLAUDE_AVAILABLE:
        return {'error': 'anthropic SDK not available'}
    if not os.getenv('ANTHROPIC_API_KEY'):
        return {'error': 'ANTHROPIC_API_KEY not set'}

    _ensure_telemetry_table()

    # Budget check
    if not force:
        spent_today = _today_cost_usd()
        if spent_today >= DAILY_BUDGET_USD:
            logger.warning(f"Claude agent: daily budget ${DAILY_BUDGET_USD} exceeded (${spent_today:.4f}) — skipping")
            return {'skipped': 'daily_budget_exceeded',
                    'spent_today': spent_today, 'budget': DAILY_BUDGET_USD}

    started = time.time()
    client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

    messages = [
        {"role": "user", "content":
         f"Je {datetime.now().strftime('%Y-%m-%d %H:%M')} ({trigger}). "
         "Zkontroluj aktivní seniory, posuď jejich stav a rozhodni o akcích. "
         "Začni `list_seniors`. Na konci VŽDY volej `create_observation` se shrnutím."}
    ]

    total_input = 0
    total_output = 0
    tool_calls_made = 0
    actions_taken = 0
    seniors_seen = set()
    final_text = ""
    error = None

    try:
        if app:
            ctx = app.app_context()
            ctx.__enter__()

        for iteration in range(MAX_TOOL_CALLS_PER_RUN):
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS_PER_RESPONSE,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens

            # Collect text + tool uses from response
            assistant_content = []
            tool_uses = []
            for block in response.content:
                assistant_content.append(block)
                if block.type == 'tool_use':
                    tool_uses.append(block)
                elif block.type == 'text':
                    final_text = block.text  # last text wins as final

            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == 'end_turn' or not tool_uses:
                break

            # Execute tools
            tool_results = []
            for tu in tool_uses:
                tool_calls_made += 1
                handler = TOOL_HANDLERS.get(tu.name)
                if not handler:
                    result = {"error": f"unknown tool: {tu.name}"}
                else:
                    try:
                        result = handler(tu.input)
                    except Exception as e:
                        result = {"error": f"tool exec: {str(e)[:200]}"}
                        logger.exception(f"Tool {tu.name} failed")

                if tu.name in WRITE_TOOLS and not result.get('error') and not result.get('skipped'):
                    actions_taken += 1
                if 'senior_id' in (tu.input or {}):
                    seniors_seen.add(tu.input['senior_id'])

                logger.info(f"[claude_agent] tool={tu.name} args={json.dumps(tu.input)[:120]} "
                            f"result={json.dumps(result)[:120]}")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                })

            messages.append({"role": "user", "content": tool_results})

        if app:
            ctx.__exit__(None, None, None)

    except Exception as e:
        error = str(e)[:500]
        logger.exception("Claude agent run failed")

    duration = time.time() - started
    cost = _record_run(total_input, total_output, tool_calls_made,
                       len(seniors_seen), actions_taken, duration,
                       final_text[:2000], error)

    summary = {
        'trigger': trigger,
        'duration_s': round(duration, 2),
        'iterations': iteration + 1 if 'iteration' in dir() else 0,
        'tool_calls': tool_calls_made,
        'seniors_evaluated': len(seniors_seen),
        'actions_taken': actions_taken,
        'input_tokens': total_input,
        'output_tokens': total_output,
        'cost_usd': round(cost or 0, 4),
        'final_text': final_text[:500],
        'error': error,
    }
    logger.info(f"[claude_agent] DONE: {json.dumps(summary, ensure_ascii=False)[:600]}")
    return summary
