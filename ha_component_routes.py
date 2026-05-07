"""
🏠 HOME ASSISTANT COMPONENT ROUTES (v396)
=============================================================================
Endpoints consumed by the `custom_components/radim` Home Assistant
integration. Each endpoint requires Bearer auth using the user's JWT
(same flow as Radim's senior frontend).

Endpoints:
    GET  /api/ha-component/ping          — health + auth check
    GET  /api/ha-component/state         — Radim's mood, brain state, last obs
    POST /api/ha-component/chat          — text-in / text-out conversation
    POST /api/ha-component/speak         — queue Radim's voice pipeline

The HA component polls /state every 60s. Conversation agent calls /chat
on every utterance. /speak fires Radim's existing voice pipeline (which
can target a media_player back in HA via the existing /api/ha/action
flow).

Why a separate blueprint? Decoupling lets us:
- Keep stable contract for HA-side schema (sensors expect specific keys)
- Add HA-specific rate limiting / telemetry without touching /api/radim/*
- Version the HA contract independently of internal chat changes
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth

logger = logging.getLogger(__name__)

ha_component_bp = Blueprint('ha_component', __name__)


def _uid(payload_user_id: str = '') -> str:
    """Pick the effective user_id: explicit override (e.g. ?user_id=) or auth user."""
    explicit = (payload_user_id or '').strip()
    if explicit:
        return explicit
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


# ════════════════════════════════════════════════════════════════════
# 1. PING — fast health + auth check
# ════════════════════════════════════════════════════════════════════

@ha_component_bp.route('/api/ha-component/ping', methods=['GET'])
@require_auth
def ha_component_ping():
    """Used by HA config flow to validate URL + token before saving."""
    return jsonify({
        'success': True,
        'service': 'radim',
        'version': '0.1.0',
        'server_time': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        'capabilities': ['ping', 'state', 'chat', 'speak'],
    })


# ════════════════════════════════════════════════════════════════════
# 2. STATE — Radim's mood + brain state + last observation
# ════════════════════════════════════════════════════════════════════

@ha_component_bp.route('/api/ha-component/state', methods=['GET'])
@require_auth
def ha_component_state():
    """Snapshot for HA sensors. Returns:
        {
          user_id, online, mood, C (brain state),
          last_observation: {message, severity, at}
        }
    """
    uid = _uid(request.args.get('user_id', ''))
    if not uid:
        return jsonify({'success': False, 'error': 'no_user'}), 400

    state = {
        'user_id': uid,
        'online': True,
        'version': '0.1.0',
        'server_time': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
    }

    # Brain state C — pull latest brain_states row for this user
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT C, alpha, emotion, created_at "
                "FROM brain_states WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (uid,)
            ).fetchone()
        if row:
            state['C'] = float(row[0]) if row[0] is not None else None
            state['alpha'] = float(row[1]) if row[1] is not None else None
            state['mood'] = row[2]
            state['brain_state_at'] = (
                row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3])
            )
    except Exception as e:
        logger.debug(f'/api/ha-component/state brain_states: {e}')

    # Last agent observation
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT message, severity, observation_type, created_at "
                "FROM agent_observations WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (uid,)
            ).fetchone()
        if row:
            state['last_observation'] = {
                'message': row[0],
                'severity': row[1],
                'type': row[2],
                'at': (row[3].isoformat() if hasattr(row[3], 'isoformat') else str(row[3])),
            }
    except Exception as e:
        logger.debug(f'/api/ha-component/state agent_observations: {e}')

    return jsonify(state)


# ════════════════════════════════════════════════════════════════════
# 3. CHAT — text in, text out (HA Assist conversation agent)
# ════════════════════════════════════════════════════════════════════

@ha_component_bp.route('/api/ha-component/chat', methods=['POST'])
@require_auth
def ha_component_chat():
    """Conversation agent entrypoint — HA Assist calls this on every utterance."""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'no_message'}), 400
    if len(message) > 2000:
        return jsonify({'success': False, 'error': 'too_long'}), 413

    uid = _uid(data.get('user_id', ''))
    if not uid:
        return jsonify({'success': False, 'error': 'no_user'}), 400

    # Reuse existing Radim chat pipeline (same one as Twilio voice / WhatsApp)
    try:
        from radim_orchestrator import radim_chat_internal
        result = radim_chat_internal(message, user_id=uid, mode='senior')
    except Exception as e:
        logger.error(f'ha-component chat failed: {e}')
        return jsonify({
            'success': False,
            'error': 'chat_failed',
            'response': 'Promiňte, teď nedokážu odpovědět.',
        }), 500

    return jsonify({
        'success': bool(result.get('success', True)),
        'response': result.get('response', ''),
        'intent': result.get('intent'),
        'user_id': uid,
    })


# ════════════════════════════════════════════════════════════════════
# 4. SPEAK — Radim's voice pipeline (Azure TTS or push notification)
# ════════════════════════════════════════════════════════════════════

@ha_component_bp.route('/api/ha-component/speak', methods=['POST'])
@require_auth
def ha_component_speak():
    """Trigger Radim to speak a message.

    Two delivery paths (auto-selected):
    1. If target_speaker is provided AND the user has a per-user HA
       configured AND that speaker exists → Radim renders SSML + sends
       via media_player.play_media (using existing ha_user_config flow)
    2. Otherwise → push notification to senior's mobile (so Radim
       speaks via the app's voice pipeline next time it foregrounds)
    """
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'no_message'}), 400
    if len(message) > 1000:
        return jsonify({'success': False, 'error': 'too_long'}), 413

    uid = _uid(data.get('user_id', ''))
    if not uid:
        return jsonify({'success': False, 'error': 'no_user'}), 400

    target = (data.get('target_speaker') or '').strip()
    delivery = 'unknown'
    delivered = False

    # Path 1: HA media_player (preferred when target_speaker given)
    if target:
        try:
            from home_assistant import ha_for
            client = ha_for(uid)
            if client and client.connected and hasattr(client, 'play_media'):
                # Generate a TTS URL via Radim's Azure TTS endpoint
                # (kept generic — Radim's Azure proxy returns mp3)
                tts_url = (
                    f"{request.host_url.rstrip('/')}/api/azure-tts"
                    f"?text={message}&user_id={uid}"
                )
                ok = client.play_media(target, tts_url, 'audio/mp3')
                if ok:
                    delivery = f'ha_media_player:{target}'
                    delivered = True
        except Exception as e:
            logger.debug(f'speak via HA failed: {e}')

    # Path 2: push notification fallback
    if not delivered:
        try:
            from notifications import send_push_to_user  # if exists
            send_push_to_user(uid, title='Radim', body=message,
                              data={'speak': True, 'message': message})
            delivery = 'push'
            delivered = True
        except Exception as e:
            logger.debug(f'speak via push failed: {e}')

    return jsonify({
        'success': delivered,
        'delivery': delivery,
        'message': message,
        'user_id': uid,
    })


logger.info('🏠 HA-component routes loaded: /api/ha-component/{ping,state,chat,speak}')
