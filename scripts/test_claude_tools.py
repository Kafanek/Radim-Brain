#!/usr/bin/env python3
"""Standalone test of every Claude agent tool against current DB.
Run via: heroku run --no-tty python3 scripts/test_claude_tools.py -a radim-brain-2025
"""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_list_seniors, _tool_get_brain_state, _tool_get_vitals,
    _tool_get_iot_status, _tool_get_recent_chat, _tool_get_observations,
)

print('=' * 60)
print('CLAUDE AGENT TOOLS — INDIVIDUAL TEST')
print('=' * 60)

seniors = _tool_list_seniors()
if not isinstance(seniors, list) or not seniors:
    print(f'❌ list_seniors FAIL: {seniors}')
    sys.exit(1)

print(f'✓ list_seniors → {len(seniors)} entries')
print(f'  First: {json.dumps(seniors[0], default=str, ensure_ascii=False)[:200]}')
print()

# Find seniors with most data — sort by recent activity
seniors_with_data = sorted(seniors, key=lambda s: s.get('last_active') or '', reverse=True)

# Test on first 3 + senior #268 (Anna, has alerts) if exists
test_set = seniors_with_data[:3]
for s in seniors:
    if s['id'] == '268' and s not in test_set:
        test_set.append(s)
        break

for senior in test_set:
    sid = senior['id']
    print(f'━━━ Senior #{sid} ({senior.get("name", "?")}) ━━━')
    for name, fn in [
        ('brain_state',  lambda: _tool_get_brain_state(sid)),
        ('vitals',       lambda: _tool_get_vitals(sid)),
        ('iot_status',   lambda: _tool_get_iot_status(sid)),
        ('recent_chat',  lambda: _tool_get_recent_chat(sid, 5)),
        ('observations', lambda: _tool_get_observations(sid, 30)),
    ]:
        try:
            r = fn()
            if isinstance(r, dict) and r.get('error'):
                print(f'  ✗ {name}: ERROR — {r["error"]}')
            else:
                payload = json.dumps(r, default=str, ensure_ascii=False)
                print(f'  ✓ {name}: {payload[:150]}{"…" if len(payload)>150 else ""}')
        except Exception as e:
            print(f'  ✗✗ {name}: EXCEPTION {type(e).__name__}: {e}')
    print()

print('=' * 60)
print('DONE')
