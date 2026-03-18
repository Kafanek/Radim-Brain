"""
Seed Demo Data v1.0
====================
Creates a demo senior user with profile, brain_states, and memory_learning
so the agent loop has real data to work with.

Usage:
  POST /api/admin/seed-demo (requires admin auth or dev mode)
  python3 seed_demo.py  (standalone, uses DATABASE_URL)
"""

import json
import logging
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DEMO_SENIOR = {
    "user_id": "demo_senior_1",
    "name": "Marie Novakova",
    "age_group": "75+",
    "hearing": "mild_loss",
    "vision": "normal",
    "memory_support": True,
    "communication_needs": "mild_dementia",
    "caregiver_id": "demo_caregiver_1",
    "medications_list": ["Donepezil 10mg", "Metformin 500mg", "Enalapril 5mg"],
    "medication_times": {
        "rano": ["Donepezil 10mg", "Metformin 500mg"],
        "vecer": ["Enalapril 5mg"]
    },
    "emergency_contacts": [
        {"name": "Jan Novak", "phone": "+420123456789", "relation": "syn"}
    ],
    "daily_routine_notes": "Vstavani 7:00, snidane 7:30, prochazka 10:00, obed 12:00, odpoledni spanek 14:00-15:00"
}


def seed_demo_data():
    """Create demo senior with realistic historical data."""
    from database import db_context, is_postgres

    user_id = DEMO_SENIOR["user_id"]
    now = datetime.utcnow()

    # 1. Create user in chat_users
    with db_context(commit=True) as db:
        if is_postgres():
            db.execute("""
                INSERT INTO chat_users (id, name, role, online, settings)
                VALUES (?, ?, 'senior', 0, '{}')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """, (user_id, DEMO_SENIOR["name"]))

            db.execute("""
                INSERT INTO chat_users (id, name, role, online, settings)
                VALUES (?, ?, 'caregiver', 0, '{}')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """, (DEMO_SENIOR["caregiver_id"], "Jan Novak"))
        else:
            db.execute("""
                INSERT OR REPLACE INTO chat_users (id, name, role, online, settings)
                VALUES (?, ?, 'senior', 0, '{}')
            """, (user_id, DEMO_SENIOR["name"]))

            db.execute("""
                INSERT OR REPLACE INTO chat_users (id, name, role, online, settings)
                VALUES (?, ?, 'caregiver', 0, '{}')
            """, (DEMO_SENIOR["caregiver_id"], "Jan Novak"))

    logger.info(f"Seed: chat_users created for {user_id}")

    # 2. Create memory profile
    profile_data = json.dumps({
        "name": DEMO_SENIOR["name"],
        "age_group": DEMO_SENIOR["age_group"],
        "hearing": DEMO_SENIOR["hearing"],
        "vision": DEMO_SENIOR["vision"],
        "memory_support": DEMO_SENIOR["memory_support"],
        "communication_needs": DEMO_SENIOR["communication_needs"],
        "caregiver_id": DEMO_SENIOR["caregiver_id"],
        "medications_list": DEMO_SENIOR["medications_list"],
        "medication_times": DEMO_SENIOR["medication_times"],
        "emergency_contacts": DEMO_SENIOR["emergency_contacts"],
        "daily_routine_notes": DEMO_SENIOR["daily_routine_notes"],
        "baseline_C": 6.0
    })

    with db_context(commit=True) as db:
        if is_postgres():
            db.execute("""
                INSERT INTO memory_profiles (user_id, data, updated_at)
                VALUES (?, ?::jsonb, NOW())
                ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
            """, (user_id, profile_data))
        else:
            db.execute("""
                INSERT OR REPLACE INTO memory_profiles (user_id, data, updated_at)
                VALUES (?, ?, datetime('now'))
            """, (user_id, profile_data))

    logger.info(f"Seed: memory_profile created for {user_id}")

    # 3. Create brain_states (last 7 days, 3-5 per day = ~28 records)
    brain_records = []
    for day_offset in range(7, 0, -1):
        base_time = now - timedelta(days=day_offset)
        interactions = random.randint(3, 5)
        for i in range(interactions):
            t = base_time + timedelta(hours=random.randint(8, 20), minutes=random.randint(0, 59))
            # Normal senior: C mostly 3-8, occasional spike to 12-15
            C = random.gauss(6.0, 2.5)
            if random.random() < 0.1:  # 10% chance of stress spike
                C = random.gauss(14.0, 3.0)
            C = max(0, min(40, C))
            alpha = random.gauss(0.2, 0.1)
            alpha = max(0, min(1, alpha))
            E = random.gauss(0.6, 0.15)
            S = alpha * (1 + C / 40 * 0.5)
            R = max(0, min(1, 1 - S + E * 0.3))
            mode = "HARMONY" if C < 12 else ("ALERT" if C < 27 else "CRISIS")
            coherence = random.gauss(0.7, 0.1)
            brain_records.append((user_id, round(C, 2), round(E, 3), round(R, 3), round(S, 3),
                                  round(alpha, 3), mode, round(coherence, 3), "chat", t.isoformat()))

    with db_context(commit=True) as db:
        # Clear old demo data first
        db.execute("DELETE FROM brain_states WHERE user_id = ?", (user_id,))
        for rec in brain_records:
            if is_postgres():
                db.execute(
                    "INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?::timestamp)",
                    rec)
            else:
                db.execute(
                    "INSERT INTO brain_states (user_id, C, E, R, S, alpha, mode, coherence, source, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rec)

    logger.info(f"Seed: {len(brain_records)} brain_states created for {user_id}")

    # 4. Create memory_learning with C_history
    c_values = [r[1] for r in brain_records[-20:]]  # last 20 C values
    avg_C = sum(c_values) / len(c_values) if c_values else 6.0
    learning_data = json.dumps({
        "topics": {"zdravi": 8, "rodina": 5, "pocasi": 4, "leky": 3},
        "preferred_length": "medium",
        "communication_style": "warm",
        "last_mood": "neutral",
        "interaction_count": len(brain_records),
        "successful_interactions": len(brain_records) - 2,
        "last_interaction": (now - timedelta(hours=3)).isoformat(),
        "C_history": c_values,
        "avg_C": round(avg_C, 2),
        "last_brain_mode": "HARMONY",
        "crisis_count": 0
    })

    with db_context(commit=True) as db:
        if is_postgres():
            db.execute("""
                INSERT INTO memory_learning (user_id, data, updated_at)
                VALUES (?, ?::jsonb, NOW())
                ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
            """, (user_id, learning_data))
        else:
            db.execute("""
                INSERT OR REPLACE INTO memory_learning (user_id, data, updated_at)
                VALUES (?, ?, datetime('now'))
            """, (user_id, learning_data))

    logger.info(f"Seed: memory_learning created for {user_id} (avg_C={avg_C:.1f}, {len(c_values)} C_history)")

    return {
        "user_id": user_id,
        "name": DEMO_SENIOR["name"],
        "brain_states_count": len(brain_records),
        "c_history_count": len(c_values),
        "avg_C": round(avg_C, 2),
        "caregiver_id": DEMO_SENIOR["caregiver_id"]
    }


# Standalone execution
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = seed_demo_data()
    print(f"\nDemo senior seeded: {json.dumps(result, indent=2)}")
