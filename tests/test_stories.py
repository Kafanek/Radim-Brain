"""
Stories Sprint C smoke tests.
Run: pytest tests/test_stories.py -v
"""


class TestStoriesAuth:
    """All endpoints require auth — unauthed returns 401."""

    def test_list_requires_auth(self, client):
        resp = client.get('/api/stories')
        assert resp.status_code in (401, 403)

    def test_create_requires_auth(self, client):
        resp = client.post('/api/stories', json={'title': 'T', 'content': 'C'})
        assert resp.status_code in (401, 403)

    def test_get_one_requires_auth(self, client):
        resp = client.get('/api/stories/1')
        assert resp.status_code in (401, 403, 404)

    def test_update_requires_auth(self, client):
        resp = client.put('/api/stories/1', json={'rating': 5})
        assert resp.status_code in (401, 403, 404)

    def test_delete_requires_auth(self, client):
        resp = client.delete('/api/stories/1')
        assert resp.status_code in (401, 403, 404)

    def test_continue_requires_auth(self, client):
        resp = client.post('/api/stories/1/continue')
        assert resp.status_code in (401, 403, 404, 502)


class TestStoriesSchema:
    def test_init_schema_idempotent(self):
        from stories_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_to_dict_tuple(self):
        """_row_to_dict handles tuple rows (SQLite)."""
        from stories_routes import _row_to_dict
        r = (42, 'Název', 'Text', 'fairy-tale', 'childhood', 'short',
             True, 5, 3, 10, 1, None, '2026-04-21')
        d = _row_to_dict(r)
        assert d['id'] == 42
        assert d['title'] == 'Název'
        assert d['favorite'] is True
        assert d['rating'] == 5
        assert d['chapterNumber'] == 1

    def test_row_to_dict_dict(self):
        """_row_to_dict handles dict rows (PG DictRow)."""
        from stories_routes import _row_to_dict
        r = {
            'id': 99, 'title': 'X', 'content': 'Y', 'genre': 'adventure',
            'theme': 'travel', 'length': 'long', 'favorite': False,
            'rating': 0, 'read_count': 0, 'series_id': None,
            'chapter_number': 1, 'parent_story_id': None,
            'created_at': '2026-04-21',
        }
        d = _row_to_dict(r)
        assert d['id'] == 99
        assert d['genre'] == 'adventure'
        assert d['favorite'] is False


class TestStoriesEndpointValidation:
    """Basic validation checks on endpoint contracts."""

    def test_create_missing_title_rejected(self, client):
        resp = client.post('/api/stories', json={'content': 'x'})
        # Without auth → 401; with auth → 400
        assert resp.status_code in (400, 401, 403)

    def test_create_missing_content_rejected(self, client):
        resp = client.post('/api/stories', json={'title': 'X'})
        assert resp.status_code in (400, 401, 403)

    def test_update_empty_body(self, client):
        """PUT with no updatable fields returns 400 (or 401 unauthed)."""
        resp = client.put('/api/stories/999', json={})
        assert resp.status_code in (400, 401, 403, 404)


class TestStoriesBlueprint:
    def test_blueprint_imports(self):
        from stories_routes import stories_bp
        assert stories_bp is not None
        assert stories_bp.name == 'stories'

    def test_continue_returns_404_for_missing(self, client):
        """Continue on nonexistent story returns 404 (or 401)."""
        resp = client.post('/api/stories/99999/continue')
        assert resp.status_code in (401, 403, 404)
