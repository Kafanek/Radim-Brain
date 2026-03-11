"""
Rate Limiter — lightweight in-memory rate limiting for Flask.
No external dependencies (no flask-limiter needed).

Usage:
    from rate_limiter import rate_limit

    @app.route('/api/ai/chat', methods=['POST'])
    @require_auth
    @rate_limit(max_requests=20, window_seconds=60, key_func='user')
    def ai_chat():
        ...

Key functions:
    'user'  — rate limit per authenticated user (g.auth_user)
    'ip'    — rate limit per IP address
    'global' — single global rate limit

Version: 1.0.0
"""

import time
import threading
import logging
from functools import wraps
from flask import request, jsonify, g

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# SLIDING WINDOW RATE LIMITER
# ═══════════════════════════════════════════════════════════════

_buckets = {}          # {bucket_key: [timestamp, timestamp, ...]}
_buckets_lock = threading.Lock()
_BUCKETS_MAX = 5000    # Max tracked keys (prevent memory leak)
_CLEANUP_INTERVAL = 300  # Cleanup every 5 minutes
_last_cleanup = time.time()


def _cleanup_old_buckets():
    """Remove expired buckets to prevent memory growth."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return

    _last_cleanup = now
    cutoff = now - 3600  # Remove buckets with no activity in 1 hour
    keys_to_remove = []

    for key, timestamps in _buckets.items():
        if not timestamps or timestamps[-1] < cutoff:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del _buckets[key]

    if keys_to_remove:
        logger.debug(f"Rate limiter cleanup: removed {len(keys_to_remove)} stale buckets")


def _get_key(key_func, endpoint_name):
    """Build a rate limit bucket key."""
    if key_func == 'user':
        user = getattr(g, 'auth_user', None)
        if user and isinstance(user, dict):
            uid = user.get('user_id') or user.get('id') or 'unknown'
        elif user:
            uid = str(user)
        else:
            uid = request.remote_addr or 'unknown'
        return f"user:{uid}:{endpoint_name}"
    elif key_func == 'ip':
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'
        # Take first IP if multiple (proxy chain)
        ip = ip.split(',')[0].strip()
        return f"ip:{ip}:{endpoint_name}"
    elif key_func == 'global':
        return f"global:{endpoint_name}"
    else:
        return f"custom:{key_func}:{endpoint_name}"


def _check_rate(bucket_key, max_requests, window_seconds):
    """Check if request is within rate limit. Returns (allowed, remaining, reset_at)."""
    now = time.time()

    with _buckets_lock:
        _cleanup_old_buckets()

        # Enforce max buckets
        if bucket_key not in _buckets and len(_buckets) >= _BUCKETS_MAX:
            # Evict oldest bucket
            oldest_key = min(_buckets, key=lambda k: _buckets[k][-1] if _buckets[k] else 0)
            del _buckets[oldest_key]

        if bucket_key not in _buckets:
            _buckets[bucket_key] = []

        timestamps = _buckets[bucket_key]

        # Remove timestamps outside the window
        cutoff = now - window_seconds
        _buckets[bucket_key] = [ts for ts in timestamps if ts > cutoff]
        timestamps = _buckets[bucket_key]

        if len(timestamps) >= max_requests:
            # Rate limited
            oldest_in_window = timestamps[0]
            reset_at = oldest_in_window + window_seconds
            remaining = 0
            return False, remaining, reset_at

        # Allow and record
        timestamps.append(now)
        remaining = max_requests - len(timestamps)
        reset_at = now + window_seconds
        return True, remaining, reset_at


# ═══════════════════════════════════════════════════════════════
# DECORATOR
# ═══════════════════════════════════════════════════════════════

def rate_limit(max_requests=30, window_seconds=60, key_func='user'):
    """Flask decorator for rate limiting.

    Args:
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Time window in seconds.
        key_func: 'user' (per auth user), 'ip' (per IP), 'global' (shared).

    Returns 429 with Retry-After header when rate limit is exceeded.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            endpoint_name = f.__name__
            bucket_key = _get_key(key_func, endpoint_name)

            allowed, remaining, reset_at = _check_rate(
                bucket_key, max_requests, window_seconds
            )

            if not allowed:
                retry_after = max(1, int(reset_at - time.time()))
                logger.warning(
                    f"Rate limit exceeded: {bucket_key} "
                    f"({max_requests}/{window_seconds}s)"
                )
                response = jsonify({
                    'success': False,
                    'error': 'Příliš mnoho požadavků, zkuste později',
                    'code': 429,
                    'retry_after': retry_after
                })
                response.status_code = 429
                response.headers['Retry-After'] = str(retry_after)
                response.headers['X-RateLimit-Limit'] = str(max_requests)
                response.headers['X-RateLimit-Remaining'] = '0'
                response.headers['X-RateLimit-Reset'] = str(int(reset_at))
                return response

            result = f(*args, **kwargs)

            # Add rate limit headers to successful responses
            if hasattr(result, 'headers'):
                result.headers['X-RateLimit-Limit'] = str(max_requests)
                result.headers['X-RateLimit-Remaining'] = str(remaining)
                result.headers['X-RateLimit-Reset'] = str(int(reset_at))

            return result
        return decorated
    return decorator
