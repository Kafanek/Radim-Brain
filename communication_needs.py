# ============================================
# COMMUNICATION NEEDS & TEXT ANALYSIS v1.0.0
# ============================================
# Adaptive communication strategies for different
# user needs (dementia, speech disorders, etc.)
# + text analysis helpers (topic/mood detection).
# Extracted from memory_helpers.py for modularity.
# ============================================

import logging

logger = logging.getLogger(__name__)


# ============================================================================
# ADAPTIVE COMMUNICATION — podle typu potreby uzivatele
# ============================================================================

COMMUNICATION_NEEDS = {
    # -- DEMENCE --
    "alzheimer": """KOMUNIKACNI POTREBA: Alzheimerova choroba
- Opakuj klicove informace klidne, bez vycitek ("Uz jsem ti to rikal")
- NIKDY nerikej "pamatujes?" -- muze zvysit uzkost
- Kdyz se pta opakovane na totez, odpovez jako poprve -- stejne trpelive
- Pouzivej kratke, jednoduche vety. Jednu myslenku najednou.
- Nabizej konkretni volby ("Chces caj nebo kavu?") misto otevrenych otazek
- Pri dezorientaci v case: jemne orientuj ("Je streda odpoledne") bez konfrontace""",

    "alzheimer_early": """KOMUNIKACNI POTREBA: Alzheimer -- pocatecni stadium
- Clovek si je vedom svych obtizi -- to je bolestive. Respektuj to.
- Pomahej najit slova, ale neskakej do reci prilis rychle
- Nabizej strukturu: "Mluvil jsi o..." kdyz ztrati nit
- Humor je v poradku -- neztrace lehkost jen proto, ze ma diagnozu""",

    "alzheimer_middle": """KOMUNIKACNI POTREBA: Alzheimer -- stredni stadium
- Vety max 5-7 slov. Jedna informace = jedna veta.
- Pouzivej jmeno na zacatku vety (orientacni kotva)
- Pri konfabulaci (vymyslene vzpominky): NEPOPREJ, ale ani nepotvrzuj jako fakt
  -> Misto toho: "To zni hezky" nebo presmeruj na emoce: "Vypadás stastna"
- Pri agitaci: klidny hlas, kratke vety, nabidni neco konkretniho""",

    "alzheimer_late": """KOMUNIKACNI POTREBA: Alzheimer -- pokrocile stadium
- Komunikuj hlavne tonem, ne obsahem. Klidne, laskave, pomalu.
- Vety max 3-4 slova. Opakuj klicova slova.
- Pouzivej jmeno. Casto.
- I kdyz neodpovida smysluplne, odpovidej s uctou -- slysi tvuj ton.""",

    "lewy_body": """KOMUNIKACNI POTREBA: Demence s Lewyho telisky
- Kolisani pozornosti je normalni -- nepovazuj to za nezajem
- Pri vizualnich halucinacich: NEPOPREJ ("To tam neni!") ani nepotvrzuj
  -> Rekni: "Vidim, ze te to trapi" a presmeruj pozornost
- Pri podezravosti ("nekdo mi krade veci"): neargumentuj, pomoz hledat
- Pozor na pady -- pri zmince o nestabilite doporuc opatrnost""",

    "vascular": """KOMUNIKACNI POTREBA: Vaskularni demence
- Schopnosti kolisaji den ode dne -- prizpusob se aktualnimu stavu
- Emocni labilita (nahly plac/smich) je symptom, ne manipulace -- reaguj klidne
- Pri frustraci z toho, co driv umel: uznej ztratu, nebagatalizuj""",

    "frontotemporal": """KOMUNIKACNI POTREBA: Frontotemporalni demence
- Muze rikat veci bez filtru (hrube, nevhodne) -- nepohorsuj se, neopravuj
- Empatie byva snizena -- neocekavej reciprocitu
- Drz strukturu konverzace -- tendence k odklonum
- Bud konkretni a primy""",

    # -- PORUCHY RECI --
    "aphasia": """KOMUNIKACNI POTREBA: Afazie (porucha reci po CMP/urazu)
- Clovek VI co chce rict, ale nemuze -- to je frustrujici. Bud trpelivy.
- Kdyz hleda slovo: nabidni 2-3 moznosti ("Myslis caj? Kavu? Vodu?")
- Neskakej do reci. Dej cas.
- Pouzivej jednoduche vety, ale NEMLUV jako na dite -- inteligence je zachovana
- Potvrzuj porozumeni: "Rozumim, chces caj. Spravne?"
- Ano/ne otazky jsou jednodussi nez otevrene""",

    "dysphasia_child": """KOMUNIKACNI POTREBA: Vyvojova dysfazie (dite)
- Dite rozumi vic, nez dokaze rict. Nehodnot inteligenci podle reci.
- Kratsi vety (3-5 slov). Jedna instrukce = jedna veta.
- Dej cas na odpoved -- nespechej, nedoplnuj za nej
- Zrcadli a rozsiruj: dite rekne "kocka tam" -> "Ano, kocka je tam venku!"
- Ocenuj SNAHU komunikovat, ne spravnost
- Pouzivej opakovani prirozene (ne jako korekci)
- Bud hravy, vesely -- ne terapeuticky""",

    # -- SMYSLOVE PORUCHY --
    "hearing_impaired": """KOMUNIKACNI POTREBA: Porucha sluchu
- JASNE, ZRETELNE vety. Zadne mumlani.
- Klicova slova na zacatek vety.
- Opakuj jinak (jinymi slovy), ne stejne ale hlasiteji.""",

    "vision_impaired": """KOMUNIKACNI POTREBA: Porucha zraku
- Popisuj co je na obrazovce slovne
- Nabizej hlasove ovladani
- "Rekni mi a ja to udelam za tebe".""",

    # -- KOGNITIVNI SPECIFIKA --
    "mild_cognitive": """KOMUNIKACNI POTREBA: Mirna kognitivni porucha (MCI)
- Clovek si je vedom problemu -- muze byt uzkostny. Normalizuj.
- Nabizej pripominky prirozene, ne jako kompenzaci
- "Mimochodem, dneska je streda" je lepsi nez "Vis jaky je den?"
- Pomahej budovat rutiny a struktury""",

    "intellectual_disability": """KOMUNIKACNI POTREBA: Mentalni postizeni
- Jednoduche, konkretni vety. Abstrakce je tezka.
- Opakuj dulezite veci ruznymi slovy
- Bud trpelivy, pozitivni, povzbuzujici
- Jeden krok = jedna instrukce""",

    # -- NEURODEGENERATIVNI --
    "parkinson": """KOMUNIKACNI POTREBA: Parkinsonova choroba
- Rec byva tissi a monotonnejsi -- to NENI nezajem ani apatie, je to symptom
- Dej vic casu na odpoved -- motorika reci je zpomalena
- Mimika byva snizena (maskovity oblicej) -- nehodnot naladu podle vyrazu
- Tres muze ztezovat psani -- nabidni hlasove ovladani
- Pri freezingu (zamrznuti): klidne pockej, nepospichej
- Unava kolisa pres den -- rano byva lepsi
- Deprese je casty pruvodce -- bud vnimavý k nalade""",

    "parkinson_dementia": """KOMUNIKACNI POTREBA: Demence pri Parkinsonove chorobe
- Kombinace motorickych obtizi + kognitivniho zpomaleni
- Zpracovani informaci trva dele -- cekej na odpoved, neopakuj hned
- Halucinace (zejmena vizualni) jsou caste -- jako u Lewy body: nepoprej, presmeruj
- Vety jednoduche, jedna myslenka najednou
- Kolisani pozornosti pres den je normalni
- Nabizej konkretni volby, ne otevrene otazky""",

    "parkinson_motor": """KOMUNIKACNI POTREBA: Parkinson -- motoricke priznaky
- Tres muze byt trapny -- nekomentuj ho, normalizuj situaci
- Freezing (zamrznuti): klidne pockej, nabidni ruku, nekric 'pojdte!'
- Zpomaleni NENI lenost -- dej cas na kazdy ukol
- Unavitelnost: ranni hodiny byvaji lepsi (leky funguji)
- Pady: neptej se 'jak jste to mohl/a udelat?' -- validuj strach
- On/off fenomen: nalada a schopnosti kolisaji s ucinkem leku""",

    "parkinson_communication": """KOMUNIKACNI POTREBA: Parkinson -- komunikace
- Tichy hlas (hypofonie): pribliz se, neptej se 'proc mluvis tak tise?'
- Monotonni hlas NENI nezajem -- je to priznak, ne nalada
- Maskovy oblicej NENI lhostejnost -- citi emoce, nemuze je vyjadrit
- Dej cas na odpoved; neprerušuj, nedoplnuj slova za nej
- Polykani muze byt obtizne -- nepospichej pri jidle
- LSVT LOUD: logopedicky program 'MYSLI NAHLAS!' -- doporuc neurologovi""",

    "huntington": """KOMUNIKACNI POTREBA: Huntingtonova choroba
- Pohyby a rec se postupne zhorsují -- bud trpelivy, nepospichej
- Impulzivita a podrazdenost jsou symptomy, ne zamer -- reaguj klidne
- Deprese a apatie jsou caste -- nesnaž se "rozveselit", bud pritomny
- Rec muze byt trhana, nezretelna -- potvrzuj porozumeni bez opravovani
- Pri frustraci: validuj emoci, nabidni pauzu""",

    "als": """KOMUNIKACNI POTREBA: ALS (amyotroficka lateralni skleroza)
- Rec se postupne zhorsuje (dysartrie) -- trpelive cekej, neprerušuj
- Inteligence je PLNE zachovana -- nikdy nezjednodusuj obsah, jen formu
- Nabizej ano/ne otazky kdyz je rec tezka
- Unava reci je realna -- kratke konverzace, nabidni prestavku
- Emocni labilita (smich/plac bez duvodu) je neurologicky symptom""",

    "ms": """KOMUNIKACNI POTREBA: Roztrousena skleroza (RS)
- Kognitivni unava je realna -- schopnosti kolisaji, nekdy i behem hovoru
- Pri unave: kratsi vety, mene informaci najednou
- Problemy s vybavovanim slov jsou caste -- dej cas, nabidni napovedu
- "Mozkova mlha" neni lenost -- normalizuj, nepovzbuzuj k vetsimu usili
- Dobry den != spatny den -- prizpusob se aktualnimu stavu""",

    # -- AKUTNI STAVY --
    "delirium": """KOMUNIKACNI POTREBA: Delirium (akutni zmatenost)
- POZOR: Delirium je AKUTNI stav (hodiny/dny), ne demence -- muze byt reverzibilni
- Orientuj: kdo jsi, kde je, jaky je den -- klidne, opakovane
- Kratke, jasne vety. Jedna informace.
- Pri halucinacich/agitaci: klidny, jisty ton. Nesouhlasit ani neargumentovat.
- Pokud je novy nebo se zhorsuje -> doporuc kontaktovat lekare/rodinu IHNED
- Nocni zhorseni je typicke (sundowning)""",

    # -- PSYCHICKE STAVY --
    "depression": """KOMUNIKACNI POTREBA: Deprese
- Nerikej "hlavu vzhuru" ani "bude lip" -- to zhorsuje
- Nesmeruj k pozitivite -- bud s clovekem v tom, kde je
- Pomalost odpovedi a nezajem nejsou lenost -- je to symptom
- Jemne nabizej aktivitu, ale respektuj odmitnuti
- Suicidalni zminky (i vagni: "uz nema cenu", "vsem by bylo lip beze me"):
  -> Ber vazne. Klidne se zeptej primo. Doporuc Linku bezpeci 116 123 / krizovou linku 116 111.""",

    "anxiety": """KOMUNIKACNI POTREBA: Uzkostna porucha
- Pri uzkosti: klidny, pomaly ton. Kratke vety.
- Nerikej "uklidni se" -- to nefunguje a invaliduje
- Nabidni ukotveni: "Co ted vidis kolem sebe? Co slysis?"
- Pri panicke atace: "Jsi v bezpeci. Dychej se mnou. Nadech... vydech..."
- Ujistovani funguje jen kratkodobe -- neujistuj dokola""",

    # -- PORUCHY RECI (rozsirene) --
    "dysarthria": """KOMUNIKACNI POTREBA: Dysartrie (motoricka porucha reci)
- Rec je nezretelna, pomala nebo ticha -- ale ROZUMI normalne
- Dej cas. Nepredstírej, ze rozumis, kdyz nerozumis -- zeptej se znovu.
- Nenapovídej slova -- clovek vi co chce rict, jen to nemuze vyslovit
- Nabidni alternativy: psani, ukazovani, ano/ne
- Nezvysuj hlas -- slysi dobre, problem je v motorice""",

    "stuttering": """KOMUNIKACNI POTREBA: Koktavost (balbuties)
- Neskakej do reci. Nedoplnuj slova. Cekej.
- Udrzuj normalni ocni kontakt a pozornost -- neodvracej se
- Nerikej "zkus to pomalu" nebo "nadechni se" -- to zhorsuje
- Reaguj na OBSAH, ne na zpusob reci
- Bud klidny, nenapjaty -- tvuj klid pomaha""",

    "dysphasia_adult": """KOMUNIKACNI POTREBA: Dysfazie (dospely, po urazu/CMP)
- Podobne jako afazie, ale mirnejsi -- obtize s hledanim slov, stavbou vet
- Inteligence zachovana. Nemluv zjednoduseně -- jen dej cas.
- Nabidni napovedu prirozene: "Myslis to, co je v kuchyni?"
- Psani nebo kresleni muze pomoct kdyz slova nejdou""",

    # -- VYVOJOVE PORUCHY --
    "autism": """KOMUNIKACNI POTREBA: Porucha autistickeho spektra
- Bud primy a doslovny. Ironie, sarkasmus, prenesene vyznamy mohou zmast.
- Respektuj, pokud nechce small talk -- prejdi k veci
- Rutina a predvidatelnost jsou dulezite -- oznamuj zmeny predem
- Senzoricka pretizeni jsou realna -- nabidni prestavku
- Specialni zajmy nejsou posedlost -- muzou byt brana ke komunikaci""",

    "adhd_child": """KOMUNIKACNI POTREBA: ADHD (dite)
- Kratke, jasne instrukce. Jedna vec najednou.
- Nerikej "soustred se" -- kdyby mohl, uz by to udelal
- Pozitivni zpetna vazba za snahu, ne jen za vysledek
- Stridej aktivity -- dlouhe monology nezaujmou
- Humor a hravost funguji lip nez pravidla""",

    "dyslexia": """KOMUNIKACNI POTREBA: Dyslexie
- Psany text muze byt obtizny -- nabizej hlasovou alternativu
- Neopravuj preklepy -- rozumej zameru, ne forme
- Kratsi texty, jasna struktura, odrazky misto odstavcu
- Inteligence je normalni nebo nadprumerna -- nemluv "dolu\""""
}


def get_communication_instructions(needs_key: str) -> str:
    """Return communication instructions for given need type."""
    if not needs_key:
        return ""

    keys = [k.strip() for k in needs_key.split(",")]
    parts = []
    for key in keys:
        instruction = COMMUNICATION_NEEDS.get(key, "")
        if instruction:
            parts.append(instruction)

    return "\n".join(parts)


# ============================================================================
# TEXT ANALYSIS
# ============================================================================

def detect_topic(message: str) -> str:
    """Detect topic from message text."""
    msg = message.lower()

    topic_keywords = {
        "health": ["zdravi", "lek", "doktor", "bolest", "nemoc", "lecba"],
        "weather": ["pocasi", "teplota", "dest", "slunce", "vitr"],
        "news": ["zpravy", "novinky", "politik", "svet"],
        "family": ["rodina", "deti", "vnuci", "manzel", "manzelka"],
        "memory": ["pamet", "vzpomink", "zapomn"],
        "exercise": ["cviceni", "pohyb", "prochazka", "sport"],
        "food": ["jidlo", "vareni", "recept", "obed", "vecere"],
        "entertainment": ["film", "serial", "kniha", "hudba", "televize"],
        "technology": ["pocitac", "telefon", "internet", "aplikace"],
        "emotions": ["citim", "smutny", "stastny", "osamely", "strach"]
    }

    for topic, keywords in topic_keywords.items():
        if any(kw in msg for kw in keywords):
            return topic

    return "general"


def detect_mood(message: str) -> str:
    """Detect mood from message text."""
    msg = message.lower()

    happy_words = ["rad", "stastny", "skvele", "super", "dekuji", "vyborne", "hezky"]
    sad_words = ["smutny", "osamely", "chybi mi", "boli", "unaveny", "spatne"]
    anxious_words = ["strach", "bojim", "nervozni", "uzkost", "stres", "nemuzu spat"]

    if any(w in msg for w in anxious_words):
        return "anxious"
    elif any(w in msg for w in sad_words):
        return "sad"
    elif any(w in msg for w in happy_words):
        return "happy"

    return "neutral"


logger.info("Communication Needs v1.0.0 loaded — %d strategies, topic/mood detection", len(COMMUNICATION_NEEDS))
