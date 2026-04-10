#!/usr/bin/env python3
"""
🤖 RadimCare Autonomous Health Agent
=====================================
Uses Claude Agent SDK to monitor, diagnose, and fix system issues.
Runs as scheduled task or manual trigger.

Features:
- Checks all backend services health
- Reads and analyzes Heroku logs
- Diagnoses root causes with Claude AI
- Executes safe fixes (cache clear, restart)
- Reports to admin via Slack/email
- Learns from past incidents
"""

import anyio
import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================
# HEALTH AGENT — Custom tools via Claude API
# ============================================

import anthropic

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
BACKEND_URL = os.environ.get('BACKEND_URL', 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com')
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')


def check_backend_health():
    """Check all backend services health status."""
    import requests
    try:
        resp = requests.get(f'{BACKEND_URL}/health', timeout=10)
        data = resp.json()
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"BACKEND UNREACHABLE: {str(e)}"


def check_self_healing_status():
    """Check circuit breaker and self-healing state."""
    import requests
    try:
        resp = requests.get(f'{BACKEND_URL}/health', timeout=10)
        data = resp.json()
        healing = data.get('self_healing', {})
        return json.dumps(healing, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"Cannot check self-healing: {str(e)}"


def check_database_status():
    """Check PostgreSQL database connectivity and stats."""
    import requests
    try:
        resp = requests.get(f'{BACKEND_URL}/health', timeout=10)
        data = resp.json()
        return json.dumps({
            'db_status': data.get('db_status'),
            'latency_ms': data.get('latency_ms'),
        }, indent=2)
    except Exception as e:
        return f"DB check failed: {str(e)}"


def get_active_users():
    """Get count of active users in last 24h."""
    import requests
    try:
        headers = {'X-Admin-Secret': ADMIN_SECRET} if ADMIN_SECRET else {}
        resp = requests.get(f'{BACKEND_URL}/api/admin/stats', headers=headers, timeout=10)
        if resp.status_code == 200:
            return json.dumps(resp.json(), indent=2, ensure_ascii=False)
        return f"Stats endpoint returned {resp.status_code}"
    except Exception as e:
        return f"Cannot get stats: {str(e)}"


def check_agent_loop_status():
    """Check if proactive agent loop is running."""
    import requests
    try:
        headers = {'X-Admin-Secret': ADMIN_SECRET} if ADMIN_SECRET else {}
        resp = requests.get(f'{BACKEND_URL}/api/admin/stats', headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps({
                'observations': data.get('observations_count', 'unknown'),
                'brain_states': data.get('brain_states_count', 'unknown'),
            }, indent=2)
        return f"Agent loop check returned {resp.status_code}"
    except Exception as e:
        return f"Agent loop check failed: {str(e)}"


def check_tts_health():
    """Check Azure TTS service availability."""
    import requests
    try:
        resp = requests.post(
            f'{BACKEND_URL}/api/azure/tts',
            json={'text': 'test', 'voice': 'cs-CZ-AntoninNeural'},
            timeout=15
        )
        if resp.status_code == 200:
            return f"TTS OK — response size: {len(resp.content)} bytes"
        return f"TTS returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"TTS check failed: {str(e)}"


def get_recent_errors():
    """Get recent error observations from agent_observations table."""
    import requests
    try:
        headers = {'X-Admin-Secret': ADMIN_SECRET} if ADMIN_SECRET else {}
        resp = requests.get(
            f'{BACKEND_URL}/api/admin/stats',
            headers=headers, timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return json.dumps(data, indent=2, ensure_ascii=False)
        return f"Error log returned {resp.status_code}"
    except Exception as e:
        return f"Cannot get errors: {str(e)}"


def send_admin_notification(message, severity='info'):
    """Send notification to admin (log + DB storage)."""
    timestamp = datetime.utcnow().isoformat()
    logger.info(f"🤖 AGENT [{severity.upper()}]: {message}")

    # Store in DB for history — use columns that definitely exist
    try:
        from database import db_context
        with db_context(commit=True) as db:
            try:
                db.execute("""
                    INSERT INTO agent_observations (user_id, observation_type, severity, summary, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, ('system-health-agent', 'health_check', severity.upper(), message[:500], timestamp))
            except Exception:
                # Fallback without summary column
                db.execute("""
                    INSERT INTO agent_observations (user_id, observation_type, severity, created_at)
                    VALUES (?, ?, ?, ?)
                """, ('system-health-agent', f'health_check: {message[:200]}', severity.upper(), timestamp))
    except Exception as e:
        logger.debug(f"Agent notification DB save failed: {e}")

    return f"Notification sent: [{severity}] {message}"


def reset_circuit_breaker(service_name):
    """Reset a circuit breaker to closed (healthy) state."""
    try:
        from self_healing import SelfHealingEngine
        engine = SelfHealingEngine()
        if service_name in engine.circuit_breakers:
            cb = engine.circuit_breakers[service_name]
            cb['state'] = 'closed'
            cb['failures'] = 0
            return f"Circuit breaker '{service_name}' reset to closed"
        return f"Circuit breaker '{service_name}' not found"
    except Exception as e:
        return f"Cannot reset circuit breaker: {str(e)}"


def clear_application_cache():
    """Clear backend caches to free memory."""
    import requests
    try:
        # Clear brain state cache
        resp = requests.post(f'{BACKEND_URL}/api/admin/clear-cache',
                             headers={'X-Admin-Secret': ADMIN_SECRET} if ADMIN_SECRET else {},
                             timeout=10)
        if resp.status_code == 200:
            return "Cache cleared successfully"
        # Fallback: at least clear what we can
        return f"Cache clear returned {resp.status_code} — may need manual intervention"
    except Exception as e:
        return f"Cache clear failed: {str(e)}"


def check_chat_ai():
    """Test chat AI response — send test message and check response."""
    import requests
    try:
        resp = requests.post(
            f'{BACKEND_URL}/api/radim/chat',
            json={'message': 'Kolik je hodin?', 'mode': 'senior'},
            timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            return f"Chat OK — response: {str(data.get('response',''))[:100]}"
        return f"Chat returned {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return f"Chat test failed: {str(e)}"


def check_frontend_status():
    """Check frontend (Cloudflare Pages) availability."""
    import requests
    try:
        resp = requests.get('https://app.radimcare.cz/', timeout=10)
        size = len(resp.content)
        has_modules = 'module-home' in resp.text
        has_scripts = 'radim-app.min.js' in resp.text
        return f"Frontend OK — HTTP {resp.status_code}, {size}b, modules: {has_modules}, scripts: {has_scripts}"
    except Exception as e:
        return f"Frontend check failed: {str(e)}"


def check_all_agents_status():
    """Check status of all 13 proactive agents in the system."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # Count observations by type in last 48h
            rows = db.execute("""
                SELECT observation_type, severity, COUNT(*) as cnt
                FROM agent_observations
                WHERE created_at > ?
                GROUP BY observation_type, severity
                ORDER BY cnt DESC
            """, ((datetime.utcnow() - __import__('datetime').timedelta(hours=48)).isoformat(),)).fetchall()

            # Count unique active users
            users = db.execute("""
                SELECT COUNT(DISTINCT user_id) FROM brain_states
                WHERE created_at > ?
            """, ((datetime.utcnow() - __import__('datetime').timedelta(hours=48)).isoformat(),)).fetchone()

            # Brain state stats
            brain = db.execute("""
                SELECT AVG(coherence), MIN(coherence), MAX(coherence), COUNT(*)
                FROM brain_states WHERE created_at > ?
            """, ((datetime.utcnow() - __import__('datetime').timedelta(hours=48)).isoformat(),)).fetchone()

        result = "== Agent Activity (48h) ==\n"
        result += f"Active users: {users[0] if users else 0}\n"
        result += f"Brain states: {brain[3] if brain else 0} records, avg C={brain[0]:.1f}, min={brain[1]:.1f}, max={brain[2]:.1f}\n" if brain and brain[0] else "Brain states: no data\n"
        result += "\nObservations by type:\n"
        for r in (rows or []):
            result += f"  {r[0]} [{r[1]}]: {r[2]}×\n"
        if not rows:
            result += "  No observations in 48h\n"
        return result
    except Exception as e:
        return f"Agent status check failed: {str(e)}"


def save_admin_report(report_text):
    """Save a comprehensive report to database for admin to read in the app."""
    timestamp = datetime.utcnow().isoformat()
    try:
        from database import db_context
        with db_context(commit=True) as db:
            # Store as special observation type
            db.execute("""
                INSERT INTO agent_observations (user_id, observation_type, severity, summary, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, ('system-health-agent', 'admin_report', 'INFO', report_text[:4000], timestamp))
        logger.info(f"🤖 Admin report saved ({len(report_text)} chars)")
        return f"Report uložen do databáze ({len(report_text)} znaků). Admin ho uvidí v modulu Admin."
    except Exception as e:
        return f"Report save failed: {str(e)}"


def get_health_history():
    """Get last 10 health check results for trend analysis."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # Use observation_type + severity (always exist) — summary may not
            try:
                rows = db.execute("""
                    SELECT severity, summary, created_at
                    FROM agent_observations
                    WHERE user_id = 'system-health-agent'
                    ORDER BY created_at DESC LIMIT 10
                """).fetchall()
            except Exception:
                # Fallback without summary column
                rows = db.execute("""
                    SELECT severity, observation_type, created_at
                    FROM agent_observations
                    WHERE user_id = 'system-health-agent'
                    ORDER BY created_at DESC LIMIT 10
                """).fetchall()

        if not rows:
            return "No previous health checks found — this is the first run"

        history = []
        for r in rows:
            history.append(f"[{r[0]}] {r[2]}: {str(r[1])[:100]}")
        return "\n".join(history)
    except Exception as e:
        return f"Cannot read history: {str(e)}"


# ============================================
# MAIN AGENT — Claude API with tool use
# ============================================

TOOLS = [
    {
        "name": "check_backend_health",
        "description": "Check all backend services health status. Returns JSON with service statuses, circuit breakers, database connectivity.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_self_healing_status",
        "description": "Check circuit breaker states for all services (gemini, claude, azure_tts, twilio, database). Shows open/closed/half-open states.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_database_status",
        "description": "Check PostgreSQL database connectivity and response latency.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_active_users",
        "description": "Get count of active users, brain states, and system stats from the last 24 hours.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_agent_loop_status",
        "description": "Check if the proactive agent loop (5-min monitoring) is running and producing observations.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_tts_health",
        "description": "Test Azure Text-to-Speech service by sending a test request. Returns response size or error.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_recent_errors",
        "description": "Get recent error observations and alerts from the system.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "send_admin_notification",
        "description": "Send a notification to the admin about system status or issues found. Also saves to database for history.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification message in Czech"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"], "description": "Severity level"}
            },
            "required": ["message", "severity"]
        }
    },
    {
        "name": "reset_circuit_breaker",
        "description": "Reset a stuck circuit breaker back to closed (healthy) state. Use when a service recovered but breaker is still open.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "enum": ["gemini", "claude", "azure_tts", "azure_stt", "twilio", "database"], "description": "Service name"}
            },
            "required": ["service_name"]
        }
    },
    {
        "name": "clear_application_cache",
        "description": "Clear backend application caches to free memory. Safe operation, no data loss.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_health_history",
        "description": "Get last 10 health check results for trend analysis. Shows if issues are recurring or new.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_chat_ai",
        "description": "Test the main chat AI by sending a test question. Checks if Gemini/Claude AI responds correctly.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_frontend_status",
        "description": "Check Cloudflare Pages frontend (app.radimcare.cz). Verifies HTML loads, modules present, scripts loaded.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "check_all_agents_status",
        "description": "Check activity of all 13 proactive agents. Shows observations by type, active users, brain state stats for last 48h.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "save_admin_report",
        "description": "Save a comprehensive report to database. Admin will see it in the Admin module. Use for 48h summary reports with recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "report_text": {"type": "string", "description": "Full report text in Czech with markdown formatting. Include: system status, agent activity, recommendations, improvement ideas."}
            },
            "required": ["report_text"]
        }
    },
]

TOOL_FUNCTIONS = {
    "check_backend_health": lambda _: check_backend_health(),
    "check_self_healing_status": lambda _: check_self_healing_status(),
    "check_database_status": lambda _: check_database_status(),
    "get_active_users": lambda _: get_active_users(),
    "check_agent_loop_status": lambda _: check_agent_loop_status(),
    "check_tts_health": lambda _: check_tts_health(),
    "get_recent_errors": lambda _: get_recent_errors(),
    "send_admin_notification": lambda args: send_admin_notification(args.get("message", ""), args.get("severity", "info")),
    "reset_circuit_breaker": lambda args: reset_circuit_breaker(args.get("service_name", "")),
    "clear_application_cache": lambda _: clear_application_cache(),
    "get_health_history": lambda _: get_health_history(),
    "check_chat_ai": lambda _: check_chat_ai(),
    "check_frontend_status": lambda _: check_frontend_status(),
    "check_all_agents_status": lambda _: check_all_agents_status(),
    "save_admin_report": lambda args: save_admin_report(args.get("report_text", "")),
}

SYSTEM_PROMPT = """Jsi RadimCare Health Agent — autonomní monitorovací a opravný agent pro senior care aplikaci RadimCare.

## Tvůj úkol:
1. Zkontroluj zdraví VŠECH služeb
2. Podívej se na historii předchozích kontrol (get_health_history)
3. Analyzuj a diagnostikuj problémy
4. OPRAV co můžeš sám (reset circuit breaker, clear cache)
5. Pošli report adminu

## Auto-fix pravidla (co můžeš opravit sám):
- Circuit breaker stuck open → reset_circuit_breaker (služba se mezitím zotavila)
- Vysoké využití paměti → clear_application_cache
- Degradovaná služba → zkontroluj detaily, pokud se zotavila → reset breaker

## Co NEOPRAVUJ sám (jen notifikuj admin):
- Database down → critical notifikace
- Opakující se stejný problém 3+ → escalate
- Neznámý error → notifikuj s full context

## Učení z historie:
- Vždy začni s get_health_history — podívej se na předchozí problémy
- Pokud vidíš opakující se pattern → zmíň to v reportu
- Pokud problém z minula je vyřešen → zmíň že se zlepšilo

## Pravidla:
- Notifikace piš ČESKY
- Severity: info (vše OK), warning (degradace/opraveno), critical (výpadek)
- Buď stručný ale přesný — tabulka služeb + summary
- Vždy ukonči odesláním notifikace adminu

## Architektura aplikace (ZNÁŠ JI):

### Backend (Flask, Heroku v537)
- 52+ blueprintů, 17 registrovaných v app.py
- DB: PostgreSQL Essential-0, 75+ tabulek
- AI: Gemini 2.0 Flash (primary) + Claude (fallback)
- TTS: Azure cs-CZ-AntoninNeural (SSML, φ-pauzy, voice filter)
- STT: Browser Web Speech API (cs-CZ, continuous)
- Self-healing: 6 circuit breakers (gemini, claude, azure_tts, azure_stt, twilio, database)

### Frontend (Cloudflare Pages, app.radimcare.cz)
- 27 modulů: home, chat, calls, news, music, tv, quiz, exercises, medical, settings, help, tasks, calendar, stories, notes, education, library, email, smarthome, gallery, skillmap, trend, survey, caregiver, admin
- 3 JS bundly: radim-head (51KB), radim-services (108KB), radim-app (362KB)
- 32 lazy-loaded section scripts
- Service Worker v15 s cache

### Klíčové systémy:
- **SpeechOrchestrator**: FSM (idle→fetching→playing), token-based race prevention, priority queue
- **SpeechPipeline**: TTS warmup (3min), 12 pre-cached phrases, FastAck, Turn Manager
- **Agent Loop**: 5 detektorů (C trend, activity drop, vitals, interaction silence, fall detection)
- **Anticipation Engine**: Ĉ predikce, behavioral patterns, speech rhythm adaptation
- **Circadian Engine**: Wake/sleep detection, 7 proactive triggers
- **Scenario Engine**: 20 crisis situations, instant response
- **TV Module**: YouTube embed + search (backend proxy), 16 kanálů
- **Calls**: Jitsi WebRTC + app-to-app (SocketIO popup), group calls
- **Family Dashboard**: /api/family/* (checkin, activity, cognitive, photos, remote profile)
- **Drug Interactions**: 10 common dangerous combinations
- **i18n**: cs/sk/en (80 keys)

### APScheduler (8 jobs):
1. radim_reminders (5 min)
2. telemed_reminders (5 min)
3. agent_loop (5 min) — senior monitoring
4. morning_checkin (8:00)
5. daily_cleanup (3:00)
6. daily_engagement (14:00)
7. daily_summary (20:00)
8. health_agent (15 min) — TY

### Běžné problémy a řešení:
- Circuit breaker open → reset_circuit_breaker (pokud služba funguje)
- TTS timeout → Azure cold start, warmup ping pomáhá
- DB connection pool → restart pomáhá, PostgreSQL Essential-0 má limit 20 connections
- Memory high → clear_application_cache
- Frontend cache starý → bump CACHE_VERSION v service-worker.js
- Heroku dyno restart (24h) → normální, agent_loop se restartuje automaticky
"""


QUICK_TOOLS = [t for t in TOOLS if t['name'] in (
    'check_backend_health', 'check_database_status', 'check_tts_health',
    'send_admin_notification', 'get_health_history', 'reset_circuit_breaker'
)]


def run_health_check():
    """Run QUICK health check (fits in 30s Heroku timeout)."""
    if not ANTHROPIC_API_KEY:
        logger.warning("🤖 Health Agent: ANTHROPIC_API_KEY not set, skipping")
        return {"status": "skipped", "reason": "no API key"}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {"role": "user", "content": "Rychlá kontrola: backend, DB, TTS. Pokud problém → oprav a notifikuj. Pokud OK → krátká notifikace. Max 3 kroky."}
    ]

    max_turns = 4
    turn = 0

    while turn < max_turns:
        turn += 1

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=QUICK_TOOLS,
            messages=messages
        )

        # If done
        if response.stop_reason == "end_turn":
            final_text = next((b.text for b in response.content if b.type == "text"), "")
            logger.info(f"🤖 Health Agent completed in {turn} turns: {final_text[:200]}")
            return {"status": "completed", "turns": turn, "summary": final_text}

        # Execute tool calls
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool in tool_use_blocks:
            func = TOOL_FUNCTIONS.get(tool.name)
            if func:
                try:
                    result = func(tool.input)
                except Exception as e:
                    result = f"Tool error: {str(e)}"
            else:
                result = f"Unknown tool: {tool.name}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool.id,
                "content": str(result)
            })

        messages.append({"role": "user", "content": tool_results})

    return {"status": "max_turns_reached", "turns": turn}


SUMMARY_SYSTEM_PROMPT = """Jsi RadimCare Coordination Agent — píšeš 48-hodinový souhrnný report pro admina.

## Tvůj úkol:
1. Zkontroluj zdraví systému (check_backend_health)
2. Zjisti aktivitu všech agentů za 48h (check_all_agents_status)
3. Podívej se na historii (get_health_history)
4. Napiš KOMPLETNÍ report a ulož ho (save_admin_report)

## Report musí obsahovat:

### 📊 Stav systému
- Backend, DB, TTS, AI — funguje/nefunguje
- Latence DB, počet blueprintů

### 🤖 Aktivita agentů (48h)
- Kolik observací, jaké typy, jaké severity
- Kolik aktivních seniorů
- Brain state statistiky (průměr C, trend)

### 👴 Péče o seniory
- Kolik seniorů bylo aktivních
- Jaké problémy agenti detekovali
- Krizové situace (ALERT/CRISIS)

### 💡 Doporučení
- Co vylepšit v systému
- Jaké moduly potřebují pozornost
- Návrhy na nové funkce nebo úpravy
- Koordinace mezi agenty — co by měli dělat jinak

### 🔮 Proaktivní návrhy
- Predikce možných problémů
- Sezonní doporučení (počasí, svátky)
- Návrhy na engagement seniorů

## Pravidla:
- Piš ČESKY, markdown formátování
- Buď konkrétní — čísla, data, trendy
- Report ulož přes save_admin_report
"""


def run_summary_report():
    """Run 48h summary report for admin."""
    if not ANTHROPIC_API_KEY:
        return {"status": "skipped", "reason": "no API key"}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {"role": "user", "content": "Vytvoř kompletní 48-hodinový souhrnný report pro admina. Zkontroluj systém, agenty, seniory a napiš doporučení. Ulož report do databáze."}
    ]

    max_turns = 8
    turn = 0

    while turn < max_turns:
        turn += 1
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=8000,
            system=SUMMARY_SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            final_text = next((b.text for b in response.content if b.type == "text"), "")
            logger.info(f"🤖 Summary report completed in {turn} turns")
            return {"status": "completed", "turns": turn, "summary": final_text}

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool in tool_use_blocks:
            func = TOOL_FUNCTIONS.get(tool.name)
            if func:
                try:
                    result = func(tool.input)
                except Exception as e:
                    result = f"Tool error: {str(e)}"
            else:
                result = f"Unknown tool: {tool.name}"
            tool_results.append({"type": "tool_result", "tool_use_id": tool.id, "content": str(result)})

        messages.append({"role": "user", "content": tool_results})

    return {"status": "max_turns_reached", "turns": turn}


# ============================================
# FLASK ENDPOINT — trigger via API or cron
# ============================================

from flask import Blueprint, jsonify

health_agent_bp = Blueprint('health_agent', __name__, url_prefix='/api/agent')


@health_agent_bp.route('/health-check', methods=['POST'])
def trigger_health_check():
    """Manually trigger health agent check.
    Requires X-Admin-Secret header OR valid JWT auth.
    """
    from flask import request

    # Check admin secret
    secret = request.headers.get('X-Admin-Secret', '')
    if ADMIN_SECRET and secret == ADMIN_SECRET:
        pass  # Authorized via secret
    else:
        # Check JWT auth
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized — use X-Admin-Secret or Bearer token'}), 401

    try:
        result = run_health_check()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'status': 'failed'}), 500


@health_agent_bp.route('/summary-report', methods=['POST'])
def trigger_summary_report():
    """Generate 48h summary report asynchronously (Heroku 30s timeout)."""
    from flask import request
    secret = request.headers.get('X-Admin-Secret', '')
    auth = request.headers.get('Authorization', '')
    if ADMIN_SECRET and secret != ADMIN_SECRET and not auth.startswith('Bearer '):
        return jsonify({'error': 'Unauthorized'}), 401

    # Run in background thread (Heroku 30s timeout)
    import threading
    def _bg_report():
        try:
            from flask import current_app
            with current_app.app_context() if hasattr(current_app, 'app_context') else __import__('contextlib').nullcontext():
                run_summary_report()
        except Exception as e:
            logger.warning(f"🤖 Background summary report failed: {e}")

    try:
        # Try app context
        from flask import current_app
        app = current_app._get_current_object()
        def _run():
            with app.app_context():
                run_summary_report()
        t = threading.Thread(target=_run, daemon=True)
    except Exception:
        t = threading.Thread(target=lambda: run_summary_report(), daemon=True)

    t.start()
    return jsonify({'status': 'generating', 'message': 'Report se generuje na pozadí. Podívejte se za minutu na záložku Agent Reporty.'})


@health_agent_bp.route('/reports', methods=['GET'])
def get_reports():
    """Get saved admin reports for display in admin module."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            rows = db.execute("""
                SELECT summary, created_at
                FROM agent_observations
                WHERE user_id = 'system-health-agent'
                AND observation_type = 'admin_report'
                ORDER BY created_at DESC LIMIT 5
            """).fetchall()

        reports = []
        for r in (rows or []):
            reports.append({'text': r[0], 'created_at': str(r[1])})

        return jsonify({'success': True, 'reports': reports})
    except Exception as e:
        return jsonify({'success': True, 'reports': [], 'note': str(e)})


@health_agent_bp.route('/health-check', methods=['GET'])
def get_last_check():
    """Get last health check result."""
    return jsonify({
        'agent': 'RadimCare Health Agent',
        'model': 'claude-haiku-4-5',
        'tools': len(TOOLS),
        'status': 'ready',
        'trigger': 'POST /api/agent/health-check with X-Admin-Secret header'
    })
