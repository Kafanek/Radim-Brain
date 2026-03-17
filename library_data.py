# ============================================
# RADIM LIBRARY DATA v1.0.0
# ============================================
# Static book data and helpers for Library API.
# Extracted from library_routes.py for modularity.
# ============================================

import logging

logger = logging.getLogger(__name__)


# ============================================
# DEMO BOOKS (nahradit DB v produkci)
# ============================================

DEMO_BOOKS = {
    "book-001": {
        "id": "book-001",
        "title": "Babicka",
        "author": "Bozena Nemcova",
        "description": "Klasicky cesky roman o moudrosti a zivote na venkove. Pribeh laskave babicky a jejich vnoucat v krasne ceske krajine.",
        "category": "Klasika",
        "cover_image": "\U0001f4d6",
        "difficulty": "easy",
        "duration_minutes": 45,
        "tags": ["klasika", "ceska literatura", "rodina", "venkov"],
        "language": "cs",
        "year": 1855,
        "pages": 320,
        "rating": 4.8,
        "reads": 1250,
        "chapters": [
            {"id": 1, "title": "Prijezd babicky", "paragraphs": [
                "Bylo to v mesici kvetnu. Krasne jarni slunce svitilo na udoli, kde lezelo male mestecko.",
                "Deti se radovaly z prijezdu babicky. Uz z dalky videly jeji laskavy usmev.",
                "Babicka privezla s sebou vuni domova a plny kosik dobrot z venkova.",
                "\"Pojdte sem, detatka moje,\" volala babicka a rozprahla naruc.",
                "A tak zacal nejkrasnejsi cas v zivote deti -- leto s babickou."
            ]},
            {"id": 2, "title": "Zivot na venkove", "paragraphs": [
                "Kazde rano babicka vstavala se sluncem. Jeji den zacinal modlitbou a peci o zahradu.",
                "Deti se od babicky ucily poznavat byliny, zvirata a stare zvyky.",
                "Vecer u krbu babicka vypravela pribehy z davnych casu.",
                "\"Kazdy clovek ma v sobe dobro,\" rikavala babicka. \"Staci ho jen najit.\"",
                "Venkovský zivot mel svuj poklidny rytmus, ktery lecil telo i dusi."
            ]},
            {"id": 3, "title": "Moudrost stari", "paragraphs": [
                "Babicka znala lek na kazdy neduh -- bylinkovy caj, laskave slovo, nebo jen tiche naslouchani.",
                "Cela vesnice si babicku vazila pro jeji moudrost a dobre srdce.",
                "\"Zivot je jako zahrada,\" rikavala. \"Co zasejes, to sklizis.\"",
                "Deti postupne chapaly, ze nejvetsi pokladem neni zlato, ale laska.",
                "A babickina moudrost zila dal v srdcich vsech, kteri ji znali."
            ]}
        ]
    },
    "book-002": {
        "id": "book-002",
        "title": "Pohadky z ceske kotliny",
        "author": "Karel Jaromir Erben",
        "description": "Sbirka tradicnich ceskych pohadek plnych moudrosti a pouceni. Idealni pro vecerni cteni.",
        "category": "Pohadky",
        "cover_image": "\U0001f3f0",
        "difficulty": "easy",
        "duration_minutes": 30,
        "tags": ["pohadky", "tradice", "moudrost", "ceska kultura"],
        "language": "cs",
        "year": 1853,
        "pages": 180,
        "rating": 4.9,
        "reads": 980,
        "chapters": [
            {"id": 1, "title": "O chytre horakyni", "paragraphs": [
                "Byl jednou jeden sedlak, a ten mel dceru. A ta dcera byla tak chytra, ze ji v celem kraji nebylo rovno.",
                "Jednoho dne prisel k nim na dvur sam kral a dal horakyni tri hadanky.",
                "\"Kdo tyto hadanky rozlusti, tomu dam, co si preje,\" pravil kral.",
                "Horakyne se usmala a odpovedela na vsechny tri hadanky spravne.",
                "A tak se chytra horakyne stala kralovnou a vladla moudre a spravedlive."
            ]},
            {"id": 2, "title": "Zlatovlaska", "paragraphs": [
                "Za devatero horami a devatero rekami zila princezna se zlatymi vlasy.",
                "Jeji vlasy zarily jako slunce a kdokoli je spatril, zustal okouzlen.",
                "Statecny Jirik se vydal na dlouhou cestu, aby princeznu nasel.",
                "Cestou pomahal kazdemu, koho potkal -- mravencum, rybam i ptakum.",
                "A prave diky sve dobrote a statecnosti nakonec Zlatovlasku ziskal."
            ]}
        ]
    },
    "book-003": {
        "id": "book-003",
        "title": "Zdravi v kazdem veku",
        "author": "MUDr. Jan Kovar",
        "description": "Prakticke rady pro zdravy zivotni styl senioru. Cviceni, vyziva a dusevni pohoda.",
        "category": "Zdravi",
        "cover_image": "\U0001f4aa",
        "difficulty": "easy",
        "duration_minutes": 25,
        "tags": ["zdravi", "cviceni", "vyziva", "senior"],
        "language": "cs",
        "year": 2024,
        "pages": 150,
        "rating": 4.6,
        "reads": 750,
        "chapters": [
            {"id": 1, "title": "Ranni rozcvicka", "paragraphs": [
                "Kazde rano zacnete jednoduchym protazenim. Staci pet minut a vas den bude lepsi.",
                "Pomalu se protahnete v posteli -- ruce nad hlavu, prsty na nohou k sobe.",
                "Vstavejte pomalu, nejdrive se posadte a chvili pockejte.",
                "U okna udelejte pet hlubokych nadechu. Cerstvý vzduch probudi telo i mysl.",
                "Pravidelny pohyb je klic k dlouhemu a stastnemu zivotu."
            ]},
            {"id": 2, "title": "Vyziva pro seniory", "paragraphs": [
                "Strava je zaklad zdravi v kazdem veku. Pro seniory je dulezita vyvazenost.",
                "Jezte hodne zeleniny a ovoce -- alespon pet porci denne.",
                "Pijte dostatek tekutin. Idealne dva litry ciste vody nebo bylinkoveho caje.",
                "Bilkoviny jsou dulezite pro udrzeni svalove hmoty. Ryby, drubez, lusteniny.",
                "Doprejte si obcas i neco dobreho -- radost z jidla je take zdrava!"
            ]}
        ]
    },
    "book-004": {
        "id": "book-004",
        "title": "Vzpominky na mladi",
        "author": "Jaroslava Kolarova",
        "description": "Nostalgicke pribehy z ceske historie 20. stoleti. Vzpominky na doby, kdy byl svet jednodussi.",
        "category": "Vzpominky",
        "cover_image": "\U0001f570\ufe0f",
        "difficulty": "medium",
        "duration_minutes": 40,
        "tags": ["vzpominky", "historie", "nostalgie", "Cesko"],
        "language": "cs",
        "year": 2023,
        "pages": 240,
        "rating": 4.7,
        "reads": 620,
        "chapters": [
            {"id": 1, "title": "Prazdniny u babicky", "paragraphs": [
                "Kazde leto jsme jezdili k babicce na venkov. Vlak jel pomalu pres zelene kopce.",
                "Babicka nas vzdycky cekala u plotu s cerstvym kolacem v ruce.",
                "Cele dny jsme travili venku -- koupani v potoce, sber boruvek, hry na sena.",
                "Vecer jsme sedeli na lavicce a divali se na hvezdy. Babicka znala kazdy souhvezdi.",
                "Ty prazdniny byly nejkrasnejsi cas meho detstvi."
            ]},
            {"id": 2, "title": "Prvni tanec", "paragraphs": [
                "Na podzimnim plese v sokolovne hrala kapela stare valciky.",
                "Bylo mi patnact a poprve jsem si oblekla maminciny lodicky.",
                "Zezacatku jsem se stydela, ale pak me vytahl k tanci Pepa od sousedu.",
                "Tancili jsme cely vecer a ja poprve pochopila, proc miluji dospeli hudbu.",
                "Dodnes, kdyz slysim valcik, citim motylky v brise jako tehdy."
            ]}
        ]
    },
    "book-005": {
        "id": "book-005",
        "title": "Kafanek a jeho pratele",
        "author": "Tym Radim",
        "description": "Vesele pribehy pana Kafanka, moudreho kamarada senioru. Humor a moudrost v kazde kapitole.",
        "category": "Humor",
        "cover_image": "\u2615",
        "difficulty": "easy",
        "duration_minutes": 20,
        "tags": ["humor", "kafanek", "pratelstvi", "radost"],
        "language": "cs",
        "year": 2025,
        "pages": 100,
        "rating": 4.9,
        "reads": 2100,
        "chapters": [
            {"id": 1, "title": "Jak Kafanek zachranil rano", "paragraphs": [
                "Pan Kafanek se probudil drive nez ostatni. Slunce jeste spalo za kopcem.",
                "\"Dnes bude krasny den,\" rekl si a zacal pripravovat svou slavnou kavu.",
                "Vune cerstve kavy probudila cely dum senioru. Jeden po druhem prichazeli do kuchynky.",
                "\"Kafanku, ty jsi nas ranni hrdina!\" smala se pani Marie.",
                "A pan Kafanek vedel, ze nejlepsi zacatek dne je sdileny usmev a teply salek."
            ]},
            {"id": 2, "title": "Kafankova zahradni slavnost", "paragraphs": [
                "Jednoho dne se pan Kafanek rozhodl usporadat zahradni slavnost.",
                "Pozval vsechny seniory z domu, ale taky sousedy a deti ze skolky.",
                "Na zahrade vonely kolace, hrala hudba a vsichni se smali.",
                "Pan Dvorak dokonce vytahl svou harmoniku a zahral stare pisnicky.",
                "\"Tohle je to, na cem zalezi,\" septal Kafanek. \"Byt spolu.\""
            ]}
        ]
    },
    "book-006": {
        "id": "book-006",
        "title": "Zahrada pro radost",
        "author": "Ing. Helena Zelena",
        "description": "Prakticky pruvodce zahradkarenim pro seniory. Jednoduche postupy pro krasnou zahradu.",
        "category": "Hobby",
        "cover_image": "\U0001f33b",
        "difficulty": "easy",
        "duration_minutes": 35,
        "tags": ["zahrada", "hobby", "priroda", "relaxace"],
        "language": "cs",
        "year": 2024,
        "pages": 200,
        "rating": 4.5,
        "reads": 430,
        "chapters": [
            {"id": 1, "title": "Jarni priprava zahonku", "paragraphs": [
                "Jaro je cas novych zacatku. I vase zahrada potrebuje probudit z zimniho spanku.",
                "Zacnete lehkym prehrabanim pudy. Nemusite kopat hluboko -- staci povrch.",
                "Vysejte nejdrive mrkev, petržel a redkvicky. Ty zvladne i zacatecnik.",
                "Nezapomente na bylinky! Bazalka, rozmarin a mata zkrasli i okenni parapet.",
                "Zahradniceni je nejlepsi terapie. Ruce v hline, mysl v klidu."
            ]}
        ]
    }
}


# ============================================
# USER PROGRESS TRACKING
# ============================================

# Uživatelský pokrok při čtení (bounded, max 500 users)
USER_PROGRESS = {}
_USER_PROGRESS_MAX = 500


def evict_old_progress():
    """Remove oldest progress entries if over limit."""
    if len(USER_PROGRESS) <= _USER_PROGRESS_MAX:
        return
    sorted_users = sorted(
        USER_PROGRESS.keys(),
        key=lambda u: USER_PROGRESS[u].get('last_read', '')
    )
    for uid in sorted_users[:len(USER_PROGRESS) - _USER_PROGRESS_MAX]:
        del USER_PROGRESS[uid]


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_book_compact(book):
    """Return compact version of book (without chapters/paragraphs)"""
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


logger.info("Library Data v1.0.0 loaded — 6 books, helpers")
