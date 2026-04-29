#!/usr/bin/env python3
"""Test settings + onboarding tools."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_senior_settings,
    _tool_update_setting,
    _tool_get_radim_mode,
    _tool_get_onboarding_status,
    _tool_list_seniors,
)

print('=' * 60)
print('SETTINGS + ONBOARDING — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Get settings
print('━━━ 1. get_senior_settings ━━━')
s = _tool_get_senior_settings(test_sid)
if s.get('error'):
    print(f'  → {s}')
else:
    ps = s.get('profile_settings', {})
    print(f'  radim_mode: {ps.get("radim_mode")}')
    print(f'  language: {ps.get("language")}')
    print(f'  font_size: {ps.get("font_size")}, theme: {ps.get("theme")}')
    print(f'  large_buttons: {ps.get("large_buttons")}, simplified_ui: {ps.get("simplified_ui")}')
    print(f'  voice_pref: {ps.get("voice_pref")}')
    acc = s.get('account', {})
    print(f'  account: role={acc.get("role")}, subscription={acc.get("subscription_status")}, age={acc.get("account_age_days")}d')
    ob = s.get('onboarding', {})
    if ob:
        print(f'  onboarding: started={ob.get("started", False)}, finished={ob.get("finished", False)}')
print()

# 2. Get radim_mode
print('━━━ 2. get_radim_mode ━━━')
m = _tool_get_radim_mode(test_sid)
print(f'  mode: {m.get("radim_mode")}')
print(f'  allows_proactive_chat: {m.get("allows_proactive_chat")}')
print(f'  allows_proactive_call: {m.get("allows_proactive_call")}')
print(f'  meaning: {m.get("_meaning")}')
print()

# 3. Get onboarding
print('━━━ 3. get_onboarding_status ━━━')
ob = _tool_get_onboarding_status(test_sid)
print(f'  → {ob}')
print()

# 4. Update setting (round-trip)
print('━━━ 4. update_setting (round-trip) ━━━')
TAG = f'test_theme_{int(time.time())}'
r = _tool_update_setting(test_sid, 'theme', TAG)
print(f'  set theme={TAG}: {r}')

# Read back
s2 = _tool_get_senior_settings(test_sid)
new_theme = s2.get('profile_settings', {}).get('theme')
print(f'  read back: theme={new_theme} {"✓" if new_theme == TAG else "✗"}')

# Restore
_tool_update_setting(test_sid, 'theme', s.get('profile_settings', {}).get('theme'))
print()

# 5. radim_mode update
print('━━━ 5. radim_mode change ━━━')
old_mode = _tool_get_radim_mode(test_sid).get('radim_mode')
print(f'  before: {old_mode}')
r = _tool_update_setting(test_sid, 'radim_mode', 'observer')
print(f'  set observer: {r}')
m2 = _tool_get_radim_mode(test_sid)
print(f'  now: {m2.get("radim_mode")} | proactive_chat={m2.get("allows_proactive_chat")}')
# Restore
_tool_update_setting(test_sid, 'radim_mode', old_mode or 'guide')
print()

# 6. Edge cases
print('━━━ 6. Edge cases ━━━')
r = _tool_update_setting(test_sid, 'email', 'evil@test.com')
print(f'  email change rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_update_setting(test_sid, 'password', 'hack')
print(f'  password change rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_update_setting(test_sid, 'subscription_status', 'unlimited')
print(f'  subscription rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_update_setting(test_sid, 'radim_mode', 'BOGUS_MODE')
print(f'  invalid radim_mode rejected: {"✓" if r.get("error") else "✗"}')

print()
print('=' * 60)
print('DONE')
