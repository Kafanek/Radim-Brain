"""
Tests for proactive agent loop — detectors and baselines.
"""

import json
from unittest.mock import patch


class TestBehaviorBaseline:
    """Baseline computation tests."""

    def test_mean_std(self):
        from behavior_baseline import _mean_std
        avg, std = _mean_std([10, 10, 10])
        assert avg == 10.0
        assert std == 0.0

        avg, std = _mean_std([1, 2, 3, 4, 5])
        assert abs(avg - 3.0) < 0.01
        assert std > 0

    def test_mean_std_empty(self):
        from behavior_baseline import _mean_std
        avg, std = _mean_std([])
        assert avg == 0.0
        assert std == 0.0

    def test_time_window(self):
        from behavior_baseline import _time_window
        w = _time_window()
        assert w in ("morning", "afternoon", "evening", "night")

    def test_needs_update_missing(self):
        from behavior_baseline import needs_update
        assert needs_update({}) is True
        assert needs_update({"baselines": {}}) is True
        assert needs_update({"baselines": {"updated_at": "2020-01-01T00:00:00"}}) is True


class TestAgentLoopDetectors:
    """Anomaly detector unit tests."""

    def test_c_trend_no_data(self):
        """No C_history → no observation."""
        from agent_loop import _check_c_trend
        with patch('agent_loop.db_load_learning', return_value={"C_history": []}):
            obs = _check_c_trend("test_user", {"avg_C": 5.0, "std_C": 2.0})
            assert obs is None

    def test_c_trend_normal(self):
        """Normal C values → no observation."""
        from agent_loop import _check_c_trend
        with patch('agent_loop.db_load_learning', return_value={"C_history": [5, 6, 5, 4, 5, 6, 5, 4, 5, 6, 5, 4, 5, 6, 5, 4, 5, 6, 5, 4]}):
            obs = _check_c_trend("test_user", {"avg_C": 5.0, "std_C": 2.0})
            assert obs is None

    def test_c_trend_rising_warning(self):
        """Rising C trend → WARNING."""
        from agent_loop import _check_c_trend
        # Baseline avg=5, std=2. Recent avg should be > 5 + 1.5*2 = 8
        history = [5]*15 + [9, 10, 11, 10, 9]  # recent avg = ~9.8
        with patch('agent_loop.db_load_learning', return_value={"C_history": history}):
            obs = _check_c_trend("test_user", {"avg_C": 5.0, "std_C": 2.0})
            assert obs is not None
            assert obs["severity"] == "WARNING"
            assert obs["type"] == "c_trend_rising"

    def test_c_trend_crisis(self):
        """Very high C → CRISIS."""
        from agent_loop import _check_c_trend
        history = [5]*15 + [30, 32, 28, 31, 29]
        with patch('agent_loop.db_load_learning', return_value={"C_history": history}):
            obs = _check_c_trend("test_user", {"avg_C": 5.0, "std_C": 2.0})
            assert obs is not None
            assert obs["severity"] == "CRISIS"

    def test_interaction_silence_recent(self):
        """Recent interaction → no observation."""
        from agent_loop import _check_interaction_silence
        from datetime import datetime
        recent = datetime.utcnow().isoformat()
        with patch('agent_loop.db_load_learning', return_value={"last_interaction": recent}):
            obs = _check_interaction_silence("test_user", {})
            assert obs is None

    def test_interaction_silence_long(self):
        """25h silence → WARNING."""
        from agent_loop import _check_interaction_silence
        from datetime import datetime, timedelta
        old = (datetime.utcnow() - timedelta(hours=25)).isoformat()
        with patch('agent_loop.db_load_learning', return_value={"last_interaction": old}):
            obs = _check_interaction_silence("test_user", {})
            assert obs is not None
            assert obs["severity"] == "WARNING"

    def test_interaction_silence_very_long(self):
        """50h silence → ALERT."""
        from agent_loop import _check_interaction_silence
        from datetime import datetime, timedelta
        old = (datetime.utcnow() - timedelta(hours=50)).isoformat()
        with patch('agent_loop.db_load_learning', return_value={"last_interaction": old}):
            obs = _check_interaction_silence("test_user", {})
            assert obs is not None
            assert obs["severity"] == "ALERT"


class TestAgentObservationsTable:
    """DB table smoke test."""

    def test_table_exists(self, client):
        """agent_observations table should be created by init_db."""
        from database import db_context
        with db_context() as db:
            # Should not raise — table created by init_db via conftest
            row = db.execute("SELECT COUNT(*) as cnt FROM agent_observations").fetchone()
            assert row is not None


class TestExistingTestsStillPass:
    """Ensure agent_loop doesn't break existing health endpoint."""

    def test_health_still_works(self, client):
        resp = client.get('/health')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['blueprint_count'] >= 15
