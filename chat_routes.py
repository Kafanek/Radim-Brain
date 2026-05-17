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
    """v330+B6: Validate authenticated user matches requested user_id.
    Returns None if OK, or error response tuple if IDOR detected.
    Allows admins/caregivers through.

    Audit-fix B6: dříve `if not auth_user: return None` umožňoval ANONYMNÍMU
    uživateli (žádný token) přistupovat k libovolnému user_id — IDOR bypass.
    Teď: anonymní user může jen pokud requested_user_id == 'radim'/'radim-ai'
    (nutné pro server-side broadcasty Radimových zpráv) — všechny ostatní
    cesty pro anonymous=403.
    """
    auth_user = getattr(g, 'auth_user', None)

    # B6: Anonymous přístup povolen JEN pro Radimovy systémové akce
    if not auth_user:
        if str(requested_user_id) in ('radim', 'radim-ai'):
            return None
        logger.warning(f"IDOR blocked: anonymous user tried to access {requested_user_id}")
        return jsonify({'success': False, 'error': 'Pristup zamitnut — vyzaduje prihlaseni'}), 401

    user_role = auth_user.get('role', 'user') if isinstance(auth_user, dict) else 'user'
    auth_id = str(auth_user.get('id', '')) if isinstance(auth_user, dict) else ''

    # Admins / pečující bypass IDOR check
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

# v397.28 — short-TTL caches absorb burst polls when frontend keeps refetching.
# Chat data needs near-real-time freshness, so TTL is short (5s). The cache
# eliminates Heroku 30s gunicorn timeouts caused by repeated slow LIKE
# scans hitting the same dyno worker queue.
import time as _time
import threading as _threading
_CONV_CACHE: dict = {}
_MSG_CACHE: dict = {}
_CHAT_CACHE_TTL_S = 5.0
_CHAT_CACHE_MAX = 500
_CHAT_CACHE_LOCK = _threading.Lock()


def _chat_cache_get(cache, key):
    with _CHAT_CACHE_LOCK:
        entry = cache.get(key)
    if entry and (_time.time() - entry[0]) < _CHAT_CACHE_TTL_S:
        return entry[1]
    return None


def _chat_cache_set(cache, key, payload):
    now = _time.time()
    with _CHAT_CACHE_LOCK:
        cache[key] = (now, payload)
        if len(cache) > _CHAT_CACHE_MAX:
            ordered = sorted(cache.items(), key=lambda kv: kv[1][0])
            for k, _v in ordered[:100]:
                cache.pop(k, None)


def chat_cache_invalidate_user(user_id):
    """Called from POST routes (send_message, create_conversation) to keep
    cache coherent — drop user's conversations cache so next GET is fresh."""
    with _CHAT_CACHE_LOCK:
        _CONV_CACHE.pop(str(user_id), None)


def chat_cache_invalidate_conversation(conversation_id):
    with _CHAT_CACHE_LOCK:
        # Drop all message-cache entries for this conversation regardless of limit
        for k in list(_MSG_CACHE.keys()):
            if k.startswith(f"{conversation_id}::"):
                _MSG_CACHE.pop(k, None)


@chat_bp.route('/api/chat/conversations/<user_id>', methods=['GET'])
@optional_auth
def get_conversations(user_id):
    idor = _check_idor(user_id)
    if idor:
        return idor

    # Short-TTL cache: same user re-fetching within 5s gets cached payload.
    cached = _chat_cache_get(_CONV_CACHE, str(user_id))
    if cached is not None:
        return jsonify({**cached, '_cache': 'hit'})

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
            try:
                conv['participants'] = json.loads(conv['participants']) if conv['participants'] else []
            except Exception:
                conv['participants'] = []
            try:
                conv['last_message'] = json.loads(conv['last_message']) if conv['last_message'] else None
            except Exception:
                conv['last_message'] = None
            try:
                conv['settings'] = json.loads(conv['settings']) if conv['settings'] else {}
            except Exception:
                conv['settings'] = {}
            conversations.append(conv)

        payload = {'success': True, 'conversations': conversations}
        _chat_cache_set(_CONV_CACHE, str(user_id), payload)
        return jsonify({**payload, '_cache': 'miss'})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        # Soft-fail with empty list — better than 500/503 spinner-of-death
        return jsonify({'success': True, 'conversations': [],
                        '_partial': True, '_error': str(e)[:120]})


@chat_bp.route('/api/chat/conversations', methods=['POST'])
@optional_auth
def create_conversation():
    try:
        data = request.get_json(silent=True) or {}
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

        # v397.28 — invalidate cache so participants see the new conversation
        # immediately on next GET (otherwise they'd wait up to 5s).
        for p in participants:
            try: chat_cache_invalidate_user(p)
            except Exception: pass

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

        # 5s cache only when no `before` cursor (i.e. initial load).
        # Pagination requests are pass-through (always fresh) since they're
        # one-shot.
        cache_key = f"{conversation_id}::{limit}" if not before else None
        if cache_key:
            cached = _chat_cache_get(_MSG_CACHE, cache_key)
            if cached is not None:
                return jsonify({**cached, '_cache': 'hit'})

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
            try:
                msg['reactions'] = json.loads(msg['reactions']) if msg['reactions'] else []
            except Exception:
                msg['reactions'] = []
            try:
                msg['read_by'] = json.loads(msg['read_by']) if msg['read_by'] else []
            except Exception:
                msg['read_by'] = []
            try:
                msg['metadata'] = json.loads(msg['metadata']) if msg['metadata'] else {}
            except Exception:
                msg['metadata'] = {}
            messages.append(msg)

        payload = {
            'success':  True,
            'messages': list(reversed(messages)),
            'hasMore':  len(messages) == limit,
        }
        if cache_key:
            _chat_cache_set(_MSG_CACHE, cache_key, payload)
        return jsonify({**payload, '_cache': 'miss' if cache_key else 'pass'})
    except Exception as e:
        logger.error(f"chat_routes error: {e}")
        # Soft-fail with empty list — chat shows "no messages" instead of error
        return jsonify({'success': True, 'messages': [], 'hasMore': False,
                        '_partial': True, '_error': str(e)[:120]})


@chat_bp.route('/api/chat/messages', methods=['POST'])
@optional_auth
@rate_limit(30, 60, 'ip')  # v330: Rate limit message sending
def send_message():
    try:
        data = request.get_json(silent=True) or {}
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

        # v397.28 — invalidate cache so the new message appears instantly
        # on the next GET (recipients otherwise wait up to 5s).
        try:
            chat_cache_invalidate_conversation(message['conversation_id'])
            # Also invalidate sender + any other participants for the
            # conversations list cache (last_message changed).
            cur = db.execute(
                "SELECT participants FROM chat_conversations WHERE id = ?",
                (message['conversation_id'],)
            ).fetchone()
            if cur:
                try:
                    parts = json.loads(cur['participants']) if cur['participants'] else []
                    for p in parts:
                        chat_cache_invalidate_user(p)
                except Exception:
                    pass
        except Exception:
            pass

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
        # Audit-fix B1+B3+B5:
        #   B1) AI volání bylo bez try/except — pokud Gemini timeoutoval,
        #       user msg byl uložen, AI msg ne, frontend čekal navěky na typing.
        #   B3) push notifikace AI odpovědi se posílala SENDERU (sám sobě)
        #       místo OSTATNÍM lidským účastníkům — push spam u sendera, ostatní
        #       nedostali nic.
        #   B5) AI engine běžel i když sender_id NENÍ v participants → data
        #       corruption (cizí user pošle AI v cizí konverzaci).
        cursor = db.execute('SELECT participants FROM chat_conversations WHERE id = ?', (conversation_id,))
        conv = cursor.fetchone()

        try:
            participants = json.loads(conv['participants']) if conv else []
        except (TypeError, ValueError):
            participants = []

        # Bezpečnostní gate: Radim odpoví JEN když:
        #   1) konverzace má Radima jako účastníka
        #   2) sender_id je v participants (sender skutečně patří do konverzace)
        #   3) sender není Radim sám (zabránit nekonečné smyčce AI ↔ AI)
        sender_in_conv = sender_id in participants
        radim_in_conv = 'radim' in participants
        ai_should_run = radim_in_conv and sender_in_conv and sender_id != 'radim'

        if ai_should_run:
            try:
                # X21.44 UNIFICATION: was `get_ai_response(history)` via
                # ai_bridge — a separate "engine B" with NO brain Ψ(t), NO
                # long-term memory, NO identity layer, NO voice_mode, NO
                # lang awareness. Result: Radim in Komunikace was a
                # different, "weaker" Radim than the one users got on
                # phone / WhatsApp / main chat (which all routed through
                # radim_chat_internal — "engine A").
                #
                # Now: chat_routes also routes through radim_chat_internal,
                # so Komunikace Radim has the same memory + brain + lang +
                # identity as everywhere else. Single source of truth.
                #
                # Trade-off: we lose conv-specific chat_messages history
                # context (the AI no longer sees "what was said in this
                # exact thread before"). But radim_chat_internal pulls
                # memory_history which is CROSS-SURFACE — it captures
                # everything the senior said anywhere. Net better.
                from radim_orchestrator import radim_chat_internal
                _result = radim_chat_internal(content, user_id=sender_id, mode='senior')
                ai_response = _result.get('response') if _result else None
                # If radim_chat_internal returned the canned error string
                # ("Omlouvám se, zkuste to prosím později.") on a real
                # failure, the chat_message INSERT below would persist
                # that as Radim's reply — better to surface as ai_error
                # so the typing indicator hides.
                if _result and not _result.get('success', True):
                    ai_response = None
            except Exception as ai_err:
                # B1: AI selhalo (timeout, rate limit, výpadek poskytovatele).
                # User msg už je commitnutá z dřívějška. Frontend by čekal na
                # typing co nikdy nepřijde — emitneme 'ai_error' aby frontend
                # mohl skrýt typing dots a pokud chce, ukázal toast.
                logger.warning(f"AI response failed for conv={conversation_id}: {ai_err}")
                try:
                    socketio.emit('ai_error', {
                        'conversationId': conversation_id,
                        'replyTo': message['id'],
                        'reason': 'temporary',  # nemusíme leakovat detaily uživateli
                    }, room=conversation_id)
                except Exception:
                    pass
                ai_response = None

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

                try:
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

                    # B3: push notifikace AI odpovědi → OSTATNÍM lidským
                    # účastníkům (typicky pečující rodina), NE senderu.
                    # Sender už vidí Radimovu odpověď v UI — push by jen rušila.
                    # Ostatní v rodině můžou chtít vidět "Babička dostala
                    # odpověď od Radima — vše OK" jako kontrolní signál.
                    try:
                        ai_other_humans = [p for p in participants
                                           if p and p != sender_id and p != 'radim']
                        for other_uid in ai_other_humans:
                            send_push_notification(
                                other_uid,
                                'Radim odpovedel',
                                ai_response[:100],
                                {
                                    'conversationId': conversation_id,
                                    'messageId': ai_message['id'],
                                    'senderId': 'radim',
                                    'action': 'open_conversation',
                                }
                            )
                    except Exception as push_err:
                        logger.debug(f'AI push fanout failed: {push_err}')
                except Exception as db_err:
                    # B1: ukládání AI odpovědi do DB selhalo (síť, locks...)
                    logger.error(f"AI message save failed for conv={conversation_id}: {db_err}", exc_info=True)
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    try:
                        socketio.emit('ai_error', {
                            'conversationId': conversation_id,
                            'replyTo': message['id'],
                            'reason': 'storage',
                        }, room=conversation_id)
                    except Exception:
                        pass

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
        data = request.get_json(silent=True) or {}
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
        data = request.get_json(silent=True) or {}
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


# v10.99 — Sprint M: delete message (soft-delete = replace with tombstone)
@chat_bp.route('/api/chat/messages/<message_id>', methods=['DELETE'])
@optional_auth
def delete_message(message_id):
    """Soft-delete: replaces content with tombstone marker, preserves the
    bubble in chronology. WhatsApp-style "Tato zpráva byla odstraněna"."""
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'error': 'Chybi userId'}), 400

        # IDOR: only sender can delete their own messages
        idor = _check_idor(user_id)
        if idor:
            return idor

        db = get_db()
        cursor = db.execute(
            'SELECT sender_id, conversation_id FROM chat_messages WHERE id = ?',
            (message_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Message not found'}), 404
        if str(row['sender_id']) != str(user_id):
            return jsonify({'success': False, 'error': 'Nelze smazat zprávu jiného uživatele'}), 403

        conv_id = row['conversation_id']
        tombstone_meta = json.dumps({'deleted': True, 'deleted_at': now_iso(),
                                     'deleted_by': user_id})
        db.execute('''
            UPDATE chat_messages
               SET type = 'system', content = '🗑 Tato zpráva byla odstraněna',
                   metadata = ?, status = 'deleted'
             WHERE id = ?
        ''', (tombstone_meta, message_id))
        db.commit()

        socketio, *_ = _get_app_helpers()
        socketio.emit('message_deleted', {
            'messageId': message_id,
            'conversationId': conv_id,
            'deletedBy': user_id,
        }, room=conv_id)

        # Sprint P: audit
        try:
            from chat_hardening_routes import _log_audit
            _log_audit(user_id=user_id, action='message_deleted',
                       target_type='message', target_id=message_id,
                       metadata={'conversationId': conv_id})
        except Exception:
            pass

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"delete_message error: {e}")
        return jsonify({'success': False, 'error': 'Interni chyba serveru'}), 500


# v10.99 — Sprint M: star/unstar message (per-user, stored in metadata)
@chat_bp.route('/api/chat/messages/<message_id>/star', methods=['POST'])
@optional_auth
def star_message(message_id):
    """Toggle a star on a message — per-user list stored in message.metadata.starred_by[]."""
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get('userId')
        if not user_id:
            return jsonify({'success': False, 'error': 'Chybi userId'}), 400

        db = get_db()
        cursor = db.execute('SELECT metadata FROM chat_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Message not found'}), 404
        meta = json.loads(row['metadata']) if row['metadata'] else {}
        starred_by = list(meta.get('starred_by', []))
        if user_id in starred_by:
            starred_by.remove(user_id)
            starred = False
        else:
            starred_by.append(user_id)
            starred = True
        meta['starred_by'] = starred_by
        db.execute('UPDATE chat_messages SET metadata = ? WHERE id = ?',
                   (json.dumps(meta), message_id))
        db.commit()
        # Sprint P: audit
        try:
            from chat_hardening_routes import _log_audit
            _log_audit(user_id=user_id,
                       action='message_starred' if starred else 'message_unstarred',
                       target_type='message', target_id=message_id)
        except Exception:
            pass
        return jsonify({'success': True, 'starred': starred, 'starred_by': starred_by})
    except Exception as e:
        logger.error(f"star_message error: {e}")
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
        data = request.get_json(silent=True) or {}
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
