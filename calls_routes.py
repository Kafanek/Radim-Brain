"""
📞 CALLS ROUTES v1.0 (Sprint C)
=============================================================================
Server-side call logging + safety indicators + quick dial.

Endpoints
---------
  GET  /api/calls/safe-to-call/<contact_id>   — 🟢🟡🔴 if contact is linked senior
  POST /api/calls/log                         — frontend logs call start/end
  GET  /api/calls/history                     — server-side history (syncs across devices)
  GET  /api/calls/quick-dial                  — top 3 contacts by frequency
  POST /api/calls/end                         — wrap-up: duration + notify family + audit

Table
-----
  call_log (id, user_id, contact_id, contact_name, room_code, call_type,
            started_at, ended_at, duration_sec, status, direction)

Audit
-----
  Every call logs into experience_audit_log via experience_routes._audit().
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth
from database import db_context, is_postgres

logger = logging.getLogger(__name__)

calls_bp = Blueprint('calls', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

CALLS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS call_log (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        contact_id TEXT,
        contact_name TEXT,
        callee_user_id TEXT,
        room_code TEXT,
        call_type TEXT DEFAULT 'video',
        direction TEXT DEFAULT 'outgoing',
        status TEXT DEFAULT 'started',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        duration_sec INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_call_log_user ON call_log(user_id, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_call_log_contact ON call_log(user_id, contact_id);
    CREATE INDEX IF NOT EXISTS idx_call_log_room ON call_log(room_code);
"""


def _init_schema():
    try:
        with db_context(commit=True) as db:
            for stmt in CALLS_SCHEMA.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    db.execute(stmt)
    except Exception as e:
        logger.debug(f"Calls schema init: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _uid():
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def _is_family_of(senior_id, family_uid):
    if not senior_id or not family_uid:
        return False
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


def _audit(actor_id, action, target_id=None, detail=None):
    """Best-effort: log into experience_audit_log via experience_routes helper."""
    try:
        from experience_routes import _audit as exp_audit
        exp_audit(
            user_id=actor_id,
            action='call_' + action,
            target_type='call',
            target_id=target_id,
            detail=detail,
            actor_id=actor_id,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@calls_bp.route('/api/calls/safe-to-call/<contact_id>', methods=['GET', 'OPTIONS'])
@require_auth
def safe_to_call(contact_id):
    """If contact is a linked senior family member, proxy caregiver/safe-to-call.
    Otherwise returns green (generic OK) — we can't reason about non-linked contacts."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Look up the contact → get phone/email/linked user id
    target_user_id = None
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT id, linked_family_link_id FROM contacts "
                "WHERE user_id = ? AND id = ?",
                (uid, contact_id)
            ).fetchone() if contact_id.isdigit() else None
            if r:
                link_id = r[1] if isinstance(r, (list, tuple)) else r.get('linked_family_link_id')
                if link_id:
                    r2 = db.execute(
                        "SELECT senior_id FROM senior_family_links WHERE id = ?",
                        (link_id,)
                    ).fetchone()
                    if r2:
                        target_user_id = r2[0] if isinstance(r2, (list, tuple)) else r2.get('senior_id')
    except Exception:
        pass

    # If target is linked senior, use caregiver safe-to-call heuristic
    if target_user_id and _is_family_of(target_user_id, uid):
        try:
            from caregiver_routes import _last_interaction, _recent_c_avg
            hour = datetime.utcnow().hour
            hour_cz = (hour + 2) % 24
            _, min_ago = _last_interaction(target_user_id)
            active = (min_ago is not None and min_ago < 10)
            c_avg, c_n = _recent_c_avg(target_user_id, hours=2)
            distressed = (c_avg is not None and c_n >= 3 and c_avg < 0.32)
            calm = (c_avg is not None and c_n >= 3 and c_avg >= 0.55)

            if distressed:
                return jsonify({'success': True, 'status': 'red',
                                'title': 'Možná nevolejte teď',
                                'detail': 'Tento člověk se teď necítí dobře. Zkuste později.'})
            if hour_cz >= 22 or hour_cz < 6:
                return jsonify({'success': True, 'status': 'yellow',
                                'title': 'Možná odpočívá',
                                'detail': f'Je {hour_cz}:00. Raději počkejte do rána.'})
            if active:
                return jsonify({'success': True, 'status': 'yellow',
                                'title': 'Právě mluví s Radimem',
                                'detail': f'Odezva před {min_ago} min — zkuste za chvíli.'})
            if calm:
                return jsonify({'success': True, 'status': 'green',
                                'title': 'Dobrý čas zavolat',
                                'detail': 'Je v klidu, hezký den na hovor.'})
        except Exception as e:
            logger.debug(f"safe-to-call linked: {e}")

    # Default: green with generic message (non-linked contact)
    return jsonify({
        'success': True,
        'status': 'green',
        'title': 'Zavolejte',
        'detail': 'Vše v pořádku.',
    })


@calls_bp.route('/api/calls/log', methods=['POST', 'OPTIONS'])
@require_auth
def log_call():
    """Frontend logs a call at start. Returns call_log id for later /end hook."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    contact_id = (data.get('contactId') or '')[:64]
    contact_name = (data.get('contactName') or 'Kontakt')[:200]
    callee_uid = (data.get('calleeUserId') or '')[:80]
    room_code = (data.get('roomCode') or '')[:120]
    call_type = (data.get('callType') or 'video').strip().lower()
    direction = (data.get('direction') or 'outgoing').strip().lower()
    if call_type not in ('video', 'audio'):
        call_type = 'video'
    if direction not in ('outgoing', 'incoming'):
        direction = 'outgoing'

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                r = db.execute(
                    "INSERT INTO call_log "
                    "(user_id, contact_id, contact_name, callee_user_id, "
                    "room_code, call_type, direction, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                    (uid, contact_id or None, contact_name, callee_uid or None,
                     room_code, call_type, direction, 'started')
                ).fetchone()
                call_id = r[0] if isinstance(r, (list, tuple)) else r.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO call_log "
                    "(user_id, contact_id, contact_name, callee_user_id, "
                    "room_code, call_type, direction, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (uid, contact_id or None, contact_name, callee_uid or None,
                     room_code, call_type, direction, 'started')
                )
                call_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"log call: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'started', call_id, f'{direction}:{call_type}:{contact_name}')
    return jsonify({'success': True, 'callId': call_id})


@calls_bp.route('/api/calls/end', methods=['POST', 'OPTIONS'])
@require_auth
def end_call():
    """Frontend signals call end. Records duration, notifies linked family if
    short/missed, audits."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    call_id = int(data.get('callId') or 0)
    duration = max(0, int(data.get('durationSec') or 0))
    reason = (data.get('reason') or 'completed').strip().lower()

    if not call_id:
        return jsonify({'success': False, 'error': 'callId required'}), 400
    status = 'completed' if duration >= 5 else ('missed' if duration == 0 else 'short')

    try:
        with db_context(commit=True) as db:
            # Ownership check + update
            r = db.execute(
                "SELECT contact_name, callee_user_id FROM call_log "
                "WHERE id = ? AND user_id = ?",
                (call_id, uid)
            ).fetchone()
            if not r:
                return jsonify({'success': False, 'error': 'not found'}), 404
            def v(i, k):
                return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            contact_name = v(0, 'contact_name')
            callee_uid = v(1, 'callee_user_id')

            db.execute(
                "UPDATE call_log SET ended_at = CURRENT_TIMESTAMP, "
                "duration_sec = ?, status = ? WHERE id = ? AND user_id = ?",
                (duration, status, call_id, uid)
            )
    except Exception as e:
        logger.error(f"end call: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'ended', call_id, f'dur={duration}s status={status}')

    # If caller is senior AND callee is linked family, notify that call ended
    try:
        if callee_uid and _is_family_of(uid, callee_uid):
            # Caller was linked family of senior, or vice versa
            from caregiver_routes import create_caregiver_notification
            if status == 'completed':
                create_caregiver_notification(
                    recipient_id=callee_uid,
                    senior_id=uid,
                    ntype='call_ended',
                    title='📞 Hovor skončil',
                    body=f'Hovor s vaším blízkým ({contact_name}) trval {duration // 60} min {duration % 60} s.',
                    severity='info',
                    ref_type='call',
                    ref_id=call_id,
                )
    except Exception as e:
        logger.debug(f"end-call notify: {e}")

    return jsonify({
        'success': True,
        'callId': call_id,
        'durationSec': duration,
        'status': status,
    })


@calls_bp.route('/api/calls/history', methods=['GET', 'OPTIONS'])
@require_auth
def history():
    """Server-side history — last 50 calls, synced across devices."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT id, contact_id, contact_name, room_code, call_type, "
                "direction, status, started_at, ended_at, duration_sec "
                "FROM call_log WHERE user_id = ? "
                "ORDER BY started_at DESC LIMIT 50",
                (uid,)
            ).fetchall()
    except Exception:
        rows = []

    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        dur = v(9) or 0
        items.append({
            'id': v(0),
            'contactId': v(1),
            'contactName': v(2),
            'roomCode': v(3),
            'callType': v(4),
            'direction': v(5),
            'status': v(6),
            'startedAt': str(v(7) or ''),
            'endedAt': str(v(8) or ''),
            'durationSec': dur,
            'durationLabel': f'{dur // 60}:{(dur % 60):02d}' if dur else '',
        })
    return jsonify({'success': True, 'history': items, 'count': len(items)})


@calls_bp.route('/api/calls/quick-dial', methods=['GET', 'OPTIONS'])
@require_auth
def quick_dial():
    """Top 3 contacts by completed-call frequency in last 60 days."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    cutoff = datetime.utcnow() - timedelta(days=60)
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT contact_id, contact_name, COUNT(*) as cnt "
                "FROM call_log "
                "WHERE user_id = ? AND status = ? AND started_at >= ? "
                "AND contact_name IS NOT NULL "
                "GROUP BY contact_id, contact_name "
                "ORDER BY cnt DESC LIMIT 3",
                (uid, 'completed', cutoff)
            ).fetchall()
    except Exception:
        rows = []

    items = []
    for r in rows or []:
        def v(i):
            return r[i] if isinstance(r, (list, tuple)) else list(r.values())[i]
        items.append({
            'contactId': v(0),
            'contactName': v(1),
            'callCount': int(v(2) or 0),
        })
    return jsonify({'success': True, 'items': items, 'count': len(items)})



# ─────────────────────────────────────────────────────────────────────────────
# Sprint D — ICE servers + telemetry (stability)
# ─────────────────────────────────────────────────────────────────────────────

# Default ICE configuration:
#   - Google public STUN (free, always available)
#   - Cloudflare STUN (secondary)
#   - Metered OpenRelay TURN (free public, rate-limited — good for MVP)
#
# For production, set ENV vars:
#   TURN_URL       — e.g. turn:turn.radimcare.cz:3478
#   TURN_USER      — username
#   TURN_PASSWORD  — password
#   (or METERED_API_KEY for dynamic TURN creds from metered.ca)
#
# Metered.ca free tier: 500 MB/month — enough for ~8 hrs of video.
# Self-hosted coturn: ~€6/mo on Hetzner CX22 — unlimited.

_DEFAULT_STUN = [
    'stun:stun.l.google.com:19302',
    'stun:stun1.l.google.com:19302',
    'stun:stun.cloudflare.com:3478',
]

# OpenRelay public TURN — works without signup; rate-limited for abuse
_OPENRELAY_TURN = [
    {'urls': 'turn:openrelay.metered.ca:80',
     'username': 'openrelayproject', 'credential': 'openrelayproject'},
    {'urls': 'turn:openrelay.metered.ca:443',
     'username': 'openrelayproject', 'credential': 'openrelayproject'},
    {'urls': 'turns:openrelay.metered.ca:443?transport=tcp',
     'username': 'openrelayproject', 'credential': 'openrelayproject'},
]


@calls_bp.route('/api/calls/ice-servers', methods=['GET', 'OPTIONS'])
@require_auth
def ice_servers():
    """Return ICE server list for WebRTC RTCPeerConnection config.
    STUN + TURN with credentials. TURN from env or fallback to OpenRelay."""
    import os as _os
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    servers = [{'urls': s} for s in _DEFAULT_STUN]

    # Priority 1: explicit TURN credentials via env vars
    turn_url = _os.environ.get('TURN_URL', '').strip()
    turn_user = _os.environ.get('TURN_USER', '').strip()
    turn_pwd = _os.environ.get('TURN_PASSWORD', '').strip()
    if turn_url and turn_user and turn_pwd:
        servers.append({
            'urls': turn_url,
            'username': turn_user,
            'credential': turn_pwd,
        })
        source = 'self-hosted'
    else:
        # Priority 2: OpenRelay public TURN (no signup needed)
        servers.extend(_OPENRELAY_TURN)
        source = 'openrelay-public'

    return jsonify({
        'success': True,
        'iceServers': servers,
        'iceTransportPolicy': 'all',
        'source': source,
    })


@calls_bp.route('/api/calls/telemetry', methods=['POST', 'OPTIONS'])
@require_auth
def telemetry():
    """Frontend posts connection quality stats for debugging / aggregate.
    Not persisted by default — just logs at INFO when quality degrades."""
    if request.method == 'OPTIONS':
        return '', 204
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json() or {}
    call_id = data.get('callId')
    quality = (data.get('quality') or 'unknown')[:32]
    bitrate_kbps = int(data.get('bitrateKbps') or 0)
    packet_loss = float(data.get('packetLoss') or 0)
    rtt_ms = int(data.get('rttMs') or 0)
    event = (data.get('event') or 'sample')[:32]

    if quality in ('poor', 'very_poor', 'lost'):
        logger.info(f"📹 call-telemetry uid={uid} call={call_id} "
                    f"quality={quality} br={bitrate_kbps}kbps "
                    f"loss={packet_loss:.2%} rtt={rtt_ms}ms event={event}")
    return jsonify({'success': True})



# ─────────────────────────────────────────────────────────────────────────────
# Sprint E2 — recording upload + transcript save (persistence)
# ─────────────────────────────────────────────────────────────────────────────

_MAX_RECORDING_BYTES = 50 * 1024 * 1024   # 50 MB (ca. 15-20 min at 300 kbps)
_MAX_TRANSCRIPT_LEN = 20000               # ~3000 words


@calls_bp.route('/api/calls/<int:call_id>/recording', methods=['POST', 'OPTIONS'])
@require_auth
def upload_recording(call_id):
    """Upload recorded call as a contribution in Radimův Odkaz OR as a
    gallery photo (depending on target).

    Body accepts either:
      - multipart form with 'recording' file + 'target' ('odkaz'|'gallery')
      - JSON with 'dataUrl' + 'target'
    """
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Verify call ownership
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT contact_name FROM call_log WHERE id = ? AND user_id = ?",
                (call_id, uid)
            ).fetchone()
        if not r:
            return jsonify({'success': False, 'error': 'not found'}), 404
        contact_name = r[0] if isinstance(r, (list, tuple)) else r.get('contact_name')
    except Exception:
        return jsonify({'success': False, 'error': 'internal'}), 500

    target = (request.form.get('target') or
              (request.get_json(silent=True) or {}).get('target') or 'odkaz').strip().lower()

    # Parse payload
    file_bytes = None
    mime = 'video/webm'
    if 'recording' in request.files:
        f = request.files['recording']
        file_bytes = f.read()
        mime = f.mimetype or 'video/webm'
    else:
        data = request.get_json(silent=True) or {}
        data_url = data.get('dataUrl')
        if data_url and isinstance(data_url, str) and data_url.startswith('data:'):
            import base64
            try:
                header, b64 = data_url.split(',', 1)
                mime = header.split(';')[0].replace('data:', '') or 'video/webm'
                file_bytes = base64.b64decode(b64)
            except Exception:
                return jsonify({'success': False, 'error': 'invalid dataUrl'}), 400

    if not file_bytes:
        return jsonify({'success': False, 'error': 'no recording provided'}), 400
    if len(file_bytes) > _MAX_RECORDING_BYTES:
        return jsonify({'success': False,
                        'error': f'Nahrávka je větší než {_MAX_RECORDING_BYTES // (1024*1024)} MB'}), 413

    # Store as data URL (mirrors gallery pattern). TODO: cloud storage later.
    import base64 as _b64
    data_url = f"data:{mime};base64,{_b64.b64encode(file_bytes).decode('ascii')}"
    size = len(file_bytes)

    new_id = None
    if target == 'gallery':
        # Save into gallery_photos as a video item
        try:
            with db_context(commit=True) as db:
                if is_postgres():
                    row = db.execute(
                        "INSERT INTO gallery_photos "
                        "(user_id, url, caption, album, filename, mime, size_bytes, shared_with_family) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                        (uid, data_url, f'Hovor s {contact_name}', 'calls',
                         f'call-{call_id}.webm', mime, size, False)
                    ).fetchone()
                    new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
                else:
                    cur = db.execute(
                        "INSERT INTO gallery_photos "
                        "(user_id, url, caption, album, filename, mime, size_bytes, shared_with_family) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (uid, data_url, f'Hovor s {contact_name}', 'calls',
                         f'call-{call_id}.webm', mime, size, 0)
                    )
                    new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
        except Exception as e:
            logger.error(f"recording upload gallery: {e}")
            return jsonify({'success': False, 'error': 'internal'}), 500
    else:
        # Save as Radimův Odkaz contribution (draft, senior will approve)
        try:
            with db_context(commit=True) as db:
                title = f'Hovor s {contact_name}'[:200]
                transcript = f'(Nahrávka hovoru — {size // 1024} kB, {mime})'
                if is_postgres():
                    row = db.execute(
                        "INSERT INTO experience_contributions "
                        "(user_id, type, title, theme, depth, transcript, "
                        "audio_url, audio_size_bytes, privacy) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                        (uid, 'witness', title, 'family', 1, transcript,
                         data_url, size, 'draft')
                    ).fetchone()
                    new_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
                else:
                    cur = db.execute(
                        "INSERT INTO experience_contributions "
                        "(user_id, type, title, theme, depth, transcript, "
                        "audio_url, audio_size_bytes, privacy) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (uid, 'witness', title, 'family', 1, transcript,
                         data_url, size, 'draft')
                    )
                    new_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
        except Exception as e:
            logger.error(f"recording upload odkaz: {e}")
            return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'recording_saved', call_id, f'target={target} size={size}')
    return jsonify({
        'success': True,
        'callId': call_id,
        'target': target,
        'id': new_id,
        'sizeBytes': size,
    })


@calls_bp.route('/api/calls/<int:call_id>/transcript', methods=['POST', 'OPTIONS'])
@require_auth
def save_transcript(call_id):
    """Save auto-captured live transcript to user_notes with #call:<name> tag."""
    if request.method == 'OPTIONS':
        return '', 204
    _init_schema()
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json() or {}
    text = (data.get('text') or '').strip()[:_MAX_TRANSCRIPT_LEN]
    if len(text) < 20:
        return jsonify({'success': False, 'error': 'Přepis je příliš krátký.'}), 400

    # Verify call ownership
    contact_name = 'Kontakt'
    try:
        with db_context() as db:
            r = db.execute(
                "SELECT contact_name FROM call_log WHERE id = ? AND user_id = ?",
                (call_id, uid)
            ).fetchone()
        if r:
            contact_name = r[0] if isinstance(r, (list, tuple)) else r.get('contact_name')
    except Exception:
        pass

    tag_safe = ''.join(c for c in (contact_name or '').lower()
                       if c.isalnum() or c == '_')[:40]
    note_text = (
        f'📞 Přepis hovoru s {contact_name}\n\n'
        f'{text}\n\n'
        f'#call_{tag_safe} #hovor'
    )

    try:
        with db_context(commit=True) as db:
            if is_postgres():
                row = db.execute(
                    "INSERT INTO user_notes "
                    "(user_id, text, category) VALUES (?, ?, ?) RETURNING id",
                    (uid, note_text[:10000], 'call')
                ).fetchone()
                note_id = row[0] if isinstance(row, (list, tuple)) else row.get('id')
            else:
                cur = db.execute(
                    "INSERT INTO user_notes "
                    "(user_id, text, category) VALUES (?, ?, ?)",
                    (uid, note_text[:10000], 'call')
                )
                note_id = cur.lastrowid if hasattr(cur, 'lastrowid') else None
    except Exception as e:
        logger.error(f"transcript save: {e}")
        return jsonify({'success': False, 'error': 'internal'}), 500

    _audit(uid, 'transcript_saved', call_id, f'note={note_id} chars={len(text)}')
    return jsonify({'success': True, 'callId': call_id, 'noteId': note_id})


logger.info("📞 Calls routes v1.2 loaded — ice-servers + telemetry + recording + transcript")
