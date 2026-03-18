# ============================================
# EDUCATION HELPERS v3.0.0
# ============================================
# Shared DB helpers, adaptive profile logic, and utilities
# v3.0: db_context, unified ? placeholders

from flask import g
from datetime import datetime
from database import get_connection, is_postgres, db_context
from utils import now_iso
import json
import logging

logger = logging.getLogger(__name__)


# ============================================
# DEFAULT ADAPTIVE PROFILE
# ============================================

_DEFAULT_PROFILE = {
    "level": "beginner",
    "total_score": 0,
    "total_quizzes": 0,
    "avg_score": 0,
    "strengths": [],
    "weaknesses": [],
    "recommended_courses": [],
    "completed_courses": [],
    "badges": [],
    "streak_days": 0,
    "last_activity": None,
    "communication_adaptation": None,
    "teacher_notes": []
}


# ============================================
# DB HELPERS — Progress
# ============================================

def db_save_progress(user_id, course_id, module_id=None, lesson_id=None, action='view', score=None, data=None):
    """Save education progress event to DB"""
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO education_progress (user_id, course_id, module_id, lesson_id, action, score, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, course_id, module_id, lesson_id, action, score, json.dumps(data or {}))
            )
    except Exception as e:
        logger.error(f"education progress save error: {e}")


def db_get_progress(user_id):
    """Reconstruct progress dict from DB events"""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT course_id, module_id, lesson_id, action, score, data, created_at "
                "FROM education_progress WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,)
            ).fetchall()

            progress = {}
            for row in rows:
                cid = row['course_id']
                if cid not in progress:
                    progress[cid] = {
                        "completed_modules": [],
                        "completed_lessons": [],
                        "quiz_scores": {},
                        "started_at": str(row['created_at']),
                        "last_activity": str(row['created_at'])
                    }
                p = progress[cid]
                p["last_activity"] = str(row['created_at'])

                action = row['action']
                mid = row['module_id']
                lid = row['lesson_id']

                if action == 'complete_lesson' and lid and lid not in p["completed_lessons"]:
                    p["completed_lessons"].append(lid)
                elif action == 'complete_module' and mid and mid not in p["completed_modules"]:
                    p["completed_modules"].append(mid)
                elif action == 'quiz_submit' and mid:
                    try:
                        extra = json.loads(row['data']) if isinstance(row['data'], str) else (row['data'] or {})
                    except Exception:
                        extra = {}
                    p["quiz_scores"][mid] = {
                        "score": row['score'] or 0,
                        "correct": extra.get("correct", 0),
                        "total": extra.get("total", 0),
                        "passed": (row['score'] or 0) >= 60,
                        "completed_at": str(row['created_at'])
                    }
                    if (row['score'] or 0) >= 60 and mid not in p["completed_modules"]:
                        p["completed_modules"].append(mid)
                elif action == 'scenario':
                    try:
                        extra = json.loads(row['data']) if isinstance(row['data'], str) else (row['data'] or {})
                    except Exception:
                        extra = {}
                    key = f"scenario_{extra.get('scenario_id', mid)}"
                    p[key] = extra

                if mid:
                    p["last_module"] = mid
                if lid:
                    p["last_lesson"] = lid

            return progress
    except Exception as e:
        logger.error(f"education progress load error: {e}")
        return {}


def db_count_active_learners():
    """Count distinct users with education progress"""
    try:
        with db_context() as db:
            row = db.execute('SELECT COUNT(DISTINCT user_id) as cnt FROM education_progress').fetchone()
            return row['cnt'] if row else 0
    except Exception:
        return 0


# ============================================
# DB HELPERS — Adaptive Profile
# ============================================

def get_adaptive_profile(user_id):
    """Získat nebo vytvořit adaptivní profil uživatele (z DB)"""
    try:
        with db_context() as db:
            row = db.execute(
                'SELECT level, data FROM education_profiles WHERE user_id = ?',
                (user_id,)
            ).fetchone()

            if row:
                try:
                    data = json.loads(row['data']) if isinstance(row['data'], str) else (row['data'] or {})
                except Exception:
                    data = {}
                profile = {**_DEFAULT_PROFILE, **data}
                profile["user_id"] = user_id
                profile["level"] = row['level'] or profile.get("level", "beginner")
                return profile
    except Exception as e:
        logger.error(f"education profile load error: {e}")
    return {**_DEFAULT_PROFILE, "user_id": user_id}


def save_adaptive_profile(user_id, profile):
    """Uložit adaptivní profil do DB"""
    try:
        data = {k: v for k, v in profile.items() if k not in ('user_id', 'level')}
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO education_profiles (user_id, level, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (user_id) DO UPDATE SET level = EXCLUDED.level, data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP",
                    (user_id, profile.get("level", "beginner"), json.dumps(data))
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO education_profiles (user_id, level, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (user_id, profile.get("level", "beginner"), json.dumps(data))
                )
    except Exception as e:
        logger.error(f"education profile save error: {e}")


def evaluate_and_adapt(user_id, course_id, module_id, score, education_courses):
    """Adaptivní vyhodnocení — přizpůsobí doporučení na základě výsledků."""
    profile = get_adaptive_profile(user_id)
    profile["total_quizzes"] += 1
    profile["total_score"] += score
    profile["avg_score"] = round(profile["total_score"] / profile["total_quizzes"]) if profile["total_quizzes"] > 0 else 0
    profile["last_activity"] = now_iso()

    course = education_courses.get(course_id, {})
    topic = course.get("category", course_id)

    if score >= 80 and topic not in profile["strengths"]:
        profile["strengths"].append(topic)
        if topic in profile["weaknesses"]:
            profile["weaknesses"].remove(topic)
    elif score < 60 and topic not in profile["weaknesses"]:
        profile["weaknesses"].append(topic)

    avg = profile["avg_score"]
    if avg >= 85 and profile["total_quizzes"] >= 5:
        profile["level"] = "advanced"
    elif avg >= 60 and profile["total_quizzes"] >= 3:
        profile["level"] = "intermediate"
    else:
        profile["level"] = "beginner"

    if score == 100 and "perfektni_score" not in profile["badges"]:
        profile["badges"].append("perfektni_score")
    if profile["total_quizzes"] >= 5 and "pilny_student" not in profile["badges"]:
        profile["badges"].append("pilny_student")
    if profile["total_quizzes"] >= 10 and "mistr_vzdelavani" not in profile["badges"]:
        profile["badges"].append("mistr_vzdelavani")
    if len(profile["strengths"]) >= 2 and "znalec" not in profile["badges"]:
        profile["badges"].append("znalec")

    profile["recommended_courses"] = []
    for cid, c in education_courses.items():
        if cid not in profile.get("completed_courses", []):
            if c["category"] in profile["weaknesses"]:
                profile["recommended_courses"].insert(0, {"id": cid, "title": c["title"], "reason": "Posílení slabší oblasti"})
            elif c["category"] not in profile["strengths"]:
                profile["recommended_courses"].append({"id": cid, "title": c["title"], "reason": "Nové téma k prozkoumání"})

    save_adaptive_profile(user_id, profile)
    return profile


def get_evaluation_message(profile):
    """Vrátí textové hodnocení studenta"""
    avg = profile["avg_score"]
    total = profile["total_quizzes"]

    if total == 0:
        return "Ještě jste nezačali žádný kvíz. Vyberte si kurz a zkuste to!"
    if avg >= 90:
        return f"Výborné výsledky! Průměrné skóre {avg}% z {total} kvízů. Jste pokročilý student."
    elif avg >= 70:
        return f"Dobré výsledky! Průměrné skóre {avg}% z {total} kvízů. Pokračujte a dosáhněte na pokročilou úroveň."
    elif avg >= 50:
        return f"Průměrné skóre {avg}% z {total} kvízů. Doporučujeme zopakovat slabší témata."
    else:
        return f"Průměrné skóre {avg}% z {total} kvízů. Doporučujeme projít lekce znovu a pomalu."


# ============================================
# DB HELPERS — Teacher Assignment
# ============================================

def db_get_teacher_assignment(user_id):
    """Get assigned teacher_id for user from DB"""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT teacher_id FROM education_assignments WHERE student_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            return row['teacher_id'] if row else None
    except Exception:
        return None


def db_assign_teacher(user_id, teacher_id, teacher_type='ai'):
    """Assign teacher to student in DB (upsert)"""
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO education_assignments (student_id, teacher_id, teacher_type, status) VALUES (?, ?, ?, 'active') "
                    "ON CONFLICT (student_id, teacher_id) WHERE status = 'active' "
                    "DO UPDATE SET teacher_type = EXCLUDED.teacher_type, updated_at = CURRENT_TIMESTAMP",
                    (user_id, teacher_id, teacher_type)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO education_assignments (student_id, teacher_id, teacher_type, status) VALUES (?, ?, ?, 'active')",
                    (user_id, teacher_id, teacher_type)
                )
    except Exception as e:
        logger.error(f"teacher assign error: {e}")


# ============================================
# Teacher helpers
# ============================================

def get_teacher_id():
    """Get current teacher's user_id from JWT"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


def get_teacher_students(teacher_id):
    """Get all students assigned to this teacher"""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT student_id FROM education_assignments WHERE teacher_id = ? AND status = 'active'",
                (teacher_id,)
            ).fetchall()
            return [r['student_id'] for r in rows]
    except Exception as e:
        logger.error(f"get teacher students error: {e}")
        return []


def verify_teacher_student(teacher_id, student_id):
    """Verify teacher has access to this student"""
    students = get_teacher_students(teacher_id)
    return student_id in students


def notify_teacher(student_id, event, data):
    """Send SocketIO notification to student's teacher(s). Non-blocking."""
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if not socketio:
            return

        with db_context() as db:
            rows = db.execute(
                "SELECT teacher_id FROM education_assignments WHERE student_id = ? AND status = 'active'",
                (student_id,)
            ).fetchall()

        for row in rows:
            socketio.emit(event, {**data, 'student_id': student_id}, room=f'user_{row["teacher_id"]}')
    except Exception:
        pass
