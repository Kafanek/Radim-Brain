# ============================================
# TELEMEDICINE HELPERS — Shared utilities
# DB functions, notifications, validation, constants
# Extracted from telemedicine_routes.py for modularity
# ============================================

import json
import time
import uuid
import os
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import g
from database import get_connection, is_postgres
from utils import now_iso


# ============================================
# SQL + AUTH HELPERS
# ============================================

def _p():
    """SQL placeholder — always ? (PgCursorWrapper converts to %s automatically)"""
    return "?"


def _get_user_id():
    """Get current user ID from JWT"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


def _get_teacher_id_local():
    """Get teacher ID from JWT (local copy to avoid circular import issues)"""
    user = getattr(g, 'auth_user', {})
    return str(user.get('id', user.get('user_id', '')))


# ============================================
# DB QUERY HELPERS
# ============================================

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
# VALIDATION HELPERS
# ============================================

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


# ============================================
# TEACHER-STUDENT RELATIONSHIP HELPERS
# ============================================

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


# ============================================
# MULTI-PARTY HELPERS
# ============================================

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


# ============================================
# CONSTANTS
# ============================================

MAX_TEXT = 10000  # max characters for text fields

# --- Multi-party constants ---
PARTICIPANT_ROLES = ('organizer', 'specialist', 'observer', 'patient')
SPECIALTIES = ('speech_therapist', 'neurologist', 'social_worker', 'psychologist',
               'doctor', 'nurse', 'physiotherapist', 'occupational_therapist', 'other')
PARTICIPANT_STATUSES = ('invited', 'accepted', 'declined', 'joined', 'left')


# ============================================
# SCHEDULER HELPER — exported for app.py
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
