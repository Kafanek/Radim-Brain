#!/usr/bin/env python3
"""LIVE test: directly call agent_loop._execute_action with a mock ALERT
observation and verify Claude agent fires async."""
import sys, os, time
sys.path.insert(0, '.')

# Force-enable trigger
os.environ['CLAUDE_AGENT_EVENT_TRIGGER'] = '1'
os.environ['CLAUDE_AGENT_ENABLED'] = '1'

from claude_autonomous_agent import (
    _can_trigger_for_senior, _event_trigger_history, run_claude_agent,
)
from agent_loop import _execute_action

print('=' * 60)
print('LIVE EVENT TRIGGER TEST')
print('=' * 60)
print()

# Reset cooldown for our test senior
TEST_SID = '287'
_event_trigger_history.pop(TEST_SID, None)

# Build mock ALERT observation
mock_obs = {
    'type': 'c_trend_alert_test',
    'severity': 'ALERT',
    'message': 'TEST: Mock rising C trend for event-trigger verification',
    'details': {'C_trend': 3.0, 'C_now': 14.5, 'C_predicted': 17.5},
}

print(f'━━━ Calling _execute_action(senior={TEST_SID}, severity=ALERT) ━━━')
print(f'  pre-check: can_trigger={_can_trigger_for_senior(TEST_SID)}')
print()

# Get baseline Claude run id
import urllib.request, json
BASE = 'https://radim-brain-2025-be1cd52b04dc.herokuapp.com'
SECRET = os.environ.get('ADMIN_SECRET', '')
if not SECRET:
    # In dyno context, we can read directly from DB
    from database import db_context
    with db_context() as db:
        row = db.execute("SELECT MAX(id) FROM claude_agent_telemetry").fetchone()
        last_id = list(row.values())[0] if hasattr(row, 'values') else row[0]
        print(f'  last claude_agent run id (from DB): {last_id}')
else:
    req = urllib.request.Request(BASE + '/api/admin/claude-agent/telemetry',
                                  headers={'X-Admin-Secret': SECRET})
    b = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    last_id = b['recent_runs'][0]['id'] if b['recent_runs'] else 0
    print(f'  last claude_agent run id (from API): {last_id}')

print()
print('▶ FIRING _execute_action...')
# We need an "app" — create a minimal Flask app context
try:
    from flask import Flask
    app = Flask(__name__)
    _execute_action(TEST_SID, mock_obs, app)
    print('  ✓ _execute_action returned (Claude was triggered async in thread)')
except Exception as e:
    print(f'  ✗ EXCEPTION: {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()

# Verify trigger was recorded
print()
print(f'  post-call: can_trigger={_can_trigger_for_senior(TEST_SID)} (should be False — cooldown)')
print(f'  cooldown history: {dict(_event_trigger_history)}')

# Wait for async Claude run to complete
print()
print('⏳ Waiting 100s for async Claude run...')
import time
from database import db_context
for i in range(13):
    time.sleep(8)
    with db_context() as db:
        row = db.execute(
            "SELECT id, run_at, cost_usd, tool_calls, summary "
            "FROM claude_agent_telemetry WHERE id > ? ORDER BY id DESC LIMIT 1",
            (int(last_id) if last_id else 0,)
        ).fetchone()
    if row:
        vals = list(row.values()) if hasattr(row, 'values') else list(row)
        print(f'  ✓ NEW RUN id={vals[0]} after {(i+1)*8}s')
        print(f'    run_at: {vals[1]}')
        print(f'    cost: ${vals[2]} | tools: {vals[3]}')
        summary = (vals[4] or '')[:600]
        if 'event' in summary.lower() or 'trigger' in summary.lower() or '287' in summary:
            print(f'    ✓ Summary mentions event/trigger context')
        print(f'    summary preview: {summary}')
        break
    print(f'  [{i+1}/13]...')
else:
    print(f'  ✗ No Claude run detected in 100s — hook may have failed silently')

print()
print('=' * 60)
print('DONE')
