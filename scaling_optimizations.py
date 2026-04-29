# ============================================
# ⚡ SCALING OPTIMIZATIONS — Cost & Performance
# ============================================
# 1. TTS Cache — avoid duplicate Azure API calls (-40% TTS cost)
# 2. AI Response Cache — common intents without Gemini call
# 3. Adaptive Agent Interval — 10min for low-risk, 5min for high-risk
# 4. DB Query Batching — reduce per-user query count
# ============================================

import hashlib
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ============================================
# 1. TTS CACHE — In-memory LRU for Azure TTS
# ============================================
# Azure TTS costs ~$0.12/1000 chars. Radim repeats many phrases:
# "Ahoj!", "Dobrý den!", "Výborně!", "Správně!", etc.
# Cache audio bytes in memory — saves 30-50% of TTS API calls.

class TTSCache:
    """LRU cache for TTS audio responses.

    Key: hash(text + voice + rate)
    Value: (audio_bytes, timestamp)
    Max: 200 entries (~40MB at 200KB average per audio)
    TTL: 24 hours
    """

    def __init__(self, max_entries=200, ttl_hours=24):
        self._cache = {}
        self._access_order = []
        self.max_entries = max_entries
        self.ttl = ttl_hours * 3600
        self.hits = 0
        self.misses = 0

    def _key(self, text, voice='cs-CZ-AntoninNeural', rate=0.9):
        """Generate cache key from text + voice params."""
        # Normalize: strip whitespace, lowercase for matching
        normalized = text.strip().lower()[:500]  # Cap at 500 chars
        raw = f"{normalized}|{voice}|{rate}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, text, voice='cs-CZ-AntoninNeural', rate=0.9):
        """Get cached audio bytes. Returns None on miss."""
        key = self._key(text, voice, rate)
        entry = self._cache.get(key)
        if entry is None:
            self.misses += 1
            return None

        audio_bytes, cached_at = entry
        # Check TTL
        if time.time() - cached_at > self.ttl:
            del self._cache[key]
            self.misses += 1
            return None

        self.hits += 1
        # Move to end (most recently used)
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        return audio_bytes

    def put(self, text, audio_bytes, voice='cs-CZ-AntoninNeural', rate=0.9):
        """Cache audio bytes for text."""
        if not audio_bytes or len(audio_bytes) < 100:
            return  # Don't cache empty/error responses

        key = self._key(text, voice, rate)

        # Evict oldest if at capacity
        while len(self._cache) >= self.max_entries:
            if self._access_order:
                oldest = self._access_order.pop(0)
                self._cache.pop(oldest, None)
            else:
                break

        self._cache[key] = (audio_bytes, time.time())
        self._access_order.append(key)

    def stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        mem_bytes = sum(len(v[0]) for v in self._cache.values())
        return {
            'entries': len(self._cache),
            'max_entries': self.max_entries,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate_pct': round(hit_rate, 1),
            'memory_mb': round(mem_bytes / 1024 / 1024, 2)
        }

    def clear(self):
        self._cache.clear()
        self._access_order.clear()
        self.hits = 0
        self.misses = 0


# Global singleton
tts_cache = TTSCache()


# ============================================
# Sprint AL.4: Azure TTS QUOTA TRACKER
# ============================================
# Counts characters sent to Azure (cache MISS = real Azure call) so we
# can predict monthly cost. Azure Neural TTS pricing is per character:
#   - Standard tier: $16 / 1M chars
#   - Free tier: 500k chars/month
# Live counters reset on dyno restart. For long-term tracking we'd
# need a DB row, but per-dyno counters are enough for spot-checks.

import time as _time_az

class _TTSQuotaTracker:
    def __init__(self):
        self.start_ts = _time_az.time()
        self.azure_chars = 0      # chars actually sent to Azure
        self.cached_chars = 0      # chars served from cache (no $)
        self.azure_calls = 0
        self.cached_calls = 0

    def record_azure(self, text_len):
        self.azure_chars += int(text_len or 0)
        self.azure_calls += 1

    def record_cached(self, text_len):
        self.cached_chars += int(text_len or 0)
        self.cached_calls += 1

    def stats(self):
        uptime_h = max(0.001, (_time_az.time() - self.start_ts) / 3600)
        # Project to 30-day bill at current rate
        chars_per_h = self.azure_chars / uptime_h
        projected_30d = chars_per_h * 24 * 30
        # Azure standard tier: $16 / 1M chars (Neural)
        projected_usd = projected_30d / 1_000_000 * 16
        total_calls = self.azure_calls + self.cached_calls
        cache_savings_pct = (self.cached_calls / total_calls * 100) if total_calls else 0
        return {
            'uptime_hours': round(uptime_h, 2),
            'azure_chars': self.azure_chars,
            'azure_calls': self.azure_calls,
            'cached_chars': self.cached_chars,
            'cached_calls': self.cached_calls,
            'cache_savings_pct': round(cache_savings_pct, 1),
            'projected_monthly_chars': round(projected_30d),
            'projected_monthly_usd': round(projected_usd, 2),
        }

tts_quota = _TTSQuotaTracker()


# ============================================
# 2. AI RESPONSE CACHE — Skip Gemini for repeated queries
# ============================================
# Many seniors ask same things: "kolik je hodin", "jaké je počasí"
# Intent resolver handles 15 local intents — but some medium-freq
# questions go to Gemini unnecessarily.
# Cache recent AI responses for identical messages (5 min TTL).

class AIResponseCache:
    """Short-lived cache for AI responses.

    Prevents duplicate Gemini calls when senior repeats a question.
    Very short TTL (5 min) — responses should feel fresh.
    """

    def __init__(self, max_entries=100, ttl_seconds=300):
        self._cache = {}
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self.hits = 0
        self.misses = 0

    def _key(self, message, user_id='', mode='senior'):
        """Normalize message for matching."""
        normalized = message.strip().lower()[:200]
        return hashlib.md5(f"{normalized}|{user_id}|{mode}".encode()).hexdigest()

    def get(self, message, user_id='', mode='senior'):
        key = self._key(message, user_id, mode)
        entry = self._cache.get(key)
        if entry is None:
            self.misses += 1
            return None
        response, cached_at = entry
        if time.time() - cached_at > self.ttl:
            del self._cache[key]
            self.misses += 1
            return None
        self.hits += 1
        return response

    def put(self, message, response, user_id='', mode='senior'):
        if not response:
            return
        key = self._key(message, user_id, mode)
        # Evict if full
        if len(self._cache) >= self.max_entries:
            # Remove oldest
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
        self._cache[key] = (response, time.time())

    def stats(self):
        total = self.hits + self.misses
        return {
            'entries': len(self._cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate_pct': round((self.hits / total * 100) if total > 0 else 0, 1)
        }


ai_cache = AIResponseCache()


# ============================================
# 3. ADAPTIVE AGENT INTERVAL
# ============================================
# Currently: every user checked every 5 min (12 queries/user)
# Optimization: low-risk users checked every 15 min,
# high-risk users stay at 5 min.

def should_evaluate_user(user_id, risk_level='low'):
    """Decide if user needs evaluation this cycle.

    High-risk (risk_level='high'/'critical'): every cycle (5 min)
    Medium-risk: every 2nd cycle (10 min)
    Low-risk: every 3rd cycle (15 min)

    Uses modular arithmetic on minute to distribute load evenly.
    """
    minute = datetime.utcnow().minute

    if risk_level in ('high', 'critical'):
        return True  # Always evaluate

    if risk_level == 'medium':
        # Every 10 minutes (0, 10, 20, 30, 40, 50)
        return minute % 10 < 5

    # Low risk: every 15 minutes (0, 15, 30, 45)
    # Use hash of user_id to distribute across different minutes
    user_hash = int(hashlib.md5(str(user_id).encode()).hexdigest()[:4], 16)
    offset = user_hash % 3  # 0, 1, or 2
    return (minute // 5) % 3 == offset


def get_user_risk_level(user_id):
    """Get cached risk level for adaptive scheduling.

    Falls back to 'medium' if unknown (safe default).
    """
    try:
        from database import db_context
        with db_context(commit=False) as db:
            row = db.execute("""
                SELECT coherence FROM brain_states
                WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
            """, (user_id,)).fetchone()
            if row:
                c = float(row[0])
                if c > 20:
                    return 'high'
                if c > 12:
                    return 'medium'
                return 'low'
    except Exception:
        pass
    return 'medium'


# ============================================
# 4. QUERY BATCHING — Reduce DB round-trips
# ============================================

def batch_load_user_data(user_id):
    """Load profile + learning + last brain state in ONE query.

    Reduces 3 separate queries to 1 with UNION or JOIN.
    Falls back to individual queries if batch fails.
    """
    try:
        from database import db_context, is_postgres
        if not is_postgres():
            return None  # SQLite doesn't benefit much

        with db_context(commit=False) as db:
            row = db.execute("""
                SELECT
                    p.data AS profile_data,
                    l.data AS learning_data,
                    b.coherence AS last_c,
                    b.created_at AS brain_ts
                FROM memory_profiles p
                LEFT JOIN memory_learning l ON l.user_id = p.user_id
                LEFT JOIN LATERAL (
                    SELECT coherence, created_at FROM brain_states
                    WHERE user_id = p.user_id
                    ORDER BY created_at DESC LIMIT 1
                ) b ON true
                WHERE p.user_id = ?
            """, (user_id,)).fetchone()

            if row:
                import json
                # JSONB columns return parsed dict/list directly; TEXT columns return string.
                # Handle both — only json.loads when value is a string.
                def _maybe(v, default):
                    if v is None:
                        return default
                    if isinstance(v, (dict, list)):
                        return v
                    if isinstance(v, str):
                        try:
                            return json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            return default
                    return default
                return {
                    'profile': _maybe(row[0], {}),
                    'learning': _maybe(row[1], {}),
                    'last_c': float(row[2]) if row[2] else 5.0,
                    'brain_ts': row[3]
                }
    except Exception as e:
        logger.debug(f"Batch load fallback: {e}")

    return None


# ============================================
# 5. STATS ENDPOINT — Monitor optimization impact
# ============================================

def get_optimization_stats():
    """Get current optimization stats for admin dashboard."""
    return {
        'tts_cache': tts_cache.stats(),
        'ai_cache': ai_cache.stats(),
        'timestamp': datetime.utcnow().isoformat()
    }


logger.info("⚡ Scaling optimizations loaded — TTS cache, AI cache, adaptive agent, batch queries")
