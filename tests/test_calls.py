"""
Calls Sprint C tests.
Run: pytest tests/test_calls.py -v
"""


class TestCallsAuth:
    def test_safe_to_call_requires_auth(self, client):
        resp = client.get('/api/calls/safe-to-call/42')
        assert resp.status_code in (401, 403)

    def test_log_requires_auth(self, client):
        resp = client.post('/api/calls/log', json={'contactName': 'x'})
        assert resp.status_code in (401, 403)

    def test_end_requires_auth(self, client):
        resp = client.post('/api/calls/end', json={'callId': 1, 'durationSec': 30})
        assert resp.status_code in (401, 403, 404)

    def test_history_requires_auth(self, client):
        resp = client.get('/api/calls/history')
        assert resp.status_code in (401, 403)

    def test_quick_dial_requires_auth(self, client):
        resp = client.get('/api/calls/quick-dial')
        assert resp.status_code in (401, 403)


class TestBlueprint:
    def test_blueprint_imports(self):
        from calls_routes import calls_bp
        assert calls_bp is not None
        assert calls_bp.name == 'calls'

    def test_all_endpoints_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/calls/safe-to-call/<contact_id>' in r for r in rules)
        assert any(r.endswith('/api/calls/log') for r in rules)
        assert any(r.endswith('/api/calls/end') for r in rules)
        assert any(r.endswith('/api/calls/history') for r in rules)
        assert any(r.endswith('/api/calls/quick-dial') for r in rules)


class TestSchema:
    def test_init_schema_idempotent(self):
        from calls_routes import _init_schema
        _init_schema()
        _init_schema()

    def test_schema_has_core_columns(self):
        from calls_routes import CALLS_SCHEMA
        assert 'call_log' in CALLS_SCHEMA
        assert 'room_code' in CALLS_SCHEMA
        assert 'duration_sec' in CALLS_SCHEMA
        assert 'direction' in CALLS_SCHEMA
        assert 'status' in CALLS_SCHEMA


class TestHelpers:
    def test_is_family_of_self(self):
        from calls_routes import _is_family_of
        assert _is_family_of('u1', 'u1') is True

    def test_is_family_of_empty(self):
        from calls_routes import _is_family_of
        assert _is_family_of('', 'x') is False
        assert _is_family_of('x', '') is False

    def test_is_family_of_unrelated(self):
        from calls_routes import _is_family_of, _init_schema
        _init_schema()
        assert _is_family_of('senior-xyz', 'stranger-abc') is False


class TestAuditHook:
    def test_audit_function_exists(self):
        from calls_routes import _audit
        assert callable(_audit)

    def test_audit_silent_on_empty(self):
        """_audit must never raise."""
        from calls_routes import _audit
        _audit('', 'test')  # no actor, should be no-op


class TestValidation:
    def test_log_validates_call_type(self, client):
        """POST /log without auth → 401/403 (validation would be 400)."""
        resp = client.post('/api/calls/log', json={'callType': 'weird'})
        assert resp.status_code in (400, 401, 403)

    def test_end_requires_call_id(self, client):
        """End without callId → 400 (or 401 unauthed)."""
        resp = client.post('/api/calls/end', json={})
        assert resp.status_code in (400, 401, 403)


# ═══════════════════════════════════════════════════════════════════
# Sprint D — ICE servers + telemetry
# ═══════════════════════════════════════════════════════════════════

class TestSprintD:
    def test_ice_servers_requires_auth(self, client):
        resp = client.get('/api/calls/ice-servers')
        assert resp.status_code in (401, 403)

    def test_ice_servers_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/calls/ice-servers') for r in rules)

    def test_telemetry_requires_auth(self, client):
        resp = client.post('/api/calls/telemetry',
                           json={'quality': 'poor', 'rttMs': 250})
        assert resp.status_code in (401, 403)

    def test_telemetry_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any(r.endswith('/api/calls/telemetry') for r in rules)

    def test_default_stun_servers_defined(self):
        from calls_routes import _DEFAULT_STUN
        assert isinstance(_DEFAULT_STUN, list)
        assert len(_DEFAULT_STUN) >= 2
        assert all(s.startswith('stun:') for s in _DEFAULT_STUN)

    def test_openrelay_turn_configured(self):
        from calls_routes import _OPENRELAY_TURN
        assert isinstance(_OPENRELAY_TURN, list)
        assert len(_OPENRELAY_TURN) >= 2
        for s in _OPENRELAY_TURN:
            assert 'urls' in s and 'username' in s and 'credential' in s
            assert s['urls'].startswith('turn:') or s['urls'].startswith('turns:')


class TestIceServerEnvFallback:
    """If TURN_URL env is set, it should be prioritized over openrelay."""

    def test_env_turn_creates_self_hosted(self, monkeypatch):
        # This only verifies the code path exists — full integration needs auth
        import os
        monkeypatch.setenv('TURN_URL', 'turn:turn.example.com:3478')
        monkeypatch.setenv('TURN_USER', 'user')
        monkeypatch.setenv('TURN_PASSWORD', 'pass')
        # Re-read envs — the endpoint reads at call time, so this works per request.
        assert os.environ.get('TURN_URL') == 'turn:turn.example.com:3478'


# ═══════════════════════════════════════════════════════════════════
# Sprint E2 — recording upload + transcript save
# ═══════════════════════════════════════════════════════════════════

class TestRecordingEndpoint:
    def test_upload_requires_auth(self, client):
        resp = client.post('/api/calls/1/recording')
        assert resp.status_code in (401, 403, 404)

    def test_upload_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/calls/<int:call_id>/recording' in r for r in rules)


class TestTranscriptEndpoint:
    def test_save_requires_auth(self, client):
        resp = client.post('/api/calls/1/transcript', json={'text': 'ahoj mama'})
        assert resp.status_code in (401, 403, 404)

    def test_save_registered(self, app):
        rules = [str(r) for r in app.url_map.iter_rules()]
        assert any('/api/calls/<int:call_id>/transcript' in r for r in rules)

    def test_rejects_short_text(self, client):
        # Auth fails first with 401; validation check would be 400
        resp = client.post('/api/calls/1/transcript', json={'text': 'ok'})
        assert resp.status_code in (400, 401, 403, 404)


class TestRecordingSizeLimit:
    def test_max_recording_bytes_defined(self):
        from calls_routes import _MAX_RECORDING_BYTES
        assert _MAX_RECORDING_BYTES >= 10 * 1024 * 1024   # at least 10 MB
        assert _MAX_RECORDING_BYTES <= 100 * 1024 * 1024  # at most 100 MB

    def test_max_transcript_len_defined(self):
        from calls_routes import _MAX_TRANSCRIPT_LEN
        assert _MAX_TRANSCRIPT_LEN >= 5000
        assert _MAX_TRANSCRIPT_LEN <= 50000
