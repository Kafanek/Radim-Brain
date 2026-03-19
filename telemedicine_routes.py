# ============================================
# TELEMEDICINE ROUTES v3.0.0 — Student + Shared + Health
# ============================================
# v3.0: db_context(), ? placeholders throughout.
# ============================================

import logging
import os
from datetime import date
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)
from database import db_context, db_insert
from auth_middleware import require_auth
from utils import now_iso
from telemedicine_helpers import (
    _get_user_id,
    _get_consultation, _get_assigned_teacher,
    _notify_user, _is_participant,
    _validate_date, _validate_time,
    MAX_TEXT,
    # Re-export for backward compatibility (app.py imports from here)
    get_upcoming_consultations_for_reminder,
)
from telemedicine_audit import (
    log_event, check_join_eligibility, generate_join_token,
)

telemedicine_bp = Blueprint('telemedicine', __name__)


# ============================================
# STUDENT ENDPOINTS — My Consultations
# ============================================

@telemedicine_bp.route('/api/telemedicine/my/upcoming', methods=['GET'])
@require_auth
def telemed_my_upcoming():
    """Student's upcoming consultations"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    today = date.today().isoformat()

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, teacher_id, scheduled_date, scheduled_time, duration_minutes, status, consultation_type, room_code, jitsi_url "
                "FROM telemedicine_consultations WHERE student_id = ? AND scheduled_date >= ? AND status IN ('requested', 'confirmed', 'in_progress') "
                "ORDER BY scheduled_date, scheduled_time",
                (student_id, today)
            ).fetchall()

            upcoming = []
            for r in rows:
                d = dict(r)
                for k in ('scheduled_date', 'scheduled_time'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                upcoming.append(d)
    except Exception as e:
        logger.error(f"telemed_my_upcoming DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "upcoming": upcoming, "total": len(upcoming), "timestamp": now_iso()})


@telemedicine_bp.route('/api/telemedicine/my/history', methods=['GET'])
@require_auth
def telemed_my_history():
    """Student's past consultations"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, teacher_id, scheduled_date, scheduled_time, status, consultation_type, complaint, findings, recommendations, created_at "
                "FROM telemedicine_consultations WHERE student_id = ? AND status IN ('completed', 'archived') "
                "ORDER BY scheduled_date DESC LIMIT 50",
                (student_id,)
            ).fetchall()

            history = []
            for r in rows:
                d = dict(r)
                for k in ('scheduled_date', 'scheduled_time', 'created_at'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                history.append(d)
    except Exception as e:
        logger.error(f"telemed_my_history DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "history": history, "total": len(history), "timestamp": now_iso()})


@telemedicine_bp.route('/api/telemedicine/my/request', methods=['POST'])
@require_auth
def telemed_my_request():
    """Student requests a consultation"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    data = request.json or {}
    teacher_id = data.get('teacher_id')
    preferred_date = data.get('preferred_date', '').strip()
    preferred_time = data.get('preferred_time', '').strip()
    complaint = data.get('complaint', '').strip()[:MAX_TEXT]
    consultation_type = data.get('consultation_type', 'video')

    if not preferred_date or not preferred_time:
        return jsonify({"success": False, "error": "preferred_date a preferred_time jsou povinne"}), 400
    if not _validate_date(preferred_date):
        return jsonify({"success": False, "error": "Datum musi byt ve formatu YYYY-MM-DD"}), 400
    if not _validate_time(preferred_time):
        return jsonify({"success": False, "error": "Cas musi byt ve formatu HH:MM"}), 400
    if consultation_type not in ('video', 'audio'):
        consultation_type = 'video'

    if not teacher_id:
        teacher_id = _get_assigned_teacher(student_id)
    if not teacher_id:
        return jsonify({"success": False, "error": "Nemate prirazeneho terapeuta"}), 400

    try:
        with db_context(commit=True) as db:
            cid = db_insert(db, 'telemedicine_consultations',
                ['teacher_id', 'student_id', 'scheduled_date', 'scheduled_time', 'complaint', 'consultation_type'],
                (teacher_id, student_id, preferred_date, preferred_time, complaint, consultation_type)
            )
    except Exception as e:
        logger.error(f"telemed_my_request DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    log_event(cid, 'consultation_requested', student_id,
              new_status='requested', actor_consultation_role='patient',
              metadata={'teacher_id': teacher_id, 'type': consultation_type})

    _notify_user(teacher_id, 'telemedicine_new_request', {
        'consultation_id': cid, 'student_id': student_id,
        'scheduled_date': preferred_date, 'scheduled_time': preferred_time
    })

    return jsonify({
        "success": True, "message": "Zadost o konzultaci odeslana",
        "consultation_id": cid, "status": "requested", "timestamp": now_iso()
    }), 201


@telemedicine_bp.route('/api/telemedicine/my/consultation/<int:consultation_id>', methods=['GET'])
@require_auth
def telemed_my_consultation_detail(consultation_id):
    """Student views consultation detail + notes"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    consultation = _get_consultation(consultation_id)
    if not consultation or consultation.get('student_id') != student_id:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404

    return jsonify({"success": True, "consultation": consultation, "timestamp": now_iso()})


@telemedicine_bp.route('/api/telemedicine/my/teacher/availability', methods=['GET'])
@require_auth
def telemed_my_teacher_availability():
    """View assigned teacher's available slots"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    teacher_id = _get_assigned_teacher(student_id)
    if not teacher_id:
        return jsonify({"success": False, "error": "Nemate prirazeneho terapeuta"}), 400

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, day_of_week, specific_date, start_time, end_time, slot_duration_minutes "
                "FROM telemedicine_availability WHERE teacher_id = ? AND is_active = 1 ORDER BY day_of_week, start_time",
                (teacher_id,)
            ).fetchall()

            slots = []
            for r in rows:
                d = dict(r)
                for k in ('specific_date', 'start_time', 'end_time'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                slots.append(d)
    except Exception as e:
        logger.error(f"telemed_my_teacher_availability DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "teacher_id": teacher_id, "slots": slots, "total": len(slots), "timestamp": now_iso()})


@telemedicine_bp.route('/api/telemedicine/my/consultation/<int:consultation_id>/cancel', methods=['PUT'])
@require_auth
def telemed_my_cancel(consultation_id):
    """Student cancels own consultation"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    data = request.json or {}
    reason = data.get('reason', '').strip()[:MAX_TEXT]

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, teacher_id, status FROM telemedicine_consultations WHERE id = ? AND student_id = ?",
                (consultation_id, student_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] not in ('requested', 'confirmed'):
                return jsonify({"success": False, "error": f"Nelze zrusit konzultaci ve stavu '{row['status']}'"}), 400

            db.execute(
                "UPDATE telemedicine_consultations SET status = 'cancelled', cancel_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (reason, consultation_id)
            )
            teacher_id = row['teacher_id']
            old_status = row['status']
    except Exception as e:
        logger.error(f"telemed_my_cancel DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    log_event(consultation_id, 'consultation_cancelled', student_id,
              old_status=old_status, new_status='cancelled', reason=reason,
              actor_consultation_role='patient')

    _notify_user(teacher_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'student', 'reason': reason
    })

    return jsonify({"success": True, "message": "Konzultace zrusena", "timestamp": now_iso()})


# ============================================
# SHARED — Join consultation
# ============================================

@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/join', methods=['GET'])
@require_auth
def telemed_join(consultation_id):
    """Get Jitsi join URL with full eligibility check + short-lived token (v4.1 hardened)"""
    user_id = _get_user_id()

    # Full eligibility check (Point 4): participant? status? time window? revoked?
    eligible, reason = check_join_eligibility(consultation_id, user_id)
    if not eligible:
        log_event(consultation_id, 'join_url_accessed', user_id,
                  metadata={'allowed': False, 'reason': reason})
        return jsonify({"success": False, "error": reason}), 403

    consultation = _get_consultation(consultation_id)
    if not consultation:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404

    room_code = consultation.get('room_code')
    if not room_code:
        return jsonify({"success": False, "error": "Jitsi room neni k dispozici"}), 404

    # Generate short-lived join token instead of permanent URL
    join_token = generate_join_token(consultation_id, user_id)

    frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
    join_page = f"{frontend_url}/call.html?room={room_code}&type={consultation.get('consultation_type', 'video')}"
    if join_token:
        join_page += f"&token={join_token}"

    log_event(consultation_id, 'join_url_accessed', user_id,
              metadata={'allowed': True, 'has_token': bool(join_token)})

    return jsonify({
        "success": True, "room_code": room_code,
        "join_page": join_page, "join_token": join_token,
        "token_ttl_minutes": 30,
        "consultation_id": consultation_id, "timestamp": now_iso()
    })


# ============================================
# HEALTH CHECK
# ============================================

@telemedicine_bp.route('/api/telemedicine/health', methods=['GET'])
def telemedicine_health():
    """Health check for telemedicine service."""
    return jsonify({
        'status': 'healthy', 'service': 'Telemedicine v3.0.0',
        'modules': ['student (this)', 'teacher (telemedicine_teacher_routes)', 'multiparty (telemedicine_multiparty_routes)'],
        'features': ['consultations', 'scheduling', 'summaries']
    })
