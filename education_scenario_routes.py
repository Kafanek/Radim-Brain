# ============================================
# 🎭🔍📰 EDUCATION SCENARIO & CONTENT ROUTES
# ============================================
# Extracted from education_routes.py for modularity.
#
# Routes:
#   GET  /api/education/search                              — Full-text search
#   GET  /api/education/stats                               — System stats
#   GET  /api/education/communication-needs                 — Needs mapping
#   GET  /api/education/news                                — Health/education news
#   GET  /api/education/scenarios                           — Scenario list
#   GET  /api/education/scenarios/<id>                      — Scenario detail
#   POST /api/education/scenarios/<id>/answer               — Scenario answer
#
# Version: 1.0.0

from flask import Blueprint, request, jsonify
import logging

from education_data import (
    EDUCATION_COURSES, COMMUNICATION_SCENARIOS,
    STATIC_NEWS, COURSE_TO_NEEDS
)
from education_helpers import (
    now_iso, db_save_progress, db_count_active_learners, notify_teacher
)

logger = logging.getLogger(__name__)

education_scenario_bp = Blueprint('education_scenario', __name__)


# ============================================
# 🔍 SEARCH & STATS
# ============================================


@education_scenario_bp.route('/api/education/search', methods=['GET'])
def search_education():
    """Vyhledávání napříč kurzy a lekcemi"""
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return jsonify({"success": False, "error": "Parametr 'query' je vyžadován"}), 400

    ql = query.lower()
    results = []

    for course in EDUCATION_COURSES.values():
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


@education_scenario_bp.route('/api/education/stats', methods=['GET'])
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


@education_scenario_bp.route('/api/education/communication-needs', methods=['GET'])
def get_communication_needs():
    """Propojení se systémem komunikačních potřeb z memory_routes"""
    need_type = request.args.get('type', None)

    if need_type:
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

    return jsonify({
        "success": True,
        "mapping": COURSE_TO_NEEDS,
        "description": "Mapování vzdělávacích kurzů na komunikační potřeby (z memory_routes)",
        "timestamp": now_iso()
    })


# ============================================
# 📰 NEWS
# ============================================


@education_scenario_bp.route('/api/education/news', methods=['GET'])
def education_news():
    """Zdravotní a vzdělávací zprávy relevantní ke kurzům"""
    category = request.args.get('category', 'health')

    articles = STATIC_NEWS.get(category, STATIC_NEWS["health"])

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


@education_scenario_bp.route('/api/education/scenarios', methods=['GET'])
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


@education_scenario_bp.route('/api/education/scenarios/<scenario_id>', methods=['GET'])
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


@education_scenario_bp.route('/api/education/scenarios/<scenario_id>/answer', methods=['POST'])
def answer_scenario(scenario_id):
    """Odpověď na scénář — vyhodnocení volby"""
    data = request.json or {}
    answer_id = data.get('answer')
    user_id = data.get('userId', 'anonymous')

    if not answer_id:
        return jsonify({"success": False, "error": "answer je vyžadováno"}), 400

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

    chosen = next((o for o in scenario["options"] if o["id"] == answer_id), None)
    if not chosen:
        return jsonify({"success": False, "error": "Neplatná odpověď"}), 400

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

    db_save_progress(user_id, 'scenarios', scenario_id, None, 'scenario', chosen["score"], {
        "scenario_id": scenario_id,
        "answer": answer_id
    })

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


logger.info("✅ Education Scenario Blueprint loaded — search/stats/news/scenarios")
