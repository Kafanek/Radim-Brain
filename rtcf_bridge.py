"""
RTCF Bridge — The clock source integration
==============================================
Maps existing brain inputs to RTCF inputs, runs the full pipeline,
and enriches compute_psi_state() output with the heartbeat.

This is the ONLY file that imports both brain_* and rtcf_* modules.
All other RTCF files are self-contained math.

Feature flag: ENABLE_RTCF (env var, default: false)
"""

import os
import time
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# FEATURE FLAG
# ═══════════════════════════════════════════════════════════

ENABLE_RTCF = os.environ.get("ENABLE_RTCF", "false").lower() == "true"

# ═══════════════════════════════════════════════════════════
# PER-USER Ψ(t-1) CACHE (for ratio computation)
# ═══════════════════════════════════════════════════════════
# Same TTL pattern as brain_speech._early_psi_cache

_PSI_CACHE_TTL = 1800  # 30 minutes
_psi_previous = {}      # {user_id: (psi_rtcf_value, timestamp)}


def _get_previous_psi(user_id):
    """Get cached Psi_RTCF(t-1) for ratio computation."""
    if not user_id or user_id not in _psi_previous:
        return None
    val, ts = _psi_previous[user_id]
    if time.time() - ts > _PSI_CACHE_TTL:
        del _psi_previous[user_id]
        return None
    return val


def _set_previous_psi(user_id, psi_value):
    """Cache current Psi_RTCF for next ratio computation."""
    if not user_id:
        return
    now = time.time()
    _psi_previous[user_id] = (psi_value, now)
    # Evict stale entries (max 200 users cached)
    if len(_psi_previous) > 200:
        cutoff = now - _PSI_CACHE_TTL
        stale = [k for k, (_, ts) in _psi_previous.items() if ts < cutoff]
        for k in stale:
            del _psi_previous[k]


# ═══════════════════════════════════════════════════════════
# INPUT MAPPING — Brain → RTCF
# ═══════════════════════════════════════════════════════════

def _map_brain_to_rtcf(C, alpha, psi_state, C_MAX=40.0):
    """Map existing brain state to RTCF normalized [0,1] inputs.

    Args:
        C: consciousness value (0-40)
        alpha: emotional activation (0-1)
        psi_state: dict from compute_psi_state()
        C_MAX: max consciousness value

    Returns:
        dict with all 13 RTCF input fields, normalized [0,1]
    """
    C_norm = max(0.0, min(1.0, C / C_MAX))
    E = psi_state.get("empathy", {}).get("E", 0.5)
    S = psi_state.get("psi", {}).get("S", 0.0)

    return {
        "timestamp": time.time(),
        "n": max(1, min(14, round(C_norm * 14))),
        "risk": C_norm,
        "threat": max(0.0, min(1.0, alpha)),
        "trust": max(0.0, min(1.0, E)),
        "safety": max(0.0, min(1.0, E * 0.8 + (1.0 - alpha) * 0.2)),
        "load": max(0.0, min(1.0, C_norm * 0.6 + S * 0.4)),
        "recovery": max(0.0, min(1.0, 1.0 - C_norm)),
        "anomaly": max(0.0, min(1.0, alpha)),
        "uncertainty": max(0.0, min(1.0, S)),
        # Extension points — will be wired to memory_logic / circadian
        "contradiction": 0.0,
        "history_mismatch": 0.0,
        "context_deviation": 0.0,
    }


# ═══════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

def enhance_with_rtcf(psi_state, C, alpha, user_id=None):
    """Enhance compute_psi_state() output with RTCF heartbeat.

    This is the clock source — it adds a living pulse to the brain state.

    Args:
        psi_state: dict from compute_psi_state() (returned unchanged on failure)
        C: consciousness value (0-40)
        alpha: emotional activation (0-1)
        user_id: optional, for per-user Psi(t-1) caching

    Returns:
        psi_state enriched with 'rtcf' key containing full policy object
    """
    if not ENABLE_RTCF:
        return psi_state

    try:
        from rtcf_beat import compute_beat_state
        from rtcf_coherence import compute_coherence_full
        from rtcf_policy import build_policy

        # 1. Map brain inputs to RTCF inputs
        inputs = _map_brain_to_rtcf(C, alpha, psi_state)

        # 2. Compute BeatState (the heartbeat)
        beat = compute_beat_state(
            risk=inputs["risk"],
            pain=(inputs["risk"] + inputs["anomaly"]) / 2.0,
            intuition=1.0 - inputs["uncertainty"],
            load=inputs["load"],
            recovery=inputs["recovery"],
            threat=inputs["threat"],
            trust=inputs["trust"],
            safety=inputs["safety"],
        )

        # 3. Compute Psi_RTCF + ratio + state
        psi_prev = _get_previous_psi(user_id)
        coherence = compute_coherence_full(
            t=inputs["timestamp"],
            n=inputs["n"],
            psi_previous=psi_prev,
        )

        # 4. Cache for next ratio computation
        _set_previous_psi(user_id, coherence["psi_rtcf"])

        # 5. Build reasoning string
        reasoning = (
            f"n={coherence['n']}, "
            f"H={coherence['components']['harmony']:.2f}, "
            f"R={coherence['components']['radim']:.2f}, "
            f"P={coherence['components']['crisis']:.2f}, "
            f"T={coherence['components']['temporal']:.2f}, "
            f"BPM={beat['bpm']}, "
            f"HRV={beat['hrv']}, "
            f"autonomic={beat['autonomic_mode']}, "
            f"ratio={coherence['ratio']:.3f} → {coherence['state']}"
        )

        # 6. Assemble policy
        policy = build_policy(
            state=coherence["state"],
            psi_rtcf=coherence["psi_rtcf"],
            ratio=coherence["ratio"],
            beat_state=beat,
            reasoning=reasoning,
        )

        # 7. Enrich result — add as sibling key, never overwrite existing data
        psi_state["rtcf"] = policy

        logger.debug(f"RTCF [{user_id or 'anon'}]: {coherence['state']} "
                      f"ψ={coherence['psi_rtcf']:.2f} r={coherence['ratio']:.3f} "
                      f"BPM={beat['bpm']}")

    except Exception as e:
        # Graceful degradation — never break the existing pipeline
        logger.warning(f"RTCF non-fatal error: {e}")

    return psi_state


# ═══════════════════════════════════════════════════════════
# STANDALONE API (for direct RTCF computation without brain)
# ═══════════════════════════════════════════════════════════

def compute_rtcf_standalone(inputs):
    """Compute RTCF from raw normalized inputs (without brain_core).

    Args:
        inputs: dict with 13 RTCF input fields (all [0,1] + timestamp + n)

    Returns:
        dict with full RTCF policy object
    """
    from rtcf_beat import compute_beat_state
    from rtcf_coherence import compute_coherence_full
    from rtcf_policy import build_policy

    beat = compute_beat_state(
        risk=inputs.get("risk", 0.0),
        pain=(inputs.get("risk", 0.0) + inputs.get("anomaly", 0.0)) / 2.0,
        intuition=1.0 - inputs.get("uncertainty", 0.5),
        load=inputs.get("load", 0.0),
        recovery=inputs.get("recovery", 0.5),
        threat=inputs.get("threat", 0.0),
        trust=inputs.get("trust", 0.5),
        safety=inputs.get("safety", 0.5),
    )

    coherence = compute_coherence_full(
        t=inputs.get("timestamp", time.time()),
        n=inputs.get("n", 5),
        psi_previous=inputs.get("psi_previous"),
    )

    reasoning = (
        f"standalone: n={coherence['n']}, "
        f"BPM={beat['bpm']}, {beat['autonomic_mode']}, "
        f"ratio={coherence['ratio']:.3f} → {coherence['state']}"
    )

    return build_policy(
        state=coherence["state"],
        psi_rtcf=coherence["psi_rtcf"],
        ratio=coherence["ratio"],
        beat_state=beat,
        reasoning=reasoning,
    )
