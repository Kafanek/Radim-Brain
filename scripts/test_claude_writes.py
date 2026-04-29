#!/usr/bin/env python3
"""Test that Claude agent's WRITE tools actually persist to DB."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_send_chat_message, _tool_create_observation,
    _tool_get_recent_chat, _tool_get_observations,
)
from database import db_context

TEST_SENIOR = '268'  # Anna AU has chat history already
TEST_TAG = f'CLAUDE_TEST_{int(time.time())}'

print(f'━━━ Test write tools on senior #{TEST_SENIOR} ({TEST_TAG}) ━━━')
print()

# 1. send_chat_message
print('1. send_chat_message...')
r = _tool_send_chat_message(TEST_SENIOR, f'TESTOVACÍ ZPRÁVA {TEST_TAG} - prosím ignorujte')
print(f'   tool returned: {r}')

# 2. read back from memory_history
chat = _tool_get_recent_chat(TEST_SENIOR, n=3)
found_chat = any(TEST_TAG in (m.get('content', '') or '') for m in (chat if isinstance(chat, list) else []))
print(f'   ✓ visible in recent_chat' if found_chat else f'   ✗ NOT visible in chat: {chat}')
print()

# 3. create_observation
print('2. create_observation...')
r = _tool_create_observation(TEST_SENIOR, 'INFO', f'Observation test {TEST_TAG}')
print(f'   tool returned: {r}')

# 4. read back from agent_observations
obs = _tool_get_observations(TEST_SENIOR, days=1)
found_obs = any(TEST_TAG in (o.get('message', '') or '') for o in (obs if isinstance(obs, list) else []))
print(f'   ✓ visible in observations' if found_obs else f'   ✗ NOT visible: {obs}')
print()

# 5. cleanup — delete the test rows
with db_context(commit=True) as db:
    if hasattr(db.execute('SELECT 1').fetchone(), 'values'):
        # PG
        cur = db.execute("DELETE FROM memory_history WHERE user_id = %s AND content LIKE %s",
                         (TEST_SENIOR, f'%{TEST_TAG}%'))
        cur2 = db.execute("DELETE FROM agent_observations WHERE user_id = %s AND message LIKE %s",
                          (TEST_SENIOR, f'%{TEST_TAG}%'))
    else:
        cur = db.execute("DELETE FROM memory_history WHERE user_id = ? AND content LIKE ?",
                         (TEST_SENIOR, f'%{TEST_TAG}%'))
        cur2 = db.execute("DELETE FROM agent_observations WHERE user_id = ? AND message LIKE ?",
                          (TEST_SENIOR, f'%{TEST_TAG}%'))
print(f'   cleanup: deleted test rows')
print()

if found_chat and found_obs:
    print('━━━ ALL WRITE TOOLS WORKING ✓ ━━━')
    sys.exit(0)
else:
    print('━━━ SOME WRITE TOOLS BROKEN ✗ ━━━')
    sys.exit(1)
