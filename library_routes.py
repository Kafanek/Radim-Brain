# ============================================
# RADIM LIBRARY API BLUEPRINT v1.1.0
# ============================================
# E-book knihovna pro seniory
# Endpoints: /kal/library/*
# Data + helpers in library_data.py.
# ============================================

from flask import Blueprint, request, jsonify
from datetime import datetime
import random
import logging
from utils import now_iso

logger = logging.getLogger(__name__)

library_bp = Blueprint('library', __name__)

# ============================================================================
# IMPORTS FROM DATA MODULE (+ re-exports for backward compat)
# ============================================================================

from library_data import (
    DEMO_BOOKS,
    USER_PROGRESS,
    evict_old_progress,
    get_book_compact,
)

# Backward compat aliases
_evict_old_progress = evict_old_progress


# ============================================
# ENDPOINTS
# ============================================

@library_bp.route('/kal/library/books', methods=['GET'])
def list_books():
    """Seznam vsech knih s volitelnym filtrovanim"""
    category = request.args.get('category', None)
    difficulty = request.args.get('difficulty', None)
    search = request.args.get('query', request.args.get('search', None))

    books = list(DEMO_BOOKS.values())

    if category:
        books = [b for b in books if b["category"].lower() == category.lower()]
    if difficulty:
        books = [b for b in books if b["difficulty"] == difficulty]
    if search:
        search_lower = search.lower()
        books = [b for b in books if
                 search_lower in b["title"].lower() or
                 search_lower in b["author"].lower() or
                 search_lower in b["description"].lower() or
                 any(search_lower in tag.lower() for tag in b["tags"])]

    compact_books = [get_book_compact(b) for b in books]

    return jsonify({
        "success": True,
        "count": len(compact_books),
        "books": compact_books,
        "categories": list(set(b["category"] for b in DEMO_BOOKS.values())),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/search', methods=['GET'])
def search_books():
    """Vyhledavani knih"""
    query = request.args.get('query', request.args.get('q', ''))
    if not query:
        return jsonify({"success": False, "error": "Parametr 'query' je vyzadovan"}), 400

    query_lower = query.lower()
    results = []
    for book in DEMO_BOOKS.values():
        score = 0
        if query_lower in book["title"].lower():
            score += 10
        if query_lower in book["author"].lower():
            score += 8
        if query_lower in book["description"].lower():
            score += 5
        for tag in book["tags"]:
            if query_lower in tag.lower():
                score += 3
        if query_lower == book["category"].lower():
            score += 6

        if score > 0:
            result = get_book_compact(book)
            result["relevance_score"] = score
            results.append(result)

    results.sort(key=lambda x: x["relevance_score"], reverse=True)

    return jsonify({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results,
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/categories', methods=['GET'])
def list_categories():
    """Seznam kategorii s poctem knih"""
    categories = {}
    for book in DEMO_BOOKS.values():
        cat = book["category"]
        if cat not in categories:
            categories[cat] = {"name": cat, "count": 0, "books": []}
        categories[cat]["count"] += 1
        categories[cat]["books"].append({"id": book["id"], "title": book["title"]})

    return jsonify({
        "success": True,
        "categories": list(categories.values()),
        "total_books": len(DEMO_BOOKS),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/books/<book_id>', methods=['GET'])
def get_book(book_id):
    """Detail knihy vcetne seznamu kapitol (bez plneho textu)"""
    book = DEMO_BOOKS.get(book_id)
    if not book:
        return jsonify({
            "success": False,
            "error": f"Kniha {book_id} nenalezena",
            "available_ids": list(DEMO_BOOKS.keys())
        }), 404

    book_detail = get_book_compact(book)
    book_detail["chapters"] = [
        {"id": ch["id"], "title": ch["title"], "paragraph_count": len(ch["paragraphs"])}
        for ch in book.get("chapters", [])
    ]

    return jsonify({
        "success": True,
        "book": book_detail,
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/read/<book_id>', methods=['GET'])
def read_book(book_id):
    """Cteni knihy -- vrati plny text kapitol"""
    book = DEMO_BOOKS.get(book_id)
    if not book:
        return jsonify({"success": False, "error": f"Kniha {book_id} nenalezena"}), 404

    chapter_id = request.args.get('chapter', None, type=int)

    if chapter_id is not None:
        chapter = next((ch for ch in book["chapters"] if ch["id"] == chapter_id), None)
        if not chapter:
            return jsonify({"success": False, "error": f"Kapitola {chapter_id} nenalezena"}), 404
        return jsonify({
            "success": True,
            "book_id": book_id,
            "book_title": book["title"],
            "chapter": chapter,
            "timestamp": now_iso()
        })

    return jsonify({
        "success": True,
        "book_id": book_id,
        "book_title": book["title"],
        "author": book["author"],
        "chapters": book["chapters"],
        "total_chapters": len(book["chapters"]),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/progress', methods=['GET', 'POST'])
def handle_progress():
    """Sprava pokroku cteni"""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        user_id = data.get('userId', 'anonymous')
        book_id = data.get('bookId')
        chapter_id = data.get('chapterId')
        paragraph = data.get('paragraph', 0)
        percent = data.get('percent', 0)

        if not book_id:
            return jsonify({"success": False, "error": "bookId je vyzadovano"}), 400

        if user_id not in USER_PROGRESS:
            evict_old_progress()
            USER_PROGRESS[user_id] = {}

        USER_PROGRESS[user_id][book_id] = {
            "book_id": book_id,
            "chapter_id": chapter_id,
            "paragraph": paragraph,
            "percent": percent,
            "updated_at": now_iso()
        }

        return jsonify({
            "success": True,
            "message": "Pokrok ulozen",
            "progress": USER_PROGRESS[user_id][book_id],
            "timestamp": now_iso()
        })

    # GET
    user_id = request.args.get('userId', 'anonymous')
    progress = USER_PROGRESS.get(user_id, {})
    return jsonify({
        "success": True,
        "user_id": user_id,
        "progress": progress,
        "books_started": len(progress),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/recommend/<user_id>', methods=['GET'])
def recommend_books(user_id):
    """Doporuceni knih na zaklade historie"""
    read_books = set(USER_PROGRESS.get(user_id, {}).keys())

    recommendations = []
    for book_id, book in DEMO_BOOKS.items():
        if book_id not in read_books:
            rec = get_book_compact(book)
            reasons = []
            if book["rating"] >= 4.8:
                reasons.append("Vysoce hodnocena")
            if book["difficulty"] == "easy":
                reasons.append("Snadne cteni")
            if book["reads"] > 1000:
                reasons.append("Oblibena u ctenaru")
            if "kafanek" in " ".join(book["tags"]).lower():
                reasons.append("Od pana Kafanka")
            rec["recommendation_reasons"] = reasons if reasons else ["Novy titul pro vas"]
            recommendations.append(rec)

    recommendations.sort(key=lambda x: x.get("rating", 0), reverse=True)

    return jsonify({
        "success": True,
        "user_id": user_id,
        "recommendations": recommendations[:5],
        "total_available": len(recommendations),
        "timestamp": now_iso()
    })


@library_bp.route('/kal/library/stats', methods=['GET'])
def library_stats():
    """Statistiky knihovny"""
    categories = {}
    total_chapters = 0
    total_reads = 0

    for book in DEMO_BOOKS.values():
        cat = book["category"]
        categories[cat] = categories.get(cat, 0) + 1
        total_chapters += len(book.get("chapters", []))
        total_reads += book.get("reads", 0)

    return jsonify({
        "success": True,
        "stats": {
            "total_books": len(DEMO_BOOKS),
            "total_chapters": total_chapters,
            "total_reads": total_reads,
            "categories": categories,
            "avg_rating": round(sum(b.get("rating", 0) for b in DEMO_BOOKS.values()) / len(DEMO_BOOKS), 1),
            "active_readers": len(USER_PROGRESS),
            "most_popular": max(DEMO_BOOKS.values(), key=lambda b: b.get("reads", 0))["title"]
        },
        "timestamp": now_iso()
    })


# ============================================================================
# STARTUP
# ============================================================================
logger.info("Library Routes v1.1.0 loaded — /kal/library/*")
logger.info("   Data module: library_data.py")
