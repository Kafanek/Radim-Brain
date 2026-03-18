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
    """Load session from DB, return dict or None."""
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                'SELECT state, "C", kappa, alpha, last_tts_text, conversation, wake_count, created_at '
                'FROM voice_sessions WHERE session_id = ?',
                (session_id,)
            ).fetchone()
            if row:
                conv = row['conversation']
                if isinstance(conv, str):
                    conv = json.loads(conv)
                return {
                    'state': row['state'] or STATES['IDLE'],
                    'C': float(row['C'] or 5.0),
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
                    'INSERT INTO voice_sessions (session_id, state, "C", kappa, alpha, last_tts_text, conversation, wake_count, updated_at) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) '
                    'ON CONFLICT (session_id) DO UPDATE SET '
                    'state=EXCLUDED.state, "C"=EXCLUDED."C", kappa=EXCLUDED.kappa, alpha=EXCLUDED.alpha, '
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


# ============================================
# MATEMATICKÝ ENGINE
# ============================================

def compute_C(sensors: dict, bio: dict) -> float:
    """
    Výpočet C(t) - míra zatížení systému

    Vstupy:
    - sensors: {noise, light, temperature, motion}
    - bio: {heart_rate, stress_indicator, activity}
    """
    C = 5.0

    noise = sensors.get('noise', 30)
    light = sensors.get('light', 50)
    temp = sensors.get('temperature', 22)

    hr = bio.get('heart_rate', 70)
    stress = bio.get('stress_indicator', 0.3)

    if noise > 60:
        C += (noise - 60) * 0.3
    if light < 20 or light > 80:
        C += abs(50 - light) * 0.1
    if temp < 18 or temp > 26:
        C += abs(22 - temp) * 0.5

    if hr > 90:
        C += (hr - 90) * 0.2
    C += stress * 15

    return min(max(C, 0), 50)


def compute_kappa(C: float, alpha: float, prev_kappa: float) -> float:
    """
    Výpočet κ(t) - koherence systému
    κ(t+1) = κ(t) + f(α) - g(C)
    """
    f = alpha * PHI * 0.1
    g = (C / 50) * 0.15
    kappa = prev_kappa + f - g
    return min(max(kappa, 0), 1)


def compute_alpha(state: str, user_intent: str) -> float:
    """Výpočet α(t) - regulační zásah"""
    base_alpha = 0.0

    if state == 'HARMONIE':
        base_alpha = 0.1
    elif state == 'ALERT':
        base_alpha = 0.5
    elif state == 'KRIZE':
        base_alpha = 1.0

    if 'pomoc' in user_intent.lower() or 'help' in user_intent.lower():
        base_alpha += 0.3
    if 'uklidni' in user_intent.lower() or 'relax' in user_intent.lower():
        base_alpha += 0.2

    return min(base_alpha, 1.0)


def get_system_state(C: float) -> str:
    """Určení stavu systému podle C"""
    if C < THRESHOLD_HARMONY:
        return 'HARMONIE'
    elif C < THRESHOLD_ALERT:
        return 'ALERT'
    else:
        return 'KRIZE'


def get_tts_params(system_state: str) -> dict:
    """Parametry TTS podle stavu"""
    if system_state == 'HARMONIE':
        return {
            'rate': 1.0,
            'pitch': '+0Hz',
            'style': 'friendly',
            'max_sentences': 5,
            'pause_ms': int(1000 * (1 / PHI))  # ~618ms
        }
    elif system_state == 'ALERT':
        return {
            'rate': 0.85,
            'pitch': '-5Hz',
            'style': 'calm',
            'max_sentences': 3,
            'pause_ms': int(1000 * 1)  # 1000ms
        }
    else:  # KRIZE
        return {
            'rate': 0.7,
            'pitch': '-10Hz',
            'style': 'soothing',
            'max_sentences': 1,
            'pause_ms': int(1000 * PHI)  # ~1618ms
        }


# ============================================
# RELEVANCE CLASSIFIER
# ============================================

RADIM_KEYWORDS = [
    'radim', 'radime', 'ahoj', 'pomoc', 'help',
    'počasí', 'weather', 'čas', 'time', 'datum', 'date',
    'připomeň', 'remind', 'nastav', 'set',
    'zavolej', 'call', 'zpráva', 'message',
    'světlo', 'light', 'teplota', 'temperature',
    'televize', 'tv', 'rádio', 'radio',
    'léky', 'medicine', 'doktor', 'doctor',
    'jídlo', 'food', 'pití', 'drink',
    'cvičení', 'exercise', 'procházka', 'walk',
    'rodina', 'family', 'vnuk', 'vnučka',
    'sos', 'emergency', 'nouzové', 'bolest', 'pain'
]

IGNORE_PATTERNS = [
    'reklama', 'advertisement', 'sponzor',
    'předpověď počasí na obrazovce',
    'zprávy dne', 'news of the day'
]


def compute_relevance(text: str, context: dict = None) -> float:
    """Výpočet relevance dotazu pro Radima (0.0-1.0)"""
    text_lower = text.lower()
    score = 0.0

    if 'radim' in text_lower or 'radime' in text_lower:
        score += 0.5

    keyword_hits = sum(1 for kw in RADIM_KEYWORDS if kw in text_lower)
    score += min(keyword_hits * 0.15, 0.4)

    for pattern in IGNORE_PATTERNS:
        if pattern in text_lower:
            score -= 0.3

    words = text.split()
    if 2 <= len(words) <= 10:
        score += 0.1

    if len(words) > 30:
        score -= 0.2

    return max(0.0, min(1.0, score))


# ============================================
# ECHO SIMILARITY (AEC)
# ============================================

def compute_echo_similarity(text: str, last_tts: str) -> float:
    """Detekce echo - Jaccard similarity s posledním TTS (>0.75 = echo)"""
    if not last_tts:
        return 0.0

    text_words = set(text.lower().split())
    tts_words = set(last_tts.lower().split())

    if not tts_words:
        return 0.0

    intersection = text_words & tts_words
    union = text_words | tts_words

    if not union:
        return 0.0

    return len(intersection) / len(union)


# ============================================
# TTS TEXT CLEANER
# ============================================

def clean_for_tts(text):
    """Vyčistit text pro TTS (remove emoji, markdown)"""
    import re
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001F900-\U0001F9FF"
        u"\U00002600-\U000026FF"
        u"\U00002700-\U000027BF"
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub('', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\*\-]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


logger.info("✅ Voice Runtime Engine loaded — math, sessions, relevance, echo, TTS cleaner")
