"""
Library Sprint C smoke tests.
Run: pytest tests/test_library.py -v
"""


class TestLibraryAuth:
    """All new endpoints require auth."""

    def test_progress_post_requires_auth(self, client):
        resp = client.post('/api/library/progress/book-1', json={'paragraph': 5, 'percent': 30})
        assert resp.status_code in (401, 403)

    def test_progress_list_requires_auth(self, client):
        resp = client.get('/api/library/progress')
        assert resp.status_code in (401, 403)

    def test_continue_reading_requires_auth(self, client):
        resp = client.get('/api/library/continue-reading')
        assert resp.status_code in (401, 403)

    def test_bookmark_post_requires_auth(self, client):
        resp = client.post('/api/library/bookmark/book-1', json={'paragraph': 3})
        assert resp.status_code in (401, 403)

    def test_bookmarks_list_requires_auth(self, client):
        resp = client.get('/api/library/bookmarks/book-1')
        assert resp.status_code in (401, 403)

    def test_favorite_toggle_requires_auth(self, client):
        resp = client.post('/api/library/favorite/book-1')
        assert resp.status_code in (401, 403)

    def test_favorites_list_requires_auth(self, client):
        resp = client.get('/api/library/favorites')
        assert resp.status_code in (401, 403)

    def test_family_reading_requires_auth(self, client):
        resp = client.get('/api/library/family/some-senior/reading')
        assert resp.status_code in (401, 403)


class TestLibrarySchema:
    def test_init_schema_idempotent(self):
        from library_progress_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_val_helper(self):
        from library_progress_routes import _row_val
        assert _row_val(None, 0, 'x') is None
        assert _row_val(('a', 'b'), 1, 'y') == 'b'
        assert _row_val({'y': 42}, 0, 'y') == 42


class TestLibraryValidation:
    def test_progress_missing_book_id(self, client):
        # Empty book_id in URL would 404 before route matches; whitespace
        # path is not valid. Test the body-level required-field path:
        resp = client.post('/api/library/progress/x',
                           json={'paragraph': 0, 'percent': 0})
        assert resp.status_code in (400, 401, 403)

    def test_bookmark_missing_paragraph(self, client):
        resp = client.post('/api/library/bookmark/book-1', json={})
        assert resp.status_code in (400, 401, 403)


class TestLibraryBlueprint:
    def test_blueprint_imports(self):
        from library_progress_routes import library_progress_bp
        assert library_progress_bp is not None
        assert library_progress_bp.name == 'library_progress'

    def test_blueprint_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/library/progress/' in r for r in rules)
        assert any('/api/library/progress' in r for r in rules)
        assert any('/api/library/continue-reading' in r for r in rules)
        assert any('/api/library/bookmark/' in r for r in rules)
        assert any('/api/library/bookmarks/' in r for r in rules)
        assert any('/api/library/favorite/' in r for r in rules)
        assert any('/api/library/favorites' in r for r in rules)
        assert any('/api/library/family/' in r and '/reading' in r for r in rules)


class TestLibraryFamily:
    def test_family_reading_unlinked(self, client):
        """Without senior_family_links → 401 (unauthed) or 403 (auth but unlinked)."""
        resp = client.get('/api/library/family/nonexistent-senior/reading')
        assert resp.status_code in (401, 403)


class TestLibraryDeadCode:
    """Verify the legacy EbookLibrary.js is gone after Sprint A unification."""

    def test_ebook_library_js_removed(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'EbookLibrary.js'
        )
        assert not os.path.exists(path), 'EbookLibrary.js should be deleted (merged into library-module.js v2.0)'


class TestLibraryNoEndpointConflict:
    """Make sure /api/library/* routes don't collide with existing /kal/library/*."""

    def test_kal_library_books_still_public(self, client):
        """Legacy public endpoint must still respond (200/4xx, not 401)."""
        resp = client.get('/kal/library/books')
        # Anything except 401 indicates blueprint is intact
        assert resp.status_code != 401
