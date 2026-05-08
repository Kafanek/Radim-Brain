"""
🔔 In-app notifications — account-to-account (v10.37)
=============================================================================
Replaces Twilio SMS paths for family/caregiver alerts. GDPR-clean: all data
stays inside RADIM, no external messaging provider.

Core flow:
    notify(to_user_id, type, title, body, ...) → DB row + SocketIO push

Crisis flow integration:
    notify_senior_family(senior_id, ...) → resolves all confirmed
    senior_family_links and notifies every linked family account.
"""

import json
import logging
from datetime import datetime

from database import db_context, db_insert, is_postgres

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# UNREAD COUNT — Redis cache (Sprint X6: perf)
# ═══════════════════════════════════════════════════════════════════
# This endpoint is hit ~30×/min per active user (frontend polls for the
# bell-icon badge). A trivial COUNT() query that takes 470ms across the
# Atlantic adds up. Cache 10s per user; invalidate on write paths
# (notify, mark_read, mark_all_read). Worst-case staleness: 10s, which
# is invisible because frontend itself polls every 2-5s.

_UNREAD_TTL = 10  # seconds


def _unread_cache_key(user_id):
    return f"unread:{user_id}"


def _invalidate_unread(user_id):
    """Drop the cached unread count for this user. Safe to call from any
    write path; silent no-op if Redis is unavailable."""
    if not user_id:
        return
    try:
        from redis_cache import cache_delete
        cache_delete(_unread_cache_key(user_id))
    except Exception:
        pass  # cache is best-effort, never block the write path

# ═══════════════════════════════════════════════════════════════════
# NOTIFICATION TYPES (documented — do not free-type)
# ═══════════════════════════════════════════════════════════════════

TYPES = {
    "sos": "SOS senior tísňové volání",
    "crisis_alert": "Krizová událost (pád, vitální, ticho)",
    "family_invite": "Pozvánka do rodinného propojení",
    "family_accepted": "Rodinný člen přijal pozvánku",
    "family_revoked": "Rodinné propojení zrušeno",
    "health_alert": "Zdravotní upozornění",
    "reminder": "Připomenutí",
    "chat_msg": "Nová zpráva",
    "info": "Informace",
}

SEVERITIES = ("info", "warning", "alert", "crisis")


# ═══════════════════════════════════════════════════════════════════
# LOW-LEVEL — create one notification + push via SocketIO
# ═══════════════════════════════════════════════════════════════════

def _load_notif_prefs(user_id):
    """Load user's notification preferences (muted types + DND window).

    Returns dict: {muted_types: [...], dnd_until: iso_or_None}.
    Gracefully returns empty defaults if table missing or user has none.
    """
    try:
        with db_context() as db:
            row = db.execute(
                "SELECT muted_types, dnd_until FROM user_notification_prefs "
                "WHERE user_id = ?",
                (str(user_id),)
            ).fetchone()
        if not row:
            return {"muted_types": [], "dnd_until": None}
        muted_raw = row[0] if isinstance(row, (list, tuple)) else row.get("muted_types")
        dnd = row[1] if isinstance(row, (list, tuple)) else row.get("dnd_until")
        try:
            muted = json.loads(muted_raw) if isinstance(muted_raw, str) else (muted_raw or [])
        except Exception:
            muted = []
        return {"muted_types": muted or [], "dnd_until": str(dnd) if dnd else None}
    except Exception:
        # Table likely missing — return defaults silently
        return {"muted_types": [], "dnd_until": None}


def _should_suppress_push(user_id, type, severity):
    """Sprint C: respect user's DND + per-type mutes for WebPush delivery.

    SOS + crisis severity always bypass suppression (safety-critical).
    Does NOT suppress in-app DB insert or SocketIO emit — those remain
    available when user opens the app.
    """
    if type == "sos":
        return False
    if severity == "crisis":
        return False
    prefs = _load_notif_prefs(user_id)
    # DND window
    dnd = prefs.get("dnd_until")
    if dnd:
        try:
            until = datetime.fromisoformat(dnd.replace("Z", "+00:00"))
            if until.replace(tzinfo=None) > datetime.utcnow():
                return True
        except Exception:
            pass
    # Per-type mute
    if type in (prefs.get("muted_types") or []):
        return True
    return False


def notify(to_user_id, type, title, body=None, from_user_id=None,
           severity="info", data=None):
    """Create notification + push live via SocketIO `user_{id}` room.

    Returns notification id (int) or None on failure.
    Sprint C: respects user_notification_prefs — SOS and crisis bypass mute.
    """
    if not to_user_id or not title or not type:
        logger.warning("notify(): missing required field")
        return None
    if severity not in SEVERITIES:
        severity = "info"

    data_json = json.dumps(data or {}, ensure_ascii=False)
    nid = None

    try:
        with db_context(commit=True) as db:
            nid = db_insert(
                db, "user_notifications",
                ["to_user_id", "from_user_id", "type", "severity",
                 "title", "body", "data"],
                [str(to_user_id), str(from_user_id) if from_user_id else None,
                 type, severity, title, body or "", data_json],
            )
    except Exception as e:
        logger.error(f"notify DB insert failed: {e}")
        return None

    # Invalidate unread cache so the new notification shows in the badge
    # within ~1 polling tick instead of waiting up to 10s.
    _invalidate_unread(to_user_id)

    suppressed = _should_suppress_push(to_user_id, type, severity)

    # Always push SocketIO — client respects DND to avoid flash/chime but can
    # see the notification in the bell panel on demand.
    try:
        from socketio_handlers import socketio
        if socketio:
            payload = {
                "id": nid,
                "type": type,
                "severity": severity,
                "title": title,
                "body": body,
                "from_user_id": str(from_user_id) if from_user_id else None,
                "data": data or {},
                "created_at": datetime.utcnow().isoformat() + "Z",
            }
            socketio.emit("notification:new", payload, room=f"user_{to_user_id}")
    except Exception as e:
        logger.debug(f"SocketIO push skipped: {e}")

    # WebPush — SKIPPED when user muted or DND active (sleeping senior
    # should not be woken by non-critical push).
    if not suppressed:
        try:
            _webpush_if_subscribed(to_user_id, title, body or "", severity, type,
                                   extra_data=data or {})
        except Exception as e:
            logger.debug(f"WebPush skipped: {e}")

    logger.info(
        f"🔔 notify → user={to_user_id} type={type} sev={severity} id={nid}"
        f"{' SUPPRESSED_PUSH' if suppressed else ''}"
    )
    return nid


def _webpush_if_subscribed(user_id, title, body, severity, type, extra_data=None):
    """Send WebPush to subscribed devices for this user_id.
    Sprint I.2: extra_data forwards action + ids so SW click handler
    can deep-link to the right module (e.g. /?module=komunikace&openConv=…)."""
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return
    import os
    vapid_priv = os.environ.get("VAPID_PRIVATE_KEY")
    vapid_claims = os.environ.get("VAPID_CLAIMS_EMAIL", "mailto:info@radimcare.cz")
    if not vapid_priv:
        return

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT endpoint, keys FROM push_subscriptions WHERE user_id = ?",
                (str(user_id),)
            ).fetchall()
    except Exception:
        return

    # Derive deep-link URL from action
    url = "/?notifications=1"
    try:
        action = (extra_data or {}).get("action")
        if action == "open_conversation" and (extra_data or {}).get("conversationId"):
            url = f"/?module=komunikace&openConv={extra_data['conversationId']}"
        elif action == "incoming_call" and (extra_data or {}).get("callerId"):
            url = f"/?action=incoming_call&callerId={extra_data['callerId']}"
        elif action == "incoming_group_call" and (extra_data or {}).get("roomId"):
            url = f"/?action=incoming_group_call&roomId={extra_data['roomId']}"
        elif action == "open_caregiver_inbox" and (extra_data or {}).get("senior_id"):
            # Sprint AG.2: caregiver taps push for senior crisis → opens
            # caregiver dashboard with that senior's inbox in focus, with
            # the specific obs_id highlighted/pre-acked if obs_id present.
            sid = extra_data["senior_id"]
            obs_id = extra_data.get("obs_id")
            if obs_id:
                url = f"/?module=caregiver&senior={sid}&obs={obs_id}"
            else:
                url = f"/?module=caregiver&senior={sid}"
    except Exception:
        pass

    payload = json.dumps({
        "title": title, "body": body[:140], "severity": severity, "type": type,
        "url": url,
        "data": extra_data or {},
    }, ensure_ascii=False)

    for row in rows or []:
        try:
            endpoint = row[0]
            keys = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
            webpush(
                subscription_info={"endpoint": endpoint, "keys": keys},
                data=payload,
                vapid_private_key=vapid_priv,
                vapid_claims={"sub": vapid_claims},
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# HIGH-LEVEL — crisis / SOS broadcast to senior's family
# ═══════════════════════════════════════════════════════════════════

def notify_senior_family(senior_id, type, title, body=None,
                         severity="alert", data=None, include_caregiver=True):
    """Notify every confirmed family member linked to this senior.

    Respects per-link opt-in flags (v10.38):
      notify_on_sos      — fired when type == 'sos'
      notify_on_crisis   — fired when type in {'crisis_alert', 'health_alert'}
      notify_on_daily    — fired when type in {'daily_summary', 'info'}
      (other types always notify — family_invite, family_accepted, etc.)

    Also notifies memory_profiles.data.caregiver_id (1-to-1 legacy link)
    if include_caregiver=True.

    Returns list of notification ids successfully created.
    """
    if not senior_id:
        return []

    # Map notification type to opt-in column
    OPT_IN_MAP = {
        "sos": "notify_on_sos",
        "crisis_alert": "notify_on_crisis",
        "health_alert": "notify_on_crisis",
        "daily_summary": "notify_on_daily",
        "info": "notify_on_daily",
    }
    opt_column = OPT_IN_MAP.get(type)

    targets = set()

    # Resolve confirmed family links — honor per-link opt-in
    try:
        with db_context() as db:
            if opt_column:
                # Filter by the opt-in column (default TRUE if column missing / null)
                rows = db.execute(
                    f"SELECT family_user_id FROM senior_family_links "
                    f"WHERE senior_id = ? AND confirmed_at IS NOT NULL "
                    f"AND revoked_at IS NULL AND family_user_id IS NOT NULL "
                    f"AND COALESCE({opt_column}, TRUE) = TRUE",
                    (str(senior_id),)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT family_user_id FROM senior_family_links "
                    "WHERE senior_id = ? AND confirmed_at IS NOT NULL "
                    "AND revoked_at IS NULL AND family_user_id IS NOT NULL",
                    (str(senior_id),)
                ).fetchall()
            for row in rows or []:
                if row[0]:
                    targets.add(str(row[0]))
    except Exception as e:
        logger.debug(f"notify_senior_family link lookup: {e}")

    # Resolve legacy single caregiver_id from memory_profiles
    if include_caregiver:
        try:
            from memory_helpers import db_load_profile
            profile = db_load_profile(str(senior_id)) or {}
            cg = profile.get("caregiver_id")
            if cg:
                targets.add(str(cg))
        except Exception as e:
            logger.debug(f"notify_senior_family caregiver lookup: {e}")

    data = dict(data or {})
    data.setdefault("senior_id", str(senior_id))

    ids = []
    for uid in targets:
        nid = notify(
            to_user_id=uid, type=type, title=title, body=body,
            from_user_id=senior_id, severity=severity, data=data,
        )
        if nid:
            ids.append(nid)

    logger.info(f"🔔 notify_senior_family senior={senior_id} type={type} "
                f"→ {len(ids)}/{len(targets)} recipients")
    return ids


# ═══════════════════════════════════════════════════════════════════
# READ / ACK
# ═══════════════════════════════════════════════════════════════════

def list_notifications(user_id, limit=50, unread_only=False, before_id=None):
    """List notifications for a user, newest first."""
    if not user_id:
        return []
    try:
        with db_context() as db:
            q = ("SELECT id, type, severity, title, body, data, read_at, "
                 "created_at, from_user_id FROM user_notifications "
                 "WHERE to_user_id = ?")
            args = [str(user_id)]
            if unread_only:
                q += " AND read_at IS NULL"
            if before_id:
                q += " AND id < ?"
                args.append(int(before_id))
            q += " ORDER BY id DESC LIMIT ?"
            args.append(int(limit))
            rows = db.execute(q, tuple(args)).fetchall() or []
            result = []
            for r in rows:
                data_val = r[5]
                if isinstance(data_val, str):
                    try: data_val = json.loads(data_val)
                    except Exception: data_val = {}
                result.append({
                    "id": r[0], "type": r[1], "severity": r[2],
                    "title": r[3], "body": r[4], "data": data_val or {},
                    "read_at": str(r[6]) if r[6] else None,
                    "created_at": str(r[7]) if r[7] else None,
                    "from_user_id": r[8],
                })
            return result
    except Exception as e:
        logger.error(f"list_notifications: {e}")
        return []


def unread_count(user_id):
    if not user_id:
        return 0

    # Try cache first (10s TTL). Cache miss / Redis unavailable → fall to DB.
    try:
        from redis_cache import cache_get_json
        cached = cache_get_json(_unread_cache_key(user_id))
        if cached is not None and isinstance(cached, dict) and "count" in cached:
            return int(cached["count"])
    except Exception:
        pass

    try:
        with db_context() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM user_notifications "
                "WHERE to_user_id = ? AND read_at IS NULL",
                (str(user_id),)
            ).fetchone()
            count = int(row[0]) if row else 0

            # Populate cache (best-effort)
            try:
                from redis_cache import cache_set_json
                cache_set_json(
                    _unread_cache_key(user_id),
                    {"count": count},
                    ttl=_UNREAD_TTL,
                )
            except Exception:
                pass

            return count
    except Exception:
        return 0


def mark_read(notif_id, user_id):
    if not notif_id or not user_id:
        return False
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "UPDATE user_notifications SET read_at = NOW() "
                    "WHERE id = ? AND to_user_id = ? AND read_at IS NULL",
                    (int(notif_id), str(user_id))
                )
            else:
                db.execute(
                    "UPDATE user_notifications SET read_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND to_user_id = ? AND read_at IS NULL",
                    (int(notif_id), str(user_id))
                )
        _invalidate_unread(user_id)
        return True
    except Exception as e:
        logger.debug(f"mark_read: {e}")
        return False


def mark_all_read(user_id):
    if not user_id:
        return 0
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                cur = db.execute(
                    "UPDATE user_notifications SET read_at = NOW() "
                    "WHERE to_user_id = ? AND read_at IS NULL",
                    (str(user_id),)
                )
            else:
                cur = db.execute(
                    "UPDATE user_notifications SET read_at = CURRENT_TIMESTAMP "
                    "WHERE to_user_id = ? AND read_at IS NULL",
                    (str(user_id),)
                )
            n = cur.rowcount if hasattr(cur, 'rowcount') else 0
        _invalidate_unread(user_id)
        return n
    except Exception:
        return 0
