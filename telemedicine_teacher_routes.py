# ============================================
# TELEMEDICINE TEACHER ROUTES v2.0.0
# Teacher-facing endpoints: dashboard, availability, consultations
# v2.0: db_context() eliminates boilerplate, ? placeholders throughout.
# ============================================

import json
import logging
import os
import smtplib
from datetime import date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)
from database import get_connection, db_context, db_insert
from auth_middleware import require_auth, require_teacher
from utils import now_iso
from telemedicine_helpers import (
    _get_teacher_id_local,
    _get_consultation, _generate_room_code,
    _notify_user, _notify_all_participants,
    _validate_date, _validate_time,
    _verify_teacher_student_local,
    MAX_TEXT,
)

telemedicine_teacher_bp = Blueprint('telemedicine_teacher', __name__)


# ============================================
# TEACHER ENDPOINTS — Telemedicine Dashboard
# ============================================

@telemedicine_teacher_bp.route('/api/telemedicine/dashboard', methods=['GET'])
@require_auth
@require_teacher
def telemed_dashboard():
    """Teacher telemedicine overview"""
    teacher_id = _get_teacher_id_local()
    today = date.today().isoformat()

    try:
        with db_context() as db:
            today_rows = db.execute(
                "SELECT id, student_id, scheduled_time, status, consultation_type FROM telemedicine_consultations "
                "WHERE teacher_id = ? AND scheduled_date = ? AND status != 'cancelled' ORDER BY scheduled_time",
                (teacher_id, today)
            ).fetchall()

            pending = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE teacher_id = ? AND status = 'requested'",
                (teacher_id,)
            ).fetchone()

            month_start = date.today().replace(day=1).isoformat()
            total = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE teacher_id = ? AND scheduled_date >= ? AND status = 'completed'",
                (teacher_id, month_start)
            ).fetchone()
    except Exception as e:
        logger.error(f"telemed_dashboard DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    today_list = []
    for r in today_rows:
        d = dict(r)
        if d.get('scheduled_time') and hasattr(d['scheduled_time'], 'isoformat'):
            d['scheduled_time'] = d['scheduled_time'].isoformat()
        today_list.append(d)

    return jsonify({
        "success": True, "teacher_id": teacher_id,
        "today": today_list, "today_count": len(today_list),
        "pending_requests": pending['cnt'] if pending else 0,
        "completed_this_month": total['cnt'] if total else 0,
        "date": today, "timestamp": now_iso()
    })


# --- Availability ---

@telemedicine_teacher_bp.route('/api/telemedicine/availability', methods=['POST'])
@require_auth
@require_teacher
def telemed_set_availability():
    """Set teacher availability slot"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}

    day_of_week = data.get('day_of_week')
    specific_date = data.get('specific_date')
    start_time = data.get('start_time', '').strip()
    end_time = data.get('end_time', '').strip()
    slot_duration = data.get('slot_duration_minutes', 30)

    if not start_time or not end_time:
        return jsonify({"success": False, "error": "start_time a end_time jsou povinne (HH:MM)"}), 400
    if not _validate_time(start_time) or not _validate_time(end_time):
        return jsonify({"success": False, "error": "Cas musi byt ve formatu HH:MM"}), 400
    if specific_date and not _validate_date(specific_date):
        return jsonify({"success": False, "error": "Datum musi byt ve formatu YYYY-MM-DD"}), 400
    if day_of_week is not None and (not isinstance(day_of_week, int) or day_of_week < 0 or day_of_week > 6):
        return jsonify({"success": False, "error": "day_of_week musi byt 0-6 (Po-Ne)"}), 400

    try:
        with db_context(commit=True) as db:
            slot_id = db_insert(db, 'telemedicine_availability',
                ['teacher_id', 'day_of_week', 'specific_date', 'start_time', 'end_time', 'slot_duration_minutes'],
                (teacher_id, day_of_week, specific_date, start_time, end_time, slot_duration)
            )
    except Exception as e:
        logger.error(f"telemed_set_availability DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "slot_id": slot_id, "message": "Dostupnost nastavena", "timestamp": now_iso()}), 201


@telemedicine_teacher_bp.route('/api/telemedicine/availability', methods=['GET'])
@require_auth
@require_teacher
def telemed_get_availability():
    """Get teacher's availability slots"""
    teacher_id = _get_teacher_id_local()

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT * FROM telemedicine_availability WHERE teacher_id = ? AND is_active = 1 ORDER BY day_of_week, start_time",
                (teacher_id,)
            ).fetchall()

            slots = []
            for r in rows:
                d = dict(r)
                for k in ('specific_date', 'start_time', 'end_time', 'created_at'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                slots.append(d)
    except Exception as e:
        logger.error(f"telemed_get_availability DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "slots": slots, "total": len(slots), "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/availability/<int:slot_id>', methods=['DELETE'])
@require_auth
@require_teacher
def telemed_delete_availability(slot_id):
    """Remove availability slot"""
    teacher_id = _get_teacher_id_local()

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id FROM telemedicine_availability WHERE id = ? AND teacher_id = ?",
                (slot_id, teacher_id)
            ).fetchone()
            if not row:
                return jsonify({"success": False, "error": "Slot nenalezen"}), 404

            db.execute("UPDATE telemedicine_availability SET is_active = 0 WHERE id = ?", (slot_id,))
    except Exception as e:
        logger.error(f"telemed_delete_availability DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "message": "Slot odstranen", "timestamp": now_iso()})


# --- Consultation management ---

@telemedicine_teacher_bp.route('/api/telemedicine/consultations', methods=['GET'])
@require_auth
@require_teacher
def telemed_list_consultations():
    """List consultations for teacher (filters: status, date, student_id)"""
    teacher_id = _get_teacher_id_local()
    status_filter = request.args.get('status')
    date_filter = request.args.get('date')
    student_filter = request.args.get('student_id')
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 20, type=int), 100)

    try:
        with db_context() as db:
            conditions = ["teacher_id = ?"]
            params = [teacher_id]

            if status_filter:
                conditions.append("status = ?")
                params.append(status_filter)
            if date_filter:
                conditions.append("scheduled_date = ?")
                params.append(date_filter)
            if student_filter:
                conditions.append("student_id = ?")
                params.append(student_filter)

            where = " AND ".join(conditions)
            offset = (page - 1) * limit

            count_row = db.execute(
                f"SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE {where}",
                tuple(params)
            ).fetchone()
            total = count_row['cnt'] if count_row else 0

            rows = db.execute(
                f"SELECT id, student_id, scheduled_date, scheduled_time, duration_minutes, status, consultation_type, created_at "
                f"FROM telemedicine_consultations WHERE {where} ORDER BY scheduled_date DESC, scheduled_time DESC "
                f"LIMIT {limit} OFFSET {offset}",
                tuple(params)
            ).fetchall()

            consultations = []
            for r in rows:
                d = dict(r)
                for k in ('scheduled_date', 'scheduled_time', 'created_at'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                consultations.append(d)
    except Exception as e:
        logger.error(f"telemed_list_consultations DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({
        "success": True, "consultations": consultations,
        "total": total, "page": page, "limit": limit, "timestamp": now_iso()
    })


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/confirm', methods=['PUT'])
@require_auth
@require_teacher
def telemed_confirm(consultation_id):
    """Teacher confirms a consultation request"""
    teacher_id = _get_teacher_id_local()

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, student_id, status FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] != 'requested':
                return jsonify({"success": False, "error": f"Nelze potvrdit konzultaci ve stavu '{row['status']}'"}), 400

            db.execute(
                "UPDATE telemedicine_consultations SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (consultation_id,)
            )
            student_id = row['student_id']
    except Exception as e:
        logger.error(f"telemed_confirm DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    _notify_user(student_id, 'telemedicine_confirmed', {
        'consultation_id': consultation_id, 'teacher_id': teacher_id
    })
    _notify_all_participants(consultation_id, 'telemedicine_confirmed', {
        'consultation_id': consultation_id, 'teacher_id': teacher_id
    })

    return jsonify({"success": True, "message": "Konzultace potvrzena", "consultation_id": consultation_id, "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/cancel', methods=['PUT'])
@require_auth
@require_teacher
def telemed_teacher_cancel(consultation_id):
    """Teacher cancels a consultation"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}
    reason = data.get('reason', '').strip()[:MAX_TEXT]

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, student_id, status FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] in ('completed', 'cancelled', 'archived'):
                return jsonify({"success": False, "error": f"Nelze zrusit konzultaci ve stavu '{row['status']}'"}), 400

            db.execute(
                "UPDATE telemedicine_consultations SET status = 'cancelled', cancel_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (reason, consultation_id)
            )
            student_id = row['student_id']
    except Exception as e:
        logger.error(f"telemed_teacher_cancel DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    _notify_user(student_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'teacher', 'reason': reason
    })
    _notify_all_participants(consultation_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'organizer', 'reason': reason
    })

    return jsonify({"success": True, "message": "Konzultace zrusena", "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/start', methods=['PUT'])
@require_auth
@require_teacher
def telemed_start(consultation_id):
    """Teacher starts consultation — generates Jitsi room"""
    teacher_id = _get_teacher_id_local()

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, student_id, status, is_multiparty FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] not in ('confirmed', 'requested'):
                return jsonify({"success": False, "error": f"Nelze spustit konzultaci ve stavu '{row['status']}'"}), 400

            student_id = row['student_id']
            is_mp = bool(row.get('is_multiparty'))
            room_code = _generate_room_code(teacher_id, student_id, multiparty=is_mp)
            jitsi_url = f"https://meet.jit.si/{room_code}"

            db.execute(
                "UPDATE telemedicine_consultations SET status = 'in_progress', room_code = ?, jitsi_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (room_code, jitsi_url, consultation_id)
            )
    except Exception as e:
        logger.error(f"telemed_start DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
    join_page = f"{frontend_url}/call.html?room={room_code}&from=Terapeut&type=video"

    _notify_user(student_id, 'telemedicine_starting', {
        'consultation_id': consultation_id, 'jitsi_url': jitsi_url,
        'room_code': room_code, 'join_page': join_page
    })
    _notify_all_participants(consultation_id, 'telemedicine_starting', {
        'consultation_id': consultation_id, 'jitsi_url': jitsi_url,
        'room_code': room_code, 'join_page': join_page
    })

    return jsonify({
        "success": True, "message": "Konzultace zahajena",
        "consultation_id": consultation_id, "jitsi_url": jitsi_url,
        "room_code": room_code, "join_page": join_page, "timestamp": now_iso()
    })


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/complete', methods=['PUT'])
@require_auth
@require_teacher
def telemed_complete(consultation_id):
    """Teacher completes consultation"""
    teacher_id = _get_teacher_id_local()

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, status FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] != 'in_progress':
                return jsonify({"success": False, "error": f"Nelze ukoncit konzultaci ve stavu '{row['status']}'"}), 400

            db.execute(
                "UPDATE telemedicine_consultations SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (consultation_id,)
            )
    except Exception as e:
        logger.error(f"telemed_complete DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "message": "Konzultace ukoncena", "consultation_id": consultation_id, "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/notes', methods=['PUT'])
@require_auth
@require_teacher
def telemed_notes(consultation_id):
    """Teacher records consultation notes"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}

    complaint = data.get('complaint', '').strip()[:MAX_TEXT]
    findings = data.get('findings', '').strip()[:MAX_TEXT]
    recommendations = data.get('recommendations', '').strip()[:MAX_TEXT]
    extra_notes = data.get('notes', {})

    if not any([complaint, findings, recommendations]):
        return jsonify({"success": False, "error": "Alespon jedno pole (complaint, findings, recommendations) je povinne"}), 400

    try:
        with db_context(commit=True) as db:
            row = db.execute(
                "SELECT id, student_id, status FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()

            if not row:
                return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
            if row['status'] not in ('in_progress', 'completed'):
                return jsonify({"success": False, "error": "Nalez lze zapsat jen u probihajici/dokoncene konzultace"}), 400

            notes_json = json.dumps(extra_notes) if extra_notes else '{}'
            student_id = row['student_id']

            db.execute(
                "UPDATE telemedicine_consultations SET complaint = ?, findings = ?, recommendations = ?, notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (complaint, findings, recommendations, notes_json, consultation_id)
            )
    except Exception as e:
        logger.error(f"telemed_notes DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    _notify_user(student_id, 'telemedicine_notes_ready', {'consultation_id': consultation_id})

    return jsonify({"success": True, "message": "Nalez zapsan", "consultation_id": consultation_id, "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/consultation/<int:consultation_id>/send-summary', methods=['POST'])
@require_auth
@require_teacher
def telemed_send_summary(consultation_id):
    """Send consultation summary via email"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}
    to_email = data.get('to_email', '').strip()

    consultation = _get_consultation(consultation_id)
    if not consultation or consultation.get('teacher_id') != teacher_id:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404

    if not to_email:
        to_email = data.get('email', '')
    if not to_email or '@' not in to_email:
        return jsonify({"success": False, "error": "to_email je povinny"}), 400

    subject = f"Konzultace {consultation.get('scheduled_date', '')} - Shrnuti a doporuceni"
    body_html = f"""
    <html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
    <h2 style="color: #2563eb;">Radim Care - Shrnuti konzultace</h2>
    <p><strong>Datum:</strong> {consultation.get('scheduled_date', '')} v {consultation.get('scheduled_time', '')}</p>
    <p><strong>Typ:</strong> {consultation.get('consultation_type', 'video')}</p>
    <hr/>
    <h3>Duvod konzultace</h3>
    <p>{consultation.get('complaint', '-')}</p>
    <h3>Nalezy</h3>
    <p>{consultation.get('findings', '-')}</p>
    <h3>Doporuceni</h3>
    <p>{consultation.get('recommendations', '-')}</p>
    <hr/>
    <p style="color: #6b7280; font-size: 12px;">Tato zprava byla odeslana z platformy Radim Care (radimcare.cz).</p>
    </body></html>
    """

    try:
        smtp_host = os.environ.get('SMTP_HOST', '')
        smtp_port = int(os.environ.get('SMTP_PORT', '465'))
        smtp_user = os.environ.get('SMTP_USER', '')
        smtp_pass = os.environ.get('SMTP_PASS', '')
        smtp_from = os.environ.get('SMTP_FROM', smtp_user)

        if not smtp_host or not smtp_user:
            return jsonify({"success": False, "error": "SMTP neni nakonfigurovany"}), 503

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, to_email, msg.as_string())
        server.quit()

        try:
            with db_context(commit=True) as db2:
                db2.execute(
                    "UPDATE telemedicine_consultations SET email_sent = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (consultation_id,)
                )
        except Exception:
            pass

    except Exception as e:
        return jsonify({"success": False, "error": f"Email error: {e}"}), 500

    _notify_user(consultation.get('student_id'), 'telemedicine_summary_sent', {
        'consultation_id': consultation_id, 'email': to_email
    })

    return jsonify({"success": True, "message": f"Email odeslan na {to_email}", "timestamp": now_iso()})


@telemedicine_teacher_bp.route('/api/telemedicine/student/<student_id>/history', methods=['GET'])
@require_auth
@require_teacher
def telemed_student_history(student_id):
    """Consultation history for a student (teacher view)"""
    teacher_id = _get_teacher_id_local()
    if not _verify_teacher_student_local(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student vam neni prirazen"}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, scheduled_date, scheduled_time, status, consultation_type, complaint, findings, recommendations, created_at "
                "FROM telemedicine_consultations WHERE teacher_id = ? AND student_id = ? AND status != 'cancelled' "
                "ORDER BY scheduled_date DESC, scheduled_time DESC LIMIT 50",
                (teacher_id, student_id)
            ).fetchall()

            history = []
            for r in rows:
                d = dict(r)
                for k in ('scheduled_date', 'scheduled_time', 'created_at'):
                    if d.get(k) and hasattr(d[k], 'isoformat'):
                        d[k] = d[k].isoformat()
                history.append(d)
    except Exception as e:
        logger.error(f"telemed_student_history DB error: {e}")
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    return jsonify({"success": True, "history": history, "total": len(history), "student_id": student_id, "timestamp": now_iso()})
