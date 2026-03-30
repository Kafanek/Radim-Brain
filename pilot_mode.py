"""
🧪 PILOT MODE v1.0 — Režim pro reálné nasazení
=================================================
Speciální mód pro pilotní provoz:
- Jednoduchý onboarding týmu
- Pozvánka lékaře
- Šablony diagnóz
- Testovací vs ostrá data
- Týdenní souhrn
- Export jedním klikem

Endpoints:
    POST /api/pilot/invite        — Pozvat lékaře do případu
    GET  /api/pilot/templates     — Šablony diagnóz
    POST /api/pilot/setup-senior  — Kompletní setup seniora
    GET  /api/pilot/weekly/<sid>  — Týdenní souhrn
    GET  /api/pilot/export/<sid>  — Export jedním klikem (JSON)
    GET  /api/pilot/status        — Stav pilotu
"""

import logging
import json
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g

from auth_middleware import optional_auth
from database import db_context

logger = logging.getLogger(__name__)

pilot_bp = Blueprint('pilot', __name__)

# ============================================================================
# DIAGNOSIS TEMPLATES — běžné diagnózy pro rychlý setup
# ============================================================================

DIAGNOSIS_TEMPLATES = {
    'hypertenze': {
        'name': 'Hypertenze (vysoký krevní tlak)',
        'goals': ['Udržet tlak pod 140/90', 'Pravidelný pohyb min. 30 min/den'],
        'metrics': [
            {'name': 'Krevní tlak', 'unit': 'mmHg', 'range': '<140/90', 'freq': '2x denně'},
            {'name': 'Tepová frekvence', 'unit': 'bpm', 'range': '60-90', 'freq': '1x denně'},
        ],
        'risks': ['Mozková příhoda', 'Srdeční selhání'],
        'team': ['general_practitioner', 'cardiologist'],
        'medications_example': ['Enalapril 10mg ráno', 'Hydrochlorothiazid 25mg ráno'],
    },
    'diabetes_2': {
        'name': 'Diabetes mellitus 2. typu',
        'goals': ['HbA1c pod 53 mmol/mol', 'BMI pod 30', 'Pravidelné měření glykémie'],
        'metrics': [
            {'name': 'Glykémie', 'unit': 'mmol/l', 'range': '4-7 nalačno', 'freq': '1x denně'},
            {'name': 'HbA1c', 'unit': 'mmol/mol', 'range': '<53', 'freq': '1x za 3 měsíce'},
            {'name': 'Hmotnost', 'unit': 'kg', 'range': 'dle BMI', 'freq': '1x týdně'},
        ],
        'risks': ['Hypoglykémie', 'Diabetická noha', 'Retinopatie'],
        'team': ['general_practitioner', 'diabetologist'],
        'medications_example': ['Metformin 500mg 2x denně'],
    },
    'demence_pocatecni': {
        'name': 'Počáteční demence',
        'goals': ['Zachovat orientaci', 'Bezpečný pohyb', 'Sociální stimulace'],
        'metrics': [
            {'name': 'Kognitivní skóre (C)', 'unit': 'score', 'range': '0-12', 'freq': 'průběžně'},
            {'name': 'Orientace v čase', 'unit': 'test', 'range': 'bez chyb', 'freq': '1x denně'},
            {'name': 'Sociální kontakt', 'unit': 'počet', 'range': '>1/den', 'freq': 'denně'},
        ],
        'risks': ['Bloudění', 'Pád', 'Zapomínání léků', 'Izolace'],
        'team': ['general_practitioner', 'neurologist', 'caregiver'],
        'medications_example': ['Donepezil 5mg večer'],
    },
    'po_operaci_kycle': {
        'name': 'Rehabilitace po operaci kyčle',
        'goals': ['Obnovit chůzi bez pomůcek', 'Snížit bolest pod 3/10'],
        'metrics': [
            {'name': 'Bolest (VAS)', 'unit': '0-10', 'range': '<3', 'freq': '2x denně'},
            {'name': 'Pohyblivost', 'unit': 'stupeň', 'range': '>90°', 'freq': '1x denně'},
            {'name': 'Chůze', 'unit': 'metry', 'range': '>100m', 'freq': '1x denně'},
        ],
        'risks': ['Pád', 'Trombóza', 'Infekce'],
        'team': ['general_practitioner', 'orthopedist', 'physiotherapist', 'caregiver'],
        'medications_example': ['Ibuprofen 400mg při bolesti', 'Heparin subkutánně 14 dní'],
    },
    'srdecni_selhani': {
        'name': 'Chronické srdeční selhání',
        'goals': ['Stabilní váha (±1kg)', 'Dušnost pod kontrolou', 'Omezení soli'],
        'metrics': [
            {'name': 'Hmotnost', 'unit': 'kg', 'range': '±1kg', 'freq': '1x denně'},
            {'name': 'Dušnost', 'unit': 'NYHA', 'range': 'I-II', 'freq': '1x denně'},
            {'name': 'Otoky', 'unit': 'stupeň', 'range': '0', 'freq': '1x denně'},
            {'name': 'SpO2', 'unit': '%', 'range': '>94', 'freq': '2x denně'},
        ],
        'risks': ['Akutní dekompenzace', 'Renální selhání', 'Arytmie'],
        'team': ['cardiologist', 'general_practitioner', 'caregiver'],
        'medications_example': ['Furosemid 40mg ráno', 'Ramipril 5mg ráno', 'Bisoprolol 2.5mg ráno'],
    },
}


# ============================================================================
# ENDPOINTS
# ============================================================================

@pilot_bp.route('/api/pilot/templates', methods=['GET'])
@optional_auth
def get_templates():
    """Get all diagnosis templates."""
    templates = []
    for key, t in DIAGNOSIS_TEMPLATES.items():
        templates.append({
            'id': key,
            'name': t['name'],
            'goals': len(t['goals']),
            'metrics': len(t['metrics']),
            'risks': len(t['risks']),
            'team': t['team'],
        })
    return jsonify({'success': True, 'templates': templates, 'count': len(templates)})


@pilot_bp.route('/api/pilot/templates/<template_id>', methods=['GET'])
@optional_auth
def get_template_detail(template_id):
    """Get template detail."""
    t = DIAGNOSIS_TEMPLATES.get(template_id)
    if not t:
        return jsonify({'success': False, 'error': 'Šablona nenalezena'}), 404
    return jsonify({'success': True, 'template': t})


@pilot_bp.route('/api/pilot/setup-senior', methods=['POST'])
@optional_auth
def setup_senior_from_template():
    """Setup complete senior from diagnosis template."""
    data = request.json or {}
    senior_id = data.get('senior_id', '')
    template_id = data.get('template_id', '')
    senior_name = data.get('name', '')

    if not senior_id or not template_id:
        return jsonify({'success': False, 'error': 'senior_id a template_id jsou povinné'}), 400

    template = DIAGNOSIS_TEMPLATES.get(template_id)
    if not template:
        return jsonify({'success': False, 'error': 'Šablona nenalezena'}), 404

    results = {'senior_id': senior_id, 'template': template['name']}

    # 1. Create care plan from template
    try:
        from care_plan import _init_care_plan_schema
        _init_care_plan_schema()
        with db_context(commit=True) as db:
            goals = [{'id': i+1, 'text': g, 'status': 'active', 'priority': 'high'} for i, g in enumerate(template['goals'])]
            metrics = template['metrics']
            risks = [{'id': i+1, 'text': r, 'severity': 'high', 'mitigation': ''} for i, r in enumerate(template['risks'])]
            meds = [{'name': m, 'dose': '', 'time': ''} for m in template.get('medications_example', [])]

            db.execute(
                "INSERT INTO care_plans (senior_id, goals, monitored_metrics, risks, medications) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (senior_id) DO UPDATE SET "
                "goals = EXCLUDED.goals, monitored_metrics = EXCLUDED.monitored_metrics, "
                "risks = EXCLUDED.risks, medications = EXCLUDED.medications, updated_at = NOW()",
                (senior_id, json.dumps(goals), json.dumps(metrics), json.dumps(risks), json.dumps(meds))
            )
        results['care_plan'] = 'created'
    except Exception as e:
        results['care_plan'] = f'error: {e}'

    # 2. Setup medical team roles
    results['team_roles'] = template['team']

    return jsonify({
        'success': True,
        'message': f'✅ Senior nastaven ze šablony: {template["name"]}',
        'results': results,
    })


@pilot_bp.route('/api/pilot/invite', methods=['POST'])
@optional_auth
def invite_doctor():
    """Invite doctor to case — generates invitation."""
    data = request.json or {}
    senior_id = data.get('senior_id', '')
    doctor_email = data.get('email', '')
    role = data.get('role', 'general_practitioner')
    invited_by = ''
    auth = getattr(g, 'auth_user', None)
    if auth:
        invited_by = str(auth.get('id', ''))

    if not senior_id or not doctor_email:
        return jsonify({'success': False, 'error': 'senior_id a email jsou povinné'}), 400

    invitation = {
        'senior_id': senior_id,
        'email': doctor_email,
        'role': role,
        'invited_by': invited_by,
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'link': f'https://app.radimcare.cz/?invite={senior_id}&role={role}',
    }

    return jsonify({
        'success': True,
        'message': f'✅ Pozvánka vytvořena pro {doctor_email} ({role})',
        'invitation': invitation,
    })


@pilot_bp.route('/api/pilot/weekly/<senior_id>', methods=['GET'])
@optional_auth
def weekly_summary(senior_id):
    """Weekly summary for family + coordinator."""
    summary = {'senior_id': senior_id, 'period': 'last 7 days'}

    # Brain trend
    try:
        with db_context() as db:
            since = (datetime.utcnow() - timedelta(days=7)).isoformat()
            rows = db.execute(
                "SELECT ROUND(AVG(c)::numeric,1), ROUND(AVG(s)::numeric,2), COUNT(*), "
                "MODE() WITHIN GROUP (ORDER BY mode) "
                "FROM brain_states WHERE user_id = ? AND created_at > ?",
                (senior_id, since)
            ).fetchone()
            if rows:
                summary['brain'] = {
                    'avg_c': float(rows[0]) if rows[0] else 0,
                    'avg_stress': float(rows[1]) if rows[1] else 0,
                    'interactions': int(rows[2]),
                    'dominant_mode': rows[3] or 'HARMONY',
                }
    except Exception:
        summary['brain'] = {'note': 'No data'}

    # Observations
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT severity, COUNT(*) FROM agent_observations "
                "WHERE user_id = ? AND created_at > NOW() - INTERVAL '7 days' "
                "GROUP BY severity", (senior_id,)
            ).fetchall()
            summary['observations'] = {r[0]: r[1] for r in rows}
    except Exception:
        summary['observations'] = {}

    # Surveys
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*), SUM(points_earned) FROM survey_responses "
                "WHERE user_id = ? AND created_at > NOW() - INTERVAL '7 days'",
                (senior_id,)
            ).fetchone()
            if row:
                summary['surveys'] = {'completed': int(row[0]), 'points': int(row[1] or 0)}
    except Exception:
        summary['surveys'] = {'completed': 0, 'points': 0}

    # Care plan status
    try:
        from care_plan import _get_plan
        plan = _get_plan(senior_id)
        active_goals = len([g for g in plan.get('goals', []) if g.get('status') == 'active'])
        upcoming = len([c for c in plan.get('checkups', []) if c.get('status') == 'planned'])
        summary['care_plan'] = {'active_goals': active_goals, 'upcoming_checkups': upcoming}
    except Exception:
        summary['care_plan'] = {}

    return jsonify({'success': True, 'summary': summary})


@pilot_bp.route('/api/pilot/export/<senior_id>', methods=['GET'])
@optional_auth
def export_all(senior_id):
    """One-click export — everything about senior in JSON."""
    export = {'senior_id': senior_id, 'exported_at': datetime.utcnow().isoformat() + 'Z', 'format': 'radimcare-v1'}

    # Profile
    try:
        from memory_helpers import db_load_profile, db_load_learning
        export['profile'] = db_load_profile(senior_id)
        export['learning'] = db_load_learning(senior_id)
    except Exception:
        pass

    # Care plan
    try:
        from care_plan import _get_plan
        export['care_plan'] = _get_plan(senior_id)
    except Exception:
        pass

    # Brain states (last 30 days)
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT c, e, r, s, mode, coherence, source, created_at FROM brain_states "
                "WHERE user_id = ? AND created_at > NOW() - INTERVAL '30 days' ORDER BY created_at",
                (senior_id,)
            ).fetchall()
        export['brain_states'] = [{
            'c': r[0], 'e': r[1], 'r': r[2], 's': r[3],
            'mode': r[4], 'coherence': r[5], 'source': r[6], 'date': str(r[7]),
        } for r in rows]
    except Exception:
        pass

    # Medical team
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, name, role, specialization FROM medical_team WHERE senior_id = ?",
                (senior_id,)
            ).fetchall()
        export['medical_team'] = [{'user_id': r[0], 'name': r[1], 'role': r[2], 'spec': r[3]} for r in rows]
    except Exception:
        pass

    # Observations
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT observation_type, severity, message, created_at FROM agent_observations "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
                (senior_id,)
            ).fetchall()
        export['observations'] = [{'type': r[0], 'severity': r[1], 'message': r[2], 'date': str(r[3])} for r in rows]
    except Exception:
        pass

    # FHIR bundle
    try:
        from fhir_adapter import _fhir_patient
        export['fhir_patient'] = _fhir_patient(senior_id, export.get('profile'))
    except Exception:
        pass

    # Audit
    try:
        from audit_log import log_audit
        auth = getattr(g, 'auth_user', None)
        user_id = str(auth.get('id', '')) if auth else ''
        log_audit('EXPORT', 'pilot_export', user_id, senior_id, {'format': 'json'})
    except Exception:
        pass

    return jsonify({'success': True, 'export': export})


@pilot_bp.route('/api/pilot/status', methods=['GET'])
@optional_auth
def pilot_status():
    """Overall pilot status."""
    status = {'mode': 'pilot', 'version': 'v1.0'}

    try:
        with db_context() as db:
            status['seniors'] = db.execute("SELECT COUNT(*) FROM care_plans").fetchone()[0]
            status['team_members'] = db.execute("SELECT COUNT(*) FROM medical_team WHERE active = true").fetchone()[0]
            status['brain_states'] = db.execute("SELECT COUNT(*) FROM brain_states").fetchone()[0]
            status['surveys'] = db.execute("SELECT COUNT(*) FROM survey_responses").fetchone()[0]
    except Exception:
        pass

    status['templates'] = len(DIAGNOSIS_TEMPLATES)
    status['timestamp'] = datetime.utcnow().isoformat() + 'Z'

    return jsonify({'success': True, 'status': status})


logger.info("🧪 Pilot Mode v1.0 loaded — templates, invite, export")
