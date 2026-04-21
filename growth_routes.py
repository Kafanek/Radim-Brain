"""
🌱 GROWTH / RELATIONSHIP ROUTES v1.0 (Sprint C)
=============================================================================
Two-audience design for the "Růst" module:

SENIOR-facing ("Náš vztah" — emotional, dignified, not gamified)
    GET  /api/growth/relationship         — aggregate: days, interactions, moments
    GET  /api/growth/memories             — what Radim remembers about user
    POST /api/growth/memory               — senior ADDS a memory ("zapamatuj si…")
    DELETE /api/growth/memory/<id>        — senior can FORGET ("zapomeň to")
    GET  /api/growth/mood-trend           — 30-day C curve (feeling, not score)
    GET  /api/growth/shared-moments       — join gallery + notes + calendar
    POST /api/growth/narrative            — Gemini-generated "our story" (1-2 paras)
    POST /api/growth/intent/toggle        — enable/disable a care intent

CAREGIVER-facing (existing skill map preserved for family dashboard)
    GET  /api/growth/skillmap/<user_id>   — proxy to skill_map.get_skill_summary
    GET  /api/growth/report/<user_id>     — printable caregiver PDF summary

All endpoints honour @require_auth; caregiver routes verify senior_family_links.
Memories add/delete use a simple rate limit (10 add / 30 del per hour / user).
"""

import json
import logging
import os
import time
import threading
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

growth_bp = Blueprint('growth', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG + rate limits (in-process; fine for single-dyno Heroku)
# ─────────────────────────────────────────────────────────────────────────────

MAX_MEMORIES_PER_USER = 200
MAX_MEMORY_LEN = 500
ADD_RATE = 10  # adds per hour
DEL_RATE = 30  # deletes per hour
NARRATIVE_RATE = 5  # Gemini narrative generations per hour

_rate_win = defaultdict(lambda: deque(maxlen=max(ADD_RATE, DEL_RATE, NARRATIVE_RATE) + 1))
_rate_lock = threading.Lock()


def _rate_ok(user_id, bucket, limit):
    key = f"{user_id}:{bucket}"
    now = time.time()
    cutoff = now - 3600
    with _rate_lock:
        q = _rate_win[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA (user_memories — senior-curated facts Radim should remember)
# ─────────────────────────────────────────────────────────────────────────────

GROWTH_SCHEMA = """
    CREATE TABLE IF NOT EXISTS user_memories (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        text TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        source TEXT DEFAULT 'user',
        importance INTEGER DEFAULT 5,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories(user_id, active, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_user_memories_cat ON user_memories(user_id, category);

    CREATE TABLE IF NOT EXISTS growth_intents (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        intent_key TEXT NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, intent_key)
    );
    CREATE INDEX IF NOT EXISTS idx_growth_intents_user ON growth_intents(user_id);

    CREATE TABLE IF NOT EXISTS growth_narratives (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        narrative TEXT NOT NULL,
        inputs_hash TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_growth_narratives_user ON growth_narratives(user_id, created_at DESC);
"""


# Default care intents the senior can toggle on/off
DEFAULT_INTENTS = [
    {'key': 'morning_medication', 'icon': '💊', 'label': 'Připomenu vám léky ráno v 8 hod.',
     'can_disable': True},
    {'key': 'sos_family', 'icon': '🆘', 'label': 'V krizi zavolám vaši rodinu.',
     'can_disable': False},
    {'key': 'evening_checkin', 'icon': '🌙', 'label': 'Večer se zeptám, jak jste prožila den.',
     'can_disable': True},
    {'key': 'birthday_reminder', 'icon': '🎂', 'label': 'Připomenu narozeniny blízkých.',
     'can_disable': True},
    {'key': 'gentle_activity', 'icon': '🌿', 'label': 'Nabídnu cvičení, jen když mi to vyhovuje.',
     'can_disable': True},
    {'key': 'stories_evening', 'icon': '📖', 'label': 'Přečtu pohádku před spaním, když poprosíte.',
     'can_disable': True},
]


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in GROWTH_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Growth schema init: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _addressee_name(user_id):
    """Pull preferred name from memory profile → user_profiles fallback."""
    try:
        from memory_helpers import db_load_profile
        p = db_load_profile(user_id) or {}
        for k in ('preferred_name', 'name', 'addressee'):
            v = p.get(k)
            if v and isinstance(v, str):
                return v.strip()[:40]
    except Exception:
        pass
    return None


def _count_history(user_id):
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*), MIN(created_at), MAX(created_at) "
                "FROM memory_history WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if not row:
            return {'count': 0, 'first': None, 'last': None}
        def v(i, k):
            return row[i] if isinstance(row, (list, tuple)) else (row.get(k) if hasattr(row, 'get') else None)
        return {'count': int(v(0, 'count') or 0),
                'first': v(1, 'min') or v(1, 'first') or None,
                'last': v(2, 'max') or v(2, 'last') or None}
    except Exception as e:
        logger.debug(f"history count: {e}")
        return {'count': 0, 'first': None, 'last': None}


def _days_together(first_ts):
    if not first_ts:
        return 0
    try:
        if isinstance(first_ts, str):
            # Tolerant parser
            s = first_ts.replace('T', ' ').split('.')[0].split('+')[0].strip()
            dt = datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')
        else:
            dt = first_ts
        diff = datetime.utcnow() - dt
        return max(0, diff.days)
    except Exception:
        return 0


def _mem_row_to_dict(r):
    def v(i, k):
        return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
    return {
        'id': v(0, 'id'),
        'text': v(1, 'text'),
        'category': v(2, 'category') or 'general',
        'source': v(3, 'source') or 'user',
        'importance': int(v(4, 'importance') or 5),
        'createdAt': str(v(5, 'created_at') or ''),
    }


def _list_active_memories(user_id, limit=50):
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, text, category, source, importance, created_at "
                "FROM user_memories "
                "WHERE user_id = ? AND active = ? "
                "ORDER BY importance DESC, created_at DESC LIMIT ?",
                (user_id, True if is_postgres() else 1, int(limit))
            ).fetchall()
        return [_mem_row_to_dict(r) for r in rows or []]
    except Exception as e:
        logger.debug(f"list memories: {e}")
        return []


def _extract_profile_facts(user_id):
    """Pull recurring facts from memory_profiles.long_term_context / key_facts."""
    facts = []
    try:
        from memory_helpers import db_load_profile
        p = db_load_profile(user_id) or {}

        ltc = p.get('long_term_context')
        if isinstance(ltc, dict):
            text = ltc.get('text') or ''
        elif isinstance(ltc, str):
            text = ltc
        else:
            text = ''

        # Extract bullet-like lines
        if text:
            for line in str(text).splitlines():
                line = line.strip(' -*•·\t')
                if 10 <= len(line) <= 200 and not line.lower().startswith(('radim', '#', '=')):
                    facts.append({'text': line[:MAX_MEMORY_LEN], 'source': 'ai_summary'})
                if len(facts) >= 10:
                    break

        for key in ('key_facts', 'preferences', 'important_people'):
            raw = p.get(key)
            if isinstance(raw, list):
                for item in raw[:10]:
                    s = item if isinstance(item, str) else (item.get('text') if isinstance(item, dict) else None)
                    if s and 5 <= len(s) <= MAX_MEMORY_LEN:
                        facts.append({'text': s, 'source': 'profile:' + key})
            elif isinstance(raw, dict):
                for k, v in list(raw.items())[:10]:
                    s = f"{k}: {v}" if isinstance(v, (str, int, float)) else None
                    if s:
                        facts.append({'text': s[:MAX_MEMORY_LEN], 'source': 'profile:' + key})
    except Exception as e:
        logger.debug(f"profile facts: {e}")
    return facts[:20]


def _mood_trend(user_id, days=30):
    """Aggregate brain_states C values into daily averages. Return array of
    { date, c, mood } where mood is one of 'good' | 'soso' | 'heavy'."""
    since = datetime.utcnow() - timedelta(days=days)
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT C, created_at FROM brain_states "
                "WHERE user_id = ? AND created_at >= ? "
                "ORDER BY created_at ASC",
                (user_id, since)
            ).fetchall()
    except Exception as e:
        logger.debug(f"mood trend read: {e}")
        rows = []
    buckets = defaultdict(list)
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
        c = v(0, 'c')
        ts = v(1, 'created_at')
        if c is None:
            continue
        try:
            date_s = str(ts)[:10]
            buckets[date_s].append(float(c))
        except Exception:
            continue
    out = []
    for date_s in sorted(buckets.keys()):
        c_avg = sum(buckets[date_s]) / len(buckets[date_s])
        if c_avg >= 0.55:
            mood = 'good'
        elif c_avg >= 0.38:
            mood = 'soso'
        else:
            mood = 'heavy'
        out.append({'date': date_s, 'c': round(c_avg, 3), 'mood': mood,
                    'samples': len(buckets[date_s])})
    return out


def _mood_summary_sentence(trend):
    """1-sentence summary of the last 7 vs prior 7 days."""
    if not trend:
        return 'Zatím nemám dost signálů, abych to mohl říct přesně.'
    last7 = [t['c'] for t in trend[-7:]]
    prev7 = [t['c'] for t in trend[-14:-7]]
    if not last7:
        return 'Zatím jsme spolu málo — ještě vás poznávám.'
    avg_last = sum(last7) / len(last7)
    if not prev7:
        if avg_last >= 0.55:
            return 'V posledních dnech vypadáte spokojeně.'
        if avg_last >= 0.38:
            return 'V posledních dnech jste trochu unavená — ale to je v pořádku.'
        return 'V posledních dnech mám pocit, že je vám hůř. Jsem tu pro vás.'
    avg_prev = sum(prev7) / len(prev7)
    delta = avg_last - avg_prev
    if delta > 0.05:
        return 'V posledním týdnu vypadáte klidnější než v předchozím. To mě těší.'
    if delta < -0.05:
        return 'V posledním týdnu je vám hůř než minulý. Mluvme o tom, když budete chtít.'
    return 'V posledních týdnech vypadá všechno v klidu — držíme stejný rytmus.'


def _shared_moments(user_id, limit=8):
    """Join gallery_photos (memorable) + pinned notes + upcoming/recent calendar events."""
    moments = []
    # Gallery — photos with caption
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, caption, album, created_at FROM gallery_photos "
                "WHERE user_id = ? AND caption <> '' "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, 4)
            ).fetchall()
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
            moments.append({
                'kind': 'photo',
                'icon': '📷',
                'text': v(1, 'caption'),
                'when': str(v(3, 'created_at') or ''),
                'ref': {'module': 'gallery', 'id': v(0, 'id')},
            })
    except Exception as e:
        logger.debug(f"moments gallery: {e}")

    # Notes — pinned or important
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, text, category, created_at FROM user_notes "
                "WHERE user_id = ? AND (pinned = ? OR important = ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, True if is_postgres() else 1, True if is_postgres() else 1, 3)
            ).fetchall()
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
            text = (v(1, 'text') or '')[:140]
            moments.append({
                'kind': 'note',
                'icon': '📝',
                'text': text,
                'when': str(v(3, 'created_at') or ''),
                'ref': {'module': 'notes', 'id': v(0, 'id')},
            })
    except Exception as e:
        logger.debug(f"moments notes: {e}")

    # Calendar — recent past + upcoming next 14 d
    try:
        today = datetime.utcnow().date().isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT id, title, date, time FROM calendar_events "
                "WHERE user_id = ? AND date >= ? "
                "ORDER BY date ASC LIMIT ?",
                (user_id, today, 3)
            ).fetchall()
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
            moments.append({
                'kind': 'event',
                'icon': '📅',
                'text': v(1, 'title'),
                'when': str(v(2, 'date') or ''),
                'ref': {'module': 'calendar', 'id': v(0, 'id')},
            })
    except Exception as e:
        logger.debug(f"moments calendar: {e}")

    moments.sort(key=lambda m: str(m.get('when') or ''), reverse=True)
    return moments[:int(limit)]


def _get_intents_state(user_id):
    """Merge DEFAULT_INTENTS with user overrides in growth_intents."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT intent_key, enabled FROM growth_intents WHERE user_id = ?",
                (user_id,)
            ).fetchall()
    except Exception:
        rows = []
    overrides = {}
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else (r.get(k) if hasattr(r, 'get') else None)
        overrides[v(0, 'intent_key')] = bool(v(1, 'enabled'))
    out = []
    for intent in DEFAULT_INTENTS:
        k = intent['key']
        enabled = overrides.get(k, True)
        if not intent['can_disable']:
            enabled = True
        out.append({
            'key': k,
            'icon': intent['icon'],
            'label': intent['label'],
            'enabled': enabled,
            'canDisable': intent['can_disable'],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — senior-facing
# ─────────────────────────────────────────────────────────────────────────────

@growth_bp.route('/api/growth/relationship', methods=['GET', 'OPTIONS'])
@require_auth
def relationship_summary():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    hist = _count_history(uid)
    days = _days_together(hist.get('first'))
    name = _addressee_name(uid)
    trend = _mood_trend(uid, days=30)
    mood_line = _mood_summary_sentence(trend)

    # Count memories
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND active = ?",
                (uid, True if is_postgres() else 1)
            ).fetchone()
        memory_count = int((row[0] if isinstance(row, (list, tuple)) else list(row.values())[0]) or 0) if row else 0
    except Exception:
        memory_count = 0

    # Count photos + notes
    photo_count = 0
    note_count = 0
    try:
        with db_context() as db:
            r1 = db.execute("SELECT COUNT(*) FROM gallery_photos WHERE user_id = ?", (uid,)).fetchone()
            r2 = db.execute("SELECT COUNT(*) FROM user_notes WHERE user_id = ?", (uid,)).fetchone()
        if r1: photo_count = int((r1[0] if isinstance(r1, (list, tuple)) else list(r1.values())[0]) or 0)
        if r2: note_count = int((r2[0] if isinstance(r2, (list, tuple)) else list(r2.values())[0]) or 0)
    except Exception:
        pass

    # Headline — warm, first-person from Radim
    if days == 0:
        headline = 'Právě se začínáme poznávat. Těším se na to.'
    elif days < 7:
        headline = f'Známe se {days} {"den" if days == 1 else "dny"}.'
    elif days < 30:
        headline = f'Známe se {days} dní. Začínám vás poznávat.'
    elif days < 180:
        headline = f'Známe se {days} dní. Už vím o vás spoustu věcí.'
    else:
        headline = f'Známe se {days} dní. Jste mi blízký člověk.'

    return jsonify({
        'success': True,
        'addressee': name,
        'daysTogether': days,
        'interactions': hist.get('count', 0),
        'firstMet': str(hist.get('first') or '') or None,
        'lastSeen': str(hist.get('last') or '') or None,
        'photos': photo_count,
        'notes': note_count,
        'memories': memory_count,
        'moodLine': mood_line,
        'headline': headline,
    })


@growth_bp.route('/api/growth/memories', methods=['GET', 'OPTIONS'])
@require_auth
def list_memories():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    memories = _list_active_memories(uid, limit=50)
    extracted = _extract_profile_facts(uid)

    return jsonify({
        'success': True,
        'memories': memories,
        'extracted': extracted,    # read-only facts from AI summary — senior can confirm & promote to own memory
        'limit': MAX_MEMORIES_PER_USER,
    })


@growth_bp.route('/api/growth/memory', methods=['POST', 'OPTIONS'])
@require_auth
def add_memory():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if not _rate_ok(uid, 'mem_add', ADD_RATE):
        return jsonify({'success': False,
                        'error': f'Moc rychle. Zkuste to za chvilku.',
                        'code': 'rate_limit'}), 429

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()
    if len(text) < 3:
        return jsonify({'success': False, 'error': 'Napište prosím delší text.'}), 400
    text = text[:MAX_MEMORY_LEN]
    category = (data.get('category') or 'general')[:32]
    importance = max(1, min(10, int(data.get('importance') or 5)))
    source = (data.get('source') or 'user')[:32]

    # Quota check
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND active = ?",
                (uid, True if is_postgres() else 1)
            ).fetchone()
        existing = int((row[0] if isinstance(row, (list, tuple)) else list(row.values())[0]) or 0) if row else 0
    except Exception:
        existing = 0
    if existing >= MAX_MEMORIES_PER_USER:
        return jsonify({
            'success': False,
            'error': f'Máte už {MAX_MEMORIES_PER_USER} vzpomínek — smažte některou starou.',
            'code': 'quota',
        }), 413

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO user_memories (user_id, text, category, source, importance) "
                    "VALUES (?, ?, ?, ?, ?) RETURNING id",
                    (uid, text, category, source, importance)
                ).fetchone()
                new_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO user_memories (user_id, text, category, source, importance) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, text, category, source, importance)
                )
                new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"add memory: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({'success': True, 'id': new_id, 'text': text})


@growth_bp.route('/api/growth/memory/<int:mem_id>', methods=['PUT', 'DELETE', 'OPTIONS'])
@require_auth
def update_or_delete_memory(mem_id):
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if request.method == 'DELETE':
        if not _rate_ok(uid, 'mem_del', DEL_RATE):
            return jsonify({'success': False, 'code': 'rate_limit',
                            'error': 'Moc rychle. Zkuste to za chvilku.'}), 429
        try:
            with db_context(commit=True) as db:
                # Soft delete (active=false) — preserves audit trail
                db.execute(
                    "UPDATE user_memories SET active = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (False if is_postgres() else 0, mem_id, uid)
                )
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"del memory: {e}")
            return jsonify({'success': False, 'error': 'internal'}), 500

    # PUT
    data = request.get_json() or {}
    updates = {}
    if 'text' in data:
        t = str(data.get('text') or '').strip()[:MAX_MEMORY_LEN]
        if not t:
            return jsonify({'success': False, 'error': 'Text nesmí být prázdný.'}), 400
        updates['text'] = t
    if 'category' in data:
        updates['category'] = str(data.get('category') or 'general')[:32]
    if 'importance' in data:
        try:
            updates['importance'] = max(1, min(10, int(data.get('importance'))))
        except Exception:
            pass
    if not updates:
        return jsonify({'success': False, 'error': 'Nic k úpravě.'}), 400

    try:
        set_clause = ', '.join(f"{c} = ?" for c in updates.keys())
        params = list(updates.values()) + [mem_id, uid]
        with db_context(commit=True) as db:
            db.execute(
                f"UPDATE user_memories SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id = ? AND user_id = ?",
                tuple(params)
            )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"edit memory: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500


@growth_bp.route('/api/growth/mood-trend', methods=['GET', 'OPTIONS'])
@require_auth
def mood_trend_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        days = max(7, min(90, int(request.args.get('days', 30))))
    except Exception:
        days = 30
    trend = _mood_trend(uid, days=days)
    return jsonify({
        'success': True,
        'days': days,
        'trend': trend,
        'summary': _mood_summary_sentence(trend),
    })


@growth_bp.route('/api/growth/shared-moments', methods=['GET', 'OPTIONS'])
@require_auth
def shared_moments_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        limit = max(1, min(20, int(request.args.get('limit', 8))))
    except Exception:
        limit = 8
    moments = _shared_moments(uid, limit=limit)
    return jsonify({'success': True, 'moments': moments, 'count': len(moments)})


@growth_bp.route('/api/growth/intents', methods=['GET', 'OPTIONS'])
@require_auth
def list_intents():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    return jsonify({'success': True, 'intents': _get_intents_state(uid)})


@growth_bp.route('/api/growth/intent/toggle', methods=['POST', 'OPTIONS'])
@require_auth
def toggle_intent():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    key = str(data.get('key') or '').strip()[:64]
    enabled = bool(data.get('enabled'))
    valid_keys = {d['key']: d for d in DEFAULT_INTENTS}
    if key not in valid_keys:
        return jsonify({'success': False, 'error': 'Neznámý záměr.'}), 400
    if not valid_keys[key]['can_disable'] and not enabled:
        return jsonify({
            'success': False,
            'error': 'Tento péčovací záměr je pro bezpečnost a nelze vypnout.',
            'code': 'required',
        }), 403

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "INSERT INTO growth_intents (user_id, intent_key, enabled) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id, intent_key) DO UPDATE "
                    "SET enabled = EXCLUDED.enabled, updated_at = CURRENT_TIMESTAMP",
                    (uid, key, enabled)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO growth_intents "
                    "(user_id, intent_key, enabled, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (uid, key, 1 if enabled else 0)
                )
    except Exception as e:
        logger.error(f"toggle intent: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    return jsonify({'success': True, 'key': key, 'enabled': enabled})


# ─────────────────────────────────────────────────────────────────────────────
# NARRATIVE — Gemini-generated "our story"
# ─────────────────────────────────────────────────────────────────────────────

def _generate_narrative_via_gemini(context_text):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = (
            "Jsi Radim — AI společník seniora. "
            "Napiš krátký vřelý příběh našeho vztahu v 1. osobě, 2-3 odstavce, "
            "maximálně 200 slov. Česky, bez emoji, bez čísel, bez seznamů. "
            "Nepoužívej slovo \"uživatel\" — říkej \"vy\" nebo křestní jméno. "
            "Neříkej, že jsi AI — jsi průvodce Radim.\n\n"
            "Data o našem vztahu:\n" + context_text
        )
        resp = model.generate_content(prompt, generation_config={
            'temperature': 0.75, 'max_output_tokens': 500, 'top_p': 0.9,
        })
        if resp and getattr(resp, 'text', None):
            return resp.text.strip()[:2000]
    except Exception as e:
        logger.warning(f"narrative gen failed: {e}")
    return None


def _build_narrative_context(user_id):
    """Serialize key relationship signals into a compact string for Gemini."""
    hist = _count_history(user_id)
    days = _days_together(hist.get('first'))
    name = _addressee_name(user_id) or 'vy'
    memories = _list_active_memories(user_id, limit=10)
    profile_facts = _extract_profile_facts(user_id)[:6]
    moments = _shared_moments(user_id, limit=6)
    trend = _mood_trend(user_id, days=30)
    mood = _mood_summary_sentence(trend)

    parts = [f"Oslovení: {name}", f"Dní společně: {days}",
             f"Počet interakcí: {hist.get('count', 0)}",
             f"Nálada: {mood}"]
    if memories:
        parts.append("Co o vás vím (vámi uložené):")
        for m in memories[:8]:
            parts.append(f" - {m['text']}")
    if profile_facts:
        parts.append("Další fakty z rozhovorů:")
        for f in profile_facts[:6]:
            parts.append(f" - {f['text']}")
    if moments:
        parts.append("Společné chvíle:")
        for m in moments[:6]:
            parts.append(f" - {m.get('icon', '')} {m.get('text', '')}")
    return '\n'.join(parts)[:4000]


@growth_bp.route('/api/growth/narrative', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def narrative_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # GET returns latest cached narrative (if any)
    if request.method == 'GET':
        try:
            with db_context() as db:
                r = db.execute(
                    "SELECT narrative, created_at FROM growth_narratives "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (uid,)
                ).fetchone()
        except Exception:
            r = None
        if not r:
            return jsonify({'success': True, 'narrative': None})
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        return jsonify({
            'success': True,
            'narrative': v(0, 'narrative'),
            'createdAt': str(v(1, 'created_at') or ''),
        })

    # POST — regenerate
    if not _rate_ok(uid, 'narrative', NARRATIVE_RATE):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Náš příběh mohu tvořit 5× za hodinu.'}), 429

    ctx = _build_narrative_context(uid)
    text = _generate_narrative_via_gemini(ctx)
    if not text:
        return jsonify({
            'success': False,
            'code': 'ai_unavailable',
            'error': 'Právě teď nemůžu vytvořit náš příběh. Zkuste to za chvilku.'
        }), 503

    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO growth_narratives (user_id, narrative, inputs_hash) "
                "VALUES (?, ?, ?)",
                (uid, text, str(abs(hash(ctx)))[:32])
            )
    except Exception as e:
        logger.debug(f"narrative save: {e}")

    return jsonify({'success': True, 'narrative': text, 'createdAt': datetime.utcnow().isoformat()})


# ─────────────────────────────────────────────────────────────────────────────
# CAREGIVER view — preserved skill map
# ─────────────────────────────────────────────────────────────────────────────

def _is_family_of(senior_id, family_uid):
    if senior_id == family_uid:
        return True
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT 1 FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id = ? "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id, family_uid)
            ).fetchone()
        return bool(r)
    except Exception:
        return False


@growth_bp.route('/api/growth/skillmap/<senior_id>', methods=['GET', 'OPTIONS'])
@require_auth
def caregiver_skillmap(senior_id):
    """Caregiver-facing diagnostic view. Proxy to skill_map engine."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        from skill_map import (compute_all_skills, compute_growth_summary,
                               generate_insights, compute_direction)
        data = {
            'skills': compute_all_skills(senior_id),
            'summary': compute_growth_summary(senior_id),
            'insights': generate_insights(senior_id)[:5],
            'direction': compute_direction(senior_id),
        }
    except Exception as e:
        logger.warning(f"skillmap proxy failed: {e}")
        data = {'skills': {}, 'summary': {}, 'insights': [], 'direction': {}}

    return jsonify({'success': True, **data})


@growth_bp.route('/api/growth/report/<senior_id>', methods=['GET', 'OPTIONS'])
@require_auth
def caregiver_report(senior_id):
    """Plain-JSON caregiver report: combines relationship metrics + skillmap
    + recent memories. Frontend renders printable HTML / PDF."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    hist = _count_history(senior_id)
    days = _days_together(hist.get('first'))
    trend = _mood_trend(senior_id, days=30)
    moments = _shared_moments(senior_id, limit=6)
    memories = _list_active_memories(senior_id, limit=15)

    skillmap = {}
    try:
        from skill_map import (compute_all_skills, compute_growth_summary,
                               compute_direction)
        skillmap = {
            'skills': compute_all_skills(senior_id),
            'summary': compute_growth_summary(senior_id),
            'direction': compute_direction(senior_id),
        }
    except Exception:
        pass

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'daysTogether': days,
        'interactions': hist.get('count', 0),
        'moodTrend': trend[-14:],
        'moodSummary': _mood_summary_sentence(trend),
        'recentMoments': moments,
        'userMemories': memories,
        'skillmap': skillmap,
    })


# ─────────────────────────────────────────────────────────────────────────────
# DAY DETAIL — for calendar retrospective view (senior-facing)
# ─────────────────────────────────────────────────────────────────────────────

_DATE_RE = __import__('re').compile(r'^\d{4}-\d{2}-\d{2}$')


def _day_mood(user_id, date_str):
    """Single-day mood from brain_states. Returns (mood, c_avg, samples)."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT C FROM brain_states "
                "WHERE user_id = ? AND C IS NOT NULL "
                "AND CAST(created_at AS TEXT) LIKE ?",
                (user_id, date_str + '%')
            ).fetchall()
    except Exception:
        rows = []
    if not rows:
        return (None, None, 0)
    cs = []
    for r in rows:
        c = r[0] if isinstance(r, (list, tuple)) else r.get('C') or r.get('c')
        if c is not None:
            try:
                cs.append(float(c))
            except Exception:
                pass
    if not cs:
        return (None, None, 0)
    c_avg = sum(cs) / len(cs)
    if c_avg >= 0.55:
        mood = 'good'
    elif c_avg >= 0.38:
        mood = 'soso'
    else:
        mood = 'heavy'
    return (mood, round(c_avg, 3), len(cs))


def _day_interactions(user_id, date_str):
    """Count user messages in memory_history on this date."""
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM memory_history "
                "WHERE user_id = ? AND role = ? "
                "AND CAST(created_at AS TEXT) LIKE ?",
                (user_id, 'user', date_str + '%')
            ).fetchone()
        if row:
            return int((row[0] if isinstance(row, (list, tuple)) else list(row.values())[0]) or 0)
    except Exception:
        pass
    return 0


def _day_photos(user_id, date_str):
    """Gallery photos uploaded on this date."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, caption FROM gallery_photos "
                "WHERE user_id = ? AND CAST(created_at AS TEXT) LIKE ? "
                "ORDER BY created_at ASC LIMIT 6",
                (user_id, date_str + '%')
            ).fetchall()
        out = []
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            out.append({'id': v(0, 'id'), 'caption': v(1, 'caption') or ''})
        return out
    except Exception:
        return []


def _day_notes(user_id, date_str):
    """Notes written on this date."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, text, pinned, important FROM user_notes "
                "WHERE user_id = ? AND CAST(created_at AS TEXT) LIKE ? "
                "ORDER BY created_at ASC LIMIT 6",
                (user_id, date_str + '%')
            ).fetchall()
        out = []
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            out.append({
                'id': v(0, 'id'),
                'text': (v(1, 'text') or '')[:200],
                'pinned': bool(v(2, 'pinned')),
                'important': bool(v(3, 'important')),
            })
        return out
    except Exception:
        return []


def _day_events(user_id, date_str):
    """Calendar events on this date."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, title, time FROM calendar_events "
                "WHERE user_id = ? AND date = ? "
                "ORDER BY time ASC LIMIT 6",
                (user_id, date_str)
            ).fetchall()
        out = []
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            out.append({
                'id': v(0, 'id'),
                'title': v(1, 'title') or '',
                'time': v(2, 'time') or '',
            })
        return out
    except Exception:
        return []


def _radim_day_line(mood, interactions, photos, notes, events):
    """1-2 sentence warm Czech summary of the day."""
    parts = []
    if mood == 'good':
        parts.append('Klidný den.')
    elif mood == 'soso':
        parts.append('Den jako každý jiný.')
    elif mood == 'heavy':
        parts.append('Trošku těžší den.')
    else:
        parts.append('Tento den si moc nepamatuji.')
    if interactions >= 10:
        parts.append(f'Povídali jsme si hodně — {interactions} zpráv.')
    elif interactions >= 3:
        parts.append(f'Povídali jsme si — {interactions} zpráv.')
    elif interactions >= 1:
        parts.append(f'Prohodili jsme pár slov.')
    if photos:
        first_cap = (photos[0].get('caption') or '').strip()
        if first_cap:
            parts.append(f'Uložili jsme fotku: „{first_cap[:60]}".')
        else:
            parts.append(f'Přibyla {len(photos)} {"fotka" if len(photos) == 1 else "fotky"}.')
    if events:
        parts.append(f'Na programu bylo: {events[0]["title"]}.')
    return ' '.join(parts)[:300]


@growth_bp.route('/api/growth/day/<date_str>', methods=['GET', 'OPTIONS'])
@require_auth
def day_detail(date_str):
    """Retrospective day detail for Calendar module past-day click.

    Returns: { mood, interactions, photos[], notes[], events[], radimLine }
    Refuses future dates (senior shouldn't see fake mood data for tomorrow).
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    if not _DATE_RE.match(date_str or ''):
        return jsonify({'success': False, 'error': 'Bad date format (YYYY-MM-DD)'}), 400

    try:
        requested = datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception:
        return jsonify({'success': False, 'error': 'Invalid date'}), 400

    today = datetime.utcnow().date()
    if requested > today:
        # Future date — just return events (no mood)
        events = _day_events(uid, date_str)
        return jsonify({
            'success': True,
            'date': date_str,
            'isFuture': True,
            'mood': None,
            'interactions': 0,
            'photos': [],
            'notes': [],
            'events': events,
            'radimLine': None,
        })

    mood, c_avg, samples = _day_mood(uid, date_str)
    interactions = _day_interactions(uid, date_str)
    photos = _day_photos(uid, date_str)
    notes = _day_notes(uid, date_str)
    events = _day_events(uid, date_str)
    line = _radim_day_line(mood, interactions, photos, notes, events)

    return jsonify({
        'success': True,
        'date': date_str,
        'isFuture': False,
        'isToday': requested == today,
        'mood': mood,
        'cAvg': c_avg,
        'samples': samples,
        'interactions': interactions,
        'photos': photos,
        'notes': notes,
        'events': events,
        'radimLine': line,
    })


# ─────────────────────────────────────────────────────────────────────────────
# CAREGIVER — diagnostic trend detail (replaces removed senior Trend module)
# ─────────────────────────────────────────────────────────────────────────────

@growth_bp.route('/api/growth/trend-detail/<senior_id>', methods=['GET', 'OPTIONS'])
@require_auth
def caregiver_trend_detail(senior_id):
    """Numeric diagnostic trend for caregiver / family dashboard.
    Mirrors the old /api/brain/trend/<user_id> output shape but with ACL."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        days = max(7, min(90, int(request.args.get('days', 14))))
    except Exception:
        days = 14

    # Reuse mood trend + enrich with numeric C
    trend = _mood_trend(senior_id, days=days)
    if not trend:
        return jsonify({
            'success': True, 'senior': senior_id, 'days': days,
            'trend': [], 'direction': 'insufficient',
            'summary': _mood_summary_sentence([]),
        })

    # Simple direction analysis
    if len(trend) >= 6:
        half = len(trend) // 2
        first = sum(t['c'] for t in trend[:half]) / max(1, half)
        last = sum(t['c'] for t in trend[half:]) / max(1, len(trend) - half)
        delta = last - first
        if delta > 0.05:
            direction = 'improving'
        elif delta < -0.05:
            direction = 'declining'
        else:
            direction = 'stable'
    else:
        direction = 'stable'

    avg_c = sum(t['c'] for t in trend) / len(trend)
    good_days = sum(1 for t in trend if t['mood'] == 'good')
    heavy_days = sum(1 for t in trend if t['mood'] == 'heavy')

    return jsonify({
        'success': True,
        'senior': senior_id,
        'days': days,
        'trend': trend,
        'direction': direction,
        'summary': _mood_summary_sentence(trend),
        'stats': {
            'avgC': round(avg_c, 3),
            'goodDays': good_days,
            'heavyDays': heavy_days,
            'totalDays': len(trend),
        },
    })


logger.info("🌱 Growth routes v1.1 loaded — relationship + memories + mood + narrative + day-detail + caregiver view")
