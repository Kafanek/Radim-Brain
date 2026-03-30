"""
🏥 FHIR ADAPTER v1.0 — HL7 FHIR R4 data mapping
==================================================
Maps RadimCare internal data to FHIR R4 resources.
NOT a full FHIR server — an adapter for export/import.

Supports:
    Patient, Practitioner, Observation, MedicationStatement,
    CarePlan, CareTeam, Condition

Endpoints:
    GET /api/fhir/Patient/<senior_id>
    GET /api/fhir/Observation/<senior_id>?days=7
    GET /api/fhir/CarePlan/<senior_id>
    GET /api/fhir/CareTeam/<senior_id>
    GET /api/fhir/Bundle/<senior_id>  — complete export
"""

import logging
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

from auth_middleware import optional_auth
from database import db_context

logger = logging.getLogger(__name__)

fhir_bp = Blueprint('fhir', __name__)

FHIR_VERSION = 'R4'
SYSTEM_URL = 'https://radimcare.cz/fhir'


def _fhir_patient(senior_id, profile=None):
    """Map senior profile → FHIR Patient resource."""
    if not profile:
        try:
            from memory_helpers import db_load_profile
            profile = db_load_profile(senior_id)
        except Exception:
            profile = {}

    personal = profile.get('personal', {})
    name = profile.get('name', 'Unknown')
    parts = name.split(' ', 1)

    return {
        'resourceType': 'Patient',
        'id': str(senior_id),
        'meta': {'profile': [f'{SYSTEM_URL}/StructureDefinition/RadimPatient']},
        'identifier': [{'system': SYSTEM_URL, 'value': str(senior_id)}],
        'name': [{'family': parts[1] if len(parts) > 1 else '', 'given': [parts[0]]}],
        'communication': [{'language': {'coding': [{'system': 'urn:ietf:bcp:47', 'code': 'cs'}]}}],
        'extension': [
            {'url': f'{SYSTEM_URL}/age-group', 'valueString': profile.get('age_group', '')},
            {'url': f'{SYSTEM_URL}/hearing', 'valueString': profile.get('hearing', 'normal')},
            {'url': f'{SYSTEM_URL}/mobility', 'valueString': profile.get('mobility', 'normal')},
            {'url': f'{SYSTEM_URL}/memory-support', 'valueBoolean': profile.get('memory_support', False)},
        ],
    }


def _fhir_observation(senior_id, brain_state):
    """Map brain_state → FHIR Observation."""
    return {
        'resourceType': 'Observation',
        'status': 'final',
        'category': [{'coding': [{'system': 'http://terminology.hl7.org/CodeSystem/observation-category',
                                   'code': 'survey', 'display': 'Survey'}]}],
        'code': {'coding': [{'system': SYSTEM_URL, 'code': 'brain-state', 'display': 'RadimCare Brain State'}]},
        'subject': {'reference': f'Patient/{senior_id}'},
        'effectiveDateTime': str(brain_state.get('created_at', '')),
        'component': [
            {'code': {'text': 'Consciousness (C)'}, 'valueQuantity': {'value': brain_state.get('c', 0), 'unit': 'score'}},
            {'code': {'text': 'Empathy (E)'}, 'valueQuantity': {'value': brain_state.get('e', 0), 'unit': 'ratio'}},
            {'code': {'text': 'Rationality (R)'}, 'valueQuantity': {'value': brain_state.get('r', 0), 'unit': 'ratio'}},
            {'code': {'text': 'Stress (S)'}, 'valueQuantity': {'value': brain_state.get('s', 0), 'unit': 'ratio'}},
            {'code': {'text': 'Mode'}, 'valueString': brain_state.get('mode', 'HARMONY')},
            {'code': {'text': 'Coherence'}, 'valueQuantity': {'value': brain_state.get('coherence', 0), 'unit': 'ratio'}},
        ],
    }


def _fhir_medication(med):
    """Map medication → FHIR MedicationStatement."""
    return {
        'resourceType': 'MedicationStatement',
        'status': 'active',
        'medicationCodeableConcept': {'text': med.get('name', '')},
        'dosage': [{'text': med.get('dose', ''), 'timing': {'code': {'text': med.get('time', '')}}}],
    }


def _fhir_care_plan(senior_id, plan):
    """Map care_plan → FHIR CarePlan."""
    activities = []
    for goal in plan.get('goals', []):
        activities.append({
            'detail': {
                'description': goal.get('text', ''),
                'status': 'in-progress' if goal.get('status') == 'active' else 'completed',
            }
        })
    return {
        'resourceType': 'CarePlan',
        'status': 'active',
        'intent': 'plan',
        'subject': {'reference': f'Patient/{senior_id}'},
        'activity': activities,
        'note': [{'text': plan.get('notes', '')}],
    }


def _fhir_care_team(senior_id, members):
    """Map medical_team → FHIR CareTeam."""
    participants = []
    role_map = {
        'coordinator': 'Care coordinator',
        'general_practitioner': 'General practitioner',
        'cardiologist': 'Cardiologist',
        'dermatologist': 'Dermatologist',
        'vascular': 'Vascular specialist',
        'caregiver': 'Caregiver',
    }
    for m in members:
        participants.append({
            'role': [{'text': role_map.get(m.get('role', ''), m.get('role', ''))}],
            'member': {'display': m.get('name', ''), 'reference': f'Practitioner/{m.get("user_id", "")}'},
        })
    return {
        'resourceType': 'CareTeam',
        'status': 'active',
        'subject': {'reference': f'Patient/{senior_id}'},
        'participant': participants,
    }


def _fhir_condition(topic_name, topic_info):
    """Map health_topic → FHIR Condition."""
    return {
        'resourceType': 'Condition',
        'clinicalStatus': {'coding': [{'code': 'active'}]},
        'code': {'text': topic_name},
        'note': [{'text': f'First reported: {topic_info.get("first_seen", "")}, '
                          f'mentions: {topic_info.get("count", 0)}'}],
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@fhir_bp.route('/api/fhir/Patient/<senior_id>', methods=['GET'])
@optional_auth
def fhir_patient(senior_id):
    return jsonify(_fhir_patient(senior_id))


@fhir_bp.route('/api/fhir/Observation/<senior_id>', methods=['GET'])
@optional_auth
def fhir_observations(senior_id):
    days = request.args.get('days', 7, type=int)
    observations = []
    try:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT c, e, r, s, mode, coherence, created_at FROM brain_states "
                "WHERE user_id = ? AND created_at > ? ORDER BY created_at DESC LIMIT 100",
                (senior_id, since)
            ).fetchall()
        for row in rows:
            observations.append(_fhir_observation(senior_id, {
                'c': row[0], 'e': row[1], 'r': row[2], 's': row[3],
                'mode': row[4], 'coherence': row[5], 'created_at': str(row[6]),
            }))
    except Exception as e:
        logger.debug(f"FHIR observations: {e}")

    return jsonify({
        'resourceType': 'Bundle', 'type': 'searchset',
        'total': len(observations), 'entry': [{'resource': o} for o in observations],
    })


@fhir_bp.route('/api/fhir/CarePlan/<senior_id>', methods=['GET'])
@optional_auth
def fhir_care_plan(senior_id):
    try:
        from care_plan import _get_plan
        plan = _get_plan(senior_id)
        return jsonify(_fhir_care_plan(senior_id, plan))
    except Exception:
        return jsonify({'resourceType': 'CarePlan', 'status': 'draft', 'activity': []})


@fhir_bp.route('/api/fhir/CareTeam/<senior_id>', methods=['GET'])
@optional_auth
def fhir_care_team(senior_id):
    members = []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, name, role FROM medical_team WHERE senior_id = ? AND active = true",
                (senior_id,)
            ).fetchall()
        members = [{'user_id': r[0], 'name': r[1], 'role': r[2]} for r in rows]
    except Exception:
        pass
    return jsonify(_fhir_care_team(senior_id, members))


@fhir_bp.route('/api/fhir/Bundle/<senior_id>', methods=['GET'])
@optional_auth
def fhir_bundle(senior_id):
    """Complete FHIR Bundle — all resources for one senior."""
    entries = []

    # Patient
    entries.append({'resource': _fhir_patient(senior_id)})

    # Observations (last 7 days)
    try:
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT c, e, r, s, mode, coherence, created_at FROM brain_states "
                "WHERE user_id = ? AND created_at > ? ORDER BY created_at DESC LIMIT 50",
                (senior_id, since)
            ).fetchall()
        for row in rows:
            entries.append({'resource': _fhir_observation(senior_id, {
                'c': row[0], 'e': row[1], 'r': row[2], 's': row[3],
                'mode': row[4], 'coherence': row[5], 'created_at': str(row[6]),
            })})
    except Exception:
        pass

    # CarePlan
    try:
        from care_plan import _get_plan
        plan = _get_plan(senior_id)
        entries.append({'resource': _fhir_care_plan(senior_id, plan)})
        # Medications
        for med in plan.get('medications', []):
            entries.append({'resource': _fhir_medication(med)})
    except Exception:
        pass

    # CareTeam
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, name, role FROM medical_team WHERE senior_id = ? AND active = true",
                (senior_id,)
            ).fetchall()
        members = [{'user_id': r[0], 'name': r[1], 'role': r[2]} for r in rows]
        entries.append({'resource': _fhir_care_team(senior_id, members)})
    except Exception:
        pass

    # Health conditions
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(senior_id)
        for name, info in learning.get('health_topics', {}).items():
            entries.append({'resource': _fhir_condition(name, info)})
    except Exception:
        pass

    return jsonify({
        'resourceType': 'Bundle',
        'type': 'collection',
        'meta': {'lastUpdated': datetime.utcnow().isoformat() + 'Z'},
        'total': len(entries),
        'entry': entries,
    })


logger.info("🏥 FHIR Adapter v1.0 loaded — HL7 FHIR R4 export")
