# ============================================
# RADIM WHATSAPP ORCHESTRATOR v2.1.0
# ============================================
# Main chat endpoint + greeting + health.
# CRUD routes (tasks, medications, stories, voice/speak)
# moved to radim_service_routes.py
#
# Architecture (v2.1):
#   radim_helpers.py       — config, intent, safety, time/date extractors
#   radim_ai_engine.py     — Gemini wrapper, response parser, story templates
#   radim_service_routes.py — tasks, medications, stories, voice/speak
#   radim_orchestrator.py  (this file) — chat + greeting + health
# ============================================

from flask import Blueprint, request, jsonify, g
from auth_middleware import optional_auth
from rate_limiter import rate_limit
import logging
from datetime import datetime

from radim_helpers import (
    GEMINI_API_KEY, _extract_user_id, detect_intent, extract_time, extract_date,
    _safety_notify_caregivers, _safety_log_crisis_event
)
from radim_ai_engine import call_gemini_whatsapp
import os

logger = logging.getLogger(__name__)

radim_bp = Blueprint('radim', __name__)

# ============================================
# OPTIONAL IMPORTS (graceful fallback)
# ============================================

# Intent Resolver (v272 — local NLU)
try:
    from intent_resolver import resolve_intent as _resolve_intent
    _INTENT_RESOLVER = True
except ImportError:
    _INTENT_RESOLVER = False

# Memory system integration
try:
    from memory_routes import (
        build_personalized_prompt as _orch_build_prompt,
        get_conversation_messages as _orch_get_history,
        record_interaction as _orch_record,
        detect_mood as _orch_detect_mood
    )
    _ORCH_MEMORY_AVAILABLE = True
except ImportError:
    _ORCH_MEMORY_AVAILABLE = False

# Brain Engine — Ψ(t) = (C, E, R, S)
try:
    from radim_brain_routes import (
        compute_psi_state as _brain_psi,
        reinforcement_update as _brain_reinforce,
        decision_model as _brain_decision,
        derive_text_empathy_proxies as _brain_proxies,
    )
    _ORCH_BRAIN_AVAILABLE = True
except ImportError:
    _ORCH_BRAIN_AVAILABLE = False

# Text Rhythm Engine
try:
    from text_rhythm import (
        estimate_C_alpha_from_text as _tr_estimate,
        calculate_text_params as _tr_calc,
        build_anticipation_prompt as _tr_prompt,
        get_anticipation_metadata as _tr_meta,
        get_adjusted_generation_config as _tr_gen_config,
        enforce_crisis_limits as _tr_enforce
    )
    _ORCH_TEXT_RHYTHM = True
except ImportError:
    _ORCH_TEXT_RHYTHM = False

# Task Service (for AI action processing in chat)
try:
    from task_service import (
        create_task as _ts_create,
        log_medication as _ts_log_med,
        build_tasks_context as _ts_context
    )
    _ORCH_TASK_SERVICE = True
except ImportError:
    _ORCH_TASK_SERVICE = False


# ============================================
# MAIN CHAT ENDPOINT
# ============================================

@radim_bp.route('/api/radim/chat', methods=['POST', 'OPTIONS'])
@optional_auth
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def radim_chat():
    """Hlavní WhatsApp-styl chat endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.get_json(force=True, silent=True) or {}
        message = data.get('message', '')
        user_id = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
        mode = data.get('mode', 'senior')
        context = data.get('context', {})
        emotional_context = data.get('emotional_context', '')

        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400

        # v442: Input sanitizer — prompt injection defense
        try:
            from input_sanitizer import sanitize_input
            message, threat_level, threat_details = sanitize_input(message, user_id=user_id)
            if threat_level == 'blocked':
                return jsonify({
                    'success': True,
                    'response': message,  # safe replacement text
                    'intent': 'blocked',
                    'mode': mode
                })
        except ImportError:
            pass

        # Add emotional context from frontend (RadimEmpathyBridge)
        if emotional_context:
            context['emotional_state'] = emotional_context

        # v321: Neuron context from frontend KafanekNeurons
        neuron_ctx = data.get('neuron_context')
        if neuron_ctx and isinstance(neuron_ctx, dict):
            context['neuron_intervention'] = neuron_ctx

        intent = detect_intent(message)

        if intent == 'task':
            context['extracted_time'] = extract_time(message)
            context['extracted_date'] = extract_date(message)

        if intent == 'safety':
            msg_lower = message.lower()
            is_critical = any(w in msg_lower for w in ['155', '112', 'záchranka', 'záchranku', 'sebevražd', 'sebevrazd', 'chci umřít', 'chci umrit', 'zabij', 'nechci žít'])
            severity = 'critical' if is_critical else 'high'

            # v432: CRITICAL (explicit 155/suicide) → hardcoded fast response + notify
            # HIGH (pain, fall, breathing) → let AI respond with empathy, notify async
            import threading
            threading.Thread(
                target=_safety_notify_caregivers,
                args=(user_id, message, severity),
                daemon=True
            ).start()
            threading.Thread(
                target=_safety_log_crisis_event,
                args=(user_id, message, severity),
                daemon=True
            ).start()

            if is_critical:
                # Explicit emergency call → fast hardcoded response
                return jsonify({
                    'success': True,
                    'response': 'Jsem tady s vámi. Dýchejte pomalu. Volám záchranku a informuji vaši rodinu. Zůstaňte v klidu, pomoc je na cestě.',
                    'radim_action': {
                        'type': 'safety_alert',
                        'payload': {'user_id': user_id, 'severity': severity, 'message': message},
                        'ui': {'suggested_buttons': ['Zavolat 155', 'Kontaktovat rodinu', 'Jsem v pořádku']}
                    },
                'intent': 'safety',
                'brain_C': 35.0,
                'brain_mode': 'CRISIS',
                'mode': mode
            })
            else:
                # HIGH severity (pain, fall, breathing) → empathetic structured response
                # AI in CRISIS mode gives too-short answers, so we build it here
                msg_lower = message.lower()
                if any(w in msg_lower for w in ['dýchat', 'dech', 'dušnost', 'hrud']):
                    crisis_resp = 'Jsem tady s vámi, nikam neodcházím. Zkuste se posadit a dýchat pomalu — nádech nosem, výdech ústy. Bolí to stále stejně, nebo se to mění? Doporučuji zavolat záchrannou službu na 155. Chcete, abych zavolal?'
                elif any(w in msg_lower for w in ['spadl', 'upadl', 'nemůžu vstát', 'nemuzu vstat', 'zlomen']):
                    crisis_resp = 'Hlavně se nehýbejte a zůstaňte na místě. Bolí vás i hlava, nebo jen to místo kde jste spadl? Pro jistotu doporučuji zavolat na 155. Chcete, abych zavolal záchranku nebo rodinu?'
                elif any(w in msg_lower for w in ['krev', 'rána', 'řízl', 'pořezal']):
                    crisis_resp = 'Zůstaňte v klidu. Přitiskněte na ránu čistý hadřík a držte tlak. Je to velká rána? Doporučuji zavolat záchranku na 155.'
                else:
                    crisis_resp = 'Slyším, že vám není dobře, a jsem tady s vámi. Posaďte se nebo si lehněte. Můžete mi říct víc o tom, co cítíte? Pokud je to vážné, doporučuji zavolat na 155. Chcete, abych zavolal lékaře nebo rodinu?'

                return jsonify({
                    'success': True,
                    'response': crisis_resp,
                    'radim_action': {
                        'type': 'safety_alert',
                        'payload': {'user_id': user_id, 'severity': 'high', 'message': message},
                        'ui': {'suggested_buttons': ['Zavolat lékaře', 'Zavolat rodinu', 'Jsem v pořádku']}
                    },
                    'intent': 'safety',
                    'mode': 'CRISIS',
                    'brain_C': 30.0,
                    'brain_mode': 'CRISIS',
                })

        # Load personalization and history from memory
        personalized = ''
        history = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                personalized = _orch_build_prompt(user_id)
                history = _orch_get_history(user_id, limit=15)
            except Exception as mem_err:
                logger.warning(f"Memory load warning: {mem_err}")

        # Load pending tasks context for AI awareness
        if _ORCH_TASK_SERVICE:
            try:
                tasks_ctx = _ts_context(user_id)
                if tasks_ctx:
                    personalized += tasks_ctx
            except Exception as tc_err:
                logger.warning(f"Tasks context warning: {tc_err}")

        # Text Rhythm: matematika → styl textu
        anticipation_prompt = ''
        anticipation_meta = None
        gen_config = None
        C = 5.0
        alpha = 0.0
        mood = "neutral"
        if _ORCH_TEXT_RHYTHM:
            try:
                C_val = data.get('C')
                alpha_val = data.get('alpha')

                if C_val is not None and alpha_val is not None:
                    C = float(C_val)
                    alpha = float(alpha_val)
                else:
                    mood = _orch_detect_mood(message) if _ORCH_MEMORY_AVAILABLE else "neutral"
                    baseline_C = None
                    if _ORCH_MEMORY_AVAILABLE:
                        try:
                            from memory_routes import _db_load_profile
                            _prof = _db_load_profile(user_id)
                            baseline_C = _prof.get('baseline_C')
                            if baseline_C is not None:
                                baseline_C = float(baseline_C)
                        except Exception:
                            pass
                    C, alpha = _tr_estimate(message, mood, user_baseline_C=baseline_C)

                text_result = _tr_calc(C, alpha)
                anticipation_prompt = _tr_prompt(text_result)
                anticipation_meta = _tr_meta(text_result)
                gen_config = _tr_gen_config(text_result)
            except Exception as tr_err:
                logger.warning(f"Text rhythm warning (non-fatal): {tr_err}")

        # Brain Engine: Ψ(t) = (C, E, R, S)
        brain_meta = None
        if _ORCH_BRAIN_AVAILABLE:
            try:
                proxies = _brain_proxies(message, mood, alpha)
                psi_state = _brain_psi(
                    C, alpha,
                    proxies["voice_tone"], proxies["hrv"], proxies["speech_tempo"],
                    user_id=user_id
                )
                decision = _brain_decision(
                    C, psi_state["psi"]["E"], psi_state["psi"]["R"], psi_state["psi"]["S"]
                )
                brain_meta = {
                    "psi": psi_state["psi"],
                    "mode": psi_state["mode"],
                    "decision": decision["level"],
                    "coherence": psi_state["coherence"],
                    "phi_index": psi_state.get("phi_index"),
                    "rho_stability": psi_state.get("rho_stability")
                }
                if psi_state.get("rhythm_return"):
                    brain_meta["rhythm_return"] = psi_state["rhythm_return"]
                personalized += f"\n\n[RADIM Brain: mode={psi_state['mode']}, coherence={psi_state['coherence']:.2f}]\n{decision['instructions']}"
            except Exception as brain_err:
                logger.warning(f"Brain warning (non-fatal): {brain_err}")

        # Intent Resolver: short-circuit simple queries locally (v272)
        action_json = None
        text_response = None
        _resolved_intent = intent
        if _INTENT_RESOLVER:
            try:
                _brain_mode = brain_meta.get("mode", "HARMONY") if brain_meta else "HARMONY"
                _resolved_text, _resolved_intent, _resolved_meta = _resolve_intent(message, user_id, _brain_mode)
                if _resolved_text:
                    text_response = _resolved_text
                    logger.info(f"🎯 Intent '{_resolved_intent}' resolved locally for {user_id}")
            except Exception as ir_err:
                logger.warning(f"Intent resolver warning (non-fatal): {ir_err}")

        # v321+v3: Inject neuron intervention + rhythm into AI prompt
        if neuron_ctx:
            ntype = neuron_ctx.get('type', 'unknown')
            ntone = neuron_ctx.get('tone', 'patient')
            nhint = neuron_ctx.get('hint', '')
            nrhythm = neuron_ctx.get('rhythm')
            personalized += f"\n\n═══ NEURONOVÁ INTERVENCE ({ntype}) ═══\n"
            personalized += f"Tón: {ntone}. "
            if nhint:
                personalized += f"Nápověda: {nhint}\n"
            if nrhythm:
                rmode = nrhythm.get('mode', 'HARMONY')
                personalized += f"[Ψ-rytmus: {rmode}, koherence: {nrhythm.get('coherence', 0.8):.1f}] "
            personalized += "Přizpůsob odpověď — buď extra trpělivý, klidný a empatický."

        # v451: Unified Context Builder — replaces scattered emotional/relationship/coherence logic
        _emotional_state = {}
        _radim_context = None
        try:
            from self_healing import detect_emotional_state
            from context_builder import build_radim_context, context_to_prompt_section, meta_observe, compress_memory
            _emotional_state = detect_emotional_state(message)

            # Build unified context
            _brain_for_ctx = None
            if _ORCH_BRAIN_AVAILABLE:
                try:
                    _brain_for_ctx = {'phi_index': anticipation_meta.get('phi_index', 0.5) if anticipation_meta else 0.5,
                                      'rho_stability': anticipation_meta.get('rho_stability', 0.5) if anticipation_meta else 0.5,
                                      'mode': _brain_mode_val or 'HARMONY'}
                except Exception:
                    pass

            _rel_data = None
            try:
                from relationship_engine import identify_relationship
                _rel_data = identify_relationship(user_id)
            except Exception:
                pass

            _learn_data = None
            try:
                from memory_helpers import db_load_learning
                _learn_data = db_load_learning(user_id)
            except Exception:
                pass

            _radim_context = build_radim_context(
                user_id, message,
                brain_state=_brain_for_ctx,
                relationship=_rel_data,
                emotional_state=_emotional_state,
                learning_data=_learn_data
            )

            # Inject context into prompt
            ctx_prompt = context_to_prompt_section(_radim_context)
            personalized += "\n" + ctx_prompt

            # Compress memory periodically
            if _learn_data and _learn_data.get('interaction_count', 0) % 50 == 0:
                try:
                    compressed = compress_memory(_learn_data)
                    from memory_helpers import db_save_learning
                    db_save_learning(user_id, compressed)
                except Exception:
                    pass

        except ImportError:
            # Fallback to old emotional detection
            try:
                from self_healing import detect_emotional_state
                _emotional_state = detect_emotional_state(message)
            except ImportError:
                pass

        if _emotional_state.get('needs_simplification'):
            personalized += "\n═══ UŽIVATEL POTŘEBUJE JEDNODUŠŠÍ KOMUNIKACI ═══\n"
            if _emotional_state.get('confused'):
                personalized += "Uživatel nerozumí. Mluv POMALEJI, KRATŠÍ věty, OPAKUJ klíčové info.\n"
            if _emotional_state.get('stressed'):
                personalized += "Uživatel je ve stresu. Začni uklidněním. Žádné otázky, jen podpora.\n"

        # ═══ v456: HYBRID LLM ROUTER ═══
        # Claude = primary (empatie, zdraví, vztahy, kognitivní pipeline)
        # Gemini = fallback (rychlý, levný, spolehlivý)
        # Static = last resort (circuit breakers open)
        _ai_provider = None
        _brain_C_val = None
        _brain_mode_val = None
        if text_response is None:
            try:
                from self_healing import get_breaker, log_healing_event
                from claude_helpers import get_claude_client, extract_text_from_response, CLAUDE_MODEL

                # ── PRIMARY: Claude (empatie, 7-step pipeline) ──
                claude_breaker = get_breaker('claude')
                if claude_breaker.can_proceed():
                    try:
                        client = get_claude_client()
                        if client:
                            _sys = personalized or "Jsi Radim, český AI asistent péče. Odpovídej česky, stručně, s diakritikou."
                            # Build messages with history
                            _msgs = []
                            if history:
                                for h in history[-10:]:
                                    _msgs.append({"role": h.get("role", "user"), "content": h.get("content", "")})
                            _msgs.append({"role": "user", "content": message})

                            claude_resp = client.messages.create(
                                model=CLAUDE_MODEL,
                                max_tokens=400,
                                system=_sys,
                                messages=_msgs
                            )
                            text_response = extract_text_from_response(claude_resp)
                            if text_response:
                                claude_breaker.record_success()
                                _ai_provider = 'claude'
                                print(f"🧠 Claude primary for {user_id}")
                            else:
                                claude_breaker.record_failure()
                                log_healing_event('empty_response', 'claude', {'message': message[:50]})
                    except Exception as e:
                        claude_breaker.record_failure()
                        log_healing_event('exception', 'claude', {'error': str(e)[:100]})
                        print(f"❌ Claude FAILED: {type(e).__name__}: {e}")
                else:
                    log_healing_event('circuit_open', 'claude')

                # ── FALLBACK: Gemini (if Claude failed) ──
                if not text_response:
                    gemini_breaker = get_breaker('gemini')
                    if gemini_breaker.can_proceed():
                        try:
                            text_response, action_json = call_gemini_whatsapp(
                                message, context, mode, personalized, history,
                                anticipation_prompt, gen_config
                            )
                            if text_response:
                                gemini_breaker.record_success()
                                _ai_provider = 'gemini'
                                print(f"🔄 Gemini fallback for {user_id}")
                            else:
                                gemini_breaker.record_failure()
                        except Exception as e:
                            gemini_breaker.record_failure()
                            log_healing_event('exception', 'gemini', {'error': str(e)[:100]})
                    else:
                        log_healing_event('circuit_open', 'gemini')

            except ImportError:
                # No self-healing — try Gemini directly
                text_response, action_json = call_gemini_whatsapp(
                    message, context, mode, personalized, history,
                    anticipation_prompt, gen_config
                )

        if not text_response:
            try:
                from self_healing import safe_response
                text_response = safe_response(intent=intent, user_message=message, is_crisis=(intent == 'safety'))
            except ImportError:
                text_response = "Promiňte, zkuste to za chvíli. 🙏"

        # v448: Apply emotional healing to response
        if _emotional_state.get('needs_simplification') and text_response:
            try:
                from self_healing import apply_emotional_healing
                text_response, _ = apply_emotional_healing(text_response, _emotional_state)
            except ImportError:
                pass

        # v439: SAFETY GATE — hardcoded 155 injection for crisis keywords
        # Gemini sometimes ignores prompt rules, so we enforce programmatically
        _crisis_kw = ['bolí mě na hrudi', 'nemůžu dýchat', 'dušnost', 'spadl jsem', 'nemůžu vstát',
                       'bolest na hrudi', 'hrudník', 'nemohu dýchat', 'ztrácím vědomí', 'mdloba']
        _msg_lower = message.lower()
        if any(kw in _msg_lower for kw in _crisis_kw):
            if '155' not in text_response and '112' not in text_response:
                text_response += ' Doporučuji zavolat záchrannou službu na číslo 155.'
                logger.info(f"🚨 Safety gate: injected 155 into response for user {user_id}")

        # Crisis enforcement: hard limit na počet vět (ALERT/CRISIS)
        if _ORCH_TEXT_RHYTHM and anticipation_meta and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                text_response = _tr_enforce(text_response, {
                    'state': anticipation_meta.get('state', 'HARMONY'),
                    'params': anticipation_meta.get('text_params', {})
                })
            except Exception:
                pass

        # Process AI actions (create_task, log_health from ---RADIM_ACTION---)
        if action_json and _ORCH_TASK_SERVICE:
            try:
                action_type = action_json.get('type', 'none')
                payload = action_json.get('payload', {})

                if action_type == 'create_task':
                    task = _ts_create(
                        user_id=user_id,
                        title=payload.get('title', 'Připomínka od Radima'),
                        task_type=payload.get('task_type', 'reminder'),
                        scheduled_time=payload.get('time') or extract_time(message),
                        scheduled_date=payload.get('date') or extract_date(message),
                        description=payload.get('description')
                    )
                    if task:
                        action_json['created_task'] = task
                        logger.info(f"📋 AI created task: #{task['id']} '{task['title']}'")

                elif action_type == 'log_health':
                    _ts_log_med(
                        user_id=user_id,
                        medication_name=payload.get('medication', payload.get('name', 'nespecifikováno')),
                        dosage=payload.get('dosage'),
                        notes=payload.get('notes', message[:200])
                    )
                    logger.info(f"💊 AI logged medication for {user_id}")
            except Exception as act_err:
                logger.warning(f"Action processing warning: {act_err}")

        # Record interaction to memory
        if _ORCH_MEMORY_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                _brain_C_val = brain_meta["psi"]["C"] if brain_meta else None
                _brain_mode_val = brain_meta["mode"] if brain_meta else None
                _orch_record(user_id, message, text_response, brain_C=_brain_C_val, brain_mode=_brain_mode_val)
            except Exception as rec_err:
                logger.warning(f"Memory record warning: {rec_err}")

        # v452: Voice profile learning — detect "pomaleji", "hlasitěji"
        try:
            from voice_profile_engine import learn_from_message
            learn_from_message(user_id, message)
        except (ImportError, Exception):
            pass

        # Brain reinforcement: adapt per-user after response
        if _ORCH_BRAIN_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                success = intent != "safety" and bool(text_response)
                _brain_reinforce(success, user_id=user_id)
            except Exception:
                pass

        result = {
            'success': True,
            'response': text_response,
            'radim_action': action_json,
            'intent': _resolved_intent if _INTENT_RESOLVER else intent,
            'mode': mode,
            'ai_provider': _ai_provider or 'local',
            'brain_C': _brain_C_val,
            'brain_mode': _brain_mode_val,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        if anticipation_meta:
            result['anticipation'] = anticipation_meta
        if brain_meta:
            result['brain'] = brain_meta
        # v522: Relationship trust
        try:
            from relationship_engine import identify_relationship
            rel = identify_relationship(user_id)
            result['relationship'] = {
                'type': rel.get('type'),
                'trust': rel.get('trust'),
                'permission': rel.get('permission_level'),
            }
        except Exception:
            pass
        return jsonify(result)

    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================
# INTERNAL CHAT API (v387 — for WhatsApp, proactive calls, etc.)
# ============================================

def radim_chat_internal(message, user_id=None, mode="senior"):
    """Call Radim chat pipeline without HTTP request context.

    Used by: WhatsApp webhook, proactive calls, scheduled reminders.

    Returns:
        dict: {success, response, intent}
    """
    try:
        if not message:
            return {"success": False, "response": "Promiňte, nerozuměl jsem.", "intent": None}

        user_id = user_id or "anonymous"

        # Intent resolver first
        text_response = None
        intent = detect_intent(message)

        if _INTENT_RESOLVER:
            try:
                _resolved_text, intent, _ = _resolve_intent(message, user_id, "HARMONY")
                if _resolved_text:
                    text_response = _resolved_text
            except Exception:
                pass

        # AI call if intent not resolved locally
        if text_response is None:
            personalized = ""
            history = None
            if _ORCH_MEMORY_AVAILABLE:
                try:
                    personalized = _orch_build_prompt(user_id)
                    history = _orch_get_history(user_id, limit=15)
                except Exception:
                    pass

            text_response, _ = call_gemini_whatsapp(
                message, {}, mode, personalized, history, "", None
            )

        if not text_response:
            text_response = "Omlouvám se, zkuste to prosím později."

        # Record to memory + compute brain state
        brain_mode = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                _orch_record(user_id, message, text_response)
            except Exception:
                pass

        # v394: Brain Ψ(t) computation for WhatsApp/calls
        try:
            from brain_core import compute_psi_state
            from intent_resolver import quick_estimate_from_text
            C_est, alpha_est = quick_estimate_from_text(message)
            psi = compute_psi_state(C_est, alpha_est, user_id=user_id)
            brain_mode = psi.get("mode", "HARMONY")
        except Exception:
            pass

        return {"success": True, "response": text_response, "intent": intent, "brain_mode": brain_mode}

    except Exception as e:
        logger.error(f"radim_chat_internal error: {e}")
        return {"success": False, "response": "Nastala chyba, omlouvám se.", "intent": None}


# ============================================
# GREETING + HEALTH
# ============================================

@radim_bp.route('/api/radim/greeting', methods=['GET'])
def radim_greeting():
    """Time-based greeting — single source of truth for all frontends"""
    try:
        from radim_shared import get_greeting, get_nameday, build_time_context_string
        greeting_emoji = get_greeting(with_emoji=True)
        greeting_plain = get_greeting(with_emoji=False)
        nameday = get_nameday()
        time_ctx = build_time_context_string()

        return jsonify({
            'success': True,
            'greeting': greeting_emoji,
            'greeting_plain': greeting_plain,
            'nameday': nameday or None,
            'time_context': time_ctx,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
    except Exception as e:
        # Minimal fallback
        hour = datetime.now().hour
        if 5 <= hour < 12:
            g_text = "Dobré ráno! ☀️"
        elif 12 <= hour < 18:
            g_text = "Dobré odpoledne! 🌤️"
        elif 18 <= hour < 22:
            g_text = "Dobrý večer! 🌙"
        else:
            g_text = "Dobrou noc! 🌟"
        return jsonify({'success': True, 'greeting': g_text, 'timestamp': datetime.utcnow().isoformat() + 'Z'})


@radim_bp.route('/api/radim/health', methods=['GET'])
def radim_health():
    """Health check"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'service': 'Radim WhatsApp Orchestrator',
        'version': '2.1.0',
        'features': {
            'whatsapp_chat': True,
            'task_management': _ORCH_TASK_SERVICE,
            'voice_synthesis': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'anticipation_engine': _ORCH_TEXT_RHYTHM,
            'brain_engine': _ORCH_BRAIN_AVAILABLE,
            'memory': _ORCH_MEMORY_AVAILABLE,
            'ai_provider': 'claude+gemini (hybrid)'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })
