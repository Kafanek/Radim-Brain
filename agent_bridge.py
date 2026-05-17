# ============================================
# 🌉 AGENT BRIDGE — Connects reactive + proactive systems
# ============================================
# Fills gaps between:
# - Agent Coordinator (6 reactive agents) ↔ Agent Loop (proactive monitoring)
# - Survey Engine → agent actions
# - Emergency Protocol → retry logic
# - Text Rhythm → proactive messages (adapt style to brain state)
# - Live risk data → caregiver dashboard
# ============================================

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ============================================
# 1. RHYTHM-AWARE PROACTIVE MESSAGES
# ============================================
# Agent Loop sends push/speak to senior — but without style adaptation.
# This wraps proactive messages through Text Rhythm for state-appropriate tone.

def _maybe_add_identity_overlay(user_id, raw_message, severity, observation_type=None):
    """Sprint 4 (v8.19.33): osobní touch v proaktivní zprávě.

    Když je situace klidná (INFO/WARNING) a senior NENÍ v truchlení/horších dnech,
    obohatí raw_message o krátký identitní opener — proaktivní zpráva pak zní
    osobněji než „Dlouho jsme nemluvili."

    Pravidla:
    - Pouze INFO/WARNING — ALERT/CRISIS musí zůstat jasné a bezpečnostně priorizované
    - SKIP pokud active_preset ∈ {grief, rough_days, goodbye} — tam buďto tichá
    - SKIP pro vital_anomaly / fall_detected typy — žádné rozptýlení od bezpečnosti
    - Logováno do identity_activations s via='agent_loop_proactive'
    """
    if severity not in ('INFO', 'WARNING'):
        return raw_message
    if observation_type and observation_type in (
        'vital_anomaly', 'fall_detected', 'fall_suspected',
        'crisis_chat', 'crisis_message', 'safety_critical'
    ):
        return raw_message

    # Skip when senior is in quiet preset
    try:
        from memory_helpers import db_load_profile
        profile = db_load_profile(str(user_id)) or {}
        ap = profile.get('active_preset') or {}
        if isinstance(ap, dict) and ap.get('id') in ('grief', 'rough_days', 'goodbye'):
            return raw_message
    except Exception:
        pass

    try:
        from radim_identity import LOVES, CURIOUS_ABOUT
        import random
        # 1 facet — ne dvě, ať to není „Radim teď bude vyprávět o sobě"
        pool = LOVES + CURIOUS_ABOUT
        if not pool:
            return raw_message
        facet = random.choice(pool)

        # Helper: lowercase pouze prvního písmena (zachovat Smetanu/Dvořáka)
        def _lower_first(s):
            return (s[0].lower() + s[1:]) if s else s

        # Templates podle observation_type → osobnější opener
        facet_lc = _lower_first(facet)
        opener_templates_by_type = {
            'no_interaction': [
                f"Vzpomněl jsem si na tohle: {facet} A napadlo mě, jak se vy dnes máte?",
                f"Něco mi proběhlo myslí — {facet_lc} A přitom mi došlo, že jsme se dlouho neslyšeli.",
            ],
            'c_trend_rising': [
                f"Já mám taky rád obyčejné věci — {facet_lc} Co kdybychom si dali takovou chvíli?",
            ],
            'activity_drop': [
                f"Dnes je den, kdy si vzpomínám na {facet_lc}",
            ],
        }
        # Default opener (jakýkoli jiný observation_type)
        default_openers = [
            f"Něco mi proběhlo hlavou: {facet}",
            f"Vzpomněl jsem si na tohle: {facet}",
        ]

        opener = random.choice(opener_templates_by_type.get(observation_type, default_openers))

        # Compose: opener + původní zpráva (jemně oddělené dvěma spaces)
        composed = f"{opener}  {raw_message}"

        # Log activation (best-effort)
        try:
            from database import db_context
            with db_context(commit=True) as db:
                db.execute(
                    "INSERT INTO identity_activations (user_id, activation_type, text, via, fired_at) "
                    "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (str(user_id), 'proactive_overlay', opener[:500],
                     f'agent_loop_{observation_type or "generic"}')
                )
        except Exception:
            pass

        return composed
    except Exception as e:
        logger.debug(f"identity overlay skipped: {e}")
        return raw_message


def compose_proactive_message(user_id, raw_message, severity='INFO', observation_type=None):
    """Adapt a proactive agent message to the user's current brain state.

    Uses Text Rhythm to adjust length, tone, complexity.
    Falls back to raw message if Text Rhythm unavailable.

    v8.19.33 (Sprint 4): when severity is INFO/WARNING and senior isn't in
    grief/rough_days, weaves an identity-flavored opener for personal touch.

    Args:
        user_id: Senior identifier
        raw_message: Original message from agent
        severity: INFO/WARNING/ALERT/CRISIS
        observation_type: optional type (no_interaction/c_trend_rising/...) for
                          template selection

    Returns:
        dict: {text, speech_rate, pause_ms, tone, state}
    """
    # Sprint 4: identity overlay BEFORE rhythm adaptation, so rhythm scales the
    # complete (opener + original) text consistently
    raw_message = _maybe_add_identity_overlay(user_id, raw_message, severity, observation_type)

    result = {
        'text': raw_message,
        'speech_rate': 0.9,
        'pause_ms': 618,
        'tone': 'neutral',
        'state': 'HARMONY'
    }

    try:
        from text_rhythm import estimate_C_alpha_from_text, calculate_text_params, enforce_crisis_limits

        # Get current brain C from DB
        C = 5.0
        try:
            from database import db_context
            with db_context(commit=False) as db:
                row = db.execute("""
                    SELECT coherence FROM brain_states
                    WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
                """, (user_id,)).fetchone()
                if row:
                    C = float(row[0])
        except Exception:
            pass

        # Map severity → alpha (emotional intensity)
        alpha_map = {'INFO': 0.0, 'WARNING': 0.3, 'ALERT': 0.6, 'CRISIS': 0.9}
        alpha = alpha_map.get(severity, 0.0)

        text_result = calculate_text_params(C, alpha)
        state = text_result.get('state', 'HARMONY')

        # Enforce text limits for crisis
        adapted_text = enforce_crisis_limits(raw_message, text_result)

        # Extract speech params
        speech = text_result.get('speech_params', {})

        result['text'] = adapted_text
        result['speech_rate'] = speech.get('rate', 0.9)
        result['pause_ms'] = speech.get('pause_after_sentence', 618)
        result['tone'] = text_result.get('params', {}).get('tone', 'neutral')
        result['state'] = state

    except (ImportError, Exception) as e:
        logger.debug(f"Text rhythm adaptation skipped: {e}")

    return result


# ============================================
# 2. AGENT LOOP → COORDINATOR BRIDGE
# ============================================
# Agent Loop detects anomaly → pass it through Rhythm Coordinator
# for smarter response selection (not just severity-based).

def evaluate_proactive_observation(user_id, observation):
    """Pass a proactive observation through the 6 reactive agents.

    This lets SafetyAgent, CareAgent, etc. weigh in on how to respond
    to a proactive detection — not just hardcoded severity thresholds.

    Args:
        user_id: Senior identifier
        observation: dict from agent_loop detector

    Returns:
        dict: {agent, action, message, tone, priority} or None
    """
    try:
        from rhythm_state import compute_rhythm_state
        from agent_coordinator import pick_best_action

        state = compute_rhythm_state(user_id)
        if not state:
            return None

        # Synthesize user_input from observation for agent evaluation
        synthetic_input = observation.get('message', '')

        decision = pick_best_action(state, synthetic_input)
        if decision and decision.should_act:
            return {
                'agent': decision.agent_name,
                'action': decision.action,
                'message': decision.message or observation.get('message', ''),
                'tone': decision.tone,
                'priority': decision.priority,
                'reason': decision.reason
            }

    except Exception as e:
        # X21.31: was `except (ImportError, Exception)` — ImportError is a
        # subclass of Exception, so the tuple was redundant. Cleaner this way.
        logger.debug(f"Coordinator bridge skipped: {e}")

    return None


# ============================================
# 3. EMERGENCY RETRY LOGIC
# ============================================
# If SMS/call fails, retry up to 3 times with exponential backoff.

def emergency_with_retry(user_id, trigger, app=None, max_retries=3):
    """Execute emergency protocol with retry logic.

    Retries failed steps (SMS, call) individually.
    Logs all attempts for audit trail.

    Args:
        user_id: Senior identifier
        trigger: Crisis description
        app: Flask app context
        max_retries: Max retry attempts per action
    """
    logger.critical(f"🚨 EMERGENCY (with retry) for {user_id}: {trigger}")

    actions = [
        ('log', _emergency_log),
        ('ha_lights', _emergency_ha),
        ('call', _emergency_call),
        ('sms', _emergency_sms),
        ('push', _emergency_push),
    ]

    # Sprint AF: ValueError from emergency actions = permanent error
    # ("No phone for X", "No emergency contacts configured", "No valid phone
    # numbers in contacts"). Retrying these 3× with exp backoff just delays
    # the rest of the protocol by 7s and fills logs with noise. Skip retry
    # on ValueError; only retry transient failures (network, timeout,
    # third-party API hiccups → RuntimeError, ConnectionError, requests
    # exceptions, etc.).
    # X21.31: removed AttributeError from this tuple. On the HA client path
    # (_emergency_ha), AttributeError is usually transient — a momentarily
    # disconnected/half-initialized client, not a config bug. Treating it
    # as permanent was disabling the retry that was supposed to recover the
    # path. ValueError stays (config-level errors that won't fix on retry).
    permanent_error_types = (ValueError,)

    results = {}
    for action_name, action_fn in actions:
        success = False
        last_error = None
        attempt = 0
        for attempt in range(max_retries):
            try:
                action_fn(user_id, trigger, app)
                success = True
                logger.info(f"🚨 Emergency {action_name}: ✅ (attempt {attempt + 1})")
                break
            except permanent_error_types as pe:
                # Configuration / data missing — won't get better with retry
                last_error = f"permanent: {pe}"
                logger.warning(f"🚨 Emergency {action_name}: skipped permanently — {pe}")
                break
            except Exception as e:
                last_error = str(e)
                logger.warning(f"🚨 Emergency {action_name}: attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s, 4s

        results[action_name] = {
            'success': success,
            'attempts': attempt + 1,
            'error': last_error if not success else None
        }

    # Log summary to DB
    try:
        from database import db_context
        with db_context(commit=True) as db:
            # Sprint AC: column is `observation_type`, not `type` (matches schema).
            # Old wrong column name caused agent_loop's account_cleanup + this
            # emergency_summary insert to silently fail with retry storms in logs.
            db.execute("""
                INSERT INTO agent_observations
                (user_id, observation_type, severity, message, details, created_at)
                VALUES (?, 'emergency_summary', 'CRISIS', ?, ?, ?)
            """, (
                user_id,
                f"Emergency protocol: {sum(1 for r in results.values() if r['success'])}/{len(results)} actions succeeded",
                str(results),
                datetime.utcnow().isoformat()
            ))
    except Exception:
        pass

    # If call AND sms both failed → escalate to system admin
    if not results.get('call', {}).get('success') and not results.get('sms', {}).get('success'):
        logger.critical(f"🚨🚨 BOTH call and SMS failed for {user_id}! Manual intervention needed.")
        _alert_system_admin(user_id, trigger, results)

    return results


def _emergency_log(user_id, trigger, app):
    """Log crisis event."""
    from database import db_context
    with db_context(commit=True) as db:
        # Sprint AC: column is `observation_type` (matches schema)
        db.execute("""
            INSERT INTO agent_observations
            (user_id, observation_type, severity, message, created_at)
            VALUES (?, 'emergency_protocol', 'CRISIS', ?, ?)
        """, (user_id, f"Trigger: {trigger}", datetime.utcnow().isoformat()))


def _emergency_ha(user_id, trigger, app):
    """Turn on all lights + unlock doors via Home Assistant (per-user)."""
    from home_assistant import ha_for
    client = ha_for(user_id)
    if not client.connected:
        raise ConnectionError("HA not connected")
    devices = client.get_devices_by_type()
    for light in devices.get('light', []):
        client.light_on(light['entity_id'], brightness=100)
    for lock_dev in devices.get('lock', []):
        client.unlock(lock_dev['entity_id'])


def _emergency_call(user_id, trigger, app):
    """Call senior via Twilio."""
    from twilio_voice_helpers import initiate_proactive_call, get_senior_phone
    phone = get_senior_phone(user_id)
    if not phone:
        raise ValueError(f"No phone for {user_id}")
    result = initiate_proactive_call(
        phone,
        "Dobrý den, tady Radim. Detekovali jsme možnou krizovou situaci. Jste v pořádku?",
        user_id=user_id, reason='emergency'
    )
    if not result.get('success'):
        raise RuntimeError(f"Call failed: {result.get('error')}")


def _emergency_sms(user_id, trigger, app):
    """SMS all emergency contacts."""
    from memory_helpers import db_load_profile
    from twilio_voice_helpers import send_sms
    profile = db_load_profile(user_id) or {}
    contacts = profile.get('emergency_contacts', [])
    name = profile.get('name', 'Senior')
    if not contacts:
        raise ValueError("No emergency contacts configured")
    sent = 0
    for contact in contacts:
        phone = contact.get('phone')
        if phone:
            send_sms(phone, f"🚨 KRIZE: {name} potřebuje pomoc! Důvod: {trigger}. Kontaktujte ho/ji prosím.")
            sent += 1
    if sent == 0:
        raise ValueError("No valid phone numbers in contacts")


def _emergency_push(user_id, trigger, app):
    """Push notification to senior + caregiver."""
    if not app:
        return
    try:
        from agent_loop import _push_to_senior, _alert_caregiver
        obs = {"type": "emergency", "severity": "CRISIS", "message": trigger, "details": {}}
        _push_to_senior(user_id, obs, app)
        _alert_caregiver(user_id, obs, app)
    except Exception as e:
        logger.debug(f"Push fallback: {e}")


def _alert_system_admin(user_id, trigger, results):
    """Last resort: alert system admin when all communication fails."""
    try:
        # Try Health Agent to log critical failure
        from radim_health_agent import run_agent_chat
        run_agent_chat(
            f"KRITICKÁ SITUACE: Pro seniora {user_id} selhalo volání i SMS. "
            f"Trigger: {trigger}. Výsledky: {results}. Vyžaduje manuální zásah."
        )
    except Exception:
        pass

    # Also log to stderr for Heroku monitoring
    import sys
    print(f"🚨🚨🚨 CRITICAL: Emergency communication failure for {user_id}: {trigger}", file=sys.stderr)


# ============================================
# 4. LIVE RISK ENDPOINT (for caregiver dashboard)
# ============================================
# Aggregates all signals into one live-updated risk view.

def get_live_risk_summary(user_id):
    """Get comprehensive real-time risk summary for caregiver.

    Combines: rhythm state, prediction, survey, recent observations.

    Returns:
        dict with all risk dimensions + recommended actions
    """
    summary = {
        'user_id': user_id,
        'timestamp': datetime.utcnow().isoformat(),
        'risk_score': 0,
        'risk_level': 'low',
        'brain_mode': 'HARMONY',
        'dimensions': {},
        'recent_alerts': [],
        'recommended_actions': []
    }

    # 1. Rhythm State
    try:
        from rhythm_state import compute_rhythm_state
        state = compute_rhythm_state(user_id)
        if state:
            summary['dimensions']['energy'] = round(state.energy, 2)
            summary['dimensions']['stress'] = round(state.stress, 2)
            summary['dimensions']['mood'] = round(state.mood, 2)
            summary['dimensions']['social_need'] = round(state.social_need, 2)
            summary['dimensions']['cognitive_load'] = round(state.cognitive_load, 2)
            summary['dimensions']['risk'] = round(state.risk, 2)
            summary['brain_mode'] = state.brain_mode
            summary['dimensions']['phase'] = state.rhythm_phase
            summary['dimensions']['interruptibility'] = round(state.interruptibility, 2)
    except Exception as e:
        logger.debug(f"Live risk — rhythm: {e}")

    # 2. Predictive Agent
    try:
        from predictive_agent import predict_risk
        prediction = predict_risk(user_id)
        summary['risk_score'] = prediction.get('risk_score', 0)
        summary['risk_level'] = prediction.get('risk_level', 'low')
        summary['prediction_signals'] = prediction.get('signals', {})
        summary['recommended_actions'] = prediction.get('recommended_actions', [])
    except Exception as e:
        logger.debug(f"Live risk — prediction: {e}")

    # 3. Survey Risk
    try:
        from survey_engine import compute_survey_risk
        survey = compute_survey_risk(user_id)
        summary['dimensions']['survey_score'] = survey.get('score', 0)
        summary['dimensions']['survey_severity'] = survey.get('severity', 'OK')
        if survey.get('severity') in ('WARNING', 'URGENT'):
            summary['recommended_actions'].append(f"Survey: {survey.get('summary', '')}")
    except Exception as e:
        logger.debug(f"Live risk — survey: {e}")

    # 4. Recent observations (last 24h)
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # X21.39: was SELECT `type` — but the column is observation_type
            # (per database_schema.py; also matches the INSERT statements
            # at lines 308 and 336 in this same file). Caregiver dashboard
            # "recent alerts" was silently empty for 24h windows because
            # this query threw "column type does not exist" and got
            # swallowed by the outer try/except.
            rows = db.execute("""
                SELECT observation_type, severity, message, created_at
                FROM agent_observations
                WHERE user_id = ? AND created_at > ?
                ORDER BY created_at DESC LIMIT 10
            """, (user_id, (datetime.utcnow() - timedelta(hours=24)).isoformat())).fetchall()

        for r in (rows or []):
            summary['recent_alerts'].append({
                'type': r[0], 'severity': r[1],
                'message': r[2], 'time': r[3]
            })
    except Exception as e:
        logger.debug(f"Live risk — observations: {e}")

    # 5. Family proposals pending
    try:
        from family_routes import get_pending_proposals
        proposals = get_pending_proposals(user_id)
        if proposals:
            summary['family_proposals'] = proposals
    except Exception:
        pass

    return summary


# ============================================
# 5. FLASK ROUTES — Live risk API
# ============================================

from flask import Blueprint, jsonify
agent_bridge_bp = Blueprint('agent_bridge', __name__, url_prefix='/api/bridge')


@agent_bridge_bp.route('/live-risk/<user_id>', methods=['GET'])
def api_live_risk(user_id):
    """Real-time aggregated risk summary for caregiver dashboard.

    GET /api/bridge/live-risk/<user_id>
    Returns: comprehensive risk with all dimensions.
    """
    try:
        summary = get_live_risk_summary(user_id)
        return jsonify({'success': True, **summary})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@agent_bridge_bp.route('/live-risk-all', methods=['GET'])
def api_live_risk_all():
    """Lightweight risk overview for ALL active seniors.

    GET /api/bridge/live-risk-all
    Returns: list of basic risk data (1 query, no per-user iteration).
    """
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # Single query: latest brain state per user + observation count
            rows = db.execute("""
                SELECT b.user_id, b.coherence, b.created_at,
                       (SELECT COUNT(*) FROM agent_observations o
                        WHERE o.user_id = b.user_id AND o.created_at > ?) as alert_count
                FROM brain_states b
                INNER JOIN (
                    SELECT user_id, MAX(created_at) as max_ts
                    FROM brain_states
                    WHERE created_at > ?
                    GROUP BY user_id
                ) latest ON b.user_id = latest.user_id AND b.created_at = latest.max_ts
                ORDER BY b.coherence DESC
                LIMIT 20
            """, (
                (datetime.utcnow() - timedelta(hours=24)).isoformat(),
                (datetime.utcnow() - timedelta(hours=48)).isoformat()
            )).fetchall()

        seniors = []
        for r in (rows or []):
            c = float(r[1]) if r[1] else 5.0
            risk_level = 'critical' if c > 27 else 'high' if c > 20 else 'medium' if c > 12 else 'low'
            brain_mode = 'CRISIS' if c > 27 else 'ALERT' if c > 12 else 'HARMONY'
            seniors.append({
                'user_id': r[0],
                'risk_score': min(100, int(c * 3.7)),
                'risk_level': risk_level,
                'brain_mode': brain_mode,
                'last_active': r[2],
                'recent_alerts': int(r[3]) if r[3] else 0,
                'dimensions': {'stress': min(1.0, c / 40.0)}
            })

        seniors.sort(key=lambda s: s.get('risk_score', 0), reverse=True)

        return jsonify({
            'success': True,
            'seniors': seniors,
            'count': len(seniors)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


logger.info("🌉 Agent Bridge loaded — reactive↔proactive, retry, live risk, text rhythm adaptation")
