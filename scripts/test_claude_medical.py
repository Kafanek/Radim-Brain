#!/usr/bin/env python3
"""Test medical team + telemedicine tools."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_medical_team,
    _tool_get_medical_alerts,
    _tool_create_medical_alert,
    _tool_get_upcoming_consultations,
    _tool_request_consultation,
    _tool_get_consultation_join_link,
    _tool_get_medical_history,
    _tool_emergency_call_doctor,
    _tool_list_seniors,
)

print('=' * 60)
print('MEDICAL TEAM + TELEMEDICINE — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Medical team
print('━━━ 1. get_medical_team ━━━')
mt = _tool_get_medical_team(test_sid)
if mt.get('error'):
    print(f'  → {mt}')
else:
    print(f'  count: {mt.get("count")}, roles: {mt.get("roles_breakdown")}')
    for member in mt.get('team', [])[:3]:
        print(f'    • {member.get("role"):15s} {member.get("name", "?")} consent={member.get("consent_given")}')
print()

# 2. Medical alerts
print('━━━ 2. get_medical_alerts ━━━')
ma = _tool_get_medical_alerts(test_sid, days=30)
if ma.get('error'):
    print(f'  → {ma}')
else:
    print(f'  count: {ma.get("count")}, severity_min: {ma.get("severity_min")}')
    for a in ma.get('alerts', [])[:3]:
        print(f'    • [{a.get("severity")}] {a.get("type")}: {a.get("message", "")[:80]}')
print()

# 3. Upcoming consultations
print('━━━ 3. get_upcoming_consultations ━━━')
uc = _tool_get_upcoming_consultations(test_sid, days=30)
if uc.get('error'):
    print(f'  → {uc}')
else:
    print(f'  count: {uc.get("count", 0)}')
    for c in uc.get('consultations', [])[:3]:
        print(f'    • {c.get("date")} {c.get("time")}: {c.get("type")} ({c.get("status")}) — "{c.get("complaint", "")[:60]}"')
print()

# 4. Medical history aggregate
print('━━━ 4. get_medical_history ━━━')
mh = _tool_get_medical_history(test_sid, days=30)
if mh.get('error'):
    print(f'  → {mh}')
else:
    sym = mh.get('symptoms', {})
    if not sym.get('error'):
        print(f'  symptoms: {sym.get("count", 0)} entries, '
              f'avg_pain={sym.get("avg_pain")}, avg_mood={sym.get("avg_mood")}')
    appts = mh.get('appointments', {})
    if not appts.get('error'):
        print(f'  appointments: {appts.get("count", 0)}')
    print(f'  brain_modes: {mh.get("brain_modes")}')
print()

# 5. Create medical alert (test)
print('━━━ 5. create_medical_alert (test) ━━━')
import time
TAG = f'CLAUDE_MED_TEST_{int(time.time())}'
ca = _tool_create_medical_alert(
    test_sid, 'pain_high', 'warning',
    f'Test alert {TAG} — auto-cleanup'
)
print(f'  → {ca}')
print()

# 6. Request consultation (test, will be cancelled)
print('━━━ 6. request_consultation ━━━')
rc = _tool_request_consultation(
    test_sid, doctor_user_id='9999',  # fake doctor for test
    scheduled_date='2026-05-15',
    scheduled_time='10:00',
    complaint=f'Test consultation request {TAG}',
    consultation_type='video'
)
print(f'  → {rc}')
test_consultation_id = rc.get('consultation_id')
print()

# 7. Emergency call (will fail gracefully if no coordinator)
print('━━━ 7. emergency_call_doctor (test) ━━━')
ec = _tool_emergency_call_doctor(
    test_sid,
    reason=f'TEST EMERGENCY {TAG} — auto-cleanup',
    severity='alert'  # not crisis to avoid triggering real escalation
)
print(f'  → {ec}')
print()

# Cleanup test rows
print('━━━ Cleanup ━━━')
from database import db_context, is_postgres
with db_context(commit=True) as db:
    if is_postgres():
        db.execute("DELETE FROM medical_alerts WHERE message LIKE %s", (f'%{TAG}%',))
        db.execute("DELETE FROM telemedicine_consultations WHERE complaint LIKE %s", (f'%{TAG}%',))
    else:
        db.execute("DELETE FROM medical_alerts WHERE message LIKE ?", (f'%{TAG}%',))
        db.execute("DELETE FROM telemedicine_consultations WHERE complaint LIKE ?", (f'%{TAG}%',))
print(f'  ✓ test rows removed')

# 8. Edge cases
print()
print('━━━ 8. Edge cases ━━━')
r = _tool_create_medical_alert(test_sid, 'x', 'BOGUS', 'x')
print(f'  invalid severity rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_emergency_call_doctor(test_sid, 'x', severity='info')
print(f'  emergency requires alert/crisis: {"✓" if r.get("error") else "✗"}')
r = _tool_request_consultation(test_sid, '9999', '2026-05-01', '10:00', '')
print(f'  empty complaint rejected: {"✓" if r.get("error") else "✗"}')

print()
print('=' * 60)
print('DONE')
