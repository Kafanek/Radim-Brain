# ============================================
# 👴 RADIM SENIORS API BLUEPRINT
# ============================================
# Version: 1.0.0
# Správa seniorů v systému Radim Brain
# Endpoints: /api/seniors, /api/seniors/<id>

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
import random
import uuid

seniors_bp = Blueprint('seniors', __name__)

# ============================================
# IN-MEMORY DATA (nahradit DB v produkci)
# ============================================

DEMO_SENIORS = {
    "senior-001": {
        "id": "senior-001",
        "name": "Marie Novotná",
        "age": 78,
        "room": "A-12",
        "floor": 1,
        "facility": "Dům seniorů Háje",
        "status": "active",
        "care_level": 2,
        "diagnoses": ["hypertenze", "diabetes mellitus 2. typu"],
        "medications": [
            {"name": "Metformin", "dose": "500mg", "frequency": "2x denně"},
            {"name": "Lisinopril", "dose": "10mg", "frequency": "1x ráno"}
        ],
        "emergency_contact": {"name": "Jana Novotná", "relation": "dcera", "phone": "+420 777 123 456"},
        "preferences": {
            "wake_time": "06:30",
            "sleep_time": "21:00",
            "coffee_preference": "Kafánek Classic s mlékem",
            "activity_level": "střední",
            "communication_style": "klidný, laskavý"
        },
        "smart_room": {
            "enabled": True,
            "sensors": ["temperature", "humidity", "motion", "light", "door"],
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": "2025-09-15T08:00:00Z",
        "updated_at": None
    },
    "senior-002": {
        "id": "senior-002",
        "name": "Josef Dvořák",
        "age": 82,
        "room": "A-15",
        "floor": 1,
        "facility": "Dům seniorů Háje",
        "status": "active",
        "care_level": 3,
        "diagnoses": ["ischemická choroba srdeční", "artróza kolen", "mírná kognitivní porucha"],
        "medications": [
            {"name": "Atorvastatin", "dose": "20mg", "frequency": "1x večer"},
            {"name": "Aspirin", "dose": "100mg", "frequency": "1x ráno"},
            {"name": "Ibuprofen", "dose": "400mg", "frequency": "dle potřeby"}
        ],
        "emergency_contact": {"name": "Petr Dvořák", "relation": "syn", "phone": "+420 602 987 654"},
        "preferences": {
            "wake_time": "07:00",
            "sleep_time": "20:30",
            "coffee_preference": "Kafánek Espresso bez cukru",
            "activity_level": "nízký",
            "communication_style": "přímý, stručný"
        },
        "smart_room": {
            "enabled": True,
            "sensors": ["temperature", "humidity", "motion", "light", "door", "bed_pressure", "fall_detection"],
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": "2025-10-01T10:00:00Z",
        "updated_at": None
    },
    "senior-003": {
        "id": "senior-003",
        "name": "Božena Černá",
        "age": 75,
        "room": "B-03",
        "floor": 2,
        "facility": "Dům seniorů Háje",
        "status": "active",
        "care_level": 1,
        "diagnoses": ["osteoporóza"],
        "medications": [
            {"name": "Vitamin D", "dose": "1000IU", "frequency": "1x denně"},
            {"name": "Calcium", "dose": "500mg", "frequency": "2x denně"}
        ],
        "emergency_contact": {"name": "Lucie Veselá", "relation": "vnučka", "phone": "+420 731 555 888"},
        "preferences": {
            "wake_time": "06:00",
            "sleep_time": "21:30",
            "coffee_preference": "Kafánek Cappuccino",
            "activity_level": "vysoký",
            "communication_style": "veselý, společenský"
        },
        "smart_room": {
            "enabled": True,
            "sensors": ["temperature", "humidity", "motion", "light"],
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": "2025-11-10T14:00:00Z",
        "updated_at": None
    },
    "senior-004": {
        "id": "senior-004",
        "name": "František Procházka",
        "age": 88,
        "room": "B-07",
        "floor": 2,
        "facility": "Dům seniorů Háje",
        "status": "active",
        "care_level": 4,
        "diagnoses": ["Alzheimerova choroba - počáteční stádium", "fibrilace síní", "chronická renální insuficience"],
        "medications": [
            {"name": "Donepezil", "dose": "10mg", "frequency": "1x večer"},
            {"name": "Warfarin", "dose": "5mg", "frequency": "1x denně - kontrola INR"},
            {"name": "Furosemid", "dose": "40mg", "frequency": "1x ráno"}
        ],
        "emergency_contact": {"name": "Eva Procházková", "relation": "manželka", "phone": "+420 608 111 222"},
        "preferences": {
            "wake_time": "07:30",
            "sleep_time": "20:00",
            "coffee_preference": "Kafánek Decaf s medem",
            "activity_level": "velmi nízký",
            "communication_style": "trpělivý, opakovat informace"
        },
        "smart_room": {
            "enabled": True,
            "sensors": ["temperature", "humidity", "motion", "light", "door", "bed_pressure", "fall_detection", "wandering_alert"],
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": "2025-08-20T09:00:00Z",
        "updated_at": None
    },
    "senior-005": {
        "id": "senior-005",
        "name": "Vlasta Horáková",
        "age": 71,
        "room": "C-01",
        "floor": 3,
        "facility": "Dům seniorů Háje",
        "status": "active",
        "care_level": 1,
        "diagnoses": ["lehká deprese", "hypothyreóza"],
        "medications": [
            {"name": "Levothyroxin", "dose": "50mcg", "frequency": "1x ráno nalačno"},
            {"name": "Sertralin", "dose": "50mg", "frequency": "1x ráno"}
        ],
        "emergency_contact": {"name": "Martin Horák", "relation": "syn", "phone": "+420 775 333 444"},
        "preferences": {
            "wake_time": "08:00",
            "sleep_time": "22:00",
            "coffee_preference": "Kafánek Latte",
            "activity_level": "střední",
            "communication_style": "empatický, pozitivní"
        },
        "smart_room": {
            "enabled": True,
            "sensors": ["temperature", "humidity", "motion", "light", "mood_lamp"],
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": "2025-12-01T11:00:00Z",
        "updated_at": None
    }
}


def now_iso():
    return datetime.utcnow().isoformat() + 'Z'


def update_last_interaction(senior_id):
    """Aktualizuje čas poslední interakce"""
    if senior_id in DEMO_SENIORS:
        DEMO_SENIORS[senior_id]["smart_room"]["last_interaction"] = now_iso()
        DEMO_SENIORS[senior_id]["updated_at"] = now_iso()


# ============================================
# ENDPOINTS
# ============================================

@seniors_bp.route('/api/seniors', methods=['GET'])
def list_seniors():
    """Seznam všech seniorů"""
    status_filter = request.args.get('status', None)
    care_level = request.args.get('care_level', None, type=int)
    floor = request.args.get('floor', None, type=int)
    facility = request.args.get('facility', None)

    seniors = list(DEMO_SENIORS.values())

    if status_filter:
        seniors = [s for s in seniors if s["status"] == status_filter]
    if care_level is not None:
        seniors = [s for s in seniors if s["care_level"] == care_level]
    if floor is not None:
        seniors = [s for s in seniors if s["floor"] == floor]
    if facility:
        seniors = [s for s in seniors if facility.lower() in s["facility"].lower()]

    # Compact view (bez medications a diagnoses)
    compact = []
    for s in seniors:
        compact.append({
            "id": s["id"],
            "name": s["name"],
            "age": s["age"],
            "room": s["room"],
            "floor": s["floor"],
            "facility": s["facility"],
            "status": s["status"],
            "care_level": s["care_level"],
            "smart_room_enabled": s["smart_room"]["enabled"],
            "sensor_count": len(s["smart_room"]["sensors"]),
            "diagnoses_count": len(s["diagnoses"])
        })

    return jsonify({
        "success": True,
        "count": len(compact),
        "seniors": compact,
        "filters_applied": {
            "status": status_filter,
            "care_level": care_level,
            "floor": floor,
            "facility": facility
        },
        "facility_summary": {
            "name": "Dům seniorů Háje",
            "total_residents": len(DEMO_SENIORS),
            "active": sum(1 for s in DEMO_SENIORS.values() if s["status"] == "active"),
            "avg_age": round(sum(s["age"] for s in DEMO_SENIORS.values()) / len(DEMO_SENIORS), 1),
            "avg_care_level": round(sum(s["care_level"] for s in DEMO_SENIORS.values()) / len(DEMO_SENIORS), 1),
            "smart_rooms": sum(1 for s in DEMO_SENIORS.values() if s["smart_room"]["enabled"])
        },
        "timestamp": now_iso()
    })


@seniors_bp.route('/api/seniors/<senior_id>', methods=['GET'])
def get_senior(senior_id):
    """Detail jednoho seniora"""
    senior = DEMO_SENIORS.get(senior_id)
    if not senior:
        return jsonify({
            "success": False,
            "error": f"Senior {senior_id} nenalezen",
            "available_ids": list(DEMO_SENIORS.keys())
        }), 404

    update_last_interaction(senior_id)

    return jsonify({
        "success": True,
        "senior": senior,
        "timestamp": now_iso()
    })


@seniors_bp.route('/api/seniors', methods=['POST'])
def create_senior():
    """Vytvoření nového seniora"""
    data = request.json or {}
    required = ['name', 'age', 'room']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"success": False, "error": f"Chybí povinná pole: {', '.join(missing)}"}), 400

    senior_id = f"senior-{str(uuid.uuid4())[:8]}"
    new_senior = {
        "id": senior_id,
        "name": data["name"],
        "age": data["age"],
        "room": data["room"],
        "floor": data.get("floor", 1),
        "facility": data.get("facility", "Dům seniorů Háje"),
        "status": "active",
        "care_level": data.get("care_level", 1),
        "diagnoses": data.get("diagnoses", []),
        "medications": data.get("medications", []),
        "emergency_contact": data.get("emergency_contact", {}),
        "preferences": data.get("preferences", {
            "wake_time": "07:00",
            "sleep_time": "21:00",
            "coffee_preference": "Kafánek Classic",
            "activity_level": "střední",
            "communication_style": "přátelský"
        }),
        "smart_room": {
            "enabled": True,
            "sensors": data.get("sensors", ["temperature", "humidity", "motion", "light"]),
            "voice_assistant": True,
            "last_interaction": None
        },
        "created_at": now_iso(),
        "updated_at": None
    }

    DEMO_SENIORS[senior_id] = new_senior

    return jsonify({
        "success": True,
        "message": f"Senior {data['name']} vytvořen",
        "senior": new_senior,
        "timestamp": now_iso()
    }), 201


@seniors_bp.route('/api/seniors/<senior_id>', methods=['PUT'])
def update_senior(senior_id):
    """Aktualizace seniora"""
    if senior_id not in DEMO_SENIORS:
        return jsonify({"success": False, "error": f"Senior {senior_id} nenalezen"}), 404

    data = request.json or {}
    senior = DEMO_SENIORS[senior_id]

    updatable = ['name', 'age', 'room', 'floor', 'status', 'care_level',
                 'diagnoses', 'medications', 'emergency_contact', 'preferences']
    updated_fields = []
    for field in updatable:
        if field in data:
            senior[field] = data[field]
            updated_fields.append(field)

    senior["updated_at"] = now_iso()

    return jsonify({
        "success": True,
        "message": f"Senior {senior_id} aktualizován",
        "updated_fields": updated_fields,
        "senior": senior,
        "timestamp": now_iso()
    })
