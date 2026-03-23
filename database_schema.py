# ============================================
# DATABASE SCHEMA v4.0
# ============================================
# Schema definitions for PostgreSQL and SQLite.
# Extracted from database.py init_db() for modularity.
#
# Functions:
#   init_postgres_schema(db) — Create all tables for PostgreSQL
#   init_sqlite_schema(db)   — Create all tables for SQLite
# ============================================

import logging

logger = logging.getLogger(__name__)

# ============================================================================
# PostgreSQL: Main schema (single multi-statement execute)
# ============================================================================

PG_MAIN_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS chat_conversations (
        id TEXT PRIMARY KEY,
        participants TEXT NOT NULL,
        type TEXT DEFAULT 'direct',
        name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_message TEXT,
        settings TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        type TEXT DEFAULT 'text',
        content TEXT NOT NULL,
        reply_to TEXT,
        metadata TEXT DEFAULT '{}',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'sent',
        reactions TEXT DEFAULT '[]',
        read_by TEXT DEFAULT '[]',
        ai_generated INTEGER DEFAULT 0,
        FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id)
    );

    CREATE TABLE IF NOT EXISTS chat_contacts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        contact_id TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        role TEXT DEFAULT 'Rodina',
        avatar TEXT,
        pinned INTEGER DEFAULT 0,
        muted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chat_users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        avatar TEXT,
        role TEXT DEFAULT 'user',
        online INTEGER DEFAULT 0,
        last_seen TIMESTAMP,
        wp_user_id INTEGER,
        push_subscription TEXT,
        settings TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chat_media (
        id TEXT PRIMARY KEY,
        message_id TEXT,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        url TEXT NOT NULL,
        public_id TEXT,
        filename TEXT,
        size INTEGER,
        duration REAL,
        thumbnail_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        keys TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, endpoint)
    );

    CREATE TABLE IF NOT EXISTS admin_stats (
        id TEXT PRIMARY KEY,
        date DATE NOT NULL,
        total_messages INTEGER DEFAULT 0,
        total_users INTEGER DEFAULT 0,
        ai_messages INTEGER DEFAULT 0,
        voice_messages INTEGER DEFAULT 0,
        active_conversations INTEGER DEFAULT 0,
        UNIQUE(date)
    );

    CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON chat_messages(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_contacts_user ON chat_contacts(user_id);
    CREATE INDEX IF NOT EXISTS idx_media_message ON chat_media(message_id);
    CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);

    CREATE TABLE IF NOT EXISTS memory_profiles (
        user_id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS memory_history (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS memory_learning (
        user_id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_memory_history_user ON memory_history(user_id);
    CREATE INDEX IF NOT EXISTS idx_memory_history_ts ON memory_history(created_at DESC);

    CREATE TABLE IF NOT EXISTS radim_tasks (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        task_type TEXT NOT NULL DEFAULT 'reminder',
        description TEXT,
        scheduled_time TIME,
        scheduled_date DATE,
        recurrence TEXT DEFAULT 'once',
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'normal',
        completed_at TIMESTAMP,
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS radim_medication_log (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        task_id INTEGER REFERENCES radim_tasks(id),
        medication_name TEXT NOT NULL,
        dosage TEXT,
        taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_radim_tasks_user ON radim_tasks(user_id);
    CREATE INDEX IF NOT EXISTS idx_radim_tasks_status ON radim_tasks(user_id, status);
    CREATE INDEX IF NOT EXISTS idx_radim_medlog_user ON radim_medication_log(user_id);

    CREATE TABLE IF NOT EXISTS education_progress (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        course_id TEXT,
        module_id TEXT,
        lesson_id TEXT,
        action TEXT NOT NULL,
        score REAL,
        data JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_profiles (
        user_id TEXT PRIMARY KEY,
        level TEXT DEFAULT 'beginner',
        data JSONB DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_assignments (
        id SERIAL PRIMARY KEY,
        student_id TEXT NOT NULL,
        teacher_id TEXT NOT NULL,
        teacher_type TEXT DEFAULT 'human',
        status TEXT DEFAULT 'active',
        notes JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_edu_assignments_unique
        ON education_assignments(student_id, teacher_id) WHERE status = 'active';

    CREATE TABLE IF NOT EXISTS education_lesson_progress (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        lesson_id TEXT NOT NULL,
        category TEXT,
        score REAL DEFAULT 0,
        completed INTEGER DEFAULT 0,
        answers JSONB DEFAULT '[]',
        time_spent INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, lesson_id)
    );

    CREATE TABLE IF NOT EXISTS voice_sessions (
        session_id TEXT PRIMARY KEY,
        state TEXT DEFAULT 'idle',
        C REAL DEFAULT 5.0,
        kappa REAL DEFAULT 0.8,
        alpha REAL DEFAULT 0.0,
        last_tts_text TEXT DEFAULT '',
        conversation JSONB DEFAULT '[]',
        wake_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_teacher_tasks (
        id SERIAL PRIMARY KEY,
        teacher_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        task_type TEXT DEFAULT 'homework',
        course_id TEXT,
        module_id TEXT,
        due_date DATE,
        status TEXT DEFAULT 'assigned',
        grade TEXT,
        teacher_feedback TEXT,
        student_submission JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_edu_progress_user ON education_progress(user_id);
    CREATE INDEX IF NOT EXISTS idx_edu_progress_course ON education_progress(user_id, course_id);
    CREATE INDEX IF NOT EXISTS idx_edu_assignments_student ON education_assignments(student_id);
    CREATE INDEX IF NOT EXISTS idx_edu_assignments_teacher ON education_assignments(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_edu_lesson_user ON education_lesson_progress(user_id);
    CREATE INDEX IF NOT EXISTS idx_voice_sessions_updated ON voice_sessions(updated_at);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_student ON education_teacher_tasks(student_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_teacher ON education_teacher_tasks(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_status ON education_teacher_tasks(student_id, status);

    -- Telemedicine v3.7
    CREATE TABLE IF NOT EXISTS telemedicine_consultations (
        id SERIAL PRIMARY KEY,
        teacher_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        scheduled_date DATE NOT NULL,
        scheduled_time TIME NOT NULL,
        duration_minutes INTEGER DEFAULT 30,
        status TEXT DEFAULT 'requested',
        room_code TEXT,
        jitsi_url TEXT,
        complaint TEXT,
        findings TEXT,
        recommendations TEXT,
        notes JSONB DEFAULT '{}',
        consultation_type TEXT DEFAULT 'video',
        cancel_reason TEXT,
        email_sent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS telemedicine_availability (
        id SERIAL PRIMARY KEY,
        teacher_id TEXT NOT NULL,
        day_of_week INTEGER,
        specific_date DATE,
        start_time TIME NOT NULL,
        end_time TIME NOT NULL,
        slot_duration_minutes INTEGER DEFAULT 30,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Multiparty telemedicine v3.8
    CREATE TABLE IF NOT EXISTS telemedicine_participants (
        id SERIAL PRIMARY KEY,
        consultation_id INTEGER NOT NULL REFERENCES telemedicine_consultations(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'specialist',
        specialty TEXT,
        status TEXT DEFAULT 'invited',
        notes_contribution TEXT,
        joined_at TIMESTAMP,
        left_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(consultation_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_teacher ON telemedicine_consultations(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_student ON telemedicine_consultations(student_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_date ON telemedicine_consultations(scheduled_date, scheduled_time);
    CREATE INDEX IF NOT EXISTS idx_telemed_status ON telemedicine_consultations(status);
    CREATE INDEX IF NOT EXISTS idx_telemed_avail ON telemedicine_availability(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_consult ON telemedicine_participants(consultation_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_user ON telemedicine_participants(user_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_status ON telemedicine_participants(user_id, status);

    -- Telemedicine audit events v4.1
    CREATE TABLE IF NOT EXISTS telemedicine_events (
        id SERIAL PRIMARY KEY,
        consultation_id INTEGER NOT NULL REFERENCES telemedicine_consultations(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        actor_user_id TEXT NOT NULL,
        actor_auth_role TEXT,
        actor_consultation_role TEXT,
        reason TEXT,
        metadata JSONB DEFAULT '{}',
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_events_consult ON telemedicine_events(consultation_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_actor ON telemedicine_events(actor_user_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_type ON telemedicine_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_created ON telemedicine_events(created_at);

    -- Telemedicine quality metrics v4.1
    CREATE TABLE IF NOT EXISTS telemedicine_quality_log (
        id SERIAL PRIMARY KEY,
        consultation_id INTEGER REFERENCES telemedicine_consultations(id) ON DELETE SET NULL,
        metric_type TEXT NOT NULL,
        metric_value NUMERIC,
        details JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_quality_type ON telemedicine_quality_log(metric_type);
    CREATE INDEX IF NOT EXISTS idx_telemed_quality_created ON telemedicine_quality_log(created_at);

    -- Rhythm Return Engine v3.9
    CREATE TABLE IF NOT EXISTS rhythm_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        preferred_bpm INTEGER DEFAULT 100,
        hy_stage TEXT,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS rhythm_states (
        id SERIAL PRIMARY KEY,
        session_id TEXT,
        M REAL NOT NULL,
        tau REAL NOT NULL,
        predicted_M REAL,
        predicted_tau REAL,
        state TEXT,
        bpm REAL,
        accent_pattern TEXT,
        confidence TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS rhythm_breakpoints (
        id SERIAL PRIMARY KEY,
        session_id TEXT,
        breakpoint_type TEXT,
        direction TEXT,
        M_before REAL,
        M_after REAL,
        action_taken TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_rhythm_sessions_user ON rhythm_sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_rhythm_states_session ON rhythm_states(session_id);
    CREATE INDEX IF NOT EXISTS idx_rhythm_breakpoints_session ON rhythm_breakpoints(session_id);

    -- Brain Engine v4.0
    CREATE TABLE IF NOT EXISTS brain_adaptation (
        user_id TEXT PRIMARY KEY,
        reward_sum INTEGER DEFAULT 0,
        interactions INTEGER DEFAULT 0,
        speech_rate_adjust REAL DEFAULT 0.0,
        pause_adjust_ms REAL DEFAULT 0.0,
        style TEXT DEFAULT 'warm',
        intervention_level REAL DEFAULT 0.5,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS brain_states (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        C REAL,
        E REAL,
        R REAL,
        S REAL,
        alpha REAL,
        mode TEXT,
        coherence REAL,
        source TEXT DEFAULT 'chat',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_brain_states_user ON brain_states(user_id);
    CREATE INDEX IF NOT EXISTS idx_brain_states_created ON brain_states(created_at);

    -- Brain Engine v4.1 — speech feedback
    CREATE TABLE IF NOT EXISTS brain_feedback (
        id SERIAL PRIMARY KEY,
        user_id TEXT NOT NULL,
        rating INTEGER,
        action TEXT,
        response_time_ms INTEGER,
        signal TEXT,
        context TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_brain_feedback_user ON brain_feedback(user_id);
'''

# PostgreSQL: IoT Bridge tables (separate executes due to index creation)
PG_IOT_TABLES = [
    # Crisis events (v284)
    ('''CREATE TABLE IF NOT EXISTS crisis_events (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            caregiver_id TEXT,
            brain_c REAL,
            message_excerpt TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_crisis_events_user ON crisis_events(user_id);
    ''', []),
    # IoT Devices (v5.0)
    ('''CREATE TABLE IF NOT EXISTS iot_devices (
            id SERIAL PRIMARY KEY,
            device_id TEXT UNIQUE NOT NULL,
            room_id TEXT NOT NULL,
            user_id TEXT,
            device_type TEXT NOT NULL,
            name TEXT,
            model TEXT,
            firmware TEXT,
            last_seen TIMESTAMP,
            status TEXT DEFAULT 'active',
            config JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', [
        "CREATE INDEX IF NOT EXISTS idx_iot_devices_room ON iot_devices(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_iot_devices_user ON iot_devices(user_id)",
    ]),
    # IoT Sensor Data
    ('''CREATE TABLE IF NOT EXISTS iot_sensor_data (
            id SERIAL PRIMARY KEY,
            device_id TEXT NOT NULL,
            room_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            metadata JSONB DEFAULT '{}',
            recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', [
        "CREATE INDEX IF NOT EXISTS idx_iot_data_device ON iot_sensor_data(device_id)",
        "CREATE INDEX IF NOT EXISTS idx_iot_data_room ON iot_sensor_data(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_iot_data_type ON iot_sensor_data(sensor_type)",
        "CREATE INDEX IF NOT EXISTS idx_iot_data_recorded ON iot_sensor_data(recorded_at)",
    ]),
    # IoT Alert Rules
    ('''CREATE TABLE IF NOT EXISTS iot_alert_rules (
            id SERIAL PRIMARY KEY,
            room_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            condition TEXT NOT NULL,
            threshold REAL NOT NULL,
            severity TEXT DEFAULT 'warning',
            notify_channels TEXT DEFAULT 'push',
            cooldown_minutes INTEGER DEFAULT 15,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', ["CREATE INDEX IF NOT EXISTS idx_iot_rules_room ON iot_alert_rules(room_id)"]),
    # IoT Alerts
    ('''CREATE TABLE IF NOT EXISTS iot_alerts (
            id SERIAL PRIMARY KEY,
            rule_id INTEGER,
            room_id TEXT NOT NULL,
            user_id TEXT,
            sensor_type TEXT NOT NULL,
            value REAL,
            threshold REAL,
            severity TEXT DEFAULT 'warning',
            message TEXT,
            notified_channels TEXT DEFAULT '[]',
            acknowledged_at TIMESTAMP,
            acknowledged_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', [
        "CREATE INDEX IF NOT EXISTS idx_iot_alerts_room ON iot_alerts(room_id)",
        "CREATE INDEX IF NOT EXISTS idx_iot_alerts_created ON iot_alerts(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_iot_alerts_severity ON iot_alerts(severity)",
    ]),
    # IoT Caregivers (v5.1)
    ('''CREATE TABLE IF NOT EXISTS iot_caregivers (
            id SERIAL PRIMARY KEY,
            room_id TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            role TEXT DEFAULT 'caregiver',
            notify_sms BOOLEAN DEFAULT TRUE,
            notify_push BOOLEAN DEFAULT TRUE,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', ["CREATE INDEX IF NOT EXISTS idx_iot_caregivers_room ON iot_caregivers(room_id)"]),
    # Audit log (v3.9 GDPR)
    ('''CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            action TEXT NOT NULL,
            resource TEXT,
            detail TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', [
        "CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)",
    ]),

    # Agent observations (v4.1 — proactive agent loop)
    ('''CREATE TABLE IF NOT EXISTS agent_observations (
            id SERIAL PRIMARY KEY,
            user_id TEXT NOT NULL,
            observation_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            details JSONB DEFAULT '{}',
            action_taken TEXT,
            acknowledged_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''', [
        "CREATE INDEX IF NOT EXISTS idx_agent_obs_user ON agent_observations(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_obs_created ON agent_observations(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_obs_severity ON agent_observations(severity)",
    ]),
]

# PostgreSQL: ALTER TABLE migrations
PG_MIGRATIONS = [
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS title TEXT",
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS is_multiparty INTEGER DEFAULT 0",
    # v4.1 — GDPR health data classification + audit
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS sensitivity_level TEXT DEFAULT 'health_data'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS consent_version TEXT",
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS legal_basis TEXT DEFAULT 'consent_art9'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS retention_class TEXT DEFAULT 'clinical_5y'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS clinical_notes_locked INTEGER DEFAULT 0",
    # v4.1 — Availability conflict prevention
    "ALTER TABLE telemedicine_availability ADD COLUMN IF NOT EXISTS buffer_before_min INTEGER DEFAULT 5",
    "ALTER TABLE telemedicine_availability ADD COLUMN IF NOT EXISTS buffer_after_min INTEGER DEFAULT 5",
    "ALTER TABLE telemedicine_availability ADD COLUMN IF NOT EXISTS location_mode TEXT DEFAULT 'remote'",
    "ALTER TABLE telemedicine_availability ADD COLUMN IF NOT EXISTS slot_status TEXT DEFAULT 'open'",
    # v4.1 — Participant visibility control
    "ALTER TABLE telemedicine_participants ADD COLUMN IF NOT EXISTS can_view_clinical INTEGER DEFAULT 0",
    "ALTER TABLE telemedicine_participants ADD COLUMN IF NOT EXISTS can_edit_notes INTEGER DEFAULT 0",
    "ALTER TABLE telemedicine_participants ADD COLUMN IF NOT EXISTS join_token TEXT",
    "ALTER TABLE telemedicine_participants ADD COLUMN IF NOT EXISTS join_token_expires TIMESTAMP",
    # v444 — Phone number for contacts (voice calling)
    "ALTER TABLE chat_contacts ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT ''",
]

# ============================================================================
# SQLite: Full schema (single executescript)
# ============================================================================

SQLITE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS chat_conversations (
        id TEXT PRIMARY KEY,
        participants TEXT NOT NULL,
        type TEXT DEFAULT 'direct',
        name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_message TEXT,
        settings TEXT DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        sender_id TEXT NOT NULL,
        type TEXT DEFAULT 'text',
        content TEXT NOT NULL,
        reply_to TEXT,
        metadata TEXT DEFAULT '{}',
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'sent',
        reactions TEXT DEFAULT '[]',
        read_by TEXT DEFAULT '[]',
        ai_generated INTEGER DEFAULT 0,
        FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id)
    );

    CREATE TABLE IF NOT EXISTS chat_contacts (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        contact_id TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT DEFAULT '',
        role TEXT DEFAULT 'Rodina',
        avatar TEXT,
        pinned INTEGER DEFAULT 0,
        muted INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chat_users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        avatar TEXT,
        role TEXT DEFAULT 'user',
        online INTEGER DEFAULT 0,
        last_seen TIMESTAMP,
        wp_user_id INTEGER,
        push_subscription TEXT,
        settings TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chat_media (
        id TEXT PRIMARY KEY,
        message_id TEXT,
        user_id TEXT NOT NULL,
        type TEXT NOT NULL,
        url TEXT NOT NULL,
        public_id TEXT,
        filename TEXT,
        size INTEGER,
        duration REAL,
        thumbnail_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        keys TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, endpoint)
    );

    CREATE TABLE IF NOT EXISTS admin_stats (
        id TEXT PRIMARY KEY,
        date DATE NOT NULL,
        total_messages INTEGER DEFAULT 0,
        total_users INTEGER DEFAULT 0,
        ai_messages INTEGER DEFAULT 0,
        voice_messages INTEGER DEFAULT 0,
        active_conversations INTEGER DEFAULT 0,
        UNIQUE(date)
    );

    CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(conversation_id);
    CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON chat_messages(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_contacts_user ON chat_contacts(user_id);
    CREATE INDEX IF NOT EXISTS idx_media_message ON chat_media(message_id);
    CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);

    CREATE TABLE IF NOT EXISTS memory_profiles (
        user_id TEXT PRIMARY KEY,
        data TEXT NOT NULL DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS memory_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS memory_learning (
        user_id TEXT PRIMARY KEY,
        data TEXT NOT NULL DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_memory_history_user ON memory_history(user_id);
    CREATE INDEX IF NOT EXISTS idx_memory_history_ts ON memory_history(created_at DESC);

    CREATE TABLE IF NOT EXISTS radim_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        task_type TEXT NOT NULL DEFAULT 'reminder',
        description TEXT,
        scheduled_time TEXT,
        scheduled_date TEXT,
        recurrence TEXT DEFAULT 'once',
        status TEXT DEFAULT 'pending',
        priority TEXT DEFAULT 'normal',
        completed_at TIMESTAMP,
        metadata TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS radim_medication_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        task_id INTEGER REFERENCES radim_tasks(id),
        medication_name TEXT NOT NULL,
        dosage TEXT,
        taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_radim_tasks_user ON radim_tasks(user_id);
    CREATE INDEX IF NOT EXISTS idx_radim_tasks_status ON radim_tasks(user_id, status);
    CREATE INDEX IF NOT EXISTS idx_radim_medlog_user ON radim_medication_log(user_id);

    CREATE TABLE IF NOT EXISTS education_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        course_id TEXT,
        module_id TEXT,
        lesson_id TEXT,
        action TEXT NOT NULL,
        score REAL,
        data TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_profiles (
        user_id TEXT PRIMARY KEY,
        level TEXT DEFAULT 'beginner',
        data TEXT DEFAULT '{}',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        teacher_id TEXT NOT NULL,
        teacher_type TEXT DEFAULT 'human',
        status TEXT DEFAULT 'active',
        notes TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_edu_assignments_unique
        ON education_assignments(student_id, teacher_id) WHERE status = 'active';

    CREATE TABLE IF NOT EXISTS education_lesson_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        lesson_id TEXT NOT NULL,
        category TEXT,
        score REAL DEFAULT 0,
        completed INTEGER DEFAULT 0,
        answers TEXT DEFAULT '[]',
        time_spent INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, lesson_id)
    );

    CREATE TABLE IF NOT EXISTS voice_sessions (
        session_id TEXT PRIMARY KEY,
        state TEXT DEFAULT 'idle',
        C REAL DEFAULT 5.0,
        kappa REAL DEFAULT 0.8,
        alpha REAL DEFAULT 0.0,
        last_tts_text TEXT DEFAULT '',
        conversation TEXT DEFAULT '[]',
        wake_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS education_teacher_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        task_type TEXT DEFAULT 'homework',
        course_id TEXT,
        module_id TEXT,
        due_date TEXT,
        status TEXT DEFAULT 'assigned',
        grade TEXT,
        teacher_feedback TEXT,
        student_submission TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_edu_progress_user ON education_progress(user_id);
    CREATE INDEX IF NOT EXISTS idx_edu_progress_course ON education_progress(user_id, course_id);
    CREATE INDEX IF NOT EXISTS idx_edu_assignments_student ON education_assignments(student_id);
    CREATE INDEX IF NOT EXISTS idx_edu_assignments_teacher ON education_assignments(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_edu_lesson_user ON education_lesson_progress(user_id);
    CREATE INDEX IF NOT EXISTS idx_voice_sessions_updated ON voice_sessions(updated_at);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_student ON education_teacher_tasks(student_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_teacher ON education_teacher_tasks(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_teacher_tasks_status ON education_teacher_tasks(student_id, status);

    -- Telemedicine v3.7
    CREATE TABLE IF NOT EXISTS telemedicine_consultations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id TEXT NOT NULL,
        student_id TEXT NOT NULL,
        scheduled_date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        duration_minutes INTEGER DEFAULT 30,
        status TEXT DEFAULT 'requested',
        room_code TEXT,
        jitsi_url TEXT,
        complaint TEXT,
        findings TEXT,
        recommendations TEXT,
        notes TEXT DEFAULT '{}',
        consultation_type TEXT DEFAULT 'video',
        cancel_reason TEXT,
        email_sent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS telemedicine_availability (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id TEXT NOT NULL,
        day_of_week INTEGER,
        specific_date TEXT,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        slot_duration_minutes INTEGER DEFAULT 30,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Multiparty telemedicine v3.8
    CREATE TABLE IF NOT EXISTS telemedicine_participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consultation_id INTEGER NOT NULL REFERENCES telemedicine_consultations(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'specialist',
        specialty TEXT,
        status TEXT DEFAULT 'invited',
        notes_contribution TEXT,
        joined_at TIMESTAMP,
        left_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(consultation_id, user_id)
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_teacher ON telemedicine_consultations(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_student ON telemedicine_consultations(student_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_date ON telemedicine_consultations(scheduled_date, scheduled_time);
    CREATE INDEX IF NOT EXISTS idx_telemed_status ON telemedicine_consultations(status);
    CREATE INDEX IF NOT EXISTS idx_telemed_avail ON telemedicine_availability(teacher_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_consult ON telemedicine_participants(consultation_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_user ON telemedicine_participants(user_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_part_status ON telemedicine_participants(user_id, status);

    -- Telemedicine audit events v4.1
    CREATE TABLE IF NOT EXISTS telemedicine_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consultation_id INTEGER NOT NULL REFERENCES telemedicine_consultations(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        actor_user_id TEXT NOT NULL,
        actor_auth_role TEXT,
        actor_consultation_role TEXT,
        reason TEXT,
        metadata TEXT DEFAULT '{}',
        ip_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_events_consult ON telemedicine_events(consultation_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_actor ON telemedicine_events(actor_user_id);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_type ON telemedicine_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_telemed_events_created ON telemedicine_events(created_at);

    -- Telemedicine quality metrics v4.1
    CREATE TABLE IF NOT EXISTS telemedicine_quality_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consultation_id INTEGER REFERENCES telemedicine_consultations(id) ON DELETE SET NULL,
        metric_type TEXT NOT NULL,
        metric_value REAL,
        details TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_telemed_quality_type ON telemedicine_quality_log(metric_type);
    CREATE INDEX IF NOT EXISTS idx_telemed_quality_created ON telemedicine_quality_log(created_at);

    -- Rhythm Return Engine v3.9
    CREATE TABLE IF NOT EXISTS rhythm_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        preferred_bpm INTEGER DEFAULT 100,
        hy_stage TEXT,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS rhythm_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        M REAL NOT NULL,
        tau REAL NOT NULL,
        predicted_M REAL,
        predicted_tau REAL,
        state TEXT,
        bpm REAL,
        accent_pattern TEXT,
        confidence TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS rhythm_breakpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        breakpoint_type TEXT,
        direction TEXT,
        M_before REAL,
        M_after REAL,
        action_taken TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_rhythm_sessions_user ON rhythm_sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_rhythm_states_session ON rhythm_states(session_id);
    CREATE INDEX IF NOT EXISTS idx_rhythm_breakpoints_session ON rhythm_breakpoints(session_id);

    -- Brain Engine v4.0
    CREATE TABLE IF NOT EXISTS brain_adaptation (
        user_id TEXT PRIMARY KEY,
        reward_sum INTEGER DEFAULT 0,
        interactions INTEGER DEFAULT 0,
        speech_rate_adjust REAL DEFAULT 0.0,
        pause_adjust_ms REAL DEFAULT 0.0,
        style TEXT DEFAULT 'warm',
        intervention_level REAL DEFAULT 0.5,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS brain_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        C REAL,
        E REAL,
        R REAL,
        S REAL,
        alpha REAL,
        mode TEXT,
        coherence REAL,
        source TEXT DEFAULT 'chat',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_brain_states_user ON brain_states(user_id);
    CREATE INDEX IF NOT EXISTS idx_brain_states_created ON brain_states(created_at);

    -- Brain Engine v4.1 — speech feedback
    CREATE TABLE IF NOT EXISTS brain_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        rating INTEGER,
        action TEXT,
        response_time_ms INTEGER,
        signal TEXT,
        context TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_brain_feedback_user ON brain_feedback(user_id);

    -- v284: Crisis events
    CREATE TABLE IF NOT EXISTS crisis_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        caregiver_id TEXT,
        brain_c REAL,
        message_excerpt TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_crisis_events_user ON crisis_events(user_id);

    -- v5.0: IoT Bridge
    CREATE TABLE IF NOT EXISTS iot_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT UNIQUE NOT NULL,
        room_id TEXT NOT NULL,
        user_id TEXT,
        device_type TEXT NOT NULL,
        name TEXT,
        model TEXT,
        firmware TEXT,
        last_seen TIMESTAMP,
        status TEXT DEFAULT 'active',
        config TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_iot_devices_room ON iot_devices(room_id);
    CREATE INDEX IF NOT EXISTS idx_iot_devices_user ON iot_devices(user_id);

    CREATE TABLE IF NOT EXISTS iot_sensor_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        room_id TEXT NOT NULL,
        sensor_type TEXT NOT NULL,
        value REAL NOT NULL,
        unit TEXT,
        metadata TEXT DEFAULT '{}',
        recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_iot_data_device ON iot_sensor_data(device_id);
    CREATE INDEX IF NOT EXISTS idx_iot_data_room ON iot_sensor_data(room_id);
    CREATE INDEX IF NOT EXISTS idx_iot_data_type ON iot_sensor_data(sensor_type);
    CREATE INDEX IF NOT EXISTS idx_iot_data_recorded ON iot_sensor_data(recorded_at);

    CREATE TABLE IF NOT EXISTS iot_alert_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL,
        sensor_type TEXT NOT NULL,
        condition TEXT NOT NULL,
        threshold REAL NOT NULL,
        severity TEXT DEFAULT 'warning',
        notify_channels TEXT DEFAULT 'push',
        cooldown_minutes INTEGER DEFAULT 15,
        enabled INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_iot_rules_room ON iot_alert_rules(room_id);

    CREATE TABLE IF NOT EXISTS iot_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER,
        room_id TEXT NOT NULL,
        user_id TEXT,
        sensor_type TEXT NOT NULL,
        value REAL,
        threshold REAL,
        severity TEXT DEFAULT 'warning',
        message TEXT,
        notified_channels TEXT DEFAULT '[]',
        acknowledged_at TIMESTAMP,
        acknowledged_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_iot_alerts_room ON iot_alerts(room_id);
    CREATE INDEX IF NOT EXISTS idx_iot_alerts_created ON iot_alerts(created_at);
    CREATE INDEX IF NOT EXISTS idx_iot_alerts_severity ON iot_alerts(severity);

    CREATE TABLE IF NOT EXISTS agent_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        observation_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        details TEXT DEFAULT '{}',
        action_taken TEXT,
        acknowledged_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_agent_obs_user ON agent_observations(user_id);
    CREATE INDEX IF NOT EXISTS idx_agent_obs_created ON agent_observations(created_at);
    CREATE INDEX IF NOT EXISTS idx_agent_obs_severity ON agent_observations(severity);
'''

# SQLite: ALTER TABLE migrations
SQLITE_MIGRATIONS = [
    "ALTER TABLE telemedicine_consultations ADD COLUMN title TEXT",
    "ALTER TABLE telemedicine_consultations ADD COLUMN is_multiparty INTEGER DEFAULT 0",
    # v4.1 — GDPR health data classification + audit
    "ALTER TABLE telemedicine_consultations ADD COLUMN sensitivity_level TEXT DEFAULT 'health_data'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN consent_version TEXT",
    "ALTER TABLE telemedicine_consultations ADD COLUMN legal_basis TEXT DEFAULT 'consent_art9'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN retention_class TEXT DEFAULT 'clinical_5y'",
    "ALTER TABLE telemedicine_consultations ADD COLUMN clinical_notes_locked INTEGER DEFAULT 0",
    # v4.1 — Availability conflict prevention
    "ALTER TABLE telemedicine_availability ADD COLUMN buffer_before_min INTEGER DEFAULT 5",
    "ALTER TABLE telemedicine_availability ADD COLUMN buffer_after_min INTEGER DEFAULT 5",
    "ALTER TABLE telemedicine_availability ADD COLUMN location_mode TEXT DEFAULT 'remote'",
    "ALTER TABLE telemedicine_availability ADD COLUMN slot_status TEXT DEFAULT 'open'",
    # v4.1 — Participant visibility control
    "ALTER TABLE telemedicine_participants ADD COLUMN can_view_clinical INTEGER DEFAULT 0",
    "ALTER TABLE telemedicine_participants ADD COLUMN can_edit_notes INTEGER DEFAULT 0",
    "ALTER TABLE telemedicine_participants ADD COLUMN join_token TEXT",
    "ALTER TABLE telemedicine_participants ADD COLUMN join_token_expires TIMESTAMP",
]


# ============================================================================
# INIT FUNCTIONS
# ============================================================================

def init_postgres_schema(db):
    """Apply full PostgreSQL schema to database connection."""
    # Main schema (one big execute)
    db.execute(PG_MAIN_SCHEMA)

    # IoT + extra tables (separate executes with index try/except)
    for table_sql, index_sqls in PG_IOT_TABLES:
        db.execute(table_sql)
        for idx_sql in index_sqls:
            try:
                db.execute(idx_sql)
            except Exception:
                pass

    # Migrations
    for mig_sql in PG_MIGRATIONS:
        try:
            db.execute(mig_sql)
        except Exception:
            pass

    # Upsert Radim AI assistant
    db.execute('''
        INSERT INTO chat_users (id, name, role, online, settings)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            role = EXCLUDED.role,
            online = EXCLUDED.online,
            settings = EXCLUDED.settings
    ''', ('radim', 'Radim Asistent', 'ai_assistant', 1, '{"ai_enabled": true, "voice": "radim"}'))


def init_sqlite_schema(db):
    """Apply full SQLite schema to database connection."""
    db.executescript(SQLITE_SCHEMA)

    # Migrations (may fail if column already exists)
    for mig_sql in SQLITE_MIGRATIONS:
        try:
            db.execute(mig_sql)
        except Exception:
            pass

    # Insert Radim AI assistant
    db.execute('''
        INSERT OR REPLACE INTO chat_users (id, name, role, online, settings)
        VALUES (?, ?, ?, ?, ?)
    ''', ('radim', 'Radim Asistent', 'ai_assistant', 1, '{"ai_enabled": true, "voice": "radim"}'))


logger.info("Database Schema v4.0 loaded — PG + SQLite schemas")
