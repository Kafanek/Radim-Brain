"""
Help module smoke tests (Sprint B backend).
Run: pytest tests/test_help.py -v
"""


class TestHelpFeedback:
    """POST /api/help/feedback — submit support request."""

    def test_feedback_happy_path(self, client):
        """Submits feedback, returns success."""
        resp = client.post(
            '/api/help/feedback',
            json={
                'email': 'senior@test.cz',
                'message': 'Nemohu se přihlásit do aplikace, prosím o pomoc.',
                'user_id': 'test-senior-help',
                'user_agent': 'Test/1.0',
            }
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_feedback_too_short(self, client):
        """Messages under 3 chars rejected with 400."""
        resp = client.post(
            '/api/help/feedback',
            json={'message': 'ab'}
        )
        assert resp.status_code == 400

    def test_feedback_missing_message(self, client):
        """Empty message rejected."""
        resp = client.post('/api/help/feedback', json={})
        assert resp.status_code == 400

    def test_feedback_truncates_long_message(self, client):
        """Very long messages accepted (backend truncates at 2000 chars)."""
        huge = 'x' * 5000
        resp = client.post(
            '/api/help/feedback',
            json={'message': huge}
        )
        assert resp.status_code == 200

    def test_feedback_anonymous(self, client):
        """Anonymous user (no user_id, no email) can still submit."""
        resp = client.post(
            '/api/help/feedback',
            json={'message': 'Jak se přihlásím? Nevím co dělat.'}
        )
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True


class TestHelpStats:
    def test_count_endpoint(self, client):
        """Open count endpoint returns int."""
        resp = client.get('/api/help/feedback/count')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'open_count' in data
        assert isinstance(data['open_count'], int)

    def test_count_increases_after_submit(self, client):
        """New feedback increments open_count."""
        # Baseline
        baseline = client.get('/api/help/feedback/count').get_json()['open_count']

        # Submit one
        client.post('/api/help/feedback',
                    json={'message': 'Testovací zpráva pro count test'})

        after = client.get('/api/help/feedback/count').get_json()['open_count']
        assert after >= baseline + 1


class TestHelpSchema:
    """Verify schema initializes correctly on SQLite."""

    def test_table_created(self, client):
        """After first request, help_feedback table exists."""
        client.get('/api/help/feedback/count')
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='help_feedback'"
            ).fetchone()
            assert row is not None

    def test_init_helper_safe_to_call_twice(self):
        """_init_help_schema is idempotent."""
        from help_routes import _init_help_schema
        _init_help_schema()
        _init_help_schema()  # CREATE IF NOT EXISTS — must not error


class TestHelpSprintC:
    """Sprint C — Gemini ask + analytics."""

    def test_ask_requires_min_length(self, client):
        """Queries under 3 chars rejected."""
        resp = client.post('/api/help/ask', json={'query': 'ab'})
        assert resp.status_code == 400

    def test_ask_returns_fallback_without_gemini_key(self, client):
        """Without GEMINI_API_KEY, returns graceful fallback answer."""
        # In test env no API key is set
        resp = client.post('/api/help/ask', json={'query': 'Jak zvětšit písmo?'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data.get('answer')
        assert data.get('source') in ('fallback', 'gemini', 'fallback_error')

    def test_ask_truncates_long_query(self, client):
        """Very long queries accepted (truncated)."""
        resp = client.post('/api/help/ask', json={'query': 'x' * 5000})
        assert resp.status_code == 200

    def test_view_tracks_section(self, client):
        """Analytics view endpoint accepts section event."""
        resp = client.post('/api/help/view',
                           json={'event_type': 'section', 'section': 'faq',
                                 'user_id': 'analytics-test'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True

    def test_view_tracks_search_with_count(self, client):
        """Analytics view endpoint accepts search event with result_count."""
        resp = client.post('/api/help/view',
                           json={'event_type': 'search', 'query': 'kalendář',
                                 'result_count': 3, 'user_id': 'analytics-test'})
        assert resp.status_code == 200

    def test_view_rejects_invalid_event_type(self, client):
        """Unknown event_type returns 400."""
        resp = client.post('/api/help/view',
                           json={'event_type': 'rogue_event'})
        assert resp.status_code == 400

    def test_analytics_summary_returns_structure(self, client):
        """Summary endpoint returns expected keys."""
        # Seed at least one event
        client.post('/api/help/view',
                    json={'event_type': 'search', 'query': 'unknown_topic_xyz',
                          'result_count': 0})
        resp = client.get('/api/help/analytics/summary')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'zero_result_searches' in data
        assert 'top_sections' in data
        assert isinstance(data['zero_result_searches'], list)
