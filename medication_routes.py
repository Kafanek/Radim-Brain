"""
💊 MEDICATION ROUTES — knowledge lookup + interaction check (v466)
=================================================================

Public lookup (no auth — knowledge is public health info):
  GET  /api/medication/info?name=Warfarin       → drug card
  GET  /api/medication/info/full?name=X         → full description (voice)
  GET  /api/medication/db/stats                 → DB inventory

Authenticated (per-user):
  GET  /api/medication/check                    → check interactions in user's stack
  GET  /api/medication/list                     → user's meds resolved against DB

Used by:
  - intent_resolver.medication_info handler ('co je Warfarin')
  - frontend medical-module.js (drug card on tap)
  - agent_loop (pre-flight interaction check before recommending OTC)
"""

import logging
from flask import Blueprint, request, jsonify, g

logger = logging.getLogger(__name__)

medication_bp = Blueprint('medication', __name__)


def _public_card(entry, full=False):
    """Strip internal fields, return TTS-friendly card."""
    if not entry:
        return None
    card = {
        'name': entry['name'],
        'group': entry.get('group_human', ''),
        'group_slug': entry.get('group', ''),
        'indication': entry.get('indication', ''),
        'food': entry.get('food', ''),
        'warnings': entry.get('warnings', []),
        'typical_dose': entry.get('typical_dose', ''),
        'aliases': entry.get('aliases', []),
        '_match_quality': entry.get('_match', 'unknown'),
    }
    return card


@medication_bp.route('/api/medication/info', methods=['GET'])
def medication_info():
    """Lookup medication by name or alias. Returns brief card + voice text."""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'name parameter required'}), 400
    try:
        from medication_db import lookup, speak_brief
        entry = lookup(name)
        if not entry:
            return jsonify({
                'success': False,
                'error': f"Lék '{name}' není v databázi. Zkuste přesný název nebo zkonzultujte s lékárníkem.",
                'voice': f"Lék {name} v mé databázi nemám. Zeptejte se lékárníka.",
                'searched': name,
            }), 404
        return jsonify({
            'success': True,
            'searched': name,
            'card': _public_card(entry),
            'voice': speak_brief(name),
        })
    except Exception as e:
        logger.warning(f"medication_info error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@medication_bp.route('/api/medication/info/full', methods=['GET'])
def medication_info_full():
    """Longer voice description (dose + food + warnings)."""
    name = (request.args.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'name parameter required'}), 400
    try:
        from medication_db import lookup, speak_full
        entry = lookup(name)
        if not entry:
            return jsonify({
                'success': False,
                'error': f"Lék '{name}' není v databázi.",
                'searched': name,
            }), 404
        return jsonify({
            'success': True,
            'searched': name,
            'card': _public_card(entry, full=True),
            'voice': speak_full(name),
        })
    except Exception as e:
        logger.warning(f"medication_info_full error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@medication_bp.route('/api/medication/db/stats', methods=['GET'])
def medication_db_stats():
    """Inventory stats — useful for admin / debugging which drugs are covered."""
    try:
        from medication_db import db_stats
        return jsonify({'success': True, **db_stats()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@medication_bp.route('/api/medication/check', methods=['GET'])
def medication_check():
    """Check the authenticated user's medications_list for known interactions.

    Returns list of warnings (HIGH / MEDIUM / LOW) + summary count.
    Auth via JWT bearer (require_auth not strictly needed here because
    user_id is passed; we accept query param for admin/family use).
    """
    user_id = (request.args.get('user_id') or '').strip()
    if not user_id:
        # Try the auth_user from g if available (when called via JWT chain)
        try:
            uid = (getattr(g, 'auth_user', None) or {}).get('id')
            user_id = str(uid) if uid is not None else ''
        except Exception:
            user_id = ''
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        from drug_interactions import check_user_interactions
        warnings = check_user_interactions(user_id)
    except Exception as e:
        logger.warning(f"interaction check error for {user_id}: {e}")
        warnings = []

    severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    for w in warnings:
        s = w.get('severity', 'LOW')
        severity_counts[s] = severity_counts.get(s, 0) + 1

    return jsonify({
        'success': True,
        'user_id': user_id,
        'interactions': warnings,
        'count': len(warnings),
        'severity_counts': severity_counts,
        'safe': len(warnings) == 0,
    })


@medication_bp.route('/api/medication/unknown', methods=['POST'])
def flag_unknown_medication():
    """v467: crowdsource flag — when senior asks about a med that isn't in
    our DB, log it for admin review so we can prioritize what to add next.

    Body: {name, user_id (optional), context (optional)}
    Storage: profile JSONB has no 'unknown_meds_seen' aggregator yet, so we
    log to a flat global JSONB record under user 'admin' (singleton). Cheap
    and survives dyno restarts via Postgres."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    user_id = (data.get('user_id') or 'anonymous').strip()
    context = (data.get('context') or '').strip()[:200]

    if not name or len(name) > 80:
        return jsonify({'success': False, 'error': 'invalid name'}), 400

    try:
        from datetime import datetime, timezone
        from memory_helpers import db_load_profile, db_save_profile
        admin_profile = db_load_profile('__admin_unknown_meds__') or {}
        queue = admin_profile.get('queue') or []
        if not isinstance(queue, list):
            queue = []
        # Cap to last 200 entries
        if len(queue) >= 200:
            queue = queue[-200:]
        # Dedup by name within last hour for same user
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        recent_dup = any(
            (e.get('name', '').lower() == name.lower()
             and e.get('user_id') == user_id
             and (now - datetime.fromisoformat(e.get('flagged_at', '').replace('Z', '+00:00'))).total_seconds() < 3600)
            for e in queue
            if isinstance(e, dict) and e.get('flagged_at')
        )
        if recent_dup:
            return jsonify({'success': True, 'duplicate': True, 'queue_size': len(queue)})

        queue.append({
            'name': name,
            'user_id': user_id,
            'context': context,
            'flagged_at': now.isoformat(),
        })
        admin_profile['queue'] = queue
        db_save_profile('__admin_unknown_meds__', admin_profile)
        return jsonify({'success': True, 'queue_size': len(queue)})
    except Exception as e:
        logger.warning(f"flag_unknown_medication error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@medication_bp.route('/api/medication/unknown', methods=['GET'])
def list_unknown_queue():
    """Admin view of unknown-med queue — sorted by frequency desc."""
    try:
        from collections import Counter
        from memory_helpers import db_load_profile
        admin_profile = db_load_profile('__admin_unknown_meds__') or {}
        queue = admin_profile.get('queue') or []
        if not isinstance(queue, list):
            queue = []
        # Aggregate by name
        names = Counter(e.get('name', '').strip() for e in queue
                        if isinstance(e, dict) and e.get('name'))
        unique = [{'name': n, 'count': c, 'top_user_examples': [
            e.get('user_id') for e in queue
            if isinstance(e, dict) and e.get('name') == n
        ][:3]} for n, c in names.most_common(50)]
        return jsonify({
            'success': True,
            'queue_size': len(queue),
            'unique_names': len(names),
            'top_unknown': unique,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@medication_bp.route('/api/medication/list', methods=['GET'])
def medication_list_for_user():
    """Return the user's medication list resolved against the drug DB.

    For each med in profile.medications_list, returns the name AND
    (if found in DB) the knowledge card. Useful for frontend medical
    module to render full info per drug instead of just bare names.
    """
    user_id = (request.args.get('user_id') or '').strip()
    if not user_id:
        try:
            uid = (getattr(g, 'auth_user', None) or {}).get('id')
            user_id = str(uid) if uid is not None else ''
        except Exception:
            user_id = ''
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        from medication_db import list_for_user
        items = list_for_user(user_id)
        resolved = [{'input_name': it['input_name'],
                     'card': _public_card(it['entry']) if it.get('entry') else None}
                    for it in items]
        return jsonify({
            'success': True,
            'user_id': user_id,
            'count': len(resolved),
            'in_db': sum(1 for r in resolved if r['card']),
            'unknown': sum(1 for r in resolved if not r['card']),
            'medications': resolved,
        })
    except Exception as e:
        logger.warning(f"medication_list error for {user_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
