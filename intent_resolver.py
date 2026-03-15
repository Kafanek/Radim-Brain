"""
Intent Resolver v1.0 — Lightweight local NLU for Radim assistant.

Resolves simple intents (time, date, greeting, nameday, etc.) locally
without calling Claude/Gemini API. Saves costs and reduces latency.

Part of v272: STT Intelligence.
"""

import re
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================================
# QUICK C/ALPHA ESTIMATION (reuse text_rhythm word sets)
# ============================================================================

_CRISIS_WORDS = {
    # Emergency calls
    'pomoc', 'help', 'sos', '155', '112',
    'záchranku', 'zachranku', 'záchranka', 'zachranka',
    # Falls
    'spadl', 'spadla', 'padám', 'padam', 'padl', 'padla', 'upadl', 'upadla',
    # Pain/medical emergency
    'bolest', 'bolest na hrudi', 'infarkt', 'mrtvice',
    'krev', 'zlomenina',
    # Breathing
    'nemohu dýchat', 'nemůžu dýchat', 'nemohu dychat', 'nemazu dychat',
    'umírám', 'umiram',
    # Unconsciousness/immobility
    'bezvědomí', 'bezvedomi', 'mdloba', 'omdlel', 'omdlela',
    'nehýbu', 'nehybu', 'nehýbám', 'nehybam',
    'nemůžu vstát', 'nemuzu vstat',
    # Suicidal ideation (v327: C3 fix)
    'umřít', 'umrit', 'zemřít', 'zemrit', 'zabít', 'zabit',
    'chci umřít', 'chci umrit', 'chci zemřít', 'chci zemrit',
    'nechci žít', 'nechci zit',
    'sebevražd', 'sebevrazd', 'sebevražed', 'sebevrazed',
    'oběsit', 'obesit', 'skočit z', 'skocit z',
    'předávkov', 'predavkov',
    'končit se životem', 'koncit se zivotem',
    'vzít si život', 'vzit si zivot',
    # Wandering/disorientation (v327: C4 fix)
    'ztratil jsem se', 'ztratila jsem se',
    'nevím kde jsem', 'nevim kde jsem',
    'kde to jsem', 'zabloudil', 'zabloudila',
    'nepoznávám', 'nepoznavam', 'nevím jak domů', 'nevim jak domu',
    # Choking/aspiration (v327: C5 fix)
    'dusím se', 'dusim se',
    'nemůžu polykat', 'nemuzu polykat', 'nemůžu polknout',
    'dávím se', 'davim se',
    # Medication emergency
    'vzal jsem dvakrát', 'vzala jsem dvakrát',
    'moc prášků', 'moc prasek', 'předávkoval', 'predavkoval',
}

_STRESS_WORDS = {
    'strach', 'bojím', 'bojim', 'nervózní', 'nervozni', 'nemocný', 'nemocny',
    'unavený', 'unaveny', 'problém', 'problem', 'bolí', 'boli',
    'nespím', 'nespim', 'samota', 'sám', 'sam', 'smutný', 'smutny',
    'osamělý', 'osamely', 'úzkost', 'uzkost', 'panika',
    'špatně', 'spatne', 'nemůžu', 'nemuzu', 'nemazu',
    'trápí', 'trapi', 'nevím', 'nevim', 'ztracený', 'ztraceny',
    'brečím', 'brecim', 'pláču', 'placu', 'stýská', 'styska',
}

_CALM_WORDS = {
    'děkuji', 'dekuji', 'díky', 'diky', 'hezky', 'dobře', 'dobre',
    'krásně', 'krasne', 'fajn', 'prima', 'skvěle', 'skvele',
    'výborně', 'vyborne', 'pohoda', 'šťastný', 'stastny',
    'radost', 'super', 'báječné', 'bajecne', 'nádherné', 'nadherne',
    'klidný', 'klidny', 'spokojený', 'spokojeny',
}


def _word_in_text(word, text):
    """Check if word appears in text. For numeric words (155, 112),
    use word-boundary matching to avoid false positives like '15500 Kč'.
    v329: Fix false positive for numbers in longer strings."""
    if word.isdigit():
        import re
        return bool(re.search(r'\b' + re.escape(word) + r'\b', text))
    return word in text


def quick_estimate_from_text(text):
    """Quick C/alpha estimation from text for streaming STT→Brain.
    Returns (C_estimate, alpha_estimate).
    """
    if not text:
        return (5.0, 0.2)

    text_lower = text.lower()
    crisis_hits = sum(1 for w in _CRISIS_WORDS if _word_in_text(w, text_lower))
    stress_hits = sum(1 for w in _STRESS_WORDS if _word_in_text(w, text_lower))
    calm_hits = sum(1 for w in _CALM_WORDS if _word_in_text(w, text_lower))

    C = 5.0
    C += crisis_hits * 12.0
    C += stress_hits * 4.0
    C -= calm_hits * 2.0
    C = max(0.0, min(50.0, C))

    alpha = 0.2
    alpha += crisis_hits * 0.3
    alpha += stress_hits * 0.15
    alpha -= calm_hits * 0.05
    alpha = max(0.0, min(1.0, alpha))

    return (C, alpha)


# ============================================================================
# CZECH NAMEDAYS (kompaktní — 366 záznamů, key = "MM-DD")
# ============================================================================

CZ_NAMEDAYS = {
    "01-01": "Nový rok", "01-02": "Karina", "01-03": "Radmila",
    "01-04": "Diana", "01-05": "Dalimil", "01-06": "Tři králové",
    "01-07": "Vilma", "01-08": "Čestmír", "01-09": "Vladan",
    "01-10": "Břetislav", "01-11": "Bohdana", "01-12": "Pravoslav",
    "01-13": "Edita", "01-14": "Radovan", "01-15": "Alice",
    "01-16": "Ctirad", "01-17": "Drahoslav", "01-18": "Vladislav",
    "01-19": "Doubravka", "01-20": "Ilona", "01-21": "Běla",
    "01-22": "Slavomír", "01-23": "Zdeněk", "01-24": "Milena",
    "01-25": "Miloš", "01-26": "Zora", "01-27": "Ingrid",
    "01-28": "Otýlie", "01-29": "Zdislava", "01-30": "Robin",
    "01-31": "Marika",
    "02-01": "Hynek", "02-02": "Nela", "02-03": "Blažej",
    "02-04": "Jarmila", "02-05": "Dobromila", "02-06": "Vanda",
    "02-07": "Veronika", "02-08": "Milada", "02-09": "Apolena",
    "02-10": "Mojmír", "02-11": "Božena", "02-12": "Slavěna",
    "02-13": "Věnceslav", "02-14": "Valentýn", "02-15": "Jiřina",
    "02-16": "Ljuba", "02-17": "Miloslava", "02-18": "Gizela",
    "02-19": "Patrik", "02-20": "Oldřich", "02-21": "Lenka",
    "02-22": "Petr", "02-23": "Svatopluk", "02-24": "Matěj",
    "02-25": "Liliana", "02-26": "Dorota", "02-27": "Alexandr",
    "02-28": "Lumír", "02-29": "Horymír",
    "03-01": "Bedřich", "03-02": "Anežka", "03-03": "Kamil",
    "03-04": "Stela", "03-05": "Kazimír", "03-06": "Miroslav",
    "03-07": "Tomáš", "03-08": "Gabriela", "03-09": "Františka",
    "03-10": "Viktorie", "03-11": "Anděla", "03-12": "Řehoř",
    "03-13": "Růžena", "03-14": "Rút a Matylda", "03-15": "Ida",
    "03-16": "Elena a Herbert", "03-17": "Vlastimil", "03-18": "Eduard",
    "03-19": "Josef", "03-20": "Světlana", "03-21": "Radek",
    "03-22": "Leona", "03-23": "Ivona", "03-24": "Gabriel",
    "03-25": "Marián", "03-26": "Emanuel", "03-27": "Dita",
    "03-28": "Soňa", "03-29": "Taťána", "03-30": "Arnošt",
    "03-31": "Kvido",
    "04-01": "Hugo", "04-02": "Erika", "04-03": "Richard",
    "04-04": "Ivana", "04-05": "Miroslava", "04-06": "Vendula",
    "04-07": "Heřman a Hermína", "04-08": "Ema", "04-09": "Dušan",
    "04-10": "Darja", "04-11": "Izabela", "04-12": "Julius",
    "04-13": "Aleš", "04-14": "Vincenc", "04-15": "Anastázie",
    "04-16": "Irena", "04-17": "Rudolf", "04-18": "Valérie",
    "04-19": "Rostislav", "04-20": "Marcela", "04-21": "Alexandra",
    "04-22": "Evženie", "04-23": "Vojtěch", "04-24": "Jiří",
    "04-25": "Marek", "04-26": "Oto", "04-27": "Jaroslav",
    "04-28": "Vlastislav", "04-29": "Robert", "04-30": "Blahoslav",
    "05-01": "Svátek práce", "05-02": "Zikmund", "05-03": "Alexej",
    "05-04": "Květoslav", "05-05": "Klaudie", "05-06": "Radoslav",
    "05-07": "Stanislas", "05-08": "Den vítězství", "05-09": "Ctibor",
    "05-10": "Blažena", "05-11": "Svatava", "05-12": "Pankrác",
    "05-13": "Servác", "05-14": "Bonifác", "05-15": "Žofie",
    "05-16": "Přemysl", "05-17": "Aneta", "05-18": "Nataša",
    "05-19": "Ivo", "05-20": "Zbyšek", "05-21": "Monika",
    "05-22": "Emil", "05-23": "Vladimír", "05-24": "Jana",
    "05-25": "Viola", "05-26": "Filip", "05-27": "Valdemar",
    "05-28": "Vilém", "05-29": "Maxmilián", "05-30": "Ferdinand",
    "05-31": "Kamila",
    "06-01": "Laura", "06-02": "Jarmil", "06-03": "Tamara",
    "06-04": "Dalibor", "06-05": "Dobroslav", "06-06": "Norbert",
    "06-07": "Iveta", "06-08": "Medard", "06-09": "Stanislav",
    "06-10": "Gita", "06-11": "Bruno", "06-12": "Antonie",
    "06-13": "Antonín", "06-14": "Roland", "06-15": "Vít",
    "06-16": "Zbyněk", "06-17": "Adolf", "06-18": "Milan",
    "06-19": "Leoš", "06-20": "Květa", "06-21": "Alois",
    "06-22": "Pavla", "06-23": "Zdeňka", "06-24": "Jan",
    "06-25": "Ivan", "06-26": "Adriana", "06-27": "Ladislav",
    "06-28": "Lubomír", "06-29": "Petr a Pavel", "06-30": "Šárka",
    "07-01": "Jaroslava", "07-02": "Patricie", "07-03": "Radomír",
    "07-04": "Prokop", "07-05": "Cyril a Metoděj", "07-06": "Den Jana Husa",
    "07-07": "Bohuslava", "07-08": "Nora", "07-09": "Drahoslava",
    "07-10": "Libuše a Přemysl", "07-11": "Olga", "07-12": "Bořek",
    "07-13": "Markéta", "07-14": "Karolína", "07-15": "Jindřich",
    "07-16": "Luboš", "07-17": "Martina", "07-18": "Drahomíra",
    "07-19": "Čeněk", "07-20": "Ilja", "07-21": "Vítězslav",
    "07-22": "Magdaléna", "07-23": "Libor", "07-24": "Kristýna",
    "07-25": "Jakub", "07-26": "Anna", "07-27": "Věroslav",
    "07-28": "Viktor", "07-29": "Marta", "07-30": "Bořivoj",
    "07-31": "Ignác",
    "08-01": "Oskar", "08-02": "Gustav", "08-03": "Miluše",
    "08-04": "Dominik", "08-05": "Kristian", "08-06": "Oldřiška",
    "08-07": "Lada", "08-08": "Soběslav", "08-09": "Roman",
    "08-10": "Vavřinec", "08-11": "Zuzana", "08-12": "Klára",
    "08-13": "Alena", "08-14": "Alan", "08-15": "Hana",
    "08-16": "Jáchym", "08-17": "Petra", "08-18": "Helena",
    "08-19": "Ludvík", "08-20": "Bernard", "08-21": "Johana",
    "08-22": "Bohuslav", "08-23": "Sandra", "08-24": "Bartoloměj",
    "08-25": "Radim", "08-26": "Luděk", "08-27": "Otakar",
    "08-28": "Augustýn", "08-29": "Evelína", "08-30": "Vladěna",
    "08-31": "Pavlína",
    "09-01": "Linda a Samuel", "09-02": "Adéla", "09-03": "Bronislav",
    "09-04": "Jindřiška", "09-05": "Boris", "09-06": "Boleslav",
    "09-07": "Regína", "09-08": "Mariana", "09-09": "Daniela",
    "09-10": "Irma", "09-11": "Denisa", "09-12": "Marie",
    "09-13": "Lubor", "09-14": "Radka", "09-15": "Jolana",
    "09-16": "Ludmila", "09-17": "Naděžda", "09-18": "Kryštof",
    "09-19": "Zita", "09-20": "Oleg", "09-21": "Matouš",
    "09-22": "Darina", "09-23": "Berta", "09-24": "Jaromír",
    "09-25": "Zlata", "09-26": "Andrea", "09-27": "Jonáš",
    "09-28": "Václav", "09-29": "Michal", "09-30": "Jeroným",
    "10-01": "Igor", "10-02": "Olivie a Oliver", "10-03": "Bohumil",
    "10-04": "František", "10-05": "Eliška", "10-06": "Hanuš",
    "10-07": "Justýna", "10-08": "Věra", "10-09": "Štefan a Sára",
    "10-10": "Marina", "10-11": "Andrej", "10-12": "Marcel",
    "10-13": "Renáta", "10-14": "Agáta", "10-15": "Tereza",
    "10-16": "Havel", "10-17": "Hedvika", "10-18": "Lukáš",
    "10-19": "Michaela", "10-20": "Vendelín", "10-21": "Brigita",
    "10-22": "Sabina", "10-23": "Teodor", "10-24": "Nina",
    "10-25": "Beáta", "10-26": "Erik", "10-27": "Šarlota a Zoe",
    "10-28": "Den vzniku Československa", "10-29": "Silvie",
    "10-30": "Tadeáš", "10-31": "Štěpánka",
    "11-01": "Felix", "11-02": "Památka zesnulých", "11-03": "Hubert",
    "11-04": "Karel", "11-05": "Miriam", "11-06": "Liběna",
    "11-07": "Saskie", "11-08": "Bohumír", "11-09": "Bohdan",
    "11-10": "Evžen", "11-11": "Martin", "11-12": "Benedikt",
    "11-13": "Tibor", "11-14": "Sáva", "11-15": "Leopold",
    "11-16": "Otmar", "11-17": "Den boje za svobodu a demokracii",
    "11-18": "Romana", "11-19": "Alžběta", "11-20": "Nikola",
    "11-21": "Albert", "11-22": "Cecílie", "11-23": "Klement",
    "11-24": "Emílie", "11-25": "Kateřina", "11-26": "Artur",
    "11-27": "Xenie", "11-28": "René", "11-29": "Zina",
    "11-30": "Ondřej",
    "12-01": "Iva", "12-02": "Blanka", "12-03": "Svatoslav",
    "12-04": "Barbora", "12-05": "Jitka", "12-06": "Mikuláš",
    "12-07": "Ambrož a Benjamín", "12-08": "Květoslava",
    "12-09": "Vratislav", "12-10": "Julie", "12-11": "Dana",
    "12-12": "Simona", "12-13": "Lucie", "12-14": "Lýdie",
    "12-15": "Radana a Radan", "12-16": "Albína", "12-17": "Daniel",
    "12-18": "Miloslav", "12-19": "Ester", "12-20": "Dagmar",
    "12-21": "Natálie", "12-22": "Šimon", "12-23": "Vlasta",
    "12-24": "Adam a Eva", "12-25": "1. svátek vánoční",
    "12-26": "Štěpán", "12-27": "Žaneta", "12-28": "Bohumila",
    "12-29": "Judita", "12-30": "David", "12-31": "Silvestr",
}


# ============================================================================
# INTENT PATTERNS (regex-based, Czech)
# ============================================================================

_INTENTS = [
    {
        "name": "time",
        "patterns": [
            r"kolik\s+je\s+hodin",
            r"kolik\s+je\s+čas",
            r"jaký\s+je\s+čas",
            r"^\s*čas\s*$",
            r"^\s*hodiny\s*$",
            r"kolik\s+ukazuj",
        ],
        "handler": "_handle_time",
    },
    {
        "name": "date",
        "patterns": [
            r"jaký\s+je\s+dnes\s+den",
            r"jaké\s+je\s+dnes\s+datum",
            r"kolikátého\s+je",
            r"kolikátého\s+dnes",
            r"jaké\s+je\s+datum",
            r"^\s*datum\s*$",
        ],
        "handler": "_handle_date",
    },
    {
        "name": "nameday",
        "patterns": [
            r"kdo\s+má\s+(dnes\s+)?svátek",
            r"jaký\s+je\s+(dnes\s+)?svátek",
            r"jmeniny",
            r"čí\s+je\s+svátek",
            r"^\s*svátek\s*$",
        ],
        "handler": "_handle_nameday",
    },
    {
        "name": "greeting",
        "patterns": [
            r"^\s*(ahoj|čau|nazdar|zdravím|dobrý\s+den|dobré\s+ráno|dobrý\s+večer|dobré\s+odpoledne)\s*[!.?]*\s*$",
        ],
        "handler": "_handle_greeting",
    },
    {
        "name": "goodbye",
        "patterns": [
            r"^\s*(nashledanou|na\s+shledanou|sbohem|čau|papa|ahoj|dobrou\s+noc)\s*[!.?]*\s*$",
        ],
        "handler": "_handle_goodbye",
    },
    {
        "name": "thanks",
        "patterns": [
            r"^\s*(děkuji?|díky|díky\s+moc|dekuji|mockrát\s+děkuji?)\s*[!.?]*\s*$",
        ],
        "handler": "_handle_thanks",
    },
    {
        "name": "identity",
        "patterns": [
            r"kdo\s+jsi",
            r"jak\s+se\s+jmenuje[šs]",
            r"co\s+jsi\s+zač",
            r"představ\s+se",
            r"jsi\s+robot",
        ],
        "handler": "_handle_identity",
    },
    {
        "name": "day_of_week",
        "patterns": [
            r"jaký\s+je\s+den\s+v\s+týdnu",
            r"který\s+je\s+den",
            r"jaký\s+máme\s+den",
            r"je\s+dnes\s+(pondělí|úterý|středa|čtvrtek|pátek|sobota|neděle)",
        ],
        "handler": "_handle_day_of_week",
    },
    {
        "name": "year",
        "patterns": [
            r"jaký\s+je\s+rok",
            r"kolikátý\s+je\s+rok",
            r"který\s+je\s+rok",
            r"jaký\s+máme\s+rok",
        ],
        "handler": "_handle_year",
    },
    {
        "name": "joke",
        "patterns": [
            r"řekni\s+(mi\s+)?vtip",
            r"pověz\s+(mi\s+)?vtip",
            r"znáš\s+(nějaký\s+)?vtip",
            r"máš\s+(nějaký\s+)?vtip",
            r"zasmě[jř]\s+m[eě]",
            r"něco\s+veselého",
            r"^\s*vtip\s*$",
        ],
        "handler": "_handle_joke",
    },
    {
        "name": "compliment",
        "patterns": [
            r"jsi\s+(skvělý|prima|super|výborný|báječný|úžasný)",
            r"máš\s+pravdu",
            r"to\s+je\s+hezké",
            r"jsi\s+chytrý",
            r"jsi\s+hodný",
        ],
        "handler": "_handle_compliment",
    },
    {
        "name": "how_are_you",
        "patterns": [
            r"jak\s+se\s+(máš|máte|daří|vede)",
            r"co\s+děláš",
            r"co\s+je\s+nového",
            r"^\s*a\s+ty\s*\??\s*$",
        ],
        "handler": "_handle_how_are_you",
    },
    {
        "name": "weather",
        "patterns": [
            r"počasí",
            r"jaké\s+bude\s+počasí",
            r"bude\s+pršet",
            r"bude\s+sněžit",
            r"jaká\s+je\s+teplota",
            r"kolik\s+je\s+stupňů",
        ],
        "handler": None,  # Pass to AI
    },
    {
        "name": "medication",
        "patterns": [
            r"léky",
            r"prášky",
            r"tablety",
            r"vzal\s+jsem",
            r"bral\s+jsem",
            r"medikace",
        ],
        "handler": None,  # Pass to AI
    },
    {
        "name": "safety",
        "patterns": [
            r"pomoc[!]*",
            r"help[!]*",
            r"spadl\s+jsem",
            r"spadla\s+jsem",
            r"nemůžu\s+dýchat",
            r"nemohu\s+dýchat",
            r"bolest\s+na\s+hrudi",
            r"záchranka",
            r"\b155\b",
            r"\b112\b",
            # v327: Suicidal ideation
            r"chci\s+umřít",
            r"chci\s+zemřít",
            r"nechci\s+žít",
            r"sebevražd",
            # v327: Wandering/disorientation
            r"ztratil\s+jsem\s+se",
            r"ztratila\s+jsem\s+se",
            r"nevím\s+kde\s+jsem",
            r"kde\s+to\s+jsem",
            # v327: Choking
            r"dusím\s+se",
            r"nemůžu\s+polykat",
            r"dávím\s+se",
            # v327: Immobility
            r"nemůžu\s+vstát",
            r"nehýbu\s+se",
        ],
        "handler": None,  # Pass to AI with high priority
    },
]

# Compile patterns
for intent in _INTENTS:
    intent["_compiled"] = [re.compile(p, re.IGNORECASE) for p in intent["patterns"]]


# ============================================================================
# RESPONSE HANDLERS
# ============================================================================

_CZ_DAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]
_CZ_MONTHS = [
    "ledna", "února", "března", "dubna", "května", "června",
    "července", "srpna", "září", "října", "listopadu", "prosince"
]

_GREETINGS = [
    "Ahoj! Jak se máte?",
    "Dobrý den! Co pro vás mohu udělat?",
    "Zdravím vás! Jsem tu pro vás.",
    "Ahoj! Rád vás slyším.",
    "Dobrý den! Jak vám mohu pomoci?",
]

_GOODBYES = [
    "Nashledanou! Mějte se krásně.",
    "Sbohem! Přeji vám hezký den.",
    "Na shledanou! Jsem tu, kdykoli budete potřebovat.",
    "Čau! Opatrujte se.",
    "Dobře, nashledanou! Buďte zdrávi.",
]

_THANKS_REPLIES = [
    "Není zač! Rád pomáhám.",
    "Rádo se stalo! Jsem tu pro vás.",
    "To je v pořádku! Kdykoli se ptejte.",
]


def _handle_time(**kwargs):
    now = datetime.now()
    h, m = now.hour, now.minute
    return f"Je {h}:{m:02d}."


def _handle_date(**kwargs):
    now = datetime.now()
    day_name = _CZ_DAYS[now.weekday()]
    return f"Dnes je {day_name} {now.day}. {_CZ_MONTHS[now.month - 1]} {now.year}."


def _handle_nameday(**kwargs):
    key = datetime.now().strftime("%m-%d")
    name = CZ_NAMEDAYS.get(key, "neznámý")
    return f"Dnes má svátek {name}."


def _handle_greeting(**kwargs):
    return random.choice(_GREETINGS)


def _handle_goodbye(**kwargs):
    return random.choice(_GOODBYES)


def _handle_thanks(**kwargs):
    return random.choice(_THANKS_REPLIES)


def _handle_identity(**kwargs):
    return "Jsem Radim, váš digitální asistent od MyKolibri. Pomáhám s každodenními činnostmi, zdravím a jsem tu pro vás kdykoli."


def _handle_day_of_week(**kwargs):
    now = datetime.now()
    day_name = _CZ_DAYS[now.weekday()]
    return f"Dnes je {day_name}."


def _handle_year(**kwargs):
    return f"Máme rok {datetime.now().year}."


_CZ_JOKES = [
    "Co řekne nula osmičce? Hezký pásek! 😄",
    "Proč nemůže bicykl stát sám? Protože je dvou-kolý! 🚲",
    "Co je to žába na suchu? Přískoč! 🐸",
    "Jaký je rozdíl mezi školou a blázincem? Telefonní číslo! 📞",
    "Co dělá kočka na počítači? Chytá myš! 🐱",
    "Proč se houby nezvou na párty? Protože zabírají moc místa! 🍄",
    "Co řekne jeden strom druhému? Listuj! 🌳",
    "Jaký je nejlepší den na vaření? Pátek — pá-tek! 🍳",
    "Proč nosí klauni velké boty? Protože mají velké nohy! 🤡",
    "Co říká ryba, když narazí do zdi? Plác! 🐟",
]


def _handle_joke(**kwargs):
    return random.choice(_CZ_JOKES)


_COMPLIMENT_REPLIES = [
    "Děkuji! To mě těší. 😊",
    "Vy jste ale milí! Děkuji.",
    "To je od vás hezké! Snažím se.",
    "Díky moc! Jsem rád, že vám mohu pomáhat.",
]


def _handle_compliment(**kwargs):
    return random.choice(_COMPLIMENT_REPLIES)


_HOW_ARE_YOU_REPLIES = [
    "Mám se skvěle, děkuji za optání! A vy?",
    "Výborně! Jsem připravený vám pomáhat. Jak se máte vy?",
    "Dobře, děkuji! Co pro vás mohu udělat?",
    "Fajn! Jsem tu pro vás. Jak se daří vám?",
]


def _handle_how_are_you(**kwargs):
    return random.choice(_HOW_ARE_YOU_REPLIES)


_HANDLERS = {
    "_handle_time": _handle_time,
    "_handle_date": _handle_date,
    "_handle_nameday": _handle_nameday,
    "_handle_greeting": _handle_greeting,
    "_handle_goodbye": _handle_goodbye,
    "_handle_thanks": _handle_thanks,
    "_handle_identity": _handle_identity,
    "_handle_day_of_week": _handle_day_of_week,
    "_handle_year": _handle_year,
    "_handle_joke": _handle_joke,
    "_handle_compliment": _handle_compliment,
    "_handle_how_are_you": _handle_how_are_you,
}


# ============================================================================
# MAIN RESOLVE FUNCTION
# ============================================================================

def resolve_intent(message, user_id=None, mode="HARMONY"):
    """Resolve intent from user message.

    Returns:
        (response_text, intent_label, metadata)
        - response_text: str if resolved locally, None if should pass to AI
        - intent_label: str (e.g. "time", "greeting", "safety")
        - metadata: dict or None (e.g. {"priority": "high"} for safety)
    """
    if not message or not message.strip():
        return (None, "empty", None)

    text = message.strip()

    for intent in _INTENTS:
        for pattern in intent["_compiled"]:
            if pattern.search(text):
                name = intent["name"]
                handler_name = intent["handler"]

                if handler_name is None:
                    # Intent recognized but needs AI processing
                    meta = None
                    if name == "safety":
                        meta = {"priority": "high"}
                    logger.info(f"Intent '{name}' detected for user={user_id}, passing to AI")
                    return (None, name, meta)

                handler = _HANDLERS.get(handler_name)
                if handler:
                    try:
                        response = handler(user_id=user_id, mode=mode)
                        logger.info(f"Intent '{name}' resolved locally for user={user_id}")
                        return (response, name, {"source": "local"})
                    except Exception as e:
                        logger.warning(f"Intent handler '{name}' failed: {e}")
                        return (None, name, None)

    return (None, "chat", None)
