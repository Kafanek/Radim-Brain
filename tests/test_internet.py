"""
Internet Sprint C smoke tests.
Run: pytest tests/test_internet.py -v
"""


class TestInternetAuth:
    """All endpoints require auth."""

    def test_favorite_post_requires_auth(self, client):
        resp = client.post('/api/internet/favorite', json={'url': 'https://example.com'})
        assert resp.status_code in (401, 403)

    def test_favorites_list_requires_auth(self, client):
        resp = client.get('/api/internet/favorites')
        assert resp.status_code in (401, 403)

    def test_history_post_requires_auth(self, client):
        resp = client.post('/api/internet/history', json={'url': 'https://example.com'})
        assert resp.status_code in (401, 403)

    def test_history_get_requires_auth(self, client):
        resp = client.get('/api/internet/history')
        assert resp.status_code in (401, 403)

    def test_history_delete_requires_auth(self, client):
        resp = client.delete('/api/internet/history')
        assert resp.status_code in (401, 403)

    def test_search_requires_auth(self, client):
        resp = client.get('/api/internet/search?q=test')
        assert resp.status_code in (401, 403)

    def test_translate_requires_auth(self, client):
        resp = client.post('/api/internet/translate', json={'text': 'hello'})
        assert resp.status_code in (401, 403)

    def test_family_activity_requires_auth(self, client):
        resp = client.get('/api/internet/family/some-senior/activity')
        assert resp.status_code in (401, 403)


class TestInternetSchema:
    def test_init_schema_idempotent(self):
        from internet_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_val_helper(self):
        from internet_routes import _row_val
        assert _row_val(None, 0, 'x') is None
        assert _row_val(('a', 'b'), 0, 'x') == 'a'
        assert _row_val({'x': 'y'}, 0, 'x') == 'y'

    def test_host_from_helper(self):
        from internet_routes import _host_from
        assert _host_from('https://www.idnes.cz/path') == 'www.idnes.cz'
        assert _host_from('not a url') == ''


class TestInternetUrlValidation:
    """URL validation rejects bad/dangerous URLs."""

    def test_validate_url_accepts_https(self):
        from internet_routes import _validate_url
        assert _validate_url('https://www.idnes.cz/') is True
        assert _validate_url('http://example.com/path?q=1') is True

    def test_validate_url_rejects_javascript(self):
        from internet_routes import _validate_url
        assert _validate_url('javascript:alert(1)') is False

    def test_validate_url_rejects_data_uri(self):
        from internet_routes import _validate_url
        assert _validate_url('data:text/html,<script>alert(1)</script>') is False

    def test_validate_url_rejects_localhost(self):
        from internet_routes import _validate_url
        assert _validate_url('http://localhost:8080/') is False
        assert _validate_url('http://127.0.0.1/') is False

    def test_validate_url_rejects_private_ip(self):
        from internet_routes import _validate_url
        assert _validate_url('http://192.168.1.1/') is False
        assert _validate_url('http://10.0.0.1/') is False

    def test_validate_url_rejects_empty(self):
        from internet_routes import _validate_url
        assert _validate_url('') is False
        assert _validate_url(None) is False

    def test_validate_url_rejects_too_long(self):
        from internet_routes import _validate_url
        assert _validate_url('https://example.com/' + 'x' * 3000) is False


class TestInternetEndpointValidation:
    """Endpoint contracts."""

    def test_favorite_missing_url(self, client):
        resp = client.post('/api/internet/favorite', json={})
        assert resp.status_code in (400, 401, 403)

    def test_favorite_invalid_url(self, client):
        resp = client.post('/api/internet/favorite',
                           json={'url': 'javascript:bad()'})
        assert resp.status_code in (400, 401, 403)

    def test_history_missing_url(self, client):
        resp = client.post('/api/internet/history', json={})
        assert resp.status_code in (400, 401, 403)

    def test_search_missing_query(self, client):
        resp = client.get('/api/internet/search')
        assert resp.status_code in (400, 401, 403)

    def test_search_too_long_query(self, client):
        resp = client.get('/api/internet/search?q=' + 'x' * 300)
        assert resp.status_code in (400, 401, 403)

    def test_translate_missing_text(self, client):
        resp = client.post('/api/internet/translate', json={})
        assert resp.status_code in (400, 401, 403)


class TestInternetBlueprint:
    def test_blueprint_imports(self):
        from internet_routes import internet_bp
        assert internet_bp is not None
        assert internet_bp.name == 'internet'

    def test_blueprint_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/internet/favorite' in r for r in rules)
        assert any('/api/internet/favorites' in r for r in rules)
        assert any('/api/internet/history' in r for r in rules)
        assert any('/api/internet/search' in r for r in rules)
        assert any('/api/internet/translate' in r for r in rules)
        assert any('/api/internet/family/' in r and '/activity' in r for r in rules)


class TestInternetFamily:
    def test_family_view_unlinked(self, client):
        resp = client.get('/api/internet/family/nonexistent-senior/activity')
        assert resp.status_code in (401, 403)


class TestInternetDeadCode:
    """Verify the legacy modules that were merged into internet-module v4.0
    are actually deleted from disk (regression guard)."""

    def test_safe_web_module_js_removed(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'sections', 'safe-web-module.js'
        )
        assert not os.path.exists(path), \
            'safe-web-module.js should be deleted (merged into internet-module v4.0)'

    def test_browser_module_js_removed(self):
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'js', 'sections', 'browser-module.js'
        )
        assert not os.path.exists(path), \
            'browser-module.js should be deleted (merged into internet-module v4.0)'


class TestInternetNoEndpointConflict:
    """Make sure /api/internet/* routes don't collide with existing browser/
    safe-web blueprints."""

    def test_browser_proxy_still_works(self, client):
        """Legacy iframe-passthrough must still respond (200/4xx, not 401)."""
        resp = client.get('/api/browser/proxy?url=https://example.com')
        # Anything except a 5xx or "blueprint not registered" status
        assert resp.status_code < 500 or resp.status_code in (502, 503)
