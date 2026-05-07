"""
Shared pytest fixtures for Kolibri app tests.
Uses SQLite temp file for isolation (no Heroku PG needed).
"""

import os
import sys
import tempfile
import pytest

# Force SQLite mode for tests
os.environ.pop('DATABASE_URL', None)
_test_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_test_db.close()
os.environ['DATABASE_PATH'] = _test_db.name

# Disable HA WebSocket supervisor — tests don't need real HA connections
os.environ.setdefault('DISABLE_HA_WS', '1')
# Stable Fernet key for token encryption tests (test only — not a real secret)
os.environ.setdefault(
    'HA_TOKEN_ENCRYPTION_KEY',
    'oNDYTq18C8qhGfgW-Uqj7Lm5M5yMFysR0ZTTF4fekBo='
)

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope='session')
def app():
    """Create Flask app for testing."""
    from app import app as flask_app

    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False

    yield flask_app

    try:
        os.unlink(_test_db.name)
    except OSError:
        pass


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
