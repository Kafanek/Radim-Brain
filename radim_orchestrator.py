# ============================================
# RADIM WHATSAPP ORCHESTRATOR
# ============================================
# Version: 2.0.0 (modular)
# WhatsApp styl chat s action JSON
#
# Architecture (v2.0):
#   radim_helpers.py    — config, intent, safety, time/date extractors
#   radim_ai_engine.py  — Gemini wrapper, response parser, story templates
#   radim_orchestrator.py (this file) — Blueprint + route handlers
#
# Routes:
#   POST /api/radim/chat              — Main WhatsApp-style chat
#   GET|POST|PUT|DELETE /api/radim/tasks — Task management
#   GET|POST /api/radim/medications   — Medication tracking
#   GET  /api/radim/stories/templates — Story templates
#   POST /api/radim/stories/generate  — Story generation
#   POST /api/radim/voice/speak       — Azure TTS
#   GET  /api/radim/greeting          — Time-based greeting
#   GET  /api/radim/health            — Health check

from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth
from rate_limiter import rate_limit
import requests
import json
import re
import os
import base64
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
import logging

# Import from helper modules
from radim_helpers import (
    GEMINI_API_KEY, WP_URL, WP_USER, WP_APP_PASSWORD,
    _extract_user_id, detect_intent, extract_time, extract_date,
    _safety_notify_caregivers, _safety_log_crisis_event
)
from radim_ai_engine import (
    call_gemini_whatsapp, parse_radim_response, STORY_TEMPLATES
)

logger = logging.getLogger(__name__)

radim_bp = Blueprint('radim', __name__)

# ============================================
# OPTIONAL IMPORTS (graceful fallback)
# ============================================

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _orch_predict_C, calculate_emotions as _orch_emotions,
        calculate_speech_params as _orch_speech_params, classify_state as _orch_classify
    )
    _ORCH_ANT_AVAILABLE = True
except ImportError:
    _ORCH_ANT_AVAILABLE = False

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

# 🧠 Brain Engine — Ψ(t) = (C, E, R, S)
try:
    from radim_brain_routes import (
        compute_psi_state as _brain_psi,
        reinforcement_update as _brain_reinforce,
        decision_model as _brain_decision,
        derive_text_empathy_proxies as _brain_proxies,
        get_brain_speech_for_user as _brain_speech_for_user
    )
    _ORCH_BRAIN_AVAILABLE = True
except ImportError:
    _ORCH_BRAIN_AVAILABLE = False

# 🎵 Text Rhythm Engine — matematika řídí styl textu
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

# 📋 Task Service — úkoly a léky s persistencí
try:
    from task_service import (
        create_task as _ts_create,
        get_tasks as _ts_get,
        complete_task as _ts_complete,
        log_medication as _ts_log_med,
        get_medication_history as _ts_med_history,
        build_tasks_context as _ts_context
    )
    _ORCH_TASK_SERVICE = True
except ImportError:
    _ORCH_TASK_SERVICE = False


# ============================================
# ENDPOINTS
# ============================================

@radim_bp.route('/api/radim/chat', methods=['POST', 'OPTIONS'])
@optional_auth
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def radim_chat():
    """Hlavní WhatsApp-styl chat endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.json
        message = data.get('message', '')
        # Prefer JWT user_id, fallback to request body (v231: unique per-session)
        user_id = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
        mode = data.get('mode', 'senior')
        context = data.get('context', {})
        emotional_context = data.get('emotional_context', '')

        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400

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
            severity = 'critical' if any(w in message.lower() for w in ['155', '112', 'záchranka', 'sebevražd', 'sebevrazd', 'chci umřít', 'chci umrit']) else 'high'

            # v327 C1 FIX: Actually notify caregivers on crisis
            _safety_notify_caregivers(user_id, message, severity)

            # v327 H6 FIX: Log crisis event to audit trail
            _safety_log_crisis_event(user_id, message, severity)

            return jsonify({
                'success': True,
                'response': '🚨 Zůstaňte v klidu! Volám pomoc a informuji rodinu.',
                'radim_action': {
                    'type': 'safety_alert',
                    'payload': {'user_id': user_id, 'severity': severity, 'message': message},
                    'ui': {'suggested_buttons': ['Zavolat 155', 'Kontaktovat rodinu', 'Jsem v pořádku']}
                },
                'intent': 'safety',
                'mode': mode
            })

        # 🧠 Load personalization and history from memory
        personalized = ''
        history = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                personalized = _orch_build_prompt(user_id)
                history = _orch_get_history(user_id, limit=6)
            except Exception as mem_err:
                logger.warning(f"Memory load warning: {mem_err}")

        # 📋 Load pending tasks context for AI awareness
        if _ORCH_TASK_SERVICE:
            try:
                tasks_ctx = _ts_context(user_id)
                if tasks_ctx:
                    personalized += tasks_ctx
            except Exception as tc_err:
                logger.warning(f"Tasks context warning: {tc_err}")

        # 🎵 Text Rhythm: matematika → styl textu
        anticipation_prompt = ''
        anticipation_meta = None
        gen_config = None
        C = 5.0      # default: klidný stav
        alpha = 0.0   # default: bez aktivace
        mood = "neutral"
        if _ORCH_TEXT_RHYTHM:
            try:
                C_val = data.get('C')
                alpha_val = data.get('alpha')

                if C_val is not None and alpha_val is not None:
                    C = float(C_val)
                    alpha = float(alpha_val)
                else:
                    # Derive from message text + mood + personalized baseline
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

        # 🧠 Brain Engine: Ψ(t) = (C, E, R, S) — stavový vektor vědomí
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
                # v282: Include rhythm return data if available
                if psi_state.get("rhythm_return"):
                    brain_meta["rhythm_return"] = psi_state["rhythm_return"]
                personalized += f"\n\n[RADIM Brain: mode={psi_state['mode']}, coherence={psi_state['coherence']:.2f}]\n{decision['instructions']}"
            except Exception as brain_err:
                logger.warning(f"Brain warning (non-fatal): {brain_err}")

        # 🎯 Intent Resolver: short-circuit simple queries locally (v272)
        action_json = None
        text_response = None
        _resolved_intent = intent  # from detect_intent() above
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

        if text_response is None:
            text_response, action_json = call_gemini_whatsapp(
                message, context, mode, personalized, history,
                anticipation_prompt, gen_config
            )

        if not text_response:
            text_response = "Promiňte, zkuste to za chvíli. 🙏"

        # ✂️ Crisis enforcement: hard limit na počet vět (ALERT/CRISIS)
        if _ORCH_TEXT_RHYTHM and anticipation_meta and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                text_response = _tr_enforce(text_response, {
                    'state': anticipation_meta.get('state', 'HARMONY'),
                    'params': anticipation_meta.get('text_params', {})
                })
            except Exception:
                pass  # Non-fatal — AI instrukce stačí jako fallback

        # 📋 Process AI actions (create_task, log_health from ---RADIM_ACTION---)
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

        # 🧠 Record interaction to memory (v283: + brain state for baseline_C learning)
        if _ORCH_MEMORY_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                _brain_C_val = brain_meta["psi"]["C"] if brain_meta else None
                _brain_mode_val = brain_meta["mode"] if brain_meta else None
                _orch_record(user_id, message, text_response, brain_C=_brain_C_val, brain_mode=_brain_mode_val)
            except Exception as rec_err:
                logger.warning(f"Memory record warning: {rec_err}")

        # 🧠 Brain reinforcement: adapt per-user after response (v282: richer signal)
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
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        if anticipation_meta:
            result['anticipation'] = anticipation_meta
        if brain_meta:
            result['brain'] = brain_meta
        return jsonify(result)

    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@radim_bp.route('/api/radim/tasks', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def radim_tasks():
    """📋 Task management endpoint — reálná persistentní implementace"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _ORCH_TASK_SERVICE:
        return jsonify({'success': False, 'error': 'Task service unavailable'}), 503

    if request.method == 'GET':
        status = request.args.get('status')
        task_type = request.args.get('type')
        date_filter = request.args.get('date')
        tasks = _ts_get(user_id, status=status, task_type=task_type, date_filter=date_filter)
        return jsonify({'success': True, 'tasks': tasks, 'count': len(tasks), 'user_id': user_id})

    elif request.method == 'POST':
        data = request.json or {}
        task = _ts_create(
            user_id=user_id,
            title=data.get('title', 'Nový úkol'),
            task_type=data.get('type', 'reminder'),
            scheduled_time=data.get('time'),
            scheduled_date=data.get('date'),
            recurrence=data.get('recurrence', 'once'),
            priority=data.get('priority', 'normal'),
            description=data.get('description'),
            metadata=data.get('metadata')
        )
        if task:
            return jsonify({'success': True, 'task': task, 'message': 'Úkol vytvořen ✅'})
        return jsonify({'success': False, 'error': 'Nepodařilo se vytvořit úkol'}), 500

    elif request.method == 'PUT':
        data = request.json or {}
        task_id = data.get('task_id') or data.get('id')
        if not task_id:
            return jsonify({'success': False, 'error': 'task_id je povinné'}), 400
        ok = _ts_complete(task_id, user_id)
        return jsonify({'success': ok, 'message': 'Úkol splněn ✅' if ok else 'Chyba při splnění'})

    elif request.method == 'DELETE':
        data = request.json or {}
        task_id = data.get('task_id') or data.get('id')
        if not task_id:
            return jsonify({'success': False, 'error': 'task_id je povinné'}), 400
        from task_service import delete_task as _ts_delete
        ok = _ts_delete(task_id, user_id)
        return jsonify({'success': ok, 'message': 'Úkol smazán' if ok else 'Chyba'})


@radim_bp.route('/api/radim/medications', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def radim_medications():
    """💊 Medication tracking endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _ORCH_TASK_SERVICE:
        return jsonify({'success': False, 'error': 'Task service unavailable'}), 503

    if request.method == 'GET':
        days = request.args.get('days', 7, type=int)
        history = _ts_med_history(user_id, days=days)
        med_tasks = _ts_get(user_id, task_type='medication')
        return jsonify({
            'success': True,
            'medications': med_tasks,
            'history': history,
            'count': len(med_tasks),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    elif request.method == 'POST':
        data = request.json or {}
        name = data.get('name', data.get('medication_name', ''))
        if not name:
            return jsonify({'success': False, 'error': 'Název léku je povinný'}), 400
        ok = _ts_log_med(
            user_id=user_id,
            medication_name=name,
            task_id=data.get('task_id'),
            dosage=data.get('dosage'),
            notes=data.get('notes')
        )
        return jsonify({
            'success': ok,
            'message': f'Lék {name} zaznamenán ✅' if ok else 'Chyba při záznamu'
        })

@radim_bp.route('/api/radim/stories/templates', methods=['GET', 'OPTIONS'])
def radim_story_templates():
    """Story templates endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    platform = request.args.get('platform')
    templates = STORY_TEMPLATES

    if platform:
        templates = [t for t in templates if platform in t['platform']]

    return jsonify({
        'success': True,
        'templates': templates,
        'count': len(templates)
    })

@radim_bp.route('/api/radim/stories/generate', methods=['POST', 'OPTIONS'])
@require_auth
def radim_story_generate():
    """Generování story obsahu"""
    if request.method == 'OPTIONS':
        return '', 204

    try:
        data = request.json
        template_id = data.get('template_id')
        fields = data.get('fields', {})
        platform = data.get('platform', 'instagram')

        prompt = f"""Vytvoř krátký příspěvek pro {platform}.
Šablona: {template_id}
Pole: {json.dumps(fields, ensure_ascii=False)}

Pravidla: Max 3 věty, senior-friendly, Kolibri tón.
Odpověz POUZE textem příspěvku:"""

        if GEMINI_API_KEY:
            import requests as _req
            response = _req.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.8, "maxOutputTokens": 200}
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result:
                    story_text = result['candidates'][0]['content']['parts'][0]['text'].strip()
                    return jsonify({
                        'success': True,
                        'story': {
                            'text': story_text,
                            'platform': platform,
                            'template_id': template_id,
                            'hashtags': ['#KavárnaKolibri', '#Senioři', '#PlusOne']
                        }
                    })

        return jsonify({'success': False, 'error': 'AI nedostupné'}), 503

    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@radim_bp.route('/api/radim/voice/speak', methods=['POST', 'OPTIONS'])
@optional_auth
def radim_voice_speak():
    """Azure TTS endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    AZURE_KEY = os.environ.get('AZURE_SPEECH_KEY')
    AZURE_REGION = os.environ.get('AZURE_SPEECH_REGION', 'westeurope')

    if not AZURE_KEY:
        return jsonify({'success': False, 'error': 'Azure Speech není nakonfigurován'}), 503

    try:
        data = request.json
        text = data.get('text', '')
        voice = data.get('voice', 'cs-CZ-AntoninNeural')
        emotion = data.get('emotion', 'friendly')

        if not text:
            return jsonify({'success': False, 'error': 'Text je povinný'}), 400

        # Sanitize inputs to prevent SSML injection
        safe_text = xml_escape(text)
        if not re.match(r'^[a-zA-Z]{2}-[A-Z]{2}-[a-zA-Z]+Neural$', voice):
            voice = 'cs-CZ-AntoninNeural'

        emotion_settings = {
            'friendly': {'pitch': '-5%', 'rate': '0.85'},
            'calm': {'pitch': '-8%', 'rate': '0.8'},
            'warm': {'pitch': '-3%', 'rate': '0.9'}
        }
        settings = emotion_settings.get(emotion, emotion_settings['friendly'])

        # Anticipation Engine: adaptive params from C/α
        ant_state = None
        C_val = data.get('C')
        alpha_val = data.get('alpha')
        if C_val is not None and alpha_val is not None and _ORCH_ANT_AVAILABLE:
            try:
                C_pred = _orch_predict_C(float(C_val), 0, float(alpha_val))
                emo = _orch_emotions(C_pred, float(alpha_val))
                ant_params = _orch_speech_params(C_pred, float(alpha_val), emo)
                ant_state = _orch_classify(C_pred)
                settings = {
                    'rate': str(ant_params['rate']),
                    'pitch': f"{ant_params['pitch']:+.0f}%"
                }
            except Exception:
                pass  # Fall back to emotion_settings

        # 🧠 Brain Engine: override with per-user Ψ(t) speech adaptation
        brain_speech = None
        if _ORCH_BRAIN_AVAILABLE:
            try:
                uid = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
                brain_speech = _brain_speech_for_user(uid)
                if brain_speech:
                    settings = {
                        'rate': str(brain_speech['rate']),
                        'pitch': f"{brain_speech['pitch_pct']:+d}%"
                    }
                    ant_state = brain_speech['mode']
            except Exception:
                pass  # Fall back to previous settings

        # v2.1: express-as for emotional style (style/styledegree from Brain Engine)
        # v330: Sanitize to prevent SSML injection
        _style = brain_speech.get('style', 'friendly') if brain_speech else 'friendly'
        _styledegree = brain_speech.get('styledegree', '1.2') if brain_speech else '1.2'
        _VALID_STYLES = {'friendly', 'cheerful', 'sad', 'angry', 'excited', 'gentle', 'serious',
                         'empathetic', 'calm', 'chat', 'assistant', 'customerservice', 'newscast'}
        if _style not in _VALID_STYLES:
            _style = 'friendly'
        if not re.match(r'^[0-9.]+$', str(_styledegree)):
            _styledegree = '1.2'

        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
               xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="cs-CZ">
            <voice name="{voice}">
                <mstts:express-as style="{_style}" styledegree="{_styledegree}">
                    <prosody rate="{settings['rate']}" pitch="{settings['pitch']}" volume="loud">{safe_text}</prosody>
                </mstts:express-as>
            </voice>
        </speak>'''

        response = requests.post(
            f"https://{AZURE_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                'Ocp-Apim-Subscription-Key': AZURE_KEY,
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3'
            },
            data=ssml.encode('utf-8'),
            timeout=15
        )

        if response.status_code == 200:
            audio_base64 = base64.b64encode(response.content).decode('utf-8')
            resp_data = {
                'success': True,
                'audio': audio_base64,
                'format': 'mp3',
                'voice': voice,
                'emotion': emotion
            }
            if ant_state:
                resp_data['anticipation_state'] = ant_state
            if brain_speech:
                resp_data['brain_speech'] = brain_speech
            return jsonify(resp_data)

        return jsonify({'success': False, 'error': f'Azure TTS error: {response.status_code}'}), 500

    except Exception as e:
        logger.error(f"⚠️ radim_orchestrator.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

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
        'version': '2.0.0',
        'features': {
            'whatsapp_chat': True,
            'task_management': True,
            'story_templates': True,
            'voice_synthesis': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'anticipation_engine': _ORCH_ANT_AVAILABLE,
            'ai_provider': 'gemini' if GEMINI_API_KEY else 'none'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })
