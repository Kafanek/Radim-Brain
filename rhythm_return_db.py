"""
RHYTHM RETURN DB v2.0 — Database persistence for therapy sessions
Extracted from rhythm_return_routes.py. Uses db_context + unified ? placeholders.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from database import db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


def _db_save_session(session_id, user_id, preferred_bpm, hy_stage, notes):
    """Create new therapy session in DB"""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO rhythm_sessions (id, user_id, preferred_bpm, hy_stage, notes) VALUES (?, ?, ?, ?, ?)",
                (session_id, user_id, preferred_bpm, hy_stage, notes)
            )
        return True
    except Exception as e:
        logger.error(f"rhythm session save error: {e}")
        return False


def _db_save_state(session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json):
    """Save rhythm state snapshot to DB"""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO rhythm_states (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_pattern, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json)
            )
        return True
    except Exception as e:
        logger.error(f"rhythm state save error: {e}")
        return False


def _db_save_breakpoint(session_id, bp_type, direction, M_before, M_after, action):
    """Save motor breakpoint event to DB"""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO rhythm_breakpoints (session_id, breakpoint_type, direction, M_before, M_after, action_taken) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, bp_type, direction, M_before, M_after, action)
            )
        return True
    except Exception as e:
        logger.error(f"rhythm breakpoint save error: {e}")
        return False


def _db_get_session(session_id):
    """Load session with full state history"""
    if not _DB_AVAILABLE:
        return None
    try:
        with db_context() as db:
            session = db.execute("SELECT * FROM rhythm_sessions WHERE id = ?", (session_id,)).fetchone()
            if not session:
                return None

            states = db.execute(
                "SELECT * FROM rhythm_states WHERE session_id = ? ORDER BY timestamp ASC LIMIT 1000", (session_id,)
            ).fetchall()

            breakpoints = db.execute(
                "SELECT * FROM rhythm_breakpoints WHERE session_id = ? ORDER BY timestamp ASC LIMIT 500", (session_id,)
            ).fetchall()

            return {
                "session": dict(session),
                "states": [dict(s) for s in states],
                "breakpoints": [dict(b) for b in breakpoints]
            }
    except Exception as e:
        logger.error(f"rhythm session load error: {e}")
        return None
