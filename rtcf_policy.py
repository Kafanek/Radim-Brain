"""
RTCF Policy Adapter — Translates heartbeat into action
==========================================================
Maps RTCF state + beat into concrete voice/proactive modifiers
that plug directly into existing voice_filter and agent_loop interfaces.

This is where the heartbeat becomes behavior.
"""


def compute_voice_modifiers(state, beat_state):
    """Map RTCF state to voice modulation deltas.

    Returns dict compatible with voice_filter.build_radim_ssml() rtcf_voice param:
        rate_adjust: float — added to profile rate (e.g., -5 means 5% slower)
        pause_adjust_ms: int — added to profile pause
        style_hint: str or None — override style if set
        styledegree_hint: str or None — override styledegree if set
    """
    bpm = beat_state.get("bpm", 68)
    hrv = beat_state.get("hrv", 0.5)
    stability = beat_state.get("stability", 0.5)
    autonomic = beat_state.get("autonomic_mode", "balanced")

    if state == "recovery":
        # Calm, slow, warm — the system is resting
        return {
            "rate_adjust": -3,   # 3% slower
            "pause_adjust_ms": round(100 * (1.0 - hrv)),  # more pause when less coherent
            "style_hint": "friendly",
            "styledegree_hint": "2.0",
        }
    elif state == "escalation":
        # Heightened — slower for clarity, longer pauses, calmer style
        return {
            "rate_adjust": -8,   # 8% slower
            "pause_adjust_ms": round(200 * (1.0 - stability)),
            "style_hint": "empathetic" if autonomic != "sympathetic" else "calm",
            "styledegree_hint": "1.5",
        }
    else:
        # optimal_conscious — minimal intervention, natural voice
        # Slight warmth from beat
        warmth_adjust = round((beat_state.get("warmth", 0.5) - 0.5) * 4)  # [-2, +2]
        return {
            "rate_adjust": warmth_adjust,
            "pause_adjust_ms": 0,
            "style_hint": None,  # don't override
            "styledegree_hint": None,
        }


def compute_proactive_modifiers(state, beat_state):
    """Map RTCF state to agent loop sensitivity adjustments.

    Returns:
        sensitivity_adjust: float — multiplier for anomaly detection thresholds
        check_interval_adjust_s: int — seconds to add/subtract from check interval
        escalation_bias: float [0, 1] — tendency to escalate severity
    """
    autonomic = beat_state.get("autonomic_mode", "balanced")

    if state == "recovery":
        # Calm period — less sensitive, longer intervals
        return {
            "sensitivity_adjust": 0.8,    # 20% less sensitive
            "check_interval_adjust_s": 60,  # check less often
            "escalation_bias": 0.1,
        }
    elif state == "escalation":
        # Heightened — more sensitive, shorter intervals
        return {
            "sensitivity_adjust": 1.3,    # 30% more sensitive
            "check_interval_adjust_s": -60,  # check more often
            "escalation_bias": 0.7 if autonomic == "sympathetic" else 0.5,
        }
    else:
        # Optimal — standard operation
        return {
            "sensitivity_adjust": 1.0,
            "check_interval_adjust_s": 0,
            "escalation_bias": 0.3,
        }


def compute_alert_bias(state, ratio):
    """Numeric alert bias in [0, 1] for severity filtering.

    Higher = more likely to escalate observations to higher severity.
    """
    if state == "recovery":
        return max(0.0, min(1.0, 0.1 + ratio * 0.05))
    elif state == "escalation":
        return max(0.0, min(1.0, 0.5 + (ratio - 2.15) * 0.3))
    else:
        return 0.3  # neutral


def build_policy(state, psi_rtcf, ratio, beat_state, reasoning=""):
    """Assemble complete RTCF policy object.

    This is the final output of the RTCF pipeline — everything
    downstream systems need to synchronize with the heartbeat.
    """
    voice_mods = compute_voice_modifiers(state, beat_state)
    proactive_mods = compute_proactive_modifiers(state, beat_state)
    alert = compute_alert_bias(state, ratio)

    return {
        "state": state,
        "psi_rtcf": psi_rtcf,
        "ratio": ratio,
        "beat_state": beat_state,
        "voice_modifiers": voice_mods,
        "proactive_modifiers": proactive_mods,
        "alert_bias": round(alert, 4),
        "reasoning": reasoning,
    }
