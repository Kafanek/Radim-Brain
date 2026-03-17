"""
🎵 RHYTHM RETURN DB — Database persistence for therapy sessions
===============================================================
Extracted from rhythm_return_routes.py for modularity.

Tables: rhythm_sessions, rhythm_states, rhythm_breakpoints

Version: 1.0.0
"""

import logging

logger = logging.getLogger(__name__)

# --- Database ---
try:
    from database import get_connection, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


def _db_save_session(session_id, user_id, preferred_bpm, hy_stage, notes):
    """Create new therapy session in DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_sessions (id, user_id, preferred_bpm, hy_stage, notes)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, user_id, preferred_bpm, hy_stage, notes)
        )
        db.commit()
        return True
    except Exception as e:
        logger.error(f"⚠️ rhythm session save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_save_state(session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json):
    """Save rhythm state snapshot to DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_states
               (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_pattern, confidence)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, M, tau, predicted_M, predicted_tau, state, bpm, accent_json, confidence_json)
        )
        db.commit()
        return True
    except Exception as e:
        logger.error(f"⚠️ rhythm state save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_save_breakpoint(session_id, bp_type, direction, M_before, M_after, action):
    """Save motor breakpoint event to DB"""
    if not _DB_AVAILABLE:
        return False
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        db.execute(
            f'''INSERT INTO rhythm_breakpoints (session_id, breakpoint_type, direction, M_before, M_after, action_taken)
               VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})''',
            (session_id, bp_type, direction, M_before, M_after, action)
        )
        db.commit()
        return True
    except Exception as e:
        logger.error(f"⚠️ rhythm breakpoint save error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def _db_get_session(session_id):
    """Load session with full state history"""
    if not _DB_AVAILABLE:
        return None
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'

        session = db.execute(
            f'SELECT * FROM rhythm_sessions WHERE id = {ph}', (session_id,)
        ).fetchone()
        if not session:
            return None

        states = db.execute(
            f'SELECT * FROM rhythm_states WHERE session_id = {ph} ORDER BY timestamp ASC LIMIT 1000', (session_id,)
        ).fetchall()

        breakpoints = db.execute(
            f'SELECT * FROM rhythm_breakpoints WHERE session_id = {ph} ORDER BY timestamp ASC LIMIT 500', (session_id,)
        ).fetchall()

        return {
            "session": dict(session),
            "states": [dict(s) for s in states],
            "breakpoints": [dict(b) for b in breakpoints]
        }
    except Exception as e:
        logger.error(f"⚠️ rhythm session load error: {e}")
        return None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


logger.info("✅ Rhythm Return DB loaded — session persistence")
