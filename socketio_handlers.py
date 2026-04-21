# ============================================
# SOCKETIO EVENT HANDLERS
# ============================================
# Extracted from app.py — all WebSocket event handlers.
# Call register_socketio_handlers(socketio, users_online, cleanup_fn)
# from app.py after SocketIO is created.
# ============================================

import logging
from flask import request
from flask_socketio import emit, join_room, leave_room
from database import get_connection
from utils import now_iso

logger = logging.getLogger(__name__)

# Module-level refs (set by register_socketio_handlers)
_users_online = None
_cleanup_fn = None


def register_socketio_handlers(socketio, users_online, cleanup_fn):
    """Register all SocketIO event handlers.

    Args:
        socketio: Flask-SocketIO instance
        users_online: dict mapping user_id → socket sid
        cleanup_fn: function to evict stale entries from users_online
    """
    global _users_online, _cleanup_fn
    _users_online = users_online
    _cleanup_fn = cleanup_fn

    @socketio.on('connect')
    def handle_connect():
        logger.info(f'Client connected: {request.sid}')

    @socketio.on('disconnect')
    def handle_disconnect(reason=None):
        # v10.41.4: newer python-socketio passes (sid, reason) — flask-socketio
        # forwards the reason kwarg. Accept it defensively for forward compat.
        user_id = None
        for uid, sid in list(_users_online.items()):
            if sid == request.sid:
                user_id = uid
                del _users_online[uid]
                break
        if user_id:
            # v10.41.4: emit(..., broadcast=True) deprecated. Default behavior
            # is already broadcast to namespace when no `to=` is given.
            socketio.emit('user_offline', {'userId': user_id, 'timestamp': now_iso()})
            db = None
            try:
                db = get_connection()
                db.execute('UPDATE chat_users SET online = 0, last_seen = ? WHERE id = ?', (now_iso(), user_id))
                db.commit()
            except Exception as e:
                logger.warning(f"Error updating user offline status: {e}")
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

    @socketio.on('join')
    def handle_join(data):
        user_id = data.get('userId')
        if user_id:
            _cleanup_fn()
            _users_online[user_id] = request.sid
            join_room(user_id)
            # v10.41.4: broadcast=True deprecated — default is broadcast already
            socketio.emit('user_online', {'userId': user_id, 'timestamp': now_iso()})
            db = None
            try:
                db = get_connection()
                db.execute('UPDATE chat_users SET online = 1 WHERE id = ?', (user_id,))
                db.commit()
            except Exception as e:
                logger.warning(f"Error updating user online status: {e}")
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass

    @socketio.on('join_conversation')
    def handle_join_conversation(data):
        conversation_id = data.get('conversationId')
        if conversation_id:
            join_room(conversation_id)

    @socketio.on('leave_conversation')
    def handle_leave_conversation(data):
        conversation_id = data.get('conversationId')
        if conversation_id:
            leave_room(conversation_id)

    @socketio.on('send_message')
    def handle_send_message(data):
        conversation_id = data.get('conversationId') or data.get('conversation_id')
        if conversation_id:
            emit('new_message', data, room=conversation_id, include_self=False)

    @socketio.on('typing')
    def handle_typing(data):
        conversation_id = data.get('conversationId')
        user_id = data.get('userId')
        if conversation_id:
            emit('user_typing', {'userId': user_id, 'conversationId': conversation_id, 'timestamp': now_iso()},
                 room=conversation_id, include_self=False)

    @socketio.on('stop_typing')
    def handle_stop_typing(data):
        conversation_id = data.get('conversationId')
        user_id = data.get('userId')
        if conversation_id:
            emit('user_stop_typing', {'userId': user_id, 'conversationId': conversation_id},
                 room=conversation_id, include_self=False)

    @socketio.on('mark_read')
    def handle_mark_read(data):
        conversation_id = data.get('conversationId')
        if conversation_id:
            emit('messages_read', data, room=conversation_id, include_self=False)

    # ============================================
    # STT STREAMING → BRAIN (v272)
    # ============================================

    @socketio.on('stt_interim')
    def handle_stt_interim(data):
        """Process interim STT results for early Brain Psi(t) estimation."""
        try:
            text = data.get('text', '')
            user_id = data.get('user_id', 'anonymous')
            is_final = data.get('is_final', False)

            if not text:
                return

            try:
                from intent_resolver import quick_estimate_from_text
                C_est, alpha_est = quick_estimate_from_text(text)
            except ImportError:
                C_est, alpha_est = 5.0, 0.2

            try:
                from radim_brain_routes import update_early_psi
                update_early_psi(user_id, C_est, alpha_est, is_final)
            except ImportError:
                pass

            mode = 'HARMONY'
            if C_est >= 27:
                mode = 'CRISIS'
            elif C_est >= 12:
                mode = 'ALERT'

            intent_hint = None
            if is_final:
                try:
                    from intent_resolver import resolve_intent
                    resolved, intent_label, _ = resolve_intent(text, user_id, mode)
                    intent_hint = intent_label
                except Exception:
                    pass

            emit('brain_update', {
                'C': round(C_est, 2),
                'alpha': round(alpha_est, 3),
                'mode': mode,
                'is_final': is_final,
                'intent_hint': intent_hint
            })
        except Exception as e:
            logger.error(f"stt_interim error (non-fatal): {e}")

    # ============================================
    # EDUCATION SOCKETIO — Teacher <-> Student
    # ============================================

    @socketio.on('join_education')
    def handle_join_education(data):
        """Student/teacher joins their education room for notifications.
        Requires JWT token for verification."""
        token = data.get('token', '')
        user_id = data.get('userId')
        if not user_id or not token:
            emit('education_error', {'error': 'userId and token required'})
            return
        try:
            from auth_middleware import decode_jwt
            payload = decode_jwt(token)
            if not payload:
                emit('education_error', {'error': 'Invalid token'})
                return
            token_user_id = str(payload.get('user', {}).get('id', ''))
            if token_user_id != str(user_id):
                emit('education_error', {'error': 'Token userId mismatch'})
                return
        except Exception:
            emit('education_error', {'error': 'Auth verification failed'})
            return
        join_room(f'user_{user_id}')
        logger.info(f"User {user_id} joined education room (verified)")

    @socketio.on('leave_education')
    def handle_leave_education(data):
        """Leave education notification room"""
        user_id = data.get('userId')
        if user_id:
            leave_room(f'user_{user_id}')

    # ═══════════════════════════════════════════════════════════
    # AGENT ACTION — backend pushes UI actions to frontend
    # ═══════════════════════════════════════════════════════════

    @socketio.on('agent_action')
    def handle_agent_action(data):
        """Forward agent action to specific user's room.
        Used by agent_loop.py to control frontend UI.

        data: {
            'user_id': 'target_user_id',
            'action': 'showModule',  # or 'speak', 'notify'
            'module': 'quiz',
            'speak': 'Optional text to speak'
        }
        """
        user_id = data.get('user_id')
        if user_id:
            emit('agent_action', data, room=f'user_{user_id}')
            logger.info(f"🤖 Agent action → user {user_id}: {data.get('action')} {data.get('module', '')}")

    # ═══════════════════════════════════════════════════════════
    # MEDICAL TEAM — real-time chat (v488)
    # ═══════════════════════════════════════════════════════════

    @socketio.on('join_medical')
    def handle_join_medical(data):
        senior_id = data.get('senior_id')
        if senior_id:
            join_room(f'medical_{senior_id}')

    @socketio.on('leave_medical')
    def handle_leave_medical(data):
        senior_id = data.get('senior_id')
        if senior_id:
            leave_room(f'medical_{senior_id}')

    @socketio.on('medical_message')
    def handle_medical_message(data):
        senior_id = data.get('senior_id')
        if senior_id:
            try:
                from database import db_context
                with db_context(commit=True) as db:
                    db.execute(
                        "INSERT INTO medical_messages (senior_id, author_id, author_role, author_name, message) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (senior_id, data.get('author_id', ''), data.get('role', ''),
                         data.get('name', ''), data.get('message', ''))
                    )
            except Exception:
                pass
            emit('medical_message', {
                'senior_id': senior_id,
                'author_id': data.get('author_id'),
                'author_role': data.get('role'),
                'author_icon': data.get('icon', '💬'),
                'author_name': data.get('name'),
                'message': data.get('message'),
                'date': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
            }, room=f'medical_{senior_id}', include_self=True)


    # ═══════════════════════════════════════════════════════════════════
    # 📹 NATIVE VIDEO CALL SIGNALING (WebRTC P2P)
    # No iframe, no Jitsi — direct browser-to-browser media via our signaling.
    # Every event validated; target user room = their user_id (set via 'join').
    # ═══════════════════════════════════════════════════════════════════

    def _caller_uid():
        """Best-effort lookup of caller's user_id from sid in _users_online."""
        for uid, sid in _users_online.items():
            if sid == request.sid:
                return uid
        return None

    @socketio.on('webrtc:invite')
    def handle_webrtc_invite(data):
        """Caller invites target to a 1-on-1 video call.
        data: { to: <user_id>, callType: 'video'|'audio', callerName }
        Forwards 'webrtc:incoming' to target's user room."""
        caller_uid = _caller_uid()
        target_uid = str(data.get('to') or '')
        if not caller_uid or not target_uid:
            return
        payload = {
            'from': caller_uid,
            'callerName': str(data.get('callerName') or 'Někdo')[:80],
            'callType': 'audio' if data.get('callType') == 'audio' else 'video',
            'roomCode': str(data.get('roomCode') or ''),
        }
        socketio.emit('webrtc:incoming', payload, room=target_uid)

    @socketio.on('webrtc:accept')
    def handle_webrtc_accept(data):
        """Target accepts the call.
        data: { to: <caller_user_id>, roomCode }
        Forwards 'webrtc:accepted' back to caller so they can start offer."""
        callee_uid = _caller_uid()
        caller_uid = str(data.get('to') or '')
        if not callee_uid or not caller_uid:
            return
        socketio.emit('webrtc:accepted', {
            'from': callee_uid,
            'roomCode': str(data.get('roomCode') or ''),
        }, room=caller_uid)

    @socketio.on('webrtc:reject')
    def handle_webrtc_reject(data):
        """Target rejects. Forwards 'webrtc:rejected' to caller."""
        callee_uid = _caller_uid()
        caller_uid = str(data.get('to') or '')
        if not callee_uid or not caller_uid:
            return
        socketio.emit('webrtc:rejected', {
            'from': callee_uid,
            'reason': str(data.get('reason') or 'rejected')[:40],
        }, room=caller_uid)

    @socketio.on('webrtc:offer')
    def handle_webrtc_offer(data):
        """SDP offer from caller to target. Opaque pass-through."""
        sender_uid = _caller_uid()
        target_uid = str(data.get('to') or '')
        if not sender_uid or not target_uid:
            return
        socketio.emit('webrtc:offer', {
            'from': sender_uid,
            'sdp': data.get('sdp'),
        }, room=target_uid)

    @socketio.on('webrtc:answer')
    def handle_webrtc_answer(data):
        """SDP answer back to caller. Opaque pass-through."""
        sender_uid = _caller_uid()
        target_uid = str(data.get('to') or '')
        if not sender_uid or not target_uid:
            return
        socketio.emit('webrtc:answer', {
            'from': sender_uid,
            'sdp': data.get('sdp'),
        }, room=target_uid)

    @socketio.on('webrtc:ice')
    def handle_webrtc_ice(data):
        """Exchange ICE candidates. Opaque pass-through."""
        sender_uid = _caller_uid()
        target_uid = str(data.get('to') or '')
        if not sender_uid or not target_uid:
            return
        socketio.emit('webrtc:ice', {
            'from': sender_uid,
            'candidate': data.get('candidate'),
        }, room=target_uid)

    @socketio.on('webrtc:hangup')
    def handle_webrtc_hangup(data):
        """Either side hangs up."""
        sender_uid = _caller_uid()
        target_uid = str(data.get('to') or '')
        if not sender_uid or not target_uid:
            return
        socketio.emit('webrtc:hangup', {
            'from': sender_uid,
        }, room=target_uid)

    logger.info("✅ SocketIO handlers registered (24 events — incl medical + WebRTC P2P signaling)")
