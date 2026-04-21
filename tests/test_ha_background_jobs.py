"""
HA P2 — background jobs (abnormal night activity + maintenance).

Run: pytest tests/test_ha_background_jobs.py -v
"""

from datetime import datetime


class TestNightHourDetection:
    """_is_night_hour — pure function, straightforward."""

    def test_midnight_is_night(self):
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 0, 30)) is True

    def test_3am_is_night(self):
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 3, 0)) is True

    def test_11pm_is_night(self):
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 23, 30)) is True

    def test_5am_is_not_night(self):
        """5:00 → no longer "night hours" (threshold reached)."""
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 5, 0)) is False

    def test_noon_is_not_night(self):
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 12, 0)) is False

    def test_8pm_is_not_night(self):
        from ha_background_jobs import _is_night_hour
        assert _is_night_hour(datetime(2026, 4, 21, 20, 0)) is False


class TestNightActivityDetection:
    """_detect_night_activity — pure function on sensor data."""

    def test_no_client_returns_empty(self):
        from ha_background_jobs import _detect_night_activity
        r = _detect_night_activity(None)
        assert r['has_activity'] is False
        assert r['active_entities'] == []

    def test_motion_on_flags_activity(self):
        from ha_background_jobs import _detect_night_activity
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'motion': [{'entity_id': 'binary_sensor.hall_motion',
                                'name': 'Chodba pohyb', 'state': 'on'}],
                    'door': [], 'battery': [], 'temperature': [], 'humidity': [],
                }
            def get_devices_by_room(self):
                return {}
        r = _detect_night_activity(FakeClient())
        assert r['has_activity'] is True
        assert 'binary_sensor.hall_motion' in r['active_entities']
        assert any('pohyb' in x.lower() for x in r['reasons'])

    def test_door_open_flags_activity(self):
        from ha_background_jobs import _detect_night_activity
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'motion': [],
                    'door': [{'entity_id': 'binary_sensor.front_door',
                              'name': 'Vchod', 'state': 'on'}],
                    'battery': [], 'temperature': [], 'humidity': [],
                }
            def get_devices_by_room(self):
                return {}
        r = _detect_night_activity(FakeClient())
        assert r['has_activity'] is True
        assert any('otev' in x.lower() for x in r['reasons'])

    def test_lights_on_flag_activity(self):
        from ha_background_jobs import _detect_night_activity
        class FakeClient:
            def get_sensors_summary(self):
                return {'motion': [], 'door': [], 'battery': [],
                        'temperature': [], 'humidity': []}
            def get_devices_by_room(self):
                return {
                    'kitchen': {'devices': [
                        {'domain': 'light', 'name': 'Kuchyň',
                         'entity_id': 'light.kitchen', 'state': 'on'},
                    ]},
                }
        r = _detect_night_activity(FakeClient())
        assert r['has_activity'] is True
        assert any('svít' in x.lower() for x in r['reasons'])

    def test_all_quiet_no_activity(self):
        from ha_background_jobs import _detect_night_activity
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'motion': [{'entity_id': 'x', 'name': 'X', 'state': 'off'}],
                    'door': [{'entity_id': 'y', 'name': 'Y', 'state': 'off'}],
                    'battery': [], 'temperature': [], 'humidity': [],
                }
            def get_devices_by_room(self):
                return {
                    'living': {'devices': [
                        {'domain': 'light', 'name': 'L', 'entity_id': 'light.l', 'state': 'off'},
                    ]},
                }
        r = _detect_night_activity(FakeClient())
        assert r['has_activity'] is False


class TestMaintenanceDetection:
    """_detect_maintenance_issues — pure function."""

    def test_no_client_returns_empty(self):
        from ha_background_jobs import _detect_maintenance_issues
        r = _detect_maintenance_issues(None)
        assert r['low_batteries'] == []
        assert r['stale_sensors'] == []

    def test_low_battery_flagged(self):
        from ha_background_jobs import _detect_maintenance_issues
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'battery': [
                        {'entity_id': 'sensor.a_batt', 'name': 'A', 'value': 12},
                        {'entity_id': 'sensor.b_batt', 'name': 'B', 'value': 80},
                    ],
                    'temperature': [], 'humidity': [], 'motion': [], 'door': [],
                }
        r = _detect_maintenance_issues(FakeClient())
        assert len(r['low_batteries']) == 1
        assert r['low_batteries'][0]['name'] == 'A'
        assert r['low_batteries'][0]['value'] == 12

    def test_healthy_battery_not_flagged(self):
        from ha_background_jobs import _detect_maintenance_issues
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'battery': [
                        {'entity_id': 'x', 'name': 'X', 'value': 85},
                    ],
                    'temperature': [], 'humidity': [], 'motion': [], 'door': [],
                }
        r = _detect_maintenance_issues(FakeClient())
        assert r['low_batteries'] == []

    def test_non_numeric_battery_ignored(self):
        """Battery sensor reporting 'unavailable' must not crash."""
        from ha_background_jobs import _detect_maintenance_issues
        class FakeClient:
            def get_sensors_summary(self):
                return {
                    'battery': [
                        {'entity_id': 'x', 'name': 'X', 'value': 'unavailable'},
                        {'entity_id': 'y', 'name': 'Y', 'value': None},
                    ],
                    'temperature': [], 'humidity': [], 'motion': [], 'door': [],
                }
        r = _detect_maintenance_issues(FakeClient())
        assert r['low_batteries'] == []


class TestSchedulerJobResilience:
    """run_*_check wrappers must not crash on import/connection errors."""

    def test_night_check_without_ha_doesnt_crash(self, app):
        from ha_background_jobs import run_night_activity_check
        # Will return skipped/error dict, NOT raise
        result = run_night_activity_check(app)
        assert isinstance(result, dict)

    def test_maintenance_check_without_ha_doesnt_crash(self, app):
        from ha_background_jobs import run_maintenance_check
        result = run_maintenance_check(app)
        assert isinstance(result, dict)


class TestConstants:
    """Configuration constants are reasonable for production."""

    def test_night_window_sane(self):
        from ha_background_jobs import NIGHT_HOUR_START, NIGHT_HOUR_END
        assert 20 <= NIGHT_HOUR_START <= 23
        assert 4 <= NIGHT_HOUR_END <= 7

    def test_dedupe_hours_positive(self):
        from ha_background_jobs import NIGHT_DEDUPE_HOURS
        assert NIGHT_DEDUPE_HOURS > 0
        assert NIGHT_DEDUPE_HOURS <= 12  # don't wait a whole day

    def test_battery_threshold_reasonable(self):
        from ha_background_jobs import BATTERY_THRESHOLD_LOW
        assert 10 <= BATTERY_THRESHOLD_LOW <= 30

    def test_stale_threshold_reasonable(self):
        from ha_background_jobs import STALE_SENSOR_HOURS
        assert 24 <= STALE_SENSOR_HOURS <= 168  # 1 day to 1 week
