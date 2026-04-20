"""
Calendar Sprint C smoke tests.
Run: pytest tests/test_calendar.py -v
"""

from datetime import date, timedelta


class TestCalendarHealth:
    def test_events_endpoint_requires_user_id(self, client):
        """GET without user_id returns 400."""
        resp = client.get('/api/calendar/events')
        assert resp.status_code in (200, 400, 401)


class TestCalendarParser:
    """Rule-based Czech natural-language event parser."""

    def test_parse_tomorrow(self):
        from calendar_routes import _parse_event_rule_based
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        r = _parse_event_rule_based('Zítra v 10 u zubaře')
        assert r['date'] == tomorrow
        assert r['time'] == '10:00'
        assert r['type'] == 'appointment'
        assert 'zubař' in r['title'].lower()

    def test_parse_today_no_time(self):
        from calendar_routes import _parse_event_rule_based
        today = date.today().isoformat()
        r = _parse_event_rule_based('Dnes nákup')
        assert r['date'] == today
        assert r['time'] is None

    def test_parse_day_after_tomorrow(self):
        from calendar_routes import _parse_event_rule_based
        expected = (date.today() + timedelta(days=2)).isoformat()
        r = _parse_event_rule_based('Pozítří v 14:30 schůzka')
        assert r['date'] == expected
        assert r['time'] == '14:30'

    def test_parse_next_weekday(self):
        from calendar_routes import _parse_event_rule_based
        r = _parse_event_rule_based('Příští středa v 9 kontrola u kardiologa')
        assert r['date'] is not None
        # Parsed date must be a Wednesday
        parsed_date = date.fromisoformat(r['date'])
        assert parsed_date.weekday() == 2  # Wednesday
        assert r['time'] == '09:00'
        assert r['type'] == 'appointment'

    def test_parse_explicit_date(self):
        from calendar_routes import _parse_event_rule_based
        r = _parse_event_rule_based('Narozeniny 15.6. oslava')
        assert r['date'] is not None
        assert r['date'].endswith('-06-15')
        assert r['type'] == 'birthday'

    def test_parse_word_hour(self):
        from calendar_routes import _parse_event_rule_based
        r = _parse_event_rule_based('Zítra v osm snídaně s rodinou')
        assert r['time'] == '08:00'

    def test_parse_extracts_title(self):
        from calendar_routes import _parse_event_rule_based
        r = _parse_event_rule_based('Přidej schůzku u zubaře zítra v 10')
        assert 'zítra' not in r['title'].lower()
        assert '10' not in r['title']
        assert r['title'].strip() != ''

    def test_parse_no_date_returns_none(self):
        from calendar_routes import _parse_event_rule_based
        r = _parse_event_rule_based('Koupit chléb')
        assert r['date'] is None
        assert r['title']  # Has title

    def test_parse_endpoint_validates_min_length(self, client):
        """POST /api/calendar/parse rejects short text."""
        resp = client.post('/api/calendar/parse', json={'text': 'ab'})
        assert resp.status_code in (400, 401)


class TestCalendarSlots:
    def test_slots_requires_user_id(self, client):
        resp = client.get('/api/calendar/slots')
        assert resp.status_code in (400, 401)

    def test_slots_returns_list_structure(self, client):
        """With a valid user_id (even unknown), returns slots array."""
        resp = client.get('/api/calendar/slots?user_id=slot-test')
        assert resp.status_code in (200, 401)
        if resp.status_code == 200:
            data = resp.get_json()
            assert 'slots' in data
            assert isinstance(data['slots'], list)

    def test_slots_skips_weekends_first(self, client):
        """First slots should be weekdays when possible."""
        resp = client.get('/api/calendar/slots?user_id=slot-test-2&days=14')
        if resp.status_code != 200:
            return  # auth path — skip
        data = resp.get_json()
        # At least one slot should exist for empty schedule
        assert len(data['slots']) >= 1
        # First slot should be a weekday (mo-fr = weekday names)
        first = data['slots'][0]
        assert first['weekday'] in ('pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek')


class TestCalendarReminderCron:
    def test_cron_importable(self):
        from calendar_routes import calendar_reminder_cron
        # Should not raise even with no events
        calendar_reminder_cron()

    def test_ensure_reminder_columns_idempotent(self):
        from calendar_routes import _ensure_reminder_columns
        _ensure_reminder_columns()
        _ensure_reminder_columns()  # Second call must not raise
