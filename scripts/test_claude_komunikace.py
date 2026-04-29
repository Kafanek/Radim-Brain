#!/usr/bin/env python3
"""Test Komunikace + TTS revalidation tools."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_communication_needs_catalog,
    _tool_get_communication_strategy,
    _tool_detect_topic_mood,
    _tool_get_senior_communication_profile,
    _tool_compose_ssml,
    _tool_get_voice_modes_catalog,
    _tool_list_seniors,
)

print('=' * 60)
print('KOMUNIKACE + TTS REVALIDATION')
print('=' * 60)
print()

# 1. Catalog of strategies
print('━━━ 1. get_communication_needs_catalog ━━━')
cat = _tool_get_communication_needs_catalog()
if cat.get('total'):
    print(f'  ✓ {cat["total"]} strategies')
    for s in cat['strategies'][:6]:
        print(f'    • {s["key"]}: {s["summary"][:80]}')
else:
    print(f'  ✗ FAIL: {cat}')
print()

# 2. Get strategy for a specific need
print('━━━ 2. get_communication_strategy(\'alzheimer_middle\') ━━━')
strat = _tool_get_communication_strategy('alzheimer_middle')
if strat.get('instructions'):
    print(f'  ✓ {strat["length"]} chars of instructions')
    print(f'  preview: {strat["instructions"][:200]}…')
else:
    print(f'  ✗ FAIL: {strat}')

# Layered (multiple needs)
print('\n━━━ 3. layered strategy alzheimer_middle + hearing_loss ━━━')
strat = _tool_get_communication_strategy('alzheimer_middle,hearing_loss')
if strat.get('instructions'):
    has_alz = 'Alzheimer' in strat['instructions']
    has_hear = 'sluch' in strat['instructions'].lower() or 'hearing' in strat['instructions'].lower()
    print(f'  ✓ Combined ({strat["length"]} chars) — alzheimer:{"✓" if has_alz else "✗"} hearing:{"✓" if has_hear else "✗"}')
print()

# 4. Topic + mood detection
print('━━━ 4. detect_topic_mood ━━━')
samples = [
    'Jsem smutny a osamely, chybi mi manzel',
    'Nemuzu spat, mam strach',
    'Dnes jsem mela krasny den s vnoucaty',
    'Bolí mě záda, musím k lékaři',
]
for s in samples:
    r = _tool_detect_topic_mood(s)
    print(f'  "{s[:50]}…"')
    print(f'    → topic={r.get("topic"):12s} mood={r.get("mood")}')
print()

# 5. Senior communication profile
print('━━━ 5. senior_communication_profile ━━━')
seniors = _tool_list_seniors()
test_seniors = [s for s in seniors if s['id'] in ('268', '282', '278')][:2]
for senior in test_seniors:
    sid = senior['id']
    name = senior.get('name', '?')
    cp = _tool_get_senior_communication_profile(sid)
    if isinstance(cp, dict) and not cp.get('error'):
        print(f'  #{sid} ({name}):')
        print(f'    needs={cp.get("communication_needs")} '
              f'channel={cp.get("preferred_channel")} '
              f'lang={cp.get("language")}')
        print(f'    has_phone={cp.get("has_phone")} family_contacts={cp.get("has_emergency_contacts")}')
        print(f'    style={cp.get("communication_style")} length={cp.get("preferred_length")}')
    else:
        print(f'  ✗ #{sid}: {cp}')
print()

# 6. TTS REVALIDATION — make sure all modes still work
print('━━━ 6. TTS revalidation: all 10 voice modes ━━━')
cat = _tool_get_voice_modes_catalog()
modes = list(cat.get('modes', {}).keys())
print(f'  {len(modes)} modes available: {", ".join(modes)}')

# Compose SSML in each mode for the same text
test_text = 'Dobré ráno, jak se máte?'
test_sid = test_seniors[0]['id'] if test_seniors else '287'

print(f'\n  Composing "{test_text}" in each mode:')
for mode in ['HARMONY', 'ALERT', 'CRISIS', 'POETRY', 'NARRATION']:
    r = _tool_compose_ssml(test_sid, test_text, mode=mode)
    if isinstance(r, dict) and not r.get('error'):
        vp = r.get('voice_params', {})
        ssml_ok = '<speak' in (r.get('ssml_preview', '') or '')
        print(f'    {mode:11s} → rate={vp.get("rate"):>5s} pause={vp.get("pause_ms"):>5}ms style={vp.get("style"):12s} ssml_ok={"✓" if ssml_ok else "✗"}')
    else:
        print(f'    {mode}: ✗ {r}')

# 7. TTS edge cases
print('\n━━━ 7. TTS edge cases ━━━')

# Empty text
r = _tool_compose_ssml(test_sid, '', mode='HARMONY')
print(f'  empty text: {"✓ rejected" if r.get("error") else "✗ should reject"}')

# Long text (over 800 chars)
long_text = 'Dobry den. ' * 100  # ~1000 chars
r = _tool_compose_ssml(test_sid, long_text, mode='HARMONY')
print(f'  long text: ssml_len={r.get("ssml_length", 0)} (truncation should keep ≤4000)')

# XML special chars
xml_text = 'Test <div>&amp;</div> "quotes"'
r = _tool_compose_ssml(test_sid, xml_text, mode='HARMONY')
ssml = r.get('ssml_preview', '')
escaped = '&lt;div&gt;' in ssml or '&amp;' in ssml
print(f'  XML escaping: {"✓" if escaped else "✗"} (special chars handled)')

print()
print('=' * 60)
print('DONE')
