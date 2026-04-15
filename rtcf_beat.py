"""
RTCF Vital Beat Engine — The heartbeat
=========================================
Computes synthetic vital signs (BPM, HRV) and autonomic mode
from normalized [0,1] inputs. This is NOT real medical data —
it's a metaphorical heartbeat that drives the system's rhythm.

BPM: 68 + 12*risk + 10*pain + 8*intuition + 6*load - 10*recovery  [50-110]
HRV: inverse of threat + load, normalized [0, 1]
Autonomic: parasympathetic / balanced / sympathetic
"""

from rtcf_constants import (
    BPM_BASE, BPM_MIN, BPM_MAX,
    BPM_RISK, BPM_PAIN, BPM_INTUITION, BPM_LOAD, BPM_RECOVERY,
)


def compute_bpm(risk=0.0, pain=0.0, intuition=0.0, load=0.0, recovery=0.0):
    """Compute synthetic BPM from normalized inputs.

    All inputs in [0, 1]. Output clamped to [50, 110].
    """
    raw = (BPM_BASE
           + BPM_RISK * risk
           + BPM_PAIN * pain
           + BPM_INTUITION * intuition
           + BPM_LOAD * load
           + BPM_RECOVERY * recovery)
    return max(BPM_MIN, min(BPM_MAX, round(raw)))


def compute_hrv(threat=0.0, load=0.0):
    """Heart rate variability — inverse of activation. Returns [0, 1].

    High HRV = calm, coherent. Low HRV = stressed, reactive.
    """
    raw = 1.0 - 0.5 * threat - 0.5 * load
    return max(0.0, min(1.0, round(raw, 4)))


def classify_autonomic_mode(risk=0.0, pain=0.0, threat=0.0, trust=0.0, safety=0.0):
    """Classify autonomic nervous system state.

    Returns one of: 'parasympathetic', 'balanced', 'sympathetic'

    Logic:
      activation = (risk + pain + threat) / 3
      calm = (trust + safety) / 2
      If calm dominates → parasympathetic (rest & digest)
      If activation dominates → sympathetic (fight or flight)
      Otherwise → balanced
    """
    activation = (risk + pain + threat) / 3.0
    calm = (trust + safety) / 2.0

    if calm > activation + 0.15:
        return "parasympathetic"
    elif activation > calm + 0.15:
        return "sympathetic"
    else:
        return "balanced"


def compute_beat_state(risk=0.0, pain=0.0, intuition=0.0, load=0.0,
                       recovery=0.0, threat=0.0, trust=0.0, safety=0.0):
    """Full BeatState computation — the heartbeat snapshot.

    All inputs normalized [0, 1].

    Returns:
        dict with bpm, hrv, arousal, stability, warmth, presence, autonomic_mode
    """
    bpm = compute_bpm(risk, pain, intuition, load, recovery)
    hrv = compute_hrv(threat, load)
    autonomic = classify_autonomic_mode(risk, pain, threat, trust, safety)

    # Derived metrics
    arousal = max(0.0, min(1.0, (risk + threat + pain) / 3.0))
    stability = max(0.0, min(1.0, hrv * (1.0 - arousal)))
    warmth = max(0.0, min(1.0, (trust + safety) / 2.0))
    presence = max(0.0, min(1.0, 1.0 - abs(0.5 - arousal) * 2.0))
    # presence peaks when arousal is moderate (0.5) — fully engaged

    return {
        "bpm": bpm,
        "hrv": round(hrv, 4),
        "arousal": round(arousal, 4),
        "stability": round(stability, 4),
        "warmth": round(warmth, 4),
        "presence": round(presence, 4),
        "autonomic_mode": autonomic,
    }
