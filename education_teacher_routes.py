# ============================================
# 🏫 EDUCATION TEACHER DASHBOARD v2.0.0
# ============================================
# Teacher dashboard: overview, students, detail, analytics, assign.
# Task CRUD moved to education_task_routes.py
# ============================================

import logging
from flask import Blueprint, request, jsonify
from database import db_context
from auth_middleware import require_auth, require_teacher
from education_helpers import (
    now_iso, get_teacher_id, get_teacher_students, verify_teacher_student,
    get_adaptive_profile, db_get_progress, db_assign_teacher
)

logger = logging.getLogger(__name__)

education_teacher_bp = Blueprint('education_teacher', __name__)


# Lazy import to avoid circular dependency
def _get_courses():
    from education_data import EDUCATION_COURSES
    return EDUCATION_COURSES


# ============================================
# 🏫 TEACHER DASHBOARD ENDPOINTS
# ============================================

@education_teacher_bp.route('/api/education/teacher-dashboard', methods=['GET'])
@require_auth
@require_teacher
def teacher_dashboard():
    """Přehled učitele — počet studentů, průměrné skóre, nedávná aktivita, pending úkoly"""
    teacher_id = get_teacher_id()
    students = get_teacher_students(teacher_id)

    # Aggregate stats
    total_score = 0
    total_quizzes = 0
    student_summaries = []
    for sid in students:
        profile = get_adaptive_profile(sid)
        total_score += profile["avg_score"] * profile["total_quizzes"]
        total_quizzes += profile["total_quizzes"]
        student_summaries.append({
            "student_id": sid,
            "level": profile["level"],
            "avg_score": profile["avg_score"],
            "total_quizzes": profile["total_quizzes"]
        })

    avg_class_score = round(total_score / total_quizzes, 1) if total_quizzes > 0 else 0

    # Pending tasks count
    pending_tasks = 0
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM education_teacher_tasks WHERE teacher_id = ? AND status = 'submitted'",
                (teacher_id,)
            ).fetchone()
            pending_tasks = row['cnt'] if row else 0
    except Exception:
        pass

    return jsonify({
        "success": True,
        "teacher_id": teacher_id,
        "total_students": len(students),
        "avg_class_score": avg_class_score,
        "total_quizzes_taken": total_quizzes,
        "pending_tasks_to_grade": pending_tasks,
        "students_preview": student_summaries[:5],
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/students', methods=['GET'])
@require_auth
@require_teacher
def teacher_dashboard_students():
    """Seznam studentů přiřazených k učiteli (s paginací)"""
    teacher_id = get_teacher_id()
    all_students = get_teacher_students(teacher_id)

    # Pagination
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    limit = min(max(limit, 1), 100)  # clamp 1-100
    sort_by = request.args.get('sort', 'score')  # score, activity, completion

    result = []
    for sid in all_students:
        profile = get_adaptive_profile(sid)
        progress = db_get_progress(sid)

        # Completion %
        total_modules = 0
        completed_modules = 0
        last_activity = None
        for cid, cprog in progress.items():
            course = _get_courses().get(cid)
            if course:
                total_modules += len(course.get("modules", []))
                completed_modules += len(cprog.get("completed_modules", []))
                la = cprog.get("last_activity")
                if la and (not last_activity or la > last_activity):
                    last_activity = la

        completion_pct = round((completed_modules / total_modules) * 100) if total_modules > 0 else 0

        result.append({
            "student_id": sid,
            "level": profile["level"],
            "avg_score": profile["avg_score"],
            "total_quizzes": profile["total_quizzes"],
            "strengths": profile["strengths"],
            "weaknesses": profile["weaknesses"],
            "completion_percent": completion_pct,
            "last_activity": last_activity
        })

    # Sort
    if sort_by == 'activity':
        result.sort(key=lambda x: x["last_activity"] or "", reverse=True)
    elif sort_by == 'completion':
        result.sort(key=lambda x: x["completion_percent"], reverse=True)
    else:
        result.sort(key=lambda x: x["avg_score"])  # struggling first

    total = len(result)
    offset = (page - 1) * limit
    paginated = result[offset:offset + limit]

    return jsonify({
        "success": True,
        "teacher_id": teacher_id,
        "students": paginated,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if limit > 0 else 1,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/student/<student_id>', methods=['GET'])
@require_auth
@require_teacher
def teacher_dashboard_student_detail(student_id):
    """Detail studenta — profil, výsledky kvízů, AI doporučení"""
    teacher_id = get_teacher_id()
    if not verify_teacher_student(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student vám není přiřazen"}), 403

    profile = get_adaptive_profile(student_id)
    progress = db_get_progress(student_id)

    course_details = []
    for cid, cprog in progress.items():
        course = _get_courses().get(cid)
        if not course:
            continue
        total_modules = len(course.get("modules", []))
        completed = len(cprog.get("completed_modules", []))
        course_details.append({
            "course_id": cid,
            "course_title": course["title"],
            "total_modules": total_modules,
            "completed_modules": completed,
            "percent": round((completed / total_modules) * 100) if total_modules > 0 else 0,
            "quiz_scores": cprog.get("quiz_scores", {}),
            "completed_lessons": cprog.get("completed_lessons", []),
            "last_activity": cprog.get("last_activity")
        })

    # AI recommendations
    auto_recommendations = []
    if profile["avg_score"] < 60 and profile["total_quizzes"] > 0:
        auto_recommendations.append("Student potřebuje zopakovat základy.")
    if profile["total_quizzes"] == 0:
        auto_recommendations.append("Student ještě nezačal žádný kvíz. Motivovat k prvnímu pokusu.")
    for weakness in profile.get("weaknesses", []):
        auto_recommendations.append(f"Slabší oblast: {weakness}")
    if profile["avg_score"] >= 85:
        auto_recommendations.append("Výborný student. Doporučit pokročilejší materiály.")

    # Tasks for this student
    tasks = []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, title, task_type, status, grade, due_date, created_at FROM education_teacher_tasks "
                "WHERE student_id = ? AND teacher_id = ? ORDER BY created_at DESC LIMIT 20",
                (student_id, teacher_id)
            ).fetchall()
            tasks = [dict(r) for r in rows]
    except Exception:
        pass

    return jsonify({
        "success": True,
        "student": {
            "user_id": student_id,
            "level": profile["level"],
            "avg_score": profile["avg_score"],
            "total_quizzes": profile["total_quizzes"],
            "strengths": profile["strengths"],
            "weaknesses": profile["weaknesses"],
            "badges": profile["badges"]
        },
        "courses": course_details,
        "tasks": tasks,
        "teacher_notes": profile.get("teacher_notes", []),
        "ai_recommendations": auto_recommendations,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/assign-student', methods=['POST'])
@require_auth
@require_teacher
def teacher_assign_student():
    """Přiřadit studenta k učiteli (human teacher)"""
    teacher_id = get_teacher_id()
    data = request.json or {}
    student_id = data.get('student_id', '').strip()

    if not student_id:
        return jsonify({"success": False, "error": "student_id je vyžadováno"}), 400

    # Check if already assigned
    if verify_teacher_student(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student je již přiřazen"}), 409

    db_assign_teacher(student_id, teacher_id, 'human')

    return jsonify({
        "success": True,
        "message": f"Student {student_id} přiřazen",
        "teacher_id": teacher_id,
        "student_id": student_id,
        "timestamp": now_iso()
    }), 201


@education_teacher_bp.route('/api/education/teacher-dashboard/analytics', methods=['GET'])
@require_auth
@require_teacher
def teacher_analytics():
    """Class analytics — průměrné skóre podle kurzu, nejslabší témata"""
    teacher_id = get_teacher_id()
    students = get_teacher_students(teacher_id)

    if not students:
        return jsonify({
            "success": True,
            "message": "Žádní studenti",
            "analytics": {},
            "timestamp": now_iso()
        })

    # Per-course stats
    course_stats = {}
    all_weaknesses = {}
    top_students = []
    struggling_students = []

    for sid in students:
        profile = get_adaptive_profile(sid)
        progress = db_get_progress(sid)

        for cid, cprog in progress.items():
            if cid not in course_stats:
                course_stats[cid] = {"scores": [], "completions": 0, "total": 0}
            course = _get_courses().get(cid)
            if course:
                total_m = len(course.get("modules", []))
                completed_m = len(cprog.get("completed_modules", []))
                course_stats[cid]["total"] += 1
                if completed_m >= total_m:
                    course_stats[cid]["completions"] += 1
                for mid, sc in cprog.get("quiz_scores", {}).items():
                    if isinstance(sc, (int, float)):
                        course_stats[cid]["scores"].append(sc)

        for w in profile.get("weaknesses", []):
            all_weaknesses[w] = all_weaknesses.get(w, 0) + 1

        entry = {"student_id": sid, "avg_score": profile["avg_score"], "level": profile["level"]}
        if profile["avg_score"] >= 80:
            top_students.append(entry)
        elif profile["avg_score"] < 50 and profile["total_quizzes"] > 0:
            struggling_students.append(entry)

    # Summarize
    course_summary = {}
    for cid, stats in course_stats.items():
        course = _get_courses().get(cid, {})
        avg = round(sum(stats["scores"]) / len(stats["scores"]), 1) if stats["scores"] else 0
        course_summary[cid] = {
            "title": course.get("title", cid),
            "avg_quiz_score": avg,
            "students_enrolled": stats["total"],
            "students_completed": stats["completions"],
            "completion_rate": round((stats["completions"] / stats["total"]) * 100) if stats["total"] > 0 else 0
        }

    # Weaknesses sorted by frequency
    weakest_topics = sorted(all_weaknesses.items(), key=lambda x: x[1], reverse=True)[:5]

    return jsonify({
        "success": True,
        "analytics": {
            "total_students": len(students),
            "courses": course_summary,
            "weakest_topics": [{"topic": t, "count": c} for t, c in weakest_topics],
            "top_students": sorted(top_students, key=lambda x: x["avg_score"], reverse=True)[:5],
            "struggling_students": sorted(struggling_students, key=lambda x: x["avg_score"])[:5]
        },
        "timestamp": now_iso()
    })
