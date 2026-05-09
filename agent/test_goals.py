"""
Unit tests for agent/goals.py + agent/planner.py — pure logic, no DB.

Run: python3 -m agent.test_goals
"""
import unittest

try:
    from .goals import (
        GOAL_MEASURES, list_goal_types, default_goals_for_persona,
        PERSONA_DEFAULT_GOALS,
    )
    from .planner import _severity_from_curve, _message_for_drift, SEVERITY_CURVE
except ImportError:
    from goals import (  # type: ignore
        GOAL_MEASURES, list_goal_types, default_goals_for_persona,
        PERSONA_DEFAULT_GOALS,
    )
    from planner import _severity_from_curve, _message_for_drift, SEVERITY_CURVE  # type: ignore


class TestGoalRegistry(unittest.TestCase):
    def test_four_canonical_goals_present(self):
        for required in ['daily_social_contact', 'sleep_quality',
                         'environment_comfort', 'medication_compliance']:
            self.assertIn(required, GOAL_MEASURES,
                f"Missing canonical goal type {required!r}")

    def test_all_measures_callable(self):
        for goal_type, fn in GOAL_MEASURES.items():
            self.assertTrue(callable(fn),
                f"{goal_type} measure is not callable")

    def test_list_goal_types_sorted(self):
        types = list_goal_types()
        self.assertEqual(types, sorted(types))


class TestPersonaDefaults(unittest.TestCase):
    def test_three_personas_have_defaults(self):
        for pid in ('senior', 'child_autism', 'child_adhd'):
            self.assertIn(pid, PERSONA_DEFAULT_GOALS)
            self.assertGreater(len(PERSONA_DEFAULT_GOALS[pid]), 0)

    def test_each_default_has_required_fields(self):
        for pid, goals in PERSONA_DEFAULT_GOALS.items():
            for g in goals:
                self.assertIn('goal_type', g, f"{pid} goal missing goal_type")
                self.assertIn('target', g)
                self.assertIn(g['goal_type'], GOAL_MEASURES)

    def test_defensive_copy(self):
        a = default_goals_for_persona('senior')
        a[0]['target']['min_per_day'] = 999
        b = default_goals_for_persona('senior')
        # Modifying returned copy should not leak into next call
        self.assertNotEqual(b[0]['target'].get('min_per_day'), 999)

    def test_unknown_persona_falls_back_to_senior(self):
        a = default_goals_for_persona('martian')
        b = default_goals_for_persona('senior')
        self.assertEqual(len(a), len(b))

    def test_autism_higher_env_strictness(self):
        senior_env = next((g for g in default_goals_for_persona('senior')
                           if g['goal_type'] == 'environment_comfort'), None)
        autism_env = next((g for g in default_goals_for_persona('child_autism')
                           if g['goal_type'] == 'environment_comfort'), None)
        if senior_env and autism_env:
            # Autism: tighter temp band, higher in-band requirement
            self.assertGreaterEqual(autism_env['target']['min_in_band_pct'],
                                    senior_env['target']['min_in_band_pct'])


class TestSeverityCurve(unittest.TestCase):
    def test_first_drift_info(self):
        self.assertEqual(_severity_from_curve(1, 'sleep_quality'), 'INFO')

    def test_second_drift_warning(self):
        self.assertEqual(_severity_from_curve(2, 'sleep_quality'), 'WARNING')

    def test_third_drift_alert(self):
        self.assertEqual(_severity_from_curve(3, 'sleep_quality'), 'ALERT')

    def test_fifth_drift_still_alert(self):
        self.assertEqual(_severity_from_curve(5, 'sleep_quality'), 'ALERT')

    def test_zero_drift_info(self):
        self.assertEqual(_severity_from_curve(0, 'sleep_quality'), 'INFO')

    def test_medication_skips_curve(self):
        # Medication compliance is critical — first miss already ALERT
        self.assertEqual(_severity_from_curve(1, 'medication_compliance'), 'ALERT')
        self.assertEqual(_severity_from_curve(2, 'medication_compliance'), 'ALERT')


class TestDriftMessages(unittest.TestCase):
    def test_social_message_in_czech(self):
        m = _message_for_drift(
            'daily_social_contact',
            {'value': 0, 'horizon_hours': 24, 'detail': {}},
            'WARNING',
        )
        self.assertIn('interakcí', m)

    def test_sleep_message(self):
        m = _message_for_drift(
            'sleep_quality',
            {'value': 50, 'horizon_hours': 24,
             'detail': {'motion_events': 50}},
            'INFO',
        )
        self.assertIn('pohybu', m)

    def test_env_message_includes_pct(self):
        m = _message_for_drift(
            'environment_comfort',
            {'value': 65.5, 'horizon_hours': 24,
             'detail': {'min_in_band_pct': 80}},
            'WARNING',
        )
        self.assertIn('65.5', m)
        self.assertIn('80', m)

    def test_medication_message(self):
        m = _message_for_drift(
            'medication_compliance',
            {'value': 60.0, 'horizon_hours': 168,
             'detail': {'min_required': 80}},
            'ALERT',
        )
        self.assertIn('60', m)


class TestSeverityCurveContents(unittest.TestCase):
    def test_curve_keys(self):
        self.assertEqual(set(SEVERITY_CURVE.keys()), {1, 2, 3})

    def test_curve_severity_order(self):
        # INFO < WARNING < ALERT progression
        order = ['INFO', 'WARNING', 'ALERT']
        for i, expected in enumerate(order, start=1):
            self.assertEqual(SEVERITY_CURVE[i], expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
