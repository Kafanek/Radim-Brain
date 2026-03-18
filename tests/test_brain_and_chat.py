"""
Tests for brain engine, chat orchestrator, memory system, and admin endpoints.
"""
import json
from unittest.mock import patch, MagicMock


class TestBrainEngine:
    """Brain core computation tests."""

    def test_compute_psi_harmony(self):
        """Low C → HARMONY mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(5.0, 0.2)
        assert result["mode"] == "HARMONY"
        assert result["psi"]["C"] == 5.0
        assert 0 <= result["psi"]["E"] <= 1
        assert 0 <= result["psi"]["R"] <= 1
        assert 0 <= result["coherence"] <= 1
        assert result["phi_index"] > 0.5  # low C = high harmony

    def test_compute_psi_alert(self):
        """Medium C → ALERT mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(18.0, 0.5)
        assert result["mode"] == "ALERT"

    def test_compute_psi_crisis(self):
        """High C → CRISIS mode."""
        from brain_core import compute_psi_state
        result = compute_psi_state(30.0, 0.8)
        assert result["mode"] == "CRISIS"
        assert result["phi_index"] < 0.5  # high C = low harmony

    def test_compute_psi_saves_to_db(self, client):
        """With user_id, psi state should be saved to brain_states."""
        from brain_core import compute_psi_state
        from database import db_context
        # Clean up first
        with db_context(commit=True) as db:
            db.execute("DELETE FROM brain_states WHERE user_id = 'test_psi_save'")
        # Compute with user_id
        compute_psi_state(10.0, 0.3, user_id='test_psi_save')
        # Verify saved
        with db_context() as db:
            row = db.execute(
                "SELECT c, mode FROM brain_states WHERE user_id = 'test_psi_save'"
            ).fetchone()
            assert row is not None
            c_val = row['c'] if 'c' in row.keys() else row[0]
            assert float(c_val) == 10.0

    def test_thresholds(self):
        """Verify T1, T2, C_MAX constants."""
        from brain_math import T1, T2, C_MAX
        assert T1 == 12
        assert T2 == 27
        assert C_MAX == 40


class TestMemorySystem:
    """Memory learning and profile tests."""

    def test_load_save_learning(self, client):
        """Learning data roundtrip."""
        from memory_helpers import db_load_learning, db_save_learning
        test_data = {"topics": {"test": 1}, "interaction_count": 5}
        db_save_learning("test_memory_user", test_data)
        loaded = db_load_learning("test_memory_user")
        assert loaded["interaction_count"] == 5
        assert loaded["topics"]["test"] == 1

    def test_build_personalized_prompt(self, client):
        """Personalized prompt builds without error."""
        from memory_logic import build_personalized_prompt
        # For unknown user, should return empty or minimal prompt
        prompt = build_personalized_prompt("nonexistent_user_xyz")
        assert isinstance(prompt, str)

    def test_agent_observations_in_prompt(self, client):
        """Agent observations appear in personalized prompt."""
        from memory_helpers import db_load_learning, db_save_learning
        from memory_logic import build_personalized_prompt
        # Set up user with agent observation
        learning = db_load_learning("test_obs_user")
        learning["interaction_count"] = 5
        learning["agent_observations"] = [
            {"type": "test", "severity": "WARNING", "message": "Test observation message"}
        ]
        db_save_learning("test_obs_user", learning)
        # Build prompt
        prompt = build_personalized_prompt("test_obs_user")
        assert "Test observation message" in prompt


class TestChatOrchestrator:
    """Chat endpoint integration tests."""

    def test_chat_missing_message(self, client):
        """Chat without message returns 400."""
        resp = client.post('/api/radim/chat',
                          json={"user_id": "test", "mode": "senior"})
        assert resp.status_code == 400

    def test_chat_options(self, client):
        """CORS preflight returns 204."""
        resp = client.options('/api/radim/chat')
        assert resp.status_code == 204


class TestAdminEndpoints:
    """Admin endpoint tests."""

    def test_admin_requires_secret(self, client):
        """Admin endpoints reject without secret when ADMIN_SECRET is set."""
        import app as app_module
        original = app_module.ADMIN_SECRET
        try:
            app_module.ADMIN_SECRET = "test_secret_123"
            # Without header
            resp = client.post('/api/admin/agent-run')
            assert resp.status_code == 401
            # With wrong header
            resp = client.post('/api/admin/agent-run',
                              headers={'X-Admin-Secret': 'wrong'})
            assert resp.status_code == 401
            # With correct header
            resp = client.post('/api/admin/agent-run',
                              headers={'X-Admin-Secret': 'test_secret_123'})
            assert resp.status_code == 200
        finally:
            app_module.ADMIN_SECRET = original

    def test_debug_prompt(self, client):
        """Debug prompt endpoint returns prompt."""
        resp = client.get('/api/admin/debug-prompt/test_user')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'prompt' in data

    def test_seed_demo(self, client):
        """Seed demo creates demo senior."""
        resp = client.post('/api/admin/seed-demo')
        assert resp.status_code == 201
        data = resp.get_json()
        assert data['success'] is True
        assert data['user_id'] == 'demo_senior_1'
        assert data['brain_states_count'] > 0


class TestHealthEndpoint:
    """Health check tests."""

    def test_health_includes_db(self, client):
        """Health check includes DB connectivity info."""
        resp = client.get('/health')
        data = resp.get_json()
        assert 'db' in data
        assert data['db']['connected'] is True
        assert data['db']['latency_ms'] is not None
        assert data['version'] == '3.5.0'

    def test_health_includes_agent_loop(self, client):
        """Health check shows agent_loop module."""
        resp = client.get('/health')
        data = resp.get_json()
        assert data['modules']['agent_loop'] is True


class TestIoTAuth:
    """IoT authentication tests."""

    def test_iot_rejects_without_token(self, client):
        """IoT bridge rejects when no gateway token configured."""
        resp = client.post('/api/iot-bridge/data',
                          json={"device_id": "test", "room_id": "test",
                                "sensor_type": "motion", "value": 1.0})
        # Should return 503 (no IOT_GATEWAY_TOKEN configured)
        assert resp.status_code == 503
