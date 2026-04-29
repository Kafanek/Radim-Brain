"""
📋 CARE PLAN v1.0 — Plán péče pro seniora
==========================================
Každý senior má strukturovaný plán:
- Cíle péče
- Denní režim
- Léky + sledované ukazatele
- Rizika
- Kdo za co odpovídá
- Kontroly + termíny

Endpoints:
    GET  /api/care-plan/<senior_id>           — Celý plán
    PUT  /api/care-plan/<senior_id>           — Aktualizovat plán
    POST /api/care-plan/<senior_id>/goal      — Přidat cíl
    POST /api/care-plan/<senior_id>/risk      — Přidat riziko
    POST /api/care-plan/<senior_id>/checkup   — Naplánovat kontrolu
    GET  /api/care-plan/<senior_id>/summary   — Souhrn pro rodinu
"""

import logging
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, g

from auth_middleware import optional_auth
from database import db_context, db_insert

logger = logging.getLogger(__name__)

care_plan_bp = Blueprint('care_plan', __name__)

CARE_PLAN_SCHEMA = """
    CREATE TABLE IF NOT EXISTS care_plans (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL UNIQUE,
        goals JSONB DEFAULT '[]',
        daily_routine JSONB DEFAULT '{}',
        medications JSONB DEFAULT '[]',
        monitored_metrics JSONB DEFAULT '[]',
        risks JSONB DEFAULT '[]',
        responsibilities JSONB DEFAULT '[]',
        checkups JSONB DEFAULT '[]',
        notes TEXT DEFAULT '',
        updated_by TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_care_plan_senior ON care_plans(senior_id);
"""

def _init_care_plan_schema():
    try:
        with db_context(commit=True) as db:
            for s in CARE_PLAN_SCHEMA.strip().split(';'):
                s = s.strip()
                if s:
                    db.execute(s)
    except Exception:
        pass


def _maybe_json(value, default):
    """Tolerant JSON load: PostgreSQL JSONB returns parsed dict/list directly,
    SQLite returns TEXT (string). Handle both — decode only if string."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value or json.dumps(default))
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _get_plan(senior_id):
    """Get or create care plan for senior."""
    _init_care_plan_schema()
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT goals, daily_routine, medications, monitored_metrics, risks, "
                "responsibilities, checkups, notes, updated_by, updated_at "
                "FROM care_plans WHERE senior_id = ?",
                (senior_id,)
            ).fetchone()

        if row:
            return {
                'goals': _maybe_json(row[0], []),
                'daily_routine': _maybe_json(row[1], {}),
                'medications': _maybe_json(row[2], []),
                'monitored_metrics': _maybe_json(row[3], []),
                'risks': _maybe_json(row[4], []),
                'responsibilities': _maybe_json(row[5], []),
                'checkups': _maybe_json(row[6], []),
                'notes': row[7] or '',
                'updated_by': row[8] or '',
                'updated_at': str(row[9]) if row[9] else '',
            }
        else:
            # Create default plan
            default = _default_plan(senior_id)
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO care_plans (senior_id, goals, daily_routine, medications, "
                    "monitored_metrics, risks, responsibilities, checkups) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (senior_id) DO NOTHING",
                    (senior_id, json.dumps(default['goals']), json.dumps(default['daily_routine']),
                     json.dumps(default['medications']), json.dumps(default['monitored_metrics']),
                     json.dumps(default['risks']), json.dumps(default['responsibilities']),
                     json.dumps(default['checkups']))
                )
            return default
    except Exception as e:
        logger.debug(f"Care plan get: {e}")
        return _default_plan(senior_id)


def _default_plan(senior_id):
    """Default care plan template."""
    return {
        'goals': [
            {'id': 1, 'text': 'Bezpečný pohyb po bytě', 'status': 'active', 'priority': 'high'},
            {'id': 2, 'text': 'Pravidelné užívání léků', 'status': 'active', 'priority': 'high'},
            {'id': 3, 'text': 'Sociální kontakt min. 1x denně', 'status': 'active', 'priority': 'medium'},
        ],
        'daily_routine': {
            '07:00': 'Probuzení, hygiena',
            '07:30': 'Snídaně + ranní léky',
            '09:00': 'Lehké cvičení / procházka',
            '12:00': 'Oběd',
            '14:00': 'Odpočinek / aktivity',
            '17:00': 'Svačina',
            '18:00': 'Večeře + večerní léky',
            '20:00': 'Relaxace, TV, čtení',
            '21:30': 'Příprava na spaní',
        },
        'medications': [],
        'monitored_metrics': [
            {'name': 'Tepová frekvence', 'unit': 'bpm', 'normal_range': '60-100', 'responsible': 'kardiolog'},
            {'name': 'Krevní tlak', 'unit': 'mmHg', 'normal_range': '120/80-140/90', 'responsible': 'kardiolog'},
            {'name': 'Pohybová aktivita', 'unit': 'kroky/den', 'normal_range': '>2000', 'responsible': 'cévní'},
            {'name': 'Nálada (C score)', 'unit': '0-40', 'normal_range': '0-12', 'responsible': 'koordinátor'},
            {'name': 'Spánek', 'unit': 'hodin', 'normal_range': '6-9', 'responsible': 'praktik'},
        ],
        'risks': [
            {'id': 1, 'text': 'Riziko pádu', 'severity': 'high', 'mitigation': 'Senzory pohybu, protiskluzové podložky'},
            {'id': 2, 'text': 'Zapomínání léků', 'severity': 'medium', 'mitigation': 'Ranní check-in Radimem'},
        ],
        'responsibilities': [
            {'role': 'coordinator', 'person': '', 'tasks': ['Celková koordinace', 'Týdenní souhrn']},
            {'role': 'cardiologist', 'person': '', 'tasks': ['Sledování tepu a tlaku']},
            {'role': 'general_practitioner', 'person': '', 'tasks': ['Preventivní prohlídky', 'Léky']},
            {'role': 'caregiver', 'person': '', 'tasks': ['Denní kontrola', 'Léky', 'Hygiena']},
            {'role': 'family', 'person': '', 'tasks': ['Sociální kontakt', 'Nákupy']},
        ],
        'checkups': [],
        'notes': '',
        'updated_by': 'system',
        'updated_at': datetime.utcnow().isoformat(),
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@care_plan_bp.route('/api/care-plan/<senior_id>', methods=['GET'])
@optional_auth
def get_care_plan(senior_id):
    """Get complete care plan."""
    plan = _get_plan(senior_id)
    return jsonify({'success': True, 'plan': plan, 'senior_id': senior_id})


@care_plan_bp.route('/api/care-plan/<senior_id>', methods=['PUT'])
@optional_auth
def update_care_plan(senior_id):
    """Update care plan (partial update — only provided fields)."""
    _init_care_plan_schema()
    data = request.get_json(silent=True) or {}
    user_id = ''
    auth = getattr(g, 'auth_user', None)
    if auth:
        user_id = str(auth.get('id', ''))

    # Ensure plan exists
    _get_plan(senior_id)

    update_fields = []
    update_values = []

    for field in ['goals', 'daily_routine', 'medications', 'monitored_metrics',
                  'risks', 'responsibilities', 'checkups', 'notes']:
        if field in data:
            val = data[field]
            if isinstance(val, (dict, list)):
                val = json.dumps(val)
            update_fields.append(f"{field} = ?")
            update_values.append(val)

    if not update_fields:
        return jsonify({'success': False, 'error': 'Žádná data k aktualizaci'}), 400

    update_fields.append("updated_by = ?")
    update_values.append(user_id)
    update_fields.append("updated_at = NOW()")
    update_values.append(senior_id)

    try:
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE care_plans SET {', '.join(update_fields)} WHERE senior_id = ?",
                tuple(update_values)
            )

        # Audit
        try:
            from audit_log import log_audit
            log_audit('UPDATE', 'care_plan', user_id, senior_id, {'fields': list(data.keys())})
        except Exception:
            pass

        return jsonify({'success': True, 'message': '✅ Plán péče aktualizován'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@care_plan_bp.route('/api/care-plan/<senior_id>/goal', methods=['POST'])
@optional_auth
def add_goal(senior_id):
    """Add care goal."""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    priority = data.get('priority', 'medium')
    if not text:
        return jsonify({'success': False, 'error': 'Text cíle je povinný'}), 400

    plan = _get_plan(senior_id)
    max_id = max([g.get('id', 0) for g in plan['goals']] + [0])
    plan['goals'].append({
        'id': max_id + 1, 'text': text, 'status': 'active',
        'priority': priority, 'added': datetime.utcnow().isoformat(),
    })

    try:
        with db_context(commit=True) as db:
            db.execute("UPDATE care_plans SET goals = ?, updated_at = NOW() WHERE senior_id = ?",
                       (json.dumps(plan['goals']), senior_id))
        return jsonify({'success': True, 'message': f'✅ Cíl přidán: {text}', 'goal_id': max_id + 1})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@care_plan_bp.route('/api/care-plan/<senior_id>/risk', methods=['POST'])
@optional_auth
def add_risk(senior_id):
    """Add risk."""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    severity = data.get('severity', 'medium')
    mitigation = data.get('mitigation', '')

    plan = _get_plan(senior_id)
    max_id = max([r.get('id', 0) for r in plan['risks']] + [0])
    plan['risks'].append({
        'id': max_id + 1, 'text': text, 'severity': severity,
        'mitigation': mitigation, 'added': datetime.utcnow().isoformat(),
    })

    try:
        with db_context(commit=True) as db:
            db.execute("UPDATE care_plans SET risks = ?, updated_at = NOW() WHERE senior_id = ?",
                       (json.dumps(plan['risks']), senior_id))
        return jsonify({'success': True, 'message': f'✅ Riziko přidáno: {text}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@care_plan_bp.route('/api/care-plan/<senior_id>/checkup', methods=['POST'])
@optional_auth
def add_checkup(senior_id):
    """Schedule checkup."""
    data = request.get_json(silent=True) or {}
    doctor = data.get('doctor', '')
    date = data.get('date', '')
    note = data.get('note', '')

    plan = _get_plan(senior_id)
    plan['checkups'].append({
        'doctor': doctor, 'date': date, 'note': note,
        'status': 'planned', 'added': datetime.utcnow().isoformat(),
    })

    try:
        with db_context(commit=True) as db:
            db.execute("UPDATE care_plans SET checkups = ?, updated_at = NOW() WHERE senior_id = ?",
                       (json.dumps(plan['checkups']), senior_id))
        return jsonify({'success': True, 'message': f'✅ Kontrola naplánována: {doctor} — {date}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@care_plan_bp.route('/api/care-plan/<senior_id>/summary', methods=['GET'])
@optional_auth
def care_plan_summary(senior_id):
    """Weekly summary for family — plain text."""
    plan = _get_plan(senior_id)

    active_goals = [g for g in plan['goals'] if g.get('status') == 'active']
    high_risks = [r for r in plan['risks'] if r.get('severity') == 'high']
    upcoming = [c for c in plan['checkups'] if c.get('status') == 'planned']

    summary = f"📋 Plán péče — souhrn\n\n"
    summary += f"🎯 Aktivní cíle ({len(active_goals)}):\n"
    for g in active_goals:
        summary += f"  • {g['text']} ({g.get('priority', '')})\n"

    summary += f"\n⚠️ Rizika ({len(high_risks)} vysokých):\n"
    for r in high_risks:
        summary += f"  • {r['text']} → {r.get('mitigation', '')}\n"

    summary += f"\n💊 Léky ({len(plan['medications'])}):\n"
    for m in plan['medications']:
        summary += f"  • {m.get('name', '?')} — {m.get('dose', '')} ({m.get('time', '')})\n"

    summary += f"\n📅 Nadcházející kontroly ({len(upcoming)}):\n"
    for c in upcoming:
        summary += f"  • {c.get('doctor', '?')} — {c.get('date', '?')}\n"

    summary += f"\n👥 Tým:\n"
    for r in plan['responsibilities']:
        summary += f"  • {r.get('role', '?')}: {', '.join(r.get('tasks', []))}\n"

    return jsonify({'success': True, 'summary': summary, 'senior_id': senior_id})


logger.info("📋 Care Plan v1.0 loaded")
