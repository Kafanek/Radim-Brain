# ============================================
# RADIM AI ENGINE
# ============================================
# Extracted from radim_orchestrator.py for modularity.
#
# Contains:
#   - call_gemini_whatsapp() — Gemini API wrapper with system prompt + history + rhythm
#   - parse_radim_response()  — Action JSON parser (---RADIM_ACTION---)
#   - STORY_TEMPLATES          — Social media story templates
#
# Version: 1.0.0

import re
import json
import logging

import requests

from radim_helpers import GEMINI_API_KEY, _get_dynamic_system_prompt
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)


# ============================================
# GEMINI AI CALL
# ============================================
def call_gemini_whatsapp(message, context=None, mode='senior', personalized_prompt='', history=None, anticipation_prompt='', gen_config=None):
    """Volání Gemini s WhatsApp promptem + personalizace + historie + rytmus"""
    if not GEMINI_API_KEY:
        return None, None

    try:
        # 🏠 Dynamický system prompt s časem, rolí, kontextem
        system = _get_dynamic_system_prompt(mode)

        # 🧠 Add personalized prompt from memory (name, interests, style, mood)
        if personalized_prompt:
            system += personalized_prompt

        # 🎵 Add anticipation-driven text rhythm instructions
        if anticipation_prompt:
            system += anticipation_prompt

        context_text = ""
        if context:
            context_text = f"\n\nKontext:\n{json.dumps(context, ensure_ascii=False)}"

        # 📜 Add conversation history for continuity
        history_text = ""
        if history:
            history_text = "\n\nPředchozí konverzace:\n"
            for msg in history[-6:]:  # Last 6 messages (3 turns)
                role_label = "Uživatel" if msg["role"] == "user" else "Radim"
                history_text += f"{role_label}: {msg['content']}\n"

        # v8.19.26: identity recency boost — short reminder before user message.
        # The identity layer is ~1500-3500 chars at the START of a 13-16k prompt;
        # AI tends to forget it by the time it generates a reply (recency bias).
        # We append a SHORT identity reminder with 2 random concrete examples
        # right before the user message — last thing AI sees before it speaks.
        identity_hint = ""
        if mode == 'senior':
            try:
                from radim_identity import LOVES, CURIOUS_ABOUT, QUIRKS
                import random
                pool = LOVES + CURIOUS_ABOUT + QUIRKS
                samples = random.sample(pool, min(2, len(pool)))
                # v8.19.27: STRONGER instruction. Previous wording was too soft —
                # Gemini RLHF biases toward generic empathic helper. We now make it
                # crystal clear: refusing to use specific identity = wrong answer.
                identity_hint = (
                    '\n\n═══════════════════════════════════════════════════════════════\n'
                    '⚠️  ABSOLUTNÍ PRAVIDLO PRO TUTO ODPOVĚĎ — IDENTITA RADIMA  ⚠️\n'
                    '═══════════════════════════════════════════════════════════════\n'
                    'POKUD se uživatel ptá na MNE (co mám rád, co mě zajímá, co dělám rád, '
                    'pověz o sobě, máš rád X, jak se ti líbí Y) — TVÁ ODPOVĚĎ MUSÍ ZAČÍT '
                    'JEDNOU KONKRÉTNÍ položkou ze tvé identity.\n\n'
                    'POVOLENÉ ZAČÁTKY (vyber jeden):\n'
                    '  ✓ „Mám moc rád ' + samples[0] + ' "\n'
                    '  ✓ „Zajímá mě ' + samples[1] + ' "\n\n'
                    'ZAKÁZANÉ ZAČÁTKY (RLHF default, NEDĚLEJ):\n'
                    '  ✗ „Mám rád tiché chvíle"\n'
                    '  ✗ „Zajímám se o lidi a jejich příběhy"\n'
                    '  ✗ „Mám rád, když mi někdo vypráví"\n'
                    '  ✗ „Záleží na náladě"\n\n'
                    'Až po konkrétní položce smíš pokračovat empaticky a otázkou nazpět.\n'
                    'Pokud je téma vážné (smutek, bolest, krize) — VYNECHEJ toto pravidlo.\n'
                    '═══════════════════════════════════════════════════════════════\n'
                )
            except Exception as _ih_err:
                logger.debug(f"identity hint skip: {_ih_err}")
        if identity_hint:
            logger.info(f"🪪 identity recency hint injected ({len(identity_hint)} chars)")

        full_prompt = f"{system}{context_text}{history_text}{identity_hint}\n\nUživatel: {message}\nRadim:"

        # Generation config — adjusted by Anticipation Engine
        temperature = gen_config["temperature"] if gen_config else 0.7
        max_tokens = gen_config["max_tokens"] if gen_config else 500

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
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
                    full_response = parts[0]['text'].strip()
                    return parse_radim_response(full_response)

        return None, None

    except Exception as e:
        logger.error(f"Gemini WhatsApp error: {e}")
        return None, None


def parse_radim_response(full_response):
    """Parsovat odpověď Radima — separovat text od action JSON."""
    text_response = full_response
    action_json = None

    action_match = re.search(r'---RADIM_ACTION---\s*(\{.*?\})\s*---END_ACTION---', full_response, re.DOTALL)

    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            text_response = full_response[:action_match.start()].strip()
        except json.JSONDecodeError:
            pass

    return text_response, action_json


# ============================================
# STORY TEMPLATES
# ============================================
STORY_TEMPLATES = [
    {
        'id': 'kolibri_plus_one_01',
        'title': 'Plus One – pozvánka',
        'description': 'Pozvánka na akci s filozofií Plus One',
        'platform': ['instagram', 'facebook'],
        'fields': {'hook': 'Úvodní věta', 'value': 'Co člověk získá', 'cta': 'Výzva k akci'},
        'prompt_hint': 'Krátké věty, Kolibri tón, plus jedna.',
        'emoji': '☕'
    },
    {
        'id': 'kolibri_tip_01',
        'title': 'Tip od Kafánka',
        'description': 'Krátký užitečný tip pro seniory',
        'platform': ['instagram', 'facebook', 'tiktok'],
        'fields': {'tip_title': 'Název tipu', 'tip_content': 'Obsah tipu', 'benefit': 'Proč to pomůže'},
        'prompt_hint': 'Senior-friendly, jednoduché slova.',
        'emoji': '💡'
    },
    {
        'id': 'kolibri_story_01',
        'title': 'Příběh z kavárny',
        'description': 'Krátký příběh z Kavárny Kolibri',
        'platform': ['instagram', 'facebook'],
        'fields': {'situation': 'Co se stalo', 'emotion': 'Jak se cítili', 'lesson': 'Co jsme se naučili'},
        'prompt_hint': 'Autentický, lidský, bez přehánění.',
        'emoji': '📖'
    }
]


logger.info("✅ Radim AI Engine loaded — Gemini wrapper, response parser, story templates")
