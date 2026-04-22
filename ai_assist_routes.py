"""
🤖 AI Assist Routes — task-specific Gemini/Claude calls for Komunikace v2.6 (Sprint L)

Single endpoint that branches by `task`:
  - suggest_replies  → 3 short reply chips for incoming message
  - translate        → detect + translate text to Czech
  - summarize        → shorten long text to 1–2 sentences
  - extract_event    → parse date/time/title for calendar add
  - explain_word     → senior-friendly definition

All tasks share rate-limit + JWT-optional auth pattern from chat_routes.
Powered by ai_bridge.get_ai_response (Gemini primary, Claude fallback).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from ai_bridge import get_ai_response
from auth_middleware import optional_auth
from rate_limiter import rate_limit

logger = logging.getLogger(__name__)
ai_assist_bp = Blueprint('ai_assist', __name__)

MAX_INPUT_LEN = 2000

# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _ai_call(system_prompt: str, user_prompt: str, max_tokens: int = 300) -> str:
    """Call Gemini/Claude with simple system+user prompts. Returns raw text."""
    msgs = [{'role': 'user', 'content': f"{system_prompt}\n\n---\n\n{user_prompt}"}]
    try:
        resp = get_ai_response(msgs, context=None)
        if isinstance(resp, dict):
            return str(resp.get('text') or resp.get('content') or resp.get('reply') or '').strip()
        return str(resp or '').strip()
    except Exception as e:
        logger.error(f'_ai_call error: {e}')
        return ''


def _parse_json_loose(text: str):
    """Try to parse JSON from possibly-markdown-wrapped text."""
    if not text:
        return None
    # Strip ```json ... ``` fences
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        # Try to find first JSON object/array in text
        m = re.search(r'(\{.*\}|\[.*\])', cleaned, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                return None
    return None


# ──────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────

@ai_assist_bp.route('/api/ai/assist', methods=['POST'])
@optional_auth
@rate_limit(20, 60, 'ip')
def ai_assist():
    try:
        data = request.get_json() or {}
        task = str(data.get('task', '')).strip().lower()
        if task not in {'suggest_replies', 'translate', 'summarize',
                        'extract_event', 'explain_word'}:
            return jsonify({'success': False, 'error': 'Unknown task'}), 400

        if task == 'suggest_replies':
            return _suggest_replies(data)
        if task == 'translate':
            return _translate(data)
        if task == 'summarize':
            return _summarize(data)
        if task == 'extract_event':
            return _extract_event(data)
        if task == 'explain_word':
            return _explain_word(data)
    except Exception as e:
        logger.error(f'ai_assist error: {e}')
        return jsonify({'success': False, 'error': 'Interní chyba'}), 500


# ──────────────────────────────────────────────────────────────────
# Task implementations
# ──────────────────────────────────────────────────────────────────

def _suggest_replies(data):
    """Suggest 3 short, natural replies in Czech for the given context.

    payload: {
      lastMessage: { authorName, content, type },
      conversation: { isGroup, name, contactName },
      recentHistory: [{authorName, content}, ...]  (last 5)
    }
    """
    payload = data.get('payload') or {}
    last = payload.get('lastMessage') or {}
    history = payload.get('recentHistory') or []
    last_text = str(last.get('content') or '')[:MAX_INPUT_LEN]
    if not last_text:
        return jsonify({'success': True, 'result': []})

    history_str = '\n'.join(
        f"- {m.get('authorName','?')}: {str(m.get('content',''))[:200]}"
        for m in history[-5:]
    )
    system = (
        "Jsi laskavý český asistent pro seniora. "
        "Navrhni 3 KRÁTKÉ odpovědi (max 8 slov každá) na poslední zprávu "
        "v rozhovoru. Odpovídej jen jako JSON pole stringů, např: "
        '["Ano, díky", "Zavolám později", "Zatím ne"]. '
        "Odpovědi musí být přirozené, srdečné a v češtině."
    )
    user = (
        f"Poslední zpráva ({last.get('authorName','Někdo')}): \"{last_text}\"\n\n"
        f"Předchozí zprávy:\n{history_str}\n\n"
        "Vrať jen JSON pole 3 odpovědí."
    )
    raw = _ai_call(system, user, max_tokens=200)
    arr = _parse_json_loose(raw)
    if not isinstance(arr, list):
        # Fallback: split by newlines
        arr = [l.strip(' "\'-•') for l in raw.split('\n') if l.strip()][:3]
    arr = [str(x)[:80] for x in arr if str(x).strip()][:3]
    return jsonify({'success': True, 'result': arr})


def _translate(data):
    """Detect language + translate to Czech (or specified target)."""
    payload = data.get('payload') or {}
    text = str(payload.get('text') or '')[:MAX_INPUT_LEN]
    target = str(payload.get('target') or 'čeština').strip()[:20]
    if not text:
        return jsonify({'success': True, 'result': {'translated': '', 'detected': '?'}})
    system = (
        f"Jsi překladatel. Detekuj jazyk vstupního textu a přelož ho do "
        f"jazyka: {target}. Odpověz jen JSON: "
        '{"detected": "název jazyka", "translated": "překlad"}'
    )
    raw = _ai_call(system, text, max_tokens=400)
    obj = _parse_json_loose(raw) or {}
    return jsonify({'success': True, 'result': {
        'detected': str(obj.get('detected', '?'))[:50],
        'translated': str(obj.get('translated', ''))[:1500],
    }})


def _summarize(data):
    """Summarize long text in Czech, 1–2 sentences, friendly tone."""
    payload = data.get('payload') or {}
    text = str(payload.get('text') or '')[:MAX_INPUT_LEN]
    if not text:
        return jsonify({'success': True, 'result': ''})
    system = (
        "Jsi laskavý český asistent. Shrň následující zprávu pro seniora "
        "do 1–2 vět v jednoduché češtině. Zachovej hlavní informaci, "
        "vynech detaily. Odpověz jen samotným shrnutím, bez dalšího textu."
    )
    raw = _ai_call(system, text, max_tokens=160)
    return jsonify({'success': True, 'result': raw[:400]})


def _extract_event(data):
    """Extract calendar-event candidate (title, date, time, who) from text."""
    payload = data.get('payload') or {}
    text = str(payload.get('text') or '')[:MAX_INPUT_LEN]
    if not text:
        return jsonify({'success': True, 'result': None})

    today = datetime.now().strftime('%Y-%m-%d (%A)')
    system = (
        f"Dnes je {today}. Z následující české zprávy vytáhni informace "
        "o události (schůzce, návštěvě, akci). Pokud žádná není, vrať null. "
        "Jinak odpověz JSON: "
        '{"title": "krátký název", "date": "YYYY-MM-DD", '
        '"time": "HH:MM nebo prázdné", "duration_min": 60, '
        '"who": "kdo se účastní", "notes": "krátká poznámka"}. '
        "Pokud datum není explicitní, odhadni z kontextu (\"středu\" → "
        "nejbližší středa, \"zítra\" → +1 den)."
    )
    raw = _ai_call(system, text, max_tokens=240)
    obj = _parse_json_loose(raw)
    if obj is None or (isinstance(obj, dict) and not obj):
        return jsonify({'success': True, 'result': None})
    if not isinstance(obj, dict):
        return jsonify({'success': True, 'result': None})
    # Sanitize
    result = {
        'title': str(obj.get('title', ''))[:100],
        'date': str(obj.get('date', ''))[:10],
        'time': str(obj.get('time', ''))[:5],
        'duration_min': int(obj.get('duration_min', 60) or 60),
        'who': str(obj.get('who', ''))[:100],
        'notes': str(obj.get('notes', ''))[:200],
    }
    if not result['title'] and not result['date']:
        return jsonify({'success': True, 'result': None})
    return jsonify({'success': True, 'result': result})


def _explain_word(data):
    """Senior-friendly explanation of a word/phrase."""
    payload = data.get('payload') or {}
    word = str(payload.get('word') or '')[:120]
    context = str(payload.get('context') or '')[:500]
    if not word:
        return jsonify({'success': True, 'result': ''})
    system = (
        "Jsi laskavý český slovník pro seniora. Vysvětli slovo nebo "
        "spojení jednoduchými větami (max 2 věty). Pokud je to cizí "
        "slovo, řekni i odkud pochází. Odpověz jen samotným vysvětlením."
    )
    user = f"Slovo: {word}" + (f"\nKontext: {context}" if context else '')
    raw = _ai_call(system, user, max_tokens=180)
    return jsonify({'success': True, 'result': raw[:400]})
