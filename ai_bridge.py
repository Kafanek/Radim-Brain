# ============================================
# AI BRIDGE — Gemini + Claude Integration
# ============================================
# Centralized AI provider calls used by chat routes,
# admin routes, and the Radim system prompt.
# ============================================

import os
import logging
import requests as http_requests
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# System prompt — centralized in radim_system_prompt.py
try:
    from radim_system_prompt import get_chat_prompt
    RADIM_SYSTEM_PROMPT = get_chat_prompt()
except ImportError:
    RADIM_SYSTEM_PROMPT = "Jsi Radim, přátelský český AI asistent."
    logger.warning("radim_system_prompt.py not found, using fallback prompt")


def call_gemini_ai(messages, context=None, image=None):
    """Volání Gemini AI pro Radima"""
    if not GEMINI_API_KEY:
        return None

    try:
        conversation_text = ""
        for msg in messages[-10:]:
            role = "Uživatel" if msg.get('sender_id') != 'radim' else "Radim"
            conversation_text += f"{role}: {msg.get('content', '')}\n"

        prompt = f"{RADIM_SYSTEM_PROMPT}\n\nKonverzace:\n{conversation_text}\nRadim:"

        parts = [{"text": prompt}]

        if image:
            if image.startswith("data:"):
                image = image.split(",")[1]
            parts.insert(0, {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image
                }
            })

        response = http_requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.7,
                    # Bug-fix (komunikace "Mám" / "abych ti nasl" truncation):
                    #
                    #   ROOT CAUSE Gemini 2.5 Flash:
                    #     Gemini 2.5+ rodina má THINKING tokens (interní
                    #     reasoning), které se počítají PROTI maxOutputTokens
                    #     PŘED viditelnou odpovědí. Když Radim "myslí" za
                    #     ~400 tokenů, na text zbude ~20 → useknuté slovo.
                    #
                    #   Fix dvojí (belt + suspenders):
                    #     1) thinkingBudget = 0 → vypneme reasoning úplně.
                    #        Pro senior chat nepotřebujeme deep reasoning,
                    #        jen rychlou empatickou odpověď. Bonus: nižší
                    #        latence + cena.
                    #     2) maxOutputTokens 500 → 1500 jako safety net,
                    #        kdyby thinkingConfig nebyl podporovaný v
                    #        budoucích verzích modelu.
                    "maxOutputTokens": 1500,
                    "topP": 0.9,
                    "thinkingConfig": {
                        "thinkingBudget": 0
                    }
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            },
            timeout=22  # B1: tightened pod Heroku 30s router buffer
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('candidates'):
                # Bug-fix (komunikace "Mám" truncation):
                #   PŘEDTÍM `return parts[0]['text']` — Gemini občas rozdělí
                #   odpověď do více `parts` segmentů (např. když je v odpovědi
                #   inline obrázek, code block, nebo prostě interní streaming).
                #   První part byl typicky úvodní fragment "Ahoj! Mám" a
                #   pokračování "se dobře, jak ty?" se ZAHODILO.
                #   Teď iterujeme přes všechny parts a spojíme text.
                content_parts = data['candidates'][0].get('content', {}).get('parts', [])
                texts = [p.get('text', '') for p in content_parts if p.get('text')]
                full_text = ''.join(texts).strip()
                if full_text:
                    # Doplňková kontrola: pokud Gemini hlásí finishReason
                    # MAX_TOKENS, nechá uživatele vědět ale text vrátíme tak
                    # jak je (server ho nesmí oseknout dál).
                    finish = data['candidates'][0].get('finishReason', '')
                    if finish == 'MAX_TOKENS':
                        logger.warning(f"Gemini hit MAX_TOKENS, response may be truncated: {full_text[:80]}...")
                    return full_text

        logger.error(f"Gemini error: {response.status_code} — body: {(response.text or '')[:200]}")
        return None

    except http_requests.exceptions.Timeout:
        logger.warning("Gemini timeout — caller bude fallbackovat na Claude")
        return None
    except Exception as e:
        logger.error(f"Gemini AI error: {e}", exc_info=True)
        return None


def call_claude_ai(messages, context=None):
    """Fallback na Claude API"""
    if not ANTHROPIC_API_KEY:
        return None

    try:
        conversation = [{"role": "user" if m.get('sender_id') != 'radim' else "assistant",
                        "content": m.get('content', '')} for m in messages[-10:]]

        response = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                # Bug-fix: 200 tokens je málo, viz Gemini fix výše.
                "max_tokens": 500,
                "system": RADIM_SYSTEM_PROMPT,
                "messages": conversation
            },
            timeout=22  # tightened pod Heroku 30s router buffer
        )

        if response.status_code == 200:
            data = response.json()
            if 'content' in data and data['content']:
                # Bug-fix (komunikace "Mám" truncation):
                #   Claude Messages API vrací `content` jako pole bloků
                #   (typicky [{"type":"text","text":"..."}], ale může být
                #   i tool_use, image, atd.). Předtím jsme brali jen [0],
                #   teď konkatenujeme všechny text bloky.
                texts = [b.get('text', '') for b in data['content']
                         if b.get('type') == 'text' and b.get('text')]
                full_text = ''.join(texts).strip()
                if full_text:
                    stop_reason = data.get('stop_reason', '')
                    if stop_reason == 'max_tokens':
                        logger.warning(f"Claude hit max_tokens, may be truncated: {full_text[:80]}...")
                    return full_text

        logger.error(f"Claude error: {response.status_code} — body: {(response.text or '')[:200]}")
        return None

    except http_requests.exceptions.Timeout:
        logger.warning("Claude timeout")
        return None
    except Exception as e:
        logger.error(f"Claude AI error: {e}", exc_info=True)
        return None


def get_ai_response(messages, context=None, image=None):
    """Získej AI odpověď (Gemini s fallbackem na Claude)"""
    response = call_gemini_ai(messages, context, image)
    if not response:
        response = call_claude_ai(messages, context)
    if not response:
        response = "Omlouvám se, momentálně mám technické potíže. Zkuste to prosím za chvíli."
    return response
