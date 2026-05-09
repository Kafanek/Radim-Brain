"""
Persona-aware threshold registry
=================================

Single source of truth for per-persona detector thresholds. Each detector
in agent_loop.py reads from `get_thresholds_for_user(user_id)` instead of
using hardcoded T1/T2 globals — so a senior, a child with autism, and a
child with ADHD get different alert/crisis bands tuned to their profile.

Personas (matched to math_engine.PERSONA_WEIGHTS):
    senior          — default, conservative thresholds
    child_autism    — lower thresholds (sensitive to overload), faster
                      routine-deviation alerts
    child_adhd      — higher tolerance for state fluctuation, shorter
                      silence windows (engagement matters)

Storage:
    persona_id is stored in memory_profiles.data['persona_id'] (JSONB key).
    No schema migration needed. Defaults to 'senior' when missing.

Sprint X20.1 / Fix 3 — persona-aware detectors
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Per-persona threshold dictionaries ────────────────────────────────────
#
# Keys map to specific detectors:
#   c_alert / c_crisis        → _check_c_trend, _check_recent_chat_crisis
#   silence_*_hours           → _check_interaction_silence
#   activity_drop_factor      → _check_activity_drop
#   hr_high / hr_low          → _check_vitals
#   spo2_low                  → _check_vitals
#   door_open_alert_min       → _detect_door_open_long
#   no_motion_alert_hours     → _detect_no_motion_during_day
#   battery_low_pct           → _detect_battery_low
#
# When a detector reads a key not present in a persona, it falls back to
# the senior baseline (deepmerged below at module load).

_SENIOR_BASE = {
    # C-band classification (mirrors math_engine constants)
    'c_alert':                12,
    'c_crisis':               27,

    # Interaction silence (interaction_silence detector)
    'silence_warning_hours':  24,
    'silence_alert_hours':    48,
    'silence_crisis_hours':   72,

    # Activity drop (activity_drop detector)
    'activity_drop_factor':   0.5,    # 50% below baseline → ALERT
    'activity_drop_std_mul':  2.0,    # OR > 2σ below baseline

    # Vitals (vitals detector)
    'hr_high':                100,    # bpm
    'hr_low':                 50,
    'spo2_low':               95,     # %

    # Tapo IoT
    'door_open_alert_min':    30,
    'no_motion_alert_hours':  6,
    'battery_low_pct':        20,
    'kitchen_idle_hours':     24,

    # Sleep
    'sleep_min_hours':        6,

    # Per-persona communication adaptation hint (not a numeric threshold —
    # consumed by context-hints API for module tone)
    'tone_hint': 'warm, calm, slightly slower when tired',
    'avoid':     [],
}

PERSONA_THRESHOLDS = {
    'senior': dict(_SENIOR_BASE),
    'child_autism': {
        # Lower thresholds — overload is real and fast
        'c_alert':              9,
        'c_crisis':             22,
        'silence_warning_hours': 12,
        'silence_alert_hours':   24,
        'silence_crisis_hours':  48,
        'activity_drop_factor':  0.35,
        'hr_high':              110,
        'hr_low':               55,
        'spo2_low':             95,
        'door_open_alert_min':  15,    # earlier — wandering risk
        'no_motion_alert_hours': 4,
        'battery_low_pct':      20,
        'kitchen_idle_hours':   24,
        'sleep_min_hours':      8,
        'tone_hint': 'predictable, structured, no idioms, advance warnings',
        'avoid':    ['surprises', 'irony', 'ambiguity'],
    },
    'child_adhd': {
        # Higher tolerance for fluctuation, but shorter silence (engagement)
        'c_alert':              14,
        'c_crisis':             28,
        'silence_warning_hours':  6,
        'silence_alert_hours':   12,
        'silence_crisis_hours':  24,
        'activity_drop_factor':  0.3,
        'hr_high':              120,
        'hr_low':                50,
        'spo2_low':              95,
        'door_open_alert_min':   20,
        'no_motion_alert_hours':  4,
        'battery_low_pct':       20,
        'kitchen_idle_hours':    24,
        'sleep_min_hours':        7,
        'tone_hint': 'engaging, short replies, clear next steps',
        'avoid':    ['long_explanations'],
    },
}

# Deep-merge non-senior personas with senior base so any missing key
# inherits the conservative default. This makes it safe to remove a key
# from child_autism (e.g.) and not break detectors.
for _pid, _cfg in PERSONA_THRESHOLDS.items():
    if _pid == 'senior':
        continue
    merged = dict(_SENIOR_BASE)
    merged.update(_cfg)
    PERSONA_THRESHOLDS[_pid] = merged


# ─── User → persona resolution ─────────────────────────────────────────────


_DEFAULT_PERSONA = 'senior'


def get_persona_id(user_id: str) -> str:
    """Read persona_id from memory_profiles.data JSONB.
    Returns 'senior' when missing or on DB error (graceful fallback)."""
    if not user_id:
        return _DEFAULT_PERSONA
    try:
        from memory_helpers import db_load_profile
    except ImportError:
        return _DEFAULT_PERSONA
    try:
        profile = db_load_profile(str(user_id)) or {}
        pid = profile.get('persona_id')
        if pid and pid in PERSONA_THRESHOLDS:
            return pid
    except Exception as e:
        logger.debug(f"[personas] get_persona_id failed for {user_id}: {e}")
    return _DEFAULT_PERSONA


def set_persona_id(user_id: str, persona_id: str) -> bool:
    """Write persona_id into memory_profiles.data. Returns success bool.
    Validates persona_id against the registry — refuses unknown values."""
    if persona_id not in PERSONA_THRESHOLDS:
        return False
    try:
        from memory_helpers import db_load_profile, db_save_profile
    except ImportError:
        return False
    try:
        profile = db_load_profile(str(user_id)) or {}
        profile['persona_id'] = persona_id
        db_save_profile(str(user_id), profile)
        return True
    except Exception as e:
        logger.warning(f"[personas] set_persona_id failed for {user_id}: {e}")
        return False


def get_thresholds(persona_id: str) -> dict:
    """Return a defensive copy of the threshold dict for the given persona.
    Unknown persona → senior fallback."""
    if persona_id not in PERSONA_THRESHOLDS:
        persona_id = _DEFAULT_PERSONA
    return dict(PERSONA_THRESHOLDS[persona_id])


def get_thresholds_for_user(user_id: str) -> dict:
    """One-stop: read persona_id from DB, return matching thresholds."""
    return get_thresholds(get_persona_id(user_id))


def list_personas() -> list[str]:
    return list(PERSONA_THRESHOLDS.keys())
