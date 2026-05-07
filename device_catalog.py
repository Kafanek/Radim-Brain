"""
🛒 DEVICE CATALOG (v397) — pre-configured device types for the senior wizard.
=============================================================================

Reflects the actual STARTER KIT in proforma O36312996 (TP-Link Tapo +
Canyon BT speaker), not generic Aqara/Zigbee. This means:
  - No Zigbee2MQTT setup required (Tapo Hub speaks Wi-Fi/proprietary)
  - HA's built-in `tplink` integration auto-discovers via mDNS on port 9999
  - Tapo Hub MUST be paired FIRST — sub-sensors (T100, T110) attach to it
  - Canyon OnMove is a Bluetooth speaker — pairs to the device that runs
    Radim (NUC / phone), not to HA itself

Catalog flags:
  - `starter_kit: True`  — show in primary tile section
  - `pairing_order: N`   — wizard shows them in this order (Hub=1 first!)

Each entry tells the frontend wizard:
  - How to render the tile (icon, tagline)
  - How to talk to the user during pairing (instructions, hints)
  - What the backend should do (HA tplink discovery / BT pair / manual)
  - How to auto-assign once paired (default role, default room hint)
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════
# PAIRING METHODS — what the backend does when wizard says "start"
# ════════════════════════════════════════════════════════════════════

PAIR_TPLINK_DISCOVERY = 'tplink_discovery'        # HA tplink integration mDNS scan
PAIR_TAPO_HUB_SUBDEVICE = 'tapo_hub_subdevice'    # T100/T110 attach to existing Hub
PAIR_BLUETOOTH_HOST = 'bluetooth_host'            # User pairs BT speaker to phone/NUC
PAIR_BLUETOOTH_HA = 'bluetooth_ha'                # HA bluetooth integration BLE scan
PAIR_HA_CONFIG_FLOW = 'ha_config_flow'            # Generic HA flow (other brands)
PAIR_ZIGBEE_PERMIT_JOIN = 'zigbee_permit_join'    # Aqara/Sonoff Zigbee (future)
PAIR_WITHINGS_OAUTH = 'withings_oauth'            # Wearable OAuth dance (future)
PAIR_MANUAL = 'manual'                             # Technician sets up, app records


# ════════════════════════════════════════════════════════════════════
# CATALOG — STARTER KIT (Tapo + Canyon — actual proforma O36312996)
# ════════════════════════════════════════════════════════════════════

DEVICE_CATALOG = {

    # ─── 1. Tapo H110 Hub — must be first ───
    'tapo_hub': {
        'category': 'infrastructure',
        'starter_kit': True,
        'pairing_order': 1,
        'label': 'Tapo Hub (H110)',
        'icon': '📡',
        'tagline': 'Mozek pro Tapo senzory',
        'description': (
            'Malá bílá krabička do zásuvky. Přijímá signály z Tapo senzorů '
            '(pohyb, dveře). Bez Hubu nebudou T100 a T110 fungovat — '
            'přidejte ho jako úplně první.'
        ),
        'manufacturer_hints': ['TP-Link Tapo H110'],
        'protocol': 'wifi',
        'pairing': {
            'method': PAIR_TPLINK_DISCOVERY,
            'duration_seconds': 60,
            'instructions': (
                'Zapojte Hub do zásuvky a vyčkejte, než LED bliká pomalu. '
                'V aplikaci Tapo (na mobilu) Hub jednorázově nastavte do '
                'Wi-Fi. Pak Radim Hub najde do 30 sekund.'
            ),
            'visual_hint': 'Modrá LED svítí trvale = připojen k síti.',
            'requires_fields': [],
        },
        'default_role': 'gateway',
        'default_device_class': None,
        'ha_domain': 'sensor',  # Hub se hlásí jako sensor.tapo_h110_signal
        'detected_signals': ['hub_status'],
        'auto_actions': {},
    },

    # ─── 2. Tapo P115 smart plug ─── ×2 v objednávce
    'tapo_plug': {
        'category': 'control',
        'starter_kit': True,
        'pairing_order': 2,
        'label': 'Smart zásuvka (P115)',
        'icon': '🔌',
        'tagline': 'Zapni / vypni jakýkoliv spotřebič',
        'description': (
            'Mini zásuvka na Wi-Fi. Radim přes ni může zapínat lampu, rádio, '
            'topinkovač. Měří i spotřebu — zjistí, kdyby babička zapomněla '
            'vypnout žehličku.'
        ),
        'manufacturer_hints': ['TP-Link Tapo P115'],
        'protocol': 'wifi',
        'pairing': {
            'method': PAIR_TPLINK_DISCOVERY,
            'duration_seconds': 60,
            'instructions': (
                'Zasuňte zásuvku do zdi. V aplikaci Tapo ji jednorázově '
                'připojte k Wi-Fi. Pak ji Radim sám najde a zeptá se, '
                'co je do ní zapojené (lampa? rádio? topinkovač?).'
            ),
            'visual_hint': 'Zelená LED = připojeno. Oranžová = čeká na Wi-Fi.',
            'requires_fields': [],
        },
        'default_role': 'switch',
        'default_device_class': 'outlet',
        'ha_domain': 'switch',
        'detected_signals': ['state', 'current_power_w', 'today_energy'],
        'auto_actions': {'energy_anomaly_alert': True},
    },

    # ─── 3. Tapo T100 motion sensor ───
    'tapo_motion': {
        'category': 'sensor',
        'starter_kit': True,
        'pairing_order': 3,
        'label': 'Senzor pohybu (T100)',
        'icon': '🚶',
        'tagline': 'Radim pozná, kdy vstáváte',
        'description': (
            'Malý čtvereček do rohu místnosti, na baterku. Hlásí se přes '
            'Tapo Hub. Báze pro detekci ranního probuzení a noční '
            'aktivity. Vydrží roky bez výměny baterie.'
        ),
        'manufacturer_hints': ['TP-Link Tapo T100'],
        'protocol': 'wifi_via_hub',
        'pairing': {
            'method': PAIR_TAPO_HUB_SUBDEVICE,
            'duration_seconds': 60,
            'instructions': (
                'V aplikaci Tapo přidejte senzor k Hubu (přidržte tlačítko '
                'na zadní straně 5s). Radim ho pak vidí jako součást Hubu.'
            ),
            'visual_hint': 'Krátké blikání = párování s Hubem.',
            'requires_fields': [],
        },
        'requires_device': 'tapo_hub',
        'default_role': 'motion',
        'default_device_class': 'motion',
        'ha_domain': 'binary_sensor',
        'detected_signals': ['occupancy', 'battery'],
        'auto_actions': {'night_alert': True, 'morning_log': True},
    },

    # ─── 4. Tapo T110 door/window sensor ───
    'tapo_contact': {
        'category': 'sensor',
        'starter_kit': True,
        'pairing_order': 4,
        'label': 'Senzor dveří / okna (T110)',
        'icon': '🚪',
        'tagline': 'Hlídá vchod a okna',
        'description': (
            'Dvojdílný senzor — jedna část na rám dveří, druhá na dveře. '
            'Když se otevřou, Radim to ví. Užitečné pro vchod (poznáme '
            'odchod) i ledničku (kontrola krmení).'
        ),
        'manufacturer_hints': ['TP-Link Tapo T110'],
        'protocol': 'wifi_via_hub',
        'pairing': {
            'method': PAIR_TAPO_HUB_SUBDEVICE,
            'duration_seconds': 60,
            'instructions': (
                'V aplikaci Tapo přidejte senzor k Hubu. Vyzkoušejte '
                'otevřením/zavřením — musí 2× pípnout na potvrzení.'
            ),
            'visual_hint': 'Oranžová LED 3× blikne při zavření = funguje.',
            'requires_fields': [],
        },
        'requires_device': 'tapo_hub',
        'default_role': 'contact',
        'default_device_class': 'opening',
        'ha_domain': 'binary_sensor',
        'detected_signals': ['contact', 'battery'],
        'auto_actions': {'door_log': True},
    },

    # ─── 5. Tapo L510E smart bulb ───
    'tapo_bulb': {
        'category': 'control',
        'starter_kit': True,
        'pairing_order': 5,
        'label': 'Smart žárovka (L510E)',
        'icon': '💡',
        'tagline': 'Stmívatelná teplá bílá',
        'description': (
            'Wi-Fi žárovka E27, stmívatelná, teplé bílé světlo. Radim ji '
            'umí ráno postupně rozsvěcet (digitální východ slunce) a '
            'večer ztlumit. Šetří očím seniora.'
        ),
        'manufacturer_hints': ['TP-Link Tapo L510E'],
        'protocol': 'wifi',
        'pairing': {
            'method': PAIR_TPLINK_DISCOVERY,
            'duration_seconds': 60,
            'instructions': (
                'Zašroubujte do objímky E27. Zapněte vypínač — žárovka '
                'pulzuje = čeká na Wi-Fi. V aplikaci Tapo ji jednorázově '
                'připojte. Radim ji pak najde sám.'
            ),
            'visual_hint': 'Pulzování = párování. Stálé světlo = hotovo.',
            'requires_fields': [],
        },
        'default_role': 'light',
        'default_device_class': None,
        'ha_domain': 'light',
        'detected_signals': ['state', 'brightness', 'color_temp'],
        'auto_actions': {'sunrise_routine': True, 'sunset_dim': True},
    },

    # ─── 6. Canyon OnMove 11 — Bluetooth speaker ───
    'canyon_speaker': {
        'category': 'output',
        'starter_kit': True,
        'pairing_order': 6,
        'label': 'Reproduktor Canyon (OnMove 11)',
        'icon': '🔊',
        'tagline': 'Aby Radim mluvil',
        'description': (
            'Přenosný Bluetooth reproduktor 20W, vodotěsný (IPX6). Spáruje '
            'se přes Bluetooth se zařízením, na kterém běží Radim '
            '(telefon, tablet nebo NUC). 24 hodin výdrže na nabití.'
        ),
        'manufacturer_hints': ['Canyon OnMove 11 (HA1CNECBTSP11)'],
        'protocol': 'bluetooth',
        'pairing': {
            'method': PAIR_BLUETOOTH_HOST,
            'duration_seconds': 90,
            'instructions': (
                '1. Zapněte reproduktor (delší stisk power tlačítka).\n'
                '2. Držte Bluetooth tlačítko, dokud nezačne rychle blikat '
                'modře.\n'
                '3. Na vašem zařízení (telefon / tablet / NUC) otevřete '
                'Nastavení → Bluetooth a vyberte "Canyon OnMove 11". '
                'Spárujte.\n'
                '4. Vyzkoušejte: Radim řekne "Ahoj, jsem Radim".'
            ),
            'visual_hint': 'Modré rychlé blikání = připraven k párování.',
            'requires_fields': ['paired_with_device'],
        },
        'default_role': 'speaker',
        'default_device_class': None,
        'ha_domain': None,  # Není HA entity — pairing přímo s OS
        'detected_signals': [],
        'auto_actions': {'set_as_default_voice_target': True},
        'verification': {
            'speak_test': 'Ahoj, jsem Radim. Slyšíte mě dobře?',
        },
    },

    # ════════════════════════════════════════════════════════════════
    # BLUETOOTH — HA's bluetooth integration (BLE auto-discovery)
    # Pairing flow: user activates pairing on the device, HA's BT
    # scanner picks it up within seconds, wizard shows the list to pick
    # from. Works with Xiaomi BLE, Govee, BTHome, Switchbot, Withings,
    # ESPHome bluetooth_proxy, etc.
    # ════════════════════════════════════════════════════════════════

    'bluetooth_scan': {
        'category': 'sensor',
        'starter_kit': False,
        'pairing_order': 50,
        'label': 'Bluetooth zařízení (auto-scan)',
        'icon': '📶',
        'tagline': 'Najdu cokoli v dosahu',
        'description': (
            'Pro BLE senzory: Xiaomi teploměr, Govee, Switchbot, BTHome, '
            'Withings vahy, BPM monitor. Stiskněte párovací tlačítko '
            'zařízení a Radim ho najde do 30 sekund přes Home Assistant.'
        ),
        'manufacturer_hints': [
            'Xiaomi LYWSD03MMC (teploměr)',
            'Govee H5072 / H5075 (teploměr/vlhkoměr)',
            'Switchbot Meter / Button',
            'Withings BPM Core / Body+',
            'jakýkoliv BTHome 2.0 sensor',
        ],
        'protocol': 'bluetooth_le',
        'pairing': {
            'method': PAIR_BLUETOOTH_HA,
            'duration_seconds': 60,
            'instructions': (
                '1. Aktivujte párovací režim na zařízení (stiskněte '
                'tlačítko 3-5s, nebo vložte baterii — viz manuál).\n'
                '2. Radim během 60 sekund naskenuje vše v dosahu Bluetooth '
                'a zobrazí seznam.\n'
                '3. Vyberete to vaše a Radim si ho zapamatuje.'
            ),
            'visual_hint': 'LED bliká rychle = párovací režim aktivní.',
            'requires_fields': [],
        },
        'default_role': 'bt_sensor',
        'default_device_class': None,
        'ha_domain': 'sensor',  # BLE devices typically appear as sensor.*
        'detected_signals': ['temperature', 'humidity', 'battery', 'pressure',
                             'illuminance', 'motion', 'weight', 'heart_rate'],
        'auto_actions': {},
    },

    'bt_thermometer': {
        'category': 'sensor',
        'starter_kit': False,
        'pairing_order': 51,
        'label': 'BT teploměr (Xiaomi LYWSD03MMC)',
        'icon': '🌡️',
        'tagline': 'Levný BT teploměr s LCD',
        'description': (
            'Cca 150 Kč na e-shopech. Bateriová životnost 1 rok. Ukazuje '
            'teplotu a vlhkost na malém LCD. Radim přes BLE čte hodnoty '
            'každých 10 minut. Žádný Hub netřeba.'
        ),
        'manufacturer_hints': ['Xiaomi LYWSD03MMC', 'Mijia Bluetooth Thermometer'],
        'protocol': 'bluetooth_le',
        'pairing': {
            'method': PAIR_BLUETOOTH_HA,
            'duration_seconds': 60,
            'instructions': (
                'Vložte baterii do teploměru. Radim ho najde sám během '
                'minuty (LYWSD03MMC vysílá hodnoty stále).'
            ),
            'visual_hint': 'Po vložení baterie se na LCD ukáže teplota.',
            'requires_fields': [],
        },
        'default_role': 'climate',
        'default_device_class': 'temperature',
        'ha_domain': 'sensor',
        'detected_signals': ['temperature', 'humidity', 'battery'],
        'auto_actions': {'min_temp_alert': 18, 'max_temp_alert': 28},
    },

    'bt_health': {
        'category': 'health',
        'starter_kit': False,
        'pairing_order': 52,
        'label': 'BT vážka / tlakoměr',
        'icon': '⚖️',
        'tagline': 'Withings, Xiaomi, BTHome',
        'description': (
            'Pro BT vážku (Xiaomi Mi Body Composition Scale 2), tlakoměr '
            '(Withings BPM Core), oximeter. Radim načítá hodnoty automaticky '
            'po měření.'
        ),
        'manufacturer_hints': [
            'Xiaomi Mi Body Composition Scale 2',
            'Withings BPM Core (BT mode)',
            'Beurer SBM',
        ],
        'protocol': 'bluetooth_le',
        'pairing': {
            'method': PAIR_BLUETOOTH_HA,
            'duration_seconds': 90,
            'instructions': (
                'Zapněte BT režim na zařízení. Pro vážku — postavte se na '
                'ni. Pro tlakoměr — proveďte jedno měření. Radim ho zachytí.'
            ),
            'visual_hint': 'Většina BT health zařízení vysílá hodnoty po měření.',
            'requires_fields': [],
        },
        'default_role': 'health_sensor',
        'default_device_class': None,
        'ha_domain': 'sensor',
        'detected_signals': ['weight', 'bmi', 'heart_rate', 'blood_pressure_sys',
                             'blood_pressure_dia', 'spo2'],
        'auto_actions': {},
    },

    # ════════════════════════════════════════════════════════════════
    # FUTURE / ADD-ON DEVICES — not in starter kit, but wizard
    # supports adding them later
    # ════════════════════════════════════════════════════════════════

    'smoke': {
        'category': 'sensor',
        'starter_kit': False,
        'pairing_order': 100,
        'label': 'Detektor kouře',
        'icon': '🔥',
        'tagline': 'Bezpečí v noci',
        'description': (
            'Kruhový detektor na strop kuchyně nebo chodby. Při kouři Radim '
            'okamžitě volá 150, otevře dveře pro hasiče a upozorní rodinu. '
            'Doporučujeme přidat brzy.'
        ),
        'manufacturer_hints': ['Tapo S200B (přes Hub)', 'Heiman HS3SA (Zigbee)'],
        'protocol': 'wifi_via_hub',
        'pairing': {
            'method': PAIR_TAPO_HUB_SUBDEVICE,
            'duration_seconds': 60,
            'instructions': 'V aplikaci Tapo přidejte detektor k Hubu.',
            'visual_hint': '',
            'requires_fields': [],
        },
        'requires_device': 'tapo_hub',
        'default_role': 'smoke',
        'default_device_class': 'smoke',
        'ha_domain': 'binary_sensor',
        'detected_signals': ['smoke'],
        'auto_actions': {
            'on_trigger': ['call_150', 'unlock_doors', 'lights_on', 'family_sms'],
            'severity': 'CRISIS',
        },
    },

    'temperature': {
        'category': 'sensor',
        'starter_kit': False,
        'pairing_order': 101,
        'label': 'Teplota a vlhkost',
        'icon': '🌡️',
        'tagline': 'Aby bylo doma teplo',
        'description': (
            'Senzor s LCD displejem. Radim hlídá, aby teplota neklesla pod '
            '18 °C ani nestoupla nad 28 °C — staří lidé to tělem často '
            'nepoznají.'
        ),
        'manufacturer_hints': ['Tapo T315 (přes Hub)', 'Aqara WSDCGQ11LM'],
        'protocol': 'wifi_via_hub',
        'pairing': {
            'method': PAIR_TAPO_HUB_SUBDEVICE,
            'duration_seconds': 60,
            'instructions': 'V aplikaci Tapo přidejte senzor k Hubu.',
            'visual_hint': '',
            'requires_fields': [],
        },
        'requires_device': 'tapo_hub',
        'default_role': 'climate',
        'default_device_class': 'temperature',
        'ha_domain': 'sensor',
        'detected_signals': ['temperature', 'humidity', 'battery'],
        'auto_actions': {'min_temp_alert': 18, 'max_temp_alert': 28},
    },

    'sos_button': {
        'category': 'safety',
        'starter_kit': False,
        'pairing_order': 102,
        'label': 'SOS knoflík',
        'icon': '🆘',
        'tagline': 'Pomoc jedním stiskem',
        'description': (
            'Kulatý knoflík na zdi nebo v kapse. 1× = tichý poplach, 3× = '
            'volá rodině, dlouhý stisk = volá 155.'
        ),
        'manufacturer_hints': ['Tapo S200B (přes Hub)', 'Aqara WXKG11LM (Zigbee)'],
        'protocol': 'wifi_via_hub',
        'pairing': {
            'method': PAIR_TAPO_HUB_SUBDEVICE,
            'duration_seconds': 60,
            'instructions': 'V aplikaci Tapo přidejte tlačítko k Hubu.',
            'visual_hint': '',
            'requires_fields': [],
        },
        'requires_device': 'tapo_hub',
        'default_role': 'sos_button',
        'default_device_class': None,
        'ha_domain': 'sensor',
        'detected_signals': ['action', 'click', 'long_press'],
        'auto_actions': {
            'single_click': ['silent_alert'],
            'triple_click': ['call_family'],
            'long_press': ['crisis_protocol', 'call_155'],
        },
    },

    'wearable': {
        'category': 'health',
        'starter_kit': False,
        'pairing_order': 103,
        'label': 'Náramek / hodinky',
        'icon': '⌚',
        'tagline': 'Tep, kroky, pád',
        'description': (
            'Náramek nebo hodinky, které měří tep a kroky. Withings, Fitbit, '
            'Garmin a kompatibilní. Radim včas upozorní na arytmii nebo pád.'
        ),
        'manufacturer_hints': ['Withings BPM Core', 'Fitbit Charge', 'Garmin Vivo'],
        'protocol': 'oauth_cloud',
        'pairing': {
            'method': PAIR_WITHINGS_OAUTH,
            'duration_seconds': 180,
            'instructions': (
                'Otevře se přihlášení do Withings — přihlaste se účtem '
                'seniora a povolte přístup. Radim pak začne číst data.'
            ),
            'visual_hint': '',
            'requires_fields': [],
        },
        'default_role': 'wearable',
        'default_device_class': None,
        'ha_domain': 'sensor',
        'detected_signals': ['heart_rate', 'spo2', 'blood_pressure_sys',
                             'blood_pressure_dia', 'steps', 'fall'],
        'auto_actions': {
            'heart_rate_critical_high': 120,
            'heart_rate_critical_low': 50,
            'spo2_alert': 90,
            'fall_detection': True,
        },
    },

    'mini_pc': {
        'category': 'infrastructure',
        'starter_kit': False,
        'pairing_order': 104,
        'label': 'Mini PC (Home Assistant OS)',
        'icon': '🖥️',
        'tagline': 'Hlavní server domácnosti',
        'description': (
            'Lenovo TinyPC nebo Intel NUC s Home Assistant OS. Hostuje HA, '
            'integrace, automatizace. Radim se s ním propojí přes long-lived '
            'token. Volitelné — Tapo Hub umí fungovat i bez HA.'
        ),
        'manufacturer_hints': ['Lenovo ThinkCentre M75q', 'Intel NUC 11/12',
                                'Beelink Mini S'],
        'protocol': 'ha_rest',
        'pairing': {
            'method': PAIR_MANUAL,
            'duration_seconds': 0,
            'instructions': (
                'Technik nainstaluje HAOS na mini PC. Po instalaci zadáte '
                'URL (např. http://192.168.1.100:8123) a long-lived token.'
            ),
            'visual_hint': 'HAOS image: github.com/home-assistant/operating-system',
            'requires_fields': ['ha_url', 'ha_token'],
        },
        'default_role': 'ha_server',
        'ha_domain': None,
        'detected_signals': [],
        'auto_actions': {},
        'aliases_to_existing_flow': '/api/ha/config',
    },
}


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def get_device(device_type: str) -> dict | None:
    """Lookup catalog entry. Returns None if unknown."""
    return DEVICE_CATALOG.get(device_type)


def list_for_wizard(starter_kit_only: bool = False) -> list[dict]:
    """Public list returned to the frontend wizard. Excludes Python-only fields.

    starter_kit_only: if True, returns just the 6 actually-purchased devices,
    sorted by pairing_order (Hub first, then plugs, sensors, bulb, speaker).
    """
    out = []
    for key, entry in DEVICE_CATALOG.items():
        if starter_kit_only and not entry.get('starter_kit'):
            continue
        out.append({
            'type': key,
            'category': entry['category'],
            'label': entry['label'],
            'icon': entry['icon'],
            'tagline': entry['tagline'],
            'description': entry['description'],
            'manufacturer_hints': entry.get('manufacturer_hints', []),
            'protocol': entry['protocol'],
            'pairing_method': entry['pairing']['method'],
            'pairing_duration_seconds': entry['pairing']['duration_seconds'],
            'pairing_instructions': entry['pairing']['instructions'],
            'pairing_visual_hint': entry['pairing'].get('visual_hint', ''),
            'pairing_requires_fields': entry['pairing'].get('requires_fields', []),
            'ha_domain': entry.get('ha_domain'),
            'aliases_to_existing_flow': entry.get('aliases_to_existing_flow'),
            'starter_kit': bool(entry.get('starter_kit')),
            'pairing_order': entry.get('pairing_order', 999),
            'requires_device': entry.get('requires_device'),
        })
    # Sort: starter kit first by pairing_order, then alphabetically
    out.sort(key=lambda d: (not d['starter_kit'], d['pairing_order'], d['label']))
    return out


def is_zigbee(device_type: str) -> bool:
    entry = get_device(device_type)
    return bool(entry and entry['pairing']['method'] == PAIR_ZIGBEE_PERMIT_JOIN)


def is_tplink_device(device_type: str) -> bool:
    """True for devices that go through HA's tplink integration."""
    entry = get_device(device_type)
    if not entry:
        return False
    method = entry['pairing']['method']
    return method in (PAIR_TPLINK_DISCOVERY, PAIR_TAPO_HUB_SUBDEVICE)


def is_critical_safety_device(device_type: str) -> bool:
    """Returns True for devices whose triggers require crisis protocol."""
    entry = get_device(device_type)
    if not entry:
        return False
    severity = (entry.get('auto_actions') or {}).get('severity')
    return severity == 'CRISIS'


def get_starter_kit_order() -> list[str]:
    """Returns device_type IDs of the 6 starter kit items in correct order
    (Hub first, then plugs, sensors, bulb, speaker)."""
    starter = [(k, v.get('pairing_order', 999))
               for k, v in DEVICE_CATALOG.items() if v.get('starter_kit')]
    starter.sort(key=lambda x: x[1])
    return [k for k, _ in starter]
