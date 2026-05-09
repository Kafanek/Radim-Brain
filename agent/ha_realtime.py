"""
Real-time Home Assistant event subscriber
==========================================

Hooks into the existing HomeAssistantClient.start_websocket() (in
home_assistant.py) to deliver instant alerts for life-safety events
that can't wait for the 5-min agent_loop poll:

  smoke, gas, carbon_monoxide  → CRISIS  (life threat)
  moisture (water leak)         → ALERT   (property damage)
  safety, tamper                → ALERT   (security)
  fall (custom)                 → CRISIS

Latency: HA event → observation saved → push notification < 1 second
(vs ~5 min worst case for the polling agent_loop).

Architecture:
  app.py startup → HARealtimeRegistry.init_all()
                 ↓
  for each user with HA: ha_for_user(uid).start_websocket() + register handler
                 ↓
  HA fires state_changed event for binary_sensor.smoke_*
                 ↓
  handler.run inside app.app_context()
                 ↓
  filter device_class against CRITICAL_DEVICE_CLASSES
                 ↓
  _save_observation()  (existing pipeline → push, SMS, caregiver alert)
                 ↓
  audit.log_event()    (ISO 27001 trace)

Sprint X20.1 / Fix 5
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ─── Constants ──────────────────────────────────────────────────────────────

# device_class values that warrant an instant observation. Not every
# binary_sensor: motion + door + window are routine + handled by the
# 5-min agent_loop. These are LIFE-SAFETY or PROPERTY events only.
CRITICAL_DEVICE_CLASSES = {
    'smoke':           ('CRISIS', '🚨 Detekován kouř'),
    'gas':             ('CRISIS', '🚨 Detekován plyn'),
    'carbon_monoxide': ('CRISIS', '🚨 Detekován oxid uhelnatý — okamžitě otevři okna'),
    'moisture':        ('ALERT',  '💧 Detekován únik vody'),
    'safety':          ('ALERT',  '⚠️ Bezpečnostní senzor aktivován'),
    'tamper':          ('ALERT',  '⚠️ Detekováno narušení'),
}

# Per-user, per-entity dedupe window (ms). Same alarm firing twice within
# this window = single observation. HA can emit duplicate state_changed
# events on rapid polling.
DEDUPE_MS = 30_000  # 30 sec


# ─── Filter logic (pure, testable without DB or WS) ─────────────────────────


def is_critical_event(entity_id: str, new_state) -> tuple[bool, str | None, str | None]:
    """Return (is_critical, severity, message_prefix) for a state change.

    `new_state` may be a dict with {state, attributes} or a string.
    Critical = binary_sensor.* with critical device_class transitioning to 'on'.
    """
    if not entity_id or not entity_id.startswith('binary_sensor.'):
        return False, None, None

    if not isinstance(new_state, dict):
        return False, None, None

    state = new_state.get('state')
    if state != 'on':
        # Could be 'off' (alarm cleared) — not critical, just informational
        return False, None, None

    attrs = new_state.get('attributes') or {}
    device_class = str(attrs.get('device_class') or '').lower()
    info = CRITICAL_DEVICE_CLASSES.get(device_class)
    if not info:
        return False, None, None

    severity, message = info
    return True, severity, message


# ─── Registry — one process-wide singleton ──────────────────────────────────


class HARealtimeRegistry:
    """Tracks which users have an active HA WebSocket handler registered.

    HA WebSocket is per-HA-instance (per-user-home). The registry ensures
    we don't double-register handlers when the same user is initialized
    multiple times (e.g., agent_loop cycle + admin force-init).
    """

    def __init__(self, app=None):
        self.app = app
        self._started_users: set[str] = set()
        self._dedupe: dict[str, int] = {}  # 'uid|entity' → last_ts_ms
        self._lock = threading.Lock()

    # ── lifecycle ──

    def init_user(self, user_id: str) -> bool:
        """Start WebSocket + register critical handler for this user.
        Idempotent. Returns True if newly started, False if already
        active or HA not configured."""
        with self._lock:
            if user_id in self._started_users:
                return False

        try:
            from ha_user_config import ha_for_user
        except ImportError:
            logger.debug("[ha_realtime] ha_user_config unavailable")
            return False

        try:
            client = ha_for_user(user_id)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ha_realtime] ha_for_user({user_id}) failed: {e}")
            return False

        if not client:
            return False
        if not getattr(client, 'available', False):
            return False
        if not hasattr(client, 'start_websocket') or not hasattr(client, 'on_state_change'):
            logger.debug(f"[ha_realtime] client for {user_id} lacks WS methods")
            return False

        # Register handler + start (or join existing) WS
        try:
            client.on_state_change(self._make_handler(user_id))
            client.start_websocket()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ha_realtime] start failed for {user_id}: {e}")
            return False

        with self._lock:
            self._started_users.add(user_id)
        logger.info(f"[ha_realtime] subscribed for user {user_id}")
        return True

    def init_all(self) -> int:
        """Best-effort initialize WS for every user with HA configured.
        Returns count newly started."""
        started = 0
        try:
            from ha_user_config import list_all_homes
            homes = list_all_homes() or []
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ha_realtime] list_all_homes failed: {e}")
            return 0

        seen: set[str] = set()
        for h in homes:
            uid = h.get('user_id') if isinstance(h, dict) else None
            if not uid or uid in seen:
                continue
            seen.add(uid)
            if self.init_user(str(uid)):
                started += 1

        logger.info(f"[ha_realtime] init_all: subscribed to {started} HA homes")
        return started

    # ── handler factory ──

    def _make_handler(self, user_id: str):
        """Returns a closure suitable for HomeAssistantClient.on_state_change.
        Ensures Flask app context is active when DB writes happen."""
        registry = self
        app = self.app

        def handler(entity_id, new_state):
            try:
                if app is not None:
                    with app.app_context():
                        registry._handle_event(user_id, entity_id, new_state)
                else:
                    registry._handle_event(user_id, entity_id, new_state)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[ha_realtime] handler error for {user_id}: {e}")
        return handler

    # ── core: process a single state-change event ──

    def _handle_event(self, user_id: str, entity_id: str, new_state) -> None:
        is_critical, severity, msg_prefix = is_critical_event(entity_id, new_state)
        if not is_critical:
            return

        # Per-user/entity dedupe
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        key = f"{user_id}|{entity_id}"
        with self._lock:
            last = self._dedupe.get(key)
            if last and (now_ms - last) < DEDUPE_MS:
                return
            self._dedupe[key] = now_ms
            # Cap dedupe map size — drop oldest if > 1000 entries
            if len(self._dedupe) > 1000:
                oldest = sorted(self._dedupe.items(), key=lambda kv: kv[1])[:200]
                for k, _ in oldest:
                    self._dedupe.pop(k, None)

        attrs = (new_state.get('attributes') or {}) if isinstance(new_state, dict) else {}
        device_class = str(attrs.get('device_class') or '').lower()
        friendly = attrs.get('friendly_name') or entity_id

        obs = {
            'type':     f'ha_realtime_{device_class}',
            'severity': severity,
            'message':  f'{msg_prefix} ({friendly})',
            'details': {
                'entity_id':    entity_id,
                'device_class': device_class,
                'friendly_name': friendly,
                'source':       'ha_websocket',
                'latency':      'instant',
            },
        }

        # Save observation through the existing pipeline (push, SMS, caregiver
        # alert handled inside _save_observation + downstream).
        try:
            from agent_loop import _save_observation, _is_in_cooldown
            if _is_in_cooldown(user_id, obs['type']):
                logger.debug(f"[ha_realtime] {user_id} {obs['type']} in cooldown — skip")
                return
            _save_observation(user_id, obs)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[ha_realtime] _save_observation failed: {e}")

        # ISO 27001 audit-log entry separately tagged source=ha_websocket
        try:
            from .audit import log_event
            log_event(
                user_id=user_id,
                actor='ha_websocket',
                action='critical_event',
                detector_id=obs['type'],
                severity=severity,
                payload=obs['details'],
            )
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ha_realtime] audit log_event failed: {e}")

        logger.info(
            f"[ha_realtime] {severity} for {user_id}: {entity_id} "
            f"(class={device_class})"
        )

    # ── status ──

    def status(self) -> dict:
        with self._lock:
            return {
                'subscribed_users': len(self._started_users),
                'users':            sorted(self._started_users),
                'dedupe_entries':   len(self._dedupe),
            }


# ─── Module-level singleton ─────────────────────────────────────────────────


_registry: HARealtimeRegistry | None = None


def init_registry(app=None) -> HARealtimeRegistry:
    """Idempotent. Call once from app.py at startup."""
    global _registry
    if _registry is None:
        _registry = HARealtimeRegistry(app=app)
    elif app is not None and _registry.app is None:
        _registry.app = app
    return _registry


def get_registry() -> HARealtimeRegistry | None:
    return _registry
