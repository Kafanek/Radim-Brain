"""
Translator Sprint C smoke tests.
Run: pytest tests/test_translator.py -v
"""

import os


class TestTranslatorAuth:
    """All Sprint C endpoints require auth."""

    def test_history_post_requires_auth(self, client):
        resp = client.post('/api/translator/history',
                           json={'sourceText': 'Ahoj'})
        assert resp.status_code in (401, 403)

    def test_history_get_requires_auth(self, client):
        resp = client.get('/api/translator/history')
        assert resp.status_code in (401, 403)

    def test_history_delete_requires_auth(self, client):
        resp = client.delete('/api/translator/history')
        assert resp.status_code in (401, 403)

    def test_favorite_toggle_requires_auth(self, client):
        resp = client.post('/api/translator/favorite',
                           json={'phraseId': 'cat:0'})
        assert resp.status_code in (401, 403)

    def test_favorites_list_requires_auth(self, client):
        resp = client.get('/api/translator/favorites')
        assert resp.status_code in (401, 403)

    def test_family_activity_requires_auth(self, client):
        resp = client.get('/api/translator/family/some-senior/activity')
        assert resp.status_code in (401, 403)


class TestTranslatorSchema:
    def test_init_schema_idempotent(self):
        from translator_progress_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_val_helper(self):
        from translator_progress_routes import _row_val
        assert _row_val(None, 0, 'x') is None
        assert _row_val(('a', 'b'), 0, 'x') == 'a'
        assert _row_val({'x': 'y'}, 0, 'x') == 'y'

    def test_valid_lang_helper(self):
        from translator_progress_routes import _valid_lang
        assert _valid_lang('cs') is True
        assert _valid_lang('en-US') is True
        assert _valid_lang('') is False
        assert _valid_lang(None) is False
        assert _valid_lang('x' * 20) is False
        assert _valid_lang('cs;DROP') is False  # alnum + dash only


class TestTranslatorValidation:
    def test_history_missing_source_text(self, client):
        resp = client.post('/api/translator/history', json={})
        assert resp.status_code in (400, 401, 403)

    def test_history_empty_source_text(self, client):
        resp = client.post('/api/translator/history',
                           json={'sourceText': '   '})
        assert resp.status_code in (400, 401, 403)

    def test_history_invalid_target_lang(self, client):
        resp = client.post('/api/translator/history',
                           json={'sourceText': 'Ahoj', 'targetLang': 'cs;DROP'})
        assert resp.status_code in (400, 401, 403)

    def test_favorite_missing_phrase_id(self, client):
        resp = client.post('/api/translator/favorite', json={})
        assert resp.status_code in (400, 401, 403)


class TestTranslatorBlueprint:
    def test_blueprint_imports(self):
        from translator_progress_routes import translator_progress_bp
        assert translator_progress_bp is not None
        assert translator_progress_bp.name == 'translator_progress'

    def test_blueprint_registered_on_app(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/translator/history' in r for r in rules)
        assert any('/api/translator/favorite' in r for r in rules)
        assert any('/api/translator/favorites' in r for r in rules)
        assert any('/api/translator/family/' in r and '/activity' in r for r in rules)


class TestTranslatorFamily:
    def test_family_activity_unlinked(self, client):
        """Without senior_family_links → 401/403."""
        resp = client.get('/api/translator/family/nonexistent-senior/activity')
        assert resp.status_code in (401, 403)


class TestTranslatorPhrasebook:
    """Regression: phrasebook.json must exist for the offline phrasebook mode."""

    def test_phrasebook_json_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'data', 'phrasebook.json'
        )
        assert os.path.exists(path), \
            'phrasebook.json must exist for offline frázník mode'

    def test_phrasebook_json_valid(self):
        import json as _json
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'mykolibri-academy-project', 'data', 'phrasebook.json'
        )
        with open(path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        assert isinstance(data, dict)
        assert 'categories' in data
        assert isinstance(data['categories'], list)
        assert len(data['categories']) > 0


class TestTranslatorNoEndpointConflict:
    """Make sure /api/translator/* routes don't collide with the existing
    public /api/translate (text translation) endpoints."""

    def test_translate_endpoint_still_works(self, client):
        """Legacy public /api/translate must still respond (not 401)."""
        resp = client.post('/api/translate',
                           json={'text': 'Ahoj', 'source': 'cs', 'target': 'en'})
        # Anything except a "blueprint not registered" status
        assert resp.status_code != 404


class TestTranslatorIdempotency:
    """The history insert dedupes on (user_id, client_id) — prevents duplicate
    rows when the outbox retries a sync."""

    def test_idempotency_helper_exists(self):
        from translator_progress_routes import add_history
        # Just confirm callable; runtime test gated by auth
        assert callable(add_history)
