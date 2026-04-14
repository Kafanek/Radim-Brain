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
                db.execute(
                    "SELECT * FROM calendar_events WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date, time",
                    (user_id, date_from, date_to)
                )
            else:
                db.execute(
                    "SELECT * FROM calendar_events WHERE user_id = ? ORDER BY date DESC, time LIMIT 100",
                    (user_id,)
                )
            rows = db.fetchall()

        events = []
        for r in rows:
            events.append({
                'id': r['id'],
                'title': r['title'],
                'date': r['date'],
                'time': r['time'] or '',
                'description': r['description'] or '',
                'type': r['type'] or 'event',
                'color': r['color'] or '#5BA8A0',
                'reminder': bool(r['reminder']),
                'repeat': r['repeat_type'] or 'none',
                'location': r['location'] or '',
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
                db.execute(
                    "SELECT * FROM calendar_events WHERE user_id = ? AND date = ? ORDER BY time",
                    (user_id, today)
                )
                rows = db.fetchall()
                for r in rows:
                    events.append({
                        'id': r['id'], 'title': r['title'],
                        'time': r['time'] or '', 'type': r['type'] or 'event'
                    })

        # Upcoming 7 days
        upcoming = []
        if user_id:
            week_later = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d')
            with db_context() as db:
                db.execute(
                    "SELECT * FROM calendar_events WHERE user_id = ? AND date > ? AND date <= ? ORDER BY date, time LIMIT 10",
                    (user_id, today, week_later)
                )
                for r in db.fetchall():
                    upcoming.append({
                        'id': r['id'], 'title': r['title'],
                        'date': r['date'], 'time': r['time'] or '', 'type': r['type'] or 'event'
                    })

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


logger.info("📅 Calendar routes v1.0 loaded")
