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

logger = logging.getLogger(__name__)

# Blueprint with same prefix as claude_bp — Flask allows multiple blueprints on same prefix
claude_content_bp = Blueprint('claude_content', __name__, url_prefix='/api/claude')

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
@require_auth
def get_news():
    """📰 Získat aktuální české zprávy"""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    category = 'general'
    count = 5
    try:
        data = request.get_json() or {}
        category = data.get('category', 'general')
        count = data.get('count', 5)

        client = get_claude_client()
        info = get_today_info()

        if not client:
            return jsonify({
                "success": True,
                "category": category,
                "articles": get_fallback_news(category),
                "ai_summary": "Lokální zprávy (AI nedostupná)",
                "timestamp": datetime.utcnow().isoformat()
            })

        category_queries = {
            "politics": "české politické zprávy dnes",
            "sports": "český sport zprávy hokej fotbal",
            "health": "zdraví zprávy tipy pro seniory",
            "culture": "kultura Praha divadlo koncerty",
            "science": "věda technika zajímavosti Česko",
            "local": "Praha zprávy doprava události",
            "general": "hlavní české zprávy dnes"
        }

        query = category_queries.get(category, category_queries["general"])

        system = f"""Vyhledej {count} aktuálních českých zpráv z kategorie: {category}.

FORMÁT (pouze JSON pole):
[
  {{"title": "Titulek", "description": "Popis", "source": "Zdroj"}}
]

Dnešní datum: {info['date']}"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": f"Vyhledej zprávy: {query}"}]
        )

        text = extract_text_from_response(response)

        # Parse JSON
        articles = []
        try:
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                articles = json.loads(json_match.group())
        except Exception:
            articles = [{"title": f"Zprávy z {category}", "description": text[:200], "source": "Claude AI"}]

        return jsonify({
            "success": True,
            "category": category,
            "articles": articles,
            "ai_summary": f"{len(articles)} zpráv ke dni {info['date']}",
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"News error: {e}")
        # Gemini fallback on credit errors
        if is_credit_error(e):
            info = get_today_info()
            gemini_text = call_gemini_fallback(
                f"Vyhledej {count if 'count' in dir() else 5} aktuálních českých zpráv z kategorie: {category}. Dnešní datum: {info['date']}. Odpověz jako JSON pole [{{'title':'...','description':'...','source':'...'}}]",
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
                            "ai_summary": f"Zprávy via Gemini",
                            "source": "gemini_fallback",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                except Exception:
                    pass
        return jsonify({
            "success": True,
            "category": category,
            "articles": get_fallback_news(category),
            "timestamp": datetime.utcnow().isoformat()
        })


@claude_content_bp.route('/weather', methods=['GET', 'POST'])
@optional_auth
def get_weather():
    """🌤️ Získat aktuální počasí"""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    if request.method == 'POST':
        data = request.get_json() or {}
        location = data.get('city') or data.get('location', 'Praha')
    else:
        location = request.args.get('location', 'Praha')

    try:
        client = get_claude_client()

        if not client:
            return jsonify(get_fallback_weather(location))

        system = """Vyhledej aktuální počasí a odpověz pouze JSON:
{"temperature": 5, "condition": "Oblačno", "humidity": 75, "wind": 12, "forecast": "Odpoledne déšť."}"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": f"Aktuální počasí v {location}?"}]
        )

        text = extract_text_from_response(response)

        # Parse JSON
        weather = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                weather = json.loads(json_match.group())
        except Exception:
            weather = {"condition": "Informace nedostupná"}

        return jsonify({
            "success": True,
            "location": location,
            "temperature": weather.get("temperature"),
            "condition": weather.get("condition", "Neznámé"),
            "humidity": weather.get("humidity"),
            "wind": weather.get("wind"),
            "forecast": weather.get("forecast"),
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Weather error: {e}")
        return jsonify(get_fallback_weather(location))


@claude_content_bp.route('/quiz', methods=['POST'])
@require_auth
@rate_limit(max_requests=10, window_seconds=60, key_func='user')
def generate_quiz():
    """🎮 Vygenerovat kvíz"""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    topic = 'general'
    try:
        data = request.get_json() or {}
        topic = data.get('topic', 'general')
        difficulty = data.get('difficulty', 'easy')
        count = data.get('count', 5)

        system = f"""Vytvoř {count} kvízových otázek pro seniory.
Téma: {topic}, Obtížnost: {difficulty}

FORMÁT (pouze JSON):
[{{"question": "Otázka?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Vysvětlení."}}]"""

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=2048,
                    system=system,
                    messages=[{"role": "user", "content": f"Vytvoř kvíz na téma: {topic}"}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude quiz failed: {claude_err}")

        # Gemini fallback
        if not text:
            gemini_text = call_gemini_fallback(
                f"Vytvoř kvíz na téma: {topic}",
                system,
                2048
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
            questions = get_fallback_quiz(topic)

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
            "questions": get_fallback_quiz(topic),
            "timestamp": datetime.utcnow().isoformat()
        })


@claude_content_bp.route('/story', methods=['POST'])
@require_auth
@rate_limit(max_requests=10, window_seconds=60, key_func='user')
def generate_story():
    """📖 Vygenerovat příběh"""
    get_claude_client, extract_text_from_response, get_today_info, is_credit_error, call_gemini_fallback, CLAUDE_MODEL = _get_claude_helpers()
    theme = 'nature'
    try:
        data = request.get_json() or {}
        theme = data.get('theme', 'nature')
        length = data.get('length', 'short')
        style = data.get('style', 'relaxing')

        length_words = {"short": "100-150", "medium": "200-300", "long": "400-500"}

        system = f"""Vyprávěj {style} příběh pro seniory.
Téma: {theme}, Délka: {length_words.get(length, '150')} slov.
Česká jména a místa. Pozitivní a uklidňující.

FORMÁT (pouze JSON):
{{"title": "Název", "content": "Text příběhu..."}}"""

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": f"Vyprávěj příběh na téma: {theme}"}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude story failed: {claude_err}")

        # Gemini fallback
        if not text:
            gemini_text = call_gemini_fallback(
                f"Vyprávěj příběh na téma: {theme}",
                system,
                1024
            )
            if gemini_text:
                text = gemini_text

        # Static fallback
        if not text:
            return jsonify({
                "success": True,
                "title": "Procházka parkem",
                "content": "Bylo krásné jarní ráno. Pan Josef vyšel na svou oblíbenou procházku do parku. Slunce hřálo a ptáci zpívali. U rybníčku potkal svého starého přítele Karla a společně si povídali o starých časech. Byl to krásný den.",
                "theme": theme,
                "timestamp": datetime.utcnow().isoformat()
            })

        story = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                story = json.loads(json_match.group())
        except Exception:
            story = {"title": f"Příběh o {theme}", "content": text}

        return jsonify({
            "success": True,
            "title": story.get("title", "Příběh"),
            "content": story.get("content", text),
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Story error: {e}")
        return jsonify({
            "success": False,
            "title": "Chyba",
            "content": "Nepodařilo se vytvořit příběh.",
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })


# ============================================================================
# FALLBACK DATA
# ============================================================================

def get_fallback_news(category):
    """Lokální fallback zprávy"""
    news = {
        "politics": [
            {"title": "Vláda schválila sociální podporu", "description": "Rozšíření příspěvků pro seniory.", "source": "ČTK"},
            {"title": "Prezident Pavel v Bruselu", "description": "Summit EU o bezpečnosti.", "source": "iDNES"}
        ],
        "sports": [
            {"title": "Hokejisté vyhráli turnaj", "description": "Zlatá medaile pro ČR.", "source": "Sport.cz"},
            {"title": "Sparta v Lize mistrů", "description": "Vítězství 2:1.", "source": "iSport"}
        ],
        "health": [
            {"title": "Očkování proti chřipce", "description": "Zdarma pro seniory 65+.", "source": "VZP"},
            {"title": "Prevence je základ", "description": "Pravidelné prohlídky.", "source": "MZ ČR"}
        ],
        "culture": [
            {"title": "Národní divadlo: premiéra", "description": "Prodaná nevěsta.", "source": "Kultura.cz"},
            {"title": "Výstava Muchy", "description": "Retrospektiva v Praze.", "source": "Aktuálně.cz"}
        ],
        "science": [
            {"title": "Nová exoplaneta", "description": "Objev českých astronomů.", "source": "Akademie věd"},
            {"title": "AI v medicíně", "description": "Diagnostika s 95% přesností.", "source": "Tech.cz"}
        ],
        "local": [
            {"title": "Metro D se staví", "description": "Otevření v 2027.", "source": "Praha.eu"},
            {"title": "Farmářské trhy", "description": "Každou sobotu.", "source": "Pražský deník"}
        ]
    }
    return news.get(category, news["politics"])


def get_fallback_weather(location):
    """Lokální fallback počasí"""
    month = datetime.now().month

    if month in [12, 1, 2]:
        temp = random.randint(-5, 3)
        condition = "Zataženo"
    elif month in [3, 4, 5]:
        temp = random.randint(8, 16)
        condition = "Polojasno"
    elif month in [6, 7, 8]:
        temp = random.randint(22, 30)
        condition = "Jasno"
    else:
        temp = random.randint(6, 14)
        condition = "Oblačno"

    return {
        "success": True,
        "location": location,
        "temperature": temp,
        "condition": condition,
        "humidity": random.randint(50, 85),
        "wind": random.randint(5, 20),
        "timestamp": datetime.utcnow().isoformat()
    }


def get_fallback_quiz(topic):
    """Lokální fallback kvíz"""
    return [
        {
            "question": "Který hrad je největší na světě?",
            "options": {"A": "Pražský hrad", "B": "Windsor", "C": "Versailles", "D": "Kreml"},
            "correct": "A",
            "explanation": "Pražský hrad je podle Guinessovy knihy rekordů největší hradní komplex."
        },
        {
            "question": "Která řeka protéká Prahou?",
            "options": {"A": "Morava", "B": "Vltava", "C": "Labe", "D": "Odra"},
            "correct": "B",
            "explanation": "Vltava je nejdelší řeka v České republice."
        }
    ]


logger.info("✅ Claude Content Blueprint loaded - news/weather/quiz/story endpoints ready")
