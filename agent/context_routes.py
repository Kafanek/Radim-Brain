"""
Agent Context Hints API
=======================

Flask blueprint exposing the agent's current understanding of a user
to other modules (frontend or backend). Every module that wants
"agent-aware" behavior can hit one of these and adapt itself.

Endpoints (all under /api/agent):

  GET  /heartbeat/<user_id>              → full live snapshot
  GET  /context-hints/<user_id>/<module> → tone + speech + mode hints
  POST /tick/<user_id>                   → force a synchronous beat (debug)
  GET  /personas                         → list available personas + weights

Auth: all endpoints require either:
  - Authorization: Bearer <jwt>     (user-scoped, must match path user_id)
  - X-Admin-Secret: <secret>        (admin / cron / ops)

Sprint X20.1
"""
from __future__ import annotations

import os

from flask import Blueprint, g, jsonify, request

from .math_engine import PERSONA_WEIGHTS
from .runtime import get_runtime, _serialize_snapshot

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')


def _admin_authorized() -> bool:
    expected = os.environ.get('ADMIN_SECRET')
    if not expected:
        return False
    return request.headers.get('X-Admin-Secret') == expected


def _decode_jwt_from_header():
    """Read JWT from Authorization header and return (payload, user) or (None, None)."""
    try:
        from auth_middleware import decode_jwt
    except ImportError:
        return None, None
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None, None
    token = auth_header[7:].strip()
    if not token:
        return None, None
    payload = decode_jwt(token)
    if not payload:
        return None, None
    user = payload.get('user') or {}
    return payload, user


def _user_authorized(user_id: str):
    """Returns (ok, jwt_user). ok=True if admin OR JWT user matches path uid.
    Path uid is normalized to string for comparison (JWT may carry int id)."""
    if _admin_authorized():
        return True, None
    _, jwt_user = _decode_jwt_from_header()
    if not jwt_user:
        return False, None
    # Coerce both to string for comparison — WP user ids are integers in JWT
    # but the frontend sends them as strings in the URL path.
    jwt_id = jwt_user.get('id') or jwt_user.get('user_id')
    if jwt_id is None:
        return False, jwt_user
    if str(jwt_id) == str(user_id):
        # Stash on g so handlers can reuse without re-decoding
        try:
            g.auth_user = jwt_user
        except Exception:
            pass
        return True, jwt_user
    return False, jwt_user


def _require_auth(user_id: str):
    ok, _ = _user_authorized(user_id)
    if not ok:
        return jsonify({'success': False, 'error': 'unauthorized',
                        'code': 'token_required'}), 401
    return None


@agent_bp.route('/heartbeat/<user_id>', methods=['GET'])
def heartbeat(user_id):
    err = _require_auth(user_id)
    if err:
        return err
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    snap = rt.latest(user_id)
    if not snap:
        # Cold start — ensure heartbeat exists, do an immediate tick
        try:
            snap = rt.force_tick(user_id)
        except Exception as e:  # noqa: BLE001
            return jsonify({'available': False, 'error': str(e)}), 500
    return jsonify({
        'available': True,
        'user_id': user_id,
        'snapshot': _serialize_snapshot(snap),
    })


@agent_bp.route('/context-hints/<user_id>/<module>', methods=['GET'])
def context_hints(user_id, module):
    """Lightweight, frontend-friendly context for `module` to adapt itself."""
    err = _require_auth(user_id)
    if err:
        return err
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    return jsonify(rt.context_hints(user_id, module))


@agent_bp.route('/tick/<user_id>', methods=['POST'])
def force_tick(user_id):
    """Debug — synchronously fire one heartbeat and return the snapshot.
    Admin-only (cron, debugging)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    rt = get_runtime()
    if not rt:
        return jsonify({'available': False, 'reason': 'runtime_not_initialized'}), 503
    try:
        snap = rt.force_tick(user_id)
    except Exception as e:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(e)}), 500
    return jsonify({'success': True, 'snapshot': _serialize_snapshot(snap)})


@agent_bp.route('/personas', methods=['GET'])
def list_personas():
    """List available personas with their weight + threshold profiles.
    Sprint X20.5: weights include all 6 dimensions (cognitive + circadian)."""
    def _w_dict(w):
        return {
            'emotional':     w.emotional,
            'environmental': w.environmental,
            'social':        w.social,
            'physical':      w.physical,
            'cognitive':     w.cognitive,
            'circadian':     w.circadian,
        }
    out = {}
    try:
        from .personas import PERSONA_THRESHOLDS
        for pid, w in PERSONA_WEIGHTS.items():
            out[pid] = {
                'weights': _w_dict(w),
                'thresholds': PERSONA_THRESHOLDS.get(pid, {}),
            }
    except ImportError:
        for pid, w in PERSONA_WEIGHTS.items():
            out[pid] = {'weights': _w_dict(w)}
    return jsonify({'personas': out})


@agent_bp.route('/persona/<user_id>', methods=['GET'])
def get_user_persona(user_id):
    """Get persona_id assigned to user. Self or admin."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .personas import get_persona_id, get_thresholds
        pid = get_persona_id(user_id)
        return jsonify({
            'success': True,
            'user_id': user_id,
            'persona_id': pid,
            'thresholds': get_thresholds(pid),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/persona/<user_id>', methods=['POST'])
def set_user_persona(user_id):
    """Set persona_id for user. Admin-only (caregiver-driven from dashboard).
    Body: {"persona_id": "senior" | "child_autism" | "child_adhd"}"""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    pid = body.get('persona_id')
    if not pid:
        return jsonify({'success': False, 'error': 'missing_persona_id'}), 400
    try:
        from .personas import set_persona_id, get_thresholds
        ok = set_persona_id(user_id, pid)
        if not ok:
            return jsonify({'success': False,
                            'error': 'unknown_persona_or_db_error'}), 400
        # Audit-log the change
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'persona_changed',
                      payload={'persona_id': pid})
        except Exception:
            pass
        return jsonify({'success': True, 'persona_id': pid,
                        'thresholds': get_thresholds(pid)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/health', methods=['GET'])
def agent_health():
    """Public — light health check, no auth required."""
    rt = get_runtime()
    out = {
        'available': bool(rt),
        'active_heartbeats': len(rt._heartbeats) if rt else 0,
        'version': '1.0.0',
    }
    # Sprint X20.1/Fix 5 — surface ha_realtime registry status
    try:
        from .ha_realtime import get_registry
        reg = get_registry()
        out['ha_realtime'] = reg.status() if reg else {'available': False}
    except Exception:
        pass
    return jsonify(out)


@agent_bp.route('/ha-realtime/init', methods=['POST'])
def ha_realtime_init():
    """Admin: kick off WebSocket subscription for all configured HA homes.
    Useful after a Heroku restart or after a new home was added without
    waiting for the next agent_loop cycle to discover it."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .ha_realtime import get_registry, init_registry
        reg = get_registry() or init_registry()
        # Fetch the running Flask app for context binding
        try:
            from flask import current_app
            reg.app = reg.app or current_app._get_current_object()
        except Exception:
            pass
        started = reg.init_all()
        return jsonify({
            'success': True,
            'newly_started': started,
            'status': reg.status(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/ha-realtime/init/<user_id>', methods=['POST'])
def ha_realtime_init_user(user_id):
    """Admin: subscribe to a single user's HA. Idempotent."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .ha_realtime import get_registry, init_registry
        reg = get_registry() or init_registry()
        try:
            from flask import current_app
            reg.app = reg.app or current_app._get_current_object()
        except Exception:
            pass
        ok = reg.init_user(user_id)
        return jsonify({
            'success': True,
            'newly_started': ok,
            'user_id': user_id,
            'status': reg.status(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Sprint X20.1/Fix 6 — Goal-driven planner endpoints ──────────────────


@agent_bp.route('/goals/<user_id>', methods=['GET'])
def list_user_goals(user_id):
    """List active goals for user — self or admin."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .planner import list_active_goals
        from .goals import list_goal_types
        return jsonify({
            'success': True,
            'user_id': user_id,
            'goals': list_active_goals(user_id),
            'available_types': list_goal_types(),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/<user_id>', methods=['POST'])
def upsert_user_goal(user_id):
    """Admin: create or update a goal.
    Body: {"goal_type": "...", "target": {...}, "horizon_hours": 24}"""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    goal_type = body.get('goal_type')
    target = body.get('target', {})
    horizon_hours = body.get('horizon_hours', 24)
    if not goal_type:
        return jsonify({'success': False, 'error': 'missing_goal_type'}), 400
    try:
        from .planner import upsert_goal
        from .goals import GOAL_MEASURES
        if goal_type not in GOAL_MEASURES:
            return jsonify({'success': False,
                            'error': f'unknown_goal_type:{goal_type}'}), 400
        gid = upsert_goal(user_id, goal_type, target, horizon_hours)
        # Audit
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'goal_upsert',
                      payload={'goal_id': gid, 'goal_type': goal_type,
                               'target': target,
                               'horizon_hours': horizon_hours})
        except Exception:
            pass
        return jsonify({'success': True, 'goal_id': gid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/<user_id>/<int:goal_id>', methods=['DELETE'])
def deactivate_user_goal(user_id, goal_id):
    """Admin: deactivate a goal (preserve history, just stop evaluating)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .planner import deactivate_goal
        ok = deactivate_goal(user_id, goal_id)
        if ok:
            try:
                from .audit import log_event
                log_event(user_id, 'admin', 'goal_deactivated',
                          payload={'goal_id': goal_id})
            except Exception:
                pass
        return jsonify({'success': ok, 'goal_id': goal_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/<user_id>/init-defaults', methods=['POST'])
def init_default_goals(user_id):
    """Admin: bulk-create the persona's default goal set for this user.
    Reads persona from memory_profiles.data (set via /api/agent/persona)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .personas import get_persona_id
        from .planner import initialize_default_goals
        persona = get_persona_id(user_id)
        created = initialize_default_goals(user_id, persona)
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'goals_init_defaults',
                      payload={'persona_id': persona, 'created': created})
        except Exception:
            pass
        return jsonify({'success': True, 'persona_id': persona,
                        'created_or_updated': created})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/<user_id>/progress', methods=['GET'])
def goal_progress(user_id):
    """Recent goal-progress measurements (last N samples)."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .planner import get_goal_progress
        limit = max(1, min(500, int(request.args.get('limit', 50))))
        return jsonify({
            'success': True,
            'user_id': user_id,
            'progress': get_goal_progress(user_id, limit=limit),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/<user_id>/evaluate', methods=['POST'])
def force_evaluate_goals(user_id):
    """Admin: manually trigger goal evaluation (debugging / testing)."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .planner import evaluate
        obs = evaluate(user_id) or []
        return jsonify({'success': True, 'observations': obs,
                        'count': len(obs)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Sprint X20.9 — Caregiver IFTTT automations ──────────────────────────


@agent_bp.route('/automations/<user_id>', methods=['GET'])
def list_automations(user_id):
    """Self/admin — list user's automation rules."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .automations import list_user_automations
        return jsonify({
            'success':     True,
            'user_id':     user_id,
            'automations': list_user_automations(user_id),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/<user_id>', methods=['POST'])
def create_automation(user_id):
    """Admin — create a new rule. Body:
       {name, trigger_type, trigger_config, condition_config, action_config, enabled?}
    """
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    try:
        from .automations import upsert_automation
        rid = upsert_automation(
            user_id=user_id,
            name=body.get('name', 'Automatizace'),
            trigger_type=body.get('trigger_type', ''),
            trigger_config=body.get('trigger_config') or {},
            condition_config=body.get('condition_config') or {},
            action_config=body.get('action_config') or {},
            enabled=bool(body.get('enabled', False)),
        )
        if not rid:
            return jsonify({'success': False,
                            'error': 'invalid_or_capped_or_unsafe'}), 400
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'automation_created',
                      payload={'rule_id': rid, 'name': body.get('name'),
                               'trigger_type': body.get('trigger_type'),
                               'action_type': (body.get('action_config') or {}).get('type')})
        except Exception:
            pass
        return jsonify({'success': True, 'rule_id': rid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/<user_id>/<int:rule_id>', methods=['PUT'])
def update_automation(user_id, rule_id):
    """Admin — update existing rule."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    try:
        from .automations import upsert_automation
        rid = upsert_automation(
            user_id=user_id,
            name=body.get('name', 'Automatizace'),
            trigger_type=body.get('trigger_type', ''),
            trigger_config=body.get('trigger_config') or {},
            condition_config=body.get('condition_config') or {},
            action_config=body.get('action_config') or {},
            enabled=bool(body.get('enabled', False)),
            rule_id=rule_id,
        )
        return jsonify({'success': bool(rid), 'rule_id': rid})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/<user_id>/<int:rule_id>', methods=['DELETE'])
def delete_automation_route(user_id, rule_id):
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .automations import delete_automation
        ok = delete_automation(user_id, rule_id)
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'automation_deleted',
                      payload={'rule_id': rule_id})
        except Exception:
            pass
        return jsonify({'success': ok, 'rule_id': rule_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/<user_id>/<int:rule_id>/enabled', methods=['POST'])
def toggle_automation(user_id, rule_id):
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('enabled', False))
    try:
        from .automations import set_enabled
        ok = set_enabled(user_id, rule_id, enabled)
        return jsonify({'success': ok, 'enabled': enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/<user_id>/<int:rule_id>/test', methods=['POST'])
def test_fire_automation(user_id, rule_id):
    """Admin — force-fire one rule for testing. Bypasses trigger + cooldown
    but still respects sensitive-action gates."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .automations import test_fire
        result = test_fire(user_id, rule_id)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/automations/types', methods=['GET'])
def list_automation_types():
    """Public — UI dropdowns for trigger + action types."""
    try:
        from .automations import (
            list_trigger_types, list_action_types,
            MAX_RULES_PER_USER, DEFAULT_COOLDOWN_MIN, SENSITIVE_HA_DOMAINS,
        )
        return jsonify({
            'success':         True,
            'triggers':        list_trigger_types(),
            'actions':         list_action_types(),
            'max_per_user':    MAX_RULES_PER_USER,
            'default_cooldown_minutes': DEFAULT_COOLDOWN_MIN,
            'sensitive_ha_domains':     sorted(SENSITIVE_HA_DOMAINS),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Sprint X20.8 — Per-user correlation analysis ────────────────────────


@agent_bp.route('/correlations/<user_id>', methods=['GET'])
def get_user_correlations(user_id):
    """Self/admin — read latest cached correlation matrix + insights."""
    err = _require_auth(user_id)
    if err:
        return err
    try:
        from .correlation import get_correlation_matrix
        result = get_correlation_matrix(user_id)
        if not result:
            return jsonify({'success': True, 'available': False,
                            'note': 'No correlation matrix yet — POST /recompute first.'})
        return jsonify({'success': True, 'available': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/correlations/<user_id>/recompute', methods=['POST'])
def recompute_user_correlations(user_id):
    """Admin — recompute now (debug / manual trigger). Cron does this weekly."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .correlation import recompute_for_user
        from .personas import get_persona_id
        body = request.get_json(silent=True) or {}
        window_days = int(body.get('window_days', 7))
        persona = get_persona_id(user_id)
        result = recompute_for_user(user_id, persona_id=persona,
                                      window_days=window_days)
        # Audit
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'correlations_recomputed',
                      payload={'window_days': window_days,
                               'insights_count': len(result.get('insights', []))})
        except Exception:
            pass
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─── Sprint X20.7 — Federated baseline learning ──────────────────────────


@agent_bp.route('/population/baselines', methods=['GET'])
def get_population_baselines():
    """List published (k-anon-passing) population baselines.
    Public — already anonymized, no per-user data."""
    try:
        from .federated import list_population_baselines
        persona = request.args.get('persona')
        return jsonify({
            'success':   True,
            'baselines': list_population_baselines(persona_id=persona),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/population/baseline/<persona_id>/<metric>', methods=['GET'])
def get_population_baseline_one(persona_id, metric):
    """Get one population baseline. Public — k-anonymity enforced."""
    try:
        from .federated import get_population_baseline
        time_window = request.args.get('window', '7d')
        baseline = get_population_baseline(persona_id, metric, time_window)
        if not baseline:
            return jsonify({'success': False,
                            'error': 'not_found_or_below_k_anonymity'}), 404
        return jsonify({'success': True, 'baseline': baseline})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/population/aggregate', methods=['POST'])
def trigger_population_aggregate():
    """Admin: manually run federated aggregation across all personas."""
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    try:
        from .federated import aggregate_population_baselines
        persona = request.args.get('persona')
        upserted = aggregate_population_baselines(persona_id=persona)
        return jsonify({
            'success': True,
            'rows_upserted': upserted,
            'persona': persona or 'all',
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/population/opt-in/<user_id>', methods=['GET', 'POST'])
def federated_opt_in(user_id):
    """Per-user opt-in toggle. GET returns current state; POST {enabled: bool}.
    GET self-or-admin; POST admin (caregiver-driven from dashboard)."""
    if request.method == 'GET':
        err = _require_auth(user_id)
        if err:
            return err
        try:
            from .federated import is_federated_enabled
            return jsonify({'success': True, 'user_id': user_id,
                            'enabled': is_federated_enabled(user_id)})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    # POST
    if not _admin_authorized():
        return jsonify({'success': False, 'error': 'admin_required'}), 401
    body = request.get_json(silent=True) or {}
    enabled = bool(body.get('enabled'))
    try:
        from .federated import set_federated_enabled
        ok = set_federated_enabled(user_id, enabled)
        # Audit
        try:
            from .audit import log_event
            log_event(user_id, 'admin', 'federated_opt_in',
                      payload={'enabled': enabled})
        except Exception:
            pass
        return jsonify({'success': ok, 'user_id': user_id, 'enabled': enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bp.route('/goals/sources', methods=['GET'])
def list_goal_sources():
    """Public/self — list available custom goal data sources + operators
    for the dashboard's custom-goal builder UI (Sprint X20.6)."""
    try:
        from .goals import list_custom_sources, list_operators, list_goal_types
        return jsonify({
            'success':         True,
            'data_sources':    list_custom_sources(),
            'operators':       list_operators(),
            'builtin_types':   list_goal_types(),
            'note': ("Custom goals are stored under goal_type='custom' with "
                     "target = {_source, _filter, _op, _value, _label}."),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
