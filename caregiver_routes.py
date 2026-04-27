"""
👩‍⚕️ CAREGIVER ROUTES v1.0
=============================================================================
Partner view for family + professional caregivers.

Philosophy:
    - Family sees ONE loved one (mother, grandmother).
    - Professional sees MANY seniors.
    - Both see Radim as partner (not a dashboard).

Endpoints
---------
    GET /api/caregiver/view-mode                     — family | professional | none
    GET /api/caregiver/seniors                       — list with enriched cards
    GET /api/caregiver/senior/<id>/overview          — rich detail (hero card)
    GET /api/caregiver/senior/<id>/safe-to-call      — dignity + activity check
    GET /api/caregiver/senior/<id>/narrative         — Gemini-generated daily summary (cached 6h)
    GET /api/caregiver/senior/<id>/legacy-preview    — counts of contributions/messages earmarked for heir
    GET /api/caregiver/senior/<id>/shared-gallery    — photos shared with family
    GET /api/caregiver/senior/<id>/wisdom-cloud      — aggregated themes, people, places
    GET /api/caregiver/senior/<id>/live-activity     — what the senior is doing right now
    GET /api/caregiver/notifications                 — unread caregiver alerts
    POST /api/caregiver/notification/<id>/ack        — mark read

Auth model: every endpoint uses @require_auth AND checks senior_family_links
(except /seniors and /view-mode which use role + link aggregation).
"""

import json
import logging
import os
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres
from ai_config import GEMINI_MODEL

logger = logging.getLogger(__name__)

caregiver_bp = Blueprint('caregiver', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA — caregiver notifications + decline reasons
# ─────────────────────────────────────────────────────────────────────────────

CAREGIVER_SCHEMA = """
    CREATE TABLE IF NOT EXISTS caregiver_notifications (
        id SERIAL PRIMARY KEY,
        recipient_id TEXT NOT NULL,
        senior_id TEXT,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        severity TEXT DEFAULT 'info',
        ref_type TEXT,
        ref_id INTEGER,
        data JSONB,
        read_at TIMESTAMP,
        acted_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cg_notif_recipient ON caregiver_notifications(recipient_id, read_at, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_cg_notif_senior ON caregiver_notifications(senior_id, type);

    CREATE TABLE IF NOT EXISTS caregiver_cosign_declines (
        id SERIAL PRIMARY KEY,
        contract_id INTEGER NOT NULL,
        senior_id TEXT NOT NULL,
        caregiver_id TEXT NOT NULL,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cg_decline_contract ON caregiver_cosign_declines(contract_id);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in CAREGIVER_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Caregiver schema init: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

NARRATIVE_CACHE_HOURS = 6
_narrative_cache = {}
_narrative_lock = threading.Lock()


# Rate limiter for Gemini-heavy endpoints
_rate_win = defaultdict(lambda: deque(maxlen=50))
_rate_lock = threading.Lock()


def _rate_ok(user_id, bucket, limit, window_seconds=3600):
    key = f"{user_id}:{bucket}"
    now = time.time()
    cutoff = now - window_seconds
    with _rate_lock:
        q = _rate_win[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _role():
    au = getattr(g, 'auth_user', None) or {}
    return (au.get('role') or au.get('user', {}).get('role') or '').lower()


def _list_linked_seniors(family_uid):
    """Return list of (senior_id, senior_name, relation) for confirmed links."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT senior_id, family_name, relation "
                "FROM senior_family_links "
                "WHERE family_user_id = ? AND confirmed_at IS NOT NULL "
                "AND revoked_at IS NULL",
                (family_uid,)
            ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        out.append({
            'seniorId': v(0, 'senior_id'),
            'familyName': v(1, 'family_name'),
            'relation': v(2, 'relation'),
        })
    return out


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


def _addressee_name(user_id):
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


def _last_interaction(user_id):
    """Return timestamp + minutes-ago of last user message."""
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT MAX(created_at) FROM memory_history "
                "WHERE user_id = ? AND role = ?",
                (user_id, 'user')
            ).fetchone()
    except Exception:
        return None, None
    if not r:
        return None, None
    ts = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
    if not ts:
        return None, None
    try:
        dt = datetime.strptime(str(ts)[:19], '%Y-%m-%d %H:%M:%S')
        delta = (datetime.utcnow() - dt).total_seconds()
        return str(ts), int(delta / 60)
    except Exception:
        return str(ts), None


def _recent_c_avg(user_id, hours=2):
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT AVG(C), COUNT(*) FROM brain_states "
                "WHERE user_id = ? AND C IS NOT NULL AND created_at >= ?",
                (user_id, datetime.utcnow() - timedelta(hours=hours))
            ).fetchone()
    except Exception:
        return None, 0
    if not r:
        return None, 0
    def v(i):
        return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
    try:
        return float(v(0) or 0), int(v(1) or 0)
    except Exception:
        return None, 0


# ─────────────────────────────────────────────────────────────────────────────
# VIEW MODE — family | professional | none
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/view-mode', methods=['GET', 'OPTIONS'])
@require_auth
def view_mode():
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    role = _role()
    linked = _list_linked_seniors(uid)
    professional = role in ('caregiver', 'teacher', 'administrator', 'admin')

    if professional:
        mode = 'professional'
    elif len(linked) == 1:
        mode = 'family'
    elif len(linked) > 1:
        mode = 'family_multi'
    else:
        mode = 'none'

    return jsonify({
        'success': True,
        'mode': mode,
        'role': role,
        'linkedSeniors': linked,
        'seniorCount': len(linked),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SAFE-TO-CALL — should family call right now?
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/safe-to-call', methods=['GET'])
@require_auth
def safe_to_call(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    hour = datetime.utcnow().hour
    # Plus CZ timezone offset guess — UTC+1/+2 depending on DST
    hour_cz = (hour + 2) % 24  # approx; safe enough for UI hint

    # Activity signal
    _, min_ago = _last_interaction(senior_id)
    active_now = (min_ago is not None and min_ago < 10)

    # Mood signal
    c_avg, c_samples = _recent_c_avg(senior_id, hours=2)
    distressed = (c_avg is not None and c_samples >= 3 and c_avg < 0.32)
    calm = (c_avg is not None and c_samples >= 3 and c_avg >= 0.55)

    # Decide
    if distressed:
        status = 'red'
        title = 'Možná nevolejte teď'
        detail = 'Váš blízký se teď necítí dobře. Zkuste později.'
    elif hour_cz >= 22 or hour_cz < 6:
        status = 'yellow'
        title = 'Odpočívá'
        detail = f'Je večer/noc ({hour_cz}:00). Raději počkejte do rána.'
    elif active_now:
        status = 'yellow'
        title = 'Právě mluví s Radimem'
        detail = f'Senior komunikoval před {min_ago} minutami. Zavolejte za chvíli.'
    elif calm:
        status = 'green'
        title = 'Dobrý čas zavolat'
        detail = 'Senior je v klidu. Hezký den na hovor.'
    else:
        status = 'yellow'
        title = 'Spíš v pořádku'
        detail = 'Nemám jasný signál. Zkuste zavolat.'

    return jsonify({
        'success': True,
        'status': status,
        'title': title,
        'detail': detail,
        'signals': {
            'hourCz': hour_cz,
            'minutesSinceLastActivity': min_ago,
            'recentCAvg': round(c_avg, 3) if c_avg is not None else None,
            'samples': c_samples,
        },
    })


# ─────────────────────────────────────────────────────────────────────────────
# LIVE ACTIVITY — last 5 minutes signals
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/live-activity', methods=['GET'])
@require_auth
def live_activity(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    since = datetime.utcnow() - timedelta(minutes=30)
    msgs = 0
    photos = 0
    notes = 0
    last_action = None
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) FROM memory_history "
                "WHERE user_id = ? AND created_at >= ?",
                (senior_id, since)
            ).fetchone()
            if r:
                msgs = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
            try:
                r = db.execute(
                    "SELECT COUNT(*) FROM gallery_photos "
                    "WHERE user_id = ? AND created_at >= ?",
                    (senior_id, since)
                ).fetchone()
                if r:
                    photos = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
            except Exception:
                pass
            try:
                r = db.execute(
                    "SELECT COUNT(*) FROM user_notes "
                    "WHERE user_id = ? AND created_at >= ?",
                    (senior_id, since)
                ).fetchone()
                if r:
                    notes = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
            except Exception:
                pass
    except Exception:
        pass

    last_ts, min_ago = _last_interaction(senior_id)

    return jsonify({
        'success': True,
        'msgsLast30Min': msgs,
        'photosLast30Min': photos,
        'notesLast30Min': notes,
        'lastInteractionAt': last_ts,
        'minutesSinceLastInteraction': min_ago,
    })


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY PREVIEW — what family will inherit
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/legacy-preview', methods=['GET'])
@require_auth
def legacy_preview(senior_id):
    """Counts only — no content until senior passes + heir unlock."""
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    family_contribs = 0
    public_contribs = 0
    scheduled_waiting = 0
    scheduled_for_me = 0
    heir_name = None
    royalty_years = None

    try:
        with db_context() as db:
            try:
                r = db.execute(
                    "SELECT COUNT(*) FROM experience_contributions "
                    "WHERE user_id = ? AND privacy = ?",
                    (senior_id, 'family')
                ).fetchone()
                if r:
                    family_contribs = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
                r = db.execute(
                    "SELECT COUNT(*) FROM experience_contributions "
                    "WHERE user_id = ? AND privacy = ?",
                    (senior_id, 'public')
                ).fetchone()
                if r:
                    public_contribs = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
            except Exception:
                pass
            try:
                r = db.execute(
                    "SELECT COUNT(*) FROM experience_scheduled_messages "
                    "WHERE user_id = ? AND status = ?",
                    (senior_id, 'scheduled')
                ).fetchone()
                if r:
                    scheduled_waiting = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0)
                # Try to count messages specifically for this caregiver
                r = db.execute(
                    "SELECT COUNT(*) FROM experience_scheduled_messages "
                    "WHERE user_id = ? AND status = ? "
                    "AND recipient_contact LIKE ?",
                    (senior_id, 'scheduled', '%')  # can't perfectly match without email/profile join
                ).fetchone()
                # keep scheduled_for_me placeholder at 0 — proper matching via heir record below
            except Exception:
                pass
            try:
                r = db.execute(
                    "SELECT heir_name, heir_relation, royalty_years_after_death "
                    "FROM experience_inheritance WHERE user_id = ?",
                    (senior_id,)
                ).fetchone()
                if r:
                    def v(i, k):
                        return r[i] if isinstance(r, (list, tuple)) else r.get(k)
                    heir_name = v(0, 'heir_name')
                    royalty_years = v(2, 'royalty_years_after_death')
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({
        'success': True,
        'familyContributions': family_contribs,
        'publicContributions': public_contribs,
        'scheduledMessagesWaiting': scheduled_waiting,
        'heirName': heir_name,
        'royaltyYearsAfterDeath': royalty_years,
        'message': ('Toto uvidíte až ve chvíli, kdy váš blízký bude chtít předat. '
                    'Zatím vidíte jen počty.'),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SHARED GALLERY — photos family is allowed to see
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/shared-gallery', methods=['GET'])
@require_auth
def shared_gallery(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    limit = max(1, min(50, int(request.args.get('limit', 20))))
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, caption, album, created_at "
                "FROM gallery_photos "
                "WHERE user_id = ? AND shared_with_family = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (senior_id, True if is_postgres() else 1, limit)
            ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        items.append({
            'id': v(0, 'id'),
            'caption': v(1, 'caption') or '',
            'album': v(2, 'album'),
            'createdAt': str(v(3, 'created_at') or ''),
        })
    return jsonify({'success': True, 'photos': items, 'count': len(items)})


# ─────────────────────────────────────────────────────────────────────────────
# WISDOM CLOUD — aggregated themes + names + places
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/wisdom-cloud', methods=['GET'])
@require_auth
def wisdom_cloud(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    theme_counts = defaultdict(int)
    word_counts = defaultdict(int)
    total = 0
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT theme, title, transcript FROM experience_contributions "
                "WHERE user_id = ? AND privacy IN (?, ?, ?) "
                "ORDER BY created_at DESC LIMIT 50",
                (senior_id, 'family', 'public', 'research')
            ).fetchall()
    except Exception:
        rows = []

    # Simple tokenizer — Czech names typically capitalized
    import re
    stopwords = {
        'a', 'i', 'o', 'u', 'v', 'na', 'do', 'se', 'že', 'je', 'to',
        'ale', 'jen', 'už', 'by', 'být', 'byl', 'byla', 'když', 'co',
        'jak', 'kde', 'my', 'vy', 'oni', 'on', 'ona', 'si', 'po', 'za',
        'pro', 'ten', 'ta', 'to', 'jsem', 'jsi', 'jsme', 'jste', 'jsou',
        'jsme', 'nás', 'vás', 'jich',
    }
    for r in rows or []:
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        theme_counts[v(0, 'theme')] += 1
        total += 1
        text = (v(2, 'transcript') or '')[:5000]
        # Extract capitalized tokens that look like names (Anička, Karel, Praha)
        for tok in re.findall(r'\b[A-ZĚŠČŘŽÝÁÍÉÚŮŇŤĎÓ][a-záčďéěíňóřšťúůýž]{2,}\b', text):
            if tok.lower() in stopwords:
                continue
            word_counts[tok] += 1

    # Top 10 themes, top 12 words
    themes_sorted = sorted(theme_counts.items(), key=lambda x: -x[1])
    words_sorted = sorted(word_counts.items(), key=lambda x: -x[1])[:12]

    return jsonify({
        'success': True,
        'totalContributions': total,
        'themes': [{'theme': t, 'count': c} for t, c in themes_sorted],
        'people': [{'word': w, 'count': c} for w, c in words_sorted if c >= 2],
    })


# ─────────────────────────────────────────────────────────────────────────────
# DAILY NARRATIVE — Gemini-generated summary for family
# ─────────────────────────────────────────────────────────────────────────────

def _build_narrative_context(senior_id):
    """Compact context string for Gemini."""
    parts = []
    name = _addressee_name(senior_id) or 'senior'
    parts.append(f"Jméno: {name}")

    # Today's activity counts
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) FROM memory_history "
                "WHERE user_id = ? AND created_at >= ? AND role = ?",
                (senior_id, today_start, 'user')
            ).fetchone()
            msgs_today = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0) if r else 0
            parts.append(f"Zpráv dnes: {msgs_today}")

            # Today C average
            r = db.execute(
                "SELECT AVG(C) FROM brain_states "
                "WHERE user_id = ? AND created_at >= ?",
                (senior_id, today_start)
            ).fetchone()
            try:
                c = float((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0.5) if r else 0.5
            except Exception:
                c = 0.5
            parts.append(f"Průměrný C dnes: {round(c, 2)}")

            # Last photo + caption
            try:
                r = db.execute(
                    "SELECT caption, created_at FROM gallery_photos "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (senior_id,)
                ).fetchone()
                if r:
                    def v(i, k):
                        return r[i] if isinstance(r, (list, tuple)) else r.get(k)
                    cap = (v(0, 'caption') or '')
                    if cap:
                        parts.append(f"Poslední fotka s popiskem: „{cap[:80]}\"")
            except Exception:
                pass
            # Last note
            try:
                r = db.execute(
                    "SELECT text FROM user_notes "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (senior_id,)
                ).fetchone()
                if r:
                    t = (r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or ''
                    if t:
                        parts.append(f"Poslední poznámka: „{t[:80]}\"")
            except Exception:
                pass
            # Latest observation
            try:
                r = db.execute(
                    "SELECT severity, message FROM agent_observations "
                    "WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                    (senior_id,)
                ).fetchone()
                if r:
                    def v(i, k):
                        return r[i] if isinstance(r, (list, tuple)) else r.get(k)
                    parts.append(f"Poslední pozorování Radima: {v(0, 'severity')} — {v(1, 'message')[:100]}")
            except Exception:
                pass
    except Exception:
        pass
    return '\n'.join(parts)


def _call_gemini_narrative(ctx, name):
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = (
            "Jsi Radim — AI společník pro seniory. "
            "Piš rodině jeden krátký vřelý odstavec (4–6 vět, česky) o tom, "
            "jak dnes senior prožil den. Piš v minulém čase, jako o někom "
            "blízkém. Zmiňuj konkrétní detaily z dat. Nepřidávej klinické "
            "hodnocení. Nevymýšlej si fakta. Pokud je dat málo, napiš to otevřeně.\n\n"
            f"Jméno seniora: {name}\n\n"
            f"Dnešní data:\n{ctx}\n\n"
            "Odstavec (bez úvodu, bez 'Vážená rodino', rovnou do věci):"
        )
        resp = model.generate_content(prompt, generation_config={
            'temperature': 0.6, 'max_output_tokens': 400,
        })
        if resp and getattr(resp, 'text', None):
            return resp.text.strip()[:1000]
    except Exception as e:
        logger.debug(f"narrative Gemini: {e}")
    return None


@caregiver_bp.route('/api/caregiver/senior/<senior_id>/narrative', methods=['GET', 'OPTIONS'])
@require_auth
def narrative(senior_id):
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    # Cache by senior+date (one per day per senior)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    cache_key = f"{senior_id}:{today}"
    with _narrative_lock:
        cached = _narrative_cache.get(cache_key)
    if cached and (time.time() - cached['ts']) < NARRATIVE_CACHE_HOURS * 3600:
        return jsonify({
            'success': True,
            'narrative': cached['text'],
            'cached': True,
            'generatedAt': cached['iso'],
        })

    # Rate limit per caregiver
    if not _rate_ok(uid, 'narrative', 20):
        return jsonify({'success': False, 'code': 'rate_limit',
                        'error': 'Radim píše shrnutí max 20× za hodinu.'}), 429

    name = _addressee_name(senior_id) or 'váš blízký'
    ctx = _build_narrative_context(senior_id)
    text = _call_gemini_narrative(ctx, name)
    if not text:
        # Honest fallback
        text = (
            f'Dnes o {name} nemám dost signálů, abych napsal pečlivé shrnutí. '
            f'Zkuste to později — nebo zavolejte a zeptejte se přímo. '
            f'To je vždy nejlepší.'
        )
        ai_generated = False
    else:
        ai_generated = True

    with _narrative_lock:
        _narrative_cache[cache_key] = {
            'text': text,
            'ts': time.time(),
            'iso': datetime.utcnow().isoformat() + 'Z',
        }

    return jsonify({
        'success': True,
        'narrative': text,
        'cached': False,
        'aiGenerated': ai_generated,
        'generatedAt': datetime.utcnow().isoformat() + 'Z',
    })


# ─────────────────────────────────────────────────────────────────────────────
# SENIOR OVERVIEW — enriched card data for family
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/overview', methods=['GET'])
@require_auth
def senior_overview(senior_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid):
        return jsonify({'success': False, 'error': 'not linked'}), 403

    name = _addressee_name(senior_id) or 'Senior'
    last_ts, min_ago = _last_interaction(senior_id)

    # 7-day mood trend (simplified — daily averages)
    trend = []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT CAST(created_at AS TEXT) AS d, C "
                "FROM brain_states WHERE user_id = ? "
                "AND C IS NOT NULL "
                "AND created_at >= ?",
                (senior_id, datetime.utcnow() - timedelta(days=7))
            ).fetchall()
        buckets = defaultdict(list)
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            date_s = str(v(0, 'd'))[:10]
            try:
                buckets[date_s].append(float(v(1, 'C')))
            except Exception:
                pass
        for date_s in sorted(buckets.keys()):
            avg = sum(buckets[date_s]) / len(buckets[date_s])
            if avg >= 0.55:
                mood = 'good'
            elif avg >= 0.38:
                mood = 'soso'
            else:
                mood = 'heavy'
            trend.append({'date': date_s, 'c': round(avg, 3), 'mood': mood})
    except Exception:
        pass

    # Latest observation
    obs = []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT severity, message, created_at "
                "FROM agent_observations WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT 5",
                (senior_id,)
            ).fetchall()
        for r in rows or []:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            obs.append({
                'severity': v(0, 'severity'),
                'message': v(1, 'message'),
                'createdAt': str(v(2, 'created_at') or ''),
            })
    except Exception:
        pass

    # Link relation
    relation = None
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT relation, family_name FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id = ? "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id, uid)
            ).fetchone()
        if r:
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            relation = v(0, 'relation')
    except Exception:
        pass

    return jsonify({
        'success': True,
        'seniorId': senior_id,
        'name': name,
        'relation': relation,
        'lastInteractionAt': last_ts,
        'minutesSinceLastInteraction': min_ago,
        'moodTrend7d': trend,
        'recentObservations': obs,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SENIORS LIST (professional or family_multi)
# ─────────────────────────────────────────────────────────────────────────────

def _is_real_senior(user_id):
    """Heuristic: a 'real senior' has EITHER
       - role='senior' in users table, OR
       - an addressee name in their profile (preferred_name), OR
       - at least 3 real interactions in memory_history
       This filters test users, admin accounts, and empty placeholder rows.
    """
    if not user_id:
        return False
    # Role check
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT role FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
        if r:
            role = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
            if role == 'senior':
                return True
    except Exception:
        pass
    # Name in profile
    if _addressee_name(user_id):
        return True
    # Real interaction count
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) FROM memory_history "
                "WHERE user_id = ? AND role = ?",
                (user_id, 'user')
            ).fetchone()
        cnt = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0) if r else 0
        return cnt >= 3
    except Exception:
        return False


@caregiver_bp.route('/api/caregiver/seniors', methods=['GET'])
@require_auth
def caregiver_seniors():
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    role = _role()

    # Collect senior IDs
    senior_ids = []
    if role in ('caregiver', 'teacher', 'administrator', 'admin'):
        try:
            with db_context() as db:
                # Preferred: users with role='senior'
                rows = db.execute(
                    "SELECT id FROM users WHERE role = ? LIMIT 200",
                    ('senior',)
                ).fetchall()
                for r in rows or []:
                    sid = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
                    if sid:
                        senior_ids.append(sid)

                # Fallback: from memory_profiles, filtered
                if not senior_ids:
                    rows = db.execute(
                        "SELECT DISTINCT user_id FROM memory_profiles LIMIT 200"
                    ).fetchall()
                    for r in rows or []:
                        sid = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
                        if sid and _is_real_senior(sid):
                            senior_ids.append(sid)
        except Exception:
            pass
    else:
        linked = _list_linked_seniors(uid)
        senior_ids = [l['seniorId'] for l in linked]

    out = []
    for sid in senior_ids[:50]:
        name = _addressee_name(sid)
        if not name:
            # Skip seniors without even a name — clearly placeholder/test rows
            # (except explicit linked family — show them anyway for family view)
            if role in ('caregiver', 'teacher', 'administrator', 'admin'):
                continue
            name = 'Senior'

        last_ts, min_ago = _last_interaction(sid)
        c_avg, samples = _recent_c_avg(sid, hours=24)

        # Require some signal: either a name OR recent activity OR samples
        if not _addressee_name(sid) and min_ago is None and samples == 0:
            if role in ('caregiver', 'teacher', 'administrator', 'admin'):
                continue  # professional view hides ghost rows

        if c_avg is None:
            mood = 'unknown'
        elif c_avg >= 0.55:
            mood = 'good'
        elif c_avg >= 0.38:
            mood = 'soso'
        else:
            mood = 'heavy'

        # Sprint AG.3: brain_mode now (last 30 min) + unacknowledged
        # CRISIS/ALERT count — drives status dot + red badge on grid card
        # so caregiver sees who needs attention before opening detail.
        brain_mode_now = None
        unack_crisis = 0
        try:
            with db_context() as db:
                if is_postgres():
                    brow = db.execute(
                        "SELECT mode FROM brain_states WHERE user_id = ? "
                        "AND created_at > NOW() - INTERVAL '30 minutes' "
                        "ORDER BY created_at DESC LIMIT 1",
                        (sid,)
                    ).fetchone()
                else:
                    brow = db.execute(
                        "SELECT mode FROM brain_states WHERE user_id = ? "
                        "AND created_at > datetime('now', '-30 minutes') "
                        "ORDER BY created_at DESC LIMIT 1",
                        (sid,)
                    ).fetchone()
                if brow:
                    brain_mode_now = (brow.get('mode') if hasattr(brow, 'get') else brow[0]) or None

                # Count unacknowledged ALERT+CRISIS observations in last 24h
                if is_postgres():
                    crow = db.execute(
                        "SELECT COUNT(*) FROM agent_observations WHERE user_id = ? "
                        "AND severity IN ('CRISIS','ALERT') "
                        "AND acknowledged_at IS NULL "
                        "AND created_at > NOW() - INTERVAL '24 hours'",
                        (sid,)
                    ).fetchone()
                else:
                    crow = db.execute(
                        "SELECT COUNT(*) FROM agent_observations WHERE user_id = ? "
                        "AND severity IN ('CRISIS','ALERT') "
                        "AND acknowledged_at IS NULL "
                        "AND created_at > datetime('now', '-24 hours')",
                        (sid,)
                    ).fetchone()
                if crow:
                    val = crow.get(0) if hasattr(crow, 'get') else crow[0]
                    unack_crisis = int(val or 0)
        except Exception as e:
            logger.debug(f"caregiver_seniors brain enrichment {sid}: {e}")

        out.append({
            'seniorId': sid,
            'name': name,
            'minutesSinceLastInteraction': min_ago,
            'mood': mood,
            'cAvg24h': round(c_avg, 3) if c_avg is not None else None,
            'hasRealData': bool(_addressee_name(sid)) or samples > 0,
            'brainMode': brain_mode_now,
            'unacknowledgedCrisis': unack_crisis,
        })

    # Sort: brain CRISIS/ALERT first → unack count → heavy mood → recency
    # Sprint AG.3: brain_mode trumps mood for ordering, so a senior whose
    # chat literally just said "spadl jsem" rises above someone with
    # generic "heavy" 24h average — even if both look concerning, the
    # acute case must surface first.
    mood_rank = {'heavy': 0, 'soso': 1, 'unknown': 3, 'good': 2}
    brain_rank = {'CRISIS': 0, 'ALERT': 1, 'HARMONY': 3}
    out.sort(key=lambda s: (
        brain_rank.get(s.get('brainMode'), 4),
        -int(s.get('unacknowledgedCrisis') or 0),
        mood_rank.get(s['mood'], 5),
        s['minutesSinceLastInteraction'] or 99999,
    ))

    return jsonify({'success': True, 'seniors': out, 'count': len(out)})


# ─────────────────────────────────────────────────────────────────────────────
# COSIGN QUEUE + UI ACTION (proxy to experience_routes for display coherence)
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/cosign-queue', methods=['GET'])
@require_auth
def caregiver_cosign_queue(senior_id):
    """List contracts awaiting family cosign for this senior."""
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT c.id, c.price_kc, c.signed_at, c.cooling_off_until, "
                "c.cosigned_at, o.title, b.name "
                "FROM experience_contracts c "
                "LEFT JOIN experience_offers o ON o.id = c.offer_id "
                "LEFT JOIN experience_buyers b ON b.id = c.buyer_id "
                "WHERE c.user_id = ? AND c.requires_family_cosign = ? "
                "AND c.revoked_at IS NULL ORDER BY c.signed_at DESC LIMIT 50",
                (senior_id, True if is_postgres() else 1)
            ).fetchall()
    except Exception:
        rows = []
    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        items.append({
            'id': v(0),
            'priceKc': v(1),
            'signedAt': str(v(2) or ''),
            'coolingOffUntil': str(v(3) or ''),
            'cosignedAt': str(v(4) or ''),
            'offerTitle': v(5),
            'buyerName': v(6),
            'pending': not v(4),
        })
    return jsonify({
        'success': True,
        'contracts': items,
        'pendingCount': sum(1 for x in items if x['pending']),
    })



# ─────────────────────────────────────────────────────────────────────────────
# SPRINT C — NOTIFICATIONS + DECLINE + SCHEDULED VIEW + AUDIT + SCHEDULER
# ─────────────────────────────────────────────────────────────────────────────

def _audit_caregiver_access(senior_id, caregiver_id, action, target_type=None, target_id=None, detail=None):
    """Log caregiver access into experience_audit_log so senior can see it.
    Best-effort — never raises."""
    if not senior_id or not caregiver_id or senior_id == caregiver_id:
        return
    try:
        from experience_routes import _audit as exp_audit
        exp_audit(
            user_id=senior_id,          # who the data belongs to
            action='caregiver_' + action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            actor_id=caregiver_id,       # who did it
        )
    except Exception as e:
        logger.debug(f"caregiver audit: {e}")


def create_caregiver_notification(recipient_id, senior_id, ntype, title,
                                  body=None, severity='info',
                                  ref_type=None, ref_id=None, data=None):
    """Public helper — used by experience_routes to queue cosign notifications.
    Safe to call from anywhere. Returns notification id or None."""
    _init_schema()
    if not recipient_id or not title:
        return None
    try:
        with db_context(commit=True) as db:
            data_json = json.dumps(data) if data else None
            if is_postgres():
                r = db.execute(
                    "INSERT INTO caregiver_notifications "
                    "(recipient_id, senior_id, type, title, body, severity, "
                    "ref_type, ref_id, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (recipient_id, senior_id, ntype, title[:200], (body or '')[:1000],
                     severity, ref_type, ref_id, data_json)
                ).fetchone()
                return r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO caregiver_notifications "
                    "(recipient_id, senior_id, type, title, body, severity, "
                    "ref_type, ref_id, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (recipient_id, senior_id, ntype, title[:200], (body or '')[:1000],
                     severity, ref_type, ref_id, data_json)
                )
                return cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.warning(f"create caregiver notification: {e}")
        return None


def notify_family_of_cosign(senior_id, contract_id, offer_title, price_kc):
    """Called from experience_routes.accept_offer when cosign is required.
    Queues a notification to every confirmed family member."""
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT family_user_id FROM senior_family_links "
                "WHERE senior_id = ? AND family_user_id IS NOT NULL "
                "AND confirmed_at IS NOT NULL AND revoked_at IS NULL",
                (senior_id,)
            ).fetchall()
    except Exception:
        rows = []
    sent = 0
    for r in rows or []:
        fid = r[0] if isinstance(r, (list, tuple)) else r.get('family_user_id')
        if not fid:
            continue
        create_caregiver_notification(
            recipient_id=fid,
            senior_id=senior_id,
            ntype='cosign_required',
            title='⚠️ Čeká na vaše schválení',
            body=f'Váš blízký podepsal smlouvu „{offer_title}" za {price_kc} Kč. Bez vašeho spolupodpisu se výplata neuvolní.',
            severity='warning',
            ref_type='contract',
            ref_id=contract_id,
        )
        sent += 1
    return sent


@caregiver_bp.route('/api/caregiver/notifications', methods=['GET', 'OPTIONS'])
@require_auth
def list_notifications():
    """List caregiver's notifications (unread first, last 50)."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    only_unread = request.args.get('unread', '').lower() in ('1', 'true', 'yes')

    try:
        with db_context() as db:
            if only_unread:
                rows = db.execute(
                    "SELECT id, senior_id, type, title, body, severity, "
                    "ref_type, ref_id, read_at, acted_at, created_at "
                    "FROM caregiver_notifications "
                    "WHERE recipient_id = ? AND read_at IS NULL "
                    "ORDER BY created_at DESC LIMIT 50",
                    (uid,)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, senior_id, type, title, body, severity, "
                    "ref_type, ref_id, read_at, acted_at, created_at "
                    "FROM caregiver_notifications "
                    "WHERE recipient_id = ? "
                    "ORDER BY read_at NULLS FIRST, created_at DESC LIMIT 50",
                    (uid,)
                ).fetchall() if is_postgres() else db.execute(
                    "SELECT id, senior_id, type, title, body, severity, "
                    "ref_type, ref_id, read_at, acted_at, created_at "
                    "FROM caregiver_notifications "
                    "WHERE recipient_id = ? "
                    "ORDER BY (read_at IS NOT NULL), created_at DESC LIMIT 50",
                    (uid,)
                ).fetchall()
    except Exception as e:
        logger.error(f"list notifications: {e}")
        rows = []

    items = []
    unread_count = 0
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        read_at = str(v(8) or '')
        if not read_at:
            unread_count += 1
        items.append({
            'id': v(0),
            'seniorId': v(1),
            'type': v(2),
            'title': v(3),
            'body': v(4),
            'severity': v(5),
            'refType': v(6),
            'refId': v(7),
            'readAt': read_at,
            'actedAt': str(v(9) or ''),
            'createdAt': str(v(10) or ''),
        })
    return jsonify({
        'success': True,
        'notifications': items,
        'count': len(items),
        'unreadCount': unread_count,
    })


@caregiver_bp.route('/api/caregiver/notifications/count', methods=['GET'])
@require_auth
def notifications_count():
    """Lightweight unread count — used for badge."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT COUNT(*) FROM caregiver_notifications "
                "WHERE recipient_id = ? AND read_at IS NULL",
                (uid,)
            ).fetchone()
        cnt = int((r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]) or 0) if r else 0
    except Exception:
        cnt = 0
    return jsonify({'success': True, 'unreadCount': cnt})


@caregiver_bp.route('/api/caregiver/notification/<int:notif_id>/ack', methods=['POST'])
@require_auth
def ack_notification(notif_id):
    """Mark notification as read."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE caregiver_notifications "
                "SET read_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND recipient_id = ? AND read_at IS NULL",
                (notif_id, uid)
            )
    except Exception as e:
        logger.error(f"ack notification: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500
    return jsonify({'success': True, 'id': notif_id})


@caregiver_bp.route('/api/caregiver/notifications/ack-all', methods=['POST'])
@require_auth
def ack_all_notifications():
    """Mark all my notifications as read."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE caregiver_notifications "
                "SET read_at = CURRENT_TIMESTAMP "
                "WHERE recipient_id = ? AND read_at IS NULL",
                (uid,)
            )
    except Exception as e:
        logger.error(f"ack all: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────────────────────────
# COSIGN DECLINE — family rejects with reason (transparency)
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/contract/<int:contract_id>/decline-cosign', methods=['POST'])
@require_auth
def decline_cosign(contract_id):
    """Family rejects cosign — records reason, revokes the contract, notifies senior."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()[:500]

    # Verify contract exists + caregiver is family of the senior
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT user_id, cosigned_at, revoked_at "
                "FROM experience_contracts WHERE id = ?",
                (contract_id,)
            ).fetchone()
        if not r:
            return jsonify({'success': False, 'error': 'not found'}), 404
        def v(i, k):
            return r[i] if isinstance(r, (list, tuple)) else r.get(k)
        senior_id = v(0, 'user_id')
        if v(1, 'cosigned_at'):
            return jsonify({'success': False, 'error': 'Již spolupodepsáno.'}), 409
        if v(2, 'revoked_at'):
            return jsonify({'success': False, 'error': 'Smlouva byla zrušena.'}), 409
    except Exception as e:
        logger.error(f"decline read: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked family'}), 403

    # Record decline + revoke contract
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO caregiver_cosign_declines "
                "(contract_id, senior_id, caregiver_id, reason) "
                "VALUES (?, ?, ?, ?)",
                (contract_id, senior_id, uid, reason)
            )
            db.execute(
                "UPDATE experience_contracts SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (contract_id,)
            )
    except Exception as e:
        logger.error(f"decline write: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    # Audit in senior's Odkaz audit log
    _audit_caregiver_access(
        senior_id, uid,
        action='cosign_declined',
        target_type='contract',
        target_id=contract_id,
        detail=f'reason={reason[:100]}' if reason else 'no reason given',
    )

    # Notify senior via push + queue caregiver-notification so other family knows
    try:
        from notification_helpers import notify_user
        notify_user(
            user_id=senior_id,
            type='cosign_declined',
            title='ℹ️ Rodina nespolupodepsala smlouvu',
            body=(reason or 'Rodina nemohla smlouvu teď podpořit.')[:200],
            severity='info',
            data={'contract_id': contract_id},
        )
    except Exception:
        pass

    return jsonify({
        'success': True,
        'contractId': contract_id,
        'message': 'Smlouva zrušena. Váš blízký bude informován.',
    })


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULED MESSAGES FAMILY TRACKER
# ─────────────────────────────────────────────────────────────────────────────

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/scheduled-messages', methods=['GET'])
@require_auth
def caregiver_scheduled_messages(senior_id):
    """Family sees counts + recipient names of senior's scheduled messages.
    Content is locked — family sees only: 'A message for Anička on 2026-05-18'."""
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, recipient_name, recipient_relation, release_event, "
                "release_date, status "
                "FROM experience_scheduled_messages "
                "WHERE user_id = ? AND status IN (?, ?) "
                "ORDER BY release_date ASC LIMIT 30",
                (senior_id, 'scheduled', 'delivered')
            ).fetchall()
    except Exception:
        rows = []

    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        items.append({
            'id': v(0),
            'recipientName': v(1),
            'recipientRelation': v(2),
            'releaseEvent': v(3),
            'releaseDate': str(v(4) or ''),
            'status': v(5),
        })

    # Audit — family viewed senior's scheduled messages list
    _audit_caregiver_access(
        senior_id, uid,
        action='viewed_scheduled_messages',
        target_type='overview',
    )

    return jsonify({
        'success': True,
        'messages': items,
        'count': len(items),
        'message': 'Obsah zpráv zůstává soukromý. Uvidíte je, až přijde jejich čas.',
    })


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT WIRING — senior sees who from family accessed what
# Patch existing endpoints to log access.
# ─────────────────────────────────────────────────────────────────────────────

# We monkey-patch by adding audit calls to existing endpoint internals.
# Already called via _audit_caregiver_access in decline_cosign + scheduled_messages.
# For overview / narrative, we log selectively (not every read — too noisy).

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/audit-ping', methods=['POST', 'OPTIONS'])
@require_auth
def audit_ping(senior_id):
    """Frontend pings this once per opened detail view to log caregiver access.
    Keeps main GET endpoints cheap + side-effect-free while still recording
    significant accesses to senior's audit log."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    if not _is_family_of(senior_id, uid) or senior_id == uid:
        return jsonify({'success': False, 'error': 'not linked'}), 403

    data = request.get_json(silent=True) or {}
    section = (data.get('section') or 'detail')[:32]
    _audit_caregiver_access(
        senior_id, uid,
        action='viewed_' + section,
        target_type='detail',
    )
    return jsonify({'success': True})


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULER — daily narrative for all active family pairs at 22:00
# ─────────────────────────────────────────────────────────────────────────────

def run_daily_narratives():
    """Precompute daily narratives for every senior with at least one confirmed
    family link, so when family opens the module next morning it's instant."""
    _init_schema()
    # Collect all (senior_id) with active links
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT DISTINCT senior_id FROM senior_family_links "
                "WHERE confirmed_at IS NOT NULL AND revoked_at IS NULL LIMIT 500"
            ).fetchall()
    except Exception as e:
        logger.debug(f"daily narratives scan: {e}")
        return 0

    generated = 0
    today = datetime.utcnow().strftime('%Y-%m-%d')
    for r in rows or []:
        senior_id = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
        if not senior_id:
            continue
        cache_key = f"{senior_id}:{today}"
        with _narrative_lock:
            if cache_key in _narrative_cache:
                continue  # already cached for today
        try:
            name = _addressee_name(senior_id) or 'váš blízký'
            ctx = _build_narrative_context(senior_id)
            text = _call_gemini_narrative(ctx, name)
            if not text:
                text = (f'Dnes o {name} nemám dost signálů. Zkuste zavolat — '
                        f'to je vždy nejlepší.')
            with _narrative_lock:
                _narrative_cache[cache_key] = {
                    'text': text,
                    'ts': time.time(),
                    'iso': datetime.utcnow().isoformat() + 'Z',
                }
            generated += 1
        except Exception as e:
            logger.debug(f"daily narrative {senior_id}: {e}")
    logger.info(f"Daily narratives generated: {generated}")
    return generated


# ═════════════════════════════════════════════════════════════════════
# Sprint AG.1: CAREGIVER INBOX — agent_observations surfaced to family
# ═════════════════════════════════════════════════════════════════════
# Until now, agent_loop wrote observations to DB but the family / caregivers
# had no way to see them. This endpoint exposes the senior's recent
# observations + brain mode + last interaction so a caregiver dashboard
# can render "what's happening with my parent right now".

@caregiver_bp.route('/api/caregiver/inbox/<senior_id>', methods=['GET', 'OPTIONS'])
def caregiver_inbox(senior_id):
    """List recent agent observations + brain status for a senior.

    Auth: caller must be linked to senior_id via senior_family_links
    (confirmed, not revoked) OR be the senior themselves.

    Query params:
      since: optional ISO timestamp — only observations newer than this
      limit: max observations (default 50, max 200)
      severity_min: INFO|WARNING|ALERT|CRISIS (default INFO)

    Response:
    {
      "senior": {"id", "name"},
      "now": {
        "brain_mode": "HARMONY|ALERT|CRISIS",
        "coherence": 0.68,
        "last_interaction_minutes_ago": 12
      },
      "observations": [
        {"id", "type", "severity", "message", "created_at",
         "acknowledged_at", "details": {...}}
      ],
      "summary": {"crisis": 0, "alert": 1, "warning": 2, "info": 5}
    }
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    from auth_middleware import require_auth as _ra
    # Inline auth: keep route handler readable, allow caller-not-linked → 403
    @_ra
    def _inner(_senior_id):
        caller = getattr(g, 'auth_user', None) or {}
        caller_id = str(caller.get('user_id') or caller.get('id') or '')
        if not caller_id:
            return jsonify({'success': False, 'error': 'Auth required'}), 401

        if not _is_family_of(_senior_id, caller_id):
            return jsonify({'success': False, 'error': 'Not linked to this senior'}), 403

        try:
            limit = max(1, min(200, int(request.args.get('limit', 50))))
        except ValueError:
            limit = 50
        sev_min = (request.args.get('severity_min') or 'INFO').upper()
        sev_order = ['INFO', 'WARNING', 'ALERT', 'CRISIS']
        if sev_min not in sev_order:
            sev_min = 'INFO'
        sev_filter = sev_order[sev_order.index(sev_min):]
        since_iso = request.args.get('since')

        observations = []
        summary = {'crisis': 0, 'alert': 0, 'warning': 0, 'info': 0}
        try:
            with db_context() as db:
                # Build placeholders for severity IN (?, ?, ?)
                placeholders = ','.join(['?'] * len(sev_filter))
                params = [_senior_id] + sev_filter
                where_extra = ''
                if since_iso:
                    where_extra = ' AND created_at > ?'
                    params.append(since_iso)
                params.append(limit)
                rows = db.execute(
                    f"SELECT id, observation_type, severity, message, "
                    f"       details, action_taken, acknowledged_at, created_at "
                    f"FROM agent_observations "
                    f"WHERE user_id = ? AND severity IN ({placeholders})"
                    f"{where_extra} "
                    f"ORDER BY created_at DESC LIMIT ?",
                    tuple(params)
                ).fetchall()
                for r in rows:
                    try:
                        details = r.get('details') if hasattr(r, 'get') else r[4]
                    except Exception:
                        details = None
                    if isinstance(details, str):
                        try:
                            details = json.loads(details)
                        except Exception:
                            details = {'raw': details[:200]}
                    obs_id = r.get('id') if hasattr(r, 'get') else r[0]
                    obs_type = r.get('observation_type') if hasattr(r, 'get') else r[1]
                    sev = (r.get('severity') if hasattr(r, 'get') else r[2]) or 'INFO'
                    msg = r.get('message') if hasattr(r, 'get') else r[3]
                    action = r.get('action_taken') if hasattr(r, 'get') else r[5]
                    ack = r.get('acknowledged_at') if hasattr(r, 'get') else r[6]
                    created = r.get('created_at') if hasattr(r, 'get') else r[7]

                    observations.append({
                        'id': int(obs_id) if obs_id is not None else None,
                        'type': obs_type,
                        'severity': sev.upper(),
                        'message': msg,
                        'action_taken': action,
                        'acknowledged_at': created.isoformat() if hasattr(created, 'isoformat') and ack else (str(ack) if ack else None),
                        'created_at': created.isoformat() if hasattr(created, 'isoformat') else str(created),
                        'details': details or {},
                    })
                    sev_key = sev.lower()
                    if sev_key in summary:
                        summary[sev_key] += 1
        except Exception as e:
            logger.warning(f"caregiver_inbox observations error: {e}")

        # Brain status NOW
        brain_now = {'brain_mode': None, 'coherence': None}
        try:
            with db_context() as db:
                if is_postgres():
                    brow = db.execute(
                        "SELECT mode, coherence FROM brain_states "
                        "WHERE user_id = ? AND created_at > NOW() - INTERVAL '30 minutes' "
                        "ORDER BY created_at DESC LIMIT 1",
                        (_senior_id,)
                    ).fetchone()
                else:
                    brow = db.execute(
                        "SELECT mode, coherence FROM brain_states "
                        "WHERE user_id = ? AND created_at > datetime('now', '-30 minutes') "
                        "ORDER BY created_at DESC LIMIT 1",
                        (_senior_id,)
                    ).fetchone()
            if brow:
                brain_now['brain_mode'] = (brow.get('mode') if hasattr(brow, 'get') else brow[0]) or 'HARMONY'
                co = brow.get('coherence') if hasattr(brow, 'get') else brow[1]
                brain_now['coherence'] = round(float(co), 3) if co is not None else None
        except Exception as e:
            logger.debug(f"brain_now lookup: {e}")

        # Last interaction
        last_iso, last_min_ago = _last_interaction(_senior_id) if False else (None, None)
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT MAX(created_at) FROM memory_history WHERE user_id = ? AND role = 'user'",
                    (_senior_id,)
                ).fetchone()
                if row and (row.get(0) if hasattr(row, 'get') else row[0]):
                    last_dt = row.get(0) if hasattr(row, 'get') else row[0]
                    if hasattr(last_dt, 'isoformat'):
                        last_iso = last_dt.isoformat()
                        delta = datetime.utcnow() - last_dt.replace(tzinfo=None) if hasattr(last_dt, 'tzinfo') and last_dt.tzinfo else datetime.utcnow() - last_dt
                        last_min_ago = max(0, int(delta.total_seconds() // 60))
        except Exception:
            pass

        # Sprint AI.1: caregiver-appropriate bus slice.
        # Filters out internal kinds (intent, decision, user_input, ack)
        # — caregiver shouldn't see "AI rozhodl: speak". Keeps observation
        # + context (warning+) so the family can see "co Radim právě
        # zaznamenal" without raw technical noise. Translation to plain
        # Czech happens client-side via caregiver-module._translateSender.
        recent_activity = []
        try:
            from agent_bus import recent as _bus_recent
            raw = _bus_recent(_senior_id, since=120, limit=20,
                              kinds=['observation', 'context'],
                              severity_min='warning')
            for m in raw:
                # Strip payload internals — only what UI needs
                payload = m.get('payload') or {}
                recent_activity.append({
                    'id': m.get('id'),
                    'sender': m.get('sender'),
                    'kind': m.get('kind'),
                    'severity': m.get('severity'),
                    'topic': m.get('topic'),
                    'message': payload.get('message') or '',
                    'created_at': m.get('created_at'),
                })
        except Exception as e:
            logger.debug(f"caregiver_inbox bus fetch: {e}")

        return jsonify({
            'success': True,
            'senior': {
                'id': _senior_id,
                'name': _addressee_name(_senior_id),
            },
            'now': {
                'brain_mode': brain_now['brain_mode'],
                'coherence': brain_now['coherence'],
                'last_interaction_at': last_iso,
                'last_interaction_minutes_ago': last_min_ago,
            },
            'observations': observations,
            'summary': summary,
            'recent_activity': recent_activity,
        })

    return _inner(senior_id)


# ═════════════════════════════════════════════════════════════════════
# Sprint AJ: caregiver -> Radim -> senior message injection ("whisper")
# ═════════════════════════════════════════════════════════════════════
# Caregiver doesn't write directly to the senior. They write a whisper
# TO RADIM and Radim weaves it into the next natural conversation.
# This preserves the "personal assistant who happens to remember"
# illusion instead of "your daughter is monitoring you" anxiety.

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/whisper', methods=['POST', 'OPTIONS'])
def caregiver_whisper(senior_id):
    """Caregiver leaves a private note for Radim about their senior.

    Body: {"text": "Připomeň jí prosím vzít léky večer", "priority": "normal"}
        priority: 'low' | 'normal' | 'high' (affects how soon Radim raises it)

    Stored in memory_learning.caregiver_whispers + emitted to bus
    as kind='context' so chat-time prompt builder picks it up.

    Idempotent: same text within 5 min returns existing whisper id.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    from auth_middleware import require_auth as _ra
    @_ra
    def _inner(_senior_id):
        caller = getattr(g, 'auth_user', None) or {}
        caller_id = str(caller.get('user_id') or caller.get('id') or '')
        if not caller_id:
            return jsonify({'success': False, 'error': 'Auth required'}), 401

        if not _is_family_of(_senior_id, caller_id):
            return jsonify({'success': False, 'error': 'Not linked to this senior'}), 403

        body = request.get_json(silent=True) or {}
        text = (body.get('text') or '').strip()
        if not text:
            return jsonify({'success': False, 'error': 'text required'}), 400
        if len(text) > 500:
            text = text[:500]
        priority = body.get('priority', 'normal')
        if priority not in ('low', 'normal', 'high'):
            priority = 'normal'

        # Idempotency check: same caller + same text within 5 min
        try:
            from memory_helpers import db_load_learning, db_save_learning
            learning = db_load_learning(_senior_id) or {}
            whispers = learning.get('caregiver_whispers', [])
            now_iso = datetime.utcnow().isoformat()
            cutoff = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
            for w in whispers:
                if (w.get('text') == text and w.get('from') == caller_id
                        and w.get('created_at', '') > cutoff and not w.get('consumed_at')):
                    return jsonify({
                        'success': True,
                        'whisper_id': w.get('id'),
                        'message': 'Stejný whisper poslán před chvílí — zachovávám původní.',
                        'idempotent': True,
                    })

            # New whisper
            new_id = max([w.get('id', 0) for w in whispers], default=0) + 1
            whisper = {
                'id': new_id,
                'text': text,
                'priority': priority,
                'from': caller_id,
                'created_at': now_iso,
                'consumed_at': None,  # set when Radim weaves it into a chat reply
                'expires_at': (datetime.utcnow() + timedelta(hours=24)).isoformat(),
            }
            whispers.append(whisper)
            # Cap history — keep last 50 (consumed/expired pruned by daily cleanup)
            learning['caregiver_whispers'] = whispers[-50:]
            db_save_learning(_senior_id, learning)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:120]}), 500

        # Bus emit so chat sees it via bus.context as well
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=_senior_id,
                sender=f'caregiver.{caller_id}',
                kind='context',
                severity='info',
                topic='whisper',
                payload={
                    'whisper_id': new_id,
                    'text': text,
                    'priority': priority,
                    'message': f'Pečovatel chce, abys při přirozené příležitosti řekl: "{text}"',
                },
                ttl_minutes=1440,  # 24h
            )
        except Exception:
            pass

        # Audit log so we can trace what caregiver requested
        try:
            from memory_helpers import audit_log as _audit
            _audit(caller_id, 'caregiver_whisper', f'senior:{_senior_id}',
                   f'priority={priority} text={text[:120]}')
        except Exception:
            pass

        return jsonify({
            'success': True,
            'whisper_id': new_id,
            'expires_at': whisper['expires_at'],
        })

    return _inner(senior_id)


@caregiver_bp.route('/api/caregiver/senior/<senior_id>/whispers', methods=['GET', 'OPTIONS'])
def caregiver_whispers_list(senior_id):
    """List active (not yet consumed, not expired) whispers for a senior.

    Used by the caregiver UI to show "what's still pending" — so they
    don't double-send the same nudge.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    from auth_middleware import require_auth as _ra
    @_ra
    def _inner(_senior_id):
        caller = getattr(g, 'auth_user', None) or {}
        caller_id = str(caller.get('user_id') or caller.get('id') or '')
        if not caller_id or not _is_family_of(_senior_id, caller_id):
            return jsonify({'success': False, 'error': 'Not linked'}), 403
        try:
            from memory_helpers import db_load_learning
            learning = db_load_learning(_senior_id) or {}
            whispers = learning.get('caregiver_whispers', [])
            now_iso = datetime.utcnow().isoformat()
            active = [w for w in whispers
                      if not w.get('consumed_at')
                      and w.get('expires_at', '') > now_iso]
            consumed = [w for w in whispers if w.get('consumed_at')][-5:]
            return jsonify({
                'success': True,
                'active': active,
                'recently_delivered': consumed,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:120]}), 500

    return _inner(senior_id)


# ═════════════════════════════════════════════════════════════════════
# Sprint AU: Caregiver navrhne životní balík → senior musí potvrdit
# ═════════════════════════════════════════════════════════════════════

@caregiver_bp.route('/api/caregiver/senior/<senior_id>/suggest-preset',
                    methods=['POST', 'OPTIONS'])
def caregiver_suggest_preset(senior_id):
    """Caregiver suggests a life preset to senior — sets pending suggestion
    that senior sees + must explicitly confirm before any settings change.

    Body: {"preset_id": "grief" | "recovery" | "strong" | "rough_days",
           "note": "Mami, kvůli tátovi..."}

    No bypass: caregiver cannot directly activate presets. Senior is
    always in the loop — push notification + explicit confirm.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    from auth_middleware import require_auth as _ra
    @_ra
    def _inner(_senior_id):
        caller = getattr(g, 'auth_user', None) or {}
        caller_id = str(caller.get('user_id') or caller.get('id') or '')
        if not caller_id:
            return jsonify({'success': False, 'error': 'Auth required'}), 401
        if not _is_family_of(_senior_id, caller_id):
            return jsonify({'success': False, 'error': 'Not linked to this senior'}), 403

        body = request.get_json(silent=True) or {}
        preset_id = body.get('preset_id')
        note = (body.get('note') or '').strip()[:300]

        try:
            from life_presets import PRESETS
        except ImportError:
            return jsonify({'success': False, 'error': 'Presets not available'}), 503
        if preset_id not in PRESETS:
            return jsonify({
                'success': False,
                'error': 'Neznámý preset',
                'available': list(PRESETS.keys()),
            }), 400

        preset = PRESETS[preset_id]

        # Resolve caregiver name
        cg_name = 'Někdo z rodiny'
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT name FROM auth_users WHERE id = ?",
                    (int(caller_id),) if caller_id.isdigit() else (caller_id,)
                ).fetchone()
                if row:
                    cg_name = (row.get('name') if hasattr(row, 'get') else row[0]) or cg_name
        except Exception:
            pass

        # Save as pending suggestion in learning (same path as voice intent)
        try:
            from memory_helpers import db_load_learning, db_save_learning
            learning = db_load_learning(_senior_id) or {}
            learning['pending_preset_suggestion'] = {
                'preset_id': preset_id,
                'suggested_at': datetime.utcnow().isoformat(),
                'confidence': 'high',  # caregiver-initiated = explicit
                'source': 'caregiver',
                'caregiver_id': caller_id,
                'caregiver_name': cg_name,
                'note': note,
            }
            db_save_learning(_senior_id, learning)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:120]}), 500

        # Push notification to senior — explicit consent flow
        try:
            from notification_helpers import notify
            notify(
                to_user_id=_senior_id,
                type='preset_suggestion',
                title=f"{preset['icon']} {cg_name} něco navrhuje",
                body=('Doporučuje balík „' + preset['name'] + '". ' +
                      (('Vzkaz: ' + note) if note else 'Otevřete Radim a podívejte se.')),
                severity='info',
                data={
                    'preset_id': preset_id,
                    'preset_name': preset['name'],
                    'from_name': cg_name,
                    'note': note,
                },
            )
        except Exception as _push_err:
            logger.debug(f"preset suggestion push (non-fatal): {_push_err}")

        # Bus emit — chat-time prompt picks it up too
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=_senior_id,
                sender=f'caregiver.{caller_id}.suggest_preset',
                kind='context',
                severity='info',
                topic='preset_suggested_by_caregiver',
                payload={
                    'preset_id': preset_id,
                    'preset_name': preset['name'],
                    'caregiver_name': cg_name,
                    'note': note,
                    'message': (f"Pečovatel/ka {cg_name} doporučuje aktivovat balík "
                                f"'{preset['name']}'. {('Vzkaz: ' + note) if note else ''}"),
                },
                ttl_minutes=60 * 48,
            )
        except Exception:
            pass

        # Audit
        try:
            from memory_helpers import audit_log as _audit
            _audit(caller_id, 'caregiver_preset_suggest', _senior_id,
                   f"preset={preset_id} note={note[:80]}")
        except Exception:
            pass

        return jsonify({
            'success': True,
            'message': f"Návrh '{preset['name']}' poslán seniorovi. Musí potvrdit.",
            'preset': {'id': preset_id, 'name': preset['name'], 'icon': preset['icon']},
        })

    return _inner(senior_id)


@caregiver_bp.route('/api/caregiver/observations/<int:obs_id>/ack', methods=['POST', 'OPTIONS'])
def caregiver_observation_ack(obs_id):
    """Mark an agent_observation as acknowledged by the caregiver.

    Caller must be linked to the senior the observation belongs to.
    Idempotent: re-ack just refreshes the timestamp.
    """
    if request.method == 'OPTIONS':
        return ('', 204)

    from auth_middleware import require_auth as _ra
    @_ra
    def _inner(_obs_id):
        caller = getattr(g, 'auth_user', None) or {}
        caller_id = str(caller.get('user_id') or caller.get('id') or '')
        if not caller_id:
            return jsonify({'success': False, 'error': 'Auth required'}), 401

        # Look up observation senior
        try:
            with db_context() as db:
                r = db.execute(
                    "SELECT user_id, observation_type FROM agent_observations WHERE id = ?",
                    (_obs_id,)
                ).fetchone()
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:120]}), 500
        if not r:
            return jsonify({'success': False, 'error': 'observation not found'}), 404

        senior_id = (r.get('user_id') if hasattr(r, 'get') else r[0])
        if not senior_id or not _is_family_of(senior_id, caller_id):
            return jsonify({'success': False, 'error': 'Not authorized for this senior'}), 403

        # Look up observation type/severity for the bus ack message
        obs_type = None
        obs_severity = None
        try:
            with db_context() as db:
                row = db.execute(
                    "SELECT observation_type, severity FROM agent_observations WHERE id = ?",
                    (_obs_id,)
                ).fetchone()
            if row:
                obs_type = row.get('observation_type') if hasattr(row, 'get') else row[0]
                obs_severity = row.get('severity') if hasattr(row, 'get') else row[1]
        except Exception:
            pass

        # Mark
        try:
            with db_context(commit=True) as db:
                db.execute(
                    "UPDATE agent_observations SET acknowledged_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), _obs_id)
                )
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:120]}), 500

        # Sprint AG.4.6: emit ack to bus so:
        #   - chat-time AI sees that caregiver has been notified
        #     (-> calmer follow-up tone, no "rodina o tom neví")
        #   - agent_loop dedupe sees ack -> can skip re-alerting on
        #     same topic for the cooldown window
        try:
            from agent_bus import emit as _bus_emit
            _bus_emit(
                user_id=senior_id,
                sender=f'caregiver.{caller_id}',
                kind='ack',
                severity='info',
                topic=obs_type or 'unknown',
                payload={
                    'observation_id': _obs_id,
                    'acknowledged_by': caller_id,
                    'original_severity': obs_severity,
                    'message': f'Pečovatel potvrdil pozorování typu {obs_type}.',
                },
                correlates_with=_obs_id,
            )
        except Exception:
            pass

        return jsonify({'success': True, 'observation_id': _obs_id, 'acknowledged_at': datetime.utcnow().isoformat()})

    return _inner(obs_id)


def register_scheduler_jobs(scheduler):
    """Hook into main APScheduler. Safe to call twice — replace_existing=True."""
    try:
        scheduler.add_job(
            run_daily_narratives,
            'cron', hour=22, minute=0, id='caregiver_daily_narratives',
            replace_existing=True,
            max_instances=1, misfire_grace_time=3600,
        )
        logger.info("✅ Caregiver scheduler registered (daily narratives at 22:00)")
    except Exception as e:
        logger.warning(f"⚠️ Caregiver scheduler registration: {e}")


logger.info("👩‍⚕️ Caregiver routes v1.1 loaded — notifications + decline + scheduled view + audit + scheduler")
