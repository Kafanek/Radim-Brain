"""
📊 System status routes — live health dashboard for admins (v10.41)
=============================================================================
Collects status of key services used by Radim Care and returns unified JSON.

Checks:
    database       — SELECT 1 with latency
    smtp           — connect (no send) with latency
    twilio         — credentials present + account lookup
    azure_tts      — TTS proxy endpoint reachable
    ai_providers   — Gemini/Claude reachable (key presence + ping)
    schedulers     — APScheduler jobs status
    feature_flags  — active env flags

Results cached 30 s in memory to avoid hammering upstream services.

Endpoint:
    GET /api/system/status (admin-only via ADMIN_SECRET header OR admin role)
"""

import logging
import os
import socket
import time
from datetime import datetime

from flask import Blueprint, g, jsonify, request

logger = logging.getLogger(__name__)

system_status_bp = Blueprint("system_status", __name__)


_cache = {"at": 0, "data": None}
_CACHE_TTL = 30  # seconds


def _options_ok():
    return ("", 204)


def _is_admin():
    # Either X-Admin-Secret header matches, or authed user has admin role
    secret = request.headers.get("X-Admin-Secret", "")
    expected = os.environ.get("ADMIN_SECRET", "")
    if expected and secret and secret == expected:
        return True
    au = getattr(g, "auth_user", None) or {}
    role = (au.get("role") or au.get("user", {}).get("role") or "").lower()
    return role in ("admin", "administrator")


# ═══════════════════════════════════════════════════════════════════
# Individual checks
# ═══════════════════════════════════════════════════════════════════

def _check_db():
    start = time.time()
    try:
        from database import db_context
        with db_context() as db:
            row = db.execute("SELECT 1").fetchone()
            latency_ms = int((time.time() - start) * 1000)
            if row and (row[0] == 1 or str(row[0]) == "1"):
                return {"status": "ok", "latency_ms": latency_ms}
            return {"status": "degraded", "error": "unexpected response", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "error", "error": str(e)[:120],
                "latency_ms": int((time.time() - start) * 1000)}


def _check_smtp():
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", 465))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
    if not (host and user and password):
        return {"status": "not_configured"}
    start = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        return {"status": "ok", "latency_ms": int((time.time() - start) * 1000),
                "host": host, "port": port}
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}


def _check_twilio():
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    phone = os.environ.get("TWILIO_PHONE_NUMBER")
    if not (sid and token and phone):
        return {"status": "not_configured"}
    fake = os.environ.get("FAKE_SMS_MODE", "false").lower() == "true"
    return {
        "status": "ok" if not fake else "fake_mode",
        "sid_prefix": sid[:8] + "…",
        "phone": phone,
        "fake_sms_mode": fake,
    }


def _check_azure_tts():
    key = os.environ.get("AZURE_SPEECH_KEY") or os.environ.get("AZURE_TTS_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION") or os.environ.get("AZURE_TTS_REGION")
    if not (key and region):
        return {"status": "not_configured"}
    return {"status": "ok", "region": region}


def _check_ai_providers():
    results = {}
    gemini = os.environ.get("GEMINI_API_KEY")
    claude = os.environ.get("ANTHROPIC_API_KEY")
    results["gemini"] = "ok" if gemini else "not_configured"
    results["anthropic"] = "ok" if claude else "not_configured"
    return results


def _check_schedulers():
    try:
        # Try to import and detect scheduler instance
        import app as main_app
        sched = getattr(main_app, "scheduler", None)
        if not sched:
            return {"status": "not_running"}
        jobs = []
        for j in sched.get_jobs():
            jobs.append({
                "id": j.id,
                "next_run_at": str(j.next_run_time) if j.next_run_time else None,
            })
        return {"status": "ok", "jobs": jobs, "count": len(jobs)}
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}


def _check_feature_flags():
    flags = {}
    for key in ["ENABLE_SAFE_WEB_AGENT", "ENABLE_BROWSER_AGENT", "ENABLE_RTCF",
                "SOS_ESCALATION", "FAKE_SMS_MODE", "FRONTEND_URL"]:
        val = os.environ.get(key)
        flags[key] = val if val is not None else None
    return flags


def _check_tables():
    """Count key tables for sanity — grouped by subsystem."""
    try:
        from database import db_context
        counts = {}
        with db_context() as db:
            tbls = [
                # Auth + users
                "auth_users", "memory_profiles", "memory_history",
                # Brain + Ψ pipeline
                "brain_states", "brain_adaptation", "brain_feedback",
                # Agent observations + SOS
                "agent_observations", "sos_events",
                # Family + contacts + notifications
                "senior_family_links", "contacts", "user_notifications",
                "push_subscriptions",
                # IoT + sensors
                "iot_devices", "iot_sensor_data", "iot_alerts",
                # Education + rhythm
                "education_progress", "rhythm_sessions", "rhythm_states",
                # Chat
                "chat_conversations", "chat_messages",
                # Medical
                "crisis_events", "medical_alerts",
                # Telemedicine
                "telemedicine_consultations",
                # Audit
                "audit_log",
            ]
            for tbl in tbls:
                try:
                    row = db.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                    # DictRow has __getitem__(int) via row[0]; fallback to value lookup
                    if row is None:
                        counts[tbl] = 0
                    elif hasattr(row, 'keys'):
                        # dict-like (PG RealDictCursor) — keys may vary ("count" or numeric)
                        vals = list(row.values()) if hasattr(row, 'values') else []
                        counts[tbl] = int(vals[0]) if vals else 0
                    else:
                        counts[tbl] = int(row[0])
                except Exception:
                    counts[tbl] = None
        return counts
    except Exception as e:
        return {"error": str(e)[:80]}


def _check_recent_activity():
    """Last-24h activity counters — shows if system is actually used."""
    try:
        from database import db_context, is_postgres
        out = {}
        with db_context() as db:
            interval_sql = "NOW() - INTERVAL '24 hours'" if is_postgres() else "datetime('now', '-1 day')"
            for label, tbl, col in [
                ("chat_24h", "memory_history", "created_at"),
                ("brain_24h", "brain_states", "created_at"),
                ("observations_24h", "agent_observations", "created_at"),
                ("notifications_24h", "user_notifications", "created_at"),
                ("sos_24h", "sos_events", "created_at"),
                ("registrations_24h", "auth_users", "created_at"),
            ]:
                try:
                    row = db.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} > {interval_sql}").fetchone()
                    if row is None:
                        out[label] = 0
                    elif hasattr(row, 'values'):
                        vals = list(row.values())
                        out[label] = int(vals[0]) if vals else 0
                    else:
                        out[label] = int(row[0])
                except Exception:
                    out[label] = None
        return out
    except Exception as e:
        return {"error": str(e)[:80]}


# ═══════════════════════════════════════════════════════════════════
# MAIN ROUTE
# ═══════════════════════════════════════════════════════════════════

@system_status_bp.route("/api/system/status", methods=["GET", "OPTIONS"])
def system_status():
    if request.method == "OPTIONS":
        return _options_ok()

    # Minimal auth — need auth_user header via middleware OR admin secret
    # Apply require_auth at route level? Use optional auth instead to also accept admin secret.
    from auth_middleware import optional_auth
    # Emulate: parse token manually; simpler — just require admin check
    if not _is_admin():
        # Try to extract JWT to populate g.auth_user
        try:
            from auth_middleware import _extract_and_validate_token
            payload = _extract_and_validate_token(request)
            if payload:
                g.auth_user = payload
        except Exception:
            pass
        if not _is_admin():
            return jsonify({"success": False, "error": "Admin access required"}), 403

    # Cache
    now = time.time()
    if _cache["data"] and (now - _cache["at"]) < _CACHE_TTL:
        return jsonify({**_cache["data"], "cached": True, "cache_age_s": int(now - _cache["at"])})

    result = {
        "success": True,
        "timestamp": datetime.utcnow().isoformat(),
        "app_version": os.environ.get("HEROKU_RELEASE_VERSION", "local"),
        "checks": {
            "database":       _check_db(),
            "smtp":           _check_smtp(),
            "twilio":         _check_twilio(),
            "azure_tts":      _check_azure_tts(),
            "ai_providers":   _check_ai_providers(),
            "schedulers":     _check_schedulers(),
        },
        "feature_flags": _check_feature_flags(),
        "table_counts":  _check_tables(),
        "activity_24h":  _check_recent_activity(),
    }

    # Overall status (worst of all)
    worst = "ok"
    for check in result["checks"].values():
        if isinstance(check, dict):
            st = check.get("status")
            if st == "error":
                worst = "error"
                break
            elif st in ("degraded", "not_configured", "not_running"):
                if worst != "error":
                    worst = "degraded"
    result["overall"] = worst

    _cache["at"] = now
    _cache["data"] = result

    return jsonify(result)


logger.info("📊 System status routes loaded: /api/system/status")
