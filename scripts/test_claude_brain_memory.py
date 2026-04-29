#!/usr/bin/env python3
"""Test brain + memory tools of Claude agent."""
import sys, json, time
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_compute_brain_state,
    _tool_compute_empathy,
    _tool_get_speech_adaptation,
    _tool_get_full_profile,
    _tool_get_learning_state,
    _tool_update_learning,
    _tool_update_profile,
    _tool_list_seniors,
)

print('=' * 60)
print('BRAIN + MEMORY TOOLS — TEST')
print('=' * 60)
print()

print('━━━ BRAIN (math, no senior needed) ━━━')

# Compute Ψ(t) at C=15, alpha=0.6 — should give ALERT mode
psi = _tool_compute_brain_state('test', C=15, alpha=0.6)
if isinstance(psi, dict) and not psi.get('error'):
    print(f'  ✓ compute_brain_state(C=15, alpha=0.6):')
    print(f'    mode={psi.get("mode")} | E={psi.get("E"):.3f} | R={psi.get("R"):.3f} | S={psi.get("S"):.3f}')
    print(f'    coherence={psi.get("coherence"):.3f} | phi_index={psi.get("phi_index"):.3f}')
    speech = psi.get('speech', {})
    if speech:
        print(f'    speech: rate={speech.get("rate")} pause={speech.get("pause_ms")}ms')
else:
    print(f'  ✗ FAIL: {psi}')

# Compute Ψ(t) at edge of CRISIS
psi2 = _tool_compute_brain_state('test', C=28, alpha=0.3)
print(f'  ✓ compute_brain_state(C=28, alpha=0.3): mode={psi2.get("mode")} (should be CRISIS)')

# Empathy
emp = _tool_compute_empathy(0.7, 0.4, 0.6)
print(f'  ✓ compute_empathy(0.7, 0.4, 0.6): E={emp.get("E"):.3f}')
print()

# Per-senior tests
print('━━━ MEMORY (per senior) ━━━')
seniors = _tool_list_seniors()
test_seniors = []
for s in seniors:
    if s['id'] in ('268', '282', '272'):
        test_seniors.append(s)
if not test_seniors:
    test_seniors = seniors[:2]

for senior in test_seniors:
    sid = senior['id']
    name = senior.get('name', '?')
    print(f'\n  Senior #{sid} ({name}):')

    # speech_adaptation
    sa = _tool_get_speech_adaptation(sid)
    if 'error' in sa:
        print(f'    ✗ speech_adaptation: {sa["error"]}')
    elif sa.get('info'):
        print(f'    ✓ speech_adaptation: {sa["info"][:80]}')
    else:
        sp = sa.get('speech', {})
        print(f'    ✓ speech_adaptation: mode={sa.get("mode")} rate={sp.get("rate")} pause={sp.get("pause_ms")}ms')

    # full profile
    prof = _tool_get_full_profile(sid)
    if isinstance(prof, dict) and prof.get('error'):
        print(f'    ✗ full_profile: {prof["error"]}')
    elif isinstance(prof, dict) and prof.get('info'):
        print(f'    ✓ full_profile: {prof["info"]}')
    else:
        keys = list(prof.keys()) if isinstance(prof, dict) else []
        print(f'    ✓ full_profile: {len(keys)} fields — {keys[:6]}...')

    # learning state
    lrn = _tool_get_learning_state(sid)
    if isinstance(lrn, dict) and not lrn.get('error'):
        c_hist_len = len(lrn.get('C_history', []))
        print(f'    ✓ learning: interactions={lrn.get("interaction_count")}, '
              f'mood={lrn.get("last_mood")}, C_history_len={c_hist_len}, '
              f'crisis_count={lrn.get("crisis_count", 0)}')
    else:
        print(f'    ✗ learning: {lrn}')

# Test write tools on senior #287 (no cooldown, test account)
print()
print('━━━ MEMORY WRITE — round-trip test on #287 ━━━')
TAG = f'CLAUDE_BRAINMEM_{int(time.time())}'

# update_learning
r = _tool_update_learning('287', 'last_mood', f'test:{TAG}')
print(f'  update_learning: {r}')
lrn_back = _tool_get_learning_state('287')
ok_l = lrn_back.get('last_mood') == f'test:{TAG}'
print(f'  read back: last_mood={lrn_back.get("last_mood")} {"✓" if ok_l else "✗"}')

# update_profile (whitelisted key)
r = _tool_update_profile('287', 'notes', f'test note {TAG}')
print(f'  update_profile(notes): {r}')
prof_back = _tool_get_full_profile('287')
ok_p = isinstance(prof_back, dict) and TAG in (prof_back.get('notes') or '')
print(f'  read back: notes contains TAG {"✓" if ok_p else "✗"}')

# Try forbidden key
r = _tool_update_profile('287', 'phone', '+420999999999')
print(f'  update_profile(phone) — should reject: {r.get("error", "NOT REJECTED!!")}')

# Try forbidden learning key
r = _tool_update_learning('287', 'C_history', [1,2,3])
print(f'  update_learning(C_history) — should reject: {r.get("error", "NOT REJECTED!!")}')

# Cleanup
_tool_update_learning('287', 'last_mood', 'neutral')
_tool_update_profile('287', 'notes', '')
print()
print('=' * 60)
print('DONE')
