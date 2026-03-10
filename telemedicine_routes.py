# ============================================
# 🏥 TELEMEDICINE ROUTES v2.0.0 — Multiparty
# Remote consultations: scheduling, Jitsi video, notes, email summaries
# Multi-party: multiple professionals consult together about one patient
# ============================================

import json
import time
import uuid
import os
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, request, jsonify, g
from database import get_connection, is_postgres
from auth_middleware import require_auth, require_teacher

telemedicine_bp = Blueprint('telemedicine', __name__)

# ============================================
# HELPERS
# ============================================

def _p():
    """SQL placeholder: %s for Postgres, ? for SQLite"""
    return "%s" if is_postgres() else "?"


def _now_iso():
    return datetime.utcnow().isoformat() + "Z"


def _get_user_id():
    """Get current user ID from JWT"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


def _get_teacher_id_local():
    """Get teacher ID from JWT (local copy to avoid circular import issues)"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


def _verify_teacher_owns_consultation(teacher_id, consultation_id):
    """Verify teacher owns this consultation"""
    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
            (consultation_id, teacher_id)
        ).fetchone()
        return row is not None
    except Exception:
        return False


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
def _verify_student_owns_consultation(student_id, consultation_id):
    """Verify student owns this consultation"""
    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id FROM telemedicine_consultations WHERE id = {p} AND student_id = {p}",
            (consultation_id, student_id)
        ).fetchone()
        return row is not None
    except Exception:
        return False


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
def _get_consultation(consultation_id):
    """Get consultation by ID"""
    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT * FROM telemedicine_consultations WHERE id = {p}",
            (consultation_id,)
        ).fetchone()
        if row:
            d = dict(row)
            for k in ('scheduled_date', 'scheduled_time', 'created_at', 'updated_at'):
                if d.get(k) and hasattr(d[k], 'isoformat'):
                    d[k] = d[k].isoformat()
            if isinstance(d.get('notes'), str):
                try:
                    d['notes'] = json.loads(d['notes'])
                except Exception:
                    d['notes'] = {}
            return d
        return None
    except Exception:
        return None


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
def _generate_room_code(teacher_id, student_id, multiparty=False):
    """Generate Jitsi room code (UUID for multi-party, legacy format for 1:1)"""
    if multiparty:
        return f"radim-team-{uuid.uuid4().hex[:12]}"
    ts = int(time.time())
    return f"radim-consult-{str(teacher_id)[:8]}-{str(student_id)[:8]}-{ts}"


def _notify_user(user_id, event, data):
    """Emit SocketIO event (non-blocking, non-fatal)"""
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit(event, data, room=f'user_{user_id}')
    except Exception:
        pass


def _validate_date(d):
    """Validate YYYY-MM-DD format, return parsed or None"""
    try:
        return datetime.strptime(d, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _validate_time(t):
    """Validate HH:MM format, return parsed or None"""
    try:
        return datetime.strptime(t, '%H:%M').time()
    except (ValueError, TypeError):
        return None


def _get_teacher_students_local(teacher_id):
    """Get students assigned to teacher (local copy)"""
    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT student_id FROM education_assignments WHERE teacher_id = {p} AND status = 'active'",
            (teacher_id,)
        ).fetchall()
        return [r['student_id'] for r in rows]
    except Exception:
        return []


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
def _verify_teacher_student_local(teacher_id, student_id):
    """Verify teacher-student relationship (local)"""
    return student_id in _get_teacher_students_local(teacher_id)


def _get_assigned_teacher(student_id):
    """Get student's assigned teacher"""
    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT teacher_id FROM education_assignments WHERE student_id = {p} AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (student_id,)
        ).fetchone()
        return row['teacher_id'] if row else None
    except Exception:
        return None


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
MAX_TEXT = 10000  # max characters for text fields

# --- Multi-party constants ---
PARTICIPANT_ROLES = ('organizer', 'specialist', 'observer', 'patient')
SPECIALTIES = ('speech_therapist', 'neurologist', 'social_worker', 'psychologist',
               'doctor', 'nurse', 'physiotherapist', 'occupational_therapist', 'other')
PARTICIPANT_STATUSES = ('invited', 'accepted', 'declined', 'joined', 'left')


def _is_participant(user_id, consultation):
    """Check if user is organizer, patient, or accepted participant"""
    if user_id == str(consultation.get('teacher_id', '')) or user_id == str(consultation.get('student_id', '')):
        return True
    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id FROM telemedicine_participants WHERE consultation_id = {p} AND user_id = {p} AND status = 'accepted'",
            (consultation.get('id'), user_id)
        ).fetchone()
        return row is not None
    except Exception:
        return False


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
def _notify_all_participants(consultation_id, event, data):
    """Notify all accepted participants of a consultation event"""
    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT user_id FROM telemedicine_participants WHERE consultation_id = {p} AND status = 'accepted'",
            (consultation_id,)
        ).fetchall()
        for r in rows:
            _notify_user(r['user_id'], event, data)
    except Exception:
        pass


    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
# ============================================
# 🩺 TEACHER ENDPOINTS — Telemedicine Dashboard
# ============================================

@telemedicine_bp.route('/api/telemedicine/dashboard', methods=['GET'])
@require_auth
@require_teacher
def telemed_dashboard():
    """Teacher telemedicine overview"""
    teacher_id = _get_teacher_id_local()
    today = date.today().isoformat()

    db = None
    try:
        db = get_connection()
        p = _p()

        # Today's consultations
        today_rows = db.execute(
            f"SELECT id, student_id, scheduled_time, status, consultation_type FROM telemedicine_consultations "
            f"WHERE teacher_id = {p} AND scheduled_date = {p} AND status != 'cancelled' ORDER BY scheduled_time",
            (teacher_id, today)
        ).fetchall()

        # Pending requests
        pending = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE teacher_id = {p} AND status = 'requested'",
            (teacher_id,)
        ).fetchone()

        # Total consultations this month
        month_start = date.today().replace(day=1).isoformat()
        total = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE teacher_id = {p} AND scheduled_date >= {p} AND status = 'completed'",
            (teacher_id, month_start)
        ).fetchone()

    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    today_list = []
    for r in today_rows:
        d = dict(r)
        if d.get('scheduled_time') and hasattr(d['scheduled_time'], 'isoformat'):
            d['scheduled_time'] = d['scheduled_time'].isoformat()
        today_list.append(d)

    return jsonify({
        "success": True,
        "teacher_id": teacher_id,
        "today": today_list,
        "today_count": len(today_list),
        "pending_requests": pending['cnt'] if pending else 0,
        "completed_this_month": total['cnt'] if total else 0,
        "date": today,
        "timestamp": _now_iso()
    })


# --- Availability ---

@telemedicine_bp.route('/api/telemedicine/availability', methods=['POST'])
@require_auth
@require_teacher
def telemed_set_availability():
    """Set teacher availability slot"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}

    day_of_week = data.get('day_of_week')  # 0-6 or None
    specific_date = data.get('specific_date')  # YYYY-MM-DD or None
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

    db = None
    try:
        db = get_connection()
        p = _p()
        if is_postgres():
            row = db.execute(
                f"INSERT INTO telemedicine_availability (teacher_id, day_of_week, specific_date, start_time, end_time, slot_duration_minutes) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id",
                (teacher_id, day_of_week, specific_date, start_time, end_time, slot_duration)
            ).fetchone()
            slot_id = row['id'] if row else None
        else:
            cursor = db.execute(
                f"INSERT INTO telemedicine_availability (teacher_id, day_of_week, specific_date, start_time, end_time, slot_duration_minutes) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
                (teacher_id, day_of_week, specific_date, start_time, end_time, slot_duration)
            )
            slot_id = cursor.lastrowid
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
        "slot_id": slot_id,
        "message": "Dostupnost nastavena",
        "timestamp": _now_iso()
    }), 201


@telemedicine_bp.route('/api/telemedicine/availability', methods=['GET'])
@require_auth
@require_teacher
def telemed_get_availability():
    """Get teacher's availability slots"""
    teacher_id = _get_teacher_id_local()

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT * FROM telemedicine_availability WHERE teacher_id = {p} AND is_active = 1 ORDER BY day_of_week, start_time",
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "slots": slots,
        "total": len(slots),
        "timestamp": _now_iso()
    })


@telemedicine_bp.route('/api/telemedicine/availability/<int:slot_id>', methods=['DELETE'])
@require_auth
@require_teacher
def telemed_delete_availability(slot_id):
    """Remove availability slot"""
    teacher_id = _get_teacher_id_local()

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id FROM telemedicine_availability WHERE id = {p} AND teacher_id = {p}",
            (slot_id, teacher_id)
        ).fetchone()
        if not row:
            return jsonify({"success": False, "error": "Slot nenalezen"}), 404

        db.execute(
            f"UPDATE telemedicine_availability SET is_active = 0 WHERE id = {p}",
            (slot_id,)
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
    return jsonify({"success": True, "message": "Slot odstranen", "timestamp": _now_iso()})


# --- Consultation management ---

@telemedicine_bp.route('/api/telemedicine/consultations', methods=['GET'])
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

    db = None
    try:
        db = get_connection()
        p = _p()
        conditions = [f"teacher_id = {p}"]
        params = [teacher_id]

        if status_filter:
            conditions.append(f"status = {p}")
            params.append(status_filter)
        if date_filter:
            conditions.append(f"scheduled_date = {p}")
            params.append(date_filter)
        if student_filter:
            conditions.append(f"student_id = {p}")
            params.append(student_filter)

        where = " AND ".join(conditions)
        offset = (page - 1) * limit

        # Count
        count_row = db.execute(
            f"SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE {where}",
            tuple(params)
        ).fetchone()
        total = count_row['cnt'] if count_row else 0

        # Fetch
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({
        "success": True,
        "consultations": consultations,
        "total": total,
        "page": page,
        "limit": limit,
        "timestamp": _now_iso()
    })


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/confirm', methods=['PUT'])
@require_auth
@require_teacher
def telemed_confirm(consultation_id):
    """Teacher confirms a consultation request"""
    teacher_id = _get_teacher_id_local()

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, student_id, status FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
            (consultation_id, teacher_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
        if row['status'] != 'requested':
            return jsonify({"success": False, "error": f"Nelze potvrdit konzultaci ve stavu '{row['status']}'"}), 400

        db.execute(
            f"UPDATE telemedicine_consultations SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (consultation_id,)
        )
        db.commit()
        student_id = row['student_id']
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    _notify_user(student_id, 'telemedicine_confirmed', {
        'consultation_id': consultation_id, 'teacher_id': teacher_id
    })
    # Multi-party: also notify all participants
    _notify_all_participants(consultation_id, 'telemedicine_confirmed', {
        'consultation_id': consultation_id, 'teacher_id': teacher_id
    })

    return jsonify({"success": True, "message": "Konzultace potvrzena", "consultation_id": consultation_id, "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/cancel', methods=['PUT'])
@require_auth
@require_teacher
def telemed_teacher_cancel(consultation_id):
    """Teacher cancels a consultation"""
    teacher_id = _get_teacher_id_local()
    data = request.json or {}
    reason = data.get('reason', '').strip()[:MAX_TEXT]

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, student_id, status FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
            (consultation_id, teacher_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
        if row['status'] in ('completed', 'cancelled', 'archived'):
            return jsonify({"success": False, "error": f"Nelze zrusit konzultaci ve stavu '{row['status']}'"}), 400

        db.execute(
            f"UPDATE telemedicine_consultations SET status = 'cancelled', cancel_reason = {p}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (reason, consultation_id)
        )
        db.commit()
        student_id = row['student_id']
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    _notify_user(student_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'teacher', 'reason': reason
    })
    # Multi-party: also notify all participants
    _notify_all_participants(consultation_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'organizer', 'reason': reason
    })

    return jsonify({"success": True, "message": "Konzultace zrusena", "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/start', methods=['PUT'])
@require_auth
@require_teacher
def telemed_start(consultation_id):
    """Teacher starts consultation — generates Jitsi room"""
    teacher_id = _get_teacher_id_local()

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, student_id, status, is_multiparty FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
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
            f"UPDATE telemedicine_consultations SET status = 'in_progress', room_code = {p}, jitsi_url = {p}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (room_code, jitsi_url, consultation_id)
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
    # Build frontend join URL
    frontend_url = os.environ.get('FRONTEND_URL', 'https://polite-bush-001303503.6.azurestaticapps.net')
    join_page = f"{frontend_url}/call.html?room={room_code}&from=Terapeut&type=video"

    _notify_user(student_id, 'telemedicine_starting', {
        'consultation_id': consultation_id,
        'jitsi_url': jitsi_url,
        'room_code': room_code,
        'join_page': join_page
    })
    # Multi-party: notify all accepted participants
    _notify_all_participants(consultation_id, 'telemedicine_starting', {
        'consultation_id': consultation_id,
        'jitsi_url': jitsi_url,
        'room_code': room_code,
        'join_page': join_page
    })

    return jsonify({
        "success": True,
        "message": "Konzultace zahajena",
        "consultation_id": consultation_id,
        "jitsi_url": jitsi_url,
        "room_code": room_code,
        "join_page": join_page,
        "timestamp": _now_iso()
    })


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/complete', methods=['PUT'])
@require_auth
@require_teacher
def telemed_complete(consultation_id):
    """Teacher completes consultation"""
    teacher_id = _get_teacher_id_local()

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, status FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
            (consultation_id, teacher_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
        if row['status'] != 'in_progress':
            return jsonify({"success": False, "error": f"Nelze ukoncit konzultaci ve stavu '{row['status']}'"}), 400

        db.execute(
            f"UPDATE telemedicine_consultations SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (consultation_id,)
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
    return jsonify({"success": True, "message": "Konzultace ukoncena", "consultation_id": consultation_id, "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/notes', methods=['PUT'])
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

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, student_id, status FROM telemedicine_consultations WHERE id = {p} AND teacher_id = {p}",
            (consultation_id, teacher_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
        if row['status'] not in ('in_progress', 'completed'):
            return jsonify({"success": False, "error": f"Nalez lze zapsat jen u probihajici/dokoncene konzultace"}), 400

        notes_json = json.dumps(extra_notes) if extra_notes else '{}'
        student_id = row['student_id']

        db.execute(
            f"UPDATE telemedicine_consultations SET complaint = {p}, findings = {p}, recommendations = {p}, notes = {p}, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
            (complaint, findings, recommendations, notes_json, consultation_id)
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
    _notify_user(student_id, 'telemedicine_notes_ready', {'consultation_id': consultation_id})

    return jsonify({"success": True, "message": "Nalez zapsan", "consultation_id": consultation_id, "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/send-summary', methods=['POST'])
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
        # Try to get student email from JWT user data or fallback
        to_email = data.get('email', '')

    if not to_email or '@' not in to_email:
        return jsonify({"success": False, "error": "to_email je povinny"}), 400

    # Build email
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

    # Send via SMTP
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

        # Mark email sent
        db2 = None
        try:
            db2 = get_connection()
            p = _p()
            db2.execute(
                f"UPDATE telemedicine_consultations SET email_sent = 1, updated_at = CURRENT_TIMESTAMP WHERE id = {p}",
                (consultation_id,)
            )
            db2.commit()
        finally:
            if db2:
                try:
                    db2.close()
                except Exception:
                    pass

    except Exception as e:
        return jsonify({"success": False, "error": f"Email error: {e}"}), 500

    _notify_user(consultation.get('student_id'), 'telemedicine_summary_sent', {
        'consultation_id': consultation_id, 'email': to_email
    })

    return jsonify({"success": True, "message": f"Email odeslan na {to_email}", "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/student/<student_id>/history', methods=['GET'])
@require_auth
@require_teacher
def telemed_student_history(student_id):
    """Consultation history for a student (teacher view)"""
    teacher_id = _get_teacher_id_local()
    if not _verify_teacher_student_local(teacher_id, student_id):
        return jsonify({"success": False, "error": "Student vam neni prirazen"}), 403

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, scheduled_date, scheduled_time, status, consultation_type, complaint, findings, recommendations, created_at "
            f"FROM telemedicine_consultations WHERE teacher_id = {p} AND student_id = {p} AND status != 'cancelled' "
            f"ORDER BY scheduled_date DESC, scheduled_time DESC LIMIT 50",
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
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    return jsonify({"success": True, "history": history, "total": len(history), "student_id": student_id, "timestamp": _now_iso()})


# ============================================
# 👤 STUDENT ENDPOINTS — My Consultations
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
    return jsonify({"success": True, "upcoming": upcoming, "total": len(upcoming), "timestamp": _now_iso()})


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
    return jsonify({"success": True, "history": history, "total": len(history), "timestamp": _now_iso()})


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
        "timestamp": _now_iso()
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

    return jsonify({"success": True, "consultation": consultation, "timestamp": _now_iso()})


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
    return jsonify({"success": True, "teacher_id": teacher_id, "slots": slots, "total": len(slots), "timestamp": _now_iso()})


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

    return jsonify({"success": True, "message": "Konzultace zrusena", "timestamp": _now_iso()})


# ============================================
# 🔗 SHARED — Join consultation
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
        "timestamp": _now_iso()
    })


# ============================================
# 👥 MULTI-PARTY ENDPOINTS — Team Consultations
# ============================================

@telemedicine_bp.route('/api/telemedicine/consultation/multiparty', methods=['POST'])
@require_auth
@require_teacher
def telemed_create_multiparty():
    """Create a multi-party consultation with invited specialists"""
    organizer_id = _get_teacher_id_local()
    data = request.json or {}

    patient_id = data.get('patient_id', '').strip()
    title = data.get('title', '').strip()[:MAX_TEXT]
    scheduled_date = data.get('scheduled_date', '').strip()
    scheduled_time = data.get('scheduled_time', '').strip()
    duration = data.get('duration_minutes', 30)
    consultation_type = data.get('consultation_type', 'video')
    complaint = data.get('complaint', '').strip()[:MAX_TEXT]
    participants = data.get('participants', [])  # [{"user_id": "...", "specialty": "neurologist"}, ...]

    if not patient_id:
        return jsonify({"success": False, "error": "patient_id je povinny"}), 400
    if not scheduled_date or not scheduled_time:
        return jsonify({"success": False, "error": "scheduled_date a scheduled_time jsou povinne"}), 400
    if not _validate_date(scheduled_date):
        return jsonify({"success": False, "error": "Datum musi byt ve formatu YYYY-MM-DD"}), 400
    if not _validate_time(scheduled_time):
        return jsonify({"success": False, "error": "Cas musi byt ve formatu HH:MM"}), 400
    if consultation_type not in ('video', 'audio'):
        consultation_type = 'video'

    # Verify organizer has relationship with patient
    if not _verify_teacher_student_local(organizer_id, patient_id):
        return jsonify({"success": False, "error": "Pacient vam neni prirazen"}), 403

    db = None
    try:
        db = get_connection()
        p = _p()

        # Create consultation
        if is_postgres():
            row = db.execute(
                f"INSERT INTO telemedicine_consultations (teacher_id, student_id, scheduled_date, scheduled_time, duration_minutes, "
                f"consultation_type, complaint, title, is_multiparty, status) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 1, 'confirmed') RETURNING id",
                (organizer_id, patient_id, scheduled_date, scheduled_time, duration, consultation_type, complaint, title)
            ).fetchone()
            cid = row['id'] if row else None
        else:
            cursor = db.execute(
                f"INSERT INTO telemedicine_consultations (teacher_id, student_id, scheduled_date, scheduled_time, duration_minutes, "
                f"consultation_type, complaint, title, is_multiparty, status) "
                f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 1, 'confirmed')",
                (organizer_id, patient_id, scheduled_date, scheduled_time, duration, consultation_type, complaint, title)
            )
            cid = cursor.lastrowid

        # Auto-insert organizer as participant
        db.execute(
            f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, specialty, status) VALUES ({p}, {p}, 'organizer', {p}, 'accepted')",
            (cid, organizer_id, data.get('organizer_specialty', 'other'))
        )

        # Auto-insert patient as participant
        db.execute(
            f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, status) VALUES ({p}, {p}, 'patient', 'accepted')",
            (cid, patient_id)
        )

        # Invite specialists
        invited_count = 0
        for part in participants[:20]:  # max 20 participants
            uid = str(part.get('user_id', '')).strip()
            specialty = part.get('specialty', 'other')
            role = part.get('role', 'specialist')
            if not uid or uid in (organizer_id, patient_id):
                continue
            if specialty not in SPECIALTIES:
                specialty = 'other'
            if role not in ('specialist', 'observer'):
                role = 'specialist'
            try:
                db.execute(
                    f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, specialty, status) VALUES ({p}, {p}, {p}, {p}, 'invited')",
                    (cid, uid, role, specialty)
                )
                invited_count += 1
            except Exception:
                pass  # duplicate — skip

        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    # Notify patient
    _notify_user(patient_id, 'telemedicine_confirmed', {
        'consultation_id': cid, 'teacher_id': organizer_id, 'title': title, 'multiparty': True
    })
    # Notify invited participants
    for part in participants[:20]:
        uid = str(part.get('user_id', '')).strip()
        if uid and uid not in (organizer_id, patient_id):
            _notify_user(uid, 'telemedicine_invited', {
                'consultation_id': cid, 'organizer_id': organizer_id, 'title': title,
                'scheduled_date': scheduled_date, 'scheduled_time': scheduled_time
            })

    return jsonify({
        "success": True,
        "message": "Multiparty konzultace vytvorena",
        "consultation_id": cid,
        "participants_invited": invited_count,
        "status": "confirmed",
        "is_multiparty": True,
        "timestamp": _now_iso()
    }), 201


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants', methods=['POST'])
@require_auth
@require_teacher
def telemed_invite_participant(consultation_id):
    """Invite a specialist to consultation (organizer only)"""
    organizer_id = _get_teacher_id_local()

    consultation = _get_consultation(consultation_id)
    if not consultation or consultation.get('teacher_id') != organizer_id:
        return jsonify({"success": False, "error": "Konzultace nenalezena nebo nejste organizator"}), 404

    if consultation.get('status') in ('completed', 'cancelled', 'archived'):
        return jsonify({"success": False, "error": "Nelze pridavat ucastniky k ukoncene konzultaci"}), 400

    data = request.json or {}
    user_id = str(data.get('user_id', '')).strip()
    role = data.get('role', 'specialist')
    specialty = data.get('specialty', 'other')

    if not user_id:
        return jsonify({"success": False, "error": "user_id je povinny"}), 400
    if role not in ('specialist', 'observer'):
        return jsonify({"success": False, "error": f"role musi byt specialist nebo observer"}), 400
    if specialty not in SPECIALTIES:
        specialty = 'other'

    db = None
    try:
        db = get_connection()
        p = _p()

        # Mark as multiparty if not already
        if not consultation.get('is_multiparty'):
            db.execute(f"UPDATE telemedicine_consultations SET is_multiparty = 1 WHERE id = {p}", (consultation_id,))
            # Auto-insert organizer and patient if first time
            try:
                db.execute(
                    f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, status) VALUES ({p}, {p}, 'organizer', 'accepted')",
                    (consultation_id, organizer_id)
                )
            except Exception:
                pass
            try:
                db.execute(
                    f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, status) VALUES ({p}, {p}, 'patient', 'accepted')",
                    (consultation_id, consultation.get('student_id'))
                )
            except Exception:
                pass

        if is_postgres():
            row = db.execute(
                f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, specialty, status) "
                f"VALUES ({p}, {p}, {p}, {p}, 'invited') RETURNING id",
                (consultation_id, user_id, role, specialty)
            ).fetchone()
            pid = row['id'] if row else None
        else:
            cursor = db.execute(
                f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, specialty, status) "
                f"VALUES ({p}, {p}, {p}, {p}, 'invited')",
                (consultation_id, user_id, role, specialty)
            )
            pid = cursor.lastrowid

        db.commit()
    except Exception as e:
        if 'UNIQUE' in str(e).upper() or 'unique' in str(e):
            return jsonify({"success": False, "error": "Uzivatel je jiz pozvan"}), 409
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    _notify_user(user_id, 'telemedicine_invited', {
        'consultation_id': consultation_id, 'organizer_id': organizer_id,
        'role': role, 'specialty': specialty
    })

    return jsonify({"success": True, "participant_id": pid, "message": "Odbornik pozvan", "timestamp": _now_iso()}), 201


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants', methods=['GET'])
@require_auth
def telemed_list_participants(consultation_id):
    """List all participants of a consultation"""
    user_id = _get_user_id()
    consultation = _get_consultation(consultation_id)

    if not consultation:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
    if not _is_participant(user_id, consultation):
        return jsonify({"success": False, "error": "Nemate opravneni"}), 403

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, user_id, role, specialty, status, notes_contribution, joined_at, left_at, created_at "
            f"FROM telemedicine_participants WHERE consultation_id = {p} ORDER BY created_at",
            (consultation_id,)
        ).fetchall()

        participants = []
        for r in rows:
            d = dict(r)
            for k in ('joined_at', 'left_at', 'created_at'):
                if d.get(k) and hasattr(d[k], 'isoformat'):
                    d[k] = d[k].isoformat()
            participants.append(d)
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    # If no participants rows (legacy 1:1), return synthetic list
    if not participants:
        participants = [
            {"user_id": consultation.get('teacher_id'), "role": "organizer", "status": "accepted"},
            {"user_id": consultation.get('student_id'), "role": "patient", "status": "accepted"}
        ]

    return jsonify({
        "success": True,
        "consultation_id": consultation_id,
        "participants": participants,
        "total": len(participants),
        "is_multiparty": bool(consultation.get('is_multiparty')),
        "timestamp": _now_iso()
    })


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/respond', methods=['PUT'])
@require_auth
def telemed_respond_invitation(consultation_id):
    """Accept or decline a consultation invitation"""
    user_id = _get_user_id()
    data = request.json or {}
    response = data.get('response', '').strip().lower()

    if response not in ('accepted', 'declined'):
        return jsonify({"success": False, "error": "response musi byt 'accepted' nebo 'declined'"}), 400

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, status, consultation_id FROM telemedicine_participants WHERE consultation_id = {p} AND user_id = {p}",
            (consultation_id, user_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Pozvanka nenalezena"}), 404
        if row['status'] != 'invited':
            return jsonify({"success": False, "error": f"Pozvanka je jiz ve stavu '{row['status']}'"}), 400

        db.execute(
            f"UPDATE telemedicine_participants SET status = {p} WHERE id = {p}",
            (response, row['id'])
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
    # Notify organizer
    consultation = _get_consultation(consultation_id)
    if consultation:
        _notify_user(consultation.get('teacher_id'), 'telemedicine_invitation_response', {
            'consultation_id': consultation_id, 'user_id': user_id, 'response': response
        })

    return jsonify({"success": True, "status": response, "message": f"Pozvanka {response}", "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/notes', methods=['PUT'])
@require_auth
@require_teacher
def telemed_participant_notes(consultation_id):
    """Specialist submits their individual notes"""
    user_id = _get_teacher_id_local()
    data = request.json or {}
    notes_contribution = data.get('notes_contribution', '').strip()[:MAX_TEXT]

    if not notes_contribution:
        return jsonify({"success": False, "error": "notes_contribution je povinne"}), 400

    consultation = _get_consultation(consultation_id)
    if not consultation:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
    if consultation.get('status') not in ('in_progress', 'completed'):
        return jsonify({"success": False, "error": "Poznamky lze zapsat jen u probihajici/dokoncene konzultace"}), 400

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id, role FROM telemedicine_participants WHERE consultation_id = {p} AND user_id = {p} AND status = 'accepted'",
            (consultation_id, user_id)
        ).fetchone()

        if not row:
            # Allow organizer to write even without participant row (legacy 1:1)
            if user_id != consultation.get('teacher_id'):
                return jsonify({"success": False, "error": "Nejste ucastnikem konzultace"}), 403
            # Auto-create participant row for organizer
            db.execute(
                f"INSERT INTO telemedicine_participants (consultation_id, user_id, role, status, notes_contribution) "
                f"VALUES ({p}, {p}, 'organizer', 'accepted', {p})",
                (consultation_id, user_id, notes_contribution)
            )
        else:
            db.execute(
                f"UPDATE telemedicine_participants SET notes_contribution = {p} WHERE id = {p}",
                (notes_contribution, row['id'])
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
    # Notify organizer if specialist wrote notes
    if user_id != consultation.get('teacher_id'):
        _notify_user(consultation.get('teacher_id'), 'telemedicine_notes_ready', {
            'consultation_id': consultation_id, 'from_user': user_id
        })

    return jsonify({"success": True, "message": "Poznamky ulozeny", "timestamp": _now_iso()})


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/all-notes', methods=['GET'])
@require_auth
def telemed_all_notes(consultation_id):
    """Get compiled notes from all participants"""
    user_id = _get_user_id()
    consultation = _get_consultation(consultation_id)

    if not consultation:
        return jsonify({"success": False, "error": "Konzultace nenalezena"}), 404
    if not _is_participant(user_id, consultation):
        return jsonify({"success": False, "error": "Nemate opravneni"}), 403

    # Organizer's main notes
    organizer_notes = {
        "complaint": consultation.get('complaint', ''),
        "findings": consultation.get('findings', ''),
        "recommendations": consultation.get('recommendations', '')
    }

    # Specialist contributions
    specialist_notes = []
    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT user_id, role, specialty, notes_contribution FROM telemedicine_participants "
            f"WHERE consultation_id = {p} AND notes_contribution IS NOT NULL AND notes_contribution != ''",
            (consultation_id,)
        ).fetchall()
        specialist_notes = [dict(r) for r in rows]
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
        "consultation_id": consultation_id,
        "organizer_notes": organizer_notes,
        "specialist_notes": specialist_notes,
        "total_contributions": len(specialist_notes),
        "timestamp": _now_iso()
    })


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/<participant_user_id>', methods=['DELETE'])
@require_auth
@require_teacher
def telemed_remove_participant(consultation_id, participant_user_id):
    """Remove participant from consultation (organizer only)"""
    organizer_id = _get_teacher_id_local()

    consultation = _get_consultation(consultation_id)
    if not consultation or consultation.get('teacher_id') != organizer_id:
        return jsonify({"success": False, "error": "Konzultace nenalezena nebo nejste organizator"}), 404

    # Cannot remove organizer or patient
    if participant_user_id == organizer_id:
        return jsonify({"success": False, "error": "Nelze odebrat organizatora"}), 400
    if participant_user_id == consultation.get('student_id'):
        return jsonify({"success": False, "error": "Nelze odebrat pacienta"}), 400

    db = None
    try:
        db = get_connection()
        p = _p()
        row = db.execute(
            f"SELECT id FROM telemedicine_participants WHERE consultation_id = {p} AND user_id = {p}",
            (consultation_id, participant_user_id)
        ).fetchone()

        if not row:
            return jsonify({"success": False, "error": "Ucastnik nenalezen"}), 404

        db.execute(f"DELETE FROM telemedicine_participants WHERE id = {p}", (row['id'],))
        db.commit()
    except Exception as e:
        return jsonify({"success": False, "error": f"DB error: {e}"}), 500

    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
    _notify_user(participant_user_id, 'telemedicine_cancelled', {
        'consultation_id': consultation_id, 'cancelled_by': 'organizer', 'reason': 'Odebrán z konzultace'
    })

    return jsonify({"success": True, "message": "Ucastnik odstranen", "timestamp": _now_iso()})


# ============================================
# ⏰ SCHEDULER HELPER — exported for app.py
# ============================================

def get_upcoming_consultations_for_reminder(window_minutes=15):
    """Get confirmed consultations starting within N minutes (called by APScheduler in app.py)"""
    now = datetime.now()
    current_date = now.date().isoformat()
    current_time = now.strftime('%H:%M')
    future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M')

    db = None
    try:
        db = get_connection()
        p = _p()
        rows = db.execute(
            f"SELECT id, teacher_id, student_id, scheduled_time, scheduled_date "
            f"FROM telemedicine_consultations "
            f"WHERE status = 'confirmed' AND scheduled_date = {p} AND scheduled_time >= {p} AND scheduled_time <= {p}",
            (current_date, current_time, future_time)
        ).fetchall()

        results = []
        for r in rows:
            d = dict(r)
            sched_str = f"{d['scheduled_date']} {d['scheduled_time']}"
            try:
                sched_dt = datetime.strptime(str(sched_str), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    sched_dt = datetime.strptime(str(sched_str), '%Y-%m-%d %H:%M')
                except ValueError:
                    continue
            d['minutes_until'] = max(0, int((sched_dt - now).total_seconds() / 60))
            # Multi-party: include participant IDs
            try:
                part_rows = db.execute(
                    f"SELECT user_id FROM telemedicine_participants WHERE consultation_id = {p} AND status = 'accepted'",
                    (d['id'],)
                ).fetchall()
                d['participant_ids'] = [pr['user_id'] for pr in part_rows]
            except Exception:
                d['participant_ids'] = []
            results.append(d)
        return results
    except Exception:
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass
