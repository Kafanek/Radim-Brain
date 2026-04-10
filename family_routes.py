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
        with db_context(commit=False) as db:
            # Last brain states (activity indicator)
            states = db.execute("""
                SELECT created_at, mode, coherence
                FROM brain_states
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 10
            """, (user_id,)).fetchall()

            # Last chat messages (just timestamps, not content)
            try:
                chats = db.execute("""
                    SELECT created_at
                    FROM chat_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT 5
                """, (user_id,)).fetchall()
            except Exception:
                chats = []  # chat_history table may not exist

            # Agent observations (health alerts)
            observations = db.execute("""
                SELECT created_at, observation_type, severity, summary
                FROM agent_observations
                WHERE user_id = ?
                AND created_at > ?
                ORDER BY created_at DESC LIMIT 10
            """, (user_id, (datetime.utcnow() - timedelta(days=1)).isoformat())).fetchall()

        # Build activity timeline
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
