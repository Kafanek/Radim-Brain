"""
🌍 CLAUDE CONTENT I18N — translation tables for news/weather/quiz/story endpoints.

X21.17: Supports cs/sk/pl/hu/en. Czech is the default fallback for missing keys.

Used by claude_content_routes.py.
"""

SUPPORTED_LANGS = ('cs', 'sk', 'pl', 'hu', 'en')


def normalize_lang(lang):
    """Return lang if supported, else 'cs'."""
    if not lang:
        return 'cs'
    raw = str(lang).split(',')[0].split('-')[0].strip().lower()
    return raw if raw in SUPPORTED_LANGS else 'cs'


# ── NEWS ─────────────────────────────────────────────────────────────────

# Category-specific search queries by language.
NEWS_QUERIES = {
    'cs': {
        'politics': 'české politické zprávy dnes',
        'sports':   'český sport zprávy hokej fotbal',
        'health':   'zdraví zprávy tipy pro seniory',
        'culture':  'kultura Praha divadlo koncerty',
        'science':  'věda technika zajímavosti Česko',
        'local':    'Praha zprávy doprava události',
        'general':  'hlavní české zprávy dnes',
    },
    'sk': {
        'politics': 'slovenské politické správy dnes',
        'sports':   'slovenský šport hokej futbal',
        'health':   'zdravie správy tipy pre seniorov',
        'culture':  'kultúra Bratislava divadlo koncerty',
        'science':  'veda technika zaujímavosti Slovensko',
        'local':    'Bratislava správy doprava udalosti',
        'general':  'hlavné slovenské správy dnes',
    },
    'pl': {
        'politics': 'polskie wiadomości polityczne dzisiaj',
        'sports':   'polski sport hokej piłka nożna',
        'health':   'zdrowie wiadomości porady dla seniorów',
        'culture':  'kultura Warszawa teatr koncerty',
        'science':  'nauka technika ciekawostki Polska',
        'local':    'Warszawa wiadomości transport wydarzenia',
        'general':  'główne polskie wiadomości dzisiaj',
    },
    'hu': {
        'politics': 'magyar politikai hírek ma',
        'sports':   'magyar sport jégkorong futball hírek',
        'health':   'egészség hírek tippek időseknek',
        'culture':  'kultúra Budapest színház koncertek',
        'science':  'tudomány technika érdekességek Magyarország',
        'local':    'Budapest hírek közlekedés események',
        'general':  'fő magyar hírek ma',
    },
    'en': {
        'politics': 'world politics news today',
        'sports':   'sports news hockey football today',
        'health':   'health news tips for seniors',
        'culture':  'culture theater concerts',
        'science':  'science technology discoveries',
        'local':    'local news transport events',
        'general':  'top headlines today',
    },
}

# System prompt templates by language. {count}, {category}, {date} interpolated.
NEWS_SYSTEM = {
    'cs': """Vyhledej {count} aktuálních zpráv (v češtině) z kategorie: {category}.

FORMÁT (pouze JSON pole):
[
  {{"title": "Titulek", "description": "Popis", "source": "Zdroj"}}
]

Dnešní datum: {date}""",
    'sk': """Vyhľadaj {count} aktuálnych správ (v slovenčine) z kategórie: {category}.

FORMÁT (iba JSON pole):
[
  {{"title": "Titulok", "description": "Popis", "source": "Zdroj"}}
]

Dnešný dátum: {date}""",
    'pl': """Znajdź {count} aktualnych wiadomości (po polsku) z kategorii: {category}.

FORMAT (tylko tablica JSON):
[
  {{"title": "Tytuł", "description": "Opis", "source": "Źródło"}}
]

Dzisiejsza data: {date}""",
    'hu': """Keress {count} aktuális hírt (magyarul) a kategóriából: {category}.

FORMÁTUM (csak JSON tömb):
[
  {{"title": "Cím", "description": "Leírás", "source": "Forrás"}}
]

Mai dátum: {date}""",
    'en': """Find {count} current news articles (in English) in category: {category}.

FORMAT (JSON array only):
[
  {{"title": "Headline", "description": "Description", "source": "Source"}}
]

Today's date: {date}""",
}

# User message templates.
NEWS_USER = {
    'cs': "Vyhledej zprávy: {query}",
    'sk': "Vyhľadaj správy: {query}",
    'pl': "Znajdź wiadomości: {query}",
    'hu': "Keress híreket: {query}",
    'en': "Find news: {query}",
}

# AI summary strings.
NEWS_SUMMARY = {
    'cs': "{n} zpráv ke dni {date}",
    'sk': "{n} správ ku dňu {date}",
    'pl': "{n} wiadomości na dzień {date}",
    'hu': "{n} hír a napra {date}",
    'en': "{n} articles for {date}",
}

NEWS_OFFLINE_SUMMARY = {
    'cs': "Lokální zprávy (AI nedostupná)",
    'sk': "Lokálne správy (AI nedostupná)",
    'pl': "Lokalne wiadomości (AI niedostępna)",
    'hu': "Helyi hírek (AI nem elérhető)",
    'en': "Local news (AI unavailable)",
}

# Fallback news (used when Claude/Gemini both fail). Per-category, per-language.
NEWS_FALLBACK = {
    'cs': {
        'politics': [
            {"title": "Vláda schválila sociální podporu", "description": "Rozšíření příspěvků pro seniory.", "source": "ČTK"},
            {"title": "Prezident v Bruselu", "description": "Summit EU.", "source": "iDNES"},
        ],
        'sports': [
            {"title": "Hokejisté vyhráli turnaj", "description": "Zlatá medaile.", "source": "Sport.cz"},
            {"title": "Sparta v Lize mistrů", "description": "Vítězství 2:1.", "source": "iSport"},
        ],
        'health': [
            {"title": "Očkování proti chřipce", "description": "Zdarma pro seniory 65+.", "source": "VZP"},
            {"title": "Prevence je základ", "description": "Pravidelné prohlídky.", "source": "MZ ČR"},
        ],
        'culture': [
            {"title": "Národní divadlo: premiéra", "description": "Prodaná nevěsta.", "source": "Kultura.cz"},
            {"title": "Výstava Muchy", "description": "Retrospektiva v Praze.", "source": "Aktuálně.cz"},
        ],
        'science': [
            {"title": "Nová exoplaneta", "description": "Objev astronomů.", "source": "Akademie věd"},
            {"title": "AI v medicíně", "description": "Diagnostika s 95% přesností.", "source": "Tech.cz"},
        ],
        'local': [
            {"title": "Metro D se staví", "description": "Otevření v 2027.", "source": "Praha.eu"},
            {"title": "Farmářské trhy", "description": "Každou sobotu.", "source": "Pražský deník"},
        ],
    },
    'sk': {
        'politics': [
            {"title": "Vláda schválila sociálnu podporu", "description": "Rozšírenie príspevkov pre seniorov.", "source": "TASR"},
            {"title": "Prezident v Bruseli", "description": "Summit EÚ.", "source": "SME"},
        ],
        'sports': [
            {"title": "Hokejisti vyhrali turnaj", "description": "Zlatá medaila.", "source": "Šport.sk"},
            {"title": "Slovan v lige", "description": "Víťazstvo 2:1.", "source": "Pravda"},
        ],
        'health': [
            {"title": "Očkovanie proti chrípke", "description": "Zdarma pre seniorov 65+.", "source": "VšZP"},
            {"title": "Prevencia je základ", "description": "Pravidelné prehliadky.", "source": "MZ SR"},
        ],
        'culture': [
            {"title": "SND: premiéra", "description": "Predaná nevesta.", "source": "Kultura.sk"},
            {"title": "Výstava Muchu", "description": "Retrospektíva.", "source": "Aktuality"},
        ],
        'science': [
            {"title": "Nová exoplanéta", "description": "Objav astronómov.", "source": "SAV"},
            {"title": "AI v medicíne", "description": "Diagnostika 95% presnosť.", "source": "Tech.sk"},
        ],
        'local': [
            {"title": "Bratislava: doprava", "description": "Nová električková trať.", "source": "Bratislava.sk"},
            {"title": "Trhy v meste", "description": "Každú sobotu.", "source": "Bratislavské noviny"},
        ],
    },
    'pl': {
        'politics': [
            {"title": "Rząd zatwierdził wsparcie społeczne", "description": "Rozszerzenie świadczeń dla seniorów.", "source": "PAP"},
            {"title": "Prezydent w Brukseli", "description": "Szczyt UE.", "source": "Onet"},
        ],
        'sports': [
            {"title": "Hokeiści wygrali turniej", "description": "Złoty medal.", "source": "Sport.pl"},
            {"title": "Legia w Lidze Mistrzów", "description": "Zwycięstwo 2:1.", "source": "Przegląd Sportowy"},
        ],
        'health': [
            {"title": "Szczepienia przeciw grypie", "description": "Bezpłatnie dla seniorów 65+.", "source": "NFZ"},
            {"title": "Profilaktyka to podstawa", "description": "Regularne badania.", "source": "MZ"},
        ],
        'culture': [
            {"title": "Teatr Narodowy: premiera", "description": "Wesele.", "source": "Kultura.pl"},
            {"title": "Wystawa Wyspiańskiego", "description": "Retrospektywa.", "source": "Onet"},
        ],
        'science': [
            {"title": "Nowa egzoplaneta", "description": "Odkrycie astronomów.", "source": "PAN"},
            {"title": "AI w medycynie", "description": "Diagnostyka 95% dokładności.", "source": "Spider's Web"},
        ],
        'local': [
            {"title": "Warszawa: metro", "description": "Nowa linia.", "source": "Warszawa.pl"},
            {"title": "Targi miejskie", "description": "Każdą sobotę.", "source": "Gazeta Stołeczna"},
        ],
    },
    'hu': {
        'politics': [
            {"title": "A kormány szociális támogatást fogadott el", "description": "Idősek juttatásainak bővítése.", "source": "MTI"},
            {"title": "Elnök Brüsszelben", "description": "EU csúcs.", "source": "Index"},
        ],
        'sports': [
            {"title": "Jégkorongozók nyertek tornát", "description": "Aranyérem.", "source": "Nemzeti Sport"},
            {"title": "Fradi a Bajnokok Ligájában", "description": "2:1 győzelem.", "source": "Sport24"},
        ],
        'health': [
            {"title": "Influenza elleni oltás", "description": "Ingyenes 65+ idősebbeknek.", "source": "OEP"},
            {"title": "A megelőzés alapvető", "description": "Rendszeres szűrések.", "source": "EMMI"},
        ],
        'culture': [
            {"title": "Operaház: premier", "description": "Hunyadi László.", "source": "Kultura.hu"},
            {"title": "Munkácsy kiállítás", "description": "Retrospektív.", "source": "Index"},
        ],
        'science': [
            {"title": "Új exobolygó", "description": "Csillagászok felfedezése.", "source": "MTA"},
            {"title": "AI a gyógyászatban", "description": "95% pontosság.", "source": "HVG Tech"},
        ],
        'local': [
            {"title": "Budapest: metró", "description": "Új vonal.", "source": "Budapest.hu"},
            {"title": "Városi piacok", "description": "Minden szombat.", "source": "Pesti Hírlap"},
        ],
    },
    'en': {
        'politics': [
            {"title": "Government approves social support", "description": "Expanded benefits for seniors.", "source": "Reuters"},
            {"title": "President at EU summit", "description": "Security talks in Brussels.", "source": "BBC"},
        ],
        'sports': [
            {"title": "Hockey team wins tournament", "description": "Gold medal victory.", "source": "ESPN"},
            {"title": "Champions League win", "description": "2:1 home victory.", "source": "BBC Sport"},
        ],
        'health': [
            {"title": "Free flu vaccination", "description": "Available for seniors 65+.", "source": "WHO"},
            {"title": "Prevention is key", "description": "Regular check-ups recommended.", "source": "NHS"},
        ],
        'culture': [
            {"title": "National Theatre: new premiere", "description": "Classical opera staging.", "source": "Culture News"},
            {"title": "Art retrospective", "description": "Major museum exhibition.", "source": "Guardian"},
        ],
        'science': [
            {"title": "New exoplanet discovered", "description": "Astronomers report find.", "source": "Nature"},
            {"title": "AI in medicine", "description": "95% diagnostic accuracy.", "source": "MIT Tech Review"},
        ],
        'local': [
            {"title": "New metro line", "description": "Opening planned for 2027.", "source": "City News"},
            {"title": "Farmers markets", "description": "Every Saturday in town.", "source": "Local Times"},
        ],
    },
}


# ── WEATHER ──────────────────────────────────────────────────────────────

WEATHER_SYSTEM = {
    'cs': """Vyhledej aktuální počasí a odpověz POUZE jako JSON (popisy v češtině):
{"temperature": 5, "condition": "Oblačno", "humidity": 75, "wind": 12, "forecast": "Odpoledne déšť."}""",
    'sk': """Vyhľadaj aktuálne počasie a odpovedz IBA ako JSON (popisy v slovenčine):
{"temperature": 5, "condition": "Oblačno", "humidity": 75, "wind": 12, "forecast": "Popoludní dážď."}""",
    'pl': """Znajdź aktualną pogodę i odpowiedz TYLKO jako JSON (opisy po polsku):
{"temperature": 5, "condition": "Pochmurno", "humidity": 75, "wind": 12, "forecast": "Po południu deszcz."}""",
    'hu': """Keresd meg az aktuális időjárást, és válaszolj CSAK JSON-ként (leírások magyarul):
{"temperature": 5, "condition": "Felhős", "humidity": 75, "wind": 12, "forecast": "Délután eső."}""",
    'en': """Find the current weather and respond ONLY as JSON (descriptions in English):
{"temperature": 5, "condition": "Cloudy", "humidity": 75, "wind": 12, "forecast": "Rain in the afternoon."}""",
}

WEATHER_USER = {
    'cs': "Aktuální počasí v {location}?",
    'sk': "Aktuálne počasie v {location}?",
    'pl': "Aktualna pogoda w {location}?",
    'hu': "Mai időjárás itt: {location}?",
    'en': "Current weather in {location}?",
}

# Static condition strings + unknown for fallback.
WEATHER_FALLBACK_CONDITIONS = {
    'cs': {'winter': 'Zataženo', 'spring': 'Polojasno', 'summer': 'Jasno',  'autumn': 'Oblačno', 'unknown': 'Neznámé', 'unavailable': 'Informace nedostupná'},
    'sk': {'winter': 'Zatiahnuté', 'spring': 'Polojasno', 'summer': 'Jasno', 'autumn': 'Oblačno', 'unknown': 'Neznáme', 'unavailable': 'Informácia nedostupná'},
    'pl': {'winter': 'Pochmurno', 'spring': 'Częściowo pochmurnie', 'summer': 'Słonecznie', 'autumn': 'Pochmurno', 'unknown': 'Nieznane', 'unavailable': 'Informacje niedostępne'},
    'hu': {'winter': 'Felhős', 'spring': 'Részben felhős', 'summer': 'Napos', 'autumn': 'Felhős', 'unknown': 'Ismeretlen', 'unavailable': 'Információ nem elérhető'},
    'en': {'winter': 'Overcast', 'spring': 'Partly cloudy', 'summer': 'Sunny', 'autumn': 'Cloudy', 'unknown': 'Unknown', 'unavailable': 'Information unavailable'},
}


# ── QUIZ ─────────────────────────────────────────────────────────────────

QUIZ_SYSTEM = {
    'cs': """Vytvoř {count} kvízových otázek pro seniory (v češtině).
Téma: {topic}, Obtížnost: {difficulty}

Krátké otázky, krátké odpovědi (max 60 znaků každá), krátké explanace.

FORMÁT (pouze JSON):
[{{"question": "Otázka?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Vysvětlení."}}]""",
    'sk': """Vytvor {count} kvízových otázok pre seniorov (v slovenčine).
Téma: {topic}, Obtiažnosť: {difficulty}

Krátke otázky, krátke odpovede (max 60 znakov každá), krátke vysvetlenia.

FORMÁT (iba JSON):
[{{"question": "Otázka?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Vysvetlenie."}}]""",
    'pl': """Stwórz {count} pytań quizowych dla seniorów (po polsku).
Temat: {topic}, Trudność: {difficulty}

Krótkie pytania, krótkie odpowiedzi (max 60 znaków każda), krótkie wyjaśnienia.

FORMAT (tylko JSON):
[{{"question": "Pytanie?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Wyjaśnienie."}}]""",
    'hu': """Készíts {count} kvíz kérdést időseknek (magyarul).
Téma: {topic}, Nehézség: {difficulty}

Rövid kérdések, rövid válaszok (max 60 karakter), rövid magyarázatok.

FORMÁTUM (csak JSON):
[{{"question": "Kérdés?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Magyarázat."}}]""",
    'en': """Create {count} quiz questions for seniors (in English).
Topic: {topic}, Difficulty: {difficulty}

Short questions, short answers (max 60 chars each), short explanations.

FORMAT (JSON only):
[{{"question": "Question?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Explanation."}}]""",
}

QUIZ_USER = {
    'cs': "Vytvoř kvíz na téma: {topic}",
    'sk': "Vytvor kvíz na tému: {topic}",
    'pl': "Stwórz quiz na temat: {topic}",
    'hu': "Készíts kvízt témára: {topic}",
    'en': "Create a quiz on the topic: {topic}",
}

# Tiny fallback quiz per language. Used only when both Claude + Gemini fail.
QUIZ_FALLBACK = {
    'cs': [
        {"question": "Která řeka protéká Prahou?",
         "options": {"A": "Morava", "B": "Vltava", "C": "Labe", "D": "Odra"},
         "correct": "B", "explanation": "Vltava je nejdelší řeka v ČR."},
        {"question": "Kdo byl první československý prezident?",
         "options": {"A": "Beneš", "B": "Masaryk", "C": "Havel", "D": "Klaus"},
         "correct": "B", "explanation": "T. G. Masaryk byl prezident v letech 1918–1935."},
    ],
    'sk': [
        {"question": "Aká rieka preteká Bratislavou?",
         "options": {"A": "Váh", "B": "Hron", "C": "Dunaj", "D": "Morava"},
         "correct": "C", "explanation": "Dunaj je druhá najdlhšia rieka v Európe."},
        {"question": "Kto bol prvý slovenský prezident?",
         "options": {"A": "Mečiar", "B": "Kováč", "C": "Schuster", "D": "Gašparovič"},
         "correct": "B", "explanation": "Michal Kováč bol prezident SR v rokoch 1993–1998."},
    ],
    'pl': [
        {"question": "Jaka rzeka przepływa przez Warszawę?",
         "options": {"A": "Odra", "B": "Wisła", "C": "Bug", "D": "Warta"},
         "correct": "B", "explanation": "Wisła to najdłuższa rzeka w Polsce."},
        {"question": "Kto był pierwszym prezydentem RP po 1989?",
         "options": {"A": "Wałęsa", "B": "Kwaśniewski", "C": "Jaruzelski", "D": "Kaczyński"},
         "correct": "A", "explanation": "Lech Wałęsa, prezydent 1990–1995."},
    ],
    'hu': [
        {"question": "Melyik folyó folyik át Budapesten?",
         "options": {"A": "Tisza", "B": "Duna", "C": "Dráva", "D": "Maros"},
         "correct": "B", "explanation": "A Duna a második leghosszabb folyó Európában."},
        {"question": "Ki volt az első magyar köztársasági elnök?",
         "options": {"A": "Göncz Árpád", "B": "Mádl Ferenc", "C": "Antall József", "D": "Horn Gyula"},
         "correct": "A", "explanation": "Göncz Árpád elnök 1990–2000 között."},
    ],
    'en': [
        {"question": "Which river flows through London?",
         "options": {"A": "Severn", "B": "Thames", "C": "Mersey", "D": "Avon"},
         "correct": "B", "explanation": "The Thames is England's longest river in southern England."},
        {"question": "Who painted the Mona Lisa?",
         "options": {"A": "Michelangelo", "B": "Leonardo da Vinci", "C": "Raphael", "D": "Donatello"},
         "correct": "B", "explanation": "Leonardo da Vinci painted it around 1503–1519."},
    ],
}


# ── STORY ────────────────────────────────────────────────────────────────

STORY_SYSTEM = {
    'cs': """Vyprávěj {style} příběh pro seniory (v češtině).
Téma: {theme}, Délka: {length_words} slov.
Pozitivní a uklidňující.

FORMÁT (pouze JSON):
{{"title": "Název", "content": "Text příběhu..."}}""",
    'sk': """Rozprávaj {style} príbeh pre seniorov (v slovenčine).
Téma: {theme}, Dĺžka: {length_words} slov.
Pozitívny a upokojujúci.

FORMÁT (iba JSON):
{{"title": "Názov", "content": "Text príbehu..."}}""",
    'pl': """Opowiedz {style} historię dla seniorów (po polsku).
Temat: {theme}, Długość: {length_words} słów.
Pozytywna i uspokajająca.

FORMAT (tylko JSON):
{{"title": "Tytuł", "content": "Treść historii..."}}""",
    'hu': """Mesélj egy {style} történetet időseknek (magyarul).
Téma: {theme}, Hossz: {length_words} szó.
Pozitív és megnyugtató.

FORMÁTUM (csak JSON):
{{"title": "Cím", "content": "A történet szövege..."}}""",
    'en': """Tell a {style} story for seniors (in English).
Theme: {theme}, Length: {length_words} words.
Positive and calming.

FORMAT (JSON only):
{{"title": "Title", "content": "Story text..."}}""",
}

STORY_USER = {
    'cs': "Vyprávěj příběh na téma: {theme}",
    'sk': "Rozprávaj príbeh na tému: {theme}",
    'pl': "Opowiedz historię na temat: {theme}",
    'hu': "Mesélj egy történetet a témáról: {theme}",
    'en': "Tell a story about: {theme}",
}

STORY_FALLBACK = {
    'cs': {"title": "Procházka parkem", "content": "Bylo krásné jarní ráno. Pan Josef vyšel na svou oblíbenou procházku do parku. Slunce hřálo a ptáci zpívali. U rybníčku potkal svého starého přítele Karla a společně si povídali o starých časech. Byl to krásný den."},
    'sk': {"title": "Prechádzka v parku", "content": "Bolo krásne jarné ráno. Pán Jozef vyšiel na svoju obľúbenú prechádzku do parku. Slnko hrialo a vtáky spievali. Pri rybníčku stretol svojho starého priateľa Karola a spolu sa rozprávali o starých časoch. Bol to krásny deň."},
    'pl': {"title": "Spacer w parku", "content": "Był piękny wiosenny poranek. Pan Józef wybrał się na swój ulubiony spacer do parku. Słońce grzało, a ptaki śpiewały. Nad stawem spotkał swojego starego przyjaciela Karola i rozmawiali o dawnych czasach. To był piękny dzień."},
    'hu': {"title": "Séta a parkban", "content": "Gyönyörű tavaszi reggel volt. József úr elindult kedvenc sétájára a parkba. A nap melegen sütött, és a madarak énekeltek. A tó mellett találkozott régi barátjával, Károllyal, és együtt beszélgettek a régi időkről. Csodás nap volt."},
    'en': {"title": "A walk in the park", "content": "It was a beautiful spring morning. Mr. Joseph set off on his favorite walk in the park. The sun was warm and the birds were singing. By the pond he met his old friend Charles, and they talked together about old times. It was a beautiful day."},
}

STORY_ERROR_TITLE = {'cs': 'Chyba', 'sk': 'Chyba', 'pl': 'Błąd', 'hu': 'Hiba', 'en': 'Error'}
STORY_ERROR_CONTENT = {
    'cs': 'Nepodařilo se vytvořit příběh.',
    'sk': 'Nepodarilo sa vytvoriť príbeh.',
    'pl': 'Nie udało się stworzyć historii.',
    'hu': 'Nem sikerült történetet készíteni.',
    'en': 'Failed to create story.',
}


# ── HELPERS ──────────────────────────────────────────────────────────────

def t(table, lang, key=None, **kwargs):
    """Pick localized value from a (lang→...) table with cs fallback, format with kwargs."""
    bucket = table.get(lang) or table.get('cs') or {}
    if key is None:
        val = bucket
    else:
        val = bucket.get(key) if isinstance(bucket, dict) else None
        if val is None and lang != 'cs':
            cs_bucket = table.get('cs') or {}
            val = cs_bucket.get(key) if isinstance(cs_bucket, dict) else None
    if isinstance(val, str) and kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, IndexError):
            return val
    return val
