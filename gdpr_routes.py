# -*- coding: utf-8 -*-
"""
🔒 RADIM GDPR ROUTES — Data export, erasure, retention, audit
GDPR čl. 17 (Právo být zapomenut), čl. 20 (Právo na přenositelnost)
Extracted from memory_routes.py for modularity.

Version: 1.0.0
"""

import json
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth
from memory_helpers import (
    db_available, db_load_profile, audit_log, get_gdpr_consent, save_gdpr_consent
)

logger = logging.getLogger(__name__)

gdpr_bp = Blueprint('gdpr', __name__, url_prefix='/api/memory')

try:
    from database import is_postgres, db_context
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# GDPR CONSENT SYNC (frontend → Heroku backend)
# ─────────────────────────────────────────────────────────────────────────────

@gdpr_bp.route('/gdpr-consent/<user_id>', methods=['POST'])
@require_auth
def sync_gdpr_consent(user_id):
    """Sync GDPR consent from WordPress/frontend to Heroku backend.
    Called after user grants/revokes consent in GDPR dialog."""
    data = request.get_json(silent=True) or {}
    consent = {
        "data_processing": bool(data.get("data_processing", False)),
        "chat_history": bool(data.get("chat_history", False)),
        "health_data": bool(data.get("health_data", False)),
    }
    save_gdpr_consent(user_id, consent)
    audit_log(user_id, "consent_change", "gdpr", str(consent), request.remote_addr)
    logger.info(f"🔒 [GDPR] Consent synced for user={user_id}: {consent}")

    # If user revoked chat_history consent, delete existing history
    if not consent["chat_history"]:
        try:
            with db_context(commit=True) as db:
                db.execute("DELETE FROM memory_history WHERE user_id = ?", (user_id,))
            logger.info(f"[GDPR] Chat history deleted for user={user_id} (consent revoked)")
        except Exception as e:
            logger.warning(f"GDPR history cleanup error: {e}")

    return jsonify({"success": True, "consent": consent})


@gdpr_bp.route('/gdpr-consent/<user_id>', methods=['GET'])
@require_auth
def get_gdpr_consent_route(user_id):
    """Get current GDPR consent status."""
    consent = get_gdpr_consent(user_id)
    return jsonify({"success": True, "consent": consent})


# ─────────────────────────────────────────────────────────────────────────────
# GDPR DATA EXPORT (čl. 20 — Právo na přenositelnost údajů)
# ─────────────────────────────────────────────────────────────────────────────

@gdpr_bp.route('/gdpr/export/<user_id>', methods=['GET'])
@require_auth
def gdpr_export(user_id):
    """Export všech osobních údajů uživatele ve strojově čitelném formátu (JSON).
    GDPR čl. 20 — Právo na přenositelnost údajů."""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403

    export_data = {
        "export_info": {
            "system": "Kolibri — Asistivní technologie pro seniory",
            "exported_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "format": "JSON (GDPR čl. 20)",
            "version": "1.0"
        },
        "profile": {},
        "gdpr_consent": {},
        "conversation_history": [],
        "learning_data": {},
        "iot_sensor_data": [],
        "iot_devices": [],
        "iot_alerts": [],
        "education_data": {},
        "audit_log": [],
        "safe_web_sessions": {
            "note": "Safe Web sessions (senior-facing browsing) are in-memory only with 15-min TTL and are never persisted. Only the aggregated audit trail below survives.",
            "active_session_count": 0,
            "audit_trail": []
        }
    }

    if not _DB_AVAILABLE:
        return jsonify({"success": False, "error": "Databáze není dostupná"}), 503

    try:
        with db_context() as db:
            # 1. Profil
            try:
                row = db.execute("SELECT data FROM memory_profiles WHERE user_id = ?", (user_id,)).fetchone()
                if row:
                    export_data["profile"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    export_data["gdpr_consent"] = export_data["profile"].get("gdpr_consent", {})
            except Exception as e:
                logger.debug(f"GDPR export profile: {e}")

            # 2. Historie konverzací
            try:
                for row in db.execute("SELECT role, content, created_at FROM memory_history WHERE user_id = ? ORDER BY created_at", (user_id,)).fetchall():
                    export_data["conversation_history"].append({"role": row[0], "content": row[1], "timestamp": str(row[2])})
            except Exception as e:
                logger.debug(f"GDPR export history: {e}")

            # 3. Učební data
            try:
                row = db.execute("SELECT data FROM memory_learning WHERE user_id = ?", (user_id,)).fetchone()
                if row:
                    export_data["learning_data"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception as e:
                logger.debug(f"GDPR export learning: {e}")

            # 4. IoT senzorová data
            try:
                for row in db.execute(
                    "SELECT device_id, sensor_type, value, unit, recorded_at FROM iot_sensor_data "
                    "WHERE room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) ORDER BY recorded_at DESC LIMIT 10000",
                    (user_id,)
                ).fetchall():
                    export_data["iot_sensor_data"].append({
                        "device_id": row[0], "sensor_type": row[1], "value": row[2], "unit": row[3], "timestamp": str(row[4])
                    })
            except Exception as e:
                logger.debug(f"GDPR export IoT data: {e}")

            # 5. IoT zařízení
            try:
                for row in db.execute("SELECT device_id, device_type, room_id, name, created_at FROM iot_devices WHERE user_id = ?", (user_id,)).fetchall():
                    export_data["iot_devices"].append({"device_id": row[0], "type": row[1], "room": row[2], "name": row[3], "installed": str(row[4])})
            except Exception as e:
                logger.debug(f"GDPR export IoT devices: {e}")

            # 6. IoT alerty
            try:
                for row in db.execute(
                    "SELECT alert_type, severity, message, resolved, created_at FROM iot_alerts "
                    "WHERE room_id IN (SELECT room_id FROM iot_devices WHERE user_id = ?) ORDER BY created_at DESC LIMIT 1000",
                    (user_id,)
                ).fetchall():
                    export_data["iot_alerts"].append({"type": row[0], "severity": row[1], "message": row[2], "resolved": bool(row[3]), "timestamp": str(row[4])})
            except Exception as e:
                logger.debug(f"GDPR export alerts: {e}")

            # 7. Vzdělávací data
            try:
                row = db.execute("SELECT data FROM education_profiles WHERE user_id = ?", (user_id,)).fetchone()
                if row:
                    export_data["education_data"]["profile"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            except Exception as e:
                logger.debug(f"GDPR export education: {e}")

            # 8. Audit log
            try:
                for row in db.execute(
                    "SELECT action, resource, detail, ip_address, created_at FROM audit_log WHERE user_id = ? ORDER BY created_at DESC LIMIT 500",
                    (user_id,)
                ).fetchall():
                    export_data["audit_log"].append({"action": row[0], "resource": row[1], "detail": row[2], "ip": row[3], "timestamp": str(row[4])})
            except Exception as e:
                logger.debug(f"GDPR export audit: {e}")

            # 9. Safe Web Agent — privacy-minimal audit trail (v10.36)
            try:
                for row in db.execute(
                    "SELECT observation_type, severity, message, details, created_at FROM agent_observations "
                    "WHERE user_id = ? AND observation_type LIKE 'safe_web_%' ORDER BY created_at DESC LIMIT 500",
                    (user_id,)
                ).fetchall():
                    export_data["safe_web_sessions"]["audit_trail"].append({
                        "type": row[0], "severity": row[1], "message": row[2],
                        "details": row[3] if isinstance(row[3], dict) else (json.loads(row[3]) if row[3] else {}),
                        "timestamp": str(row[4]),
                    })
            except Exception as e:
                logger.debug(f"GDPR export safe-web: {e}")

            # 9b. Active in-memory safe-web sessions for this user (not persisted)
            try:
                from browser_agent_safe import _safe_sessions, _safe_lock
                with _safe_lock:
                    uid = str(user_id)
                    export_data["safe_web_sessions"]["active_session_count"] = sum(
                        1 for s in _safe_sessions.values() if s.get("user_id") == uid
                    )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"GDPR export error: {e}")
        return jsonify({"success": False, "error": "Chyba při exportu dat"}), 500

    # Audit log záznam o exportu
    audit_log(user_id, "data_export", "all_user_data", "GDPR data export", request.remote_addr)

    logger.info(f"📦 [GDPR] Data exported for user={user_id}")

    return jsonify({
        "success": True,
        "export": export_data,
        "message": "Kompletní export osobních údajů dle GDPR čl. 20"
    })


# ─────────────────────────────────────────────────────────────────────────────
# GDPR KOMPLETNÍ VÝMAZ (čl. 17 — rozšířený o IoT a vzdělávací data)
# ─────────────────────────────────────────────────────────────────────────────

@gdpr_bp.route('/gdpr/erase/<user_id>', methods=['DELETE'])
@require_auth
def gdpr_full_erase(user_id):
    """Kompletní výmaz VŠECH osobních údajů uživatele.
    GDPR čl. 17 — Právo být zapomenut.
    Rozšířená verze: maže profil + historii + learning + IoT data + education."""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403

    if not _DB_AVAILABLE:
        return jsonify({"success": False, "error": "Databáze není dostupná"}), 503

    deleted = {
        "memory_profiles": 0,
        "memory_history": 0,
        "memory_learning": 0,
        "iot_sensor_data": 0,
        "iot_devices": 0,
        "iot_alerts": 0,
        "iot_alert_rules": 0,
        "education_profiles": 0,
        "education_progress": 0,
        "safe_web_sessions_inmemory": 0,
        "safe_web_observations": 0,
    }

    try:
        with db_context(commit=True) as db:
            # 1. Memory data
            for table in ["memory_profiles", "memory_history", "memory_learning"]:
                try:
                    cur = db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                    deleted[table] = cur.rowcount if hasattr(cur, 'rowcount') else 0
                except Exception as e:
                    logger.debug(f"GDPR erase {table}: {e}")

            # 2. IoT data
            try:
                cur = db.execute("SELECT DISTINCT room_id FROM iot_devices WHERE user_id = ?", (user_id,))
                room_ids = [row[0] for row in cur.fetchall()]

                if room_ids:
                    placeholders = ",".join(["?"] * len(room_ids))
                    for table in ["iot_sensor_data", "iot_alerts", "iot_alert_rules"]:
                        try:
                            cur = db.execute(f"DELETE FROM {table} WHERE room_id IN ({placeholders})", tuple(room_ids))
                            deleted[table] = cur.rowcount if hasattr(cur, 'rowcount') else 0
                        except Exception as e:
                            logger.debug(f"GDPR erase IoT {table}: {e}")

                cur = db.execute("DELETE FROM iot_devices WHERE user_id = ?", (user_id,))
                deleted["iot_devices"] = cur.rowcount if hasattr(cur, 'rowcount') else 0
            except Exception as e:
                logger.debug(f"GDPR erase IoT: {e}")

            # 3. Education data
            for table in ["education_profiles", "education_progress"]:
                try:
                    cur = db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
                    deleted[table] = cur.rowcount if hasattr(cur, 'rowcount') else 0
                except Exception as e:
                    logger.debug(f"GDPR erase {table}: {e}")

            # 4. Safe Web Agent — drop safe_web audit observations (v10.36)
            try:
                cur = db.execute(
                    "DELETE FROM agent_observations WHERE user_id = ? AND observation_type LIKE 'safe_web_%'",
                    (user_id,)
                )
                deleted["safe_web_observations"] = cur.rowcount if hasattr(cur, 'rowcount') else 0
            except Exception as e:
                logger.debug(f"GDPR erase safe_web audit: {e}")

    except Exception as e:
        logger.error(f"GDPR full erase error: {e}")
        return jsonify({"success": False, "error": "Chyba při mazání dat"}), 500

    # 5. Safe Web Agent — drop any in-memory sessions for this user (v10.36)
    try:
        from browser_agent_safe import _safe_sessions, _safe_lock
        with _safe_lock:
            uid = str(user_id)
            to_drop = [sid for sid, s in _safe_sessions.items() if s.get("user_id") == uid]
            for sid in to_drop:
                _safe_sessions.pop(sid, None)
            deleted["safe_web_sessions_inmemory"] = len(to_drop)
    except Exception as e:
        logger.debug(f"GDPR erase safe_web sessions: {e}")

    # Audit log — záznam o výmazu (tento záznam se uchovává!)
    audit_log(user_id, "data_delete", "all_user_data_full",
              f"GDPR full erase: {json.dumps(deleted)}", request.remote_addr)

    total = sum(deleted.values())
    logger.info(f"🗑️ [GDPR] Full erase for user={user_id}: {total} records deleted")

    return jsonify({
        "success": True,
        "message": f"Všechna osobní data smazána ({total} záznamů)",
        "deleted": deleted,
        "note": "Audit log o výmazu je uchován po dobu 36 měsíců pro prokázání splnění žádosti.",
        "timestamp": datetime.utcnow().isoformat()
    })


# ─────────────────────────────────────────────────────────────────────────────
# GDPR DATA RETENTION — automatická likvidace starých dat
# ─────────────────────────────────────────────────────────────────────────────

@gdpr_bp.route('/gdpr/retention/run', methods=['POST'])
@require_auth
def gdpr_retention_run():
    """Spustí automatickou likvidaci dat dle retencí (admin/dpo only).
    Volat z Heroku Scheduler nebo manuálně.

    v8.19.108:
      • Přidán explicit admin/dpo role check (předtím TODO bez ochrany)
      • audit_log retention nyní přes audit_log_archive_delete()
        SECURITY DEFINER fn — bypass append-only triggeru
    """
    # SEC FIX: pouze admin / dpo
    role = (g.auth_user or {}).get('role', '')
    if role not in ('administrator', 'admin', 'dpo'):
        try:
            from audit_log import audit, A
            audit(A.AUTH_ACCESS_DENIED, outcome='denied', severity='warning',
                  reason=f'role={role} attempted /gdpr/retention/run',
                  resource_type='gdpr_retention')
        except Exception:
            pass
        return jsonify({"success": False, "error": "Vyžaduje admin/DPO roli",
                        "code": "admin_required"}), 403

    if not _DB_AVAILABLE:
        return jsonify({"success": False, "error": "Databáze není dostupná"}), 503

    results = {}
    # Retention policies: table → (PG interval, SQLite interval)
    # Pozor: audit_log MUSÍ použít archive_delete fn (append-only trigger)
    _retention = [
        ("iot_sensor_data", "recorded_at", "30 days", "-30 days", "iot_sensor_data_30d"),
        ("memory_history", "created_at", "90 days", "-90 days", "memory_history_90d"),
        ("iot_alerts", "created_at", "24 months", "-24 months", "iot_alerts_24m"),
    ]
    try:
        with db_context(commit=True) as db:
            for table, col, pg_interval, sqlite_interval, key in _retention:
                try:
                    if is_postgres():
                        cur = db.execute(f"DELETE FROM {table} WHERE {col} < NOW() - INTERVAL '{pg_interval}'")
                    else:
                        cur = db.execute(f"DELETE FROM {table} WHERE {col} < datetime('now', '{sqlite_interval}')")
                    results[key] = cur.rowcount if hasattr(cur, 'rowcount') else 0
                except Exception as e:
                    results[key] = f"error: {str(e)[:120]}"

            # audit_log — přes archive_delete fn (bypass trigger)
            try:
                if is_postgres():
                    # Najdi staré IDčka, pak je všechny smaž přes fn
                    rows = db.execute(
                        "SELECT id FROM audit_log WHERE created_at < NOW() - INTERVAL '36 months' "
                        "LIMIT 5000"
                    ).fetchall()
                    if rows:
                        ids = [r[0] for r in rows]
                        cur = db.execute(
                            "SELECT audit_log_archive_delete(?::BIGINT[])",
                            (ids,)
                        )
                        n = cur.fetchone()[0] if hasattr(cur, 'fetchone') else len(ids)
                        results["audit_log_36m"] = n
                    else:
                        results["audit_log_36m"] = 0
                else:
                    cur = db.execute(
                        "DELETE FROM audit_log WHERE created_at < datetime('now', '-36 months')"
                    )
                    results["audit_log_36m"] = cur.rowcount if hasattr(cur, 'rowcount') else 0
            except Exception as e:
                results["audit_log_36m"] = f"error: {str(e)[:120]}"

    except Exception as e:
        logger.error(f"GDPR retention error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

    total = sum(v for v in results.values() if isinstance(v, int))
    audit_log("system", "data_delete", "retention_job",
              f"Retention run: {json.dumps(results)}", request.remote_addr)

    logger.info(f"🗑️ [GDPR] Retention run: {total} records deleted — {results}")

    return jsonify({
        "success": True,
        "message": f"Retence dokončena — {total} záznamů smazáno",
        "results": results,
        "timestamp": datetime.utcnow().isoformat()
    })


# ─────────────────────────────────────────────────────────────────────────────
# GDPR AUDIT LOG — přehled pro DPO
# ─────────────────────────────────────────────────────────────────────────────

@gdpr_bp.route('/gdpr/audit/<user_id>', methods=['GET'])
@require_auth
def gdpr_audit_log(user_id):
    """Přehled audit logů pro uživatele (pro DPO / uživatele samotného)."""
    auth_user_id = str(g.auth_user.get('id', ''))
    if auth_user_id and auth_user_id != str(user_id):
        return jsonify({"success": False, "error": "Přístup odepřen"}), 403

    if not _DB_AVAILABLE:
        return jsonify({"success": False, "error": "Databáze není dostupná"}), 503

    limit = request.args.get('limit', 100, type=int)
    logs = []
    try:
        with db_context() as db:
            for row in db.execute(
                f"SELECT action, resource, detail, ip_address, created_at FROM audit_log "
                f"WHERE user_id = ? ORDER BY created_at DESC LIMIT {min(limit, 500)}",
                (user_id,)
            ).fetchall():
                logs.append({"action": row[0], "resource": row[1], "detail": row[2], "ip": row[3], "timestamp": str(row[4])})
    except Exception as e:
        logger.warning(f"GDPR audit log read: {e}")

    return jsonify({
        "success": True,
        "user_id": user_id,
        "audit_logs": logs,
        "count": len(logs),
        "timestamp": datetime.utcnow().isoformat()
    })
