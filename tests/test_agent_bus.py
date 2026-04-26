"""Sprint AG.4 tests for agent_bus.py — bus core ops."""

import os
import sys
import time
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

# Use SQLite for tests — bus must work on either backend.
os.environ['FORCE_SQLITE'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup_temp_db():
    """Initialise a fresh SQLite with the AG.4 + AG-1 tables."""
    from database import init_db
    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    os.environ['SQLITE_DB_PATH'] = path
    # database.py reads env var lazily — re-import
    init_db()
    return path


class TestAgentBus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = _setup_temp_db()

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    def setUp(self):
        # Wipe between tests
        from database import db_context
        with db_context(commit=True) as db:
            db.execute("DELETE FROM agent_messages")
            db.execute("DELETE FROM agent_observations")

    # ── emit + recent ──────────────────────────────────────
    def test_emit_returns_id(self):
        from agent_bus import emit
        mid = emit('user_a', 'safety_agent', 'observation', 'crisis',
                   'fall', payload={'C': 30, 'message': 'spadl jsem'})
        self.assertIsNotNone(mid)
        self.assertIsInstance(mid, int)

    def test_emit_observation_mirrors_agent_observations(self):
        from agent_bus import emit
        from database import db_context
        emit('user_b', 'agent_loop', 'observation', 'alert', 'isolation',
             payload={'message': 'isolation 12h'})
        with db_context() as db:
            rows = db.execute(
                "SELECT user_id, observation_type, severity, message "
                "FROM agent_observations WHERE user_id = ?",
                ('user_b',)
            ).fetchall()
        self.assertEqual(len(rows), 1)
        # Mirror ok regardless of column-row representation
        self.assertEqual(rows[0][0], 'user_b')
        self.assertEqual(rows[0][1], 'isolation')

    def test_emit_non_observation_does_not_mirror(self):
        from agent_bus import emit
        from database import db_context
        emit('user_c', 'chat_input', 'user_input', 'info', 'weather_query')
        with db_context() as db:
            rows = db.execute(
                "SELECT COUNT(*) FROM agent_observations WHERE user_id = ?",
                ('user_c',)
            ).fetchone()
        self.assertEqual(rows[0], 0)

    def test_recent_returns_newest_first(self):
        from agent_bus import emit, recent
        emit('user_d', 'a1', 'context', 'info', 't1')
        time.sleep(0.01)
        emit('user_d', 'a2', 'context', 'info', 't2')
        rows = recent('user_d', limit=10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['topic'], 't2')
        self.assertEqual(rows[1]['topic'], 't1')

    def test_recent_filters_by_kind(self):
        from agent_bus import emit, recent
        emit('user_e', 's1', 'observation', 'crisis', 'fall')
        emit('user_e', 's2', 'user_input', 'info', 'chat')
        obs = recent('user_e', kinds=['observation'])
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]['topic'], 'fall')

    def test_recent_filters_by_severity_min(self):
        from agent_bus import emit, recent
        emit('user_f', 's1', 'observation', 'info', 't_info')
        emit('user_f', 's2', 'observation', 'crisis', 't_crisis')
        warn_or_above = recent('user_f', severity_min='warning')
        self.assertEqual(len(warn_or_above), 1)
        self.assertEqual(warn_or_above[0]['topic'], 't_crisis')

    # ── context (high-signal subset) ────────────────────────
    def test_context_includes_observations_and_high_severity(self):
        from agent_bus import emit, context
        emit('user_g', 's1', 'observation', 'info', 'obs_topic')
        emit('user_g', 's2', 'context', 'crisis', 'context_topic')
        emit('user_g', 's3', 'context', 'info', 'low_severity_skipped')
        ctx = context('user_g')
        topics = sorted(c['topic'] for c in ctx)
        self.assertEqual(topics, ['context_topic', 'obs_topic'])

    # ── dedupe ──────────────────────────────────────────────
    def test_dedupe_finds_existing(self):
        from agent_bus import emit, dedupe
        emit('user_h', 'safety', 'observation', 'crisis', 'fall')
        self.assertTrue(dedupe('user_h', 'safety', 'fall'))

    def test_dedupe_any_sender(self):
        from agent_bus import emit, dedupe
        emit('user_i', 'agent_loop', 'observation', 'crisis', 'fall')
        # Different sender — should be detected with any_sender=True
        self.assertFalse(dedupe('user_i', 'safety', 'fall'))
        self.assertTrue(dedupe('user_i', None, 'fall', any_sender=True))

    def test_dedupe_different_topic_does_not_match(self):
        from agent_bus import emit, dedupe
        emit('user_j', 'safety', 'observation', 'crisis', 'fall')
        self.assertFalse(dedupe('user_j', 'safety', 'fire'))

    # ── prune ───────────────────────────────────────────────
    def test_prune_deletes_expired(self):
        from agent_bus import emit, prune, recent
        from database import db_context
        emit('user_k', 's1', 'context', 'info', 'fresh')
        # Fake expired row — use SAME format as emit (strftime, not isoformat)
        # so SQLite TEXT comparison with datetime('now') in prune works.
        with db_context(commit=True) as db:
            past = (datetime.utcnow() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
            db.execute(
                "INSERT INTO agent_messages "
                "(user_id, sender, kind, severity, topic, payload, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('user_k', 's_old', 'context', 'info', 'expired', '{}', past)
            )
        # Count BEFORE prune
        with db_context() as db:
            before = db.execute(
                "SELECT COUNT(*) FROM agent_messages WHERE user_id = ?",
                ('user_k',)
            ).fetchone()[0]
        prune()  # rowcount on some drivers returns -1 → don't trust return value
        with db_context() as db:
            after = db.execute(
                "SELECT COUNT(*) FROM agent_messages WHERE user_id = ?",
                ('user_k',)
            ).fetchone()[0]
        self.assertGreater(before, after)
        rows = recent('user_k')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['topic'], 'fresh')

    # ── format_for_prompt ───────────────────────────────────
    def test_format_for_prompt_renders(self):
        from agent_bus import emit, recent, format_for_prompt
        emit('user_l', 'safety', 'observation', 'crisis', 'fall',
             payload={'message': 'spadl jsem'})
        rows = recent('user_l')
        out = format_for_prompt(rows)
        self.assertIn('CRISIS', out)
        self.assertIn('fall', out)
        self.assertIn('safety', out)


if __name__ == '__main__':
    unittest.main()
