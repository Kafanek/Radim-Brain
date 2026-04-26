"""
Sprint AL.5: Pilot Demo Seeder
==============================
Creates a complete pilot scenario for screening / demo / pilot kickoff:

  - 1 senior (Anna Novotná, 78, mild dementia, lives alone)
  - 1 family caregiver (Jana, daughter, linked + confirmed)
  - 7 days of brain_states (mild rising trend → ALERT in last 24h)
  - 5 chat history rows (gradual concern surfacing)
  - 2 IoT devices (motion + door sensor) with last 24h data
  - 1 active CRISIS observation (chat-induced "spadl jsem")
  - 1 medication schedule (3 meds across morning + evening)
  - 1 caregiver whisper still pending ("připomeň léky")
  - 1 family invite already accepted (so caregiver inbox shows real link)

Idempotent — re-running cleans up old demo rows first so the state
is always fresh.

POST /api/admin/seed-pilot-demo (requires X-Admin-Secret).
"""

import json
import logging
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Stable identifiers — re-seed wipes & restores by these
SENIOR_ID = 'pilot_demo_senior_anna'
CAREGIVER_ID = 'pilot_demo_caregiver_jana'

PILOT_SENIOR_PROFILE = {
    'name': 'Anna Novotná',
    'preferred_name': 'paní Anna',
    'age_group': '75+',
    'hearing': 'mild_loss',
    'vision': 'mild_loss',
    'memory_support': True,
    'communication_needs': 'mild_dementia',
    'medications_list': [
        'Donepezil 10mg (paměť)',
        'Metformin 500mg (cukrovka)',
        'Enalapril 5mg (tlak)',
    ],
    'medication_times': {
        'rano': ['Donepezil 10mg (paměť)', 'Metformin 500mg (cukrovka)'],
        'vecer': ['Enalapril 5mg (tlak)'],
    },
    'emergency_contacts': [
        {'name': 'Jana Procházková', 'phone': '+420603111222', 'relation': 'dcera'},
    ],
    'caregiver_id': CAREGIVER_ID,
    'daily_routine_notes': 'Snídaně v 7:30, procházka v parku 10:00, oběd 12:30, odpolední spánek 14-15h, večeře 18:00.',
    'home_address': 'Senior bydlí v bytě 2+1 sám. Pečující pomáhá 3× týdně.',
}

PILOT_CHAT_HISTORY = [
    # Last 5 user messages — show gradual surfacing concern
    ("Dobrý den Radime. Dnes je krásné počasí.", 7.0, 'HARMONY'),
    ("Vzala jsem si ráno léky. Děkuji za připomenutí.", 5.0, 'HARMONY'),
    ("Trochu mě bolí hlava, ale jinak v pořádku.", 14.0, 'HARMONY'),
    ("Včera v noci jsem skoro nespala. Cítím se unavená.", 18.0, 'ALERT'),
    ("Spadla jsem v koupelně, bolí mě záda.", 30.0, 'CRISIS'),
]


def seed_pilot_demo():
    """Idempotent: wipe + restore."""
    from database import db_context, is_postgres, db_insert
    from memory_helpers import db_save_profile, db_save_learning

    now = datetime.utcnow()
    now_iso = now.isoformat()

    summary = {
        'senior_id': SENIOR_ID,
        'caregiver_id': CAREGIVER_ID,
        'cleaned': {},
        'created': {},
    }

    # ─── 1. Wipe previous pilot demo rows ─────────────────────────
    with db_context(commit=True) as db:
        for table, where in [
            ('memory_history', f"user_id = '{SENIOR_ID}'"),
            ('memory_profiles', f"user_id IN ('{SENIOR_ID}', '{CAREGIVER_ID}')"),
            ('memory_learning', f"user_id IN ('{SENIOR_ID}', '{CAREGIVER_ID}')"),
            ('brain_states', f"user_id = '{SENIOR_ID}'"),
            ('agent_observations', f"user_id = '{SENIOR_ID}'"),
            ('agent_messages', f"user_id = '{SENIOR_ID}'"),
            ('senior_family_links',
             f"senior_id = '{SENIOR_ID}' OR family_user_id = '{CAREGIVER_ID}'"),
            ('iot_sensor_data',
             f"device_id LIKE 'pilot_demo_%'"),
            ('iot_devices', f"user_id = '{SENIOR_ID}'"),
        ]:
            try:
                cur = db.execute(f"DELETE FROM {table} WHERE {where}")
                cnt = getattr(cur, 'rowcount', 0) or 0
                summary['cleaned'][table] = int(cnt) if cnt > 0 else 0
            except Exception as e:
                logger.debug(f"seed_pilot wipe {table}: {e}")

    # ─── 2. Senior profile ────────────────────────────────────────
    try:
        db_save_profile(SENIOR_ID, PILOT_SENIOR_PROFILE)
        summary['created']['senior_profile'] = True
    except Exception as e:
        logger.error(f"seed_pilot save_profile: {e}")
        summary['created']['senior_profile'] = False

    # ─── 3. Caregiver profile (minimal) ───────────────────────────
    try:
        db_save_profile(CAREGIVER_ID, {
            'name': 'Jana Procházková',
            'preferred_name': 'Jana',
            'role': 'caregiver',
            'email': 'jana.demo@pilot.test',
            'phone': '+420603111222',
        })
        summary['created']['caregiver_profile'] = True
    except Exception:
        pass

    # ─── 4. Confirmed family link ─────────────────────────────────
    try:
        with db_context(commit=True) as db:
            link_id = db_insert(
                db, 'senior_family_links',
                ['senior_id', 'family_user_id', 'family_email', 'family_name',
                 'relation', 'confirmed_at',
                 'notify_on_sos', 'notify_on_crisis', 'notify_on_daily'],
                [SENIOR_ID, CAREGIVER_ID, 'jana.demo@pilot.test',
                 'Jana Procházková', 'dcera', now_iso, True, True, False]
            )
            summary['created']['family_link_id'] = link_id
    except Exception as e:
        logger.error(f"seed_pilot family_link: {e}")

    # ─── 5. Memory learning with C_history (7 days mild trend) ────
    try:
        c_hist = []
        # Older days HARMONY (5-8), then 24h trending up to ALERT
        for d in range(7, 0, -1):
            c_hist.append(round(5 + random.random() * 3, 1))
        c_hist.extend([8.5, 11.0, 14.5, 18.0, 22.0])  # last 5 hours rising
        avg_c = sum(c_hist) / len(c_hist)
        learning = {
            'C_history': c_hist,
            'avg_C': round(avg_c, 2),
            'last_brain_mode': 'CRISIS',
            'crisis_count': 1,
            'interaction_count': len(PILOT_CHAT_HISTORY),
            'successful_interactions': len(PILOT_CHAT_HISTORY),
            'last_interaction': now_iso,
            'first_interaction': (now - timedelta(days=7)).isoformat(),
            'topics': {'health': 4, 'family': 2, 'weather': 1},
            'caregiver_whispers': [
                {
                    'id': 1,
                    'text': 'Připomeň jí prosím vzít večerní léky a teplou polévku.',
                    'priority': 'normal',
                    'from': CAREGIVER_ID,
                    'created_at': (now - timedelta(minutes=15)).isoformat(),
                    'consumed_at': None,
                    'expires_at': (now + timedelta(hours=24)).isoformat(),
                }
            ],
        }
        db_save_learning(SENIOR_ID, learning)
        summary['created']['memory_learning'] = {'c_samples': len(c_hist), 'avg_c': round(avg_c, 2)}
    except Exception as e:
        logger.error(f"seed_pilot memory_learning: {e}")

    # ─── 6. brain_states 7-day series (one per day, last day spike) ──
    try:
        from brain_math import brain_mode_for_C
    except ImportError:
        def brain_mode_for_C(C):
            return 'CRISIS' if C >= 27 else 'ALERT' if C >= 12 else 'HARMONY'

    try:
        with db_context(commit=True) as db:
            for d in range(7, 0, -1):
                C = round(5 + random.random() * 3, 1)
                ts = (now - timedelta(days=d, hours=random.randint(8, 20))).isoformat()
                db.execute(
                    "INSERT INTO brain_states "
                    "(user_id, C, E, R, S, alpha, mode, coherence, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (SENIOR_ID, C, 0.6, 0.5, 0.2 + (C / 50), 0.3,
                     brain_mode_for_C(C), 0.7 - (C / 80), ts)
                )
            # Last 5 hours: rising trend, last entry 5 min ago (CRISIS)
            # so operator console (30min window) shows brain.mode=CRISIS
            time_offsets_minutes = [240, 180, 120, 60, 5]
            for offset_min, C in zip(time_offsets_minutes, [11.0, 14.5, 18.0, 22.0, 30.0]):
                ts = (now - timedelta(minutes=offset_min)).isoformat()
                db.execute(
                    "INSERT INTO brain_states "
                    "(user_id, C, E, R, S, alpha, mode, coherence, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (SENIOR_ID, C, max(0.2, 0.6 - C / 50), 0.5, min(1.0, 0.2 + C / 30),
                     min(0.9, 0.3 + C / 60), brain_mode_for_C(C),
                     max(0.2, 0.7 - C / 50), ts)
                )
        summary['created']['brain_states'] = 12
    except Exception as e:
        logger.error(f"seed_pilot brain_states: {e}")

    # ─── 7. Chat history (memory_history) ─────────────────────────
    try:
        with db_context(commit=True) as db:
            for idx, (msg, _C, _mode) in enumerate(PILOT_CHAT_HISTORY):
                ts = (now - timedelta(hours=4 - idx)).isoformat()
                db.execute(
                    "INSERT INTO memory_history (user_id, role, content, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (SENIOR_ID, 'user', msg, ts)
                )
                db.execute(
                    "INSERT INTO memory_history (user_id, role, content, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (SENIOR_ID, 'assistant',
                     'Děkuji paní Anno, jsem tu pro vás.', ts)
                )
        summary['created']['memory_history'] = len(PILOT_CHAT_HISTORY) * 2
    except Exception as e:
        logger.error(f"seed_pilot memory_history: {e}")

    # ─── 8. CRISIS observation from last "spadla jsem" message ────
    try:
        with db_context(commit=True) as db:
            cur = db.execute(
                "INSERT INTO agent_observations "
                "(user_id, observation_type, severity, message, details, "
                " action_taken, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (SENIOR_ID, 'recent_chat_crisis', 'CRISIS',
                 'Paní Anna hlásila pád v koupelně a bolest zad.',
                 json.dumps({'C': 30, 'mode': 'CRISIS', 'source': 'safety_intent'}),
                 'crisis',
                 (now - timedelta(minutes=5)).isoformat())
            )
        summary['created']['observation_crisis'] = True
    except Exception as e:
        logger.error(f"seed_pilot observation: {e}")

    # ─── 9. IoT devices + 24h sensor data ─────────────────────────
    try:
        with db_context(commit=True) as db:
            for dev_id, dev_type in [
                ('pilot_demo_motion_living', 'motion'),
                ('pilot_demo_door_main', 'door'),
            ]:
                db.execute(
                    "INSERT INTO iot_devices "
                    "(device_id, user_id, room_id, device_type, name, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (dev_id, SENIOR_ID,
                     'living_room' if 'motion' in dev_id else 'entrance',
                     dev_type,
                     'Pohyb obývák' if 'motion' in dev_id else 'Vchodové dveře',
                     now_iso)
                )
                # 24 events spread over 24h, lower in last 5h (consistent
                # with rising stress + isolation pattern)
                for h in range(24):
                    val = 1 if (h < 19 and random.random() > 0.25) else 0
                    ts = (now - timedelta(hours=24 - h, minutes=random.randint(0, 50))).isoformat()
                    db.execute(
                        "INSERT INTO iot_sensor_data "
                        "(device_id, user_id, sensor_type, value, recorded_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (dev_id, SENIOR_ID, dev_type, val, ts)
                    )
        summary['created']['iot_devices'] = 2
        summary['created']['iot_sensor_data'] = 48
    except Exception as e:
        logger.error(f"seed_pilot iot: {e}")

    return summary
