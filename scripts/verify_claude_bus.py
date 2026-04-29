#!/usr/bin/env python3
"""Verify Claude agent's emissions on the shared bus."""
import sys
sys.path.insert(0, '.')

from agent_bus import recent

# Check who emitted in last 30 minutes for Eva (282) and others Claude analyzed
for sid in ['282', '278', '268']:
    msgs = recent(sid, since=30, severity_min='info', limit=10)
    print(f'\n━━━ Senior #{sid} — last 30 min ({len(msgs)} messages) ━━━')
    for m in msgs:
        sender = m.get('sender', '?')
        kind = m.get('kind', '?')
        sev = m.get('severity', '?')
        topic = m.get('topic', '?')
        msg = (m.get('payload') or {}).get('message', '')[:90]
        ts = m.get('created_at', '')
        print(f'  [{sender}] {kind}/{sev} {ts}')
        print(f'    topic: {topic}')
        if msg:
            print(f'    msg: {msg}')
