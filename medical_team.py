"""
🏥 MEDICAL TEAM v1.0
=====================
Digitální zdravotní tým pro seniora.
Jeden senior = jeden sdílený prostor pro více odborníků.

Roles:
    coordinator  — praktický lékař (hlavní koordinátor)
    cardiologist — kardiolog (❤️ tep, tlak)
    dermatologist — dermatolog (🧴 kůže, fotky)
    vascular    — cévní specialista (🦵 pohyb, prokrvení)
    caregiver   — pečovatel (denní péče)
    family      — rodina (klid mysli)

Features:
    - Sdílený profil seniora s filtrovanými views
    - Medical chat per senior
    - Filtered alerts (tep→kardiolog, kůže→dermatolog)
    - Koordinátor péče (praktik nebo AI)
"""

import logging
import json
from datetime import datetime
from flask import Blueprint, request, jsonify, g

from auth_middleware import require_auth, optional_auth
from database import db_context, db_insert

logger = logging.getLogger(__name__)

medical_bp = Blueprint('medical', __name__)


# ============================================================================
# MEDICAL ROLES + PERMISSIONS
# ============================================================================

MEDICAL_ROLES = {
    'coordinator': {
        'name': 'Koordinátor péče',
        'icon': '👨‍⚕️',
        'view_all': True,
        'can_message': True,
        'can_alert': True,
        'can_invite': True,
        'data_access': ['vitals', 'activity', 'mood', 'medications', 'photos', 'brain'],
    },
    'cardiologist': {
        'name': 'Kardiolog',
        'icon': '❤️',
        'view_all': False,
        'can_message': True,
        'can_alert': True,
        'can_invite': False,
        'data_access': ['vitals', 'activity', 'medications'],
        'alert_filter': ['heart_rate', 'blood_pressure', 'activity_drop'],
    },
    'dermatologist': {
        'name': 'Dermatolog',
        'icon': '🧴',
        'view_all': False,
        'can_message': True,
        'can_alert': True,
        'can_invite': False,
        'data_access': ['photos', 'medications'],
        'alert_filter': ['skin_change', 'photo_upload'],
    },
    'vascular': {
        'name': 'Cévní specialista',
        'icon': '🦵',
        'view_all': False,
        'can_message': True,
        'can_alert': True,
        'can_invite': False,
        'data_access': ['vitals', 'activity', 'medications'],
        'alert_filter': ['activity_drop', 'circulation', 'movement'],
    },
    'caregiver': {
        'name': 'Pečovatel',
        'icon': '🤝',
        'view_all': False,
        'can_message': True,
        'can_alert': False,
        'can_invite': False,
        'data_access': ['activity', 'mood', 'medications', 'brain'],
        'alert_filter': ['activity_drop', 'no_interaction', 'medication_missed'],
    },
    'family': {
        'name': 'Rodina',
        'icon': '👨‍👩‍👧',
        'view_all': False,
        'can_message': True,
        'can_alert': False,
        'can_invite': False,
        'data_access': ['activity', 'mood'],
        'alert_filter': ['activity_drop', 'no_interaction', 'crisis'],
    },
}


# ============================================================================
# DB SCHEMA — auto-create
# ============================================================================

MEDICAL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS medical_team (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'family',
        specialty TEXT,
        name TEXT,
        email TEXT,
        phone TEXT,
        active BOOLEAN DEFAULT true,
        invited_by TEXT,
        consent_given BOOLEAN DEFAULT false,
        consent_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(senior_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_medteam_senior ON medical_team(senior_id);
    CREATE INDEX IF NOT EXISTS idx_medteam_user ON medical_team(user_id);

    CREATE TABLE IF NOT EXISTS medical_messages (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        author_id TEXT NOT NULL,
        author_role TEXT,
        author_name TEXT,
        message TEXT NOT NULL,
        message_type TEXT DEFAULT 'text',
        attachments JSONB DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_medmsg_senior ON medical_messages(senior_id);

    CREATE TABLE IF NOT EXISTS medical_alerts (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        severity TEXT DEFAULT 'info',
        message TEXT NOT NULL,
        data JSONB DEFAULT '{}',
        routed_to JSONB DEFAULT '[]',
        acknowledged_by TEXT,
        acknowledged_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_medalert_senior ON medical_alerts(senior_id);
"""


def _init_medical_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in MEDICAL_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Medical schema: {e}")


# ============================================================================
# ENDPOINTS
# ============================================================================

@medical_bp.route('/api/medical/team/<senior_id>', methods=['GET'])
@optional_auth
def get_team(senior_id):
    """Get medical team for a senior."""
    _init_medical_schema()
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, user_id, role, specialty, name, email, phone, active, created_at "
                "FROM medical_team WHERE senior_id = ? AND active = true ORDER BY created_at",
                (senior_id,)
            ).fetchall()

        team = []
        for r in rows:
            role_info = MEDICAL_ROLES.get(r[2] if isinstance(r, (list, tuple)) else r.get('role', ''), {})
            team.append({
                'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                'user_id': r[1] if isinstance(r, (list, tuple)) else r.get('user_id'),
                'role': r[2] if isinstance(r, (list, tuple)) else r.get('role'),
                'role_name': role_info.get('name', ''),
                'icon': role_info.get('icon', '👤'),
                'specialty': r[3] if isinstance(r, (list, tuple)) else r.get('specialty'),
                'name': r[4] if isinstance(r, (list, tuple)) else r.get('name'),
                'email': r[5] if isinstance(r, (list, tuple)) else r.get('email'),
                'active': r[7] if isinstance(r, (list, tuple)) else r.get('active'),
            })

        return jsonify({'success': True, 'team': team, 'count': len(team), 'roles': list(MEDICAL_ROLES.keys())})
    except Exception as e:
        logger.error(f"Get team error: {e}")
        return jsonify({'success': True, 'team': [], 'count': 0, 'roles': list(MEDICAL_ROLES.keys())})


@medical_bp.route('/api/medical/team/<senior_id>/add', methods=['POST'])
@require_auth
def add_team_member(senior_id):
    """Add a member to medical team."""
    _init_medical_schema()
    data = request.json or {}
    role = data.get('role', 'family')
    name = data.get('name', '')
    email = data.get('email', '')
    phone = data.get('phone', '')
    user_id = data.get('user_id', email or f'member-{datetime.utcnow().timestamp():.0f}')

    if role not in MEDICAL_ROLES:
        return jsonify({'success': False, 'error': f'Neznámá role: {role}. Povolené: {list(MEDICAL_ROLES.keys())}'}), 400

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_team (senior_id, user_id, role, name, email, phone, invited_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (senior_id, user_id) DO UPDATE SET "
                "role = EXCLUDED.role, name = EXCLUDED.name, active = true",
                (senior_id, user_id, role, name, email, phone,
                 str(getattr(g, 'auth_user', {}).get('id', '')))
            )

        role_info = MEDICAL_ROLES[role]
        return jsonify({
            'success': True,
            'message': f'{role_info["icon"]} {name or role_info["name"]} přidán do týmu',
            'role': role,
            'role_name': role_info['name'],
        })
    except Exception as e:
        logger.error(f"Add member error: {e}")
        return jsonify({'success': False, 'error': 'Chyba při přidávání'}), 500


@medical_bp.route('/api/medical/messages/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def medical_messages(senior_id):
    """Medical chat for a senior's team."""
    _init_medical_schema()

    if request.method == 'GET':
        limit = request.args.get('limit', 50, type=int)
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, author_id, author_role, author_name, message, message_type, "
                    "attachments, created_at FROM medical_messages "
                    "WHERE senior_id = ? ORDER BY created_at DESC LIMIT ?",
                    (senior_id, limit)
                ).fetchall()

            messages = []
            for r in rows:
                role = r[2] if isinstance(r, (list, tuple)) else r.get('author_role', '')
                role_info = MEDICAL_ROLES.get(role, {})
                messages.append({
                    'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                    'author_id': r[1] if isinstance(r, (list, tuple)) else r.get('author_id'),
                    'author_role': role,
                    'author_icon': role_info.get('icon', '👤'),
                    'author_name': r[3] if isinstance(r, (list, tuple)) else r.get('author_name'),
                    'message': r[4] if isinstance(r, (list, tuple)) else r.get('message'),
                    'type': r[5] if isinstance(r, (list, tuple)) else r.get('message_type', 'text'),
                    'date': str(r[7] if isinstance(r, (list, tuple)) else r.get('created_at', '')),
                })

            messages.reverse()
            return jsonify({'success': True, 'messages': messages, 'count': len(messages)})
        except Exception as e:
            return jsonify({'success': True, 'messages': [], 'count': 0})

    elif request.method == 'POST':
        data = request.json or {}
        message = data.get('message', '').strip()
        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400

        auth = getattr(g, 'auth_user', {}) or {}
        author_id = str(auth.get('id', data.get('author_id', '')))
        author_role = data.get('role', auth.get('role', 'family'))
        author_name = data.get('name', auth.get('name', ''))

        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO medical_messages (senior_id, author_id, author_role, author_name, message, message_type) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (senior_id, author_id, author_role, author_name, message,
                     data.get('type', 'text'))
                )

            role_info = MEDICAL_ROLES.get(author_role, {})
            return jsonify({
                'success': True,
                'message': f'{role_info.get("icon","💬")} Zpráva odeslána',
            })
        except Exception as e:
            logger.error(f"Medical message error: {e}")
            return jsonify({'success': False, 'error': 'Chyba'}), 500


@medical_bp.route('/api/medical/alerts/<senior_id>', methods=['GET'])
@optional_auth
def get_alerts(senior_id):
    """Get filtered alerts for a senior."""
    _init_medical_schema()
    role = request.args.get('role', '')
    limit = request.args.get('limit', 20, type=int)

    try:
        with db_context() as db:
            if role and role in MEDICAL_ROLES:
                # Filter by role's alert types
                allowed = MEDICAL_ROLES[role].get('alert_filter', [])
                if allowed:
                    placeholders = ','.join(['?' for _ in allowed])
                    rows = db.execute(
                        f"SELECT id, alert_type, severity, message, data, routed_to, created_at "
                        f"FROM medical_alerts WHERE senior_id = ? AND alert_type IN ({placeholders}) "
                        f"ORDER BY created_at DESC LIMIT ?",
                        (senior_id, *allowed, limit)
                    ).fetchall()
                else:
                    rows = []
            else:
                rows = db.execute(
                    "SELECT id, alert_type, severity, message, data, routed_to, created_at "
                    "FROM medical_alerts WHERE senior_id = ? ORDER BY created_at DESC LIMIT ?",
                    (senior_id, limit)
                ).fetchall()

        alerts = []
        for r in rows:
            alerts.append({
                'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                'type': r[1] if isinstance(r, (list, tuple)) else r.get('alert_type'),
                'severity': r[2] if isinstance(r, (list, tuple)) else r.get('severity'),
                'message': r[3] if isinstance(r, (list, tuple)) else r.get('message'),
                'date': str(r[6] if isinstance(r, (list, tuple)) else r.get('created_at', '')),
            })

        return jsonify({'success': True, 'alerts': alerts, 'count': len(alerts)})
    except Exception as e:
        return jsonify({'success': True, 'alerts': [], 'count': 0})


@medical_bp.route('/api/medical/dashboard/<senior_id>', methods=['GET'])
@optional_auth
def medical_dashboard(senior_id):
    """Shared senior dashboard — filtered by viewer's role."""
    role = request.args.get('role', 'coordinator')
    role_info = MEDICAL_ROLES.get(role, MEDICAL_ROLES['family'])
    data_access = role_info.get('data_access', [])

    dashboard = {'success': True, 'senior_id': senior_id, 'role': role, 'view': {}}

    try:
        # Basic profile
        from memory_helpers import db_load_profile, db_load_learning
        profile = db_load_profile(senior_id)
        learning = db_load_learning(senior_id)

        dashboard['view']['name'] = profile.get('name', 'Senior')
        dashboard['view']['age_group'] = profile.get('age_group', '')

        # Activity (everyone)
        if 'activity' in data_access:
            dashboard['view']['activity'] = {
                'interaction_count': learning.get('interaction_count', 0),
                'last_mood': learning.get('last_mood', 'neutral'),
            }

        # Mood (caregiver, family)
        if 'mood' in data_access:
            dashboard['view']['mood'] = learning.get('last_mood', 'neutral')

        # Medications (doctors, caregiver)
        if 'medications' in data_access:
            dashboard['view']['medications'] = profile.get('medications_list', [])
            dashboard['view']['medication_times'] = profile.get('medication_times', {})

        # Vitals (cardiologist, vascular)
        if 'vitals' in data_access:
            dashboard['view']['vitals'] = {
                'note': 'Vitální data z IoT senzorů — připojit na NUC'
            }

        # Brain state (coordinator, caregiver) — with DB fallback
        if 'brain' in data_access:
            c_history = learning.get('C_history', [])
            avg_c = learning.get('avg_C')
            last_mode = learning.get('last_brain_mode')

            # Fallback: query brain_states directly if learning is empty
            if not c_history:
                try:
                    with db_context() as db:
                        rows = db.execute(
                            "SELECT c, mode FROM brain_states WHERE user_id = ? "
                            "ORDER BY created_at DESC LIMIT 10",
                            (senior_id,)
                        ).fetchall()
                    if rows:
                        c_history = [float(r[0]) for r in rows if r[0] is not None]
                        c_history.reverse()
                        last_mode = rows[0][1] if rows[0][1] else 'HARMONY'
                        avg_c = round(sum(c_history) / len(c_history), 1) if c_history else 0
                except Exception:
                    pass

            dashboard['view']['brain'] = {
                'avg_c': avg_c or 0,
                'last_mode': last_mode or 'HARMONY',
                'recent_c': c_history[-5:] if c_history else [],
            }

        # Team count
        _init_medical_schema()
        with db_context() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM medical_team WHERE senior_id = ? AND active = true",
                (senior_id,)
            ).fetchone()
            dashboard['view']['team_size'] = count[0] if count else 0

    except Exception as e:
        logger.debug(f"Medical dashboard: {e}")

    return jsonify(dashboard)


@medical_bp.route('/api/medical/roles', methods=['GET'])
def list_roles():
    """List available medical roles."""
    roles = []
    for rid, info in MEDICAL_ROLES.items():
        roles.append({
            'id': rid,
            'name': info['name'],
            'icon': info['icon'],
            'data_access': info['data_access'],
        })
    return jsonify({'success': True, 'roles': roles})


# ============================================================================
# CONSENT FLOW (GDPR)
# ============================================================================

@medical_bp.route('/api/medical/consent/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def consent(senior_id):
    """GDPR consent — senior approves/revokes doctor access."""
    _init_medical_schema()

    if request.method == 'GET':
        # List pending and approved consents
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, user_id, role, name, consent_given, consent_at "
                    "FROM medical_team WHERE senior_id = ? AND active = true",
                    (senior_id,)
                ).fetchall()

            members = []
            for r in rows:
                role_info = MEDICAL_ROLES.get(r[2] if isinstance(r, (list, tuple)) else r.get('role', ''), {})
                members.append({
                    'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                    'user_id': r[1] if isinstance(r, (list, tuple)) else r.get('user_id'),
                    'role': r[2] if isinstance(r, (list, tuple)) else r.get('role'),
                    'role_name': role_info.get('name', ''),
                    'icon': role_info.get('icon', '👤'),
                    'name': r[3] if isinstance(r, (list, tuple)) else r.get('name'),
                    'consent_given': r[4] if isinstance(r, (list, tuple)) else r.get('consent_given', False),
                    'consent_at': str(r[5]) if r[5] else None,
                })

            pending = [m for m in members if not m['consent_given']]
            approved = [m for m in members if m['consent_given']]

            return jsonify({
                'success': True,
                'pending': pending,
                'approved': approved,
                'total': len(members),
            })
        except Exception as e:
            return jsonify({'success': True, 'pending': [], 'approved': [], 'total': 0})

    elif request.method == 'POST':
        data = request.json or {}
        member_id = data.get('member_id')
        action = data.get('action', 'approve')  # approve / revoke

        if not member_id:
            return jsonify({'success': False, 'error': 'member_id je povinný'}), 400

        try:
            with db_context(commit=True) as db:
                if action == 'approve':
                    db.execute(
                        "UPDATE medical_team SET consent_given = true, consent_at = NOW() WHERE id = ? AND senior_id = ?",
                        (member_id, senior_id)
                    )
                    return jsonify({'success': True, 'message': '✅ Souhlas udělen'})
                elif action == 'revoke':
                    db.execute(
                        "UPDATE medical_team SET consent_given = false, active = false WHERE id = ? AND senior_id = ?",
                        (member_id, senior_id)
                    )
                    return jsonify({'success': True, 'message': '🔒 Přístup odebrán'})
                else:
                    return jsonify({'success': False, 'error': 'Neznámá akce'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': 'Chyba'}), 500


# ============================================================================
# PHOTO DOCUMENTATION
# ============================================================================

@medical_bp.route('/api/medical/photos/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def medical_photos(senior_id):
    """Photo documentation — upload + timeline."""
    if request.method == 'GET':
        # Return photo history (stored as medical messages with type='photo')
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, author_name, author_role, message, attachments, created_at "
                    "FROM medical_messages WHERE senior_id = ? AND message_type = 'photo' "
                    "ORDER BY created_at DESC LIMIT 50",
                    (senior_id,)
                ).fetchall()

            photos = []
            for r in rows:
                photos.append({
                    'id': r[0] if isinstance(r, (list, tuple)) else r.get('id'),
                    'author': r[1] if isinstance(r, (list, tuple)) else r.get('author_name'),
                    'role': r[2] if isinstance(r, (list, tuple)) else r.get('author_role'),
                    'description': r[3] if isinstance(r, (list, tuple)) else r.get('message'),
                    'date': str(r[5] if isinstance(r, (list, tuple)) else r.get('created_at', '')),
                })

            return jsonify({'success': True, 'photos': photos, 'count': len(photos)})
        except Exception:
            return jsonify({'success': True, 'photos': [], 'count': 0})

    elif request.method == 'POST':
        data = request.json or {}
        description = data.get('description', '')
        photo_url = data.get('photo_url', '')  # Base64 or URL
        auth = getattr(g, 'auth_user', {}) or {}

        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO medical_messages (senior_id, author_id, author_role, author_name, "
                    "message, message_type, attachments) VALUES (?, ?, ?, ?, ?, 'photo', ?)",
                    (senior_id, str(auth.get('id', '')), data.get('role', 'caregiver'),
                     data.get('name', auth.get('name', '')), description,
                     json.dumps([{'url': photo_url, 'type': 'photo'}]) if photo_url else '[]')
                )
            return jsonify({'success': True, 'message': '📸 Fotodokumentace uložena'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Chyba'}), 500


# ============================================================================
# PDF REPORT EXPORT
# ============================================================================

@medical_bp.route('/api/medical/report/<senior_id>', methods=['GET'])
@optional_auth
def export_report(senior_id):
    """Generate text report for a senior (last 30 days)."""
    days = request.args.get('days', 30, type=int)

    try:
        from memory_helpers import db_load_profile, db_load_learning
        profile = db_load_profile(senior_id)
        learning = db_load_learning(senior_id)

        report = {
            'success': True,
            'senior': {
                'name': profile.get('name', 'Senior'),
                'age_group': profile.get('age_group', ''),
                'medications': profile.get('medications_list', []),
            },
            'period': f'Posledních {days} dní',
            'generated_at': datetime.utcnow().isoformat() + 'Z',
        }

        # Brain trend
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT created_at::date as day, ROUND(AVG(c)::numeric,1) as avg_c, "
                    "ROUND(AVG(s)::numeric,2) as avg_s, COUNT(*) as msgs "
                    f"FROM brain_states WHERE user_id = ? AND created_at > NOW() - INTERVAL '{days} days' "
                    "GROUP BY created_at::date ORDER BY day",
                    (senior_id,)
                ).fetchall()

            report['brain_trend'] = [{
                'date': str(r[0]),
                'avg_c': float(r[1]) if r[1] else 0,
                'avg_s': float(r[2]) if r[2] else 0,
                'messages': int(r[3]),
            } for r in rows]

            if report['brain_trend']:
                avg_c = sum(d['avg_c'] for d in report['brain_trend']) / len(report['brain_trend'])
                report['summary'] = {
                    'avg_c': round(avg_c, 1),
                    'total_days': len(report['brain_trend']),
                    'total_messages': sum(d['messages'] for d in report['brain_trend']),
                    'status': 'stabilní' if avg_c < 12 else 'vyžaduje pozornost' if avg_c < 27 else 'kritické',
                }
        except Exception:
            report['brain_trend'] = []

        # Medical alerts
        try:
            with db_context() as db:
                alerts = db.execute(
                    f"SELECT alert_type, severity, message, created_at FROM medical_alerts "
                    f"WHERE senior_id = ? AND created_at > NOW() - INTERVAL '{days} days' "
                    "ORDER BY created_at DESC LIMIT 20",
                    (senior_id,)
                ).fetchall()
            report['alerts'] = [{
                'type': r[0], 'severity': r[1], 'message': r[2], 'date': str(r[3])
            } for r in alerts]
        except Exception:
            report['alerts'] = []

        # Team
        try:
            with db_context() as db:
                team = db.execute(
                    "SELECT name, role FROM medical_team WHERE senior_id = ? AND active = true",
                    (senior_id,)
                ).fetchall()
            report['team'] = [{'name': r[0], 'role': r[1]} for r in team]
        except Exception:
            report['team'] = []

        return jsonify(report)

    except Exception as e:
        logger.error(f"Report error: {e}")
        return jsonify({'success': False, 'error': 'Chyba při generování reportu'}), 500


logger.info("🏥 Medical Team v2.0 loaded — consent, photos, reports, smart routing")
