"""
Unit tests for agent/audit.py

Pure-Python tests of the hash chain math + canonical JSON.
DB-backed tests would require a live PG/SQLite — skipped here; run them
in integration via the deployed /api/audit/verify endpoint.

Run: python3 -m agent.test_audit
"""
import unittest
from datetime import datetime, timezone

try:
    from .audit import (
        _canonical_json, _compute_entry_hash,
    )
except ImportError:
    from audit import _canonical_json, _compute_entry_hash  # type: ignore


class TestCanonicalJson(unittest.TestCase):
    def test_stable_ordering(self):
        a = {'b': 1, 'a': 2}
        b = {'a': 2, 'b': 1}
        self.assertEqual(_canonical_json(a), _canonical_json(b))

    def test_ascii_preserved(self):
        s = _canonical_json({'msg': 'Pán'})
        self.assertIn('Pán', s)  # ensure_ascii=False

    def test_separators_minified(self):
        s = _canonical_json({'a': 1, 'b': 2})
        self.assertNotIn(' ', s)  # tight separators

    def test_nested_stable(self):
        a = {'x': {'b': 1, 'a': 2}, 'y': [3, 1, 2]}
        b = {'y': [3, 1, 2], 'x': {'a': 2, 'b': 1}}
        self.assertEqual(_canonical_json(a), _canonical_json(b))


class TestEntryHash(unittest.TestCase):
    TS = '2026-05-09T16:00:00+00:00'

    def test_deterministic(self):
        h1 = _compute_entry_hash(None, '{"a":1}', self.TS, 'agent', 'observe', 'u1')
        h2 = _compute_entry_hash(None, '{"a":1}', self.TS, 'agent', 'observe', 'u1')
        self.assertEqual(h1, h2)

    def test_chain_propagation(self):
        # Chain: A → B → C
        h_a = _compute_entry_hash(None, '{"n":1}', self.TS, 'agent', 'a', 'u1')
        h_b = _compute_entry_hash(h_a,  '{"n":2}', self.TS, 'agent', 'a', 'u1')
        h_c = _compute_entry_hash(h_b,  '{"n":3}', self.TS, 'agent', 'a', 'u1')
        # Modifying B's payload changes C's expected hash
        h_b_tampered = _compute_entry_hash(h_a, '{"n":99}', self.TS, 'agent', 'a', 'u1')
        h_c_after_tamper = _compute_entry_hash(h_b_tampered, '{"n":3}', self.TS, 'agent', 'a', 'u1')
        self.assertNotEqual(h_c, h_c_after_tamper)

    def test_different_user_different_hash(self):
        h_a = _compute_entry_hash(None, '{"n":1}', self.TS, 'agent', 'a', 'u1')
        h_b = _compute_entry_hash(None, '{"n":1}', self.TS, 'agent', 'a', 'u2')
        self.assertNotEqual(h_a, h_b)

    def test_different_actor_different_hash(self):
        h_a = _compute_entry_hash(None, '{"n":1}', self.TS, 'agent', 'a', 'u1')
        h_b = _compute_entry_hash(None, '{"n":1}', self.TS, 'admin', 'a', 'u1')
        self.assertNotEqual(h_a, h_b)

    def test_payload_separator_safe(self):
        # Boundary attack: try to shift content from payload into ts via
        # well-placed |. Pipe separator + each field's own context should
        # block this.
        h_normal = _compute_entry_hash(None, '{"a":1}', self.TS, 'agent', 'observe', 'u1')
        # Attacker tries to encode a "merged" payload+ts but our hash
        # uses literal pipes between fields, so different decomposition
        # = different hash.
        h_attack = _compute_entry_hash(
            None, '{"a":1}|' + self.TS, '', 'agent', 'observe', 'u1')
        self.assertNotEqual(h_normal, h_attack)

    def test_hash_format(self):
        h = _compute_entry_hash(None, '{}', self.TS, 'agent', 'a', 'u1')
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in h))

    def test_null_prev_uses_zero_string(self):
        # First entry has prev=None → should be hashed deterministically
        h1 = _compute_entry_hash(None, '{}', self.TS, 'agent', 'a', 'u1')
        # Re-running gives the same hash
        h2 = _compute_entry_hash(None, '{}', self.TS, 'agent', 'a', 'u1')
        self.assertEqual(h1, h2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
