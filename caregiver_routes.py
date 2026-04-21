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

logger = logging.getLogger(__name__)

caregiver_bp = Blueprint('caregiver', __name__)


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
        model = genai.GenerativeModel('gemini-2.0-flash')
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

@caregiver_bp.route('/api/caregiver/seniors', methods=['GET'])
@require_auth
def caregiver_seniors():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    role = _role()

    # Collect senior IDs
    senior_ids = []
    if role in ('caregiver', 'teacher', 'administrator', 'admin'):
        try:
            with db_context() as db:
                rows = db.execute(
                    "SELECT DISTINCT user_id FROM memory_profiles LIMIT 200"
                ).fetchall()
            for r in rows or []:
                sid = r[0] if isinstance(r, (list, tuple)) else list(r.values())[0]
                if sid:
                    senior_ids.append(sid)
        except Exception:
            pass
    else:
        linked = _list_linked_seniors(uid)
        senior_ids = [l['seniorId'] for l in linked]

    out = []
    for sid in senior_ids[:50]:
        name = _addressee_name(sid) or 'Senior'
        last_ts, min_ago = _last_interaction(sid)
        c_avg, samples = _recent_c_avg(sid, hours=24)
        if c_avg is None:
            mood = 'unknown'
        elif c_avg >= 0.55:
            mood = 'good'
        elif c_avg >= 0.38:
            mood = 'soso'
        else:
            mood = 'heavy'
        out.append({
            'seniorId': sid,
            'name': name,
            'minutesSinceLastInteraction': min_ago,
            'mood': mood,
            'cAvg24h': round(c_avg, 3) if c_avg is not None else None,
        })

    # Sort: heavy mood first (needs attention)
    mood_rank = {'heavy': 0, 'soso': 1, 'unknown': 2, 'good': 3}
    out.sort(key=lambda s: (mood_rank.get(s['mood'], 5),
                            s['minutesSinceLastInteraction'] or 99999))

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


logger.info("👩‍⚕️ Caregiver routes v1.0 loaded — family + professional unified partner view")
