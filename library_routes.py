# ============================================
# 📚 RADIM LIBRARY API BLUEPRINT
# ============================================
# Version: 1.0.0
# E-book knihovna pro seniory
# Endpoints: /kal/library/*

from flask import Blueprint, request, jsonify
from datetime import datetime
import random

library_bp = Blueprint('library', __name__)

# ============================================
# DEMO KNIHY (nahradit DB v produkci)
# ============================================

DEMO_BOOKS = {
    "book-001": {
        "id": "book-001",
        "title": "Babička",
        "author": "Božena Němcová",
        "description": "Klasický český román o moudrosti a životě na venkově. Příběh laskavé babičky a jejích vnoučat v krásné české krajině.",
        "category": "Klasika",
        "cover_image": "📖",
        "difficulty": "easy",
        "duration_minutes": 45,
        "tags": ["klasika", "česká literatura", "rodina", "venkov"],
        "language": "cs",
        "year": 1855,
        "pages": 320,
        "rating": 4.8,
        "reads": 1250,
        "chapters": [
            {"id": 1, "title": "Příjezd babičky", "paragraphs": [
                "Bylo to v měsíci květnu. Krásné jarní slunce svítilo na údolí, kde leželo malé městečko.",
                "Děti se radovaly z příjezdu babičky. Už z dálky viděly její laskavý úsměv.",
                "Babička přivezla s sebou vůni domova a plný košík dobrot z venkova.",
                "\"Pojďte sem, děťátka moje,\" volala babička a rozpřáhla náruč.",
                "A tak začal nejkrásnější čas v životě dětí — léto s babičkou."
            ]},
            {"id": 2, "title": "Život na venkově", "paragraphs": [
                "Každé ráno babička vstávala se sluncem. Její den začínal modlitbou a péčí o zahradu.",
                "Děti se od babičky učily poznávat byliny, zvířata a staré zvyky.",
                "Večer u krbu babička vyprávěla příběhy z dávných časů.",
                "\"Každý člověk má v sobě dobro,\" říkávala babička. \"Stačí ho jen najít.\"",
                "Venkovský život měl svůj poklidný rytmus, který léčil tělo i duši."
            ]},
            {"id": 3, "title": "Moudrost stáří", "paragraphs": [
                "Babička znala lék na každý neduh — bylinkový čaj, laskavé slovo, nebo jen tiché naslouchání.",
                "Celá vesnice si babičku vážila pro její moudrost a dobré srdce.",
                "\"Život je jako zahrada,\" říkávala. \"Co zaséješ, to sklidíš.\"",
                "Děti postupně chápaly, že největším pokladem není zlato, ale láska.",
                "A babičkina moudrost žila dál v srdcích všech, kteří ji znali."
            ]}
        ]
    },
    "book-002": {
        "id": "book-002",
        "title": "Pohádky z české kotliny",
        "author": "Karel Jaromír Erben",
        "description": "Sbírka tradičních českých pohádek plných moudrosti a poučení. Ideální pro večerní čtení.",
        "category": "Pohádky",
        "cover_image": "🏰",
        "difficulty": "easy",
        "duration_minutes": 30,
        "tags": ["pohádky", "tradice", "moudrost", "česká kultura"],
        "language": "cs",
        "year": 1853,
        "pages": 180,
        "rating": 4.9,
        "reads": 980,
        "chapters": [
            {"id": 1, "title": "O chytré horákyni", "paragraphs": [
                "Byl jednou jeden sedlák, a ten měl dceru. A ta dcera byla tak chytrá, že jí v celém kraji nebylo rovno.",
                "Jednoho dne přišel k nim na dvůr sám král a dal horákyni tři hádanky.",
                "\"Kdo tyto hádanky rozluští, tomu dám, co si přeje,\" pravil král.",
                "Horákyně se usmála a odpověděla na všechny tři hádanky správně.",
                "A tak se chytrá horákyně stala královnou a vládla moudře a spravedlivě."
            ]},
            {"id": 2, "title": "Zlatovláska", "paragraphs": [
                "Za devatero horami a devatero řekami žila princezna se zlatými vlasy.",
                "Její vlasy zářily jako slunce a kdokoli je spatřil, zůstal okouzlen.",
                "Statečný Jiřík se vydal na dlouhou cestu, aby princeznu našel.",
                "Cestou pomáhal každému, koho potkal — mravencům, rybám i ptákům.",
                "A právě díky své dobrotě a statečnosti nakonec Zlatovlásku získal."
            ]}
        ]
    },
    "book-003": {
        "id": "book-003",
        "title": "Zdraví v každém věku",
        "author": "MUDr. Jan Kovář",
        "description": "Praktické rady pro zdravý životní styl seniorů. Cvičení, výživa a duševní pohoda.",
        "category": "Zdraví",
        "cover_image": "💪",
        "difficulty": "easy",
        "duration_minutes": 25,
        "tags": ["zdraví", "cvičení", "výživa", "senior"],
        "language": "cs",
        "year": 2024,
        "pages": 150,
        "rating": 4.6,
        "reads": 750,
        "chapters": [
            {"id": 1, "title": "Ranní rozcvička", "paragraphs": [
                "Každé ráno začněte jednoduchým protažením. Stačí pět minut a váš den bude lepší.",
                "Pomalu se protáhněte v posteli — ruce nad hlavu, prsty na nohou k sobě.",
                "Vstávejte pomalu, nejdříve se posaďte a chvíli počkejte.",
                "U okna udělejte pět hlubokých nádechů. Čerstvý vzduch probudí tělo i mysl.",
                "Pravidelný pohyb je klíč k dlouhému a šťastnému životu."
            ]},
            {"id": 2, "title": "Výživa pro seniory", "paragraphs": [
                "Strava je základ zdraví v každém věku. Pro seniory je důležitá vyváženost.",
                "Jezte hodně zeleniny a ovoce — alespoň pět porcí denně.",
                "Pijte dostatek tekutin. Ideálně dva litry čisté vody nebo bylinného čaje.",
                "Bílkoviny jsou důležité pro udržení svalové hmoty. Ryby, drůbež, luštěniny.",
                "Dopřejte si občas i něco dobrého — radost z jídla je také zdravá!"
            ]}
        ]
    },
    "book-004": {
        "id": "book-004",
        "title": "Vzpomínky na mládí",
        "author": "Jaroslava Kolářová",
        "description": "Nostalgické příběhy z české historie 20. století. Vzpomínky na doby, kdy byl svět jednodušší.",
        "category": "Vzpomínky",
        "cover_image": "🕰️",
        "difficulty": "medium",
        "duration_minutes": 40,
        "tags": ["vzpomínky", "historie", "nostalgie", "Česko"],
        "language": "cs",
        "year": 2023,
        "pages": 240,
        "rating": 4.7,
        "reads": 620,
        "chapters": [
            {"id": 1, "title": "Prázdniny u babičky", "paragraphs": [
                "Každé léto jsme jezdili k babičce na venkov. Vlak jel pomalu přes zelené kopce.",
                "Babička nás vždycky čekala u plotu s čerstvým koláčem v ruce.",
                "Celé dny jsme trávili venku — koupání v potoce, sběr borůvek, hry na sena.",
                "Večer jsme seděli na lavičce a dívali se na hvězdy. Babička znala každý souhvězdí.",
                "Ty prázdniny byly nejkrásnější čas mého dětství."
            ]},
            {"id": 2, "title": "První tanec", "paragraphs": [
                "Na podzimním plese v sokolovně hrála kapela staré valčíky.",
                "Bylo mi patnáct a poprvé jsem si oblékla maminčiny lodičky.",
                "Zezačátku jsem se styděla, ale pak mě vytáhl k tanci Pepa od sousedů.",
                "Tančili jsme celý večer a já poprvé pochopila, proč milují dospělí hudbu.",
                "Dodnes, když slyším valčík, cítím motýlky v břiše jako tehdy."
            ]}
        ]
    },
    "book-005": {
        "id": "book-005",
        "title": "Kafánek a jeho přátelé",
        "author": "Tým Radim",
        "description": "Veselé příběhy pana Kafánka, moudrého kamaráda seniorů. Humor a moudrost v každé kapitole.",
        "category": "Humor",
        "cover_image": "☕",
        "difficulty": "easy",
        "duration_minutes": 20,
        "tags": ["humor", "kafánek", "přátelství", "radost"],
        "language": "cs",
        "year": 2025,
        "pages": 100,
        "rating": 4.9,
        "reads": 2100,
        "chapters": [
            {"id": 1, "title": "Jak Kafánek zachránil ráno", "paragraphs": [
                "Pan Kafánek se probudil dříve než ostatní. Slunce ještě spalo za kopcem.",
                "\"Dnes bude krásný den,\" řekl si a začal připravovat svou slavnou kávu.",
                "Vůně čerstvé kávy probudila celý dům seniorů. Jeden po druhém přicházeli do kuchyňky.",
                "\"Kafánku, ty jsi náš ranní hrdina!\" smála se paní Marie.",
                "A pan Kafánek věděl, že nejlepší začátek dne je sdílený úsměv a teplý šálek."
            ]},
            {"id": 2, "title": "Kafánkova zahradní slavnost", "paragraphs": [
                "Jednoho dne se pan Kafánek rozhodl uspořádat zahradní slavnost.",
                "Pozval všechny seniory z domu, ale taky sousedy a děti ze školky.",
                "Na zahradě voněly koláče, hrála hudba a všichni se smáli.",
                "Pan Dvořák dokonce vytáhl svou harmoniku a zahrál staré písničky.",
                "\"Tohle je to, na čem záleží,\" šeptal Kafánek. \"Být spolu.\""
            ]}
        ]
    },
    "book-006": {
        "id": "book-006",
        "title": "Zahrada pro radost",
        "author": "Ing. Helena Zelená",
        "description": "Praktický průvodce zahrádkařením pro seniory. Jednoduché postupy pro krásnou zahradu.",
        "category": "Hobby",
        "cover_image": "🌻",
        "difficulty": "easy",
        "duration_minutes": 35,
        "tags": ["zahrada", "hobby", "příroda", "relaxace"],
        "language": "cs",
        "year": 2024,
        "pages": 200,
        "rating": 4.5,
        "reads": 430,
        "chapters": [
            {"id": 1, "title": "Jarní příprava záhonků", "paragraphs": [
                "Jaro je čas nových začátků. I vaše zahrada potřebuje probudit z zimního spánku.",
                "Začněte lehkým přehrabáním půdy. Nemusíte kopat hluboko — stačí povrch.",
                "Vysejte nejdříve mrkev, petržel a ředkvičky. Ty zvládne i začátečník.",
                "Nezapomeňte na bylinky! Bazalka, rozmarýn a máta zkrášlí i okenní parapet.",
                "Zahradničení je nejlepší terapie. Ruce v hlíně, mysl v klidu."
            ]}
        ]
    }
}

# Uživatelský pokrok při čtení (bounded, max 500 users)
USER_PROGRESS = {}
_USER_PROGRESS_MAX = 500


def _evict_old_progress():
    """Remove oldest progress entries if over limit."""
    if len(USER_PROGRESS) <= _USER_PROGRESS_MAX:
        return
    # Sort by last_read timestamp, remove oldest
    sorted_users = sorted(
        USER_PROGRESS.keys(),
        key=lambda u: USER_PROGRESS[u].get('last_read', '')
    )
    for uid in sorted_users[:len(USER_PROGRESS) - _USER_PROGRESS_MAX]:
        del USER_PROGRESS[uid]

# ============================================
# HELPER FUNCTIONS
# ============================================

def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def get_book_compact(book):
    """Vrátí kompaktní verzi knihy (bez chapters/paragraphs)"""
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "description": book["description"],
        "category": book["category"],
        "cover_image": book["cover_image"],
        "difficulty": book["difficulty"],
        "duration_minutes": book["duration_minutes"],
        "tags": book["tags"],
        "language": book.get("language", "cs"),
        "year": book.get("year"),
        "pages": book.get("pages"),
        "rating": book.get("rating", 0),
        "reads": book.get("reads", 0),
        "chapter_count": len(book.get("chapters", []))
    }


# ============================================
# ENDPOINTS
# ============================================

@library_bp.route('/kal/library/books', methods=['GET'])
def list_books():
    """Seznam všech knih s volitelným filtrováním"""
    category = request.args.get('category', None)
    difficulty = request.args.get('difficulty', None)
    search = request.args.get('query', request.args.get('search', None))

    books = list(DEMO_BOOKS.values())

    if category:
        books = [b for b in books if b["category"].lower() == category.lower()]
    if difficulty:
        books = [b for b in books if b["difficulty"] == difficulty]
    if search:
        search_lower = search.lower()
        books = [b for b in books if
                 search_lower in b["title"].lower() or
                 search_lower in b["author"].lower() or
                 search_lower in b["description"].lower() or
                 any(search_lower in tag.lower() for tag in b["tags"])]

    compact_books = [get_book_compact(b) for b in books]

    return jsonify({
        "success": True,
        "count": len(compact_books),
        "books": compact_books,
        "categories": list(set(b["category"] for b in DEMO_BOOKS.values())),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/search', methods=['GET'])
def search_books():
    """Vyhledávání knih"""
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return jsonify({"success": False, "error": "Parametr 'query' je vyžadován"}), 400

    query_lower = query.lower()
    results = []
    for book in DEMO_BOOKS.values():
        score = 0
        if query_lower in book["title"].lower():
            score += 10
        if query_lower in book["author"].lower():
            score += 8
        if query_lower in book["description"].lower():
            score += 5
        for tag in book["tags"]:
            if query_lower in tag.lower():
                score += 3
        if query_lower == book["category"].lower():
            score += 6

        if score > 0:
            result = get_book_compact(book)
            result["relevance_score"] = score
            results.append(result)

    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    return jsonify({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results,
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/categories', methods=['GET'])
def list_categories():
    """Seznam kategorií s počtem knih"""
    categories = {}
    for book in DEMO_BOOKS.values():
        cat = book["category"]
        if cat not in categories:
            categories[cat] = {"name": cat, "count": 0, "books": []}
        categories[cat]["count"] += 1
        categories[cat]["books"].append({"id": book["id"], "title": book["title"]})

    return jsonify({
        "success": True,
        "categories": list(categories.values()),
        "total_books": len(DEMO_BOOKS),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/books/<book_id>', methods=['GET'])
def get_book(book_id):
    """Detail knihy včetně seznamu kapitol (bez plného textu)"""
    book = DEMO_BOOKS.get(book_id)
    if not book:
        return jsonify({
            "success": False,
            "error": f"Kniha {book_id} nenalezena",
            "available_ids": list(DEMO_BOOKS.keys())
        }), 404

    # Vrátit knihu s kapitolami ale bez paragraphs
    book_detail = get_book_compact(book)
    book_detail["chapters"] = [
        {"id": ch["id"], "title": ch["title"], "paragraph_count": len(ch["paragraphs"])}
        for ch in book.get("chapters", [])
    ]

    return jsonify({
        "success": True,
        "book": book_detail,
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/read/<book_id>', methods=['GET'])
def read_book(book_id):
    """Čtení knihy — vrátí plný text kapitol"""
    book = DEMO_BOOKS.get(book_id)
    if not book:
        return jsonify({"success": False, "error": f"Kniha {book_id} nenalezena"}), 404

    chapter_id = request.args.get('chapter', None, type=int)

    if chapter_id is not None:
        # Vrátit konkrétní kapitolu
        chapter = next((ch for ch in book["chapters"] if ch["id"] == chapter_id), None)
        if not chapter:
            return jsonify({"success": False, "error": f"Kapitola {chapter_id} nenalezena"}), 404
        return jsonify({
            "success": True,
            "book_id": book_id,
            "book_title": book["title"],
            "chapter": chapter,
            "timestamp": now_iso()
        })

    # Vrátit všechny kapitoly
    return jsonify({
        "success": True,
        "book_id": book_id,
        "book_title": book["title"],
        "author": book["author"],
        "chapters": book["chapters"],
        "total_chapters": len(book["chapters"]),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/progress', methods=['GET', 'POST'])
def handle_progress():
    """Správa pokroku čtení"""
    if request.method == 'POST':
        data = request.json or {}
        user_id = data.get('userId', 'anonymous')
        book_id = data.get('bookId')
        chapter_id = data.get('chapterId')
        paragraph = data.get('paragraph', 0)
        percent = data.get('percent', 0)

        if not book_id:
            return jsonify({"success": False, "error": "bookId je vyžadováno"}), 400

        if user_id not in USER_PROGRESS:
            _evict_old_progress()
            USER_PROGRESS[user_id] = {}

        USER_PROGRESS[user_id][book_id] = {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "paragraph": paragraph,
            "percent": percent,
            "updated_at": now_iso()
        }

        return jsonify({
            "success": True,
            "message": "Pokrok uložen",
            "progress": USER_PROGRESS[user_id][book_id],
            "timestamp": now_iso()
        })

    # GET — vrátit pokrok uživatele
    user_id = request.args.get('userId', 'anonymous')
    progress = USER_PROGRESS.get(user_id, {})
    return jsonify({
        "success": True,
        "user_id": user_id,
        "progress": progress,
        "books_started": len(progress),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/recommend/<user_id>', methods=['GET'])
def recommend_books(user_id):
    """Doporučení knih na základě historie"""
    # Zjistit, co uživatel již četl
    read_books = set(USER_PROGRESS.get(user_id, {}).keys())

    # Doporučit knihy, které ještě nečetl
    recommendations = []
    for book_id, book in DEMO_BOOKS.items():
        if book_id not in read_books:
            rec = get_book_compact(book)
            # Přidat důvod doporučení
            reasons = []
            if book["rating"] >= 4.8:
                reasons.append("Vysoce hodnocená")
            if book["difficulty"] == "easy":
                reasons.append("Snadné čtení")
            if book["reads"] > 1000:
                reasons.append("Oblíbená u čtenářů")
            if "kafánek" in " ".join(book["tags"]).lower():
                reasons.append("Od pana Kafánka")
            rec["recommendation_reasons"] = reasons if reasons else ["Nový titul pro vás"]
            recommendations.append(rec)

    # Seřadit podle ratingu
    recommendations.sort(key=lambda x: x.get("rating", 0), reverse=True)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "recommendations": recommendations[:5],
        "total_available": len(recommendations),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/stats', methods=['GET'])
def library_stats():
    """Statistiky knihovny"""
    categories = {}
    total_chapters = 0
    total_reads = 0

    for book in DEMO_BOOKS.values():
        cat = book["category"]
        categories[cat] = categories.get(cat, 0) + 1
        total_chapters += len(book.get("chapters", []))
        total_reads += book.get("reads", 0)

    return jsonify({
        "success": True,
        "stats": {
            "total_books": len(DEMO_BOOKS),
            "total_chapters": total_chapters,
            "total_reads": total_reads,
            "categories": categories,
            "avg_rating": round(sum(b.get("rating", 0) for b in DEMO_BOOKS.values()) / len(DEMO_BOOKS), 1),
            "active_readers": len(USER_PROGRESS),
            "most_popular": max(DEMO_BOOKS.values(), key=lambda b: b.get("reads", 0))["title"]
        },
        "timestamp": now_iso()
    })
