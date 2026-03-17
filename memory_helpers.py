# -*- coding: utf-8 -*-
"""
🧠 RADIM MEMORY HELPERS — DB layer, communication strategies, analysis
Extracted from memory_routes.py for modularity.

Version: 2.0.0
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE LAYER
# ============================================================================

try:
    from database import get_connection, is_postgres
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("⚠️ database module not available - memory will not persist")

MAX_HISTORY = 50  # Posledních 50 zpráv v DB


def db_available():
    """Check if database is available."""
    return _DB_AVAILABLE


# ============================================================================
# GDPR CONSENT — kontrola souhlasu s ukládáním dat
# ============================================================================

def get_gdpr_consent(user_id: str) -> dict:
    """Načti GDPR souhlas uživatele z profilu.
    Vrací dict s klíči: data_processing, chat_history, health_data (bool)"""
    profile = db_load_profile(user_id)
    return profile.get("gdpr_consent", {
        "data_processing": False,
        "chat_history": False,
        "health_data": False,
    })


def audit_log(user_id: str, action: str, resource: str = None, detail: str = None, ip_address: str = None):
    """Zapiš audit log záznam pro GDPR compliance.
    Actions: login, logout, consent_change, data_export, data_delete, chat_access, profile_access"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        if is_postgres():
            db.execute(
                "INSERT INTO audit_log (user_id, action, resource, detail, ip_address) VALUES (%s, %s, %s, %s, %s)",
                (user_id, action, resource, detail, ip_address)
            )
        else:
            db.execute(
                "INSERT INTO audit_log (user_id, action, resource, detail, ip_address) VALUES (?, ?, ?, ?, ?)",
                (user_id, action, resource, detail, ip_address)
            )
        db.commit()
    except Exception as e:
        logger.warning(f"Audit log write error (non-fatal): {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def save_gdpr_consent(user_id: str, consent: dict):
    """Ulož GDPR souhlas do profilu uživatele (Heroku PG)"""
    profile = db_load_profile(user_id)
    profile["gdpr_consent"] = {
        "data_processing": bool(consent.get("data_processing", False)),
        "chat_history": bool(consent.get("chat_history", False)),
        "health_data": bool(consent.get("health_data", False)),
        "updated_at": datetime.utcnow().isoformat(),
    }
    db_save_profile(user_id, profile)


# ============================================================================
# DB CRUD — Profile, History, Learning
# ============================================================================

def db_load_profile(user_id: str) -> dict:
    """Load user profile from DB"""
    if not _DB_AVAILABLE:
        return {}
    db = None
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_profiles WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_profiles WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            return data
        return {}
    except Exception as e:
        logger.warning(f"DB load profile error: {e}")
        return {}
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_save_profile(user_id: str, profile: dict):
    """Save user profile to DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        data_json = json.dumps(profile, ensure_ascii=False)
        if is_postgres():
            db.execute(
                """INSERT INTO memory_profiles (user_id, data, updated_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at""",
                (user_id, data_json, datetime.utcnow())
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO memory_profiles (user_id, data, updated_at) VALUES (?, ?, ?)",
                (user_id, data_json, datetime.utcnow().isoformat())
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB save profile error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_delete_profile(user_id: str):
    """Delete all user data from DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_profiles WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.execute(f"DELETE FROM memory_learning WHERE user_id = {p}", (user_id,))
        db.commit()
    except Exception as e:
        logger.warning(f"DB delete profile error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_load_history(user_id: str, limit: int = 50) -> list:
    """Load conversation history from DB"""
    if not _DB_AVAILABLE:
        return []
    db = None
    try:
        db = get_connection()
        if is_postgres():
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        # Reverse so oldest first
        messages = []
        for r in reversed(rows):
            ts = r['created_at']
            if hasattr(ts, 'isoformat'):
                ts = ts.isoformat()
            messages.append({
                "role": r['role'],
                "content": r['content'],
                "timestamp": str(ts)
            })
        return messages
    except Exception as e:
        logger.warning(f"DB load history error: {e}")
        return []
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_add_history(user_id: str, role: str, content: str):
    """Add message to conversation history in DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        if is_postgres():
            db.execute(
                "INSERT INTO memory_history (user_id, role, content) VALUES (%s, %s, %s)",
                (user_id, role, content)
            )
            # Trim old messages (keep last MAX_HISTORY)
            db.execute(
                """DELETE FROM memory_history WHERE id IN (
                    SELECT id FROM memory_history WHERE user_id = %s
                    ORDER BY created_at DESC OFFSET %s
                )""",
                (user_id, MAX_HISTORY)
            )
        else:
            db.execute(
                "INSERT INTO memory_history (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
            db.execute(
                """DELETE FROM memory_history WHERE id NOT IN (
                    SELECT id FROM memory_history WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT ?
                ) AND user_id = ?""",
                (user_id, MAX_HISTORY, user_id)
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB add history error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_clear_history(user_id: str):
    """Clear conversation history from DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        p = "%s" if is_postgres() else "?"
        db.execute(f"DELETE FROM memory_history WHERE user_id = {p}", (user_id,))
        db.commit()
    except Exception as e:
        logger.warning(f"DB clear history error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_load_learning(user_id: str) -> dict:
    """Load learning data from DB"""
    if not _DB_AVAILABLE:
        return default_learning()
    db = None
    try:
        db = get_connection()
        row = db.execute(
            "SELECT data FROM memory_learning WHERE user_id = %s" if is_postgres()
            else "SELECT data FROM memory_learning WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row:
            data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            # Ensure all keys exist
            defaults = default_learning()
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        return default_learning()
    except Exception as e:
        logger.warning(f"DB load learning error: {e}")
        return default_learning()
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def db_save_learning(user_id: str, learning: dict):
    """Save learning data to DB"""
    if not _DB_AVAILABLE:
        return
    db = None
    try:
        db = get_connection()
        data_json = json.dumps(learning, ensure_ascii=False)
        if is_postgres():
            db.execute(
                """INSERT INTO memory_learning (user_id, data, updated_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at""",
                (user_id, data_json, datetime.utcnow())
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO memory_learning (user_id, data, updated_at) VALUES (?, ?, ?)",
                (user_id, data_json, datetime.utcnow().isoformat())
            )
        db.commit()
    except Exception as e:
        logger.warning(f"DB save learning error: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass


def default_learning() -> dict:
    return {
        "topics": {},
        "preferred_length": "medium",
        "communication_style": "warm",
        "last_mood": "neutral",
        "interaction_count": 0,
        "successful_interactions": 0,
        "last_interaction": None,
        # v283: Brain state learning
        "C_history": [],          # Posledních 20 hodnot C pro výpočet baseline
        "avg_C": None,            # Klouzavý průměr C (= learned baseline_C)
        "last_brain_mode": None,  # Poslední brain mode (HARMONY/ALERT/CRISIS)
        "crisis_count": 0         # Počet krizových stavů pro trend
    }


# ============================================================================
# IMPORTS FROM COMMUNICATION NEEDS MODULE (+ re-exports for backward compat)
# ============================================================================

from communication_needs import (
    COMMUNICATION_NEEDS,
    get_communication_instructions,
    detect_topic,
    detect_mood,
)

# Backward compat alias (underscore-prefixed name used internally)
_COMMUNICATION_NEEDS = COMMUNICATION_NEEDS
