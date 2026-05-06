#!/usr/bin/env python3
"""
🔌 RadimCare Tapo Gateway v1.0
================================
Local poller for TP-Link Tapo devices. Runs on the mini PC in the senior's
apartment, polls Tapo cloud + local API, posts readings to Heroku Radim
backend.

Hardware tested with (1× pilot byt):
  • Tapo H110          IoT hub (sub-1GHz ↔ Wi-Fi bridge)
  • Tapo T100          PIR motion sensor (battery, via H110)
  • Tapo T110          door/window contact (battery, via H110)
  • Tapo P115 × 2      smart plugs with energy monitoring (Wi-Fi)
  • Tapo L510E         dimmable smart bulb (Wi-Fi)

Required env (set in /etc/radimcare-gateway.env or systemd):
  TAPO_EMAIL              your TP-Link account email
  TAPO_PASSWORD           account password
  RADIM_API_BASE          https://radim-brain-2025-be1cd52b04dc.herokuapp.com
                          (or https://api.radimcare.cz once CNAME is set)
  IOT_GATEWAY_TOKEN       shared secret (must match Heroku config)
  RADIM_SENIOR_ID         this apartment's senior user_id (UUID)
  RADIM_ROOM_PREFIX       optional room name prefix, e.g. "byt_novakova"
  POLL_INTERVAL_SECONDS   default 30

Install (Windows 10/11 mini PC):
  1. Python 3.11+ z https://python.org (zaškrtnout "Add to PATH")
  2. cmd jako Administrator:
       pip install tapo aiohttp
       mkdir C:\RadimCare
       copy tapo_gateway.py C:\RadimCare\
       copy tapo_gateway.bat C:\RadimCare\
  3. Vytvořit env soubor C:\RadimCare\.env (viz env vars níže)
  4. Task Scheduler:
       - Trigger: At system startup
       - Action: C:\RadimCare\tapo_gateway.bat
       - Settings: Restart task if fails (every 1 min, 999×)
  5. Test: spustit ručně .bat, zkontrolovat C:\RadimCare\gateway.log

Install (Linux mini PC, Ubuntu 22.04+):
  pip3 install tapo aiohttp
  sudo cp tapo_gateway.py /opt/radimcare/
  sudo cp radimcare-gateway.service /etc/systemd/system/
  sudo systemctl enable --now radimcare-gateway

Architecture:
  ┌──── mini PC (this script) ─────────────┐
  │                                         │
  │  tapo.ApiClient(email, password)        │
  │   ├─ p115_kuchyne_rychlovarka.get_state │
  │   ├─ p115_kuchyne_mikrovlnka.get_state  │
  │   ├─ l510e_loznice_svetlo.get_state     │
  │   └─ h110_hub                           │
  │      ├─ child(t100_obyvak).get_state    │  via hub
  │      └─ child(t110_dvere).get_state     │  via hub
  │                                         │
  │  every 30s → batch POST → Heroku        │
  │     /api/iot-bridge/data/batch          │
  └─────────────────────────────────────────┘
"""

import os
import sys
import json
import time
import asyncio
import logging
from datetime import datetime, timezone

try:
    from tapo import ApiClient
except ImportError:
    print("ERROR: pip install tapo  (the mihai-dinculescu/tapo library)", file=sys.stderr)
    sys.exit(1)

import aiohttp

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("tapo_gateway")


# ─── Config ────────────────────────────────────────────────────────────────

TAPO_EMAIL    = os.environ.get("TAPO_EMAIL", "")
TAPO_PASSWORD = os.environ.get("TAPO_PASSWORD", "")
RADIM_API     = os.environ.get("RADIM_API_BASE",
                               "https://radim-brain-2025-be1cd52b04dc.herokuapp.com")
IOT_TOKEN     = os.environ.get("IOT_GATEWAY_TOKEN", "")
SENIOR_ID     = os.environ.get("RADIM_SENIOR_ID", "")
ROOM_PREFIX   = os.environ.get("RADIM_ROOM_PREFIX", "byt")
POLL_S        = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

# Device IPs are auto-discovered, but H110 requires login on the hub itself.
# Per-device IP can be hard-coded or set via Tapo app's static lease in the
# router. For pilot, IP-by-mDNS-name works on most home routers:
DEVICES = {
    # Wi-Fi devices (direct local API)
    "p115_rychlovarka": {
        "type": "P115",  "ip": os.environ.get("TAPO_P115_RYCHLOVARKA_IP", ""),
        "room": f"{ROOM_PREFIX}_kuchyne",
        "name": "Rychlovarka",
    },
    "p115_mikrovlnka": {
        "type": "P115",  "ip": os.environ.get("TAPO_P115_MIKROVLNKA_IP", ""),
        "room": f"{ROOM_PREFIX}_kuchyne",
        "name": "Mikrovlnka",
    },
    "l510e_loznice": {
        "type": "L510",  "ip": os.environ.get("TAPO_L510E_LOZNICE_IP", ""),
        "room": f"{ROOM_PREFIX}_loznice",
        "name": "Lampa u postele",
    },
    # Sub-1GHz devices reach via H110 hub child API
    "h110_hub": {
        "type": "H110",  "ip": os.environ.get("TAPO_H110_IP", ""),
        "room": f"{ROOM_PREFIX}_hub",
        "name": "Hub",
        "children": {
            "t100_obyvak":  {"type": "T100", "room": f"{ROOM_PREFIX}_obyvak",
                             "name": "Pohyb obývák"},
            "t110_dvere":   {"type": "T110", "room": f"{ROOM_PREFIX}_chodba",
                             "name": "Dveře vstup"},
        },
    },
}


# ─── Posting layer ─────────────────────────────────────────────────────────

_START_TIME = time.time()


async def _post_batch(session, readings):
    """POST batch of readings to Heroku /api/iot-bridge/data/batch."""
    if not readings:
        return
    if not IOT_TOKEN:
        logger.warning("IOT_GATEWAY_TOKEN not set, skipping POST")
        return

    url = f"{RADIM_API.rstrip('/')}/api/iot-bridge/data/batch"
    headers = {"X-IoT-Token": IOT_TOKEN, "Content-Type": "application/json"}
    payload = {"readings": readings, "senior_id": SENIOR_ID}

    try:
        async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
            if resp.status >= 400:
                body = await resp.text()
                logger.error(f"POST failed {resp.status}: {body[:200]}")
            else:
                logger.info(f"POSTed {len(readings)} readings → {resp.status}")
    except Exception as e:
        logger.warning(f"POST error (will retry next tick): {e}")


async def _post_heartbeat(session):
    """v8.19.108: POST gateway heartbeat — backend ví, že mini PC žije.

    Detektor _detect_gateway_offline triggeruje, pokud > 5 min nedostane HB.
    """
    if not IOT_TOKEN or not SENIOR_ID:
        return
    url = f"{RADIM_API.rstrip('/')}/api/iot-bridge/heartbeat"
    headers = {"X-IoT-Token": IOT_TOKEN, "Content-Type": "application/json"}
    payload = {
        "senior_id": SENIOR_ID,
        "gateway_id": f"gw_{ROOM_PREFIX}",
        "version": "1.0",
        "uptime_s": int(time.time() - _START_TIME),
        "room_id": f"{ROOM_PREFIX}_gateway",
    }
    try:
        async with session.post(url, json=payload, headers=headers, timeout=5) as resp:
            if resp.status >= 400:
                logger.warning(f"HB failed {resp.status}")
    except Exception as e:
        logger.debug(f"HB error: {e}")


def _reading(device_id, room_id, sensor_type, value, unit="", metadata=None):
    return {
        "device_id":   device_id,
        "room_id":     room_id,
        "sensor_type": sensor_type,
        "value":       float(value),
        "unit":        unit,
        "metadata":    metadata or {},
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── Per-device pollers ────────────────────────────────────────────────────

async def _poll_p115(client, dev_id, conf):
    """P115: smart plug + energy monitoring."""
    if not conf["ip"]:
        return []
    out = []
    try:
        plug = await client.p115(conf["ip"])
        info = await plug.get_device_info()
        # device_on bool, signal_level int
        out.append(_reading(dev_id, conf["room"], "plug_state",
                            1 if info.device_on else 0, "bool",
                            {"name": conf["name"], "model": "P115"}))
        # Energy monitoring (watts)
        try:
            energy = await plug.get_current_power()
            out.append(_reading(dev_id, conf["room"], "power_w",
                                energy.current_power, "W",
                                {"name": conf["name"]}))
        except Exception as e:
            logger.debug(f"P115 {dev_id} energy not available: {e}")
    except Exception as e:
        logger.warning(f"P115 {dev_id} poll failed: {e}")
    return out


async def _poll_l510(client, dev_id, conf):
    """L510E: smart bulb."""
    if not conf["ip"]:
        return []
    out = []
    try:
        bulb = await client.l510(conf["ip"])
        info = await bulb.get_device_info()
        out.append(_reading(dev_id, conf["room"], "bulb_state",
                            1 if info.device_on else 0, "bool",
                            {"name": conf["name"], "model": "L510E",
                             "brightness": getattr(info, "brightness", None)}))
        if getattr(info, "brightness", None) is not None:
            out.append(_reading(dev_id, conf["room"], "brightness",
                                info.brightness, "percent",
                                {"name": conf["name"]}))
    except Exception as e:
        logger.warning(f"L510 {dev_id} poll failed: {e}")
    return out


async def _poll_h110_children(client, hub_conf):
    """H100/H110 hub: query for child devices (T100, T110).

    API podle mihai-dinculescu/tapo lib — ověřeno z tapo_h100.py example:
      • client.h100(ip)  ← stejná metoda i pro H110 (kompatibilní API)
      • hub.get_child_device_list()
      • T100: child.detected (bool)
      • T110: child.open (bool)
      • battery: child.at_low_battery (bool flag) — procenta nejsou
        v public API, jen low/normal flag

    Pro 'no motion N hours' detektor zapisujeme RŮZNĚ:
      • motion_detected: 1 když právě detekován, 0 když ne — historie v DB
        nám dá "kdy naposled byla 1" → odečteme age v detektoru
    """
    out = []
    if not hub_conf["ip"]:
        return out
    try:
        # H110 používá stejné API jako H100 — metoda je client.h100()
        hub = await client.h100(hub_conf["ip"])
        children = await hub.get_child_device_list()
        for child in children:
            ch_name = (getattr(child, "nickname", "") or
                       getattr(child, "device_id", "")) or "unknown"
            ch_model = (getattr(child, "model", "") or "").upper()

            # T100 motion sensor — .detected je bool (live)
            if "T100" in ch_model:
                detected = bool(getattr(child, "detected", False))
                room = _resolve_child_room(ch_name, "obyvak")
                out.append(_reading(
                    f"t100_{room}", room, "motion_detected",
                    1 if detected else 0, "bool",
                    {"name": ch_name, "model": "T100"}
                ))
                # Low-battery flag (separátní, ne procenta — Tapo public
                # API procenta nedává, jen on/off threshold)
                low_bat = getattr(child, "at_low_battery", None)
                if low_bat is not None:
                    out.append(_reading(
                        f"t100_{room}", room, "low_battery",
                        1 if bool(low_bat) else 0, "bool",
                        {"name": ch_name, "model": "T100"}
                    ))

            # T110 contact sensor — .open je bool (live)
            elif "T110" in ch_model:
                opened = bool(getattr(child, "open", False))
                room = _resolve_child_room(ch_name, "chodba")
                out.append(_reading(
                    f"t110_{room}", room, "contact_state",
                    1 if opened else 0, "bool",
                    {"name": ch_name, "model": "T110"}
                ))
                low_bat = getattr(child, "at_low_battery", None)
                if low_bat is not None:
                    out.append(_reading(
                        f"t110_{room}", room, "low_battery",
                        1 if bool(low_bat) else 0, "bool",
                        {"name": ch_name, "model": "T110"}
                    ))

        # Hub samo o sobě — heartbeat
        out.append(_reading(
            "h110_hub", hub_conf["room"], "hub_online", 1, "bool",
            {"name": hub_conf["name"], "model": "H110",
             "children_count": len(children)}
        ))
    except Exception as e:
        logger.warning(f"H100/H110 hub poll failed: {e}")
        out.append(_reading(
            "h110_hub", hub_conf["room"], "hub_online", 0, "bool",
            {"error": str(e)[:100]}
        ))
    return out


def _resolve_child_room(child_name: str, default: str) -> str:
    """Map Tapo nickname → our room_id. User pojmenuje v Tapo app."""
    name = (child_name or "").lower()
    if "obyvak" in name or "obývák" in name or "living" in name:
        return f"{ROOM_PREFIX}_obyvak"
    if "loznice" in name or "ložnice" in name or "bedroom" in name:
        return f"{ROOM_PREFIX}_loznice"
    if "kuchyn" in name or "kitchen" in name:
        return f"{ROOM_PREFIX}_kuchyne"
    if "chodba" in name or "vstup" in name or "dveř" in name or "dver" in name:
        return f"{ROOM_PREFIX}_chodba"
    if "koupel" in name:
        return f"{ROOM_PREFIX}_koupelna"
    return f"{ROOM_PREFIX}_{default}"


# ─── Main loop ─────────────────────────────────────────────────────────────

async def main():
    if not TAPO_EMAIL or not TAPO_PASSWORD:
        logger.error("TAPO_EMAIL / TAPO_PASSWORD not set")
        sys.exit(1)
    if not SENIOR_ID:
        logger.warning("RADIM_SENIOR_ID not set — readings will not be linked to a senior")

    logger.info(f"🔌 Tapo Gateway starting; senior={SENIOR_ID}, "
                f"prefix={ROOM_PREFIX}, poll={POLL_S}s")
    logger.info(f"   API: {RADIM_API}")

    client = ApiClient(TAPO_EMAIL, TAPO_PASSWORD)
    async with aiohttp.ClientSession() as session:
        while True:
            t0 = time.time()
            readings = []

            # Wi-Fi devices
            for dev_id, conf in DEVICES.items():
                if conf["type"] == "P115":
                    readings.extend(await _poll_p115(client, dev_id, conf))
                elif conf["type"] == "L510":
                    readings.extend(await _poll_l510(client, dev_id, conf))
                elif conf["type"] == "H110":
                    readings.extend(await _poll_h110_children(client, conf))

            # Send batch + heartbeat
            await _post_batch(session, readings)
            await _post_heartbeat(session)

            elapsed = time.time() - t0
            sleep_s = max(1, POLL_S - elapsed)
            logger.debug(f"Tick: {len(readings)} readings in {elapsed:.1f}s, sleep {sleep_s:.1f}s")
            await asyncio.sleep(sleep_s)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Tapo Gateway stopped")
