#!/usr/bin/env python3
"""Test education tools — courses, lessons, progress, scenarios."""
import sys, json
sys.path.insert(0, '.')

from claude_autonomous_agent import (
    _tool_get_education_courses,
    _tool_get_lesson_progress,
    _tool_get_recommended_lessons,
    _tool_get_lesson_content,
    _tool_get_assignments,
    _tool_recommend_scenario,
    _tool_list_seniors,
)

print('=' * 60)
print('EDUCATION — TEST')
print('=' * 60)
print()

seniors = _tool_list_seniors()
test_sid = next((s['id'] for s in seniors if s['id'] in ('268', '282', '287')), '287')
print(f'Test senior: #{test_sid}')
print()

# 1. Courses catalog
print('━━━ 1. get_education_courses ━━━')
c = _tool_get_education_courses()
print(f'  count: {c.get("count", 0)}')
for course in (c.get('courses') or [])[:4]:
    print(f'    • {course.get("course_id"):20s} | {course.get("title", "")[:40]:40s} | {course.get("modules_count")}M | {course.get("level")}')
print()

# 2. Progress
print('━━━ 2. get_lesson_progress ━━━')
p = _tool_get_lesson_progress(test_sid)
if isinstance(p, dict) and not p.get('error'):
    print(f'  level: {p.get("level")}')
    print(f'  modules completed: {p.get("total_modules_completed")}')
    print(f'  courses active: {p.get("courses_active")}')
    print(f'  badges: {len(p.get("badges", []))}')
    print(f'  recommended: {p.get("recommended_courses", [])[:5]}')
else:
    print(f'  → {p}')
print()

# 3. Recommendations
print('━━━ 3. get_recommended_lessons ━━━')
r = _tool_get_recommended_lessons(test_sid, limit=3)
if isinstance(r, dict) and not r.get('error'):
    print(f'  count: {r.get("count", 0)} | senior_level: {r.get("senior_level")}')
    print(f'  needs: {r.get("senior_needs")}')
    for rec in (r.get('recommendations') or []):
        print(f'    • {rec.get("course_id"):15s}/{rec.get("module_id"):20s} | {rec.get("title", "")[:40]} | {rec.get("reason")}')
else:
    print(f'  → {r}')
print()

# 4. Lesson content (first available)
print('━━━ 4. get_lesson_content ━━━')
courses = _tool_get_education_courses()
if courses.get('courses'):
    cid = courses['courses'][0]['course_id']
    # Get first module from this course
    from education_data import EDUCATION_COURSES
    course = EDUCATION_COURSES.get(cid, {})
    modules = course.get('modules', {})
    if modules:
        mid = list(modules.keys())[0]
        l = _tool_get_lesson_content(cid, mid)
        if isinstance(l, dict) and not l.get('error'):
            print(f'  course: {cid} module: {mid}')
            print(f'  title: {l.get("title")}')
            print(f'  duration: {l.get("duration_min")}min, level={l.get("level")}')
            print(f'  content preview: {(l.get("content") or "")[:150]}…')
            print(f'  key_points: {len(l.get("key_points", []))}, has_scenario: {l.get("has_scenario")}')
            print(f'  quiz_questions: {l.get("quiz_questions_count", 0)}')
        else:
            print(f'  → {l}')
print()

# 5. Assignments
print('━━━ 5. get_assignments ━━━')
a = _tool_get_assignments(test_sid, status='active')
print(f'  count: {a.get("count", 0)} | filter: {a.get("status_filter")}')
for asg in (a.get('assignments') or [])[:3]:
    print(f'    • {asg.get("title")} (due: {asg.get("due_date")}) — {asg.get("status")}')
print()

# 6. Scenario recommendations
print('━━━ 6. recommend_scenario ━━━')
test_situations = [
    'alzheimer agitace',
    'samota deprese',
    'odmítá léky',
    'pád koupelna',
]
for sit in test_situations:
    s = _tool_recommend_scenario(test_sid, sit)
    if isinstance(s, dict) and s.get('scenario_id'):
        print(f'  "{sit}" → {s.get("scenario_id")} (match={s.get("match_score")}, options={s.get("options_count")})')
        print(f'      title: {(s.get("title") or "")[:60]}')
    else:
        print(f'  "{sit}" → {s.get("info", "no match")}')
print()

print('=' * 60)
print('DONE')
