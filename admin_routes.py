# ============================================
# ADMIN, WORDPRESS, AI SETTINGS, STUBS, CLIENT/EMERGENCY ROUTES
# ============================================
# Extracted from app.py — Blueprint: admin_bp

import os
import json
import uuid
import logging
import requests as http_requests
from datetime import datetime
from flask import Blueprint, request, jsonify

from database import get_db_for_flask
from auth_middleware import require_auth
from rate_limiter import rate_limit
from utils import generate_id, now_iso, today_date

logger = logging.getLogger(__name__)

admin_bp = Blueprint('admin', __name__)

# ============================================
# ENV VARS
# ============================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')


# ============================================
# LAZY IMPORTS FROM app.py (avoid circular)
# ============================================
def _get_app_helpers():
    """Lazy import to avoid circular imports."""
    import app as _app
    return _app.users_online, _app.get_ai_response, _app.get_wp_user, _app.sync_wp_user


# ============================================
# HELPERS
# ============================================
def get_db():
    return get_db_for_flask()



def update_daily_stats(field):
    ALLOWED_FIELDS = {'total_messages', 'total_users', 'ai_messages', 'voice_messages', 'active_conversations'}
    if field not in ALLOWED_FIELDS:
        logger.warning(f"Invalid stats field: {field}")
        return
    try:
        db = get_db()
        today = today_date()
        db.execute(f'''
            INSERT INTO admin_stats (id, date, {field})
            VALUES (?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1
        ''', (generate_id(), today))
        db.commit()
    except Exception as e:
        logger.error(f"Stats update error: {e}")


# ============================================
# ADMIN ENDPOINTS
# ============================================
@admin_bp.route('/api/admin/stats', methods=['GET'])
@require_auth
def get_admin_stats():
    try:
        users_online, _, _, _ = _get_app_helpers()
        days = request.args.get('days', 7, type=int)
        db = get_db()
        cursor = db.execute('SELECT * FROM admin_stats ORDER BY date DESC LIMIT ?', (days,))
        daily_stats = [dict(row) for row in cursor.fetchall()]
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_messages')
        total_messages = cursor.fetchone()['count']
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_users WHERE role != "ai_assistant"')
        total_users = cursor.fetchone()['count']
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_conversations')
        total_conversations = cursor.fetchone()['count']
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_messages WHERE ai_generated = 1')
        ai_messages = cursor.fetchone()['count']
        active_users = len(users_online)
        cursor = db.execute('''
            SELECT m.*, u.name as sender_name
            FROM chat_messages m
            LEFT JOIN chat_users u ON m.sender_id = u.id
            ORDER BY m.timestamp DESC LIMIT 20
        ''')
        recent_messages = [dict(row) for row in cursor.fetchall()]
        return jsonify({
            'success': True,
            'stats': {
                'totals': {
                    'messages': total_messages, 'users': total_users,
                    'conversations': total_conversations, 'ai_messages': ai_messages,
                    'active_users': active_users
                },
                'daily': daily_stats,
                'recent_activity': recent_messages
            }
        })
    except Exception as e:
        logger.error(f"Admin stats error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@admin_bp.route('/api/admin/users', methods=['GET'])
@require_auth
def get_admin_users():
    try:
        users_online, _, _, _ = _get_app_helpers()
        db = get_db()
        cursor = db.execute('''
            SELECT u.*,
                   (SELECT COUNT(*) FROM chat_messages WHERE sender_id = u.id) as message_count,
                   (SELECT COUNT(*) FROM chat_conversations WHERE participants LIKE '%"' || u.id || '"%') as conversation_count
            FROM chat_users u
            ORDER BY u.created_at DESC
        ''')
        users = [dict(row) for row in cursor.fetchall()]
        for user in users:
            user['online'] = user['id'] in users_online
            user['settings'] = json.loads(user['settings']) if user['settings'] else {}
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        logger.error(f"Admin users error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@admin_bp.route('/api/admin/conversations', methods=['GET'])
@require_auth
def get_admin_conversations():
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT c.*,
                   (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
            FROM chat_conversations c
            ORDER BY c.updated_at DESC
        ''')
        conversations = []
        for row in cursor.fetchall():
            conv = dict(row)
            conv['participants'] = json.loads(conv['participants'])
            conv['last_message'] = json.loads(conv['last_message']) if conv['last_message'] else None
            conversations.append(conv)
        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        logger.error(f"Admin conversations error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================
# AI SETTINGS & CHAT
# ============================================
@admin_bp.route('/api/ai/settings', methods=['GET'])
def get_ai_settings():
    return jsonify({
        'success': True,
        'settings': {
            'providers': {
                'gemini': bool(GEMINI_API_KEY),
                'claude': bool(ANTHROPIC_API_KEY),
                'openai': bool(OPENAI_API_KEY)
            },
            'primary_provider': 'gemini' if GEMINI_API_KEY else ('claude' if ANTHROPIC_API_KEY else None),
            'radim_enabled': bool(GEMINI_API_KEY or ANTHROPIC_API_KEY)
        }
    })


@admin_bp.route('/api/ai/chat', methods=['POST'])
@require_auth
@rate_limit(max_requests=20, window_seconds=60, key_func='user')
def ai_chat():
    try:
        _, get_ai_response, _, _ = _get_app_helpers()
        data = request.json
        messages = data.get("messages", [])
        image_data = data.get("image")
        if not messages:
            return jsonify({"success": False, "error": "No messages provided"}), 400
        response = get_ai_response(messages, context=None, image=image_data)
        return jsonify({
            'success': True,
            'response': response,
            'provider': 'gemini' if GEMINI_API_KEY else 'claude'
        })
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================
# WORDPRESS INTEGRATION
# ============================================
@admin_bp.route('/api/wordpress/login', methods=['POST'])
def wp_login():
    try:
        _, _, get_wp_user, sync_wp_user = _get_app_helpers()
        data = request.json
        email = data.get('email')
        wp_user = get_wp_user(email)
        if wp_user:
            user_id = sync_wp_user(wp_user)
            return jsonify({
                'success': True,
                'user': {
                    'id': user_id,
                    'name': wp_user.get('name'),
                    'email': email,
                    'avatar': wp_user.get('avatar_urls', {}).get('96'),
                    'wp_id': wp_user['id']
                }
            })
        return jsonify({'success': False, 'error': 'User not found'}), 404
    except Exception as e:
        logger.error(f"WP login error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


@admin_bp.route('/api/wordpress/sync', methods=['POST'])
def wp_sync_users():
    try:
        _, _, _, sync_wp_user = _get_app_helpers()
        if not WP_URL or not WP_USER:
            return jsonify({'success': False, 'error': 'WordPress not configured'}), 500
        response = http_requests.get(
            f"{WP_URL}/wp-json/wp/v2/users",
            params={'per_page': 100},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=30
        )
        if response.status_code == 200:
            users = response.json()
            synced = []
            for wp_user in users:
                user_id = sync_wp_user(wp_user)
                if user_id:
                    synced.append(user_id)
            return jsonify({
                'success': True,
                'synced': len(synced),
                'users': synced
            })
        return jsonify({'success': False, 'error': 'WordPress API error'}), 500
    except Exception as e:
        logger.error(f"WP sync error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================
# STUB ENDPOINTS
# ============================================
@admin_bp.route('/api/consciousness/unified/state')
def consciousness_unified_state():
    senior_id = request.args.get('senior_id', 'unknown')
    return jsonify({
        "status": "not_implemented",
        "message": "Consciousness panel not available in backend v3.0.0",
        "senior_id": senior_id
    }), 200


@admin_bp.route('/api/messenger/contacts')
def messenger_contacts():
    return jsonify([]), 200


@admin_bp.route('/api/proxy/azure/speech-token')
def azure_speech_token():
    return jsonify({
        "error": "Use /api/speech/azure-token endpoint instead",
        "status": "deprecated"
    }), 200


@admin_bp.route('/api/windsurf/health')
def windsurf_health():
    return jsonify({
        "status": "ok",
        "message": "Windsurf integration not available"
    }), 200


# ============================================
# CLIENT & EMERGENCY
# ============================================
@admin_bp.route('/api/clients', methods=['POST', 'OPTIONS'])
def api_clients():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    action = data.get('action', 'sync')
    if action == 'sync':
        client = data.get('client', {})
        contacts = data.get('contacts', [])
        client_id = client.get('id')
        if client_id:
            logger.info(f"[CLIENT SYNC] {client_id}")
        return jsonify({
            'success': True, 'action': 'sync', 'client_id': client_id,
            'contacts_count': len(contacts), 'timestamp': now_iso()
        }), 200
    return jsonify({'success': False, 'error': 'Unknown action'}), 400


@admin_bp.route('/api/clients/<client_id>', methods=['GET', 'OPTIONS'])
def api_get_client(client_id):
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({
        'success': True, 'client': None, 'contacts': [],
        'message': 'Client data managed on frontend (localStorage)'
    }), 200


# ============================================
# ADMIN PANEL API — user management + system overview (v429)
# ============================================

def _require_admin(f):
    """Decorator: require administrator role via JWT."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import g
        if not hasattr(g, 'auth_user') or not g.auth_user:
            return jsonify({'success': False, 'error': 'Přihlášení vyžadováno'}), 401
        if g.auth_user.get('role') not in ('administrator', 'admin'):
            return jsonify({'success': False, 'error': 'Nedostatečná oprávnění'}), 403
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/api/admin/users-full', methods=['GET'])
@require_auth
@_require_admin
def admin_users_full():
    """Full user listing: auth_users + memory + brain states."""
    from database import db_context, is_postgres
    try:
        with db_context() as db:
            # Get all registered users
            users = db.execute("""
                SELECT id, email, name, role, created_at
                FROM auth_users ORDER BY created_at DESC
            """).fetchall()

            result = []
            for u in users:
                uid = str(u[0])
                user_data = {
                    'id': uid, 'email': u[1], 'name': u[2] or '',
                    'role': u[3] or 'subscriber', 'created_at': str(u[4] or '')
                }

                # Memory profile
                try:
                    prof = db.execute("SELECT data FROM memory_profiles WHERE user_id = ?", (uid,)).fetchone()
                    if prof:
                        import json as _json
                        pd = _json.loads(prof[0]) if isinstance(prof[0], str) else prof[0]
                        user_data['profile'] = {
                            'name': pd.get('name', ''),
                            'traits': pd.get('traits', []),
                        }
                except Exception:
                    pass

                # Latest brain state
                try:
                    bs = db.execute(
                        "SELECT c_value, mode, created_at FROM brain_states WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if bs:
                        user_data['brain'] = {'C': bs[0], 'mode': bs[1], 'last_active': str(bs[2])}
                except Exception:
                    pass

                # Message count
                try:
                    mc = db.execute(
                        "SELECT COUNT(*) FROM memory_history WHERE user_id = ?", (uid,)
                    ).fetchone()
                    user_data['message_count'] = mc[0] if mc else 0
                except Exception:
                    user_data['message_count'] = 0

                result.append(user_data)

        return jsonify({'success': True, 'users': result, 'count': len(result)})
    except Exception as e:
        logger.error(f"Admin users-full error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/admin/users/<user_id>/role', methods=['PUT', 'OPTIONS'])
@require_auth
@_require_admin
def admin_change_role(user_id):
    """Change user role."""
    if request.method == 'OPTIONS':
        return '', 204
    from database import db_context
    data = request.get_json() or {}
    new_role = data.get('role', '')
    valid_roles = ('subscriber', 'premium', 'teacher', 'administrator')
    if new_role not in valid_roles:
        return jsonify({'success': False, 'error': f'Neplatná role. Povolené: {valid_roles}'}), 400

    try:
        with db_context(commit=True) as db:
            db.execute("UPDATE auth_users SET role = ? WHERE id = ?", (new_role, int(user_id)))
        return jsonify({'success': True, 'user_id': user_id, 'role': new_role})
    except Exception as e:
        logger.error(f"Admin change role error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/admin/users/<user_id>', methods=['DELETE', 'OPTIONS'])
@require_auth
@_require_admin
def admin_delete_user(user_id):
    """Delete user and all their data. Irreversible."""
    if request.method == 'OPTIONS':
        return '', 204
    from database import db_context
    try:
        with db_context(commit=True) as db:
            uid = str(user_id)
            tables = [
                ("auth_users", "id", int(user_id)),
                ("memory_profiles", "user_id", uid),
                ("memory_history", "user_id", uid),
                ("memory_learning", "user_id", uid),
                ("brain_states", "user_id", uid),
                ("agent_observations", "user_id", uid),
                ("chat_contacts", "user_id", uid),
            ]
            deleted = {}
            for table, col, val in tables:
                try:
                    r = db.execute(f"DELETE FROM {table} WHERE {col} = ?", (val,))
                    deleted[table] = r.rowcount if r else 0
                except Exception:
                    deleted[table] = 'skip'

        logger.info(f"Admin deleted user {user_id}: {deleted}")
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        logger.error(f"Admin delete user error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/admin/system', methods=['GET'])
@require_auth
@_require_admin
def admin_system():
    """System overview — counts, agent status, online users."""
    from database import db_context
    try:
        with db_context() as db:
            counts = {}
            for table in ['auth_users', 'brain_states', 'agent_observations', 'memory_profiles', 'memory_history']:
                try:
                    r = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                    counts[table] = r[0] if r else 0
                except Exception:
                    counts[table] = 0

        try:
            users_online, _, _, _ = _get_app_helpers()
            online = len(users_online) if users_online else 0
        except Exception:
            online = 0

        return jsonify({
            'success': True,
            'counts': counts,
            'online_users': online,
            'timestamp': now_iso()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/emergency', methods=['POST', 'OPTIONS'])
def api_emergency():
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    event = data.get('event', 'unknown')
    user_id = data.get('user_id', 'unknown')
    timestamp = data.get('timestamp', now_iso())
    logger.info(f"[EMERGENCY] {event} from {user_id} at {timestamp}")
    contacts = data.get('contacts', [])
    return jsonify({
        'success': True, 'event': event, 'user_id': user_id,
        'timestamp': timestamp, 'contacts_notified': len(contacts),
        'message': 'Emergency logged successfully'
    }), 200
