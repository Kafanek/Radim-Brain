"""
🎙️ VOICE CHOICE ROUTES (v397) — senior picks Radim's voice in Domácnost.

Reuses the existing voice_profile_engine + speech_routes catalog.
This is a thin layer that exposes:
  GET  /api/voice/choices       — list available voices (Antonín, Vlasta, ...)
  GET  /api/voice/profile       — my current choice
  POST /api/voice/profile       — change my choice (validates)
  POST /api/voice/preview       — synthesize a 1-line sample so user can hear

Why a separate file? Keeps the senior-friendly UI surface decoupled from
the existing TTS proxy. Reading & writing flows through
voice_profile_engine.{get,save}_voice_profile, so one source of truth.
"""
from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth

logger = logging.getLogger(__name__)

voice_choice_bp = Blueprint('voice_choice', __name__)


# Curated catalog (subset of speech_routes.CZECH_VOICES — only what makes sense
# to expose to seniors directly. We hide internal aliases like 'radim'=Antonín.)
VOICE_CHOICES = [
    {
        'id': 'antonin',
        'name': 'Antonín',
        'azure_name': 'cs-CZ-AntoninNeural',
        'gender': 'male',
        'tagline': 'Klidný a přátelský muž',
        'recommended': True,
        'sample_text': 'Dobrý den. Jsem Radim a budu vám pomáhat.',
    },
    {
        'id': 'vlasta',
        'name': 'Vlasta',
        'azure_name': 'cs-CZ-VlastaNeural',
        'gender': 'female',
        'tagline': 'Vřelý ženský hlas',
        'recommended': False,
        'sample_text': 'Dobrý den. Jsem Radim a budu vám pomáhat.',
    },
]


def _uid() -> str:
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


@voice_choice_bp.route('/api/voice/choices', methods=['GET'])
@require_auth
def voice_choices():
    return jsonify({'success': True, 'choices': VOICE_CHOICES})


@voice_choice_bp.route('/api/voice/profile', methods=['GET'])
@require_auth
def get_my_voice():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        from voice_profile_engine import get_voice_profile
        profile = get_voice_profile(uid) or {}
    except Exception as e:
        logger.debug(f'voice profile load: {e}')
        profile = {}
    chosen_voice = profile.get('voice_id') or 'antonin'
    return jsonify({
        'success': True,
        'voice_id': chosen_voice,
        'rate': profile.get('preferred_rate', 0.9),
        'pause_ms': profile.get('preferred_pause_ms', 618),
        'style': profile.get('preferred_style', 'friendly'),
    })


@voice_choice_bp.route('/api/voice/profile', methods=['POST'])
@require_auth
def set_my_voice():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    voice_id = (data.get('voice_id') or '').strip().lower()
    valid_ids = {v['id'] for v in VOICE_CHOICES}
    if voice_id and voice_id not in valid_ids:
        return jsonify({
            'success': False, 'error': 'unknown_voice',
            'allowed': sorted(valid_ids),
        }), 400

    try:
        from voice_profile_engine import get_voice_profile, save_voice_profile
        profile = get_voice_profile(uid) or {}
    except Exception as e:
        logger.debug(f'voice profile load: {e}')
        profile = {}

    if voice_id:
        profile['voice_id'] = voice_id
    if 'rate' in data:
        try:
            r = float(data['rate'])
            if 0.5 <= r <= 1.4:
                profile['preferred_rate'] = r
        except (TypeError, ValueError):
            pass
    if 'style' in data:
        profile['preferred_style'] = str(data['style'])[:30]

    try:
        save_voice_profile(uid, profile)
    except Exception as e:
        logger.warning(f'voice profile save: {e}')
        return jsonify({'success': False, 'error': 'save_failed'}), 500

    return jsonify({'success': True, 'profile': {
        'voice_id': profile.get('voice_id', 'antonin'),
        'rate': profile.get('preferred_rate', 0.9),
        'style': profile.get('preferred_style', 'friendly'),
    }})


@voice_choice_bp.route('/api/voice/preview', methods=['POST'])
@require_auth
def voice_preview():
    """Returns sample text + voice id so frontend can call existing TTS."""
    data = request.get_json(silent=True) or {}
    voice_id = (data.get('voice_id') or 'antonin').lower()
    catalog = next((v for v in VOICE_CHOICES if v['id'] == voice_id), VOICE_CHOICES[0])
    return jsonify({
        'success': True,
        'voice_id': catalog['id'],
        'azure_name': catalog['azure_name'],
        'sample_text': catalog['sample_text'],
        # Frontend should POST this to /api/azure-tts (existing endpoint) to play.
        'tts_endpoint': '/api/azure-tts',
        'tts_payload': {
            'text': catalog['sample_text'],
            'voice': catalog['id'],
            'rate': data.get('rate', 0.9),
        },
    })


logger.info('🎙️ Voice choice routes loaded: /api/voice/{choices,profile,preview}')
