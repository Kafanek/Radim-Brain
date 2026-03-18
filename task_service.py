# -*- coding: utf-8 -*-
"""
RADIM Task & Medication Service v2.0.0
Persistentní úkoly, připomínky a sledování léků.

v2.0: db_context, unified ? placeholders, killed _p()
"""

import json
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)

try:
    from database import db_context, db_insert
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("task_service: database module not available")


# ============================================
# TASK CRUD
# ============================================

def create_task(user_id, title, task_type='reminder', scheduled_time=None,
                scheduled_date=None, recurrence='once', priority='normal',
                description=None, metadata=None):
    """Vytvořit nový úkol. Vrací dict s ID."""
    if not _DB_AVAILABLE:
        return None
    try:
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        if scheduled_date is None and scheduled_time is not None:
            scheduled_date = date.today().isoformat()

        with db_context(commit=True) as db:
            task_id = db_insert(db, 'radim_tasks',
                ['user_id', 'title', 'task_type', 'scheduled_time', 'scheduled_date',
                 'recurrence', 'priority', 'description', 'metadata'],
                (user_id, title, task_type, scheduled_time, scheduled_date,
                 recurrence, priority, description, meta_json)
            )

        if task_id:
            logger.info(f"Task created: #{task_id} '{title}' for {user_id}")
            return {
                'id': task_id, 'title': title, 'task_type': task_type,
                'scheduled_time': scheduled_time, 'scheduled_date': scheduled_date,
                'recurrence': recurrence, 'status': 'pending',
                'priority': priority, 'description': description
            }
        return None
    except Exception as e:
        logger.error(f"create_task error: {e}")
        return None


def get_tasks(user_id, status=None, task_type=None, date_filter=None):
    """Získat úkoly uživatele s volitelnými filtry."""
    if not _DB_AVAILABLE:
        return []
    try:
        with db_context() as db:
            query = "SELECT * FROM radim_tasks WHERE user_id = ?"
            params = [user_id]

            if status:
                query += " AND status = ?"
                params.append(status)
            if task_type:
                query += " AND task_type = ?"
                params.append(task_type)
            if date_filter:
                query += " AND (scheduled_date = ? OR scheduled_date IS NULL)"
                params.append(date_filter)

            query += " ORDER BY scheduled_time ASC, priority DESC LIMIT 200"
            rows = db.execute(query, tuple(params)).fetchall()

            result = []
            for r in rows:
                d = dict(r)
                for key in ['created_at', 'updated_at', 'completed_at']:
                    if key in d and d[key] and hasattr(d[key], 'isoformat'):
                        d[key] = d[key].isoformat()
                for key in ['scheduled_date', 'scheduled_time']:
                    if key in d and d[key] and hasattr(d[key], 'isoformat'):
                        d[key] = d[key].isoformat()
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


def complete_task(task_id, user_id):
    """Označit úkol jako splněný."""
    if not _DB_AVAILABLE:
        return False
    try:
        now = datetime.utcnow()
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE radim_tasks SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (now, now, task_id, user_id)
            )
        logger.info(f"Task #{task_id} completed by {user_id}")
        return True
    except Exception as e:
        logger.error(f"complete_task error: {e}")
        return False


def delete_task(task_id, user_id):
    """Smazat úkol."""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM radim_tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        logger.info(f"Task #{task_id} deleted by {user_id}")
        return True
    except Exception as e:
        logger.error(f"delete_task error: {e}")
        return False


def get_due_tasks(user_id, window_minutes=30):
    """Získat úkoly, které jsou splatné v příštích N minutách."""
    if not _DB_AVAILABLE:
        return []
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')
        future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M:%S')
        current_date = now.date().isoformat()

        with db_context() as db:
            rows = db.execute(
                "SELECT * FROM radim_tasks WHERE user_id = ? AND status = 'pending' "
                "AND scheduled_time IS NOT NULL "
                "AND (scheduled_date = ? OR scheduled_date IS NULL OR recurrence != 'once') "
                "AND scheduled_time >= ? AND scheduled_time <= ? ORDER BY scheduled_time",
                (user_id, current_date, current_time, future_time)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_due_tasks error: {e}")
        return []


# ============================================
# SCHEDULER HELPERS
# ============================================

def get_all_due_tasks(window_minutes=5):
    """Získat VŠECHNY splatné úkoly napříč uživateli (pro scheduler)."""
    if not _DB_AVAILABLE:
        return []
    try:
        now = datetime.now()
        current_time = now.strftime('%H:%M')
        future_time = (now + timedelta(minutes=window_minutes)).strftime('%H:%M')
        current_date = now.date().isoformat()

        with db_context() as db:
            rows = db.execute(
                "SELECT * FROM radim_tasks WHERE status = 'pending' "
                "AND scheduled_time IS NOT NULL "
                "AND (scheduled_date = ? OR scheduled_date IS NULL OR recurrence != 'once') "
                "AND scheduled_time >= ? AND scheduled_time <= ? ORDER BY scheduled_time",
                (current_date, current_time, future_time)
            ).fetchall()

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


def mark_task_notified(task_id):
    """Označit úkol jako notifikovaný."""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            row = db.execute("SELECT metadata FROM radim_tasks WHERE id = ?", (task_id,)).fetchone()

            meta = {}
            if row and row['metadata']:
                try:
                    meta = json.loads(row['metadata']) if isinstance(row['metadata'], str) else dict(row['metadata'])
                except (json.JSONDecodeError, TypeError):
                    pass

            meta['notified'] = True
            meta['notified_at'] = datetime.now().isoformat()

            db.execute("UPDATE radim_tasks SET metadata = ? WHERE id = ?", (json.dumps(meta), task_id))

        logger.info(f"Task #{task_id} marked as notified")
        return True
    except Exception as e:
        logger.error(f"mark_task_notified error: {e}")
        return False


# ============================================
# MEDICATION LOG
# ============================================

def log_medication(user_id, medication_name, task_id=None, dosage=None, notes=None):
    """Zaznamenat užití léku. Includes double-dose protection (2h window)."""
    if not _DB_AVAILABLE:
        return False
    try:
        with db_context(commit=True) as db:
            two_hours_ago = (datetime.utcnow() - timedelta(hours=2)).isoformat()
            recent = db.execute(
                "SELECT id, taken_at FROM radim_medication_log "
                "WHERE user_id = ? AND medication_name = ? AND taken_at > ? ORDER BY taken_at DESC LIMIT 1",
                (user_id, medication_name, two_hours_ago)
            ).fetchone()

            if recent:
                recent_time = recent['taken_at'] if isinstance(recent, dict) else recent[1]
                logger.warning(f"DOUBLE-DOSE WARNING: {medication_name} for {user_id} — already taken at {recent_time}")
                db.execute(
                    "INSERT INTO radim_medication_log (user_id, task_id, medication_name, dosage, notes) VALUES (?,?,?,?,?)",
                    (user_id, task_id, medication_name, dosage,
                     f"MOŽNÝ DVOJITÝ DÁVEK — předchozí v {recent_time}. {notes or ''}")
                )
                return {'logged': True, 'double_dose_warning': True, 'previous_at': str(recent_time)}

            db.execute(
                "INSERT INTO radim_medication_log (user_id, task_id, medication_name, dosage, notes) VALUES (?,?,?,?,?)",
                (user_id, task_id, medication_name, dosage, notes)
            )

        logger.info(f"Medication logged: {medication_name} for {user_id}")
        return True
    except Exception as e:
        logger.error(f"log_medication error: {e}")
        return False


def get_medication_history(user_id, days=7):
    """Získat historii užívání léků za posledních N dní."""
    if not _DB_AVAILABLE:
        return []
    try:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with db_context() as db:
            rows = db.execute(
                "SELECT * FROM radim_medication_log WHERE user_id = ? AND taken_at >= ? ORDER BY taken_at DESC LIMIT 500",
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


# ============================================
# CHAT INTEGRATION — context pro system prompt
# ============================================

def build_tasks_context(user_id):
    """Sestavit kontext o úkolech pro injekci do system promptu."""
    try:
        today = date.today().isoformat()
        tasks = get_tasks(user_id, status='pending', date_filter=today)

        if not tasks:
            return ""

        type_emoji = {'medication': '\U0001f48a', 'reminder': '\U0001f514', 'appointment': '\U0001f4c5', 'custom': '\U0001f4cc'}

        lines = ["\n=== DNEŠNÍ ÚKOLY A PŘIPOMÍNKY ==="]
        for t in tasks[:8]:
            emoji = type_emoji.get(t.get('task_type', 'reminder'), '\U0001f4cc')
            time_str = ""
            if t.get('scheduled_time'):
                time_val = t['scheduled_time']
                if isinstance(time_val, str):
                    time_str = f" v {time_val[:5]}"
                elif hasattr(time_val, 'strftime'):
                    time_str = f" v {time_val.strftime('%H:%M')}"
            lines.append(f"- {emoji} {t['title']}{time_str}")

        lines.append(f"Celkem: {len(tasks)} ukol(u) na dnes.")
        lines.append("Pokud se uzivatel zepta na ukoly, zmin je.")
        lines.append("=================================")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"build_tasks_context warning: {e}")
        return ""
