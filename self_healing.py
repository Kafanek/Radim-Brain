"""
🔄 RADIM SELF-HEALING ENGINE v1.0
===================================
Detects, decides, recovers — safely and predictably.

NOT autonomous chaos. Every recovery is:
- logged
- bounded (max 2 retries)
- safe (fallback to simpler, not riskier)
- human-escalatable

Failure types handled:
1. LLM failure → fallback model → safe static response
2. TTS failure → browser TTS fallback → text-only
3. STT failure → text input prompt
4. DB failure → in-memory cache → graceful degrade
5. API timeout → retry once → static response
6. Action failure → rollback + notify
7. Emotional misread → slow down + simplify

Philosophy: Better a simple correct response than a complex broken one.
"""

import logging
import time
import json
from datetime import datetime, timedelta
from functools import wraps

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

MAX_RETRIES = 2
RETRY_DELAY_MS = 500
CIRCUIT_BREAKER_THRESHOLD = 5  # failures before circuit opens
CIRCUIT_BREAKER_RESET_SEC = 300  # 5 min cooldown
ESCALATION_THRESHOLD = 3  # consecutive failures → escalate to human


# ============================================================================
# CIRCUIT BREAKER — prevents cascading failures
# ============================================================================

class CircuitBreaker:
    """Per-service circuit breaker. Opens after N failures, resets after cooldown."""

    def __init__(self, name, threshold=CIRCUIT_BREAKER_THRESHOLD, reset_sec=CIRCUIT_BREAKER_RESET_SEC):
        self.name = name
        self.threshold = threshold
        self.reset_sec = reset_sec
        self.failures = 0
        self.last_failure = 0
        self.state = 'closed'  # closed=OK, open=failing, half-open=testing

    def record_success(self):
        self.failures = 0
        self.state = 'closed'

    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            self.state = 'open'
            logger.warning(f"🔴 Circuit OPEN: {self.name} ({self.failures} failures)")

    def can_proceed(self):
        if self.state == 'closed':
            return True
        if self.state == 'open':
            if time.time() - self.last_failure > self.reset_sec:
                self.state = 'half-open'
                logger.info(f"🟡 Circuit HALF-OPEN: {self.name} (testing)")
                return True
            return False
        return True  # half-open: allow one test

    def get_status(self):
        return {'name': self.name, 'state': self.state, 'failures': self.failures}


# Global circuit breakers
_breakers = {
    'gemini': CircuitBreaker('gemini'),
    'claude': CircuitBreaker('claude'),
    'azure_tts': CircuitBreaker('azure_tts'),
    'azure_stt': CircuitBreaker('azure_stt'),
    'twilio': CircuitBreaker('twilio'),
    'database': CircuitBreaker('database', threshold=3, reset_sec=60),
}


def get_breaker(name):
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name)
    return _breakers[name]


# ============================================================================
# SAFE STATIC RESPONSES — when everything fails
# ============================================================================

SAFE_RESPONSES = {
    'default': 'Promiňte, zrovna mám technické potíže. Zkuste to prosím za chvilku.',
    'crisis': 'Jsem tu s vámi. Pokud potřebujete pomoc, zavolejte prosím na 155.',
    'greeting': 'Dobrý den! Jsem Radim, váš asistent. Momentálně se načítám, zkuste to za chvíli.',
    'understanding': 'Rozumím, že je to pro vás důležité. Můžete mi to říct jinak?',
    'tts_fail': 'Odpověď je připravena, ale hlas momentálně nefunguje. Přečtěte si text na obrazovce.',
}


# ============================================================================
# RETRY WITH FALLBACK — decorator
# ============================================================================

def with_retry(service_name, max_retries=MAX_RETRIES, fallback_fn=None):
    """Decorator: retry + circuit breaker + fallback.

    Usage:
        @with_retry('gemini', fallback_fn=call_claude_fallback)
        def call_gemini(prompt): ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            breaker = get_breaker(service_name)

            # Circuit open → skip to fallback
            if not breaker.can_proceed():
                logger.info(f"⚡ {service_name} circuit open, using fallback")
                if fallback_fn:
                    try:
                        return fallback_fn(*args, **kwargs)
                    except Exception:
                        pass
                return None

            # Try with retries
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    result = fn(*args, **kwargs)
                    breaker.record_success()
                    return result
                except Exception as e:
                    last_error = e
                    breaker.record_failure()
                    if attempt < max_retries:
                        time.sleep(RETRY_DELAY_MS / 1000)
                        logger.info(f"🔄 {service_name} retry {attempt+1}/{max_retries}: {e}")

            # All retries failed → fallback
            logger.warning(f"❌ {service_name} failed after {max_retries} retries: {last_error}")
            if fallback_fn:
                try:
                    return fallback_fn(*args, **kwargs)
                except Exception as e2:
                    logger.error(f"❌ {service_name} fallback also failed: {e2}")

            return None
        return wrapper
    return decorator


# ============================================================================
# EMOTIONAL SELF-HEALING — adapt when user is confused
# ============================================================================

_CONFUSION_SIGNALS = [
    'nerozumím', 'nechápu', 'co tím myslíš', 'co to znamená',
    'ještě jednou', 'zopakuj', 'pomaleji', 'nevím co',
    'jak to myslíš', 'nechci', 'přestaň', 'moc rychle',
    'co říkáš', 'špatně slyším', 'hlasitěji',
]

_STRESS_SIGNALS = [
    'bojím se', 'mám strach', 'nevím co dělat', 'pomoc',
    'je mi špatně', 'nechci být sám', 'jsem zmatený',
]


def detect_emotional_state(message):
    """Detect if user is confused, stressed, or needs simpler communication.

    Returns:
        dict: {confused: bool, stressed: bool, needs_simplification: bool,
               suggested_adjustments: list}
    """
    if not message:
        return {'confused': False, 'stressed': False, 'needs_simplification': False, 'suggested_adjustments': []}

    msg_lower = message.lower().strip()
    adjustments = []

    confused = any(sig in msg_lower for sig in _CONFUSION_SIGNALS)
    stressed = any(sig in msg_lower for sig in _STRESS_SIGNALS)

    if confused:
        adjustments.extend([
            'slow_down',           # Slower TTS rate
            'simplify_language',   # Shorter sentences
            'repeat_key_info',     # Say the important thing twice
            'ask_confirmation',    # "Rozuměli jste?"
        ])

    if stressed:
        adjustments.extend([
            'calm_tone',           # Empathetic voice style
            'short_sentences',     # Max 2 sentences
            'no_questions',        # Don't ask, just support
            'grounding',           # "Jsem tady s vámi"
        ])

    needs_simplification = confused or stressed

    return {
        'confused': confused,
        'stressed': stressed,
        'needs_simplification': needs_simplification,
        'suggested_adjustments': adjustments
    }


def apply_emotional_healing(text_response, emotional_state, speech_params=None):
    """Adjust response based on emotional state.

    Returns:
        tuple: (adjusted_text, adjusted_speech_params)
    """
    if not emotional_state.get('needs_simplification'):
        return text_response, speech_params or {}

    adjusted = text_response
    sp = dict(speech_params or {})

    if emotional_state.get('confused'):
        # Shorten: keep first 2 sentences
        sentences = [s.strip() for s in adjusted.replace('!', '.').replace('?', '.').split('.') if s.strip()]
        if len(sentences) > 2:
            adjusted = '. '.join(sentences[:2]) + '.'

        # Slow down speech
        sp['rate'] = min(sp.get('rate', 1.0), 0.8)
        sp['pause_ms'] = max(sp.get('pause_ms', 618), 1000)

    if emotional_state.get('stressed'):
        # Prepend grounding
        if not adjusted.startswith('Jsem'):
            adjusted = 'Jsem tady s vámi. ' + adjusted

        # Calm tone
        sp['style'] = 'calm'
        sp['rate'] = min(sp.get('rate', 1.0), 0.75)

    return adjusted, sp


# ============================================================================
# HEALTH CHECK — system self-diagnosis
# ============================================================================

def get_system_health():
    """Return health status of all subsystems."""
    health = {
        'timestamp': datetime.utcnow().isoformat(),
        'circuits': {name: b.get_status() for name, b in _breakers.items()},
        'overall': 'healthy'
    }

    open_circuits = [name for name, b in _breakers.items() if b.state == 'open']
    if open_circuits:
        health['overall'] = 'degraded'
        health['degraded_services'] = open_circuits

    critical_down = any(name in open_circuits for name in ['database', 'gemini'])
    if critical_down:
        health['overall'] = 'critical'

    return health


# ============================================================================
# SAFE RESPONSE BUILDER — when all else fails
# ============================================================================

def safe_response(intent='default', user_message='', is_crisis=False):
    """Build a safe static response when AI is unavailable.

    Always works. No external calls. No exceptions.
    """
    if is_crisis or any(w in (user_message or '').lower() for w in ['155', 'záchrank', 'nemůžu dýchat', 'bolí na hrudi']):
        return SAFE_RESPONSES['crisis']

    if any(w in (user_message or '').lower() for w in ['ahoj', 'dobrý den', 'čau']):
        return SAFE_RESPONSES['greeting']

    if any(w in (user_message or '').lower() for w in _CONFUSION_SIGNALS):
        return SAFE_RESPONSES['understanding']

    return SAFE_RESPONSES.get(intent, SAFE_RESPONSES['default'])


# ============================================================================
# LOG HEALING EVENT
# ============================================================================

def log_healing_event(event_type, service, details=None):
    """Log self-healing event for observability."""
    try:
        from database import db_context
        import json
        with db_context(commit=True) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS healing_events (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    service TEXT NOT NULL,
                    details JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute(
                "INSERT INTO healing_events (event_type, service, details) VALUES (?, ?, ?)",
                (event_type, service, json.dumps(details or {}, ensure_ascii=False))
            )
    except Exception:
        # Healing log failure must NEVER break the system
        pass

    logger.info(f"🔄 HEALING: {event_type} on {service} — {details}")


logger.info("🔄 Self-Healing Engine v1.0 loaded — circuit breakers, emotional healing, safe responses")
