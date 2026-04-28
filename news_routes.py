# ============================================
# 📰 NEWS ROUTES — AI-powered personalized news
# ============================================
# Uses Claude/Gemini with web search to fetch real news.
# Adapts to senior's interests based on reading history.
# ============================================

import logging
import json
import re
import threading
import time
from datetime import datetime
from flask import Blueprint, request, jsonify
from auth_middleware import optional_auth
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)

news_bp = Blueprint('news_api', __name__, url_prefix='/api/news')

# ═══════════════════════════════════════════════════════════════════
# In-memory short cache per (category, interests_key) — 15 min TTL.
# Prevents hammering Gemini when multiple seniors refresh. Doesn't
# starve freshness — TTL is shorter than a typical session.
# ═══════════════════════════════════════════════════════════════════
_NEWS_CACHE = {}                       # key → { articles, expires_at, fetched_at }
_NEWS_CACHE_LOCK = threading.Lock()
_NEWS_CACHE_TTL = 15 * 60              # seconds
_NEWS_CACHE_MAX_ENTRIES = 80


def _cache_key(category, interests):
    # Interests normalized so ordering doesn't produce miss
    safe_interests = ','.join(sorted(i.strip().lower() for i in interests[:5] if i))
    # Hour bucket so each hour slot gets a new prompt (within TTL of 15 min the
    # same bucket reuses the cached result — but crossing an hour boundary
    # guarantees a fresh prompt variation).
    hour_slot = int(time.time() // 3600)
    return f"{category}|{safe_interests}|{hour_slot}"


def _cache_get(key):
    with _NEWS_CACHE_LOCK:
        entry = _NEWS_CACHE.get(key)
        if not entry:
            return None
        if entry['expires_at'] < time.time():
            _NEWS_CACHE.pop(key, None)
            return None
        return entry


def _cache_put(key, articles):
    with _NEWS_CACHE_LOCK:
        if len(_NEWS_CACHE) >= _NEWS_CACHE_MAX_ENTRIES:
            # Drop oldest
            oldest = min(_NEWS_CACHE.items(), key=lambda kv: kv[1]['expires_at'])
            _NEWS_CACHE.pop(oldest[0], None)
        _NEWS_CACHE[key] = {
            'articles': articles,
            'expires_at': time.time() + _NEWS_CACHE_TTL,
            'fetched_at': time.time(),
        }


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
    data = request.get_json(silent=True) or {}
    category = data.get('category', 'general')
    interests = data.get('interests', [])
    count = min(data.get('count', 5), 8)
    force_refresh = bool(data.get('force_refresh'))

    # Respect manual refresh — bypass cache when the senior explicitly
    # re-pulls (pull-to-refresh, reload button).
    key = _cache_key(category, interests)
    cached = None if force_refresh else _cache_get(key)
    if cached:
        return jsonify({
            'success': True,
            'articles': cached['articles'][:count],
            'category': category,
            'fetched_at': cached['fetched_at'],
            'cache': 'hit',
        })

    try:
        articles = _fetch_with_ai(category, interests, count)
        _cache_put(key, articles)
        return jsonify({
            'success': True,
            'articles': articles,
            'category': category,
            'fetched_at': time.time(),
            'cache': 'miss',
        })
    except Exception as e:
        logger.warning(f"📰 News fetch error: {e}")
        fallback = _get_fallback(category)
        return jsonify({
            'success': True,
            'articles': fallback,
            'category': category,
            'fetched_at': time.time(),
            'fallback': True,
            'cache': 'miss',
        })


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

    data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '')
    category = data.get('category', '')

    if user_id and category:
        _track_reading(user_id, category)

    return jsonify({'success': True})


# ═══════════════════════════════════════════════════════════════════
# v10.56: Real RSS feeds from Czech publishers, summarized by Gemini.
# Replaces AI-generated-from-scratch news (which risked hallucinations).
# ═══════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    # Hlavní zprávy (mix)
    'general': [
        ('iDNES',         'https://servis.idnes.cz/rss.aspx?c=zpravodaj'),
        ('ČT24',          'https://ct24.ceskatelevize.cz/rss/hlavni-zpravy'),
        ('Novinky',       'https://www.novinky.cz/rss'),
        ('Seznam Zprávy', 'https://www.seznamzpravy.cz/rss'),
    ],
    'politics': [
        ('ČT24',    'https://ct24.ceskatelevize.cz/rss/domaci'),
        ('iDNES',   'https://servis.idnes.cz/rss.aspx?c=zpravodaj'),
        ('Novinky', 'https://www.novinky.cz/rss'),
    ],
    'health': [
        ('Novinky zdraví',  'https://www.novinky.cz/rss/zena/zdravi'),
        ('Seznam Zdraví',   'https://www.seznamzpravy.cz/rss?section=zdravi'),
    ],
    'sport': [
        ('iDNES sport',    'https://servis.idnes.cz/rss.aspx?c=sport'),
        ('Novinky sport',  'https://www.novinky.cz/rss/sport'),
    ],
    'culture': [
        ('iDNES kultura',   'https://servis.idnes.cz/rss.aspx?c=kultura'),
        ('ČT24 kultura',    'https://ct24.ceskatelevize.cz/rss/kultura'),
        ('Novinky kultura', 'https://www.novinky.cz/rss/kultura'),
    ],
    'local': [
        ('Novinky Praha',   'https://www.novinky.cz/rss/domaci/praha'),
        ('ČT24 domácí',     'https://ct24.ceskatelevize.cz/rss/domaci'),
    ],
    'world': [
        ('ČT24 svět',          'https://ct24.ceskatelevize.cz/rss/svet'),
        ('Novinky zahraniční', 'https://www.novinky.cz/rss/zahranicni'),
    ],
    'economy': [
        ('iDNES ekonomika',    'https://servis.idnes.cz/rss.aspx?c=ekonomika'),
        ('ČT24 ekonomika',     'https://ct24.ceskatelevize.cz/rss/ekonomika'),
        ('Novinky ekonomika',  'https://www.novinky.cz/rss/ekonomika'),
    ],
    'science': [
        ('iDNES technet',   'https://servis.idnes.cz/rss.aspx?c=technet'),
        ('ČT24 věda',       'https://ct24.ceskatelevize.cz/rss/veda'),
        ('Novinky věda',    'https://www.novinky.cz/rss/veda-a-skoly'),
    ],
    # Bez spolehlivých RSS: tipy — fallback na AI generování.
}

_RSS_CACHE = {}                 # url → { items, expires_at }
_RSS_CACHE_LOCK = threading.Lock()
_RSS_CACHE_TTL = 10 * 60        # 10 min per feed


def _fetch_rss(url):
    """Fetch + parse a single RSS feed. Returns list of dicts or []."""
    with _RSS_CACHE_LOCK:
        cached = _RSS_CACHE.get(url)
        if cached and cached['expires_at'] > time.time():
            return cached['items']

    try:
        import requests as req
        from lxml import etree
        resp = req.get(url, timeout=8, headers={
            'User-Agent': 'Mozilla/5.0 (RadimCare News Reader)',
        })
        if resp.status_code != 200 or not resp.content:
            return []
        root = etree.fromstring(resp.content)
        NS = {
            'media':   'http://search.yahoo.com/mrss/',
            'content': 'http://purl.org/rss/1.0/modules/content/',
            'atom':    'http://www.w3.org/2005/Atom',
        }
        out = []
        for it in root.findall('.//item')[:15]:
            title = (it.findtext('title') or '').strip()
            link = (it.findtext('link') or '').strip()
            desc = (it.findtext('description') or '').strip()
            pub  = (it.findtext('pubDate') or '').strip()
            # Image: try enclosure → media:thumbnail → media:content → og parse later
            image = None
            enc = it.find('enclosure')
            if enc is not None and enc.get('type', '').startswith('image'):
                image = enc.get('url')
            if not image:
                mt = it.find('media:thumbnail', NS)
                if mt is not None: image = mt.get('url')
            if not image:
                mc = it.find('media:content', NS)
                if mc is not None and mc.get('medium') != 'video':
                    image = mc.get('url')
            # Strip HTML from description
            if desc and '<' in desc:
                desc = re.sub(r'<[^>]+>', ' ', desc)
                desc = re.sub(r'\s+', ' ', desc).strip()
            if not title or not link:
                continue
            out.append({
                'title': title[:200],
                'link': link,
                'description': desc[:600],
                'pubDate': pub,
                'image': image,
            })
        with _RSS_CACHE_LOCK:
            _RSS_CACHE[url] = {'items': out, 'expires_at': time.time() + _RSS_CACHE_TTL}
        return out
    except Exception as e:
        logger.debug(f'RSS fetch error {url}: {e}')
        return []


def _interleave(lists):
    """Round-robin merge: first from each, then second from each, etc."""
    result = []
    max_len = max((len(l) for l in lists), default=0)
    for i in range(max_len):
        for l in lists:
            if i < len(l):
                result.append(l[i])
    return result


def _fetch_via_rss(category, count):
    """Fetch from real Czech RSS sources, summarize via Gemini if available.

    Returns list of article dicts compatible with the frontend schema:
        { id, title, summary, source, category, link, image, readTime, timestamp }
    """
    feeds = RSS_FEEDS.get(category)
    if not feeds:
        return None  # caller falls back to AI generation

    # Fetch in parallel (bounded)
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=min(4, len(feeds))) as ex:
        futs = {ex.submit(_fetch_rss, url): (src, url) for src, url in feeds}
        per_feed = {}
        for fut in cf.as_completed(futs, timeout=10):
            src, url = futs[fut]
            try:
                items = fut.result() or []
            except Exception:
                items = []
            # Attach source
            for it in items:
                it['source'] = src
            per_feed[src] = items

    # Interleave so we get variety
    merged = _interleave(list(per_feed.values()))
    if not merged:
        return None

    # Dedupe by normalized title prefix
    seen, deduped = set(), []
    for it in merged:
        key = re.sub(r'\s+', ' ', (it['title'] or '').lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
        if len(deduped) >= count * 2:  # take some extra, may discard in summarize
            break

    # Summarize via Gemini (senior-friendly 2-3 sentences per article)
    articles = _summarize_for_senior(deduped[:count], category)
    return articles


def _summarize_for_senior(items, category):
    """Batch-summarize RSS items into senior-friendly Czech summaries.

    Uses one Gemini call for the whole batch so latency stays low.
    Gemini sees the original title + description and writes a 2-3
    sentence summary adapted for a Czech senior reader. Falls back to
    the original RSS description if Gemini is unavailable.
    """
    import os
    ts = datetime.utcnow().isoformat()
    now_iso = datetime.now().isoformat()

    # Always wrap with our final article shape regardless of Gemini success
    def _wrap(items, summaries):
        out = []
        for i, it in enumerate(items):
            summary = (summaries[i] if i < len(summaries) else None) \
                      or (it.get('description') or it['title'])
            out.append({
                'id':       f"rss-{category}-{i}-{int(time.time())}",
                'title':    it['title'],
                'summary':  summary[:320].strip(),
                'source':   it.get('source', 'Zprávy'),
                'category': category,
                'link':     it.get('link'),
                'image':    it.get('image'),
                'publishedAt': it.get('pubDate') or now_iso,
                'readTime': _read_time(summary),
                'timestamp': ts,
            })
        return out

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key or not items:
        return _wrap(items, [])

    numbered = '\n\n'.join(
        f"{i+1}. TITULEK: {it['title']}\n   POPIS: {it.get('description','')[:400]}"
        for i, it in enumerate(items)
    )
    prompt = (
        "Jsi redaktor zpráv pro seniory. U každé ze zpráv níže napiš "
        "SENIOR-FRIENDLY SHRNUTÍ ve 2 nebo 3 krátkých jasných větách "
        "(max 220 znaků). Jednoduchá čeština, konkrétní fakta, neutrální nebo "
        "mírně pozitivní tón. Vrať VÝHRADNĚ tento formát, jedna zpráva per "
        "řádek: '1. <shrnutí>' přes '{n}. <shrnutí>'. Neuváděj titulek, "
        "žádné poznámky, žádný markdown.\n\n"
        f"ZPRÁVY:\n\n{numbered}"
    )
    try:
        import requests as req
        resp = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/'
            f'{GEMINI_MODEL}:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 1600},
            },
            timeout=18,
        )
        if resp.status_code != 200:
            logger.debug(f'Gemini summary HTTP {resp.status_code}')
            return _wrap(items, [])
        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        # Parse numbered lines back to list in order
        summaries = {}
        cur_idx = None
        cur_buf = []
        for line in text.strip().split('\n'):
            m = re.match(r'^\s*(\d+)[\.\)]\s*(.*)$', line)
            if m:
                if cur_idx is not None:
                    summaries[cur_idx] = ' '.join(cur_buf).strip()
                cur_idx = int(m.group(1)) - 1
                cur_buf = [m.group(2).strip()]
            else:
                if cur_idx is not None and line.strip():
                    cur_buf.append(line.strip())
        if cur_idx is not None:
            summaries[cur_idx] = ' '.join(cur_buf).strip()
        ordered = [summaries.get(i, '') for i in range(len(items))]
        return _wrap(items, ordered)
    except Exception as e:
        logger.warning(f'Gemini summarize failed: {e}')
        return _wrap(items, [])


def _read_time(summary):
    """Estimate read time in minutes from summary length.
    Czech ~180 WPM, rounded up to full minute, min 1 min."""
    words = len((summary or '').split())
    return f"{max(1, round(words / 180))} min"


def _fetch_with_ai(category, interests, count):
    """Preferred path: real RSS → Gemini summary. Falls back to AI-generated
    content only when no RSS sources are configured for the category (e.g.
    'tips') or when all feeds fail."""
    rss_articles = _fetch_via_rss(category, count)
    if rss_articles and len(rss_articles) >= 2:
        return rss_articles
    logger.info(f'📰 Falling back to AI-generated news for {category}')
    return _fetch_via_ai(category, interests, count)


def _fetch_via_ai(category, interests, count):
    """Legacy AI-generated path — used only when RSS not available."""
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
        'tv_program': 'dnešní televizní program hlavních českých stanic. Pro každý pořad uveď: v poli "source" název stanice (ČT1, ČT2, Nova, Prima), v "title" čas a název pořadu (např. "20:00 — Zprávy"), v "summary" krátký popis co to je.',
    }

    topic = category_prompts.get(category, category_prompts['general'])
    interest_ctx = ''
    if interests:
        interest_ctx = f" Senior se zajímá o: {', '.join(interests[:5])}. Zaměř se na tato témata."

    now = datetime.now()
    today_cs = now.strftime('%-d. %-m. %Y') if hasattr(now, 'strftime') else now.isoformat()
    # Hour-slot + minute seed → Gemini sees variation across refreshes,
    # while the server cache dedupes within the 15-min TTL.
    seed = f"{now.strftime('%H')}:{now.strftime('%M')[0]}0"
    # Weekday / season context — helps Gemini ground output in reality
    weekday_cs = [
        'pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota', 'neděle'
    ][now.weekday()]

    prompt = f"""Jsi redaktor zpráv pro seniory. Dnes je {weekday_cs} {today_cs}, aktuální čas {seed}.
Napiš {count} KRÁTKÝCH zpravodajských článků na téma: {topic}.{interest_ctx}

Důležité požadavky:
- Česky, krátké a jasné věty (senior-friendly)
- Každá zpráva jiná než ta předchozí — různá témata, různé zdroje, různé úhly
- Zdroje střídej: ČT24, iDNES, Seznam, Novinky, Blesk, ČTK, specializované weby
- Konkrétní fakta, čísla, data, místa (např. "Sněmovna 15. dubna schválila…")
- Pozitivní nebo neutrální tón (neděsit)
- Žádná opakovaná klišé typu "odborníci varují", "experti doporučují"

Formát odpovědi: VÝHRADNĚ JSON pole {count} objektů, nic jiného:
[{{"title": "<max 70 znaků>", "summary": "<2-3 věty, max 160 znaků, konkrétní>", "source": "<jméno zdroje>", "category": "{category}"}}]

Začni rovnou hranatou závorkou [, neuváděj markdown ani komentáře."""

    # Try Gemini first
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key:
        try:
            import requests as req
            resp = req.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_key}',
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
        'tv_program': [
            {'title': '8:00 — Studio 6', 'summary': 'Ranní zpravodajský magazín', 'source': 'ČT1'},
            {'title': '12:00 — Zprávy', 'summary': 'Polední zprávy', 'source': 'ČT1'},
            {'title': '14:10 — Receptář', 'summary': 'Vaření a tipy pro domácnost', 'source': 'ČT1'},
            {'title': '18:00 — Události v regionech', 'summary': 'Regionální zpravodajství', 'source': 'ČT1'},
            {'title': '19:15 — Události', 'summary': 'Hlavní zprávy dne', 'source': 'ČT1'},
            {'title': '20:00 — Film / Seriál', 'summary': 'Hlavní večerní program', 'source': 'ČT1'},
            {'title': '17:00 — Odpolední zprávy', 'summary': 'Přehled dne', 'source': 'Nova'},
            {'title': '19:30 — Televizní noviny', 'summary': 'Hlavní zprávy Nova', 'source': 'Nova'},
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
