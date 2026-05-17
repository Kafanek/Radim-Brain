"""
🚨 EMERGENCY I18N — multi-language strings for safety-critical paths.

X21.41: closes the last deferred item from the X21.38-40 emergency audit.
Before this, every emergency message (proactive welfare call greetings,
crisis chat responses, SMS body, push title/body) was hardcoded Czech —
so an SK/PL/HU/EN-speaking senior in distress heard Czech they might
not understand at the worst possible moment.

Structure mirrors `claude_content_i18n.py` (X21.17): dict-of-dicts keyed
by lang, fallback to 'cs'. Two helpers:

    get_emergency(key, lang, **fmt) — looks up a string by key,
        formats with kwargs, falls back to Czech if unknown.
    get_voice_for_lang(lang) — returns the Azure Neural voice name
        for outbound Twilio TTS in that locale.

Languages: cs / sk / pl / hu / en (matches the rest of the app).
"""

SUPPORTED_LANGS = ('cs', 'sk', 'pl', 'hu', 'en')


def normalize_lang(lang):
    if not lang:
        return 'cs'
    raw = str(lang).split(',')[0].split('-')[0].strip().lower()
    return raw if raw in SUPPORTED_LANGS else 'cs'


# Azure Neural voice per language (same map as SpeechOrchestrator + X21.15).
# Used by twilio_voice_helpers when synthesizing outbound calls.
_AZURE_VOICE = {
    'cs': 'cs-CZ-AntoninNeural',
    'sk': 'sk-SK-LukasNeural',
    'pl': 'pl-PL-MarekNeural',
    'hu': 'hu-HU-TamasNeural',
    'en': 'en-US-GuyNeural',
}


def get_voice_for_lang(lang):
    return _AZURE_VOICE.get(normalize_lang(lang), _AZURE_VOICE['cs'])


# ─── Proactive welfare-call greetings (agent_loop._call_senior) ─────────
# Keyed by observation type. Fallback under '_default'.
CALL_GREETINGS = {
    'cs': {
        '_default':       'Dobrý den, tady Radim. Chtěl jsem se zeptat, jak se máte.',
        'c_trend_rising': 'Dobrý den, tady Radim. Všiml jsem si, že v posledních rozhovorech jste byl trochu napjatější. Chtěl jsem se zeptat, jestli je vše v pořádku.',
        'activity_drop':  'Dobrý den, tady Radim. Dnes jste byl méně aktivní než obvykle, tak jsem vám chtěl zavolat a zeptat se, jak se máte.',
        'vital_anomaly':  'Dobrý den, tady Radim. Zaznamenal jsem neobvyklou hodnotu vašich životních funkcí. Jak se cítíte?',
        'no_interaction': 'Dobrý den, tady Radim. Už jsme spolu delší dobu nemluvili, tak jsem vám chtěl zavolat. Jak se vám daří?',
    },
    'sk': {
        '_default':       'Dobrý deň, tu Radim. Chcel som sa opýtať, ako sa máte.',
        'c_trend_rising': 'Dobrý deň, tu Radim. Všimol som si, že v posledných rozhovoroch ste boli trochu napätejší. Chcel som sa opýtať, či je všetko v poriadku.',
        'activity_drop':  'Dobrý deň, tu Radim. Dnes ste boli menej aktívny ako zvyčajne, tak som vám chcel zavolať a opýtať sa, ako sa máte.',
        'vital_anomaly':  'Dobrý deň, tu Radim. Zaznamenal som nezvyčajnú hodnotu vašich životných funkcií. Ako sa cítite?',
        'no_interaction': 'Dobrý deň, tu Radim. Už sme spolu dlhšiu dobu nehovorili, tak som vám chcel zavolať. Ako sa vám darí?',
    },
    'pl': {
        '_default':       'Dzień dobry, tu Radim. Chciałem zapytać, jak się Pan/Pani miewa.',
        'c_trend_rising': 'Dzień dobry, tu Radim. Zauważyłem, że w ostatnich rozmowach był Pan/Pani trochę bardziej spięty. Chciałem zapytać, czy wszystko w porządku.',
        'activity_drop':  'Dzień dobry, tu Radim. Dzisiaj był Pan/Pani mniej aktywny niż zwykle, więc chciałem zadzwonić i zapytać, jak się Pan/Pani miewa.',
        'vital_anomaly':  'Dzień dobry, tu Radim. Zarejestrowałem nietypową wartość funkcji życiowych. Jak się Pan/Pani czuje?',
        'no_interaction': 'Dzień dobry, tu Radim. Już długo nie rozmawialiśmy, więc chciałem zadzwonić. Jak się Panu/Pani powodzi?',
    },
    'hu': {
        '_default':       'Jó napot kívánok, itt Radim. Csak meg akartam kérdezni, hogy van.',
        'c_trend_rising': 'Jó napot kívánok, itt Radim. Észrevettem, hogy az utóbbi beszélgetésekben kissé feszültebb volt. Meg akartam kérdezni, hogy minden rendben van-e.',
        'activity_drop':  'Jó napot kívánok, itt Radim. Ma kevésbé volt aktív, mint általában, ezért fel akartam hívni és megkérdezni, hogy van.',
        'vital_anomaly':  'Jó napot kívánok, itt Radim. Szokatlan értéket észleltem az életfunkcióiban. Hogy érzi magát?',
        'no_interaction': 'Jó napot kívánok, itt Radim. Régen beszéltünk, ezért fel akartam hívni. Hogy van?',
    },
    'en': {
        '_default':       'Hello, this is Radim. I just wanted to ask how you are doing.',
        'c_trend_rising': "Hello, this is Radim. I've noticed our recent chats felt a bit more tense. I wanted to check whether everything is alright.",
        'activity_drop':  "Hello, this is Radim. You've been less active than usual today, so I wanted to call and ask how you are.",
        'vital_anomaly':  'Hello, this is Radim. I noticed an unusual reading on your vital signs. How are you feeling?',
        'no_interaction': "Hello, this is Radim. We haven't spoken in a while, so I wanted to call and check in. How are you doing?",
    },
}


# ─── In-app crisis chat responses (radim_orchestrator) ──────────────────
CRISIS_CHAT = {
    'cs': {
        'breathing':   'Jsem tady s vámi, nikam neodcházím. Zkuste se posadit a dýchat pomalu — nádech nosem, výdech ústy. Bolí to stále stejně, nebo se to mění? Doporučuji zavolat záchrannou službu na 155. Chcete, abych zavolal?',
        'fall':        'Hlavně se nehýbejte a zůstaňte na místě. Bolí vás i hlava, nebo jen to místo kde jste spadl? Pro jistotu doporučuji zavolat na 155. Chcete, abych zavolal záchranku nebo rodinu?',
        'bleeding':    'Zůstaňte v klidu. Přitiskněte na ránu čistý hadřík a držte tlak. Je to velká rána? Doporučuji zavolat záchranku na 155.',
        '_default':    'Slyším, že vám není dobře, a jsem tady s vámi. Posaďte se nebo si lehněte. Můžete mi říct víc o tom, co cítíte? Pokud je to vážné, doporučuji zavolat na 155. Chcete, abych zavolal lékaře nebo rodinu?',
    },
    'sk': {
        'breathing':   'Som tu s vami, nikam neodchádzam. Skúste si sadnúť a dýchať pomaly — nádych nosom, výdych ústami. Bolí to stále rovnako, alebo sa to mení? Odporúčam zavolať záchrannú službu na 155. Chcete, aby som zavolal?',
        'fall':        'Hlavne sa nehýbte a zostaňte na mieste. Bolí vás aj hlava, alebo len miesto, kde ste spadli? Pre istotu odporúčam zavolať na 155. Chcete, aby som zavolal záchranku alebo rodinu?',
        'bleeding':    'Zostaňte pokojní. Pritlačte na ranu čistú handričku a držte tlak. Je to veľká rana? Odporúčam zavolať záchranku na 155.',
        '_default':    'Počujem, že vám nie je dobre, a som tu s vami. Sadnite si alebo si ľahnite. Môžete mi povedať viac o tom, čo cítite? Ak je to vážne, odporúčam zavolať na 155. Chcete, aby som zavolal lekára alebo rodinu?',
    },
    'pl': {
        'breathing':   'Jestem tu z Panem/Panią, nigdzie nie odchodzę. Proszę usiąść i oddychać powoli — wdech nosem, wydech ustami. Czy ból jest taki sam, czy się zmienia? Polecam zadzwonić na pogotowie 112. Chce Pan/Pani, żebym zadzwonił?',
        'fall':        'Proszę się nie ruszać i zostać na miejscu. Czy boli także głowa, czy tylko miejsce upadku? Dla pewności polecam zadzwonić na 112. Chce Pan/Pani, żebym zadzwonił po pogotowie lub rodzinę?',
        'bleeding':    'Proszę zachować spokój. Przyciśnij czysty materiał do rany i utrzymaj nacisk. Czy rana jest duża? Polecam zadzwonić na pogotowie 112.',
        '_default':    'Słyszę, że nie czuje się Pan/Pani dobrze, jestem tu z Panem/Panią. Proszę usiąść lub się położyć. Czy może Pan/Pani powiedzieć więcej o tym, co Pan/Pani czuje? Jeśli to poważne, polecam zadzwonić na 112. Chce Pan/Pani, żebym zadzwonił po lekarza lub rodzinę?',
    },
    'hu': {
        'breathing':   'Itt vagyok Önnel, sehova nem megyek. Próbáljon leülni és lassan lélegezni — orron be, szájon ki. A fájdalom ugyanolyan, vagy változik? Javaslom, hogy hívja a 112-t. Szeretné, ha hívnám?',
        'fall':        'Maradjon nyugton és a helyén. Fáj a feje is, vagy csak ahol elesett? Biztonság kedvéért javaslom a 112 hívását. Szeretné, hogy mentőt vagy családot hívjak?',
        'bleeding':    'Maradjon nyugodt. Nyomjon tiszta ruhát a sebre és tartsa rajta. Nagy a seb? Javaslom hívni a 112-t.',
        '_default':    'Hallom, hogy nem érzi jól magát, itt vagyok Önnel. Üljön le vagy feküdjön le. Tudna mondani többet arról, mit érez? Ha komoly, javaslom hívni a 112-t. Szeretné, hogy orvost vagy családot hívjak?',
    },
    'en': {
        'breathing':   "I'm here with you, I'm not going anywhere. Try to sit down and breathe slowly — in through the nose, out through the mouth. Is the pain the same or changing? I recommend calling emergency services. Would you like me to call?",
        'fall':        "Please don't move and stay where you are. Does your head hurt too, or just the spot where you fell? To be safe, I recommend calling emergency services. Would you like me to call for an ambulance or family?",
        'bleeding':    'Stay calm. Press a clean cloth to the wound and hold pressure. Is the wound large? I recommend calling emergency services.',
        '_default':    "I hear that you're not feeling well, and I'm here with you. Please sit down or lie down. Can you tell me more about what you feel? If it's serious, I recommend calling emergency services. Would you like me to call a doctor or family?",
    },
}


# ─── SMS body to caregivers (radim_helpers) ─────────────────────────────
# Format keys: {severity}, {senior_id}, {message_short}
# (NB: kwarg is `senior_id` not `user_id` to avoid collision with the
# get_emergency(user_id=...) parameter which controls lang lookup.)
SMS_BODY = {
    'cs': 'RADIM KRIZOVY ALERT [{severity}]: Uzivatel {senior_id} - {message_short}',
    'sk': 'RADIM KRIZOVY ALERT [{severity}]: Pouzivatel {senior_id} - {message_short}',
    'pl': 'RADIM ALERT KRYZYSOWY [{severity}]: Uzytkownik {senior_id} - {message_short}',
    'hu': 'RADIM VESZHELYZET [{severity}]: Felhasznalo {senior_id} - {message_short}',
    'en': 'RADIM CRISIS ALERT [{severity}]: User {senior_id} - {message_short}',
}


# ─── Push notification title / body (radim_helpers) ─────────────────────
PUSH_TITLE = {
    'cs': 'KRIZOVA SITUACE — {severity}',
    'sk': 'KRIZOVA SITUACIA — {severity}',
    'pl': 'SYTUACJA KRYZYSOWA — {severity}',
    'hu': 'VESZHELYZET — {severity}',
    'en': 'CRISIS — {severity}',
}

PUSH_BODY = {
    'cs': 'Uzivatel {senior_id} potrebuje pomoc: {message_short}',
    'sk': 'Pouzivatel {senior_id} potrebuje pomoc: {message_short}',
    'pl': 'Uzytkownik {senior_id} potrzebuje pomocy: {message_short}',
    'hu': 'A felhasznalo {senior_id} segitsegre szorul: {message_short}',
    'en': 'User {senior_id} needs help: {message_short}',
}


# ─── Resolver ───────────────────────────────────────────────────────────

def _resolve_user_lang(user_id):
    """Look up senior's preferred language from memory_profiles.data.lang.
    Returns 'cs' if unknown / DB unavailable / no profile."""
    if not user_id:
        return 'cs'
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        # Profile may store lang at top level OR under data.lang (legacy)
        lang = profile.get('lang') or profile.get('language')
        if not lang and isinstance(profile.get('data'), dict):
            lang = profile['data'].get('lang') or profile['data'].get('language')
        return normalize_lang(lang)
    except Exception:
        return 'cs'


def get_emergency(table_name, key, lang=None, user_id=None, **fmt):
    """Pull a string from one of the localized tables.

    Args:
        table_name: 'CALL_GREETINGS' | 'CRISIS_CHAT' | 'SMS_BODY' |
                    'PUSH_TITLE' | 'PUSH_BODY'
        key:        sub-key (observation type, scenario, or ignored for flat tables)
        lang:       explicit language; if None, resolved from user_id's profile
        user_id:    used to look up profile lang when lang is None
        fmt:        format kwargs (e.g. severity, message_short)

    Returns a formatted string, never None — falls back to Czech default
    if anything goes wrong so the safety path always has something to say.
    """
    tables = {
        'CALL_GREETINGS': CALL_GREETINGS,
        'CRISIS_CHAT':    CRISIS_CHAT,
        'SMS_BODY':       SMS_BODY,
        'PUSH_TITLE':     PUSH_TITLE,
        'PUSH_BODY':      PUSH_BODY,
    }
    table = tables.get(table_name)
    if not table:
        return ''

    if lang is None:
        lang = _resolve_user_lang(user_id)
    else:
        lang = normalize_lang(lang)

    bucket = table.get(lang) or table.get('cs') or {}

    # Flat string-table (SMS_BODY, PUSH_TITLE, PUSH_BODY) — bucket IS the string
    if isinstance(bucket, str):
        text = bucket
    else:
        # Nested dict (CALL_GREETINGS, CRISIS_CHAT) — look up key, fall to _default
        text = bucket.get(key) or bucket.get('_default') or ''
        if not text and lang != 'cs':
            cs_bucket = table.get('cs') or {}
            text = cs_bucket.get(key) or cs_bucket.get('_default') or ''

    if fmt and text:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text
