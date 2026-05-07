"""
🏠 HA BACKGROUND JOBS — abnormal night activity + maintenance (P2)
=============================================================================
Scheduled monitors that run over the shared HA client state.

Exported functions (called from app.py scheduler):
    run_night_activity_check(app)  — every 15 min between 23:00–05:00
    run_maintenance_check(app)     — daily at 09:00

Both are best-effort: if HA is unreachable or memory_helpers not set up,
they log and return silently — never crash the scheduler.

Night activity model:
    For each active senior:
      1. Query HA motion/door binary sensors + light states
      2. If anything is "on" during sleep hours → record entry in
         memory_learning.night_activity_log (once per night, deduped)
      3. Push family notification ONCE per night (severity=info, not alarm)
      4. Brain memory gets last_night_activity_at for chat context

Maintenance model:
    For each senior with HA configured:
      1. Check all battery sensors
      2. If value < 25% → record + push reminder (once per week per device)
      3. If sensor hasn't reported for > 48h → record + push
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def _get_active_user_ids(app):
    """Return list of user_ids that have HA activity or recent brain state.
    We don't want to query HA for every user who ever registered.
    """
    try:
        from database import db_context
    except Exception:
        return []
    user_ids = set()
    try:
        with app.app_context():
            with db_context() as db:
                # Recent brain states → active seniors
                cutoff = datetime.utcnow() - timedelta(days=7)
                rows = db.execute(
                    "SELECT DISTINCT user_id FROM brain_states "
                    "WHERE created_at >= ? LIMIT 200",
                    (cutoff,)
                ).fetchall() or []
                for r in rows:
                    uid = r[0] if isinstance(r, (list, tuple)) else r.get('user_id')
                    if uid:
                        user_ids.add(str(uid))
    except Exception as e:
        logger.debug(f'_get_active_user_ids: {e}')
    return list(user_ids)


def _save_brain_memory(app, user_id, key, value):
    """Best-effort write to memory_learning under a specific key."""
    try:
        from memory_helpers import db_load_learning, db_save_learning
        with app.app_context():
            learning = db_load_learning(user_id) or {}
            learning[key] = value
            db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f'_save_brain_memory {key}: {e}')


def _append_brain_memory_log(app, user_id, list_key, entry, cap=30):
    try:
        from memory_helpers import db_load_learning, db_save_learning
        with app.app_context():
            learning = db_load_learning(user_id) or {}
            hist = learning.get(list_key) or []
            hist.append(entry)
            learning[list_key] = hist[-cap:]
            db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f'_append_brain_memory_log {list_key}: {e}')


def _push_family(user_id, title, body, severity='info', data=None):
    try:
        from notification_helpers import notify_senior_family
        notify_senior_family(
            senior_id=user_id,
            type='home_' + severity,
            title=title,
            body=body,
            severity=severity,
            data=data or {},
            include_caregiver=True,
        )
        return True
    except Exception as e:
        logger.debug(f'_push_family: {e}')
        return False


# ================================================================
# NIGHT ACTIVITY CHECK
# ================================================================

NIGHT_HOUR_START = 23        # 23:00
NIGHT_HOUR_END = 5           # 05:00
NIGHT_DEDUPE_HOURS = 4       # Push family at most once per 4 hours


def _is_night_hour(dt=None):
    """23:00–05:00 local (we trust server tz is reasonable)."""
    dt = dt or datetime.now()
    hour = dt.hour
    return hour >= NIGHT_HOUR_START or hour < NIGHT_HOUR_END


def _detect_night_activity(ha_client):
    """Returns dict {has_activity, active_entities, reasons} from HA state."""
    if not ha_client:
        return {'has_activity': False, 'active_entities': [], 'reasons': []}

    reasons = []
    active = []
    try:
        sensors = ha_client.get_sensors_summary() or {}
    except Exception:
        sensors = {}

    # Motion
    for m in sensors.get('motion', []):
        if m.get('state') == 'on':
            active.append(m.get('entity_id') or m.get('name'))
            reasons.append(f"pohyb: {m.get('name') or '?'}")

    # Door/window opened
    for d in sensors.get('door', []):
        if d.get('state') == 'on':
            active.append(d.get('entity_id') or d.get('name'))
            reasons.append(f"otevřené: {d.get('name') or '?'}")

    # Lights on in night hours is unusual
    try:
        rooms = ha_client.get_devices_by_room() or {}
        on_lights = []
        for room in rooms.values():
            for device in room.get('devices', []):
                if device.get('domain') == 'light' and device.get('state') == 'on':
                    on_lights.append(device.get('name') or device.get('entity_id'))
        if on_lights:
            active.extend(on_lights[:5])
            reasons.append(f"svítí: {', '.join(on_lights[:3])}")
    except Exception as e:
        logger.debug(f'light scan: {e}')

    return {
        'has_activity': bool(active),
        'active_entities': active[:10],
        'reasons': reasons[:5],
    }


def run_night_activity_check(app):
    """Scheduler entry — runs every 15 min, active only during night hours."""
    if not _is_night_hour():
        return {'skipped': 'not_night'}

    try:
        from home_assistant import ha_for
    except Exception as e:
        logger.debug(f'run_night_activity_check HA import: {e}')
        return {'error': 'ha import'}

    user_ids = _get_active_user_ids(app)
    if not user_ids:
        return {'checked': 0}

    checked = 0
    pushed = 0
    for uid in user_ids:
        checked += 1
        # Per-user HA: each senior has their own home, snapshot per-user
        client = ha_for(uid)
        snapshot = _detect_night_activity(client)
        if not snapshot['has_activity']:
            continue

        # Dedupe: only push once per NIGHT_DEDUPE_HOURS
        try:
            from memory_helpers import db_load_learning
            with app.app_context():
                learning = db_load_learning(uid) or {}
                last_push = learning.get('night_activity_last_push_at')
        except Exception:
            last_push = None

        should_push = True
        if last_push:
            try:
                last_dt = datetime.fromisoformat(last_push.replace('Z', ''))
                if (datetime.utcnow() - last_dt).total_seconds() < NIGHT_DEDUPE_HOURS * 3600:
                    should_push = False
            except Exception:
                pass

        entry = {
            'at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
            'reasons': snapshot['reasons'],
            'entities': snapshot['active_entities'],
            'pushed': should_push,
        }
        _append_brain_memory_log(app, uid, 'night_activity_log', entry, cap=50)
        _save_brain_memory(app, uid, 'last_night_activity_at', entry['at'])

        if should_push:
            summary = ', '.join(snapshot['reasons'][:3])
            ok = _push_family(
                uid,
                '🌙 Noční aktivita',
                f'Váš blízký je v noci vzhůru ({summary}). Zatím nic nehlásí.',
                severity='info',
                data={'entities': snapshot['active_entities'][:5]}
            )
            if ok:
                pushed += 1
                _save_brain_memory(
                    app, uid,
                    'night_activity_last_push_at',
                    entry['at']
                )

    logger.info(f"🌙 Night activity check: checked={checked} pushed={pushed}")
    return {'checked': checked, 'pushed': pushed, 'has_activity': snapshot['has_activity']}


# ================================================================
# MAINTENANCE CHECK (battery low / sensor stale)
# ================================================================

BATTERY_THRESHOLD_LOW = 25       # %
BATTERY_NUDGE_DAYS = 7           # Don't re-nudge same device for a week
STALE_SENSOR_HOURS = 48          # Sensor that hasn't reported in 48h


def _detect_maintenance_issues(ha_client):
    """Returns {low_batteries: [...], stale_sensors: [...]}."""
    if not ha_client:
        return {'low_batteries': [], 'stale_sensors': []}

    low = []
    stale = []
    try:
        sensors = ha_client.get_sensors_summary() or {}
    except Exception:
        sensors = {}

    for b in sensors.get('battery', []):
        val = b.get('value')
        if isinstance(val, (int, float)) and val < BATTERY_THRESHOLD_LOW:
            low.append({
                'entity_id': b.get('entity_id'),
                'name': b.get('name'),
                'value': val,
            })

    # HA returns last_updated on attributes; use it if available
    try:
        now = datetime.utcnow()
        threshold = timedelta(hours=STALE_SENSOR_HOURS)
        # This branch is HA-dependent; in simulated mode we skip
        for kind in ('temperature', 'humidity', 'motion', 'door'):
            for s in sensors.get(kind, []):
                last = s.get('last_updated')
                if not last:
                    continue
                try:
                    last_dt = datetime.fromisoformat(str(last).replace('Z', ''))
                    if now - last_dt > threshold:
                        stale.append({
                            'entity_id': s.get('entity_id'),
                            'name': s.get('name'),
                            'last_seen': str(last),
                            'kind': kind,
                        })
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f'stale scan: {e}')

    return {'low_batteries': low[:10], 'stale_sensors': stale[:10]}


def run_maintenance_check(app):
    """Scheduler entry — runs daily at 09:00. Per-user iteration."""
    try:
        from home_assistant import ha_for
    except Exception as e:
        logger.debug(f'run_maintenance_check HA import: {e}')
        return {'error': 'ha import'}

    user_ids = _get_active_user_ids(app)
    if not user_ids:
        return {'checked': 0}

    pushed = 0
    total_low = 0
    total_stale = 0
    for uid in user_ids:
        # Per-user HA — each senior has their own sensors/batteries
        client = ha_for(uid)
        issues = _detect_maintenance_issues(client)
        total_low += len(issues['low_batteries'])
        total_stale += len(issues['stale_sensors'])
        if not issues['low_batteries'] and not issues['stale_sensors']:
            continue

        # Track per-device last nudge
        try:
            from memory_helpers import db_load_learning
            with app.app_context():
                learning = db_load_learning(uid) or {}
        except Exception:
            learning = {}

        nudges = learning.get('maintenance_nudges') or {}
        now_iso = datetime.utcnow().isoformat(timespec='seconds') + 'Z'
        bodies = []
        updated_nudges = dict(nudges)

        for b in issues['low_batteries']:
            key = 'low:' + (b.get('entity_id') or b.get('name') or 'x')
            last = nudges.get(key)
            should_nudge = True
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace('Z', ''))
                    if (datetime.utcnow() - last_dt).days < BATTERY_NUDGE_DAYS:
                        should_nudge = False
                except Exception:
                    pass
            if should_nudge:
                bodies.append(f"🔋 {b.get('name', '?')} má {b.get('value')} %")
                updated_nudges[key] = now_iso

        for s in issues['stale_sensors']:
            key = 'stale:' + (s.get('entity_id') or s.get('name') or 'x')
            last = nudges.get(key)
            should_nudge = True
            if last:
                try:
                    last_dt = datetime.fromisoformat(last.replace('Z', ''))
                    if (datetime.utcnow() - last_dt).days < BATTERY_NUDGE_DAYS:
                        should_nudge = False
                except Exception:
                    pass
            if should_nudge:
                bodies.append(f"📶 {s.get('name', '?')} se neozývá (> 48h)")
                updated_nudges[key] = now_iso

        if bodies:
            title = '🔧 Údržba domácnosti'
            body = 'Zkontrolujte: ' + '; '.join(bodies[:4])
            ok = _push_family(
                uid, title, body, severity='info',
                data={'low_count': len(issues['low_batteries']),
                      'stale_count': len(issues['stale_sensors'])}
            )
            if ok:
                pushed += 1
                # Persist nudge timestamps
                learning['maintenance_nudges'] = updated_nudges
                try:
                    from memory_helpers import db_save_learning
                    with app.app_context():
                        db_save_learning(uid, learning)
                except Exception:
                    pass

    logger.info(
        f"🔧 Maintenance check: users={len(user_ids)} "
        f"low_batt={total_low} stale={total_stale} pushed={pushed}"
    )
    return {
        'checked': len(user_ids),
        'low_batteries': total_low,
        'stale_sensors': total_stale,
        'pushed': pushed,
    }
