"""
Radim Math + Heartbeat — CLI demo
==================================

Two modes:

1) Single-shot snapshot
   python3 -m agent.math_demo --scenario rising --persona senior

2) Live heartbeat (animated, watch the rhythm change)
   python3 -m agent.math_demo --heartbeat --scenario evolving --persona senior
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta

try:
    from .math_engine import (
        State, DomainWeights, run_engine, classify, PERSONA_WEIGHTS,
        C_HARMONY, C_ALERT, C_MAX,
    )
    from .heartbeat import Heartbeat
except ImportError:
    from math_engine import (  # type: ignore
        State, DomainWeights, run_engine, classify, PERSONA_WEIGHTS,
        C_HARMONY, C_ALERT, C_MAX,
    )
    from heartbeat import Heartbeat  # type: ignore


# ─── Synthetic scenarios ────────────────────────────────────────────────────


def _make_state(t: datetime, ce, env, soc, phy, alpha, e=0.0) -> State:
    return State(t=t, c_emotional=ce, c_environmental=env, c_social=soc,
                 c_physical=phy, alpha=alpha, e_valence=e)


def synthesize(scenario: str, n: int = 6) -> list[State]:
    """Build a 6-step (~25 min) state history for a named scenario."""
    base = datetime.utcnow().replace(microsecond=0) - timedelta(minutes=5 * (n - 1))
    history: list[State] = []
    for i in range(n):
        t = base + timedelta(minutes=5 * i)
        if scenario == "calm":
            history.append(_make_state(t, 8, 10, 8, 9, 0.30, 0.2))
        elif scenario == "rising":
            history.append(_make_state(t, 8 + i * 1.5,
                                          10 + i * 0.5,
                                          8,
                                          9 + i * 0.8,
                                          0.30 + i * 0.06))
        elif scenario == "crisis":
            history.append(_make_state(t, 20 + i * 2.5,
                                          18 + i * 2.0,
                                          15,
                                          20 + i * 1.5,
                                          0.50 + i * 0.07, -0.4))
        elif scenario == "child_overload":
            # Sensory buildup (env dominant), modest emotional, low social
            history.append(_make_state(t, 12 + i * 1.0,
                                          22 + i * 2.5,   # env spikes hardest
                                          8,
                                          15 + i * 0.5,
                                          0.40 + i * 0.08, -0.2))
        elif scenario == "recovery":
            # Started stressed, calming down
            history.append(_make_state(t, 28 - i * 2.5,
                                          25 - i * 2.0,
                                          15 + i * 0.5,
                                          25 - i * 1.5,
                                          0.70 - i * 0.08, 0.1))
        else:
            raise ValueError(f"unknown scenario: {scenario}")
    return history


# ─── Pretty printing ────────────────────────────────────────────────────────

GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def mode_color(mode: str) -> str:
    return {"HARMONY": GREEN, "ALERT": YELLOW, "CRISIS": RED}.get(mode, "")


def bar(value: float, max_val: float = C_MAX, width: int = 24) -> str:
    """Unicode bar with mode-colored segments."""
    n = int(round(value / max_val * width))
    cells = []
    for i in range(width):
        # Segment colored by which mode this position represents
        seg_value = (i + 1) / width * max_val
        c = mode_color(classify(seg_value)) if i < n else ""
        cells.append(f"{c}█{RESET}" if i < n else f"{DIM}·{RESET}")
    return "".join(cells)


def print_snapshot(snap, persona: str, scenario: str) -> None:
    color = mode_color(snap.mode)
    print(f"\n{BOLD}🧠 Radim Math Engine{RESET}  "
          f"{DIM}persona={persona}  scenario={scenario}{RESET}\n")
    print(f"  {BOLD}Current{RESET}    "
          f"C={snap.c_total:5.2f}  α={snap.state.alpha:.2f}   "
          f"{color}{BOLD}{snap.mode}{RESET}")
    print(f"  {BOLD}Trend{RESET}      "
          f"ΔC_emot={snap.trend.c_emotional:+.2f}/step   "
          f"Δα={snap.trend.alpha:+.3f}/step")
    print()
    print(f"  {BOLD}30-min horizon{RESET}  (each cell = +5 min)")
    for i, s in enumerate(snap.horizon_30min):
        c = s.total(PERSONA_WEIGHTS[persona]
                    if persona in PERSONA_WEIGHTS else DomainWeights())
        m = classify(c)
        col = mode_color(m)
        marker = " ←peak" if i + 1 == snap.preemptive.peak_at_minute // 5 else ""
        print(f"     +{(i+1)*5:2d}min  C={c:5.2f}  {bar(c)}  "
              f"{col}{m}{RESET}{marker}")
    print()
    if snap.preemptive.crosses_up:
        print(f"  {RED}{BOLD}⚠️  PREEMPTIVE ALERT{RESET} "
              f"{snap.preemptive.current_mode} → "
              f"{mode_color(snap.preemptive.predicted_mode)}"
              f"{snap.preemptive.predicted_mode}{RESET} "
              f"in {snap.preemptive.peak_at_minute} min — act now\n")
    elif snap.preemptive.crosses_down:
        print(f"  {GREEN}{BOLD}✓ Recovery trending{RESET} — "
              f"horizon dips into "
              f"{mode_color('HARMONY')}HARMONY{RESET}\n")
    print(f"  {BOLD}🎙️  Speech params for Azure SSML{RESET}")
    print(f"     empathy={snap.speech.empathy:.2f}   "
          f"rate={snap.speech.rate:.3f}   "
          f"pitch={snap.speech.pitch:+.2f}st   "
          f"pause={snap.speech.pause_ms}ms")
    print(f"     {DIM}prosody  →  "
          f"<prosody {snap.speech.to_ssml_prosody()}>...</prosody>{RESET}\n")


def snapshot_to_json(snap, persona: str) -> dict:
    weights = (PERSONA_WEIGHTS[persona]
               if persona in PERSONA_WEIGHTS else DomainWeights())
    return {
        "persona": persona,
        "current": {
            "c_total": round(snap.c_total, 2),
            "mode": snap.mode,
            "alpha": round(snap.state.alpha, 3),
            "domains": {
                "emotional": round(snap.state.c_emotional, 2),
                "environmental": round(snap.state.c_environmental, 2),
                "social": round(snap.state.c_social, 2),
                "physical": round(snap.state.c_physical, 2),
            },
        },
        "trend": {
            "c_emotional": round(snap.trend.c_emotional, 3),
            "alpha": round(snap.trend.alpha, 3),
        },
        "horizon_30min": [
            {
                "t_offset_min": (i + 1) * 5,
                "c_total": round(s.total(weights), 2),
                "mode": classify(s.total(weights)),
            }
            for i, s in enumerate(snap.horizon_30min)
        ],
        "preemptive": {
            "predicted_mode": snap.preemptive.predicted_mode,
            "crosses_up": snap.preemptive.crosses_up,
            "crosses_down": snap.preemptive.crosses_down,
            "peak_c": round(snap.preemptive.peak_c, 2),
            "peak_at_minute": snap.preemptive.peak_at_minute,
        },
        "speech": {
            "empathy": round(snap.speech.empathy, 2),
            "rate": round(snap.speech.rate, 3),
            "pitch": round(snap.speech.pitch, 2),
            "pause_ms": snap.speech.pause_ms,
            "ssml_prosody": snap.speech.to_ssml_prosody(),
        },
    }


# ─── Heartbeat live demo ────────────────────────────────────────────────────


def heartbeat_demo(persona: str, scenario: str, beats: int = 8,
                   tick_seconds: float = 2.0) -> None:
    """Animated demo: heartbeat ticks, scenario evolves, cadence adapts.

    Compresses real-world cadence (300 s / 60 s / 30 s) into
    `tick_seconds` for visualization. The MODE cadence ratio is
    preserved so you can see the rhythm change."""
    print(f"\n{BOLD}💓 Radim Heartbeat — live demo{RESET}\n"
          f"   {DIM}persona={persona}  scenario={scenario}  "
          f"beats={beats}  (1 second of demo = ~150 seconds of real life){RESET}\n")

    # Build evolving series: extends as time progresses
    base_history = synthesize(scenario, n=4)

    # Closure over a "wall clock" that advances each beat
    state_holder = {"hist": list(base_history), "step": 0}

    def provider():
        return state_holder["hist"]

    # Make the demo cadence visible: scale real cadences to seconds
    # HARMONY=300s → 6s, ALERT=60s → 1.2s, CRISIS=30s → 0.6s
    visual_cadence = {
        "HARMONY": int(round(tick_seconds * 3)),
        "ALERT":   int(round(tick_seconds * 0.6)),
        "CRISIS":  int(round(tick_seconds * 0.3)),
    }
    # Floor at 1 sec so we don't spin
    for k in visual_cadence:
        visual_cadence[k] = max(1, visual_cadence[k])

    hb = Heartbeat(persona=persona, state_provider=provider,
                   cadence=visual_cadence, quiet_hours=None)

    def listener(snap):
        col = mode_color(snap.mode)
        pre = ""
        if snap.preemptive.crosses_up:
            pre = f"  {RED}⚠ preemptive→{snap.preemptive.predicted_mode}{RESET}"
        print(f"  {DIM}beat {hb.stats.total_beats:>2}{RESET}  "
              f"{col}● {snap.mode:<7}{RESET}  "
              f"C={snap.c_total:5.2f}  α={snap.state.alpha:.2f}  "
              f"rate={snap.speech.rate:.2f}  pause={snap.speech.pause_ms}ms{pre}")

    hb.subscribe(listener)
    hb.start()
    try:
        # Each demo "second" we extend the history with a new state
        # (as if 5 real-world minutes passed and a fresh sample arrived)
        last_state = state_holder["hist"][-1]
        for i in range(beats):
            time.sleep(tick_seconds)
            state_holder["step"] += 1
            # Evolve the scenario by appending a new sample
            new_history = synthesize(scenario, n=4 + state_holder["step"] + 1)
            state_holder["hist"] = new_history
        # Wait for last beat to complete
        time.sleep(tick_seconds)
    finally:
        hb.stop()
        print(f"\n  {DIM}heartbeat stopped — "
              f"total beats={hb.stats.total_beats}, "
              f"mode counts={hb.stats.mode_counts}, "
              f"preemptive={hb.stats.preemptive_count}{RESET}\n")


# ─── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="rising",
                   choices=["calm", "rising", "crisis",
                            "child_overload", "recovery"])
    p.add_argument("--persona", default="senior",
                   choices=list(PERSONA_WEIGHTS.keys()))
    p.add_argument("--json", action="store_true",
                   help="Emit JSON snapshot only (machine-readable)")
    p.add_argument("--heartbeat", action="store_true",
                   help="Run live heartbeat demo (animated)")
    p.add_argument("--beats", type=int, default=8,
                   help="Number of beats for heartbeat demo")
    args = p.parse_args()

    if args.heartbeat:
        heartbeat_demo(args.persona, args.scenario, beats=args.beats)
        return 0

    history = synthesize(args.scenario)
    weights = PERSONA_WEIGHTS[args.persona]
    snap = run_engine(history, weights)

    if args.json:
        out = snapshot_to_json(snap, args.persona)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print_snapshot(snap, args.persona, args.scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main())
