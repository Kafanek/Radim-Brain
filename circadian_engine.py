"""
🕐 CIRCADIAN ENGINE v1.0
=========================
Detects senior's daily rhythm and behavioral changes over time.
Connects HA sensors + brain states + chat patterns into a unified timeline.

Architecture:
    1. Circadian Profile — personal wake/sleep/activity pattern per senior
    2. HA Sensor Timeline — motion, door, temperature by hour
    3. Proactive Scenario Triggers — HA events → Radim speaks
    4. Behavioral Change Detection — shift in routine → early warning
    5. Time-based Proactive Actions — right message at right time

Detects:
    - Wake time (first motion after 5:00)
    - Sleep time (last motion before 23:00)
    - Active periods (motion clusters)
    - Quiet periods (no motion gaps)
    - Door events (leaving/returning home)
    - Night restlessness (motion 23:00-05:00)
    - Routine shifts (waking 2h later than usual)
    - Activity decline (less motion day-over-day)
"""

import json
import logging
import math
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

try:
    from database import db_context, is_postgres
    from memory_helpers import db_load_learning, db_save_learning, db_load_profile
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# CIRCADIAN PROFILE — per-senior daily rhythm
# ═══════════════════════════════════════════════════════════════════

def compute_circadian_profile(user_id, days=14):
    """Build circadian profile from HA motion sensors + chat history.

    Returns:
        {
            usual_wake_hour: 7.5,       # avg wake time
            usual_sleep_hour: 22.0,     # avg sleep time
            active_hours: [8,9,10,14,15,16],  # high-activity hours
            quiet_hours: [12,13,20,21],       # low-activity hours
            avg_daily_motion: 45,       # avg motion events per day
            night_restlessness: 0.2,    # 0-1 (0=calm, 1=very restless)
            routine_stability: 0.85,    # 0-1 (1=very stable routine)
            chat_peak_hours: [9,10,15], # when senior chats most
            last_updated: "ISO"
        }
    """
    if not _AVAILABLE:
        return _default_profile()

    profile = {
        'usual_wake_hour': None,
        'usual_sleep_hour': None,
        'active_hours': [],
        'quiet_hours': [],
        'avg_daily_motion': 0,
        'night_restlessness': 0,
        'routine_stability': 0,
        'chat_peak_hours': [],
        'days_analyzed': 0,
        'last_updated': datetime.utcnow().isoformat(),
    }

    try:
        with db_context() as db:
            # Motion events by hour (last N days)
            if is_postgres():
                rows = db.execute(
                    "SELECT EXTRACT(HOUR FROM recorded_at) as hr, COUNT(*) as cnt, "
                    "DATE(recorded_at) as day "
                    "FROM iot_sensor_data WHERE sensor_type = 'motion' AND value > 0 "
                    "AND recorded_at > NOW() - INTERVAL '%s days' "
                    "GROUP BY hr, day ORDER BY hr" % days
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT CAST(strftime('%%H', recorded_at) AS INTEGER) as hr, COUNT(*) as cnt, "
                    "DATE(recorded_at) as day "
                    "FROM iot_sensor_data WHERE sensor_type = 'motion' AND value > 0 "
                    "AND recorded_at > datetime('now', '-%d days') "
                    "GROUP BY hr, day ORDER BY hr" % days
                ).fetchall()

            if not rows:
                return _default_profile()

            # Aggregate by hour
            hourly = {}  # hour → [counts per day]
            daily_totals = {}  # date → total motion
            wake_times = []
            sleep_times = []

            for r in rows:
                hr = int(r[0]) if isinstance(r, (list, tuple)) else int(r.get('hr', 0))
                cnt = int(r[1]) if isinstance(r, (list, tuple)) else int(r.get('cnt', 0))
                day = str(r[2]) if isinstance(r, (list, tuple)) else str(r.get('day', ''))

                hourly.setdefault(hr, []).append(cnt)
                daily_totals[day] = daily_totals.get(day, 0) + cnt

            # Wake time: earliest hour with motion (5:00-12:00)
            for hr in range(5, 13):
                if hr in hourly and len(hourly[hr]) > 0:
                    wake_times.append(hr)
                    break

            # Sleep time: latest hour with motion (20:00-02:00)
            for hr in reversed(range(20, 24)):
                if hr in hourly and len(hourly[hr]) > 0:
                    sleep_times.append(hr)
                    break

            # Active vs quiet hours
            avg_per_hour = {}
            for hr, counts in hourly.items():
                avg_per_hour[hr] = sum(counts) / len(counts)

            if avg_per_hour:
                threshold = sum(avg_per_hour.values()) / max(len(avg_per_hour), 1)
                profile['active_hours'] = sorted([h for h, avg in avg_per_hour.items() if avg > threshold])
                profile['quiet_hours'] = sorted([h for h, avg in avg_per_hour.items() if avg <= threshold * 0.3 and 6 <= h <= 22])

            # Night restlessness (23:00-05:00)
            night_counts = sum(sum(hourly.get(h, [])) for h in list(range(23, 24)) + list(range(0, 6)))
            total_counts = sum(sum(counts) for counts in hourly.values())
            profile['night_restlessness'] = round(min(1.0, night_counts / max(total_counts * 0.1, 1)), 2)

            # Averages
            if daily_totals:
                profile['avg_daily_motion'] = round(sum(daily_totals.values()) / len(daily_totals))
                profile['days_analyzed'] = len(daily_totals)

            if wake_times:
                profile['usual_wake_hour'] = round(sum(wake_times) / len(wake_times), 1)
            if sleep_times:
                profile['usual_sleep_hour'] = round(sum(sleep_times) / len(sleep_times), 1)

            # Routine stability: how consistent is daily motion count
            if len(daily_totals) >= 3:
                vals = list(daily_totals.values())
                avg = sum(vals) / len(vals)
                std = math.sqrt(sum((v - avg) ** 2 for v in vals) / len(vals))
                cv = std / max(avg, 1)  # coefficient of variation
                profile['routine_stability'] = round(max(0, 1 - cv), 2)

            # Chat peak hours
            if is_postgres():
                chat_rows = db.execute(
                    "SELECT EXTRACT(HOUR FROM created_at) as hr, COUNT(*) as cnt "
                    "FROM memory_history WHERE user_id = ? AND role = 'user' "
                    "AND created_at > NOW() - INTERVAL '%s days' GROUP BY hr ORDER BY cnt DESC LIMIT 5" % days,
                    (user_id,)
                ).fetchall()
            else:
                chat_rows = db.execute(
                    "SELECT CAST(strftime('%%H', created_at) AS INTEGER) as hr, COUNT(*) as cnt "
                    "FROM memory_history WHERE user_id = ? AND role = 'user' "
                    "AND created_at > datetime('now', '-%d days') GROUP BY hr ORDER BY cnt DESC LIMIT 5" % days,
                    (user_id,)
                ).fetchall()
            profile['chat_peak_hours'] = [int(r[0]) for r in chat_rows] if chat_rows else []

    except Exception as e:
        logger.debug(f"Circadian profile error: {e}")
        return _default_profile()

    # Save to learning
    try:
        learning = db_load_learning(user_id)
        learning['circadian_profile'] = profile
        db_save_learning(user_id, learning)
    except Exception:
        pass

    return profile


def _default_profile():
    return {
        'usual_wake_hour': 7.0,
        'usual_sleep_hour': 22.0,
        'active_hours': [8, 9, 10, 14, 15, 16],
        'quiet_hours': [12, 13, 20, 21],
        'avg_daily_motion': 0,
        'night_restlessness': 0,
        'routine_stability': 0.5,
        'chat_peak_hours': [],
        'days_analyzed': 0,
        'last_updated': datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# PROACTIVE SCENARIO TRIGGERS — HA → Radim speaks
# ═══════════════════════════════════════════════════════════════════

def check_proactive_triggers(user_id, app=None):
    """Check HA sensors for situations that need proactive Radim response.

    Called by agent_loop every 5 min.

    Returns: list of triggered scenarios with messages.
    """
    triggers = []
    now = datetime.utcnow()
    hour = now.hour

    try:
        from home_assistant import ha_for
        client = ha_for(user_id)
        if not client.connected:
            return triggers

        sensors = client.get_sensors_summary()
        learning = db_load_learning(user_id) if _AVAILABLE else {}
        circadian = learning.get('circadian_profile', _default_profile())
        last_triggers = learning.get('proactive_triggers', {})

        # ── 1. Night motion (23:00-05:00) — restlessness check ──
        if 23 <= hour or hour < 5:
            active_motion = sum(1 for m in sensors.get('motion', []) if m.get('state') == 'on')
            if active_motion > 0 and _cooldown_ok(last_triggers, 'night_motion', 60):
                triggers.append({
                    'type': 'night_motion',
                    'message': 'Zdá se, že nemůžete spát. Potřebujete něco? Zkuste si pustit relaxační hudbu nebo dýchací cvičení.',
                    'tts_mode': 'crisis',  # Slow, calm voice at night
                    'severity': 'low',
                    'action': 'suggest_meditation',
                })

        # ── 2. No motion in morning (usual wake + 2h) — oversleeping ──
        usual_wake = circadian.get('usual_wake_hour', 7)
        if usual_wake and hour >= usual_wake + 2 and hour < usual_wake + 4:
            motion_now = sum(1 for m in sensors.get('motion', []) if m.get('state') == 'on')
            if motion_now == 0 and _cooldown_ok(last_triggers, 'oversleep', 120):
                triggers.append({
                    'type': 'oversleep',
                    'message': 'Dobré ráno! Obvykle v tuto dobu už býváte vzhůru. Je vše v pořádku?',
                    'tts_mode': 'alert',
                    'severity': 'medium',
                    'action': 'check_wellbeing',
                })

        # ── 3. Door opened at unusual time (night) ──
        doors = sensors.get('door', [])
        door_open = any(d.get('state') == 'on' for d in doors)
        if door_open and (hour >= 23 or hour < 5) and _cooldown_ok(last_triggers, 'night_door', 30):
            triggers.append({
                'type': 'night_door',
                'message': 'Dveře jsou otevřené. Je pozdě — potřebujete něco? Jste v pořádku?',
                'tts_mode': 'alert',
                'severity': 'high',
                'action': 'notify_caregiver',
            })

        # ── 4. Temperature too low — hypothermia risk ──
        temps = sensors.get('temperature', [])
        for t in temps:
            if t.get('value', 20) < 16 and _cooldown_ok(last_triggers, 'cold', 120):
                triggers.append({
                    'type': 'cold_room',
                    'message': f'V místnosti {t.get("name", "")} je jen {t["value"]}°C. Zvýším topení. Přikryjte se dekou.',
                    'tts_mode': 'normal',
                    'severity': 'medium',
                    'action': 'ha_heat_up',
                })
                # Auto action: raise temperature
                try:
                    devices = client.get_devices_by_type('climate')
                    for clim in devices.get('climate', []):
                        client.set_temperature(clim['entity_id'], 22)
                except Exception:
                    pass

        # ── 5. No activity for 4+ hours during daytime ──
        if 8 <= hour <= 20:
            all_motion = sum(1 for m in sensors.get('motion', []) if m.get('state') == 'on')
            if all_motion == 0 and _cooldown_ok(last_triggers, 'no_activity_day', 240):
                triggers.append({
                    'type': 'no_activity_day',
                    'message': 'Už dlouho jsem nezaznamenal žádný pohyb. Jak se máte? Chcete si protáhnout?',
                    'tts_mode': 'normal',
                    'severity': 'medium',
                    'action': 'suggest_exercise',
                })

        # ── 6. Medication time (from profile) ──
        if _AVAILABLE:
            prof = db_load_profile(user_id)
            med_times = prof.get('medication_times', [])
            for mt in med_times:
                try:
                    med_hour = int(mt.get('hour', 0))
                    if hour == med_hour and _cooldown_ok(last_triggers, f'med_{med_hour}', 60):
                        meds = mt.get('medications', prof.get('medications', 'léky'))
                        triggers.append({
                            'type': 'medication_reminder',
                            'message': f'Je čas na léky: {meds}. Vzal/a jste si je?',
                            'tts_mode': 'normal',
                            'severity': 'low',
                            'action': 'medication_check',
                        })
                except Exception:
                    pass

        # ── 7. Chat engagement at peak time ──
        peak_hours = circadian.get('chat_peak_hours', [])
        if hour in peak_hours and _cooldown_ok(last_triggers, 'chat_engage', 360):
            triggers.append({
                'type': 'chat_engagement',
                'message': 'Jak se dnes máte? Chcete si popovídat, pustit hudbu, nebo zkusit kvíz?',
                'tts_mode': 'normal',
                'severity': 'positive',
                'action': 'engage',
            })

        # Save trigger timestamps
        if triggers and _AVAILABLE:
            for t in triggers:
                last_triggers[t['type']] = now.isoformat()
            learning['proactive_triggers'] = last_triggers
            db_save_learning(user_id, learning)

    except Exception as e:
        logger.debug(f"Proactive triggers error: {e}")

    return triggers


def _cooldown_ok(last_triggers, trigger_type, minutes):
    """Check if enough time passed since last trigger of this type."""
    last = last_triggers.get(trigger_type)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.utcnow() - last_dt).total_seconds() > minutes * 60
    except Exception:
        return True


# ═══════════════════════════════════════════════════════════════════
# BEHAVIORAL CHANGE DETECTION — routine shifts
# ═══════════════════════════════════════════════════════════════════

def detect_behavioral_changes(user_id):
    """Compare recent behavior (3 days) vs baseline (14 days).

    Detects:
        - Wake time shift (sleeping later/earlier)
        - Activity level change (less/more active)
        - Night restlessness change
        - Social engagement change
        - Routine stability change
    """
    if not _AVAILABLE:
        return {'changes': [], 'stability': 'unknown'}

    learning = db_load_learning(user_id)
    current = learning.get('circadian_profile', {})
    if not current or current.get('days_analyzed', 0) < 3:
        return {'changes': [], 'stability': 'insufficient_data'}

    # Compute fresh 3-day profile for comparison
    recent = compute_circadian_profile(user_id, days=3)
    baseline = current  # 14-day profile already stored

    changes = []

    # Wake time shift
    if baseline.get('usual_wake_hour') and recent.get('usual_wake_hour'):
        diff = recent['usual_wake_hour'] - baseline['usual_wake_hour']
        if abs(diff) >= 1.5:
            direction = 'later' if diff > 0 else 'earlier'
            changes.append({
                'type': 'wake_time_shift',
                'direction': direction,
                'magnitude': abs(diff),
                'message': f"Senior vstává o {abs(diff):.1f}h {'později' if direction == 'later' else 'dříve'} než obvykle",
                'severity': 'watch' if abs(diff) < 2.5 else 'warning',
            })

    # Activity level change
    if baseline.get('avg_daily_motion', 0) > 5 and recent.get('avg_daily_motion', 0) >= 0:
        ratio = recent['avg_daily_motion'] / max(baseline['avg_daily_motion'], 1)
        if ratio < 0.5:
            changes.append({
                'type': 'activity_decline',
                'ratio': ratio,
                'message': f"Denní aktivita klesla na {ratio*100:.0f}% oproti obvyklé",
                'severity': 'warning',
            })
        elif ratio > 1.5:
            changes.append({
                'type': 'activity_increase',
                'ratio': ratio,
                'message': f"Denní aktivita vzrostla na {ratio*100:.0f}% — pozitivní trend",
                'severity': 'positive',
            })

    # Night restlessness change
    if baseline.get('night_restlessness', 0) > 0:
        rest_diff = recent.get('night_restlessness', 0) - baseline['night_restlessness']
        if rest_diff > 0.3:
            changes.append({
                'type': 'night_restlessness_increase',
                'message': 'Zvýšený noční neklid oproti obvyklému',
                'severity': 'watch',
            })

    # Routine stability drop
    if baseline.get('routine_stability', 0) > 0.5:
        stab_diff = baseline['routine_stability'] - recent.get('routine_stability', 0)
        if stab_diff > 0.3:
            changes.append({
                'type': 'routine_disruption',
                'message': 'Denní rutina se stává méně pravidelnou',
                'severity': 'watch',
            })

    # Save changes
    try:
        learning['behavioral_changes'] = {
            'changes': changes,
            'detected_at': datetime.utcnow().isoformat(),
            'baseline_days': baseline.get('days_analyzed', 0),
            'recent_days': recent.get('days_analyzed', 0),
        }
        db_save_learning(user_id, learning)
    except Exception:
        pass

    return {
        'changes': changes,
        'stability': 'stable' if not changes else 'changing',
        'change_count': len(changes),
    }


# ═══════════════════════════════════════════════════════════════════
# EXECUTE PROACTIVE TRIGGERS — send to frontend
# ═══════════════════════════════════════════════════════════════════

def execute_proactive_trigger(trigger, user_id, app=None):
    """Send proactive trigger to senior's frontend via SocketIO + push."""
    message = trigger.get('message', '')
    tts_mode = trigger.get('tts_mode', 'normal')

    # SocketIO → frontend speaks it
    try:
        if app:
            socketio = app.extensions.get('socketio')
            if socketio:
                socketio.emit('agent_action', {
                    'speak': message,
                    'tts_mode': tts_mode,
                    'trigger_type': trigger.get('type'),
                    'action': trigger.get('action'),
                }, room=user_id)
    except Exception:
        pass

    # Push notification
    try:
        from push_helpers import send_push_to_user
        send_push_to_user(user_id, 'Radim', message[:100])
    except Exception:
        pass

    # Log
    try:
        from memory_helpers import audit_log
        audit_log(user_id, f"proactive_{trigger['type']}", 'circadian_engine', message[:100])
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# FLASK ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

circadian_bp = Blueprint('circadian_engine', __name__)


@circadian_bp.route('/api/circadian/profile/<user_id>', methods=['GET'])
def api_circadian_profile(user_id):
    """Get circadian rhythm profile for a senior."""
    days = int(request.args.get('days', 14))
    profile = compute_circadian_profile(user_id, days)
    return jsonify({'success': True, 'profile': profile})


@circadian_bp.route('/api/circadian/changes/<user_id>', methods=['GET'])
def api_behavioral_changes(user_id):
    """Detect behavioral changes vs baseline."""
    result = detect_behavioral_changes(user_id)
    return jsonify({'success': True, **result})


@circadian_bp.route('/api/circadian/triggers/<user_id>', methods=['GET'])
def api_proactive_triggers(user_id):
    """Check current proactive triggers (what Radim should say now)."""
    triggers = check_proactive_triggers(user_id)
    return jsonify({'success': True, 'triggers': triggers, 'count': len(triggers)})


logger.info("🕐 Circadian Engine v1.0 loaded — rhythm detection, proactive triggers, behavioral changes")
