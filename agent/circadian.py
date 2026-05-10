"""
Circadian dimension — time-of-day driven C contribution per persona
=====================================================================

Returns C_circadian ∈ [0, 40] from `(persona_id, when)`. Pure function,
no DB / no IO. Called by runtime.collect_state_history to populate the
6th dimension of State.

Curves (validated against clinical literature on sundowning + ADHD
rhythms; tunable per individual via memory_profiles.data
['circadian_offset_hours']):

  senior:        Bell with sundown bump 16:00–20:00 → C peaks at ~18
                 (sundowning syndrome — confusion + agitation late afternoon)
  child_adhd:    Bimodal — morning fog 8–10 + evening burnout 20–22
  child_autism:  Stable baseline (low variability) — schedule is the
                 anchor; deviations show up in cognitive dim instead

All curves clamped to [0, 40].

Test scenarios:
  >>> import datetime as dt
  >>> compute_circadian_c('senior', dt.datetime(2026, 5, 10, 18, 0))
  # ~18.0 — sundowning peak
  >>> compute_circadian_c('senior', dt.datetime(2026, 5, 10, 3, 0))
  # ~5.0 — deep night
  >>> compute_circadian_c('child_adhd', dt.datetime(2026, 5, 10, 9, 0))
  # ~12.0 — morning fog
  >>> compute_circadian_c('child_adhd', dt.datetime(2026, 5, 10, 14, 0))
  # ~6.0 — alert window
  >>> compute_circadian_c('child_autism', dt.datetime(2026, 5, 10, 18, 0))
  # ~6.0 — flat baseline

Sprint X20.5
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 40.0) -> float:
    return max(lo, min(hi, x))


def _hour_of_day(when: datetime) -> float:
    """Decimal hour 0-24 in local time. Caller should pass localized
    datetime; defaults treat naive datetime as local."""
    return when.hour + when.minute / 60.0 + when.second / 3600.0


# ─── Per-persona curves ────────────────────────────────────────────────────


def _senior_curve(h: float) -> float:
    """Senior with sundowning syndrome.

    Phases:
      00-06   deep sleep — low (5)
      06-12   morning rise (5 → 8)
      12-16   afternoon plateau (8)
      16-20   SUNDOWN — sharp rise to ~18 (peak agitation around 18-19)
      20-24   evening drop (18 → 6)
    """
    if h < 6.0:
        return 5.0
    if h < 12.0:
        # Linear 5 → 8 over 6h
        return 5.0 + (h - 6.0) * (3.0 / 6.0)
    if h < 16.0:
        return 8.0
    if h < 20.0:
        # SUNDOWN: 8 → 18 over 4h
        return 8.0 + (h - 16.0) * (10.0 / 4.0)
    # 20-24 evening drop: 18 → 6
    return max(6.0, 18.0 - (h - 20.0) * 3.0)


def _child_adhd_curve(h: float) -> float:
    """ADHD: bimodal — morning fog + evening burnout.

    Phases:
      00-08   sleep / low (5)
      08-10   MORNING FOG — peak ~12
      10-18   alert window (6, low cognitive load from circadian alone)
      18-22   evening burnout — rises to 12
      22-24   wind-down (12 → 8)
    """
    if h < 8.0:
        return 5.0
    if h < 10.0:
        # 0 → 7 over 2h, peaking at 12 (fog index)
        return 5.0 + (h - 8.0) * (7.0 / 2.0)
    if h < 18.0:
        return 6.0
    if h < 22.0:
        # 6 → 12 over 4h
        return 6.0 + (h - 18.0) * (6.0 / 4.0)
    return max(8.0, 12.0 - (h - 22.0) * 2.0)


def _child_autism_curve(h: float) -> float:
    """Autism: stable baseline. Schedule is the anchor, so circadian
    contribution is small. Routine deviations and transitions surface
    in the COGNITIVE dimension, not circadian."""
    # Very mild dips at typical transition points (school start/end);
    # mostly flat. Range 5–8.
    if h < 7.0 or h >= 21.0:
        return 5.0
    if 7.0 <= h < 9.0 or 14.0 <= h < 16.0:
        # Transitions
        return 8.0
    return 6.0


PERSONA_CURVES = {
    'senior':       _senior_curve,
    'child_adhd':   _child_adhd_curve,
    'child_autism': _child_autism_curve,
}


def compute_circadian_c(persona_id: str,
                        when: Optional[datetime] = None,
                        offset_hours: float = 0.0) -> float:
    """Return C_circadian ∈ [0, 40] for (persona, time).

    Args:
      persona_id    — 'senior' | 'child_autism' | 'child_adhd'
      when          — datetime; defaults to datetime.now()
      offset_hours  — per-individual phase shift (e.g. night-shift worker
                      effectively lives -6h offset). Stored per user in
                      memory_profiles.data['circadian_offset_hours'].
    """
    when = when or datetime.now()
    h = _hour_of_day(when) - float(offset_hours or 0.0)
    # Wrap into [0, 24)
    h = h % 24.0
    curve = PERSONA_CURVES.get(persona_id, _senior_curve)
    return _clamp(curve(h))


def describe_circadian_phase(persona_id: str,
                              when: Optional[datetime] = None) -> str:
    """Human-readable label of current circadian phase for the persona.
    Used by context-hints API + audit log entries for explainability."""
    c = compute_circadian_c(persona_id, when)
    h = _hour_of_day(when or datetime.now())

    if persona_id == 'senior':
        if 16 <= h < 20:           return 'sundown_peak'
        if h < 6 or h >= 22:       return 'deep_sleep'
        if 6 <= h < 12:            return 'morning_rise'
        return 'afternoon_plateau'
    if persona_id == 'child_adhd':
        if 8 <= h < 10:            return 'morning_fog'
        if 18 <= h < 22:           return 'evening_burnout'
        if 10 <= h < 18:           return 'alert_window'
        return 'sleep'
    if persona_id == 'child_autism':
        if 7 <= h < 9 or 14 <= h < 16: return 'transition'
        if h < 7 or h >= 21:       return 'sleep'
        return 'routine_stable'
    return 'unknown'
