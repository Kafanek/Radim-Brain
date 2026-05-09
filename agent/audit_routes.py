"""
Audit API — ISO 27001 / GDPR endpoints
=======================================

All endpoints under /api/audit. Most require admin secret; user-export
allows the user themselves OR admin (per GDPR Article 15).

Endpoints:
  POST /api/audit/event                    — append event (server-internal)
  GET  /api/audit/log/<user_id>            — admin: paginated entries
  GET  /api/audit/verify                   — admin: chain verification
  GET  /api/audit/user/<user_id>/export    — admin or self: GDPR export
  POST /api/audit/user/<user_id>/erase     — admin: GDPR art. 17 pseudonymize
  GET  /api/audit/compliance               — admin: anonymized stats report
  POST /api/audit/cleanup                  — admin: retention cleanup
  GET  /api/audit/health                   — public: light health check

Sprint X20.3
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from .audit import (
    log_event, log_access, verify_chain, export_user_data,
    pseudonymize_user, cleanup_old_entries, compliance_report,
    DEFAULT_RETENTION_DAYS,
)

audit_bp = Blueprint('audit', __name__, url_prefix='/api/audit')


def _admin_authorized() -> bool:
    expected = os.environ.get('ADMIN_SECRET')
    if not expected:
        return False
    return request.headers.get('X-Admin-Secret') == expected


def _self_authorized(user_id: str) -> bool:
    """User can export their own data (GDPR art. 15)."""
    if _admin_authorized():
        return True
    try:
        from flask import g
        u = getattr(g, 'user', None)
        if u and (u.get('id') == user_id or u.get('user_id') == user_id):
            return True
    except Exception:
        pass
    return False


def _viewer_id() -> str:
    """Identify the caller for the access log."""
    if _admin_authorized():
        return 'admin'
    try:
        from flask import g
        u = getattr(g, 'user', None)
        if u:
            return str(u.get('id') or u.get('user_id') or 'unknown')
    except Exception:
        pass
    return 'anonymous'


# ─── Endpoints ─────────────────────────────────────────────────────────────


@audit_bp.route('/event', methods=['POST'])
def post_event():
    """Internal use — admin-only manual event injection (e.g. for ops/cron)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    user_id = body.get('user_id')
    actor   = body.get('actor', 'admin')
    action  = body.get('action')
    payload = body.get('payload', {})
    severity = body.get('severity')
    detector_id = body.get('detector_id')
    if not user_id or not action:
        return jsonify({'success': False, 'error': 'missing_user_id_or_action'}), 400
    new_id = log_event(user_id, actor, action, payload, severity, detector_id)
    return jsonify({'success': True, 'id': new_id})


@audit_bp.route('/log/<user_id>', methods=['GET'])
def get_log(user_id):
    """Paginated audit log for a user. Admin-only.
    Logs the access in agent_audit_access (A.12.4.3)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        limit = max(1, min(500, int(request.args.get('limit', 100))))
        offset = max(0, int(request.args.get('offset', 0)))
    except ValueError:
        return jsonify({'success': False, 'error': 'invalid_pagination'}), 400

    log_access(_viewer_id(), user_id, audit_entry_id=None, reason='log_view')

    try:
        from database import db_context
        with db_context() as db:
            cur = db.execute(
                "SELECT id, actor, action, detector_id, severity, "
                "prev_hash, entry_hash, ts FROM agent_audit_log "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (str(user_id), limit, offset)
            )
            rows = cur.fetchall() or []
        out = []
        for r in rows:
            ts = r['ts'] if 'ts' in r.keys() else r[7]
            out.append({
                'id':           r['id']           if 'id'           in r.keys() else r[0],
                'actor':        r['actor']        if 'actor'        in r.keys() else r[1],
                'action':       r['action']       if 'action'       in r.keys() else r[2],
                'detector_id':  r['detector_id']  if 'detector_id'  in r.keys() else r[3],
                'severity':     r['severity']     if 'severity'     in r.keys() else r[4],
                'prev_hash':    (r['prev_hash']   if 'prev_hash'    in r.keys() else r[5] or ''),
                'entry_hash':   r['entry_hash']   if 'entry_hash'   in r.keys() else r[6],
                'ts':           ts.isoformat() if hasattr(ts, 'isoformat') else str(ts),
            })
        return jsonify({'success': True, 'user_id': user_id, 'entries': out,
                        'limit': limit, 'offset': offset})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@audit_bp.route('/verify', methods=['GET'])
def verify():
    """Chain integrity check. Admin-only (computes hashes for all rows;
    expensive on large logs — use ?user_id=… or ?since=YYYY-MM-DD)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    user_id = request.args.get('user_id')
    since_str = request.args.get('since')
    since_dt = None
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'success': False, 'error': 'bad_since_iso'}), 400
    res = verify_chain(user_id=user_id, since=since_dt)
    return jsonify(res)


@audit_bp.route('/user/<user_id>/export', methods=['GET'])
def export(user_id):
    """GDPR Article 15/20 export. User can export their own; admin can
    export any. Logs the access (A.12.4.3 + GDPR art. 30 record)."""
    if not _self_authorized(user_id):
        return jsonify({'success': False, 'error': 'unauthorized'}), 401
    log_access(_viewer_id(), user_id, audit_entry_id=None, reason='gdpr_export')
    fmt = request.args.get('format', 'json')
    data = export_user_data(user_id, format=fmt)
    return jsonify(data)


@audit_bp.route('/user/<user_id>/erase', methods=['POST'])
def erase(user_id):
    """GDPR Article 17 — right to erasure. Pseudonymizes audit entries
    (preserves statistical traceability without PII link). Admin-only."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    pseudo = pseudonymize_user(user_id)
    if not pseudo:
        return jsonify({'success': False, 'error': 'erase_failed'}), 500
    log_event('system', 'admin', 'gdpr_erasure_executed',
              payload={'pseudonym': pseudo, 'requested_by': _viewer_id()})
    return jsonify({'success': True, 'pseudonym': pseudo})


@audit_bp.route('/compliance', methods=['GET'])
def compliance():
    """Anonymized statistics for ISO 27001 management review. Admin-only."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    days = int(request.args.get('days', 30))
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, min(365, days)))
    return jsonify(compliance_report(start, end))


@audit_bp.route('/cleanup', methods=['POST'])
def cleanup():
    """Retention cleanup — drop entries older than retention_days.
    Admin-only. Default = 7 years; tune via ?days="""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    days = int(request.args.get('days', DEFAULT_RETENTION_DAYS))
    removed = cleanup_old_entries(retention_days=days)
    log_event('system', 'admin', 'retention_cleanup',
              payload={'days': days, 'removed': removed,
                       'requested_by': _viewer_id()})
    return jsonify({'success': True, 'removed': removed, 'retention_days': days})


@audit_bp.route('/health', methods=['GET'])
def health():
    return jsonify({
        'available': True,
        'version': '1.0.0',
        'iso_27001': ['A.12.4.1', 'A.12.4.2', 'A.12.4.3', 'A.12.4.4'],
        'gdpr': ['art_15', 'art_17', 'art_20', 'art_30'],
        'default_retention_days': DEFAULT_RETENTION_DAYS,
    })
