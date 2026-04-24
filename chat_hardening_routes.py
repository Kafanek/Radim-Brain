"""
🛡️ Sprint P — Production hardening for Komunikace
  - chat_audit table + GET /api/chat/audit/<user_id>
  - GET /api/chat/export/<user_id>     — GDPR data dump
  - GET /api/chat/health                — stats + uptime
  - POST /api/chat/audit                — log custom event from frontend
"""
from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, jsonify, request

from auth_middleware import optional_auth, require_auth
from flask import g as _g
from database import db_context, is_postgres, db_insert

logger = logging.getLogger(__name__)
chat_hardening_bp = Blueprint('chat_hardening', __name__)

_BOOT_TS = time.time()
_AUDIT_INITIALIZED = False


def _init_audit_schema():
    """Lazy-create chat_audit table on first use."""
    global _AUDIT_INITIALIZED
    if _AUDIT_INITIALIZED:
        return
    try:
        with db_context(commit=True) as db:
            if is_postgres():
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_audit (
                        id SERIAL PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        target_type TEXT,
                        target_id TEXT,
                        metadata JSONB DEFAULT '{}'::jsonb,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_chat_audit_user_time ON chat_audit(user_id, created_at DESC)")
            else:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        target_type TEXT,
                        target_id TEXT,
                        metadata TEXT DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                db.execute("CREATE INDEX IF NOT EXISTS idx_chat_audit_user_time ON chat_audit(user_id, created_at DESC)")
        _AUDIT_INITIALIZED = True
        logger.info("✅ chat_audit table ready")
    except Exception as e:
        logger.error(f"chat_audit init: {e}")


def _log_audit(user_id, action, target_type=None, target_id=None, metadata=None):
    """Public helper — other modules can call this to log."""
    _init_audit_schema()
    if not user_id or not action:
        return
    try:
        with db_context(commit=True) as db:
            db_insert(db, 'chat_audit',
                      ['user_id', 'action', 'target_type', 'target_id', 'metadata'],
                      [str(user_id)[:80], str(action)[:60],
                       (str(target_type)[:40] if target_type else None),
                       (str(target_id)[:80] if target_id else None),
                       json.dumps(metadata or {}, ensure_ascii=False)])
    except Exception as e:
        logger.warning(f'_log_audit failed: {e}')


# ──────────────────────────────────────────────────────────────────
# GET /api/chat/audit/<user_id> — list user's recent actions
# ──────────────────────────────────────────────────────────────────

@chat_hardening_bp.route('/api/chat/audit/<user_id>', methods=['GET'])
@require_auth
def get_audit(user_id):
    _init_audit_schema()
    # Sprint W security: enforce user_id matches auth'd user (IDOR protection)
    auth_uid = str((getattr(_g, 'auth_user', None) or {}).get('id') or '')
    if not auth_uid:
        return jsonify({'success': False, 'error': 'Auth required'}), 401
    if auth_uid != str(user_id):
        return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403
    try:
        limit = min(int(request.args.get('limit', 50)), 500)
        with db_context() as db:
            cursor = db.execute(
                "SELECT id, user_id, action, target_type, target_id, metadata, created_at "
                "FROM chat_audit WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (str(user_id), limit)
            )
            rows = []
            for row in cursor.fetchall():
                d = dict(row) if hasattr(row, 'keys') else {
                    'id': row[0], 'user_id': row[1], 'action': row[2],
                    'target_type': row[3], 'target_id': row[4],
                    'metadata': row[5], 'created_at': row[6],
                }
                meta = d.get('metadata')
                if isinstance(meta, str):
                    try: d['metadata'] = json.loads(meta)
                    except: d['metadata'] = {}
                rows.append(d)
        return jsonify({'success': True, 'audit': rows, 'count': len(rows)})
    except Exception as e:
        logger.error(f'get_audit: {e}')
        return jsonify({'success': False, 'error': 'Interní chyba'}), 500


# ──────────────────────────────────────────────────────────────────
# POST /api/chat/audit — log custom event (frontend side)
# ──────────────────────────────────────────────────────────────────

@chat_hardening_bp.route('/api/chat/audit', methods=['POST'])
@require_auth
def post_audit():
    try:
        data = request.get_json() or {}
        # Sprint W: force user_id from auth, ignore client-supplied userId (IDOR fix)
        auth_uid = str((getattr(_g, 'auth_user', None) or {}).get('id') or '')
        if not auth_uid:
            return jsonify({'success': False, 'error': 'Auth required'}), 401
        user_id = auth_uid
        action = str(data.get('action') or '')
        if not action:
            return jsonify({'success': False, 'error': 'Chybí action'}), 400
        _log_audit(
            user_id=user_id,
            action=action,
            target_type=data.get('targetType'),
            target_id=data.get('targetId'),
            metadata=data.get('metadata') or {},
        )
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f'post_audit: {e}')
        return jsonify({'success': False, 'error': 'Interní chyba'}), 500


# ──────────────────────────────────────────────────────────────────
# GET /api/chat/export/<user_id> — GDPR data dump
# ──────────────────────────────────────────────────────────────────

@chat_hardening_bp.route('/api/chat/export/<user_id>', methods=['GET'])
@require_auth
def export_data(user_id):
    """Return all conversations + messages where user_id is participant or sender.
    For GDPR Article 15 (right of access) compliance.
    Sprint W: enforce user_id matches auth'd user (IDOR protection)."""
    auth_uid = str((getattr(_g, 'auth_user', None) or {}).get('id') or '')
    if not auth_uid:
        return jsonify({'success': False, 'error': 'Auth required'}), 401
    if auth_uid != str(user_id):
        return jsonify({'success': False, 'error': 'Přístup odepřen'}), 403
    try:
        with db_context() as db:
            # Conversations user participates in
            cursor = db.execute(
                "SELECT * FROM chat_conversations WHERE participants LIKE ? "
                "ORDER BY updated_at DESC",
                (f'%"{user_id}"%',)
            )
            conversations = []
            conv_ids = []
            for row in cursor.fetchall():
                d = dict(row) if hasattr(row, 'keys') else {}
                if d.get('participants'):
                    try: d['participants'] = json.loads(d['participants'])
                    except: pass
                if d.get('settings'):
                    try: d['settings'] = json.loads(d['settings'])
                    except: pass
                if d.get('last_message'):
                    try: d['last_message'] = json.loads(d['last_message'])
                    except: pass
                conversations.append(d)
                conv_ids.append(d.get('id'))

            # Messages from those conversations OR sent by user
            messages = []
            if conv_ids:
                placeholders = ','.join(['?'] * len(conv_ids))
                cursor = db.execute(
                    f"SELECT * FROM chat_messages WHERE conversation_id IN ({placeholders}) "
                    f"ORDER BY timestamp ASC",
                    conv_ids
                )
                for row in cursor.fetchall():
                    m = dict(row) if hasattr(row, 'keys') else {}
                    for k in ('reactions', 'read_by', 'metadata'):
                        if m.get(k) and isinstance(m[k], str):
                            try: m[k] = json.loads(m[k])
                            except: m[k] = None
                    messages.append(m)

            # Audit log
            _init_audit_schema()
            cursor = db.execute(
                "SELECT * FROM chat_audit WHERE user_id = ? ORDER BY created_at DESC LIMIT 1000",
                (user_id,)
            )
            audit = []
            for row in cursor.fetchall():
                a = dict(row) if hasattr(row, 'keys') else {}
                if a.get('metadata') and isinstance(a['metadata'], str):
                    try: a['metadata'] = json.loads(a['metadata'])
                    except: pass
                audit.append(a)

        return jsonify({
            'success': True,
            'exportedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'userId': user_id,
            'gdpr_notice': (
                'Tento export obsahuje veškerá vaše data v Komunikaci dle GDPR čl. 15. '
                'Můžete jej uchovat, předat nebo požádat o smazání kontaktováním '
                'správce na info@radimcare.cz.'
            ),
            'conversations': conversations,
            'messages': messages,
            'audit': audit,
            'counts': {
                'conversations': len(conversations),
                'messages': len(messages),
                'audit_entries': len(audit),
            },
        })
    except Exception as e:
        logger.error(f'export_data: {e}')
        return jsonify({'success': False, 'error': 'Interní chyba'}), 500


# ──────────────────────────────────────────────────────────────────
# GET /api/chat/health — stats + uptime
# ──────────────────────────────────────────────────────────────────

@chat_hardening_bp.route('/api/chat/health', methods=['GET'])
def chat_health():
    started = time.time()
    try:
        with db_context() as db:
            cursor = db.execute("SELECT COUNT(*) FROM chat_conversations")
            conv_count = cursor.fetchone()[0]
            cursor = db.execute("SELECT COUNT(*) FROM chat_messages")
            msg_count = cursor.fetchone()[0]
            # Messages last 24h
            try:
                if is_postgres():
                    cursor = db.execute(
                        "SELECT COUNT(*) FROM chat_messages "
                        "WHERE timestamp > NOW() - INTERVAL '24 hours'"
                    )
                else:
                    cursor = db.execute(
                        "SELECT COUNT(*) FROM chat_messages "
                        "WHERE datetime(timestamp) > datetime('now', '-24 hours')"
                    )
                msgs_24h = cursor.fetchone()[0]
            except Exception:
                msgs_24h = None
        latency_ms = int((time.time() - started) * 1000)
        return jsonify({
            'success': True,
            'status': 'ok',
            'uptime_seconds': int(time.time() - _BOOT_TS),
            'db_latency_ms': latency_ms,
            'stats': {
                'conversations_total': conv_count,
                'messages_total': msg_count,
                'messages_24h': msgs_24h,
            },
        })
    except Exception as e:
        logger.error(f'chat_health: {e}')
        return jsonify({
            'success': False, 'status': 'degraded',
            'error': str(e)[:120],
        }), 503
