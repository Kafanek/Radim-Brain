"""
Unit tests for agent/circadian.py — pure time-driven curves.

Run: python3 -m agent.test_circadian
"""
import unittest
from datetime import datetime

try:
    from .circadian import (
        compute_circadian_c, describe_circadian_phase,
        PERSONA_CURVES, _hour_of_day,
    )
except ImportError:
    from circadian import (  # type: ignore
        compute_circadian_c, describe_circadian_phase,
        PERSONA_CURVES, _hour_of_day,
    )


def t(hour, minute=0):
    return datetime(2026, 5, 10, hour, minute)


class TestSeniorCurve(unittest.TestCase):
    def test_deep_night_low(self):
        self.assertEqual(compute_circadian_c('senior', t(3)), 5.0)

    def test_morning_rise(self):
        # 5 → 8 over 6h
        self.assertAlmostEqual(compute_circadian_c('senior', t(9)), 6.5, places=1)

    def test_afternoon_plateau(self):
        self.assertAlmostEqual(compute_circadian_c('senior', t(14)), 8.0)

    def test_sundown_peak(self):
        # 20:00 → 18.0 (sundowning peak)
        self.assertAlmostEqual(compute_circadian_c('senior', t(19, 30)), 16.75, places=1)
        self.assertGreater(compute_circadian_c('senior', t(18)), 12.0)

    def test_evening_drop(self):
        c20 = compute_circadian_c('senior', t(20))  # peak ~18
        c23 = compute_circadian_c('senior', t(23))
        self.assertGreater(c20, c23)
        self.assertGreaterEqual(c23, 6.0)

    def test_phase_label(self):
        self.assertEqual(describe_circadian_phase('senior', t(18)), 'sundown_peak')
        self.assertEqual(describe_circadian_phase('senior', t(3)),  'deep_sleep')
        self.assertEqual(describe_circadian_phase('senior', t(8)),  'morning_rise')
        self.assertEqual(describe_circadian_phase('senior', t(14)), 'afternoon_plateau')


class TestADHDCurve(unittest.TestCase):
    def test_morning_fog(self):
        # 9:00 — peak fog
        c9 = compute_circadian_c('child_adhd', t(9))
        self.assertGreater(c9, 8.0)  # > baseline
        self.assertLessEqual(c9, 12.0)  # peak around 12

    def test_alert_window(self):
        c14 = compute_circadian_c('child_adhd', t(14))
        c11 = compute_circadian_c('child_adhd', t(11))
        # Alert window 10-18 should be flat 6
        self.assertEqual(c14, 6.0)
        self.assertEqual(c11, 6.0)

    def test_evening_burnout(self):
        c18 = compute_circadian_c('child_adhd', t(18))
        c21 = compute_circadian_c('child_adhd', t(21))
        # 18 → 22 ramps 6 → 12
        self.assertEqual(c18, 6.0)
        self.assertGreater(c21, c18)
        self.assertLessEqual(c21, 12.0)

    def test_phase_label(self):
        self.assertEqual(describe_circadian_phase('child_adhd', t(9)),  'morning_fog')
        self.assertEqual(describe_circadian_phase('child_adhd', t(14)), 'alert_window')
        self.assertEqual(describe_circadian_phase('child_adhd', t(20)), 'evening_burnout')


class TestAutismCurve(unittest.TestCase):
    def test_routine_baseline_low(self):
        c10 = compute_circadian_c('child_autism', t(10))
        c14 = compute_circadian_c('child_autism', t(14))
        # Stable midday = 6
        self.assertEqual(c10, 6.0)

    def test_transition_bump(self):
        c8 = compute_circadian_c('child_autism', t(8))
        c10 = compute_circadian_c('child_autism', t(10))
        # 7-9 transition should be slightly higher
        self.assertGreater(c8, c10)

    def test_sleep_low(self):
        self.assertEqual(compute_circadian_c('child_autism', t(2)), 5.0)
        self.assertEqual(compute_circadian_c('child_autism', t(23)), 5.0)


class TestOffset(unittest.TestCase):
    def test_offset_shifts_curve(self):
        # Negative offset = effectively earlier in the curve
        c_normal = compute_circadian_c('senior', t(18), offset_hours=0)
        c_shifted = compute_circadian_c('senior', t(18), offset_hours=2)
        # +2h offset means it's "16:00 in the user's body clock" → not yet sundown peak
        self.assertNotEqual(c_normal, c_shifted)

    def test_zero_offset_default(self):
        a = compute_circadian_c('senior', t(12))
        b = compute_circadian_c('senior', t(12), offset_hours=0)
        self.assertEqual(a, b)


class TestBoundaries(unittest.TestCase):
    def test_clamped_to_range(self):
        for hour in range(24):
            for persona in ('senior', 'child_adhd', 'child_autism'):
                c = compute_circadian_c(persona, t(hour))
                self.assertGreaterEqual(c, 0.0)
                self.assertLessEqual(c, 40.0)

    def test_unknown_persona_falls_back_senior(self):
        c_senior = compute_circadian_c('senior', t(18))
        c_unknown = compute_circadian_c('martian', t(18))
        self.assertEqual(c_senior, c_unknown)

    def test_three_curves_registered(self):
        for pid in ('senior', 'child_adhd', 'child_autism'):
            self.assertIn(pid, PERSONA_CURVES)
            self.assertTrue(callable(PERSONA_CURVES[pid]))


class TestHourOfDay(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_hour_of_day(t(15, 30)), 15.5)
        self.assertEqual(_hour_of_day(t(0, 0)), 0.0)

    def test_seconds_included(self):
        d = datetime(2026, 5, 10, 12, 30, 30)
        self.assertAlmostEqual(_hour_of_day(d), 12.508, places=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
