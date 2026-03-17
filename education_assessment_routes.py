# ============================================
# 🎓📝 EDUCATION ASSESSMENT ROUTES
# ============================================
# Extracted from education_routes.py for modularity.
#
# Routes:
#   POST /api/education/courses/<cid>/modules/<mid>/quiz     — Get quiz
#   POST /api/education/courses/<cid>/modules/<mid>/quiz/submit — Submit quiz
#   POST /api/education/evaluate                              — Adaptive evaluation
#   GET  /api/education/certificate/<uid>/<cid>               — Certificate check
#   GET  /api/education/quiz-result/<uid>/<cid>/<mid>         — Quiz result + recommendations
#
# Version: 1.0.0

from flask import Blueprint, request, jsonify
import logging

from education_data import EDUCATION_COURSES
from education_helpers import (
    now_iso, db_save_progress, db_get_progress,
    get_adaptive_profile, save_adaptive_profile, evaluate_and_adapt,
    get_evaluation_message, db_get_teacher_assignment, notify_teacher
)

logger = logging.getLogger(__name__)

education_assessment_bp = Blueprint('education_assessment', __name__)


# ============================================
# 🎯 QUIZ ROUTES
# ============================================


@education_assessment_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz', methods=['POST'])
def get_quiz(course_id, module_id):
    """Získat kvíz modulu"""
    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    # Sanitize — neposílat správné odpovědi
    sanitized_questions = []
    for q in quiz["questions"]:
        sq = {
            "id": q["id"],
            "question": q["question"],
            "type": q["type"],
            "icon": q.get("icon", "❓"),
        }
        if q["type"] == "single_choice":
            sq["options"] = q["options"]
        elif q["type"] == "true_false":
            sq["options"] = [
                {"id": "true", "text": "Pravda"},
                {"id": "false", "text": "Nepravda"}
            ]
        elif q["type"] == "matching":
            sq["left"] = q["left"]
            sq["right"] = q["right"]
        elif q["type"] == "ordering":
            import random
            items = list(q["items"])
            random.shuffle(items)
            sq["items"] = items
        sanitized_questions.append(sq)

    return jsonify({
        "success": True,
        "quiz": {
            "title": quiz["title"],
            "description": quiz.get("description", ""),
            "passing_score": quiz.get("passing_score", 60),
            "questions": sanitized_questions
        },
        "course_id": course_id,
        "module_id": module_id,
        "timestamp": now_iso()
    })


@education_assessment_bp.route('/api/education/courses/<course_id>/modules/<module_id>/quiz/submit', methods=['POST'])
def submit_quiz(course_id, module_id):
    """Odeslat odpovědi na kvíz — vyhodnocení"""
    data = request.json or {}
    answers = data.get('answers', {})
    user_id = data.get('userId', 'anonymous')

    course = EDUCATION_COURSES.get(course_id)
    if not course:
        return jsonify({"success": False, "error": f"Kurz '{course_id}' nenalezen"}), 404

    module = next((m for m in course.get("modules", []) if m["id"] == module_id), None)
    if not module:
        return jsonify({"success": False, "error": f"Modul '{module_id}' nenalezen"}), 404

    quiz = module.get("quiz")
    if not quiz:
        return jsonify({"success": False, "error": "Tento modul nemá kvíz"}), 404

    # Evaluate
    total = len(quiz["questions"])
    correct_count = 0
    results = []

    for q in quiz["questions"]:
        qid = q["id"]
        user_answer = answers.get(qid)
        is_correct = False

        if q["type"] == "single_choice":
            correct = q["correct"]
            is_correct = user_answer == correct

        elif q["type"] == "true_false":
            correct = str(q["correct"]).lower()
            is_correct = str(user_answer).lower() == correct

        elif q["type"] == "matching":
            correct = q["correct_pairs"]
            if isinstance(user_answer, dict):
                is_correct = user_answer == correct

        elif q["type"] == "ordering":
            correct = q["correct_order"]
            if isinstance(user_answer, list):
                is_correct = user_answer == correct

        if is_correct:
            correct_count += 1

        results.append({
            "question_id": qid,
            "question": q["question"],
            "your_answer": user_answer,
            "is_correct": is_correct,
            "explanation": q.get("explanation", ""),
            "type": q["type"]
        })

    score = round((correct_count / total) * 100) if total > 0 else 0
    passed = score >= quiz.get("passing_score", 60)

    # Save to DB
    db_save_progress(user_id, course_id, module_id, None, 'quiz', score, {
        "correct": correct_count, "total": total, "passed": passed
    })

    # Adaptive learning update
    profile_update = evaluate_and_adapt(user_id, course_id, module_id, score, correct_count, total)

    # Motivational message
    if score >= 90:
        message = "🌟 Výborně! Skvělé zvládnutí tématu!"
    elif score >= 70:
        message = "👍 Dobrá práce! Pokračujte dál."
    elif score >= 50:
        message = "📚 Docela dobře! Zkuste si projít lekce znovu pro lepší výsledek."
    else:
        message = "💪 Nevzdávejte to! Projděte si lekce a zkuste kvíz znovu."

    # Notify teacher
    notify_teacher(user_id, 'education_student_completed', {
        'type': 'quiz',
        'course_id': course_id,
        'module_id': module_id,
        'score': score,
        'passed': passed,
        'correct': correct_count,
        'total': total
    })

    return jsonify({
        "success": True,
        "score": score,
        "correct": correct_count,
        "total": total,
        "passed": passed,
        "message": message,
        "results": results,
        "profile_update": profile_update,
        "course_id": course_id,
        "module_id": module_id,
        "timestamp": now_iso()
    })


# ============================================
# 🎓 ADAPTIVE EVALUATION
# ============================================


@education_assessment_bp.route('/api/education/evaluate', methods=['POST'])
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
# 🎓 CERTIFICATE ENDPOINT
# ============================================


@education_assessment_bp.route('/api/education/certificate/<user_id>/<course_id>', methods=['GET'])
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

    module_results = []
    all_passed = True
    total_score = 0
    quizzes_taken = 0
    missing_modules = []

    for m in modules:
        mid = m["id"]
        quiz = m.get("quiz")
        has_quiz = quiz is not None

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


@education_assessment_bp.route('/api/education/quiz-result/<user_id>/<course_id>/<module_id>', methods=['GET'])
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
    if isinstance(score_data, dict):
        score = score_data.get("score")
    elif isinstance(score_data, (int, float)):
        score = score_data
    else:
        score = None

    profile = get_adaptive_profile(user_id)

    module_ids = [m["id"] for m in course.get("modules", [])]
    current_idx = module_ids.index(module_id) if module_id in module_ids else 0

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
        recommendations.append({
            "type": "review",
            "message": f"Skóre {score}% — doporučujeme si projít lekce znovu a zkusit kvíz později.",
            "action": "review_lessons",
            "target": module_id
        })
        for lesson in module.get("lessons", []):
            recommendations.append({
                "type": "lesson",
                "message": f"Zopakujte: {lesson['title']}",
                "action": "study_lesson",
                "target": lesson["id"]
            })
    elif score < 90:
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


logger.info("✅ Education Assessment Blueprint loaded — quiz/evaluate/certificate/quiz-result")
