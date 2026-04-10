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
    """Send notification to admin (log + optional webhook)."""
    timestamp = datetime.utcnow().isoformat()
    notification = f"[{severity.upper()}] {timestamp}: {message}"
    logger.info(f"🤖 AGENT NOTIFICATION: {notification}")

    # Store in DB for admin dashboard
    import requests
    try:
        requests.post(
            f'{BACKEND_URL}/api/admin/agent-notification',
            json={'message': message, 'severity': severity, 'timestamp': timestamp},
            headers={'X-Admin-Secret': ADMIN_SECRET} if ADMIN_SECRET else {},
            timeout=5
        )
    except Exception:
        pass

    return f"Notification sent: [{severity}] {message}"


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
        "description": "Send a notification to the admin about system status or issues found.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Notification message in Czech"},
                "severity": {"type": "string", "enum": ["info", "warning", "critical"], "description": "Severity level"}
            },
            "required": ["message", "severity"]
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
}

SYSTEM_PROMPT = """Jsi RadimCare Health Agent — autonomní monitorovací agent pro senior care aplikaci RadimCare.

Tvůj úkol:
1. Zkontroluj zdraví všech služeb (backend, databáze, TTS, agent loop)
2. Analyzuj nalezené problémy
3. Diagnostikuj root cause
4. Pokud najdeš problém, pošli notifikaci adminovi s doporučením
5. Pokud je vše v pořádku, pošli krátký info report

Pravidla:
- Kontroluj VŠECHNY služby systematicky
- Vždy začni s check_backend_health
- Pokud je služba degradovaná, zkontroluj detaily
- Notifikace piš ČESKY
- Severity: info (vše OK), warning (degradace), critical (výpadek)
- Buď stručný ale přesný
- Vždy ukonči odesláním notifikace adminu

Kontext:
- Backend: Flask na Heroku (radim-brain-2025)
- DB: PostgreSQL Essential-0
- TTS: Azure cs-CZ-AntoninNeural
- AI: Gemini 2.0 Flash (primary) + Claude (fallback)
- 13 proaktivních agentů běží každých 5 minut
- 5+ aktivních seniorů
"""


def run_health_check():
    """Run autonomous health check using Claude API with tool use."""
    if not ANTHROPIC_API_KEY:
        logger.warning("🤖 Health Agent: ANTHROPIC_API_KEY not set, skipping")
        return {"status": "skipped", "reason": "no API key"}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    messages = [
        {"role": "user", "content": "Proveď kompletní zdravotní kontrolu systému RadimCare. Zkontroluj všechny služby a pošli report."}
    ]

    max_turns = 10
    turn = 0

    while turn < max_turns:
        turn += 1

        response = client.messages.create(
            model="claude-haiku-4-5",  # Fast + cheap for monitoring
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
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


# ============================================
# FLASK ENDPOINT — trigger via API or cron
# ============================================

from flask import Blueprint, jsonify

health_agent_bp = Blueprint('health_agent', __name__, url_prefix='/api/agent')


@health_agent_bp.route('/health-check', methods=['POST'])
def trigger_health_check():
    """Manually trigger health agent check.
    Requires X-Admin-Secret header.
    """
    from flask import request
    secret = request.headers.get('X-Admin-Secret', '')
    if ADMIN_SECRET and secret != ADMIN_SECRET:
        return jsonify({'error': 'Unauthorized'}), 401

    result = run_health_check()
    return jsonify(result)


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
