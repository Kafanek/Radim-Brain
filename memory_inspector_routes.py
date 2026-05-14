"""
👁️ MEMORY INSPECTOR — GDPR-friendly "what does Radim remember about me" endpoint.

X21.25: Users have the right under GDPR to see what data is held about them.
This route returns a structured, human-readable snapshot of every piece of
memory Radim associates with the logged-in user:

  • profile basics (name, interests, family, health)
  • compressed long-term context (the summary written by memory_summarization)
  • recent activity counts (history rows, brain state count, last chat)
  • mood / cognitive trends from memory_learning
  • last known brain mode (HARMONY / ALERT / CRISIS)
  • crisis events (kept forever for safety — user can see them but not delete)

Authentication: JWT-required. User can only see their own memory.

Caregivers / admins can fetch any user via /api/admin/memory-stats and
/api/admin/debug-prompt/{user_id} (already exists).

Endpoint shape:
  GET /api/user/memory/me
  → {
      "user_id": "...",
      "profile": { "name", "interests", "family", "health", ... },
      "summary": "compressed long-term context (text)",
      "stats": {
          "messages_total": int,
          "messages_oldest": iso8601 or null,
          "brain_states": int,
          "last_chat_at": iso8601 or null,
          "last_mode": "HARMONY|ALERT|CRISIS|null",
      },
      "learning": { mood_trend, interest_mentions, family_mentions, ... },
      "crisis_count": int,
      "retention_info": "human-readable",
  }
"""

import json
import logging
from flask import Blueprint, jsonify, g

from auth_middleware import require_auth

logger = logging.getLogger(__name__)

memory_inspector_bp = Blueprint('memory_inspector', __name__)


def _safe_load_jsonb(value):
    """Profile / learning data may be a dict already (PG JSONB) or a JSON string."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return {}


@memory_inspector_bp.route('/api/user/memory/me', methods=['GET', 'OPTIONS'])
@require_auth
def get_my_memory():
    """Return everything Radim remembers about the authenticated user."""
    from flask import request
    if request.method == 'OPTIONS':
        return ('', 204)

    user_id = str(g.auth_user.get('id', '') or '')
    if not user_id:
        return jsonify({'success': False, 'error': 'no_user_id'}), 400

    try:
        from database import db_context, is_postgres
    except ImportError:
        return jsonify({'success': False, 'error': 'db_unavailable'}), 503

    is_pg = is_postgres()
    result = {'user_id': user_id, 'profile': {}, 'summary': None, 'stats': {},
              'learning': {}, 'crisis_count': 0}

    # ── Profile (long-term: name, interests, family, health) ──
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT data, updated_at FROM memory_profiles WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if row:
                data = _safe_load_jsonb(row['data'] if 'data' in row.keys() else row[0])
                # Pull just the senior-facing fields (skip preset internals etc.)
                friendly = {}
                for key in (
                    'name', 'age_group', 'interests', 'family', 'health',
                    'hearing', 'vision', 'memory_support',
                    'character', 'tone', 'communication_style',
                    'medications_list', 'medication_times',
                    'allergies', 'weight_kg',
                ):
                    if key in data and data[key]:
                        friendly[key] = data[key]
                result['profile'] = friendly
                # Compressed long-term context (the summary written by Gemini/Claude)
                ltc = data.get('long_term_context')
                if ltc:
                    if isinstance(ltc, dict):
                        result['summary'] = ltc.get('text') or ltc.get('summary') or None
                    else:
                        result['summary'] = str(ltc)[:2000]
                result['profile_updated_at'] = str(row['updated_at'])[:19] if 'updated_at' in row.keys() else None
    except Exception as e:
        logger.warning(f"memory_inspector profile load failed: {e}")

    # ── Activity stats ──
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) AS n, MIN(created_at) AS oldest, MAX(created_at) AS newest "
                "FROM memory_history WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if r:
                result['stats']['messages_total'] = r['n'] if 'n' in r.keys() else r[0]
                oldest = r['oldest'] if 'oldest' in r.keys() else r[1]
                newest = r['newest'] if 'newest' in r.keys() else r[2]
                result['stats']['messages_oldest'] = str(oldest)[:19] if oldest else None
                result['stats']['last_chat_at']    = str(newest)[:19] if newest else None
    except Exception as e:
        logger.warning(f"memory_inspector history stats failed: {e}")

    # ── Brain state count + last mode ──
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) AS n FROM brain_states WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if r:
                result['stats']['brain_states'] = r['n'] if 'n' in r.keys() else r[0]
        with db_context() as db:
            r = db.execute(
                "SELECT mode FROM brain_states WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            if r:
                result['stats']['last_mode'] = r['mode'] if 'mode' in r.keys() else r[0]
    except Exception as e:
        logger.warning(f"memory_inspector brain stats failed: {e}")

    # ── Learning aggregates (mood, interests, family mentions) ──
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT data FROM memory_learning WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if r:
                data = _safe_load_jsonb(r['data'] if 'data' in r.keys() else r[0])
                # Surface only the user-meaningful bits
                friendly = {}
                for key in (
                    'visits_total', 'visit_streak', 'topics_mentioned',
                    'family_members_mentioned', 'mood_trend',
                    'health_topics', 'preferred_topics',
                ):
                    if key in data:
                        friendly[key] = data[key]
                result['learning'] = friendly
    except Exception as e:
        logger.warning(f"memory_inspector learning load failed: {e}")

    # ── Crisis event count (visible to user, NOT deletable) ──
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) AS n FROM crisis_events WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            if r:
                result['crisis_count'] = r['n'] if 'n' in r.keys() else r[0]
    except Exception as e:
        logger.debug(f"memory_inspector crisis count failed: {e}")

    result['retention_info'] = (
        "memory_history is auto-trimmed to the last 50 messages per user; "
        "brain_states kept 90 days; agent observations 30 days; "
        "long-term profile and summary kept until you ask to delete them. "
        "Crisis events are kept indefinitely for safety auditing."
    )
    result['success'] = True
    return jsonify(result), 200


@memory_inspector_bp.route('/api/user/memory/forget-history', methods=['POST', 'OPTIONS'])
@require_auth
def forget_history():
    """Clear the conversation history (last 50 messages) but keep the
    long-term profile/summary. Lets a senior wipe a "bad day" of chats
    without losing the relationship Radim has built up.

    Distinct from GDPR /api/gdpr/delete which removes EVERYTHING.
    """
    from flask import request
    if request.method == 'OPTIONS':
        return ('', 204)

    user_id = str(g.auth_user.get('id', '') or '')
    if not user_id:
        return jsonify({'success': False, 'error': 'no_user_id'}), 400

    try:
        from memory_helpers import db_clear_history, audit_log
        db_clear_history(user_id)
        try:
            audit_log(
                user_id=user_id,
                action="memory_forget_history",
                resource="memory_history",
                detail="user-initiated short-term wipe",
            )
        except Exception:
            pass
        return jsonify({'success': True, 'message': 'history_cleared'}), 200
    except Exception as e:
        logger.error(f"forget_history failed: {e}")
        return jsonify({'success': False, 'error': str(e)[:120]}), 500


logger.info("✅ Memory Inspector Blueprint loaded: /api/user/memory/me, /api/user/memory/forget-history")
