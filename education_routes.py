# ============================================
# 🎓 RADIM EDUCATION API BLUEPRINT
# ============================================
# Version: 3.1.0 — Modular architecture
#
# Module structure:
#   education_data.py               — Course content, teachers, scenarios, news
#   education_helpers.py            — DB helpers, adaptive profiles, shared utils
#   education_routes.py             — Core routes: courses, progress, teachers (THIS FILE)
#   education_assessment_routes.py  — Quiz, evaluation, certificate, quiz results
#   education_scenario_routes.py    — Search, stats, news, scenarios
#   education_teacher_routes.py     — Teacher dashboard routes
#
# Endpoints: /api/education/*
# Focus: Disfázie, vzácné neurodegenerativní a vývojové poruchy

from flask import Blueprint, request, jsonify, g
from datetime import datetime
import json
import logging

from database import is_postgres, db_context

from education_data import (
    EDUCATION_COURSES, TEACHERS, COURSE_TO_NEEDS
)
from education_helpers import (
    now_iso, db_save_progress, db_get_progress, db_count_active_learners,
    get_adaptive_profile, save_adaptive_profile, evaluate_and_adapt,
    get_evaluation_message, db_get_teacher_assignment, db_assign_teacher,
    notify_teacher
)
from auth_middleware import require_auth, require_teacher, optional_auth

logger = logging.getLogger(__name__)

education_bp = Blueprint('education', __name__)


# ============================================
# 📚 COURSE ROUTES
# ============================================


@education_bp.route('/api/education/courses', methods=['GET'])
def list_courses():
    """Seznam všech vzdělávacích kurzů"""
    category = request.args.get('category', None)
    difficulty = request.args.get('difficulty', None)
    search = request.args.get('query', request.args.get('search', None))

    courses = list(EDUCATION_COURSES.values())

    if category:
        courses = [c for c in courses if c["category"] == category]

    if difficulty:
        courses = [c for c in courses if c.get("difficulty") == difficulty]

    if search:
        sl = search.lower()
        courses = [c for c in courses if
                   sl in c["title"].lower() or
                   sl in c["description"].lower() or
                   any(sl in tag.lower() for tag in c.get("tags", []))]

    # Compact view
    result = []
    for c in courses:
        result.append({
            "id": c["id"],
            "title": c["title"],
            "description": c["description"],
            "category": c["category"],
            "icon": c["icon"],
            "difficulty": c.get("difficulty", "beginner"),
            "duration_hours": c.get("duration_hours", 0),
            "tags": c["tags"],
            "modules_count": len(c.get("modules", [])),
            "lessons_count": sum(len(m.get("lessons", [])) for m in c.get("modules", [])),
            "has_quizzes": any("quiz" in m for m in c.get("modules", []))
        })

    return jsonify({
        "success": True,
        "courses": result,
        "total": len(result),
        "filters": {"category": category, "difficulty": difficulty, "search": search},
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>', methods=['GET'])
def get_course(course_id):
    """Detail kurzu s modulovou strukturou"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    # Module overview (bez plného obsahu lekcí)
    modules = []
    for m in course.get("modules", []):
        quiz = m.get("quiz")
        modules.append({
            "id": m["id"],
            "title": m["title"],
            "order": m.get("order", 0),
            "duration_minutes": m.get("duration_minutes", 0),
            "icon": m.get("icon", "📚"),
            "lessons": [{
                "id": l["id"],
                "title": l["title"],
                "type": l.get("type", "article"),
                "key_points": l.get("key_points", [])
            } for l in m.get("lessons", [])],
            "has_quiz": quiz is not None,
            "quiz_title": quiz["title"] if quiz else None,
            "quiz_questions_count": len(quiz["questions"]) if quiz else 0
        })

    return jsonify({
        "success": True,
        "course": {
            "id": course["id"],
            "title": course["title"],
            "description": course["description"],
            "category": course["category"],
            "icon": course["icon"],
            "difficulty": course.get("difficulty", "beginner"),
            "duration_hours": course.get("duration_hours", 0),
            "tags": course["tags"],
            "modules": modules,
            "communication_needs": COURSE_TO_NEEDS.get(course_id, [])
        },
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>', methods=['GET'])
def get_module(course_id, module_id):
    """Detail modulu s plným obsahem lekcí"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    return jsonify({
        "success": True,
        "module": module,
        "course_id": course_id,
        "course_title": course["title"],
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/lessons/<lesson_id>', methods=['GET'])
def get_lesson(course_id, module_id, lesson_id):
    """Detail jedné lekce — plný obsah"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    lesson = next((l for l in module.get("lessons", []) if l["id"] == lesson_id), None)
    if not lesson:
        return jsonify({"success": False, "error": f"Lekce '{lesson_id}' nenalezena"}), 404

    return jsonify({
        "success": True,
        "lesson": lesson,
        "course_id": course_id,
        "module_id": module_id,
        "timestamp": now_iso()
    })


# ============================================
# 📊 PROGRESS TRACKING
# ============================================


@education_bp.route('/api/education/progress', methods=['POST', 'GET'])
def handle_progress():
    """Uložit nebo získat progress uživatele"""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        user_id = data.get('userId', 'anonymous')
        course_id = data.get('courseId')
        module_id = data.get('moduleId')
        lesson_id = data.get('lessonId')
        progress_type = data.get('type', 'lesson')
        score = data.get('score')
        details = data.get('details')

        if not course_id:
            return jsonify({"success": False, "error": "courseId je vyžadováno"}), 400

        db_save_progress(user_id, course_id, module_id, lesson_id, progress_type, score, details)

        # If lesson completed, notify teacher
        if progress_type == 'lesson' and lesson_id:
            notify_teacher(user_id, 'education_student_completed', {
                'type': 'lesson',
                'course_id': course_id,
                'module_id': module_id,
                'lesson_id': lesson_id
            })

        return jsonify({
            "success": True,
            "message": "Progress uložen",
            "user_id": user_id,
            "timestamp": now_iso()
        })
    else:
        user_id = request.args.get('userId', 'anonymous')
        progress = db_get_progress(user_id)
        return jsonify({
            "success": True,
            "user_id": user_id,
            "progress": progress,
            "timestamp": now_iso()
        })


@education_bp.route('/api/education/lesson-progress', methods=['POST'])
def lesson_progress_sync():
    """Sync lesson-level progress from frontend (localStorage) with backend"""
    data = request.get_json(silent=True) or {}
    user_id = data.get('userId', 'anonymous')
    lessons = data.get('lessons', [])

    if not lessons:
        return jsonify({"success": True, "synced": 0, "timestamp": now_iso()})

    synced = 0
    try:
        with db_context(commit=True) as db:
            for entry in lessons:
                course_id = entry.get('courseId')
                module_id = entry.get('moduleId')
                lesson_id = entry.get('lessonId')
                completed_at = entry.get('completedAt', now_iso())

                if not (course_id and module_id and lesson_id):
                    continue

                # Upsert — PG uses ON CONFLICT, SQLite uses INSERT OR REPLACE
                if is_postgres():
                    db.execute(
                        "INSERT INTO education_lesson_progress (user_id, course_id, module_id, lesson_id, completed_at) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT (user_id, course_id, module_id, lesson_id) DO UPDATE SET completed_at = EXCLUDED.completed_at",
                        (user_id, course_id, module_id, lesson_id, completed_at))
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO education_lesson_progress (user_id, course_id, module_id, lesson_id, completed_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (user_id, course_id, module_id, lesson_id, completed_at))
                synced += 1

            # Notify teacher about batch completion
            if synced > 0:
                notify_teacher(user_id, 'education_student_completed', {
                    'type': 'lesson_batch',
                    'synced_count': synced,
                    'course_id': lessons[0].get('courseId', ''),
                })

    except Exception as e:
        logger.error(f"Lesson progress sync error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": True, "user_id": user_id, "synced": synced, "timestamp": now_iso()})


# ============================================
# 👩‍🏫 TEACHER / TUTOR ROUTES
# ============================================


@education_bp.route('/api/education/teachers', methods=['GET'])
def list_teachers():
    """Seznam dostupných učitelů/tutorů"""
    specialization = request.args.get('specialization')
    teachers = list(TEACHERS.values())
    if specialization:
        teachers = [t for t in teachers if specialization.lower() in
                    ' '.join(t.get('specialization', [])).lower()]
    return jsonify({
        "success": True,
        "teachers": teachers,
        "total": len(teachers),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/teacher/<teacher_id>', methods=['GET'])
def get_teacher_detail(teacher_id):
    """Detail učitele včetně specializovaného průvodce"""
    teacher = TEACHERS.get(teacher_id)
    if not teacher:
        return jsonify({"success": False, "error": "Učitel nenalezen"}), 404

    result = {
        "success": True,
        "teacher": teacher,
        "timestamp": now_iso()
    }

    if teacher_id == "dysphasia-child-tutor":
        result["guide"] = teacher.get("teaching_approach", {})
        result["guide_type"] = "dysphasia_child"
        result["related_courses"] = ["dysphasia"]
        result["related_communication_needs"] = ["dysphasia_child"]
    elif teacher_id == "dementia-tutor":
        result["guide"] = teacher.get("dementia_guide", {})
        result["guide_type"] = "dementia"
        result["related_courses"] = ["dementia"]
        result["related_communication_needs"] = [
            "alzheimer", "alzheimer_early", "alzheimer_middle", "alzheimer_late",
            "lewy_body", "vascular", "frontotemporal", "parkinson_dementia"
        ]
    elif teacher_id == "parkinson-tutor":
        result["guide"] = teacher.get("parkinson_guide", {})
        result["guide_type"] = "parkinson"
        result["related_courses"] = ["parkinson"]
        result["related_communication_needs"] = [
            "parkinson", "parkinson_dementia", "parkinson_motor", "parkinson_communication"
        ]

    return jsonify(result)


@education_bp.route('/api/education/teacher/assign', methods=['POST'])
@optional_auth
def assign_teacher():
    """Přiřadit AI učitele k uživateli"""
    data = request.get_json(silent=True) or {}
    auth_user = getattr(g, 'auth_user', None)
    user_id = str(auth_user.get('id', '')) if auth_user else data.get('userId', 'anonymous')
    if not user_id:
        user_id = data.get('userId', 'anonymous')
    teacher_id = data.get('teacherId', 'radim-tutor')

    if teacher_id not in TEACHERS:
        return jsonify({"success": False, "error": "Učitel nenalezen"}), 404

    db_assign_teacher(user_id, teacher_id, 'ai')
    teacher = TEACHERS[teacher_id]

    return jsonify({
        "success": True,
        "message": f"Učitel {teacher['name']} byl přiřazen",
        "teacher": teacher,
        "user_id": user_id,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/teacher/note', methods=['POST'])
def add_teacher_note():
    """Učitel přidá poznámku k profilu studenta"""
    data = request.get_json(silent=True) or {}
    user_id = data.get('userId')
    note_text = data.get('note', '')
    teacher_id = data.get('teacherId', 'radim-tutor')

    if not user_id or not note_text:
        return jsonify({"success": False, "error": "userId a note jsou vyžadovány"}), 400

    profile = get_adaptive_profile(user_id)
    note = {
        "teacher_id": teacher_id,
        "teacher_name": TEACHERS.get(teacher_id, {}).get("name", "Neznámý"),
        "text": note_text,
        "timestamp": now_iso()
    }
    profile.setdefault("teacher_notes", []).append(note)
    save_adaptive_profile(user_id, profile)

    return jsonify({
        "success": True,
        "message": "Poznámka uložena",
        "note": note,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/teacher/review/<user_id>', methods=['GET'])
def teacher_review(user_id):
    """Učitelský přehled studenta — profil, výsledky, doporučení"""
    profile = get_adaptive_profile(user_id)
    progress = db_get_progress(user_id)

    course_details = []
    for cid, cprog in progress.items():
        course = EDUCATION_COURSES.get(cid)
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
            "started_at": cprog.get("started_at"),
            "last_activity": cprog.get("last_activity")
        })

    auto_recommendations = []
    if profile["avg_score"] < 60 and profile["total_quizzes"] > 0:
        auto_recommendations.append("Student potřebuje zopakovat základy. Doporučit modul 1 znovu.")
    if profile["total_quizzes"] == 0:
        auto_recommendations.append("Student ještě nezačal žádný kvíz. Motivovat k prvnímu pokusu.")
    for weakness in profile.get("weaknesses", []):
        auto_recommendations.append(f"Slabší oblast: {weakness} — zopakovat příslušné lekce.")
    if profile["avg_score"] >= 85:
        auto_recommendations.append("Výborný student. Doporučit pokročilejší materiály.")

    assigned_tid = db_get_teacher_assignment(user_id)
    if assigned_tid == "dysphasia-child-tutor":
        auto_recommendations.append("Specialistka: Zkontrolovat IVP dítěte a spolupráci s SPC.")
        auto_recommendations.append("Tip: Využít cvičení 'Pojmenuj obrázek' a 'Rýmy a říkanky'.")
        if profile["avg_score"] < 50:
            auto_recommendations.append("Doporučení: Zjednodušit materiály — vizuální podpora, piktogramy.")
    elif assigned_tid == "dementia-tutor":
        auto_recommendations.append("Specialista: Ověřit, zda pečovatel zná správný typ demence pacienta.")
        auto_recommendations.append("Tip: Procvičit komunikační pravidla pro příslušné stádium.")
        if "Demence" in profile.get("weaknesses", []):
            auto_recommendations.append("Priorita: Zopakovat rozdíly mezi typy demence a komunikační strategie.")
    elif assigned_tid == "parkinson-tutor":
        auto_recommendations.append("Specialista: Ověřit znalost motorických i nemotorických příznaků.")
        auto_recommendations.append("Tip: Procvičit reakci na hypomimii a hypofonii v komunikačních scénářích.")
        if "Parkinson" in profile.get("weaknesses", []):
            auto_recommendations.append("Priorita: Zopakovat rozdíl mezi příznaky nemoci a 'lhostejností'.")

    return jsonify({
        "success": True,
        "student": {
            "user_id": user_id,
            "level": profile["level"],
            "avg_score": profile["avg_score"],
            "total_quizzes": profile["total_quizzes"],
            "strengths": profile["strengths"],
            "weaknesses": profile["weaknesses"],
            "badges": profile["badges"]
        },
        "courses": course_details,
        "teacher_notes": profile.get("teacher_notes", []),
        "auto_recommendations": auto_recommendations,
        "assigned_teacher": TEACHERS.get(db_get_teacher_assignment(user_id)),
        "timestamp": now_iso()
    })


# ============================================
# 📋 MODULE & LESSON LISTING (compact)
# ============================================


@education_bp.route('/api/education/courses/<course_id>/modules', methods=['GET'])
def list_course_modules(course_id):
    """Seznam modulů kurzu (bez obsahu lekcí — compact)"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    modules = []
    for m in course.get("modules", []):
        quiz = m.get("quiz")
        modules.append({
            "id": m["id"],
            "title": m["title"],
            "order": m.get("order", 0),
            "duration_minutes": m.get("duration_minutes", 0),
            "icon": m.get("icon", "📚"),
            "lessons_count": len(m.get("lessons", [])),
            "has_quiz": quiz is not None,
            "quiz_questions_count": len(quiz.get("questions", [])) if quiz else 0
        })

    return jsonify({
        "success": True,
        "course_id": course_id,
        "course_title": course["title"],
        "modules": modules,
        "total_modules": len(modules),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/lessons', methods=['GET'])
def list_module_lessons(course_id, module_id):
    """Seznam lekcí modulu (bez plného HTML obsahu — compact)"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    lessons = []
    for l in module.get("lessons", []):
        lessons.append({
            "id": l["id"],
            "title": l["title"],
            "type": l.get("type", "article"),
            "key_points": l.get("key_points", []),
            "has_content": bool(l.get("content"))
        })

    return jsonify({
        "success": True,
        "course_id": course_id,
        "module_id": module_id,
        "module_title": module["title"],
        "lessons": lessons,
        "total_lessons": len(lessons),
        "timestamp": now_iso()
    })


logger.info("✅ Education Blueprint loaded — courses/progress/teachers/modules/lessons")
