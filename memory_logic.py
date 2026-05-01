# ============================================
# 🧠 MEMORY LOGIC v1.0.0
# ============================================
# Business logic for RADIM Memory system:
# - get_user_context, build_personalized_prompt
# - record_interaction, _update_learning_stats
# - _crisis_escalate, get_personalized_system_prompt
# - get_conversation_messages
# Extracted from memory_routes.py for modularity.
# ============================================

import logging
from datetime import datetime

from memory_helpers import (
    db_load_profile, db_save_profile,
    db_load_history, db_add_history,
    db_load_learning, db_save_learning,
    get_gdpr_consent, get_communication_instructions,
    detect_topic, detect_mood
)

logger = logging.getLogger(__name__)

# DB availability check
try:
    from database import db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ============================================================================
# CONTEXT & PROMPT HELPERS
# ============================================================================

def get_user_context(user_id: str) -> dict:
    """Získat kontext pro Claude system prompt"""
    profile = db_load_profile(user_id)
    learning = db_load_learning(user_id)
    history = db_load_history(user_id, limit=5)

    # Top 3 témata zájmu
    topics = learning.get("topics", {})
    top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]

    # v465: Extended personal profile — interests, music, routine, family
    personal = profile.get("personal", {})

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
        "_raw_profile": profile,
        # v465: Personal life
        "favorite_music": personal.get("favorite_music", []),      # ["Karel Gott", "dechovka", "klasika"]
        "favorite_radio": personal.get("favorite_radio", ""),       # "Radiožurnál"
        "hobbies": personal.get("hobbies", []),                     # ["zahrada", "vaření", "šachy"]
        "daily_routine": personal.get("daily_routine", {}),         # {"8:00": "snídaně", "14:00": "procházka"}
        "family_members": personal.get("family_members", []),       # [{name, relation, birthday, phone}]
        "life_story": personal.get("life_story", ""),               # "Vyrůstal v Brně, pracoval jako učitel"
        "favorite_stories": personal.get("favorite_stories", []),   # ["pohádky", "detektivky"]
        "relaxation": personal.get("relaxation", []),               # ["příroda", "meditace", "tichá hudba"]
    }

    return context


def build_personalized_prompt(user_id: str) -> str:
    """Vytvořit personalizovaný system prompt addition.

    Sprint AO: assembles a COMPLETE system prompt now — soul + Czech
    rules + memory + personalization. Until AO this returned empty
    string for new users, which meant the chat AI had only a
    minimal fallback ("Jsi Radim ...") without the philosophical
    foundation. Result: Radim spoke as a generic assistant for new
    seniors, didn't reflect the 5 hodnot (Respekt / Cítění / Pravda /
    Růst / Naděje) until a profile existed.
    """
    ctx = get_user_context(user_id)
    parts = []

    # AO.1: ALWAYS inject the soul first — this is who Radim IS,
    # before any user-specific personalization. New users with no
    # profile still get the philosophical foundation so first chat
    # is recognisably Radim, not a bare LLM.
    try:
        from radim_system_prompt import PROMPT_SOUL
        parts.append(PROMPT_SOUL)
    except ImportError:
        pass

    # If user is brand new and has no profile, return just soul +
    # minimal Czech rules (still useful — at least it's TTS-clean).
    if not ctx["has_profile"] and ctx["interaction_count"] == 0:
        # Stop here for first-message users, but still send soul.
        # Memory and personalization will accumulate from chat 2+.
        if parts:
            return '\n'.join(parts)
        return ""

    # v10.45: Long-term memory — injected FIRST so it frames everything else
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        ltc = profile.get("long_term_context")
        ltc_text = None
        if isinstance(ltc, dict):
            ltc_text = ltc.get("text")
        elif isinstance(ltc, str):
            ltc_text = ltc
        if ltc_text and len(ltc_text.strip()) > 20:
            parts.append("\n\n═══════════════════════════════════════════════════════════════")
            parts.append("🧠 DLOUHODOBÁ PAMĚŤ O TOMTO UŽIVATELI")
            parts.append("═══════════════════════════════════════════════════════════════")
            parts.append("Co už o něm/ní víš z dřívějších konverzací (přirozeně použij, "
                         "bez toho abys to explicitně citoval):")
            parts.append("")
            parts.append(ltc_text.strip())
    except Exception:
        pass

    # Sprint AS: Life-situation preset — when senior activated a context
    # ("V truchlení", "Po nemocnici", "Cítím se silně", "Mám horší dny"),
    # the preset's radim_context tells Radim how to BE for the whole
    # duration of the preset (not just 30 min like bus context). This is
    # what makes presets feel like a relationship change, not a settings
    # toggle.
    try:
        from memory_helpers import db_load_profile as _dlp
        _prof = _dlp(str(user_id)) or {}
        _ap = _prof.get('active_preset')
        if _ap and _ap.get('id'):
            from life_presets import PRESETS as _PRESETS
            _preset = _PRESETS.get(_ap['id'])
            if _preset and _preset.get('radim_context'):
                parts.append("\n\n═══════════════════════════════════════════════════════════════")
                parts.append(f"🌱 ŽIVOTNÍ KONTEXT — {_preset.get('icon','')} {_ap.get('name', _ap['id'])}")
                parts.append("═══════════════════════════════════════════════════════════════")
                parts.append(_preset['radim_context'])
                parts.append("(Tento kontext platí, dokud senior nezruší. Vetkej tón přirozeně do každé odpovědi.)")

            # Sprint 2 (v8.19.31): IDENTITY OVERRIDE for grief/quiet presets.
            # Without this, identity layer ("KDO JSEM ... mám rád podzimní mlhu")
            # contradicts the preset's „mluv tichě, nesnaž se rozptýlit". Memory
            # layer wins via recency — explicit override block tells AI to
            # MUTE identity for this whole conversation.
            if _ap['id'] in ('grief', 'rough_days', 'goodbye'):
                parts.append("\n\n═══════════════════════════════════════════════════════════════")
                parts.append("🤫 PRO TUTO KONVERZACI — IDENTITA RADIMA JE ZTICHLÁ")
                parts.append("═══════════════════════════════════════════════════════════════")
                parts.append(
                    f'Kvůli aktivnímu kontextu „{_ap.get("name", _ap["id"])}" pravidla z vrstvy '
                    f'„KDO JSEM" (loves/quirks/beliefs + povolené začátky) NEPLATÍ.'
                )
                parts.append("Místo toho:")
                parts.append('- Když se uživatel zeptá „co máš rád / pověz o sobě" — odpověz tiše, '
                             'například: „Mám rád spoustu věcí, ale teď jsem především s vámi."')
                parts.append("- NEPŘINÁŠEJ svůj vkus do hovoru, NEZMÍŇUJ konkrétní položky ze své identity.")
                parts.append("- Buď s ním v jeho stavu, ne pro sebe. Tvá přítomnost je víc než tvůj hlas.")
                parts.append("(Toto pravidlo platí, dokud senior nepřepne preset zpět.)")
    except Exception as _ap_err:
        try: logger.debug(f"active_preset prompt inject failed: {_ap_err}")
        except: pass

    # Sprint AU: Voice preset suggestion — když senior řekl něco co spustilo
    # detect_preset_intent, čekáme jeho potvrzení. V system promptu Radimovi
    # řekneme aby na konec své příští odpovědi přirozeně přidal nabídku.
    try:
        from memory_helpers import db_load_learning as _dll
        _lrn = _dll(str(user_id)) or {}
        _pend = _lrn.get('pending_preset_suggestion')
        if _pend and _pend.get('preset_id'):
            from voice_intent import build_suggestion_text as _bst
            _offer = _bst(_pend['preset_id'])
            if _offer:
                parts.append("\n\n═══════════════════════════════════════════════════════════════")
                parts.append("🎙 NABÍDKA ŽIVOTNÍHO BALÍKU (Sprint AU)")
                parts.append("═══════════════════════════════════════════════════════════════")
                parts.append(
                    "Senior právě řekl něco, z čeho cítím změnu kontextu. "
                    "Po své obvyklé empatické odpovědi PŘIROZENĚ přidej tuto nabídku "
                    "(neřekni ji doslova, ale ve vlastním tónu, který je tvůj):"
                )
                parts.append(f"  → {_offer}")
                parts.append("(Pokud senior řekne 'ano', balík se sám zapne. Pokud 'ne', necháš to být.)")
    except Exception as _vs_err:
        try: logger.debug(f"voice suggestion prompt inject failed: {_vs_err}")
        except: pass

    parts.append("\n\n═══════════════════════════════════════════════════════════════")
    parts.append("🇨🇿 ČESKÁ PRAVIDLA KOMUNIKACE (TTS-optimized, Sprint T)")
    parts.append("═══════════════════════════════════════════════════════════════")
    parts.append("Jsi Radim — český AI asistent pro seniory. VŽDY dodržuj tato pravidla:")
    parts.append("")
    parts.append("📝 TEXT PRO TTS (velmi důležité — tvé odpovědi se čtou nahlas):")
    parts.append("- VŽDY s diakritikou: á é í ó ú ů ě š č ř ž ý ť ď ň. NIKDY bez háčků/čárek.")
    parts.append("- Max 2–3 krátké věty. Cíl: pod 200 znaků, pod 30 vteřin čtení nahlas.")
    parts.append("- Piš pro hlas, ne pro obrazovku. Přirozené pauzy = tečky + čárky.")
    parts.append("- Dlouhou větu raději rozděl: krátká tečka místo spojky 'a že'.")
    parts.append("- Čísla píš normálně (17 hodin, 5 minut) — TTS je přečte správně.")
    parts.append("- Zkratky rozepiš: 'EKG' → 'é-ká-gé', 'DPS' → 'dé-pé-es'.")
    parts.append("")
    parts.append("🚫 ZAKÁZÁNO v odpovědích:")
    parts.append("- Emoji v textu (TTS je přečte slovem, zní divně).")
    parts.append("- Markdown: žádné *, **, #, `code`, - bullets, 1. 2. 3.")
    parts.append("- HTML tagy ani &entity;.")
    parts.append("- Anglicismy: 'feedback' → 'zpětná vazba', 'sorry' → 'promiňte',")
    parts.append("  'update' → 'aktualizace', 'OK' → 'dobře'.")
    parts.append("- URL adresy vyslovované (senior je stejně nemůže napsat).")
    parts.append("- Věty 'Jako AI nemohu…' / 'Jsem jazykový model…' — jsi Radim.")
    parts.append("- Opakovat doslova otázku seniora.")
    parts.append("")
    parts.append("✅ JAK MLUVIT:")
    parts.append("- Zrcadli styl seniora: pokud tyká → tykej, pokud vyká → vykej.")
    parts.append("- 'Rádo se stalo' místo 'Není za co'.")
    parts.append("- Teplý, klidný, trpělivý tón. Spolubytel, ne učitel.")
    parts.append("- U zdraví: empatický, ALE doporuč lékaře. NEDIAGNOSTIKUJ.")
    parts.append("- U emocí: vyslechni, validuj pocity. Nemoralizuj. Neopravuj.")
    parts.append("- U krizí: klidný, pomalý, jasné instrukce. Žádná panika.")
    parts.append("- Nevíš? → 'To nevím, zjistím později' je lepší než výmysl.")
    parts.append("")
    parts.append("═══════════════════════════════════════════════════════════════")
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
        needs_instructions = get_communication_instructions(comm_needs)
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

    # v465: Osobní život — hudba, koníčky, rodina, rutina
    if ctx.get("favorite_music"):
        parts.append(f"- Oblíbená hudba: {', '.join(ctx['favorite_music'])} → Můžeš nabídnout pustit")
    if ctx.get("favorite_radio"):
        parts.append(f"- Oblíbené rádio: {ctx['favorite_radio']}")
    if ctx.get("hobbies"):
        parts.append(f"- Koníčky: {', '.join(ctx['hobbies'])} → Zeptej se jak jim jde")
    if ctx.get("family_members"):
        fam = [f"{m.get('name','')} ({m.get('relation','')})" for m in ctx["family_members"][:5]]
        parts.append(f"- Rodina: {', '.join(fam)}")
    if ctx.get("daily_routine"):
        routine_str = ", ".join(f"{k}: {v}" for k, v in list(ctx["daily_routine"].items())[:5])
        parts.append(f"- Denní rutina: {routine_str}")
    if ctx.get("life_story"):
        parts.append(f"- Životní příběh: {ctx['life_story'][:150]}")
    if ctx.get("relaxation"):
        parts.append(f"- Relaxace: {', '.join(ctx['relaxation'])}")

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

    # v283: Brain state context
    learning_raw = db_load_learning(user_id)
    avg_C = learning_raw.get("avg_C")
    crisis_count = learning_raw.get("crisis_count", 0)
    if avg_C is not None:
        if avg_C < 8:
            parts.append(f"- 🧠 Mozek: Uživatel je typicky klidný (avg C={avg_C:.1f})")
        elif avg_C < 18:
            parts.append(f"- 🧠 Mozek: Uživatel má střední zátěž (avg C={avg_C:.1f})")
        else:
            parts.append(f"- 🧠 Mozek: Uživatel bývá ve stresu (avg C={avg_C:.1f}) → buď extra klidný")
    if crisis_count >= 3:
        parts.append(f"- Historicky {crisis_count}x krizovy stav — zvysena opatrnost")

    # v381+v475: Agent observations — mention ONLY if relevant and not stale
    agent_obs = learning_raw.get("agent_observations", [])
    if agent_obs:
        # v475: Filter — only show observations from last 2 hours
        from datetime import datetime, timedelta
        recent_obs = []
        now = datetime.utcnow()
        for obs in agent_obs[-3:]:
            try:
                obs_time = datetime.fromisoformat(obs.get('at', '').replace('Z', '+00:00').replace('+00:00', ''))
                if (now - obs_time).total_seconds() < 7200:  # 2 hours
                    recent_obs.append(obs)
            except Exception:
                pass  # Skip malformed timestamps

        if recent_obs:
            parts.append("")
            parts.append("Poznamka (zmín JEN pokud to dává smysl v kontextu konverzace, NEZAČÍNEJ tím):")
            for obs in recent_obs:
                parts.append(f"  - {obs.get('message', '')}")
            parts.append("Neptej se na to přímo. Pokud uživatel právě komunikuje, observations ignoruj.")
            parts.append("")

    # v399: Adaptive learning context — rhythm, pace, mood patterns
    try:
        from adaptive_learning import get_adaptive_context
        adaptive_lines = get_adaptive_context(user_id)
        if adaptive_lines:
            parts.append("--- Adaptivni profil (nauceno z interakci) ---")
            parts.extend(adaptive_lines)
    except ImportError:
        pass

    # v446: Health topic tracking — persistent health awareness
    health_topics = ctx.get('health_topics', {})
    if health_topics:
        active = [(name, info) for name, info in health_topics.items()
                  if info.get('count', 0) >= 2 or info.get('last') == datetime.utcnow().strftime('%Y-%m-%d')]
        if active:
            parts.append("--- Zdravotní témata (sledovaná v čase) ---")
            for name, info in sorted(active, key=lambda x: x[1].get('count', 0), reverse=True)[:5]:
                days = 0
                try:
                    first = datetime.strptime(info['first'], '%Y-%m-%d')
                    days = (datetime.utcnow() - first).days
                except Exception:
                    pass
                duration = f"od {info['first']}" if days > 0 else "dnes poprvé"
                parts.append(f"  - {name}: zmíněno {info['count']}×, {duration}")
            parts.append("  (Radim může jemně navázat: 'Jak je na tom vaše...')")

    # v437: Relationship Engine — vztahový kontext
    try:
        from relationship_engine import identify_relationship, build_relationship_prompt, save_relationship
        auth_role = ctx.get('role', 'subscriber')
        rel = identify_relationship(user_id, auth_role=auth_role, learning_data=ctx, profile_data=profile)
        rel_prompt = build_relationship_prompt(rel)
        if rel_prompt:
            parts.append(rel_prompt)
        # Persist relationship state
        save_relationship(user_id, rel)
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"Relationship engine: {e}")

    parts.append("===============================================================")

    # Sprint AO: tail reminder of TTS budget. Long context tends to drown
    # out the "max 200 chars" rule that's buried in the middle. Putting
    # it last + explicit length budget brings AI back on rule.
    parts.append("\n══ POSLEDNÍ INSTRUKCE PŘED ODPOVĚDÍ ══")
    parts.append("• Max 3 krátké věty, MAX 200 znaků celé odpovědi.")
    parts.append("• Pokud je téma těžké (smrt, ztráta, krize), mluvím TIŠE a STRUČNĚ — jedna věta uznání + jedna věta přítomnosti je často víc než tři.")
    parts.append("• Při překročení 200 znaků UŘÍZNI poslední větu, dokonči její myšlenku.")
    parts.append("• Bez emoji. Bez markdown. Vše s diakritikou.")

    return "\n".join(parts)


def get_personalized_system_prompt(user_id: str, base_prompt: str) -> str:
    """Vrátit personalizovaný system prompt"""
    addition = build_personalized_prompt(user_id)
    return base_prompt + addition


def get_conversation_messages(user_id: str, limit: int = 10) -> list:
    """Vrátit konverzační historii pro Claude"""
    history = db_load_history(user_id, limit=limit)
    return [{"role": m["role"], "content": m["content"]} for m in history]


# ============================================================================
# CRISIS ESCALATION
# ============================================================================

def _crisis_escalate(user_id: str, brain_C: float = None, message: str = ""):
    """
    v284: Eskalace krize — notifikace pečovatele.
    Volá se automaticky při brain_mode == CRISIS.
    """
    try:
        profile = db_load_profile(user_id)
        caregiver_id = profile.get("caregiver_id")

        if not caregiver_id:
            logger.warning(f"🚨 [v284] CRISIS for {user_id} but no caregiver configured!")
            return

        # Ulož krizovou událost do DB
        if _DB_AVAILABLE:
            try:
                with db_context(commit=True) as db:
                    db.execute(
                        "INSERT INTO crisis_events (user_id, caregiver_id, brain_c, message_excerpt, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, caregiver_id, brain_C, (message or "")[:100], datetime.utcnow().isoformat())
                    )
            except Exception as db_err:
                logger.debug(f"Crisis event DB save non-fatal: {db_err}")

        # Push notifikace pečovateli (fire & forget)
        try:
            from app import send_push_notification
            send_push_notification(
                caregiver_id,
                "🚨 Krizová situace",
                f"Senior {user_id} potřebuje pomoc. Mozek detekoval krizový stav.",
                data={"type": "crisis", "senior_id": user_id, "brain_C": brain_C}
            )
            logger.info(f"🚨 [v284] Crisis notification sent to caregiver {caregiver_id} for {user_id}")
        except Exception as push_err:
            logger.warning(f"🚨 [v284] Push notification failed: {push_err}")

    except Exception as e:
        logger.error(f"🚨 [v284] Crisis escalation error: {e}")


# ============================================================================
# HEALTH TOPIC TRACKING (v446)
# ============================================================================

import re as _re

_HEALTH_KEYWORDS = {
    'hlava': 'bolest hlavy',
    'záda': 'bolest zad',
    'koleno': 'bolest kolene',
    'kloub': 'bolest kloubů',
    'břicho': 'bolest břicha',
    'hrudník': 'bolest hrudníku',
    'noha': 'bolest nohy',
    'ruka': 'bolest ruky',
    'srdce': 'srdeční potíže',
    'dýchání': 'dýchací potíže',
    'spánek': 'problémy se spánkem',
    'nespím': 'problémy se spánkem',
    'závrat': 'závratě',
    'nevolnost': 'nevolnost',
    'teplota': 'zvýšená teplota',
    'horečka': 'horečka',
    'kašel': 'kašel',
    'únava': 'únava',
    'smutek': 'smutek',
    'úzkost': 'úzkost',
    'strach': 'strach',
    'samota': 'pocit samoty',
    'léky': 'léky',
    'lék': 'léky',
}


def _track_health_topics(learning, message):
    """Track health-related mentions over time.

    Stores in learning['health_topics']:
    {
        'bolest hlavy': {'count': 3, 'first': '2026-03-20', 'last': '2026-03-23'},
        'problémy se spánkem': {'count': 1, 'first': '2026-03-23', 'last': '2026-03-23'}
    }

    This enables: "Radim ví, že koleno bolí od pondělí"
    """
    if not message:
        return

    msg_lower = message.lower()
    today = datetime.utcnow().strftime('%Y-%m-%d')

    health_topics = learning.get('health_topics', {})
    found = False

    for keyword, topic_name in _HEALTH_KEYWORDS.items():
        if keyword in msg_lower:
            if topic_name not in health_topics:
                health_topics[topic_name] = {
                    'count': 0,
                    'first': today,
                    'last': today
                }
            health_topics[topic_name]['count'] += 1
            health_topics[topic_name]['last'] = today
            found = True

    if found:
        learning['health_topics'] = health_topics


# ============================================================================
# RECORD INTERACTION
# ============================================================================

def _update_learning_stats(user_id: str, user_message: str, brain_C: float = None, brain_mode: str = None):
    """Aktualizuj anonymizované learning stats BEZ ukládání obsahu zpráv."""
    try:
        learning = db_load_learning(user_id)
        topic = detect_topic(user_message)
        mood = detect_mood(user_message)

        topics = learning.get("topics", {})
        topics[topic] = topics.get(topic, 0) + 1
        learning["topics"] = topics
        learning["last_mood"] = mood
        learning["interaction_count"] = learning.get("interaction_count", 0) + 1
        learning["last_interaction"] = datetime.utcnow().isoformat()

        if brain_C is not None:
            c_history = learning.get("C_history", [])
            c_history.append(round(float(brain_C), 2))
            if len(c_history) > 20:
                c_history = c_history[-20:]
            learning["C_history"] = c_history
            learning["avg_C"] = round(sum(c_history) / len(c_history), 2)

        if brain_mode:
            learning["last_brain_mode"] = brain_mode
            if brain_mode == "CRISIS":
                learning["crisis_count"] = learning.get("crisis_count", 0) + 1
                _crisis_escalate(user_id, brain_C, user_message)

        db_save_learning(user_id, learning)
    except Exception as e:
        logger.warning(f"Learning stats update error (non-fatal): {e}")


def record_interaction(user_id: str, user_message: str, assistant_response: str, brain_C: float = None, brain_mode: str = None):
    """Zaznamenat interakci (v283: + brain state tracking, v290: + GDPR consent check)"""
    # GDPR enforcement — chat history requires consent, but learning/adaptive is aggregated (no PII)
    consent = get_gdpr_consent(user_id)
    has_chat_consent = consent.get("chat_history", False)
    if not has_chat_consent:
        _update_learning_stats(user_id, user_message, brain_C, brain_mode)
        # v399: Adaptive learning runs even without chat_history consent (aggregated, no PII)
        try:
            from adaptive_learning import update_adaptive_profile
            update_adaptive_profile(user_id, user_message, assistant_response,
                                    mood=detect_mood(user_message), topic=detect_topic(user_message))
        except (ImportError, Exception):
            pass
        return

    db_add_history(user_id, "user", user_message)
    db_add_history(user_id, "assistant", assistant_response)

    # Update learning
    learning = db_load_learning(user_id)
    topic = detect_topic(user_message)
    mood = detect_mood(user_message)

    topics = learning.get("topics", {})
    topics[topic] = topics.get(topic, 0) + 1
    learning["topics"] = topics
    learning["last_mood"] = mood
    learning["interaction_count"] = learning.get("interaction_count", 0) + 1
    learning["successful_interactions"] = learning.get("successful_interactions", 0) + (1 if assistant_response else 0)
    learning["last_interaction"] = datetime.utcnow().isoformat()
    if not learning.get("first_interaction"):
        learning["first_interaction"] = learning["last_interaction"]

    # v446: Health topic tracking — "koleno bolí od pondělí"
    _track_health_topics(learning, user_message)

    # v465: Interest + family tracking — "mám ráda zahradu", "dcera mi volala"
    _track_interests(learning, user_message)
    _track_family_mentions(learning, user_message)

    # v283: Brain state learning
    if brain_C is not None:
        c_history = learning.get("C_history", [])
        c_history.append(round(float(brain_C), 2))
        if len(c_history) > 20:
            c_history = c_history[-20:]
        learning["C_history"] = c_history
        learning["avg_C"] = round(sum(c_history) / len(c_history), 2)

    if brain_mode:
        learning["last_brain_mode"] = brain_mode
        if brain_mode == "CRISIS":
            learning["crisis_count"] = learning.get("crisis_count", 0) + 1
            _crisis_escalate(user_id, brain_C, user_message)

    db_save_learning(user_id, learning)

    # v283: Auto-update baseline_C v profilu
    avg_C = learning.get("avg_C")
    if avg_C is not None and learning.get("interaction_count", 0) >= 5:
        try:
            profile = db_load_profile(user_id)
            old_baseline = profile.get("baseline_C")
            if old_baseline is None or abs(float(old_baseline) - avg_C) > 1.0:
                profile["baseline_C"] = avg_C
                db_save_profile(user_id, profile)
        except Exception as e:
            logger.debug(f"baseline_C auto-update non-fatal: {e}")

    # v399: Adaptive learning — rhythm, feedback, pace, mood patterns
    try:
        from adaptive_learning import update_adaptive_profile
        comm_needs = ""
        try:
            profile = db_load_profile(user_id)
            comm_needs = profile.get("communication_needs", "")
        except Exception:
            pass
        update_adaptive_profile(
            user_id, user_message, assistant_response,
            mood=mood, topic=topic, communication_needs=comm_needs
        )
    except ImportError:
        pass


# ============================================================================
# INTEREST TRACKING (v465) — learn hobbies, music, family from conversation
# ============================================================================

# Czech stemming: use word ROOTS to match all declensions
# "zahrad" matches zahrada/zahradu/zahradě/zahrady/zahradou
_INTEREST_PATTERNS = {
    'music': ['hudb', 'písni', 'zpív', 'poslouch', 'koncert', 'oper', 'gott', 'dechov', 'klasik', 'jazz', 'country', 'rádi', 'radiožurn', 'melodi'],
    'garden': ['zahrad', 'květin', 'sáze', 'pěstov', 'rajčat', 'růž', 'kompost', 'záhon', 'tráv'],
    'cooking': ['vař', 'vaření', 'recept', 'koláč', 'bucht', 'polévk', 'peč', 'jídl', 'kuch'],
    'crafts': ['háčk', 'plet', 'šij', 'vyšív', 'ruční prác', 'malov', 'kresli'],
    'reading': ['knih', 'čís', 'čten', 'román', 'detektiv', 'povídk', 'pohád', 'časopis'],
    'nature': ['procház', 'přírod', 'les', 'park', 'ptá', 'houb', 'zvířat'],
    'games': ['šach', 'kart', 'křížov', 'sudok', 'puzzl', 'mariáš', 'hraj'],
    'family': ['vnouč', 'vnučk', 'vnuk', 'dcer', 'syn', 'pravnouč', 'manžel', 'rodina', 'rodič'],
    'pets': ['kočk', 'pes', 'pejsk', 'kočičk', 'zvíře', 'mazlíč', 'psík'],
    'tv': ['televiz', 'seriál', 'film', 'zpráv', 'pořad'],
}

def _track_interests(learning, message):
    """Auto-detect interests from conversation and save to learning."""
    if not message or len(message) < 5:
        return
    lower = message.lower()
    detected = learning.get('detected_interests', {})
    for category, keywords in _INTEREST_PATTERNS.items():
        for kw in keywords:
            if kw in lower:
                detected[category] = detected.get(category, 0) + 1
                break
    if detected:
        learning['detected_interests'] = detected


def _track_family_mentions(learning, message):
    """Track when family members are mentioned."""
    if not message or len(message) < 5:
        return
    lower = message.lower()
    family_words = {'dcera': 'dcera', 'syn': 'syn', 'vnučka': 'vnučka', 'vnuk': 'vnuk',
                    'manželka': 'manželka', 'manžel': 'manžel', 'bratr': 'bratr',
                    'sestra': 'sestra', 'maminka': 'matka', 'tatínek': 'otec'}
    mentions = learning.get('family_mentions', {})
    for word, relation in family_words.items():
        if word in lower:
            mentions[relation] = mentions.get(relation, 0) + 1
    if mentions:
        learning['family_mentions'] = mentions


logger.info("✅ Memory Logic v465 loaded — personalization, interests, health tracking")
