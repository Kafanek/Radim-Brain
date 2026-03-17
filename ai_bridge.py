# ============================================
# AI BRIDGE — Gemini + Claude Integration
# ============================================
# Centralized AI provider calls used by chat routes,
# admin routes, and the Radim system prompt.
# ============================================

import os
import logging
import requests as http_requests

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
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 200,
                    "topP": 0.9
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            if data.get('candidates'):
                parts = data['candidates'][0].get('content', {}).get('parts', [])
                if parts and parts[0].get('text'):
                    return parts[0]['text'].strip()

        logger.error(f"Gemini error: {response.status_code}")
        return None

    except Exception as e:
        logger.error(f"Gemini AI error: {e}")
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
                "max_tokens": 200,
                "system": RADIM_SYSTEM_PROMPT,
                "messages": conversation
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            if 'content' in data and data['content']:
                return data['content'][0]['text'].strip()

        return None

    except Exception as e:
        logger.error(f"Claude AI error: {e}")
        return None


def get_ai_response(messages, context=None, image=None):
    """Získej AI odpověď (Gemini s fallbackem na Claude)"""
    response = call_gemini_ai(messages, context, image)
    if not response:
        response = call_claude_ai(messages, context)
    if not response:
        response = "Omlouvám se, momentálně mám technické potíže. Zkuste to prosím za chvíli."
    return response
