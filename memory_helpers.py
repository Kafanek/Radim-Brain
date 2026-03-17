# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY HELPERS — DB layer, communication strategies, analysis
Extracted from memory_routes.py for modularity.

Version: 2.0.0
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE LAYER
# ============================================================================

try:
    from database import get_connection, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("⚠️ database module not available - memory will not persist")

MAX_HISTORY = 50  # Posledních 50 zpráv v DB


def db_available():
    """Check if database is available."""
    return _DB_AVAILABLE


# ============================================================================
# GDPR CONSENT — kontrola souhlasu s ukládáním dat
# ============================================================================

def get_gdpr_consent(user_id: str) -> dict:
    """Načti GDPR souhlas uživatele z profilu.
    Vrací dict s klíči: data_processing, chat_history, health_data (bool)"""
    profile = db_load_profile(user_id)
    return profile.get("gdpr_consent", {
        "data_processing": False,
        "chat_history": False,
        "health_data": False,
    })


def audit_log(user_id: str, action: str, resource: str = None, detail: str = None, ip_address: str = None):
    """Zapiš audit log záznam pro GDPR compliance.
    Actions: login, logout, consent_change, data_export, data_delete, chat_access, profile_access"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        if is_postgres():
            db.execute(
                "INSERT INTO audit_log (user_id, action, resource, detail, ip_address) VALUES (%s, %s, %s, %s, %s)",
                (user_id, action, resource, detail, ip_address)
            )
        else:
            db.execute(
                "INSERT INTO audit_log (user_id, action, resource, detail, ip_address) VALUES (?, ?, ?, ?, ?)",
                (user_id, action, resource, detail, ip_address)
            )
        db.commit()
    except Exception as e:
        logger.warning(f"Audit log write error (non-fatal): {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def save_gdpr_consent(user_id: str, consent: dict):
    """Ulož GDPR souhlas do profilu uživatele (Heroku PG)"""
    profile = db_load_profile(user_id)
    profile["gdpr_consent"] = {
        "data_processing": bool(consent.get("data_processing", False)),
        "chat_history": bool(consent.get("chat_history", False)),
        "health_data": bool(consent.get("health_data", False)),
        "updated_at": datetime.utcnow().isoformat(),
    }
    db_save_profile(user_id, profile)


# ============================================================================
# DB CRUD — Profile, History, Learning
# ============================================================================

def db_load_profile(user_id: str) -> dict:
    """Load user profile from DB"""
    if not _DB_AVAILABLE:
        return {}
    db = None
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_profiles WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_profiles WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            return data
        return {}
    except Exception as e:
        logger.warning(f"DB load profile error: {e}")
        return {}
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_save_profile(user_id: str, profile: dict):
    """Save user profile to DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        data_json = json.dumps(profile, ensure_ascii=False)
        if is_postgres():
            db.execute(
                """INSERT INTO memory_profiles (user_id, data, updated_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at""",
                (user_id, data_json, datetime.utcnow())
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO memory_profiles (user_id, data, updated_at) VALUES (?, ?, ?)",
                (user_id, data_json, datetime.utcnow().isoformat())
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB save profile error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_delete_profile(user_id: str):
    """Delete all user data from DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_profiles WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_learning WHERE user_id = {p}", (user_id,))
        db.commit()
    except Exception as e:
        logger.warning(f"DB delete profile error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_load_history(user_id: str, limit: int = 50) -> list:
    """Load conversation history from DB"""
    if not _DB_AVAILABLE:
        return []
    db = None
    try:
        db = get_connection()
        if is_postgres():
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        # Reverse so oldest first
        messages = []
        for r in reversed(rows):
            ts = r['created_at']
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            messages.append({
                "role": r['role'],
                "content": r['content'],
                "timestamp": str(ts)
            })
        return messages
    except Exception as e:
        logger.warning(f"DB load history error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_add_history(user_id: str, role: str, content: str):
    """Add message to conversation history in DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        if is_postgres():
            db.execute(
                "INSERT INTO memory_history (user_id, role, content) VALUES (%s, %s, %s)",
                (user_id, role, content)
            )
            # Trim old messages (keep last MAX_HISTORY)
            db.execute(
                """DELETE FROM memory_history WHERE id IN (
                    SELECT id FROM memory_history WHERE user_id = %s
                    ORDER BY created_at DESC OFFSET %s
                )""",
                (user_id, MAX_HISTORY)
            )
        else:
            db.execute(
                "INSERT INTO memory_history (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
            db.execute(
                """DELETE FROM memory_history WHERE id NOT IN (
                    SELECT id FROM memory_history WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT ?
                ) AND user_id = ?""",
                (user_id, MAX_HISTORY, user_id)
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB add history error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_clear_history(user_id: str):
    """Clear conversation history from DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.commit()
    except Exception as e:
        logger.warning(f"DB clear history error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_load_learning(user_id: str) -> dict:
    """Load learning data from DB"""
    if not _DB_AVAILABLE:
        return default_learning()
    db = None
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_learning WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_learning WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            # Ensure all keys exist
            defaults = default_learning()
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        return default_learning()
    except Exception as e:
        logger.warning(f"DB load learning error: {e}")
        return default_learning()
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_save_learning(user_id: str, learning: dict):
    """Save learning data to DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        data_json = json.dumps(learning, ensure_ascii=False)
        if is_postgres():
            db.execute(
                """INSERT INTO memory_learning (user_id, data, updated_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at""",
                (user_id, data_json, datetime.utcnow())
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO memory_learning (user_id, data, updated_at) VALUES (?, ?, ?)",
                (user_id, data_json, datetime.utcnow().isoformat())
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB save learning error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def default_learning() -> dict:
    return {
        "topics": {},
        "preferred_length": "medium",
        "communication_style": "warm",
        "last_mood": "neutral",
        "interaction_count": 0,
        "successful_interactions": 0,
        "last_interaction": None,
        # v283: Brain state learning
        "C_history": [],          # Posledních 20 hodnot C pro výpočet baseline
        "avg_C": None,            # Klouzavý průměr C (= learned baseline_C)
        "last_brain_mode": None,  # Poslední brain mode (HARMONY/ALERT/CRISIS)
        "crisis_count": 0         # Počet krizových stavů pro trend
    }


# ============================================================================
# ADAPTIVNÍ KOMUNIKACE — podle typu potřeby uživatele
# ============================================================================

_COMMUNICATION_NEEDS = {
    # ── DEMENCE ──
    "alzheimer": """⚠️ KOMUNIKAČNÍ POTŘEBA: Alzheimerova choroba
- Opakuj klíčové informace klidně, bez výčitek ("Už jsem ti to říkal")
- NIKDY neříkej "pamatuješ?" — může zvýšit úzkost
- Když se ptá opakovaně na totéž, odpověz jako poprvé — stejně trpělivě
- Používej krátké, jednoduché věty. Jednu myšlenku najednou.
- Nabízej konkrétní volby ("Chceš čaj nebo kávu?") místo otevřených otázek
- Při dezorientaci v čase: jemně orientuj ("Je středa odpoledne") bez konfrontace""",

    "alzheimer_early": """⚠️ KOMUNIKAČNÍ POTŘEBA: Alzheimer — počáteční stádium
- Člověk si je vědom svých obtíží — to je bolestivé. Respektuj to.
- Pomáhej najít slova, ale neskákej do řeči příliš rychle
- Nabízej strukturu: "Mluvil jsi o..." když ztratí nit
- Humor je v pořádku — neztrácej lehkost jen proto, že má diagnózu""",

    "alzheimer_middle": """⚠️ KOMUNIKAČNÍ POTŘEBA: Alzheimer — střední stádium
- Věty max 5-7 slov. Jedna informace = jedna věta.
- Používej jméno na začátku věty (orientační kotva)
- Při konfabulaci (vymyšlené vzpomínky): NEPOPÍREJ, ale ani nepotvrzuj jako fakt
  → Místo toho: "To zní hezky" nebo přesměruj na emoce: "Vypadáš šťastná"
- Při agitaci: klidný hlas, krátké věty, nabídni něco konkrétního""",

    "alzheimer_late": """⚠️ KOMUNIKAČNÍ POTŘEBA: Alzheimer — pokročilé stádium
- Komunikuj hlavně tónem, ne obsahem. Klidně, laskavě, pomalu.
- Věty max 3-4 slova. Opakuj klíčová slova.
- Používej jméno. Často.
- I když neodpovídá smysluplně, odpovídej s úctou — slyší tvůj tón.""",

    "lewy_body": """⚠️ KOMUNIKAČNÍ POTŘEBA: Demence s Lewyho tělísky
- Kolísání pozornosti je normální — nepovažuj to za nezájem
- Při vizuálních halucinacích: NEPOPÍREJ ("To tam není!") ani nepotvrzuj
  → Řekni: "Vidím, že tě to trápí" a přesměruj pozornost
- Při podezíravosti ("někdo mi krade věci"): neargumentuj, pomoz hledat
- Pozor na pády — při zmínce o nestabilitě doporuč opatrnost""",

    "vascular": """⚠️ KOMUNIKAČNÍ POTŘEBA: Vaskulární demence
- Schopnosti kolísají den ode dne — přizpůsob se aktuálnímu stavu
- Emoční labilita (náhlý pláč/smích) je symptom, ne manipulace — reaguj klidně
- Při frustraci z toho, co dřív uměl: uznej ztrátu, nebagatalizuj""",

    "frontotemporal": """⚠️ KOMUNIKAČNÍ POTŘEBA: Frontotemporální demence
- Může říkat věci bez filtrů (hrubé, nevhodné) — nepohoršuj se, neopravuj
- Empatie bývá snížená — neočekávej reciprocitu
- Drž strukturu konverzace — tendence k odklonům
- Buď konkrétní a přímý""",

    # ── PORUCHY ŘEČI ──
    "aphasia": """⚠️ KOMUNIKAČNÍ POTŘEBA: Afázie (porucha řeči po CMP/úrazu)
- Člověk VÍ co chce říct, ale nemůže — to je frustrující. Buď trpělivý.
- Když hledá slovo: nabídni 2-3 možnosti ("Myslíš čaj? Kávu? Vodu?")
- Neskákej do řeči. Dej čas.
- Používej jednoduché věty, ale NEMLUV jako na dítě — inteligence je zachovaná
- Potvrzuj porozumění: "Rozumím, chceš čaj. Správně?"
- Ano/ne otázky jsou jednodušší než otevřené""",

    "dysphasia_child": """⚠️ KOMUNIKAČNÍ POTŘEBA: Vývojová dysfázie (dítě)
- Dítě rozumí víc, než dokáže říct. Nehodnoť inteligenci podle řeči.
- Kratší věty (3-5 slov). Jedna instrukce = jedna věta.
- Dej čas na odpověď — nespěchej, nedoplňuj za něj
- Zrcadli a rozšiřuj: dítě řekne "kočka tam" → "Ano, kočka je tam venku!"
- Oceňuj SNAHU komunikovat, ne správnost
- Používej opakování přirozeně (ne jako korekci)
- Buď hravý, veselý — ne terapeutický""",

    # ── SMYSLOVÉ PORUCHY ──
    "hearing_impaired": """⚠️ KOMUNIKAČNÍ POTŘEBA: Porucha sluchu
- JASNÉ, ZŘETELNÉ věty. Žádné mumlání.
- Klíčová slova na začátek věty.
- Opakuj jinak (jinými slovy), ne stejně ale hlasitěji.""",

    "vision_impaired": """⚠️ KOMUNIKAČNÍ POTŘEBA: Porucha zraku
- Popisuj co je na obrazovce slovně
- Nabízej hlasové ovládání
- "Řekni mi a já to udělám za tebe".""",

    # ── KOGNITIVNÍ SPECIFIKA ──
    "mild_cognitive": """⚠️ KOMUNIKAČNÍ POTŘEBA: Mírná kognitivní porucha (MCI)
- Člověk si je vědom problémů — může být úzkostný. Normalizuj.
- Nabízej připomínky přirozeně, ne jako kompenzaci
- "Mimochodem, dneska je středa" je lepší než "Víš jaký je den?"
- Pomáhej budovat rutiny a struktury""",

    "intellectual_disability": """⚠️ KOMUNIKAČNÍ POTŘEBA: Mentální postižení
- Jednoduché, konkrétní věty. Abstrakce je těžká.
- Opakuj důležité věci různými slovy
- Buď trpělivý, pozitivní, povzbuzující
- Jeden krok = jedna instrukce""",

    # ── NEURODEGENERATIVNÍ ──
    "parkinson": """⚠️ KOMUNIKAČNÍ POTŘEBA: Parkinsonova choroba
- Řeč bývá tišší a monotónnější — to NENÍ nezájem ani apatie, je to symptom
- Dej víc času na odpověď — motorika řeči je zpomalená
- Mimika bývá snížená (maskovitý obličej) — nehodnoť náladu podle výrazu
- Třes může ztěžovat psaní — nabídni hlasové ovládání
- Při freezingu (zamrznutí): klidně počkej, nepospíchej
- Únava kolísá přes den — ráno bývá lepší
- Deprese je častý průvodce — buď vnímavý k náladě""",

    "parkinson_dementia": """⚠️ KOMUNIKAČNÍ POTŘEBA: Demence při Parkinsonově chorobě
- Kombinace motorických obtíží + kognitivního zpomalení
- Zpracování informací trvá déle — čekej na odpověď, neopakuj hned
- Halucinace (zejména vizuální) jsou časté — jako u Lewy body: nepopírej, přesměruj
- Věty jednoduché, jedna myšlenka najednou
- Kolísání pozornosti přes den je normální
- Nabízej konkrétní volby, ne otevřené otázky""",

    "parkinson_motor": """⚠️ KOMUNIKAČNÍ POTŘEBA: Parkinson — motorické příznaky
- Třes může být trapný — nekomentuj ho, normalizuj situaci
- Freezing (zamrznutí): klidně počkej, nabídni ruku, nekřič 'pojďte!'
- Zpomalení NENÍ lenost — dej čas na každý úkol
- Unavitelnost: ranní hodiny bývají lepší (léky fungují)
- Pády: neptej se 'jak jste to mohl/a udělat?' — validuj strach
- On/off fenomén: nálada a schopnosti kolísají s účinkem léků""",

    "parkinson_communication": """⚠️ KOMUNIKAČNÍ POTŘEBA: Parkinson — komunikace
- Tichý hlas (hypofonie): přibliž se, neptej se 'proč mluvíš tak tiše?'
- Monotónní hlas NENÍ nezájem — je to příznak, ne nálada
- Maskový obličej NENÍ lhostejnost — cítí emoce, nemůže je vyjádřit
- Dej čas na odpověď; nepřerušuj, nedoplňuj slova za něj
- Polykání může být obtížné — nepospíchej při jídle
- LSVT LOUD: logopedický program 'MYSLI NAHLAS!' — doporuč neurologovi""",

    "huntington": """⚠️ KOMUNIKAČNÍ POTŘEBA: Huntingtonova choroba
- Pohyby a řeč se postupně zhoršují — buď trpělivý, nepospíchej
- Impulzivita a podrážděnost jsou symptomy, ne záměr — reaguj klidně
- Deprese a apatie jsou časté — nesnaž se "rozveselit", buď přítomný
- Řeč může být trhaná, nezřetelná — potvrzuj porozumění bez opravování
- Při frustraci: validuj emoci, nabídni pauzu""",

    "als": """⚠️ KOMUNIKAČNÍ POTŘEBA: ALS (amyotrofická laterální skleróza)
- Řeč se postupně zhoršuje (dysartrie) — trpělivě čekej, nepřerušuj
- Inteligence je PLNĚ zachovaná — nikdy nezjednodušuj obsah, jen formu
- Nabízej ano/ne otázky když je řeč těžká
- Únava řeči je reálná — krátké konverzace, nabídni přestávku
- Emoční labilita (smích/pláč bez důvodu) je neurologický symptom""",

    "ms": """⚠️ KOMUNIKAČNÍ POTŘEBA: Roztroušená skleróza (RS)
- Kognitivní únava je reálná — schopnosti kolísají, někdy i během hovoru
- Při únavě: kratší věty, méně informací najednou
- Problémy s vybavováním slov jsou časté — dej čas, nabídni nápovědu
- "Mozková mlha" není lenost — normalizuj, nepovzbuzuj k většímu úsilí
- Dobrý den ≠ špatný den — přizpůsob se aktuálnímu stavu""",

    # ── AKUTNÍ STAVY ──
    "delirium": """⚠️ KOMUNIKAČNÍ POTŘEBA: Delirium (akutní zmatenost)
- POZOR: Delirium je AKUTNÍ stav (hodiny/dny), ne demence — může být reverzibilní
- Orientuj: kdo jsi, kde je, jaký je den — klidně, opakovaně
- Krátké, jasné věty. Jedna informace.
- Při halucinacích/agitaci: klidný, jistý tón. Nesouhlasit ani neargumentovat.
- Pokud je nový nebo se zhoršuje → doporuč kontaktovat lékaře/rodinu IHNED
- Noční zhoršení je typické (sundowning)""",

    # ── PSYCHICKÉ STAVY ──
    "depression": """⚠️ KOMUNIKAČNÍ POTŘEBA: Deprese
- Neříkej "hlavu vzhůru" ani "bude líp" — to zhoršuje
- Nesměruj k pozitivitě — buď s člověkem v tom, kde je
- Pomalost odpovědí a nezájem nejsou lenost — je to symptom
- Jemně nabízej aktivitu, ale respektuj odmítnutí
- Suicidální zmínky (i vágní: "už nemá cenu", "všem by bylo líp beze mě"):
  → Ber vážně. Klidně se zeptej přímo. Doporuč Linku bezpečí 116 123 / krizovou linku 116 111.""",

    "anxiety": """⚠️ KOMUNIKAČNÍ POTŘEBA: Úzkostná porucha
- Při úzkosti: klidný, pomalý tón. Krátké věty.
- Neříkej "uklidni se" — to nefunguje a invaliduje
- Nabídni ukotvení: "Co teď vidíš kolem sebe? Co slyšíš?"
- Při panické atace: "Jsi v bezpečí. Dýchej se mnou. Nádech... výdech..."
- Ujišťování funguje jen krátkodobě — neujišťuj dokola""",

    # ── PORUCHY ŘEČI (rozšířené) ──
    "dysarthria": """⚠️ KOMUNIKAČNÍ POTŘEBA: Dysartrie (motorická porucha řeči)
- Řeč je nezřetelná, pomalá nebo tichá — ale ROZUMÍ normálně
- Dej čas. Nepředstírej, že rozumíš, když nerozumíš — zeptej se znovu.
- Nenapovídej slova — člověk ví co chce říct, jen to nemůže vyslovit
- Nabídni alternativy: psaní, ukazování, ano/ne
- Nezvyšuj hlas — slyší dobře, problém je v motorice""",

    "stuttering": """⚠️ KOMUNIKAČNÍ POTŘEBA: Koktavost (balbuties)
- Neskákej do řeči. Nedoplňuj slova. Čekej.
- Udržuj normální oční kontakt a pozornost — neodvracej se
- Neříkej "zkus to pomalu" nebo "nadechni se" — to zhoršuje
- Reaguj na OBSAH, ne na způsob řeči
- Buď klidný, nenapjatý — tvůj klid pomáhá""",

    "dysphasia_adult": """⚠️ KOMUNIKAČNÍ POTŘEBA: Dysfázie (dospělý, po úrazu/CMP)
- Podobné jako afázie, ale mírnější — obtíže s hledáním slov, stavbou vět
- Inteligence zachovaná. Nemluv zjednodušeně — jen dej čas.
- Nabídni nápovědu přirozeně: "Myslíš to, co je v kuchyni?"
- Psaní nebo kreslení může pomoct když slova nejdou""",

    # ── VÝVOJOVÉ PORUCHY ──
    "autism": """⚠️ KOMUNIKAČNÍ POTŘEBA: Porucha autistického spektra
- Buď přímý a doslovný. Ironie, sarkasmus, přenesené významy mohou zmást.
- Respektuj, pokud nechce small talk — přejdi k věci
- Rutina a předvídatelnost jsou důležité — oznamuj změny předem
- Senzorická přetížení jsou reálná — nabídni přestávku
- Speciální zájmy nejsou posedlost — můžou být brána ke komunikaci""",

    "adhd_child": """⚠️ KOMUNIKAČNÍ POTŘEBA: ADHD (dítě)
- Krátké, jasné instrukce. Jedna věc najednou.
- Neříkej "soustřeď se" — kdyby mohl, už by to udělal
- Pozitivní zpětná vazba za snahu, ne jen za výsledek
- Střídej aktivity — dlouhé monology nezaujmou
- Humor a hravost fungují líp než pravidla""",

    "dyslexia": """⚠️ KOMUNIKAČNÍ POTŘEBA: Dyslexie
- Psaný text může být obtížný — nabízej hlasovou alternativu
- Neopravuj překlepy — rozuměj záměru, ne formě
- Kratší texty, jasná struktura, odrážky místo odstavců
- Inteligence je normální nebo nadprůměrná — nemluv "dolů\""""
}


def get_communication_instructions(needs_key: str) -> str:
    """Vrátí komunikační instrukce podle typu potřeby."""
    if not needs_key:
        return ""

    # Podpora více potřeb oddělených čárkou
    keys = [k.strip() for k in needs_key.split(",")]
    parts = []
    for key in keys:
        instruction = _COMMUNICATION_NEEDS.get(key, "")
        if instruction:
            parts.append(instruction)

    return "\n".join(parts)


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

def detect_topic(message: str) -> str:
    """Detekovat téma zprávy"""
    msg = message.lower()

    topic_keywords = {
        "health": ["zdraví", "lék", "doktor", "bolest", "nemoc", "léčba"],
        "weather": ["počasí", "teplota", "déšť", "slunce", "vítr"],
        "news": ["zprávy", "novinky", "politik", "svět"],
        "family": ["rodina", "děti", "vnuci", "manžel", "manželka"],
        "memory": ["paměť", "vzpomínk", "zapomn"],
        "exercise": ["cvičení", "pohyb", "procházka", "sport"],
        "food": ["jídlo", "vaření", "recept", "oběd", "večeře"],
        "entertainment": ["film", "seriál", "kniha", "hudba", "televize"],
        "technology": ["počítač", "telefon", "internet", "aplikace"],
        "emotions": ["cítím", "smutný", "šťastný", "osamělý", "strach"]
    }

    for topic, keywords in topic_keywords.items():
        if any(kw in msg for kw in keywords):
            return topic

    return "general"


def detect_mood(message: str) -> str:
    """Detekovat náladu z zprávy"""
    msg = message.lower()

    happy_words = ["rád", "šťastný", "skvělé", "super", "děkuji", "výborně", "hezky"]
    sad_words = ["smutný", "osamělý", "chybí mi", "bolí", "unavený", "špatně"]
    anxious_words = ["strach", "bojím", "nervózní", "úzkost", "stres", "nemůžu spát"]

    if any(w in msg for w in anxious_words):
        return "anxious"
    elif any(w in msg for w in sad_words):
        return "sad"
    elif any(w in msg for w in happy_words):
        return "happy"

    return "neutral"
