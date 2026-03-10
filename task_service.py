# -*- coding: utf-8 -*-
"""
📋 RADIM Task & Medication Service v1.1.0
Persistentní úkoly, připomínky a sledování léků.
PostgreSQL / SQLite backed.

Používá database.py adapter — stejný pattern jako memory_routes.py.

v1.1.0 — Fixed connection leak: all get_connection() calls now use try/finally
"""

import json
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

# ============================================
# DATABASE IMPORT
# ============================================
try:
    from database import get_connection, USE_POSTGRES
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    USE_POSTGRES = False
    logger.warning("⚠️ task_service: database module not available")


def _p():
    """Placeholder pro SQL parametry — %s pro Postgres, ? pro SQLite."""
    return "%s" if USE_POSTGRES else "?"


# ============================================
# TASK CRUD
# ============================================

def create_task(user_id, title, task_type='reminder', scheduled_time=None,
                scheduled_date=None, recurrence='once', priority='normal',
                description=None, metadata=None):
    """
    Vytvořit nový úkol. Vrací dict s ID.
    """
    if not _DB_AVAILABLE:
        return None

    db = None
    try:
        db = get_connection()
        p = _p()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        # Default: dnes
        if scheduled_date is None and scheduled_time is not None:
            scheduled_date = date.today().isoformat()

        if USE_POSTGRES:
            row = db.execute(
                f"""INSERT INTO radim_tasks
                    (user_id, title, task_type, scheduled_time, scheduled_date,
                     recurrence, priority, description, metadata)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})
                    RETURNING id""",
                (user_id, title, task_type, scheduled_time, scheduled_date,
                 recurrence, priority, description, meta_json)
            ).fetchone()
            task_id = row['id'] if row else None
        else:
            cursor = db.execute(
                f"""INSERT INTO radim_tasks
                    (user_id, title, task_type, scheduled_time, scheduled_date,
                     recurrence, priority, description, metadata)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p})""",
                (user_id, title, task_type, scheduled_time, scheduled_date,
                 recurrence, priority, description, meta_json)
            )
            task_id = cursor.lastrowid

        db.commit()

        if task_id:
            logger.info(f"✅ Task created: #{task_id} '{title}' for {user_id}")
            return {
                'id': task_id, 'title': title, 'task_type': task_type,
                'scheduled_time': scheduled_time,
                'scheduled_date': scheduled_date,
                'recurrence': recurrence, 'status': 'pending',
                'priority': priority, 'description': description
            }
        return None

    except Exception as e:
        logger.error(f"create_task error: {e}")
        return None
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def get_tasks(user_id, status=None, task_type=None, date_filter=None):
    """
    Získat úkoly uživatele s volitelnými filtry.
    """
    if not _DB_AVAILABLE:
        return []

    db = None
    try:
        db = get_connection()
        p = _p()

        query = f"SELECT * FROM radim_tasks WHERE user_id = {p}"
        params = [user_id]

        if status:
            query += f" AND status = {p}"
            params.append(status)
        if task_type:
            query += f" AND task_type = {p}"
            params.append(task_type)
        if date_filter:
            query += f" AND (scheduled_date = {p} OR scheduled_date IS NULL)"
            params.append(date_filter)

        query += " ORDER BY scheduled_time ASC, priority DESC LIMIT 200"

        rows = db.execute(query, tuple(params)).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            # Serialize datetime objects
            for key in ['created_at', 'updated_at', 'completed_at']:
                if key in d and d[key] and hasattr(d[key], 'isoformat'):
                    d[key] = d[key].isoformat()
            if 'scheduled_date' in d and d['scheduled_date'] and hasattr(d['scheduled_date'], 'isoformat'):
                d['scheduled_date'] = d['scheduled_date'].isoformat()
            if 'scheduled_time' in d and d['scheduled_time'] and hasattr(d['scheduled_time'], 'isoformat'):
                d['scheduled_time'] = d['scheduled_time'].isoformat()
            # Parse metadata
            if 'metadata' in d and isinstance(d['metadata'], str):
                try:
                    d['metadata'] = json.loads(d['metadata'])
                except (json.JSONDecodeError, TypeError):
                    d['metadata'] = {}
            result.append(d)

        return result

    except Exception as e:
        logger.error(f"get_tasks error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def complete_task(task_id, user_id):
    """Označit úkol jako splněný."""
    if not _DB_AVAILABLE:
        return False

    db = None
    try:
        db = get_connection()
        p = _p()
        now = datetime.utcnow()

        db.execute(
            f"""UPDATE radim_tasks
                SET status = 'done', completed_at = {p}, updated_at = {p}
                WHERE id = {p} AND user_id = {p}""",
            (now, now, task_id, user_id)
        )
        db.commit()

        logger.info(f"✅ Task #{task_id} completed by {user_id}")
        return True

    except Exception as e:
        logger.error(f"complete_task error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def delete_task(task_id, user_id):
    """Smazat úkol."""
    if not _DB_AVAILABLE:
        return False

    db = None
    try:
        db = get_connection()
        p = _p()

        db.execute(
            f"DELETE FROM radim_tasks WHERE id = {p} AND user_id = {p}",
            (task_id, user_id)
        )
        db.commit()

        logger.info(f"🗑️ Task #{task_id} deleted by {user_id}")
        return True

    except Exception as e:
        logger.error(f"delete_task error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def get_due_tasks(user_id, window_minutes=30):
    """
    Získat úkoly, které jsou splatné v příštích N minutách.
    """
    if not _DB_AVAILABLE:
        return []

    db = None
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')
        future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M:%S')
        current_date = now.date().isoformat()

        db = get_connection()
        p = _p()

        rows = db.execute(
            f"""SELECT * FROM radim_tasks
                WHERE user_id = {p} AND status = 'pending'
                AND scheduled_time IS NOT NULL
                AND (scheduled_date = {p} OR scheduled_date IS NULL OR recurrence != 'once')
                AND scheduled_time >= {p} AND scheduled_time <= {p}
                ORDER BY scheduled_time""",
            (user_id, current_date, current_time, future_time)
        ).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:
        logger.error(f"get_due_tasks error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


# ============================================
# SCHEDULER HELPERS (v231 — background reminder checks)
# ============================================

def get_all_due_tasks(window_minutes=5):
    """
    Získat VŠECHNY splatné úkoly napříč uživateli (pro scheduler).
    """
    if not _DB_AVAILABLE:
        return []

    db = None
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M')
        current_date = now.date().isoformat()

        db = get_connection()
        p = _p()

        rows = db.execute(
            f"""SELECT * FROM radim_tasks
                WHERE status = 'pending'
                AND scheduled_time IS NOT NULL
                AND (scheduled_date = {p} OR scheduled_date IS NULL OR recurrence != 'once')
                AND scheduled_time >= {p} AND scheduled_time <= {p}
                ORDER BY scheduled_time""",
            (current_date, current_time, future_time)
        ).fetchall()

        # Filter out already-notified tasks
        results = []
        for r in rows:
            d = dict(r)
            meta = {}
            if d.get('metadata'):
                try:
                    meta = json.loads(d['metadata']) if isinstance(d['metadata'], str) else d['metadata']
                except (json.JSONDecodeError, TypeError):
                    pass
            if not meta.get('notified'):
                results.append(d)

        return results

    except Exception as e:
        logger.error(f"get_all_due_tasks error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def mark_task_notified(task_id):
    """Označit úkol jako notifikovaný (zabránit dvojitému odeslání)."""
    if not _DB_AVAILABLE:
        return False

    db = None
    try:
        db = get_connection()
        p = _p()

        # Read existing metadata
        row = db.execute(
            f"SELECT metadata FROM radim_tasks WHERE id = {p}", (task_id,)
        ).fetchone()

        meta = {}
        if row and row['metadata']:
            try:
                meta = json.loads(row['metadata']) if isinstance(row['metadata'], str) else dict(row['metadata'])
            except (json.JSONDecodeError, TypeError):
                pass

        meta['notified'] = True
        meta['notified_at'] = datetime.now().isoformat()

        db.execute(
            f"UPDATE radim_tasks SET metadata = {p} WHERE id = {p}",
            (json.dumps(meta), task_id)
        )
        db.commit()

        logger.info(f"🔔 Task #{task_id} marked as notified")
        return True

    except Exception as e:
        logger.error(f"mark_task_notified error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


# ============================================
# MEDICATION LOG
# ============================================

def log_medication(user_id, medication_name, task_id=None, dosage=None, notes=None):
    """
    Zaznamenat užití léku.
    """
    if not _DB_AVAILABLE:
        return False

    db = None
    try:
        db = get_connection()
        p = _p()

        db.execute(
            f"""INSERT INTO radim_medication_log
                (user_id, task_id, medication_name, dosage, notes)
                VALUES ({p},{p},{p},{p},{p})""",
            (user_id, task_id, medication_name, dosage, notes)
        )
        db.commit()

        logger.info(f"💊 Medication logged: {medication_name} for {user_id}")
        return True

    except Exception as e:
        logger.error(f"log_medication error: {e}")
        return False
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def get_medication_history(user_id, days=7):
    """
    Získat historii užívání léků za posledních N dní.
    """
    if not _DB_AVAILABLE:
        return []

    db = None
    try:
        db = get_connection()
        p = _p()
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()

        rows = db.execute(
            f"""SELECT * FROM radim_medication_log
                WHERE user_id = {p} AND taken_at >= {p}
                ORDER BY taken_at DESC LIMIT 500""",
            (user_id, since)
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            if 'taken_at' in d and d['taken_at'] and hasattr(d['taken_at'], 'isoformat'):
                d['taken_at'] = d['taken_at'].isoformat()
            result.append(d)
        return result

    except Exception as e:
        logger.error(f"get_medication_history error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


# ============================================
# CHAT INTEGRATION — context pro system prompt
# ============================================

def build_tasks_context(user_id):
    """
    Sestavit kontext o úkolech uživatele pro injekci do system promptu.
    Radim tak bude vědět o čekajících úkolech a může na ně reagovat.
    """
    try:
        today = date.today().isoformat()
        tasks = get_tasks(user_id, status='pending', date_filter=today)

        if not tasks:
            return ""

        type_emoji = {
            'medication': '💊', 'reminder': '🔔',
            'appointment': '📅', 'custom': '📌'
        }

        lines = ["\n═══ DNEŠNÍ ÚKOLY A PŘIPOMÍNKY ═══"]
        for t in tasks[:8]:  # Max 8 úkolů v kontextu
            emoji = type_emoji.get(t.get('task_type', 'reminder'), '📌')
            time_str = ""
            if t.get('scheduled_time'):
                time_val = t['scheduled_time']
                if isinstance(time_val, str):
                    time_str = f" v {time_val[:5]}"
                elif hasattr(time_val, 'strftime'):
                    time_str = f" v {time_val.strftime('%H:%M')}"
            lines.append(f"- {emoji} {t['title']}{time_str}")

        lines.append(f"Celkem: {len(tasks)} úkol(ů) na dnes.")
        lines.append("Pokud se uživatel zeptá na úkoly, zmíň je. Pokud se blíží čas, jemně připomeň.")
        lines.append("═══════════════════════════════════")

        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"build_tasks_context warning: {e}")
        return ""
