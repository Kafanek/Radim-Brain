# -*- coding: utf-8 -*-
"""
RADIM MEMORY HELPERS — DB layer, communication strategies, analysis
Extracted from memory_routes.py for modularity.

Version: 3.0.0 — db_context, unified ? placeholders
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
    from database import is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False
    logger.warning("database module not available - memory will not persist")

MAX_HISTORY = 50  # Posledních 50 zpráv v DB


def db_available():
    """Check if database is available."""
    return _DB_AVAILABLE


# ============================================================================
# GDPR CONSENT — kontrola souhlasu s ukládáním dat
# ============================================================================

def get_gdpr_consent(user_id: str) -> dict:
    """Načti GDPR souhlas uživatele z profilu."""
    profile = db_load_profile(user_id)
    return profile.get("gdpr_consent", {
        "data_processing": False,
        "chat_history": False,
        "health_data": False,
    })


def audit_log(user_id: str, action: str, resource: str = None, detail: str = None, ip_address: str = None):
    """Zapiš audit log záznam — DELEGUJE na audit_log.audit() pro hash chain.

    v8.19.108: Předtím direct INSERT bez hashování → ~99 % auditních řádků
    mělo current_hash=NULL. Teď delegujeme na hashing audit() funkci,
    všichni existující volači beze změny kódu.

    Mapování:
      user_id    → actor_user_id (override default z g.auth_user)
      action     → action (zachováno)
      resource   → resource_type
      detail     → reason (krátké) nebo metadata.legacy_detail (delší)
      ip_address → metadata.legacy_ip (audit() jinak vezme z request)
    """
    try:
        from audit_log import audit  # náš modul, ne self-recursion (jiný name space)
        meta = {}
        if ip_address:
            meta['legacy_ip'] = ip_address
        if detail and len(str(detail)) > 512:
            meta['legacy_detail'] = str(detail)[:4096]
            reason_arg = None
        else:
            reason_arg = detail
        audit(
            action,
            actor_user_id=user_id,
            resource_type=resource,
            reason=reason_arg,
            metadata=(meta or None),
        )
    except Exception as e:
        logger.warning(f"Audit log delegation error (non-fatal): {e}")


def save_gdpr_consent(user_id: str, consent: dict):
    """Ulož GDPR souhlas do profilu uživatele."""
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
    try:
        with db_context() as db:
            row = db.execute("SELECT data FROM memory_profiles WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                return row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
            return {}
    except Exception as e:
        logger.warning(f"DB load profile error: {e}")
        return {}


def db_save_profile(user_id: str, profile: dict):
    """Save user profile to DB"""
    if not _DB_AVAILABLE:
        return
    try:
        with db_context(commit=True) as db:
            data_json = json.dumps(profile, ensure_ascii=False)
            # PG uses ON CONFLICT ... DO UPDATE, SQLite uses INSERT OR REPLACE
            if is_postgres():
                db.execute(
                    "INSERT INTO memory_profiles (user_id, data, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
                    (user_id, data_json, datetime.utcnow())
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO memory_profiles (user_id, data, updated_at) VALUES (?, ?, ?)",
                    (user_id, data_json, datetime.utcnow().isoformat())
                )
    except Exception as e:
        logger.warning(f"DB save profile error: {e}")


def db_delete_profile(user_id: str):
    """Delete all user data from DB"""
    if not _DB_AVAILABLE:
        return
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM memory_profiles WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM memory_history WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM memory_learning WHERE user_id = ?", (user_id,))
    except Exception as e:
        logger.warning(f"DB delete profile error: {e}")


def db_load_history(user_id: str, limit: int = 50) -> list:
    """Load conversation history from DB"""
    if not _DB_AVAILABLE:
        return []
    try:
        with db_context() as db:
            rows = db.execute(
                "SELECT role, content, created_at FROM memory_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            messages = []
            for r in reversed(rows):
                ts = r['created_at']
                if hasattr(ts, 'isoformat'):
                    ts = ts.isoformat()
                messages.append({"role": r['role'], "content": r['content'], "timestamp": str(ts)})
            return messages
    except Exception as e:
        logger.warning(f"DB load history error: {e}")
        return []


def db_add_history(user_id: str, role: str, content: str):
    """Add message to conversation history in DB"""
    if not _DB_AVAILABLE:
        return
    try:
        with db_context(commit=True) as db:
            db.execute(
                "INSERT INTO memory_history (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content)
            )
            # Trim old messages — PG uses OFFSET, SQLite uses NOT IN + LIMIT
            if is_postgres():
                db.execute(
                    "DELETE FROM memory_history WHERE id IN ("
                    "SELECT id FROM memory_history WHERE user_id = ? ORDER BY created_at DESC OFFSET ?)",
                    (user_id, MAX_HISTORY)
                )
            else:
                db.execute(
                    "DELETE FROM memory_history WHERE id NOT IN ("
                    "SELECT id FROM memory_history WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
                    ") AND user_id = ?",
                    (user_id, MAX_HISTORY, user_id)
                )
    except Exception as e:
        logger.warning(f"DB add history error: {e}")

    # v10.45: trigger long-term memory summarization at 100-message boundary
    # (async, non-blocking)
    if role in ('user', 'assistant', 'radim'):
        try:
            from memory_summarization import maybe_summarize_on_message
            maybe_summarize_on_message(user_id)
        except Exception:
            pass


def db_clear_history(user_id: str):
    """Clear conversation history from DB"""
    if not _DB_AVAILABLE:
        return
    try:
        with db_context(commit=True) as db:
            db.execute("DELETE FROM memory_history WHERE user_id = ?", (user_id,))
    except Exception as e:
        logger.warning(f"DB clear history error: {e}")


def db_load_learning(user_id: str) -> dict:
    """Load learning data from DB"""
    if not _DB_AVAILABLE:
        return default_learning()
    try:
        with db_context() as db:
            row = db.execute("SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                data = row['data'] if isinstance(row['data'], dict) else json.loads(row['data'])
                defaults = default_learning()
                for k, v in defaults.items():
                    if k not in data:
                        data[k] = v
                return data
            return default_learning()
    except Exception as e:
        logger.warning(f"DB load learning error: {e}")
        return default_learning()


def db_save_learning(user_id: str, learning: dict):
    """Save learning data to DB"""
    if not _DB_AVAILABLE:
        return
    try:
        with db_context(commit=True) as db:
            data_json = json.dumps(learning, ensure_ascii=False)
            if is_postgres():
                db.execute(
                    "INSERT INTO memory_learning (user_id, data, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data, updated_at = EXCLUDED.updated_at",
                    (user_id, data_json, datetime.utcnow())
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO memory_learning (user_id, data, updated_at) VALUES (?, ?, ?)",
                    (user_id, data_json, datetime.utcnow().isoformat())
                )
    except Exception as e:
        logger.warning(f"DB save learning error: {e}")


def default_learning() -> dict:
    return {
        "topics": {},
        "preferred_length": "medium",
        "communication_style": "warm",
        "last_mood": "neutral",
        "interaction_count": 0,
        "successful_interactions": 0,
        "last_interaction": None,
        "C_history": [],
        "avg_C": None,
        "last_brain_mode": None,
        "crisis_count": 0
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

# Backward compat alias
_COMMUNICATION_NEEDS = COMMUNICATION_NEEDS
