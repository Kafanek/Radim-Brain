#!/usr/bin/env python3
"""Test TTS subsystem of Claude agent — voice modes, memory, composition, generation, feedback."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_voice_modes_catalog,
    _tool_get_voice_memory,
    _tool_compose_ssml,
    _tool_generate_voice_audio,
    _tool_record_voice_feedback,
    _tool_list_seniors,
)

print('=' * 60)
print('TTS TOOLS — TEST (5 tools, voice + memory)')
print('=' * 60)
print()

# 1. Catalog (no senior needed)
print('━━━ 1. get_voice_modes_catalog ━━━')
cat = _tool_get_voice_modes_catalog()
if isinstance(cat, dict) and not cat.get('error'):
    modes = cat.get('modes', {})
    print(f'  ✓ {len(modes)} modes loaded')
    for m in ['HARMONY', 'ALERT', 'CRISIS']:
        p = modes.get(m, {})
        print(f'    {m}: style={p.get("style")} rate={p.get("rate")} pause={p.get("pause_ms")}ms')
else:
    print(f'  ✗ FAIL: {cat}')
print()

# 2. Get test seniors
seniors = _tool_list_seniors()
test_seniors = [s for s in seniors if s['id'] in ('268', '282', '287')]
if not test_seniors:
    test_seniors = seniors[:2]

# 2. voice_memory + compose_ssml + generate (Anna #268 — should be HARMONY)
for senior in test_seniors[:2]:
    sid = senior['id']
    name = senior.get('name', '?')
    print(f'━━━ Senior #{sid} ({name}) ━━━')

    # voice_memory
    vm = _tool_get_voice_memory(sid)
    if isinstance(vm, dict) and not vm.get('error'):
        learned = vm.get('learned_prefs', {})
        stats = vm.get('interaction_stats', {})
        print(f'  ✓ voice_memory: maturity={vm.get("maturity")} | '
              f'rate={learned.get("preferred_rate_pct")}% pause={learned.get("preferred_pause_ms")}ms | '
              f'interactions={stats.get("total")}')
        print(f'    hint: {vm.get("_hint", "")[:80]}')
    else:
        print(f'  ✗ voice_memory: {vm}')

    # compose_ssml (auto-mode)
    text = f'Dobrý den, {name}. Jak se dnes máte?'
    ssml = _tool_compose_ssml(sid, text)
    if isinstance(ssml, dict) and not ssml.get('error'):
        vp = ssml.get('voice_params', {})
        print(f'  ✓ compose_ssml: mode={ssml.get("mode")} | '
              f'rate={vp.get("rate")} pitch={vp.get("pitch")} pause={vp.get("pause_ms")}ms')
        print(f'    SSML preview: {ssml.get("ssml_preview", "")[:120]}…')
    else:
        print(f'  ✗ compose_ssml: {ssml}')
    print()

# 3. generate_voice_audio — JEN JEDNOU pro úsporu Azure
print('━━━ 3. generate_voice_audio (1× Azure call) ━━━')
sid = test_seniors[0]['id']
audio = _tool_generate_voice_audio(sid, 'Test hlasu Radim. Dnes je krásný den.', mode='HARMONY')
if isinstance(audio, dict) and not audio.get('error'):
    print(f'  ✓ Audio generated: {audio.get("audio_kb")}KB | mode={audio.get("mode")} | '
          f'cost=${audio.get("cost_usd_estimate")} | remaining={audio.get("generations_remaining")}')
else:
    print(f'  ✗ generate FAILED: {audio}')
print()

# 4. record_voice_feedback (round-trip)
print('━━━ 4. record_voice_feedback round-trip on #287 ━━━')
TEST_SID = '287'
# Get baseline
vm0 = _tool_get_voice_memory(TEST_SID)
n_before = vm0.get('interaction_stats', {}).get('total', 0)
print(f'  baseline: total={n_before}')

# Record positive feedback
r = _tool_record_voice_feedback(TEST_SID, 'positive', voice_mode='HARMONY')
print(f'  record(positive): {r}')

vm1 = _tool_get_voice_memory(TEST_SID)
n_after = vm1.get('interaction_stats', {}).get('total', 0)
ok = n_after == n_before + 1
print(f'  after: total={n_after} {"✓" if ok else "✗"} (delta {n_after - n_before})')

# Try invalid event_type
r_bad = _tool_record_voice_feedback(TEST_SID, 'bogus_event')
print(f'  invalid event reject: {"✓" if r_bad.get("error") else "✗"}')

# Try invalid mode in compose
ssml_bad = _tool_compose_ssml(TEST_SID, 'test', mode='INVALID_MODE')
# Should fall back to HARMONY (voice_filter does this)
print(f'  invalid mode fallback: mode={ssml_bad.get("mode")} (expects HARMONY fallback)')

print()
print('=' * 60)
print('DONE')
