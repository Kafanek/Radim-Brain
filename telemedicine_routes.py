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
# SPRINT A+B — Consent + Patient-friendly summary
# ============================================

@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/consent', methods=['POST'])
@require_auth
def telemed_consent(consultation_id):
    """Patient records recording/processing consent before joining.

    Body: { consent: true, consent_version: "2.0", accepted_at: ISO8601 }
    Writes audit event + updates consent_version on consultation row.
    """
    user_id = _get_user_id()
    data = request.get_json() or {}
    consent = bool(data.get('consent', False))
    version = str(data.get('consent_version') or '1.0')[:32]

    try:
        with db_context(commit=True) as db:
            # Participant-scoped: patient must own this consultation
            row = db.execute(
                "SELECT student_id, teacher_id FROM telemedicine_consultations WHERE id = ?",
                (consultation_id,)
            ).fetchone()
            if not row:
                return jsonify({'success': False, 'error': 'Consultation not found'}), 404
            student_id = row[0] if isinstance(row, (list, tuple)) else row.get('student_id')
            if str(student_id) != str(user_id):
                # Allow participants too
                if not _is_participant(consultation_id, user_id):
                    return jsonify({'success': False, 'error': 'Forbidden'}), 403

            # Mark consent
            if consent:
                db.execute(
                    "UPDATE telemedicine_consultations SET consent_version = ? WHERE id = ?",
                    (version, consultation_id)
                )
            try:
                log_event(consultation_id=consultation_id,
                          event_type='consent_recorded' if consent else 'consent_declined',
                          actor_user_id=user_id,
                          reason=f'consent={consent} v{version}',
                          metadata={'consent': consent, 'version': version})
            except Exception:
                pass

        return jsonify({'success': True, 'consent': consent, 'version': version})
    except Exception as e:
        logger.error(f"consent error: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@telemedicine_bp.route('/api/telemedicine/consultation/<int:consultation_id>/patient-summary', methods=['POST'])
@require_auth
def telemed_patient_summary(consultation_id):
    """Patient-friendly 3-step next-action summary for a completed consultation.

    Uses Gemini to translate complaint/findings/recommendations into
    3 simple steps a senior can follow. Falls back to rule-based if no key.
    """
    user_id = _get_user_id()

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT student_id, teacher_id, complaint, findings, recommendations, "
                "title, status, notes "
                "FROM telemedicine_consultations WHERE id = ?",
                (consultation_id,)
            ).fetchone()
    except Exception as e:
        logger.error(f"patient-summary DB error: {e}")
        return jsonify({'success': False, 'error': 'db_error'}), 500

    if not row:
        return jsonify({'success': False, 'error': 'Consultation not found'}), 404

    def _v(r, i, k):
        return r[i] if isinstance(r, (list, tuple)) else r.get(k)

    student_id = _v(row, 0, 'student_id')
    if str(student_id) != str(user_id) and not _is_participant(consultation_id, user_id):
        return jsonify({'success': False, 'error': 'Forbidden'}), 403

    complaint = _v(row, 2, 'complaint') or ''
    findings = _v(row, 3, 'findings') or ''
    recommendations = _v(row, 4, 'recommendations') or ''
    status = _v(row, 6, 'status') or ''

    if status not in ('completed', 'archived'):
        return jsonify({
            'success': True, 'summary': '',
            'hint': 'Shrnutí bude k dispozici až po dokončení konzultace.'
        })

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return jsonify({
            'success': True,
            'summary': _rule_based_patient_summary(complaint, findings, recommendations),
            'source': 'rule_based'
        })

    prompt = (
        "Jsi lékařský asistent. Přelož doporučení lékaře do 3 krátkých, jasných kroků "
        "v češtině, kterým snadno porozumí senior. Každý krok začíná slovesem. "
        "Pokud je něco nejasného, vynech. Maximálně 3 kroky. "
        "Neurčuj diagnózu ani nepřekračuj doporučení lékaře — jen je přepiš lidsky.\n\n"
        f"Co pacient hlásil: {complaint or '—'}\n"
        f"Co lékař zjistil: {findings or '—'}\n"
        f"Doporučení lékaře: {recommendations or '—'}\n\n"
        "Odpověz v tomto formátu (bez dalšího textu):\n"
        "1. [první krok]\n2. [druhý krok]\n3. [třetí krok]"
    )

    try:
        import requests as req
        resp = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 300},
            },
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            text = (data.get('candidates', [{}])[0]
                      .get('content', {})
                      .get('parts', [{}])[0]
                      .get('text', '')).strip()
            if text:
                return jsonify({'success': True, 'summary': text, 'source': 'gemini'})
    except Exception as e:
        logger.debug(f"gemini patient-summary error: {e}")

    return jsonify({
        'success': True,
        'summary': _rule_based_patient_summary(complaint, findings, recommendations),
        'source': 'rule_based_fallback'
    })


def _rule_based_patient_summary(complaint, findings, recommendations):
    """Deterministic Czech fallback summary."""
    steps = []
    if recommendations:
        # Split on sentence boundaries, take first 3
        import re as _re
        parts = _re.split(r'[.!?]\s+|\n+', recommendations.strip())
        for p in parts:
            p = p.strip()
            if p and len(p) > 3:
                steps.append(p)
            if len(steps) >= 3:
                break
    if not steps and findings:
        steps.append(f"Lékař zjistil: {findings.strip()[:100]}")
    if not steps:
        steps.append("Pokud se vaše obtíže zhorší, kontaktujte tým.")
    numbered = '\n'.join(f"{i+1}. {s}" for i, s in enumerate(steps[:3]))
    return numbered


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
