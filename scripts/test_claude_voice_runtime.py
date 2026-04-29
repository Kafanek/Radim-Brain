#!/usr/bin/env python3
"""Test wake word + voice runtime + proactive communication tools."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_voice_session_state,
    _tool_get_voice_conversation_history,
    _tool_speak_to_senior,
    _tool_get_active_voice_seniors,
    _tool_list_seniors,
)
from voice_runtime_engine import get_session, STATES

print('=' * 60)
print('WAKE WORD + USER COMMUNICATION — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = '287'  # Q — test account

# 1. Initial state (should be IDLE for fresh session)
print('━━━ 1. get_voice_session_state (initial) ━━━')
s = _tool_get_voice_session_state(test_sid)
print(f'  state={s.get("state")} | safe_to_speak={s.get("safe_to_speak")} | C={s.get("C")}')
print(f'  hint: {s.get("_hint", "")[:80]}')
print()

# 2. Speak to IDLE senior
print('━━━ 2. speak_to_senior on IDLE ━━━')
TAG = f'CLAUDE_VOICE_{int(time.time())}'
r = _tool_speak_to_senior(test_sid, f'Test {TAG} - dobré ráno paní Janičko',
                          mode='HARMONY')
print(f'  result: {r}')
print()

# 3. Conversation history should now contain it
print('━━━ 3. get_voice_conversation_history ━━━')
h = _tool_get_voice_conversation_history(test_sid, limit=5)
recent = h.get('recent', [])
found_tag = any(TAG in (t.get('content', '') or '') for t in recent)
print(f'  total turns: {h.get("total_turns")} | recent: {len(recent)} | tag visible: {"✓" if found_tag else "✗"}')
if recent:
    last = recent[-1]
    print(f'  last: [{last.get("role")}] {last.get("content", "")[:100]}')
print()

# 4. Force LISTENING state, then try speak (should skip)
print('━━━ 4. speak when senior is LISTENING (should skip) ━━━')
session = get_session(test_sid)
session['state'] = STATES['LISTENING']
s = _tool_get_voice_session_state(test_sid)
print(f'  state forced to: {s.get("state")} | safe_to_speak={s.get("safe_to_speak")}')
r = _tool_speak_to_senior(test_sid, 'Should skip — listening')
print(f'  speak result: {r}')
print(f'  {"✓ correctly skipped" if r.get("skipped") else "✗ should have skipped"}')
print()

# 5. force_interrupt=True (CRISIS scenario)
print('━━━ 5. force_interrupt=True (CRISIS) ━━━')
r = _tool_speak_to_senior(test_sid, f'CRISIS interrupt {TAG}',
                          force_interrupt=True, mode='CRISIS')
print(f'  result: {r}')
print(f'  {"✓ interrupted" if r.get("spoken") else "✗"}')
print()

# 6. Reset to IDLE
print('━━━ 6. Reset to IDLE + active seniors list ━━━')
session['state'] = STATES['IDLE']
active = _tool_get_active_voice_seniors()
print(f'  active count: {active.get("count")} | total in cache: {active.get("total_in_cache")}')
print()

# 7. Empty message rejection
print('━━━ 7. Edge cases ━━━')
r = _tool_speak_to_senior(test_sid, '')
print(f'  empty message: {"✓ rejected" if r.get("error") else "✗ should reject"}')

# Cleanup test conversation entries
session = get_session(test_sid)
session['conversation'] = [t for t in session.get('conversation', [])
                           if TAG not in (t.get('content', '') if isinstance(t, dict) else str(t))]

print()
print('=' * 60)
print('DONE')
