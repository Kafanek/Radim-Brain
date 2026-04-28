# ============================================
# 👨‍👩‍👧 FAMILY ROUTES — Activity feed for family members
# ============================================
# Family can see senior's activity (not content, just timestamps).
# "Máma je aktivní, poslední aktivita 14:30"
# Photo sharing between senior ↔ family.
# ============================================

import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from auth_middleware import optional_auth
from database import db_context

logger = logging.getLogger(__name__)

family_bp = Blueprint('family', __name__, url_prefix='/api/family')


@family_bp.route('/activity/<user_id>', methods=['GET'])
@optional_auth
def get_activity(user_id):
    """Get senior's recent activity summary for family dashboard.

    Returns activity categories (not content) for privacy.
    Family sees: "chat at 14:30", "music at 15:00" — not WHAT was said/played.
    """
    try:
        states = []
        observations = []

        try:
            with db_context(commit=False) as db:
                states = db.execute("""
                    SELECT created_at, mode, coherence
                    FROM brain_states
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT 10
                """, (user_id,)).fetchall()
        except Exception:
            pass

        try:
            with db_context(commit=False) as db:
                observations = db.execute("""
                    SELECT created_at, observation_type, severity, summary
                    FROM agent_observations
                    WHERE user_id = ?
                    AND created_at > ?
                    ORDER BY created_at DESC LIMIT 10
                """, (user_id, (datetime.utcnow() - timedelta(days=1)).isoformat())).fetchall()
        except Exception:
            pass

        # Build activity timeline
        chats = []  # chat_history not used (table may not exist)
        activities = []

        if states:
            last = states[0]
            activities.append({
                'type': 'brain_active',
                'time': last[0],
                'detail': f'Mozek: {last[1]} (C={last[2]:.1f})'
            })

        for chat in (chats or []):
            activities.append({
                'type': 'chat',
                'time': chat[0],
                'detail': 'Konverzace s Radimem'
            })

        for obs in (observations or []):
            activities.append({
                'type': 'observation',
                'time': obs[0],
                'severity': obs[2],
                'detail': obs[3] or obs[1]
            })

        # Sort by time desc
        activities.sort(key=lambda a: a.get('time', ''), reverse=True)

        # Status summary
        is_active = False
        last_active = None
        if states:
            last_time = datetime.fromisoformat(states[0][0].replace('Z', '+00:00')) if isinstance(states[0][0], str) else states[0][0]
            is_active = (datetime.utcnow() - last_time.replace(tzinfo=None)).total_seconds() < 600  # 10 min
            last_active = states[0][0]

        alerts = [o for o in (observations or []) if o[2] in ('WARNING', 'ALERT', 'CRISIS')]

        return jsonify({
            'success': True,
            'user_id': user_id,
            'is_active': is_active,
            'last_active': last_active,
            'today_interactions': len(chats or []),
            'alerts': [{
                'severity': a[2],
                'summary': a[3] or a[1],
                'time': a[0]
            } for a in alerts],
            'activities': activities[:15],
            'generated_at': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.warning(f'Family activity error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@family_bp.route('/checkin/<user_id>', methods=['GET'])
@optional_auth
def daily_checkin(user_id):
    """Simple daily check-in: Is the senior OK today?

    Returns: active/inactive, mood, last interaction, any alerts.
    Designed for family push notification: "Máma je aktivní od 8:30"
    """
    try:
        today = datetime.utcnow().date().isoformat()

        with db_context(commit=False) as db:
            # Today's brain states
            row = db.execute("""
                SELECT COUNT(*), MAX(created_at), AVG(coherence)
                FROM brain_states
                WHERE user_id = ? AND created_at >= ?
            """, (user_id, today)).fetchone()
            count = (row[0] or 0) if row else 0
            last_time = row[1] if row else None
            avg_c = row[2] if row else None

            # Any alerts today
            alert_row = db.execute("""
                SELECT COUNT(*)
                FROM agent_observations
                WHERE user_id = ? AND created_at >= ? AND severity IN ('WARNING', 'ALERT', 'CRISIS')
            """, (user_id, today)).fetchone()
            alert_count = (alert_row[0] or 0) if alert_row else 0

        status = 'active' if count > 0 else 'inactive'
        mood = 'good'
        if avg_c and avg_c < 3.0:
            mood = 'low'
        elif avg_c and avg_c > 5.0:
            mood = 'great'

        return jsonify({
            'success': True,
            'user_id': user_id,
            'date': today,
            'status': status,
            'interactions_today': count,
            'last_active': last_time,
            'mood': mood,
            'avg_coherence': round(avg_c, 1) if avg_c else None,
            'alerts_today': alert_count,
            'message': _build_checkin_message(status, count, last_time, mood, alert_count)
        })

    except Exception as e:
        logger.warning(f'Family checkin error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


def _build_checkin_message(status, count, last_time, mood, alerts):
    """Build human-readable Czech check-in message."""
    if status == 'inactive':
        return 'Dnes zatím žádná aktivita. Možná ještě spí nebo nebyl online.'

    time_str = ''
    if last_time:
        try:
            t = datetime.fromisoformat(str(last_time).replace('Z', '+00:00'))
            time_str = t.strftime('%H:%M')
        except Exception:
            time_str = '?'

    mood_map = {'great': 'výborná', 'good': 'dobrá', 'low': 'mírně snížená'}
    mood_text = mood_map.get(mood, 'normální')

    msg = f'Poslední aktivita v {time_str}. '
    msg += f'Dnes {count} interakcí. '
    msg += f'Nálada: {mood_text}. '

    if alerts > 0:
        msg += f'⚠️ {alerts} upozornění dnes!'

    return msg


# ============================================
# 🔧 REMOTE MANAGEMENT — family configures senior's app
# ============================================

@family_bp.route('/remote/profile/<user_id>', methods=['GET'])
@optional_auth
def get_remote_profile(user_id):
    """Family reads senior's profile for remote management."""
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(user_id) or {}
        # Return only safe fields (not passwords/tokens)
        safe = {
            'name': profile.get('name', ''),
            'age_group': profile.get('age_group', ''),
            'medications_list': profile.get('medications_list', []),
            'medication_times': profile.get('medication_times', {}),
            'contacts': profile.get('contacts', []),
            'hearing': profile.get('hearing', 'normal'),
            'vision': profile.get('vision', 'normal'),
            'memory': profile.get('memory', 'normal'),
        }
        return jsonify({'success': True, 'profile': safe})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@family_bp.route('/remote/profile/<user_id>', methods=['PUT'])
@optional_auth
def update_remote_profile(user_id):
    """Family updates senior's profile remotely.

    Body: { "medications_list": [...], "contacts": [...], ... }
    Only whitelisted fields can be updated.
    """
    data = request.json or {}
    ALLOWED_FIELDS = ['name', 'age_group', 'medications_list', 'medication_times',
                      'contacts', 'hearing', 'vision', 'memory']

    try:
        from memory_helpers import db_load_profile, db_save_profile
        profile = db_load_profile(user_id) or {}

        updated = []
        for field in ALLOWED_FIELDS:
            if field in data:
                profile[field] = data[field]
                updated.append(field)

        if updated:
            db_save_profile(user_id, profile)
            logger.info(f"👨‍👩‍👧 Remote profile update for {user_id}: {updated}")

        return jsonify({
            'success': True,
            'updated_fields': updated,
            'message': f'Aktualizováno: {", ".join(updated)}' if updated else 'Žádné změny'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@family_bp.route('/remote/settings/<user_id>', methods=['GET', 'PUT'])
@optional_auth
def remote_settings(user_id):
    """Family reads/updates senior's app settings remotely.

    Settings stored in memory_learning JSONB under 'remote_settings' key.
    """
    try:
        with db_context(commit=(request.method == 'PUT')) as db:
            if request.method == 'GET':
                row = db.execute(
                    "SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)
                ).fetchone()
                settings = {}
                if row:
                    import json
                    learning = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                    settings = learning.get('remote_settings', {})
                return jsonify({'success': True, 'settings': settings})

            else:  # PUT
                data = request.json or {}
                row = db.execute(
                    "SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)
                ).fetchone()
                import json
                learning = {}
                if row:
                    learning = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                learning['remote_settings'] = data
                db.execute(
                    "UPDATE memory_learning SET data = ?, updated_at = ? WHERE user_id = ?",
                    (json.dumps(learning), datetime.utcnow().isoformat(), user_id)
                )
                return jsonify({'success': True, 'message': 'Nastavení aktualizováno'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================
# 🧠 COGNITIVE ASSESSMENT
# ============================================

@family_bp.route('/cognitive/<user_id>', methods=['GET'])
@optional_auth
def get_cognitive_assessment(user_id):
    """Get cognitive assessment score and history.

    Returns score (0-100), trend, signals, recommendations.
    Used by family to monitor cognitive health over time.
    """
    try:
        from cognitive_assessment import compute_cognitive_score, get_cognitive_history
        score = compute_cognitive_score(user_id)
        history = get_cognitive_history(user_id, days=90)
        return jsonify({
            'success': True,
            **score,
            'history': history
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@family_bp.route('/photos', methods=['POST'])
@optional_auth
def share_photo():
    """Senior shares a photo with family.

    Body: { "user_id": "...", "photo_url": "...", "caption": "..." }
    Stores in DB + sends push to family contacts.
    """
    data = request.json or {}
    user_id = data.get('user_id', '')
    photo_url = data.get('photo_url', '')
    caption = data.get('caption', '')

    if not user_id or not photo_url:
        return jsonify({'success': False, 'error': 'user_id and photo_url required'}), 400

    try:
        with db_context(commit=True) as db:
            db.execute("""
                INSERT INTO family_shared_photos (user_id, photo_url, caption, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, photo_url, caption, datetime.utcnow().isoformat()))

        # Try to notify family contacts via push
        try:
            from push_helpers import send_push_to_user
            # Get family contacts from memory_profiles
            with db_context(commit=False) as db:
                db.execute("SELECT data FROM memory_profiles WHERE user_id = ?", (user_id,))
                row = db.fetchone()
                if row:
                    import json
                    profile = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    contacts = profile.get('contacts', [])
                    senior_name = profile.get('name', 'Senior')
                    for contact in contacts:
                        if contact.get('canReceiveAlerts'):
                            # Notify via push if they have app
                            pass  # Future: push to family app
        except Exception:
            pass

        return jsonify({
            'success': True,
            'message': 'Fotka sdílena s rodinou!'
        })

    except Exception as e:
        logger.warning(f'Photo share error: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


@family_bp.route('/photos/<user_id>', methods=['GET'])
@optional_auth
def get_shared_photos(user_id):
    """Get photos shared by senior for family viewing."""
    try:
        with db_context(commit=False) as db:
            try:
                photos = db.execute("""
                    SELECT photo_url, caption, created_at
                    FROM family_shared_photos
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT 20
                """, (user_id,)).fetchall()
            except Exception:
                photos = []  # Table may not exist yet

        return jsonify({
            'success': True,
            'photos': [{
                'url': p[0],
                'caption': p[1],
                'time': p[2]
            } for p in (photos or [])]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================
# 🎯 ACTIVITY PROPOSALS — Family → Senior workflow
# ============================================
# Family member proposes activity → Senior sees notification → Accept/Reject
# Accepted proposals auto-open the module + notify family
# Rejected/expired proposals notify family with reason
# ============================================

VALID_ACTIVITIES = {
    'quiz': 'Kvíz',
    'exercises': 'Cvičení',
    'music': 'Hudba',
    'stories': 'Příběhy',
    'news': 'Novinky',
    'calls': 'Videohovor',
    'walk': 'Procházka',
    'medication': 'Léky',
    'hydration': 'Pití',
    'custom': 'Vlastní aktivita',
}


def _ensure_proposals_table():
    """Create proposals table if not exists (auto-migration)."""
    try:
        with db_context(commit=True) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS family_activity_proposals (
                    id SERIAL PRIMARY KEY,
                    senior_id TEXT NOT NULL,
                    proposed_by TEXT NOT NULL,
                    proposed_by_name TEXT DEFAULT '',
                    activity_type TEXT NOT NULL,
                    activity_title TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    reasoning TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    responded_at TIMESTAMP,
                    response_note TEXT DEFAULT '',
                    expires_at TIMESTAMP
                )
            """)
    except Exception as e:
        logger.debug(f"Proposals table creation: {e}")


@family_bp.route('/proposals/<senior_id>', methods=['POST'])
@optional_auth
def create_proposal(senior_id):
    """Family member proposes an activity for the senior.

    POST /api/family/proposals/<senior_id>
    Body: {
        "activity_type": "quiz|exercises|music|...|custom",
        "title": "Paměťový kvíz",
        "description": "Zkus paměťový kvíz",
        "reasoning": "Paní doktorka doporučila",
        "proposed_by": "family-member-id",
        "proposed_by_name": "Jana"
    }
    """
    _ensure_proposals_table()
    try:
        data = request.get_json(silent=True) or {}
        activity = data.get('activity_type', '').strip()
        if activity not in VALID_ACTIVITIES:
            return jsonify({
                'success': False,
                'error': f'Neplatný typ aktivity. Povolené: {", ".join(VALID_ACTIVITIES.keys())}'
            }), 400

        proposed_by = data.get('proposed_by', 'family')
        proposed_by_name = data.get('proposed_by_name', 'Rodina')
        title = data.get('title', VALID_ACTIVITIES.get(activity, activity))
        description = data.get('description', '')
        reasoning = data.get('reasoning', '')

        # Expire in 24 hours
        expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()

        with db_context(commit=True) as db:
            # Check for duplicate pending proposals
            existing = db.execute("""
                SELECT COUNT(*) FROM family_activity_proposals
                WHERE senior_id = ? AND activity_type = ? AND status = 'pending'
            """, (senior_id, activity)).fetchone()

            if existing and existing[0] > 0:
                return jsonify({
                    'success': False,
                    'error': 'Tato aktivita je už navržena a čeká na schválení.'
                }), 409

            db.execute("""
                INSERT INTO family_activity_proposals
                (senior_id, proposed_by, proposed_by_name, activity_type,
                 activity_title, description, reasoning, status, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (senior_id, proposed_by, proposed_by_name, activity,
                  title, description, reasoning, expires_at))

        logger.info(f"📋 Proposal: {proposed_by_name} → {senior_id}: {activity}")

        # Push notification to senior via SocketIO
        try:
            from flask_socketio import emit
            from app import socketio
            socketio.emit('family_proposal', {
                'type': 'activity_proposal',
                'activity': activity,
                'title': title,
                'from': proposed_by_name,
                'description': description
            }, room=senior_id)
        except Exception:
            pass

        return jsonify({
            'success': True,
            'message': f'Návrh "{title}" odeslán seniorovi.',
            'activity_type': activity
        })

    except Exception as e2:
        logger.error(f"Proposal create error: {e2}")
        return jsonify({'success': False, 'error': str(e2)}), 500


@family_bp.route('/proposals/<senior_id>', methods=['GET'])
@optional_auth
def get_proposals(senior_id):
    """Get all activity proposals for a senior.

    GET /api/family/proposals/<senior_id>?status=pending
    """
    _ensure_proposals_table()
    try:
        status_filter = request.args.get('status', '')

        with db_context(commit=False) as db:
            if status_filter:
                rows = db.execute("""
                    SELECT id, activity_type, activity_title, description, reasoning,
                           proposed_by_name, status, created_at, responded_at,
                           response_note, expires_at
                    FROM family_activity_proposals
                    WHERE senior_id = ? AND status = ?
                    ORDER BY created_at DESC LIMIT 50
                """, (senior_id, status_filter)).fetchall()
            else:
                rows = db.execute("""
                    SELECT id, activity_type, activity_title, description, reasoning,
                           proposed_by_name, status, created_at, responded_at,
                           response_note, expires_at
                    FROM family_activity_proposals
                    WHERE senior_id = ?
                    ORDER BY created_at DESC LIMIT 50
                """, (senior_id,)).fetchall()

        now = datetime.utcnow()
        proposals = []
        for r in (rows or []):
            p = {
                'id': r[0], 'activity_type': r[1], 'title': r[2],
                'description': r[3], 'reasoning': r[4], 'from': r[5],
                'status': r[6], 'created_at': r[7], 'responded_at': r[8],
                'response_note': r[9], 'expires_at': r[10],
                'activity_label': VALID_ACTIVITIES.get(r[1], r[1])
            }
            # Auto-expire old pending proposals
            if p['status'] == 'pending' and p['expires_at']:
                try:
                    exp = datetime.fromisoformat(str(p['expires_at']).replace('Z', ''))
                    if now > exp:
                        p['status'] = 'expired'
                        _update_proposal_status(p['id'], 'expired', 'Vypršelo (24h)')
                except Exception:
                    pass
            proposals.append(p)

        return jsonify({
            'success': True,
            'proposals': proposals,
            'pending_count': sum(1 for p in proposals if p['status'] == 'pending')
        })

    except Exception as e3:
        return jsonify({'success': False, 'error': str(e3)}), 500


@family_bp.route('/proposals/<senior_id>/<int:proposal_id>', methods=['PUT'])
@optional_auth
def respond_to_proposal(senior_id, proposal_id):
    """Senior accepts or rejects a proposal.

    PUT /api/family/proposals/<senior_id>/<proposal_id>
    Body: { "action": "accept" | "reject", "note": "Díky, hned to zkusím" }
    """
    try:
        data = request.get_json(silent=True) or {}
        action = data.get('action', '').strip().lower()
        note = data.get('note', '')

        if action not in ('accept', 'reject'):
            return jsonify({'success': False, 'error': 'Akce musí být accept nebo reject'}), 400

        new_status = 'accepted' if action == 'accept' else 'rejected'
        _update_proposal_status(proposal_id, new_status, note)

        # Get proposal details
        with db_context(commit=False) as db:
            row = db.execute("""
                SELECT activity_type, activity_title, proposed_by, proposed_by_name
                FROM family_activity_proposals WHERE id = ?
            """, (proposal_id,)).fetchone()

        activity_type = row[0] if row else ''
        activity_title = row[1] if row else ''
        proposed_by = row[2] if row else ''

        # Notify family via SocketIO
        try:
            from flask_socketio import emit
            from app import socketio
            socketio.emit('proposal_response', {
                'proposal_id': proposal_id,
                'status': new_status,
                'activity': activity_type,
                'note': note,
                'senior_id': senior_id
            }, room=proposed_by)
        except Exception:
            pass

        result = {
            'success': True,
            'status': new_status,
            'message': f'Aktivita "{activity_title}" {"přijata" if action == "accept" else "odmítnuta"}.'
        }
        if action == 'accept' and activity_type in VALID_ACTIVITIES:
            result['open_module'] = activity_type

        logger.info(f"📋 Proposal #{proposal_id}: {new_status} by {senior_id}")
        return jsonify(result)

    except Exception as e4:
        return jsonify({'success': False, 'error': str(e4)}), 500


def _update_proposal_status(proposal_id, status, note=''):
    """Update proposal status in DB."""
    try:
        with db_context(commit=True) as db:
            db.execute("""
                UPDATE family_activity_proposals
                SET status = ?, responded_at = ?, response_note = ?
                WHERE id = ?
            """, (status, datetime.utcnow().isoformat(), note, proposal_id))
    except Exception as e:
        logger.debug(f"Proposal status update error: {e}")


def get_pending_proposals(senior_id):
    """Get pending proposals for orchestrator context injection."""
    try:
        _ensure_proposals_table()
        with db_context(commit=False) as db:
            rows = db.execute("""
                SELECT activity_title, proposed_by_name, reasoning
                FROM family_activity_proposals
                WHERE senior_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 5
            """, (senior_id,)).fetchall()

        if not rows:
            return ''

        lines = [f'Rodina navrhuje: {r[0]} (od: {r[1]}' +
                 (f', důvod: {r[2]}' if r[2] else '') + ')'
                 for r in rows]
        return 'NÁVRHY OD RODINY:\n' + '\n'.join(lines)

    except Exception:
        return ''


logger.info("👨‍👩‍👧 Family proposals workflow loaded — propose → approve/reject → notify")
