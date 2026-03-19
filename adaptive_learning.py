"""
Adaptive Learning v2.0 — Radim Adaptive Engine
===============================================
Learns from EVERY interaction:
1. Interaction rhythm — when does this user talk? (time-of-day heatmap)
2. Message pace — how long are their messages? How fast do they respond?
3. Response length preference — do they prefer short or long answers?
4. Feedback detection — "děkuji" = success, "nerozumím" = failure
5. STT error tracking — what words does STT get wrong for THIS user?
6. Emotional transitions — mood state machine per user
7. Topic freshness — time-weighted topic interests

All data stored in memory_learning JSONB under "adaptive" key.
Updated on every interaction via update_adaptive_profile().
"""

import logging
import re
from datetime import datetime, timedelta
from collections import Counter

logger = logging.getLogger(__name__)

# ============================================================================
# FEEDBACK DETECTION — did user like the response?
# ============================================================================

_SUCCESS_SIGNALS = [
    r'\b(d[ěe]kuj[iu]|d[ií]ky|dekuju|fajn|super|skv[ěe]l[ýeya]|v[ýy]born[ěeya]|dobre|spr[áa]vn[ěeya])\b',
    r'\b(ano|jo|jasn[ěeya]|p[řr]esn[ěeya]|souhlas[ií]m|m[áa][šs]\s+pravdu)\b',
    r'\b(pomohlo|pomoh|rozum[ií]m|ch[áa]pu|ok[ée]j?|ok)\b',
]

_FAILURE_SIGNALS = [
    r'\b(nerozum[ií]m|nech[áa]pu|co\s+t[ií]m\s+mysl[ií][šs])\b',
    r'\b(ne\s+ne|to\s+nen[ií]|[šs]patn[ěeya]|blb[ěeya]|h[ůu][řr])\b',
    r'\b(opakuj|znovu|je[šs]t[ěe]\s+jednou|pomaleji|hlasit[ěe]ji)\b',
    r'\b(moc\s+dlouh[ýeya]|kr[áa]t[čc]e|stru[čc]n[ěeya])\b',
    r'\b(nev[ií]m|nevad[ií]|jedno)\b',
]

_COMPILED_SUCCESS = [re.compile(p, re.IGNORECASE) for p in _SUCCESS_SIGNALS]
_COMPILED_FAILURE = [re.compile(p, re.IGNORECASE) for p in _FAILURE_SIGNALS]

# Explicit length feedback
_WANTS_SHORTER = re.compile(r'(kr[áa]t[čc]e|stru[čc]n|moc\s+dlouh|zkra[ťt])', re.IGNORECASE)
_WANTS_LONGER = re.compile(r'(v[ií]c|podrobn|rozve[ďd]|vysv[ěe]tli)', re.IGNORECASE)


def detect_feedback(message):
    """Detect user feedback from their response.

    Returns:
        dict: {
            "signal": "success" | "failure" | "neutral",
            "strength": 0.0-1.0,
            "length_pref": "shorter" | "longer" | None,
            "wants_repeat": bool,
        }
    """
    if not message:
        return {"signal": "neutral", "strength": 0.0, "length_pref": None, "wants_repeat": False}

    text = message.strip()
    text_lower = text.lower()

    success_hits = sum(1 for p in _COMPILED_SUCCESS if p.search(text_lower))
    failure_hits = sum(1 for p in _COMPILED_FAILURE if p.search(text_lower))

    # Determine signal
    if success_hits > failure_hits:
        signal = "success"
        strength = min(1.0, success_hits * 0.4)
    elif failure_hits > success_hits:
        signal = "failure"
        strength = min(1.0, failure_hits * 0.4)
    else:
        signal = "neutral"
        strength = 0.0

    # Length preference
    length_pref = None
    if _WANTS_SHORTER.search(text_lower):
        length_pref = "shorter"
    elif _WANTS_LONGER.search(text_lower):
        length_pref = "longer"

    # Repeat request
    wants_repeat = bool(re.search(r'(opakuj|znovu|je[šs]t[ěe]\s+jednou|zopakuj)', text_lower, re.IGNORECASE))

    # Implicit: very short response after long answer = possible confusion
    if len(text) < 5 and text_lower not in ("ano", "jo", "ne", "ok", "díky"):
        if signal == "neutral":
            signal = "confusion"
            strength = 0.2

    # Compute normalized score: -1 (failure) to +1 (success)
    if signal == "success":
        score = min(1.0, strength)
    elif signal in ("failure", "confusion"):
        score = max(-1.0, -strength)
    else:
        score = 0.0

    # Confidence: how sure are we about this signal?
    confidence = min(1.0, abs(score) * 1.5) if signal != "neutral" else 0.1

    return {
        "signal": signal,
        "score": round(score, 2),
        "confidence": round(confidence, 2),
        "strength": strength,
        "length_pref": length_pref,
        "wants_repeat": wants_repeat,
    }


# ============================================================================
# RHYTHM TRACKING — when and how does this user interact?
# ============================================================================

def _hour_bucket(hour):
    """Map hour to 4 time buckets."""
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 22:
        return "evening"
    return "night"


def update_rhythm(adaptive, message, response):
    """Update interaction rhythm data.

    Tracks:
    - time_buckets: {morning: count, afternoon: count, ...}
    - avg_message_length: exponential moving average of user message length
    - avg_response_time_sec: average time between interactions
    - interaction_hours: list of recent interaction hours (last 50)
    """
    now = datetime.now()
    bucket = _hour_bucket(now.hour)

    # Time bucket counts
    buckets = adaptive.get("time_buckets", {"morning": 0, "afternoon": 0, "evening": 0, "night": 0})
    buckets[bucket] = buckets.get(bucket, 0) + 1
    adaptive["time_buckets"] = buckets

    # Message length — exponential moving average (α=0.2)
    msg_len = len(message) if message else 0
    prev_avg = adaptive.get("avg_message_length", msg_len)
    adaptive["avg_message_length"] = round(0.8 * prev_avg + 0.2 * msg_len)

    # Response length tracking
    resp_len = len(response) if response else 0
    prev_resp = adaptive.get("avg_response_length", resp_len)
    adaptive["avg_response_length"] = round(0.8 * prev_resp + 0.2 * resp_len)

    # Interaction hours (last 50 for pattern detection)
    hours = adaptive.get("interaction_hours", [])
    hours.append(now.hour)
    adaptive["interaction_hours"] = hours[-50:]

    # Peak interaction time
    if len(hours) >= 5:
        hour_counts = Counter(hours)
        peak = hour_counts.most_common(1)[0][0]
        adaptive["peak_hour"] = peak

    # Time since last interaction
    last = adaptive.get("last_interaction_ts")
    if last:
        try:
            last_dt = datetime.fromisoformat(str(last).split('+')[0])
            gap_sec = (now - last_dt).total_seconds()
            prev_gap = adaptive.get("avg_gap_minutes", gap_sec / 60)
            adaptive["avg_gap_minutes"] = round(0.8 * prev_gap + 0.2 * (gap_sec / 60), 1)
        except (ValueError, TypeError):
            pass
    adaptive["last_interaction_ts"] = now.isoformat()

    return adaptive


# ============================================================================
# RESPONSE LENGTH ADAPTATION
# ============================================================================

def compute_preferred_length(adaptive):
    """Compute preferred response length from user behavior.

    Logic:
    - If user sends short messages (<30 chars avg), prefer short responses
    - If user explicitly asked for shorter/longer, weight that heavily
    - If user's success signals come after short responses, prefer short

    Returns: "short" | "medium" | "long"
    """
    avg_msg = adaptive.get("avg_message_length", 50)
    explicit_prefs = adaptive.get("length_feedback", [])  # list of "shorter"/"longer"

    # Start with message-length heuristic
    if avg_msg < 20:
        score = -1  # prefers short
    elif avg_msg > 80:
        score = 1   # prefers long
    else:
        score = 0   # medium

    # Explicit feedback weighs 3x
    for pref in explicit_prefs[-5:]:  # last 5 feedbacks
        if pref == "shorter":
            score -= 3
        elif pref == "longer":
            score += 3

    if score <= -2:
        return "short"
    elif score >= 2:
        return "long"
    return "medium"


# ============================================================================
# EMOTIONAL TRANSITIONS
# ============================================================================

def update_mood_transitions(adaptive, current_mood):
    """Track mood transitions for pattern detection.

    Stores last 20 mood values with timestamps for transition analysis.
    """
    mood_history = adaptive.get("mood_history", [])
    mood_history.append({
        "mood": current_mood,
        "hour": datetime.now().hour,
        "ts": datetime.now().isoformat()[:16],  # minute precision
    })
    adaptive["mood_history"] = mood_history[-20:]

    # Detect concerning patterns
    if len(mood_history) >= 3:
        last_3 = [m["mood"] for m in mood_history[-3:]]
        if all(m in ("sad", "anxious") for m in last_3):
            adaptive["mood_concern"] = True
            adaptive["mood_concern_since"] = mood_history[-3]["ts"]
        else:
            adaptive["mood_concern"] = False

    return adaptive


# ============================================================================
# TOPIC FRESHNESS — time-weighted interests
# ============================================================================

def update_topic_freshness(adaptive, topic):
    """Track topics with time decay — recent topics weigh more.

    Instead of raw counts, store timestamps of last 5 mentions per topic.
    """
    if not topic or topic == "general":
        return adaptive

    topic_times = adaptive.get("topic_times", {})
    times = topic_times.get(topic, [])
    times.append(datetime.now().isoformat()[:16])
    topic_times[topic] = times[-5:]  # keep last 5 per topic
    adaptive["topic_times"] = topic_times

    # Compute fresh interests (topics mentioned in last 7 days)
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()[:16]
    fresh = {}
    for t, ts_list in topic_times.items():
        recent = sum(1 for ts in ts_list if ts > week_ago)
        if recent > 0:
            fresh[t] = recent
    adaptive["fresh_interests"] = fresh

    return adaptive


# ============================================================================
# STT ERROR TRACKING — what words does STT get wrong for THIS user?
# ============================================================================

def track_stt_corrections(adaptive, corrections):
    """Track STT corrections per user to build personal vocabulary.

    Args:
        corrections: list of "word → correction" strings from correct_stt_output()
    """
    if not corrections:
        return adaptive

    stt_errors = adaptive.get("stt_error_counts", {})
    for corr in corrections:
        # Extract the wrong word
        parts = corr.split(" → ")
        if len(parts) == 2:
            wrong = parts[0].strip("'")
            stt_errors[wrong] = stt_errors.get(wrong, 0) + 1

    # Keep top 20 most frequent errors
    if len(stt_errors) > 20:
        sorted_errors = sorted(stt_errors.items(), key=lambda x: -x[1])
        stt_errors = dict(sorted_errors[:20])

    adaptive["stt_error_counts"] = stt_errors
    return adaptive


# ============================================================================
# DYSPHASIA / SPEECH DISORDER RHYTHM ADAPTATION
# ============================================================================

def compute_speech_patience(adaptive, communication_needs=""):
    """Compute how patient Radim should be with this specific user.

    Returns:
        dict: {
            "speech_timeout_multiplier": 1.0-3.0,
            "response_pace": "normal" | "slow" | "very_slow",
            "repeat_tolerance": 1-5 (how many repeats before escalating),
            "preferred_confirmation": "verbal" | "yes_no" | "dtmf",
        }
    """
    needs = (communication_needs or "").lower()
    avg_msg = adaptive.get("avg_message_length", 50)
    repeat_count = adaptive.get("repeat_requests", 0)
    success_rate = adaptive.get("success_rate", 0.5)

    # Base patience from communication needs
    multiplier = 1.0
    pace = "normal"
    confirm = "verbal"

    if any(n in needs for n in ["afazi", "dysartr", "dysf"]):
        multiplier = 2.5
        pace = "very_slow"
        confirm = "yes_no"  # offer simple choices
    elif any(n in needs for n in ["kokta", "parkinson", "als", "huntington"]):
        multiplier = 2.0
        pace = "slow"
        confirm = "yes_no"
    elif any(n in needs for n in ["demenc", "alzheim"]):
        multiplier = 1.5
        pace = "slow"
        confirm = "yes_no"

    # Adapt from actual behavior — if user often asks to repeat, increase patience
    if repeat_count > 5:
        multiplier = min(3.0, multiplier + 0.5)
    if avg_msg < 15:  # very short messages = may struggle to express
        multiplier = min(3.0, multiplier + 0.3)

    # If success rate is low, slow down more
    if success_rate < 0.3:
        pace = "very_slow"
        multiplier = min(3.0, multiplier + 0.5)

    return {
        "speech_timeout_multiplier": round(multiplier, 1),
        "response_pace": pace,
        "repeat_tolerance": 5 if "afazi" in needs else 3,
        "preferred_confirmation": confirm,
    }


# ============================================================================
# LANGUAGE COMPLEXITY — reduce if user struggles
# ============================================================================

def compute_language_complexity(adaptive):
    """Compute appropriate language complexity level.

    Reduces complexity when:
    - Repeated confusion (repeat_requests > 3)
    - Low success rate (< 0.4)
    - Very short messages (user can't express complex thoughts)
    - Communication needs include cognitive impairment

    Returns: "simple" | "normal"
    """
    success_rate = adaptive.get("success_rate", 0.5)
    repeats = adaptive.get("repeat_requests", 0)
    avg_msg = adaptive.get("avg_message_length", 50)
    confusion_count = adaptive.get("confusion_count", 0)

    # Score: negative = simplify
    score = 0
    if success_rate < 0.3:
        score -= 3
    elif success_rate < 0.4:
        score -= 1

    if repeats > 5:
        score -= 2
    elif repeats > 3:
        score -= 1

    if avg_msg < 15:
        score -= 1

    if confusion_count > 3:
        score -= 2

    return "simple" if score <= -2 else "normal"


# ============================================================================
# ENERGY LEVEL — time-of-day + activity patterns
# ============================================================================

def compute_energy_level(adaptive):
    """Estimate user's current energy level (0.0-1.0).

    Based on:
    - Time of day (seniors typically peak 9-11 AM)
    - Current time vs user's peak_hour
    - Recent mood patterns
    - Activity frequency today vs baseline

    Returns: float 0.0 (exhausted) to 1.0 (energetic)
    """
    now = datetime.now()
    hour = now.hour

    # Base energy curve for seniors (circadian rhythm)
    # Peak at 10 AM, low at 2 PM (post-lunch dip), moderate evening
    base_curve = {
        6: 0.4, 7: 0.5, 8: 0.7, 9: 0.85, 10: 0.9, 11: 0.85,
        12: 0.7, 13: 0.5, 14: 0.4, 15: 0.5, 16: 0.6, 17: 0.6,
        18: 0.5, 19: 0.4, 20: 0.3, 21: 0.2, 22: 0.1,
    }
    base = base_curve.get(hour, 0.2)

    # Adjust for personal peak hour
    peak = adaptive.get("peak_hour")
    if peak is not None:
        distance = abs(hour - peak)
        if distance <= 1:
            base = min(1.0, base + 0.15)
        elif distance >= 4:
            base = max(0.1, base - 0.1)

    # Mood adjustment
    mood_history = adaptive.get("mood_history", [])
    if mood_history:
        recent_moods = [m["mood"] for m in mood_history[-3:]]
        sad_count = sum(1 for m in recent_moods if m in ("sad", "anxious"))
        if sad_count >= 2:
            base = max(0.1, base - 0.2)
        elif all(m == "happy" for m in recent_moods):
            base = min(1.0, base + 0.1)

    return round(base, 2)


# ============================================================================
# TRUST SCORE — how reliable is our adaptive model for this user?
# ============================================================================

def compute_trust_score(adaptive):
    """Compute trust/confidence in our adaptive model (0.0-1.0).

    Based on:
    - Number of interactions (more data = more trust)
    - Feedback consistency (stable signals = higher trust)
    - Behavioral stability (predictable patterns = higher trust)

    Returns: float 0.0 (unreliable) to 1.0 (highly confident)
    """
    total = adaptive.get("total_adaptive_interactions", 0)

    # Data volume component (logarithmic — diminishing returns)
    if total < 3:
        return 0.1  # not enough data
    import math
    volume = min(0.4, math.log10(total) * 0.2)

    # Feedback consistency: low variance in success_rate changes
    success_rate = adaptive.get("success_rate", 0.5)
    # Closer to extremes = more consistent signal
    consistency = abs(success_rate - 0.5) * 0.6  # 0 to 0.3

    # Behavioral stability: does user have a clear peak_hour?
    hours = adaptive.get("interaction_hours", [])
    stability = 0.0
    if len(hours) >= 10:
        hour_counts = Counter(hours)
        top_count = hour_counts.most_common(1)[0][1]
        stability = min(0.3, (top_count / len(hours)) * 0.5)

    return round(min(1.0, volume + consistency + stability), 2)


# ============================================================================
# ERROR RECOVERY — simplify when communication fails
# ============================================================================

_FAILURE_THRESHOLD = 3  # consecutive failures before recovery mode

def check_error_recovery(adaptive):
    """Check if error recovery mode should activate.

    Activates when:
    - 3+ consecutive negative feedbacks
    - success_rate drops below 0.2
    - repeat_requests spike (>3 in current session)

    Returns:
        dict: {
            "active": bool,
            "actions": list of recovery actions,
            "level": 0 (none) | 1 (mild) | 2 (moderate) | 3 (maximum)
        }
    """
    success_rate = adaptive.get("success_rate", 0.5)
    repeats = adaptive.get("repeat_requests", 0)
    consecutive_failures = adaptive.get("consecutive_failures", 0)

    level = 0
    actions = []

    if consecutive_failures >= 5 or success_rate < 0.15:
        level = 3
        actions = ["yes_no_mode", "ultra_short", "very_slow_speech", "emergency_check"]
    elif consecutive_failures >= _FAILURE_THRESHOLD or success_rate < 0.25:
        level = 2
        actions = ["simple_language", "short_responses", "slow_speech", "confirm_understanding"]
    elif success_rate < 0.35 or repeats > 5:
        level = 1
        actions = ["simplify_slightly", "add_confirmation"]

    return {
        "active": level > 0,
        "level": level,
        "actions": actions,
    }


# ============================================================================
# STRUCTURED OUTPUT — for system prompt injection
# ============================================================================

def build_adaptive_state(adaptive, communication_needs=""):
    """Build structured adaptive state for system prompt.

    Returns a clean dict (not text lines) that can be:
    1. Injected into system prompt as structured context
    2. Used by TTS/voice filter for speech params
    3. Logged for analytics

    This is the canonical output of the adaptive engine.
    """
    patience = adaptive.get("speech_patience", {})
    recovery = check_error_recovery(adaptive)
    energy = compute_energy_level(adaptive)
    trust = compute_trust_score(adaptive)
    complexity = compute_language_complexity(adaptive)
    length = adaptive.get("computed_length", "medium")

    # Override from recovery mode
    if recovery["active"]:
        if recovery["level"] >= 2:
            length = "short"
            complexity = "simple"

    # Build mood state
    mood_history = adaptive.get("mood_history", [])
    mood_state = "neutral"
    mood_trend = "stable"
    mood_risk = 0.0

    if mood_history:
        recent = [m["mood"] for m in mood_history[-3:]]
        # Current state = most recent
        mood_state = recent[-1] if recent else "neutral"
        mood_map = {"happy": "positive", "neutral": "neutral", "sad": "negative", "anxious": "negative"}
        mood_state = mood_map.get(mood_state, "neutral")

        # Trend
        if len(mood_history) >= 5:
            older = [m["mood"] for m in mood_history[-5:-2]]
            newer = recent
            old_neg = sum(1 for m in older if m in ("sad", "anxious"))
            new_neg = sum(1 for m in newer if m in ("sad", "anxious"))
            if new_neg > old_neg:
                mood_trend = "declining"
            elif new_neg < old_neg:
                mood_trend = "improving"

        # Risk
        if adaptive.get("mood_concern"):
            mood_risk = 0.7
        elif mood_state == "negative":
            mood_risk = 0.4

    # Build topics
    fresh = adaptive.get("fresh_interests", {})
    short_term = sorted(fresh.keys(), key=lambda k: -fresh[k])[:5] if fresh else []

    topic_times = adaptive.get("topic_times", {})
    long_term = sorted(topic_times.keys(), key=lambda k: -len(topic_times[k]))[:5] if topic_times else []

    # Determine speech speed
    pace = patience.get("response_pace", "normal")
    if recovery["active"] and recovery["level"] >= 2:
        pace = "very_slow"

    speech_speed = "slow" if pace in ("slow", "very_slow") else "normal"

    # Determine interaction mode
    confirm_type = patience.get("preferred_confirmation", "verbal")
    if recovery["active"]:
        interaction_mode = "recovery"
    elif confirm_type == "yes_no":
        interaction_mode = "patient"
    else:
        interaction_mode = "normal"

    return {
        "feedback": {
            "score": adaptive.get("success_rate", 0.5),
            "confidence": trust,
        },
        "communication": {
            "preferred_length": length,
            "speech_speed": speech_speed,
            "patience_multiplier": patience.get("speech_timeout_multiplier", 1.0),
            "language_level": complexity,
        },
        "behavior": {
            "peak_hour": adaptive.get("peak_hour"),
            "energy_level": energy,
        },
        "mood": {
            "state": mood_state,
            "trend": mood_trend,
            "risk_level": round(mood_risk, 2),
        },
        "topics": {
            "short_term": short_term,
            "long_term": long_term,
        },
        "trust_score": trust,
        "recovery": recovery,
    }


# ============================================================================
# MASTER UPDATE — called after every interaction
# ============================================================================

def update_adaptive_profile(user_id, message, response, mood=None, topic=None,
                            stt_corrections=None, communication_needs=""):
    """Update all adaptive learning data for a user.

    Called from record_interaction() in memory_logic.py.

    Args:
        user_id: user identifier
        message: user's message text
        response: Radim's response text
        mood: detected mood (or None)
        topic: detected topic (or None)
        stt_corrections: list of STT corrections applied
        communication_needs: user's communication_needs string
    """
    try:
        from memory_helpers import db_load_learning, db_save_learning

        learning = db_load_learning(user_id)
        adaptive = learning.get("adaptive", {})

        # 1. Rhythm
        adaptive = update_rhythm(adaptive, message, response)

        # 2. Feedback detection (explicit + implicit)
        feedback = detect_feedback(message)
        if feedback["signal"] == "success":
            prev_rate = adaptive.get("success_rate", 0.5)
            adaptive["success_rate"] = round(0.85 * prev_rate + 0.15 * 1.0, 3)
            adaptive["consecutive_failures"] = 0  # reset on success
        elif feedback["signal"] in ("failure", "confusion"):
            prev_rate = adaptive.get("success_rate", 0.5)
            adaptive["success_rate"] = round(0.85 * prev_rate + 0.15 * 0.0, 3)
            adaptive["consecutive_failures"] = adaptive.get("consecutive_failures", 0) + 1
            if feedback["signal"] == "confusion":
                adaptive["confusion_count"] = adaptive.get("confusion_count", 0) + 1

        if feedback["length_pref"]:
            length_fb = adaptive.get("length_feedback", [])
            length_fb.append(feedback["length_pref"])
            adaptive["length_feedback"] = length_fb[-10:]

        if feedback["wants_repeat"]:
            adaptive["repeat_requests"] = adaptive.get("repeat_requests", 0) + 1

        # 3. Preferred response length (empirical)
        adaptive["computed_length"] = compute_preferred_length(adaptive)

        # 4. Language complexity
        adaptive["language_level"] = compute_language_complexity(adaptive)

        # 5. Mood transitions
        if mood:
            adaptive = update_mood_transitions(adaptive, mood)

        # 6. Topic freshness
        if topic:
            adaptive = update_topic_freshness(adaptive, topic)

        # 7. STT error tracking
        if stt_corrections:
            adaptive = track_stt_corrections(adaptive, stt_corrections)

        # 8. Speech patience (every 5 interactions)
        total = adaptive.get("time_buckets", {})
        total_interactions = sum(total.values()) if total else 0
        if total_interactions % 5 == 0:
            patience = compute_speech_patience(adaptive, communication_needs)
            adaptive["speech_patience"] = patience

        # 9. Energy level + trust score (lightweight, every interaction)
        adaptive["energy_level"] = compute_energy_level(adaptive)
        adaptive["trust_score"] = compute_trust_score(adaptive)

        # 10. Error recovery check
        adaptive["recovery"] = check_error_recovery(adaptive)

        # 11. Interaction counter
        adaptive["total_adaptive_interactions"] = adaptive.get("total_adaptive_interactions", 0) + 1

        # Save
        learning["adaptive"] = adaptive
        db_save_learning(user_id, learning)

        logger.debug(f"Adaptive update for {user_id}: rhythm={adaptive.get('peak_hour')}h, "
                     f"success={adaptive.get('success_rate', '?')}, "
                     f"length={adaptive.get('computed_length')}")

    except Exception as e:
        logger.debug(f"Adaptive learning error for {user_id}: {e}")


# ============================================================================
# QUERY — get adaptive data for prompt building
# ============================================================================

def get_adaptive_context(user_id):
    """Get adaptive learning context for system prompt injection.

    Returns human-readable lines to add to personalized prompt.
    Uses build_adaptive_state() for structured data, then converts to text.
    """
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(user_id)
        adaptive = learning.get("adaptive", {})

        if not adaptive or adaptive.get("total_adaptive_interactions", 0) < 3:
            return []  # not enough data yet

        state = build_adaptive_state(adaptive)
        lines = []

        # Communication style
        comm = state["communication"]
        if comm["preferred_length"] == "short":
            lines.append("- Uživatel preferuje KRÁTKÉ odpovědi (2-3 věty max)")
        elif comm["preferred_length"] == "long":
            lines.append("- Uživatel preferuje podrobné odpovědi")

        if comm["language_level"] == "simple":
            lines.append("- Používej JEDNODUCHÉ věty a slova — uživatel potřebuje srozumitelnost")

        if comm["speech_speed"] == "slow":
            lines.append("- Mluv POMALU a trpělivě — uživatel potřebuje více času")

        if comm["patience_multiplier"] >= 2.0:
            lines.append("- Nabízej jednoduché volby (ANO/NE) místo otevřených otázek")

        # Behavior
        peak = state["behavior"]["peak_hour"]
        if peak is not None:
            lines.append(f"- Nejčastěji komunikuje kolem {peak}:00")

        energy = state["behavior"]["energy_level"]
        if energy < 0.3:
            lines.append("- Uživatel má pravděpodobně nízkou energii — buď stručný a klidný")

        # Mood
        mood = state["mood"]
        if mood["risk_level"] >= 0.5:
            lines.append("- POZOR: Uživatel je opakovaně smutný/úzkostný — buď extra empatický")
        if mood["trend"] == "declining":
            lines.append("- Nálada se zhoršuje — věnuj extra pozornost emočnímu stavu")

        # Topics
        short_term = state["topics"]["short_term"]
        if short_term:
            lines.append(f"- Aktuální zájmy: {', '.join(short_term[:3])}")

        # Recovery mode
        recovery = state["recovery"]
        if recovery["active"]:
            if recovery["level"] >= 2:
                lines.append("- RECOVERY MODE: Zjednodušuj, zkracuj, ověřuj porozumění po každé větě")
            else:
                lines.append("- Mírné potíže s komunikací — přidej potvrzení porozumění")

        # Trust
        if state["trust_score"] < 0.2:
            lines.append("- Adaptivní profil je zatím nejistý — buď obecnější")

        return lines

    except Exception:
        return []


def get_adaptive_state(user_id):
    """Get full structured adaptive state (for API/analytics).

    Returns the structured dict from build_adaptive_state().
    """
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(user_id)
        adaptive = learning.get("adaptive", {})
        if not adaptive:
            return None
        return build_adaptive_state(adaptive)
    except Exception:
        return None


logger.info("Adaptive Learning v2.0 loaded — rhythm, feedback, energy, trust, recovery")
