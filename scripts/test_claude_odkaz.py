#!/usr/bin/env python3
"""Test Odkaz (legacy + monetization) tools."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_senior_experiences,
    _tool_get_active_offers,
    _tool_get_earnings_summary,
    _tool_get_legacy_status,
    _tool_get_inheritance_settings,
    _tool_record_experience_session,
    _tool_list_seniors,
)

print('=' * 60)
print('ODKAZ (legacy + monetization) — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Experiences
print('━━━ 1. get_senior_experiences ━━━')
e = _tool_get_senior_experiences(test_sid)
if e.get('error'):
    print(f'  → {e}')
else:
    print(f'  count: {e.get("count")}')
    for exp in e.get('experiences', [])[:3]:
        print(f'    • {exp.get("type"):8s} {exp.get("theme"):10s} | "{exp.get("title")[:50]}" | {exp.get("word_count")}w | privacy={exp.get("privacy")}')
print()

# 2. Active offers
print('━━━ 2. get_active_offers ━━━')
o = _tool_get_active_offers(test_sid)
if o.get('error'):
    print(f'  → {o}')
else:
    print(f'  count: {o.get("count")}, senior_themes: {o.get("senior_themes")}')
    for offer in o.get('offers', [])[:3]:
        print(f'    • [{offer.get("buyer_type")}] {offer.get("buyer_name", "?"):20s} | {offer.get("title", "")[:30]} | {offer.get("price_kc")}Kč | relevant={offer.get("relevant_to_senior")}')
print()

# 3. Earnings
print('━━━ 3. get_earnings_summary ━━━')
es = _tool_get_earnings_summary(test_sid)
if es.get('error'):
    print(f'  → {es}')
else:
    print(f'  all_time: {es.get("all_time_kc")}Kč')
    print(f'  this_month: {es.get("this_month_kc")}Kč')
    print(f'  active_contracts: {es.get("active_contracts")}')
    print(f'  bank_info: {es.get("bank_info")}')
print()

# 4. Legacy status
print('━━━ 4. get_legacy_status ━━━')
ls = _tool_get_legacy_status(test_sid)
print(f'  → {ls}')
print()

# 5. Inheritance settings
print('━━━ 5. get_inheritance_settings ━━━')
ih = _tool_get_inheritance_settings(test_sid)
print(f'  → {ih}')
print()

# 6. Record experience session (DRAFT only)
print('━━━ 6. record_experience_session (creates DRAFT) ━━━')
import time
TAG = f'CLAUDE_ODKAZ_TEST_{int(time.time())}'
r = _tool_record_experience_session(
    test_sid,
    topic=f'Test odkaz {TAG}',
    transcript_summary=f'Test legacy session {TAG}. ' * 30,  # 90 words
    contribution_type='wisdom',
    theme='family'
)
print(f'  → {r}')
contrib_id = r.get('contribution_id')
print()

# 7. Verify it's in draft (visible in get_senior_experiences)
e2 = _tool_get_senior_experiences(test_sid)
draft_visible = any(TAG in (exp.get('title', '') or '') for exp in e2.get('experiences', []))
print(f'  draft visible in experiences: {"✓" if draft_visible else "✗"}')

# Cleanup
print()
print('━━━ Cleanup ━━━')
from database import db_context, is_postgres
with db_context(commit=True) as db:
    if contrib_id:
        if is_postgres():
            db.execute("DELETE FROM experience_contributions WHERE id = %s", (contrib_id,))
        else:
            db.execute("DELETE FROM experience_contributions WHERE id = ?", (contrib_id,))
print(f'  ✓ test contribution deleted')

# 8. Edge cases
print()
print('━━━ 8. Edge cases ━━━')
r = _tool_record_experience_session(test_sid, 'topic', '', contribution_type='story')
print(f'  empty transcript rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_record_experience_session(test_sid, 'topic', 'text', contribution_type='BOGUS')
print(f'  invalid type rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_record_experience_session(test_sid, 'topic', 'text', theme='BOGUS')
print(f'  invalid theme rejected: {"✓" if r.get("error") else "✗"}')

print()
print('=' * 60)
print('DONE')
