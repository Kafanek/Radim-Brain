"""
Unit tests for agent/personas.py — DB-free.

Run: python3 -m agent.test_personas
"""
import unittest

try:
    from .personas import (
        PERSONA_THRESHOLDS, get_thresholds, list_personas,
        _SENIOR_BASE, _DEFAULT_PERSONA,
    )
except ImportError:
    from personas import (  # type: ignore
        PERSONA_THRESHOLDS, get_thresholds, list_personas,
        _SENIOR_BASE, _DEFAULT_PERSONA,
    )


class TestPersonaRegistry(unittest.TestCase):
    def test_senior_is_default(self):
        self.assertEqual(_DEFAULT_PERSONA, 'senior')
        self.assertIn('senior', PERSONA_THRESHOLDS)

    def test_three_personas_present(self):
        self.assertSetEqual(set(list_personas()),
                            {'senior', 'child_autism', 'child_adhd'})


class TestThresholds(unittest.TestCase):
    def test_senior_baseline_keys(self):
        t = get_thresholds('senior')
        # Required keys for detector consumers
        for key in ['c_alert', 'c_crisis',
                    'silence_warning_hours', 'silence_alert_hours',
                    'silence_crisis_hours', 'activity_drop_factor',
                    'hr_high', 'hr_low', 'spo2_low',
                    'door_open_alert_min', 'no_motion_alert_hours',
                    'battery_low_pct']:
            self.assertIn(key, t, f"Missing key {key!r} in senior thresholds")

    def test_child_autism_lower_c(self):
        s = get_thresholds('senior')
        a = get_thresholds('child_autism')
        # Autism reacts faster — lower bands
        self.assertLess(a['c_alert'],  s['c_alert'])
        self.assertLess(a['c_crisis'], s['c_crisis'])

    def test_child_adhd_higher_c_tolerance(self):
        s = get_thresholds('senior')
        d = get_thresholds('child_adhd')
        # ADHD: more fluctuation tolerated for ALERT, but shorter silence
        self.assertGreater(d['c_alert'],  s['c_alert'])
        self.assertLess(d['silence_warning_hours'], s['silence_warning_hours'])

    def test_unknown_persona_falls_back_to_senior(self):
        self.assertEqual(get_thresholds('martian'), get_thresholds('senior'))

    def test_thresholds_are_defensive_copies(self):
        a = get_thresholds('senior')
        a['c_alert'] = 999
        # Original should not be mutated
        self.assertEqual(get_thresholds('senior')['c_alert'],
                         _SENIOR_BASE['c_alert'])

    def test_all_personas_inherit_senior_keys(self):
        senior_keys = set(get_thresholds('senior').keys())
        for pid in list_personas():
            t = get_thresholds(pid)
            missing = senior_keys - set(t.keys())
            self.assertFalse(missing,
                f"persona {pid!r} missing inherited keys: {missing}")

    def test_door_open_autism_earlier(self):
        # Wandering risk → autism alerts at 15 min vs senior 30 min
        self.assertLess(get_thresholds('child_autism')['door_open_alert_min'],
                        get_thresholds('senior')['door_open_alert_min'])

    def test_tone_hint_present(self):
        for pid in list_personas():
            self.assertIn('tone_hint', get_thresholds(pid))


if __name__ == '__main__':
    unittest.main(verbosity=2)
