"""
Voice Lexicon Routes — per-user TTS pronunciation overrides (v456)
==================================================================

Lets a senior teach Radim how to say a specific name (typically grandkids,
pets, family) without touching code. Entries are stored as a flat
{original: alias} dict inside memory_profiles.data['voice_lexicon'] and
applied by voice_filter._apply_user_lexicon() before built-in fixes.

Endpoints (all require Bearer JWT):
  GET    /api/voice/lexicon              → list current user's entries
  POST   /api/voice/lexicon              → upsert {original, alias}
  DELETE /api/voice/lexicon/<original>   → remove a single entry
  DELETE /api/voice/lexicon              → clear all entries

Each successful write invalidates the in-memory lexicon cache so the next
TTS render picks up the new state immediately (without waiting for the
60 s TTL).

Limits:
  - max 100 entries per user (defensive, prevents runaway growth)
  - original max 80 chars, alias max 120 chars
  - empty/whitespace-only inputs rejected
"""

import logging
from flask import Blueprint, request, jsonify, g

from auth_middleware import require_auth

logger = logging.getLogger(__name__)

voice_lexicon_bp = Blueprint('voice_lexicon', __name__)

MAX_ENTRIES = 100
MAX_ORIGINAL_LEN = 80
MAX_ALIAS_LEN = 120


def _user_id_from_g():
    """Pull the authenticated user_id from flask.g (set by require_auth)."""
    user = getattr(g, 'auth_user', None) or {}
    uid = user.get('id') or user.get('user_id') or user.get('sub')
    return str(uid) if uid is not None else None


def _load_lexicon(user_id):
    from memory_helpers import db_load_profile
    profile = db_load_profile(user_id) or {}
    lex = profile.get('voice_lexicon') or {}
    if not isinstance(lex, dict):
        lex = {}
    return profile, lex


def _save_lexicon(user_id, profile, lex):
    from memory_helpers import db_save_profile
    profile['voice_lexicon'] = lex
    db_save_profile(user_id, profile)
    # Hot-invalidate the in-process cache
    try:
        from voice_filter import invalidate_user_lexicon_cache
        invalidate_user_lexicon_cache(user_id)
    except Exception as e:
        logger.debug(f"invalidate_user_lexicon_cache failed: {e}")


@voice_lexicon_bp.route('/api/voice/lexicon', methods=['GET'])
@require_auth
def list_lexicon():
    uid = _user_id_from_g()
    if not uid:
        return jsonify({'success': False, 'error': 'no user_id'}), 400
    _, lex = _load_lexicon(uid)
    return jsonify({
        'success': True,
        'entries': [{'original': k, 'alias': v} for k, v in sorted(lex.items())],
        'count': len(lex),
        'max_entries': MAX_ENTRIES,
    })


@voice_lexicon_bp.route('/api/voice/lexicon', methods=['POST'])
@require_auth
def upsert_lexicon_entry():
    uid = _user_id_from_g()
    if not uid:
        return jsonify({'success': False, 'error': 'no user_id'}), 400

    data = request.get_json(silent=True) or {}
    original = (data.get('original') or '').strip()
    alias = (data.get('alias') or '').strip()

    if not original or not alias:
        return jsonify({'success': False, 'error': 'original and alias are required'}), 400
    if len(original) > MAX_ORIGINAL_LEN:
        return jsonify({'success': False, 'error': f'original too long (>{MAX_ORIGINAL_LEN} chars)'}), 400
    if len(alias) > MAX_ALIAS_LEN:
        return jsonify({'success': False, 'error': f'alias too long (>{MAX_ALIAS_LEN} chars)'}), 400

    profile, lex = _load_lexicon(uid)
    is_new = original not in lex
    if is_new and len(lex) >= MAX_ENTRIES:
        return jsonify({
            'success': False,
            'error': f'lexicon full ({MAX_ENTRIES} entries) — delete one first',
        }), 409

    lex[original] = alias
    _save_lexicon(uid, profile, lex)
    logger.info(f"voice_lexicon: user={uid} {'added' if is_new else 'updated'} '{original}' → '{alias}'")
    return jsonify({
        'success': True,
        'created': is_new,
        'entry': {'original': original, 'alias': alias},
        'count': len(lex),
    })


@voice_lexicon_bp.route('/api/voice/lexicon/<path:original>', methods=['DELETE'])
@require_auth
def delete_lexicon_entry(original):
    uid = _user_id_from_g()
    if not uid:
        return jsonify({'success': False, 'error': 'no user_id'}), 400

    original = (original or '').strip()
    if not original:
        return jsonify({'success': False, 'error': 'original required'}), 400

    profile, lex = _load_lexicon(uid)
    if original not in lex:
        return jsonify({'success': False, 'error': 'not found', 'count': len(lex)}), 404

    del lex[original]
    _save_lexicon(uid, profile, lex)
    logger.info(f"voice_lexicon: user={uid} removed '{original}'")
    return jsonify({'success': True, 'count': len(lex)})


@voice_lexicon_bp.route('/api/voice/lexicon', methods=['DELETE'])
@require_auth
def clear_lexicon():
    uid = _user_id_from_g()
    if not uid:
        return jsonify({'success': False, 'error': 'no user_id'}), 400

    profile, lex = _load_lexicon(uid)
    removed = len(lex)
    if removed:
        lex.clear()
        _save_lexicon(uid, profile, lex)
        logger.info(f"voice_lexicon: user={uid} cleared {removed} entries")
    return jsonify({'success': True, 'removed': removed, 'count': 0})
