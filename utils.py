# ============================================
# SHARED UTILITIES — Centralized helpers
# ============================================
# Used across all blueprints. Import from here
# instead of redefining in each module.
# ============================================

import uuid
from datetime import datetime


def generate_id():
    """Generate a unique UUID string."""
    return str(uuid.uuid4())


def now_iso():
    """Return current UTC time in ISO 8601 format with Z suffix."""
    return datetime.utcnow().isoformat() + 'Z'


def today_date():
    """Return today's date as YYYY-MM-DD string."""
    return datetime.utcnow().strftime('%Y-%m-%d')
