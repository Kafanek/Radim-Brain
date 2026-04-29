#!/usr/bin/env python3
"""Test agent bus + RTCF beat tools of Claude agent."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_agent_inventory,
    _tool_get_agent_messages,
    _tool_check_agent_dedup,
    _tool_emit_agent_message,
    _tool_get_beat_state,
    _tool_compute_custom_beat,
    _tool_list_seniors,
)

print('=' * 60)
print('AGENTS + BEAT — TEST')
print('=' * 60)
print()

# 1. Inventory (no senior)
print('━━━ 1. get_agent_inventory ━━━')
inv = _tool_get_agent_inventory()
if inv.get('total'):
    print(f'  ✓ {inv["total"]} agents registered')
    for name, meta in list(inv['agents'].items())[:5]:
        print(f'    • {name}: {meta["role"]}')
    print(f'  bus available: {inv["message_bus"]["available"]}')
else:
    print(f'  ✗ FAIL: {inv}')
print()

# Find seniors with active observations
seniors = _tool_list_seniors()
test_seniors = [s for s in seniors if s['id'] in ('268', '282', '278', '287')]
if not test_seniors:
    test_seniors = seniors[:2]

# 2. Agent messages + beat per senior
for senior in test_seniors[:3]:
    sid = senior['id']
    name = senior.get('name', '?')
    print(f'━━━ Senior #{sid} ({name}) ━━━')

    # agent messages
    msgs = _tool_get_agent_messages(sid, hours=72)
    if isinstance(msgs, dict) and not msgs.get('error'):
        print(f'  ✓ agent_messages (72h): {msgs.get("count", 0)} from other agents')
        for m in (msgs.get('messages', []) or [])[:3]:
            print(f'    • {m.get("sender")}: [{m.get("severity")}] {m.get("topic")} — {m.get("message", "")[:60]}')
    else:
        print(f'  ✗ agent_messages: {msgs}')

    # dedup check
    dup = _tool_check_agent_dedup(sid, topic='isolation', within_minutes=60, severity_min='warning')
    if isinstance(dup, dict) and not dup.get('error'):
        print(f'  ✓ dedup check (isolation, 60min): duplicate={dup.get("duplicate")}')
        if dup.get('recent_emitters'):
            for e in dup['recent_emitters'][:2]:
                print(f'    already raised by: {e["sender"]}')
    else:
        print(f'  ✗ dedup: {dup}')

    # beat state
    beat = _tool_get_beat_state(sid)
    if isinstance(beat, dict) and not beat.get('error'):
        print(f'  ✓ beat: BPM={beat.get("bpm")} HRV={beat.get("hrv")} '
              f'autonomic={beat.get("autonomic_mode")} arousal={beat.get("arousal")}')
        inputs = beat.get('_inputs', {})
        if inputs:
            print(f'    inputs: C={inputs.get("C")} mode={inputs.get("mode")} '
                  f'risk={inputs.get("derived_risk")} threat={inputs.get("derived_threat")}')
    else:
        print(f'  ✗ beat: {beat}')
    print()

# 3. Custom beat (hypothetical)
print('━━━ 3. compute_custom_beat (hypothetical) ━━━')
panic = _tool_compute_custom_beat(threat=0.9, risk=0.8, load=0.7, trust=0.3, safety=0.2)
print(f'  panic scenario: {panic}')

calm = _tool_compute_custom_beat(recovery=0.8, trust=0.9, safety=0.95)
print(f'  calm scenario:  {calm}')
print()

# 4. emit_agent_message round-trip on test senior
print('━━━ 4. emit + read round-trip on #287 ━━━')
TAG = f'CLAUDE_BUS_{int(time.time())}'

emit = _tool_emit_agent_message('287', 'context', 'info',
                                topic=f'test_{TAG}',
                                message=f'TEST emission {TAG}')
print(f'  emit: {emit}')

# Read back
msgs = _tool_get_agent_messages('287', hours=1, severity_min='info')
found = any(TAG in (m.get('topic', '') or '') for m in msgs.get('messages', []))
print(f'  visible in messages: {"✓" if found else "✗"}')

# Try invalid kind
bad = _tool_emit_agent_message('287', 'BOGUS_KIND', 'info', 'test', 'msg')
print(f'  invalid kind reject: {"✓" if bad.get("error") else "✗"}')

# Cleanup test bus message
try:
    from database import db_context, is_postgres
    with db_context(commit=True) as db:
        if is_postgres():
            db.execute("DELETE FROM agent_messages WHERE topic LIKE %s", (f'%{TAG}%',))
        else:
            db.execute("DELETE FROM agent_messages WHERE topic LIKE ?", (f'%{TAG}%',))
except Exception:
    pass

print()
print('=' * 60)
print('DONE')
