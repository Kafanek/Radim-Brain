"""
Unit tests for agent/federated.py — pure DP + blender logic, no DB.

Run: python3 -m agent.test_federated
"""
import unittest

try:
    from .federated import (
        apply_dp_noise, _laplace, _summary_stats, blend_baselines,
        K_ANONYMITY_MIN, DEFAULT_EPSILON, METRIC_SENSITIVITY,
        METRIC_GATHERERS, PERSONA_COHORTS,
    )
except ImportError:
    from federated import (  # type: ignore
        apply_dp_noise, _laplace, _summary_stats, blend_baselines,
        K_ANONYMITY_MIN, DEFAULT_EPSILON, METRIC_SENSITIVITY,
        METRIC_GATHERERS, PERSONA_COHORTS,
    )


class TestPrivacyConstants(unittest.TestCase):
    def test_k_anonymity_minimum(self):
        # We MUST have k≥5 to publish — anything lower is re-identifiable
        self.assertGreaterEqual(K_ANONYMITY_MIN, 5)

    def test_epsilon_in_strong_band(self):
        # ε=1.0 is the standard "strong privacy" baseline
        self.assertGreater(DEFAULT_EPSILON, 0)
        self.assertLessEqual(DEFAULT_EPSILON, 2.0)

    def test_three_persona_cohorts(self):
        self.assertEqual(set(PERSONA_COHORTS),
                         {'senior', 'child_autism', 'child_adhd'})

    def test_metric_sensitivities_present(self):
        # Every metric we aggregate must have a sensitivity bound
        for metric in METRIC_GATHERERS.keys():
            self.assertIn(metric, METRIC_SENSITIVITY,
                f"{metric} missing from METRIC_SENSITIVITY")


class TestLaplaceMechanism(unittest.TestCase):
    def test_zero_scale_returns_zero(self):
        self.assertEqual(_laplace(0), 0.0)

    def test_negative_scale_returns_zero(self):
        self.assertEqual(_laplace(-1), 0.0)

    def test_noise_distribution_centered(self):
        # Sample many times — average should approach 0 with scale=1.0
        import random as _r
        _r.seed(42)
        samples = [_laplace(1.0) for _ in range(2000)]
        avg = sum(samples) / len(samples)
        self.assertLess(abs(avg), 0.2,  # tight tolerance
            f"Laplace samples not centered: avg={avg}")

    def test_noise_scales_with_scale(self):
        import random as _r
        _r.seed(42)
        small = sum(abs(_laplace(0.1)) for _ in range(500)) / 500
        _r.seed(42)
        large = sum(abs(_laplace(10.0)) for _ in range(500)) / 500
        self.assertGreater(large, small * 50)  # 100× scale → ~100× spread


class TestApplyDpNoise(unittest.TestCase):
    def test_zero_sensitivity_returns_value(self):
        self.assertEqual(apply_dp_noise(5.0, 0, 1.0), 5.0)

    def test_zero_epsilon_returns_value(self):
        self.assertEqual(apply_dp_noise(5.0, 1.0, 0), 5.0)

    def test_none_returns_none(self):
        self.assertIsNone(apply_dp_noise(None, 1.0, 1.0))

    def test_higher_epsilon_less_noise(self):
        import random as _r
        _r.seed(42)
        low_eps_var = sum(abs(apply_dp_noise(10.0, 1.0, 0.1) - 10.0)
                          for _ in range(200)) / 200
        _r.seed(42)
        high_eps_var = sum(abs(apply_dp_noise(10.0, 1.0, 5.0) - 10.0)
                           for _ in range(200)) / 200
        # ε=5 should produce much less deviation than ε=0.1
        self.assertLess(high_eps_var, low_eps_var)


class TestSummaryStats(unittest.TestCase):
    def test_empty(self):
        s = _summary_stats([])
        self.assertIsNone(s['mean'])
        self.assertIsNone(s['std'])

    def test_single(self):
        s = _summary_stats([42.0])
        self.assertEqual(s['mean'], 42.0)
        self.assertEqual(s['std'], 0.0)
        self.assertEqual(s['p50'], 42.0)

    def test_known_values(self):
        s = _summary_stats([1, 2, 3, 4, 5])
        self.assertEqual(s['mean'], 3.0)
        self.assertEqual(s['p50'], 3)
        self.assertEqual(s['p25'], 2)
        self.assertEqual(s['p75'], 4)

    def test_std(self):
        # Known: variance of [1,2,3,4,5] (n-population) = 2.0, σ = √2
        s = _summary_stats([1, 2, 3, 4, 5])
        self.assertAlmostEqual(s['std'], 2 ** 0.5, places=4)


class TestBlendBaselines(unittest.TestCase):
    P = {'mean': 10.0, 'std': 2.0, 'p50': 9.0}
    Q = {'mean': 20.0, 'std': 5.0, 'p50': 19.0}

    def test_neither_returns_none(self):
        self.assertIsNone(blend_baselines(None, None))

    def test_only_personal(self):
        b = blend_baselines(self.P, None, days_of_personal_data=10)
        self.assertEqual(b['mean'], 10.0)

    def test_only_population(self):
        b = blend_baselines(None, self.Q, days_of_personal_data=10)
        self.assertEqual(b['mean'], 20.0)

    def test_cold_start_favors_population(self):
        # Day 0 — 0.20 personal, 0.80 population
        b = blend_baselines(self.P, self.Q, days_of_personal_data=0)
        # 0.20*10 + 0.80*20 = 18.0
        self.assertAlmostEqual(b['mean'], 18.0, places=2)
        self.assertEqual(b['_w_personal'], 0.20)

    def test_day_7_balanced(self):
        # Day 7 — 0.50 personal, 0.50 population
        b = blend_baselines(self.P, self.Q, days_of_personal_data=7)
        self.assertAlmostEqual(b['mean'], 15.0, places=2)
        self.assertEqual(b['_w_personal'], 0.50)

    def test_day_30_favors_personal(self):
        # Day 30+ — 0.90 personal, 0.10 population
        b = blend_baselines(self.P, self.Q, days_of_personal_data=30)
        # 0.90*10 + 0.10*20 = 11.0
        self.assertAlmostEqual(b['mean'], 11.0, places=2)
        self.assertEqual(b['_w_personal'], 0.90)

    def test_day_100_capped_at_30(self):
        b1 = blend_baselines(self.P, self.Q, days_of_personal_data=30)
        b2 = blend_baselines(self.P, self.Q, days_of_personal_data=100)
        self.assertEqual(b1['_w_personal'], b2['_w_personal'])

    def test_negative_days_treated_as_zero(self):
        b = blend_baselines(self.P, self.Q, days_of_personal_data=-5)
        self.assertEqual(b['_w_personal'], 0.20)

    def test_intermediate_days(self):
        # Day 14 — between 7 and 30 — should be linear interpolation
        b = blend_baselines(self.P, self.Q, days_of_personal_data=14)
        # w_personal = 0.50 + (7/23)*(0.90 - 0.50) ≈ 0.622
        self.assertAlmostEqual(b['_w_personal'], 0.622, places=2)

    def test_blends_all_quantiles(self):
        b = blend_baselines(
            {'mean': 10, 'p25': 8, 'p50': 10, 'p75': 12, 'std': 2},
            {'mean': 20, 'p25': 18, 'p50': 20, 'p75': 22, 'std': 5},
            days_of_personal_data=15,
        )
        for k in ('mean', 'std', 'p25', 'p50', 'p75'):
            self.assertIsNotNone(b[k])


class TestMetricGatherers(unittest.TestCase):
    def test_all_required_present(self):
        for required in ('avg_C', 'avg_chat_per_day', 'avg_motion_per_day'):
            self.assertIn(required, METRIC_GATHERERS)

    def test_all_callable(self):
        for metric, fn in METRIC_GATHERERS.items():
            self.assertTrue(callable(fn))


if __name__ == '__main__':
    unittest.main(verbosity=2)
