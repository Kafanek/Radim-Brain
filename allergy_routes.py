"""
🩹 ALLERGY + WEIGHT ROUTES (v467)
==================================

Stores user's allergies + weight in memory_profiles JSONB and exposes
combined safety checks (meds × meds + meds × allergies).

Endpoints:
  GET    /api/allergy?user_id=X              → list user's allergies
  POST   /api/allergy?user_id=X              → add {substance, severity, notes}
  DELETE /api/allergy/<substance>?user_id=X  → remove one
  DELETE /api/allergy?user_id=X              → clear all

  GET    /api/profile/weight?user_id=X       → current weight + history
  POST   /api/profile/weight?user_id=X       → record new {kg}
  DELETE /api/profile/weight?user_id=X       → clear weight

  GET    /api/medication/safety-check?user_id=X
                                              → combined warnings
                                                (interactions + allergy clashes)

Auth: same pattern as voice_lexicon — accepts user_id query param OR
takes from JWT g.auth_user. Simple for now; lock down later if needed.
"""

import logging
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g

logger = logging.getLogger(__name__)

allergy_bp = Blueprint('allergy', __name__)

MAX_ALLERGIES = 30
MAX_WEIGHT_HISTORY = 50
ALLOWED_SEVERITIES = {'severe', 'moderate', 'mild'}


def _resolve_user_id():
    uid = (request.args.get('user_id') or '').strip()
    if uid:
        return uid
    try:
        u = (getattr(g, 'auth_user', None) or {})
        u_id = u.get('id') or u.get('user_id') or u.get('sub')
        return str(u_id) if u_id is not None else ''
    except Exception:
        return ''


def _load(uid):
    from memory_helpers import db_load_profile
    return db_load_profile(uid) or {}


def _save(uid, profile):
    from memory_helpers import db_save_profile
    db_save_profile(uid, profile)


# ─────────────────────────────────────────────────────────────────
# ALLERGY CRUD
# ─────────────────────────────────────────────────────────────────
@allergy_bp.route('/api/allergy', methods=['GET'])
def list_allergies():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        profile = _load(uid)
        allergies = profile.get('allergies') or []
        if not isinstance(allergies, list):
            allergies = []
        return jsonify({
            'success': True,
            'user_id': uid,
            'count': len(allergies),
            'allergies': allergies,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@allergy_bp.route('/api/allergy', methods=['POST'])
def add_allergy():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    data = request.get_json(silent=True) or {}
    substance = (data.get('substance') or data.get('name') or '').strip()
    severity = (data.get('severity') or 'moderate').lower().strip()
    notes = (data.get('notes') or '').strip()

    if not substance:
        return jsonify({'success': False, 'error': 'substance required'}), 400
    if len(substance) > 100:
        return jsonify({'success': False, 'error': 'substance too long'}), 400
    if severity not in ALLOWED_SEVERITIES:
        severity = 'moderate'
    if len(notes) > 300:
        notes = notes[:300]

    try:
        from allergy_db import normalize_allergy
        normalized = normalize_allergy(substance)

        profile = _load(uid)
        allergies = profile.get('allergies') or []
        if not isinstance(allergies, list):
            allergies = []

        # Replace if same substance (case-insensitive) already present
        substance_low = substance.lower()
        allergies = [a for a in allergies
                     if isinstance(a, dict)
                     and (a.get('substance', '').lower() != substance_low)]

        if len(allergies) >= MAX_ALLERGIES:
            return jsonify({
                'success': False,
                'error': f'lze uložit maximálně {MAX_ALLERGIES} alergií, nejdřív některou smažte',
            }), 409

        entry = {
            'substance': substance,
            'normalized_class': normalized,  # may be None for free-text
            'severity': severity,
            'notes': notes,
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        }
        allergies.append(entry)
        profile['allergies'] = allergies
        _save(uid, profile)

        logger.info(f"allergy added: user={uid} substance='{substance}' severity={severity} normalized={normalized}")
        return jsonify({
            'success': True,
            'entry': entry,
            'count': len(allergies),
            'recognized': normalized is not None,
        })
    except Exception as e:
        logger.warning(f"add_allergy failed for {uid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@allergy_bp.route('/api/allergy/<path:substance>', methods=['DELETE'])
def delete_allergy(substance):
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    substance = (substance or '').strip().lower()
    try:
        profile = _load(uid)
        allergies = profile.get('allergies') or []
        if not isinstance(allergies, list):
            allergies = []
        before = len(allergies)
        allergies = [a for a in allergies
                     if isinstance(a, dict)
                     and (a.get('substance', '').lower() != substance)]
        if len(allergies) == before:
            return jsonify({'success': False, 'error': 'not found'}), 404
        profile['allergies'] = allergies
        _save(uid, profile)
        logger.info(f"allergy removed: user={uid} substance={substance}")
        return jsonify({'success': True, 'count': len(allergies)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@allergy_bp.route('/api/allergy', methods=['DELETE'])
def clear_allergies():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        profile = _load(uid)
        before = len(profile.get('allergies') or [])
        profile['allergies'] = []
        _save(uid, profile)
        return jsonify({'success': True, 'removed': before, 'count': 0})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────
# WEIGHT TRACKING
# ─────────────────────────────────────────────────────────────────
@allergy_bp.route('/api/profile/weight', methods=['GET'])
def get_weight():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        profile = _load(uid)
        current = profile.get('weight_kg')
        history = profile.get('weight_history') or []
        if not isinstance(history, list):
            history = []
        return jsonify({
            'success': True,
            'user_id': uid,
            'weight_kg': current,
            'history': history[-MAX_WEIGHT_HISTORY:],
            'recorded_count': len(history),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@allergy_bp.route('/api/profile/weight', methods=['POST'])
def post_weight():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    data = request.get_json(silent=True) or {}
    try:
        kg = float(data.get('kg') or data.get('weight_kg') or 0)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'kg must be a number'}), 400

    if kg < 25 or kg > 250:
        return jsonify({'success': False, 'error': 'kg must be between 25 and 250'}), 400

    try:
        profile = _load(uid)
        history = profile.get('weight_history') or []
        if not isinstance(history, list):
            history = []
        history.append({
            'kg': round(kg, 1),
            'recorded_at': datetime.now(timezone.utc).isoformat(),
        })
        # Cap history to keep JSONB compact
        if len(history) > MAX_WEIGHT_HISTORY:
            history = history[-MAX_WEIGHT_HISTORY:]
        profile['weight_kg'] = round(kg, 1)
        profile['weight_history'] = history
        _save(uid, profile)
        logger.info(f"weight recorded: user={uid} kg={kg}")
        return jsonify({
            'success': True,
            'weight_kg': profile['weight_kg'],
            'recorded_count': len(history),
        })
    except Exception as e:
        logger.warning(f"post_weight failed for {uid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@allergy_bp.route('/api/profile/weight', methods=['DELETE'])
def clear_weight():
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400
    try:
        profile = _load(uid)
        profile.pop('weight_kg', None)
        profile['weight_history'] = []
        _save(uid, profile)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────
# COMBINED SAFETY CHECK — meds × meds + meds × allergies
# ─────────────────────────────────────────────────────────────────
@allergy_bp.route('/api/medication/safety-check', methods=['GET'])
def safety_check():
    """One-stop safety scan — returns ALL warnings (interactions + allergies)
    with severity counts. Designed for the medical-module dashboard banner."""
    uid = _resolve_user_id()
    if not uid:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    payload = {'success': True, 'user_id': uid}

    try:
        from drug_interactions import check_user_interactions
        interactions = check_user_interactions(uid) or []
    except Exception as e:
        logger.warning(f"interactions check error: {e}")
        interactions = []

    try:
        from allergy_db import check_user_allergies
        allergy_clashes = check_user_allergies(uid) or []
    except Exception as e:
        logger.warning(f"allergy check error: {e}")
        allergy_clashes = []

    # Severity counts
    severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0, 'severe': 0, 'moderate': 0, 'mild': 0}
    for w in interactions:
        s = w.get('severity', 'LOW')
        severity_counts[s] = severity_counts.get(s, 0) + 1
    for w in allergy_clashes:
        s = w.get('severity', 'moderate')
        severity_counts[s] = severity_counts.get(s, 0) + 1

    # Overall risk level — used for frontend banner colour
    overall = 'safe'
    if severity_counts['HIGH'] > 0 or severity_counts['severe'] > 0:
        overall = 'high'
    elif severity_counts['MEDIUM'] > 0 or severity_counts['moderate'] > 0:
        overall = 'medium'
    elif severity_counts['LOW'] > 0 or severity_counts['mild'] > 0:
        overall = 'low'

    payload['interactions'] = interactions
    payload['allergy_clashes'] = allergy_clashes
    payload['interactions_count'] = len(interactions)
    payload['allergy_clashes_count'] = len(allergy_clashes)
    payload['severity_counts'] = {k: v for k, v in severity_counts.items() if v > 0}
    payload['overall_risk'] = overall  # 'safe' | 'low' | 'medium' | 'high'
    payload['safe'] = overall == 'safe'

    return jsonify(payload)
