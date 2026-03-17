# ============================================
# RADIM SERVICE ROUTES v1.0.0
# ============================================
# CRUD / service endpoints extracted from radim_orchestrator.py:
#   - Tasks management (GET/POST/PUT/DELETE /api/radim/tasks)
#   - Medication tracking (GET/POST /api/radim/medications)
#   - Story templates + generation (/api/radim/stories/*)
#   - Voice speak / Azure TTS (/api/radim/voice/speak)
# ============================================

from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth
import requests
import json
import re
import os
import base64
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
import logging

from radim_helpers import (
    GEMINI_API_KEY, _extract_user_id
)
from radim_ai_engine import STORY_TEMPLATES

logger = logging.getLogger(__name__)

radim_service_bp = Blueprint('radim_service', __name__)

# ============================================
# OPTIONAL IMPORTS
# ============================================

# Anticipation Engine
try:
    from anticipation_routes import (
        predict_C as _svc_predict_C, calculate_emotions as _svc_emotions,
        calculate_speech_params as _svc_speech_params, classify_state as _svc_classify
    )
    _SVC_ANT_AVAILABLE = True
except ImportError:
    _SVC_ANT_AVAILABLE = False

# Brain Engine
try:
    from radim_brain_routes import (
        get_brain_speech_for_user as _svc_brain_speech_for_user
    )
    _SVC_BRAIN_AVAILABLE = True
except ImportError:
    _SVC_BRAIN_AVAILABLE = False

# Task Service
try:
    from task_service import (
        create_task as _ts_create,
        get_tasks as _ts_get,
        complete_task as _ts_complete,
        log_medication as _ts_log_med,
        get_medication_history as _ts_med_history,
    )
    _SVC_TASK_SERVICE = True
except ImportError:
    _SVC_TASK_SERVICE = False


# ============================================
# TASKS ENDPOINT
# ============================================

@radim_service_bp.route('/api/radim/tasks', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def radim_tasks():
    """Task management endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _SVC_TASK_SERVICE:
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


# ============================================
# MEDICATIONS ENDPOINT
# ============================================

@radim_service_bp.route('/api/radim/medications', methods=['GET', 'POST', 'OPTIONS'])
@require_auth
def radim_medications():
    """Medication tracking endpoint"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = _extract_user_id(getattr(g, 'auth_user', None), request.args.get('user_id'))

    if not _SVC_TASK_SERVICE:
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


# ============================================
# STORIES ENDPOINTS
# ============================================

@radim_service_bp.route('/api/radim/stories/templates', methods=['GET', 'OPTIONS'])
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


@radim_service_bp.route('/api/radim/stories/generate', methods=['POST', 'OPTIONS'])
@require_auth
def radim_story_generate():
    """Story content generation"""
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
        logger.error(f"Story generate error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


# ============================================
# VOICE / AZURE TTS ENDPOINT
# ============================================

@radim_service_bp.route('/api/radim/voice/speak', methods=['POST', 'OPTIONS'])
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
        if C_val is not None and alpha_val is not None and _SVC_ANT_AVAILABLE:
            try:
                C_pred = _svc_predict_C(float(C_val), 0, float(alpha_val))
                emo = _svc_emotions(C_pred, float(alpha_val))
                ant_params = _svc_speech_params(C_pred, float(alpha_val), emo)
                ant_state = _svc_classify(C_pred)
                settings = {
                    'rate': str(ant_params['rate']),
                    'pitch': f"{ant_params['pitch']:+.0f}%"
                }
            except Exception:
                pass  # Fall back to emotion_settings

        # Brain Engine: override with per-user Ψ(t) speech adaptation
        brain_speech = None
        if _SVC_BRAIN_AVAILABLE:
            try:
                uid = _extract_user_id(getattr(g, 'auth_user', None), data.get('user_id'))
                brain_speech = _svc_brain_speech_for_user(uid)
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
        logger.error(f"Voice speak error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500


logger.info("✅ Radim Service routes loaded — tasks, medications, stories, voice/speak")
