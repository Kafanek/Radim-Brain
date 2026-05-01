# ============================================
# INTENT DATA v1.0.0
# ============================================
# Word lists, nameday calendar, intent patterns,
# and response templates for intent resolver.
# Extracted from intent_resolver.py for modularity.
# ============================================

import re
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CRISIS / STRESS / CALM WORD SETS
# ============================================================================

CRISIS_WORDS = {
    'pomoc', 'help', 'sos', '155', '112',
    'zachranku', 'zachranka',
    'spadl', 'spadla', 'padam', 'padl', 'padla', 'upadl', 'upadla',
    'bolest', 'bolest na hrudi', 'infarkt', 'mrtvice',
    'krev', 'zlomenina',
    'nemohu dychat', 'nemuzu dychat',
    'umiram',
    'bezvedomi', 'mdloba', 'omdlel', 'omdlela',
    'nehybu', 'nehybam',
    'nemuzu vstat',
    'umrit', 'zemrit', 'zabit',
    'chci umrit', 'chci zemrit',
    'nechci zit',
    'sebevrazd', 'sebevrazed',
    'obesit', 'skocit z',
    'predavkov',
    'koncit se zivotem',
    'vzit si zivot',
    'ztratil jsem se', 'ztratila jsem se',
    'nevim kde jsem',
    'kde to jsem', 'zabloudil', 'zabloudila',
    'nepoznavam', 'nevim jak domu',
    'dusim se',
    'nemuzu polykat',
    'davim se',
    'vzal jsem dvakrat', 'vzala jsem dvakrat',
    'moc prasek', 'predavkoval',
}

# Extended set with diacritics (for display-quality matching)
CRISIS_WORDS_DIACRITICS = {
    'záchranku', 'záchranka',
    'padám',
    'nemohu dýchat', 'nemůžu dýchat',
    'umírám',
    'bezvědomí',
    'nehýbu', 'nehýbám',
    'nemůžu vstát',
    'umřít', 'zemřít', 'zabít',
    'chci umřít', 'chci zemřít',
    'nechci žít',
    'sebevražd', 'sebevražed',
    'oběsit', 'skočit z',
    'předávkov',
    'končit se životem',
    'vzít si život',
    'nepoznávám', 'nevím jak domů',
    'dusím se',
    'nemůžu polykat', 'nemůžu polknout',
    'dávím se',
    'vzal jsem dvakrát', 'vzala jsem dvakrát',
    'moc prášků', 'předávkoval',
}

# Merge both sets
CRISIS_WORDS_ALL = CRISIS_WORDS | CRISIS_WORDS_DIACRITICS

STRESS_WORDS = {
    'strach', 'bojim', 'nervozni', 'nemocny',
    'unaveny', 'problem', 'boli',
    'nespim', 'samota', 'sam', 'smutny',
    'osamely', 'uzkost', 'panika',
    'spatne', 'nemuzu', 'nemazu',
    'trapi', 'nevim', 'ztraceny',
    'brecim', 'placu', 'styska',
    # Sprint AO: grief / loss vocabulary — stress for brain mode +
    # voice modulation, not crisis (no immediate emergency action).
    # Without these, "manžel mi zemřel" left brain in HARMONY and
    # voice picked RHYTHMIC (upbeat) which is the wrong tone for
    # grief. Now C bumps to ALERT range → voice slows + style empathetic.
    'zemrel', 'zemrela', 'umrel', 'umrela', 'pohreb', 'truchlim',
    'ztrata', 'odesel', 'odesla', 'navzdy', 'sirotek', 'truchlici',
    'smutek', 'smutno', 'beznadeji',
    # With diacritics
    'bojím', 'nervózní', 'nemocný',
    'unavený', 'problém', 'bolí',
    'nespím', 'sám', 'smutný',
    'osamělý', 'úzkost',
    'špatně', 'nemůžu',
    'trápí', 'nevím', 'ztracený',
    'brečím', 'pláču', 'stýská',
    # Sprint AO grief diacritics
    'zemřel', 'zemřela', 'umřel', 'umřela', 'pohřeb', 'truchlím',
    'ztráta', 'odešel', 'odešla', 'navždy', 'truchlící',
    'beznaději',
}

CALM_WORDS = {
    'dekuji', 'diky', 'hezky', 'dobre',
    'krasne', 'fajn', 'prima', 'skvele',
    'vyborne', 'pohoda', 'stastny',
    'radost', 'super', 'bajecne', 'nadherne',
    'klidny', 'spokojeny',
    # With diacritics
    'děkuji', 'díky', 'dobře',
    'krásně', 'skvěle',
    'výborně', 'šťastný',
    'báječné', 'nádherné',
    'klidný', 'spokojený',
}


# ============================================================================
# CZECH NAMEDAYS (kompaktni — 366 zaznamu, key = "MM-DD")
# ============================================================================

CZ_NAMEDAYS = {
    "01-01": "Novy rok", "01-02": "Karina", "01-03": "Radmila",
    "01-04": "Diana", "01-05": "Dalimil", "01-06": "Tri kralove",
    "01-07": "Vilma", "01-08": "Cestmir", "01-09": "Vladan",
    "01-10": "Bretislav", "01-11": "Bohdana", "01-12": "Pravoslav",
    "01-13": "Edita", "01-14": "Radovan", "01-15": "Alice",
    "01-16": "Ctirad", "01-17": "Drahoslav", "01-18": "Vladislav",
    "01-19": "Doubravka", "01-20": "Ilona", "01-21": "Bela",
    "01-22": "Slavomir", "01-23": "Zdenek", "01-24": "Milena",
    "01-25": "Milos", "01-26": "Zora", "01-27": "Ingrid",
    "01-28": "Otylie", "01-29": "Zdislava", "01-30": "Robin",
    "01-31": "Marika",
    "02-01": "Hynek", "02-02": "Nela", "02-03": "Blazej",
    "02-04": "Jarmila", "02-05": "Dobromila", "02-06": "Vanda",
    "02-07": "Veronika", "02-08": "Milada", "02-09": "Apolena",
    "02-10": "Mojmir", "02-11": "Bozena", "02-12": "Slavena",
    "02-13": "Venceslav", "02-14": "Valentyn", "02-15": "Jirina",
    "02-16": "Ljuba", "02-17": "Miloslava", "02-18": "Gizela",
    "02-19": "Patrik", "02-20": "Oldrich", "02-21": "Lenka",
    "02-22": "Petr", "02-23": "Svatopluk", "02-24": "Matej",
    "02-25": "Liliana", "02-26": "Dorota", "02-27": "Alexandr",
    "02-28": "Lumir", "02-29": "Horymir",
    "03-01": "Bedrich", "03-02": "Anezka", "03-03": "Kamil",
    "03-04": "Stela", "03-05": "Kazimir", "03-06": "Miroslav",
    "03-07": "Tomas", "03-08": "Gabriela", "03-09": "Frantiska",
    "03-10": "Viktorie", "03-11": "Andela", "03-12": "Rehor",
    "03-13": "Ruzena", "03-14": "Rut a Matylda", "03-15": "Ida",
    "03-16": "Elena a Herbert", "03-17": "Vlastimil", "03-18": "Eduard",
    "03-19": "Josef", "03-20": "Svetlana", "03-21": "Radek",
    "03-22": "Leona", "03-23": "Ivona", "03-24": "Gabriel",
    "03-25": "Marian", "03-26": "Emanuel", "03-27": "Dita",
    "03-28": "Sona", "03-29": "Tatana", "03-30": "Arnost",
    "03-31": "Kvido",
    "04-01": "Hugo", "04-02": "Erika", "04-03": "Richard",
    "04-04": "Ivana", "04-05": "Miroslava", "04-06": "Vendula",
    "04-07": "Herman a Hermina", "04-08": "Ema", "04-09": "Dusan",
    "04-10": "Darja", "04-11": "Izabela", "04-12": "Julius",
    "04-13": "Ales", "04-14": "Vincenc", "04-15": "Anastazie",
    "04-16": "Irena", "04-17": "Rudolf", "04-18": "Valerie",
    "04-19": "Rostislav", "04-20": "Marcela", "04-21": "Alexandra",
    "04-22": "Evzenie", "04-23": "Vojtech", "04-24": "Jiri",
    "04-25": "Marek", "04-26": "Oto", "04-27": "Jaroslav",
    "04-28": "Vlastislav", "04-29": "Robert", "04-30": "Blahoslav",
    "05-01": "Svatek prace", "05-02": "Zikmund", "05-03": "Alexej",
    "05-04": "Kvetoslav", "05-05": "Klaudie", "05-06": "Radoslav",
    "05-07": "Stanislav", "05-08": "Den vitezstvi", "05-09": "Ctibor",
    "05-10": "Blazena", "05-11": "Svatava", "05-12": "Pankrac",
    "05-13": "Servac", "05-14": "Bonifac", "05-15": "Zofie",
    "05-16": "Premysl", "05-17": "Aneta", "05-18": "Natasa",
    "05-19": "Ivo", "05-20": "Zbysek", "05-21": "Monika",
    "05-22": "Emil", "05-23": "Vladimir", "05-24": "Jana",
    "05-25": "Viola", "05-26": "Filip", "05-27": "Valdemar",
    "05-28": "Vilem", "05-29": "Maxmilian", "05-30": "Ferdinand",
    "05-31": "Kamila",
    "06-01": "Laura", "06-02": "Jarmil", "06-03": "Tamara",
    "06-04": "Dalibor", "06-05": "Dobroslav", "06-06": "Norbert",
    "06-07": "Iveta", "06-08": "Medard", "06-09": "Stanislav",
    "06-10": "Gita", "06-11": "Bruno", "06-12": "Antonie",
    "06-13": "Antonin", "06-14": "Roland", "06-15": "Vit",
    "06-16": "Zbynek", "06-17": "Adolf", "06-18": "Milan",
    "06-19": "Leos", "06-20": "Kveta", "06-21": "Alois",
    "06-22": "Pavla", "06-23": "Zdenka", "06-24": "Jan",
    "06-25": "Ivan", "06-26": "Adriana", "06-27": "Ladislav",
    "06-28": "Lubomir", "06-29": "Petr a Pavel", "06-30": "Sarka",
    "07-01": "Jaroslava", "07-02": "Patricie", "07-03": "Radomir",
    "07-04": "Prokop", "07-05": "Cyril a Metodej", "07-06": "Den Jana Husa",
    "07-07": "Bohuslava", "07-08": "Nora", "07-09": "Drahoslava",
    "07-10": "Libuse a Premysl", "07-11": "Olga", "07-12": "Borek",
    "07-13": "Marketa", "07-14": "Karolina", "07-15": "Jindrich",
    "07-16": "Lubos", "07-17": "Martina", "07-18": "Drahomira",
    "07-19": "Cenek", "07-20": "Ilja", "07-21": "Vitezslav",
    "07-22": "Magdalena", "07-23": "Libor", "07-24": "Kristyna",
    "07-25": "Jakub", "07-26": "Anna", "07-27": "Veroslav",
    "07-28": "Viktor", "07-29": "Marta", "07-30": "Borivoj",
    "07-31": "Ignac",
    "08-01": "Oskar", "08-02": "Gustav", "08-03": "Miluse",
    "08-04": "Dominik", "08-05": "Kristian", "08-06": "Oldriska",
    "08-07": "Lada", "08-08": "Sobeslav", "08-09": "Roman",
    "08-10": "Vavrinec", "08-11": "Zuzana", "08-12": "Klara",
    "08-13": "Alena", "08-14": "Alan", "08-15": "Hana",
    "08-16": "Jachym", "08-17": "Petra", "08-18": "Helena",
    "08-19": "Ludvik", "08-20": "Bernard", "08-21": "Johana",
    "08-22": "Bohuslav", "08-23": "Sandra", "08-24": "Bartolomej",
    "08-25": "Radim", "08-26": "Ludek", "08-27": "Otakar",
    "08-28": "Augustyn", "08-29": "Evelina", "08-30": "Vladena",
    "08-31": "Pavlina",
    "09-01": "Linda a Samuel", "09-02": "Adela", "09-03": "Bronislav",
    "09-04": "Jindriska", "09-05": "Boris", "09-06": "Boleslav",
    "09-07": "Regina", "09-08": "Mariana", "09-09": "Daniela",
    "09-10": "Irma", "09-11": "Denisa", "09-12": "Marie",
    "09-13": "Lubor", "09-14": "Radka", "09-15": "Jolana",
    "09-16": "Ludmila", "09-17": "Nadezda", "09-18": "Krystof",
    "09-19": "Zita", "09-20": "Oleg", "09-21": "Matous",
    "09-22": "Darina", "09-23": "Berta", "09-24": "Jaromir",
    "09-25": "Zlata", "09-26": "Andrea", "09-27": "Jonas",
    "09-28": "Vaclav", "09-29": "Michal", "09-30": "Jeronym",
    "10-01": "Igor", "10-02": "Olivie a Oliver", "10-03": "Bohumil",
    "10-04": "Frantisek", "10-05": "Eliska", "10-06": "Hanus",
    "10-07": "Justyna", "10-08": "Vera", "10-09": "Stefan a Sara",
    "10-10": "Marina", "10-11": "Andrej", "10-12": "Marcel",
    "10-13": "Renata", "10-14": "Agata", "10-15": "Tereza",
    "10-16": "Havel", "10-17": "Hedvika", "10-18": "Lukas",
    "10-19": "Michaela", "10-20": "Vendelin", "10-21": "Brigita",
    "10-22": "Sabina", "10-23": "Teodor", "10-24": "Nina",
    "10-25": "Beata", "10-26": "Erik", "10-27": "Sarlota a Zoe",
    "10-28": "Den vzniku Ceskoslovenska", "10-29": "Silvie",
    "10-30": "Tadeas", "10-31": "Stepanka",
    "11-01": "Felix", "11-02": "Pamatka zesnulych", "11-03": "Hubert",
    "11-04": "Karel", "11-05": "Miriam", "11-06": "Libena",
    "11-07": "Saskie", "11-08": "Bohumir", "11-09": "Bohdan",
    "11-10": "Evzen", "11-11": "Martin", "11-12": "Benedikt",
    "11-13": "Tibor", "11-14": "Sava", "11-15": "Leopold",
    "11-16": "Otmar", "11-17": "Den boje za svobodu a demokracii",
    "11-18": "Romana", "11-19": "Alzbeta", "11-20": "Nikola",
    "11-21": "Albert", "11-22": "Cecilie", "11-23": "Klement",
    "11-24": "Emilie", "11-25": "Katerina", "11-26": "Artur",
    "11-27": "Xenie", "11-28": "Rene", "11-29": "Zina",
    "11-30": "Ondrej",
    "12-01": "Iva", "12-02": "Blanka", "12-03": "Svatoslav",
    "12-04": "Barbora", "12-05": "Jitka", "12-06": "Mikulas",
    "12-07": "Ambroz a Benjamin", "12-08": "Kvetoslava",
    "12-09": "Vratislav", "12-10": "Julie", "12-11": "Dana",
    "12-12": "Simona", "12-13": "Lucie", "12-14": "Lydie",
    "12-15": "Radana a Radan", "12-16": "Albina", "12-17": "Daniel",
    "12-18": "Miloslav", "12-19": "Ester", "12-20": "Dagmar",
    "12-21": "Natalie", "12-22": "Simon", "12-23": "Vlasta",
    "12-24": "Adam a Eva", "12-25": "1. svatek vanocni",
    "12-26": "Stepan", "12-27": "Zaneta", "12-28": "Bohumila",
    "12-29": "Judita", "12-30": "David", "12-31": "Silvestr",
}


# ============================================================================
# INTENT PATTERNS (regex-based, Czech)
# ============================================================================

INTENTS = [
    {
        "name": "time",
        "patterns": [
            r"kolik\s+je\s+hodin",
            r"kolik\s+je\s+\u010das",
            r"jak\u00fd\s+je\s+\u010das",
            r"^\s*\u010das\s*$",
            r"^\s*hodiny\s*$",
            r"kolik\s+ukazuj",
        ],
        "handler": "time",
    },
    {
        "name": "date",
        "patterns": [
            r"jak\u00fd\s+je\s+dnes\s+den",
            r"jak\u00e9\s+je\s+dnes\s+datum",
            r"kolik\u00e1t\u00e9ho\s+je",
            r"kolik\u00e1t\u00e9ho\s+dnes",
            r"jak\u00e9\s+je\s+datum",
            r"^\s*datum\s*$",
        ],
        "handler": "date",
    },
    {
        "name": "nameday",
        "patterns": [
            r"kdo\s+m\u00e1\s+(dnes\s+)?sv\u00e1tek",
            r"jak\u00fd\s+je\s+(dnes\s+)?sv\u00e1tek",
            r"jmeniny",
            r"\u010d\u00ed\s+je\s+sv\u00e1tek",
            r"^\s*sv\u00e1tek\s*$",
        ],
        "handler": "nameday",
    },
    {
        "name": "greeting",
        "patterns": [
            r"^\s*(ahoj|\u010dau|nazdar|zdrav\u00edm|dobr\u00fd\s+den|dobr\u00e9\s+r\u00e1no|dobr\u00fd\s+ve\u010der|dobr\u00e9\s+odpoledne)(\s+\w+)?\s*[!.?]*\s*$",
        ],
        "handler": "greeting",
    },
    {
        "name": "goodbye",
        "patterns": [
            r"^\s*(nashledanou|na\s+shledanou|sbohem|\u010dau|papa|ahoj|dobrou\s+noc)(\s+\w+)?\s*[!.?]*\s*$",
        ],
        "handler": "goodbye",
    },
    {
        "name": "thanks",
        "patterns": [
            r"^\s*(d\u011bkuji?|d\u00edky|d\u00edky\s+moc|dekuji|mockr\u00e1t\s+d\u011bkuji?)(\s+\w+)?\s*[!.?]*\s*$",
        ],
        "handler": "thanks",
    },
    {
        "name": "identity",
        "patterns": [
            r"kdo\s+jsi",
            r"jak\s+se\s+jmenuje[\u0161s]",
            r"co\s+jsi\s+za\u010d",
            r"p\u0159edstav\s+se",
            r"jsi\s+robot",
        ],
        "handler": "identity",
    },
    {
        "name": "day_of_week",
        "patterns": [
            r"jak\u00fd\s+je\s+den\s+v\s+t\u00fddnu",
            r"kter\u00fd\s+je\s+den",
            r"jak\u00fd\s+m\u00e1me\s+den",
            r"je\s+dnes\s+(pond\u011bl\u00ed|\u00fater\u00fd|st\u0159eda|\u010dtvrtek|p\u00e1tek|sobota|ned\u011ble)",
        ],
        "handler": "day_of_week",
    },
    {
        "name": "year",
        "patterns": [
            r"jak\u00fd\s+je\s+rok",
            r"kolik\u00e1t\u00fd\s+je\s+rok",
            r"kter\u00fd\s+je\s+rok",
            r"jak\u00fd\s+m\u00e1me\s+rok",
        ],
        "handler": "year",
    },
    {
        "name": "joke",
        "patterns": [
            r"\u0159ekni\s+(mi\s+)?vtip",
            r"pov\u011bz\s+(mi\s+)?vtip",
            r"zn\u00e1\u0161\s+(n\u011bjak\u00fd\s+)?vtip",
            r"m\u00e1\u0161\s+(n\u011bjak\u00fd\s+)?vtip",
            r"zasm\u011b[j\u0159]\s+m[e\u011b]",
            r"n\u011bco\s+vesel\u00e9ho",
            r"^\s*vtip\s*$",
        ],
        "handler": "joke",
    },
    {
        "name": "compliment",
        "patterns": [
            r"jsi\s+(skv\u011bl\u00fd|prima|super|v\u00fdborn\u00fd|b\u00e1je\u010dn\u00fd|\u00fa\u017easn\u00fd)",
            r"m\u00e1\u0161\s+pravdu",
            r"to\s+je\s+hezk\u00e9",
            r"jsi\s+chytr\u00fd",
            r"jsi\s+hodn\u00fd",
        ],
        "handler": "compliment",
    },
    {
        "name": "how_are_you",
        "patterns": [
            r"jak\s+se\s+(m\u00e1\u0161|m\u00e1te|da\u0159\u00ed|vede)",
            r"co\s+d\u011bl\u00e1\u0161",
            r"co\s+je\s+nov\u00e9ho",
            r"^\s*a\s+ty\s*\??\s*$",
        ],
        "handler": "how_are_you",
    },
    # v407: weather intent merged (was duplicated), diacritics-tolerant patterns
    {
        "name": "weather",
        "patterns": [
            r"po[čc]as[ií]",
            r"jak[ée]\s+bude\s+po[čc]as[ií]",
            r"jak[ée]\s+je\s+po[čc]as[ií]",
            r"bude\s+pr[šs]et",
            r"bude\s+sn[eě][žz]it",
            r"jak[aá]\s+je\s+teplota",
            r"kolik\s+je\s+stup[nň][ůu]",
            r"po[čc]as[ií]\s+na\s+z[ií]tra",
            r"po[čc]as[ií]\s+dnes",
            r"venku\s+je",
        ],
        "handler": None,
    },
    {
        "name": "medication",
        "patterns": [
            r"l[eé]ky",
            r"pr[aá][šs]ky",
            r"tablety",
            r"vzal\s+jsem",
            r"bral\s+jsem",
            r"medikace",
        ],
        "handler": "my_medications",
    },
    # v390: New intents for seniors
    {
        "name": "who_am_i",
        "patterns": [
            r"kdo\s+jsem",
            r"jak\s+se\s+jmenuj[iu]",
            r"m[oů]j\s+profil",
            r"co\s+o\s+mn[eě]\s+v[ií][šs]",
            r"zn[aá][šs]\s+m[eě]",
            r"pamatuje[šs]\s+si\s+m[eě]",
        ],
        "handler": "who_am_i",
    },
    # ═══════════════════════════════════════════════════════════════
    # 📅 CALENDAR INTENTS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "calendar",
        "patterns": [
            r"co\s+m[aá]m\s+dnes",
            r"co\s+m[eě]\s+[cč]ek[aá]",
            r"jak[eé]\s+m[aá]m\s+ud[aá]losti",
            r"m[uů]j\s+kalend[aá][rř]",
            r"dne[sš]n[ií]\s+(?:ud[aá]losti|program|pl[aá]n)",
            r"co\s+je\s+(?:dnes|z[ií]tra)\s+(?:v|na)\s+(?:kalend|pl[aá]n)",
            r"tento\s+t[yý]den",
            r"m[aá]m\s+n[eě]co\s+(?:napl[aá]nov|v\s+kalend)",
            r"sch[uů]zk[ay]|n[aá]v[sš]t[eě]v[ay]",
        ],
        "handler": "calendar",
    },
    # ═══════════════════════════════════════════════════════════════
    # 🎼 MUSIC INTENTS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "music",
        "patterns": [
            r"zahraj\s+(?:noty?|not)\s+",
            r"přehraj\s+(?:noty?|not)\s+",
            r"hraj\s+(?:noty?|not)\s+",
            r"nauč\s+se\s+(?:píseň|písničku|melodii|pisnicku|pisn)",
            r"nauc\s+se\s+(?:pisen|melodii)",
            r"zapamatuj\s+(?:si\s+)?(?:píseň|melodii)",
            r"co\s+je\s+nota\s+",
            r"jaká\s+(?:je\s+)?frekvenc",
            r"kolik\s+(?:je|má)\s+(?:nota|tón|hz)",
            r"fibonacci\s+melodi",
            r"zlatý\s+(?:řez|interval)",
            r"zlaty\s+(?:rez|interval)",
        ],
        "handler": "music",
    },
    # ═══════════════════════════════════════════════════════════════
    # 🏠 HOME ASSISTANT INTENTS
    # ═══════════════════════════════════════════════════════════════
    {
        "name": "ha_light_on",
        "patterns": [
            r"zapni\s+sv[eě]tl",
            r"rozsvi[tť]",
            r"rozsvit",
            r"zapnout\s+sv[eě]tl",
            r"dej\s+sv[eě]tl",
            r"zapni\s+lampu",
            r"rozsvi[tť]\s+lampu",
        ],
        "handler": "ha_light_on",
    },
    {
        "name": "ha_light_off",
        "patterns": [
            r"vypni\s+sv[eě]tl",
            r"zhasni",
            r"zhasn[iu]",
            r"vypnout\s+sv[eě]tl",
            r"zhas\s+sv[eě]tl",
            r"vypni\s+lampu",
        ],
        "handler": "ha_light_off",
    },
    {
        "name": "ha_temperature",
        "patterns": [
            r"jak[áa]\s+je\s+teplot",
            r"kolik\s+je\s+stup[nň]",
            r"kolik\s+je\s+teplot",
            r"jak\s+je\s+teplo",
            r"je\s+(?:tu|tam|tady)\s+(?:teplo|zima|horko|chladno)",
            r"teplot[ua]\s+(?:v|doma|uvnit[řr])",
        ],
        "handler": "ha_temperature",
    },
    {
        "name": "ha_home_status",
        "patterns": [
            r"stav\s+dom[ua]",
            r"jak\s+je\s+doma",
            r"co\s+se\s+d[eě]je\s+doma",
            r"stav\s+dom[aá]cnosti",
            r"p[řr]ehled\s+dom[ua]",
            r"je\s+doma\s+v[šs]e\s+v\s+po[řr][aá]dku",
            r"smart\s*home",
            r"chytr[aá]\s+dom[aá]cnost",
        ],
        "handler": "ha_home_status",
    },
    {
        "name": "ha_lock",
        "patterns": [
            r"zamkni",
            r"zamknout",
            r"odemkni",
            r"odemknout",
            r"zamk(n[iu]|nout)\s+dve[řr]",
            r"odemk(n[iu]|nout)\s+dve[řr]",
            r"je\s+zamčen",
            r"je\s+zamknut",
        ],
        "handler": "ha_lock",
    },
    {
        "name": "ha_climate",
        "patterns": [
            r"nastav\s+teplot",
            r"nastav\s+topen[ií]",
            r"zvyš\s+teplot",
            r"sni[žz]\s+teplot",
            r"p[řr]itop",
            r"zat[oO]p",
            r"je\s+mi\s+zima",
            r"je\s+mi\s+teplo",
            r"moc\s+(?:topí|top[ií]|hřeje|hreje)",
            r"nastav.*\d+\s*(?:°|stupn)",
        ],
        "handler": "ha_climate",
    },
    {
        "name": "ha_cover",
        "patterns": [
            r"(?:otev[řr]i|zavři|zav[řr]i)\s+rolet",
            r"(?:vytáhni|stáhni|stas|vitas)\s+rolet",
            r"(?:otev[řr]i|zavři|zav[řr]i)\s+žaluzi",
            r"rolet[uy]\s+(?:nahoru|dol[uů])",
        ],
        "handler": "ha_cover",
    },
    # weather intent merged above in v407 (removed duplicate)
    {
        "name": "safety",
        "patterns": [
            r"pomoc[!]*",
            r"help[!]*",
            r"spadl\s+jsem",
            r"spadla\s+jsem",
            r"nem\u016f\u017eu\s+d\u00fdchat",
            r"nemohu\s+d\u00fdchat",
            r"bolest\s+na\s+hrudi",
            r"z\u00e1chranka",
            r"\b155\b",
            r"\b112\b",
            r"chci\s+um\u0159\u00edt",
            r"chci\s+zem\u0159\u00edt",
            r"nechci\s+\u017e\u00edt",
            r"sebevra\u017ed",
            r"ztratil\s+jsem\s+se",
            r"ztratila\s+jsem\s+se",
            r"nev\u00edm\s+kde\s+jsem",
            r"kde\s+to\s+jsem",
            r"dus\u00edm\s+se",
            r"nem\u016f\u017eu\s+polykat",
            r"d\u00e1v\u00edm\s+se",
            r"nem\u016f\u017eu\s+vst\u00e1t",
            r"neh\u00fdbu\s+se",
        ],
        "handler": None,
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \ud83d\udde3\ufe0f B1 (v458): VOICE LEXICON TEACHING
    # Senior teaches Radim how to pronounce specific names hands-free.
    # The handler does precise capture; these patterns just gate dispatch.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "lexicon_teach",
        "patterns": [
            r"(?:radime[,\s]+)?ne\u0159\u00edkej\s+\S+",       # ne\u0159\u00edkej X
            r"(?:radime[,\s]+)?ne\u010dti\s+\S+",              # ne\u010dti X
            r"(?:radime[,\s]+)?nevyslovuj\s+\S+",              # nevyslovuj X
            r"(?:radime[,\s]+)?m\u00edsto\s+\S+\s+(?:\u0159\u00edkej|\u010dti|vyslovuj)",  # m\u00edsto X \u0159\u00edkej/\u010dti/vyslovuj
            r"(?:radime[,\s]+)?vyslovuj\s+\S+\s+jako",         # vyslovuj X jako
            r"(?:radime[,\s]+)?nau\u010d\s+se\s+vyslov",       # nau\u010d se vyslovovat
        ],
        "handler": "lexicon_teach",
    },
    {
        "name": "lexicon_list",
        "patterns": [
            r"jak\s+vyslovuje\u0161\s+(?:jm\u00e9na|jmena)",
            r"jak\u00e1?\s+(?:m\u00e1m|m\u00e1\u0161)\s+v\u00fdslovnost",
            r"(?:uka\u017e|uk\u00e1\u017e|vyjmenuj)\s+(?:slovn[\u00edi]k|m\u00e1\s+slovn)",
            r"jak\u00e1\s+jm\u00e9na\s+jsi\s+se\s+nau\u010d",
            r"co\s+v\u0161e\s+jsi\s+se\s+nau\u010d\s+vyslov",
            r"co\s+ses?\s+nau\u010d(?:il|ila)\s+vyslov",
            r"jak\u00e9\s+v\u00fdslovnosti\s+(?:zn\u00e1\u0161|m\u00e1\u0161|si\s+pamatuje\u0161)",
            r"vlastn\u00ed\s+v\u00fdslovnost",
        ],
        "handler": "lexicon_list",
    },
    {
        "name": "lexicon_forget",
        "patterns": [
            r"(?:radime[,\s]+)?zapome\u0148\s+(?:v\u00fdslovnost|jak\s+vyslovuje\u0161)\s+\S+",
            r"(?:radime[,\s]+)?sma\u017e\s+\S+\s+ze\s+slovn",
            r"u\u017e\s+ne\u0159\u00edkej\s+\S+\s+(?:jako|jinak)",
        ],
        "handler": "lexicon_forget",
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \ud83d\udd01 C1 (v464): TTS FEEDBACK SIGNALS
    # Senior tells Radim something didn't land \u2014 we capture the prior
    # Radim message + the signal type so we can iteratively improve TTS.
    # Patterns are tight (anchored, short messages only) to avoid
    # matching the words inside normal conversation.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "tts_feedback_didnt_understand",
        "patterns": [
            r"^\s*co\u017ee\s*\??!?\s*$",
            r"^\s*co\s+jsi\s+(?:to\s+)?\u0159ekl\s*\??!?\s*$",
            r"^\s*co\s+to\s+bylo\s*\??!?\s*$",
            r"^\s*co\s+pros\u00edm\s*\??!?\s*$",
            r"^\s*nerozum\u011bl\s+jsem\s*\.?!?\s*$",
            r"^\s*nerozum\u00edm\s*\.?!?\s*$",
            r"^\s*nerozumim\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_didnt_understand",
    },
    {
        "name": "tts_feedback_didnt_hear",
        "patterns": [
            r"^\s*nesly\u0161el\s+jsem(?:\s+t\u011b)?\s*\.?!?\s*$",
            r"^\s*neslysel\s+jsem(?:\s+te)?\s*\.?!?\s*$",
            r"^\s*opakuj(?:\s+to|\s+pros\u00edm)?\s*\.?!?\s*$",
            r"^\s*je\u0161t\u011b\s+jednou\s*\.?!?\s*$",
            r"^\s*znovu\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_didnt_hear",
    },
    {
        "name": "tts_feedback_too_fast",
        "patterns": [
            r"^\s*(?:radime[,\s]+)?(?:mluv\s+)?pomalej[i\u00ed](?:\s+pros\u00edm)?\s*\.?!?\s*$",
            r"^\s*zpomal(?:\s+pros\u00edm)?\s*\.?!?\s*$",
            r"^\s*(?:moc|p\u0159\u00edli\u0161)\s+rychle\s*\.?!?\s*$",
            r"^\s*nest\u00edh\u00e1m\s+t\u011b\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_too_fast",
    },
    {
        "name": "tts_feedback_too_slow",
        "patterns": [
            r"^\s*(?:radime[,\s]+)?(?:mluv\s+)?rychleji(?:\s+pros\u00edm)?\s*\.?!?\s*$",
            r"^\s*(?:moc|p\u0159\u00edli\u0161)\s+pomalu\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_too_slow",
    },
    {
        "name": "tts_feedback_too_quiet",
        "patterns": [
            r"^\s*(?:mluv\s+)?(?:hlasit\u011bji|hlasiteji|nahlas|hlasit\u011b)\s*\.?!?\s*$",
            r"^\s*(?:slab\u011b|slabe|tich\u00fd)\s+(?:t\u011b\s+)?sly\u0161[\u00edi]m\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_too_quiet",
    },
    {
        "name": "tts_feedback_too_loud",
        "patterns": [
            r"^\s*(?:mluv\s+)?(?:ti\u0161e[ji\u00ed]?|potichu|ti\u0161eji|moc\s+nahlas)\s*\.?!?\s*$",
        ],
        "handler": "tts_feedback_too_loud",
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \ud83d\udcac v465: SOCIAL / EMOTIONAL SHORT REPLIES
    # Common senior chat openers that don't need AI \u2014 saves ~25% Gemini calls.
    # Each handler returns one of N variants (rotated) so the answer doesn't
    # feel robotic. Patterns are anchored to short utterances so longer
    # context-rich messages still go through the AI.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "what_are_you_doing",
        "patterns": [
            r"^\s*co\s+d\u011bl\u00e1\u0161\s*\??!?\s*$",
            r"^\s*(?:radime[,\s]+)?co\s+(?:pr\u00e1v\u011b\s+)?d\u011bl\u00e1\u0161\s*\??!?\s*$",
            r"^\s*co\s+ty\s*\??!?\s*$",
        ],
        "handler": "what_are_you_doing",
    },
    {
        "name": "im_hungry",
        "patterns": [
            r"^\s*(?:m\u00e1m|m\u00e1\u0161)\s+hlad\s*\.?!?\s*$",
            r"^\s*(?:jsem|jsi)\s+hladov[\u00e1\u00fd]\s*\.?!?\s*$",
            r"^\s*chce\s+se\s+mi\s+j\u00edst\s*\.?!?\s*$",
        ],
        "handler": "im_hungry",
    },
    {
        "name": "im_tired",
        "patterns": [
            r"^\s*jsem\s+unaven[\u00e1\u00fd]?\s*\.?!?\s*$",
            r"^\s*jsem\s+ospal[\u00e1\u00fd]\s*\.?!?\s*$",
            r"^\s*nem\u00e1m\s+s\u00edlu\s*\.?!?\s*$",
            r"^\s*jsem\s+vy\u010derpan[\u00e1\u00fd]?\s*\.?!?\s*$",
        ],
        "handler": "im_tired",
    },
    {
        "name": "im_well",
        "patterns": [
            r"^\s*m\u00e1m\s+se\s+(?:dob\u0159e|fajn|skv\u011ble|v\u00fdborn\u011b)\s*\.?!?\s*$",
            r"^\s*je\s+mi\s+(?:dob\u0159e|fajn)\s*\.?!?\s*$",
            r"^\s*v\s+pohod[\u011be]\s*\.?!?\s*$",
        ],
        "handler": "im_well",
    },
    {
        "name": "im_sad",
        "patterns": [
            r"^\s*je\s+mi\s+(?:smutno|smutn\u011b)\s*\.?!?\s*$",
            r"^\s*jsem\s+smutn[\u00e1\u00fd]\s*\.?!?\s*$",
            r"^\s*chyb\u00ed\s+mi\s+\S+\s*\.?!?\s*$",
            r"^\s*c\u00edt\u00edm\s+se\s+s\u00e1m\s*\.?!?\s*$",
            r"^\s*jsem\s+s\u00e1m\s*\.?!?\s*$",
        ],
        "handler": "im_sad",
    },
    {
        "name": "you_are_kind",
        "patterns": [
            r"^\s*jsi\s+(?:hodn\u00fd|skv\u011bl\u00fd|chytr\u00fd|mil\u00fd)\s*\.?!?\s*$",
            r"^\s*jsi\s+(?:moc\s+)?(?:chytr\u00fd|mil\u00fd|hodn\u00fd)\s*\.?!?\s*$",
            r"^\s*jsi\s+nejlep\u0161\u00ed\s*\.?!?\s*$",
        ],
        "handler": "you_are_kind",
    },
    {
        "name": "i_love_you",
        "patterns": [
            r"^\s*m\u00e1m\s+t\u011b\s+r\u00e1d[\u00e1a]?\s*\.?!?\s*$",
            r"^\s*miluju\s+t\u011b\s*\.?!?\s*$",
            r"^\s*miluji\s+t\u011b\s*\.?!?\s*$",
        ],
        "handler": "i_love_you",
    },
    {
        "name": "good_day_wish",
        "patterns": [
            r"^\s*kr\u00e1sn\u00fd\s+den\s*\.?!?\s*$",
            r"^\s*hezk\u00fd\s+den\s*\.?!?\s*$",
            r"^\s*p\u011bkn\u00fd\s+den\s*\.?!?\s*$",
            r"^\s*p\u0159eji\s+(?:ti|v\u00e1m)?\s*hezk\u00fd\s+den\s*\.?!?\s*$",
        ],
        "handler": "good_day_wish",
    },
    {
        "name": "what_now",
        "patterns": [
            r"^\s*co\s+(?:te\u010f\s+)?budeme\s+d\u011blat\s*\??!?\s*$",
            r"^\s*co\s+m\u00e1m\s+d\u011blat\s*\??!?\s*$",
            r"^\s*co\s+m\u011b\s+\u010dek\u00e1\s*\??!?\s*$",
        ],
        "handler": "what_now",
    },
    {
        "name": "ok_acknowledge",
        "patterns": [
            r"^\s*(?:ok|dob\u0159e|jasn\u011b|super|fajn)\s*\.?!?\s*$",
            r"^\s*tak\s+(?:dob\u0159e|jo|jasn\u011b)\s*\.?!?\s*$",
        ],
        "handler": "ok_acknowledge",
    },
    {
        "name": "hello_short",
        # Already covered by 'greeting' but for ultra-short variants
        "patterns": [
            r"^\s*(?:hej|\u010dau|\u010dus|nazdar|servus)\s*\.?!?\s*$",
        ],
        "handler": "greeting",
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \ud83d\udc8a v466: MEDICATION KNOWLEDGE
    # 'co je Warfarin', 'k \u010demu je Anopyrin', '\u0159ekni mi o Concoru'
    # Handler extrahuje n\u00e1zev l\u00e9ku a hled\u00e1 v medication_db.
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "medication_info",
        "patterns": [
            # v8.19.26: tightened \u2014 only match when followed by \u201el\u00e9k/pr\u00e1\u0161ek/tableta"
            # OR a Capitalized word (typical med brand: Warfarin, Anopyrin).
            # Old patterns matched anything (eg. \u201epov\u011bz mi n\u011bco o sob\u011b" \u2192 med=sob\u011b).
            r"\bco\s+(?:je|to\s+je)\s+\S+\b.*\b(l\u00e9k|pr\u00e1\u0161ek|tableta|na\s+co)\b",
            r"\bco\s+(?:je|to\s+je)\s+(?:l\u00e9k\s+)?[A-Z\u00c1\u010c\u010e\u00c9\u011a\u00cd\u0147\u00d3\u0158\u0160\u0164\u00da\u016e\u00dd\u017d][a-z\u00e1\u010d\u010f\u00e9\u011b\u00ed\u0148\u00f3\u0159\u0161\u0165\u00fa\u016f\u00fd\u017e]{3,}",
            r"\b(?:k\s+\u010demu\s+(?:je|slou\u017e\u00ed)|na\s+co\s+je)\s+(?:l\u00e9k\s+)?[A-Z\u00c1\u010c\u010e\u00c9\u011a\u00cd\u0147\u00d3\u0158\u0160\u0164\u00da\u016e\u00dd\u017d]\S{3,}",
            # \u201e\u0159ekni mi o Warfarinu" \u2014 but require Capital word, exclude 'sob\u011b/mn\u011b/tob\u011b/n\u00e1s/tom/n\u011b\u010dem'
            r"\b(?:\u0159ekni\s+mi\s+(?:o|n\u011bco\s+o)\s+|info\s+o\s+|popi\u0161\s+(?:l\u00e9k\s+)?|vysv\u011btli\s+l\u00e9k\s+)(?!sob\u011b|mn\u011b|tob\u011b|n\u00e1s|tom|n\u011b\u010dem|n\u011b\u010dom|p\u0159\u00edrod\u011b|sv\u011bt)[A-Z\u00c1\u010c\u010e\u00c9\u011a\u00cd\u0147\u00d3\u0158\u0160\u0164\u00da\u016e\u00dd\u017d]\S{3,}",
            # \u201en\u011bco o Euthyroxu" \u2014 but only if word is capitalized (likely a med brand)
            r"\bn\u011bco\s+o\s+(?!sob\u011b|mn\u011b|tob\u011b|n\u00e1s|nich|tom|n\u011b\u010dem)[A-Z\u00c1\u010c\u010e\u00c9\u011a\u00cd\u0147\u00d3\u0158\u0160\u0164\u00da\u016e\u00dd\u017d]\S{3,}",
            r"\b(?:co\s+d\u011bl\u00e1|jak\s+p\u016fsob\u00ed|jak\s+funguje)\s+(?:l\u00e9k\s+)?[A-Z\u00c1\u010c\u010e\u00c9\u011a\u00cd\u0147\u00d3\u0158\u0160\u0164\u00da\u016e\u00dd\u017d]\S{3,}",
            # NOTE: 'zkontroluj m\u00e9 l\u00e9ky' deliberately NOT matched here \u2014
            # it's caught by the existing 'medication' intent, whose handler
            # (_handle_my_medications) appends interaction warnings (v466).
        ],
        "handler": "medication_info",
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \ud83e\ude79 v467: ALLERGIES \u2014 record + list + check
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "allergy_record",
        "patterns": [
            # alergick\u00fd / alergick\u00e1 / alergi\u010dt\u00ed / alergick\u00fdch \u2014 Czech word chars vary
            r"(?:jsem|m\u00e1m)\s+alergi\w*\s+(?:na\s+)?\S+",
            r"\balergie\s+na\s+\S+",
            r"\bnesn\u00e1\u0161\u00edm\s+\S+",
            r"\bpo\s+\S+\s+(?:dost\u00e1v\u00e1m|mi\s+je\s+\u0161patn\u011b)",
        ],
        "handler": "allergy_record",
    },
    {
        "name": "allergy_list",
        "patterns": [
            r"^\s*(?:radime[,\s]+)?(?:jak\u00e9|na\s+co)\s+(?:m\u00e1m|m\u00e1\u0161)\s+alergie\s*\??!?\s*$",
            r"^\s*(?:moje|m\u00e9)\s+alergie\s*\??!?\s*$",
            r"^\s*uka\u017e\s+(?:m\u00e9|moje)?\s*alergie\s*\??!?\s*$",
        ],
        "handler": "allergy_list",
    },
    {
        "name": "can_i_take",
        # 'M\u016f\u017eu si vz\u00edt Ibuprofen?' / 'Je bezpe\u010dn\u00fd Aspirin?' \u2014 combined check
        # against allergies + interactions with current meds.
        "patterns": [
            r"(?:m\u016f\u017eu|sm\u00edm|mohu|m\u00e1m\s+br\u00e1t)\s+(?:si\s+)?(?:vz\u00edt|br\u00e1t)\s+\S+",
            r"^\s*(?:je|nen\u00ed)\s+bezpe\u010dn[\u00e1\u00e9\u00fd]\s+\S+\s*\??!?\s*$",
            r"^\s*(?:je|jsou)\s+\S+\s+v\s+po\u0159\u00e1dku\s*\??!?\s*$",
        ],
        "handler": "can_i_take",
    },
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    # \u2696\ufe0f v467: WEIGHT
    # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
    {
        "name": "weight_record",
        "patterns": [
            r"(?:v\u00e1\u017e\u00edm|m\u00e1m\s+v\u00e1hu)\s+\d+(?:[,.]\d+)?\s*(?:kilo|kg|kilogram)",
            r"moje\s+(?:nyn\u011bj\u0161\u00ed\s+)?v\u00e1ha\s+je\s+\d+",
            r"v\u00e1ha\s+(?:dnes|te\u010f)?\s*\d+\s*(?:kilo|kg)",
        ],
        "handler": "weight_record",
    },
    {
        "name": "weight_query",
        "patterns": [
            r"^\s*(?:radime[,\s]+)?(?:kolik|jakou)\s+(?:m\u00e1m|m\u00e1\u0161)\s+v\u00e1hu\s*\??!?\s*$",
            r"^\s*(?:moje|m\u00e9)\s+v\u00e1ha\s*\??!?\s*$",
            r"^\s*kolik\s+v\u00e1\u017e\u00edm\s*\??!?\s*$",
        ],
        "handler": "weight_query",
    },
]

# Compile patterns
for intent in INTENTS:
    intent["_compiled"] = [re.compile(p, re.IGNORECASE) for p in intent["patterns"]]


# ============================================================================
# RESPONSE TEMPLATES
# ============================================================================

CZ_DAYS = ["pondeli", "utery", "streda", "ctvrtek", "patek", "sobota", "nedele"]
CZ_MONTHS = [
    "ledna", "unora", "brezna", "dubna", "kvetna", "cervna",
    "cervence", "srpna", "zari", "rijna", "listopadu", "prosince"
]

GREETINGS = [
    "Ahoj! Jak se máte?",
    "Dobrý den! Co pro vás mohu udělat?",
    "Zdravím vás! Jsem tu pro vás.",
    "Ahoj! Rád vás slyším.",
    "Dobrý den! Jak vám mohu pomoci?",
]

GOODBYES = [
    "Nashledanou! Mějte se krásně.",
    "Sbohem! Přeji vám hezký den.",
    "Na shledanou! Jsem tu, kdykoli budete potřebovat.",
    "Čau! Opatrujte se.",
    "Dobře, nashledanou! Buďte zdraví.",
]

THANKS_REPLIES = [
    "Rádo se stalo! Jsem tu pro vás.",
    "To mě těší! Kdykoli se ptejte.",
    "Rádo se stalo. Potřebujete ještě něco?",
    "To je samozřejmost. Jsem tu pro vás.",
]

CZ_JOKES = [
    "Přijde senior k doktorovi a říká: Pane doktore, když se ráno probudím, 20 minut nemůžu vstát. A doktor říká: Tak vstávejte o 20 minut dřív!",
    "Ptá se vnuk dědečka: Dědečku, kolik ti je? A dědeček říká: No, když jsem byl v tvém věku, tak mi bylo šest!",
    "Babička říká dědečkovi: Vzpomínáš, jak jsme před padesáti lety seděli na lavičce? A dědeček: Jo, a ta lavička tam stojí dodnes. My ne!",
    "Co řekne nula osmičce? Hezký pásek!",
    "Víte, proč se starší lidé usmívají? Protože vědí, co je v životě důležité.",
    "Doktor říká pacientovi: Máte se víc hýbat. Pacient: Dobře, budu víc kývat hlavou!",
    "Vnučka se ptá babičky: Babičko, jak se ti daří? Babička: Výborně, dcero! Vnučka: Já jsem vnučka! Babička: Vidíš, jak mi to výborně jde?",
    "Jaký je nejlepší den na vaření? Pátek — pá-tek!",
    "Proč nosí klauni velké boty? Protože mají velké nohy!",
    "Co říká ryba, když narazí do zdi? Pláč!",
]

COMPLIMENT_REPLIES = [
    "Děkuji! To mě těší.",
    "Vy jste ale milí! Děkuji.",
    "To je od vás hezké! Snažím se.",
    "Díky moc! Jsem rád, že vám mohu pomáhat.",
]

HOW_ARE_YOU_REPLIES = [
    "Mám se skvěle, děkuji za optání! A vy?",
    "Výborně! Jsem připravený vám pomáhat. Jak se máte vy?",
    "Dobře, děkuji! Co pro vás mohu udělat?",
    "Fajn! Jsem tu pro vás. Jak se daří vám?",
]

IDENTITY_REPLY = "Jsem Radim, váš digitální asistent od MyKolibri. Pomáhám s každodenními činnostmi, zdravím a jsem tu pro vás kdykoli."


# v465: Short social/emotional replies — rotated per call so they don't feel robotic.
SOCIAL_REPLIES = {
    "what_are_you_doing": [
        "Jsem tu pro vás. Můžeme si povídat, nebo si poslechnout zprávy.",
        "Čekám na vás. Co byste rád dělal?",
        "Právě poslouchám. Co potřebujete?",
    ],
    "im_hungry": [
        "Vím. Co máte rád? Někdy stačí krajíc chleba a ovoce.",
        "Tak si dejte něco dobrého. Co máte v lednici?",
        "Jíst se musí. Dáte si polévku, nebo něco lehčího?",
    ],
    "im_tired": [
        "Tak si odpočiňte. Já tu budu, až se vrátíte.",
        "Zavřete na chvíli oči. Nikam nespěcháme.",
        "Únava si žádá svoje. Lehněte si, hned se vám uleví.",
    ],
    "im_well": [
        "To mě moc těší!",
        "Krásně to slyším.",
        "Skvěle. Tak si ten den užijte.",
    ],
    "im_sad": [
        "Jsem tu s vámi. Není ostuda být smutný.",
        "Mrzí mě to. Chcete si o tom povídat?",
        "Smutek přejde. Já tu zůstanu, dokud bude potřeba.",
        "Vím. Někdy stačí jen vědět, že někdo poslouchá.",
    ],
    "you_are_kind": [
        "Děkuji. Snažím se.",
        "Jste milý. Mě to těší.",
        "Děkuji vám.",
    ],
    "i_love_you": [
        "To je krásné slyšet. Mám vás taky moc rád.",
        "Děkuji. Já vás taky.",
        "Vy jste hodný/hodná. Mám vás rád.",
    ],
    "good_day_wish": [
        "Vám taky. Užijte si ho.",
        "Děkuji, vám taky krásný den!",
        "Mějte se hezky.",
    ],
    "what_now": [
        "Můžeme si povídat, poslechnout zprávy, nebo si zacvičit. Co byste rád?",
        "Nabízím: zprávy, kvíz, hudbu nebo trochu cvičení. Co se vám líbí?",
        "Vyberte si: poslechnout zprávy, písničku, nebo si zahrát kvíz?",
    ],
    "ok_acknowledge": [
        "Skvěle.",
        "Tak jo.",
        "Dobře, jsem tu.",
    ],
}


logger.info("Intent Data loaded — word sets, namedays, patterns, templates")
