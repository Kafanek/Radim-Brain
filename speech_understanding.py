"""
Speech Understanding v1.0 — Fuzzy matching for speech-impaired seniors
======================================================================
Handles:
1. Czech diacritics normalization (háčky/čárky → ASCII for matching)
2. Fuzzy safety word detection (Levenshtein distance ≤ 2)
3. Phonetic Czech matching (common STT errors: š→s, č→c, ř→r, ž→z)
4. Adaptive Twilio Gather parameters per communication profile
5. Low-confidence STT retry logic

Used by: intent_resolver.py, twilio_voice_routes.py, intent_data.py
"""

import re
import unicodedata
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CZECH TEXT NORMALIZATION
# ============================================================================

def strip_diacritics(text):
    """Remove Czech diacritics: háčky + čárky → ASCII.
    'Příliš žluťoučký kůň' → 'Prilis zlutoucky kun'
    """
    # NFD decomposes: č → c + combining caron
    nfkd = unicodedata.normalize('NFKD', text)
    # Remove combining marks (category M)
    return ''.join(c for c in nfkd if unicodedata.category(c) != 'Mn')


def normalize_czech(text):
    """Full normalization for matching: lowercase + strip diacritics + collapse whitespace + strip punctuation."""
    if not text:
        return ""
    t = text.lower().strip()
    t = strip_diacritics(t)
    t = re.sub(r'[!?.,;:"\'-]', '', t)  # remove common punctuation
    t = re.sub(r'\s+', ' ', t)
    return t


# ============================================================================
# FUZZY SAFETY DETECTION — must catch "pomo", "pomc", "pomc" etc.
# ============================================================================

# Safety words with max Levenshtein distance allowed
# Format: (normalized_word, max_distance, severity)
SAFETY_FUZZY = [
    # Emergency — distance 2 catches "pomo", "pomco", "pomc"
    ("pomoc", 2, "critical"),
    ("pomozte", 2, "critical"),
    ("zachranka", 2, "critical"),
    ("zachranku", 2, "critical"),
    ("zavolej", 2, "critical"),
    # Numbers — exact match only (distance 0)
    ("155", 0, "critical"),
    ("112", 0, "critical"),
    ("158", 0, "critical"),
    # Health crisis — distance 1
    ("bolest", 1, "high"),
    ("bolit", 1, "high"),
    ("spadl", 1, "high"),
    ("spadla", 1, "high"),
    ("nemohu", 1, "high"),
    ("nemuzu", 1, "high"),
    ("dychej", 2, "critical"),  # dýchej → dychej, dychet, dichet
    ("dusim", 1, "critical"),
    # Distress
    ("strach", 1, "medium"),
    ("boji", 1, "medium"),
    ("ztratil", 2, "high"),
    ("ztratila", 2, "high"),
    ("nevim", 1, "medium"),
    # Suicidal (must not miss)
    ("sebevrazda", 2, "critical"),
    ("nechci", 1, "high"),
    ("zabij", 2, "critical"),
]


def _levenshtein(s1, s2):
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            # Insert, delete, replace
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (0 if c1 == c2 else 1)
            ))
        prev = curr

    return prev[-1]


def detect_safety_fuzzy(text):
    """Detect safety/crisis words with fuzzy matching.

    Returns:
        dict or None: {"word": matched_word, "input": user_word,
                       "distance": int, "severity": str}
    """
    normalized = normalize_czech(text)
    words = normalized.split()

    best_match = None
    best_severity_rank = {"critical": 3, "high": 2, "medium": 1}

    for word in words:
        if len(word) < 2:
            continue

        for target, max_dist, severity in SAFETY_FUZZY:
            # Quick length check — can't match if lengths differ by more than max_dist
            if abs(len(word) - len(target)) > max_dist:
                continue

            dist = _levenshtein(word, target)
            if dist <= max_dist:
                rank = best_severity_rank.get(severity, 0)
                if best_match is None or rank > best_severity_rank.get(best_match["severity"], 0):
                    best_match = {
                        "word": target,
                        "input": word,
                        "distance": dist,
                        "severity": severity,
                    }
                # Critical always wins
                if severity == "critical" and dist <= max_dist:
                    return best_match

    return best_match


# ============================================================================
# PHONETIC CZECH NORMALIZATION (common STT errors)
# ============================================================================

# Czech phonetic equivalents — what STT often confuses
_PHONETIC_MAP = {
    'sh': 's',    # sometimes STT writes "sh" for "š"
    'ch': 'h',    # "ch" is single phoneme in Czech
    'rz': 'r',    # Polish-influenced STT
    'sz': 's',
    'cz': 'c',
    'dz': 'z',
}

# Single char replacements (after diacritics strip)
_CHAR_NORMALIZE = str.maketrans({
    'y': 'i',     # y/i confusion very common in Czech
    'w': 'v',     # w→v for international keyboards
})


def phonetic_normalize(text):
    """Aggressive phonetic normalization for matching.
    Used as fallback when exact + fuzzy matching fails.
    """
    t = normalize_czech(text)
    for old, new in _PHONETIC_MAP.items():
        t = t.replace(old, new)
    t = t.translate(_CHAR_NORMALIZE)
    # Remove doubled consonants
    t = re.sub(r'(.)\1+', r'\1', t)
    return t


# ============================================================================
# ADAPTIVE TWILIO GATHER PARAMETERS
# ============================================================================

def get_gather_params(user_id=None):
    """Return Twilio <Gather> parameters adapted to user's communication profile.

    Returns:
        dict: {speech_timeout, timeout, language, hints}
    """
    defaults = {
        "speech_timeout": 3,
        "timeout": 10,
        "language": "cs-CZ",
        "hints": "",  # speech recognition hints
    }

    if not user_id:
        return defaults

    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)
        needs = (profile.get("communication_needs") or "").lower()

        # Aphasia, dysarthria, stuttering — need MORE time
        slow_speech = any(n in needs for n in [
            "afazi", "dysartr", "kokta", "parkinson",
            "als", "huntington", "ms", "dysf",
        ])

        # Dementia — shorter timeout (they forget what they were saying)
        dementia = any(n in needs for n in [
            "demenc", "alzheim", "lewy", "vaskul", "frontotemp",
        ])

        # Hearing impairment — normal timing but add hints
        hearing = "sluch" in needs

        if slow_speech:
            defaults["speech_timeout"] = 8  # 8s instead of 3s — wait for them
            defaults["timeout"] = 20        # 20s total — patient gathering
            logger.debug(f"Adaptive gather for {user_id}: slow_speech mode (8s/20s)")

        elif dementia:
            defaults["speech_timeout"] = 5  # bit more time
            defaults["timeout"] = 15
            # Add medication/name hints for better recognition
            meds = profile.get("medications_list", [])
            if meds:
                defaults["hints"] = ",".join(meds[:5])
            logger.debug(f"Adaptive gather for {user_id}: dementia mode (5s/15s)")

        if hearing:
            # No timing change, but we could add TTS volume boost in future
            pass

        # v401: Override from adaptive learning (learned from actual user behavior)
        try:
            from adaptive_learning import get_adaptive_state
            state = get_adaptive_state(user_id)
            if state:
                multiplier = state.get("communication", {}).get("patience_multiplier", 1.0)
                if multiplier > 1.0:
                    # Adaptive engine learned this user needs more time
                    adapted_st = max(defaults["speech_timeout"], round(3 * multiplier))
                    adapted_to = max(defaults["timeout"], round(10 * multiplier))
                    if adapted_st > defaults["speech_timeout"]:
                        defaults["speech_timeout"] = min(adapted_st, 15)  # cap at 15s
                        defaults["timeout"] = min(adapted_to, 30)         # cap at 30s
                        logger.debug(f"Adaptive gather override for {user_id}: {defaults['speech_timeout']}s/{defaults['timeout']}s (×{multiplier})")
        except (ImportError, Exception):
            pass

    except Exception as e:
        logger.debug(f"get_gather_params error: {e}")

    return defaults


# ============================================================================
# LOW CONFIDENCE HANDLER
# ============================================================================

def should_retry_stt(speech_result, confidence, user_id=None):
    """Decide if we should ask user to repeat (low confidence)
    vs. try to understand (fuzzy match).

    Returns:
        (action, data) where:
        - ("retry", None) — ask to repeat
        - ("safety", match_dict) — safety word detected despite low confidence
        - ("proceed", None) — confidence acceptable, proceed normally
    """
    conf = float(confidence or 0)

    # Always check safety first — even with terrible confidence
    if speech_result:
        safety = detect_safety_fuzzy(speech_result)
        if safety and safety["severity"] == "critical":
            return ("safety", safety)

    # Very low confidence + short text = retry
    if conf < 0.3 and len((speech_result or "").strip()) < 10:
        return ("retry", None)

    # Low confidence but long text = probably OK (context helps)
    if conf < 0.4 and len((speech_result or "").strip()) < 5:
        return ("retry", None)

    # Medium confidence — check if fuzzy safety matches
    if conf < 0.6 and speech_result:
        safety = detect_safety_fuzzy(speech_result)
        if safety:
            return ("safety", safety)

    return ("proceed", None)


# ============================================================================
# RETRY MESSAGES (Czech, empathetic)
# ============================================================================

RETRY_MESSAGES = [
    "Promiňte, neslyšel jsem vás dobře. Můžete to prosím zopakovat?",
    "Omlouvám se, nerozuměl jsem. Řekněte to prosím ještě jednou.",
    "Promiňte, nezachytil jsem to. Můžete to zopakovat pomaleji?",
]

SAFETY_CONFIRM_MESSAGE = (
    "Slyšel jsem, že potřebujete pomoc. Je to tak? "
    "Řekněte ano, nebo stiskněte jedničku."
)


# ============================================================================
# STT POST-PROCESSOR — correct common Twilio Czech STT errors
# ============================================================================

# Common Twilio cs-CZ STT errors: what it hears → what was actually said
# Collected from real Twilio logs with Czech seniors
_STT_CORRECTIONS = {
    # Numbers misheard as words
    "jedna pět pět": "155",
    "jedna jedna dva": "112",
    "jedna padesát pět": "155",
    # Medications (common STT mangles)
    "done pezil": "donepezil",
    "dona pezil": "donepezil",
    "met formin": "metformin",
    "ena lapril": "enalapril",
    "war farin": "warfarin",
    "ibu profen": "ibuprofen",
    # Common Czech words STT gets wrong
    "prosim": "prosím",
    "dekuji": "děkuji",
    "dobre": "dobře",
    "ano": "ano",
    "ne": "ne",
    # Senior speech patterns
    "co co": "co",           # repetition (dementia)
    "tak tak": "tak",         # filler
    "no no no": "no",         # filler
    "halo halo": "haló",      # phone greeting
}

# Word-level corrections (applied per word, not per phrase)
_WORD_CORRECTIONS = {
    "pomok": "pomoc",
    "pomoct": "pomoc",
    "pomoci": "pomoc",
    "pomůžu": "pomoc",
    "zachranku": "záchranku",
    "zachranka": "záchranka",
    "doktora": "doktora",
    "doktor": "doktor",
    "nemocnice": "nemocnice",
    "nemocnici": "nemocnici",
    "leky": "léky",
    "prasky": "prášky",
    "tablety": "tablety",
    "bolesti": "bolesti",
    "bolest": "bolest",
    "spatne": "špatně",
    "spatny": "špatný",
}


MAX_CORRECTION_STEPS = 5  # safety: stop correcting after N changes to prevent over-correction


def correct_stt_output(text, user_id=None):
    """Post-process STT output to fix common Czech recognition errors.

    Safety: stops after MAX_CORRECTION_STEPS to prevent over-correction.
    If limit hit, logs warning and returns partially corrected text.

    Returns:
        (corrected_text, corrections_applied)
    """
    if not text:
        return text, []

    original = text
    corrections = []
    lower = text.lower().strip()

    # Phase 1: Full phrase corrections
    for wrong, right in _STT_CORRECTIONS.items():
        if wrong in lower:
            lower = lower.replace(wrong, right)
            corrections.append(f"'{wrong}' → '{right}'")

    # Phase 2: Word-level corrections (with limit)
    words = lower.split()
    corrected_words = []
    for w in words:
        if len(corrections) >= MAX_CORRECTION_STEPS:
            corrected_words.append(w)  # stop correcting, pass through
            continue
        clean = re.sub(r'[.,!?;:]', '', w)
        if clean in _WORD_CORRECTIONS:
            replacement = _WORD_CORRECTIONS[clean]
            suffix = w[len(clean):] if len(w) > len(clean) else ""
            corrected_words.append(replacement + suffix)
            corrections.append(f"'{clean}' → '{replacement}'")
        else:
            corrected_words.append(w)

    result = " ".join(corrected_words)

    if len(corrections) >= MAX_CORRECTION_STEPS:
        logger.warning(f"STT correction limit hit ({MAX_CORRECTION_STEPS}): '{original}'")

    # Phase 3: Collapse repeated words (dementia pattern: "co co co" → "co")
    result = re.sub(r'\b(\w+)(\s+\1){2,}\b', r'\1', result)

    # Phase 4: Per-user learned corrections (from adaptive_learning STT tracking)
    if user_id:
        try:
            from memory_helpers import db_load_learning
            learning = db_load_learning(user_id)
            stt_errors = learning.get("adaptive", {}).get("stt_error_counts", {})
            # If a word appears 3+ times in error log, it's a systematic STT issue
            # We don't auto-correct (risky) but log for speech hints improvement
            for wrong_word, count in stt_errors.items():
                if count >= 3 and wrong_word in result:
                    logger.debug(f"Known STT issue for {user_id}: '{wrong_word}' (seen {count}x)")
        except (ImportError, Exception):
            pass

    if corrections:
        logger.debug(f"STT correction: '{original}' → '{result}' [{', '.join(corrections)}]")

    return result, corrections


def build_speech_hints(user_id):
    """Build Twilio speech recognition hints from user profile.

    Hints improve STT accuracy for user-specific vocabulary:
    - Medication names (Donepezil, Metformin)
    - Family member names (Marie, Karel)
    - Common phrases for their needs

    Returns:
        str: comma-separated hints for Twilio <Gather hints="...">
    """
    hints = [
        # Always include safety words
        "pomoc", "záchranku", "bolest", "spadl", "špatně",
        # Common senior phrases
        "léky", "prášky", "doktor", "nemocnice",
        "ano", "ne", "prosím", "děkuji",
    ]

    if not user_id:
        return ",".join(hints)

    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id)

        # Add medication names
        meds = profile.get("medications_list", [])
        if meds and isinstance(meds, list):
            hints.extend(meds[:5])

        # Add user's name (helps STT recognize it)
        name = profile.get("name", "")
        if name:
            hints.append(name)

        # Add emergency contact names
        contacts = profile.get("emergency_contacts", [])
        if contacts and isinstance(contacts, list):
            for c in contacts[:3]:
                cname = c.get("name", "")
                if cname:
                    hints.append(cname)

        # v402: Add user-learned error words as hints (prevents repeated STT errors)
        try:
            from memory_helpers import db_load_learning
            learning = db_load_learning(user_id)
            stt_errors = learning.get("adaptive", {}).get("stt_error_counts", {})
            # Add frequently misheard words (3+ occurrences)
            for word, count in sorted(stt_errors.items(), key=lambda x: -x[1])[:10]:
                if count >= 3 and word not in hints:
                    # Add the CORRECT version if we know it
                    correct = _WORD_CORRECTIONS.get(word)
                    if correct and correct not in hints:
                        hints.append(correct)
        except Exception:
            pass

    except Exception:
        pass

    # Twilio limit: 500 hints, each max 100 chars
    return ",".join(hints[:50])


# ============================================================================
# SAFETY PRIORITY CLASSIFICATION
# ============================================================================

def classify_safety_priority(text, confidence=1.0):
    """Classify message safety priority.

    Returns:
        dict: {
            "priority": "CRITICAL" | "MEDIUM" | "LOW",
            "bypass_ai": bool,     # skip AI for immediate response
            "escalate": bool,      # trigger caregiver notification
            "reason": str or None,
        }
    """
    if not text:
        return {"priority": "LOW", "bypass_ai": False, "escalate": False, "reason": None}

    # Check fuzzy safety first
    safety = detect_safety_fuzzy(text)
    conf = float(confidence or 0)

    if safety and safety["severity"] == "critical":
        return {
            "priority": "CRITICAL",
            "bypass_ai": True,
            "escalate": True,
            "reason": f"Safety word '{safety['word']}' detected (distance={safety['distance']})",
        }

    if safety and safety["severity"] == "high":
        return {
            "priority": "CRITICAL" if conf > 0.5 else "MEDIUM",
            "bypass_ai": conf > 0.5,
            "escalate": conf > 0.5,
            "reason": f"High-severity word '{safety['word']}' (confidence={conf})",
        }

    if safety and safety["severity"] == "medium":
        return {
            "priority": "MEDIUM",
            "bypass_ai": False,
            "escalate": False,
            "reason": f"Medium-severity word '{safety['word']}'",
        }

    # Check for confusion patterns (repeated words, very short)
    normalized = normalize_czech(text)
    words = normalized.split()
    if len(words) >= 3:
        unique = set(words)
        if len(unique) <= len(words) * 0.4:  # >60% repetition
            return {
                "priority": "MEDIUM",
                "bypass_ai": False,
                "escalate": False,
                "reason": "Repeated words pattern (possible confusion)",
            }

    return {"priority": "LOW", "bypass_ai": False, "escalate": False, "reason": None}


# ============================================================================
# LATENCY GUARD — fallback if processing takes too long
# ============================================================================

LATENCY_LIMIT_MS = 2500  # target: respond within 2.5s (leaves 500ms for network)

LATENCY_FALLBACK_RESPONSES = [
    "Promiňte, chvilku mi to trvá. Můžete to zkusit ještě jednou?",
    "Omlouvám se za zdržení. Jsem tu pro vás.",
    "Moment prosím, zpracovávám vaši odpověď.",
]


def get_latency_fallback():
    """Return a short fallback response when processing exceeds time limit."""
    import random
    return random.choice(LATENCY_FALLBACK_RESPONSES)


logger.info("Speech Understanding v2.0 loaded — safety priority + correction limit + error learning")
