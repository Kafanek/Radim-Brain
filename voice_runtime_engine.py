# ============================================
# RADIM VOICE RUNTIME ENGINE v1.0.0
# ============================================
# Math engine, session management, relevance classifier, echo detection.
# Extracted from voice_runtime_routes.py for modularity.
# ============================================

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================
# MATEMATICKÉ KONSTANTY (RADIM String Model)
# ============================================
PHI = 1.618033988749895      # Zlatý řez φ
DELTA = 2.414213562373095    # Stříbrný řez δ
RADIM_R = 3.906              # RADIM konstanta

# Fibonacci sekvence pro timing
FIBONACCI = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]

# Prahy pro stavy
THRESHOLD_HARMONY = 12       # C < 12 = HARMONIE
THRESHOLD_ALERT = 27         # 12 <= C < 27 = ALERT
# C >= 27 = KRIZE

# ============================================
# STAVOVÝ AUTOMAT
# ============================================
STATES = {
    'IDLE': 'idle',
    'WAKE_DETECTED': 'wake_detected',
    'LISTENING': 'listening',
    'THINKING': 'thinking',
    'SPEAKING': 'speaking'
}


# ============================================
# SESSION MANAGEMENT (cache + DB)
# ============================================

# Session storage: in-memory cache backed by PostgreSQL
# Max 200 sessions in memory; oldest evicted when exceeded
_sessions_cache = {}
_SESSION_CACHE_MAX = 200


def _evict_oldest_sessions():
    """Remove oldest sessions from cache when over limit."""
    if len(_sessions_cache) <= _SESSION_CACHE_MAX:
        return
    sorted_ids = sorted(
        _sessions_cache.keys(),
        key=lambda sid: _sessions_cache[sid].get('created', ''),
    )
    to_remove = len(_sessions_cache) - _SESSION_CACHE_MAX
    for sid in sorted_ids[:to_remove]:
        try:
            save_session(sid)
        except Exception as e:
            logger.warning(f"Session eviction save failed for {sid}: {e}")
        del _sessions_cache[sid]
    logger.info(f"Evicted {to_remove} oldest voice sessions from cache")


def _load_session_from_db(session_id):
    """Load session from DB, return dict or None.

    PostgreSQL folds unquoted identifiers to lowercase — actual column is `c`,
    not `"C"`. Use lowercase consistently across both backends.
    """
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                'SELECT state, c, kappa, alpha, last_tts_text, conversation, wake_count, created_at '
                'FROM voice_sessions WHERE session_id = ?',
                (session_id,)
            ).fetchone()
            if row:
                conv = row['conversation']
                if isinstance(conv, str):
                    conv = json.loads(conv)
                return {
                    'state': row['state'] or STATES['IDLE'],
                    'C': float(row['c'] or 5.0),
                    'kappa': float(row['kappa'] or 0.8),
                    'alpha': float(row['alpha'] or 0.0),
                    'last_tts_text': row['last_tts_text'] or '',
                    'conversation': conv if conv else [],
                    'wake_count': int(row['wake_count'] or 0),
                    'created': str(row['created_at'] or datetime.now().isoformat()),
                }
    except Exception as e:
        logger.warning(f"DB load session {session_id} (non-fatal): {e}")
    return None


def save_session(session_id):
    """Persist session to DB (call after key changes)."""
    session = _sessions_cache.get(session_id)
    if not session:
        return
    try:
        from database import is_postgres, db_context
        conv_json = json.dumps(session['conversation'][-50:])
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute(
                    'INSERT INTO voice_sessions (session_id, state, c, kappa, alpha, last_tts_text, conversation, wake_count, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) '
                    'ON CONFLICT (session_id) DO UPDATE SET '
                    'state=EXCLUDED.state, c=EXCLUDED.c, kappa=EXCLUDED.kappa, alpha=EXCLUDED.alpha, '
                    'last_tts_text=EXCLUDED.last_tts_text, conversation=EXCLUDED.conversation, '
                    'wake_count=EXCLUDED.wake_count, updated_at=CURRENT_TIMESTAMP',
                    (session_id, session['state'], session['C'], session['kappa'],
                     session['alpha'], session['last_tts_text'], conv_json, session['wake_count'])
                )
            else:
                db.execute(
                    'INSERT OR REPLACE INTO voice_sessions '
                    '(session_id, state, C, kappa, alpha, last_tts_text, conversation, wake_count, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                    (session_id, session['state'], session['C'], session['kappa'],
                     session['alpha'], session['last_tts_text'], conv_json, session['wake_count'])
                )
    except Exception as e:
        logger.warning(f"DB save session {session_id} (non-fatal): {e}")


def get_session(session_id):
    """Get or create session (cache + DB backed)."""
    if session_id not in _sessions_cache:
        _evict_oldest_sessions()
        db_session = _load_session_from_db(session_id)
        if db_session:
            _sessions_cache[session_id] = db_session
        else:
            try:
                from anticipation_routes import BASELINE_AMBIENT
                _bl = BASELINE_AMBIENT
            except ImportError:
                _bl = {'C': 5.0, 'alpha': 0.0}
            _sessions_cache[session_id] = {
                'state': STATES['IDLE'],
                'C': _bl['C'],
                'kappa': 0.8,
                'alpha': _bl['alpha'],
                'last_tts_text': '',
                'conversation': [],
                'wake_count': 0,
                'created': datetime.now().isoformat(),
            }
    return _sessions_cache[session_id]


# Legacy alias
sessions = _sessions_cache



# X21.29: removed the math engine (compute_C / compute_kappa / compute_alpha /
# get_system_state / get_tts_params), relevance classifier (RADIM_KEYWORDS,
# IGNORE_PATTERNS, compute_relevance), echo detector (compute_echo_similarity),
# and clean_for_tts() — all had zero external callers after voice_runtime_routes
# was retired in X21.28. The autonomous-agent path uses only the session-state
# helpers above (get_session / save_session / STATES / sessions cache).

logger.info("✅ Voice Runtime Engine loaded — math, sessions, relevance, echo, TTS cleaner")
