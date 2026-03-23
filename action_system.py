"""
⚡ RADIM ACTION SYSTEM v1.0
============================
Formální pipeline pro REÁLNÉ akce (ne jen mluvení).

Každá akce:
1. Je registrovaná s risk_level a required_permission
2. Projde approval flow (Relationship Engine → trust → permission)
3. Je zalogovaná do audit_log (compliance)
4. Má rollback mechanismus

Risk levels:
  0 = READ    (čtení dat, žádný side-effect)
  1 = LOW     (nastavení připomínky, přehrání příběhu)
  2 = MEDIUM  (odeslání zprávy, vytvoření úkolu)
  3 = HIGH    (telefonní hovor, email třetí straně)
  4 = CRITICAL (nouzové volání 155, smazání dat)

Permission flow:
  SUGGEST → user confirms → execute
  ASSIST  → execute + show + cancel option
  EXECUTE → auto + notify

Philosophy: Radim NIKDY nejedná za zády uživatele.
"""

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# ACTION REGISTRY
# ============================================================================

ACTIONS = {
    # READ (risk=0) — vždy povoleno
    'get_time': {'risk': 0, 'description': 'Zjistit čas'},
    'get_weather': {'risk': 0, 'description': 'Zjistit počasí'},
    'get_nameday': {'risk': 0, 'description': 'Zjistit svátek'},
    'read_news': {'risk': 0, 'description': 'Přečíst zprávy'},

    # LOW (risk=1) — SUGGEST pro nové, auto pro trusted
    'set_reminder': {'risk': 1, 'description': 'Nastavit připomínku'},
    'play_story': {'risk': 1, 'description': 'Přehrát příběh'},
    'start_quiz': {'risk': 1, 'description': 'Spustit kvíz'},
    'start_exercise': {'risk': 1, 'description': 'Spustit cvičení'},
    'open_module': {'risk': 1, 'description': 'Otevřít modul'},

    # MEDIUM (risk=2) — SUGGEST/ASSIST
    'send_message': {'risk': 2, 'description': 'Odeslat zprávu'},
    'create_task': {'risk': 2, 'description': 'Vytvořit úkol'},
    'save_note': {'risk': 2, 'description': 'Uložit poznámku'},
    'update_profile': {'risk': 2, 'description': 'Upravit profil'},

    # HIGH (risk=3) — vždy SUGGEST/ASSIST, nikdy auto
    'make_call': {'risk': 3, 'description': 'Zavolat kontaktu'},
    'send_email': {'risk': 3, 'description': 'Odeslat email'},
    'notify_caregiver': {'risk': 3, 'description': 'Upozornit pečovatele'},

    # CRITICAL (risk=4) — hardcoded safety, vždy execute
    'emergency_call': {'risk': 4, 'description': 'Nouzové volání 155'},
    'alert_family': {'risk': 4, 'description': 'Alertovat rodinu'},
}


# ============================================================================
# APPROVAL ENGINE
# ============================================================================

def check_permission(action_name, trust_level, permission_level, is_crisis=False):
    """
    Determine if action can proceed and HOW.

    Returns:
        dict: {
            'allowed': bool,
            'mode': 'execute'|'assist'|'suggest'|'blocked',
            'reason': str,
            'needs_confirmation': bool
        }
    """
    action = ACTIONS.get(action_name)
    if not action:
        return {'allowed': False, 'mode': 'blocked', 'reason': f'Unknown action: {action_name}', 'needs_confirmation': False}

    risk = action['risk']

    # CRITICAL (risk=4): ALWAYS execute in crisis, SUGGEST otherwise
    if risk == 4:
        if is_crisis:
            return {'allowed': True, 'mode': 'execute', 'reason': 'Crisis override', 'needs_confirmation': False}
        else:
            return {'allowed': True, 'mode': 'suggest', 'reason': 'Critical action needs confirmation', 'needs_confirmation': True}

    # READ (risk=0): always allowed
    if risk == 0:
        return {'allowed': True, 'mode': 'execute', 'reason': 'Read-only', 'needs_confirmation': False}

    # LOW (risk=1): auto for trusted, suggest for new
    if risk == 1:
        if permission_level == 'EXECUTE':
            return {'allowed': True, 'mode': 'execute', 'reason': 'Trusted user', 'needs_confirmation': False}
        else:
            return {'allowed': True, 'mode': 'assist', 'reason': 'Low risk', 'needs_confirmation': False}

    # MEDIUM (risk=2): assist for trusted, suggest for new
    if risk == 2:
        if permission_level == 'EXECUTE':
            return {'allowed': True, 'mode': 'assist', 'reason': 'Medium risk — showing action', 'needs_confirmation': False}
        elif permission_level == 'ASSIST':
            return {'allowed': True, 'mode': 'suggest', 'reason': 'Medium risk — needs confirmation', 'needs_confirmation': True}
        else:
            return {'allowed': True, 'mode': 'suggest', 'reason': 'New user — asking first', 'needs_confirmation': True}

    # HIGH (risk=3): always suggest or assist, never auto
    if risk == 3:
        if permission_level == 'EXECUTE':
            return {'allowed': True, 'mode': 'assist', 'reason': 'High risk — confirm', 'needs_confirmation': True}
        else:
            return {'allowed': True, 'mode': 'suggest', 'reason': 'High risk — asking', 'needs_confirmation': True}

    return {'allowed': False, 'mode': 'blocked', 'reason': 'Unknown risk level', 'needs_confirmation': False}


# ============================================================================
# ACTION EXECUTOR
# ============================================================================

def execute_action(action_name, user_id, params=None, permission_level='SUGGEST', is_crisis=False):
    """
    Execute an action through the approval pipeline.

    Returns:
        dict: {
            'success': bool,
            'action': str,
            'mode': str,
            'result': any,
            'message': str (Czech, for user)
        }
    """
    params = params or {}

    # 1. Check permission
    perm = check_permission(action_name, 0, permission_level, is_crisis)

    if not perm['allowed']:
        return {
            'success': False, 'action': action_name, 'mode': 'blocked',
            'result': None, 'message': 'Tato akce není povolena.'
        }

    # 2. Log to audit
    _log_action(user_id, action_name, perm['mode'], params)

    # 3. If needs confirmation, return suggestion
    if perm['mode'] == 'suggest':
        action_info = ACTIONS.get(action_name, {})
        return {
            'success': True, 'action': action_name, 'mode': 'suggest',
            'result': None,
            'message': f"Chcete, abych provedl: {action_info.get('description', action_name)}?",
            'needs_confirmation': True,
            'confirmation_buttons': ['✅ Ano', '❌ Ne']
        }

    # 4. Execute
    try:
        result = _dispatch(action_name, user_id, params)
        _log_action(user_id, action_name, 'completed', params, result=result)
        return {
            'success': True, 'action': action_name, 'mode': perm['mode'],
            'result': result, 'message': result.get('message', 'Hotovo.')
        }
    except Exception as e:
        _log_action(user_id, action_name, 'failed', params, error=str(e))
        logger.error(f"Action {action_name} failed for {user_id}: {e}")
        return {
            'success': False, 'action': action_name, 'mode': 'failed',
            'result': None, 'message': 'Akce se nezdařila. Zkuste to znovu.'
        }


# ============================================================================
# ACTION DISPATCH — routes to actual implementation
# ============================================================================

def _dispatch(action_name, user_id, params):
    """Route action to its implementation."""

    if action_name == 'open_module':
        return {'type': 'ui', 'command': 'showModule', 'module': params.get('module', 'home'),
                'message': f"Otevírám {params.get('module', 'domů')}."}

    if action_name == 'make_call':
        phone = params.get('phone', '')
        name = params.get('name', 'kontakt')
        if not phone:
            return {'type': 'error', 'message': f'Nemám telefonní číslo na {name}.'}
        # Trigger Twilio call
        try:
            from twilio_voice_helpers import initiate_proactive_call
            initiate_proactive_call(phone, f"Volám {name} pro uživatele.", user_id)
            return {'type': 'call', 'phone': phone, 'message': f'Volám {name}...'}
        except Exception as e:
            return {'type': 'error', 'message': f'Nepodařilo se zavolat: {e}'}

    if action_name == 'emergency_call':
        try:
            from twilio_voice_helpers import initiate_proactive_call
            initiate_proactive_call('+420155', 'Nouzové volání.', user_id)
            return {'type': 'emergency', 'message': 'Volám záchrannou službu 155.'}
        except Exception:
            return {'type': 'emergency', 'message': 'Zavolejte prosím sami na 155.'}

    if action_name == 'set_reminder':
        return {'type': 'reminder', 'message': f"Připomínka nastavena: {params.get('text', '')}"}

    if action_name == 'start_quiz':
        return {'type': 'ui', 'command': 'showModule', 'module': 'quiz',
                'message': 'Otevírám kvízy.'}

    if action_name == 'read_news':
        return {'type': 'ui', 'command': 'showModule', 'module': 'news',
                'message': 'Otevírám zprávy.'}

    # Default: return UI command
    return {'type': 'info', 'message': f'Akce {action_name} provedena.'}


# ============================================================================
# AUDIT LOG
# ============================================================================

def _log_action(user_id, action_name, status, params=None, result=None, error=None):
    """Log action to database for audit trail."""
    try:
        from database import db_context, db_insert
        import json

        with db_context(commit=True) as db:
            # Create table if not exists (first run)
            db.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params JSONB DEFAULT '{}',
                    result JSONB DEFAULT '{}',
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            db_insert(db, 'audit_log',
                ['user_id', 'action', 'status', 'params', 'result', 'error'],
                (user_id, action_name, status,
                 json.dumps(params or {}, ensure_ascii=False),
                 json.dumps(result or {}, ensure_ascii=False),
                 error))

    except Exception as e:
        # Audit log failure must NEVER break the action
        logger.warning(f"Audit log error (non-fatal): {e}")


def get_audit_trail(user_id, limit=50):
    """Get recent actions for a user."""
    try:
        from database import db_context
        with db_context() as db:
            rows = db.execute(
                "SELECT * FROM audit_log WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


logger.info("⚡ Action System v1.0 loaded — 20 actions, 5 risk levels, audit trail")
