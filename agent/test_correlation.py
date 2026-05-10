"""
Unit tests for agent/correlation.py — pure stats + insight extraction.

Run: python3 -m agent.test_correlation
"""
import unittest
from datetime import datetime

try:
    from .correlation import (
        pearson, extract_insights, _strength_label, _make_insight_label,
        DOMAINS, _hour_bucket,
    )
except ImportError:
    from correlation import (  # type: ignore
        pearson, extract_insights, _strength_label, _make_insight_label,
        DOMAINS, _hour_bucket,
    )


class TestPearson(unittest.TestCase):
    def test_identity(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]), 1.0, places=4)

    def test_perfect_negative(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]), -1.0, places=4)

    def test_zero_correlation(self):
        # Symmetric around mean → r ≈ 0
        r = pearson([1, 2, 3, 4, 5], [3, 1, 4, 1, 3])
        self.assertIsNotNone(r)
        self.assertLess(abs(r), 0.5)

    def test_constant_series_returns_none(self):
        self.assertIsNone(pearson([1, 1, 1, 1], [1, 2, 3, 4]))
        self.assertIsNone(pearson([1, 2, 3, 4], [5, 5, 5, 5]))

    def test_different_lengths_returns_none(self):
        self.assertIsNone(pearson([1, 2, 3], [1, 2, 3, 4]))

    def test_too_short_returns_none(self):
        self.assertIsNone(pearson([1, 2], [1, 2]))
        self.assertIsNone(pearson([], []))

    def test_known_dataset(self):
        # Known textbook sample: r ≈ 0.927 for monotonic-ish ascending pair
        xs = [1, 2, 3, 4, 5, 6]
        ys = [2, 1, 4, 5, 5, 7]
        r = pearson(xs, ys)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r, 0.927, places=2)

    def test_handles_negative_values(self):
        r = pearson([-3, -2, -1, 0, 1, 2], [6, 4, 2, 0, -2, -4])
        self.assertAlmostEqual(r, -1.0, places=4)


class TestStrengthLabel(unittest.TestCase):
    def test_strong(self):
        self.assertEqual(_strength_label(0.7), 'silná')
        self.assertEqual(_strength_label(-0.95), 'silná')

    def test_medium(self):
        self.assertEqual(_strength_label(0.5), 'střední')
        self.assertEqual(_strength_label(-0.65), 'střední')

    def test_mild(self):
        self.assertEqual(_strength_label(0.3), 'mírná')
        self.assertEqual(_strength_label(-0.45), 'mírná')

    def test_weak(self):
        self.assertEqual(_strength_label(0.1), 'slabá')
        self.assertEqual(_strength_label(0.0), 'slabá')


class TestInsightLabel(unittest.TestCase):
    def test_positive_correlation_message(self):
        s = _make_insight_label('emotional', 'physical', 0.62)
        self.assertIn('Emoční pohoda', s)
        self.assertIn('pohybová aktivita', s)
        self.assertIn('+0.62', s)
        self.assertIn('společně', s)

    def test_negative_correlation_message(self):
        s = _make_insight_label('emotional', 'social', -0.45)
        self.assertIn('opačném', s)
        self.assertIn('-0.45', s)


class TestExtractInsights(unittest.TestCase):
    def _result(self, matrix, samples_per_pair=50):
        # Build samples dict matching matrix shape
        samples = {a: {b: samples_per_pair for b in DOMAINS} for a in DOMAINS}
        return {'matrix': matrix, 'samples': samples}

    def test_empty_matrix_returns_empty(self):
        self.assertEqual(extract_insights({}), [])
        self.assertEqual(extract_insights({'matrix': {}}), [])

    def test_filters_below_threshold(self):
        # All r=0.1 → below 0.3 threshold → empty
        matrix = {a: {b: 0.1 for b in DOMAINS} for a in DOMAINS}
        for a in DOMAINS:
            matrix[a][a] = 1.0
        ins = extract_insights(self._result(matrix))
        self.assertEqual(len(ins), 0)

    def test_filters_low_samples(self):
        # Strong correlation but only 5 samples → filtered out
        matrix = {a: {b: (0.8 if a != b else 1.0) for b in DOMAINS} for a in DOMAINS}
        ins = extract_insights(self._result(matrix, samples_per_pair=5))
        self.assertEqual(len(ins), 0)

    def test_returns_top_n(self):
        # All r=0.5 → all qualify, top_n=5 means we get 5 pairs
        matrix = {a: {b: (0.5 if a != b else 1.0) for b in DOMAINS} for a in DOMAINS}
        ins = extract_insights(self._result(matrix), top_n=5)
        self.assertEqual(len(ins), 5)

    def test_no_duplicate_pairs(self):
        matrix = {a: {b: (0.5 if a != b else 1.0) for b in DOMAINS} for a in DOMAINS}
        ins = extract_insights(self._result(matrix), top_n=99)
        # 6 dims → C(6,2) = 15 unique pairs
        self.assertEqual(len(ins), 15)

    def test_sorted_by_strength_desc(self):
        # Mixed: 0.8, 0.4, 0.6 — should sort 0.8 → 0.6 → 0.4
        matrix = {a: {b: 0 for b in DOMAINS} for a in DOMAINS}
        for a in DOMAINS:
            matrix[a][a] = 1.0
        matrix['emotional']['physical']  = 0.8
        matrix['physical']['emotional']  = 0.8
        matrix['emotional']['social']    = 0.4
        matrix['social']['emotional']    = 0.4
        matrix['environmental']['cognitive'] = 0.6
        matrix['cognitive']['environmental'] = 0.6
        ins = extract_insights(self._result(matrix), top_n=10)
        # First should be the 0.8 pair
        self.assertAlmostEqual(abs(ins[0]['r']), 0.8, places=2)
        self.assertAlmostEqual(abs(ins[1]['r']), 0.6, places=2)

    def test_negative_correlations_included(self):
        matrix = {a: {b: 0 for b in DOMAINS} for a in DOMAINS}
        for a in DOMAINS:
            matrix[a][a] = 1.0
        matrix['social']['emotional']    = -0.55
        matrix['emotional']['social']    = -0.55
        ins = extract_insights(self._result(matrix))
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]['direction'], 'negative')

    def test_threshold_param_respected(self):
        matrix = {a: {b: 0 for b in DOMAINS} for a in DOMAINS}
        matrix['emotional']['physical'] = 0.4
        matrix['physical']['emotional'] = 0.4
        # Default threshold 0.3 → included
        self.assertEqual(len(extract_insights(self._result(matrix))), 1)
        # Custom threshold 0.5 → excluded
        self.assertEqual(len(extract_insights(self._result(matrix), threshold=0.5)), 0)


class TestDomainsList(unittest.TestCase):
    def test_six_domains(self):
        self.assertEqual(set(DOMAINS), {'emotional', 'environmental', 'social',
                                        'physical', 'cognitive', 'circadian'})


class TestHourBucket(unittest.TestCase):
    def test_naive_datetime(self):
        b = _hour_bucket(datetime(2026, 5, 10, 14, 35, 22))
        self.assertEqual(b, datetime(2026, 5, 10, 14, 0, 0))

    def test_iso_string(self):
        b = _hour_bucket('2026-05-10T14:35:22+00:00')
        self.assertEqual(b.hour, 14)
        self.assertEqual(b.minute, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
