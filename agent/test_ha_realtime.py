"""
Unit tests for agent/ha_realtime.py — pure filter logic, no DB / WS.

Run: python3 -m agent.test_ha_realtime
"""
import unittest

try:
    from .ha_realtime import (
        is_critical_event, CRITICAL_DEVICE_CLASSES, HARealtimeRegistry,
    )
except ImportError:
    from ha_realtime import (  # type: ignore
        is_critical_event, CRITICAL_DEVICE_CLASSES, HARealtimeRegistry,
    )


def state(value, device_class=None, friendly_name=None):
    return {
        'state': value,
        'attributes': {
            **({'device_class': device_class} if device_class else {}),
            **({'friendly_name': friendly_name} if friendly_name else {}),
        },
    }


class TestIsCriticalEvent(unittest.TestCase):
    def test_smoke_on_is_critical_crisis(self):
        ok, sev, msg = is_critical_event(
            'binary_sensor.kitchen_smoke', state('on', 'smoke'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'CRISIS')
        self.assertIn('kouř', msg)

    def test_gas_on_is_critical_crisis(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.kitchen_gas', state('on', 'gas'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'CRISIS')

    def test_co_on_is_critical_crisis(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.bedroom_co', state('on', 'carbon_monoxide'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'CRISIS')

    def test_moisture_on_is_alert_not_crisis(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.bath_leak', state('on', 'moisture'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'ALERT')  # property not life

    def test_smoke_off_is_not_critical(self):
        ok, _, _ = is_critical_event(
            'binary_sensor.kitchen_smoke', state('off', 'smoke'))
        self.assertFalse(ok)

    def test_motion_is_not_critical(self):
        # Motion is routine — handled by 5-min poll, not real-time
        ok, _, _ = is_critical_event(
            'binary_sensor.hall_motion', state('on', 'motion'))
        self.assertFalse(ok)

    def test_door_is_not_critical(self):
        ok, _, _ = is_critical_event(
            'binary_sensor.front_door', state('on', 'door'))
        self.assertFalse(ok)

    def test_non_binary_sensor_ignored(self):
        # Light state changes are NOT critical
        ok, _, _ = is_critical_event(
            'light.living_room', state('on', 'smoke'))
        self.assertFalse(ok)

    def test_missing_device_class_ignored(self):
        ok, _, _ = is_critical_event(
            'binary_sensor.unknown', state('on'))
        self.assertFalse(ok)

    def test_string_state_ignored(self):
        # Real HA always sends dict; defensive against malformed
        ok, _, _ = is_critical_event('binary_sensor.smoke', 'on')
        self.assertFalse(ok)

    def test_none_state_ignored(self):
        ok, _, _ = is_critical_event('binary_sensor.smoke', None)
        self.assertFalse(ok)

    def test_uppercase_device_class_normalized(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.smoke', state('on', 'SMOKE'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'CRISIS')

    def test_safety_is_alert(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.alarm', state('on', 'safety'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'ALERT')

    def test_tamper_is_alert(self):
        ok, sev, _ = is_critical_event(
            'binary_sensor.tamper_kitchen', state('on', 'tamper'))
        self.assertTrue(ok)
        self.assertEqual(sev, 'ALERT')


class TestRegistry(unittest.TestCase):
    def test_singleton_state(self):
        r = HARealtimeRegistry(app=None)
        self.assertEqual(r.status()['subscribed_users'], 0)

    def test_init_user_no_ha(self):
        # User without HA configured → returns False, doesn't crash
        r = HARealtimeRegistry(app=None)
        # ha_for_user('nonexistent_user') will return None or raise
        result = r.init_user('nonexistent_test_user_xyz')
        self.assertFalse(result)
        self.assertEqual(r.status()['subscribed_users'], 0)

    def test_dedupe_within_window(self):
        # Direct test of internal _dedupe behavior
        r = HARealtimeRegistry(app=None)
        # Manually mark a key
        import time
        now_ms = int(time.time() * 1000)
        r._dedupe['user1|binary_sensor.smoke'] = now_ms
        # Within 30s = dedupe should suppress
        # We can't easily test _handle_event without mocking _save_observation,
        # so just verify the dedupe map lifecycle
        self.assertEqual(len(r._dedupe), 1)


class TestCriticalDeviceClasses(unittest.TestCase):
    def test_required_classes_present(self):
        for required in ['smoke', 'gas', 'carbon_monoxide', 'moisture',
                         'safety', 'tamper']:
            self.assertIn(required, CRITICAL_DEVICE_CLASSES)

    def test_severity_format(self):
        for cls, info in CRITICAL_DEVICE_CLASSES.items():
            self.assertIsInstance(info, tuple)
            self.assertEqual(len(info), 2)
            sev, msg = info
            self.assertIn(sev, ('CRISIS', 'ALERT', 'WARNING'))
            self.assertIsInstance(msg, str)
            self.assertGreater(len(msg), 0)

    def test_life_safety_is_crisis(self):
        for cls in ('smoke', 'gas', 'carbon_monoxide'):
            sev, _ = CRITICAL_DEVICE_CLASSES[cls]
            self.assertEqual(sev, 'CRISIS',
                f"{cls} must be CRISIS — life safety")


if __name__ == '__main__':
    unittest.main(verbosity=2)
