"""
Notes Sprint C smoke tests.
Run: pytest tests/test_notes.py -v
"""


class TestNotesAuth:
    """All endpoints require auth — unauthed returns 401/403."""

    def test_list_requires_auth(self, client):
        resp = client.get('/api/notes')
        assert resp.status_code in (401, 403)

    def test_create_requires_auth(self, client):
        resp = client.post('/api/notes', json={'text': 'Test'})
        assert resp.status_code in (401, 403)

    def test_get_one_requires_auth(self, client):
        resp = client.get('/api/notes/1')
        assert resp.status_code in (401, 403, 404)

    def test_update_requires_auth(self, client):
        resp = client.put('/api/notes/1', json={'text': 'x'})
        assert resp.status_code in (401, 403, 404)

    def test_delete_requires_auth(self, client):
        resp = client.delete('/api/notes/1')
        assert resp.status_code in (401, 403, 404)

    def test_share_requires_auth(self, client):
        resp = client.post('/api/notes/1/share')
        assert resp.status_code in (401, 403, 404)

    def test_to_event_requires_auth(self, client):
        resp = client.post('/api/notes/1/to-event', json={})
        assert resp.status_code in (401, 403, 404)

    def test_to_task_requires_auth(self, client):
        resp = client.post('/api/notes/1/to-task', json={})
        assert resp.status_code in (401, 403, 404)

    def test_family_view_requires_auth(self, client):
        resp = client.get('/api/notes/family/some-senior-id')
        assert resp.status_code in (401, 403)


class TestNotesSchema:
    def test_init_schema_idempotent(self):
        from notes_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_to_dict_tuple(self):
        """_row_to_dict handles tuple rows (SQLite)."""
        from notes_routes import _row_to_dict
        # (id, client_id, text, category, pinned, important,
        #  share_with_family, mood, created_at)
        r = (7, 'cli-abc', 'Nakoupit', 'shopping', True, False,
             False, None, '2026-04-21 10:00:00')
        d = _row_to_dict(r)
        assert d['id'] == 7
        assert d['clientId'] == 'cli-abc'
        assert d['text'] == 'Nakoupit'
        assert d['category'] == 'shopping'
        assert d['pinned'] is True
        assert d['important'] is False
        assert d['shareWithFamily'] is False
        assert d['mood'] is None

    def test_row_to_dict_dict(self):
        """_row_to_dict handles dict rows (PG DictRow)."""
        from notes_routes import _row_to_dict
        r = {
            'id': 42, 'client_id': None, 'text': 'Zítra k lékaři',
            'category': 'health', 'pinned': False, 'important': True,
            'share_with_family': True,
            'mood': None,
            'created_at': '2026-04-21',
        }
        d = _row_to_dict(r)
        assert d['id'] == 42
        assert d['category'] == 'health'
        assert d['important'] is True
        assert d['shareWithFamily'] is True

    def test_row_to_dict_mood_json_string(self):
        """_row_to_dict parses mood JSON string (SQLite TEXT column)."""
        from notes_routes import _row_to_dict
        r = (1, None, 't', 'personal', False, False, False,
             '{"emoji":"😊","score":8}', '2026-04-21')
        d = _row_to_dict(r)
        assert isinstance(d['mood'], dict)
        assert d['mood'].get('emoji') == '😊'
        assert d['mood'].get('score') == 8


class TestNotesValidation:
    """Contract validation on endpoints."""

    def test_create_missing_text(self, client):
        """POST without text is rejected (400 or 401 unauthed)."""
        resp = client.post('/api/notes', json={})
        assert resp.status_code in (400, 401, 403)

    def test_create_empty_text(self, client):
        resp = client.post('/api/notes', json={'text': '   '})
        assert resp.status_code in (400, 401, 403)

    def test_update_empty_body(self, client):
        """PUT with no updatable fields → 400 (or auth error)."""
        resp = client.put('/api/notes/999', json={})
        assert resp.status_code in (400, 401, 403, 404)

    def test_to_event_without_date_unauthed(self, client):
        """to-event without a note/date returns auth or 404/400."""
        resp = client.post('/api/notes/999/to-event', json={})
        assert resp.status_code in (400, 401, 403, 404)

    def test_to_event_invalid_date(self, client):
        """Invalid date format (if auth gets that far) → 400/401."""
        resp = client.post(
            '/api/notes/999/to-event',
            json={'date': 'zitra'},
        )
        assert resp.status_code in (400, 401, 403, 404)


class TestNotesBlueprint:
    def test_blueprint_imports(self):
        from notes_routes import notes_bp
        assert notes_bp is not None
        assert notes_bp.name == 'notes'

    def test_blueprint_registered_on_app(self, app):
        """Blueprint is registered on the Flask app."""
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/notes' in r for r in rules)
        # Key endpoints exist
        assert any(r.endswith('/api/notes') for r in rules)
        assert any('/api/notes/<int:note_id>' in r for r in rules)
        assert any('/share' in r and '/api/notes' in r for r in rules)
        assert any('/to-event' in r for r in rules)
        assert any('/to-task' in r for r in rules)
        assert any('/family/' in r and '/api/notes' in r for r in rules)


class TestNotesParserFallback:
    """to-event falls back to calendar parser when no date provided."""

    def test_calendar_parser_importable(self):
        """Parser fallback dependency is importable."""
        from calendar_routes import _parse_event_rule_based
        result = _parse_event_rule_based('zítra v 10 lékař')
        # Parser returns a dict
        assert isinstance(result, dict)


class TestNotesFamilyView:
    """family view endpoint checks senior_family_links."""

    def test_family_view_not_linked_returns_403(self, client):
        """Without linkage (and without auth too) endpoint refuses."""
        resp = client.get('/api/notes/family/nonexistent-senior')
        # Unauthed will fail first; if auth ever passes, 403 is expected.
        assert resp.status_code in (401, 403)
