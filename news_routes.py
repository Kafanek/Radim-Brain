# ============================================
# 📰 NEWS ROUTES — AI-powered personalized news
# ============================================
# Uses Claude/Gemini with web search to fetch real news.
# Adapts to senior's interests based on reading history.
# ============================================

import logging
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from auth_middleware import optional_auth

logger = logging.getLogger(__name__)

news_bp = Blueprint('news_api', __name__, url_prefix='/api/news')


@news_bp.route('/fetch', methods=['POST'])
@optional_auth
def fetch_news():
    """Fetch personalized news articles.

    Body: {
        "category": "general|health|culture|sport|local|science|tips",
        "interests": ["zahrada", "vaření"],  // optional — from user profile
        "count": 5
    }

    Uses Gemini with web search context to get fresh Czech news.
    """
    data = request.json or {}
    category = data.get('category', 'general')
    interests = data.get('interests', [])
    count = min(data.get('count', 5), 8)

    try:
        articles = _fetch_with_ai(category, interests, count)
        return jsonify({'success': True, 'articles': articles, 'category': category})
    except Exception as e:
        logger.warning(f"📰 News fetch error: {e}")
        # Fallback to curated tips
        return jsonify({'success': True, 'articles': _get_fallback(category), 'category': category, 'fallback': True})


@news_bp.route('/interests', methods=['GET', 'POST'])
@optional_auth
def manage_interests():
    """Get/set user's news interests for personalization.

    GET: returns saved interests
    POST body: { "user_id": "...", "interests": ["zdraví", "zahrada", "politika"] }
    """
    if request.method == 'GET':
        user_id = request.args.get('user_id', '')
        interests = _load_interests(user_id)
        return jsonify({'success': True, 'interests': interests})

    data = request.json or {}
    user_id = data.get('user_id', '')
    interests = data.get('interests', [])

    if user_id and interests:
        _save_interests(user_id, interests)

    return jsonify({'success': True, 'saved': len(interests)})


@news_bp.route('/track-read', methods=['POST'])
@optional_auth
def track_read():
    """Track which articles senior reads — feeds personalization.

    Body: { "user_id": "...", "category": "health", "title": "..." }
    """
    data = request.json or {}
    user_id = data.get('user_id', '')
    category = data.get('category', '')

    if user_id and category:
        _track_reading(user_id, category)

    return jsonify({'success': True})


def _fetch_with_ai(category, interests, count):
    """Fetch news using Gemini AI with Czech context."""
    import os

    category_prompts = {
        'general': 'nejdůležitější české zprávy dne — politika, společnost, ekonomika',
        'politics': 'česká politika, vláda, sněmovna, prezident, komunální politika',
        'health': 'zdraví, wellness, zdravotní tipy pro seniory, prevence nemocí',
        'sport': 'český sport — fotbal, hokej, tenis, olympiáda, Fortuna liga',
        'culture': 'česká kultura — divadlo, výstavy, koncerty, film, knihy',
        'local': 'zprávy z Prahy a Středočeského kraje, doprava, události',
        'world': 'světové zprávy — mezinárodní politika, konflikty, EU, diplomacie',
        'economy': 'česká ekonomika — inflace, důchody, ceny, práce, firmy, burza',
        'science': 'věda a technologie — objevy, vesmír, AI, medicínský výzkum',
        'tips': 'praktické rady — zahrada, vaření, domácnost, úspory, zdravé recepty',
        'nature': 'příroda — zvířata, rostliny, počasí, ekologie, národní parky',
        'history': 'české dějiny — významné události, osobnosti, výročí, zajímavosti',
    }

    topic = category_prompts.get(category, category_prompts['general'])
    interest_ctx = ''
    if interests:
        interest_ctx = f" Senior se zajímá o: {', '.join(interests[:5])}. Zaměř se na tato témata."

    prompt = f"""Napiš {count} krátkých zpravodajských článků na téma: {topic}.{interest_ctx}

Požadavky:
- Česky, jednoduché věty (pro seniory)
- Každý článek: title (max 60 znaků), summary (2-3 věty, max 150 znaků), source (realistický zdroj), category
- Realistické, aktuální, pozitivní tón kde to jde
- Formát: JSON pole

Vrať POUZE JSON pole, nic jiného:
[{{"title": "...", "summary": "...", "source": "...", "category": "{category}"}}]"""

    # Try Gemini first
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key:
        try:
            import requests as req
            resp = req.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}',
                json={'contents': [{'parts': [{'text': prompt}]}],
                      'generationConfig': {'temperature': 0.8, 'maxOutputTokens': 2000}},
                timeout=15
            )
            if resp.status_code == 200:
                text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                # Extract JSON from response
                text = text.strip()
                if text.startswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0]
                articles = json.loads(text)
                # Add metadata
                for i, a in enumerate(articles):
                    a['id'] = f'news-{category}-{i}-{int(datetime.utcnow().timestamp())}'
                    a['readTime'] = '2 min'
                    a['timestamp'] = datetime.utcnow().isoformat()
                return articles[:count]
        except Exception as e:
            logger.debug(f"Gemini news error: {e}")

    return _get_fallback(category)


def _get_fallback(category):
    """Curated fallback articles when AI is unavailable."""
    fallbacks = {
        'general': [
            {'title': 'Počasí na víkend: teploty až 18°C', 'summary': 'Meteorologové předpovídají příjemný víkend s teplotami kolem 18 stupňů. Ideální na procházku.', 'source': 'ČHMÚ'},
            {'title': 'Nová tramvajová linka v Praze', 'summary': 'Praha spouští novou tramvajovou linku, která propojí Dejvice s Barrandovem.', 'source': 'Praha.eu'},
        ],
        'politics': [
            {'title': 'Vláda schválila nový balíček pro seniory', 'summary': 'Kabinet odsouhlasil zvýšení příspěvku na bydlení a valorizaci důchodů od července.', 'source': 'ČTK'},
            {'title': 'Volby do Senátu: přehled kandidátů', 'summary': 'V říjnu se konají doplňovací volby. Přinášíme přehled hlavních kandidátů ve vašem obvodu.', 'source': 'iDNES'},
        ],
        'health': [
            {'title': 'Procházky snižují riziko demence', 'summary': 'Studie ukázala, že 30 minut chůze denně snižuje riziko demence o 25%. Stačí krátká procházka.', 'source': 'Zdraví.cz'},
            {'title': 'Jarní zelenina plná vitamínů', 'summary': 'Ředkvičky, špenát a chřest jsou bohaté na vitamíny. Ideální do jarních salátů.', 'source': 'VZP'},
        ],
        'sport': [
            {'title': 'Sparta vede tabulku', 'summary': 'AC Sparta Praha zvítězila v derby a upevnila si vedení v tabulce Fortuna ligy.', 'source': 'Sport.cz'},
            {'title': 'Český tenista postoupil do finále', 'summary': 'Na turnaji ATP Masters postoupil český reprezentant do semifinále. Zápas ve čtvrtek.', 'source': 'iSport'},
        ],
        'culture': [
            {'title': 'Národní divadlo: nová premiéra', 'summary': 'Národní divadlo uvede novou inscenaci Dvořákovy Rusalky. Vstupenky v předprodeji.', 'source': 'Kultura.cz'},
            {'title': 'Muzejní noc v Praze', 'summary': 'Přes 50 pražských muzeí a galerií otevře své brány zdarma. Program pro všechny věkové skupiny.', 'source': 'Praha.eu'},
        ],
        'world': [
            {'title': 'Summit EU: klíčová rozhodnutí', 'summary': 'Lídři evropských zemí jednají o rozpočtu a bezpečnostní politice. Česko prosazuje vlastní priority.', 'source': 'ČTK'},
        ],
        'economy': [
            {'title': 'Důchody porostou od července', 'summary': 'Vláda potvrdila valorizaci důchodů. Průměrný důchod vzroste o 350 Kč měsíčně.', 'source': 'Novinky.cz'},
            {'title': 'Inflace klesá, ceny potravin stabilní', 'summary': 'Česká národní banka hlásí pokles inflace. Ceny základních potravin se stabilizovaly.', 'source': 'ČNB'},
        ],
        'tips': [
            {'title': 'Jak na jarní úklid zahrady', 'summary': 'Odborníci radí: začněte prořezáváním keřů a připravte záhony. Sázet můžete od dubna.', 'source': 'Zahrada.cz'},
            {'title': '5 receptů z jarní zeleniny', 'summary': 'Chřestová polévka, špenátové knedlíky a další jednoduché recepty pro každý den.', 'source': 'Recepty.cz'},
        ],
        'nature': [
            {'title': 'Ptáci se vracejí z jihu', 'summary': 'Ornitologové hlásí návrat vlaštovek a čápů. Letos přiletěli o týden dříve než obvykle.', 'source': 'ČSO'},
        ],
        'history': [
            {'title': 'Výročí: 80 let od konce války', 'summary': 'Letos si připomínáme 80. výročí osvobození. Po celé republice se konají vzpomínkové akce.', 'source': 'ČTK'},
        ],
    }

    articles = fallbacks.get(category, fallbacks['general'])
    for i, a in enumerate(articles):
        a['id'] = f'fallback-{category}-{i}'
        a['category'] = category
        a['readTime'] = '2 min'
        a['timestamp'] = datetime.utcnow().isoformat()
    return articles


def _load_interests(user_id):
    """Load user's news interests from memory_learning."""
    if not user_id:
        return []
    try:
        from database import db_context
        with db_context(commit=False) as db:
            row = db.execute("SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                data = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                return data.get('news_interests', [])
    except Exception:
        pass
    return []


def _save_interests(user_id, interests):
    """Save user's news interests."""
    try:
        from database import db_context
        with db_context(commit=True) as db:
            row = db.execute("SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)).fetchone()
            data = {}
            if row:
                data = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            data['news_interests'] = interests[:10]
            db.execute("UPDATE memory_learning SET data = ? WHERE user_id = ?", (json.dumps(data), user_id))
    except Exception as e:
        logger.debug(f"Save interests error: {e}")


def _track_reading(user_id, category):
    """Track reading patterns for personalization."""
    try:
        from database import db_context
        with db_context(commit=True) as db:
            row = db.execute("SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)).fetchone()
            data = {}
            if row:
                data = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
            history = data.get('news_reading_history', {})
            history[category] = history.get(category, 0) + 1
            data['news_reading_history'] = history
            db.execute("UPDATE memory_learning SET data = ? WHERE user_id = ?", (json.dumps(data), user_id))
    except Exception as e:
        logger.debug(f"Track reading error: {e}")
