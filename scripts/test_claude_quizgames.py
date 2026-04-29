#!/usr/bin/env python3
"""Test quiz + games + exercises tools."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_exercises_catalog,
    _tool_recommend_exercise,
    _tool_start_exercise_for_senior,
    _tool_generate_quiz,
    _tool_start_quiz_for_senior,
    _tool_get_quiz_history,
    _tool_recommend_brain_game,
    _tool_list_seniors,
)

print('=' * 60)
print('QUIZ + GAMES + EXERCISES — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Catalog
print('━━━ 1. get_exercises_catalog ━━━')
all_e = _tool_get_exercises_catalog()
print(f'  categories: {all_e.get("categories")}, total: {all_e.get("total")}')
mem = _tool_get_exercises_catalog(category='memory')
print(f'  memory games:')
for e in mem.get('exercises', []):
    print(f'    • {e["id"]:12s} {e["name"]:25s} | {e["difficulty"]:6s} | {e["duration_min"]}min')
print()

# 2. Recommend exercise (mode-aware)
print('━━━ 2. recommend_exercise ━━━')
r = _tool_recommend_exercise(test_sid)
top = r.get('top_recommendation') or {}
reason = r.get('reason', {})
print(f'  → {top.get("name")} (id={top.get("id")}, {top.get("duration_min")}min)')
print(f'  reason: brain_mode={reason.get("brain_mode")}, hour={reason.get("hour")}, target_category={reason.get("target_category")}')
print()

# Override target
print('  with target="calm":')
r2 = _tool_recommend_exercise(test_sid, target='calm')
print(f'  → {r2.get("top_recommendation", {}).get("name")} (category: {r2.get("reason", {}).get("target_category")})')

print('\n  with target="cognitive":')
r3 = _tool_recommend_exercise(test_sid, target='cognitive')
print(f'  → {r3.get("top_recommendation", {}).get("name")} (category: {r3.get("reason", {}).get("target_category")})')
print()

# 3. Start exercise (likely skipped if voice active)
print('━━━ 3. start_exercise_for_senior ━━━')
s = _tool_start_exercise_for_senior(test_sid, 'breath_478')
print(f'  → {s}')
print()

# 4. Brain game recommendation
print('━━━ 4. recommend_brain_game ━━━')
g = _tool_recommend_brain_game(test_sid)
top = g.get('recommendation') or {}
print(f'  → {top.get("name") if top else "(none)"} | reason: {g.get("reason")}')
print()

# 5. Quiz history
print('━━━ 5. get_quiz_history ━━━')
qh = _tool_get_quiz_history(test_sid, days=30)
print(f'  → {qh}')
print()

# 6. Generate quiz (real call to /api/kal/generate-quiz)
print('━━━ 6. generate_quiz ━━━')
q = _tool_generate_quiz('Česká příroda', difficulty='easy', count=3)
if q.get('error'):
    print(f'  ⚠ {q["error"][:120]}')
else:
    print(f'  topic={q.get("topic")} | difficulty={q.get("difficulty")} | count={q.get("count")}')
    for i, qq in enumerate(q.get('questions', []), 1):
        print(f'  Q{i}: {qq.get("question")}')
        print(f'      options: {qq.get("options")}')
        print(f'      correct: {qq.get("correct")}')
print()

# 7. Edge cases
print('━━━ 7. Edge cases ━━━')
r = _tool_get_exercises_catalog(category='BOGUS')
print(f'  invalid category rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_generate_quiz('', difficulty='easy')
print(f'  empty topic rejected: {"✓" if r.get("error") else "✗"}')
r = _tool_start_exercise_for_senior(test_sid, 'BOGUS_ID')
print(f'  invalid exercise_id rejected: {"✓" if r.get("error") else "✗"}')

print()
print('=' * 60)
print('DONE')
