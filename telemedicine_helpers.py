# ============================================
# TELEMEDICINE HELPERS v3.0.0 — Shared utilities
# DB functions, notifications, validation, constants
# v3.0: db_context, unified ? placeholders
# ============================================

import json
import time
import uuid
import os
from datetime import datetime, date, timedelta
from flask import g
from database import db_context
from utils import now_iso


# ============================================
# AUTH HELPERS
# ============================================

def _get_user_id():
    """Get current user ID from JWT"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


def _get_teacher_id_local():
    """Get teacher ID from JWT"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


# ============================================
# DB QUERY HELPERS
# ============================================

def _verify_teacher_owns_consultation(teacher_id, consultation_id):
    """Verify teacher owns this consultation"""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id FROM telemedicine_consultations WHERE id = ? AND teacher_id = ?",
                (consultation_id, teacher_id)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _verify_student_owns_consultation(student_id, consultation_id):
    """Verify student owns this consultation"""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id FROM telemedicine_consultations WHERE id = ? AND student_id = ?",
                (consultation_id, student_id)
            ).fetchone()
            return row is not None
    except Exception:
        return False


def _get_consultation(consultation_id):
    """Get consultation by ID"""
    try:
        with db_context() as db:
            row = db.execute("SELECT * FROM telemedicine_consultations WHERE id = ?", (consultation_id,)).fetchone()
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


def _generate_room_code(teacher_id, student_id, multiparty=False):
    """Generate Jitsi room code"""
    if multiparty:
        return f"radim-team-{uuid.uuid4().hex[:12]}"
    ts = int(time.time())
    return f"radim-consult-{str(teacher_id)[:8]}-{str(student_id)[:8]}-{ts}"


# ============================================
# NOTIFICATION HELPERS
# ============================================

def _notify_user(user_id, event, data):
    """Emit SocketIO event (non-blocking, non-fatal)"""
    try:
        from flask import current_app
        socketio = current_app.extensions.get('socketio')
        if socketio:
            socketio.emit(event, data, room=f'user_{user_id}')
    except Exception:
        pass


def _notify_all_participants(consultation_id, event, data):
    """Notify all accepted participants of a consultation event"""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id FROM telemedicine_participants WHERE consultation_id = ? AND status = 'accepted'",
                (consultation_id,)
            ).fetchall()
            for r in rows:
                _notify_user(r['user_id'], event, data)
    except Exception:
        pass


# ============================================
# VALIDATION HELPERS
# ============================================

def _validate_date(d):
    try:
        return datetime.strptime(d, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _validate_time(t):
    try:
        return datetime.strptime(t, '%H:%M').time()
    except (ValueError, TypeError):
        return None


# ============================================
# TEACHER-STUDENT RELATIONSHIP HELPERS
# ============================================

def _get_teacher_students_local(teacher_id):
    """Get students assigned to teacher"""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT student_id FROM education_assignments WHERE teacher_id = ? AND status = 'active'",
                (teacher_id,)
            ).fetchall()
            return [r['student_id'] for r in rows]
    except Exception:
        return []


def _verify_teacher_student_local(teacher_id, student_id):
    return student_id in _get_teacher_students_local(teacher_id)


def _get_assigned_teacher(student_id):
    """Get student's assigned teacher"""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT teacher_id FROM education_assignments WHERE student_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (student_id,)
            ).fetchone()
            return row['teacher_id'] if row else None
    except Exception:
        return None


# ============================================
# MULTI-PARTY HELPERS
# ============================================

def _is_participant(user_id, consultation):
    """Check if user is organizer, patient, or accepted participant"""
    if user_id == str(consultation.get('teacher_id', '')) or user_id == str(consultation.get('student_id', '')):
        return True
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT id FROM telemedicine_participants WHERE consultation_id = ? AND user_id = ? AND status = 'accepted'",
                (consultation.get('id'), user_id)
            ).fetchone()
            return row is not None
    except Exception:
        return False


# ============================================
# CONSTANTS
# ============================================

MAX_TEXT = 10000
PARTICIPANT_ROLES = ('organizer', 'specialist', 'observer', 'patient')
SPECIALTIES = ('speech_therapist', 'neurologist', 'social_worker', 'psychologist',
               'doctor', 'nurse', 'physiotherapist', 'occupational_therapist', 'other')
PARTICIPANT_STATUSES = ('invited', 'accepted', 'declined', 'joined', 'left')


# ============================================
# SCHEDULER HELPER — exported for app.py
# ============================================

def get_upcoming_consultations_for_reminder(window_minutes=15):
    """Get confirmed consultations starting within N minutes"""
    now = datetime.now()
    current_date = now.date().isoformat()
    current_time = now.strftime('%H:%M')
    future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M')

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, teacher_id, student_id, scheduled_time, scheduled_date "
                "FROM telemedicine_consultations "
                "WHERE status = 'confirmed' AND scheduled_date = ? AND scheduled_time >= ? AND scheduled_time <= ?",
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
                try:
                    part_rows = db.execute(
                        "SELECT user_id FROM telemedicine_participants WHERE consultation_id = ? AND status = 'accepted'",
                        (d['id'],)
                    ).fetchall()
                    d['participant_ids'] = [pr['user_id'] for pr in part_rows]
                except Exception:
                    d['participant_ids'] = []
                results.append(d)
            return results
    except Exception:
        return []
