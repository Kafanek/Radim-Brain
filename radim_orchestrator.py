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
                    'mode': mode,
                    'voice_mode': 'HARMONY',
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
                'voice_mode': 'CRISIS',
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
                    'voice_mode': 'CRISIS',
                })

        # ═══ ONBOARDING — detect new user, ask for basics ═══
        try:
            from memory_helpers import db_load_profile, db_load_learning
            _profile = db_load_profile(user_id) or {}
            _learning = db_load_learning(user_id) or {}
            _interaction_count = _learning.get('interaction_count', 0)

            # First 3 interactions → onboarding mode
            # But SKIP onboarding if message already contains personal info
            msg_has_info = any(w in message.lower() for w in ['jmenuj', 'jsem', 'beru', 'léky', 'dcera', 'syn', 'manžel'])
            if _interaction_count < 3 and not _profile.get('name') and not msg_has_info:
                onboard_msg = ''
                if _interaction_count == 0:
                    onboard_msg = 'Ahoj! Jsem Radim, váš osobní asistent. Rád vás poznám. Jak se jmenujete?'
                elif _interaction_count == 1 and not _profile.get('medications_list'):
                    onboard_msg = 'Děkuji! Abych vám mohl lépe pomáhat — berete nějaké léky pravidelně? Klidně mi řekněte které.'
                elif _interaction_count == 2 and not _profile.get('contacts'):
                    onboard_msg = 'Výborně! Poslední věc — na koho mám zavolat v případě potřeby? Řekněte mi jméno a telefon nejbližšího člověka.'

                if onboard_msg:
                    # Increment interaction count
                    _learning['interaction_count'] = _interaction_count + 1
                    try:
                        from memory_helpers import db_save_learning
                        db_save_learning(user_id, _learning)
                    except Exception:
                        pass

                    return jsonify({
                        'success': True,
                        'response': onboard_msg,
                        'intent': 'onboarding',
                        'mode': mode,
                        'voice_mode': 'HARMONY',
                        'onboarding_step': _interaction_count,
                    })
        except Exception as onboard_err:
            logger.debug(f"Onboarding check (non-fatal): {onboard_err}")

        # ═══ RHYTHM-AWARE MULTI-AGENT LAYER ═══
        # Compute rhythm state and let agents decide before AI
        rhythm_context = ''
        rhythm_meta = {}
        try:
            from rhythm_state import compute_rhythm_state
            from agent_coordinator import pick_best_action
            from response_composer import compose_response

            rhythm = compute_rhythm_state(user_id)
            rhythm_meta = {
                'energy': round(rhythm.energy, 2),
                'stress': round(rhythm.stress, 2),
                'phase': rhythm.rhythm_phase,
                'tone': rhythm.preferred_tone,
                'speech_rate': rhythm.speech_rate,
                'pause_ms': rhythm.pause_ms,
                'mode': rhythm.brain_mode,
            }

            # Let agents evaluate (safety/care might override AI)
            decision = pick_best_action(rhythm, message)
            if decision and decision.should_act and decision.action == 'escalate':
                # Safety agent takes over — skip AI, return immediately
                composed = compose_response(decision, rhythm)
                return jsonify({
                    'success': True,
                    'response': composed.text,
                    'intent': 'safety',
                    'brain_mode': rhythm.brain_mode,
                    'brain_C': rhythm.coherence,
                    'voice_mode': 'CRISIS' if rhythm.brain_mode == 'CRISIS' else 'ALERT',
                    'speech_rhythm': rhythm_meta,
                    'agent': decision.agent_name,
                    'mode': mode
                })

            # Inject rhythm context into AI prompt
            rhythm_context = f"\n═══ RHYTHM STATE ═══\n"
            rhythm_context += f"Energie: {rhythm.energy:.1f}/1.0 | Stres: {rhythm.stress:.1f} | Fáze: {rhythm.rhythm_phase}\n"
            rhythm_context += f"Tón: {rhythm.preferred_tone} | Délka odpovědi: {rhythm.response_length}\n"
            if rhythm.should_be_quiet:
                rhythm_context += "POZOR: Senior by měl odpočívat. Odpovídej stručně a jemně.\n"
            if rhythm.needs_comfort:
                rhythm_context += "POZOR: Senior potřebuje útěchu. Buď empatický a laskavý.\n"
            if decision and decision.agent_name == 'care':
                rhythm_context += f"Care Agent doporučuje: {decision.tone} tón. {decision.reason}\n"

        except Exception as rhythm_err:
            logger.debug(f"Rhythm layer (non-fatal): {rhythm_err}")

        # Load personalization and history from memory
        personalized = ''
        history = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                personalized = _orch_build_prompt(user_id)
                history = _orch_get_history(user_id, limit=15)
            except Exception as mem_err:
                logger.warning(f"Memory load warning: {mem_err}")

        # v10.4: Personal Growth Engine — inject personalized context
        try:
            from personal_growth import build_personal_context, extract_memorable_topics
            growth_ctx = build_personal_context(user_id)
            if growth_ctx:
                personalized += '\n\n═══ OSOBNÍ KONTEXT ═══\n' + growth_ctx
        except (ImportError, Exception) as ge:
            logger.debug(f"Personal growth context: {ge}")

        # Load pending tasks context for AI awareness
        if _ORCH_TASK_SERVICE:
            try:
                tasks_ctx = _ts_context(user_id)
                if tasks_ctx:
                    personalized += tasks_ctx
            except Exception as tc_err:
                logger.warning(f"Tasks context warning: {tc_err}")

        # Inject rhythm context into personalization
        if rhythm_context:
            personalized += rhythm_context

        # v10.6: Family proposals — inject pending proposals from family
        try:
            from family_routes import get_pending_proposals
            family_ctx = get_pending_proposals(user_id)
            if family_ctx:
                personalized += '\n\n═══ ' + family_ctx + '\n'
                personalized += 'Pokud se senior zeptá co dělat, navrhni aktivity od rodiny.\n'
        except (ImportError, Exception):
            pass

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

        # v10.1: Scenario Engine — detect situation and use trained response
        if text_response is None:
            try:
                from scenario_engine import detect_scenario, generate_scenario_response, execute_scenario_actions
                scenario = detect_scenario(message, user_id)
                if scenario:
                    sr = generate_scenario_response(scenario, user_id, message)
                    # For crisis/high scenarios, use trained response directly (no AI needed)
                    if scenario['severity'] in ('critical', 'high'):
                        text_response = sr['text']
                        _resolved_intent = 'scenario_' + scenario['id']
                        brain_meta = brain_meta or {}
                        brain_meta['tts_mode'] = sr.get('tts_mode', 'alert')
                        # Execute side effects (notify, HA, log)
                        execute_scenario_actions(sr.get('actions'), user_id)
                        logger.info(f"🎭 Scenario '{scenario['id']}' ({scenario['severity']}) for {user_id}")
                    elif scenario['severity'] == 'medium':
                        # Medium: use as context hint for AI, let AI respond with empathy
                        personalized += f"\n\nDŮLEŽITÉ: Senior právě zmínil situaci '{scenario['id']}' ({scenario['category']}). " \
                                       f"Doporučená odpověď: {sr['text'][:150]}... Odpověz empaticky a podpůrně."
                        execute_scenario_actions(sr.get('actions'), user_id)
            except ImportError:
                pass
            except Exception as se_err:
                logger.debug(f"Scenario engine: {se_err}")

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

        # ⚡ AI Response Cache — skip LLM for repeated messages (5min TTL)
        if text_response is None:
            try:
                from scaling_optimizations import ai_cache
                cached = ai_cache.get(message, user_id, mode)
                if cached:
                    text_response = cached
                    _ai_provider = 'cache'
                    logger.debug(f"AI cache HIT: {message[:30]}...")
            except ImportError:
                pass

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

        # ⚡ Cache successful AI response (5min TTL)
        if text_response and _ai_provider in ('gemini', 'claude'):
            try:
                from scaling_optimizations import ai_cache
                ai_cache.put(message, text_response, user_id, mode)
            except Exception:
                pass

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

        # v10.4: Extract memorable topics for future follow-up
        try:
            from personal_growth import extract_memorable_topics
            extract_memorable_topics(user_id, message, text_response)
        except (ImportError, Exception):
            pass

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

        # v10.1: Anticipation Engine → speech rhythm adaptation
        _speech_rhythm = None
        try:
            from anticipation_engine import anticipate
            antic = anticipate(user_id)
            if antic and antic.get('speech_adaptation'):
                sa = antic['speech_adaptation']
                _speech_rhythm = {
                    'rate_factor': sa.get('rate_factor', 1.0),
                    'pause_delta_ms': sa.get('pause_delta_ms', 0),
                    'empathy_delta': sa.get('empathy_delta', 0),
                    'predicted_mode': antic.get('predicted', {}).get('mode_predicted', 'HARMONY'),
                    'risk_direction': antic.get('risk_direction', 'stable'),
                    'C_hat': antic.get('predicted', {}).get('C_hat'),
                    'emotions': antic.get('predicted_emotions', {}),
                }
                # Override brain_mode if anticipation predicts transition
                if antic.get('breaking_points', {}).get('B27') and _brain_mode_val != 'CRISIS':
                    _brain_mode_val = 'CRISIS'
                    logger.info(f"🔮 Anticipation override: B₂₇ → CRISIS for {user_id}")
                elif antic.get('breaking_points', {}).get('B12') and _brain_mode_val == 'HARMONY':
                    _brain_mode_val = 'ALERT'
                    logger.info(f"🔮 Anticipation override: B₁₂ → ALERT for {user_id}")
        except Exception as ae:
            logger.debug(f"Anticipation rhythm: {ae}")

        # v10.18: Autonomous voice mode selection for HTTP endpoint
        _voice_mode = _brain_mode_val or 'HARMONY'
        try:
            from voice_melody import match_song
            from voice_learning import should_use_melody

            # Music intent → SINGING
            _final_intent = _resolved_intent if _INTENT_RESOLVER else intent
            if _final_intent == 'music':
                _voice_mode = 'SINGING'
            elif text_response and match_song(text_response):
                _voice_mode = 'SINGING'
            # Also check learned melodies
            elif text_response:
                try:
                    from voice_music import enhanced_match_song
                    _mc, _md = enhanced_match_song(text_response)
                    if _mc:
                        _voice_mode = 'SINGING'
                except (ImportError, Exception):
                    pass

            if _voice_mode not in ('SINGING',):
                if _brain_mode_val in ('CRISIS', 'ALERT'):
                    _voice_mode = _brain_mode_val
                elif _brain_mode_val == 'HARMONY' and user_id:
                    if should_use_melody(str(user_id)):
                        _voice_mode = 'RHYTHMIC'
                        hour = datetime.utcnow().hour + 1  # CET ≈ UTC+1
                        if hour < 6 or hour > 21:
                            _voice_mode = 'HARMONY'
        except (ImportError, Exception):
            pass

        result = {
            'success': True,
            'response': text_response,
            'radim_action': action_json,
            'intent': _resolved_intent if _INTENT_RESOLVER else intent,
            'mode': mode,
            'voice_mode': _voice_mode,
            'ai_provider': _ai_provider or 'local',
            'brain_C': _brain_C_val,
            'brain_mode': _brain_mode_val,
            'speech_rhythm': rhythm_meta if rhythm_meta else _speech_rhythm,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        if rhythm_meta:
            result['rhythm_state'] = rhythm_meta

        # ═══ CONVERSATION MEMORY — auto-extract facts from chat ═══
        try:
            from conversation_memory import extract_and_save
            import threading
            threading.Thread(
                target=extract_and_save,
                args=(user_id, message, result.get('response', '')),
                daemon=True
            ).start()
        except Exception:
            pass

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

        # v10.10: Update last_active for subscription tracking
        try:
            with db_context(commit=True) as _db:
                _db.execute("UPDATE auth_users SET last_active = NOW() WHERE id = ?", (int(user_id),))
        except Exception:
            pass

        # v10.17: Autonomous voice mode selection
        # Orchestrátor rozhodne JAK mluvit na základě kontextu + brain state
        voice_mode = brain_mode or 'HARMONY'
        try:
            from voice_melody import match_song
            from voice_learning import should_use_melody, get_voice_prefs

            # 1. Je odpověď píseň? → SINGING
            if text_response and match_song(text_response):
                voice_mode = 'SINGING'
            # 2. CRISIS/ALERT → beze změny (safety)
            elif brain_mode in ('CRISIS', 'ALERT'):
                voice_mode = brain_mode
            # 3. HARMONY + uživatel preferuje melodii → RHYTHMIC
            elif brain_mode == 'HARMONY' and user_id:
                if should_use_melody(str(user_id)):
                    voice_mode = 'RHYTHMIC'
                    # Ráno = veselejší, večer = klidnější
                    try:
                        from datetime import datetime
                        hour = datetime.utcnow().hour + 1  # CET ≈ UTC+1
                        if hour < 6 or hour > 21:
                            voice_mode = 'HARMONY'  # Noc — klidný
                    except Exception:
                        pass
        except (ImportError, Exception):
            pass

        return {
            "success": True, "response": text_response,
            "intent": intent, "brain_mode": brain_mode,
            "voice_mode": voice_mode,  # Frontend předá TTS
        }

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
