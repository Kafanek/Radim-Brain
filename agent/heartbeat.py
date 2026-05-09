"""
Radim Heartbeat — adaptivní rytmus agenta
==========================================

The "heart" of Radim: a clock that ticks faster when arousal rises and
slower when everything is calm. Each tick produces an EngineSnapshot
(state + trend + prediction + speech params + preemptive flag).

Cadence by mode (driven by the math engine's classify()):

    HARMONY  → 300 s  (5 min — ambient, low-frequency baseline)
    ALERT    →  60 s  (1 min — vigilant, watch the trend)
    CRISIS   →  30 s  (urgent, near real-time)

Plus:
- Preemptive override: if 30-min horizon predicts upward crossing,
  cadence drops to the predicted-mode interval immediately
- Quiet hours: optional minimum interval (e.g. don't tick faster than
  5 min between 22:00–07:00 unless CRISIS)
- Listeners: subscribe to receive EngineSnapshot on each tick

Usage:

    hb = Heartbeat(persona="senior", state_provider=collect_state)
    hb.subscribe(lambda snap: print(snap.mode))
    hb.start()       # background thread
    ...
    hb.stop()

Or one-shot:

    snap = hb.tick()  # synchronous single beat

This is the runtime layer that ties math_engine to agent_loop. The
state_provider callable is what reads from DB / HA / IoT / chat (in
real life). For tests / demos, you can pass a lambda that returns a
synthetic series.

Author: Sprint X20.1 — Heartbeat
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from typing import Callable, Optional, Sequence

try:
    from .math_engine import (
        State, DomainWeights, EngineSnapshot, run_engine,
        PERSONA_WEIGHTS, classify,
    )
except ImportError:
    from math_engine import (  # type: ignore
        State, DomainWeights, EngineSnapshot, run_engine,
        PERSONA_WEIGHTS, classify,
    )


# Cadence per mode (seconds). These are the BPM of Radim's heart.
DEFAULT_CADENCE_SEC = {
    "HARMONY": 300,   # 0.2 BPM — calm
    "ALERT":    60,   # 1 BPM — vigilant
    "CRISIS":   30,   # 2 BPM — urgent
}

# Quiet hours: minimum interval (seconds) when in HARMONY/ALERT.
# CRISIS bypasses this — life safety > sleep.
DEFAULT_QUIET_HOURS = (dt_time(22, 0), dt_time(7, 0))
DEFAULT_QUIET_MIN_INTERVAL = 600  # 10 min during quiet hours


# ─── Listener type ──────────────────────────────────────────────────────────

HeartbeatListener = Callable[[EngineSnapshot], None]


# ─── State provider type ────────────────────────────────────────────────────
# A callable that returns the current state history (list of State).
# In production, this reads from DB + IoT + HA. For tests/demos, it can
# be a closure over a synthetic series.

StateProvider = Callable[[], Sequence[State]]


@dataclass
class HeartbeatStats:
    total_beats: int = 0
    last_tick_at: Optional[datetime] = None
    last_mode: Optional[str] = None
    mode_counts: dict[str, int] = field(default_factory=dict)
    preemptive_count: int = 0


class Heartbeat:
    """Adaptive-cadence agent loop.

    Args:
        persona:        key from PERSONA_WEIGHTS (or pass `weights` directly)
        weights:        explicit DomainWeights (overrides persona)
        state_provider: () -> sequence of State; called every tick
        cadence:        override DEFAULT_CADENCE_SEC
        quiet_hours:    (start, end) time tuple; None to disable
        quiet_min_interval: minimum seconds between beats during quiet hrs
        on_tick:        optional convenience listener
    """

    def __init__(
        self,
        persona: str = "senior",
        weights: Optional[DomainWeights] = None,
        state_provider: Optional[StateProvider] = None,
        cadence: Optional[dict[str, int]] = None,
        quiet_hours: Optional[tuple[dt_time, dt_time]] = DEFAULT_QUIET_HOURS,
        quiet_min_interval: int = DEFAULT_QUIET_MIN_INTERVAL,
        on_tick: Optional[HeartbeatListener] = None,
    ):
        self.persona = persona
        self.weights = weights or PERSONA_WEIGHTS.get(persona, DomainWeights())
        self.state_provider = state_provider
        self.cadence = dict(cadence or DEFAULT_CADENCE_SEC)
        self.quiet_hours = quiet_hours
        self.quiet_min_interval = quiet_min_interval

        self._listeners: list[HeartbeatListener] = []
        if on_tick:
            self._listeners.append(on_tick)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_snap: Optional[EngineSnapshot] = None
        self.stats = HeartbeatStats()

    # ─── Subscriptions ──

    def subscribe(self, listener: HeartbeatListener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: HeartbeatListener) -> None:
        try:
            self._listeners.remove(listener)
        except ValueError:
            pass

    # ─── Single beat ──

    def tick(self) -> EngineSnapshot:
        """Synchronously perform one beat; return the snapshot."""
        if not self.state_provider:
            raise RuntimeError("state_provider not configured")
        history = self.state_provider()
        if not history:
            raise RuntimeError("state_provider returned empty history")

        snap = run_engine(history, self.weights)
        self._last_snap = snap

        # Stats
        self.stats.total_beats += 1
        self.stats.last_tick_at = datetime.utcnow()
        self.stats.last_mode = snap.mode
        self.stats.mode_counts[snap.mode] = self.stats.mode_counts.get(snap.mode, 0) + 1
        if snap.preemptive.crosses_up:
            self.stats.preemptive_count += 1

        # Notify listeners (don't let one bad listener kill the loop)
        for listener in self._listeners:
            try:
                listener(snap)
            except Exception as e:  # noqa: BLE001
                self._log(f"listener error: {e}")

        return snap

    # ─── Cadence selection ──

    def _next_interval(self, snap: EngineSnapshot) -> int:
        """Pick the appropriate sleep duration for the next beat."""
        # Preemptive override: if horizon predicts higher mode, use that
        # mode's cadence right now (speed up before the crisis arrives).
        active_mode = snap.mode
        if snap.preemptive.crosses_up:
            active_mode = snap.preemptive.predicted_mode

        base = self.cadence.get(active_mode, self.cadence["ALERT"])

        # Quiet hours: if not CRISIS and we're in a quiet window, don't
        # tick faster than quiet_min_interval. CRISIS always bypasses.
        if (active_mode != "CRISIS"
                and self.quiet_hours
                and self._in_quiet_hours()):
            base = max(base, self.quiet_min_interval)

        return base

    def _in_quiet_hours(self) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        now = datetime.now().time()
        if start <= end:
            return start <= now < end
        # Wrap around midnight (22:00 → 07:00)
        return now >= start or now < end

    # ─── Background loop ──

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"Heartbeat-{self.persona}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run_loop(self) -> None:
        # Start with one immediate beat
        try:
            snap = self.tick()
            interval = self._next_interval(snap)
        except Exception as e:  # noqa: BLE001
            self._log(f"first tick failed: {e}")
            interval = self.cadence["ALERT"]

        while not self._stop_event.is_set():
            # Sleep in 0.5s chunks so stop() responds quickly
            slept = 0.0
            while slept < interval and not self._stop_event.is_set():
                time.sleep(min(0.5, interval - slept))
                slept += 0.5
            if self._stop_event.is_set():
                break
            try:
                snap = self.tick()
                interval = self._next_interval(snap)
            except Exception as e:  # noqa: BLE001
                self._log(f"tick failed: {e}")
                interval = self.cadence["ALERT"]

    # ─── Snapshot accessors ──

    @property
    def last(self) -> Optional[EngineSnapshot]:
        return self._last_snap

    def context_hints(self, module: str) -> dict:
        """Return a JSON-serializable snapshot of what the agent currently
        "sees" — designed to be served by /api/agent/context-hints/<user>/<mod>.
        Every frontend module reads this on load to know the senior's mode
        and adapt its own behavior."""
        snap = self._last_snap
        if not snap:
            return {"available": False, "module": module}
        # Per-module tone hints — minimal v1, expand per persona later
        tone_per_mode = {
            "HARMONY": "warm, confident, conversational",
            "ALERT":   "calm, clear, slightly slower",
            "CRISIS":  "very calm, slow, reassuring, short sentences",
        }
        return {
            "available": True,
            "module": module,
            "persona": self.persona,
            "current_mode": snap.mode,
            "c_total": round(snap.c_total, 2),
            "alpha": round(snap.state.alpha, 3),
            "predicted_mode_30min": snap.preemptive.predicted_mode,
            "preemptive_active": snap.preemptive.crosses_up,
            "tone": tone_per_mode.get(snap.mode, ""),
            "speech": {
                "rate": round(snap.speech.rate, 3),
                "pitch": round(snap.speech.pitch, 2),
                "pause_ms": snap.speech.pause_ms,
                "empathy": round(snap.speech.empathy, 2),
                "ssml_prosody": snap.speech.to_ssml_prosody(),
            },
            "ts": (snap.state.t.isoformat() if snap.state else None),
        }

    # ─── Internal ──

    def _log(self, msg: str) -> None:
        print(f"[heartbeat:{self.persona}] {msg}", flush=True)
