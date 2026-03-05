# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY ROUTES - Adaptivní učící se komunikace
Conversation history + User profiles + Learning
PostgreSQL persistence with in-memory cache

Version: 2.0.0
"""

import os
import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth
from collections import defaultdict

logger = logging.getLogger(__name__)

# Flask Blueprint
memory_bp = Blueprint('memory', __name__, url_prefix='/api/memory')

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


def _db_load_profile(user_id: str) -> dict:
    """Load user profile from DB"""
    if not _DB_AVAILABLE:
        return {}
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_profiles WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_profiles WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        db.close()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            return data
        return {}
    except Exception as e:
        logger.warning(f"DB load profile error: {e}")
        return {}


def _db_save_profile(user_id: str, profile: dict):
    """Save user profile to DB"""
    if not _DB_AVAILABLE:
        return
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
        db.close()
    except Exception as e:
        logger.warning(f"DB save profile error: {e}")


def _db_delete_profile(user_id: str):
    """Delete all user data from DB"""
    if not _DB_AVAILABLE:
        return
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_profiles WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_learning WHERE user_id = {p}", (user_id,))
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"DB delete profile error: {e}")


def _db_load_history(user_id: str, limit: int = 50) -> list:
    """Load conversation history from DB"""
    if not _DB_AVAILABLE:
        return []
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
        db.close()
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


def _db_add_history(user_id: str, role: str, content: str):
    """Add message to conversation history in DB"""
    if not _DB_AVAILABLE:
        return
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
        db.close()
    except Exception as e:
        logger.warning(f"DB add history error: {e}")


def _db_clear_history(user_id: str):
    """Clear conversation history from DB"""
    if not _DB_AVAILABLE:
        return
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"DB clear history error: {e}")


def _db_load_learning(user_id: str) -> dict:
    """Load learning data from DB"""
    if not _DB_AVAILABLE:
        return _default_learning()
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_learning WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_learning WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        db.close()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            # Ensure all keys exist
            defaults = _default_learning()
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        return _default_learning()
    except Exception as e:
        logger.warning(f"DB load learning error: {e}")
        return _default_learning()


def _db_save_learning(user_id: str, learning: dict):
    """Save learning data to DB"""
    if not _DB_AVAILABLE:
        return
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
        db.close()
    except Exception as e:
        logger.warning(f"DB save learning error: {e}")


def _default_learning() -> dict:
    return {
        "topics": {},
        "preferred_length": "medium",
        "communication_style": "warm",
        "last_mood": "neutral",
        "interaction_count": 0,
        "successful_interactions": 0,
        "last_interaction": None
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


def _get_communication_instructions(needs_key: str) -> str:
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
# HELPER FUNCTIONS
# ============================================================================

def get_user_context(user_id: str) -> dict:
    """Získat kontext pro Claude system prompt"""
    profile = _db_load_profile(user_id)
    learning = _db_load_learning(user_id)
    history = _db_load_history(user_id, limit=5)

    # Top 3 témata zájmu
    topics = learning.get("topics", {})
    top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]

    context = {
        "has_profile": bool(profile),
        "name": profile.get("name", ""),
        "age_group": profile.get("age_group", ""),
        "hearing": profile.get("hearing", "normal"),
        "vision": profile.get("vision", "normal"),
        "memory_support": profile.get("memory_support", False),
        "communication_needs": profile.get("communication_needs", ""),
        "mobility": profile.get("mobility", "normal"),
        "communication_style": learning.get("communication_style", "warm"),
        "preferred_length": learning.get("preferred_length", "medium"),
        "top_interests": [t[0] for t in top_topics],
        "interaction_count": learning.get("interaction_count", 0),
        "last_mood": learning.get("last_mood", "neutral"),
        "recent_history": history,
        "_raw_profile": profile  # v230: plný profil pro léky, kontakty, rutinu
    }

    return context

def build_personalized_prompt(user_id: str) -> str:
    """Vytvořit personalizovaný system prompt addition"""
    ctx = get_user_context(user_id)

    if not ctx["has_profile"] and ctx["interaction_count"] == 0:
        return ""  # Nový uživatel - žádná personalizace

    parts = ["\n\n═══════════════════════════════════════════════════════════════"]
    parts.append("👤 PERSONALIZACE PRO TOHOTO UŽIVATELE")
    parts.append("═══════════════════════════════════════════════════════════════")

    if ctx["name"]:
        parts.append(f"- Jméno: {ctx['name']} (oslovuj jménem)")

    if ctx["age_group"]:
        parts.append(f"- Věková skupina: {ctx['age_group']}")

    # Zdravotní potřeby
    if ctx["hearing"] != "normal":
        parts.append(f"- Sluch: {ctx['hearing']} → Používej JASNÉ, KRÁTKÉ věty")

    if ctx["vision"] != "normal":
        parts.append(f"- Zrak: {ctx['vision']} → Zmíň že může zapnout větší text")

    if ctx["memory_support"]:
        parts.append("- Podpora paměti: ANO → Opakuj klíčové informace, buď trpělivý")

    # Komunikační potřeby (demence, afázie, dysfázie, aj.)
    comm_needs = ctx.get("communication_needs", "")
    if comm_needs:
        needs_instructions = _get_communication_instructions(comm_needs)
        if needs_instructions:
            parts.append(needs_instructions)

    # Komunikační styl
    style_map = {
        "warm": "Buď vřelý a empatický, používej přátelský tón",
        "formal": "Buď profesionální ale stále přátelský",
        "casual": "Buď neformální, používej humor"
    }
    parts.append(f"- Styl: {style_map.get(ctx['communication_style'], style_map['warm'])}")

    # Délka odpovědí
    length_map = {
        "short": "Odpovídej STRUČNĚ (max 2-3 věty)",
        "medium": "Odpovídej středně dlouze (4-6 vět)",
        "long": "Můžeš odpovídat podrobněji"
    }
    parts.append(f"- Délka: {length_map.get(ctx['preferred_length'], length_map['medium'])}")

    # Témata zájmu
    if ctx["top_interests"]:
        interests_str = ", ".join(ctx["top_interests"])
        parts.append(f"- Oblíbená témata: {interests_str} → Můžeš na ně navázat")

    # Nálada
    mood_map = {
        "happy": "Uživatel je v dobré náladě",
        "neutral": "Neutrální nálada",
        "sad": "Uživatel může být smutný - buď extra empatický",
        "anxious": "Uživatel může být úzkostný - buď uklidňující"
    }
    if ctx["last_mood"] != "neutral":
        parts.append(f"- Nálada: {mood_map.get(ctx['last_mood'], '')}")

    # Počet interakcí
    if ctx["interaction_count"] > 10:
        parts.append(f"- Známý uživatel ({ctx['interaction_count']} interakcí) - můžeš odkazovat na předchozí konverzace")

    # v230: Léky a denní rutina
    profile = ctx.get("_raw_profile", {})
    meds_list = profile.get("medications_list")
    if meds_list and isinstance(meds_list, list) and len(meds_list) > 0:
        parts.append(f"- Léky: {', '.join(meds_list)}")
        med_times = profile.get("medication_times")
        if med_times and isinstance(med_times, dict):
            for period, meds in med_times.items():
                if meds:
                    parts.append(f"  - {period}: {', '.join(meds) if isinstance(meds, list) else meds}")
        parts.append("  → Pokud se uživatel ptá na léky, znáš jeho medikaci.")

    routine = profile.get("daily_routine_notes")
    if routine:
        parts.append(f"- Denní rutina: {routine}")

    emergency = profile.get("emergency_contacts")
    if emergency and isinstance(emergency, list) and len(emergency) > 0:
        contacts_str = ", ".join(
            f"{c.get('name', '?')} ({c.get('phone', '?')})" for c in emergency[:3]
        )
        parts.append(f"- Nouzové kontakty: {contacts_str}")

    parts.append("═══════════════════════════════════════════════════════════════")

    return "\n".join(parts)

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

# ============================================================================
# ROUTES
# ============================================================================

@memory_bp.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "service": "RADIM Memory & Learning",
        "version": "2.0.0",
        "persistence": "postgresql" if (_DB_AVAILABLE and is_postgres()) else "sqlite" if _DB_AVAILABLE else "none",
        "db_available": _DB_AVAILABLE,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# USER PROFILE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/profile/<user_id>', methods=['GET'])
@require_auth
def get_profile(user_id):
    """Získat profil uživatele"""
    # Auth check: user can only access own data
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    profile = _db_load_profile(user_id)
    learning = _db_load_learning(user_id)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "learning": {
            "interaction_count": learning.get("interaction_count", 0),
            "top_topics": dict(sorted(learning.get("topics", {}).items(), key=lambda x: x[1], reverse=True)[:5]),
            "preferred_length": learning.get("preferred_length", "medium"),
            "communication_style": learning.get("communication_style", "warm"),
            "last_mood": learning.get("last_mood", "neutral")
        },
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['POST'])
@require_auth
def save_profile(user_id):
    """Uložit/aktualizovat profil uživatele"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    # Validace
    allowed_fields = ["name", "age_group", "hearing", "vision", "memory_support",
                      "communication_style", "preferred_length", "character", "tone",
                      "communication_needs", "mobility",
                      # v230: Domácí asistent — léky, kontakty, rutina
                      "medications_list",       # ["Prednison 5mg", "Vasoretic"]
                      "medication_times",       # {"ráno": ["Prednison"], "večer": ["Vasoretic"]}
                      "emergency_contacts",     # [{"name": "Eva", "phone": "+420..."}]
                      "daily_routine_notes",    # "Vstává v 7, obědvá v 12, spát ve 22"
                      "baseline_C"]             # Personalizované C baseline (float)

    profile = _db_load_profile(user_id)

    for field in allowed_fields:
        if field in data:
            profile[field] = data[field]

    profile["updated_at"] = datetime.utcnow().isoformat()
    _db_save_profile(user_id, profile)

    # Update learning preferences
    if "communication_style" in data or "preferred_length" in data:
        learning = _db_load_learning(user_id)
        if "communication_style" in data:
            learning["communication_style"] = data["communication_style"]
        if "preferred_length" in data:
            learning["preferred_length"] = data["preferred_length"]
        _db_save_learning(user_id, learning)

    logger.info(f"Profile saved for user: {user_id}")

    return jsonify({
        "success": True,
        "user_id": user_id,
        "profile": profile,
        "message": "Profil uložen",
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/profile/<user_id>', methods=['DELETE'])
@require_auth
def delete_profile(user_id):
    """Smazat profil uživatele (GDPR)"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    _db_delete_profile(user_id)

    logger.info(f"Profile deleted for user: {user_id}")

    return jsonify({
        "success": True,
        "message": "Všechna data smazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/history/<user_id>', methods=['GET'])
@require_auth
def get_history(user_id):
    """Získat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    limit = request.args.get('limit', 20, type=int)
    history = _db_load_history(user_id, limit=limit)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "messages": history,
        "total_count": len(history),
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['POST'])
@require_auth
def add_to_history(user_id):
    """Přidat zprávu do historie"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    role = data.get("role", "user")
    content = data.get("content", "")

    if not content:
        return jsonify({"success": False, "error": "Empty message"}), 400

    # Persist to DB
    _db_add_history(user_id, role, content)

    # Update learning for user messages
    if role == "user":
        learning = _db_load_learning(user_id)
        topic = detect_topic(content)
        mood = detect_mood(content)

        topics = learning.get("topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        learning["topics"] = topics
        learning["last_mood"] = mood
        learning["interaction_count"] = learning.get("interaction_count", 0) + 1
        learning["last_interaction"] = datetime.utcnow().isoformat()
        _db_save_learning(user_id, learning)

    return jsonify({
        "success": True,
        "message_added": {"role": role, "content": content, "timestamp": datetime.utcnow().isoformat()},
        "timestamp": datetime.utcnow().isoformat()
    })

@memory_bp.route('/history/<user_id>', methods=['DELETE'])
@require_auth
def clear_history(user_id):
    """Vymazat historii konverzací"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    _db_clear_history(user_id)

    return jsonify({
        "success": True,
        "message": "Historie vymazána",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT FOR CLAUDE
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/context/<user_id>', methods=['GET'])
@require_auth
def get_context(user_id):
    """Získat kontext pro Claude API volání"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    context = get_user_context(user_id)
    personalized_prompt = build_personalized_prompt(user_id)

    # Build messages array for Claude
    history = _db_load_history(user_id, limit=10)
    claude_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    return jsonify({
        "success": True,
        "user_id": user_id,
        "context": context,
        "personalized_prompt_addition": personalized_prompt,
        "conversation_messages": claude_messages,
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# FEEDBACK & LEARNING
# ─────────────────────────────────────────────────────────────────────────────

@memory_bp.route('/feedback/<user_id>', methods=['POST'])
@require_auth
def submit_feedback(user_id):
    """Uložit feedback pro učení"""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403
    data = request.get_json() or {}

    feedback_type = data.get("type", "neutral")  # positive/negative/neutral
    comment = data.get("comment", "")

    learning = _db_load_learning(user_id)

    if feedback_type == "positive":
        learning["successful_interactions"] = learning.get("successful_interactions", 0) + 1
    elif feedback_type == "negative":
        if "příliš dlouhé" in comment.lower():
            learning["preferred_length"] = "short"
        elif "příliš krátké" in comment.lower():
            learning["preferred_length"] = "long"

    _db_save_learning(user_id, learning)

    logger.info(f"Feedback from {user_id}: {feedback_type}")

    return jsonify({
        "success": True,
        "message": "Děkuji za zpětnou vazbu!",
        "timestamp": datetime.utcnow().isoformat()
    })

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT FUNCTIONS FOR CLAUDE_ROUTES
# ─────────────────────────────────────────────────────────────────────────────

def get_personalized_system_prompt(user_id: str, base_prompt: str) -> str:
    """Vrátit personalizovaný system prompt"""
    addition = build_personalized_prompt(user_id)
    return base_prompt + addition

def get_conversation_messages(user_id: str, limit: int = 10) -> list:
    """Vrátit konverzační historii pro Claude"""
    history = _db_load_history(user_id, limit=limit)
    return [{"role": m["role"], "content": m["content"]} for m in history]

def record_interaction(user_id: str, user_message: str, assistant_response: str):
    """Zaznamenat interakci"""
    _db_add_history(user_id, "user", user_message)
    _db_add_history(user_id, "assistant", assistant_response)

    # Update learning
    learning = _db_load_learning(user_id)
    topic = detect_topic(user_message)
    mood = detect_mood(user_message)

    topics = learning.get("topics", {})
    topics[topic] = topics.get(topic, 0) + 1
    learning["topics"] = topics
    learning["last_mood"] = mood
    learning["interaction_count"] = learning.get("interaction_count", 0) + 1
    learning["last_interaction"] = datetime.utcnow().isoformat()
    _db_save_learning(user_id, learning)

# Export
__all__ = [
    'memory_bp',
    'get_personalized_system_prompt',
    'get_conversation_messages',
    'record_interaction',
    'get_user_context'
]
