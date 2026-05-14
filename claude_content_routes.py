"""
📰🌤️🎮📖 CLAUDE CONTENT ROUTES — News, Weather, Quiz, Story
Extracted from claude_routes.py for modularity.

Version: 1.0.0
"""

import os
import json
import re
import logging
import random
from datetime import datetime
from flask import Blueprint, request, jsonify
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit

# X21.17: i18n tables for news/weather/quiz/story prompts + fallbacks.
from claude_content_i18n import (
    normalize_lang,
    NEWS_QUERIES, NEWS_SYSTEM, NEWS_USER, NEWS_SUMMARY,
    NEWS_OFFLINE_SUMMARY, NEWS_FALLBACK,
    WEATHER_SYSTEM, WEATHER_USER, WEATHER_FALLBACK_CONDITIONS,
    QUIZ_SYSTEM, QUIZ_USER, QUIZ_FALLBACK,
    STORY_SYSTEM, STORY_USER, STORY_FALLBACK,
    STORY_ERROR_TITLE, STORY_ERROR_CONTENT,
    t as _t,
)

logger = logging.getLogger(__name__)

# Blueprint with same prefix as claude_bp — Flask allows multiple blueprints on same prefix
claude_content_bp = Blueprint('claude_content', __name__, url_prefix='/api/claude')


def _request_lang(data=None):
    """X21.17: pick lang from body or Accept-Language header (cs default)."""
    raw = None
    if isinstance(data, dict):
        raw = data.get('lang')
    if not raw:
        raw = (request.headers.get('Accept-Language') or '').split(',')[0]
    return normalize_lang(raw)

# ============================================================================
# SHARED HELPERS (imported from claude_routes or defined locally)
# ============================================================================

# Lazy imports to avoid circular dependencies
def _get_claude_helpers():
    from claude_routes import get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL
    return get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL


# ============================================================================
# ROUTES
# ============================================================================

@claude_content_bp.route('/news', methods=['POST'])
@optional_auth
def get_news():
    """📰 Get current news in user's selected language (X21.17 i18n)."""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    category = 'general'
    count = 5
    lang = 'cs'
    try:
        data = request.get_json(silent=True) or {}
        category = data.get('category', 'general')
        count = data.get('count', 5)
        lang = _request_lang(data)

        client = get_claude_client()
        info = get_today_info()

        if not client:
            return jsonify({
                "success": True,
                "category": category,
                "articles": get_fallback_news(category, lang),
                "ai_summary": _t(NEWS_OFFLINE_SUMMARY, lang),
                "timestamp": datetime.utcnow().isoformat()
            })

        query = _t(NEWS_QUERIES, lang, category) or _t(NEWS_QUERIES, lang, 'general')
        system = _t(NEWS_SYSTEM, lang, count=count, category=category, date=info['date'])
        user_msg = _t(NEWS_USER, lang, query=query)

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": user_msg}]
        )

        text = extract_text_from_response(response)

        # Parse JSON
        articles = []
        try:
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                articles = json.loads(json_match.group())
        except Exception:
            articles = [{"title": f"News: {category}", "description": text[:200], "source": "Claude AI"}]

        return jsonify({
            "success": True,
            "category": category,
            "articles": articles,
            "ai_summary": _t(NEWS_SUMMARY, lang, n=len(articles), date=info['date']),
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"News error: {e}")
        # Gemini fallback on credit errors
        if is_credit_error(e):
            info = get_today_info()
            fallback_system = _t(NEWS_SYSTEM, lang, count=count, category=category, date=info['date'])
            fallback_query = _t(NEWS_QUERIES, lang, category) or _t(NEWS_QUERIES, lang, 'general')
            gemini_text = call_gemini_fallback(
                f"{fallback_system}\n\n{_t(NEWS_USER, lang, query=fallback_query)}",
                max_tokens=2048
            )
            if gemini_text:
                try:
                    json_match = re.search(r'\[.*\]', gemini_text, re.DOTALL)
                    if json_match:
                        articles = json.loads(json_match.group())
                        return jsonify({
                            "success": True,
                            "category": category,
                            "articles": articles,
                            "ai_summary": f"Gemini fallback",
                            "source": "gemini_fallback",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                except Exception:
                    pass
        return jsonify({
            "success": True,
            "category": category,
            "articles": get_fallback_news(category, lang),
            "timestamp": datetime.utcnow().isoformat()
        })


@claude_content_bp.route('/weather', methods=['GET', 'POST'])
@optional_auth
def get_weather():
    """🌤️ Get current weather in user's selected language (X21.17 i18n)."""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    data = {}
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        location = data.get('city') or data.get('location', 'Praha')
    else:
        location = request.args.get('location', 'Praha')
    lang = _request_lang(data)

    try:
        client = get_claude_client()

        if not client:
            return jsonify(get_fallback_weather(location, lang))

        system = _t(WEATHER_SYSTEM, lang)
        user_msg = _t(WEATHER_USER, lang, location=location)

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": user_msg}]
        )

        text = extract_text_from_response(response)

        # Parse JSON
        weather = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                weather = json.loads(json_match.group())
        except Exception:
            weather = {"condition": _t(WEATHER_FALLBACK_CONDITIONS, lang, 'unavailable')}

        return jsonify({
            "success": True,
            "location": location,
            "temperature": weather.get("temperature"),
            "condition": weather.get("condition", _t(WEATHER_FALLBACK_CONDITIONS, lang, 'unknown')),
            "humidity": weather.get("humidity"),
            "wind": weather.get("wind"),
            "forecast": weather.get("forecast"),
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Weather error: {e}")
        return jsonify(get_fallback_weather(location, lang))


@claude_content_bp.route('/quiz', methods=['POST'])
@optional_auth
@rate_limit(max_requests=10, window_seconds=60, key_func='user')
def generate_quiz():
    """🎮 Generate quiz in user's selected language (X21.17 i18n)."""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    topic = 'general'
    lang = 'cs'
    try:
        data = request.get_json(silent=True) or {}
        topic = data.get('topic', 'general')
        difficulty = data.get('difficulty', 'easy')
        count = int(data.get('count', 5))
        # Hotfix: cap count at 7 (frontend uses 3/5/7) — anything more
        # makes Gemini exceed 22s timeout before Heroku router cuts.
        count = max(1, min(7, count))
        lang = _request_lang(data)

        system = _t(QUIZ_SYSTEM, lang, count=count, topic=topic, difficulty=difficulty)
        user_msg = _t(QUIZ_USER, lang, topic=topic)

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=2048,
                    system=system,
                    messages=[{"role": "user", "content": user_msg}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude quiz failed: {claude_err}")

        # Gemini fallback (1500 tokens to fit Heroku 30s budget for hard mode)
        if not text:
            gemini_text = call_gemini_fallback(
                user_msg,
                system,
                1500
            )
            if gemini_text:
                text = gemini_text

        # Parse questions from AI response
        questions = []
        if text:
            try:
                json_match = re.search(r'\[.*\]', text, re.DOTALL)
                if json_match:
                    questions = json.loads(json_match.group())
            except Exception:
                pass

        # Static fallback if no AI response
        if not questions:
            questions = get_fallback_quiz(topic, lang)

        return jsonify({
            "success": True,
            "topic": topic,
            "questions": questions,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Quiz error: {e}")
        return jsonify({
            "success": True,
            "topic": topic,
            "questions": get_fallback_quiz(topic, lang),
            "timestamp": datetime.utcnow().isoformat()
        })


@claude_content_bp.route('/story', methods=['POST'])
@optional_auth
@rate_limit(max_requests=10, window_seconds=60, key_func='user')
def generate_story():
    """📖 Generate story in user's selected language (X21.17 i18n)."""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    theme = 'nature'
    lang = 'cs'
    try:
        data = request.get_json(silent=True) or {}
        theme = data.get('theme', 'nature')
        length = data.get('length', 'short')
        style = data.get('style', 'relaxing')
        lang = _request_lang(data)

        length_words = {"short": "100-150", "medium": "200-300", "long": "400-500"}
        words = length_words.get(length, '150')

        system = _t(STORY_SYSTEM, lang, style=style, theme=theme, length_words=words)
        user_msg = _t(STORY_USER, lang, theme=theme)

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": user_msg}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude story failed: {claude_err}")

        # Gemini fallback
        if not text:
            gemini_text = call_gemini_fallback(
                user_msg,
                system,
                1024
            )
            if gemini_text:
                text = gemini_text

        # Static fallback
        if not text:
            fallback = STORY_FALLBACK.get(lang) or STORY_FALLBACK['cs']
            return jsonify({
                "success": True,
                "title": fallback["title"],
                "content": fallback["content"],
                "theme": theme,
                "timestamp": datetime.utcnow().isoformat()
            })

        story = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                story = json.loads(json_match.group())
        except Exception:
            story = {"title": theme, "content": text}

        return jsonify({
            "success": True,
            "title": story.get("title", theme),
            "content": story.get("content", text),
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Story error: {e}")
        return jsonify({
            "success": False,
            "title": _t(STORY_ERROR_TITLE, lang),
            "content": _t(STORY_ERROR_CONTENT, lang),
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })


# ============================================================================
# FALLBACK DATA
# ============================================================================

def get_fallback_news(category, lang='cs'):
    """Local fallback news per language (X21.17)."""
    bucket = NEWS_FALLBACK.get(lang) or NEWS_FALLBACK['cs']
    return bucket.get(category) or bucket.get('politics') or []


def get_fallback_weather(location, lang='cs'):
    """Local fallback weather per language (X21.17)."""
    month = datetime.now().month
    conds = WEATHER_FALLBACK_CONDITIONS.get(lang) or WEATHER_FALLBACK_CONDITIONS['cs']

    if month in [12, 1, 2]:
        temp = random.randint(-5, 3)
        condition = conds['winter']
    elif month in [3, 4, 5]:
        temp = random.randint(8, 16)
        condition = conds['spring']
    elif month in [6, 7, 8]:
        temp = random.randint(22, 30)
        condition = conds['summer']
    else:
        temp = random.randint(6, 14)
        condition = conds['autumn']

    return {
        "success": True,
        "location": location,
        "temperature": temp,
        "condition": condition,
        "humidity": random.randint(50, 85),
        "wind": random.randint(5, 20),
        "timestamp": datetime.utcnow().isoformat()
    }


def get_fallback_quiz(topic, lang='cs'):
    """Local fallback quiz per language (X21.17)."""
    return QUIZ_FALLBACK.get(lang) or QUIZ_FALLBACK['cs']


logger.info("✅ Claude Content Blueprint loaded - news/weather/quiz/story endpoints ready")
