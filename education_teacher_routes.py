# ============================================
# 🏫 EDUCATION TEACHER DASHBOARD
# ============================================
# Teacher/logoped endpoints for managing students.
# Extracted from education_routes.py for maintainability.
# All @require_auth + @require_teacher secured.

from flask import Blueprint, request, jsonify, g
from database import get_connection, is_postgres
from auth_middleware import require_auth, require_teacher
from education_helpers import (
    now_iso, get_teacher_id, get_teacher_students, verify_teacher_student,
    get_adaptive_profile, db_get_progress, db_assign_teacher, notify_teacher
)
import json
import logging

logger = logging.getLogger(__name__)

education_teacher_bp = Blueprint('education_teacher', __name__)


# Lazy import to avoid circular dependency
def _get_courses():
    from education_data import EDUCATION_COURSES
    return EDUCATION_COURSES


def _get_teachers():
    from education_data import TEACHERS
    return TEACHERS


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
    db = None
    try:
        db = get_connection()
        if is_postgres():
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM education_teacher_tasks WHERE teacher_id = %s AND status = 'submitted'",
                (teacher_id,)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM education_teacher_tasks WHERE teacher_id = ? AND status = 'submitted'",
                (teacher_id,)
            ).fetchone()
        pending_tasks = row['cnt'] if row else 0
    except Exception:
        pass

    finally:
        if db:
            try:
                db.close()
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

    # Reuse existing teacher_review logic
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
    db = None
    try:
        db = get_connection()
        if is_postgres():
            rows = db.execute(
                "SELECT id, title, task_type, status, grade, due_date, created_at FROM education_teacher_tasks "
                "WHERE student_id = %s AND teacher_id = %s ORDER BY created_at DESC LIMIT 20",
                (student_id, teacher_id)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, title, task_type, status, grade, due_date, created_at FROM education_teacher_tasks "
                "WHERE student_id = ? AND teacher_id = ? ORDER BY created_at DESC LIMIT 20",
                (student_id, teacher_id)
            ).fetchall()
        tasks = [dict(r) for r in rows]
    except Exception:
        pass

    finally:
        if db:
            try:
                db.close()
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


@education_teacher_bp.route('/api/education/teacher-dashboard/student/<student_id>/task', methods=['POST'])
@require_auth
@require_teacher
def teacher_create_task(student_id):
    """Učitel zadá úkol studentovi"""
    teacher_id = get_teacher_id()
    if not verify_teacher_student(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student vám není přiřazen"}), 403

    data = request.json or {}
    title = data.get('title', '').strip()
    if not title:
        return jsonify({"success": False, "error": "title je vyžadováno"}), 400
    if len(title) > 500:
        return jsonify({"success": False, "error": "title max 500 znaků"}), 400

    description = data.get('description', '')
    if len(str(description)) > 50000:
        return jsonify({"success": False, "error": "description max 50 000 znaků"}), 400

    task_type = data.get('task_type', 'homework')
    course_id = data.get('course_id')
    module_id = data.get('module_id')
    due_date = data.get('due_date')

    # Validate due_date format
    if due_date:
        try:
            from datetime import datetime as _dt
            _dt.strptime(due_date, '%Y-%m-%d')
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "due_date musí být ve formátu YYYY-MM-DD"}), 400

    valid_types = ('homework', 'reading', 'quiz', 'scenario', 'exercise')
    if task_type not in valid_types:
        task_type = 'homework'

    db = None
    try:
        db = get_connection()
        if is_postgres():
            row = db.execute(
                '''INSERT INTO education_teacher_tasks
                   (teacher_id, student_id, title, description, task_type, course_id, module_id, due_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id''',
                (teacher_id, student_id, title, description, task_type, course_id, module_id, due_date)
            ).fetchone()
            task_id = row['id'] if row else None
        else:
            cursor = db.execute(
                '''INSERT INTO education_teacher_tasks
                   (teacher_id, student_id, title, description, task_type, course_id, module_id, due_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (teacher_id, student_id, title, description, task_type, course_id, module_id, due_date)
            )
            task_id = cursor.lastrowid
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    # SocketIO notification (if available)
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('education_new_task', {
                'task_id': task_id,
                'title': title,
                'task_type': task_type,
                'teacher_id': teacher_id,
                'due_date': due_date
            }, room=f'user_{student_id}')
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": f"Úkol '{title}' zadán",
        "task_id": task_id,
        "student_id": student_id,
        "timestamp": now_iso()
    }), 201


@education_teacher_bp.route('/api/education/teacher-dashboard/student/<student_id>/tasks', methods=['GET'])
@require_auth
@require_teacher
def teacher_get_student_tasks(student_id):
    """Seznam úkolů pro studenta (filtr: status)"""
    teacher_id = get_teacher_id()
    if not verify_teacher_student(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student vám není přiřazen"}), 403

    status_filter = request.args.get('status')

    db = None
    try:
        db = get_connection()
        if status_filter:
            if is_postgres():
                rows = db.execute(
                    "SELECT * FROM education_teacher_tasks WHERE student_id = %s AND teacher_id = %s AND status = %s ORDER BY created_at DESC LIMIT 100",
                    (student_id, teacher_id, status_filter)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM education_teacher_tasks WHERE student_id = ? AND teacher_id = ? AND status = ? ORDER BY created_at DESC LIMIT 100",
                    (student_id, teacher_id, status_filter)
                ).fetchall()
        else:
            if is_postgres():
                rows = db.execute(
                    "SELECT * FROM education_teacher_tasks WHERE student_id = %s AND teacher_id = %s AND status != 'deleted' ORDER BY created_at DESC LIMIT 100",
                    (student_id, teacher_id)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM education_teacher_tasks WHERE student_id = ? AND teacher_id = ? AND status != 'deleted' ORDER BY created_at DESC LIMIT 100",
                    (student_id, teacher_id)
                ).fetchall()

        tasks = []
        for r in rows:
            task = dict(r)
            # Parse student_submission if string
            sub = task.get('student_submission')
            if isinstance(sub, str):
                try:
                    task['student_submission'] = json.loads(sub)
                except Exception:
                    task['student_submission'] = {}
            # Serialize dates
            for k in ('created_at', 'updated_at', 'due_date'):
                if task.get(k) and hasattr(task[k], 'isoformat'):
                    task[k] = task[k].isoformat()
            tasks.append(task)

    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "tasks": tasks,
        "total": len(tasks),
        "student_id": student_id,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/task/<int:task_id>/grade', methods=['PUT'])
@require_auth
@require_teacher
def teacher_grade_task(task_id):
    """Učitel ohodnotí odevzdaný úkol"""
    teacher_id = get_teacher_id()
    data = request.json or {}
    grade = data.get('grade', '').strip()
    feedback = data.get('feedback', '').strip()

    if not grade:
        return jsonify({"success": False, "error": "grade je vyžadováno"}), 400
    if len(grade) > 20:
        return jsonify({"success": False, "error": "grade max 20 znaků"}), 400
    if len(feedback) > 10000:
        return jsonify({"success": False, "error": "feedback max 10 000 znaků"}), 400

    db = None
    try:
        db = get_connection()
        # Verify task belongs to this teacher
        if is_postgres():
            row = db.execute(
                "SELECT id, student_id, status FROM education_teacher_tasks WHERE id = %s AND teacher_id = %s",
                (task_id, teacher_id)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id, student_id, status FROM education_teacher_tasks WHERE id = ? AND teacher_id = ?",
                (task_id, teacher_id)
            ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Úkol nenalezen nebo vám nepatří"}), 404

        student_id = row['student_id']

        if is_postgres():
            db.execute(
                "UPDATE education_teacher_tasks SET grade = %s, teacher_feedback = %s, status = 'graded', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (grade, feedback, task_id)
            )
        else:
            db.execute(
                "UPDATE education_teacher_tasks SET grade = ?, teacher_feedback = ?, status = 'graded', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (grade, feedback, task_id)
            )
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    # SocketIO notification
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('education_task_graded', {
                'task_id': task_id,
                'grade': grade,
                'feedback': feedback
            }, room=f'user_{student_id}')
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": f"Úkol ohodnocen: {grade}",
        "task_id": task_id,
        "grade": grade,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/task/<int:task_id>', methods=['PUT'])
@require_auth
@require_teacher
def teacher_update_task(task_id):
    """Učitel upraví úkol (title, description, due_date, task_type) — ne grading"""
    teacher_id = get_teacher_id()
    data = request.json or {}

    db = None
    try:
        db = get_connection()
        # Verify task belongs to this teacher
        if is_postgres():
            row = db.execute(
                "SELECT id, status FROM education_teacher_tasks WHERE id = %s AND teacher_id = %s",
                (task_id, teacher_id)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id, status FROM education_teacher_tasks WHERE id = ? AND teacher_id = ?",
                (task_id, teacher_id)
            ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Úkol nenalezen nebo vám nepatří"}), 404

        if row['status'] == 'graded':
            return jsonify({"success": False, "error": "Ohodnocený úkol nelze upravit"}), 400

        # Build SET clause dynamically
        updates = []
        params = []
        for field in ('title', 'description', 'task_type', 'course_id', 'module_id', 'due_date'):
            if field in data:
                val = data[field]
                if field == 'title' and (not val or not val.strip()):
                    return jsonify({"success": False, "error": "title nemůže být prázdné"}), 400
                if field == 'title' and len(val) > 500:
                    return jsonify({"success": False, "error": "title max 500 znaků"}), 400
                if field == 'description' and len(str(val)) > 50000:
                    return jsonify({"success": False, "error": "description max 50 000 znaků"}), 400
                if field == 'task_type' and val not in ('homework', 'reading', 'quiz', 'scenario', 'exercise'):
                    val = 'homework'
                ph = "%s" if is_postgres() else "?"
                updates.append(f"{field} = {ph}")
                params.append(val.strip() if isinstance(val, str) else val)

        if not updates:
            return jsonify({"success": False, "error": "Žádné pole k aktualizaci"}), 400

        ph = "%s" if is_postgres() else "?"
        updates.append(f"updated_at = CURRENT_TIMESTAMP")
        params.append(task_id)
        sql = f"UPDATE education_teacher_tasks SET {', '.join(updates)} WHERE id = {ph}"
        db.execute(sql, tuple(params))
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "message": "Úkol aktualizován",
        "task_id": task_id,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/teacher-dashboard/task/<int:task_id>', methods=['DELETE'])
@require_auth
@require_teacher
def teacher_delete_task(task_id):
    """Učitel smaže úkol (soft-delete -> status='deleted')"""
    teacher_id = get_teacher_id()

    db = None
    try:
        db = get_connection()
        # Verify task belongs to this teacher
        if is_postgres():
            row = db.execute(
                "SELECT id FROM education_teacher_tasks WHERE id = %s AND teacher_id = %s",
                (task_id, teacher_id)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id FROM education_teacher_tasks WHERE id = ? AND teacher_id = ?",
                (task_id, teacher_id)
            ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Úkol nenalezen nebo vám nepatří"}), 404

        # Soft delete
        if is_postgres():
            db.execute(
                "UPDATE education_teacher_tasks SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (task_id,)
            )
        else:
            db.execute(
                "UPDATE education_teacher_tasks SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (task_id,)
            )
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "message": "Úkol smazán",
        "task_id": task_id,
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


# ============================================
# 📋 STUDENT TASK ENDPOINTS — Phase 2
# ============================================


@education_teacher_bp.route('/api/education/my-tasks', methods=['GET'])
@require_auth
def student_my_tasks():
    """Student vidí svoje úkoly"""
    user = getattr(g, 'auth_user', {})
    student_id = str(user.get('id', user.get('user_id', '')))

    if not student_id:
        return jsonify({"success": False, "error": "Neplatný uživatel"}), 401

    status_filter = request.args.get('status')

    db = None
    try:
        db = get_connection()
        if status_filter:
            if is_postgres():
                rows = db.execute(
                    "SELECT id, title, description, task_type, course_id, module_id, due_date, status, grade, teacher_feedback, created_at "
                    "FROM education_teacher_tasks WHERE student_id = %s AND status = %s ORDER BY created_at DESC",
                    (student_id, status_filter)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, title, description, task_type, course_id, module_id, due_date, status, grade, teacher_feedback, created_at "
                    "FROM education_teacher_tasks WHERE student_id = ? AND status = ? ORDER BY created_at DESC",
                    (student_id, status_filter)
                ).fetchall()
        else:
            if is_postgres():
                rows = db.execute(
                    "SELECT id, title, description, task_type, course_id, module_id, due_date, status, grade, teacher_feedback, created_at "
                    "FROM education_teacher_tasks WHERE student_id = %s AND status != 'deleted' ORDER BY created_at DESC",
                    (student_id,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, title, description, task_type, course_id, module_id, due_date, status, grade, teacher_feedback, created_at "
                    "FROM education_teacher_tasks WHERE student_id = ? AND status != 'deleted' ORDER BY created_at DESC",
                    (student_id,)
                ).fetchall()

        tasks = []
        for r in rows:
            task = dict(r)
            for k in ('created_at', 'due_date'):
                if task.get(k) and hasattr(task[k], 'isoformat'):
                    task[k] = task[k].isoformat()
            tasks.append(task)

    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "tasks": tasks,
        "total": len(tasks),
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/my-tasks/<int:task_id>/submit', methods=['POST'])
@require_auth
def student_submit_task(task_id):
    """Student odevzdá úkol"""
    user = getattr(g, 'auth_user', {})
    student_id = str(user.get('id', user.get('user_id', '')))
    data = request.json or {}
    submission = data.get('submission', {})

    if not student_id:
        return jsonify({"success": False, "error": "Neplatný uživatel"}), 401

    # Validate submission size (max 1 MB serialized)
    try:
        submission_json = json.dumps(submission)
        if len(submission_json) > 1_000_000:
            return jsonify({"success": False, "error": "Submission příliš velké (max 1 MB)"}), 413
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Neplatný formát submission"}), 400

    db = None
    try:
        db = get_connection()
        # Verify task belongs to student
        if is_postgres():
            row = db.execute(
                "SELECT id, teacher_id, status FROM education_teacher_tasks WHERE id = %s AND student_id = %s",
                (task_id, student_id)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id, teacher_id, status FROM education_teacher_tasks WHERE id = ? AND student_id = ?",
                (task_id, student_id)
            ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Úkol nenalezen"}), 404

        if row['status'] == 'graded':
            return jsonify({"success": False, "error": "Úkol je již ohodnocen"}), 400

        teacher_id = row['teacher_id']
        # submission_json already validated and serialized above

        if is_postgres():
            db.execute(
                "UPDATE education_teacher_tasks SET student_submission = %s, status = 'submitted', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (submission_json, task_id)
            )
        else:
            db.execute(
                "UPDATE education_teacher_tasks SET student_submission = ?, status = 'submitted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (submission_json, task_id)
            )
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    # SocketIO notification to teacher
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit('education_task_submitted', {
                'task_id': task_id,
                'student_id': student_id
            }, room=f'user_{teacher_id}')
    except Exception:
        pass

    return jsonify({
        "success": True,
        "message": "Úkol odevzdán",
        "task_id": task_id,
        "timestamp": now_iso()
    })


@education_teacher_bp.route('/api/education/my-teacher', methods=['GET'])
@require_auth
def student_my_teacher():
    """Student vidí svého učitele (human nebo AI) + poznámky"""
    user = getattr(g, 'auth_user', {})
    student_id = str(user.get('id', user.get('user_id', '')))

    if not student_id:
        return jsonify({"success": False, "error": "Neplatný uživatel"}), 401

    # Get all assignments (human + AI)
    db = None
    try:
        db = get_connection()
        if is_postgres():
            rows = db.execute(
                "SELECT teacher_id, teacher_type, created_at FROM education_assignments WHERE student_id = %s AND status = 'active' ORDER BY created_at DESC",
                (student_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT teacher_id, teacher_type, created_at FROM education_assignments WHERE student_id = ? AND status = 'active' ORDER BY created_at DESC",
                (student_id,)
            ).fetchall()
    except Exception:
        rows = []

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    teachers = []
    for r in rows:
        t = {
            "teacher_id": r['teacher_id'],
            "teacher_type": r['teacher_type'],
            "assigned_at": r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at'])
        }
        # If AI teacher, add info from TEACHERS dict
        if r['teacher_type'] == 'ai':
            ai_info = _get_teachers().get(r['teacher_id'], {})
            t["name"] = ai_info.get("name", r['teacher_id'])
            t["specialization"] = ai_info.get("specialization", [])
        else:
            t["name"] = f"Učitel #{r['teacher_id']}"
        teachers.append(t)

    # Teacher notes from profile
    profile = get_adaptive_profile(student_id)
    notes = profile.get("teacher_notes", [])

    return jsonify({
        "success": True,
        "teachers": teachers,
        "teacher_notes": notes[-10:],  # last 10 notes
        "timestamp": now_iso()
    })
