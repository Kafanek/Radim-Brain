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
import logging
import sqlite3
import time
import threading
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
        logger.info(f"PostgreSQL mode - connecting to: {_safe_url}")
    except ImportError:
        logger.warning("psycopg2 not installed, falling back to SQLite")
        USE_POSTGRES = False

if not USE_POSTGRES:
    logger.info(f"SQLite mode - database: {DATABASE_PATH}")

# ============================================
# CONNECTION POOL (PostgreSQL only)
# ============================================
_pg_pool = None
_pg_pool_lock = threading.Lock()

def _get_pg_pool():
    """Get or create PostgreSQL connection pool (thread-safe)"""
    global _pg_pool
    if _pg_pool is not None and not _pg_pool.closed:
        return _pg_pool
    with _pg_pool_lock:
        # Double-check inside lock
        if _pg_pool is None or _pg_pool.closed:
            # Heroku PG connections may idle-timeout; keepalives prevent this
            # ⚡ v10.8: Increased pool from 10→18 for scaling
            # Heroku Essential-0 = 20 max connections, keep 2 for admin/migrations
            import os
            _max_conn = int(os.environ.get('DB_POOL_MAX', '18'))
            _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=_max_conn,
                dsn=DATABASE_URL,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
                options='-c statement_timeout=25000'  # 25s query timeout
            )
            logger.info(f"PostgreSQL pool created (maxconn={_max_conn}, minconn=2, keepalive=30s)")
    return _pg_pool


def _test_connection(conn):
    """Test if a PostgreSQL connection is still alive."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        return True
    except Exception:
        return False


# ============================================
# SQLITE ROW WRAPPER (makes sqlite rows dict-like)
# ============================================
class DictRow(dict):
    """Dict that also supports index-based access like sqlite3.Row"""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


# SQLite wrapper: DDL translator (SERIAL → INTEGER AUTOINCREMENT, JSONB → TEXT,
# INTERVAL 'N days' → datetime literal). Applied only when sqlite backend is used.
import re as _sqlite_re
_SERIAL_RE = _sqlite_re.compile(r'\bSERIAL\s+PRIMARY\s+KEY\b', _sqlite_re.IGNORECASE)
_JSONB_RE = _sqlite_re.compile(r'\bJSONB\b', _sqlite_re.IGNORECASE)
_INTERVAL_RE = _sqlite_re.compile(
    r"CURRENT_TIMESTAMP\s*-\s*INTERVAL\s+'(\d+)\s*(day|days|hour|hours)'",
    _sqlite_re.IGNORECASE,
)
_INTERVAL_DATE_RE = _sqlite_re.compile(
    r"CURRENT_DATE\s*-\s*INTERVAL\s+'(\d+)\s*(day|days)'",
    _sqlite_re.IGNORECASE,
)
_NOW_RE = _sqlite_re.compile(r"\bNOW\(\)", _sqlite_re.IGNORECASE)


def _translate_sqlite_sql(sql):
    if not isinstance(sql, str):
        return sql
    s = sql
    s = _SERIAL_RE.sub('INTEGER PRIMARY KEY AUTOINCREMENT', s)
    s = _JSONB_RE.sub('TEXT', s)

    def _iv_repl(m):
        n, unit = m.group(1), m.group(2).lower()
        if unit.startswith('day'):
            return f"datetime('now', '-{n} days')"
        return f"datetime('now', '-{n} hours')"

    def _iv_date_repl(m):
        n = m.group(1)
        return f"date('now', '-{n} days')"

    s = _INTERVAL_RE.sub(_iv_repl, s)
    s = _INTERVAL_DATE_RE.sub(_iv_date_repl, s)
    s = _NOW_RE.sub("CURRENT_TIMESTAMP", s)
    return s


class _SqliteCompatCursor:
    """Wrap sqlite3 cursor: translate PG-isms before execute."""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, *args, **kw):
        return self._cur.execute(_translate_sqlite_sql(sql), *args, **kw)

    def executemany(self, sql, *args, **kw):
        return self._cur.executemany(_translate_sqlite_sql(sql), *args, **kw)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _SqliteCompatConnection:
    """Wrap sqlite3 Connection so CREATE TABLE/SELECT use PG syntax."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args, **kw):
        return self._conn.execute(_translate_sqlite_sql(sql), *args, **kw)

    def executescript(self, sql):
        return self._conn.executescript(_translate_sqlite_sql(sql))

    def cursor(self, *a, **kw):
        return _SqliteCompatCursor(self._conn.cursor(*a, **kw))

    def __getattr__(self, name):
        return getattr(self._conn, name)


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
    def rowcount(self):
        return self._cursor.rowcount

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

    # INSERT OR REPLACE -> INSERT ... ON CONFLICT DO UPDATE
    # This is handled case-by-case in the code, not here
    # because ON CONFLICT needs to know the conflict target

    return query


def _convert_schema(script):
    """Convert SQLite CREATE TABLE schema to PostgreSQL-compatible"""
    # SQLite's AUTOINCREMENT -> PostgreSQL's SERIAL (not used in this app)
    # SQLite's INTEGER -> PostgreSQL's INTEGER (compatible)
    # SQLite's TIMESTAMP DEFAULT CURRENT_TIMESTAMP -> same in PostgreSQL
    # SQLite's TEXT -> same in PostgreSQL

    # Replace INSERT OR REPLACE with PostgreSQL equivalent
    script = script.replace('INSERT OR REPLACE', 'INSERT')

    # The schema is already mostly compatible
    return script


# ============================================
# PUBLIC API
# ============================================
def get_connection():
    """Get a new database connection (for use outside Flask request context).

    PostgreSQL: pulls from pool with health check + 1 retry on stale conn.
    SQLite: creates fresh connection each time.
    """
    if USE_POSTGRES:
        for attempt in range(2):
            try:
                pool = _get_pg_pool()
                conn = pool.getconn()
                # Health check - reject stale/dead connections
                if not _test_connection(conn):
                    logger.warning("Stale PG connection, discarding")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    # Force pool to give us a fresh one
                    if attempt == 0:
                        continue
                    raise Exception("No healthy PG connection available")
                return PgConnectionWrapper(conn)
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"PG pool.getconn() failed (attempt 1): {e}")
                    # Pool might be exhausted or broken - try recreating
                    global _pg_pool
                    with _pg_pool_lock:
                        try:
                            if _pg_pool and not _pg_pool.closed:
                                _pg_pool.closeall()
                        except Exception:
                            pass
                        _pg_pool = None
                    time.sleep(0.5)
                    continue
                logger.error(f"PG connection failed after 2 attempts: {e}")
                raise
    else:
        conn = sqlite3.connect(DATABASE_PATH)

        # Use DictRow (dict subclass supporting both int and str access +
        # .get()) so endpoints written for PG DictRow also work on SQLite.
        def _dict_row_factory(cursor, row):
            return DictRow({col[0]: row[i] for i, col in enumerate(cursor.description)})
        conn.row_factory = _dict_row_factory

        # Translate PG-specific DDL so SQLite-backed tests exercise the same
        # schema scripts the prod PG deployment uses (SERIAL auto-increment,
        # JSONB → TEXT, etc.). Production is unaffected.
        return _SqliteCompatConnection(conn)


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
    """Initialize database schema — delegates to database_schema.py.

    v8.19.106: Wraps PG schema init in pg_advisory_lock so only one dyno
    runs DDL at a time. Previously two dynos starting in parallel would
    race on CREATE TABLE / CREATE INDEX, leaving one in
    InFailedSqlTransaction state and crashing that worker on boot.
    The lock key (4242424242) is an arbitrary 64-bit constant unique to
    this app's schema init.
    """
    from database_schema import init_postgres_schema, init_sqlite_schema
    db = get_connection()

    if USE_POSTGRES:
        # Serialize schema init across dynos. pg_advisory_lock is session-
        # scoped and auto-released on connection close. Other dynos block
        # here briefly, then see the schema is already current and exit fast.
        SCHEMA_LOCK_KEY = 4242424242
        try:
            db.execute("SELECT pg_advisory_lock(?)", (SCHEMA_LOCK_KEY,))
            try:
                init_postgres_schema(db)
                db.commit()
            finally:
                try:
                    db.execute("SELECT pg_advisory_unlock(?)", (SCHEMA_LOCK_KEY,))
                except Exception:
                    pass
        except Exception as e:
            # Roll back the failed transaction so the connection is reusable
            # before re-raising. Without this, subsequent statements on the
            # same connection hit InFailedSqlTransaction (the symptom we saw
            # on web.2 boot crash).
            try:
                db.rollback()
            except Exception:
                pass
            logger.error(f"PG schema init failed: {e}")
            raise
    else:
        init_sqlite_schema(db)
        db.commit()

    try:
        db.close()
    except Exception:
        pass

    db_type = "PostgreSQL" if USE_POSTGRES else "SQLite"
    logger.info(f"Database initialized ({db_type}, v4.0 — schema from database_schema.py)")


def is_postgres():
    """Check if using PostgreSQL"""
    return USE_POSTGRES


class db_context:
    """Context manager for database connections with auto-commit/rollback/close.

    Usage (read-only):
        with db_context() as db:
            rows = db.execute("SELECT ...").fetchall()

    Usage (write):
        with db_context(commit=True) as db:
            db.execute("INSERT ...")

    On success: commits (if commit=True), then closes connection.
    On exception: rolls back, closes connection, re-raises.
    """

    def __init__(self, commit=False):
        self._commit = commit
        self._db = None

    def __enter__(self):
        self._db = get_connection()
        # v450: Signal DB circuit breaker success
        try:
            from self_healing import get_breaker
            get_breaker('database').record_success()
        except Exception:
            pass
        return self._db

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._db is None:
            return False
        try:
            if exc_type is not None:
                try:
                    self._db.rollback()
                except Exception:
                    pass
                # v450: Signal DB circuit breaker failure
                try:
                    from self_healing import get_breaker
                    get_breaker('database').record_failure()
                except Exception:
                    pass
            elif self._commit:
                self._db.commit()
        finally:
            try:
                self._db.close()
            except Exception:
                pass
        return False  # don't suppress exceptions


def db_insert(db, table, columns, values):
    """Insert a row and return its ID (works on both PostgreSQL and SQLite).

    Usage:
        row_id = db_insert(db, 'my_table', ['col1', 'col2'], (val1, val2))
    """
    placeholders = ', '.join(['?'] * len(values))
    col_str = ', '.join(columns)
    if USE_POSTGRES:
        row = db.execute(
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) RETURNING id",
            values
        ).fetchone()
        return row['id'] if row else None
    else:
        cursor = db.execute(
            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",
            values
        )
        return cursor.lastrowid
