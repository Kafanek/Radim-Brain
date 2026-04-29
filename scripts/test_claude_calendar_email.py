#!/usr/bin/env python3
"""Test calendar + email tools — read events, parse, scan email risk."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_upcoming_events,
    _tool_find_free_slots,
    _tool_parse_event_text,
    _tool_get_unread_emails,
    _tool_scan_email_risk,
    _tool_list_seniors,
)

print('=' * 60)
print('CALENDAR + EMAIL — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Upcoming events
print('━━━ 1. get_upcoming_events ━━━')
e = _tool_get_upcoming_events(test_sid, hours=24*7)
print(f'  count: {e.get("count")} window: {e.get("window_hours")}h')
for ev in (e.get('events') or [])[:3]:
    print(f'    • {ev.get("date")} {ev.get("time", "")}: {ev.get("title")} ({ev.get("type")})')
print()

# 2. Find free slots
print('━━━ 2. find_free_slots ━━━')
s = _tool_find_free_slots(test_sid, days=7)
print(f'  found {s.get("count", 0)} slots, busy_count={s.get("busy_count", 0)}')
for slot in (s.get('slots') or []):
    print(f'    • {slot.get("label")}')
print()

# 3. Parse event text
print('━━━ 3. parse_event_text (Czech NLP) ━━━')
samples = [
    'Zítra v 14 doktor',
    'V pondělí ráno na vyšetření',
    'Příští sobota narozeniny vnučky Aničky v 16:00',
]
for text in samples:
    r = _tool_parse_event_text(text)
    if isinstance(r, dict) and not r.get('error'):
        print(f'  "{text}"')
        print(f'    → {r.get("title")} | {r.get("date")} {r.get("time")} | type={r.get("type")} | source={r.get("_source")}')
    else:
        print(f'  "{text}" → ✗ {r.get("error", r)[:80]}')
print()

# 4. Email risk scanning (no real email needed)
print('━━━ 4. scan_email_risk ━━━')
phishing_samples = [
    {
        'name': 'Phishing',
        'subject': 'URGENT: Verify your bank account NOW',
        'body': 'Click here urgently to update your password and bank details: http://bank-verify.tk/login',
        'from_email': 'support@bank-verify.tk',
    },
    {
        'name': 'Money scam',
        'subject': 'Vyhráli jste 50000 Kč! Klikněte zde!',
        'body': 'Gratulujeme! Pošlete jen 500 Kč jako manipulační poplatek a obratem získáte výhru.',
        'from_email': 'lottery@suspicious.ru',
    },
    {
        'name': 'Legitimate',
        'subject': 'Termín kontroly u MUDr. Nováka',
        'body': 'Dobrý den, dovolujeme si Vás pozvat na pravidelnou kontrolu dne 5.5. v 10:00. S pozdravem ordinace.',
        'from_email': 'ordinace@mudrnovak.cz',
    },
]
for s in phishing_samples:
    r = _tool_scan_email_risk(s['subject'], s['body'], s['from_email'])
    flag = '🚨' if r.get('risky') else '✓'
    print(f'  {flag} {s["name"]:15s} → score={r.get("score", 0):>3d} risky={r.get("risky")}')
    for reason in (r.get('reasons') or [])[:2]:
        print(f'      • {reason}')
print()

# 5. Email reading (will likely return "no account configured" for test seniors)
print('━━━ 5. get_unread_emails ━━━')
em = _tool_get_unread_emails(test_sid, limit=5)
if em.get('info'):
    print(f'  ⚠ {em["info"]}')
elif em.get('error'):
    print(f'  ✗ {em["error"]}')
else:
    print(f'  ✓ {em.get("unread_count", 0)} unread, account={em.get("email_account")}')
    for m in (em.get('messages') or [])[:3]:
        print(f'    • {m.get("from_name", "?")} <{m.get("from_email")}>: {m.get("subject", "")[:60]}')
print()

print('=' * 60)
print('DONE')
