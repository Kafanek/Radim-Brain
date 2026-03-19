# ============================================
# TELEMEDICINE AUDIT & POLICY v4.1
# Audit logging, ABAC policy matrix, quality metrics, join tokens
# ============================================

import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from flask import request, g
from database import db_context, db_insert

logger = logging.getLogger(__name__)


# ============================================
# AUDIT EVENT LOGGING (Point 2)
# ============================================

# All auditable event types
EVENT_TYPES = (
    'consultation_requested', 'consultation_confirmed', 'consultation_started',
    'consultation_completed', 'consultation_cancelled', 'consultation_archived',
    'notes_written', 'notes_viewed', 'clinical_notes_locked',
    'participant_invited', 'participant_accepted', 'participant_declined',
    'participant_removed', 'participant_joined', 'participant_left',
    'join_token_generated', 'join_url_accessed',
    'summary_emailed', 'summary_viewed',
    'availability_set', 'availability_removed',
)


def log_event(consultation_id, event_type, actor_user_id,
              old_status=None, new_status=None, reason=None,
              metadata=None, actor_auth_role=None, actor_consultation_role=None):
    """Record an auditable event in telemedicine_events.

    Non-fatal: never raises, never blocks the caller.
    """
    try:
        ip = _get_client_ip()
        if not actor_auth_role:
            actor_auth_role = _get_auth_role()
        meta_json = json.dumps(metadata or {})

        with db_context(commit=True) as db:
            db_insert(db, 'telemedicine_events',
                ['consultation_id', 'event_type', 'old_status', 'new_status',
                 'actor_user_id', 'actor_auth_role', 'actor_consultation_role',
                 'reason', 'metadata', 'ip_address'],
                (consultation_id, event_type, old_status, new_status,
                 actor_user_id, actor_auth_role, actor_consultation_role,
                 reason, meta_json, ip)
            )
    except Exception as e:
        logger.warning(f"audit log_event failed: {e}")


def get_audit_trail(consultation_id, limit=100):
    """Return full audit trail for a consultation."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, event_type, old_status, new_status, actor_user_id, "
                "actor_auth_role, actor_consultation_role, reason, metadata, ip_address, created_at "
                "FROM telemedicine_events WHERE consultation_id = ? "
                "ORDER BY created_at ASC LIMIT ?",
                (consultation_id, limit)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get('created_at') and hasattr(d['created_at'], 'isoformat'):
                    d['created_at'] = d['created_at'].isoformat()
                if isinstance(d.get('metadata'), str):
                    try:
                        d['metadata'] = json.loads(d['metadata'])
                    except Exception:
                        pass
                result.append(d)
            return result
    except Exception as e:
        logger.error(f"get_audit_trail failed: {e}")
        return []


# ============================================
# ABAC POLICY MATRIX (Point 3)
# ============================================

# consultation_role → permissions
# Permissions: view_clinical, edit_own_notes, edit_summary, view_internal,
#              start_session, end_session, invite_participants, remove_participants
POLICY_MATRIX = {
    'organizer': {
        'view_clinical': True,
        'edit_own_notes': True,
        'edit_summary': True,
        'view_internal': True,
        'start_session': True,
        'end_session': True,
        'invite_participants': True,
        'remove_participants': True,
        'view_audit_trail': True,
        'send_summary_email': True,
        'lock_clinical_notes': True,
    },
    'therapist': {
        'view_clinical': True,
        'edit_own_notes': True,
        'edit_summary': True,
        'view_internal': True,
        'start_session': True,
        'end_session': True,
        'invite_participants': False,
        'remove_participants': False,
        'view_audit_trail': True,
        'send_summary_email': True,
        'lock_clinical_notes': True,
    },
    'specialist': {
        'view_clinical': True,
        'edit_own_notes': True,
        'edit_summary': False,
        'view_internal': True,
        'start_session': False,
        'end_session': False,
        'invite_participants': False,
        'remove_participants': False,
        'view_audit_trail': False,
        'send_summary_email': False,
        'lock_clinical_notes': False,
    },
    'observer': {
        'view_clinical': False,
        'edit_own_notes': False,
        'edit_summary': False,
        'view_internal': False,
        'start_session': False,
        'end_session': False,
        'invite_participants': False,
        'remove_participants': False,
        'view_audit_trail': False,
        'send_summary_email': False,
        'lock_clinical_notes': False,
    },
    'patient': {
        'view_clinical': False,       # sees only patient-facing summary
        'edit_own_notes': False,
        'edit_summary': False,
        'view_internal': False,
        'start_session': False,
        'end_session': False,
        'invite_participants': False,
        'remove_participants': False,
        'view_audit_trail': False,
        'send_summary_email': False,
        'lock_clinical_notes': False,
    },
    'caregiver_proxy': {
        'view_clinical': False,       # sees patient-facing only, like patient
        'edit_own_notes': False,
        'edit_summary': False,
        'view_internal': False,
        'start_session': False,
        'end_session': False,
        'invite_participants': False,
        'remove_participants': False,
        'view_audit_trail': False,
        'send_summary_email': False,
        'lock_clinical_notes': False,
    },
}

VALID_CONSULTATION_ROLES = tuple(POLICY_MATRIX.keys())


def check_permission(user_id, consultation_id, permission):
    """ABAC check: does user have this permission on this consultation?

    Resolves consultation_role from:
    1. telemedicine_participants table
    2. teacher_id match → organizer/therapist
    3. student_id match → patient

    Returns (allowed: bool, consultation_role: str|None)
    """
    try:
        with db_context() as db:
            # Check consultation exists
            consult = db.execute(
                "SELECT teacher_id, student_id, status, clinical_notes_locked FROM telemedicine_consultations WHERE id = ?",
                (consultation_id,)
            ).fetchone()
            if not consult:
                return False, None

            # Determine consultation role
            role = _resolve_consultation_role(db, user_id, consultation_id, consult)
            if not role:
                return False, None

            # Check policy matrix
            perms = POLICY_MATRIX.get(role, {})
            allowed = perms.get(permission, False)

            return allowed, role
    except Exception as e:
        logger.error(f"check_permission failed: {e}")
        return False, None


def _resolve_consultation_role(db, user_id, consultation_id, consult):
    """Resolve user's role in a specific consultation."""
    # Check participants table first (explicit role assignment)
    part = db.execute(
        "SELECT role, status FROM telemedicine_participants "
        "WHERE consultation_id = ? AND user_id = ? AND status IN ('accepted', 'joined')",
        (consultation_id, user_id)
    ).fetchone()

    if part:
        return part['role']

    # Fallback: check if teacher or student
    if user_id == str(consult['teacher_id']):
        return 'organizer'
    if user_id == str(consult['student_id']):
        return 'patient'

    return None


def get_user_consultation_role(user_id, consultation_id):
    """Public helper: get user's consultation role."""
    try:
        with db_context() as db:
            consult = db.execute(
                "SELECT teacher_id, student_id FROM telemedicine_consultations WHERE id = ?",
                (consultation_id,)
            ).fetchone()
            if not consult:
                return None
            return _resolve_consultation_role(db, user_id, consultation_id, consult)
    except Exception:
        return None


# ============================================
# JOIN TOKEN SYSTEM (Point 4)
# ============================================

JOIN_TOKEN_TTL_MINUTES = 30  # token valid for 30 min


def generate_join_token(consultation_id, user_id):
    """Generate a short-lived join token for a participant.

    Returns token string or None on failure.
    """
    try:
        token = secrets.token_urlsafe(32)
        expires = datetime.now() + timedelta(minutes=JOIN_TOKEN_TTL_MINUTES)

        with db_context(commit=True) as db:
            # Update or insert participant token
            row = db.execute(
                "SELECT id FROM telemedicine_participants WHERE consultation_id = ? AND user_id = ?",
                (consultation_id, user_id)
            ).fetchone()

            if row:
                db.execute(
                    "UPDATE telemedicine_participants SET join_token = ?, join_token_expires = ? WHERE id = ?",
                    (token, expires, row['id'])
                )
            else:
                # For teacher/student who may not be in participants table
                db.execute(
                    "INSERT INTO telemedicine_participants (consultation_id, user_id, role, status, join_token, join_token_expires) "
                    "VALUES (?, ?, 'organizer', 'accepted', ?, ?)",
                    (consultation_id, user_id, token, expires)
                )

        log_event(consultation_id, 'join_token_generated', user_id)
        return token
    except Exception as e:
        logger.error(f"generate_join_token failed: {e}")
        return None


def validate_join_token(consultation_id, token):
    """Validate a join token. Returns user_id if valid, None otherwise."""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT user_id, join_token_expires FROM telemedicine_participants "
                "WHERE consultation_id = ? AND join_token = ?",
                (consultation_id, token)
            ).fetchone()

            if not row:
                return None

            expires = row['join_token_expires']
            if expires:
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                if expires < datetime.now():
                    return None  # expired

            return row['user_id']
    except Exception as e:
        logger.error(f"validate_join_token failed: {e}")
        return None


def check_join_eligibility(consultation_id, user_id):
    """Full join eligibility check (Point 4):
    1. Is user a participant?
    2. Is consultation in correct state?
    3. Is it within time window?
    4. Is participation not revoked?

    Returns (eligible: bool, reason: str)
    """
    try:
        with db_context() as db:
            consult = db.execute(
                "SELECT status, scheduled_date, scheduled_time, duration_minutes, teacher_id, student_id "
                "FROM telemedicine_consultations WHERE id = ?",
                (consultation_id,)
            ).fetchone()

            if not consult:
                return False, "Konzultace nenalezena"

            # 1. Status check
            if consult['status'] != 'in_progress':
                return False, f"Konzultace neni aktivni (stav: {consult['status']})"

            # 2. Participant check
            role = _resolve_consultation_role(db, user_id, consultation_id, consult)
            if not role:
                return False, "Nejste ucastnikem teto konzultace"

            # 3. Check if participant was removed/declined
            part = db.execute(
                "SELECT status FROM telemedicine_participants "
                "WHERE consultation_id = ? AND user_id = ?",
                (consultation_id, user_id)
            ).fetchone()
            if part and part['status'] in ('declined', 'left'):
                return False, "Vase ucast byla zrusena"

            # 4. Time window check (allow 15 min before to 2h after scheduled start)
            try:
                sched_date = consult['scheduled_date']
                sched_time = consult['scheduled_time']
                if isinstance(sched_date, str):
                    sched_date_str = sched_date
                else:
                    sched_date_str = sched_date.isoformat()
                if isinstance(sched_time, str):
                    sched_time_str = sched_time
                else:
                    sched_time_str = sched_time.isoformat()

                sched_dt = datetime.fromisoformat(f"{sched_date_str}T{sched_time_str}")
                duration = consult['duration_minutes'] or 30
                now = datetime.now()

                window_start = sched_dt - timedelta(minutes=15)
                window_end = sched_dt + timedelta(minutes=duration + 90)

                if now < window_start:
                    return False, f"Konzultace jeste nezacala (planovany cas: {sched_time_str})"
                if now > window_end:
                    return False, "Casove okno pro pripojeni vyprselo"
            except Exception:
                pass  # If time parsing fails, allow join (don't block on data format issues)

            return True, "OK"
    except Exception as e:
        logger.error(f"check_join_eligibility failed: {e}")
        return False, f"Chyba: {e}"


# ============================================
# AVAILABILITY CONFLICT DETECTION (Point 5)
# ============================================

def check_availability_conflict(teacher_id, scheduled_date, scheduled_time, duration_minutes=30, exclude_id=None):
    """Check if a new consultation would conflict with existing ones or availability buffers.

    Returns (has_conflict: bool, conflicts: list[dict])
    """
    try:
        with db_context() as db:
            # Parse target time
            if isinstance(scheduled_time, str):
                target_start = datetime.strptime(scheduled_time, '%H:%M')
            else:
                target_start = datetime.combine(datetime.today(), scheduled_time)

            target_end = target_start + timedelta(minutes=duration_minutes)

            # Find existing consultations on same day
            conditions = [
                "teacher_id = ?", "scheduled_date = ?",
                "status IN ('requested', 'confirmed', 'in_progress')"
            ]
            params = [teacher_id, scheduled_date]

            if exclude_id:
                conditions.append("id != ?")
                params.append(exclude_id)

            rows = db.execute(
                f"SELECT id, scheduled_time, duration_minutes, status "
                f"FROM telemedicine_consultations WHERE {' AND '.join(conditions)}",
                tuple(params)
            ).fetchall()

            conflicts = []
            for r in rows:
                existing_time = r['scheduled_time']
                if isinstance(existing_time, str):
                    existing_start = datetime.strptime(existing_time[:5], '%H:%M')
                else:
                    existing_start = datetime.combine(datetime.today(), existing_time)

                existing_dur = r['duration_minutes'] or 30

                # Get buffer from availability settings
                buffer_before, buffer_after = _get_buffers(db, teacher_id)
                existing_end = existing_start + timedelta(minutes=existing_dur)

                # Add buffers
                block_start = existing_start - timedelta(minutes=buffer_before)
                block_end = existing_end + timedelta(minutes=buffer_after)

                # Check overlap
                if target_start.time() < block_end.time() and target_end.time() > block_start.time():
                    conflicts.append({
                        'consultation_id': r['id'],
                        'time': existing_time if isinstance(existing_time, str) else existing_time.isoformat(),
                        'duration': existing_dur,
                        'status': r['status'],
                        'buffer_before': buffer_before,
                        'buffer_after': buffer_after,
                    })

            return len(conflicts) > 0, conflicts
    except Exception as e:
        logger.error(f"check_availability_conflict failed: {e}")
        return False, []


def _get_buffers(db, teacher_id):
    """Get buffer settings for a teacher from availability table."""
    try:
        row = db.execute(
            "SELECT buffer_before_min, buffer_after_min FROM telemedicine_availability "
            "WHERE teacher_id = ? AND is_active = 1 LIMIT 1",
            (teacher_id,)
        ).fetchone()
        if row:
            return (row['buffer_before_min'] or 5), (row['buffer_after_min'] or 5)
    except Exception:
        pass
    return 5, 5  # default 5 min buffers


# ============================================
# QUALITY METRICS (Point 7)
# ============================================

def log_quality_metric(consultation_id, metric_type, metric_value, details=None):
    """Record a quality metric."""
    try:
        with db_context(commit=True) as db:
            db_insert(db, 'telemedicine_quality_log',
                ['consultation_id', 'metric_type', 'metric_value', 'details'],
                (consultation_id, metric_type, metric_value, json.dumps(details or {}))
            )
    except Exception as e:
        logger.warning(f"log_quality_metric failed: {e}")


def compute_quality_kpis(days=30):
    """Compute telemedicine KPIs for the last N days (Point 7).

    Returns dict with all 10 WHO-aligned metrics.
    """
    try:
        with db_context() as db:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            # Total consultations in period
            total = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations WHERE created_at >= ?",
                (cutoff,)
            ).fetchone()['cnt']

            if total == 0:
                return {'period_days': days, 'total_consultations': 0, 'message': 'Zadne konzultace v obdobi'}

            # 1. No-show rate
            noshow = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations "
                "WHERE created_at >= ? AND status = 'confirmed' AND scheduled_date < CURRENT_DATE",
                (cutoff,)
            ).fetchone()['cnt']

            # 2. Cancellation rate by reason
            cancelled = db.execute(
                "SELECT COUNT(*) as cnt, cancel_reason FROM telemedicine_consultations "
                "WHERE created_at >= ? AND status = 'cancelled' GROUP BY cancel_reason",
                (cutoff,)
            ).fetchall()
            cancel_total = sum(r['cnt'] for r in cancelled)
            cancel_reasons = {(r['cancel_reason'] or 'no_reason'): r['cnt'] for r in cancelled}

            # 3. Median time request → confirm (via audit events)
            confirm_times = db.execute(
                "SELECT e2.created_at as confirmed_at, e1.created_at as requested_at "
                "FROM telemedicine_events e1 "
                "JOIN telemedicine_events e2 ON e1.consultation_id = e2.consultation_id "
                "WHERE e1.event_type = 'consultation_requested' AND e2.event_type = 'consultation_confirmed' "
                "AND e1.created_at >= ?",
                (cutoff,)
            ).fetchall()

            # 4. Completed consultations
            completed = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations "
                "WHERE created_at >= ? AND status = 'completed'",
                (cutoff,)
            ).fetchone()['cnt']

            # 5. Average duration
            avg_duration = db.execute(
                "SELECT AVG(duration_minutes) as avg_dur FROM telemedicine_consultations "
                "WHERE created_at >= ? AND status = 'completed'",
                (cutoff,)
            ).fetchone()

            # 6. Email summary sent rate
            emails_sent = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations "
                "WHERE created_at >= ? AND email_sent = 1",
                (cutoff,)
            ).fetchone()['cnt']

            # 7. Multiparty rate
            multiparty = db.execute(
                "SELECT COUNT(*) as cnt FROM telemedicine_consultations "
                "WHERE created_at >= ? AND is_multiparty = 1",
                (cutoff,)
            ).fetchone()['cnt']

            return {
                'period_days': days,
                'total_consultations': total,
                'completed': completed,
                'completion_rate': round(completed / total * 100, 1) if total else 0,
                'noshow_count': noshow,
                'noshow_rate': round(noshow / total * 100, 1) if total else 0,
                'cancelled_total': cancel_total,
                'cancellation_rate': round(cancel_total / total * 100, 1) if total else 0,
                'cancel_reasons': cancel_reasons,
                'avg_duration_min': round(avg_duration['avg_dur'] or 0, 1) if avg_duration else 0,
                'email_summaries_sent': emails_sent,
                'summary_send_rate': round(emails_sent / max(completed, 1) * 100, 1),
                'multiparty_count': multiparty,
                'multiparty_rate': round(multiparty / total * 100, 1) if total else 0,
                'confirm_response_samples': len(confirm_times),
            }
    except Exception as e:
        logger.error(f"compute_quality_kpis failed: {e}")
        return {'error': str(e)}


# ============================================
# INTERNAL HELPERS
# ============================================

def _get_client_ip():
    """Get client IP from request, handling proxies."""
    try:
        return request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    except Exception:
        return 'unknown'


def _get_auth_role():
    """Get JWT auth role from Flask g."""
    try:
        user = getattr(g, 'auth_user', {})
        return user.get('role', user.get('auth_role', 'unknown'))
    except Exception:
        return 'unknown'
