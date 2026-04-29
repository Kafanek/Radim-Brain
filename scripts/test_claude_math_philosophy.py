#!/usr/bin/env python3
"""Test math + philosophy tools of Claude agent."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_anticipation_forecast,
    _tool_get_circadian_profile,
    _tool_get_circadian_triggers,
    _tool_get_behavioral_profile,
    _tool_get_radim_philosophy,
    _tool_list_seniors,
)

print('=' * 60)
print('MATH + PHILOSOPHY TOOLS — TEST')
print('=' * 60)
print()

# Philosophy doesn't need a senior
print('━━━ PHILOSOPHY ━━━')
phil = _tool_get_radim_philosophy()
if isinstance(phil, dict) and not phil.get('error'):
    print(f'  ✓ get_radim_philosophy(): {phil.get("time_period")} reflection: "{phil.get("reflection", "")[:80]}"')
    print(f'    values: {len(phil.get("values_summary", []))} loaded')
    print(f'    math constants: PHI={phil["math_constants"]["PHI"]}, T1={phil["math_constants"]["T1"]}, T2={phil["math_constants"]["T2"]}')
else:
    print(f'  ✗ FAIL: {phil}')

# Test focused value
phil_focused = _tool_get_radim_philosophy('empathy')
print(f'  ✓ focused on empathy: weight={phil_focused.get("focused_value", {}).get("weight")}')
print()

# Math tools need a senior with data
print('━━━ MATH (per senior) ━━━')
seniors = _tool_list_seniors()
if not isinstance(seniors, list) or not seniors:
    print(f'  ✗ no seniors available')
    sys.exit(1)

# Find Anna (#268) — has chat history + brain state
test_seniors = []
for s in seniors:
    if s['id'] in ('268', '282'):  # Anna and Eva
        test_seniors.append(s)
if not test_seniors:
    test_seniors = seniors[:2]

for senior in test_seniors:
    sid = senior['id']
    print(f'\n  Senior #{sid} ({senior.get("name", "?")}):')
    for name, fn in [
        ('anticipation_forecast', lambda: _tool_get_anticipation_forecast(sid)),
        ('circadian_profile',     lambda: _tool_get_circadian_profile(sid)),
        ('circadian_triggers',    lambda: _tool_get_circadian_triggers(sid)),
        ('behavioral_profile',    lambda: _tool_get_behavioral_profile(sid)),
    ]:
        try:
            r = fn()
            if isinstance(r, dict) and r.get('error'):
                print(f'    ✗ {name}: {r["error"]}')
            else:
                payload = json.dumps(r, default=str, ensure_ascii=False)
                print(f'    ✓ {name}: {payload[:200]}{"…" if len(payload)>200 else ""}')
        except Exception as e:
            print(f'    ✗✗ {name}: EXCEPTION {type(e).__name__}: {e}')

print()
print('=' * 60)
print('DONE')
