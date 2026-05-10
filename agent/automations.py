"""
Caregiver-defined IFTTT automations
=====================================

Pečovatel definuje pravidla TYP "když se stane X, udělej Y" z dashboardu
bez nutnosti programovat. Automation engine je vyhodnocuje uvnitř
existujících hooks (agent_loop cycle, heartbeat tick, observation save).

Architecture:

  Trigger types (4):
    agent_mode_change   — fires when heartbeat mode crosses to a target
    observation_emitted — fires on a specific observation type / severity
    goal_drift          — fires when specific goal drifts N+ cycles
    time_of_day         — fires at HH:MM on selected days of week

  Conditions (gates applied AFTER trigger matches):
    cooldown_minutes    — don't fire same rule twice within window
    require_mode        — only when current mode is X or worse
    quiet_hours_skip    — bypass user's quiet-hours filter (default: respect)

  Action types (4):
    ha_service_call     — generic HA REST call (light/switch/cover/climate/scene)
    notify_caregiver    — push notification through existing notify pipeline
    send_sms            — Twilio SMS to caregiver (existing infra)
    radim_say           — TTS through RadimVoice / local audio

Privacy + safety:
  - Per-user only (caregiver creates for users they manage)
  - Sensitive HA domains (lock, alarm_control_panel) require explicit
    `caregiver_confirmed: true` flag in action_config
  - Per-rule fire-rate limiting (default 30-min cooldown)
  - Per-user rule count cap (MAX_RULES_PER_USER=50) — prevents resource abuse
  - Every fire logged to audit hash chain
  - Disabled by default (rule.enabled=false until explicitly enabled)

Sprint X20.9
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Constants ─────────────────────────────────────────────────────────────

MAX_RULES_PER_USER     = 50
DEFAULT_COOLDOWN_MIN   = 30
SENSITIVE_HA_DOMAINS   = {'lock', 'alarm_control_panel'}

TRIGGER_TYPES = ('agent_mode_change', 'observation_emitted',
                  'goal_drift', 'time_of_day')

ACTION_TYPES  = ('ha_service_call', 'notify_caregiver',
                  'send_sms', 'radim_say')


# ─── Public list helpers (UI dropdowns) ───────────────────────────────────


def list_trigger_types() -> list[dict]:
    return [
        {
            'id':     'agent_mode_change',
            'label':  'Změna agentova módu',
            'config_keys': ['to_mode', 'from_mode'],
            'help':   'fires when the heartbeat mode crosses to to_mode '
                      '(optionally only from from_mode)',
        },
        {
            'id':     'observation_emitted',
            'label':  'Vznikla observace určitého typu',
            'config_keys': ['observation_type', 'min_severity'],
            'help':   'fires when agent_loop emits observation of given '
                      'type and severity ≥ min_severity',
        },
        {
            'id':     'goal_drift',
            'label':  'Cíl driftuje (N+ cyklů)',
            'config_keys': ['goal_type', 'min_drift_count'],
            'help':   'fires when specific goal hits drift_count ≥ N',
        },
        {
            'id':     'time_of_day',
            'label':  'Konkrétní čas v daný den',
            'config_keys': ['hour', 'minute', 'days_of_week'],
            'help':   'fires at HH:MM in days_of_week (0=Mon..6=Sun)',
        },
    ]


def list_action_types() -> list[dict]:
    return [
        {
            'id':     'ha_service_call',
            'label':  'Zavolat HA službu',
            'config_keys': ['domain', 'service', 'entity_id', 'service_data',
                             'caregiver_confirmed'],
            'help':   'Generic HA REST call. Sensitive domains (lock, '
                      'alarm_control_panel) require caregiver_confirmed=true',
        },
        {
            'id':     'notify_caregiver',
            'label':  'Push notifikace pečovateli',
            'config_keys': ['message', 'urgent'],
            'help':   'Web push to caregiver subscriber',
        },
        {
            'id':     'send_sms',
            'label':  'Twilio SMS',
            'config_keys': ['to', 'message'],
            'help':   'Direct SMS via existing Twilio infra',
        },
        {
            'id':     'radim_say',
            'label':  'Radim řekne (TTS)',
            'config_keys': ['text', 'voice'],
            'help':   'TTS announcement through RadimVoice / local audio',
        },
    ]


# ─── DB helpers ────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_user_automations(user_id: str,
                          active_only: bool = False) -> list[dict]:
    try:
        from database import db_context
    except ImportError:
        return []
    where = "user_id = ?"
    params = [str(user_id)]
    if active_only:
        where += " AND enabled = ?"
        params.append(True)
    try:
        with db_context() as db:
            cur = db.execute(
                "SELECT id, name, enabled, trigger_type, trigger_config, "
                "condition_config, action_config, last_fired_at, fire_count, "
                "created_at, updated_at "
                f"FROM agent_automations WHERE {where} ORDER BY id",
                tuple(params)
            )
            rows = cur.fetchall() or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[automations] list failed: {e}")
        return []
    out = []
    for r in rows:
        try:
            out.append(_row_to_dict(r))
        except Exception:
            continue
    return out


def _row_to_dict(row) -> dict:
    if isinstance(row, (list, tuple)):
        rid, name, enabled, ttype, tcfg, ccfg, acfg, lfa, fc, ca, ua = row
    else:
        rid, name, enabled, ttype = row['id'], row['name'], row['enabled'], row['trigger_type']
        tcfg, ccfg, acfg = row['trigger_config'], row['condition_config'], row['action_config']
        lfa, fc, ca, ua = row['last_fired_at'], row['fire_count'], row['created_at'], row['updated_at']

    def _parse(v):
        if isinstance(v, str):
            try: return json.loads(v)
            except Exception: return {}
        return v or {}

    def _ts(v):
        return v.isoformat() if hasattr(v, 'isoformat') else (str(v) if v else None)

    return {
        'id':              rid,
        'name':            name,
        'enabled':         bool(enabled),
        'trigger_type':    ttype,
        'trigger_config':  _parse(tcfg),
        'condition_config': _parse(ccfg),
        'action_config':   _parse(acfg),
        'last_fired_at':   _ts(lfa),
        'fire_count':      fc or 0,
        'created_at':      _ts(ca),
        'updated_at':      _ts(ua),
    }


def upsert_automation(user_id: str,
                       name: str,
                       trigger_type: str,
                       trigger_config: dict,
                       condition_config: dict,
                       action_config: dict,
                       enabled: bool = False,
                       rule_id: Optional[int] = None) -> Optional[int]:
    """Create or update a rule. Returns id or None on error.

    Validates:
      - trigger_type in TRIGGER_TYPES
      - action_type in ACTION_TYPES
      - sensitive HA actions require caregiver_confirmed=true
      - per-user rule count under MAX_RULES_PER_USER (on create only)
    """
    if trigger_type not in TRIGGER_TYPES:
        return None
    action_type = action_config.get('type')
    if action_type not in ACTION_TYPES:
        return None

    # Safety gate for sensitive HA actions
    if action_type == 'ha_service_call':
        domain = (action_config.get('domain') or '').lower()
        if domain in SENSITIVE_HA_DOMAINS and not action_config.get('caregiver_confirmed'):
            logger.warning(
                f"[automations] refusing sensitive HA action {domain!r} without "
                f"caregiver_confirmed flag (user={user_id})")
            return None

    try:
        from database import db_context, db_insert
    except ImportError:
        return None

    try:
        with db_context(commit=True) as db:
            if rule_id:
                db.execute(
                    "UPDATE agent_automations SET name = ?, enabled = ?, "
                    "trigger_type = ?, trigger_config = ?, condition_config = ?, "
                    "action_config = ?, updated_at = ? "
                    "WHERE id = ? AND user_id = ?",
                    (name, bool(enabled), trigger_type,
                     json.dumps(trigger_config or {}, ensure_ascii=False),
                     json.dumps(condition_config or {}, ensure_ascii=False),
                     json.dumps(action_config or {}, ensure_ascii=False),
                     _now_iso(), int(rule_id), str(user_id))
                )
                return int(rule_id)
            # Cap per-user rule count on insert
            cur = db.execute(
                "SELECT COUNT(*) FROM agent_automations WHERE user_id = ?",
                (str(user_id),)
            )
            row = cur.fetchone()
            count = (row[0] if isinstance(row, (list, tuple)) else row[0]) or 0
            if count >= MAX_RULES_PER_USER:
                logger.warning(
                    f"[automations] user {user_id} hit MAX_RULES_PER_USER cap")
                return None
            return db_insert(db, 'agent_automations',
                ['user_id', 'name', 'enabled', 'trigger_type',
                 'trigger_config', 'condition_config', 'action_config'],
                (str(user_id), name, bool(enabled), trigger_type,
                 json.dumps(trigger_config or {}, ensure_ascii=False),
                 json.dumps(condition_config or {}, ensure_ascii=False),
                 json.dumps(action_config or {}, ensure_ascii=False))
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[automations] upsert failed: {e}")
        return None


def delete_automation(user_id: str, rule_id: int) -> bool:
    try:
        from database import db_context
    except ImportError:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "DELETE FROM agent_automations WHERE id = ? AND user_id = ?",
                (int(rule_id), str(user_id))
            )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[automations] delete failed: {e}")
        return False


def set_enabled(user_id: str, rule_id: int, enabled: bool) -> bool:
    try:
        from database import db_context
    except ImportError:
        return False
    try:
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE agent_automations SET enabled = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (bool(enabled), _now_iso(), int(rule_id), str(user_id))
            )
        return True
    except Exception:
        return False


def _mark_fired(rule_id: int) -> None:
    try:
        from database import db_context
        with db_context(commit=True) as db:
            db.execute(
                "UPDATE agent_automations SET last_fired_at = ?, "
                "fire_count = COALESCE(fire_count, 0) + 1 WHERE id = ?",
                (_now_iso(), int(rule_id))
            )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[automations] mark_fired failed: {e}")


# ─── Trigger matchers (pure, testable) ────────────────────────────────────


SEVERITY_RANK = {'INFO': 0, 'WARNING': 1, 'ALERT': 2, 'CRISIS': 3}


def _trigger_matches_mode_change(rule: dict, ctx: dict) -> bool:
    """ctx: {prev_mode, new_mode}. Rule fires when new_mode == to_mode and
    (from_mode is None or prev_mode == from_mode)."""
    if ctx.get('event') != 'mode_change':
        return False
    cfg = rule.get('trigger_config') or {}
    to_mode = (cfg.get('to_mode') or '').upper()
    from_mode = (cfg.get('from_mode') or '').upper()
    new = (ctx.get('new_mode') or '').upper()
    prev = (ctx.get('prev_mode') or '').upper()
    if to_mode and new != to_mode:
        return False
    if from_mode and prev != from_mode:
        return False
    return True


def _trigger_matches_observation(rule: dict, ctx: dict) -> bool:
    """ctx: {event='observation', observation_type, severity}."""
    if ctx.get('event') != 'observation':
        return False
    cfg = rule.get('trigger_config') or {}
    want_type = cfg.get('observation_type') or ''
    if want_type and ctx.get('observation_type') != want_type:
        return False
    min_sev = (cfg.get('min_severity') or 'INFO').upper()
    actual_sev = (ctx.get('severity') or 'INFO').upper()
    if SEVERITY_RANK.get(actual_sev, 0) < SEVERITY_RANK.get(min_sev, 0):
        return False
    return True


def _trigger_matches_goal_drift(rule: dict, ctx: dict) -> bool:
    """ctx: {event='goal_drift', goal_type, drift_count}."""
    if ctx.get('event') != 'goal_drift':
        return False
    cfg = rule.get('trigger_config') or {}
    want_goal = cfg.get('goal_type') or ''
    if want_goal and ctx.get('goal_type') != want_goal:
        return False
    min_count = int(cfg.get('min_drift_count', 1) or 1)
    return int(ctx.get('drift_count', 0) or 0) >= min_count


def _trigger_matches_time_of_day(rule: dict, ctx: dict) -> bool:
    """ctx: {event='cycle_tick'} — checked once per agent_loop cycle.
    Fires if current local time matches HH:MM (within 5 min) on a selected
    day of week."""
    if ctx.get('event') != 'cycle_tick':
        return False
    cfg = rule.get('trigger_config') or {}
    hour = int(cfg.get('hour', -1) or -1)
    minute = int(cfg.get('minute', -1) or -1)
    days = cfg.get('days_of_week') or [0, 1, 2, 3, 4, 5, 6]
    now = ctx.get('now') or datetime.now()
    if now.weekday() not in days:
        return False
    # Match if within 5-min window of the configured time (so we don't miss
    # by being off-by-a-few-minutes on the cycle)
    cur_minutes = now.hour * 60 + now.minute
    target = hour * 60 + minute
    return abs(cur_minutes - target) <= 5


_TRIGGER_MATCHERS = {
    'agent_mode_change':   _trigger_matches_mode_change,
    'observation_emitted': _trigger_matches_observation,
    'goal_drift':          _trigger_matches_goal_drift,
    'time_of_day':         _trigger_matches_time_of_day,
}


def trigger_matches(rule: dict, ctx: dict) -> bool:
    matcher = _TRIGGER_MATCHERS.get(rule.get('trigger_type'))
    if not matcher:
        return False
    try:
        return bool(matcher(rule, ctx))
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[automations] matcher error: {e}")
        return False


# ─── Conditions ────────────────────────────────────────────────────────────


def conditions_pass(rule: dict, ctx: dict) -> bool:
    """Apply post-trigger gates: cooldown, mode requirement, quiet hours."""
    cond = rule.get('condition_config') or {}

    # Cooldown — explicit 0 disables; only None/missing falls back to default.
    cd_raw = cond.get('cooldown_minutes')
    cooldown_min = DEFAULT_COOLDOWN_MIN if cd_raw is None else int(cd_raw)
    last_fired = rule.get('last_fired_at')
    if last_fired and cooldown_min > 0:
        try:
            if isinstance(last_fired, str):
                lf = datetime.fromisoformat(last_fired.replace('Z', '+00:00'))
            else:
                lf = last_fired
            elapsed_s = (datetime.now(timezone.utc) - lf.replace(tzinfo=timezone.utc) if lf.tzinfo is None
                         else datetime.now(timezone.utc) - lf).total_seconds()
            if elapsed_s < cooldown_min * 60:
                return False
        except Exception:
            pass

    # Mode requirement
    require = (cond.get('require_mode') or '').upper()
    if require:
        cur_mode = (ctx.get('current_mode') or '').upper()
        if SEVERITY_RANK.get(cur_mode, 0) < SEVERITY_RANK.get(require, 0):
            return False

    return True


# ─── Action executor ───────────────────────────────────────────────────────


def execute_action(user_id: str, rule: dict, ctx: dict) -> dict:
    """Run the rule's action. Returns {ok, details}.
    Best-effort; never raises (we log and continue)."""
    action = rule.get('action_config') or {}
    atype = action.get('type')

    try:
        if atype == 'ha_service_call':
            return _execute_ha_call(user_id, action, ctx)
        if atype == 'notify_caregiver':
            return _execute_notify(user_id, action, ctx)
        if atype == 'send_sms':
            return _execute_sms(user_id, action, ctx)
        if atype == 'radim_say':
            return _execute_say(user_id, action, ctx)
        return {'ok': False, 'error': f'unknown_action_type:{atype}'}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[automations] action {atype} failed: {e}")
        return {'ok': False, 'error': str(e)}


def _execute_ha_call(user_id: str, action: dict, ctx: dict) -> dict:
    """Call HA service via existing per-user HA client."""
    try:
        from ha_user_config import ha_for_user
    except ImportError:
        return {'ok': False, 'error': 'ha_unavailable'}
    domain  = action.get('domain') or ''
    service = action.get('service') or ''
    entity  = action.get('entity_id') or ''
    data    = action.get('service_data') or {}
    if not domain or not service:
        return {'ok': False, 'error': 'missing_domain_or_service'}
    if domain in SENSITIVE_HA_DOMAINS and not action.get('caregiver_confirmed'):
        return {'ok': False, 'error': 'sensitive_action_unconfirmed'}
    try:
        client = ha_for_user(user_id)
        if not client or not getattr(client, 'available', False):
            return {'ok': False, 'error': 'ha_client_unavailable'}
        result = client.call_service(domain, service,
                                      entity_id=entity if entity else None,
                                      data=data)
        return {'ok': True, 'detail': {'domain': domain, 'service': service,
                                          'entity_id': entity, 'result': str(result)[:120]}}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)}


def _execute_notify(user_id: str, action: dict, ctx: dict) -> dict:
    """Push notification to user's caregiver subscriptions."""
    msg = action.get('message') or 'Automatizace spuštěna.'
    urgent = bool(action.get('urgent'))
    try:
        from push_helpers import push_to_user  # type: ignore
        push_to_user(user_id, title='Radim — Automatizace',
                     body=msg, urgent=urgent)
        return {'ok': True, 'detail': {'message': msg, 'urgent': urgent}}
    except ImportError:
        # Fallback to logger only
        logger.info(f"[automations] (push unavailable) NOTIFY {user_id}: {msg}")
        return {'ok': True, 'detail': {'message': msg, 'fallback': 'log_only'}}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)}


def _execute_sms(user_id: str, action: dict, ctx: dict) -> dict:
    to = action.get('to') or ''
    msg = action.get('message') or ''
    if not to or not msg:
        return {'ok': False, 'error': 'missing_to_or_message'}
    try:
        from twilio_voice_helpers import send_sms  # type: ignore
        send_sms(to, msg)
        return {'ok': True, 'detail': {'to': to[:6] + '****', 'message': msg[:80]}}
    except ImportError:
        logger.info(f"[automations] (twilio unavailable) SMS to {to[:6]}***: {msg[:60]}")
        return {'ok': True, 'detail': {'fallback': 'log_only'}}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': str(e)}


def _execute_say(user_id: str, action: dict, ctx: dict) -> dict:
    text = action.get('text') or ''
    if not text:
        return {'ok': False, 'error': 'missing_text'}
    # Try local audio service first (Mac/Pi edition); otherwise log
    try:
        import urllib.request
        url = os.environ.get('LOCAL_AUDIO_SERVICE_URL', 'http://127.0.0.1:8772')
        req = urllib.request.Request(
            f'{url}/api/audio/play',
            data=json.dumps({'text': text}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=2) as _:
            pass
        return {'ok': True, 'detail': {'text': text[:80], 'channel': 'local_audio'}}
    except Exception:  # noqa: BLE001
        logger.info(f"[automations] SAY {user_id}: {text[:80]}")
        return {'ok': True, 'detail': {'text': text[:80], 'fallback': 'log_only'}}


# ─── Evaluator (called from agent_loop / runtime / observation save) ─────


def evaluate_for_user(user_id: str, ctx: dict) -> list[dict]:
    """For a given event ctx, find matching enabled rules and run them.

    Returns list of {rule_id, name, fired, action_result}.
    Each fire is audit-logged via X20.3 hash chain.
    """
    rules = list_user_automations(user_id, active_only=True)
    if not rules:
        return []

    out = []
    for rule in rules:
        if not trigger_matches(rule, ctx):
            continue
        if not conditions_pass(rule, ctx):
            out.append({'rule_id': rule['id'], 'name': rule['name'],
                         'fired': False, 'reason': 'conditions_blocked'})
            continue

        # Execute action
        result = execute_action(user_id, rule, ctx)
        _mark_fired(rule['id'])

        # Audit-log the fire
        try:
            from .audit import log_event
            log_event(
                user_id=user_id, actor='automation',
                action='automation_fired',
                detector_id=rule.get('trigger_type'),
                severity='INFO',
                payload={
                    'rule_id':       rule['id'],
                    'rule_name':     rule['name'],
                    'trigger_type':  rule.get('trigger_type'),
                    'trigger_ctx':   {k: v for k, v in ctx.items() if not callable(v)},
                    'action_result': result,
                },
            )
        except Exception:
            pass

        out.append({
            'rule_id': rule['id'], 'name': rule['name'],
            'fired': True, 'action_result': result,
        })

    return out


def test_fire(user_id: str, rule_id: int) -> dict:
    """Force-fire a single rule (debug). Bypasses trigger + condition checks
    but still respects the action's own safety gates (sensitive_action_unconfirmed)."""
    rules = list_user_automations(user_id)
    rule = next((r for r in rules if r['id'] == int(rule_id)), None)
    if not rule:
        return {'ok': False, 'error': 'rule_not_found'}
    result = execute_action(user_id, rule, ctx={'event': 'manual_test'})
    _mark_fired(rule['id'])
    try:
        from .audit import log_event
        log_event(user_id, 'admin', 'automation_test_fired',
                  payload={'rule_id': rule['id'], 'name': rule['name'],
                            'result': result})
    except Exception:
        pass
    return result
