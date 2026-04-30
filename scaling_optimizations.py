# ============================================
# ⚡ SCALING OPTIMIZATIONS — Cost & Performance
# ============================================
# 1. TTS Cache — avoid duplicate Azure API calls (-40% TTS cost)
# 2. AI Response Cache — common intents without Gemini call
# 3. Adaptive Agent Interval — 10min for low-risk, 5min for high-risk
# 4. DB Query Batching — reduce per-user query count
# ============================================

import hashlib
import os
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ============================================
# 1. TTS CACHE — In-memory LRU + persistent disk for Azure TTS
# ============================================
# Azure TTS costs ~$16/1M chars. Radim repeats many phrases:
# "Ahoj!", "Dobrý den!", "Výborně!", "Správně!", etc.
# Cache audio bytes in memory — saves 30-50% of TTS API calls.
#
# v453: Disk-backed persistence (Heroku /tmp) so cache survives:
#   - eventlet greenlet recycle / gunicorn worker reload
#   - Eco-dyno short sleep cycles (if /tmp persists across the wake)
# Disk is BEST EFFORT — every dyno restart wipes /tmp, so persistence is
# bounded by dyno lifetime (~24 h on Heroku).

# Disk cache root: Heroku /tmp is the only writable ephemeral fs.
TTS_DISK_ROOT = os.environ.get('TTS_DISK_CACHE', '/tmp/radim_tts_cache')


class TTSCache:
    """Two-tier LRU cache for TTS audio responses.

    Layer 1 (in-memory): hot keys, instant lookup, capped by max_entries.
    Layer 2 (disk): /tmp/radim_tts_cache/<key>.mp3 + <key>.meta — survives
                    in-process restarts, lazy-loaded on cache miss.

    Key: md5(text.lower() + voice + rate)
    TTL: 24 h (both layers honour it)

    Disk operations are guarded — failures fall back silently to memory-only,
    so a full /tmp cannot break TTS.
    """

    def __init__(self, max_entries=200, ttl_hours=24, disk_root=None):
        self._cache = {}
        self._access_order = []
        self.max_entries = max_entries
        self.ttl = ttl_hours * 3600
        self.hits = 0
        self.misses = 0
        self.disk_hits = 0       # served from disk (memory miss)
        self.disk_writes = 0
        self.disk_root = disk_root if disk_root is not None else TTS_DISK_ROOT
        self._disk_ok = self._init_disk()

    def _init_disk(self):
        """Create disk root + warm in-memory index from existing files.
        Returns True if disk is usable, False on permission/IO error."""
        try:
            os.makedirs(self.disk_root, exist_ok=True)
            now = time.time()
            warmed = 0
            for fn in os.listdir(self.disk_root):
                if not fn.endswith('.meta'):
                    continue
                key = fn[:-5]
                meta_path = os.path.join(self.disk_root, fn)
                try:
                    with open(meta_path) as f:
                        cached_at = float(f.read().strip())
                except (OSError, ValueError):
                    continue
                # TTL filter — drop expired files now to keep disk tidy
                if now - cached_at > self.ttl:
                    self._unlink_safe(key)
                    continue
                # Index entry without loading audio (lazy via _read_disk on get)
                self._cache[key] = (None, cached_at)  # None = disk-only sentinel
                self._access_order.append(key)
                warmed += 1
            if warmed:
                logger.info(f"⚡ TTSCache: warmed {warmed} entries from disk ({self.disk_root})")
            return True
        except OSError as e:
            logger.warning(f"⚡ TTSCache: disk init failed ({e}); memory-only mode")
            return False

    def _file_paths(self, key):
        return (os.path.join(self.disk_root, key + '.mp3'),
                os.path.join(self.disk_root, key + '.meta'))

    def _read_disk(self, key):
        if not self._disk_ok:
            return None
        mp3_path, _ = self._file_paths(key)
        try:
            with open(mp3_path, 'rb') as f:
                return f.read()
        except OSError:
            return None

    def _write_disk(self, key, audio_bytes, cached_at):
        if not self._disk_ok:
            return
        mp3_path, meta_path = self._file_paths(key)
        try:
            # Write atomically: tmp file then rename (no torn reads)
            tmp = mp3_path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(audio_bytes)
            os.replace(tmp, mp3_path)
            with open(meta_path, 'w') as f:
                f.write(str(cached_at))
            self.disk_writes += 1
        except OSError as e:
            logger.debug(f"⚡ TTSCache disk write failed for {key[:8]}: {e}")

    def _unlink_safe(self, key):
        if not self._disk_ok:
            return
        for path in self._file_paths(key):
            try:
                os.unlink(path)
            except OSError:
                pass

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
        # Check TTL (covers both memory & disk-warmed entries)
        if time.time() - cached_at > self.ttl:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._unlink_safe(key)
            self.misses += 1
            return None

        # Disk-only entry (warmed at startup, audio not yet loaded)
        if audio_bytes is None:
            audio_bytes = self._read_disk(key)
            if audio_bytes is None:
                # Disk file vanished — drop the index entry
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                self.misses += 1
                return None
            # Promote to in-memory (with current timestamp from disk)
            self._cache[key] = (audio_bytes, cached_at)
            self.disk_hits += 1

        self.hits += 1
        # Move to end (most recently used)
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        return audio_bytes

    def put(self, text, audio_bytes, voice='cs-CZ-AntoninNeural', rate=0.9):
        """Cache audio bytes for text — both in-memory and on disk."""
        if not audio_bytes or len(audio_bytes) < 100:
            return  # Don't cache empty/error responses

        key = self._key(text, voice, rate)
        cached_at = time.time()

        # Evict oldest if at capacity
        while len(self._cache) >= self.max_entries:
            if self._access_order:
                oldest = self._access_order.pop(0)
                self._cache.pop(oldest, None)
                self._unlink_safe(oldest)
            else:
                break

        self._cache[key] = (audio_bytes, cached_at)
        self._access_order.append(key)
        self._write_disk(key, audio_bytes, cached_at)

    def stats(self):
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        # Memory-resident entries (disk-only sentinels excluded)
        mem_bytes = sum(len(v[0]) for v in self._cache.values() if v[0] is not None)
        loaded = sum(1 for v in self._cache.values() if v[0] is not None)
        disk_only = len(self._cache) - loaded
        # Disk usage (best-effort)
        disk_bytes = 0
        try:
            if self._disk_ok and os.path.isdir(self.disk_root):
                for fn in os.listdir(self.disk_root):
                    if fn.endswith('.mp3'):
                        try:
                            disk_bytes += os.path.getsize(os.path.join(self.disk_root, fn))
                        except OSError:
                            pass
        except OSError:
            pass
        return {
            'entries': len(self._cache),
            'entries_in_memory': loaded,
            'entries_disk_only': disk_only,
            'max_entries': self.max_entries,
            'hits': self.hits,
            'disk_hits': self.disk_hits,
            'misses': self.misses,
            'hit_rate_pct': round(hit_rate, 1),
            'memory_mb': round(mem_bytes / 1024 / 1024, 2),
            'disk_mb': round(disk_bytes / 1024 / 1024, 2),
            'disk_writes': self.disk_writes,
            'disk_enabled': self._disk_ok,
            'disk_root': self.disk_root,
        }

    def clear(self):
        # In-memory wipe
        keys = list(self._cache.keys())
        self._cache.clear()
        self._access_order.clear()
        self.hits = 0
        self.disk_hits = 0
        self.misses = 0
        self.disk_writes = 0
        # Disk wipe
        for key in keys:
            self._unlink_safe(key)


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
