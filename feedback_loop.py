# ============================================
# 🔄 FEEDBACK LOOP — Did the recommendation help?
# ============================================
# After agent recommends something (exercise, quiz, call),
# tracks whether the senior followed through.
# Learns what works and what doesn't for each person.
# ============================================

import logging
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def record_recommendation(user_id: str, agent: str, action: str, details: str = ''):
    """Record that an agent made a recommendation."""
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT DEFAULT '',
                    followed BOOLEAN DEFAULT NULL,
                    feedback_at TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db.execute(
                "INSERT INTO agent_feedback (user_id, agent, action, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, agent, action, details, datetime.utcnow().isoformat())
            )
    except Exception as e:
        logger.debug(f"Feedback record error: {e}")


def check_followthrough(user_id: str, action: str) -> bool:
    """Check if user followed through on a recommendation in last 2h."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # Check if action was performed (e.g., quiz started after recommendation)
            row = db.execute("""
                SELECT COUNT(*) FROM brain_states
                WHERE user_id = ? AND created_at > ?
            """, (user_id, (datetime.utcnow() - timedelta(hours=2)).isoformat())).fetchone()
            return (row[0] or 0) > 0
    except Exception:
        return False


def update_feedback(user_id: str, agent: str, followed: bool):
    """Mark whether the user followed the recommendation."""
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute("""
                UPDATE agent_feedback
                SET followed = ?, feedback_at = ?
                WHERE user_id = ? AND agent = ? AND followed IS NULL
                ORDER BY created_at DESC LIMIT 1
            """, (followed, datetime.utcnow().isoformat(), user_id, agent))
    except Exception as e:
        logger.debug(f"Feedback update error: {e}")


def get_agent_effectiveness(user_id: str, agent: str = None) -> dict:
    """Get how effective an agent's recommendations are for this user."""
    try:
        from database import db_context
        with db_context(commit=False) as db:
            query = """
                SELECT agent,
                    COUNT(*) as total,
                    SUM(CASE WHEN followed = true THEN 1 ELSE 0 END) as followed,
                    SUM(CASE WHEN followed = false THEN 1 ELSE 0 END) as ignored
                FROM agent_feedback
                WHERE user_id = ?
            """
            params = [user_id]
            if agent:
                query += " AND agent = ?"
                params.append(agent)
            query += " GROUP BY agent"

            rows = db.execute(query, tuple(params)).fetchall()

        result = {}
        for r in (rows or []):
            total = r[1] or 1
            result[r[0]] = {
                'total': total,
                'followed': r[2] or 0,
                'ignored': r[3] or 0,
                'effectiveness': round((r[2] or 0) / total * 100, 1)
            }
        return result
    except Exception as e:
        return {'error': str(e)}


logger.info("🔄 Feedback Loop loaded — tracks recommendation effectiveness per agent per user")
