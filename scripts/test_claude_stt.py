#!/usr/bin/env python3
"""Test STT tools — Czech understanding pipeline + safety detection."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_stt_status,
    _tool_stt_normalize_text,
    _tool_stt_detect_safety,
    _tool_stt_classify_priority,
    _tool_stt_correct_text,
    _tool_stt_should_retry,
    _tool_stt_gather_params,
    _tool_stt_build_hints,
    _tool_list_seniors,
)

print('=' * 60)
print('STT TOOLS — TEST')
print('=' * 60)
print()

# 1. Status
print('━━━ 1. stt_status ━━━')
s = _tool_stt_status()
print(f'  azure_key_set: {s.get("azure_key_set")}')
print(f'  azure_region: {s.get("azure_region")}')
print(f'  speech_understanding: {s.get("speech_understanding")}')
print()

# 2. Normalize
print('━━━ 2. stt_normalize_text ━━━')
samples = [
    'Příliš Žluťoučký Kůň!',
    'Já bych chtěla pivo, prosím.',
    'Pán dříň',
]
for s in samples:
    r = _tool_stt_normalize_text(s)
    print(f'  "{s}"')
    print(f'    normalized:  {r.get("normalized")}')
    print(f'    no_diacritics: {r.get("no_diacritics")}')
print()

# 3. Safety detection (fuzzy)
print('━━━ 3. stt_detect_safety (fuzzy) ━━━')
safety_samples = [
    'pomoc!',
    'pomo',          # truncated - fuzzy should catch
    'pomc',          # typo - fuzzy
    'spadla jsem',
    'nemuzu vstat',  # no diacritics
    'dnes je hezky den',  # not safety
]
for text in safety_samples:
    r = _tool_stt_detect_safety(text)
    detected = r.get('detected') if isinstance(r, dict) else r
    print(f'  "{text:30s}" → detected={detected}')
print()

# 4. Priority classification
print('━━━ 4. stt_classify_priority ━━━')
priority_samples = [
    ('Pomoc! Pomoc!', 0.9),
    ('Spadla jsem ze schodů', 0.85),
    ('Nemůžu spát, mám strach', 0.8),
    ('Boli mě záda', 0.85),
    ('Dobré ráno, jak se máte?', 0.95),
]
for text, conf in priority_samples:
    r = _tool_stt_classify_priority(text, conf)
    pr = r.get('priority') if isinstance(r, dict) else r
    print(f'  "{text[:40]:40s}" → priority={pr}')
print()

# 5. STT correction
print('━━━ 5. stt_correct_text ━━━')
typo_samples = [
    'koupila jsem si parazol',  # paracetamol typo
    'beru tu pruhonickou na cukr',
    'volala jana pres internet',
]
for text in typo_samples:
    r = _tool_stt_correct_text(text)
    print(f'  in:  "{text}"')
    print(f'  out: "{r.get("corrected", "?")}" (changed={r.get("changed")})')
print()

# 6. Should retry
print('━━━ 6. stt_should_retry ━━━')
for text, conf in [('hmm', 0.3), ('Dobré ráno', 0.95), ('něco něco', 0.55)]:
    r = _tool_stt_should_retry(text, conf)
    print(f'  "{text:25s}" conf={conf} → retry={r.get("retry")} reason={r.get("reason","")[:50]}')
print()

# 7. Gather params per senior
print('━━━ 7. stt_gather_params + stt_build_hints ━━━')
seniors = _tool_list_seniors()
for s in seniors[:2]:
    sid = s['id']
    name = s.get('name', '?')
    p = _tool_stt_gather_params(sid)
    h = _tool_stt_build_hints(sid)
    print(f'  #{sid} ({name}):')
    if isinstance(p, dict) and not p.get('error'):
        print(f'    params: timeout={p.get("timeout")} speechTimeout={p.get("speechTimeout")} '
              f'lang={p.get("language")} hints={len(p.get("hints", []) or [])}')
    if isinstance(h, dict) and not h.get('error'):
        print(f'    custom_hints: {h.get("count")} items')

print()
print('=' * 60)
print('DONE')
