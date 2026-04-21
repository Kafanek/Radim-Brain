"""
🎓 EDUCATION PROGRESS ROUTES v1.0 (Sprint C)
=============================================================================
Backend sync for the learning module:
- Idempotent lesson progress upsert (education_lesson_progress)
- Stats (streak, points, weekly count, badges)
- Quiz results (new quiz_results table)
- Family weekly report (linked caregivers / relatives)
- Course certificate JSON

Auth: all endpoints require_auth. Family view additionally verifies
senior_family_links.confirmed=TRUE.
"""

import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

education_progress_bp = Blueprint('education_progress', __name__)


QUIZ_RESULTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS quiz_results (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        course_id TEXT,
        module_id TEXT,
        score INTEGER DEFAULT 0,
        correct INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        answers JSONB,
        client_id TEXT,
        taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_quiz_results_user ON quiz_results(user_id, taken_at DESC);
    CREATE INDEX IF NOT EXISTS idx_quiz_results_client ON quiz_results(user_id, client_id);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in QUIZ_RESULTS_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"quiz_results schema init: {e}")


def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _row_val(r, idx, key):
    if r is None:
        return None
    return r[idx] if isinstance(r, (list, tuple)) else r.get(key)


def _compute_streak(dates_set):
    """Given a set of YYYY-MM-DD strings, compute consecutive-day streak
    ending today (or yesterday — still counts). Returns int."""
    if not dates_set:
        return 0
    today = datetime.utcnow().date()
    # Accept today or yesterday as start anchor
    if today.strftime('%Y-%m-%d') in dates_set:
        anchor = today
    elif (today - timedelta(days=1)).strftime('%Y-%m-%d') in dates_set:
        anchor = today - timedelta(days=1)
    else:
        return 0
    streak = 0
    cur = anchor
    while cur.strftime('%Y-%m-%d') in dates_set:
        streak += 1
        cur -= timedelta(days=1)
    return streak


# ============================================================
# LESSON PROGRESS — idempotent upsert (offline lessons)
# ============================================================

@education_progress_bp.route('/api/education/progress/lesson', methods=['POST', 'OPTIONS'])
@require_auth
def sync_lesson_progress():
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    lesson_id = (data.get('lessonId') or data.get('lesson_id') or '').strip()
    if not lesson_id:
        return jsonify({'success': False, 'error': 'lessonId required'}), 400
    lesson_id = lesson_id[:64]
    category = (data.get('category') or '')[:32]
    score = int(data.get('score') or 0)
    completed = 1 if data.get('completed', True) else 0
    answers = data.get('answers') or []
    answers_json = json.dumps(answers)[:2000]
    time_spent = int(data.get('timeSpent') or 0)

    try:
        with db_context(commit=True) as db:
            # Upsert by UNIQUE(user_id, lesson_id). Keep max score.
            existing = db.execute(
                "SELECT score, completed FROM education_lesson_progress "
                "WHERE user_id = ? AND lesson_id = ?",
                (uid, lesson_id)
            ).fetchone()
            if existing:
                old_score = int(_row_val(existing, 0, 'score') or 0)
                new_score = max(old_score, score)
                db.execute(
                    "UPDATE education_lesson_progress SET "
                    "score = ?, completed = ?, category = ?, answers = ?, "
                    "time_spent = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = ? AND lesson_id = ?",
                    (new_score, completed, category, answers_json,
                     time_spent, uid, lesson_id)
                )
                return jsonify({'success': True, 'upserted': True, 'score': new_score})
            else:
                db.execute(
                    "INSERT INTO education_lesson_progress "
                    "(user_id, lesson_id, category, score, completed, answers, time_spent) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, lesson_id, category, score, completed,
                     answers_json, time_spent)
                )
                return jsonify({'success': True, 'inserted': True, 'score': score})
    except Exception as e:
        logger.error(f"sync_lesson_progress: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@education_progress_bp.route('/api/education/progress/lessons', methods=['GET'])
@require_auth
def list_lesson_progress():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT lesson_id, category, score, completed, time_spent, updated_at "
                "FROM education_lesson_progress "
                "WHERE user_id = ? ORDER BY updated_at DESC LIMIT 500",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_lesson_progress: {e}")
        return jsonify({'success': True, 'lessons': []})

    lessons = []
    for r in rows or []:
        lessons.append({
            'lessonId': _row_val(r, 0, 'lesson_id'),
            'category': _row_val(r, 1, 'category'),
            'score': int(_row_val(r, 2, 'score') or 0),
            'completed': bool(_row_val(r, 3, 'completed')),
            'timeSpent': int(_row_val(r, 4, 'time_spent') or 0),
            'updatedAt': str(_row_val(r, 5, 'updated_at') or ''),
        })
    return jsonify({'success': True, 'lessons': lessons, 'count': len(lessons)})


# ============================================================
# STATS — aggregated from lesson_progress + quiz_results
# ============================================================

@education_progress_bp.route('/api/education/stats/me', methods=['GET'])
@require_auth
def education_stats_me():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    weekly_goal = 5
    try:
        with db_context() as db:
            lesson_rows = db.execute(
                "SELECT lesson_id, category, score, updated_at "
                "FROM education_lesson_progress "
                "WHERE user_id = ? AND completed = ?",
                (uid, 1 if not is_postgres() else True)
            ).fetchall() or []

            week_ago = datetime.utcnow() - timedelta(days=7)
            weekly_count = 0
            dates_set = set()
            total_points = 0
            categories_touched = set()
            for r in lesson_rows:
                upd = _row_val(r, 3, 'updated_at')
                score = int(_row_val(r, 2, 'score') or 0)
                category = _row_val(r, 1, 'category')
                total_points += score
                if category:
                    categories_touched.add(category)
                # Parse date
                d = None
                try:
                    if isinstance(upd, datetime):
                        d = upd
                    elif isinstance(upd, str) and upd:
                        d = datetime.fromisoformat(upd.replace('Z', '').split('.')[0])
                except Exception:
                    d = None
                if d:
                    dates_set.add(d.strftime('%Y-%m-%d'))
                    if d >= week_ago:
                        weekly_count += 1
    except Exception as e:
        logger.error(f"education_stats lessons: {e}")
        lesson_rows = []
        weekly_count = 0
        total_points = 0
        dates_set = set()
        categories_touched = set()

    # Quiz results
    quiz_count = 0
    quiz_avg = 0
    try:
        with db_context() as db:
            qrows = db.execute(
                "SELECT score FROM quiz_results WHERE user_id = ?",
                (uid,)
            ).fetchall() or []
            scores = [int(_row_val(r, 0, 'score') or 0) for r in qrows]
            quiz_count = len(scores)
            quiz_avg = round(sum(scores) / len(scores)) if scores else 0
    except Exception:
        pass

    streak = _compute_streak(dates_set)
    done = len(lesson_rows)

    badges = [
        {'id': 'first',    'icon': '🌱', 'earned': done >= 1},
        {'id': 'five',     'icon': '⭐', 'earned': done >= 5},
        {'id': 'streak7',  'icon': '🔥', 'earned': streak >= 7},
        {'id': 'pts100',   'icon': '🏆', 'earned': total_points >= 100},
        {'id': 'pts500',   'icon': '💎', 'earned': total_points >= 500},
        {'id': 'quiz_ace', 'icon': '🎯', 'earned': quiz_avg >= 80 and quiz_count >= 3},
    ]

    return jsonify({
        'success': True,
        'lessonsCompleted': done,
        'totalPoints': total_points,
        'streak': streak,
        'weekly': {'done': weekly_count, 'goal': weekly_goal},
        'categoriesTouched': sorted(categories_touched),
        'quiz': {'count': quiz_count, 'avgScore': quiz_avg},
        'badges': badges,
    })


# ============================================================
# QUIZ RESULTS
# ============================================================

@education_progress_bp.route('/api/education/quiz-result', methods=['POST', 'OPTIONS'])
@require_auth
def save_quiz_result():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    course_id = (data.get('courseId') or '')[:64] or None
    module_id = (data.get('moduleId') or '')[:64] or None
    score = max(0, min(100, int(data.get('score') or 0)))
    correct = max(0, int(data.get('correct') or 0))
    total = max(0, int(data.get('total') or 0))
    client_id = (data.get('clientId') or '')[:64] or None
    answers = data.get('answers') or {}
    try:
        answers_json = json.dumps(answers)[:4000]
    except Exception:
        answers_json = '{}'

    try:
        with db_context(commit=True) as db:
            if client_id:
                existing = db.execute(
                    "SELECT id FROM quiz_results WHERE user_id = ? AND client_id = ?",
                    (uid, client_id)
                ).fetchone()
                if existing:
                    eid = _row_val(existing, 0, 'id')
                    return jsonify({'success': True, 'id': eid, 'deduped': True})

            if is_postgres():
                row = db.execute(
                    "INSERT INTO quiz_results "
                    "(user_id, course_id, module_id, score, correct, total, answers, client_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, course_id, module_id, score, correct, total,
                     answers_json, client_id)
                ).fetchone()
                new_id = _row_val(row, 0, 'id')
            else:
                cur = db.execute(
                    "INSERT INTO quiz_results "
                    "(user_id, course_id, module_id, score, correct, total, answers, client_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, course_id, module_id, score, correct, total,
                     answers_json, client_id)
                )
                new_id = getattr(cur, 'lastrowid', None)
        return jsonify({'success': True, 'id': new_id, 'score': score})
    except Exception as e:
        logger.error(f"save_quiz_result: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@education_progress_bp.route('/api/education/quiz-results', methods=['GET'])
@require_auth
def list_quiz_results():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, course_id, module_id, score, correct, total, taken_at "
                "FROM quiz_results WHERE user_id = ? "
                "ORDER BY taken_at DESC LIMIT 200",
                (uid,)
            ).fetchall()
    except Exception as e:
        logger.error(f"list_quiz_results: {e}")
        return jsonify({'success': True, 'results': []})

    results = [{
        'id': _row_val(r, 0, 'id'),
        'courseId': _row_val(r, 1, 'course_id'),
        'moduleId': _row_val(r, 2, 'module_id'),
        'score': int(_row_val(r, 3, 'score') or 0),
        'correct': int(_row_val(r, 4, 'correct') or 0),
        'total': int(_row_val(r, 5, 'total') or 0),
        'takenAt': str(_row_val(r, 6, 'taken_at') or ''),
    } for r in rows or []]
    return jsonify({'success': True, 'results': results, 'count': len(results)})


# ============================================================
# FAMILY WEEKLY REPORT (read-only for linked family)
# ============================================================

@education_progress_bp.route('/api/education/family/<senior_id>/weekly', methods=['GET'])
@require_auth
def family_weekly(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Verify senior_family_links
    try:
        with db_context() as db:
            link = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_id = ? AND confirmed = ?",
                (senior_id, uid, True if is_postgres() else 1)
            ).fetchone()
    except Exception:
        link = None
    if not link:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    # Aggregate last 7 days
    week_ago = datetime.utcnow() - timedelta(days=7)
    try:
        with db_context() as db:
            lrows = db.execute(
                "SELECT lesson_id, category, score, updated_at "
                "FROM education_lesson_progress "
                "WHERE user_id = ? AND completed = ? AND updated_at >= ?",
                (senior_id, 1 if not is_postgres() else True, week_ago)
            ).fetchall() or []
            qrows = db.execute(
                "SELECT score FROM quiz_results "
                "WHERE user_id = ? AND taken_at >= ?",
                (senior_id, week_ago)
            ).fetchall() or []
    except Exception as e:
        logger.error(f"family_weekly: {e}")
        lrows = []
        qrows = []

    cats = {}
    total_points = 0
    for r in lrows:
        cat = _row_val(r, 1, 'category') or 'other'
        sc = int(_row_val(r, 2, 'score') or 0)
        total_points += sc
        cats[cat] = cats.get(cat, 0) + 1

    quiz_scores = [int(_row_val(r, 0, 'score') or 0) for r in qrows]
    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'weekLessons': len(lrows),
        'weekPoints': total_points,
        'byCategory': cats,
        'weekQuizzes': len(quiz_scores),
        'weekQuizAvg': round(sum(quiz_scores) / len(quiz_scores)) if quiz_scores else 0,
    })


# ============================================================
# CERTIFICATE (JSON payload — frontend prints or PDFs)
# ============================================================

@education_progress_bp.route('/api/education/certificate/<course_id>', methods=['GET'])
@require_auth
def get_certificate(course_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Look up course from in-memory education_data
    try:
        from education_data import COURSES
    except Exception as e:
        return jsonify({'success': False, 'error': 'course data unavailable'}), 500
    course = None
    for c in COURSES if isinstance(COURSES, list) else COURSES.values() if isinstance(COURSES, dict) else []:
        cid = c.get('id') if isinstance(c, dict) else None
        if cid == course_id:
            course = c
            break
    if not course:
        return jsonify({'success': False, 'error': 'course not found'}), 404

    modules = course.get('modules') or []
    required_module_ids = [m.get('id') for m in modules if isinstance(m, dict) and m.get('id')]
    if not required_module_ids:
        return jsonify({'success': False, 'error': 'course has no modules'}), 400

    # Fetch all quiz results for this course + user
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT module_id, score FROM quiz_results "
                "WHERE user_id = ? AND course_id = ?",
                (uid, course_id)
            ).fetchall() or []
    except Exception:
        rows = []

    best_score_per_module = {}
    for r in rows:
        mid = _row_val(r, 0, 'module_id')
        sc = int(_row_val(r, 1, 'score') or 0)
        if mid is None:
            continue
        if sc > best_score_per_module.get(mid, -1):
            best_score_per_module[mid] = sc

    passed_modules = [m for m in required_module_ids
                      if best_score_per_module.get(m, 0) >= 70]
    all_passed = len(passed_modules) == len(required_module_ids)

    if not all_passed:
        return jsonify({
            'success': False,
            'error': 'course not completed',
            'passedModules': passed_modules,
            'requiredModules': required_module_ids,
            'progressPct': round(100 * len(passed_modules) / len(required_module_ids)),
        }), 403

    # Get user name from auth
    au = getattr(g, 'auth_user', None) or {}
    name = au.get('name') or au.get('email') or uid

    avg_score = round(
        sum(best_score_per_module.get(m, 0) for m in required_module_ids)
        / len(required_module_ids)
    )

    return jsonify({
        'success': True,
        'certificate': {
            'courseId': course_id,
            'courseTitle': course.get('title') or course.get('name') or course_id,
            'recipient': name,
            'userId': uid,
            'avgScore': avg_score,
            'issuedAt': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
            'modules': len(required_module_ids),
            'signature': 'Radim — Váš digitální společník',
        },
    })


logger.info("🎓 Education progress routes v1.0 loaded — lesson sync + stats + quiz + family + certificate")
