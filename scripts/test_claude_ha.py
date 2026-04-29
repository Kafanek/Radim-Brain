#!/usr/bin/env python3
"""Test Home Assistant tools of Claude agent."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_ha_status,
    _tool_ha_get_sensors,
    _tool_ha_home_status,
    _tool_ha_get_device_state,
    _tool_ha_get_devices_by_room,
    _tool_ha_execute_action,
    _tool_ha_circadian_triggers,
    _tool_ha_behavioral_changes,
    _tool_list_seniors,
    _HA_SAFE_ACTIONS, _HA_CRISIS_ACTIONS, _HA_FORBIDDEN_ACTIONS,
)

print('=' * 60)
print('HOME ASSISTANT TOOLS — TEST')
print('=' * 60)
print()

# 1. Status
print('━━━ 1. ha_status ━━━')
s = _tool_ha_status()
print(f'  → {s}')
ha_connected = isinstance(s, dict) and s.get('connected') is True
print()

# Action whitelist sanity
print('━━━ 2. Action whitelist ━━━')
print(f'  SAFE ({len(_HA_SAFE_ACTIONS)}): {sorted(_HA_SAFE_ACTIONS)}')
print(f'  CRISIS-only ({len(_HA_CRISIS_ACTIONS)}): {sorted(_HA_CRISIS_ACTIONS)}')
print(f'  FORBIDDEN ({len(_HA_FORBIDDEN_ACTIONS)}): {sorted(_HA_FORBIDDEN_ACTIONS)}')
print()

# 3. Forbidden action rejection
print('━━━ 3. Forbidden action rejection ━━━')
r = _tool_ha_execute_action('lock', 'lock.front_door')
print(f'  lock (forbidden): {"✓ rejected" if r.get("error") else "✗ should reject"} → {r.get("error", "")[:80]}')

r = _tool_ha_execute_action('alarm_arm')
print(f'  alarm_arm (forbidden): {"✓ rejected" if r.get("error") else "✗ should reject"}')

# Crisis without override
r = _tool_ha_execute_action('unlock', 'lock.front_door')
print(f'  unlock without override: {"✓ rejected" if "crisis_override" in (r.get("error","")) else "✗"}')

# Crisis with override but no reason
r = _tool_ha_execute_action('unlock', 'lock.front_door', crisis_override=True)
print(f'  unlock without reason: {"✓ rejected" if r.get("error") else "✗"}')

# Unknown action
r = _tool_ha_execute_action('teleport_senior')
print(f'  unknown action: {"✓ rejected" if "unknown" in (r.get("error","")) else "✗"}')
print()

# 4. Read tools (will return error if HA not connected — that's OK)
print('━━━ 4. Read tools (graceful when HA not connected) ━━━')
for name, fn in [
    ('ha_get_sensors', lambda: _tool_ha_get_sensors()),
    ('ha_home_status', lambda: _tool_ha_home_status()),
    ('ha_get_devices_by_room', lambda: _tool_ha_get_devices_by_room()),
    ('ha_get_device_state(light.kitchen)', lambda: _tool_ha_get_device_state('light.kitchen')),
]:
    r = fn()
    if isinstance(r, dict):
        if r.get('error'):
            print(f'  {name}: ⚠ {r["error"][:80]} (graceful)')
        else:
            preview = json.dumps(r, default=str, ensure_ascii=False)[:120]
            print(f'  {name}: ✓ {preview}…')
    else:
        print(f'  {name}: returned {type(r).__name__}')
print()

# 5. Circadian triggers
print('━━━ 5. Circadian triggers per senior ━━━')
seniors = _tool_list_seniors()
test_seniors = [s for s in seniors if s['id'] in ('268', '282', '278')][:2]
for senior in test_seniors:
    sid = senior['id']
    name = senior.get('name', '?')
    t = _tool_ha_circadian_triggers(sid)
    if isinstance(t, dict) and not t.get('error'):
        print(f'  #{sid} ({name}): {t.get("count", 0)} triggers')
        for trigger in (t.get('triggers') or [])[:2]:
            print(f'    • {trigger.get("type")}: {trigger.get("message","")[:70]}')
    else:
        print(f'  #{sid}: {t}')

    # Behavioral changes
    bc = _tool_ha_behavioral_changes(sid)
    if isinstance(bc, dict) and not bc.get('error'):
        print(f'    behavioral: stability={bc.get("stability")} changes={bc.get("change_count", 0)}')

print()
print('━━━ SUMMARY ━━━')
print(f'HA connected: {"✓" if ha_connected else "✗ (expected — no real HA in pilot env)"}')
print(f'Safety whitelist: {"✓" if len(_HA_FORBIDDEN_ACTIONS) > 0 else "✗"}')
print(f'Graceful handling when HA offline: {"✓" if not ha_connected else "skipped (HA online)"}')
print()
print('=' * 60)
print('DONE')
