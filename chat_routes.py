# -*- coding: utf-8 -*-
"""
RADIM CHAT ROUTES - Conversations, Messages, Contacts
Extracted from app.py for cleaner module separation.

Provides REST API endpoints for the chat system:
  - GET/POST /api/chat/conversations
  - GET/POST /api/chat/messages
  - PATCH     /api/chat/messages/<id>/read
  - POST      /api/chat/messages/<id>/reaction
  - GET/POST /api/chat/contacts
"""

import json
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from database import get_db_for_flask
from auth_middleware import optional_auth
from rate_limiter import rate_limit
from utils import generate_id, now_iso

logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)

# ============================================
# HELPERS (local to chat routes)
# ============================================

def get_db():
    return get_db_for_flask(g)


def _get_app_helpers():
    """Lazy import of helpers defined in app.py to avoid circular imports.
    Returns (socketio, get_ai_response, update_daily_stats, send_push_notification, users_online).
    """
    import app as _app
    return (
        _app.socketio,
        _app.get_ai_response,
        _app.update_daily_stats,
        _app.send_push_notification,
        _app.users_online,
    )


# ============================================
# IDOR PROTECTION
# v330: Validates authenticated user matches requested user_id
# ============================================

def _check_idor(requested_user_id):
    """v330: Validate authenticated user matches requested user_id.
    Returns None if OK, or error response tuple if IDOR detected.
    Allows 'radim-ai' requests and admins through."""
    auth_user = getattr(g, 'auth_user', None)
    if not auth_user:
        return None  # optional_auth -- no token = anonymous access (for senior devices)
    user_role = auth_user.get('role', 'user') if isinstance(auth_user, dict) else 'user'
    auth_id = str(auth_user.get('id', '')) if isinstance(auth_user, dict) else ''
    # Admins bypass IDOR check
    if user_role in ('administrator', 'admin', 'caregiver'):
        return None
    # Check if requesting own data
    if auth_id and str(requested_user_id) != auth_id:
        logger.warning(f"IDOR blocked: user {auth_id} tried to access {requested_user_id}")
        return jsonify({'success': False, 'error': 'Pristup zamitnut'}), 403
    return None


# ============================================
# REST API - CONVERSATIONS
# ============================================

@chat_bp.route('/api/chat/conversations/<user_id>', methods=['GET'])
@optional_auth
def get_conversations(user_id):
    idor = _check_idor(user_id)
    if idor:
        return idor
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT * FROM chat_conversations
            WHERE participants LIKE ?
            ORDER BY updated_at DESC
        ''', (f'%"{user_id}"%',))

        conversations = []
        for row in cursor.fetchall():
            conv = dict(row)
            conv['participants'] = json.loads(conv['participants'])
            conv['last_message'] = json.loads(conv['last_message']) if conv['last_message'] else None
            conv['settings'] = json.loads(conv['settings']) if conv['settings'] else {}
            conversations.append(conv)

        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


@chat_bp.route('/api/chat/conversations', methods=['POST'])
@optional_auth
def create_conversation():
    try:
        data = request.json
        participants = data.get('participants', [])
        conv_type = data.get('type', 'direct' if len(participants) <= 2 else 'group')
        name = data.get('name')

        conversation = {
            'id': generate_id(),
            'participants': participants,
            'type': conv_type,
            'name': name,
            'created_at': now_iso(),
            'updated_at': now_iso(),
            'last_message': None,
            'settings': {}
        }

        db = get_db()
        db.execute('''
            INSERT INTO chat_conversations (id, participants, type, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (conversation['id'], json.dumps(participants), conv_type, name,
              conversation['created_at'], conversation['updated_at']))
        db.commit()

        return jsonify({'success': True, 'conversation': conversation}), 201
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# ============================================
# REST API - MESSAGES (with AI)
# ============================================

@chat_bp.route('/api/chat/messages/<conversation_id>', methods=['GET'])
@optional_auth
def get_messages(conversation_id):
    try:
        limit = min(request.args.get('limit', 50, type=int), 500)
        before = request.args.get('before')

        db = get_db()
        if before:
            cursor = db.execute('''
                SELECT * FROM chat_messages
                WHERE conversation_id = ? AND timestamp < ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (conversation_id, before, limit))
        else:
            cursor = db.execute('''
                SELECT * FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (conversation_id, limit))

        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            msg['reactions'] = json.loads(msg['reactions']) if msg['reactions'] else []
            msg['read_by'] = json.loads(msg['read_by']) if msg['read_by'] else []
            msg['metadata'] = json.loads(msg['metadata']) if msg['metadata'] else {}
            messages.append(msg)

        return jsonify({'success': True, 'messages': list(reversed(messages)), 'hasMore': len(messages) == limit})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


@chat_bp.route('/api/chat/messages', methods=['POST'])
@optional_auth
@rate_limit(30, 60, 'ip')  # v330: Rate limit message sending
def send_message():
    try:
        data = request.get_json() or {}
        conversation_id = data.get('conversationId')
        sender_id = data.get('senderId')
        content = data.get('content')

        if not conversation_id or not sender_id or not content:
            return jsonify({'success': False, 'error': 'Chybi povinna pole (conversationId, senderId, content)'}), 400

        # v330: IDOR -- validate senderId matches authenticated user
        idor = _check_idor(sender_id)
        if idor:
            return idor

        message = {
            'id': generate_id(),
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'type': data.get('type', 'text'),
            'content': content,
            'reply_to': data.get('replyTo'),
            'metadata': data.get('metadata', {}),
            'timestamp': now_iso(),
            'status': 'sent',
            'reactions': [],
            'read_by': [sender_id],
            'ai_generated': 0
        }

        db = get_db()
        db.execute('''
            INSERT INTO chat_messages
            (id, conversation_id, sender_id, type, content, reply_to, metadata, timestamp, status, reactions, read_by, ai_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message['id'], message['conversation_id'], message['sender_id'], message['type'],
              message['content'], message['reply_to'], json.dumps(message['metadata']),
              message['timestamp'], message['status'], json.dumps(message['reactions']),
              json.dumps(message['read_by']), message['ai_generated']))

        # Update conversation
        preview = message['content'][:50]
        if message['type'] == 'voice':
            preview = '🎤 Hlasova zprava'
        elif message['type'] == 'image':
            preview = '📷 Obrazek'

        db.execute('''
            UPDATE chat_conversations SET updated_at = ?, last_message = ? WHERE id = ?
        ''', (message['timestamp'], json.dumps({
            'content': preview,
            'sender_id': message['sender_id'],
            'timestamp': message['timestamp']
        }), message['conversation_id']))
        db.commit()

        # Get app-level helpers
        socketio, get_ai_response, update_daily_stats, send_push_notification, _ = _get_app_helpers()

        # Emit to WebSocket
        socketio.emit('new_message', message, room=conversation_id)

        # Update stats
        update_daily_stats('total_messages')
        if message['type'] == 'voice':
            update_daily_stats('voice_messages')

        # Sprint I.2: push notification to OTHER human participants
        # (Radim AI branch below handles AI-response pushes separately)
        try:
            cursor = db.execute(
                'SELECT participants FROM chat_conversations WHERE id = ?',
                (conversation_id,)
            )
            conv_row = cursor.fetchone()
            if conv_row:
                all_parts = json.loads(conv_row['participants'])
                other_humans = [p for p in all_parts
                                if p and p != sender_id and p != 'radim']
                if other_humans:
                    sender_name = str(data.get('senderName') or '')[:80] or 'Kontakt'
                    preview = content[:100] if message['type'] == 'text' else (
                        '🎤 Hlasová zpráva' if message['type'] == 'voice' else
                        '📷 Obrázek' if message['type'] == 'image' else
                        'Nová zpráva'
                    )
                    try:
                        from notification_helpers import notify as _notify
                        for other_uid in other_humans:
                            _notify(
                                to_user_id=other_uid,
                                type='new_message',
                                title=f'💬 {sender_name}',
                                body=preview,
                                from_user_id=sender_id,
                                severity='info',
                                data={
                                    'conversationId': conversation_id,
                                    'messageId': message['id'],
                                    'senderId': sender_id,
                                    'action': 'open_conversation',
                                },
                            )
                    except Exception as e:
                        logger.debug(f'push on chat_message failed: {e}')
        except Exception as e:
            logger.debug(f'push fanout skipped: {e}')

        # === RADIM AI ODPOVED ===
        # Pokud je zprava pro Radima (obsahuje 'radim' v participants)
        cursor = db.execute('SELECT participants FROM chat_conversations WHERE id = ?', (conversation_id,))
        conv = cursor.fetchone()

        if conv and 'radim' in json.loads(conv['participants']) and sender_id != 'radim':
            # Ziskej historii konverzace
            cursor = db.execute('''
                SELECT sender_id, content FROM chat_messages
                WHERE conversation_id = ?
                ORDER BY timestamp DESC LIMIT 10
            ''', (conversation_id,))
            history = [dict(row) for row in cursor.fetchall()]
            history.reverse()

            # Ziskej AI odpoved
            ai_response = get_ai_response(history)

            if ai_response:
                ai_message = {
                    'id': generate_id(),
                    'conversation_id': conversation_id,
                    'sender_id': 'radim',
                    'type': 'text',
                    'content': ai_response,
                    'reply_to': message['id'],
                    'metadata': {'ai_provider': 'gemini'},
                    'timestamp': now_iso(),
                    'status': 'sent',
                    'reactions': [],
                    'read_by': ['radim'],
                    'ai_generated': 1
                }

                db.execute('''
                    INSERT INTO chat_messages
                    (id, conversation_id, sender_id, type, content, reply_to, metadata, timestamp, status, reactions, read_by, ai_generated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ai_message['id'], ai_message['conversation_id'], ai_message['sender_id'], ai_message['type'],
                      ai_message['content'], ai_message['reply_to'], json.dumps(ai_message['metadata']),
                      ai_message['timestamp'], ai_message['status'], json.dumps(ai_message['reactions']),
                      json.dumps(ai_message['read_by']), ai_message['ai_generated']))

                db.execute('''
                    UPDATE chat_conversations SET updated_at = ?, last_message = ? WHERE id = ?
                ''', (ai_message['timestamp'], json.dumps({
                    'content': ai_response[:50],
                    'sender_id': 'radim',
                    'timestamp': ai_message['timestamp']
                }), conversation_id))
                db.commit()

                # Emit AI response
                socketio.emit('new_message', ai_message, room=conversation_id)
                update_daily_stats('ai_messages')

                # Send push notification
                send_push_notification(
                    sender_id,
                    'Radim odpovedel',
                    ai_response[:100],
                    {'conversationId': conversation_id, 'messageId': ai_message['id']}
                )

        return jsonify({'success': True, 'message': message}), 201
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# ============================================
# REST API - MESSAGE READ & REACTIONS
# ============================================

@chat_bp.route('/api/chat/messages/<message_id>/read', methods=['PATCH'])
@optional_auth
def mark_as_read(message_id):
    try:
        data = request.get_json() or {}
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'error': 'Chybi userId'}), 400

        db = get_db()
        cursor = db.execute('SELECT read_by FROM chat_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()

        if row:
            read_by = json.loads(row['read_by']) if row['read_by'] else []
            if user_id not in read_by:
                read_by.append(user_id)
                db.execute('UPDATE chat_messages SET read_by = ?, status = ? WHERE id = ?',
                          (json.dumps(read_by), 'read', message_id))
                db.commit()

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


@chat_bp.route('/api/chat/messages/<message_id>/reaction', methods=['POST'])
@optional_auth
def add_reaction(message_id):
    try:
        data = request.get_json() or {}
        user_id = data.get('userId')
        emoji = data.get('emoji')
        if not user_id or not emoji:
            return jsonify({'success': False, 'error': 'Chybi userId nebo emoji'}), 400
        conversation_id = data.get('conversationId')

        db = get_db()
        cursor = db.execute('SELECT reactions FROM chat_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()

        if row:
            reactions = json.loads(row['reactions']) if row['reactions'] else []
            existing = next((r for r in reactions if r['userId'] == user_id and r['emoji'] == emoji), None)
            if existing:
                reactions.remove(existing)
            else:
                reactions.append({'userId': user_id, 'emoji': emoji, 'timestamp': now_iso()})

            db.execute('UPDATE chat_messages SET reactions = ? WHERE id = ?', (json.dumps(reactions), message_id))
            db.commit()

            if conversation_id:
                socketio, *_ = _get_app_helpers()
                socketio.emit('message_reaction', {'messageId': message_id, 'reactions': reactions}, room=conversation_id)

            return jsonify({'success': True, 'reactions': reactions})

        return jsonify({'success': False, 'error': 'Message not found'}), 404
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# ============================================
# REST API - CONTACTS
# ============================================

@chat_bp.route('/api/chat/contacts/<user_id>', methods=['GET'])
@optional_auth
def get_contacts(user_id):
    idor = _check_idor(user_id)
    if idor:
        return idor
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT c.*, u.online, u.last_seen, u.avatar as user_avatar
            FROM chat_contacts c
            LEFT JOIN chat_users u ON c.contact_id = u.id
            WHERE c.user_id = ?
            ORDER BY c.pinned DESC, c.name ASC
        ''', (user_id,))

        # Get users_online from app module
        _, _, _, _, users_online = _get_app_helpers()

        contacts = []
        for row in cursor.fetchall():
            contact = dict(row)
            contact['online'] = contact.get('contact_id') in users_online or contact.get('online', 0) == 1
            contact['avatar'] = contact.get('avatar') or contact.get('user_avatar')
            contacts.append(contact)

        # Always include Radim
        radim_exists = any(c['contact_id'] == 'radim' for c in contacts)
        if not radim_exists:
            contacts.insert(0, {
                'id': 'radim-default', 'user_id': user_id, 'contact_id': 'radim',
                'name': 'Radim Asistent', 'role': 'AI Asistent', 'avatar': None,
                'pinned': 1, 'muted': 0, 'online': True
            })

        return jsonify({'success': True, 'contacts': contacts})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


@chat_bp.route('/api/chat/contacts', methods=['POST'])
@optional_auth
def add_contact():
    try:
        data = request.get_json() or {}
        if not data.get('userId') or not data.get('contactId') or not data.get('name'):
            return jsonify({'success': False, 'error': 'Chybi povinna pole (userId, contactId, name)'}), 400
        contact = {
            'id': generate_id(),
            'user_id': data['userId'],
            'contact_id': data['contactId'],
            'name': data['name'],
            'phone': data.get('phone', ''),
            'role': data.get('role', 'Rodina'),
            'avatar': data.get('avatar'),
            'pinned': 1 if data.get('pinned') else 0,
            'muted': 0,
            'created_at': now_iso()
        }

        db = get_db()
        db.execute('''
            INSERT INTO chat_contacts (id, user_id, contact_id, name, phone, role, avatar, pinned, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (contact['id'], contact['user_id'], contact['contact_id'], contact['name'],
              contact['phone'], contact['role'], contact['avatar'], contact['pinned'], contact['created_at']))
        db.commit()

        return jsonify({'success': True, 'contact': contact}), 201
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500
