"""
📅 Calendar Routes v1.0
========================
CRUD for calendar events stored in PostgreSQL.
Works alongside localStorage (frontend) as backend sync.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import logging
import json

from database import db_context, db_insert, is_postgres
from auth_middleware import optional_auth
from utils import now_iso

logger = logging.getLogger(__name__)

calendar_bp = Blueprint('calendar', __name__)


# ============================================================================
# ENDPOINTS
# ============================================================================

@calendar_bp.route('/api/calendar/events', methods=['GET'])
@optional_auth
def get_events():
    """Get calendar events for user within date range."""
    try:
        user_id = request.args.get('user_id', '')
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')

        if not user_id:
            return jsonify({'success': False, 'error': 'user_id required'}), 400

        with db_context() as db:
            if date_from and date_to:
                rows = db.execute(
                    "SELECT id, user_id, title, date, time, description, type, color, reminder, repeat_type, location FROM calendar_events WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date, time",
                    (user_id, date_from, date_to)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id, user_id, title, date, time, description, type, color, reminder, repeat_type, location FROM calendar_events WHERE user_id = ? ORDER BY date DESC, time LIMIT 100",
                    (user_id,)
                ).fetchall()

        events = []
        for r in rows:
            events.append({
                'id': r[0],
                'title': r[2],
                'date': r[3],
                'time': r[4] or '',
                'description': r[5] or '',
                'type': r[6] or 'event',
                'color': r[7] or '#5BA8A0',
                'reminder': bool(r[8]),
                'repeat': r[9] or 'none',
                'location': r[10] or '',
            })

        return jsonify({'success': True, 'events': events, 'count': len(events)})

    except Exception as e:
        logger.error(f"Calendar get events: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/api/calendar/events', methods=['POST'])
@optional_auth
def create_event():
    """Create a calendar event."""
    try:
        data = request.json or {}
        user_id = data.get('user_id', '')
        title = data.get('title', '').strip()

        if not user_id or not title:
            return jsonify({'success': False, 'error': 'user_id and title required'}), 400

        with db_context(commit=True) as db:
            event_id = db_insert(db, 'calendar_events',
                ['user_id', 'title', 'date', 'time', 'description', 'type', 'color', 'reminder', 'repeat_type', 'location'],
                [user_id, title,
                 data.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
                 data.get('time', ''),
                 data.get('description', ''),
                 data.get('type', 'event'),
                 data.get('color', '#5BA8A0'),
                 1 if data.get('reminder') else 0,
                 data.get('repeat', 'none'),
                 data.get('location', '')]
            )

        return jsonify({'success': True, 'id': event_id, 'message': 'Událost vytvořena'})

    except Exception as e:
        logger.error(f"Calendar create event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/api/calendar/events/<int:event_id>', methods=['PUT'])
@optional_auth
def update_event(event_id):
    """Update a calendar event."""
    try:
        data = request.json or {}

        fields = []
        values = []
        for key in ['title', 'date', 'time', 'description', 'type', 'color', 'location']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if 'reminder' in data:
            fields.append("reminder = ?")
            values.append(1 if data['reminder'] else 0)
        if 'repeat' in data:
            fields.append("repeat_type = ?")
            values.append(data['repeat'])

        if not fields:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        values.append(event_id)

        with db_context(commit=True) as db:
            db.execute(f"UPDATE calendar_events SET {', '.join(fields)} WHERE id = ?", values)

        return jsonify({'success': True, 'message': 'Událost aktualizována'})

    except Exception as e:
        logger.error(f"Calendar update event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/api/calendar/events/<int:event_id>', methods=['DELETE'])
@optional_auth
def delete_event(event_id):
    """Delete a calendar event."""
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))

        return jsonify({'success': True, 'message': 'Událost smazána'})

    except Exception as e:
        logger.error(f"Calendar delete event: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@calendar_bp.route('/api/calendar/today', methods=['GET'])
@optional_auth
def get_today():
    """Get today's events + nameday + upcoming."""
    try:
        user_id = request.args.get('user_id', '')
        today = datetime.utcnow().strftime('%Y-%m-%d')

        events = []
        if user_id:
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, title, time, type FROM calendar_events WHERE user_id = ? AND date = ? ORDER BY time",
                    (user_id, today)
                ).fetchall()
                for r in rows:
                    events.append({'id': r[0], 'title': r[1], 'time': r[2] or '', 'type': r[3] or 'event'})

        # Upcoming 7 days
        upcoming = []
        if user_id:
            week_later = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d')
            with db_context() as db:
                rows = db.execute(
                    "SELECT id, title, date, time, type FROM calendar_events WHERE user_id = ? AND date > ? AND date <= ? ORDER BY date, time LIMIT 10",
                    (user_id, today, week_later)
                ).fetchall()
                for r in rows:
                    upcoming.append({'id': r[0], 'title': r[1], 'date': r[2], 'time': r[3] or '', 'type': r[4] or 'event'})

        return jsonify({
            'success': True,
            'today': today,
            'events': events,
            'upcoming': upcoming,
            'event_count': len(events),
        })

    except Exception as e:
        logger.error(f"Calendar today: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# SPRINT C — Gemini voice-add + slot finder + reminder cron
# ═══════════════════════════════════════════════════════════════════════════

import os
import re
from datetime import date as _date
from ai_config import GEMINI_MODEL


def _ensure_reminder_columns():
    """Add reminder_24h_sent + reminder_1h_sent columns if missing (idempotent)."""
    try:
        with db_context(commit=True) as db:
            # Try best-effort ALTER; works on PG 9.6+ (IF NOT EXISTS) and SQLite
            # (which ignores the IF NOT EXISTS and raises if column exists → caught).
            try:
                db.execute(
                    "ALTER TABLE calendar_events ADD COLUMN reminder_24h_sent BOOLEAN DEFAULT FALSE"
                )
            except Exception:
                pass
            try:
                db.execute(
                    "ALTER TABLE calendar_events ADD COLUMN reminder_1h_sent BOOLEAN DEFAULT FALSE"
                )
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"ensure reminder cols: {e}")


@calendar_bp.route('/api/calendar/parse', methods=['POST'])
@optional_auth
def calendar_parse():
    """Parse Czech natural-language event text into structured form.

    Body: { text: string }
    Returns: { parsed: {title, date, time, type, description}, source }
    Uses Gemini 2.0 Flash when GEMINI_API_KEY is set, falls back to rule-based.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if len(text) < 3:
        return jsonify({'success': False, 'error': 'text too short'}), 400
    if len(text) > 500:
        text = text[:500]

    parsed = _parse_event_rule_based(text)

    api_key = os.environ.get('GEMINI_API_KEY')
    if api_key:
        gemini_parsed = _parse_event_gemini(text, api_key)
        if gemini_parsed:
            for k in ('title', 'date', 'time', 'type', 'description'):
                if gemini_parsed.get(k):
                    parsed[k] = gemini_parsed[k]
            parsed['source'] = 'gemini'
        else:
            parsed['source'] = 'rule_based_gemini_failed'
    else:
        parsed['source'] = 'rule_based'

    return jsonify({'success': True, 'parsed': parsed})


def _parse_event_rule_based(text):
    """Deterministic Czech parser — handles common time/date phrasings."""
    t = text.lower()
    today = _date.today()

    # Date
    event_date = None
    if re.search(r'\bdnes\b', t):
        event_date = today
    elif re.search(r'\bzítra\b|\bzitra\b', t):
        event_date = today + timedelta(days=1)
    elif re.search(r'\bpozítří\b|\bpozitri\b', t):
        event_date = today + timedelta(days=2)
    else:
        weekdays = {
            'pondělí': 0, 'pondeli': 0, 'pondělk': 0,
            'úterý': 1, 'utery': 1, 'úterek': 1,
            'středa': 2, 'streda': 2, 'středu': 2, 'stredu': 2,
            'čtvrtek': 3, 'ctvrtek': 3,
            'pátek': 4, 'patek': 4,
            'sobota': 5, 'sobotu': 5,
            'neděle': 6, 'nedele': 6, 'neděli': 6, 'nedeli': 6,
        }
        is_next = 'příští' in t or 'pristi' in t
        matched_day = None
        for name, idx in weekdays.items():
            if name in t:
                matched_day = idx
                break
        if matched_day is not None:
            current_dow = today.weekday()
            delta = (matched_day - current_dow) % 7
            if delta == 0:
                delta = 7
            if is_next and delta < 7:
                delta += 7
            event_date = today + timedelta(days=delta)
        else:
            m = re.search(r'(?<!\d)(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{2,4}))?', text)
            if m:
                d = int(m.group(1))
                mo = int(m.group(2))
                y = int(m.group(3)) if m.group(3) else today.year
                if y < 100:
                    y += 2000
                try:
                    event_date = _date(y, mo, d)
                except ValueError:
                    pass

    # Time
    event_time = None
    m = re.search(r'\bv(?:e|ů)?\s*(\d{1,2})(?::(\d{2}))?\b', t)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2)) if m.group(2) else 0
        if 0 <= h < 24 and 0 <= mm < 60:
            event_time = f"{h:02d}:{mm:02d}"

    if not event_time:
        word_hours = {
            'deset': 10, 'jedenáct': 11, 'dvanáct': 12,
            'osm': 8, 'devět': 9, 'sedm': 7,
        }
        for word, hr in word_hours.items():
            if re.search(r'\bv\s*' + word + r'\b', t):
                event_time = f"{hr:02d}:00"
                break

    # Type
    event_type = 'event'
    if re.search(r'\blékař|doktor|zubař|kardiolog|oční|rehabilitac|fyzio|rentgen|kontrol\w*\s+u', t):
        event_type = 'appointment'
    elif re.search(r'\bnarozenin|oslav', t):
        event_type = 'birthday'
    elif re.search(r'\bnezapomenout|připomeň|pripomen', t):
        event_type = 'reminder'

    # Title — strip date/time words
    title = text
    strip_patterns = [
        r'\bdnes\b', r'\bzítra\b', r'\bzitra\b', r'\bpozítří\b', r'\bpozitri\b',
        r'\bpříští\s+\S+', r'\bpristi\s+\S+',
        r'\bv\w?\s*\d{1,2}(?::\d{2})?\b',
        r'\b(pondělí|pondeli|pondělk\w*|úterý|utery|středa\w*|streda\w*|čtvrtek|ctvrtek|pátek|patek|sobota\w*|neděle\w*|nedele\w*)\b',
        r'\b\d{1,2}\.\s*\d{1,2}\.(\d{2,4})?\b',
        r'\bv\s+(deset|jedenáct|dvanáct|osm|devět|sedm)\b',
        r'\bpřidej\b|\bnaplánuj\b|\bnaplanuj\b|\bobjednej\b|\bvytvoř\b|\bzapiš\b|\bzapis\b',
    ]
    for p in strip_patterns:
        title = re.sub(p, '', title, flags=re.IGNORECASE)
    title = re.sub(r'\b(mi|ve|do|na|k|s)\s*$', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'\s+', ' ', title).strip(' ,.;:-')
    if not title:
        title = 'Nová událost'

    return {
        'title': title[:200],
        'date': event_date.isoformat() if event_date else None,
        'time': event_time,
        'type': event_type,
        'description': '',
    }


def _parse_event_gemini(text, api_key):
    """Gemini refinement — returns dict or None."""
    today_iso = _date.today().isoformat()
    tomorrow_iso = (_date.today() + timedelta(days=1)).isoformat()
    prompt = (
        f"Dnes je {today_iso}. Z následujícího textu v češtině extrahuj informace o "
        "události do kalendáře. Vrať POUZE JSON (žádný další text):\n"
        '{"title": "stručný název", "date": "YYYY-MM-DD nebo null", '
        '"time": "HH:MM nebo null", "type": "event|appointment|birthday|reminder", '
        '"description": ""}\n\n'
        "Pravidla:\n"
        "- lékař/doktor/zubař/kontrola u X => type=appointment\n"
        "- narozeniny/oslava => type=birthday\n"
        "- připomeň => type=reminder\n"
        f"- zítra = {tomorrow_iso}\n"
        "- Pokud datum nejasné, vrať null\n\n"
        f"TEXT: {text}"
    )
    try:
        import requests as req
        resp = req.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}',
            json={
                'contents': [{'parts': [{'text': prompt}]}],
                'generationConfig': {
                    'temperature': 0.1,
                    'maxOutputTokens': 250,
                    'response_mime_type': 'application/json',
                },
            },
            timeout=10,
        )
        if not resp.ok:
            return None
        data = resp.json()
        raw = (data.get('candidates', [{}])[0].get('content', {})
                    .get('parts', [{}])[0].get('text', '')).strip()
        parsed = json.loads(raw)
        if parsed.get('date'):
            try:
                datetime.strptime(parsed['date'], '%Y-%m-%d')
            except ValueError:
                parsed['date'] = None
        return parsed
    except Exception as e:
        logger.debug(f"gemini parse error: {e}")
        return None


@calendar_bp.route('/api/calendar/slots', methods=['GET'])
@optional_auth
def find_slots():
    """Find up to 3 free slots in the coming days.

    Query: ?user_id=X&days=7&duration=30&start_hour=8&end_hour=18
    Weekdays preferred; weekends only if no weekday slot fits.
    """
    user_id = request.args.get('user_id', '')
    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    days = max(1, min(int(request.args.get('days', 7)), 30))
    start_hour = max(0, min(int(request.args.get('start_hour', 8)), 23))
    end_hour = max(start_hour + 1, min(int(request.args.get('end_hour', 18)), 23))

    today = _date.today()
    until = today + timedelta(days=days)

    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT date, time FROM calendar_events "
                "WHERE user_id = ? AND date >= ? AND date <= ? "
                "AND time IS NOT NULL AND time != ''",
                (user_id, today.isoformat(), until.isoformat())
            ).fetchall()
    except Exception:
        rows = []

    busy = {}
    for r in rows or []:
        d_val = r[0] if isinstance(r, (list, tuple)) else r.get('date')
        t_val = r[1] if isinstance(r, (list, tuple)) else r.get('time')
        d_str = str(d_val)[:10]
        try:
            h = int(str(t_val).split(':')[0])
            busy.setdefault(d_str, set()).add(h)
        except (ValueError, IndexError):
            pass

    weekday_names = ['pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota', 'neděle']
    slots = []

    def _add_slot(d, hour):
        slots.append({
            'date': d.isoformat(),
            'time': f"{hour:02d}:00",
            'weekday': weekday_names[d.weekday()],
            'label': f"{weekday_names[d.weekday()]} {d.day}. {d.month}. v {hour:02d}:00",
        })

    # Weekdays first
    for i in range(days):
        if len(slots) >= 3:
            break
        d = today + timedelta(days=i + 1)
        if d.weekday() >= 5:
            continue
        day_busy = busy.get(d.isoformat(), set())
        for hour in range(start_hour, end_hour):
            if hour not in day_busy:
                _add_slot(d, hour)
                break  # one slot per day is enough

    # Fall back to weekends
    if len(slots) < 3:
        for i in range(days):
            if len(slots) >= 3:
                break
            d = today + timedelta(days=i + 1)
            if d.weekday() < 5:
                continue
            day_busy = busy.get(d.isoformat(), set())
            for hour in range(start_hour, end_hour):
                if hour not in day_busy:
                    _add_slot(d, hour)
                    break

    return jsonify({'success': True, 'slots': slots})


def calendar_reminder_cron():
    """Runs every 10 min. Push 24h and 1h before events with time set.

    Reuses notification_helpers.notify() — respects user DND/mute per Sprint C.
    Idempotent via reminder_24h_sent / reminder_1h_sent columns.
    """
    _ensure_reminder_columns()
    try:
        from notification_helpers import notify as _notify
    except Exception:
        return

    now = datetime.utcnow()
    t_24_lo = now + timedelta(hours=23, minutes=55)
    t_24_hi = now + timedelta(hours=24, minutes=5)
    t_1_lo = now + timedelta(minutes=55)
    t_1_hi = now + timedelta(minutes=65)

    try:
        with db_context(commit=True) as db:
            cutoff = now + timedelta(hours=25)
            rows = db.execute(
                "SELECT id, user_id, title, date, time, location, "
                "reminder_24h_sent, reminder_1h_sent "
                "FROM calendar_events "
                "WHERE time IS NOT NULL AND time != '' "
                "AND date >= ? AND date <= ?",
                (now.date().isoformat(), cutoff.date().isoformat())
            ).fetchall()

            def _v(r, i, k): return r[i] if isinstance(r, (list, tuple)) else r.get(k)
            for r in rows or []:
                eid = _v(r, 0, 'id')
                uid = _v(r, 1, 'user_id')
                title = _v(r, 2, 'title') or 'Událost'
                e_date = str(_v(r, 3, 'date') or '')[:10]
                e_time = _v(r, 4, 'time') or '00:00'
                location = _v(r, 5, 'location') or ''
                sent_24 = bool(_v(r, 6, 'reminder_24h_sent'))
                sent_1 = bool(_v(r, 7, 'reminder_1h_sent'))

                try:
                    event_dt = datetime.strptime(f"{e_date} {e_time[:5]}", '%Y-%m-%d %H:%M')
                except Exception:
                    continue

                if not sent_24 and t_24_lo <= event_dt <= t_24_hi:
                    loc_part = f" · {location}" if location else ''
                    _notify(to_user_id=uid, type='reminder',
                            title=f"📅 Zítra: {title[:60]}",
                            body=f"{e_time[:5]}{loc_part}",
                            severity='info',
                            data={'event_id': eid, 'calendar_reminder': True})
                    db.execute(
                        "UPDATE calendar_events SET reminder_24h_sent = 1 WHERE id = ?"
                        if not is_postgres() else
                        "UPDATE calendar_events SET reminder_24h_sent = TRUE WHERE id = ?",
                        (eid,)
                    )
                if not sent_1 and t_1_lo <= event_dt <= t_1_hi:
                    loc_part = f" · {location}" if location else ''
                    _notify(to_user_id=uid, type='reminder',
                            title=f"⏰ Za hodinu: {title[:60]}",
                            body=f"{e_time[:5]}{loc_part}",
                            severity='warning',
                            data={'event_id': eid, 'calendar_reminder': True})
                    db.execute(
                        "UPDATE calendar_events SET reminder_1h_sent = 1 WHERE id = ?"
                        if not is_postgres() else
                        "UPDATE calendar_events SET reminder_1h_sent = TRUE WHERE id = ?",
                        (eid,)
                    )
    except Exception as e:
        logger.debug(f"calendar_reminder_cron error: {e}")


logger.info("📅 Calendar routes v1.1 loaded — CRUD + parse (Gemini) + slots + reminder cron")
