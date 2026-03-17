"""
🗣️ RADIM BRAIN SPEECH — Speech parameters & Early Ψ Cache
============================================================
Extracted from radim_brain_routes.py for modularity.

- Early Ψ cache (streaming STT → Brain)
- Unified speech parameter computation (φ-proportioned pauses)
- Brain speech lookup from DB (for TTS endpoints)

Version: 1.0.0
"""

import time as _time_module
import logging

from brain_math import T1, T2, BRAIN_STATE_TTL_MINUTES, clamp, PHI, RHO

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# DATABASE IMPORTS (graceful fallback)
# ═══════════════════════════════════════════════════════════

try:
    from database import get_connection, is_postgres
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# ═══════════════════════════════════════════════════════════
# EARLY Ψ CACHE — Streaming STT → Brain (v272)
# ═══════════════════════════════════════════════════════════

_early_psi_cache = {}
_EARLY_PSI_TTL = 300  # 5 minutes


def update_early_psi(user_id, C_estimate, alpha_estimate, is_final=False):
    """Update brain state from interim STT — lightweight, no DB write for interim.

    For interim results: only update in-memory cache (no DB overhead).
    For final results: save to DB via existing compute_psi_state().
    """
    # Clean stale entries (> 5 min)
    now = _time_module.time()
    stale_keys = [k for k, v in _early_psi_cache.items() if now - v['ts'] > _EARLY_PSI_TTL]
    for k in stale_keys:
        del _early_psi_cache[k]

    if not is_final:
        _early_psi_cache[user_id] = {
            'C': C_estimate,
            'alpha': alpha_estimate,
            'ts': now
        }
        return

    # On final: delegate to full Ψ computation (lazy import to avoid circular)
    try:
        from radim_brain_routes import compute_psi_state
        compute_psi_state(C_estimate, 0.5, 0.5, 0.5, alpha_estimate, user_id=user_id)
    except Exception as e:
        logger.warning(f"Early Ψ final save warning: {e}")
    finally:
        # Clear interim cache for this user
        _early_psi_cache.pop(user_id, None)


def get_early_psi(user_id):
    """Get cached early Ψ estimate for a user (from streaming STT)."""
    entry = _early_psi_cache.get(user_id)
    if entry and (_time_module.time() - entry['ts']) < _EARLY_PSI_TTL:
        return entry
    return None


# ═══════════════════════════════════════════════════════════
# UNIFIED SPEECH COMPUTATION
# ═══════════════════════════════════════════════════════════

def compute_unified_speech(C, alpha, mode, user_id=None, ant_params=None,
                           _load_adaptation=None, _adaptation_fallback=None):
    """
    Unified speech parameter computation — single source of truth.

    Layer 1: Brain mode-based baseline (φ-proportioned pauses)
    Layer 2: Anticipation Engine fine-tuning (30% blend if ant_params provided)
    Layer 3: Per-user adaptation from brain_adaptation DB
    Layer 4: Pitch mapping with wider range (v2.1: +2% to -10%)

    Args:
        C: consciousness level (0-40)
        alpha: emotional activation (0-1)
        mode: "HARMONY" | "ALERT" | "CRISIS"
        user_id: if set, loads per-user adaptation from DB
        ant_params: dict from Anticipation Engine {rate, pitch, pause_ms} (optional)
        _load_adaptation: callable to load per-user adaptation (injected from brain routes)
        _adaptation_fallback: dict fallback adaptation state

    Returns:
        dict: {rate, pitch_pct, pause_ms, phrasing, style, styledegree, mode}
    """
    # Load per-user adaptation
    if user_id and _load_adaptation:
        adapt = _load_adaptation(user_id)
    elif _adaptation_fallback:
        adapt = _adaptation_fallback
    else:
        adapt = {
            "speech_rate_adjust": 0.0,
            "pause_adjust_ms": 0,
        }

    # === Layer 1: Brain mode-based baseline ===
    if mode == "HARMONY":
        rate = 1.0
        pause_ms = 618      # φ × 382
        pitch_st = 12
        phrasing = "natural"
        style = "friendly"
        styledegree = "1.2"
    elif mode == "ALERT":
        rate = 0.85
        pause_ms = 1000     # φ midpoint
        pitch_st = 8
        phrasing = "simplified"
        style = "empathetic"
        styledegree = "1.1"
    else:  # CRISIS
        rate = 0.7
        pause_ms = 1618     # φ × 1000
        pitch_st = 4
        phrasing = "single_command"
        style = "calm"
        styledegree = "1.0"

    # === Layer 2: Anticipation Engine fine-tuning (30% blend) ===
    if ant_params:
        ant_rate = float(ant_params.get('rate', 0.9))
        ant_pause = float(ant_params.get('pause_ms', 300))
        ant_pitch = float(ant_params.get('pitch', 0))
        rate += (ant_rate - 0.9) * 0.3
        pause_ms += (ant_pause - 300) * 0.3
        pitch_st += int(ant_pitch * 0.3)

    # === Layer 3: Per-user adaptation ===
    rate += adapt.get("speech_rate_adjust", 0.0)
    pause_ms += adapt.get("pause_adjust_ms", 0)

    # Clamp
    rate = clamp(rate, 0.5, 1.2)
    pause_ms = clamp(pause_ms, 200, 2500)
    pitch_st = clamp(pitch_st, 0, 16)

    # === Layer 4: Wider pitch mapping (v2.1) ===
    # 12st (HARMONY) → +2%, 8st (ALERT) → ~-5%, 4st (CRISIS) → ~-10%
    pitch_pct = round(2 - (12 - pitch_st) * 1.2)

    return {
        "rate": round(rate, 3),
        "pitch_pct": pitch_pct,
        "pause_ms": round(pause_ms),
        "phrasing": phrasing,
        "style": style,
        "styledegree": styledegree,
        "mode": mode,
    }


def get_brain_speech_for_user(user_id, _load_adaptation=None, _adaptation_fallback=None):
    """
    Load latest Ψ(t) from brain_states and compute speech params for TTS.

    Returns dict with rate, pitch, pause_ms, phrasing, style, mode, coherence
    or None if no fresh brain state exists (TTL: 30 min).
    """
    if not DB_AVAILABLE or not user_id:
        return None
    db = None
    try:
        db = get_connection()
        if is_postgres():
            row = db.execute(
                "SELECT C, E, R, S, alpha, mode, coherence FROM brain_states WHERE user_id = %s AND created_at > NOW() - INTERVAL '%s minutes' ORDER BY created_at DESC LIMIT 1",
                (user_id, BRAIN_STATE_TTL_MINUTES)
            ).fetchone()
        else:
            row = db.execute(
                "SELECT C, E, R, S, alpha, mode, coherence FROM brain_states WHERE user_id = ? AND created_at > datetime('now', '-' || ? || ' minutes') ORDER BY created_at DESC LIMIT 1",
                (user_id, BRAIN_STATE_TTL_MINUTES)
            ).fetchone()
        if not row:
            return None

        # RealDictCursor returns dict with lowercase keys
        C_val = float(row.get('c', row.get('C', 5.0)) or 5.0)
        alpha_val = float(row.get('alpha', 0.0) or 0.0)
        mode = row.get('mode', 'HARMONY') or "HARMONY"
        coherence = row.get('coherence', 0.5)

        # Use unified speech computation
        speech = compute_unified_speech(
            C_val, alpha_val, mode, user_id=user_id,
            _load_adaptation=_load_adaptation,
            _adaptation_fallback=_adaptation_fallback
        )
        speech["coherence"] = round(float(coherence or 0.5), 4)
        speech["user_id"] = user_id
        speech["source"] = "brain_states"
        return speech
    except Exception as e:
        logger.warning(f"Brain speech lookup warning: {e}")
        return None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


logger.info("✅ Brain Speech module loaded — unified speech + early Ψ cache")
