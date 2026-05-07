"""
🔗 HOME ASSISTANT PAIRING + ASSIGNMENTS (v397)
=============================================================================
Endpoints for the senior-friendly "Add device" wizard in Domácnost.

Wizard flow:
  1. Frontend GET /api/ha/devices/catalog
       → returns the 9 device types from device_catalog.py with metadata
  2. User picks one (e.g. 'motion'), picks a room
  3. Frontend POST /api/ha/pair/start { device_type, room, label }
       → backend kicks off pairing (Zigbee permit_join / HA flow / OAuth)
       → returns pair_id + ETA
  4. Frontend polls GET /api/ha/pair/status?pair_id=...
       → returns 'waiting' / 'paired' / 'timeout' / 'error'
       → on 'paired': returns entity_id + suggested label
  5. Frontend confirms POST /api/ha/assignments {entity_id, room, role, ...}
       → permanent record in device_assignments

Current implementation note:
  - Zigbee permit_join is published via the per-user MQTT bridge
    (already wired in home_assistant.py MQTTBridge)
  - Device discovery during pairing window uses MQTT topic sniffing on
    zigbee2mqtt/<device>/availability or zigbee2mqtt/bridge/event
  - For HA-flow devices (speakers), we proxy POST to HA's
    /api/config/config_entries/flow with the configured token
  - Manual / OAuth devices return immediately with instructions for the
    user to complete the dance (Withings OAuth not yet wired — placeholder)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, g, jsonify, request

from auth_middleware import require_auth

logger = logging.getLogger(__name__)

ha_pairing_bp = Blueprint('ha_pairing', __name__)


# ════════════════════════════════════════════════════════════════════
# IN-MEMORY PAIRING SESSIONS
# ════════════════════════════════════════════════════════════════════
# Pairing is a short-lived (max 3min) operation; store in-memory + lock.
# If the dyno restarts mid-pair, frontend simply reports timeout and the
# user retries — no DB persistence needed.

_PAIR_SESSIONS: dict[str, dict] = {}
_PAIR_LOCK = threading.Lock()
_PAIR_MAX_AGE_SECONDS = 300  # 5 min — anything older gets GC'd


def _gc_pair_sessions():
    cutoff = time.time() - _PAIR_MAX_AGE_SECONDS
    with _PAIR_LOCK:
        stale = [pid for pid, sess in _PAIR_SESSIONS.items() if sess['created_at'] < cutoff]
        for pid in stale:
            _PAIR_SESSIONS.pop(pid, None)


def _uid() -> str:
    au = getattr(g, 'auth_user', None) or {}
    return str(au.get('id') or au.get('user_id') or '')


# ════════════════════════════════════════════════════════════════════
# 1. CATALOG — what devices can the wizard add?
# ════════════════════════════════════════════════════════════════════

@ha_pairing_bp.route('/api/ha/devices/catalog', methods=['GET'])
@require_auth
def devices_catalog():
    """Return the 9 supported device types for the wizard tiles."""
    from device_catalog import list_for_wizard
    return jsonify({'success': True, 'devices': list_for_wizard()})


# ════════════════════════════════════════════════════════════════════
# 1b. NETWORK INFO — preflight pro Tapo párování
# ════════════════════════════════════════════════════════════════════

@ha_pairing_bp.route('/api/ha/network/info', methods=['GET'])
@require_auth
def network_info():
    """Returns HA's network coordinates so the user can check that the
    Tapo device they're about to pair is on the SAME Wi-Fi / subnet.

    Response shape:
        {
          ha_url: "http://192.168.1.10:8123",
          ha_host: "192.168.1.10",
          ha_port: 8123,
          ha_reachable: true,
          ha_latency_ms: 24,
          subnet_hint: "192.168.1.0/24",     # for "ensure device is on this network"
          subnet_human: "192.168.1.x",        # friendly form
          is_private: true,
          warnings: ["DHCP reservation recommended"]
        }
    """
    import re
    import socket
    import time
    from urllib.parse import urlparse

    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    # Resolve user's HA URL (per-user config takes priority over global env)
    ha_url = ''
    ha_host = ''
    ha_port = 0
    try:
        from ha_user_config import get_home
        home = get_home(uid)
        if home and home.get('ha_url'):
            ha_url = home['ha_url']
        else:
            import os
            ha_url = os.environ.get('HA_URL', '')
    except Exception as e:
        logger.debug(f'network_info: resolve HA url: {e}')

    if not ha_url:
        return jsonify({
            'success': False,
            'error': 'no_ha_configured',
            'message': 'Žádná Home Assistant instance není nakonfigurovaná. '
                       'Přidej ji v Nastavení → Home Assistant.',
        }), 412

    parsed = urlparse(ha_url)
    ha_host = parsed.hostname or ''
    ha_port = parsed.port or (443 if parsed.scheme == 'https' else 80)

    # Resolve hostname → IP if needed
    ha_ip = ha_host
    try:
        ha_ip = socket.gethostbyname(ha_host) if ha_host else ''
    except (socket.gaierror, socket.error):
        ha_ip = ha_host  # fallback: maybe was an IP already

    # Reachability + latency probe
    ha_reachable = False
    ha_latency_ms = None
    try:
        t0 = time.perf_counter()
        from home_assistant import ha_for
        client = ha_for(uid)
        if client:
            res = client.check_connection()
            ha_reachable = bool(res.get('connected'))
            ha_latency_ms = int((time.perf_counter() - t0) * 1000)
    except Exception as e:
        logger.debug(f'network_info: reachability: {e}')

    # Build subnet hint from IP (assume /24 — true for 99% home networks)
    subnet_hint = ''
    subnet_human = ''
    is_private = False
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', ha_ip):
        parts = ha_ip.split('.')
        subnet_hint = f'{parts[0]}.{parts[1]}.{parts[2]}.0/24'
        subnet_human = f'{parts[0]}.{parts[1]}.{parts[2]}.x'
        # RFC1918 private ranges
        first_octet = int(parts[0])
        second_octet = int(parts[1])
        is_private = (
            first_octet == 10 or
            (first_octet == 172 and 16 <= second_octet <= 31) or
            (first_octet == 192 and second_octet == 168)
        )

    warnings = []
    if not ha_reachable:
        warnings.append('HA momentálně neodpovídá — zkontroluj, že běží.')
    if not is_private and ha_ip:
        warnings.append(
            'HA běží na veřejné IP — Tapo zařízení nepřes mDNS najdete. '
            'Použij Cloudflare Tunnel nebo VPN.'
        )
    if ha_ip == 'localhost' or ha_ip.startswith('127.'):
        warnings.append(
            'HA URL ukazuje na localhost — z mobilu / tabletu seniora '
            'tohle nepojde. Použij IP routeru (např. 192.168.1.x).'
        )

    return jsonify({
        'success': True,
        'ha_url': ha_url,
        'ha_host': ha_host,
        'ha_ip': ha_ip,
        'ha_port': ha_port,
        'ha_reachable': ha_reachable,
        'ha_latency_ms': ha_latency_ms,
        'subnet_hint': subnet_hint,
        'subnet_human': subnet_human,
        'is_private': is_private,
        'mdns_port': 5353,         # UDP multicast for tplink discovery
        'tapo_local_port': 9999,   # legacy Tapo local API
        'tapo_klap_port': 80,      # newer KLAP protocol port
        'warnings': warnings,
        'requirements': [
            'Tapo zařízení musí být ve stejné Wi-Fi síti jako HA.',
            'Stejný subnet (např. ' + (subnet_human or '192.168.1.x') + ') — '
            'mDNS broadcasty neprojdou přes router.',
            'Doporučujeme DHCP rezervaci IP na routeru, '
            'aby se Tapo IP neměnila.',
        ],
    })


# ════════════════════════════════════════════════════════════════════
# 2. PAIR — start / status / cancel
# ════════════════════════════════════════════════════════════════════

@ha_pairing_bp.route('/api/ha/pair/start', methods=['POST'])
@require_auth
def pair_start():
    """Kick off a pairing session.

    Body: {
        "device_type": "motion",
        "room": "bedroom",
        "label": "Senzor pohybu — ložnice",
        "extra_fields": {...}     # required_fields filled by user (e.g. mqtt_host)
    }
    Returns: {pair_id, expires_at, instructions, method}
    """
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    device_type = (data.get('device_type') or '').strip()
    room = (data.get('room') or '').strip() or 'unassigned'
    label = (data.get('label') or '').strip()
    extra_fields = data.get('extra_fields') or {}

    from device_catalog import (
        get_device, PAIR_ZIGBEE_PERMIT_JOIN, PAIR_HA_CONFIG_FLOW,
        PAIR_WITHINGS_OAUTH, PAIR_MANUAL, PAIR_TPLINK_DISCOVERY,
        PAIR_TAPO_HUB_SUBDEVICE, PAIR_BLUETOOTH_HOST, PAIR_BLUETOOTH_HA,
    )
    catalog_entry = get_device(device_type)
    if not catalog_entry:
        return jsonify({'success': False, 'error': 'unknown_device_type',
                        'requested': device_type}), 400

    # Enforce Hub-first ordering for Tapo sub-devices (T100/T110 etc.)
    requires = catalog_entry.get('requires_device')
    if requires:
        # Check that the prerequisite device has been assigned before
        from database import db_context
        with db_context() as db:
            row = db.execute(
                "SELECT 1 FROM device_assignments "
                "WHERE user_id = ? AND device_type = ? LIMIT 1",
                (uid, requires)
            ).fetchone()
        if not row:
            req_entry = get_device(requires)
            req_label = req_entry['label'] if req_entry else requires
            return jsonify({
                'success': False,
                'error': 'prerequisite_missing',
                'requires_device_type': requires,
                'message': f'Než přidáte {catalog_entry["label"]}, musíte nejdřív přidat {req_label}.',
            }), 412  # 412 Precondition Failed

    method = catalog_entry['pairing']['method']
    duration = int(catalog_entry['pairing']['duration_seconds'])
    pair_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(seconds=max(duration, 5))

    session = {
        'pair_id': pair_id,
        'user_id': uid,
        'device_type': device_type,
        'room': room,
        'label': label or catalog_entry['label'],
        'extra_fields': extra_fields,
        'method': method,
        'created_at': time.time(),
        'expires_at': expires_at.isoformat() + 'Z',
        'status': 'waiting',
        'instructions': catalog_entry['pairing']['instructions'],
        'visual_hint': catalog_entry['pairing'].get('visual_hint', ''),
        'discovered_entity_id': None,
        'error': None,
    }

    # Method-specific kickoff
    try:
        if method in (PAIR_TPLINK_DISCOVERY, PAIR_TAPO_HUB_SUBDEVICE,
                      PAIR_HA_CONFIG_FLOW):
            # All three converge to the same HA-side discovery loop:
            # snapshot existing entities, watch for new ones in target domain.
            _start_ha_flow_pair(uid, session, catalog_entry)
        elif method == PAIR_BLUETOOTH_HA:
            # HA's bluetooth integration BLE scan — watches for any new
            # entity that has bluetooth-related attributes (mac, address).
            _start_bluetooth_ha_scan(uid, session, catalog_entry)
        elif method == PAIR_BLUETOOTH_HOST:
            # BT speaker — user pairs to phone/NUC OS, then manually
            # confirms in the wizard. We just hold the session open.
            _start_bluetooth_host_pair(uid, session, catalog_entry)
        elif method == PAIR_ZIGBEE_PERMIT_JOIN:
            _start_zigbee_pair(uid, session, duration)
        elif method == PAIR_WITHINGS_OAUTH:
            _start_withings_oauth(uid, session)
        elif method == PAIR_MANUAL:
            # Manual: nothing to start — user fills extra_fields and submits.
            session['status'] = 'manual_pending'
        else:
            session['status'] = 'error'
            session['error'] = f'unsupported_method:{method}'
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"pair_start kickoff error ({method}): {exc}")
        session['status'] = 'error'
        session['error'] = str(exc)[:200]

    _gc_pair_sessions()
    with _PAIR_LOCK:
        _PAIR_SESSIONS[pair_id] = session

    logger.info(
        f"pair_start: user={uid[:8]} type={device_type} method={method} "
        f"pair_id={pair_id[:8]} room={room}"
    )
    return jsonify({
        'success': True,
        'pair_id': pair_id,
        'expires_at': session['expires_at'],
        'method': method,
        'instructions': session['instructions'],
        'visual_hint': session['visual_hint'],
        'status': session['status'],
    })


@ha_pairing_bp.route('/api/ha/pair/status', methods=['GET'])
@require_auth
def pair_status():
    pair_id = request.args.get('pair_id', '').strip()
    if not pair_id:
        return jsonify({'success': False, 'error': 'pair_id required'}), 400
    with _PAIR_LOCK:
        session = _PAIR_SESSIONS.get(pair_id)
    if not session:
        return jsonify({'success': False, 'error': 'unknown_or_expired'}), 404
    if session['user_id'] != _uid():
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    # Auto-timeout
    if session['status'] == 'waiting':
        try:
            exp = datetime.fromisoformat(session['expires_at'].rstrip('Z'))
            if datetime.utcnow() > exp:
                session['status'] = 'timeout'
        except Exception:
            pass

    return jsonify({
        'success': True,
        'pair_id': pair_id,
        'status': session['status'],
        'discovered_entity_id': session.get('discovered_entity_id'),
        'suggested_label': session.get('label'),
        'instructions': session.get('instructions'),
        'expires_at': session['expires_at'],
        'error': session.get('error'),
        # BT scan: list of discovered candidates for user to pick from
        'bt_candidates': session.get('bt_candidates', []),
    })


@ha_pairing_bp.route('/api/ha/pair/confirm', methods=['POST'])
@require_auth
def pair_confirm():
    """User confirms manual pairing (Bluetooth speaker, manual setup).

    Body: {pair_id, entity_id (optional, generated if omitted), extra_fields}
    """
    data = request.get_json(silent=True) or {}
    pair_id = (data.get('pair_id') or '').strip()
    if not pair_id:
        return jsonify({'success': False, 'error': 'pair_id required'}), 400
    with _PAIR_LOCK:
        session = _PAIR_SESSIONS.get(pair_id)
    if not session:
        return jsonify({'success': False, 'error': 'unknown_or_expired'}), 404
    if session['user_id'] != _uid():
        return jsonify({'success': False, 'error': 'forbidden'}), 403
    if session['status'] not in ('manual_confirm_pending', 'manual_pending', 'oauth_pending'):
        return jsonify({'success': False, 'error': 'wrong_state',
                        'current_status': session['status']}), 409

    # Generate a synthetic entity_id for non-HA devices (BT speakers etc.)
    entity_id = (data.get('entity_id') or '').strip()
    if not entity_id:
        device_type = session['device_type']
        # Stable but unique synthetic id (e.g. canyon_speaker_<short_uuid>)
        entity_id = f'{device_type}.user_{session["user_id"][:6]}_{pair_id[:6]}'

    with _PAIR_LOCK:
        session['discovered_entity_id'] = entity_id
        session['status'] = 'paired'
        session['extra_fields'] = {**(session.get('extra_fields') or {}),
                                   **(data.get('extra_fields') or {})}
    logger.info(f'pair confirmed manually: pair={pair_id[:8]} entity={entity_id}')
    return jsonify({'success': True, 'discovered_entity_id': entity_id})


@ha_pairing_bp.route('/api/ha/pair/cancel', methods=['POST'])
@require_auth
def pair_cancel():
    data = request.get_json(silent=True) or {}
    pair_id = (data.get('pair_id') or '').strip()
    if not pair_id:
        return jsonify({'success': False, 'error': 'pair_id required'}), 400
    with _PAIR_LOCK:
        session = _PAIR_SESSIONS.get(pair_id)
        if session and session['user_id'] == _uid():
            session['status'] = 'cancelled'
            # If Zigbee, close permit_join
            if session.get('method') == 'zigbee_permit_join':
                _stop_zigbee_pair(session['user_id'])
    return jsonify({'success': True})


# ════════════════════════════════════════════════════════════════════
# 2a. ZIGBEE PAIRING — permit_join + topic sniffing
# ════════════════════════════════════════════════════════════════════

def _start_zigbee_pair(user_id: str, session: dict, duration: int):
    """Open Zigbee2MQTT permit_join window and watch for the next new device."""
    from home_assistant import ha_for
    client = ha_for(user_id)
    if not (client and hasattr(client, 'mqtt_bridge')):
        raise RuntimeError('MQTT bridge unavailable for this user')
    bridge = client.mqtt_bridge
    if not getattr(bridge, 'connected', False):
        raise RuntimeError('MQTT not connected — Zigbee bridge offline')

    # Publish permit_join command to zigbee2mqtt
    bridge.publish('zigbee2mqtt/bridge/request/permit_join',
                   {'value': True, 'time': duration})

    # Register a one-shot handler that captures the first new device announcement
    pair_id = session['pair_id']

    def _handler(topic: str, payload: dict):
        # zigbee2mqtt announces new devices on bridge/event with type='device_joined'
        if topic == 'zigbee2mqtt/bridge/event' and payload.get('type') == 'device_joined':
            new_dev = payload.get('data', {}).get('friendly_name') or payload.get('data', {}).get('ieee_address')
            if not new_dev:
                return
            entity_id = f'sensor.{new_dev}'  # Z2M auto-creates this
            with _PAIR_LOCK:
                sess = _PAIR_SESSIONS.get(pair_id)
                if sess and sess['status'] == 'waiting':
                    sess['discovered_entity_id'] = entity_id
                    sess['status'] = 'paired'
                    sess['raw_event'] = payload
                    logger.info(f'Zigbee paired: pair={pair_id[:8]} entity={entity_id}')

    bridge.on_sensor_update(_handler)


def _stop_zigbee_pair(user_id: str):
    """Close the permit_join window."""
    try:
        from home_assistant import ha_for
        client = ha_for(user_id)
        if client and hasattr(client, 'mqtt_bridge'):
            client.mqtt_bridge.publish(
                'zigbee2mqtt/bridge/request/permit_join',
                {'value': False},
            )
    except Exception as e:
        logger.debug(f'_stop_zigbee_pair: {e}')


# ════════════════════════════════════════════════════════════════════
# 2b. HA CONFIG FLOW PAIRING (speakers + cloud devices)
# ════════════════════════════════════════════════════════════════════

def _start_ha_flow_pair(user_id: str, session: dict, catalog_entry: dict):
    """HA-side discovery: snapshot existing entities in the target domain,
    poll HA every 3s, and the first newly-appearing entity wins.

    Works for:
      - PAIR_TPLINK_DISCOVERY (Tapo plugs, bulbs, Hub) — HA's `tplink`
        integration auto-discovers via mDNS once the device joins Wi-Fi
      - PAIR_TAPO_HUB_SUBDEVICE (T100, T110) — they appear as
        binary_sensor.* attached to the Hub once paired in Tapo app
      - PAIR_HA_CONFIG_FLOW (generic HA discovery — Sonos etc.)
    """
    from home_assistant import ha_for
    client = ha_for(user_id)
    if not (client and client.connected):
        raise RuntimeError('HA not reachable for this user')

    # Determine which domain(s) to watch
    primary_domain = catalog_entry.get('ha_domain') or 'sensor'
    # For Tapo Hub sub-devices, also watch sensor.* (battery indicator
    # often appears alongside the binary_sensor)
    domains_to_watch = {primary_domain}
    if catalog_entry.get('requires_device') == 'tapo_hub':
        domains_to_watch.add('binary_sensor')
        domains_to_watch.add('sensor')

    # Snapshot
    before: set[str] = set()
    states = client.get_all_states(use_cache=False) or []
    for s in states:
        eid = s['entity_id']
        if any(eid.startswith(f'{d}.') for d in domains_to_watch):
            before.add(eid)
    session['ha_flow_before'] = list(before)
    session['ha_flow_domains'] = sorted(domains_to_watch)

    pair_id = session['pair_id']
    duration = int(catalog_entry['pairing']['duration_seconds'])

    def _watcher():
        end_at = time.time() + duration
        while time.time() < end_at:
            time.sleep(3)
            with _PAIR_LOCK:
                sess = _PAIR_SESSIONS.get(pair_id)
                if not sess or sess['status'] != 'waiting':
                    return
            try:
                fresh_states = client.get_all_states(use_cache=False) or []
                for s in fresh_states:
                    eid = s['entity_id']
                    if eid in before:
                        continue
                    if not any(eid.startswith(f'{d}.') for d in domains_to_watch):
                        continue
                    # Found a new entity — accept the most relevant one
                    with _PAIR_LOCK:
                        sess = _PAIR_SESSIONS.get(pair_id)
                        if sess and sess['status'] == 'waiting':
                            sess['discovered_entity_id'] = eid
                            sess['status'] = 'paired'
                            logger.info(
                                f'HA flow paired: pair={pair_id[:8]} entity={eid} '
                                f'method={sess["method"]}'
                            )
                    return
            except Exception as e:
                logger.debug(f'HA flow watcher error: {e}')

    threading.Thread(target=_watcher, daemon=True).start()


def _start_bluetooth_ha_scan(user_id: str, session: dict, catalog_entry: dict):
    """HA bluetooth integration BLE scan.

    HA's bluetooth integration auto-discovers BLE devices that match
    known integrations (Xiaomi BLE, Govee, Switchbot, BTHome, Withings).
    When a new device starts advertising in pairing mode, HA picks it up
    and creates entities in `sensor.*` / `binary_sensor.*` domains.

    Strategy: snapshot all sensor/binary_sensor entities BEFORE pairing,
    poll every 3s during the pairing window, the first new entity that
    has a 'bluetooth' attribute or a BLE-style entity_id wins.

    Also collects ALL new candidates so the frontend can show a list
    if multiple BT devices are advertising at once (e.g. teploměr +
    button in the same room).
    """
    from home_assistant import ha_for
    client = ha_for(user_id)
    if not (client and client.connected):
        raise RuntimeError('HA není dostupný — Bluetooth scan vyžaduje spojení')

    # Snapshot sensor + binary_sensor entities (BLE devices land here)
    domains_to_watch = {'sensor', 'binary_sensor'}
    before: set[str] = set()
    states = client.get_all_states(use_cache=False) or []
    for s in states:
        eid = s.get('entity_id', '')
        if any(eid.startswith(f'{d}.') for d in domains_to_watch):
            before.add(eid)
    session['ha_flow_before'] = list(before)
    session['ha_flow_domains'] = sorted(domains_to_watch)
    session['bt_candidates'] = []  # collected BLE entities seen during scan

    pair_id = session['pair_id']
    duration = int(catalog_entry['pairing']['duration_seconds'])

    def _is_bt_entity(state: dict) -> bool:
        """Heuristic: BLE-derived entity has BT MAC in attributes or
        the entity_id contains a known BT manufacturer prefix."""
        eid = state.get('entity_id', '').lower()
        attrs = state.get('attributes', {}) or {}
        # Entity id hints
        bt_prefixes = ('xiaomi_', 'govee_', 'switchbot_', 'bthome_',
                       'withings_', 'lywsd', 'mijia_', 'mhccc')
        if any(p in eid for p in bt_prefixes):
            return True
        # Attribute hints
        if attrs.get('bluetooth_mac') or attrs.get('mac_address'):
            return True
        manufacturer = (attrs.get('manufacturer') or '').lower()
        if any(m in manufacturer for m in ('xiaomi', 'govee', 'switchbot',
                                           'withings')):
            return True
        return False

    def _watcher():
        end_at = time.time() + duration
        while time.time() < end_at:
            time.sleep(3)
            with _PAIR_LOCK:
                sess = _PAIR_SESSIONS.get(pair_id)
                if not sess or sess['status'] != 'waiting':
                    return
            try:
                fresh_states = client.get_all_states(use_cache=False) or []
                new_bt_entities = []
                for s in fresh_states:
                    eid = s.get('entity_id', '')
                    if eid in before:
                        continue
                    if not any(eid.startswith(f'{d}.') for d in domains_to_watch):
                        continue
                    if not _is_bt_entity(s):
                        continue
                    new_bt_entities.append({
                        'entity_id': eid,
                        'name': s.get('attributes', {}).get('friendly_name', eid),
                        'manufacturer': s.get('attributes', {}).get('manufacturer', ''),
                        'state': s.get('state', ''),
                    })
                if new_bt_entities:
                    with _PAIR_LOCK:
                        sess = _PAIR_SESSIONS.get(pair_id)
                        if sess and sess['status'] == 'waiting':
                            # Update candidates list (might find more on next tick)
                            sess['bt_candidates'] = new_bt_entities
                            # Auto-accept if exactly one device found
                            if len(new_bt_entities) == 1:
                                sess['discovered_entity_id'] = new_bt_entities[0]['entity_id']
                                sess['status'] = 'paired'
                                logger.info(
                                    f'BT scan auto-paired: pair={pair_id[:8]} '
                                    f'entity={sess["discovered_entity_id"]}'
                                )
                                return
                            # Multiple devices — wait for user to pick
                            sess['status'] = 'choose_candidate'
                            logger.info(
                                f'BT scan found {len(new_bt_entities)} devices, '
                                f'waiting for user pick: pair={pair_id[:8]}'
                            )
                            return
            except Exception as e:
                logger.debug(f'BT scan watcher error: {e}')

    threading.Thread(target=_watcher, daemon=True).start()


def _start_bluetooth_host_pair(user_id: str, session: dict, catalog_entry: dict):
    """Bluetooth speaker pairs to the OS of the device running Radim
    (phone / tablet / NUC), not to HA. Backend has no way to detect this —
    we hold the session open and the user manually confirms via wizard.
    """
    session['status'] = 'manual_confirm_pending'
    session['instructions'] = catalog_entry['pairing']['instructions']
    session['confirm_label'] = (
        f'Spárováno — vyzkoušet "{catalog_entry["verification"]["speak_test"]}"'
        if 'verification' in catalog_entry else 'Spárováno'
    )
    logger.info(f'BT host pair waiting for user confirm: pair={session["pair_id"][:8]}')


# ════════════════════════════════════════════════════════════════════
# 2c. WITHINGS OAUTH (placeholder — wires real flow in Sprint D)
# ════════════════════════════════════════════════════════════════════

def _start_withings_oauth(user_id: str, session: dict):
    """Returns instructions; OAuth callback completion happens in
    /api/integrations/withings/callback (not implemented in this sprint).
    """
    session['oauth_url'] = (
        'https://account.withings.com/oauth2_user/authorize2'
        '?response_type=code&client_id=PLACEHOLDER&'
        f'state={session["pair_id"]}&scope=user.metrics'
    )
    session['status'] = 'oauth_pending'
    session['instructions'] = (
        'Otevře se přihlášení do Withings v novém okně. Po přihlášení se '
        'zde zobrazí stav. (Zatím v rané fázi — pro produkci propojíme '
        'cloud OAuth callback.)'
    )


# ════════════════════════════════════════════════════════════════════
# 3. ASSIGNMENTS CRUD
# ════════════════════════════════════════════════════════════════════

@ha_pairing_bp.route('/api/ha/assignments', methods=['GET'])
@require_auth
def list_assignments():
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    from database import db_context
    with db_context() as db:
        rows = db.execute(
            "SELECT assignment_id, user_id, home_id, entity_id, device_type, "
            "room, role, custom_label, manufacturer, model, protocol, "
            "config, auto_actions, last_seen_at, created_at "
            "FROM device_assignments WHERE user_id = ? ORDER BY room, role, custom_label",
            (uid,)
        ).fetchall() or []
    items = [_row_to_assignment(r) for r in rows]
    return jsonify({'success': True, 'assignments': items, 'count': len(items)})


@ha_pairing_bp.route('/api/ha/assignments', methods=['POST'])
@require_auth
def create_assignment():
    """Persist a paired device into device_assignments.

    Body: {entity_id, device_type, room, role, custom_label, ...}
    """
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401

    data = request.get_json(silent=True) or {}
    required = ('entity_id', 'device_type')
    missing = [k for k in required if not (data.get(k) or '').strip()]
    if missing:
        return jsonify({'success': False, 'error': 'missing_fields',
                        'missing': missing}), 400

    from device_catalog import get_device
    catalog = get_device(data['device_type'])
    if not catalog:
        return jsonify({'success': False, 'error': 'unknown_device_type'}), 400

    assignment_id = str(uuid.uuid4())
    now = datetime.utcnow()

    config_blob = data.get('config') or {}
    auto_actions = data.get('auto_actions') or catalog.get('auto_actions') or {}

    from database import db_context, is_postgres
    with db_context(commit=True) as db:
        # Upsert by (user_id, entity_id) UNIQUE
        existing = db.execute(
            "SELECT assignment_id FROM device_assignments "
            "WHERE user_id = ? AND entity_id = ?",
            (uid, data['entity_id'])
        ).fetchone()
        if existing:
            assignment_id = existing[0] if isinstance(existing, (list, tuple)) else existing['assignment_id']
            db.execute(
                "UPDATE device_assignments SET device_type = ?, room = ?, "
                "role = ?, custom_label = ?, manufacturer = ?, model = ?, "
                "protocol = ?, config = ?, auto_actions = ?, updated_at = ? "
                "WHERE assignment_id = ?",
                (data['device_type'], data.get('room', ''),
                 data.get('role') or catalog.get('default_role') or '',
                 data.get('custom_label') or catalog['label'],
                 data.get('manufacturer', ''), data.get('model', ''),
                 catalog.get('protocol', ''),
                 json.dumps(config_blob), json.dumps(auto_actions),
                 now, assignment_id)
            )
        else:
            db.execute(
                "INSERT INTO device_assignments "
                "(assignment_id, user_id, home_id, entity_id, device_type, "
                " room, role, custom_label, manufacturer, model, protocol, "
                " config, auto_actions, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (assignment_id, uid, data.get('home_id', ''),
                 data['entity_id'], data['device_type'],
                 data.get('room', ''),
                 data.get('role') or catalog.get('default_role') or '',
                 data.get('custom_label') or catalog['label'],
                 data.get('manufacturer', ''), data.get('model', ''),
                 catalog.get('protocol', ''),
                 json.dumps(config_blob), json.dumps(auto_actions),
                 now, now)
            )

    logger.info(
        f"assignment created: user={uid[:8]} entity={data['entity_id']} "
        f"type={data['device_type']} room={data.get('room', '?')}"
    )
    saved = _get_assignment(uid, assignment_id)
    return jsonify({'success': True, 'assignment': saved}), 201


@ha_pairing_bp.route('/api/ha/assignments/<assignment_id>', methods=['PATCH'])
@require_auth
def update_assignment(assignment_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    allowed = ('room', 'role', 'custom_label', 'config', 'auto_actions')
    sets = []
    args: list = []
    for k in allowed:
        if k in data:
            v = data[k]
            if k in ('config', 'auto_actions'):
                v = json.dumps(v or {})
            sets.append(f"{k} = ?")
            args.append(v)
    if not sets:
        return jsonify({'success': False, 'error': 'no_fields'}), 400
    sets.append("updated_at = ?")
    args.append(datetime.utcnow())
    args.extend([uid, assignment_id])

    from database import db_context
    with db_context(commit=True) as db:
        cur = db.execute(
            f"UPDATE device_assignments SET {', '.join(sets)} "
            "WHERE user_id = ? AND assignment_id = ?",
            tuple(args)
        )
    if getattr(cur, 'rowcount', 0) == 0:
        return jsonify({'success': False, 'error': 'not_found'}), 404
    return jsonify({'success': True, 'assignment': _get_assignment(uid, assignment_id)})


@ha_pairing_bp.route('/api/ha/assignments/<assignment_id>', methods=['DELETE'])
@require_auth
def delete_assignment(assignment_id):
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    from database import db_context
    with db_context(commit=True) as db:
        cur = db.execute(
            "DELETE FROM device_assignments WHERE user_id = ? AND assignment_id = ?",
            (uid, assignment_id)
        )
    if getattr(cur, 'rowcount', 0) == 0:
        return jsonify({'success': False, 'error': 'not_found'}), 404
    return jsonify({'success': True})


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def _row_to_assignment(row) -> dict:
    if hasattr(row, 'keys'):
        d = dict(row)
    else:
        d = {
            'assignment_id': row[0], 'user_id': row[1], 'home_id': row[2],
            'entity_id': row[3], 'device_type': row[4], 'room': row[5],
            'role': row[6], 'custom_label': row[7], 'manufacturer': row[8],
            'model': row[9], 'protocol': row[10], 'config': row[11],
            'auto_actions': row[12], 'last_seen_at': row[13], 'created_at': row[14],
        }
    # Decode JSON blobs (PG JSONB returns dict, sqlite returns string)
    for k in ('config', 'auto_actions'):
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v) if v else {}
            except (TypeError, ValueError):
                d[k] = {}
        elif v is None:
            d[k] = {}
    return d


def _get_assignment(user_id: str, assignment_id: str) -> dict | None:
    from database import db_context
    with db_context() as db:
        row = db.execute(
            "SELECT assignment_id, user_id, home_id, entity_id, device_type, "
            "room, role, custom_label, manufacturer, model, protocol, "
            "config, auto_actions, last_seen_at, created_at "
            "FROM device_assignments WHERE user_id = ? AND assignment_id = ?",
            (user_id, assignment_id)
        ).fetchone()
    return _row_to_assignment(row) if row else None


def find_assignment_by_room_role(user_id: str, room: str, role: str) -> dict | None:
    """Used by intent_resolver: 'zhasni v ložnici' → finds the right entity."""
    from database import db_context
    with db_context() as db:
        row = db.execute(
            "SELECT assignment_id, user_id, home_id, entity_id, device_type, "
            "room, role, custom_label, manufacturer, model, protocol, "
            "config, auto_actions, last_seen_at, created_at "
            "FROM device_assignments WHERE user_id = ? AND room = ? AND role = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (user_id, room, role)
        ).fetchone()
    return _row_to_assignment(row) if row else None


logger.info('🔗 HA pairing routes loaded: catalog, pair/{start,status,cancel}, assignments')
