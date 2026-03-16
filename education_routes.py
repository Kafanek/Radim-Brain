# ============================================
# 🎓 RADIM EDUCATION API BLUEPRINT
# ============================================
# Version: 3.0.0 — Refactored modular architecture
#
# Module structure:
#   education_data.py          — Course content, teachers, scenarios, news
#   education_helpers.py       — DB helpers, adaptive profiles, shared utils
#   education_routes.py        — Student-facing API routes (THIS FILE)
#   education_teacher_routes.py — Teacher dashboard routes
#
# Endpoints: /api/education/*
# Focus: Disfázie, vzácné neurodegenerativní a vývojové poruchy

from flask import Blueprint, request, jsonify, g
from datetime import datetime
import json
import logging

from database import get_connection, is_postgres

from education_data import (
    EDUCATION_COURSES, TEACHERS, COMMUNICATION_SCENARIOS,
    STATIC_NEWS, COURSE_TO_NEEDS
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

    courses = []
    for course in EDUCATION_COURSES.values():
        # Kompaktní verze (bez modulů/lekcí)
        compact = {
            "id": course["id"],
            "title": course["title"],
            "subtitle": course.get("subtitle", ""),
            "icon": course["icon"],
            "category": course["category"],
            "difficulty": course["difficulty"],
            "duration_minutes": course["duration_minutes"],
            "tags": course["tags"],
            "description": course["description"],
            "target_audience": course.get("target_audience", []),
            "module_count": len(course.get("modules", [])),
            "quiz_count": sum(1 for m in course.get("modules", []) if "quiz" in m),
            "learning_objectives": course.get("learning_objectives", [])
        }
        courses.append(compact)

    # Filtry
    if category:
        courses = [c for c in courses if c["category"].lower() == category.lower()]
    if difficulty:
        courses = [c for c in courses if c["difficulty"] == difficulty]
    if search:
        sl = search.lower()
        courses = [c for c in courses if
                   sl in c["title"].lower() or
                   sl in c["description"].lower() or
                   any(sl in t.lower() for t in c["tags"])]

    return jsonify({
        "success": True,
        "count": len(courses),
        "courses": courses,
        "categories": list(set(c["category"] for c in EDUCATION_COURSES.values())),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>', methods=['GET'])
def get_course(course_id):
    """Detail kurzu — moduly a struktura (bez plného obsahu lekcí)"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({
            "success": False,
            "error": f"Kurz '{course_id}' nenalezen",
            "available": list(EDUCATION_COURSES.keys())
        }), 404

    # Vrátit kurz s modulovou strukturou, ale bez plného HTML obsahu
    course_detail = {
        "id": course["id"],
        "title": course["title"],
        "subtitle": course.get("subtitle", ""),
        "icon": course["icon"],
        "category": course["category"],
        "difficulty": course["difficulty"],
        "duration_minutes": course["duration_minutes"],
        "tags": course["tags"],
        "description": course["description"],
        "target_audience": course.get("target_audience", []),
        "learning_objectives": course.get("learning_objectives", []),
        "modules": []
    }

    for module in course.get("modules", []):
        mod = {
            "id": module["id"],
            "title": module["title"],
            "order": module["order"],
            "duration_minutes": module.get("duration_minutes", 0),
            "icon": module.get("icon", "📄"),
            "lesson_count": len(module.get("lessons", [])),
            "has_quiz": "quiz" in module,
            "lessons": [
                {
                    "id": l["id"],
                    "title": l["title"],
                    "type": l.get("type", "article"),
                    "prerequisites": l.get("prerequisites", []),
                    "key_points": l.get("key_points", [])
                }
                for l in module.get("lessons", [])
            ]
        }
        course_detail["modules"].append(mod)

    return jsonify({
        "success": True,
        "course": course_detail,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>', methods=['GET'])
def get_module(course_id, module_id):
    """Detail modulu — plný obsah lekcí"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    return jsonify({
        "success": True,
        "course_id": course_id,
        "course_title": course["title"],
        "module": module,
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
        "course_id": course_id,
        "module_id": module_id,
        "lesson": lesson,
        "timestamp": now_iso()
    })


# ============================================
# 📝 QUIZ ROUTES
# ============================================


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz', methods=['GET'])
def get_quiz(course_id, module_id):
    """Získat kvíz pro modul"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    # Vrátit kvíz BEZ správných odpovědí (pro frontend)
    safe_quiz = {
        "id": quiz["id"],
        "title": quiz["title"],
        "question_count": len(quiz["questions"]),
        "questions": []
    }
    for q in quiz["questions"]:
        safe_q = {
            "id": q["id"],
            "question": q["question"],
            "type": q["type"]
        }
        if q["type"] == "single_choice":
            opts = q.get("options", [])
            if opts and isinstance(opts[0], dict):
                # Old format: [{"id": "a", "text": "...", "correct": True}]
                safe_q["options"] = [{"id": o["id"], "text": o["text"]} for o in opts]
            else:
                # New format: ["option1", "option2", ...] with "correct": index
                safe_q["options"] = [{"id": i, "text": o} for i, o in enumerate(opts)]
        elif q["type"] == "true_false":
            safe_q["options"] = [
                {"id": "true", "text": "Ano, je to pravda"},
                {"id": "false", "text": "Ne, není to pravda"}
            ]
        elif q["type"] == "matching":
            # Show left items, user must match with right items
            pairs = q.get("pairs", [])
            safe_q["left_items"] = [p["left"] for p in pairs]
            safe_q["right_items"] = sorted([p["right"] for p in pairs])  # shuffled order
        elif q["type"] == "ordering":
            import random as _rnd
            items = list(q.get("options", q.get("correct_order", [])))
            # Provide items in scrambled order for the user to reorder
            safe_q["items"] = items  # frontend can shuffle
        safe_quiz["questions"].append(safe_q)

    return jsonify({
        "success": True,
        "course_id": course_id,
        "module_id": module_id,
        "quiz": safe_quiz,
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz/submit', methods=['POST'])
def submit_quiz(course_id, module_id):
    """Odeslat odpovědi na kvíz a získat hodnocení"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    data = request.json or {}
    answers = data.get("answers", {})
    user_id = data.get("userId", "anonymous")

    results = []
    correct_count = 0

    for q in quiz["questions"]:
        user_answer = answers.get(q["id"])
        is_correct = False

        if q["type"] == "single_choice":
            opts = q.get("options", [])
            if opts and isinstance(opts[0], dict):
                # Old format: [{"id": "a", "text": "...", "correct": True}]
                correct_option = next((o for o in opts if o.get("correct")), None)
                is_correct = user_answer == correct_option["id"] if correct_option else False
            else:
                # New format: ["opt1", "opt2"] with "correct": index
                is_correct = user_answer == q.get("correct")
        elif q["type"] == "true_false":
            # Support both "correct_answer" (old) and "correct" (new) keys
            expected_val = q.get("correct_answer", q.get("correct"))
            if isinstance(user_answer, bool):
                is_correct = user_answer == expected_val
            else:
                expected = "true" if expected_val else "false"
                is_correct = user_answer == expected
        elif q["type"] == "matching":
            # user_answer should be dict: {"left_value": "right_value", ...}
            if isinstance(user_answer, dict):
                correct_pairs = {p["left"]: p["right"] for p in q.get("pairs", [])}
                is_correct = user_answer == correct_pairs
            else:
                is_correct = False
        elif q["type"] == "ordering":
            # user_answer should be list of items in user's order
            if isinstance(user_answer, list):
                is_correct = user_answer == q.get("correct_order", [])
            else:
                is_correct = False

        if is_correct:
            correct_count += 1

        results.append({
            "question_id": q["id"],
            "question": q["question"],
            "user_answer": user_answer,
            "is_correct": is_correct,
            "explanation": q.get("explanation", "")
        })

    total = len(quiz["questions"])
    score = round((correct_count / total) * 100) if total > 0 else 0
    passed = score >= 60

    # Uložit do DB
    db_save_progress(user_id, course_id, module_id, None, 'quiz_submit', score, {
        "correct": correct_count,
        "total": total,
        "passed": passed
    })

    # Adaptivní vyhodnocení — automaticky po každém kvízu
    adaptive_result = evaluate_and_adapt(user_id, course_id, module_id, score, EDUCATION_COURSES)

    # Notify teacher about quiz completion
    notify_teacher(user_id, 'education_student_completed', {
        'type': 'quiz',
        'course_id': course_id,
        'module_id': module_id,
        'score': score,
        'passed': passed
    })
    # Alert teacher if student is struggling (score < 50%)
    if score < 50:
        notify_teacher(user_id, 'education_student_struggling', {
            'type': 'low_quiz_score',
            'course_id': course_id,
            'module_id': module_id,
            'score': score
        })

    # Motivační zpráva
    if score == 100:
        message = "Výborně! Perfektní skóre! Máte skvělé znalosti."
    elif score >= 80:
        message = "Velmi dobře! Máte solidní porozumění tématu."
    elif score >= 60:
        message = "Dobře! Prošli jste. Pokud chcete, můžete si lekce projít znovu pro lepší pochopení."
    else:
        message = "Zatím to není ono. Doporučujeme si lekce projít znovu a zkusit to později."

    return jsonify({
        "success": True,
        "score": score,
        "correct": correct_count,
        "total": total,
        "passed": passed,
        "message": message,
        "results": results,
        "adaptive": {
            "level": adaptive_result["level"],
            "avg_score": adaptive_result["avg_score"],
            "badges": adaptive_result["badges"],
            "strengths": adaptive_result["strengths"],
            "weaknesses": adaptive_result["weaknesses"],
            "recommended_next": adaptive_result.get("recommended_courses", [])[:2]
        },
        "timestamp": now_iso()
    })


# ============================================
# 📊 PROGRESS ROUTES
# ============================================


@education_bp.route('/api/education/progress', methods=['GET', 'POST'])
def handle_progress():
    """Správa pokroku ve vzdělávání"""
    if request.method == 'POST':
        data = request.json or {}
        user_id = data.get('userId', 'anonymous')
        course_id = data.get('courseId')
        module_id = data.get('moduleId')
        lesson_id = data.get('lessonId')
        action = data.get('action', 'view')  # view, complete

        if not course_id:
            return jsonify({"success": False, "error": "courseId je vyžadováno"}), 400

        # Map 'complete' action to specific DB action
        db_action = action
        if action == 'complete' and lesson_id:
            db_action = 'complete_lesson'
        elif action == 'complete' and module_id:
            db_action = 'complete_module'

        db_save_progress(user_id, course_id, module_id, lesson_id, db_action)

        # Return current progress
        progress = db_get_progress(user_id).get(course_id, {})

        return jsonify({
            "success": True,
            "message": "Pokrok uložen",
            "progress": progress,
            "timestamp": now_iso()
        })

    # GET
    user_id = request.args.get('userId', 'anonymous')
    progress = db_get_progress(user_id)

    # Spočítat celkový pokrok
    summary = {}
    for cid, cprog in progress.items():
        course = EDUCATION_COURSES.get(cid)
        if not course:
            continue
        total_modules = len(course.get("modules", []))
        completed = len(cprog.get("completed_modules", []))
        summary[cid] = {
            "course_title": course["title"],
            "total_modules": total_modules,
            "completed_modules": completed,
            "percent": round((completed / total_modules) * 100) if total_modules > 0 else 0,
            "quiz_scores": cprog.get("quiz_scores", {}),
            "last_activity": cprog.get("last_activity")
        }

    return jsonify({
        "success": True,
        "user_id": user_id,
        "progress": summary,
        "courses_started": len(summary),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/lesson-progress', methods=['GET', 'POST'])
def lesson_progress_sync():
    """Sync frontend lesson/quiz progress with backend DB.
    POST: save lesson progress from frontend (lessons-module, quiz-module)
    GET: load all lesson progress for user
    """
    if request.method == 'POST':
        data = request.json or {}
        user_id = data.get('userId', 'anonymous')
        lesson_id = data.get('lessonId')
        category = data.get('category', '')
        score = data.get('score', 0)
        completed = 1 if data.get('completed', False) else 0
        answers = data.get('answers', [])
        time_spent = data.get('timeSpent', 0)

        if not lesson_id:
            return jsonify({"success": False, "error": "lessonId je vyžadováno"}), 400

        db = None
        try:
            db = get_connection()
            if is_postgres():
                db.execute(
                    '''INSERT INTO education_lesson_progress (user_id, lesson_id, category, score, completed, answers, time_spent, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                       ON CONFLICT (user_id, lesson_id) DO UPDATE SET
                           score = GREATEST(education_lesson_progress.score, EXCLUDED.score),
                           completed = GREATEST(education_lesson_progress.completed, EXCLUDED.completed),
                           answers = EXCLUDED.answers,
                           time_spent = education_lesson_progress.time_spent + EXCLUDED.time_spent,
                           updated_at = CURRENT_TIMESTAMP''',
                    (user_id, lesson_id, category, score, completed, json.dumps(answers), time_spent)
                )
            else:
                db.execute(
                    '''INSERT OR REPLACE INTO education_lesson_progress (user_id, lesson_id, category, score, completed, answers, time_spent, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                    (user_id, lesson_id, category, score, completed, json.dumps(answers), time_spent)
                )
            db.commit()
        except Exception as e:
            logger.error(f"lesson progress save error: {e}")
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

        # Notify teacher when lesson completed
        if completed:
            notify_teacher(user_id, 'education_student_completed', {
                'type': 'lesson',
                'lesson_id': lesson_id,
                'category': category,
                'score': score
            })

        return jsonify({"success": True, "message": "Lesson progress saved", "timestamp": now_iso()})

    # GET
    user_id = request.args.get('userId', 'anonymous')
    db = None
    try:
        db = get_connection()
        if is_postgres():
            rows = db.execute(
                'SELECT lesson_id, category, score, completed, answers, time_spent, updated_at FROM education_lesson_progress WHERE user_id = %s',
                (user_id,)
            ).fetchall()
        else:
            rows = db.execute(
                'SELECT lesson_id, category, score, completed, answers, time_spent, updated_at FROM education_lesson_progress WHERE user_id = ?',
                (user_id,)
            ).fetchall()

        progress = {}
        for row in rows:
            try:
                answers = json.loads(row['answers']) if isinstance(row['answers'], str) else (row['answers'] or [])
            except Exception:
                answers = []
            progress[row['lesson_id']] = {
                "category": row['category'],
                "score": row['score'],
                "completed": bool(row['completed']),
                "answers": answers,
                "timeSpent": row['time_spent'],
                "updatedAt": str(row['updated_at'])
            }
    except Exception as e:
        logger.error(f"lesson progress load error: {e}")
        progress = {}
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    return jsonify({"success": True, "user_id": user_id, "progress": progress, "timestamp": now_iso()})


# ============================================
# 🔍 SEARCH & STATS
# ============================================


@education_bp.route('/api/education/search', methods=['GET'])
def search_education():
    """Vyhledávání napříč kurzy a lekcemi"""
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return jsonify({"success": False, "error": "Parametr 'query' je vyžadován"}), 400

    ql = query.lower()
    results = []

    for course in EDUCATION_COURSES.values():
        # Hledat v kurzu
        course_score = 0
        if ql in course["title"].lower():
            course_score += 10
        if ql in course["description"].lower():
            course_score += 5
        for tag in course["tags"]:
            if ql in tag.lower():
                course_score += 3

        if course_score > 0:
            results.append({
                "type": "course",
                "id": course["id"],
                "title": course["title"],
                "description": course["description"],
                "icon": course["icon"],
                "relevance": course_score
            })

        # Hledat v modulech a lekcích
        for module in course.get("modules", []):
            for lesson in module.get("lessons", []):
                lesson_score = 0
                if ql in lesson["title"].lower():
                    lesson_score += 8
                content = lesson.get("content", "")
                if ql in content.lower():
                    lesson_score += 4
                for kp in lesson.get("key_points", []):
                    if ql in kp.lower():
                        lesson_score += 2

                if lesson_score > 0:
                    results.append({
                        "type": "lesson",
                        "id": lesson["id"],
                        "title": lesson["title"],
                        "course_id": course["id"],
                        "course_title": course["title"],
                        "module_id": module["id"],
                        "module_title": module["title"],
                        "icon": module.get("icon", "📄"),
                        "relevance": lesson_score
                    })

    results.sort(key=lambda x: x["relevance"], reverse=True)

    return jsonify({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results[:20],
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/stats', methods=['GET'])
def education_stats():
    """Statistiky vzdělávacího modulu"""
    total_courses = len(EDUCATION_COURSES)
    total_modules = sum(len(c.get("modules", [])) for c in EDUCATION_COURSES.values())
    total_lessons = sum(
        len(m.get("lessons", []))
        for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
    )
    total_quizzes = sum(
        1 for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
        if "quiz" in m
    )
    total_questions = sum(
        len(m.get("quiz", {}).get("questions", []))
        for c in EDUCATION_COURSES.values()
        for m in c.get("modules", [])
        if "quiz" in m
    )

    categories = {}
    for c in EDUCATION_COURSES.values():
        cat = c["category"]
        categories[cat] = categories.get(cat, 0) + 1

    return jsonify({
        "success": True,
        "stats": {
            "total_courses": total_courses,
            "total_modules": total_modules,
            "total_lessons": total_lessons,
            "total_quizzes": total_quizzes,
            "total_questions": total_questions,
            "categories": categories,
            "active_learners": db_count_active_learners(),
            "available_courses": [
                {"id": c["id"], "title": c["title"], "icon": c["icon"]}
                for c in EDUCATION_COURSES.values()
            ]
        },
        "timestamp": now_iso()
    })


# ============================================
# 🔗 COMMUNICATION NEEDS
# ============================================


@education_bp.route('/api/education/communication-needs', methods=['GET'])
def get_communication_needs():
    """Propojení se systémem komunikačních potřeb z memory_routes"""
    need_type = request.args.get('type', None)

    if need_type:
        # Najdi kurzy relevantní pro danou komunikační potřebu
        relevant_courses = []
        for course_id, needs in COURSE_TO_NEEDS.items():
            if need_type in needs:
                course = EDUCATION_COURSES.get(course_id)
                if course:
                    relevant_courses.append({
                        "id": course["id"],
                        "title": course["title"],
                        "icon": course["icon"],
                        "description": course["description"],
                        "communication_need": need_type
                    })

        return jsonify({
            "success": True,
            "communication_need": need_type,
            "relevant_courses": relevant_courses,
            "timestamp": now_iso()
        })

    # Vrátit celou mapu
    return jsonify({
        "success": True,
        "mapping": COURSE_TO_NEEDS,
        "description": "Mapování vzdělávacích kurzů na komunikační potřeby (z memory_routes)",
        "timestamp": now_iso()
    })


# ============================================
# 🎓 ADAPTIVE EVALUATION
# ============================================


@education_bp.route('/api/education/evaluate', methods=['POST'])
def evaluate_user():
    """Celkové adaptivní vyhodnocení uživatele"""
    data = request.json or {}
    user_id = data.get('userId', 'anonymous')

    profile = get_adaptive_profile(user_id)

    # Napojení na memory_routes komunikační profil
    communication_info = None
    try:
        from memory_routes import get_user_context
        ctx = get_user_context(user_id)
        if ctx:
            communication_info = {
                "communication_needs": ctx.get("communication_needs"),
                "preferred_length": ctx.get("preferred_length", "medium"),
                "interaction_count": ctx.get("interaction_count", 0),
                "last_mood": ctx.get("last_mood", "neutral")
            }
            profile["communication_adaptation"] = communication_info
    except Exception:
        pass

    # Hodnocení
    evaluation = {
        "level": profile["level"],
        "level_label": {
            "beginner": "Začátečník",
            "intermediate": "Pokročilý",
            "advanced": "Expert"
        }.get(profile["level"], "Začátečník"),
        "total_quizzes": profile["total_quizzes"],
        "avg_score": profile["avg_score"],
        "strengths": profile["strengths"],
        "weaknesses": profile["weaknesses"],
        "badges": profile["badges"],
        "badge_labels": {
            "perfektni_score": {"name": "Perfektní skóre", "icon": "⭐", "desc": "100 % v kvízu"},
            "pilny_student": {"name": "Pilný student", "icon": "📚", "desc": "5+ kvízů"},
            "mistr_vzdelavani": {"name": "Mistr vzdělávání", "icon": "🎓", "desc": "10+ kvízů"},
            "znalec": {"name": "Znalec", "icon": "🧠", "desc": "Expert ve 2+ oblastech"}
        },
        "recommended_next": profile["recommended_courses"][:3],
        "communication_adaptation": communication_info,
        "teacher_notes": profile.get("teacher_notes", []),
        "message": get_evaluation_message(profile)
    }

    # Alert teacher if student is struggling
    if profile["total_quizzes"] > 0 and profile["avg_score"] < 50:
        notify_teacher(user_id, 'education_student_struggling', {
            'type': 'low_avg_score',
            'avg_score': profile["avg_score"],
            'total_quizzes': profile["total_quizzes"],
            'weaknesses': profile["weaknesses"]
        })

    return jsonify({
        "success": True,
        "user_id": user_id,
        "evaluation": evaluation,
        "timestamp": now_iso()
    })


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

    # Specializovaný obsah podle typu učitele
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
    data = request.json or {}
    # Use auth user_id if available, fallback to body
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
    data = request.json or {}
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

    # Spočítat detailní přehled
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

    # Generovat automatické doporučení
    auto_recommendations = []
    if profile["avg_score"] < 60 and profile["total_quizzes"] > 0:
        auto_recommendations.append("Student potřebuje zopakovat základy. Doporučit modul 1 znovu.")
    if profile["total_quizzes"] == 0:
        auto_recommendations.append("Student ještě nezačal žádný kvíz. Motivovat k prvnímu pokusu.")
    for weakness in profile.get("weaknesses", []):
        auto_recommendations.append(f"Slabší oblast: {weakness} — zopakovat příslušné lekce.")
    if profile["avg_score"] >= 85:
        auto_recommendations.append("Výborný student. Doporučit pokročilejší materiály.")

    # Doporučení na základě přiřazeného učitele
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
# 📰 NEWS
# ============================================


@education_bp.route('/api/education/news', methods=['GET'])
def education_news():
    """Zdravotní a vzdělávací zprávy relevantní ke kurzům"""
    category = request.args.get('category', 'health')

    articles = STATIC_NEWS.get(category, STATIC_NEWS["health"])

    # Pokud je relevance filtr
    relevance = request.args.get('relevance')
    if relevance:
        articles = [a for a in articles if relevance in (a.get("relevance") or "")]

    return jsonify({
        "success": True,
        "category": category,
        "count": len(articles),
        "articles": articles,
        "categories_available": list(STATIC_NEWS.keys()),
        "timestamp": now_iso()
    })


# ============================================
# 🎭 INTERACTIVE COMMUNICATION SCENARIOS
# ============================================


@education_bp.route('/api/education/scenarios', methods=['GET'])
def list_scenarios():
    """Seznam interaktivních komunikačních scénářů"""
    course = request.args.get('course')

    if course and course in COMMUNICATION_SCENARIOS:
        scenarios = COMMUNICATION_SCENARIOS[course]
    else:
        scenarios = []
        for c, sc_list in COMMUNICATION_SCENARIOS.items():
            for sc in sc_list:
                sc_copy = dict(sc)
                sc_copy["course"] = c
                scenarios.append(sc_copy)

    # Compact view — bez options/feedback (to se zobrazí až v detailu)
    compact = []
    for sc in scenarios:
        compact.append({
            "id": sc["id"],
            "title": sc["title"],
            "context": sc["context"],
            "difficulty": sc["difficulty"],
            "character": sc["character"],
            "course": sc.get("course", course or "")
        })

    return jsonify({
        "success": True,
        "count": len(compact),
        "scenarios": compact,
        "available_courses": list(COMMUNICATION_SCENARIOS.keys()),
        "timestamp": now_iso()
    })


@education_bp.route('/api/education/scenarios/<scenario_id>', methods=['GET'])
def get_scenario(scenario_id):
    """Detail scénáře — plná situace s možnostmi"""
    for course_id, sc_list in COMMUNICATION_SCENARIOS.items():
        for sc in sc_list:
            if sc["id"] == scenario_id:
                return jsonify({
                    "success": True,
                    "scenario": sc,
                    "course": course_id,
                    "timestamp": now_iso()
                })

    return jsonify({"success": False, "error": "Scénář nenalezen"}), 404


@education_bp.route('/api/education/scenarios/<scenario_id>/answer', methods=['POST'])
def answer_scenario(scenario_id):
    """Odpověď na scénář — vyhodnocení volby"""
    data = request.json or {}
    answer_id = data.get('answer')
    user_id = data.get('userId', 'anonymous')

    if not answer_id:
        return jsonify({"success": False, "error": "answer je vyžadováno"}), 400

    # Najdi scénář
    scenario = None
    course_id = None
    for cid, sc_list in COMMUNICATION_SCENARIOS.items():
        for sc in sc_list:
            if sc["id"] == scenario_id:
                scenario = sc
                course_id = cid
                break
        if scenario:
            break

    if not scenario:
        return jsonify({"success": False, "error": "Scénář nenalezen"}), 404

    # Najdi zvolenou možnost
    chosen = next((o for o in scenario["options"] if o["id"] == answer_id), None)
    if not chosen:
        return jsonify({"success": False, "error": "Neplatná odpověď"}), 400

    # Všechny možnosti s hodnocením
    all_options = []
    for opt in scenario["options"]:
        all_options.append({
            "id": opt["id"],
            "text": opt["text"],
            "score": opt["score"],
            "feedback": opt["feedback"],
            "consequence": opt["consequence"],
            "is_chosen": opt["id"] == answer_id
        })

    # Uložit do progress (DB)
    db_save_progress(user_id, 'scenarios', scenario_id, None, 'scenario', chosen["score"], {
        "scenario_id": scenario_id,
        "answer": answer_id
    })

    # Notify teacher about scenario completion
    notify_teacher(user_id, 'education_student_completed', {
        'type': 'scenario',
        'scenario_id': scenario_id,
        'score': chosen["score"],
        'is_best': chosen["score"] == 100
    })

    return jsonify({
        "success": True,
        "scenario_id": scenario_id,
        "your_answer": answer_id,
        "score": chosen["score"],
        "feedback": chosen["feedback"],
        "consequence": chosen["consequence"],
        "learning_point": scenario["learning_point"],
        "all_options": all_options,
        "is_best_answer": chosen["score"] == 100,
        "timestamp": now_iso()
    })


# ============================================
# 📋 EXTRA ROUTES — modules, lessons, certificates, quiz results
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


# ============================================
# 🎓 CERTIFICATE ENDPOINT
# ============================================


@education_bp.route('/api/education/certificate/<user_id>/<course_id>', methods=['GET'])
def get_certificate(user_id, course_id):
    """Certifikát o dokončení kurzu — ověří, že student prošel všechny moduly"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    modules = course.get("modules", [])
    progress = db_get_progress(user_id)
    course_progress = progress.get(course_id, {})
    quiz_scores = course_progress.get("quiz_scores", {})
    completed_modules = course_progress.get("completed_modules", [])
    completed_lessons = course_progress.get("completed_lessons", [])

    # Check each module
    module_results = []
    all_passed = True
    total_score = 0
    quizzes_taken = 0
    missing_modules = []

    for m in modules:
        mid = m["id"]
        quiz = m.get("quiz")
        has_quiz = quiz is not None

        # Score for this module — quiz_scores stores dicts or numbers
        mod_score_raw = quiz_scores.get(mid)
        if isinstance(mod_score_raw, dict):
            mod_score = mod_score_raw.get("score")
        elif isinstance(mod_score_raw, (int, float)):
            mod_score = mod_score_raw
        else:
            mod_score = None

        if has_quiz:
            if mod_score is not None and isinstance(mod_score, (int, float)):
                passed = mod_score >= 60
                total_score += mod_score
                quizzes_taken += 1
            else:
                passed = False
                missing_modules.append({"module_id": mid, "title": m["title"], "reason": "Kvíz nebyl dokončen"})
        else:
            # Module without quiz — check if lessons completed
            passed = mid in completed_modules

        if not passed:
            all_passed = False
            if has_quiz and mod_score is not None and mod_score < 60:
                missing_modules.append({"module_id": mid, "title": m["title"], "reason": f"Skóre {mod_score}% (minimum 60%)"})

        module_results.append({
            "module_id": mid,
            "title": m["title"],
            "quiz_score": mod_score,
            "passed": passed
        })

    avg_score = round(total_score / quizzes_taken, 1) if quizzes_taken > 0 else 0
    profile = get_adaptive_profile(user_id)

    # Count total lessons
    total_lessons = sum(len(m.get("lessons", [])) for m in modules)

    if all_passed:
        cert_date = now_iso()[:10].replace('-', '')
        certificate_id = f"CERT-{course_id.upper()[:3]}-{str(user_id)[:8]}-{cert_date}"

        return jsonify({
            "success": True,
            "eligible": True,
            "certificate": {
                "certificate_id": certificate_id,
                "user_id": user_id,
                "course_id": course_id,
                "course_title": course["title"],
                "completed_at": now_iso(),
                "all_modules_completed": True,
                "avg_quiz_score": avg_score,
                "total_lessons": total_lessons,
                "total_quizzes": quizzes_taken,
                "level": profile["level"],
                "badges_earned": profile.get("badges", []),
                "modules": module_results
            },
            "timestamp": now_iso()
        })
    else:
        return jsonify({
            "success": True,
            "eligible": False,
            "message": "Kurz ještě není dokončen",
            "missing": missing_modules,
            "progress": {
                "modules_passed": sum(1 for r in module_results if r["passed"]),
                "modules_total": len(modules),
                "avg_quiz_score": avg_score,
                "quizzes_taken": quizzes_taken,
                "modules": module_results
            },
            "timestamp": now_iso()
        })


# ============================================
# 📊 QUIZ RESULT + ADAPTIVE RECOMMENDATIONS
# ============================================


@education_bp.route('/api/education/quiz-result/<user_id>/<course_id>/<module_id>', methods=['GET'])
def get_quiz_result(user_id, course_id, module_id):
    """Detailní výsledek kvízu s adaptivními doporučeními"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    progress = db_get_progress(user_id)
    course_progress = progress.get(course_id, {})
    quiz_scores = course_progress.get("quiz_scores", {})
    score_data = quiz_scores.get(module_id)
    # quiz_scores stores dicts: {"score": 83, "correct": 5, "total": 6, "passed": True}
    if isinstance(score_data, dict):
        score = score_data.get("score")
    elif isinstance(score_data, (int, float)):
        score = score_data
    else:
        score = None

    profile = get_adaptive_profile(user_id)

    # Find module position
    module_ids = [m["id"] for m in course.get("modules", [])]
    current_idx = module_ids.index(module_id) if module_id in module_ids else 0

    # Adaptive recommendations
    recommendations = []
    next_module = None

    if score is None:
        recommendations.append({
            "type": "start",
            "message": "Ještě jste neabsolvovali tento kvíz. Projděte si nejdřív lekce a pak zkuste kvíz.",
            "action": "study_lessons",
            "target": module_id
        })
    elif score < 60:
        # Failed — recommend reviewing lessons
        recommendations.append({
            "type": "review",
            "message": f"Skóre {score}% — doporučujeme si projít lekce znovu a zkusit kvíz později.",
            "action": "review_lessons",
            "target": module_id
        })
        # Highlight weak areas from quiz questions
        weak_topics = module.get("lessons", [])
        for lesson in weak_topics:
            recommendations.append({
                "type": "lesson",
                "message": f"Zopakujte: {lesson['title']}",
                "action": "study_lesson",
                "target": lesson["id"]
            })
    elif score < 90:
        # Passed but room for improvement
        recommendations.append({
            "type": "good",
            "message": f"Dobré skóre {score}%! Můžete pokračovat dál nebo si zkusit zlepšit výsledek.",
            "action": "continue"
        })
        if current_idx + 1 < len(module_ids):
            next_mid = module_ids[current_idx + 1]
            next_mod = next((m for m in course["modules"] if m["id"] == next_mid), None)
            if next_mod:
                next_module = {"module_id": next_mid, "title": next_mod["title"]}
                recommendations.append({
                    "type": "next",
                    "message": f"Pokračujte na: {next_mod['title']}",
                    "action": "next_module",
                    "target": next_mid
                })
    else:
        # Excellent!
        recommendations.append({
            "type": "excellent",
            "message": f"Výborné skóre {score}%! Skvělé zvládnutí tématu.",
            "action": "continue"
        })
        if current_idx + 1 < len(module_ids):
            next_mid = module_ids[current_idx + 1]
            next_mod = next((m for m in course["modules"] if m["id"] == next_mid), None)
            if next_mod:
                next_module = {"module_id": next_mid, "title": next_mod["title"]}
                recommendations.append({
                    "type": "next",
                    "message": f"Pokračujte na pokročilejší téma: {next_mod['title']}",
                    "action": "next_module",
                    "target": next_mid
                })
        # Suggest other courses
        for other_cid, other_course in EDUCATION_COURSES.items():
            if other_cid != course_id:
                other_progress = progress.get(other_cid, {})
                if not other_progress.get("completed_modules"):
                    recommendations.append({
                        "type": "explore",
                        "message": f"Vyzkoušejte další kurz: {other_course['title']}",
                        "action": "new_course",
                        "target": other_cid
                    })
                    break

    return jsonify({
        "success": True,
        "user_id": user_id,
        "course_id": course_id,
        "module_id": module_id,
        "module_title": module["title"],
        "quiz_title": quiz["title"],
        "score": score,
        "passed": score is not None and score >= 60,
        "total_questions": len(quiz["questions"]),
        "question_types": list(set(q["type"] for q in quiz["questions"])),
        "next_module": next_module,
        "recommendations": recommendations,
        "profile": {
            "level": profile["level"],
            "avg_score": profile["avg_score"],
            "badges": profile.get("badges", [])
        },
        "timestamp": now_iso()
    })
