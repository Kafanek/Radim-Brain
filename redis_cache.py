"""
Redis cache wrapper — shared across Heroku dynos.

Cíl: jednotná, bezpečná abstrakce nad Heroku Redis (REDIS_URL env var).
Fail-open: pokud Redis selže (down, timeout, network), funkce vrátí None
a aplikace pokračuje bez cache. Žádné výjimky neúnikne ven.

Použití:
    from redis_cache import cache_get_json, cache_set_json, cache_get_bytes,
                            cache_set_bytes, cache_delete, cache_health

    user = cache_get_json(f"profile:{uid}")
    if not user:
        user = db_load_profile(uid)
        cache_set_json(f"profile:{uid}", user, ttl=300)  # 5 min

Klíčové konvence:
    profile:<uid>           — user profile (TTL 5 min)
    brain_speech:<uid>      — brain Ψ(t) result (TTL 30 s)
    tts:<key>               — TTS audio bytes (TTL 24 h)
    ai_response:<hash>      — AI response cache (TTL 5 min)
    rate_limit:<ip>:<bucket> — sliding window rate limits (TTL 60 s)
"""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# ─── Connection ──────────────────────────────────────────────────────────

_client = None
_available = False
_last_check = 0
_CHECK_INTERVAL = 30  # re-check Redis health every 30s

# Lazy-init: importovat redis-py jen při prvním použití
def _get_client():
    global _client, _available, _last_check
    now = time.time()

    # Fast path — already initialized and recently checked
    if _client and _available and (now - _last_check) < _CHECK_INTERVAL:
        return _client

    # Re-check or first init
    redis_url = os.environ.get('REDIS_URL') or os.environ.get('REDIS_TLS_URL')
    if not redis_url:
        if _available:  # Was up, now URL gone
            logger.warning("⚡ Redis: REDIS_URL no longer set — disabling cache")
        _available = False
        _client = None
        _last_check = now
        return None

    try:
        import redis
        if _client is None:
            # rediss:// (TLS) is auto-handled by redis-py >=5
            _client = redis.from_url(
                redis_url,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
                decode_responses=False,  # keep raw bytes for binary support
                health_check_interval=30,
                ssl_cert_reqs=None,  # Heroku Redis Mini self-signed cert
            )
        _client.ping()
        if not _available:
            logger.info("⚡ Redis: connected (or reconnected)")
        _available = True
        _last_check = now
        return _client
    except Exception as e:
        if _available:  # Was up, now down
            logger.warning(f"⚡ Redis: lost connection — {e}")
        _available = False
        _last_check = now
        return None


# ─── Public API ──────────────────────────────────────────────────────────

def is_available():
    """Quick check whether Redis is currently reachable."""
    return _get_client() is not None


def cache_get_json(key):
    """Get JSON-encoded value. Returns dict/list/None."""
    c = _get_client()
    if not c:
        return None
    try:
        raw = c.get(key)
        if raw is None:
            return None
        return json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    except Exception as e:
        logger.debug(f"⚡ Redis get_json({key[:30]}) error: {e}")
        return None


def cache_set_json(key, value, ttl=300):
    """Set JSON-encoded value with TTL (seconds). Returns True on success."""
    c = _get_client()
    if not c:
        return False
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')
        c.setex(key, ttl, encoded)
        return True
    except Exception as e:
        logger.debug(f"⚡ Redis set_json({key[:30]}) error: {e}")
        return False


def cache_get_bytes(key):
    """Get raw bytes (for audio MP3, etc.). Returns bytes/None."""
    c = _get_client()
    if not c:
        return None
    try:
        return c.get(key)
    except Exception as e:
        logger.debug(f"⚡ Redis get_bytes({key[:30]}) error: {e}")
        return None


def cache_set_bytes(key, value_bytes, ttl=86400):
    """Set raw bytes with TTL (default 24 h). Returns True on success."""
    c = _get_client()
    if not c:
        return False
    try:
        # Mini plan = 25 MB total, large MP3 (>500 KB) skip to avoid eviction storms
        if len(value_bytes) > 500 * 1024:
            logger.debug(f"⚡ Redis: skipping {key[:30]} — too big ({len(value_bytes)} bytes)")
            return False
        c.setex(key, ttl, value_bytes)
        return True
    except Exception as e:
        logger.debug(f"⚡ Redis set_bytes({key[:30]}) error: {e}")
        return False


def cache_delete(key):
    """Delete a key. Returns True if deleted, False on error."""
    c = _get_client()
    if not c:
        return False
    try:
        c.delete(key)
        return True
    except Exception as e:
        logger.debug(f"⚡ Redis delete({key[:30]}) error: {e}")
        return False


def cache_delete_pattern(pattern):
    """Delete all keys matching pattern (e.g. 'profile:*'). Use sparingly."""
    c = _get_client()
    if not c:
        return 0
    try:
        # SCAN is non-blocking, safer than KEYS on production
        deleted = 0
        for key in c.scan_iter(match=pattern, count=100):
            c.delete(key)
            deleted += 1
        return deleted
    except Exception as e:
        logger.debug(f"⚡ Redis delete_pattern({pattern}) error: {e}")
        return 0


def cache_incr(key, ttl=60):
    """Atomic counter — useful for rate limits. Returns new value or None."""
    c = _get_client()
    if not c:
        return None
    try:
        pipe = c.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl)
        results = pipe.execute()
        return int(results[0])
    except Exception as e:
        logger.debug(f"⚡ Redis incr({key[:30]}) error: {e}")
        return None


def cache_health():
    """Return health snapshot for /api/cache/stats endpoint."""
    c = _get_client()
    if not c:
        return {
            'available': False,
            'reason': 'REDIS_URL not set' if not os.environ.get('REDIS_URL') else 'connection failed',
        }
    try:
        info = c.info(section='memory')
        stats = c.info(section='stats')
        return {
            'available': True,
            'used_memory_human': info.get('used_memory_human'),
            'used_memory_peak_human': info.get('used_memory_peak_human'),
            'maxmemory_human': info.get('maxmemory_human') or 'unlimited',
            'connected_clients': c.info('clients').get('connected_clients'),
            'total_commands_processed': stats.get('total_commands_processed'),
            'keyspace_hits': stats.get('keyspace_hits', 0),
            'keyspace_misses': stats.get('keyspace_misses', 0),
            'hit_ratio': (
                stats.get('keyspace_hits', 0) /
                max(1, stats.get('keyspace_hits', 0) + stats.get('keyspace_misses', 0))
            ),
        }
    except Exception as e:
        return {'available': False, 'error': str(e)}


# Initialize at import time (best-effort, non-blocking)
_get_client()
