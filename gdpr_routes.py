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
    from database import get_connection, is_postgres, db_context
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
    data = request.get_json() or {}
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
        "audit_log": []
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
        "education_progress": 0
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

    except Exception as e:
        logger.error(f"GDPR full erase error: {e}")
        return jsonify({"success": False, "error": "Chyba při mazání dat"}), 500

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
    """Spustí automatickou likvidaci dat dle retencí (admin only).
    Volat z Heroku Scheduler nebo manuálně."""
    # TODO: přidat admin role check
    if not _DB_AVAILABLE:
        return jsonify({"success": False, "error": "Databáze není dostupná"}), 503

    results = {}
    # Retention policies: table → (PG interval, SQLite interval)
    _retention = [
        ("iot_sensor_data", "recorded_at", "30 days", "-30 days", "iot_sensor_data_30d"),
        ("memory_history", "created_at", "90 days", "-90 days", "memory_history_90d"),
        ("iot_alerts", "created_at", "24 months", "-24 months", "iot_alerts_24m"),
        ("audit_log", "created_at", "36 months", "-36 months", "audit_log_36m"),
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
                    results[key] = f"error: {e}"

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
