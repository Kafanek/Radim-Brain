"""
🏠 HOME ASSISTANT INTEGRATION v2.0
====================================
Radim ↔ Home Assistant hybrid integration.
HA runs on NUC (hardware layer), Radim is the AI brain.

Features:
    - homeassistant_api library (official Python client)
    - REST API + WebSocket for real-time events
    - MQTT bridge for IoT sensors (paho-mqtt)
    - Direct device control: TP-Link Kasa, Yeelight (no HA needed)
    - Device discovery & caching
    - Room-based grouping for seniors
    - Agent-compatible actions (lights, climate, sensors, locks, media)
    - Fallback to simulated devices when HA unavailable

Libraries:
    homeassistant_api  — Official HA REST/WS Python client
    paho-mqtt          — MQTT for Zigbee/IoT sensors
    python-kasa        — TP-Link Kasa smart plugs/lights (direct, no HA)
    yeelight           — Xiaomi Yeelight bulbs (direct, no HA)

Config (env vars):
    HA_URL              — Home Assistant URL (e.g., http://192.168.1.100:8123)
    HA_TOKEN            — Long-lived access token
    HA_WEBHOOK_SECRET   — For HA → Radim webhooks
    MQTT_BROKER         — MQTT broker IP (e.g., 192.168.1.100)
    MQTT_PORT           — MQTT port (default 1883)
    MQTT_USER           — MQTT username (optional)
    MQTT_PASS           — MQTT password (optional)
    KASA_DEVICES        — Comma-separated Kasa IPs (e.g., 192.168.1.50,192.168.1.51)
    YEELIGHT_DEVICES    — Comma-separated Yeelight IPs
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# OPTIONAL LIBRARY IMPORTS (graceful fallback)
# ═══════════════════════════════════════════════════════════════════

try:
    from homeassistant_api import Client as HAAPIClient
    HAS_HA_LIB = True
    logger.info("✅ homeassistant_api library loaded")
except ImportError:
    HAS_HA_LIB = False
    logger.info("⚠️ homeassistant_api not installed — using REST fallback")

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
    logger.info("✅ paho-mqtt library loaded")
except ImportError:
    HAS_MQTT = False

try:
    import asyncio
    from kasa import Discover as KasaDiscover, SmartPlug, SmartBulb
    HAS_KASA = True
    logger.info("✅ python-kasa library loaded")
except ImportError:
    HAS_KASA = False

try:
    from yeelight import Bulb as YeelightBulb, discover_bulbs as yeelight_discover
    HAS_YEELIGHT = True
    logger.info("✅ yeelight library loaded")
except ImportError:
    HAS_YEELIGHT = False

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

HA_URL = os.environ.get('HA_URL', '')
HA_TOKEN = os.environ.get('HA_TOKEN', '')
HA_WEBHOOK_SECRET = os.environ.get('HA_WEBHOOK_SECRET', '')

# Device type mappings
DEVICE_TYPES = {
    'light': {'icon': '💡', 'name': 'Světlo', 'domain': 'light'},
    'switch': {'icon': '🔌', 'name': 'Zásuvka', 'domain': 'switch'},
    'climate': {'icon': '🌡️', 'name': 'Topení/Klima', 'domain': 'climate'},
    'sensor': {'icon': '📊', 'name': 'Senzor', 'domain': 'sensor'},
    'binary_sensor': {'icon': '🚪', 'name': 'Senzor', 'domain': 'binary_sensor'},
    'lock': {'icon': '🔒', 'name': 'Zámek', 'domain': 'lock'},
    'cover': {'icon': '🪟', 'name': 'Roleta', 'domain': 'cover'},
    'media_player': {'icon': '📺', 'name': 'Média', 'domain': 'media_player'},
    'camera': {'icon': '📷', 'name': 'Kamera', 'domain': 'camera'},
    'fan': {'icon': '🌀', 'name': 'Ventilátor', 'domain': 'fan'},
    'vacuum': {'icon': '🤖', 'name': 'Vysavač', 'domain': 'vacuum'},
    'alarm_control_panel': {'icon': '🚨', 'name': 'Alarm', 'domain': 'alarm_control_panel'},
}

# ═══════════════════════════════════════════════════════════════════
# Diagnostic / system entity filter (Sprint X9)
# ═══════════════════════════════════════════════════════════════════
# HA REST API returns ALL entities including the platform's internal
# diagnostic + system entities (backup manager, supervisor health,
# update checkers, signal strength sensors, ...). These pollute the
# senior-facing device list. Skip them in `_build_rooms` — they're
# admin-tier, not living-room-tier.
#
# Strategy:
#   1. attribute `entity_category` = 'diagnostic' | 'config' (HA 2022+
#      standard, set by integration developers for non-user-facing
#      entities). Most reliable.
#   2. domain blacklist (`update`, `button`, `event`) — these never
#      represent a thing in the home; they're meta controls for HA itself.
#   3. entity_id substring patterns for older integrations / community
#      add-ons that haven't adopted entity_category yet.

_DIAGNOSTIC_DOMAINS = {
    'update', 'button', 'event',
    # v397.16: sun, weather, person, zone, todo, tts, group are HA meta
    # entities that aren't physical devices. Filter at domain level so we
    # don't have to enumerate every variant in patterns.
    'sun', 'weather', 'person', 'zone', 'todo', 'tts', 'group',
}

_DIAGNOSTIC_ID_PATTERNS = (
    'backup_', '_backup', 'supervisor', '_disk_', '_memory',
    '_cpu', '_load_', '_uptime', '_version', 'integration_health',
    'home_assistant_core', 'home_assistant_supervisor',
    'home_assistant_operating_system',
    'next_scheduled', 'update_available', 'check_for_updates',
    'system_health', 'pi_hole', 'hacs_',
    # v397.16: HA "sun" integration exposes these as `sensor.*` so the
    # domain blacklist above doesn't catch them — match on entity_id pattern.
    'next_dawn', 'next_dusk', 'next_setting', 'next_rising',
    'next_midnight', 'next_noon', 'sun_next_',
    # v397.17: signal/connectivity diagnostics (Tapo P115 / Tapo Hub +
    # most other integrations expose RSSI + signal-level + linkquality
    # as user-non-actionable metrics). Push them to "Systémové".
    '_signal_strength', '_signal_level', 'signal_level',
    '_rssi', '_wifi_strength', '_link_quality', 'linkquality',
    '_battery_state', '_charging_state',
    # v397.17: Tapo zero-value sensors that confuse users (when a P115
    # is OFF, current_power = 0.0 W which looks like a broken sensor).
    # Energy-today is useful (cumulative), live power isn't until plug
    # is being used. Filter only `current_power`; keep `today_energy`,
    # `month_energy`, `total_energy`.
    '_current_power', 'current_power',
    # Generic "test" / "ping" / "uptime" sensors that integrations expose
    '_ping', 'restart_required', '_uptime_seconds',
)


def _is_diagnostic_entity(entity_id, attributes):
    """Heuristic: is this a HA-internal entity that should be hidden
    from the senior-facing UI? Keep behavior conservative — false
    negatives just mean a noisy device list; false positives could hide
    something the user actually cares about."""
    domain = entity_id.split('.')[0]
    if domain in _DIAGNOSTIC_DOMAINS:
        return True
    cat = (attributes or {}).get('entity_category')
    if cat in ('diagnostic', 'config'):
        return True
    eid_lower = entity_id.lower()
    return any(p in eid_lower for p in _DIAGNOSTIC_ID_PATTERNS)


# Room mappings for Czech seniors
ROOM_NAMES = {
    'living_room': '🛋️ Obývák',
    'bedroom': '🛏️ Ložnice',
    'kitchen': '🍳 Kuchyně',
    'bathroom': '🚿 Koupelna',
    'hallway': '🚪 Chodba',
    'balcony': '🌿 Balkon',
    'garage': '🚗 Garáž',
    'garden': '🌳 Zahrada',
    'office': '💼 Pracovna',
    # v397.4: catch-all bucket for entities without area_id assigned
    # (typical for fresh Tapo Controller install before user assigns areas)
    '_unassigned': '📦 Nezařazené',
}

# ═══════════════════════════════════════════════════════════════════
# HA API CLIENT
# ═══════════════════════════════════════════════════════════════════

class HomeAssistantClient:
    """REST + WebSocket client for Home Assistant."""

    def __init__(self, url=None, token=None):
        self.url = (url or HA_URL).rstrip('/')
        self.token = token or HA_TOKEN
        self.connected = False
        self._cache = {}  # entity_id → state
        self._cache_time = 0
        self._cache_ttl = 30  # seconds
        self._rooms = {}  # room → [entity_ids]
        self._ws = None
        self._ws_thread = None
        self._event_handlers = []
        # v8.19.35: real client = real connection. Subclass SimulatedHomeAssistant
        # overrides to False so radio handler správně fallbackne na frontend.
        self.is_real = True

    @property
    def available(self):
        return bool(self.url and self.token)

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    # ─── REST API ───

    def _request(self, method, path, data=None, timeout=10):
        """Make HTTP request to HA API."""
        import requests
        try:
            url = f'{self.url}/api/{path}'
            resp = requests.request(
                method, url,
                headers=self._headers(),
                json=data,
                timeout=timeout
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 201:
                return resp.json() if resp.text else {'success': True}
            else:
                logger.warning(f'HA API {method} {path}: {resp.status_code} {resp.text[:200]}')
                return None
        except Exception as e:
            logger.warning(f'HA API error: {e}')
            return None

    def check_connection(self):
        """Test HA connection. v397.6: 5s timeout (down from default 10s)
        — fail fast on slow / dead tunnels so /api/ha/status doesn't push
        Heroku request close to its 30s limit.
        """
        if not self.available:
            return {'connected': False, 'reason': 'HA_URL or HA_TOKEN not configured'}
        result = self._request('GET', '', timeout=5)
        if result and 'message' in result:
            self.connected = True
            return {'connected': True, 'message': result['message'], 'url': self.url}
        self.connected = False
        return {'connected': False, 'reason': 'Cannot reach HA'}

    def get_config(self):
        """Get HA configuration."""
        return self._request('GET', 'config')

    # ─── STATES ───

    def get_all_states(self, use_cache=True):
        """Get all entity states."""
        now = time.time()
        if use_cache and self._cache and (now - self._cache_time) < self._cache_ttl:
            return list(self._cache.values())

        states = self._request('GET', 'states')
        if states:
            self._cache = {s['entity_id']: s for s in states}
            self._cache_time = now
            self._build_rooms()
            return states
        return list(self._cache.values()) if self._cache else []

    def get_state(self, entity_id):
        """Get single entity state."""
        # Try cache first
        if entity_id in self._cache:
            return self._cache[entity_id]
        state = self._request('GET', f'states/{entity_id}')
        if state:
            self._cache[entity_id] = state
        return state

    def _build_rooms(self):
        """Build room→entities mapping from entity attributes.

        v397.4: entities without area_id AND without guessable room name
        land in `_unassigned` bucket. Frontend can show them under
        "Nezařazené" so user sees their Tapo P115 etc. even when HA
        Tapo Controller didn't auto-set area_id.

        v397.15 (Sprint X9): also skip HA diagnostic entities (backup
        manager, system updates, supervisor health, etc.) — they pollute
        the user-facing device list. They're still queryable via the
        admin endpoint if needed.
        """
        self._rooms = {}
        for entity_id, state in self._cache.items():
            # Skip noise: HA system entities and meta entities aren't
            # rooms-relevant (sun, weather, person, zone, todo, tts, ...)
            domain = entity_id.split('.')[0]
            if domain not in DEVICE_TYPES:
                continue
            attrs = state.get('attributes', {}) or {}
            if _is_diagnostic_entity(entity_id, attrs):
                continue
            area = attrs.get('area_id', '')
            friendly = attrs.get('friendly_name', '')
            room = area or self._guess_room(entity_id, friendly)
            if not room:
                room = '_unassigned'
            self._rooms.setdefault(room, []).append(entity_id)

    def _guess_room(self, entity_id, friendly_name):
        """Guess room from entity naming patterns."""
        text = f'{entity_id} {friendly_name}'.lower()
        for key in ROOM_NAMES:
            if key.replace('_', '') in text.replace('_', '').replace(' ', ''):
                return key
        return ''

    # ─── SERVICES (ACTIONS) ───

    def call_service(self, domain, service, entity_id=None, data=None):
        """Call HA service (turn on/off, set temperature, etc.)."""
        payload = data or {}
        if entity_id:
            payload['entity_id'] = entity_id
        return self._request('POST', f'services/{domain}/{service}', payload)

    # ─── CONVENIENCE METHODS ───

    def light_on(self, entity_id, brightness=None, color_temp=None):
        """Turn on a light."""
        data = {}
        if brightness is not None:
            data['brightness_pct'] = max(1, min(100, brightness))
        if color_temp is not None:
            data['color_temp_kelvin'] = color_temp
        return self.call_service('light', 'turn_on', entity_id, data)

    def light_off(self, entity_id):
        return self.call_service('light', 'turn_off', entity_id)

    def set_temperature(self, entity_id, temperature):
        """Set climate target temperature."""
        return self.call_service('climate', 'set_temperature', entity_id, {
            'temperature': temperature
        })

    def lock(self, entity_id):
        return self.call_service('lock', 'lock', entity_id)

    def unlock(self, entity_id):
        return self.call_service('lock', 'unlock', entity_id)

    def cover_open(self, entity_id):
        return self.call_service('cover', 'open_cover', entity_id)

    def cover_close(self, entity_id):
        return self.call_service('cover', 'close_cover', entity_id)

    def switch_on(self, entity_id):
        return self.call_service('switch', 'turn_on', entity_id)

    def switch_off(self, entity_id):
        return self.call_service('switch', 'turn_off', entity_id)

    def media_play(self, entity_id):
        return self.call_service('media_player', 'media_play', entity_id)

    def media_pause(self, entity_id):
        return self.call_service('media_player', 'media_pause', entity_id)

    def media_stop(self, entity_id):
        return self.call_service('media_player', 'media_stop', entity_id)

    def media_volume(self, entity_id, volume):
        """Set volume 0-100."""
        return self.call_service('media_player', 'volume_set', entity_id, {
            'volume_level': volume / 100.0
        })

    def play_media(self, entity_id, media_url, media_type='audio/mp3'):
        """v8.19.35: Play arbitrary media URL on a player (radio streams).

        Used by ha_radio_play intent — allows Radim hlasem zapnout rádio
        skrz Home Assistant na vybraném reproduktoru (kuchyně, obývák).
        Vrací True on success, False on failure (frontend pak fallbackne
        na lokální audio element).
        """
        return self.call_service('media_player', 'play_media', entity_id, {
            'media_content_id': media_url,
            'media_content_type': media_type
        })

    def find_default_media_player(self):
        """Vrátí první nalezený media_player entity_id, nebo None.

        Senior typicky má jeden hlavní reproduktor (kuchyně/obývák).
        Pokud uživatel chce konkrétní místnost, volat get_devices_by_type
        a vybrat ručně.
        """
        try:
            devices = self.get_devices_by_type('media_player')
            mps = devices.get('media_player', [])
            return mps[0]['entity_id'] if mps else None
        except Exception:
            return None

    def alarm_arm(self, entity_id, code=None):
        data = {'code': code} if code else {}
        return self.call_service('alarm_control_panel', 'alarm_arm_away', entity_id, data)

    def alarm_disarm(self, entity_id, code=None):
        data = {'code': code} if code else {}
        return self.call_service('alarm_control_panel', 'alarm_disarm', entity_id, data)

    # ─── DEVICE DISCOVERY ───

    def get_devices_by_type(self, device_type=None):
        """Get devices grouped by type."""
        states = self.get_all_states()
        devices = {}
        for s in states:
            eid = s['entity_id']
            domain = eid.split('.')[0]
            if device_type and domain != device_type:
                continue
            if domain not in DEVICE_TYPES:
                continue
            attrs = s.get('attributes', {}) or {}
            # Sprint X9: skip HA-internal diagnostic/config entities
            if _is_diagnostic_entity(eid, attrs):
                continue
            dtype = DEVICE_TYPES[domain]
            devices.setdefault(domain, []).append({
                'entity_id': eid,
                'name': attrs.get('friendly_name', eid),
                'state': s.get('state', 'unknown'),
                'icon': dtype['icon'],
                'type_name': dtype['name'],
                'attributes': attrs,
                'last_changed': s.get('last_changed', ''),
            })
        return devices

    def get_system_entities(self):
        """Sprint X9 / B: Return entities that _build_rooms filtered out
        as 'diagnostic' so the frontend can show them in a separate
        collapsible "Systémové" section. Includes the entity_id, name,
        state, and a guess at category for grouping."""
        states = self.get_all_states()
        items = []
        for s in states:
            eid = s.get('entity_id', '')
            domain = eid.split('.')[0] if eid else ''
            attrs = s.get('attributes', {}) or {}
            if not _is_diagnostic_entity(eid, attrs):
                continue
            # Skip noise that is technically diagnostic but truly useless
            # (sun, weather metadata, person, zone trackers — those weren't
            # in DEVICE_TYPES so wouldn't appear anyway, but defensive)
            if domain in ('sun', 'person', 'zone', 'weather', 'tts', 'todo', 'group'):
                continue
            # Pick a category label for grouping in UI
            eid_lower = eid.lower()
            if 'backup' in eid_lower:
                cat = 'backup'
            elif 'update' in eid_lower or domain == 'update':
                cat = 'updates'
            elif 'supervisor' in eid_lower or 'home_assistant_' in eid_lower:
                cat = 'supervisor'
            elif '_signal' in eid_lower or '_rssi' in eid_lower:
                cat = 'signal'
            elif domain in ('button', 'event'):
                cat = 'controls'
            else:
                cat = 'other'
            items.append({
                'entity_id': eid,
                'name': attrs.get('friendly_name', eid),
                'state': s.get('state', 'unknown'),
                'category': cat,
                'domain': domain,
            })
        # Sort: backup → updates → supervisor → signal → controls → other,
        # then alphabetical by name within category
        cat_order = {'backup': 0, 'updates': 1, 'supervisor': 2,
                     'signal': 3, 'controls': 4, 'other': 5}
        items.sort(key=lambda x: (cat_order.get(x['category'], 9),
                                  x['name'].lower()))
        return items

    def get_devices_by_room(self):
        """Get devices grouped by room."""
        self.get_all_states()
        rooms = {}
        for room, entities in self._rooms.items():
            room_name = ROOM_NAMES.get(room, f'📍 {room}')
            room_devices = []
            for eid in entities:
                state = self._cache.get(eid, {})
                domain = eid.split('.')[0]
                if domain not in DEVICE_TYPES:
                    continue
                dtype = DEVICE_TYPES[domain]
                room_devices.append({
                    'entity_id': eid,
                    'name': state.get('attributes', {}).get('friendly_name', eid),
                    'state': state.get('state', 'unknown'),
                    'icon': dtype['icon'],
                    'domain': domain,
                })
            if room_devices:
                rooms[room] = {'name': room_name, 'devices': room_devices}
        return rooms

    def get_sensors_summary(self):
        """Get sensor readings summary for agent loop.

        v397.4: added energy / power / signal_strength / runtime
        categories so Tapo P115 sensors (current_power, today_energy)
        appear in Radim Domácnost UI.
        """
        states = self.get_all_states()
        sensors = {
            'temperature': [],
            'humidity': [],
            'motion': [],
            'door': [],
            'light_level': [],
            'air_quality': [],
            'battery': [],
            'power': [],          # v397.4 — Tapo P115 current_power
            'energy': [],         # v397.4 — Tapo P115 today/month energy
            'signal': [],         # v397.4 — Tapo signal_level
            'runtime': [],        # v397.4 — Tapo today/month runtime
        }
        for s in states:
            eid = s['entity_id']
            state = s.get('state', '')
            attrs = s.get('attributes', {})
            device_class = attrs.get('device_class', '')
            unit = attrs.get('unit_of_measurement', '')
            name = attrs.get('friendly_name', eid)

            try:
                val = float(state) if state not in ('unknown', 'unavailable', '') else None
            except (ValueError, TypeError):
                val = None

            if device_class == 'temperature' or '°C' in unit:
                if val is not None:
                    sensors['temperature'].append({'name': name, 'value': val, 'unit': '°C', 'entity_id': eid})
            elif device_class == 'humidity':
                if val is not None:
                    sensors['humidity'].append({'name': name, 'value': val, 'unit': '%', 'entity_id': eid})
            elif device_class == 'motion' or 'motion' in eid:
                sensors['motion'].append({'name': name, 'state': state, 'entity_id': eid})
            elif device_class == 'door' or device_class == 'opening':
                sensors['door'].append({'name': name, 'state': state, 'entity_id': eid})
            elif device_class == 'illuminance':
                if val is not None:
                    sensors['light_level'].append({'name': name, 'value': val, 'unit': 'lx', 'entity_id': eid})
            elif device_class == 'battery':
                if val is not None:
                    sensors['battery'].append({'name': name, 'value': val, 'unit': '%', 'entity_id': eid})
            elif device_class in ('pm25', 'pm10', 'co2', 'aqi'):
                if val is not None:
                    sensors['air_quality'].append({'name': name, 'value': val, 'device_class': device_class, 'entity_id': eid})
            # v397.4 — Tapo P115 power/energy/signal sensors
            elif device_class == 'power' or unit in ('W', 'kW'):
                if val is not None:
                    sensors['power'].append({'name': name, 'value': val, 'unit': unit or 'W', 'entity_id': eid})
            elif device_class == 'energy' or unit in ('kWh', 'Wh'):
                if val is not None:
                    sensors['energy'].append({'name': name, 'value': val, 'unit': unit or 'kWh', 'entity_id': eid})
            elif device_class == 'signal_strength' or unit == 'dBm':
                if val is not None:
                    sensors['signal'].append({'name': name, 'value': val, 'unit': 'dBm', 'entity_id': eid})
            elif unit in ('min', 'minutes', 'm') and 'runtime' in eid.lower():
                if val is not None:
                    sensors['runtime'].append({'name': name, 'value': val, 'unit': 'min', 'entity_id': eid})

        return sensors

    # ─── WEBSOCKET (Real-time events) ───

    def start_websocket(self):
        """Start WebSocket connection for real-time events."""
        if not self.available:
            return
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True)
        self._ws_thread.start()

    def _ws_loop(self):
        """WebSocket event loop."""
        import websocket
        ws_url = self.url.replace('http://', 'ws://').replace('https://', 'wss://')
        ws_url = f'{ws_url}/api/websocket'

        while True:
            try:
                ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                    on_open=self._on_ws_open,
                )
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.warning(f'HA WebSocket error: {e}')
            time.sleep(30)  # Reconnect after 30s

    def _on_ws_open(self, ws):
        logger.info('HA WebSocket connected')

    def _on_ws_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get('type', '')

            if msg_type == 'auth_required':
                ws.send(json.dumps({'type': 'auth', 'access_token': self.token}))
            elif msg_type == 'auth_ok':
                self.connected = True
                logger.info('HA WebSocket authenticated')
                # Subscribe to state changes
                ws.send(json.dumps({
                    'id': 1,
                    'type': 'subscribe_events',
                    'event_type': 'state_changed'
                }))
            elif msg_type == 'event':
                event_data = data.get('event', {}).get('data', {})
                entity_id = event_data.get('entity_id', '')
                new_state = event_data.get('new_state', {})
                if entity_id and new_state:
                    self._cache[entity_id] = new_state
                    for handler in self._event_handlers:
                        try:
                            handler(entity_id, new_state)
                        except Exception as e:
                            logger.warning(f'Event handler error: {e}')
        except Exception as e:
            logger.warning(f'WS message parse error: {e}')

    def _on_ws_error(self, ws, error):
        logger.warning(f'HA WebSocket error: {error}')

    def _on_ws_close(self, ws, code, msg):
        self.connected = False
        logger.info(f'HA WebSocket closed: {code} {msg}')

    def on_state_change(self, handler):
        """Register event handler: handler(entity_id, new_state)."""
        self._event_handlers.append(handler)

    # ─── AGENT ACTIONS ───

    def execute_agent_action(self, action, params=None):
        """Execute action from agent loop or voice command.

        Actions:
            light_on, light_off, light_brightness
            climate_set, climate_off
            lock, unlock
            cover_open, cover_close
            switch_on, switch_off
            alarm_arm, alarm_disarm
            get_temperature, get_humidity, get_status
        """
        params = params or {}
        entity_id = params.get('entity_id', '')

        # Find entity by room + type if no entity_id
        if not entity_id and 'room' in params and 'device_type' in params:
            entity_id = self._find_entity(params['room'], params['device_type'])
            if not entity_id:
                return {'success': False, 'message': f'Zařízení nenalezeno v {params["room"]}'}

        try:
            if action == 'light_on':
                result = self.light_on(entity_id, params.get('brightness'))
                return {'success': True, 'message': '💡 Světlo zapnuto', 'entity_id': entity_id}
            elif action == 'light_off':
                result = self.light_off(entity_id)
                return {'success': True, 'message': '💡 Světlo vypnuto', 'entity_id': entity_id}
            elif action == 'light_brightness':
                result = self.light_on(entity_id, brightness=params.get('brightness', 50))
                return {'success': True, 'message': f'💡 Jas nastaven na {params.get("brightness", 50)}%'}
            elif action == 'climate_set':
                temp = params.get('temperature', 22)
                result = self.set_temperature(entity_id, temp)
                return {'success': True, 'message': f'🌡️ Teplota nastavena na {temp}°C'}
            elif action == 'climate_off':
                result = self.call_service('climate', 'turn_off', entity_id)
                return {'success': True, 'message': '🌡️ Topení vypnuto'}
            elif action == 'lock':
                result = self.lock(entity_id)
                return {'success': True, 'message': '🔒 Zamčeno'}
            elif action == 'unlock':
                result = self.unlock(entity_id)
                return {'success': True, 'message': '🔓 Odemčeno'}
            elif action == 'cover_open':
                result = self.cover_open(entity_id)
                return {'success': True, 'message': '🪟 Roleta otevřena'}
            elif action == 'cover_close':
                result = self.cover_close(entity_id)
                return {'success': True, 'message': '🪟 Roleta zavřena'}
            elif action == 'switch_on':
                result = self.switch_on(entity_id)
                return {'success': True, 'message': '🔌 Zapnuto'}
            elif action == 'switch_off':
                result = self.switch_off(entity_id)
                return {'success': True, 'message': '🔌 Vypnuto'}
            elif action == 'get_temperature':
                sensors = self.get_sensors_summary()
                temps = sensors.get('temperature', [])
                if temps:
                    avg = sum(t['value'] for t in temps) / len(temps)
                    details = ', '.join(f"{t['name']}: {t['value']}°C" for t in temps[:5])
                    return {'success': True, 'message': f'🌡️ Průměrná teplota: {avg:.1f}°C ({details})', 'data': temps}
                return {'success': True, 'message': '🌡️ Žádné teplotní senzory nenalezeny'}
            elif action == 'get_humidity':
                sensors = self.get_sensors_summary()
                hums = sensors.get('humidity', [])
                if hums:
                    avg = sum(h['value'] for h in hums) / len(hums)
                    return {'success': True, 'message': f'💧 Průměrná vlhkost: {avg:.1f}%', 'data': hums}
                return {'success': True, 'message': '💧 Žádné senzory vlhkosti'}
            elif action == 'get_status':
                return self._get_home_status()
            elif action == 'alarm_arm':
                result = self.alarm_arm(entity_id, params.get('code'))
                return {'success': True, 'message': '🚨 Alarm aktivován'}
            elif action == 'alarm_disarm':
                result = self.alarm_disarm(entity_id, params.get('code'))
                return {'success': True, 'message': '🚨 Alarm deaktivován'}
            else:
                return {'success': False, 'message': f'Neznámá akce: {action}'}
        except Exception as e:
            return {'success': False, 'message': f'Chyba: {str(e)}'}

    def _find_entity(self, room, device_type):
        """Find entity by room and device type."""
        room_entities = self._rooms.get(room, [])
        for eid in room_entities:
            if eid.startswith(f'{device_type}.'):
                return eid
        # Fallback: search all entities
        for eid in self._cache:
            if eid.startswith(f'{device_type}.') and room.replace('_', '') in eid.replace('_', ''):
                return eid
        return None

    def _get_home_status(self):
        """Get overall home status summary.

        v397.4: counts switches as part of "controllable" devices
        (Tapo P115 is a switch, not light — but UI should still see it).
        """
        sensors = self.get_sensors_summary()
        devices = self.get_devices_by_type()

        # Lights + switches both count as "things that can be on/off"
        lights = devices.get('light', [])
        switches = devices.get('switch', [])
        on_lights_switches = sum(1 for d in lights + switches if d['state'] == 'on')
        total_lights_switches = len(lights) + len(switches)

        locks_locked = sum(1 for d in devices.get('lock', []) if d['state'] == 'locked')
        locks_total = len(devices.get('lock', []))
        doors_open = sum(1 for s in sensors.get('door', []) if s['state'] == 'on')
        motion_detected = sum(1 for s in sensors.get('motion', []) if s['state'] == 'on')

        temps = sensors.get('temperature', [])
        avg_temp = sum(t['value'] for t in temps) / len(temps) if temps else None

        low_battery = [s for s in sensors.get('battery', []) if s['value'] < 20]

        # Total entity count across all controllable types
        total_devices = sum(len(devices.get(d, [])) for d in (
            'light', 'switch', 'climate', 'lock', 'cover', 'media_player'
        ))

        status = {
            'lights': f'{on_lights_switches}/{total_lights_switches} zapnuto',
            'locks': f'{locks_locked}/{locks_total} zamčeno',
            'doors_open': doors_open,
            'motion': motion_detected > 0,
            'temperature': f'{avg_temp:.1f}°C' if avg_temp else 'N/A',
            'low_battery': [{'name': s['name'], 'level': s['value']} for s in low_battery],
            'total_devices': total_devices,
        }

        msg_parts = [
            f'🏠 Stav domácnosti:',
            f'💡 Světla: {status["lights"]}',
            f'🔒 Zámky: {status["locks"]}',
        ]
        if avg_temp:
            msg_parts.append(f'🌡️ Teplota: {avg_temp:.1f}°C')
        if doors_open:
            msg_parts.append(f'🚪 Otevřené dveře: {doors_open}')
        if low_battery:
            msg_parts.append(f'🔋 Slabá baterie: {", ".join(b["name"] for b in low_battery)}')

        return {
            'success': True,
            'message': '\n'.join(msg_parts),
            'data': status
        }


# ═══════════════════════════════════════════════════════════════════
# SIMULATED DEVICES (for testing without HA)
# ═══════════════════════════════════════════════════════════════════

class SimulatedHomeAssistant(HomeAssistantClient):
    """Simulated HA for development/demo when no HA instance available."""

    def __init__(self):
        super().__init__(url='http://simulated', token='simulated')
        self.connected = True
        # v8.19.35: explicit marker — let intent handlers know to skip HA
        # routing (rádio fallback) and use real-device pipeline (frontend
        # music-module) instead of pretending it played on a fake speaker.
        self.is_real = False
        self._sim_devices = {
            'light.living_room': {'state': 'off', 'attributes': {'friendly_name': 'Obývák světlo', 'brightness': 0, 'area_id': 'living_room', 'device_class': 'light'}},
            'light.bedroom': {'state': 'off', 'attributes': {'friendly_name': 'Ložnice světlo', 'brightness': 0, 'area_id': 'bedroom'}},
            'light.kitchen': {'state': 'on', 'attributes': {'friendly_name': 'Kuchyně světlo', 'brightness': 80, 'area_id': 'kitchen'}},
            'light.hallway': {'state': 'on', 'attributes': {'friendly_name': 'Chodba světlo', 'brightness': 40, 'area_id': 'hallway'}},
            'climate.living_room': {'state': 'heat', 'attributes': {'friendly_name': 'Obývák topení', 'temperature': 22, 'current_temperature': 21.5, 'area_id': 'living_room'}},
            'climate.bedroom': {'state': 'heat', 'attributes': {'friendly_name': 'Ložnice topení', 'temperature': 20, 'current_temperature': 19.8, 'area_id': 'bedroom'}},
            'sensor.living_room_temperature': {'state': '21.5', 'attributes': {'friendly_name': 'Obývák teplota', 'unit_of_measurement': '°C', 'device_class': 'temperature', 'area_id': 'living_room'}},
            'sensor.bedroom_temperature': {'state': '19.8', 'attributes': {'friendly_name': 'Ložnice teplota', 'unit_of_measurement': '°C', 'device_class': 'temperature', 'area_id': 'bedroom'}},
            'sensor.kitchen_temperature': {'state': '22.3', 'attributes': {'friendly_name': 'Kuchyně teplota', 'unit_of_measurement': '°C', 'device_class': 'temperature', 'area_id': 'kitchen'}},
            'sensor.living_room_humidity': {'state': '45', 'attributes': {'friendly_name': 'Obývák vlhkost', 'unit_of_measurement': '%', 'device_class': 'humidity', 'area_id': 'living_room'}},
            'binary_sensor.front_door': {'state': 'off', 'attributes': {'friendly_name': 'Vchodové dveře', 'device_class': 'door', 'area_id': 'hallway'}},
            'binary_sensor.motion_hallway': {'state': 'off', 'attributes': {'friendly_name': 'Pohyb chodba', 'device_class': 'motion', 'area_id': 'hallway'}},
            'binary_sensor.motion_living_room': {'state': 'on', 'attributes': {'friendly_name': 'Pohyb obývák', 'device_class': 'motion', 'area_id': 'living_room'}},
            'lock.front_door': {'state': 'locked', 'attributes': {'friendly_name': 'Vchodový zámek', 'area_id': 'hallway'}},
            'cover.living_room': {'state': 'open', 'attributes': {'friendly_name': 'Obývák roleta', 'area_id': 'living_room'}},
            'media_player.living_room': {'state': 'idle', 'attributes': {'friendly_name': 'Obývák TV', 'area_id': 'living_room'}},
            'sensor.front_door_battery': {'state': '85', 'attributes': {'friendly_name': 'Zámek baterie', 'unit_of_measurement': '%', 'device_class': 'battery', 'area_id': 'hallway'}},
            'sensor.motion_battery': {'state': '8', 'attributes': {'friendly_name': 'Pohybový senzor baterie', 'unit_of_measurement': '%', 'device_class': 'battery', 'area_id': 'hallway'}},
            'switch.kitchen_kettle': {'state': 'off', 'attributes': {'friendly_name': 'Kuchyně varná konvice', 'area_id': 'kitchen'}},
        }
        self._init_cache()

    def _init_cache(self):
        for eid, dev in self._sim_devices.items():
            self._cache[eid] = {
                'entity_id': eid,
                'state': dev['state'],
                'attributes': dev['attributes'],
                'last_changed': datetime.utcnow().isoformat(),
            }
        self._build_rooms()

    def check_connection(self):
        return {'connected': True, 'message': 'Simulated HA (demo mode)', 'simulated': True}

    def get_all_states(self, use_cache=True):
        return list(self._cache.values())

    def call_service(self, domain, service, entity_id=None, data=None):
        """Simulate service call."""
        if entity_id and entity_id in self._cache:
            if service in ('turn_on',):
                self._cache[entity_id]['state'] = 'on'
                if data and 'brightness_pct' in data:
                    self._cache[entity_id]['attributes']['brightness'] = data['brightness_pct']
            elif service in ('turn_off',):
                self._cache[entity_id]['state'] = 'off'
            elif service == 'lock':
                self._cache[entity_id]['state'] = 'locked'
            elif service == 'unlock':
                self._cache[entity_id]['state'] = 'unlocked'
            elif service == 'open_cover':
                self._cache[entity_id]['state'] = 'open'
            elif service == 'close_cover':
                self._cache[entity_id]['state'] = 'closed'
            elif service == 'set_temperature' and data:
                self._cache[entity_id]['attributes']['temperature'] = data.get('temperature', 22)
            self._cache[entity_id]['last_changed'] = datetime.utcnow().isoformat()
            return [self._cache[entity_id]]
        return None


# ═══════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════
# 📡 MQTT BRIDGE — IoT sensors via Zigbee2MQTT / Mosquitto
# ═══════════════════════════════════════════════════════════════════

MQTT_BROKER = os.environ.get('MQTT_BROKER', '')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
MQTT_USER = os.environ.get('MQTT_USER', '')
MQTT_PASS = os.environ.get('MQTT_PASS', '')

class MQTTBridge:
    """MQTT client for Zigbee2MQTT and other IoT sensors."""

    def __init__(self):
        self.client = None
        self.connected = False
        self.sensor_data = {}  # topic → last payload
        self._handlers = []

    def start(self):
        if not HAS_MQTT or not MQTT_BROKER:
            logger.info("MQTT not configured — skipping")
            return

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        thread = threading.Thread(target=self._connect, daemon=True)
        thread.start()

    def _connect(self):
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_forever()
        except Exception as e:
            logger.warning(f"MQTT connect error: {e}")

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = True
        logger.info(f"✅ MQTT connected to {MQTT_BROKER}")
        # Subscribe to Zigbee2MQTT topics
        client.subscribe("zigbee2mqtt/#")
        # Subscribe to general sensor topics
        client.subscribe("sensors/#")
        client.subscribe("home/#")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}
            self.sensor_data[topic] = {
                'payload': payload,
                'timestamp': datetime.utcnow().isoformat(),
                'topic': topic
            }
            # Notify handlers
            for handler in self._handlers:
                try:
                    handler(topic, payload)
                except Exception as e:
                    logger.warning(f"MQTT handler error: {e}")
        except Exception as e:
            logger.debug(f"MQTT parse error on {msg.topic}: {e}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.connected = False
        logger.warning("MQTT disconnected — will retry")

    def publish(self, topic, payload):
        """Publish command to MQTT (e.g., Zigbee2MQTT set)."""
        if self.client and self.connected:
            self.client.publish(topic, json.dumps(payload))
            return True
        return False

    def on_sensor_update(self, handler):
        """Register handler: handler(topic, payload)."""
        self._handlers.append(handler)

    def get_sensors(self):
        """Get all recent sensor readings."""
        return self.sensor_data

    def zigbee_set(self, device_name, command):
        """Send command to Zigbee2MQTT device.

        Example: zigbee_set('living_room_light', {'state': 'ON', 'brightness': 200})
        """
        return self.publish(f'zigbee2mqtt/{device_name}/set', command)


# ═══════════════════════════════════════════════════════════════════
# 🔌 DIRECT DEVICE CONTROL — TP-Link Kasa + Yeelight (no HA needed)
# ═══════════════════════════════════════════════════════════════════

KASA_DEVICES = [ip.strip() for ip in os.environ.get('KASA_DEVICES', '').split(',') if ip.strip()]
YEELIGHT_DEVICES = [ip.strip() for ip in os.environ.get('YEELIGHT_DEVICES', '').split(',') if ip.strip()]

class DirectDeviceManager:
    """Control smart devices directly without Home Assistant."""

    def __init__(self):
        self._kasa_cache = {}
        self._yeelight_cache = {}

    # ─── TP-Link Kasa ───

    async def _kasa_discover(self):
        """Discover Kasa devices on network."""
        if not HAS_KASA:
            return {}
        try:
            devices = await KasaDiscover.discover()
            self._kasa_cache = devices
            return {ip: {'alias': dev.alias, 'is_on': dev.is_on, 'type': type(dev).__name__}
                    for ip, dev in devices.items()}
        except Exception as e:
            logger.warning(f"Kasa discover error: {e}")
            return {}

    def kasa_discover_sync(self):
        """Synchronous wrapper for Kasa discovery."""
        if not HAS_KASA:
            return {'available': False, 'reason': 'python-kasa not installed'}
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self._kasa_discover())
            loop.close()
            return {'available': True, 'devices': result}
        except Exception as e:
            return {'available': False, 'error': str(e)}

    async def _kasa_control(self, ip, action):
        """Control a Kasa device."""
        if not HAS_KASA:
            return False
        try:
            dev = SmartPlug(ip)
            await dev.update()
            if action == 'on':
                await dev.turn_on()
            elif action == 'off':
                await dev.turn_off()
            elif action == 'toggle':
                if dev.is_on:
                    await dev.turn_off()
                else:
                    await dev.turn_on()
            return True
        except Exception as e:
            logger.warning(f"Kasa control error ({ip}): {e}")
            return False

    def kasa_control_sync(self, ip, action):
        """Synchronous Kasa control."""
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self._kasa_control(ip, action))
            loop.close()
            return result
        except Exception as e:
            return False

    # ─── Yeelight ───

    def yeelight_discover(self):
        """Discover Yeelight bulbs."""
        if not HAS_YEELIGHT:
            return {'available': False, 'reason': 'yeelight not installed'}
        try:
            bulbs = yeelight_discover()
            return {'available': True, 'bulbs': bulbs}
        except Exception as e:
            return {'available': False, 'error': str(e)}

    def yeelight_control(self, ip, action, params=None):
        """Control a Yeelight bulb."""
        if not HAS_YEELIGHT:
            return False
        try:
            bulb = YeelightBulb(ip)
            if action == 'on':
                bulb.turn_on()
            elif action == 'off':
                bulb.turn_off()
            elif action == 'toggle':
                bulb.toggle()
            elif action == 'brightness':
                bulb.set_brightness(params.get('brightness', 50))
            elif action == 'color_temp':
                bulb.set_color_temp(params.get('temp', 4000))
            elif action == 'rgb':
                r, g, b = params.get('r', 255), params.get('g', 255), params.get('b', 255)
                bulb.set_rgb(r, g, b)
            return True
        except Exception as e:
            logger.warning(f"Yeelight control error ({ip}): {e}")
            return False


# ═══════════════════════════════════════════════════════════════════
# 🏗️ ENHANCED HA CLIENT — uses homeassistant_api library when available
# ═══════════════════════════════════════════════════════════════════

class EnhancedHAClient(HomeAssistantClient):
    """Extended HA client that uses homeassistant_api library."""

    def __init__(self, url=None, token=None):
        super().__init__(url, token)
        self.ha_lib_client = None
        self.mqtt_bridge = MQTTBridge()
        self.device_manager = DirectDeviceManager()

        # Initialize homeassistant_api library
        if HAS_HA_LIB and self.available:
            try:
                api_url = f'{self.url}/api'
                self.ha_lib_client = HAAPIClient(api_url, self.token)
                logger.info(f"✅ homeassistant_api connected to {self.url}")
            except Exception as e:
                logger.warning(f"homeassistant_api init error: {e}")

        # Start MQTT if configured
        if MQTT_BROKER:
            self.mqtt_bridge.start()

    def get_all_states(self, use_cache=True):
        """Get states using library if available, fallback to REST."""
        if self.ha_lib_client and HAS_HA_LIB:
            try:
                entities = self.ha_lib_client.get_entities()
                states = []
                for domain_group in entities.values():
                    for entity_id, entity in domain_group.items():
                        state_obj = entity.state
                        states.append({
                            'entity_id': state_obj.entity_id,
                            'state': state_obj.state,
                            'attributes': dict(state_obj.attributes) if state_obj.attributes else {},
                            'last_changed': str(state_obj.last_changed) if state_obj.last_changed else '',
                        })
                self._cache = {s['entity_id']: s for s in states}
                self._cache_time = time.time()
                self._build_rooms()
                return states
            except Exception as e:
                logger.warning(f"HA lib get_entities failed: {e}, falling back to REST")

        return super().get_all_states(use_cache)

    def call_service(self, domain, service, entity_id=None, data=None):
        """Call service using library if available."""
        if self.ha_lib_client and HAS_HA_LIB:
            try:
                svc = self.ha_lib_client.get_domain(domain)
                kwargs = data or {}
                if entity_id:
                    kwargs['entity_id'] = entity_id
                result = getattr(svc, service)(**kwargs)
                return result
            except Exception as e:
                logger.warning(f"HA lib service call failed: {e}, falling back to REST")

        return super().call_service(domain, service, entity_id, data)

    def get_mqtt_sensors(self):
        """Get sensor data from MQTT bridge."""
        return self.mqtt_bridge.get_sensors()

    def zigbee_command(self, device, command):
        """Send Zigbee2MQTT command."""
        return self.mqtt_bridge.zigbee_set(device, command)


# ═══════════════════════════════════════════════════════════════════
# GLOBAL INSTANCE
# ═══════════════════════════════════════════════════════════════════

def get_ha_client():
    """Get the appropriate HA client (real, enhanced, or simulated)."""
    if HA_URL and HA_TOKEN:
        if HAS_HA_LIB:
            return EnhancedHAClient()
        return HomeAssistantClient()
    return SimulatedHomeAssistant()

# Singleton
_ha_client = None

def ha():
    """Get singleton HA client."""
    global _ha_client
    if _ha_client is None:
        _ha_client = get_ha_client()
    return _ha_client

# Direct device manager singleton
_device_manager = None

def devices():
    """Get direct device manager."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DirectDeviceManager()
    return _device_manager


# ═══════════════════════════════════════════════════════════════════
# FLASK BLUEPRINT — API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

ha_bp = Blueprint('home_assistant', __name__)


# ═══════════════════════════════════════════════════════════════════
# 🔒 SECURITY — auth, action whitelist, rate limiter (Sprint A)
# ═══════════════════════════════════════════════════════════════════
# CRITICAL: before this module went through Sprint A, none of the
# /api/ha/* endpoints required auth. That meant anyone on the internet
# could POST /api/ha/action {"action":"unlock","entity_id":"lock.front_door"}
# and unlock a senior's front door. Below is the fix.

from auth_middleware import require_auth as _require_auth

# Actions allowed without an extra confirm=true flag
_SAFE_ACTIONS = frozenset({
    'light_on', 'light_off', 'light_toggle',
    'switch_on', 'switch_off', 'switch_toggle',
    'climate_set', 'climate_temperature',
    'media_play', 'media_pause', 'media_stop', 'media_volume',
    'fan_on', 'fan_off',
    'cover_close',       # closing is safe; opening may expose the home
    'lock',              # locking is always safe
    'scene_activate',
    'refresh', 'noop',
})

# Actions that MUST include confirm=true in the POST body
_CONFIRM_REQUIRED_ACTIONS = frozenset({
    'unlock',                         # opening the front door
    'cover_open',                     # external gates, shutters on ground floor
    'alarm_disarm',
    'garage_open',
})

# Actions fully blocked from the senior frontend (e.g. direct device
# control bypasses the whitelist — must go through the HA state
# machine where HA itself enforces per-device policy).
_BLOCKED_ACTIONS = frozenset({
    'ha.service_call_raw',            # arbitrary HA service invocation
    'raw_shell',                      # must never be exposed
})


def _is_action_allowed(action):
    """Returns (ok, needs_confirm, reason). Pure function — easy to test."""
    if not action or not isinstance(action, str):
        return False, False, 'empty action'
    a = action.strip().lower()
    if a in _BLOCKED_ACTIONS:
        return False, False, 'action blocked by policy'
    if a in _SAFE_ACTIONS:
        return True, False, ''
    if a in _CONFIRM_REQUIRED_ACTIONS:
        return True, True, ''
    # Unknown action — default to deny. Better safe than sorry for seniors.
    return False, False, 'unknown action'


# ── Rate limiter: per-user sliding window ────────────────────────
# Home automation commands are destructive (unlock doors!). We cap
# at 1 action every 2 seconds per senior to prevent spam/abuse.
_RATE_WINDOW_SECONDS = 2.0
_RATE_LAST_ACTION = {}  # uid -> last epoch seconds
_RATE_LOCK = threading.Lock()


def _rate_limit_check(uid):
    """Returns True if within rate limit, False if too fast."""
    if not uid:
        return True
    now = time.time()
    with _RATE_LOCK:
        last = _RATE_LAST_ACTION.get(uid, 0.0)
        if now - last < _RATE_WINDOW_SECONDS:
            return False
        _RATE_LAST_ACTION[uid] = now
        # Trim the dict if it grows too big (cheap GC)
        if len(_RATE_LAST_ACTION) > 1000:
            cutoff = now - 300
            stale = [k for k, v in _RATE_LAST_ACTION.items() if v < cutoff]
            for k in stale:
                _RATE_LAST_ACTION.pop(k, None)
    return True


def _current_uid():
    """Extract authenticated user id from Flask g (set by require_auth)."""
    from flask import g as _g
    au = getattr(_g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


def ha_for(user_id, home_id=None):
    """Return the appropriate HA client for a given user.

    Resolution order:
      1. Per-user / per-home from user_ha_homes (DB lookup, decrypts token)
      2. Global env-var-based singleton (admin / dev fallback)
      3. SimulatedHomeAssistant (demo)

    Returns the client; never None — callers can always operate on it.
    Use this from agents, intent handlers, background jobs, anywhere a
    user_id is in scope. If user_id is empty / None, returns the global
    singleton (env-var-based).
    """
    if user_id:
        try:
            from ha_user_config import ha_for_user
            client = ha_for_user(str(user_id), home_id)
            if client is not None:
                return client
        except Exception as e:
            logger.warning(f"ha_for({str(user_id)[:8]}, {home_id}) failed: {e}")
    return ha()


def _client_for_request(uid):
    """Convenience for Flask handlers — honors ?home=<home_id> query param."""
    home_id = (request.args.get('home') or '').strip() or None
    return ha_for(uid, home_id)


# ═══════════════════════════════════════════════════════════════════
# Per-request HA-read cache (Sprint X6 Phase 1B)
# ═══════════════════════════════════════════════════════════════════
# /api/ha/rooms, /api/ha/sensors, /api/ha/status are polled ~10×/min
# by the SmartHome module per active user. Each call goes through the
# tunnel to the user's local HA, which adds ~150-450ms (transatlantic
# RTT × 2 plus HA REST roundtrip). Cache the assembled response in
# Redis with a short TTL (3s) — enough to absorb burst polls but
# short enough that a state change shows in the UI within ~3s.
#
# Cache is invalidated immediately after /api/ha/action so a toggle
# from the UI reflects in the next room/sensor refresh without lag.

_HA_CACHE_TTL = 3  # seconds — short enough that toggles feel instant


def _ha_cache_key(prefix, uid, home_qs=''):
    return f"ha:{prefix}:{uid}:{home_qs}"


def _ha_cache_get(prefix, uid, home_qs=''):
    """Return cached JSON for (prefix, uid, home) or None on miss."""
    if not uid:
        return None
    try:
        from redis_cache import cache_get_json
        return cache_get_json(_ha_cache_key(prefix, uid, home_qs))
    except Exception:
        return None


def _ha_cache_set(prefix, uid, payload, home_qs=''):
    if not uid:
        return
    try:
        from redis_cache import cache_set_json
        cache_set_json(_ha_cache_key(prefix, uid, home_qs), payload, ttl=_HA_CACHE_TTL)
    except Exception:
        pass


def _ha_cache_invalidate(uid, home_qs=''):
    """Drop all cached HA reads for this (uid, home). Called after every
    successful /api/ha/action so the next read sees fresh state."""
    if not uid:
        return
    try:
        from redis_cache import cache_delete
        for prefix in ('rooms', 'sensors', 'status'):
            cache_delete(_ha_cache_key(prefix, uid, home_qs))
    except Exception:
        pass


@ha_bp.route('/api/ha/status', methods=['GET'])
@_require_auth
def ha_status():
    """Check HA connection and get home status.

    Per-user: resolves to the authenticated user's default home (or
    ?home=<home_id>). Falls back to env-var global if user has no config.
    Cached 3s per (uid, home).
    """
    uid = _current_uid()
    home_qs = (request.args.get('home') or '').strip()
    cached = _ha_cache_get('status', uid, home_qs)
    if cached is not None:
        return jsonify(cached)

    client = _client_for_request(uid)
    conn = client.check_connection()
    # Diagnostic: tag which home answered
    if hasattr(client, '_home_id'):
        conn['home_id'] = client._home_id
        # Persist last_connected / last_error
        try:
            from ha_user_config import record_connection_status
            record_connection_status(client._home_id, conn.get('connected', False),
                                     None if conn.get('connected') else conn.get('reason'))
        except Exception:
            pass
    if conn.get('connected'):
        status = client._get_home_status()
        payload = {**conn, **status}
    else:
        payload = conn
    _ha_cache_set('status', uid, payload, home_qs)
    return jsonify(payload)

@ha_bp.route('/api/ha/devices', methods=['GET'])
@_require_auth
def ha_devices():
    """Get all devices, optionally grouped by room or type."""
    uid = _current_uid()
    client = _client_for_request(uid)
    group_by = request.args.get('group', 'room')  # room or type
    if group_by == 'room':
        return jsonify({'success': True, 'rooms': client.get_devices_by_room()})
    else:
        return jsonify({'success': True, 'devices': client.get_devices_by_type()})

@ha_bp.route('/api/ha/device/<entity_id>', methods=['GET'])
@_require_auth
def ha_device_state(entity_id):
    """Get single device state."""
    uid = _current_uid()
    client = _client_for_request(uid)
    state = client.get_state(entity_id)
    if state:
        return jsonify({'success': True, 'state': state})
    return jsonify({'success': False, 'error': 'Device not found'}), 404


@ha_bp.route('/api/ha/device/<entity_id>/detail', methods=['GET'])
@_require_auth
def ha_device_detail(entity_id):
    """v397.5 (Sprint X2): enriched device detail.

    Returns:
        {
          state: <full HA state>,
          related: [<sensors that share entity_id prefix>],
          assignment: <device_assignments row if user assigned this entity>,
          history: [<last 20 logbook entries from HA>]
        }

    Used by Domácnost device detail page — shows toggle + sensors +
    activity log for a single device (e.g. Tapo P115 with its 5 sensor
    siblings).
    """
    import re
    uid = _current_uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    client = _client_for_request(uid)

    state = client.get_state(entity_id)
    if not state:
        return jsonify({'success': False, 'error': 'Device not found'}), 404

    # ─── Related entities (share entity_id prefix) ───
    # Tapo P115: switch.tapo_p115 + sensor.tapo_p115_signal + sensor.tapo_p115_current_power
    # Match: strip domain + numeric/long suffix, find common stem
    stem_match = re.match(r'^[^.]+\.([a-z0-9_]+?)(_signal|_current_power|_today_energy|_month_energy|_today_runtime|_month_runtime|_battery|_temperature|_humidity)?$', entity_id.lower())
    stem = stem_match.group(1) if stem_match else entity_id.split('.', 1)[1].lower()

    related = []
    all_states = client.get_all_states(use_cache=True) or []
    for s in all_states:
        eid = s['entity_id']
        if eid == entity_id:
            continue
        # Match by stem prefix
        eid_local = eid.split('.', 1)[1].lower() if '.' in eid else eid.lower()
        if eid_local.startswith(stem):
            related.append({
                'entity_id': eid,
                'name': s.get('attributes', {}).get('friendly_name', eid),
                'state': s.get('state'),
                'unit': s.get('attributes', {}).get('unit_of_measurement', ''),
                'device_class': s.get('attributes', {}).get('device_class', ''),
                'icon': s.get('attributes', {}).get('icon', ''),
            })

    # ─── User's assignment (if any) ───
    assignment = None
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT assignment_id, room, role, custom_label, manufacturer, model "
                "FROM device_assignments WHERE user_id = ? AND entity_id = ?",
                (uid, entity_id)
            ).fetchone()
        if row:
            if hasattr(row, 'keys'):
                assignment = dict(row)
            else:
                assignment = {
                    'assignment_id': row[0], 'room': row[1], 'role': row[2],
                    'custom_label': row[3], 'manufacturer': row[4], 'model': row[5],
                }
    except Exception as e:
        logger.debug(f'detail: assignment lookup: {e}')

    # ─── Recent history from HA logbook ───
    history = _fetch_logbook(client, entity_id, hours=24, limit=20)

    return jsonify({
        'success': True,
        'state': state,
        'related': related,
        'assignment': assignment,
        'history': history,
        'home_id': getattr(client, '_home_id', None),
    })


@ha_bp.route('/api/ha/device/<entity_id>/history', methods=['GET'])
@_require_auth
def ha_device_history(entity_id):
    """v397.5: HA logbook proxy — last N entries for the entity.

    Query params:
        hours: lookback window (default 24)
        limit: max entries (default 50)
    """
    uid = _current_uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    client = _client_for_request(uid)

    try:
        hours = int(request.args.get('hours', 24))
        limit = int(request.args.get('limit', 50))
    except ValueError:
        return jsonify({'success': False, 'error': 'invalid_params'}), 400
    hours = max(1, min(168, hours))  # clamp 1h–7d
    limit = max(1, min(200, limit))

    history = _fetch_logbook(client, entity_id, hours=hours, limit=limit)
    return jsonify({'success': True, 'history': history, 'count': len(history)})


def _fetch_logbook(client, entity_id, hours=24, limit=50):
    """Fetch recent state changes from HA logbook for one entity."""
    import requests
    from datetime import datetime, timedelta, timezone
    if not client or not getattr(client, 'url', None) or not getattr(client, 'token', None):
        return []
    # Note: don't gate on client.connected — that flag is only set by
    # check_connection(). Just try the fetch; network errors are caught below.
    try:
        start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        url = f'{client.url}/api/logbook/{start}'
        resp = requests.get(
            url,
            headers={'Authorization': f'Bearer {client.token}'},
            params={'entity': entity_id},
            timeout=10,
        )
        if resp.status_code != 200:
            logger.debug(f'logbook {entity_id}: HTTP {resp.status_code} {resp.text[:120]}')
            return []
        items = resp.json() or []
        # Normalize for frontend — keep most useful fields
        out = []
        for item in items[:limit]:
            out.append({
                'when': item.get('when', ''),
                'name': item.get('name', ''),
                'state': item.get('state', ''),
                'message': item.get('message', ''),
                'icon': item.get('icon', ''),
                'context_user_id': item.get('context_user_id'),
            })
        return out
    except Exception as e:
        logger.debug(f'logbook fetch error: {e}')
        return []

@ha_bp.route('/api/ha/action', methods=['POST'])
@_require_auth
def ha_action():
    """Execute a device action.

    Body: {"action": "light_on", "entity_id": "light.living_room",
           "params": {"brightness": 80}, "confirm": true/false}
    Or:   {"action": "light_on", "room": "living_room"} — auto-find entity

    Security (Sprint A):
    - auth required (see @_require_auth)
    - action whitelist enforced via _is_action_allowed()
    - dangerous actions (unlock, alarm_disarm, cover_open) require
      confirm=true in body — prevents accidental clicks
    - rate-limited to 1 action per 2 seconds per user
    """
    uid = _current_uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    action = (data.get('action') or '').strip()

    # 1. Whitelist check
    ok, needs_confirm, reason = _is_action_allowed(action)
    if not ok:
        logger.warning(f"HA action blocked: user={uid[:8]} action={action!r} reason={reason}")
        return jsonify({
            'success': False,
            'error': 'action_not_allowed',
            'action': action,
            'reason': reason,
        }), 400

    # 2. Confirm check for dangerous actions
    if needs_confirm and not data.get('confirm'):
        logger.info(f"HA action needs confirm: user={uid[:8]} action={action}")
        return jsonify({
            'success': False,
            'error': 'confirmation_required',
            'action': action,
            'message': 'Tato akce vyžaduje výslovné potvrzení. Odešlete confirm=true.',
        }), 428  # 428 Precondition Required

    # 3. Rate limit
    if not _rate_limit_check(uid):
        logger.info(f"HA action rate-limited: user={uid[:8]} action={action}")
        return jsonify({
            'success': False,
            'error': 'rate_limited',
            'retry_after_seconds': _RATE_WINDOW_SECONDS,
        }), 429

    # 4. Build params + execute
    params = data.get('params', {}) or {}
    if data.get('entity_id'):
        params['entity_id'] = data['entity_id']
    if data.get('room'):
        params['room'] = data['room']
        if 'light' in action:
            params['device_type'] = 'light'
        elif 'climate' in action or 'temperature' in action:
            params['device_type'] = 'climate'
        elif 'lock' in action or 'unlock' in action:
            params['device_type'] = 'lock'
        elif 'cover' in action:
            params['device_type'] = 'cover'
        elif 'switch' in action:
            params['device_type'] = 'switch'

    # Audit trail — any command touching the physical home goes in the log
    client = _client_for_request(uid)
    home_tag = getattr(client, '_home_id', 'global')
    logger.info(
        f"HA action: user={uid[:8]} home={home_tag} action={action} "
        f"entity={params.get('entity_id', '?')} room={params.get('room', '?')}"
    )

    try:
        result = client.execute_agent_action(action, params)
    except Exception as e:
        logger.error(f"HA action execution error: {e}")
        return jsonify({'success': False, 'error': str(e)[:120]}), 500

    # Invalidate cached HA reads so the next /api/ha/status,sensors,rooms
    # request returns the post-action state immediately, not the 3s-stale one.
    _ha_cache_invalidate(uid, (request.args.get('home') or '').strip())

    return jsonify(result)

@ha_bp.route('/api/ha/sensors', methods=['GET'])
@_require_auth
def ha_sensors():
    """Get sensor summary (temperature, humidity, motion, etc.).
    Cached 3s per (uid, home)."""
    uid = _current_uid()
    home_qs = (request.args.get('home') or '').strip()
    cached = _ha_cache_get('sensors', uid, home_qs)
    if cached is not None:
        return jsonify(cached)

    client = _client_for_request(uid)
    sensors = client.get_sensors_summary()
    payload = {'success': True, 'sensors': sensors}
    _ha_cache_set('sensors', uid, payload, home_qs)
    return jsonify(payload)

@ha_bp.route('/api/ha/rooms', methods=['GET'])
@_require_auth
def ha_rooms():
    """Get room list with device counts + system entities.

    Sprint X9 / B: response now includes a `system` array with the
    HA-internal diagnostic entities filtered out of the main rooms.
    Frontend renders them in a collapsed "Systémové" section so
    admins can still see backup/update/supervisor state.

    Cached 3s per (uid, home)."""
    uid = _current_uid()
    home_qs = (request.args.get('home') or '').strip()
    cached = _ha_cache_get('rooms', uid, home_qs)
    if cached is not None:
        return jsonify(cached)

    client = _client_for_request(uid)
    rooms = client.get_devices_by_room()
    summary = {}
    for room_id, room_data in rooms.items():
        summary[room_id] = {
            'name': room_data['name'],
            'device_count': len(room_data['devices']),
            'devices': room_data['devices']
        }
    system = []
    try:
        system = client.get_system_entities()
    except Exception as e:
        logger.debug(f'get_system_entities failed: {e}')
    payload = {'success': True, 'rooms': summary, 'system': system}
    _ha_cache_set('rooms', uid, payload, home_qs)
    return jsonify(payload)

@ha_bp.route('/api/ha/webhook/<home_id>', methods=['POST'])
def ha_webhook_per_home(home_id):
    """Receive events from HA automations for a specific user's home.

    Auth: X-HA-Secret header must match the home's ha_webhook_secret
    (per-home, generated server-side). Constant-time compare. Fail-closed.

    HA-side configuration.yaml example:
        rest_command:
          radim_webhook:
            url: "https://app.radimcare.cz/api/ha/webhook/<home_id>"
            method: POST
            headers:
              X-HA-Secret: "!secret radim_webhook_secret"
            payload: '{"event_type":"motion_detected","entity_id":"...","new_state":"on"}'
    """
    import hmac
    try:
        from ha_user_config import get_home_by_id
        home = get_home_by_id(home_id)
    except Exception as e:
        logger.warning(f"webhook lookup failed: {e}")
        return jsonify({'error': 'webhook_disabled'}), 503

    if not home:
        return jsonify({'error': 'unknown_home'}), 404
    expected = home.get('ha_webhook_secret') or ''
    if not expected:
        return jsonify({'error': 'webhook_disabled'}), 503
    secret = request.headers.get('X-HA-Secret', '')
    if not hmac.compare_digest(secret, expected):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    event_type = data.get('event_type', 'unknown')
    entity_id = data.get('entity_id', '')
    new_state = data.get('new_state', '')

    user_id = home['user_id']
    logger.info(
        f'HA webhook: user={user_id[:8]} home={home_id[:8]} '
        f'{event_type} {entity_id} → {new_state}'
    )

    # Update the per-user client's cache so subsequent reads see fresh state
    try:
        from ha_user_config import ha_for_user
        client = ha_for_user(user_id, home_id)
        if client and entity_id:
            client._cache.setdefault(entity_id, {'entity_id': entity_id})['state'] = new_state
    except Exception:
        pass

    return jsonify({'success': True, 'processed': event_type, 'home_id': home_id})


# Legacy global webhook — kept for backwards compat with HA_WEBHOOK_SECRET
# env var (admin / dev). Prefer the per-home variant above.
@ha_bp.route('/api/ha/webhook', methods=['POST'])
def ha_webhook():
    """Legacy global webhook (env-var-based secret).

    Use /api/ha/webhook/<home_id> for per-user homes. This stays for
    admin / single-tenant dev setups that rely on HA_WEBHOOK_SECRET env.
    """
    if not HA_WEBHOOK_SECRET:
        return jsonify({
            'error': 'webhook_disabled',
            'detail': 'HA_WEBHOOK_SECRET not configured on the server',
        }), 503
    secret = request.headers.get('X-HA-Secret', '')
    import hmac
    if not hmac.compare_digest(secret, HA_WEBHOOK_SECRET):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    event_type = data.get('event_type', 'unknown')
    entity_id = data.get('entity_id', '')
    new_state = data.get('new_state', '')

    logger.info(f'HA webhook (global): {event_type} {entity_id} → {new_state}')
    if entity_id:
        ha()._cache.setdefault(entity_id, {'entity_id': entity_id})['state'] = new_state
    return jsonify({'success': True, 'processed': event_type})


# ─── MQTT ENDPOINTS ───

@ha_bp.route('/api/ha/mqtt/sensors', methods=['GET'])
@_require_auth
def ha_mqtt_sensors():
    """Get MQTT sensor data."""
    client = ha()
    if hasattr(client, 'mqtt_bridge'):
        data = client.mqtt_bridge.get_sensors()
        return jsonify({
            'success': True,
            'connected': client.mqtt_bridge.connected,
            'sensors': data,
            'count': len(data)
        })
    return jsonify({'success': True, 'connected': False, 'sensors': {}, 'count': 0})


@ha_bp.route('/api/ha/mqtt/publish', methods=['POST'])
@_require_auth
def ha_mqtt_publish():
    """Publish MQTT message (e.g., Zigbee2MQTT command)."""
    data = request.get_json(silent=True) or {}
    topic = data.get('topic', '')
    payload = data.get('payload', {})
    if not topic:
        return jsonify({'success': False, 'error': 'topic required'}), 400

    client = ha()
    if hasattr(client, 'mqtt_bridge') and client.mqtt_bridge.connected:
        result = client.mqtt_bridge.publish(topic, payload)
        return jsonify({'success': result, 'topic': topic})
    return jsonify({'success': False, 'error': 'MQTT not connected'})


# ─── DIRECT DEVICE ENDPOINTS ───

@ha_bp.route('/api/ha/direct/discover', methods=['GET'])
@_require_auth
def ha_direct_discover():
    """Discover direct devices (Kasa, Yeelight)."""
    dm = devices()
    result = {
        'kasa': dm.kasa_discover_sync() if HAS_KASA else {'available': False},
        'yeelight': dm.yeelight_discover() if HAS_YEELIGHT else {'available': False},
        'libraries': {
            'homeassistant_api': HAS_HA_LIB,
            'paho_mqtt': HAS_MQTT,
            'python_kasa': HAS_KASA,
            'yeelight': HAS_YEELIGHT,
        }
    }
    return jsonify({'success': True, **result})


@ha_bp.route('/api/ha/direct/kasa', methods=['POST'])
@_require_auth
def ha_direct_kasa():
    """Control Kasa device directly.

    Admin-only: direct LAN control bypasses the HA state machine that
    normally enforces per-device policy. Gate behind an admin role.
    """
    uid = _current_uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    from flask import g
    au = getattr(g, 'auth_user', None) or {}
    if not (au.get('is_admin') or au.get('role') == 'admin'):
        return jsonify({
            'success': False,
            'error': 'direct device control is admin-only; use /api/ha/action instead',
        }), 403
    if not _rate_limit_check(uid):
        return jsonify({'success': False, 'error': 'rate_limited'}), 429

    data = request.get_json(silent=True) or {}
    ip = data.get('ip', '')
    action = data.get('action', 'toggle')
    if not ip:
        return jsonify({'success': False, 'error': 'ip required'}), 400
    dm = devices()
    result = dm.kasa_control_sync(ip, action)
    return jsonify({'success': result, 'ip': ip, 'action': action})


@ha_bp.route('/api/ha/direct/yeelight', methods=['POST'])
@_require_auth
def ha_direct_yeelight():
    """Control Yeelight bulb directly. Admin-only (see Kasa note)."""
    uid = _current_uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    from flask import g
    au = getattr(g, 'auth_user', None) or {}
    if not (au.get('is_admin') or au.get('role') == 'admin'):
        return jsonify({
            'success': False,
            'error': 'direct device control is admin-only; use /api/ha/action instead',
        }), 403
    if not _rate_limit_check(uid):
        return jsonify({'success': False, 'error': 'rate_limited'}), 429

    data = request.get_json(silent=True) or {}
    ip = data.get('ip', '')
    action = data.get('action', 'toggle')
    params = data.get('params', {})
    if not ip:
        return jsonify({'success': False, 'error': 'ip required'}), 400
    dm = devices()
    result = dm.yeelight_control(ip, action, params)
    return jsonify({'success': result, 'ip': ip, 'action': action})


@ha_bp.route('/api/ha/libraries', methods=['GET'])
@_require_auth
def ha_libraries():
    """Show available smart home libraries and their status."""
    return jsonify({
        'success': True,
        'libraries': {
            'homeassistant_api': {'installed': HAS_HA_LIB, 'version': '5.0.3' if HAS_HA_LIB else None, 'purpose': 'Official HA REST/WS Python client'},
            'paho_mqtt': {'installed': HAS_MQTT, 'purpose': 'MQTT for Zigbee2MQTT, IoT sensors'},
            'python_kasa': {'installed': HAS_KASA, 'purpose': 'TP-Link Kasa smart plugs/lights (direct)'},
            'yeelight': {'installed': HAS_YEELIGHT, 'purpose': 'Xiaomi Yeelight bulbs (direct)'},
        },
        'config': {
            'ha_url': bool(HA_URL),
            'ha_token': bool(HA_TOKEN),
            'mqtt_broker': bool(MQTT_BROKER),
            'kasa_devices': len(KASA_DEVICES),
            'yeelight_devices': len(YEELIGHT_DEVICES),
        }
    })
