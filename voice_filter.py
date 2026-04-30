"""
🎙️ RADIM VOICE FILTER v2.0
============================
Creates Radim's distinctive warm voice using advanced Azure SSML features.

Instead of audio post-processing (which requires ffmpeg), we use Azure's
built-in voice styling capabilities:
- mstts:express-as: emotion style + degree
- prosody: rate, pitch, volume per brain mode
- break: φ-proportioned pauses between sentences
- emphasis: key words get gentle emphasis

Mode-adaptive: HARMONY/ALERT/CRISIS each have distinct voice profiles.
Falls back gracefully if Azure doesn't support a feature.
"""

import re
import logging
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# ============================================================================
# RADIM VOICE PROFILES (Azure SSML parameters)
# ============================================================================

VOICE_PROFILES = {
    # ── Brain-state modes ──
    # v10.22: PŘIROZENÝ HLAS — Antonín má vlastní intonaci, contour ji přepisuje
    # Proto: contour POUZE pro SINGING (písně). Vše ostatní = Antonínova přirozená řeč
    # + rate/pitch/pauzy pro charakter. Jednodušší = přirozenější.
    "HARMONY": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-5%",           # mírně pomalejší než přirozený
        "pitch": "+0%",          # v10.23: neutrální přirozený
        "volume": "loud",
        "pause_ms": 500,         # přirozené pauzy
        "emphasis": False,
        # NO contour — Antonínova vlastní intonace je nejpřirozenější
    },
    "ALERT": {
        "style": "empathetic",
        "styledegree": "1.5",
        "rate": "-15%",          # pomalejší pro pochopení
        "pitch": "+0%",          # v10.23: mírně hlubší
        "volume": "loud",
        "pause_ms": 800,
        "emphasis": True,
    },
    "CRISIS": {
        # Bug-fix (TTS audit #13): cs-CZ-AntoninNeural NEPODPORUJE 'calm' style.
        # Azure docs (https://learn.microsoft.com/azure/ai-services/speech-service/
        # language-support#prebuilt-neural-voices) — Czech neural voices podporují
        # jen 'friendly' a 'empathetic'. 'calm' Azure ignoroval = CRISIS zněl
        # jako default voice (ne uklidňující jako jsme zamýšleli).
        # Fix: 'empathetic' se styledegree 2.0 (max) je v Czech repertoáru
        # nejblíž pocitu klidného uklidnění. Plus pomalejší rate -20% +
        # delší pauzy 1200ms drží tu uklidňující kvalitu.
        "style": "empathetic",
        "styledegree": "2.0",
        "rate": "-20%",          # výrazně pomalejší
        "pitch": "+0%",          # v10.23: hlubší pro klid
        "volume": "x-loud",
        "pause_ms": 1200,        # dlouhé pauzy
        "emphasis": True,
    },
    "POETRY": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-10%",          # recitační tempo
        "pitch": "+0%",          # v10.23: neutrální
        "volume": "loud",
        "pause_ms": 800,         # dramatické pauzy
        "emphasis": False,
        "poetry_mode": True,
    },
    "NARRATION": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-12%",          # vypravěčské tempo
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 700,
        "emphasis": False,
    },
    "NEWS": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-3%",           # skoro přirozené
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 400,
        "emphasis": False,
    },
    "EDUCATION": {
        "style": "friendly",
        "styledegree": "1.0",
        "rate": "-12%",          # pomalejší pro učení
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 700,
        "emphasis": True,
    },
    # v10.40: FESTIVE — sváteční pozdrav, jmeniny, narozeniny
    # Mírně pomalejší než HARMONY, s teplejším tónem a delší pauzou po jmenu
    "FESTIVE": {
        "style": "friendly",
        "styledegree": "2.0",    # maximální "friendly" styling
        "rate": "-8%",           # mírně pomaleji než běžný chat
        "pitch": "+0%",          # Antonínův přirozený tón
        "volume": "loud",
        "pause_ms": 600,         # φ * 371 ≈ 600 — teplejší rytmus
        "emphasis": True,        # zdůrazní slova jako "jmeniny", "krásný"
    },
    "SINGING": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-15%",          # v10.22: mezi řečí a zpěvem — hravé tempo
        "pitch": "+0%",          # v10.23: neutrální
        "volume": "loud",
        "pause_ms": 400,
        "emphasis": False,
        "contour": "song",       # melodie z databáze písní — Radim si hraje s jazykem
        "contour_scale": 1.5,    # v10.22: 1.5× intenzivnější melodie
    },
    "RHYTHMIC": {
        "style": "friendly",
        "styledegree": "2.0",
        "rate": "-8%",
        "pitch": "+0%",
        "volume": "loud",
        "pause_ms": 500,
        "emphasis": False,
        # NO contour — Antonínova přirozená intonace + pomalejší tempo
    },
}

# Words that should get gentle emphasis in ALERT/CRISIS
EMPHASIS_WORDS = {
    # Uklidnění
    "klid", "klidně", "pomoc", "pomohu", "dýchejte", "nadechněte",
    "vydechněte", "zavolám", "jste", "bezpečí", "poradím", "společně",
    # Zdraví
    "rodina", "doktor", "lékař", "záchranku", "nemocnice",
    # Čísla — tísňová volání
    "155", "158", "112",
    # Léky
    "léky", "lék", "tabletu", "prášek",
}

# v10.20 + v10.54: Czech pronunciation fixes for Azure cs-CZ-AntoninNeural
# Applied AFTER xml_escape so SSML tags are preserved.
# Two categories:
#   A. Native Czech words where Azure mispronounces /x/ as /tʃ/ or ignores /ɲ/
#   B. Foreign words and brand names that Antonín mangles with Czech phonetics
_CZECH_PHONEME_FIXES = [
    # (pattern, ipa, display_override)  — display_override=None uses matched word

    # ── Native Czech "ch" /x/ fixes (breathing cues for exercises) ──
    (r'\b[Dd]ýchejte\b',   'diːxɛjtɛ',  None),
    (r'\b[Nn]adechněte\b', 'nadɛxɲɛtɛ', None),
    (r'\b[Vv]ydechněte\b', 'vidɛxɲɛtɛ', None),
    (r'\b[Dd]ýchat\b',     'diːxat',    None),
    (r'\b[Dd]ýchání\b',    'diːxaɲiː',  None),
    (r'\b[Dd]ýchej\b',     'diːxɛj',    None),

    # ── Brands & tech terms (English-origin, common in RADIM context) ──
    # NOTE: "Radim" is handled separately via <sub alias="Raďim"> in
    # _fix_czech_pronunciation() — IPA phoneme is unreliable for the
    # palatalized "di" cluster (Azure was rendering it as hard "Radym").
    (r'\bChatGPT\b',       'tʃɛtdʒiːpiːtiː', 'ChatGPT'),
    (r'\b[Gg]emini\b',     'ɡɛmɪnaɪ',    'Gemini'),
    (r'\b[Cc][Oo][Vv][Ii][Dd](-19)?\b', 'kɔvɪt',  'COVID'),
    (r'\b[Ee]-?mail\b',    'iːmɛjl',     'e-mail'),
    (r'\b[Ww]i-?[Ff]i\b',  'vajfaj',     'Wi-Fi'),
    (r'\b[Ii][Pp]hone\b',  'ajfoʊn',     'iPhone'),
    (r'\b[Ii][Pp]ad\b',    'ajpɛt',      'iPad'),
    (r'\b[Aa]ndroid\b',    'ɛndrɔjd',    'Android'),
    (r'\b[Bb]luetooth\b',  'bluːtuːθ',   'Bluetooth'),
    (r'\b[Yy]ou[Tt]ube\b', 'juːtjuːp',   'YouTube'),
    (r'\b[Ff]acebook\b',   'fɛjsbʊk',    'Facebook'),
    (r'\b[Ww]hats[Aa]pp\b', 'vɔtsɛp',    'WhatsApp'),
    (r'\b[Gg]oogle\b',     'ɡuːɡl',      'Google'),
    (r'\b[Mm]icrosoft\b',  'majkrosoft', 'Microsoft'),
    (r'\b[Aa]pple\b',      'ɛpl',        'Apple'),
    (r'\b[Tt]he\s',        'ðə ',        'the '),    # article in loan phrases
    (r'\b[Oo][Kk]\b',      'oʊkɛj',      'OK'),
    (r'\b[Ss][Mm][Ss]\b',  'ɛsɛmɛs',     'SMS'),
    (r'\b[Pp][Dd][Ff]\b',  'peːdeːef',   'PDF'),
    (r'\b[Uu][Ss][Aa]\b',  'uːɛsaː',     'USA'),
    (r'\b[Ee][Uu]\b',      'eːuː',       'EU'),

    # ── V4 / Visegrad conference terms that trip up Azure ──
    (r'\b[Vv]isegrád(ský|ská|ské|ského|skému|ským|ských)?\b',
                           'vɪsɛɡraːt', None),
    (r'\bV4\b',            'veːʃtiːrʒɪ', 'V4'),

    # ── v453: Tech / social brands (newer ones missing from original list) ──
    (r'\b[Tt]ik[Tt]ok\b',  'tɪktɔk',     'TikTok'),
    (r'\b[Ii]nstagram\b',  'instaɡram',  'Instagram'),
    (r'\b[Ll]inked[Ii]n\b', 'lɪŋktɪn',   'LinkedIn'),
    (r'\b[Ss]potify\b',    'spɔtɪfaj',   'Spotify'),
    (r'\b[Nn]etflix\b',    'nɛtflɪks',   'Netflix'),
    (r'\b[Ss]kype\b',      'skajp',      'Skype'),
    (r'\b[Zz]oom\b',       'zuːm',       'Zoom'),
    (r'\b[Tt]eams\b',      'tiːms',      'Teams'),
    (r'\b[Gg]mail\b',      'dʒiːmɛjl',   'Gmail'),
    (r'\b[Yy]ahoo\b',      'jahuː',      'Yahoo'),
    (r'\b[Aa]i\b',         'eːiː',       'AI'),
    (r'\b[Ee][Vv]\b',      'iːviː',      'EV'),     # electric vehicle
    (r'\b[Cc][Tt]\b',      'tseːteː',    'CT'),
    (r'\b[Mm][Rr]\b',      'ɛmɛr',       'MR'),     # magnetická rezonance
    (r'\b[Ee][Kk][Gg]\b',  'eːkaːgeː',   'EKG'),
    (r'\b[Hh][Ii][Vv]\b',  'haːiːveː',   'HIV'),
    (r'\b[Dd][Nn][Aa]\b',  'deːenaː',    'DNA'),
    (r'\b[Tt][Vv]\b',      'teːveː',     'TV'),
]


# ── v453: Smart number/date reader ──────────────────────────────────────────
# Standard Azure SSML <say-as> tags are MORE reliable than IPA for numbers,
# dates, and times because Azure's Czech morphology engine handles inflection
# (pětadvacátého prosince vs dvacátého pátého dvanáctého).
#
# Rules below are applied BEFORE the phoneme list so the say-as text doesn't
# get accidentally re-tagged. Order matters — most specific patterns first.

# Czech tísňové linky — must be read digit-by-digit so seniors don't lose
# them under stress (e.g. "jedna pět pět" not "sto padesát pět").
_EMERGENCY_NUMBERS = {'112', '150', '155', '156', '158'}


def _apply_smart_say_as(text):
    """Wrap numbers/dates/times in <say-as> so Azure reads them naturally.

    Patterns:
      - +420 XXX XXX XXX  → digits (telephone)
      - DD.MM.YYYY        → date d.m.y
      - DD.MM.            → date d.m (year inherited from context)
      - HH:MM             → time hms24
      - 4-digit years (19xx, 20xx) inside "v roce" / "rok" → cardinal
      - Emergency numbers (112/150/155/156/158) → digits
    """
    # 1. Phone numbers: +420 728 123 456 or +420728123456
    text = re.sub(
        r'\+420[\s\-]?(\d{3})[\s\-]?(\d{3})[\s\-]?(\d{3})',
        lambda m: f'<say-as interpret-as="telephone">+420 {m.group(1)} {m.group(2)} {m.group(3)}</say-as>',
        text,
    )

    # 2. Time HH:MM (24h)
    text = re.sub(
        r'\b([01]?\d|2[0-3]):([0-5]\d)\b',
        lambda m: f'<say-as interpret-as="time" format="hms24">{m.group(1)}:{m.group(2)}</say-as>',
        text,
    )

    # 3. Full date DD.MM.YYYY
    text = re.sub(
        r'\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b',
        lambda m: f'<say-as interpret-as="date" format="dmy">{m.group(1)}.{m.group(2)}.{m.group(3)}</say-as>',
        text,
    )

    # 4. Short date DD.MM. (no year)
    text = re.sub(
        r'\b(\d{1,2})\.\s?(\d{1,2})\.(?!\d)',
        lambda m: f'<say-as interpret-as="date" format="dm">{m.group(1)}.{m.group(2)}.</say-as>',
        text,
    )

    # 5. Year reading after "rok / v roce / roku"
    text = re.sub(
        r'\b([Rr]ok[uy]?|[Vv]\s+roce)\s+(19\d{2}|20\d{2})\b',
        lambda m: f'{m.group(1)} <say-as interpret-as="cardinal">{m.group(2)}</say-as>',
        text,
    )

    # 6. Emergency numbers — digit-by-digit
    text = re.sub(
        r'\b(112|150|155|156|158)\b',
        lambda m: f'<say-as interpret-as="digits">{m.group(1)}</say-as>',
        text,
    )

    return text


# ── v453: Czech-friendly aliases for commonly-mispronounced words ───────────
# Uses <sub alias="..."> so Azure's Czech engine handles inflection.
# Only includes entries where the alias actually changes pronunciation
# (no-op aliases just add SSML overhead without benefit).
_CZECH_SUB_ALIASES = [
    # Léky / medication brand names where original spelling misleads Azure
    (r'\b[Ww]arfarin\b',          'Varfarín'),    # W → V (Czech)
    (r'\b[Aa]nopyrin\b',          'Anopyrín'),    # add long í
    (r'\b[Cc]oncor\b',            'Konkor'),      # C → K
    (r'\b[Vv]erospiron\b',        'Verospíron'),
    (r'\b[Ff]urosemid\b',         'Furosemíd'),
    (r'\b[Ii]buprofen\b',         'Ibuprofén'),
    (r'\b[Ll]ozartan\b',          'Lozartán'),
    (r'\b[Mm]etformin\b',         'Metformín'),
    (r'\b[Aa]pixaban\b',          'Apixabán'),
    (r'\b[Ll]isinopril\b',        'Lisinopríl'),
    (r'\b[Ss]imvastatin\b',       'Simvastatín'),
    (r'\b[Aa]torvastatin\b',      'Atorvastatín'),

    # Communication apps — anglicismy s nečeským zvukovým profilem
    (r'\b[Mm]essenger\b',         'mesendžr'),
    (r'\b[Vv]iber\b',             'vajbr'),
]


def _apply_czech_sub_aliases(text):
    """Apply <sub alias="..."> for Czech-friendly mispronunciation fixes."""
    for pattern, alias_or_fn in _CZECH_SUB_ALIASES:
        if not re.search(pattern, text):
            continue

        if callable(alias_or_fn):
            def _replace(m, fn=alias_or_fn):
                alias = fn(m)
                return f'<sub alias="{alias}">{m.group(0)}</sub>'
        else:
            def _replace(m, alias=alias_or_fn):
                return f'<sub alias="{alias}">{m.group(0)}</sub>'

        text = re.sub(pattern, _replace, text)
    return text

def _fix_czech_pronunciation(text):
    """Fix Azure mispronunciations using IPA phoneme tags.

    Must be called AFTER xml_escape() so the SSML tags are not escaped.

    Bug-fix (TTS audit #8): dříve `re.search()` našel jen PRVNÍ výskyt
    slova v textu. Pokud text obsahoval "PDF a další PDF dokument",
    jen první PDF dostal phoneme tag, druhý zněl Azure-default.
    Fix: re.sub s callbackem nahradí VŠECHNY výskyty pattern najednou.

    v452 — Radim fix: Azure cs-CZ-AntoninNeural mispronounced base form
    "Radim" with hard /d/ + /ɪ/ → sounded like "Radym" instead of the
    proper Czech palatalized [ˈraɟɪm]. IPA phoneme tag was inconsistent.
    Solution: <sub alias="Raďim"> forces Azure's Czech engine to render
    the explicit ď, which always palatalizes correctly. Covers base form
    plus common declinations (Radime/Radima/Radimovi/Radimem) so chat
    greetings like "Ahoj Radime!" sound natural.
    """
    text = re.sub(
        r'\b([Rr])adim(e|a|em|ovi|ě|u)?\b',
        lambda m: f'<sub alias="{m.group(1)}aďim{m.group(2) or ""}">{m.group(0)}</sub>',
        text,
    )

    # v453: numbers/dates/times via standard SSML <say-as> (more reliable than IPA)
    text = _apply_smart_say_as(text)

    # v453: Czech-friendly aliases for medications and medical terms
    text = _apply_czech_sub_aliases(text)

    for pattern, ipa, display in _CZECH_PHONEME_FIXES:
        # Pre-check: pokud žádný match, přeskočit (re.sub by stejně neudělal nic,
        # ale tím se vyhneme zbytečné regex compilation)
        if not re.search(pattern, text):
            continue

        def _replace_match(m, ipa=ipa, display=display):
            word = m.group(0)
            display_text = display or word
            return f'<phoneme alphabet="ipa" ph="{ipa}">{display_text}</phoneme>'

        text = re.sub(pattern, _replace_match, text)
    return text


# Numbers and medicine names get emphasis automatically
EMPHASIS_PATTERNS = [
    r'\b\d{3}\b',             # 3-digit numbers (155, 112)
    r'\b\d{1,2}:\d{2}\b',    # times (8:30, 14:00)
]



def _add_sentence_pauses(text, pause_ms, poetry_mode=False):
    """Insert SSML breaks between sentences.

    v10.17: poetry_mode uses verse-aware pausing:
    - Period/exclamation/question at end → full pause (verse end)
    - Comma, semicolon, dash → short breath pause (200-300ms)
    - Within a verse line (no punctuation) → no pause (flow)
    """
    if not text:
        return ""

    if poetry_mode:
        return _add_poetry_pauses(text, pause_ms)

    # Standard prose pausing
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if len(sentences) <= 1:
        return xml_escape(text)

    parts = []
    for i, s in enumerate(sentences):
        parts.append(xml_escape(s.strip()))
        if i < len(sentences) - 1:
            parts.append(f'<break time="{pause_ms}ms"/>')
    return " ".join(parts)


def _add_poetry_pauses(text, base_pause_ms):
    """Verse-aware SSML pausing for poetry recitation.

    Rules:
    - Period (.) → medium pause (verse/stanza end)
    - Comma (,) → breath pause (250ms) — keeps flow within verse
    - Semicolon (;) → short pause (350ms)
    - Dash (—/-) → dramatic pause (400ms)
    - Line break (already converted to '. ') → verse pause
    - No punctuation between words → continuous flow
    """
    escaped = xml_escape(text)

    # Replace punctuation with SSML breaks
    # Comma → tiny breath (keeps verse flowing)
    escaped = re.sub(r',\s*', f', <break time="250ms"/> ', escaped)

    # Semicolon → slightly longer
    escaped = re.sub(r';\s*', f'; <break time="350ms"/> ', escaped)

    # Dash (em-dash or en-dash) → dramatic pause
    escaped = re.sub(r'\s*[—–-]\s*', f' <break time="400ms"/> ', escaped)

    # Period/exclamation/question → verse end pause
    escaped = re.sub(r'([.!?])\s+', rf'\1 <break time="{base_pause_ms}ms"/> ', escaped)

    return escaped


def _add_emphasis(text_with_breaks):
    """Add gentle emphasis to key words, numbers, medicine names.
    v473: Prevents double-nesting (<emphasis><emphasis>).
    """
    # Word emphasis
    for word in EMPHASIS_WORDS:
        pattern = re.compile(rf'(?<!<emphasis level="moderate">)\b({re.escape(word)})\b', re.IGNORECASE)
        text_with_breaks = pattern.sub(
            r'<emphasis level="moderate">\1</emphasis>',
            text_with_breaks
        )
    # Pattern emphasis (numbers, times) — skip if already wrapped
    for pat in EMPHASIS_PATTERNS:
        text_with_breaks = re.sub(
            rf'(?<!<emphasis level="moderate">)({pat})(?!</emphasis>)',
            r'<emphasis level="moderate">\1</emphasis>',
            text_with_breaks
        )
    return text_with_breaks


# v405: Response length limit — prevent long TTS output (seniors lose focus)
MAX_TTS_CHARS = 200

# v405: Fatigue hysteresis — prevent mode switching instability
_FATIGUE_ACTIVATE = 0.65
_FATIGUE_DEACTIVATE = 0.55
_FATIGUE_MAX_ENTRIES = 500  # v407: prevent memory leak — evict oldest when full
# Bug-fix (TTS audit #11): dict používáme s timestampem.
# Hodnota: (is_slow_active: bool, last_seen_ts: float)
# Pravidelně vyklízíme entries starší než 7 dní (úplně, nejen flag=False).
_fatigue_slow_active = {}  # user_id → (bool, timestamp)
_FATIGUE_TTL_SEC = 7 * 24 * 3600  # 7 dní
_fatigue_last_prune = 0  # časová značka posledního prune (lazy)


def _fatigue_get(user_id):
    """Helper: načíst is_slow flag, nebo False pokud entry neexistuje/expired."""
    entry = _fatigue_slow_active.get(user_id)
    if not entry:
        return False
    is_slow, ts = entry
    import time as _t
    if _t.time() - ts > _FATIGUE_TTL_SEC:
        # expired — vyklidíme
        del _fatigue_slow_active[user_id]
        return False
    return is_slow


def _fatigue_set(user_id, is_slow):
    """Helper: zapsat is_slow flag s timestampem + lazy prune."""
    import time as _t
    global _fatigue_last_prune
    now = _t.time()
    _fatigue_slow_active[user_id] = (is_slow, now)

    # Lazy prune: jednou za hodinu projít celý dict a vyhodit expired
    if now - _fatigue_last_prune > 3600:
        _fatigue_last_prune = now
        expired_keys = [
            uid for uid, (_, ts) in _fatigue_slow_active.items()
            if now - ts > _FATIGUE_TTL_SEC
        ]
        for k in expired_keys:
            _fatigue_slow_active.pop(k, None)

    # Hard cap: pokud i po prune má dict > MAX, vyhodit nejstarší
    if len(_fatigue_slow_active) > _FATIGUE_MAX_ENTRIES:
        oldest_uid = min(_fatigue_slow_active, key=lambda k: _fatigue_slow_active[k][1])
        _fatigue_slow_active.pop(oldest_uid, None)


def _truncate_for_tts(text, max_chars=MAX_TTS_CHARS):
    """Shorten text for TTS while preserving meaning.
    Cuts at sentence boundary, adds continuation hint.
    Guarantees: len(result) <= max_chars + 1 (for trailing period).
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    # Find last sentence boundary before limit
    truncated = text[:max_chars]
    last_period = max(truncated.rfind('.'), truncated.rfind('!'), truncated.rfind('?'))
    if last_period > max_chars * 0.4:  # at least 40% of text
        return truncated[:last_period + 1]
    # No good sentence boundary — cut at last space
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space] + "."
    # v407: Guarantee max length even for single long word
    return truncated[:max_chars - 1] + "."


def _add_pause_variability(pause_ms, mode="random"):
    """Add variability to pauses for natural speech rhythm.

    Modes:
        'random'  → ±50 ms uniform noise (default — chat, info, news)
        'phi'     → golden-ratio alternation (poetry, festive, narration)
                    pauses alternate between base*1 and base/φ (≈0.618)
        'breath'  → ±15% gaussian around base (calm, crisis)
    """
    import random, math
    PHI = 1.6180339887

    if mode == "phi":
        # Alternate longer / shorter by golden ratio → more musical
        if not hasattr(_add_pause_variability, "_phi_toggle"):
            _add_pause_variability._phi_toggle = 0
        _add_pause_variability._phi_toggle += 1
        if _add_pause_variability._phi_toggle % 2 == 0:
            return max(200, int(pause_ms * (1 / PHI)))
        return max(200, int(pause_ms))
    elif mode == "breath":
        variation = int(random.gauss(0, pause_ms * 0.15))
        return max(200, pause_ms + variation)
    else:  # random
        variation = random.randint(-50, 50)
        return max(200, pause_ms + variation)


def _lang_from_voice(voice: str) -> str:
    """Extract xml:lang code from an Azure voice name like 'cs-CZ-AntoninNeural'.
    Falls back to cs-CZ if the format is unexpected."""
    try:
        parts = (voice or "").split("-")
        if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
            return f"{parts[0].lower()}-{parts[1].upper()}"
    except Exception:
        pass
    return "cs-CZ"


def build_simple_ssml(text: str, voice: str) -> str:
    """Minimal SSML for non-Czech Azure voices (V4+EN translator output).

    No style/prosody tweaks — let the voice speak naturally in its own
    language. Czech-only Radim-branding (express-as, pronunciation fixes,
    contour mapping) is not applicable to EN/SK/PL/HU renders.
    """
    xml_lang = _lang_from_voice(voice)
    safe = xml_escape(text)
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{xml_lang}">'
        f'<voice name="{voice}">'
        f'<prosody rate="-5%">{safe}</prosody>'
        f'</voice></speak>'
    )


def build_radim_ssml(text, mode="HARMONY", voice="cs-CZ-AntoninNeural",
                     user_id=None, rtcf_voice=None, brain_speech=None):
    """Build rich SSML for Radim's voice with mode-adaptive styling.

    Sprint AA: brain_speech param wires Ψ(t)-driven speech params into SSML.
      - rate (e.g. 0.85 → "-15%"), pitch_pct, pause_ms
      - When provided, overrides static VOICE_PROFILES values with dynamic
        ones from compute_unified_speech() — closing the loop where brain
        engine output was previously dead code.
      - Mode is still derived from brain (CRISIS / ALERT / HARMONY) but
        the magnitudes adapt per-user (per-user adaptation, anticipation
        fine-tune, age, RTCF beat).

    v405 hardening:
    - MAX_TTS_CHARS truncation (seniors lose focus on long speech)
    - Fatigue hysteresis (prevent mode switching instability)
    - Pause variability (±50ms for natural rhythm)
    - Logging: mode, overrides applied, text length

    v10.52: If voice is not Czech (e.g. en-US, sk-SK, pl-PL, hu-HU from the
    translator module), drop Czech-specific SSML decorations and emit a
    minimal, language-correct envelope instead. Radim's branding only
    applies to Czech.
    """
    # Route non-Czech voices to the simple builder — Czech express-as styles
    # and pronunciation tweaks aren't valid for other locales and could
    # either be ignored or cause Azure to reject the request.
    xml_lang = _lang_from_voice(voice)
    if not xml_lang.lower().startswith("cs-"):
        # Still honor length truncation for UX
        text = _truncate_for_tts(text)
        return build_simple_ssml(text, voice)
    # Sprint V.9: normalize mode via central mapping (handles aliases:
    # 'harmony'/'friendly'/'calm' → HARMONY, etc.)
    try:
        from voice_mapping import normalize_mode
        mode = normalize_mode(mode)
    except ImportError:
        # voice_mapping.py missing — fall back to direct lookup
        if mode not in VOICE_PROFILES:
            logger.warning(f"Invalid voice mode '{mode}' — falling back to HARMONY")
            mode = "HARMONY"
    profile = dict(VOICE_PROFILES.get(mode, VOICE_PROFILES["HARMONY"]))
    overrides = []

    # v405: Truncate long text
    original_len = len(text)
    text = _truncate_for_tts(text)
    if len(text) < original_len:
        overrides.append(f"truncated:{original_len}→{len(text)}")

    # ── Sprint AA: brain_speech wires Ψ(t) state into SSML ─────────────
    # brain_speech comes from compute_unified_speech(C, alpha, mode, ...)
    # which blends:
    #   Layer 1 — brain baseline (HARMONY/ALERT/CRISIS)
    #   Layer 2 — anticipation fine-tune (predicted Ĉ_{t+1})
    #   Layer 3 — per-user adaptation (brain_adaptation table)
    #   Layer 4 — age-aware pitch mapping (semitones → %)
    # Previously only brain_speech.mode was consumed; rate/pitch/pause were
    # dead code. This override closes the loop so Radim's audio actually
    # reflects per-user Ψ(t) magnitudes, not just the static mode preset.
    if brain_speech and isinstance(brain_speech, dict):
        bs_rate = brain_speech.get('rate')
        if bs_rate is not None:
            try:
                # Numeric rate (e.g. 0.85) → SSML percent ("-15%")
                rate_pct = int(round((float(bs_rate) - 1.0) * 100))
                profile['rate'] = f"{rate_pct:+d}%"
            except (TypeError, ValueError):
                pass
        bs_pitch = brain_speech.get('pitch_pct')
        if bs_pitch is not None:
            try:
                profile['pitch'] = f"{int(round(float(bs_pitch))):+d}%"
            except (TypeError, ValueError):
                pass
        bs_pause = brain_speech.get('pause_ms')
        if bs_pause is not None:
            try:
                profile['pause_ms'] = max(200, int(bs_pause))
            except (TypeError, ValueError):
                pass
        bs_style = brain_speech.get('style')
        if bs_style:
            profile['style'] = bs_style
        bs_sd = brain_speech.get('styledegree')
        if bs_sd is not None:
            try:
                profile['styledegree'] = f"{float(bs_sd):.1f}"
            except (TypeError, ValueError):
                pass
        overrides.append(
            f"brain:{brain_speech.get('mode', mode)}"
            f":r{profile['rate']}:p{profile['pause_ms']}"
        )

    # v403: Per-user adaptive overrides
    if user_id:
        try:
            from adaptive_learning import get_adaptive_state
            state = get_adaptive_state(user_id)
            if state:
                comm = state.get("communication", {})
                if comm.get("speech_speed") == "slow" and mode == "HARMONY":
                    profile["rate"] = "-15%"
                    profile["pause_ms"] = 1000
                    overrides.append("slow_speech")

                # v405: Fatigue with hysteresis
                # v407 + TTS audit #11: dict s TTL, eviction při každém touch.
                fatigue = state.get("fatigue_level", 0)
                was_slow = _fatigue_get(user_id)
                if fatigue > _FATIGUE_ACTIVATE or (was_slow and fatigue > _FATIGUE_DEACTIVATE):
                    _fatigue_set(user_id, True)
                    current_rate = int(profile["rate"].replace("%", "").replace("+", ""))
                    profile["rate"] = f"{min(current_rate, -15)}%"
                    profile["pause_ms"] = max(profile["pause_ms"], 1200)
                    overrides.append(f"fatigue:{fatigue}")
                else:
                    # Recovery: pokud user nikdy nebyl slow, nemusíme záznam ani vytvářet
                    if was_slow:
                        _fatigue_set(user_id, False)

                recovery = state.get("recovery", {})
                if recovery.get("active") and recovery.get("level", 0) >= 2:
                    # v407: Don't speed up if already slower (e.g. CRISIS at -25%)
                    current_rate = int(profile["rate"].replace("%", "").replace("+", ""))
                    profile["rate"] = f"{min(current_rate, -20)}%"
                    profile["volume"] = "x-loud"
                    profile["pause_ms"] = max(profile["pause_ms"], 1500)
                    overrides.append(f"recovery:L{recovery['level']}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Adaptive voice failed for {user_id}: {e}")

    # v10.19: Apply voice learning (per-user adaptation)
    if user_id:
        try:
            from voice_learning import apply_voice_learning
            profile = apply_voice_learning(profile, user_id)
            overrides.append("learned")
        except ImportError:
            pass  # voice_learning not installed
        except Exception as e:
            logger.info(f"⚠️ Voice learning failed for {user_id}: {e}")

    # v10.25: RTCF heartbeat voice modifiers
    if rtcf_voice:
        rate_adj = rtcf_voice.get('rate_adjust', 0)
        if rate_adj:
            current = int(profile['rate'].replace('%', '').replace('+', ''))
            profile['rate'] = f"{current + int(rate_adj)}%"
        pause_adj = rtcf_voice.get('pause_adjust_ms', 0)
        if pause_adj:
            profile['pause_ms'] = max(200, profile['pause_ms'] + pause_adj)
        style_hint = rtcf_voice.get('style_hint')
        if style_hint:
            profile['style'] = style_hint
        sd_hint = rtcf_voice.get('styledegree_hint')
        if sd_hint:
            profile['styledegree'] = sd_hint
        overrides.append("rtcf")

    # v10.20: PER-SENTENCE prosody with individual φ-contour
    # Each sentence gets its own pitch curve → natural intonation
    # v10.40: pause variability mode by profile
    _pause_var_mode = "random"
    if mode in ("POETRY", "FESTIVE", "NARRATION", "SINGING"):
        _pause_var_mode = "phi"
    elif mode in ("CRISIS", "ALERT"):
        _pause_var_mode = "breath"
    pause_ms = _add_pause_variability(profile["pause_ms"], mode=_pause_var_mode)
    is_poetry = profile.get("poetry_mode", False)
    contour_type = profile.get("contour")
    # v10.20: Profile-specific energy → learned energy → default
    _energy = profile.get('learned_energy', profile.get('contour_energy', 0.5))

    # Split text into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    if not sentences:
        sentences = [text]

    # Build per-sentence SSML blocks
    sentence_blocks = []
    contour_used = False

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue

        safe_sentence = xml_escape(sentence)

        # v10.20: Pronunciation fixes AFTER xml_escape (SSML tags won't be escaped)
        # Azure cs-CZ-AntoninNeural says "dýčejte" instead of "dýchejte"
        # Fix: use IPA phoneme tag to force correct "ch" /x/ pronunciation
        safe_sentence = _fix_czech_pronunciation(safe_sentence)

        # Emphasis for ALERT/CRISIS
        if profile["emphasis"]:
            safe_sentence = _add_emphasis(safe_sentence)

        # Poetry: verse-aware pauses within sentence
        if is_poetry:
            safe_sentence = _add_poetry_pauses(safe_sentence, pause_ms)

        # Per-sentence contour (each sentence has its own melodic curve)
        contour_attr = ""
        if contour_type:
            try:
                from voice_melody import get_voice_contour
                contour = get_voice_contour(sentence, mode=contour_type, energy=_energy, user_id=user_id)
                if contour:
                    # v10.22: Scale contour intensity
                    _scale = profile.get('contour_scale', 1.0)
                    if _scale != 1.0:
                        import re as _re
                        def _scale_hz(m):
                            val = int(int(m.group(1)) * _scale)
                            return f'{val:+d}Hz'
                        contour = _re.sub(r'([+-]?\d+)Hz', _scale_hz, contour)
                    contour_attr = f' contour="{contour}"'
                    contour_used = True
            except (ImportError, Exception):
                pass

        # Slight pitch variation per sentence position (natural declination)
        pitch_mod = profile['pitch']
        if len(sentences) > 1:
            base_pitch = int(pitch_mod.replace('%', '').replace('+', ''))
            if i == 0:
                # Opening — slightly higher pitch
                val = base_pitch + 2
            elif i == len(sentences) - 1:
                # Closing — slightly lower
                val = base_pitch - 1
            else:
                val = base_pitch
            pitch_mod = f"{val:+d}%"  # Correct format: "+2%" or "-3%"

        sentence_blocks.append(
            f'<prosody rate="{profile["rate"]}" pitch="{pitch_mod}" volume="{profile["volume"]}"{contour_attr}>'
            f'{safe_sentence}</prosody>'
        )

        # Add pause between sentences (not after last)
        if i < len(sentences) - 1:
            sentence_blocks.append(f'<break time="{pause_ms}ms"/>')

    if contour_used:
        overrides.append(f"φ-contour:{contour_type}:e{_energy:.1f}:s{len(sentences)}")

    if overrides:
        logger.info(f"TTS [{mode}] {len(text)}ch overrides=[{','.join(overrides)}]")

    inner_ssml = "\n            ".join(sentence_blocks)
    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
           xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
    <voice name="{voice}">
        <mstts:express-as style="{profile['style']}" styledegree="{profile['styledegree']}">
            {inner_ssml}
        </mstts:express-as>
    </voice>
</speak>'''

    return ssml


def apply_radim_filter(audio_bytes, mode="HARMONY", format="mp3"):
    """
    v2.0: No-op pass-through. Voice filtering is now done at SSML level
    via build_radim_ssml(). This function exists for backward compatibility.

    Returns audio_bytes unchanged.
    """
    return audio_bytes


def is_available():
    """Voice filter is always available (SSML-based, no dependencies)."""
    return True


logger.info("✅ Voice Filter v2.0 loaded — SSML-based, no ffmpeg needed")
