# ============================================
# TELEMEDICINE MULTI-PARTY ROUTES
# Team consultations: create, participants CRUD, notes, all-notes
# Extracted from telemedicine_routes.py for modularity
# ============================================

import json
import os
from flask import Blueprint, request, jsonify
from database import get_connection, is_postgres
from auth_middleware import require_auth, require_teacher
from utils import now_iso
from telemedicine_helpers import (
    _p, _get_user_id, _get_teacher_id_local,
    _get_consultation, _is_participant, _notify_user, _notify_all_participants,
    _validate_date, _validate_time, _verify_teacher_student_local,
    MAX_TEXT, SPECIALTIES
)

telemedicine_multiparty_bp = Blueprint('telemedicine_multiparty', __name__)


# ============================================
# MULTI-PARTY ENDPOINTS — Team Consultations
# ============================================

@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/multiparty', methods=['POST'])
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
        "timestamp": now_iso()
    }), 201


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants', methods=['POST'])
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

    return jsonify({"success": True, "participant_id": pid, "message": "Odbornik pozvan", "timestamp": now_iso()}), 201


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants', methods=['GET'])
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
        "timestamp": now_iso()
    })


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/respond', methods=['PUT'])
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

    return jsonify({"success": True, "status": response, "message": f"Pozvanka {response}", "timestamp": now_iso()})


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/notes', methods=['PUT'])
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

    return jsonify({"success": True, "message": "Poznamky ulozeny", "timestamp": now_iso()})


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/all-notes', methods=['GET'])
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
        "timestamp": now_iso()
    })


@telemedicine_multiparty_bp.route('/api/telemedicine/consultation/<int:consultation_id>/participants/<participant_user_id>', methods=['DELETE'])
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
        'consultation_id': consultation_id, 'cancelled_by': 'organizer', 'reason': 'Odebr\u00e1n z konzultace'
    })

    return jsonify({"success": True, "message": "Ucastnik odstranen", "timestamp": now_iso()})
