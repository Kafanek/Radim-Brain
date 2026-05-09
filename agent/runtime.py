"""
Agent Runtime — wires math_engine + heartbeat into the live Flask app.

Responsibilities:
  1. Real state_provider — reads from `brain_states` + `iot_sensor_data` +
     chat history and projects them into the math engine's 4-domain State.
  2. Per-senior heartbeat registry (one Heartbeat instance per active user).
  3. SocketIO push on each tick (`agent:tick` event in user-{id} room).
  4. Cooldown-aware audit logging hook.

Imported lazily by `app.py` so unit tests / standalone math demos don't
require a live DB.

Sprint X20.1 — Foundation, Phase 1 of holistic agent.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Optional

from .heartbeat import Heartbeat
from .math_engine import State, DomainWeights, PERSONA_WEIGHTS

logger = logging.getLogger(__name__)


# ─── Defaults & domain mapping ──────────────────────────────────────────────

DEFAULT_PERSONA = "senior"
DEFAULT_HISTORY_LEN = 6  # 6 brain_states × 5 min = 25 min window
DEFAULT_DOMAIN_BASELINE = 8.0   # neutral starting value when no IoT data

# Comfort bands per IoT sensor type. Outside the band → environmental
# stress contributes to C_environmental.
ENV_COMFORT_BANDS = {
    'temperature': (19, 25),     # °C
    'humidity':    (40, 65),     # %
    'co2':         (400, 1000),  # ppm
    'noise':       (0, 55),      # dB
    'illuminance': (50, 1000),   # lux (extreme low or extreme bright = stress)
}


# ─── State derivation from real DB data ─────────────────────────────────────


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _band_excess(value: float, lo: float, hi: float, scale: float = 10.0) -> float:
    """How far outside a comfort band (scaled to C-units 0–40).
    Inside band → 0. Outside → roughly proportional to deviation."""
    if lo <= value <= hi:
        return 0.0
    if value < lo:
        return min(scale, (lo - value) / max(1.0, lo) * scale)
    return min(scale, (value - hi) / max(1.0, hi) * scale)


def _derive_environmental_c(user_id: str) -> float:
    """Read recent IoT sensors and compute C_environmental from comfort
    band deviations. Cheaper than recomputing per-sensor; one snapshot."""
    try:
        from database import db_context
    except ImportError:
        return DEFAULT_DOMAIN_BASELINE
    try:
        with db_context(commit=False) as cur:
            cur.execute(
                "SELECT sensor_type, value FROM iot_sensor_data "
                "WHERE recorded_at > ? "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "ORDER BY recorded_at DESC LIMIT 50",
                (datetime.utcnow() - timedelta(minutes=15), user_id)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"derive_environmental_c: DB read failed: {e}")
        return DEFAULT_DOMAIN_BASELINE

    if not rows:
        return DEFAULT_DOMAIN_BASELINE

    # Take the most recent value per sensor_type
    latest: dict[str, float] = {}
    for row in rows:
        sensor_type = row[0] if isinstance(row, (list, tuple)) else row['sensor_type']
        value = row[1] if isinstance(row, (list, tuple)) else row['value']
        if sensor_type not in latest:
            latest[sensor_type] = _safe_float(value)

    base = DEFAULT_DOMAIN_BASELINE
    excess = 0.0
    for sensor_type, value in latest.items():
        band = ENV_COMFORT_BANDS.get(sensor_type)
        if band:
            excess += _band_excess(value, band[0], band[1], scale=8.0)
    return min(40.0, base + excess)


def _derive_social_c(user_id: str) -> float:
    """C_social grows when senior has been silent (no chat / call)
    significantly longer than baseline. Proxy: hours since last chat."""
    try:
        from database import db_context
    except ImportError:
        return DEFAULT_DOMAIN_BASELINE
    try:
        with db_context(commit=False) as cur:
            cur.execute(
                "SELECT MAX(created_at) FROM chat_messages "
                "WHERE conversation_id IN ("
                "  SELECT id FROM chat_conversations WHERE participants LIKE ?"
                ")",
                (f'%{user_id}%',)
            )
            row = cur.fetchone()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"derive_social_c: DB read failed: {e}")
        return DEFAULT_DOMAIN_BASELINE

    last = row[0] if row else None
    if not last:
        return DEFAULT_DOMAIN_BASELINE
    if isinstance(last, str):
        try:
            last = datetime.fromisoformat(last.replace('Z', '+00:00'))
        except ValueError:
            return DEFAULT_DOMAIN_BASELINE

    hours = (datetime.utcnow() - last.replace(tzinfo=None)).total_seconds() / 3600.0
    # Mild ramp: 0–6h no penalty, 6–24h grows linearly to +10
    if hours <= 6:
        return DEFAULT_DOMAIN_BASELINE
    extra = min(15.0, (hours - 6) / 18.0 * 15.0)
    return min(40.0, DEFAULT_DOMAIN_BASELINE + extra)


def _derive_physical_c(user_id: str) -> float:
    """C_physical from heart-rate / motion telemetry.
    Heart rate above 100 bpm at rest → grows. Below 50 → grows (bradycardia).
    No data → baseline."""
    try:
        from database import db_context
    except ImportError:
        return DEFAULT_DOMAIN_BASELINE
    try:
        with db_context(commit=False) as cur:
            cur.execute(
                "SELECT sensor_type, AVG(value)::FLOAT FROM iot_sensor_data "
                "WHERE recorded_at > ? "
                "AND sensor_type IN ('heart_rate','motion','spo2') "
                "AND room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) "
                "GROUP BY sensor_type",
                (datetime.utcnow() - timedelta(minutes=10), user_id)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"derive_physical_c: DB read failed: {e}")
        return DEFAULT_DOMAIN_BASELINE

    if not rows:
        return DEFAULT_DOMAIN_BASELINE

    base = DEFAULT_DOMAIN_BASELINE
    extra = 0.0
    for row in rows:
        sensor_type = row[0] if isinstance(row, (list, tuple)) else row[0]
        avg_val = row[1] if isinstance(row, (list, tuple)) else row[1]
        avg_val = _safe_float(avg_val)
        if sensor_type == 'heart_rate' and avg_val > 0:
            if avg_val > 100:
                extra += min(15, (avg_val - 100) / 5)
            elif avg_val < 50:
                extra += min(15, (50 - avg_val) / 3)
        elif sensor_type == 'spo2' and avg_val > 0 and avg_val < 95:
            extra += min(15, (95 - avg_val) * 2)
    return min(40.0, base + extra)


def collect_state_history(user_id: str,
                          n: int = DEFAULT_HISTORY_LEN) -> list[State]:
    """Build a State history for the math engine from real PG data.

    Mapping:
        brain_states.C       → c_emotional   (per row)
        brain_states.alpha   → alpha         (per row)
        brain_states.E       → e_valence     (per row, normalized)
        IoT now-snapshot     → c_environmental, c_physical (constant per call)
        chat last-seen       → c_social      (constant per call)

    Returns at least 1 state. Missing brain_states → cold-start neutral
    sample at now() so the engine can still produce a baseline snapshot.
    """
    try:
        from database import db_context
    except ImportError:
        # Standalone / offline mode — return single neutral state
        return [_neutral_state(now=datetime.utcnow())]

    rows = []
    try:
        with db_context(commit=False) as cur:
            cur.execute(
                "SELECT C, alpha, E, created_at FROM brain_states "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, n),
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.warning(f"collect_state_history: DB read failed: {e}")

    # Auxiliary domains (cheap, snapshot-shared across rows in this call)
    env_now = _derive_environmental_c(user_id)
    phy_now = _derive_physical_c(user_id)
    soc_now = _derive_social_c(user_id)

    if not rows:
        s = _neutral_state(now=datetime.utcnow(),
                           env=env_now, phy=phy_now, soc=soc_now)
        return [s]

    states: list[State] = []
    for row in reversed(rows):
        # Both dict (psycopg) + tuple (sqlite) supported
        if isinstance(row, (list, tuple)):
            c, alpha, e_raw, ts = row[0], row[1], row[2], row[3]
        else:
            c, alpha, e_raw, ts = row['c'], row['alpha'], row['e'], row['created_at']
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                ts = datetime.utcnow()
        states.append(State(
            t=ts,
            c_emotional=_safe_float(c, 10.0),
            c_environmental=env_now,
            c_social=soc_now,
            c_physical=phy_now,
            alpha=max(0.0, min(1.0, _safe_float(alpha, 0.3))),
            e_valence=max(-1.0, min(1.0, _safe_float(e_raw, 0.0) / 40.0)),
        ))
    return states


def _neutral_state(now: datetime, env=DEFAULT_DOMAIN_BASELINE,
                   phy=DEFAULT_DOMAIN_BASELINE, soc=DEFAULT_DOMAIN_BASELINE) -> State:
    return State(
        t=now,
        c_emotional=10.0, c_environmental=env, c_social=soc, c_physical=phy,
        alpha=0.3, e_valence=0.0,
    )


# ─── Persona resolution ─────────────────────────────────────────────────────


def _persona_for_user(user_id: str) -> str:
    """Currently returns DEFAULT_PERSONA. When `seniors.persona_id` column
    is added (migration), read from DB. Honors per-user override via
    seniors.persona_id when available."""
    try:
        from database import db_context
        with db_context(commit=False) as cur:
            try:
                cur.execute(
                    "SELECT persona_id FROM seniors WHERE id = ? LIMIT 1",
                    (user_id,))
                row = cur.fetchone()
                if row:
                    pid = row[0] if isinstance(row, (list, tuple)) else row['persona_id']
                    if pid and pid in PERSONA_WEIGHTS:
                        return pid
            except Exception:
                pass  # column may not exist yet — graceful fallback
    except Exception:
        pass
    return DEFAULT_PERSONA


# ─── Heartbeat registry ─────────────────────────────────────────────────────


class AgentRuntime:
    """One Heartbeat per active senior. Listens for ticks, emits via
    SocketIO, and exposes the most-recent snapshot to API consumers."""

    def __init__(self, socketio=None):
        self.socketio = socketio
        self._heartbeats: dict[str, Heartbeat] = {}
        self._lock = threading.Lock()
        self._latest_snapshots: dict[str, Any] = {}  # user_id → EngineSnapshot

    # ── lifecycle ──

    def ensure(self, user_id: str) -> Heartbeat:
        """Get-or-create Heartbeat for this user. Idempotent."""
        with self._lock:
            hb = self._heartbeats.get(user_id)
            if hb and hb.running:
                return hb
            persona = _persona_for_user(user_id)
            weights = PERSONA_WEIGHTS.get(persona)
            hb = Heartbeat(
                persona=persona,
                weights=weights,
                state_provider=lambda uid=user_id: collect_state_history(uid),
                on_tick=lambda snap, uid=user_id: self._on_tick(uid, snap),
            )
            self._heartbeats[user_id] = hb
            hb.start()
            logger.info(f"[agent_runtime] heartbeat started for {user_id} (persona={persona})")
            return hb

    def stop(self, user_id: str) -> None:
        with self._lock:
            hb = self._heartbeats.pop(user_id, None)
        if hb:
            hb.stop()
            logger.info(f"[agent_runtime] heartbeat stopped for {user_id}")

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._heartbeats.keys())
        for uid in ids:
            self.stop(uid)

    # ── snapshot accessors ──

    def latest(self, user_id: str):
        return self._latest_snapshots.get(user_id)

    def context_hints(self, user_id: str, module: str) -> dict:
        hb = self._heartbeats.get(user_id)
        if hb and hb.last:
            return hb.context_hints(module)
        # Cold start: ensure a heartbeat exists for this user, return what we get
        self.ensure(user_id)
        hb = self._heartbeats.get(user_id)
        return hb.context_hints(module) if hb else {"available": False, "module": module}

    def force_tick(self, user_id: str):
        hb = self.ensure(user_id)
        return hb.tick()

    # ── tick handler ──

    def _on_tick(self, user_id: str, snap) -> None:
        self._latest_snapshots[user_id] = snap

        # Emit via SocketIO (best-effort, never block heartbeat)
        if self.socketio:
            try:
                self.socketio.emit('agent:tick', _serialize_snapshot(snap),
                                   room=f'user-{user_id}')
            except Exception as e:  # noqa: BLE001
                logger.debug(f"socketio emit failed: {e}")

        # Sprint X20.3 — full ISO 27001 audit log entry on every preemptive.
        # Non-preemptive ticks are NOT logged (would flood; one entry per
        # 30s in CRISIS = ~2880/day per senior). Only meaningful events.
        if snap.preemptive.crosses_up:
            logger.info(
                f"[agent_runtime:{user_id}] preemptive {snap.mode} → "
                f"{snap.preemptive.predicted_mode} in "
                f"{snap.preemptive.peak_at_minute} min"
            )
            try:
                from .audit import log_event
                log_event(
                    user_id=user_id,
                    actor='agent_runtime',
                    action='preemptive_trigger',
                    severity=snap.preemptive.predicted_mode,
                    payload={
                        'current_mode':   snap.mode,
                        'predicted_mode': snap.preemptive.predicted_mode,
                        'peak_c':         round(snap.preemptive.peak_c, 2),
                        'peak_at_min':    snap.preemptive.peak_at_minute,
                        'c_total':        round(snap.c_total, 2),
                        'alpha':          round(snap.state.alpha, 3),
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"audit log_event failed: {e}")


# ─── Snapshot serialization for SocketIO / REST ─────────────────────────────


def _serialize_snapshot(snap) -> dict:
    """Convert EngineSnapshot to a JSON-safe dict matching context_hints
    schema, with horizon details for advanced UIs."""
    return {
        'mode': snap.mode,
        'c_total': round(snap.c_total, 2),
        'alpha': round(snap.state.alpha, 3),
        'domains': {
            'emotional':     round(snap.state.c_emotional, 2),
            'environmental': round(snap.state.c_environmental, 2),
            'social':        round(snap.state.c_social, 2),
            'physical':      round(snap.state.c_physical, 2),
        },
        'trend': {
            'c_emotional': round(snap.trend.c_emotional, 3),
            'alpha':       round(snap.trend.alpha, 3),
        },
        'preemptive': {
            'crosses_up':     snap.preemptive.crosses_up,
            'crosses_down':   snap.preemptive.crosses_down,
            'predicted_mode': snap.preemptive.predicted_mode,
            'peak_c':         round(snap.preemptive.peak_c, 2),
            'peak_at_minute': snap.preemptive.peak_at_minute,
        },
        'speech': {
            'rate':         round(snap.speech.rate, 3),
            'pitch':        round(snap.speech.pitch, 2),
            'pause_ms':     snap.speech.pause_ms,
            'empathy':      round(snap.speech.empathy, 2),
            'ssml_prosody': snap.speech.to_ssml_prosody(),
        },
        'ts': snap.state.t.isoformat() if snap.state else None,
    }


# Module-level singleton (set by app.py during startup)
_runtime_singleton: Optional[AgentRuntime] = None


def get_runtime() -> Optional[AgentRuntime]:
    return _runtime_singleton


def init_runtime(socketio=None) -> AgentRuntime:
    """Idempotent — call from app.py once during startup."""
    global _runtime_singleton
    if _runtime_singleton is None:
        _runtime_singleton = AgentRuntime(socketio=socketio)
        logger.info("[agent_runtime] initialized")
    return _runtime_singleton
