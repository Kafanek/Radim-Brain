# ============================================
# TELEMEDICINE ROUTES v2.2.0 — Student + Shared + Health
# ============================================
# Teacher routes moved to telemedicine_teacher_routes.py
# Multi-party routes in telemedicine_multiparty_routes.py
# Helpers in telemedicine_helpers.py
# ============================================

import os
from datetime import date
from flask import Blueprint, request, jsonify
from database import get_connection, is_postgres
from auth_middleware import require_auth
from utils import now_iso
from telemedicine_helpers import (
    _p, _get_user_id,
    _get_consultation, _get_assigned_teacher,
    _notify_user, _is_participant,
    _validate_date, _validate_time,
    MAX_TEXT,
    # Re-export for backward compatibility (app.py imports from here)
    get_upcoming_consultations_for_reminder,
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

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, teacher_id, scheduled_date, scheduled_time, duration_minutes, status, consultation_type, room_code, jitsi_url "
            f"FROM telemedicine_consultations WHERE student_id = {p} AND scheduled_date >= {p} AND status IN ('requested', 'confirmed', 'in_progress') "
            f"ORDER BY scheduled_date, scheduled_time",
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    return jsonify({"success": True, "upcoming": upcoming, "total": len(upcoming), "timestamp": now_iso()})


@telemedicine_bp.route('/api/telemedicine/my/history', methods=['GET'])
@require_auth
def telemed_my_history():
    """Student's past consultations"""
    student_id = _get_user_id()
    if not student_id:
        return jsonify({"success": False, "error": "Neplatny uzivatel"}), 401

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, teacher_id, scheduled_date, scheduled_time, status, consultation_type, complaint, findings, recommendations, created_at "
            f"FROM telemedicine_consultations WHERE student_id = {p} AND status IN ('completed', 'archived') "
            f"ORDER BY scheduled_date DESC LIMIT 50",
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

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

    # If no teacher_id, use assigned teacher
    if not teacher_id:
        teacher_id = _get_assigned_teacher(student_id)
    if not teacher_id:
        return jsonify({"success": False, "error": "Nemate prirazeneho terapeuta"}), 400

    db = None
    try:
        db = get_connection()
        p = _p()
        if is_postgres():
            row = db.execute(
                f"INSERT INTO telemedicine_consultations (teacher_id, student_id, scheduled_date, scheduled_time, complaint, consultation_type) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
                (teacher_id, student_id, preferred_date, preferred_time, complaint, consultation_type)
            ).fetchone()
            cid = row['id'] if row else None
        else:
            cursor = db.execute(
                f"INSERT INTO telemedicine_consultations (teacher_id, student_id, scheduled_date, scheduled_time, complaint, consultation_type) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
                (teacher_id, student_id, preferred_date, preferred_time, complaint, consultation_type)
            )
            cid = cursor.lastrowid
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

    _notify_user(teacher_id, 'telemedicine_new_request', {
        'consultation_id': cid, 'student_id': student_id,
        'scheduled_date': preferred_date, 'scheduled_time': preferred_time
    })

    return jsonify({
        "success": True,
        "message": "Zadost o konzultaci odeslana",
        "consultation_id": cid,
        "status": "requested",
        "timestamp": now_iso()
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

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, day_of_week, specific_date, start_time, end_time, slot_duration_minutes "
            f"FROM telemedicine_availability WHERE teacher_id = {p} AND is_active = 1 ORDER BY day_of_week, start_time",
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

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

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, teacher_id, status FROM telemedicine_consultations WHERE id = {p} AND student_id = {p}",
            (consultation_id, student_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
        if row['status'] not in ('requested', 'confirmed'):
            return jsonify({"success": False, "error": f"Nelze zrusit konzultaci ve stavu '{row['status']}'"}), 400

        db.execute(
            f"UPDATE telemedicine_consultations SET status = 'cancelled', cancel_reason = {p}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (reason, consultation_id)
        )
        db.commit()
        teacher_id = row['teacher_id']
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

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
    """Get Jitsi join URL (teacher or student)"""
    user_id = _get_user_id()
    consultation = _get_consultation(consultation_id)

    if not consultation:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404

    # Check authorization (supports multi-party participants)
    if not _is_participant(user_id, consultation):
        return jsonify({"success": False, "error": "Nemate opravneni"}), 403

    if consultation.get('status') != 'in_progress':
        return jsonify({"success": False, "error": "Konzultace jeste nebyla zahajena"}), 400

    room_code = consultation.get('room_code')
    jitsi_url = consultation.get('jitsi_url')

    if not room_code:
        return jsonify({"success": False, "error": "Jitsi room neni k dispozici"}), 404

    frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
    join_page = f"{frontend_url}/call.html?room={room_code}&type={consultation.get('consultation_type', 'video')}"

    return jsonify({
        "success": True,
        "jitsi_url": jitsi_url,
        "room_code": room_code,
        "join_page": join_page,
        "consultation_id": consultation_id,
        "timestamp": now_iso()
    })


# ============================================
# HEALTH CHECK
# ============================================

@telemedicine_bp.route('/api/telemedicine/health', methods=['GET'])
def telemedicine_health():
    """Health check for telemedicine service."""
    return jsonify({
        'status': 'healthy',
        'service': 'Telemedicine v2.2.0',
        'modules': ['student (this)', 'teacher (telemedicine_teacher_routes)', 'multiparty (telemedicine_multiparty_routes)'],
        'features': ['consultations', 'scheduling', 'summaries']
    })
