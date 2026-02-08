# ============================================
# 🌡️ RADIM IoT & SENSORS API BLUEPRINT
# ============================================
# Version: 1.0.0
# IoT senzory a vitální znaky pro smart rooms
# Endpoints: /api/iot/system/status, /api/iot/sensors/<id>/vitals

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import random
import math

iot_bp = Blueprint('iot', __name__)


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def hours_ago(h):
    return (datetime.utcnow() - timedelta(hours=h)).isoformat() + 'Z'


def minutes_ago(m):
    return (datetime.utcnow() - timedelta(minutes=m)).isoformat() + 'Z'


# ============================================
# GOLDEN RATIO SENSOR SIMULATION
# ============================================
PHI = 1.618033988749895

def phi_oscillation(base, amplitude, phase=0):
    """Generuje hodnotu oscilující kolem base s amplitudou řízenou φ"""
    t = datetime.utcnow().timestamp()
    # Fibonacci-inspired frequency
    freq = 1.0 / (PHI * 3600)  # cyklus řízený φ
    value = base + amplitude * math.sin(2 * math.pi * freq * t + phase)
    # Přidáme malý šum
    noise = random.gauss(0, amplitude * 0.05)
    return round(value + noise, 1)


# ============================================
# SENSOR DEFINITIONS PER ROOM
# ============================================

ROOM_SENSORS = {
    "senior-001": {  # Marie Novotná, A-12
        "room": "A-12",
        "sensors": {
            "temperature": {"id": "temp-A12", "type": "temperature", "unit": "°C", "min": 18, "max": 26, "optimal": 22},
            "humidity": {"id": "hum-A12", "type": "humidity", "unit": "%", "min": 30, "max": 60, "optimal": 45},
            "motion": {"id": "mot-A12", "type": "motion", "unit": "events/h", "min": 0, "max": 50},
            "light": {"id": "lux-A12", "type": "light", "unit": "lux", "min": 0, "max": 500},
            "door": {"id": "door-A12", "type": "door_contact", "states": ["open", "closed"]}
        }
    },
    "senior-002": {  # Josef Dvořák, A-15
        "room": "A-15",
        "sensors": {
            "temperature": {"id": "temp-A15", "type": "temperature", "unit": "°C", "min": 18, "max": 26, "optimal": 22},
            "humidity": {"id": "hum-A15", "type": "humidity", "unit": "%", "min": 30, "max": 60, "optimal": 45},
            "motion": {"id": "mot-A15", "type": "motion", "unit": "events/h", "min": 0, "max": 50},
            "light": {"id": "lux-A15", "type": "light", "unit": "lux", "min": 0, "max": 500},
            "door": {"id": "door-A15", "type": "door_contact", "states": ["open", "closed"]},
            "bed_pressure": {"id": "bed-A15", "type": "bed_pressure", "states": ["occupied", "empty", "restless"]},
            "fall_detection": {"id": "fall-A15", "type": "fall_detection", "states": ["normal", "alert", "confirmed_fall"]}
        }
    },
    "senior-003": {  # Božena Černá, B-03
        "room": "B-03",
        "sensors": {
            "temperature": {"id": "temp-B03", "type": "temperature", "unit": "°C", "min": 18, "max": 26, "optimal": 22},
            "humidity": {"id": "hum-B03", "type": "humidity", "unit": "%", "min": 30, "max": 60, "optimal": 45},
            "motion": {"id": "mot-B03", "type": "motion", "unit": "events/h", "min": 0, "max": 50},
            "light": {"id": "lux-B03", "type": "light", "unit": "lux", "min": 0, "max": 500}
        }
    },
    "senior-004": {  # František Procházka, B-07
        "room": "B-07",
        "sensors": {
            "temperature": {"id": "temp-B07", "type": "temperature", "unit": "°C", "min": 18, "max": 26, "optimal": 22},
            "humidity": {"id": "hum-B07", "type": "humidity", "unit": "%", "min": 30, "max": 60, "optimal": 45},
            "motion": {"id": "mot-B07", "type": "motion", "unit": "events/h", "min": 0, "max": 50},
            "light": {"id": "lux-B07", "type": "light", "unit": "lux", "min": 0, "max": 500},
            "door": {"id": "door-B07", "type": "door_contact", "states": ["open", "closed"]},
            "bed_pressure": {"id": "bed-B07", "type": "bed_pressure", "states": ["occupied", "empty", "restless"]},
            "fall_detection": {"id": "fall-B07", "type": "fall_detection", "states": ["normal", "alert", "confirmed_fall"]},
            "wandering_alert": {"id": "wander-B07", "type": "wandering", "states": ["normal", "unusual_movement", "left_zone"]}
        }
    },
    "senior-005": {  # Vlasta Horáková, C-01
        "room": "C-01",
        "sensors": {
            "temperature": {"id": "temp-C01", "type": "temperature", "unit": "°C", "min": 18, "max": 26, "optimal": 22},
            "humidity": {"id": "hum-C01", "type": "humidity", "unit": "%", "min": 30, "max": 60, "optimal": 45},
            "motion": {"id": "mot-C01", "type": "motion", "unit": "events/h", "min": 0, "max": 50},
            "light": {"id": "lux-C01", "type": "light", "unit": "lux", "min": 0, "max": 500},
            "mood_lamp": {"id": "mood-C01", "type": "mood_lamp", "states": ["off", "warm", "energizing", "calming"]}
        }
    }
}


def generate_vitals(senior_id):
    """Generuje realistické vitální znaky pro seniora"""
    # Různé baseline podle seniora
    profiles = {
        "senior-001": {"hr": 72, "bp_sys": 138, "bp_dia": 82, "spo2": 96, "temp": 36.5, "glucose": 7.8, "weight": 68},
        "senior-002": {"hr": 68, "bp_sys": 145, "bp_dia": 88, "spo2": 95, "temp": 36.4, "glucose": 5.2, "weight": 82},
        "senior-003": {"hr": 74, "bp_sys": 125, "bp_dia": 78, "spo2": 97, "temp": 36.6, "glucose": 5.0, "weight": 62},
        "senior-004": {"hr": 78, "bp_sys": 150, "bp_dia": 90, "spo2": 94, "temp": 36.3, "glucose": 5.5, "weight": 75},
        "senior-005": {"hr": 70, "bp_sys": 120, "bp_dia": 75, "spo2": 97, "temp": 36.5, "glucose": 4.8, "weight": 65}
    }

    p = profiles.get(senior_id, profiles["senior-001"])
    phase = hash(senior_id) % 100  # Unique phase per senior

    return {
        "heart_rate": {
            "value": round(phi_oscillation(p["hr"], 5, phase)),
            "unit": "bpm",
            "status": "normal",
            "measured_at": minutes_ago(random.randint(5, 30))
        },
        "blood_pressure": {
            "systolic": round(phi_oscillation(p["bp_sys"], 8, phase + 1)),
            "diastolic": round(phi_oscillation(p["bp_dia"], 5, phase + 2)),
            "unit": "mmHg",
            "status": "elevated" if p["bp_sys"] > 140 else "normal",
            "measured_at": minutes_ago(random.randint(30, 120))
        },
        "oxygen_saturation": {
            "value": min(100, round(phi_oscillation(p["spo2"], 1, phase + 3))),
            "unit": "%",
            "status": "normal" if p["spo2"] >= 95 else "low",
            "measured_at": minutes_ago(random.randint(5, 60))
        },
        "body_temperature": {
            "value": round(phi_oscillation(p["temp"], 0.3, phase + 4), 1),
            "unit": "°C",
            "status": "normal",
            "measured_at": minutes_ago(random.randint(60, 240))
        },
        "blood_glucose": {
            "value": round(phi_oscillation(p["glucose"], 1.5, phase + 5), 1),
            "unit": "mmol/L",
            "status": "elevated" if p["glucose"] > 7.0 else "normal",
            "measured_at": minutes_ago(random.randint(120, 480))
        },
        "weight": {
            "value": round(phi_oscillation(p["weight"], 0.5, phase + 6), 1),
            "unit": "kg",
            "trend": "stable",
            "measured_at": hours_ago(random.randint(12, 48))
        },
        "sleep_quality": {
            "last_night_hours": round(phi_oscillation(7.0, 1.5, phase + 7), 1),
            "deep_sleep_pct": round(phi_oscillation(20, 5, phase + 8)),
            "interruptions": random.randint(0, 4),
            "status": "good" if random.random() > 0.3 else "fair"
        },
        "activity": {
            "steps_today": random.randint(500, 5000),
            "active_minutes": random.randint(10, 120),
            "calories_burned": random.randint(800, 1800),
            "status": "active" if random.random() > 0.4 else "sedentary"
        }
    }


def generate_room_readings(senior_id):
    """Generuje aktuální senzorová data pokoje"""
    config = ROOM_SENSORS.get(senior_id)
    if not config:
        return None

    readings = {}
    hour = datetime.utcnow().hour

    for name, sensor in config["sensors"].items():
        if sensor["type"] == "temperature":
            readings[name] = {
                "sensor_id": sensor["id"],
                "value": phi_oscillation(sensor["optimal"], 2),
                "unit": sensor["unit"],
                "status": "normal",
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "humidity":
            readings[name] = {
                "sensor_id": sensor["id"],
                "value": phi_oscillation(sensor["optimal"], 8),
                "unit": sensor["unit"],
                "status": "normal",
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "motion":
            # Méně pohybu v noci
            base = 5 if 22 <= hour or hour < 6 else 20
            readings[name] = {
                "sensor_id": sensor["id"],
                "value": max(0, round(phi_oscillation(base, 8))),
                "unit": sensor["unit"],
                "timestamp": minutes_ago(5)
            }
        elif sensor["type"] == "light":
            # Světlo podle denní doby
            base = 10 if 22 <= hour or hour < 6 else 300
            readings[name] = {
                "sensor_id": sensor["id"],
                "value": max(0, round(phi_oscillation(base, 50))),
                "unit": sensor["unit"],
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "door_contact":
            readings[name] = {
                "sensor_id": sensor["id"],
                "state": random.choice(sensor["states"]),
                "last_change": minutes_ago(random.randint(5, 120)),
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "bed_pressure":
            # V noci spíše occupied
            if 22 <= hour or hour < 6:
                state = random.choices(["occupied", "restless", "empty"], weights=[70, 20, 10])[0]
            else:
                state = random.choices(["empty", "occupied", "restless"], weights=[60, 30, 10])[0]
            readings[name] = {
                "sensor_id": sensor["id"],
                "state": state,
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "fall_detection":
            readings[name] = {
                "sensor_id": sensor["id"],
                "state": "normal",  # Většinou normální
                "last_alert": None,
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "wandering":
            readings[name] = {
                "sensor_id": sensor["id"],
                "state": "normal",
                "zone": "room",
                "timestamp": minutes_ago(1)
            }
        elif sensor["type"] == "mood_lamp":
            if 22 <= hour or hour < 6:
                state = "off"
            elif 6 <= hour < 10:
                state = "energizing"
            elif 18 <= hour < 22:
                state = "calming"
            else:
                state = "warm"
            readings[name] = {
                "sensor_id": sensor["id"],
                "state": state,
                "timestamp": minutes_ago(1)
            }

    return readings


# ============================================
# ENDPOINTS
# ============================================

@iot_bp.route('/api/iot/system/status', methods=['GET'])
def iot_system_status():
    """Celkový stav IoT systému"""
    total_sensors = sum(len(r["sensors"]) for r in ROOM_SENSORS.values())
    rooms_online = len(ROOM_SENSORS)

    # Simulace stavu systému
    alerts = []
    if random.random() < 0.1:  # 10% šance na alert
        alerts.append({
            "type": "sensor_offline",
            "sensor_id": "hum-B07",
            "room": "B-07",
            "message": "Senzor vlhkosti nereaguje",
            "severity": "warning",
            "since": minutes_ago(15)
        })

    return jsonify({
        "success": True,
        "system": {
            "status": "operational" if not alerts else "degraded",
            "version": "1.0.0",
            "facility": "Dům seniorů Háje",
            "gateway": {
                "status": "online",
                "protocol": "MQTT + Zigbee",
                "uptime_hours": round(phi_oscillation(720, 100)),
                "last_heartbeat": minutes_ago(1)
            },
            "network": {
                "protocol": "LoRaWAN + WiFi",
                "signal_strength": "strong",
                "latency_ms": round(phi_oscillation(15, 5))
            }
        },
        "rooms": {
            "total": rooms_online,
            "online": rooms_online,
            "offline": 0,
            "rooms": [
                {
                    "room": config["room"],
                    "senior_id": sid,
                    "sensors_count": len(config["sensors"]),
                    "status": "online"
                }
                for sid, config in ROOM_SENSORS.items()
            ]
        },
        "sensors": {
            "total": total_sensors,
            "online": total_sensors - len(alerts),
            "offline": len(alerts),
            "types": {
                "environmental": sum(1 for r in ROOM_SENSORS.values()
                    for s in r["sensors"].values() if s["type"] in ["temperature", "humidity", "light"]),
                "safety": sum(1 for r in ROOM_SENSORS.values()
                    for s in r["sensors"].values() if s["type"] in ["fall_detection", "door_contact", "wandering"]),
                "comfort": sum(1 for r in ROOM_SENSORS.values()
                    for s in r["sensors"].values() if s["type"] in ["bed_pressure", "motion", "mood_lamp"])
            }
        },
        "alerts": alerts,
        "phi_calibration": {
            "enabled": True,
            "ratio": PHI,
            "description": "Senzorové intervaly a prahy kalibrovány pomocí zlatého řezu"
        },
        "timestamp": now_iso()
    })


@iot_bp.route('/api/iot/sensors/<senior_id>/vitals', methods=['GET'])
def get_vitals(senior_id):
    """Vitální znaky a senzorová data pro konkrétního seniora"""
    if senior_id not in ROOM_SENSORS:
        return jsonify({
            "success": False,
            "error": f"Senior {senior_id} nemá nakonfigurované senzory",
            "available_ids": list(ROOM_SENSORS.keys())
        }), 404

    config = ROOM_SENSORS[senior_id]
    vitals = generate_vitals(senior_id)
    room_readings = generate_room_readings(senior_id)

    # Vyhodnocení celkového stavu
    warnings = []
    if vitals["blood_pressure"]["systolic"] > 150:
        warnings.append({"type": "high_blood_pressure", "severity": "warning",
                         "message": f"Systolický tlak {vitals['blood_pressure']['systolic']} mmHg"})
    if vitals["oxygen_saturation"]["value"] < 93:
        warnings.append({"type": "low_spo2", "severity": "critical",
                         "message": f"SpO2 {vitals['oxygen_saturation']['value']}%"})
    if vitals["blood_glucose"]["value"] > 10:
        warnings.append({"type": "high_glucose", "severity": "warning",
                         "message": f"Glykémie {vitals['blood_glucose']['value']} mmol/L"})
    if vitals["heart_rate"]["value"] > 100 or vitals["heart_rate"]["value"] < 50:
        warnings.append({"type": "abnormal_hr", "severity": "warning",
                         "message": f"Tepová frekvence {vitals['heart_rate']['value']} bpm"})

    overall = "good"
    if any(w["severity"] == "critical" for w in warnings):
        overall = "critical"
    elif warnings:
        overall = "attention"

    return jsonify({
        "success": True,
        "senior_id": senior_id,
        "room": config["room"],
        "overall_status": overall,
        "vitals": vitals,
        "room_environment": room_readings,
        "warnings": warnings,
        "warnings_count": len(warnings),
        "sensors_active": len(config["sensors"]),
        "phi_note": "Vitální hodnoty oscilují podle Fibonacci vzorců (φ = 1.618)",
        "timestamp": now_iso()
    })


@iot_bp.route('/api/iot/sensors/<senior_id>/history', methods=['GET'])
def get_vitals_history(senior_id):
    """Historie vitálních znaků za posledních 24h"""
    if senior_id not in ROOM_SENSORS:
        return jsonify({"success": False, "error": f"Senior {senior_id} nenalezen"}), 404

    hours = request.args.get('hours', 24, type=int)
    hours = min(hours, 168)  # Max 7 dní

    # Generuj historická data
    history = []
    for h in range(hours):
        ts = (datetime.utcnow() - timedelta(hours=h)).isoformat() + 'Z'
        phase = hash(senior_id) % 100
        history.append({
            "timestamp": ts,
            "heart_rate": round(phi_oscillation(72, 5, phase + h * 0.1)),
            "blood_pressure_sys": round(phi_oscillation(135, 10, phase + h * 0.15)),
            "blood_pressure_dia": round(phi_oscillation(82, 6, phase + h * 0.12)),
            "spo2": min(100, round(phi_oscillation(96, 1.5, phase + h * 0.08))),
            "temperature": round(phi_oscillation(22, 2, phase + h * 0.05), 1),
            "humidity": round(phi_oscillation(45, 8, phase + h * 0.07), 1)
        })

    return jsonify({
        "success": True,
        "senior_id": senior_id,
        "period_hours": hours,
        "data_points": len(history),
        "history": history,
        "timestamp": now_iso()
    })
