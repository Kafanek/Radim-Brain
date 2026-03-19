"""
Radim Core Engine v2.0
======================
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
# CONFIDENCE GATING — how confident is Radim in THIS response context?
# ============================================================================

def compute_confidence_score(adaptive):
    """Compute confidence in current interaction context (0.0-1.0).

    Combines:
    - Trust score (long-term model reliability)
    - Recent feedback consistency (short-term signal quality)
    - Data freshness (stale data = lower confidence)

    If < 0.5: simplify, shorten, add confirmations.
    """
    trust = adaptive.get("trust_score", 0.1)
    success_rate = adaptive.get("success_rate", 0.5)
    total = adaptive.get("total_adaptive_interactions", 0)
    consecutive_failures = adaptive.get("consecutive_failures", 0)

    # Base from trust
    base = trust * 0.5  # max 0.5 from trust alone

    # Recent feedback signal (success_rate near extremes = clear signal)
    if success_rate > 0.7:
        base += 0.3
    elif success_rate > 0.5:
        base += 0.15
    elif success_rate < 0.3:
        base -= 0.1

    # Penalize consecutive failures heavily
    if consecutive_failures >= 3:
        base -= 0.2
    elif consecutive_failures >= 1:
        base -= 0.05

    # Data volume bonus
    if total >= 20:
        base += 0.1
    elif total < 5:
        base -= 0.15

    return round(max(0.0, min(1.0, base)), 2)


# ============================================================================
# FATIGUE MODEL — detect when user is getting tired
# ============================================================================

def compute_fatigue_level(adaptive):
    """Estimate user fatigue (0.0=fresh, 1.0=exhausted).

    Based on:
    - Session duration (interactions in last 30 min)
    - Time of day (late = more fatigue)
    - Message length trend (shorter over time = fatigue)
    - Energy level (low energy = higher fatigue)

    If > 0.6: suggest break, reduce complexity, go passive.
    """
    now = datetime.now()
    hour = now.hour

    # Time-of-day fatigue (seniors tire in afternoon/evening)
    time_fatigue = 0.0
    if hour >= 20:
        time_fatigue = 0.4
    elif hour >= 17:
        time_fatigue = 0.2
    elif 13 <= hour <= 15:  # post-lunch dip
        time_fatigue = 0.15

    # Session intensity: recent interactions
    interaction_hours = adaptive.get("interaction_hours", [])
    recent_count = sum(1 for h in interaction_hours[-10:] if abs(h - hour) <= 1)
    session_fatigue = min(0.3, recent_count * 0.06)  # 5+ recent = 0.3

    # Message length decline (getting shorter = tiring)
    avg_msg = adaptive.get("avg_message_length", 50)
    length_fatigue = 0.0
    if avg_msg < 10:
        length_fatigue = 0.15
    elif avg_msg < 20:
        length_fatigue = 0.05

    # Energy inverse
    energy = adaptive.get("energy_level", 0.5)
    energy_fatigue = max(0.0, (1.0 - energy) * 0.2)

    total_fatigue = time_fatigue + session_fatigue + length_fatigue + energy_fatigue
    return round(min(1.0, total_fatigue), 2)


# ============================================================================
# RADIM SCORE — core composite metric
# ============================================================================

def compute_radim_score(adaptive):
    """Compute Radim Score (0.0-1.0) — the single metric for senior wellbeing.

    Weights:
    - feedback_score:    0.25 (how well communication works)
    - trust_score:       0.20 (model reliability)
    - mood risk:         0.20 (inverse — low risk = good)
    - energy_level:      0.15 (current energy)
    - fatigue:           0.20 (inverse — low fatigue = good)

    < 0.4 → alert caregiver
    < 0.3 → high priority alert
    """
    feedback = adaptive.get("success_rate", 0.5)
    trust = adaptive.get("trust_score", 0.3)
    energy = adaptive.get("energy_level", 0.5)
    fatigue = compute_fatigue_level(adaptive)

    # Mood risk (from mood_concern flag + recent mood history)
    mood_risk = 0.0
    if adaptive.get("mood_concern"):
        mood_risk = 0.7
    else:
        mood_history = adaptive.get("mood_history", [])
        if mood_history:
            recent = [m["mood"] for m in mood_history[-3:]]
            neg_count = sum(1 for m in recent if m in ("sad", "anxious"))
            mood_risk = neg_count * 0.25

    score = (
        feedback * 0.25 +
        trust * 0.20 +
        (1.0 - mood_risk) * 0.20 +
        energy * 0.15 +
        (1.0 - fatigue) * 0.20
    )
    return round(max(0.0, min(1.0, score)), 2)


# ============================================================================
# ALERT SYSTEM — graduated alerts based on radim_score + mood
# ============================================================================

def check_alerts(adaptive):
    """Check if any alerts should fire.

    Returns list of alert dicts, each with:
    - type: "caregiver" | "high_priority" | "check_user" | "fatigue_break"
    - reason: human-readable string
    - priority: 1 (low) to 5 (critical)
    """
    alerts = []
    radim_score = adaptive.get("radim_score", 0.5)
    mood_risk = 0.0

    if adaptive.get("mood_concern"):
        mood_risk = 0.7
    else:
        mood_history = adaptive.get("mood_history", [])
        if mood_history:
            recent = [m["mood"] for m in mood_history[-3:]]
            mood_risk = sum(1 for m in recent if m in ("sad", "anxious")) * 0.25

    fatigue = adaptive.get("fatigue_level", 0.0)

    # Critical: very low radim score
    if radim_score < 0.3:
        alerts.append({
            "type": "high_priority",
            "reason": f"Radim skóre kriticky nízké ({radim_score}). Kontaktujte pečovatele.",
            "priority": 5,
        })
    elif radim_score < 0.4:
        alerts.append({
            "type": "caregiver",
            "reason": f"Radim skóre nízké ({radim_score}). Doporučujeme kontrolu.",
            "priority": 3,
        })

    # Mood risk
    if mood_risk > 0.7:
        alerts.append({
            "type": "high_priority",
            "reason": "Opakovaně negativní nálada. Zvažte osobní kontakt.",
            "priority": 4,
        })

    # Fatigue
    if fatigue > 0.7:
        alerts.append({
            "type": "fatigue_break",
            "reason": "Uživatel je pravděpodobně unavený. Radim navrhne přestávku.",
            "priority": 2,
        })

    return alerts


# ============================================================================
# IOT ACTIVITY SCORE — prepare for sensor integration
# ============================================================================

def compute_activity_score(sensor_data):
    """Compute activity score from IoT sensor data (0.0-1.0).

    Input:
        sensor_data: {
            "motion": bool,         # motion detected right now
            "door": bool,           # door opened recently
            "presence": bool,       # person in room
            "last_activity_minutes": int  # minutes since last activity
        }

    Returns: float 0.0 (inactive) to 1.0 (active)
    """
    if not sensor_data or not isinstance(sensor_data, dict):
        return None  # no IoT data available

    score = 0.0

    if sensor_data.get("motion"):
        score += 0.4
    if sensor_data.get("door"):
        score += 0.2
    if sensor_data.get("presence"):
        score += 0.2

    last_min = sensor_data.get("last_activity_minutes", 999)
    if last_min < 5:
        score += 0.2
    elif last_min < 30:
        score += 0.1
    elif last_min > 120:
        score -= 0.2  # prolonged inactivity is concerning

    return round(max(0.0, min(1.0, score)), 2)


# ============================================================================
# SOFT ADAPTATION — gradual adjustment without hard recovery
# ============================================================================

def compute_soft_adaptation(adaptive):
    """Compute soft adaptation parameters when feedback is mildly negative.

    Differs from error recovery: soft adaptation is gradual, not a hard switch.
    Applies when feedback_score 0.3-0.5 (below average but not critical).

    Returns dict with adjustment factors.
    """
    feedback = adaptive.get("success_rate", 0.5)
    confidence = adaptive.get("confidence_score", 0.5)

    if feedback >= 0.5 and confidence >= 0.5:
        return {"active": False}

    # Soft adjustments
    length_adjust = 0  # negative = shorten
    speed_adjust = 0   # positive = slower
    complexity_adjust = 0  # negative = simpler

    if feedback < 0.5:
        length_adjust -= 1
        speed_adjust += 1
    if feedback < 0.4:
        length_adjust -= 1
        complexity_adjust -= 1
    if confidence < 0.5:
        complexity_adjust -= 1
        speed_adjust += 1

    return {
        "active": True,
        "length_adjust": length_adjust,     # -2 to 0
        "speed_adjust": speed_adjust,       # 0 to +2
        "complexity_adjust": complexity_adjust,  # -2 to 0
        "add_confirmation": confidence < 0.5 or feedback < 0.4,
    }


# ============================================================================
# STRUCTURED OUTPUT — for system prompt injection
# ============================================================================

def build_adaptive_state(adaptive, communication_needs=""):
    """Build structured adaptive state — canonical output of Radim Core Engine.

    Used for:
    1. System prompt injection (natural language)
    2. TTS/voice filter params
    3. API response / analytics
    4. Agent loop alert decisions
    """
    patience = adaptive.get("speech_patience", {})
    recovery = check_error_recovery(adaptive)
    energy = compute_energy_level(adaptive)
    trust = compute_trust_score(adaptive)
    confidence = compute_confidence_score(adaptive)
    fatigue = compute_fatigue_level(adaptive)
    complexity = compute_language_complexity(adaptive)
    length = adaptive.get("computed_length", "medium")
    soft = compute_soft_adaptation(adaptive)

    # Layer 1: Soft adaptation (gradual)
    if soft["active"] and not recovery["active"]:
        if soft["length_adjust"] <= -2:
            length = "short"
        if soft["complexity_adjust"] <= -1:
            complexity = "simple"

    # Layer 2: Hard recovery (overrides everything)
    if recovery["active"]:
        if recovery["level"] >= 2:
            length = "short"
            complexity = "simple"

    # Layer 3: Confidence gating
    if confidence < 0.5:
        if length == "long":
            length = "medium"
        if complexity != "simple" and confidence < 0.3:
            complexity = "simple"

    # Layer 4: Fatigue override
    if fatigue > 0.6:
        if length != "short":
            length = "short"

    # Build mood state
    mood_history = adaptive.get("mood_history", [])
    mood_state = "neutral"
    mood_trend = "stable"
    mood_risk = 0.0

    if mood_history:
        recent = [m["mood"] for m in mood_history[-3:]]
        mood_state = recent[-1] if recent else "neutral"
        mood_map = {"happy": "positive", "neutral": "neutral", "sad": "negative", "anxious": "negative"}
        mood_state = mood_map.get(mood_state, "neutral")

        if len(mood_history) >= 5:
            older = [m["mood"] for m in mood_history[-5:-2]]
            newer = recent
            old_neg = sum(1 for m in older if m in ("sad", "anxious"))
            new_neg = sum(1 for m in newer if m in ("sad", "anxious"))
            if new_neg > old_neg:
                mood_trend = "declining"
            elif new_neg < old_neg:
                mood_trend = "improving"

        if adaptive.get("mood_concern"):
            mood_risk = 0.7
        elif mood_state == "negative":
            mood_risk = 0.4

    # Build topics
    fresh = adaptive.get("fresh_interests", {})
    short_term = sorted(fresh.keys(), key=lambda k: -fresh[k])[:5] if fresh else []
    topic_times = adaptive.get("topic_times", {})
    long_term = sorted(topic_times.keys(), key=lambda k: -len(topic_times[k]))[:5] if topic_times else []

    # Determine speech speed (layered)
    pace = patience.get("response_pace", "normal")
    if recovery["active"] and recovery["level"] >= 2:
        pace = "very_slow"
    elif soft["active"] and soft.get("speed_adjust", 0) >= 2:
        pace = "slow"
    elif fatigue > 0.6:
        pace = "slow"
    speech_speed = "slow" if pace in ("slow", "very_slow") else "normal"

    # Confirmation level
    confirm_level = "normal"
    if recovery["active"] or confidence < 0.4:
        confirm_level = "high"
    elif soft.get("add_confirmation") or trust < 0.4:
        confirm_level = "high"

    # Energy mode
    energy_mode = "active"
    if fatigue > 0.6 or energy < 0.3:
        energy_mode = "passive"

    # Interaction mode
    if recovery["active"]:
        interaction_mode = "recovery"
    elif fatigue > 0.7:
        interaction_mode = "passive"
    elif patience.get("preferred_confirmation") == "yes_no":
        interaction_mode = "patient"
    else:
        interaction_mode = "normal"

    # Radim score
    radim_score = adaptive.get("radim_score", compute_radim_score(adaptive))

    # Alerts
    alerts = check_alerts(adaptive)

    return {
        "feedback": {
            "score": adaptive.get("success_rate", 0.5),
            "confidence": confidence,
        },
        "communication": {
            "preferred_length": length,
            "speech_speed": speech_speed,
            "patience_multiplier": patience.get("speech_timeout_multiplier", 1.0),
            "language_level": complexity,
            "confirmation_level": confirm_level,
        },
        "behavior": {
            "peak_hour": adaptive.get("peak_hour"),
            "energy_level": energy,
            "energy_mode": energy_mode,
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
        "confidence_score": confidence,
        "fatigue_level": fatigue,
        "radim_score": radim_score,
        "recovery": recovery,
        "soft_adaptation": soft,
        "interaction_mode": interaction_mode,
        "alerts": alerts,
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

        # 9. Core metrics (every interaction)
        adaptive["energy_level"] = compute_energy_level(adaptive)
        adaptive["trust_score"] = compute_trust_score(adaptive)
        adaptive["confidence_score"] = compute_confidence_score(adaptive)
        adaptive["fatigue_level"] = compute_fatigue_level(adaptive)
        adaptive["radim_score"] = compute_radim_score(adaptive)

        # 10. Error recovery + soft adaptation
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

        # Confirmation level
        if state["communication"].get("confirmation_level") == "high":
            lines.append("- Ověřuj porozumění: 'Rozumíte mi?' nebo 'Je to jasné?'")

        # Fatigue
        fatigue = state.get("fatigue_level", 0)
        if fatigue > 0.7:
            lines.append("- Uživatel je UNAVENÝ — navrhni přestávku, buď maximálně stručný")
        elif fatigue > 0.5:
            lines.append("- Uživatel začíná být unavený — zkrať odpovědi")

        # Energy mode
        if state["behavior"].get("energy_mode") == "passive":
            lines.append("- PASIVNÍ REŽIM: Uživatel má nízkou energii — nepokládej otázky, jen odpovídej")

        # Recovery mode
        recovery = state["recovery"]
        if recovery["active"]:
            if recovery["level"] >= 2:
                lines.append("- RECOVERY MODE: Zjednodušuj, zkracuj, ověřuj porozumění po každé větě")
            else:
                lines.append("- Mírné potíže s komunikací — přidej potvrzení porozumění")

        # Radim score warning
        radim = state.get("radim_score", 0.5)
        if radim < 0.3:
            lines.append("- ⚠ KRITICKÝ STAV: Radim skóre velmi nízké — maximální opatrnost a empatie")
        elif radim < 0.4:
            lines.append("- Nízké Radim skóre — buď extra pozorný a klidný")

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


logger.info("Radim Core Engine v2.0 loaded — confidence, fatigue, radim_score, alerts, IoT")
