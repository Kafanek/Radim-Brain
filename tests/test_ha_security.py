"""
Home Assistant module — Sprint A security tests.

These tests verify the critical security fixes added before the module
can be connected to real HA. BEFORE THESE FIXES, any unauthenticated
request could unlock the senior's front door.

Run: pytest tests/test_ha_security.py -v
"""


class TestHAEndpointsRequireAuth:
    """All /api/ha/* endpoints require a valid JWT — unauthed returns 401/403."""

    def test_status_requires_auth(self, client):
        resp = client.get('/api/ha/status')
        assert resp.status_code in (401, 403)

    def test_devices_requires_auth(self, client):
        resp = client.get('/api/ha/devices')
        assert resp.status_code in (401, 403)

    def test_device_detail_requires_auth(self, client):
        resp = client.get('/api/ha/device/light.living_room')
        assert resp.status_code in (401, 403)

    def test_action_requires_auth(self, client):
        """MOST CRITICAL: without this, anyone could unlock the front door."""
        resp = client.post('/api/ha/action', json={
            'action': 'unlock',
            'entity_id': 'lock.front_door',
        })
        assert resp.status_code in (401, 403)

    def test_sensors_requires_auth(self, client):
        resp = client.get('/api/ha/sensors')
        assert resp.status_code in (401, 403)

    def test_rooms_requires_auth(self, client):
        resp = client.get('/api/ha/rooms')
        assert resp.status_code in (401, 403)

    def test_mqtt_sensors_requires_auth(self, client):
        resp = client.get('/api/ha/mqtt/sensors')
        assert resp.status_code in (401, 403)

    def test_mqtt_publish_requires_auth(self, client):
        resp = client.post('/api/ha/mqtt/publish',
                           json={'topic': 'x/y', 'payload': {}})
        assert resp.status_code in (401, 403)

    def test_direct_discover_requires_auth(self, client):
        resp = client.get('/api/ha/direct/discover')
        assert resp.status_code in (401, 403)

    def test_direct_kasa_requires_auth(self, client):
        resp = client.post('/api/ha/direct/kasa',
                           json={'ip': '192.168.1.50', 'action': 'toggle'})
        assert resp.status_code in (401, 403)

    def test_direct_yeelight_requires_auth(self, client):
        resp = client.post('/api/ha/direct/yeelight',
                           json={'ip': '192.168.1.60', 'action': 'toggle'})
        assert resp.status_code in (401, 403)

    def test_libraries_requires_auth(self, client):
        resp = client.get('/api/ha/libraries')
        assert resp.status_code in (401, 403)


class TestHAWebhookSecret:
    """HA→Radim webhook uses X-HA-Secret, not JWT. Must fail-closed."""

    def test_webhook_rejects_without_configured_secret(self, client, monkeypatch):
        """If HA_WEBHOOK_SECRET not set on server → 503 (disabled),
        NOT 200 (open to the world)."""
        monkeypatch.delenv('HA_WEBHOOK_SECRET', raising=False)
        # Reload HA_WEBHOOK_SECRET in module
        import importlib, home_assistant
        importlib.reload(home_assistant)
        resp = client.post('/api/ha/webhook', json={'event_type': 'test'})
        # Either 503 (newly reloaded module) or 401 (cached old blueprint).
        # What we REALLY care about: must NOT be 200 without a secret.
        assert resp.status_code != 200

    def test_webhook_rejects_wrong_secret(self, client, monkeypatch):
        monkeypatch.setenv('HA_WEBHOOK_SECRET', 'real-secret-value')
        import importlib, home_assistant
        importlib.reload(home_assistant)
        resp = client.post('/api/ha/webhook',
                           json={'event_type': 'test'},
                           headers={'X-HA-Secret': 'wrong-value'})
        assert resp.status_code == 401


class TestHAActionWhitelist:
    """_is_action_allowed() is a pure function — test all paths."""

    def test_safe_actions_allowed_without_confirm(self):
        from home_assistant import _is_action_allowed
        for action in ['light_on', 'light_off', 'switch_toggle',
                       'climate_set', 'media_play', 'cover_close', 'lock',
                       'scene_activate']:
            ok, needs_confirm, reason = _is_action_allowed(action)
            assert ok is True, f'{action} should be allowed'
            assert needs_confirm is False, f'{action} should not need confirm'

    def test_dangerous_actions_require_confirm(self):
        from home_assistant import _is_action_allowed
        for action in ['unlock', 'cover_open', 'alarm_disarm', 'garage_open']:
            ok, needs_confirm, reason = _is_action_allowed(action)
            assert ok is True, f'{action} should be allowed with confirm'
            assert needs_confirm is True, f'{action} must require confirm'

    def test_blocked_actions_denied(self):
        from home_assistant import _is_action_allowed
        for action in ['ha.service_call_raw', 'raw_shell']:
            ok, needs_confirm, reason = _is_action_allowed(action)
            assert ok is False, f'{action} must be blocked'

    def test_unknown_action_denied_by_default(self):
        """Default-deny policy: unknown actions return ok=False."""
        from home_assistant import _is_action_allowed
        for action in ['rm_rf', 'format_disk', 'turn_off_heart_monitor',
                       'ignite_oven', 'made_up_gibberish']:
            ok, _, reason = _is_action_allowed(action)
            assert ok is False, f'{action} should be denied'

    def test_empty_action_denied(self):
        from home_assistant import _is_action_allowed
        for action in ['', None, '   ', 0, False]:
            ok, _, _ = _is_action_allowed(action)
            assert ok is False


class TestHARateLimit:
    """Per-user rate limiter: 1 action per 2 seconds."""

    def test_first_call_allowed(self):
        from home_assistant import _rate_limit_check, _RATE_LAST_ACTION
        _RATE_LAST_ACTION.clear()
        assert _rate_limit_check('user-test-1') is True

    def test_second_call_within_window_rejected(self):
        from home_assistant import _rate_limit_check, _RATE_LAST_ACTION
        _RATE_LAST_ACTION.clear()
        assert _rate_limit_check('user-test-2') is True
        # Immediate second call
        assert _rate_limit_check('user-test-2') is False

    def test_after_window_allowed(self):
        import time
        from home_assistant import _rate_limit_check, _RATE_LAST_ACTION, _RATE_WINDOW_SECONDS
        _RATE_LAST_ACTION.clear()
        _rate_limit_check('user-test-3')
        # Simulate passage of time by rewriting the cached timestamp
        _RATE_LAST_ACTION['user-test-3'] = time.time() - (_RATE_WINDOW_SECONDS + 0.5)
        assert _rate_limit_check('user-test-3') is True

    def test_per_user_isolation(self):
        """Rate limit is per-user, not global."""
        from home_assistant import _rate_limit_check, _RATE_LAST_ACTION
        _RATE_LAST_ACTION.clear()
        assert _rate_limit_check('user-A') is True
        # User B is unaffected by user A's action
        assert _rate_limit_check('user-B') is True


class TestHABlueprintRegistered:
    def test_ha_blueprint_imports(self):
        from home_assistant import ha_bp
        assert ha_bp is not None

    def test_all_thirteen_routes_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        expected_paths = [
            '/api/ha/status',
            '/api/ha/devices',
            '/api/ha/device/',
            '/api/ha/action',
            '/api/ha/sensors',
            '/api/ha/rooms',
            '/api/ha/webhook',
            '/api/ha/mqtt/sensors',
            '/api/ha/mqtt/publish',
            '/api/ha/direct/discover',
            '/api/ha/direct/kasa',
            '/api/ha/direct/yeelight',
            '/api/ha/libraries',
        ]
        for path in expected_paths:
            assert any(path in r for r in rules), \
                f'Route {path} missing from blueprint'


class TestHASimulatedFallback:
    """When HA is unreachable, the client falls back to SimulatedHomeAssistant."""

    def test_simulated_has_mock_devices(self):
        from home_assistant import SimulatedHomeAssistant
        sim = SimulatedHomeAssistant()
        rooms = sim.get_devices_by_room()
        assert isinstance(rooms, dict)
        assert len(rooms) > 0  # has at least one room of mock devices

    def test_simulated_action_safe(self):
        """Simulated mode should at least not raise."""
        from home_assistant import SimulatedHomeAssistant
        sim = SimulatedHomeAssistant()
        result = sim.execute_agent_action('light_on', {'entity_id': 'light.kitchen'})
        # Any dict response is fine; what matters is no exception
        assert isinstance(result, dict)
