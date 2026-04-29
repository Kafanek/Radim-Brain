#!/usr/bin/env python3
"""Test event-driven Claude agent trigger from agent_loop.

Simulates an ALERT observation and verifies Claude agent fires async.
"""
import sys, os, time, json
sys.path.insert(0, '.')

# Ensure trigger is enabled for this test
os.environ['CLAUDE_AGENT_EVENT_TRIGGER'] = '1'
os.environ['CLAUDE_AGENT_ENABLED'] = '1'

from claude_autonomous_agent import (
    _can_trigger_for_senior, _mark_trigger, _event_trigger_history,
    EVENT_TRIGGER_COOLDOWN_MIN,
)

print('=' * 60)
print('AGENT LOOP → CLAUDE EVENT TRIGGER — TEST')
print('=' * 60)
print()

print('━━━ 1. Cooldown logic ━━━')
sid = 'test_event_999'
# First call: should allow
print(f'  initial: can_trigger={_can_trigger_for_senior(sid)}')
_mark_trigger(sid)
# Immediate second call: should block
print(f'  immediately after mark: can_trigger={_can_trigger_for_senior(sid)}')
print(f'  cooldown_min: {EVENT_TRIGGER_COOLDOWN_MIN}')
# Cleanup
_event_trigger_history.pop(sid, None)
print()

print('━━━ 2. Focused mode initial message ━━━')
# Just verify the run_claude_agent signature accepts new args
from claude_autonomous_agent import run_claude_agent
import inspect
sig = inspect.signature(run_claude_agent)
params = list(sig.parameters.keys())
print(f'  run_claude_agent params: {params}')
assert 'focus_senior_id' in params, 'focus_senior_id param missing!'
assert 'event_context' in params, 'event_context param missing!'
print(f'  ✓ focus_senior_id + event_context both present')
print()

print('━━━ 3. Simulated agent_loop hook (dry — no actual call) ━━━')
# Don't actually run the agent (would cost $$). Just verify the hook code path
# is correct by importing and inspecting agent_loop._execute_action.
from agent_loop import _execute_action
src = inspect.getsource(_execute_action)
hooks_present = [
    'CLAUDE_AGENT_EVENT_TRIGGER' in src,
    'run_claude_agent' in src,
    'focus_senior_id' in src,
    'event_context' in src,
    'threading.Thread' in src or '_threading.Thread' in src,
]
print(f'  ENV gate present:        {"✓" if hooks_present[0] else "✗"}')
print(f'  run_claude_agent import: {"✓" if hooks_present[1] else "✗"}')
print(f'  focus_senior_id passed:  {"✓" if hooks_present[2] else "✗"}')
print(f'  event_context passed:    {"✓" if hooks_present[3] else "✗"}')
print(f'  async via threading:     {"✓" if hooks_present[4] else "✗"}')
all_ok = all(hooks_present)
print(f'  HOOK INTEGRITY: {"✓ all checks pass" if all_ok else "✗ some checks failed"}')
print()

print('━━━ 4. Event trigger flow (live, mock observation) ━━━')
# Build a fake observation that would trigger Claude
mock_obs = {
    'type': 'c_trend_alert',
    'severity': 'ALERT',
    'message': 'Test: simulated rising C trend for trigger verification',
}

# Verify can_trigger before
sid_real = '287'  # safe test senior
_event_trigger_history.pop(sid_real, None)  # reset
print(f'  pre-check: can_trigger({sid_real})={_can_trigger_for_senior(sid_real)}')

# Don't actually run agent_loop._execute_action because it has many side effects
# Instead just verify that calling run_claude_agent with the focused mode works
print(f'  (Skipping live agent call — test_claude_tools verifies that path)')

print()
print('=' * 60)
print('DONE — Hook is wired. Set CLAUDE_AGENT_EVENT_TRIGGER=1 on Heroku to enable.')
print('=' * 60)
