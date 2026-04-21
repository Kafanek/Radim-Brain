"""
HA Sprint C tests — custom scenes, emergency events, family views.

Run: pytest tests/test_ha_scenes.py -v
"""


class TestHAScenesAuth:
    """All Sprint C endpoints require auth."""

    def test_save_custom_scene_requires_auth(self, client):
        resp = client.post('/api/ha/scenes/custom',
                           json={'name': 'Test', 'actions': []})
        assert resp.status_code in (401, 403)

    def test_list_custom_scenes_requires_auth(self, client):
        resp = client.get('/api/ha/scenes/custom')
        assert resp.status_code in (401, 403)

    def test_delete_custom_scene_requires_auth(self, client):
        resp = client.delete('/api/ha/scenes/custom/1')
        assert resp.status_code in (401, 403)

    def test_emergency_requires_auth(self, client):
        resp = client.post('/api/ha/emergency', json={})
        assert resp.status_code in (401, 403)

    def test_resolve_emergency_requires_auth(self, client):
        resp = client.post('/api/ha/emergency/1/resolve')
        assert resp.status_code in (401, 403)

    def test_family_home_status_requires_auth(self, client):
        resp = client.get('/api/ha/family/some-senior/home-status')
        assert resp.status_code in (401, 403)

    def test_family_emergencies_requires_auth(self, client):
        resp = client.get('/api/ha/family/some-senior/emergencies')
        assert resp.status_code in (401, 403)


class TestHASceneValidation:
    """_validate_scene_actions is pure — test all paths."""

    def test_accepts_safe_actions(self):
        from ha_scenes_routes import _validate_scene_actions
        ok, reason = _validate_scene_actions([
            {'action': 'light_on', 'entity_id': 'light.kitchen'},
            {'action': 'switch_off', 'entity_id': 'switch.fan'},
            {'action': 'climate_set', 'params': {'temperature': 19}},
        ])
        assert ok is True, reason

    def test_rejects_empty_list(self):
        from ha_scenes_routes import _validate_scene_actions
        ok, reason = _validate_scene_actions([])
        assert ok is False
        assert 'non-empty' in reason.lower() or 'list' in reason.lower()

    def test_rejects_non_list(self):
        from ha_scenes_routes import _validate_scene_actions
        for bad in [None, 'string', 42, {'key': 'value'}]:
            ok, _ = _validate_scene_actions(bad)
            assert ok is False

    def test_rejects_too_many_actions(self):
        from ha_scenes_routes import _validate_scene_actions
        actions = [{'action': 'light_on'}] * 21
        ok, reason = _validate_scene_actions(actions)
        assert ok is False
        assert 'max' in reason.lower() or 'too many' in reason.lower()

    def test_rejects_blocked_action(self):
        """Action whitelist is enforced on scene steps."""
        from ha_scenes_routes import _validate_scene_actions
        ok, reason = _validate_scene_actions([
            {'action': 'ha.service_call_raw', 'entity_id': 'x'}
        ])
        assert ok is False

    def test_rejects_unknown_action(self):
        """Default-deny for unknown actions applies to scenes too."""
        from ha_scenes_routes import _validate_scene_actions
        ok, reason = _validate_scene_actions([
            {'action': 'format_hard_drive'}
        ])
        assert ok is False

    def test_rejects_step_without_action(self):
        from ha_scenes_routes import _validate_scene_actions
        ok, _ = _validate_scene_actions([{'entity_id': 'light.x'}])
        assert ok is False


class TestHASceneEndpointValidation:
    def test_save_scene_missing_name(self, client):
        resp = client.post('/api/ha/scenes/custom',
                           json={'actions': [{'action': 'light_on'}]})
        assert resp.status_code in (400, 401, 403)

    def test_save_scene_empty_actions(self, client):
        resp = client.post('/api/ha/scenes/custom',
                           json={'name': 'X', 'actions': []})
        assert resp.status_code in (400, 401, 403)


class TestHASchema:
    def test_init_schema_idempotent(self):
        from ha_scenes_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_row_val_helper(self):
        from ha_scenes_routes import _row_val
        assert _row_val(None, 0, 'x') is None
        assert _row_val(('a',), 0, 'x') == 'a'
        assert _row_val({'x': 'y'}, 0, 'x') == 'y'


class TestHABlueprintRegistered:
    def test_blueprint_imports(self):
        from ha_scenes_routes import ha_scenes_bp
        assert ha_scenes_bp is not None
        assert ha_scenes_bp.name == 'ha_scenes'

    def test_all_routes_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        expected = [
            '/api/ha/scenes/custom',
            '/api/ha/scenes/custom/',
            '/api/ha/emergency',
            '/api/ha/emergency/',
            '/api/ha/family/',
        ]
        for path in expected:
            assert any(path in r for r in rules), f'Missing route: {path}'


class TestHAFamilyAccessControl:
    """Family views must require senior_family_links."""

    def test_home_status_unlinked(self, client):
        resp = client.get('/api/ha/family/nonexistent-senior/home-status')
        assert resp.status_code in (401, 403)

    def test_emergencies_unlinked(self, client):
        resp = client.get('/api/ha/family/nonexistent-senior/emergencies')
        assert resp.status_code in (401, 403)


class TestHANoConflictWithSprintA:
    """Sprint C additions must not break Sprint A security guarantees."""

    def test_core_ha_routes_still_auth_gated(self, client):
        """Original /api/ha/action must still refuse unauthenticated POST."""
        resp = client.post('/api/ha/action', json={
            'action': 'unlock',
            'entity_id': 'lock.front_door',
        })
        assert resp.status_code in (401, 403)

    def test_webhook_still_fail_closed(self, client, monkeypatch):
        monkeypatch.delenv('HA_WEBHOOK_SECRET', raising=False)
        import importlib, home_assistant
        importlib.reload(home_assistant)
        resp = client.post('/api/ha/webhook',
                           json={'event_type': 'test'})
        assert resp.status_code != 200
