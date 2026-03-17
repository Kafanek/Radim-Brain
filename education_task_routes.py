# ============================================
# 📋 EDUCATION TASK ROUTES v1.0.0
# ============================================
# Task CRUD: teacher creates/grades/updates/deletes tasks,
# student views/submits tasks, student views assigned teacher.
# Extracted from education_teacher_routes.py for modularity.
# ============================================

import json
import logging
from flask import Blueprint, request, jsonify, g
from database import get_connection, is_postgres
from auth_middleware import require_auth, require_teacher
from education_helpers import (
    now_iso, get_teacher_id, verify_teacher_student, get_adaptive_profile
)

logger = logging.getLogger(__name__)

education_task_bp = Blueprint('education_task', __name__)


# Lazy import to avoid circular dependency
def _get_teachers():
    from education_data import TEACHERS
    return TEACHERS


# ============================================
# TEACHER TASK ENDPOINTS
# ============================================

@education_task_bp.route('/api/education/teacher-dashboard/student/<student_id>/task', methods=['POST'])
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


@education_task_bp.route('/api/education/teacher-dashboard/student/<student_id>/tasks', methods=['GET'])
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


@education_task_bp.route('/api/education/teacher-dashboard/task/<int:task_id>/grade', methods=['PUT'])
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


@education_task_bp.route('/api/education/teacher-dashboard/task/<int:task_id>', methods=['PUT'])
@require_auth
@require_teacher
def teacher_update_task(task_id):
    """Učitel upraví úkol (title, description, due_date, task_type) — ne grading"""
    teacher_id = get_teacher_id()
    data = request.json or {}

    db = None
    try:
        db = get_connection()
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
        updates.append("updated_at = CURRENT_TIMESTAMP")
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


@education_task_bp.route('/api/education/teacher-dashboard/task/<int:task_id>', methods=['DELETE'])
@require_auth
@require_teacher
def teacher_delete_task(task_id):
    """Učitel smaže úkol (soft-delete -> status='deleted')"""
    teacher_id = get_teacher_id()

    db = None
    try:
        db = get_connection()
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


# ============================================
# STUDENT TASK ENDPOINTS
# ============================================

@education_task_bp.route('/api/education/my-tasks', methods=['GET'])
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


@education_task_bp.route('/api/education/my-tasks/<int:task_id>/submit', methods=['POST'])
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


@education_task_bp.route('/api/education/my-teacher', methods=['GET'])
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
