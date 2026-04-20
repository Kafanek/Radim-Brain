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
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g

from auth_middleware import require_auth, optional_auth
from database import db_context, db_insert, is_postgres

logger = logging.getLogger(__name__)

medical_bp = Blueprint('medical', __name__)


def _send_team_email(to_email, member_name, role_info, senior_id):
    """v4.2: Send email notification to new team member."""
    try:
        import os, smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', '465'))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_pass = os.environ.get('SMTP_PASS')
        smtp_from = os.environ.get('SMTP_FROM', smtp_user)
        if not all([smtp_host, smtp_user, smtp_pass]):
            logger.debug("SMTP not configured, skipping email")
            return

        subject = f"{role_info['icon']} Přidáni do zdravotního týmu — Radim"
        body = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;">
            <h2 style="color:#5BA8A0;">{role_info['icon']} Zdravotní tým</h2>
            <p>Dobrý den, <strong>{member_name or 'člene'}</strong>,</p>
            <p>byli jste přidáni do zdravotního týmu jako <strong>{role_info['name']}</strong>.</p>
            <p>Přihlaste se do aplikace pro zobrazení sdíleného profilu seniora, chatu a alertů:</p>
            <a href="https://app.radimcare.cz" style="display:inline-block;padding:12px 24px;background:#5BA8A0;
               color:white;text-decoration:none;border-radius:10px;font-weight:600;">
               Otevřít Radim</a>
            <p style="color:#a0aec0;font-size:0.85rem;margin-top:20px;">
                S pozdravem,<br>Radim — AI asistent pro seniory</p>
        </div>"""

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg.attach(MIMEText(body, 'html'))

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as s:
                s.login(smtp_user, smtp_pass)
                s.sendmail(smtp_from, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                s.starttls()
                s.login(smtp_user, smtp_pass)
                s.sendmail(smtp_from, to_email, msg.as_string())

        logger.info(f"Welcome email sent to {to_email}")
    except Exception as e:
        logger.debug(f"Email send error: {e}")


def _send_escalation_email(coordinator_emails, alert_data, senior_id):
    """v4.2: Send escalation email to coordinators."""
    try:
        import os, smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', '465'))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_pass = os.environ.get('SMTP_PASS')
        smtp_from = os.environ.get('SMTP_FROM', smtp_user)
        if not all([smtp_host, smtp_user, smtp_pass]):
            return

        subject = f"🚨 ESKALACE — Radim Medical Alert"
        body = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;">
            <h2 style="color:#e53e3e;">🚨 Alert eskalován</h2>
            <p><strong>Senior:</strong> {senior_id}</p>
            <p><strong>Alert:</strong> {alert_data.get('message', '—')}</p>
            <p><strong>Závažnost:</strong> {alert_data.get('severity', '—')}</p>
            <p>Přihlaste se pro detaily a reakci:</p>
            <a href="https://app.radimcare.cz" style="display:inline-block;padding:12px 24px;background:#e53e3e;
               color:white;text-decoration:none;border-radius:10px;font-weight:600;">
               Otevřít Radim</a>
        </div>"""

        for email in (coordinator_emails or []):
            if not email:
                continue
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = smtp_from
            msg['To'] = email
            msg.attach(MIMEText(body, 'html'))

            try:
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as s:
                        s.login(smtp_user, smtp_pass)
                        s.sendmail(smtp_from, email, msg.as_string())
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                        s.starttls()
                        s.login(smtp_user, smtp_pass)
                        s.sendmail(smtp_from, email, msg.as_string())
                logger.info(f"Escalation email sent to {email}")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"Escalation email error: {e}")


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

    -- Sprint F: daily symptom check-in persistence
    CREATE TABLE IF NOT EXISTS medical_symptoms (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        pain SMALLINT,
        mood SMALLINT,
        sleep SMALLINT,
        appetite SMALLINT,
        energy SMALLINT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_medsymptoms_senior_date
        ON medical_symptoms(senior_id, created_at DESC);

    -- Sprint F: telemedicine appointment persistence (replaces localStorage)
    CREATE TABLE IF NOT EXISTS medical_appointments (
        id TEXT PRIMARY KEY,
        senior_id TEXT NOT NULL,
        with_member TEXT,
        when_at TIMESTAMP,
        mode TEXT DEFAULT 'video',
        reason TEXT,
        reminder_24h_sent BOOLEAN DEFAULT FALSE,
        reminder_1h_sent BOOLEAN DEFAULT FALSE,
        cancelled_at TIMESTAMP,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_medappts_senior_when
        ON medical_appointments(senior_id, when_at);
    CREATE INDEX IF NOT EXISTS idx_medappts_reminder
        ON medical_appointments(when_at, reminder_24h_sent, reminder_1h_sent);
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
                'phone': r[6] if isinstance(r, (list, tuple)) else r.get('phone'),
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
        auth = getattr(g, 'auth_user', None) or {}
        invited_by = str(auth.get('id', ''))

        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO medical_team (senior_id, user_id, role, name, email, phone, invited_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (senior_id, user_id) DO UPDATE SET "
                "role = EXCLUDED.role, name = EXCLUDED.name, active = true",
                (senior_id, user_id, role, name, email, phone, invited_by)
            )

        role_info = MEDICAL_ROLES[role]

        # v4.2: Send welcome email to new team member (fire-and-forget)
        if email:
            try:
                _send_team_email(email, name, role_info, senior_id)
            except Exception as email_err:
                logger.debug(f"Welcome email failed (non-blocking): {email_err}")

        return jsonify({
            'success': True,
            'message': f'{role_info["icon"]} {name or role_info["name"]} přidán do týmu',
            'role': role,
            'role_name': role_info['name'],
        })
    except Exception as e:
        logger.error(f"Add member error: {e}")
        return jsonify({'success': False, 'error': f'Chyba při přidávání: {str(e)[:100]}'}), 500


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


# Alert lifecycle states
ALERT_STATES = ['new', 'acknowledged', 'in_progress', 'resolved', 'escalated']

@medical_bp.route('/api/medical/alerts/<senior_id>/update', methods=['POST'])
@require_auth
def update_alert(senior_id):
    """Update alert state — acknowledge, resolve, escalate."""
    data = request.json or {}
    alert_id = data.get('alert_id')
    new_state = data.get('state')
    note = data.get('note', '')

    if not alert_id or new_state not in ALERT_STATES:
        return jsonify({'success': False, 'error': f'alert_id + state ({",".join(ALERT_STATES)}) required'}), 400

    auth = getattr(g, 'auth_user', {}) or {}
    user_name = auth.get('name', '')

    try:
        _init_medical_schema()
        with db_context(commit=True) as db:
            if new_state == 'acknowledged':
                db.execute(
                    "UPDATE medical_alerts SET acknowledged_by = ?, acknowledged_at = NOW(), "
                    "data = data || ?::jsonb WHERE id = ? AND senior_id = ?",
                    (str(auth.get('id', '')),
                     json.dumps({'state': new_state, 'note': note, 'by': user_name}),
                     alert_id, senior_id)
                )
            elif new_state == 'escalated':
                # Create escalation alert
                db.execute(
                    "INSERT INTO medical_alerts (senior_id, alert_type, severity, message, data, routed_to) "
                    "VALUES (?, 'escalation', 'alert', ?, ?, ?)",
                    (senior_id, f'Eskalováno: {note or "Bez reakce"}',
                     json.dumps({'original_alert': alert_id, 'escalated_by': user_name}),
                     json.dumps(['coordinator']))
                )
                # v4.2: Email coordinators on escalation
                try:
                    coordinator_rows = db.execute(
                        "SELECT email FROM medical_team WHERE senior_id = ? AND role = 'coordinator' AND active = 1 AND email IS NOT NULL",
                        (senior_id,)
                    ).fetchall()
                    emails = [r[0] for r in (coordinator_rows or []) if r[0]]
                    if emails:
                        _send_escalation_email(emails, {'message': note or 'Bez reakce', 'severity': 'alert'}, senior_id)
                except Exception as esc_e:
                    logger.debug(f"Escalation email lookup: {esc_e}")
            else:
                db.execute(
                    "UPDATE medical_alerts SET data = data || ?::jsonb WHERE id = ? AND senior_id = ?",
                    (json.dumps({'state': new_state, 'note': note, 'by': user_name, 'at': datetime.utcnow().isoformat()}),
                     alert_id, senior_id)
                )

        # Audit
        try:
            from audit_log import log_audit, ALERT
            log_audit(ALERT, 'medical_alert', alert_id, senior_id,
                      {'new_state': new_state, 'note': note})
        except Exception:
            pass

        return jsonify({'success': True, 'message': f'Alert → {new_state}', 'state': new_state})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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


@medical_bp.route('/api/medical/observations/<senior_id>', methods=['GET'])
@optional_auth
def get_observations(senior_id):
    """List recent agent_observations (brain engine proactive detections)."""
    limit = request.args.get('limit', 15, type=int)
    only_unack = request.args.get('unack', '0') in ('1', 'true', 'yes')

    try:
        with db_context() as db:
            if only_unack:
                rows = db.execute(
                    "SELECT id, observation_type, severity, message, details, "
                    "action_taken, acknowledged_at, created_at "
                    "FROM agent_observations WHERE user_id = ? AND acknowledged_at IS NULL "
                    "ORDER BY created_at DESC LIMIT ?",
                    (senior_id, limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, observation_type, severity, message, details, "
                    "action_taken, acknowledged_at, created_at "
                    "FROM agent_observations WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (senior_id, limit)
                ).fetchall()

        def _val(r, i, key):
            return r[i] if isinstance(r, (list, tuple)) else r.get(key)

        observations = []
        for r in rows:
            observations.append({
                'id': _val(r, 0, 'id'),
                'type': _val(r, 1, 'observation_type'),
                'severity': _val(r, 2, 'severity'),
                'message': _val(r, 3, 'message'),
                'details': _val(r, 4, 'details') or {},
                'action_taken': _val(r, 5, 'action_taken'),
                'acknowledged': bool(_val(r, 6, 'acknowledged_at')),
                'created_at': str(_val(r, 7, 'created_at') or ''),
            })
        return jsonify({
            'success': True,
            'observations': observations,
            'count': len(observations),
        })
    except Exception as e:
        # Table may not exist yet on fresh DBs — return empty, not error
        return jsonify({'success': True, 'observations': [], 'count': 0})


@medical_bp.route('/api/medical/observations/<senior_id>/acknowledge', methods=['POST'])
@optional_auth
def acknowledge_observation(senior_id):
    """Mark an observation as acknowledged by the caregiver/senior."""
    data = request.get_json() or {}
    obs_id = data.get('id')
    if not obs_id:
        return jsonify({'success': False, 'error': 'missing id'}), 400
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE agent_observations SET acknowledged_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND user_id = ?",
                (obs_id, senior_id)
            )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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

CONSENT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS granular_consent (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        member_id INTEGER,
        user_id TEXT,
        role TEXT,
        data_type TEXT NOT NULL,
        granted BOOLEAN DEFAULT false,
        expires_at TIMESTAMP,
        granted_at TIMESTAMP,
        revoked_at TIMESTAMP,
        change_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_gconsent_senior ON granular_consent(senior_id);
"""

CONSENT_DATA_TYPES = ['vitals', 'activity', 'mood', 'medications', 'photos', 'brain', 'chat', 'reports']

def _init_consent_schema():
    try:
        with db_context(commit=True) as db:
            for s in CONSENT_SCHEMA.strip().split(';'):
                s = s.strip()
                if s: db.execute(s)
    except Exception:
        pass


@medical_bp.route('/api/medical/consent/<senior_id>/granular', methods=['GET', 'POST'])
@optional_auth
def granular_consent(senior_id):
    """Granular GDPR consent — per role, per data type, with expiry."""
    _init_consent_schema()

    if request.method == 'GET':
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT gc.id, gc.user_id, gc.role, gc.data_type, gc.granted, gc.expires_at, gc.granted_at, "
                    "mt.name FROM granular_consent gc "
                    "LEFT JOIN medical_team mt ON gc.user_id = mt.user_id AND gc.senior_id = mt.senior_id "
                    "WHERE gc.senior_id = ? ORDER BY gc.role, gc.data_type",
                    (senior_id,)
                ).fetchall()

            consents = [{
                'id': r[0], 'user_id': r[1], 'role': r[2], 'data_type': r[3],
                'granted': r[4], 'expires_at': str(r[5]) if r[5] else None,
                'granted_at': str(r[6]) if r[6] else None, 'name': r[7] or '',
            } for r in rows]

            return jsonify({
                'success': True, 'consents': consents,
                'data_types': CONSENT_DATA_TYPES,
                'count': len(consents),
            })
        except Exception:
            return jsonify({'success': True, 'consents': [], 'data_types': CONSENT_DATA_TYPES, 'count': 0})

    elif request.method == 'POST':
        data = request.json or {}
        user_id = data.get('user_id', '')
        role = data.get('role', '')
        data_type = data.get('data_type', '')
        action = data.get('action', 'grant')  # grant / revoke
        expires_days = data.get('expires_days')  # optional: auto-expire after N days
        reason = data.get('reason', '')

        if data_type not in CONSENT_DATA_TYPES:
            return jsonify({'success': False, 'error': f'Neznámý typ dat. Povolené: {CONSENT_DATA_TYPES}'}), 400

        try:
            expires_at = None
            if expires_days:
                from datetime import timedelta
                expires_at = (datetime.utcnow() + timedelta(days=int(expires_days))).isoformat()

            with db_context(commit=True) as db:
                if action == 'grant':
                    db.execute(
                        "INSERT INTO granular_consent (senior_id, user_id, role, data_type, granted, "
                        "expires_at, granted_at, change_reason) VALUES (?, ?, ?, ?, true, ?, NOW(), ?) "
                        "ON CONFLICT DO NOTHING",
                        (senior_id, user_id, role, data_type, expires_at, reason)
                    )
                elif action == 'revoke':
                    db.execute(
                        "UPDATE granular_consent SET granted = false, revoked_at = NOW(), change_reason = ? "
                        "WHERE senior_id = ? AND user_id = ? AND data_type = ?",
                        (reason, senior_id, user_id, data_type)
                    )

            try:
                from audit_log import log_audit, CONSENT
                log_audit(CONSENT, 'granular_consent', None, senior_id,
                          {'user_id': user_id, 'data_type': data_type, 'action': action, 'expires_days': expires_days})
            except Exception:
                pass

            msg = f'✅ Souhlas {"udělen" if action == "grant" else "odebrán"} pro {data_type}'
            return jsonify({'success': True, 'message': msg})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500


@medical_bp.route('/api/medical/consent/<senior_id>/history', methods=['GET'])
@optional_auth
def consent_history(senior_id):
    """Consent change history — GDPR audit."""
    _init_consent_schema()
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT role, data_type, granted, granted_at, revoked_at, change_reason "
                "FROM granular_consent WHERE senior_id = ? ORDER BY created_at DESC LIMIT 50",
                (senior_id,)
            ).fetchall()

        history = [{
            'role': r[0], 'data_type': r[1], 'granted': r[2],
            'granted_at': str(r[3]) if r[3] else None,
            'revoked_at': str(r[4]) if r[4] else None,
            'reason': r[5],
        } for r in rows]

        return jsonify({'success': True, 'history': history, 'count': len(history)})
    except Exception:
        return jsonify({'success': True, 'history': [], 'count': 0})


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


@medical_bp.route('/api/medical/report/<senior_id>/print', methods=['GET'])
def print_report(senior_id):
    """HTML report ready to print (Ctrl+P → PDF)."""
    from flask import Response
    days = request.args.get('days', 30, type=int)

    try:
        from memory_helpers import db_load_profile, db_load_learning
        profile = db_load_profile(senior_id)
        learning = db_load_learning(senior_id)
        name = profile.get('name', 'Senior')
        meds = profile.get('medications_list', [])

        # Brain trend
        brain_rows = []
        try:
            with db_context() as db:
                brain_rows = db.execute(
                    "SELECT created_at::date as day, ROUND(AVG(c)::numeric,1) as avg_c, "
                    "ROUND(AVG(s)::numeric,2) as avg_s, COUNT(*) as msgs, "
                    "MODE() WITHIN GROUP (ORDER BY mode) as mode "
                    f"FROM brain_states WHERE user_id = ? AND created_at > NOW() - INTERVAL '{days} days' "
                    "GROUP BY created_at::date ORDER BY day",
                    (senior_id,)
                ).fetchall()
        except Exception:
            pass

        # Team
        team = []
        try:
            with db_context() as db:
                team = db.execute(
                    "SELECT name, role FROM medical_team WHERE senior_id = ? AND active = true",
                    (senior_id,)
                ).fetchall()
        except Exception:
            pass

        # Build HTML
        now = datetime.utcnow().strftime('%d.%m.%Y %H:%M')
        html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="utf-8">
<title>RadimCare — Report {name}</title>
<style>
    body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #2d3748; }}
    h1 {{ color: #5BA8A0; border-bottom: 3px solid #5BA8A0; padding-bottom: 8px; }}
    h2 {{ color: #4A9690; margin-top: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
    th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
    th {{ background: #f7fafc; font-weight: 600; }}
    .green {{ color: #38a169; }} .orange {{ color: #dd6b20; }} .red {{ color: #e53e3e; }}
    .footer {{ margin-top: 30px; border-top: 1px solid #e2e8f0; padding-top: 10px; color: #a0aec0; font-size: 0.8rem; }}
    @media print {{ body {{ padding: 0; }} }}
</style>
</head>
<body>
<h1>🏥 RadimCare — Zdravotní report</h1>
<p><strong>Senior:</strong> {name} | <strong>Období:</strong> {days} dní | <strong>Vygenerováno:</strong> {now}</p>
"""

        # Medications
        if meds:
            html += '<h2>💊 Léky</h2><p>' + ', '.join(meds) + '</p>'

        # Team
        if team:
            html += '<h2>👥 Zdravotní tým</h2><table><tr><th>Jméno</th><th>Role</th></tr>'
            for t in team:
                role_name = MEDICAL_ROLES.get(t[1], {}).get('name', t[1])
                html += f'<tr><td>{t[0]}</td><td>{role_name}</td></tr>'
            html += '</table>'

        # Brain trend
        if brain_rows:
            avg_c = sum(float(r[1]) for r in brain_rows if r[1]) / len(brain_rows)
            total_msgs = sum(int(r[3]) for r in brain_rows)
            status_class = 'green' if avg_c < 12 else 'orange' if avg_c < 27 else 'red'
            status_text = 'stabilní' if avg_c < 12 else 'vyžaduje pozornost' if avg_c < 27 else 'kritické'

            html += f'<h2>🧠 Kognitivní trend</h2>'
            html += f'<p>Průměrné C: <strong class="{status_class}">{avg_c:.1f}</strong> — '
            html += f'<span class="{status_class}">{status_text}</span> | '
            html += f'Celkem zpráv: {total_msgs} | Dní s daty: {len(brain_rows)}</p>'

            html += '<table><tr><th>Datum</th><th>Avg C</th><th>Stress</th><th>Zpráv</th><th>Mode</th></tr>'
            for r in brain_rows:
                c_val = float(r[1]) if r[1] else 0
                c_class = 'green' if c_val < 12 else 'orange' if c_val < 27 else 'red'
                html += f'<tr><td>{r[0]}</td><td class="{c_class}">{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>'
            html += '</table>'
        else:
            html += '<h2>🧠 Kognitivní trend</h2><p>Zatím nemáme dostatek dat.</p>'

        html += f"""
<div class="footer">
    <p>RadimCare — Chytrá péče o seniory | www.radimcare.cz | {now}</p>
    <p>Tento report byl vygenerován automaticky systémem RadimCare.</p>
</div>
</body></html>"""

        return Response(html, mimetype='text/html')

    except Exception as e:
        return Response(f'<h1>Chyba</h1><p>{e}</p>', mimetype='text/html'), 500


# ============================================================================
# CLINICAL NOTES — structured medical records
# ============================================================================

CLINICAL_NOTES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS clinical_notes (
        id SERIAL PRIMARY KEY,
        senior_id TEXT NOT NULL,
        author_id TEXT NOT NULL,
        author_role TEXT,
        author_name TEXT,
        note_type TEXT DEFAULT 'observation',
        content TEXT NOT NULL,
        decision TEXT,
        next_step TEXT,
        responsible TEXT,
        review_date DATE,
        attachments JSONB DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_clinotes_senior ON clinical_notes(senior_id);
"""

def _init_clinical_schema():
    try:
        with db_context(commit=True) as db:
            for s in CLINICAL_NOTES_SCHEMA.strip().split(';'):
                s = s.strip()
                if s: db.execute(s)
    except Exception:
        pass


@medical_bp.route('/api/medical/notes/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def clinical_notes(senior_id):
    """Clinical notes — structured medical observations + decisions."""
    _init_clinical_schema()

    if request.method == 'GET':
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, author_name, author_role, note_type, content, decision, "
                    "next_step, responsible, review_date, created_at "
                    "FROM clinical_notes WHERE senior_id = ? ORDER BY created_at DESC LIMIT 50",
                    (senior_id,)
                ).fetchall()

            notes = [{
                'id': r[0], 'author': r[1], 'role': r[2], 'type': r[3],
                'content': r[4], 'decision': r[5], 'next_step': r[6],
                'responsible': r[7], 'review_date': str(r[8]) if r[8] else None,
                'date': str(r[9]),
            } for r in rows]

            return jsonify({'success': True, 'notes': notes, 'count': len(notes)})
        except Exception:
            return jsonify({'success': True, 'notes': [], 'count': 0})

    elif request.method == 'POST':
        data = request.json or {}
        auth = getattr(g, 'auth_user', {}) or {}

        content = data.get('content', '').strip()
        if not content:
            return jsonify({'success': False, 'error': 'Obsah poznámky je povinný'}), 400

        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO clinical_notes (senior_id, author_id, author_role, author_name, "
                    "note_type, content, decision, next_step, responsible, review_date) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (senior_id, str(auth.get('id', '')), data.get('role', auth.get('role', '')),
                     data.get('name', auth.get('name', '')),
                     data.get('type', 'observation'), content,
                     data.get('decision'), data.get('next_step'),
                     data.get('responsible'), data.get('review_date'))
                )

            try:
                from audit_log import log_audit, CREATE
                log_audit(CREATE, 'clinical_note', None, senior_id,
                          {'type': data.get('type'), 'has_decision': bool(data.get('decision'))})
            except Exception:
                pass

            return jsonify({'success': True, 'message': '📝 Klinická poznámka uložena'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Chyba'}), 500


# ============================================================================
# CARE PLAN — structured plan per senior
# ============================================================================

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
        notes TEXT,
        updated_by TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""

def _init_care_plan_schema():
    try:
        with db_context(commit=True) as db:
            for s in CARE_PLAN_SCHEMA.strip().split(';'):
                s = s.strip()
                if s: db.execute(s)
    except Exception:
        pass


@medical_bp.route('/api/medical/care-plan/<senior_id>', methods=['GET', 'PUT'])
@optional_auth
def care_plan(senior_id):
    """Care plan — goals, routine, metrics, risks, responsibilities."""
    _init_care_plan_schema()

    if request.method == 'GET':
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT goals, daily_routine, medications, monitored_metrics, risks, "
                    "responsibilities, notes, updated_by, updated_at FROM care_plans WHERE senior_id = ?",
                    (senior_id,)
                ).fetchone()

            if row:
                def _parse_json(val, default='[]'):
                    """Parse JSONB — may already be dict/list from psycopg2."""
                    if val is None: return json.loads(default)
                    if isinstance(val, (dict, list)): return val
                    try: return json.loads(val)
                    except: return json.loads(default)

                return jsonify({
                    'success': True,
                    'plan': {
                        'goals': _parse_json(row[0], '[]'),
                        'daily_routine': _parse_json(row[1], '{}'),
                        'medications': _parse_json(row[2], '[]'),
                        'monitored_metrics': _parse_json(row[3], '[]'),
                        'risks': _parse_json(row[4], '[]'),
                        'responsibilities': _parse_json(row[5], '{}'),
                        'notes': row[6] or '',
                        'updated_by': row[7] or '',
                        'updated_at': str(row[8]) if row[8] else '',
                    }
                })
            else:
                return jsonify({
                    'success': True,
                    'plan': {
                        'goals': [], 'daily_routine': {}, 'medications': [],
                        'monitored_metrics': [], 'risks': [], 'responsibilities': [], 'notes': '',
                    }
                })
        except Exception as e:
            logger.error(f"Care plan GET error: {e}")
            return jsonify({'success': True, 'plan': {}})

    elif request.method == 'PUT':
        data = request.json or {}
        auth = getattr(g, 'auth_user', {}) or {}

        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO care_plans (senior_id, goals, daily_routine, medications, "
                    "monitored_metrics, risks, responsibilities, notes, updated_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (senior_id) DO UPDATE SET "
                    "goals = EXCLUDED.goals, daily_routine = EXCLUDED.daily_routine, "
                    "medications = EXCLUDED.medications, monitored_metrics = EXCLUDED.monitored_metrics, "
                    "risks = EXCLUDED.risks, responsibilities = EXCLUDED.responsibilities, "
                    "notes = EXCLUDED.notes, updated_by = EXCLUDED.updated_by, updated_at = NOW()",
                    (senior_id,
                     json.dumps(data.get('goals', [])),
                     json.dumps(data.get('daily_routine', {})),
                     json.dumps(data.get('medications', [])),
                     json.dumps(data.get('monitored_metrics', [])),
                     json.dumps(data.get('risks', [])),
                     json.dumps(data.get('responsibilities', [])),
                     data.get('notes', ''),
                     auth.get('name', str(auth.get('id', ''))))
                )

            try:
                from audit_log import log_audit, UPDATE
                log_audit(UPDATE, 'care_plan', senior_id, senior_id)
            except Exception:
                pass

            return jsonify({'success': True, 'message': '📋 Plán péče aktualizován'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500



# ============================================================================
# 📹 MEDICAL VIDEO CALL — doctor calls senior
# ============================================================================

@medical_bp.route('/api/medical/video-call/<senior_id>', methods=['POST'])
@optional_auth
def medical_video_call(senior_id):
    """Doctor initiates video call to senior from medical module."""
    data = request.json or {}
    auth = getattr(g, 'auth_user', None) or {}
    caller_name = data.get('name', auth.get('name', 'Lékař'))
    role = data.get('role', 'coordinator')

    import time as _time
    room_code = f"radim-med-{role}-{int(_time.time())}"
    jitsi_url = f"https://meet.jit.si/{room_code}"

    # Notify senior via SocketIO
    try:
        from app import socketio
        role_name = MEDICAL_ROLES.get(role, {}).get('name', 'Lékař')
        socketio.emit('incoming_call', {
            'room_code': room_code,
            'jitsi_url': jitsi_url,
            'caller_name': f"{role_name}: {caller_name}",
            'call_type': 'video',
            'reason': 'medical',
            'senior_id': senior_id,
        }, room=senior_id)
    except Exception as e:
        logger.debug(f"Medical video SocketIO error: {e}")

    # Push notification
    try:
        from push_helpers import send_push_to_user
        send_push_to_user(senior_id, f'📹 {caller_name} vám volá (video)', 'Klikněte pro přijetí')
    except Exception:
        pass

    return jsonify({
        'success': True,
        'room_code': room_code,
        'jitsi_url': jitsi_url,
        'message': f'Video hovor zahájen — čekáme na seniora'
    })


#############################################################################
# SPRINT F — Team member edit/delete, symptoms, appointments
#############################################################################

@medical_bp.route('/api/medical/team/<senior_id>/<int:member_id>', methods=['PATCH'])
@optional_auth
def update_team_member(senior_id, member_id):
    """Update name/email/phone/role on an existing team member."""
    _init_medical_schema()
    data = request.get_json() or {}
    allowed = {'name', 'email', 'phone', 'role'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({'success': False, 'error': 'No updatable fields'}), 400
    if 'role' in updates and updates['role'] not in MEDICAL_ROLES:
        return jsonify({'success': False, 'error': 'Invalid role'}), 400

    try:
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        params = list(updates.values()) + [member_id, senior_id]
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE medical_team SET {set_clause} "
                f"WHERE id = ? AND senior_id = ?",
                tuple(params)
            )
        return jsonify({'success': True, 'updated': list(updates.keys())})
    except Exception as e:
        logger.error(f"Update member error: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@medical_bp.route('/api/medical/team/<senior_id>/<int:member_id>', methods=['DELETE'])
@optional_auth
def delete_team_member(senior_id, member_id):
    """Soft-delete: mark active=false."""
    _init_medical_schema()
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE medical_team SET active = false "
                "WHERE id = ? AND senior_id = ?",
                (member_id, senior_id)
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Delete member error: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@medical_bp.route('/api/medical/symptoms/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def medical_symptoms(senior_id):
    """Daily symptom check-in: 5 scores (0-10) + free-text note."""
    _init_medical_schema()

    if request.method == 'POST':
        data = request.get_json() or {}
        def _clamp(x):
            try: return max(0, min(10, int(x)))
            except: return None
        entry = {
            'pain': _clamp(data.get('pain')),
            'mood': _clamp(data.get('mood')),
            'sleep': _clamp(data.get('sleep')),
            'appetite': _clamp(data.get('appetite')),
            'energy': _clamp(data.get('energy')),
            'note': (data.get('note') or '')[:500],
        }
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO medical_symptoms "
                    "(senior_id, pain, mood, sleep, appetite, energy, note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (senior_id, entry['pain'], entry['mood'], entry['sleep'],
                     entry['appetite'], entry['energy'], entry['note'])
                )
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"Symptoms POST error: {e}")
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    # GET — last 30 entries, newest first
    limit = request.args.get('limit', 30, type=int)
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, pain, mood, sleep, appetite, energy, note, created_at "
                "FROM medical_symptoms WHERE senior_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (senior_id, limit)
            ).fetchall()
        def _v(r, i, k): return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        symptoms = [{
            'id': _v(r, 0, 'id'),
            'pain': _v(r, 1, 'pain'),
            'mood': _v(r, 2, 'mood'),
            'sleep': _v(r, 3, 'sleep'),
            'appetite': _v(r, 4, 'appetite'),
            'energy': _v(r, 5, 'energy'),
            'note': _v(r, 6, 'note') or '',
            'date': str(_v(r, 7, 'created_at') or ''),
        } for r in rows]
        return jsonify({'success': True, 'symptoms': symptoms, 'count': len(symptoms)})
    except Exception as e:
        return jsonify({'success': True, 'symptoms': [], 'count': 0})


@medical_bp.route('/api/medical/appointments/<senior_id>', methods=['GET', 'POST'])
@optional_auth
def medical_appointments(senior_id):
    """Telemedicine appointments. GET lists; POST inserts/upserts by id."""
    _init_medical_schema()

    if request.method == 'POST':
        data = request.get_json() or {}
        appt_id = data.get('id') or f"appt-{int(datetime.utcnow().timestamp()*1000):x}"
        with_member = (data.get('with') or '')[:200]
        when_str = data.get('when') or ''
        mode = data.get('mode', 'video')
        if mode not in ('video', 'phone', 'in-person'):
            mode = 'video'
        reason = (data.get('reason') or '')[:500]
        created_by = (data.get('created_by') or '')[:200]

        try:
            # Normalize to ISO timestamp
            when_at = datetime.fromisoformat(when_str.replace('Z', '+00:00')) if when_str else None
        except Exception:
            when_at = None

        try:
            with db_context(commit=True) as db:
                # Upsert by id
                if is_postgres():
                    db.execute(
                        "INSERT INTO medical_appointments "
                        "(id, senior_id, with_member, when_at, mode, reason, created_by) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "with_member = EXCLUDED.with_member, when_at = EXCLUDED.when_at, "
                        "mode = EXCLUDED.mode, reason = EXCLUDED.reason",
                        (appt_id, senior_id, with_member, when_at, mode, reason, created_by)
                    )
                else:
                    db.execute(
                        "INSERT OR REPLACE INTO medical_appointments "
                        "(id, senior_id, with_member, when_at, mode, reason, created_by) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (appt_id, senior_id, with_member, when_at, mode, reason, created_by)
                    )
            return jsonify({'success': True, 'id': appt_id})
        except Exception as e:
            logger.error(f"Appointment POST error: {e}")
            return jsonify({'success': False, 'error': str(e)[:100]}), 500

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, with_member, when_at, mode, reason, "
                "reminder_24h_sent, reminder_1h_sent, cancelled_at "
                "FROM medical_appointments "
                "WHERE senior_id = ? AND cancelled_at IS NULL "
                "ORDER BY when_at",
                (senior_id,)
            ).fetchall()
        def _v(r, i, k): return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        appts = [{
            'id': _v(r, 0, 'id'),
            'with': _v(r, 1, 'with_member'),
            'when': str(_v(r, 2, 'when_at') or ''),
            'mode': _v(r, 3, 'mode'),
            'reason': _v(r, 4, 'reason') or '',
            'reminder_24h_sent': bool(_v(r, 5, 'reminder_24h_sent')),
            'reminder_1h_sent': bool(_v(r, 6, 'reminder_1h_sent')),
        } for r in rows]
        return jsonify({'success': True, 'appointments': appts, 'count': len(appts)})
    except Exception as e:
        return jsonify({'success': True, 'appointments': [], 'count': 0})


@medical_bp.route('/api/medical/appointments/<senior_id>/<appt_id>', methods=['DELETE'])
@optional_auth
def cancel_appointment(senior_id, appt_id):
    """Soft-cancel an appointment."""
    _init_medical_schema()
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE medical_appointments SET cancelled_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND senior_id = ?",
                (appt_id, senior_id)
            )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@medical_bp.route('/api/medical/symptoms/<senior_id>/summary', methods=['POST'])
@optional_auth
def symptoms_summary(senior_id):
    """Gemini-powered weekly summary of symptom check-ins for the doctor.

    Returns a 3-5 sentence Czech summary safe to paste into a medical record.
    """
    import os
    days = request.args.get('days', 7, type=int)
    days = max(1, min(days, 30))

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT pain, mood, sleep, appetite, energy, note, created_at "
                "FROM medical_symptoms WHERE senior_id = ? "
                "AND created_at > CURRENT_TIMESTAMP - INTERVAL '%d days' "
                "ORDER BY created_at DESC" % days
                if is_postgres() else
                "SELECT pain, mood, sleep, appetite, energy, note, created_at "
                "FROM medical_symptoms WHERE senior_id = ? "
                "AND created_at > datetime('now', '-%d days') "
                "ORDER BY created_at DESC" % days,
                (senior_id,)
            ).fetchall()
    except Exception as e:
        logger.error(f"symptoms_summary DB error: {e}")
        return jsonify({'success': False, 'error': 'db_error'}), 500

    if not rows or len(rows) < 2:
        return jsonify({
            'success': True,
            'summary': 'Zatím je málo check-inů pro smysluplné shrnutí. Zkuste to za několik dní.',
            'source': 'fallback',
            'count': len(rows) if rows else 0,
        })

    def _v(r, i): return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
    entries = []
    for r in rows[:days]:
        entries.append({
            'date': str(_v(r, 6) or '')[:10],
            'pain': _v(r, 0), 'mood': _v(r, 1), 'sleep': _v(r, 2),
            'appetite': _v(r, 3), 'energy': _v(r, 4),
            'note': (_v(r, 5) or '')[:200],
        })

    def _avg(k):
        vals = [e[k] for e in entries if e.get(k) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    aggregates = {k: _avg(k) for k in ('pain', 'mood', 'sleep', 'appetite', 'energy')}

    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        summary = _rule_based_symptom_summary(entries, aggregates, days)
        return jsonify({'success': True, 'summary': summary, 'source': 'rule_based', 'count': len(entries)})

    prompt = (
        "Jsi lékařský asistent. Pacient (senior) vyplnil denní check-in za posledních "
        f"{days} dní. Napiš stručné shrnutí pro ošetřujícího lékaře v češtině, "
        "3-5 vět. Ukaž klíčové trendy (bolest, nálada, spánek, chuť, energie). "
        "Zmiň konkrétní změny či výkyvy. Buď věcný, neměl bys diagnostikovat. "
        "Pokud uživatel napsal poznámku, zmiň relevantní část. "
        "Pokud je vše stabilní, zmiň i to. Škála 0-10 (0 nejhorší, 10 nejlepší; "
        "u bolesti obráceně — 0 žádná, 10 silná).\n\n"
        f"DATA ({len(entries)} záznamů, nejnovější první):\n"
    )
    for e in entries:
        prompt += (
            f"- {e['date']}: bolest={e['pain']}, nálada={e['mood']}, "
            f"spánek={e['sleep']}, chuť={e['appetite']}, energie={e['energy']}"
        )
        if e['note']:
            prompt += f" | pozn.: {e['note']}"
        prompt += "\n"

    try:
        import requests as req
        resp = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 600},
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
                return jsonify({'success': True, 'summary': text, 'source': 'gemini', 'count': len(entries)})
    except Exception as e:
        logger.debug(f"gemini summary error: {e}")

    summary = _rule_based_symptom_summary(entries, aggregates, days)
    return jsonify({'success': True, 'summary': summary, 'source': 'rule_based_fallback', 'count': len(entries)})


def _rule_based_symptom_summary(entries, aggregates, days):
    """Deterministic Czech summary if Gemini unavailable."""
    n = len(entries)
    parts = [f"Pacient vyplnil {n} check-inů za posledních {days} dní."]
    labels = [('pain', 'bolest'), ('mood', 'nálada'), ('sleep', 'spánek'),
              ('appetite', 'chuť'), ('energy', 'energie')]
    for k, label in labels:
        a = aggregates.get(k)
        if a is not None:
            parts.append(f"Průměr {label}: {a}/10.")
    if aggregates.get('pain') is not None and aggregates['pain'] >= 7:
        parts.append("⚠️ Průměrná bolest vysoká — doporučeno posouzení.")
    if aggregates.get('mood') is not None and aggregates['mood'] <= 3:
        parts.append("⚠️ Nízká průměrná nálada — zvážit psychosociální podporu.")
    notes = [e['note'] for e in entries if e.get('note')]
    if notes:
        snippet = notes[0][:100]
        parts.append('Poznámek pacienta: ' + str(len(notes)) + '. Poslední: „' + snippet + '".')
    return ' '.join(parts)


#############################################################################
# SPRINT F-3 — Medication adherence (uses existing radim_medication_log)
#############################################################################

def _normalize_medications(meds):
    """Accept list of strings or list of dicts, return list of dicts:
       {name, dose, times:[HH:MM]}. Default times = ['08:00'] if missing.
    """
    normalized = []
    for m in (meds or []):
        if isinstance(m, str):
            normalized.append({'name': m.strip(), 'dose': None, 'times': ['08:00']})
        elif isinstance(m, dict):
            name = (m.get('name') or '').strip()
            if not name:
                continue
            times = m.get('times') or []
            if not isinstance(times, list) or not times:
                times = ['08:00']
            # Validate HH:MM format
            clean_times = []
            for t in times:
                try:
                    h, mm = str(t).split(':')
                    h, mm = int(h), int(mm)
                    if 0 <= h < 24 and 0 <= mm < 60:
                        clean_times.append(f"{h:02d}:{mm:02d}")
                except Exception:
                    pass
            if not clean_times:
                clean_times = ['08:00']
            normalized.append({
                'name': name,
                'dose': m.get('dose') or None,
                'times': clean_times,
            })
    return normalized


@medical_bp.route('/api/medical/medications/<senior_id>/today', methods=['GET'])
@optional_auth
def medications_today(senior_id):
    """Today's schedule + logged doses (from radim_medication_log)."""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT medications FROM care_plans WHERE senior_id = ?",
                (senior_id,)
            ).fetchone()
            raw = None
            if row:
                raw = row[0] if isinstance(row, (list, tuple)) else row.get('medications')
            try:
                meds_raw = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                meds_raw = []

            meds = _normalize_medications(meds_raw)

            # Today's log (since midnight local)
            if is_postgres():
                log_rows = db.execute(
                    "SELECT medication_name, dosage, taken_at, notes "
                    "FROM radim_medication_log "
                    "WHERE user_id = ? AND taken_at::date = CURRENT_DATE "
                    "ORDER BY taken_at DESC",
                    (senior_id,)
                ).fetchall()
            else:
                log_rows = db.execute(
                    "SELECT medication_name, dosage, taken_at, notes "
                    "FROM radim_medication_log "
                    "WHERE user_id = ? AND DATE(taken_at) = DATE('now') "
                    "ORDER BY taken_at DESC",
                    (senior_id,)
                ).fetchall()

        logged = []
        for r in log_rows or []:
            logged.append({
                'medication_name': r[0] if isinstance(r, (list, tuple)) else r.get('medication_name'),
                'dose': r[1] if isinstance(r, (list, tuple)) else r.get('dosage'),
                'taken_at': str(r[2] if isinstance(r, (list, tuple)) else r.get('taken_at') or ''),
                'notes': r[3] if isinstance(r, (list, tuple)) else r.get('notes'),
            })

        # Build per-dose slots (name + time) and mark taken if logged_at near time
        schedule = []
        for m in meds:
            for t in m['times']:
                slot_key = f"{m['name']}|{t}"
                was_taken = any(
                    (l.get('medication_name') or '').lower() == m['name'].lower() and
                    (l.get('notes') or '').startswith(f"slot:{t}")
                    for l in logged
                )
                schedule.append({
                    'key': slot_key,
                    'name': m['name'],
                    'dose': m['dose'],
                    'time': t,
                    'taken': was_taken,
                })

        # Sort by time
        schedule.sort(key=lambda x: x['time'])

        return jsonify({
            'success': True,
            'schedule': schedule,
            'logged': logged,
            'count': len(schedule),
            'taken_count': sum(1 for s in schedule if s['taken']),
        })
    except Exception as e:
        logger.error(f"medications_today error: {e}")
        return jsonify({'success': True, 'schedule': [], 'logged': [], 'count': 0, 'taken_count': 0})


@medical_bp.route('/api/medical/medications/<senior_id>/log', methods=['POST'])
@optional_auth
def log_medication(senior_id):
    """Mark a medication dose as taken."""
    data = request.get_json() or {}
    name = (data.get('medication_name') or '').strip()
    dose = data.get('dose') or ''
    time_slot = data.get('time_slot') or ''
    note = (data.get('note') or '')[:200]
    if not name:
        return jsonify({'success': False, 'error': 'medication_name required'}), 400

    # Encode the scheduled time_slot into notes for correlation
    notes_field = f"slot:{time_slot}" + (f" | {note}" if note else '') if time_slot else note

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO radim_medication_log (user_id, medication_name, dosage, notes) "
                "VALUES (?, ?, ?, ?)",
                (senior_id, name, dose, notes_field)
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"log_medication error: {e}")
        return jsonify({'success': False, 'error': str(e)[:100]}), 500


@medical_bp.route('/api/medical/medications/<senior_id>/adherence', methods=['GET'])
@optional_auth
def medications_adherence(senior_id):
    """Per-day adherence for the last N days."""
    days = max(1, min(request.args.get('days', 7, type=int), 30))

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT medications FROM care_plans WHERE senior_id = ?",
                (senior_id,)
            ).fetchone()
            raw = None
            if row:
                raw = row[0] if isinstance(row, (list, tuple)) else row.get('medications')
            try:
                meds_raw = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                meds_raw = []
            meds = _normalize_medications(meds_raw)
            expected_per_day = sum(len(m['times']) for m in meds)

            # Count logs per day
            if is_postgres():
                log_rows = db.execute(
                    "SELECT taken_at::date AS day, COUNT(*) AS n "
                    "FROM radim_medication_log "
                    "WHERE user_id = ? AND taken_at > CURRENT_DATE - INTERVAL '%d days' "
                    "GROUP BY day ORDER BY day" % days,
                    (senior_id,)
                ).fetchall()
            else:
                log_rows = db.execute(
                    "SELECT DATE(taken_at) AS day, COUNT(*) AS n "
                    "FROM radim_medication_log "
                    "WHERE user_id = ? AND taken_at > datetime('now', '-%d days') "
                    "GROUP BY day ORDER BY day" % days,
                    (senior_id,)
                ).fetchall()

        by_day = {}
        for r in log_rows or []:
            day = r[0] if isinstance(r, (list, tuple)) else r.get('day')
            n = r[1] if isinstance(r, (list, tuple)) else r.get('n')
            by_day[str(day)] = int(n)

        from datetime import date, timedelta as _td
        today = date.today()
        daily = []
        for i in range(days - 1, -1, -1):
            d = today - _td(days=i)
            d_str = d.strftime('%Y-%m-%d')
            taken = by_day.get(d_str, 0)
            daily.append({
                'date': d_str,
                'taken': taken,
                'expected': expected_per_day,
                'pct': round((taken / expected_per_day) * 100) if expected_per_day else 0,
            })

        total_taken = sum(d['taken'] for d in daily)
        total_expected = expected_per_day * days
        return jsonify({
            'success': True,
            'daily': daily,
            'expected_per_day': expected_per_day,
            'total_taken': total_taken,
            'total_expected': total_expected,
            'adherence_pct': round((total_taken / total_expected) * 100) if total_expected else 0,
        })
    except Exception as e:
        logger.error(f"medications_adherence error: {e}")
        return jsonify({'success': True, 'daily': [], 'expected_per_day': 0, 'total_taken': 0, 'adherence_pct': 0})


def appointment_reminder_cron():
    """Runs every 10 min. Sends push 24h and 1h before upcoming appointments."""
    try:
        from notification_helpers import notify
    except Exception:
        return

    now = datetime.utcnow()
    t_24h_lo = now + timedelta(hours=23, minutes=55)
    t_24h_hi = now + timedelta(hours=24, minutes=5)
    t_1h_lo  = now + timedelta(minutes=55)
    t_1h_hi  = now + timedelta(minutes=65)

    try:
        with db_context(commit=True) as db:
            # 24h window
            rows_24h = db.execute(
                "SELECT id, senior_id, with_member, when_at, mode FROM medical_appointments "
                "WHERE cancelled_at IS NULL AND reminder_24h_sent = FALSE "
                "AND when_at BETWEEN ? AND ?",
                (t_24h_lo, t_24h_hi)
            ).fetchall()
            rows_1h = db.execute(
                "SELECT id, senior_id, with_member, when_at, mode FROM medical_appointments "
                "WHERE cancelled_at IS NULL AND reminder_1h_sent = FALSE "
                "AND when_at BETWEEN ? AND ?",
                (t_1h_lo, t_1h_hi)
            ).fetchall()

            def _v(r, i): return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
            mode_icon = {'video': '📹', 'phone': '📞', 'in-person': '🏥'}

            for r in rows_24h or []:
                aid, sid, who, when_at, mode = _v(r, 0), _v(r, 1), _v(r, 2), _v(r, 3), _v(r, 4)
                try:
                    notify(
                        to_user_id=sid, type='reminder',
                        title=f"{mode_icon.get(mode, '📅')} Zítra máte schůzku",
                        body=f"S {who or 'členem týmu'} — {when_at}",
                        severity='info'
                    )
                    db.execute(
                        "UPDATE medical_appointments SET reminder_24h_sent = TRUE WHERE id = ?",
                        (aid,)
                    )
                except Exception as e:
                    logger.debug(f"appt 24h reminder failed: {e}")

            for r in rows_1h or []:
                aid, sid, who, when_at, mode = _v(r, 0), _v(r, 1), _v(r, 2), _v(r, 3), _v(r, 4)
                try:
                    notify(
                        to_user_id=sid, type='reminder',
                        title=f"{mode_icon.get(mode, '📅')} Za hodinu schůzka",
                        body=f"S {who or 'členem týmu'} — {when_at}",
                        severity='warning'
                    )
                    db.execute(
                        "UPDATE medical_appointments SET reminder_1h_sent = TRUE WHERE id = ?",
                        (aid,)
                    )
                except Exception as e:
                    logger.debug(f"appt 1h reminder failed: {e}")
    except Exception as e:
        logger.debug(f"appointment_reminder_cron error: {e}")


def symptom_trend_alert_cron():
    """Runs daily. Creates medical_alert when pain>=7 or mood<=3 for 3 consecutive days."""
    try:
        with db_context(commit=True) as db:
            rows = db.execute(
                "SELECT DISTINCT senior_id FROM medical_symptoms "
                "WHERE created_at > CURRENT_TIMESTAMP - INTERVAL '5 days'"
                if is_postgres() else
                "SELECT DISTINCT senior_id FROM medical_symptoms "
                "WHERE created_at > datetime('now', '-5 days')"
            ).fetchall()
            senior_ids = [r[0] if isinstance(r, (list, tuple)) else r.get('senior_id') for r in rows]

            for sid in senior_ids:
                recent = db.execute(
                    "SELECT pain, mood, created_at FROM medical_symptoms "
                    "WHERE senior_id = ? ORDER BY created_at DESC LIMIT 3",
                    (sid,)
                ).fetchall()
                if len(recent) < 3:
                    continue
                pains = [(r[0] if isinstance(r, (list, tuple)) else r.get('pain')) or 0 for r in recent]
                moods = [(r[1] if isinstance(r, (list, tuple)) else r.get('mood')) or 10 for r in recent]

                high_pain = all(p >= 7 for p in pains)
                low_mood = all(m <= 3 for m in moods)
                if not (high_pain or low_mood):
                    continue

                alert_type = 'symptom_pain_trend' if high_pain else 'symptom_mood_trend'
                # Dedup: skip if same alert exists from last 24h
                exists = db.execute(
                    "SELECT 1 FROM medical_alerts WHERE senior_id = ? AND alert_type = ? "
                    "AND created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'"
                    if is_postgres() else
                    "SELECT 1 FROM medical_alerts WHERE senior_id = ? AND alert_type = ? "
                    "AND created_at > datetime('now', '-24 hours')",
                    (sid, alert_type)
                ).fetchone()
                if exists:
                    continue

                msg = (f"Pacient hlásí bolest ≥7/10 tři dny v řadě ({pains[2]}, {pains[1]}, {pains[0]})"
                       if high_pain else
                       f"Pacient hlásí sníženou náladu (≤3/10) tři dny v řadě ({moods[2]}, {moods[1]}, {moods[0]})")
                db.execute(
                    "INSERT INTO medical_alerts (senior_id, alert_type, severity, message) "
                    "VALUES (?, ?, ?, ?)",
                    (sid, alert_type, 'warning', msg)
                )
                try:
                    from notification_helpers import notify
                    notify(to_user_id=sid, type='health_alert',
                           title='⚠️ Trend v check-inu', body=msg, severity='warning')
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"symptom_trend_alert_cron error: {e}")


logger.info("🏥 Medical Team v5.0 loaded — Sprint F: symptoms, appointments, edit/delete, reminders")
