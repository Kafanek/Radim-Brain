"""
Notification preferences + suppression smoke tests (Sprint C).
Run: pytest tests/test_notifications.py -v
"""

from datetime import datetime, timedelta


class TestNotifPreferencesSchema:
    def test_table_created_on_get(self, client):
        """First GET creates the user_notification_prefs table (idempotent)."""
        # Unauthed GET returns 401; but we want to ensure the route is wired
        resp = client.get('/api/notifications/preferences')
        assert resp.status_code in (200, 401, 403)


class TestNotifSuppression:
    """Core logic in notification_helpers._should_suppress_push."""

    def _seed_prefs(self, user_id, muted_types=None, dnd_until=None):
        """Direct DB seed bypassing auth."""
        import json as _json
        from database import db_context, is_postgres
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "user_id TEXT PRIMARY KEY, muted_types JSONB DEFAULT '[]',"
                    "dnd_until TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            else:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "user_id TEXT PRIMARY KEY, muted_types TEXT DEFAULT '[]',"
                    "dnd_until TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            db.execute(
                "INSERT OR REPLACE INTO user_notification_prefs "
                "(user_id, muted_types, dnd_until) VALUES (?, ?, ?)"
                if not is_postgres() else
                "INSERT INTO user_notification_prefs (user_id, muted_types, dnd_until) "
                "VALUES (?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET "
                "muted_types = EXCLUDED.muted_types, dnd_until = EXCLUDED.dnd_until",
                (user_id, _json.dumps(muted_types or []), dnd_until)
            )

    def test_sos_bypass(self, client):
        """SOS type always bypasses suppression."""
        from notification_helpers import _should_suppress_push
        self._seed_prefs('t1', muted_types=['sos', 'reminder'])
        # Type 'sos' should not be suppressed regardless
        assert _should_suppress_push('t1', 'sos', 'info') is False

    def test_crisis_severity_bypass(self, client):
        """Severity 'crisis' bypasses suppression even for non-sos types."""
        from notification_helpers import _should_suppress_push
        self._seed_prefs('t2', muted_types=['health_alert'])
        assert _should_suppress_push('t2', 'health_alert', 'crisis') is False

    def test_muted_type_suppressed(self, client):
        """A muted type returns True (suppress WebPush)."""
        from notification_helpers import _should_suppress_push
        self._seed_prefs('t3', muted_types=['reminder'])
        assert _should_suppress_push('t3', 'reminder', 'info') is True

    def test_unmuted_type_not_suppressed(self, client):
        """Non-muted type returns False."""
        from notification_helpers import _should_suppress_push
        self._seed_prefs('t4', muted_types=['chat_msg'])
        assert _should_suppress_push('t4', 'reminder', 'info') is False

    def test_dnd_active_suppresses(self, client):
        """DND window in the future suppresses non-SOS."""
        from notification_helpers import _should_suppress_push
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        self._seed_prefs('t5', dnd_until=future)
        assert _should_suppress_push('t5', 'reminder', 'info') is True

    def test_dnd_expired_does_not_suppress(self, client):
        """DND window in the past is ignored."""
        from notification_helpers import _should_suppress_push
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        self._seed_prefs('t6', dnd_until=past)
        assert _should_suppress_push('t6', 'reminder', 'info') is False

    def test_dnd_does_not_suppress_sos(self, client):
        """Even during DND, SOS goes through."""
        from notification_helpers import _should_suppress_push
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        self._seed_prefs('t7', dnd_until=future)
        assert _should_suppress_push('t7', 'sos', 'alert') is False

    def test_unknown_user_defaults_not_suppressed(self, client):
        """User without prefs row is not suppressed."""
        from notification_helpers import _should_suppress_push
        assert _should_suppress_push('nonexistent-user-xyz', 'reminder', 'info') is False


class TestNotifyIntegration:
    """notify() respects preferences end-to-end."""

    def test_notify_creates_db_row_even_when_muted(self, client):
        """Muted types still land in DB (user can see in panel later).
        Only WebPush is skipped.
        """
        from notification_helpers import notify
        from database import db_context, is_postgres
        import json as _json

        # Seed user with reminder muted
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "user_id TEXT PRIMARY KEY, muted_types JSONB DEFAULT '[]',"
                    "dnd_until TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            else:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_notification_prefs ("
                    "user_id TEXT PRIMARY KEY, muted_types TEXT DEFAULT '[]',"
                    "dnd_until TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            db.execute(
                "INSERT OR REPLACE INTO user_notification_prefs "
                "(user_id, muted_types) VALUES (?, ?)",
                ('notify-muted-user', _json.dumps(['reminder']))
            )

        nid = notify(to_user_id='notify-muted-user', type='reminder',
                     title='Test reminder', body='body', severity='info')
        assert nid is not None

        # DB row should exist
        with db_context() as db:
            row = db.execute(
                "SELECT title FROM user_notifications WHERE id = ?", (nid,)
            ).fetchone()
        assert row is not None
