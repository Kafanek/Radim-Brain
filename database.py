# ============================================
# DATABASE ADAPTER - SQLite / PostgreSQL
# ============================================
# Detects DATABASE_URL (PostgreSQL on Heroku) or falls back to SQLite (local dev).
# Provides a unified interface for both backends.
#
# Usage:
#   from database import get_db, close_db, init_db, db_execute
#
# PostgreSQL: Set DATABASE_URL env var (Heroku Postgres sets this automatically)
# SQLite:     Set DATABASE_PATH env var or use default 'radim_chat.db'

import os
import json
import sqlite3
from urllib.parse import urlparse

# Detect database type
DATABASE_URL = os.environ.get('DATABASE_URL')
DATABASE_PATH = os.environ.get('DATABASE_PATH', 'radim_chat.db')

# Heroku sometimes uses postgres:// but psycopg2 needs postgresql://
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
        import psycopg2.pool
        # Redact credentials from log output
        try:
            from urllib.parse import urlparse as _urlparse
            _parsed = _urlparse(DATABASE_URL)
            _safe_url = f"{_parsed.scheme}://{_parsed.username}:***@{_parsed.hostname}:{_parsed.port}{_parsed.path}"
        except Exception:
            _safe_url = "postgresql://***"
        print(f"🐘 PostgreSQL mode - connecting to: {_safe_url}")
    except ImportError:
        print("⚠️  psycopg2 not installed, falling back to SQLite")
        USE_POSTGRES = False

if not USE_POSTGRES:
    print(f"📁 SQLite mode - database: {DATABASE_PATH}")

# ============================================
# CONNECTION POOL (PostgreSQL only)
# ============================================
_pg_pool = None

def _get_pg_pool():
    """Get or create PostgreSQL connection pool"""
    global _pg_pool
    if _pg_pool is None or _pg_pool.closed:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL
        )
    return _pg_pool


# ============================================
# SQLITE ROW WRAPPER (makes sqlite rows dict-like)
# ============================================
class DictRow(dict):
    """Dict that also supports index-based access like sqlite3.Row"""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


# ============================================
# POSTGRES CURSOR WRAPPER
# ============================================
class PgCursorWrapper:
    """Wraps psycopg2 cursor to provide sqlite3-like interface.
    Converts ? placeholders to %s and returns dict rows."""

    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def execute(self, query, params=None):
        query = _convert_query(query)
        if params:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)
        return self

    def executescript(self, script):
        """Execute multiple statements (for init_db)"""
        # Convert SQLite syntax to PostgreSQL
        script = _convert_schema(script)
        self._cursor.execute(script)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DictRow(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(row) for row in rows]

    @property
    def lastrowid(self):
        return getattr(self._cursor, 'lastrowid', None)

    @property
    def description(self):
        return self._cursor.description


# ============================================
# POSTGRES CONNECTION WRAPPER
# ============================================
class PgConnectionWrapper:
    """Wraps psycopg2 connection to provide sqlite3-like interface."""

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, query, params=None):
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = PgCursorWrapper(cursor, self._conn)
        wrapper.execute(query, params)
        return wrapper

    def executescript(self, script):
        cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = PgCursorWrapper(cursor, self._conn)
        wrapper.executescript(script)
        return wrapper

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            pool = _get_pg_pool()
            pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        pass  # Ignored for PostgreSQL - we always use RealDictCursor


# ============================================
# QUERY CONVERSION
# ============================================
def _convert_query(query):
    """Convert SQLite query syntax to PostgreSQL"""
    # Replace ? placeholders with %s
    result = []
    in_string = False
    string_char = None
    i = 0
    while i < len(query):
        c = query[i]
        if not in_string and c in ("'", '"'):
            in_string = True
            string_char = c
            result.append(c)
        elif in_string and c == string_char:
            in_string = False
            result.append(c)
        elif not in_string and c == '?':
            result.append('%s')
        else:
            result.append(c)
        i += 1

    query = ''.join(result)

    # INSERT OR REPLACE → INSERT ... ON CONFLICT DO UPDATE
    # This is handled case-by-case in the code, not here
    # because ON CONFLICT needs to know the conflict target

    return query


def _convert_schema(script):
    """Convert SQLite CREATE TABLE schema to PostgreSQL-compatible"""
    # SQLite's AUTOINCREMENT → PostgreSQL's SERIAL (not used in this app)
    # SQLite's INTEGER → PostgreSQL's INTEGER (compatible)
    # SQLite's TIMESTAMP DEFAULT CURRENT_TIMESTAMP → same in PostgreSQL
    # SQLite's TEXT → same in PostgreSQL

    # Replace INSERT OR REPLACE with PostgreSQL equivalent
    script = script.replace('INSERT OR REPLACE', 'INSERT')

    # The schema is already mostly compatible
    return script


# ============================================
# PUBLIC API
# ============================================
def get_connection():
    """Get a new database connection (for use outside Flask request context)"""
    if USE_POSTGRES:
        pool = _get_pg_pool()
        conn = pool.getconn()
        return PgConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def get_db_for_flask(g_obj):
    """Get database connection for Flask request context (stored in g)"""
    if 'db' not in g_obj:
        g_obj.db = get_connection()
    return g_obj.db


def close_db_for_flask(g_obj):
    """Close Flask request-scoped database connection"""
    db = g_obj.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize database schema"""
    db = get_connection()

    if USE_POSTGRES:
        # PostgreSQL schema
        db.execute('''
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

            -- ============================================
            -- Telemedicine v3.7
            -- ============================================
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

            -- ============================================
            -- Rhythm Return Engine v3.9
            -- ============================================
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
        ''')

        # v3.8 migration: add multiparty columns to existing table
        try:
            db.execute("ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS title TEXT")
            db.execute("ALTER TABLE telemedicine_consultations ADD COLUMN IF NOT EXISTS is_multiparty INTEGER DEFAULT 0")
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

    else:
        # SQLite schema (original)
        db.executescript('''
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

            -- ============================================
            -- Rhythm Return Engine v3.9
            -- ============================================
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
        ''')

        # v3.8 migration: add multiparty columns to existing table
        for col_sql in [
            "ALTER TABLE telemedicine_consultations ADD COLUMN title TEXT",
            "ALTER TABLE telemedicine_consultations ADD COLUMN is_multiparty INTEGER DEFAULT 0",
        ]:
            try:
                db.execute(col_sql)
            except Exception:
                pass

        db.execute('''
            INSERT OR REPLACE INTO chat_users (id, name, role, online, settings)
            VALUES (?, ?, ?, ?, ?)
        ''', ('radim', 'Radim Asistent', 'ai_assistant', 1, '{"ai_enabled": true, "voice": "radim"}'))

    db.commit()
    db.close()

    db_type = "PostgreSQL" if USE_POSTGRES else "SQLite"
    print(f"✅ Databáze inicializována ({db_type}, v3.9 — Rhythm Return Engine)")


def is_postgres():
    """Check if using PostgreSQL"""
    return USE_POSTGRES
