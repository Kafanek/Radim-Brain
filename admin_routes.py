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
