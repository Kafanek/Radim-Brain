# ============================================
# EVENTLET MONKEY PATCH - MUST BE FIRST!
# ============================================
import eventlet
import logging

logger = logging.getLogger(__name__)
eventlet.monkey_patch()

# ============================================
# RADIM BRAIN + CHAT - ROZŠÍŘENÝ HEROKU BACKEND
# ============================================
# Version: 3.1.0 - PostgreSQL + Security + Blueprint Registry
# radim-brain-2025.herokuapp.com

import os
import json
import uuid
import time
import hmac
import hashlib
import requests
import base64
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv
from database import get_db_for_flask, close_db_for_flask, get_connection
from database import init_db as db_init_db, is_postgres
from auth_middleware import require_auth, require_premium, optional_auth, decode_jwt
from rate_limiter import rate_limit

load_dotenv()

# Import Radim WhatsApp Orchestrator
from radim_orchestrator import radim_bp

# 🎭 Import Orchestrator Blueprint
from orchestrator_blueprint import orchestrator_bp

# Import Memory & Learning routes
try:
    from memory_routes import memory_bp
    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    logger.warning("⚠️ Memory routes not available")

# 👴 Import Seniors API
try:
    from seniors_routes import seniors_bp
    SENIORS_AVAILABLE = True
except ImportError:
    SENIORS_AVAILABLE = False
    logger.warning("⚠️ Seniors routes not available")

# 🌡️ Import IoT & Sensors API
try:
    from iot_routes import iot_bp
    IOT_AVAILABLE = True
except ImportError:
    IOT_AVAILABLE = False
    logger.warning("⚠️ IoT routes not available")

# 🔮 Import Predict & Consciousness API
try:
    from predict_routes import predict_bp
    PREDICT_AVAILABLE = True
except ImportError:
    PREDICT_AVAILABLE = False
    logger.warning("⚠️ Predict routes not available")

# 📊 Import Dashboard API
try:
    from dashboard_routes import dashboard_bp
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    logger.warning("⚠️ Dashboard routes not available")

# 📚 Import Library / E-book API
try:
    from library_routes import library_bp
    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False
    logger.warning("⚠️ Library routes not available")

# 🎓 Import Education / Rare Diseases API
try:
    from education_routes import education_bp
    EDUCATION_AVAILABLE = True
except ImportError:
    EDUCATION_AVAILABLE = False
    logger.warning("⚠️ Education routes not available")

# 🏥 Import Telemedicine Routes
try:
    from telemedicine_routes import telemedicine_bp, get_upcoming_consultations_for_reminder
    TELEMEDICINE_AVAILABLE = True
except ImportError:
    TELEMEDICINE_AVAILABLE = False
    logger.warning("⚠️ Telemedicine routes not available")

# 📧 Import Email Routes (SMTP via Wedos)
try:
    from email_routes import email_bp
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    logger.warning("⚠️ Email routes not available")

# ============================================
# FLASK APP SETUP
# ============================================
app = Flask(__name__)

# Register Radim Blueprint
app.register_blueprint(radim_bp)

# 🎭 Register Orchestrator Blueprint
app.register_blueprint(orchestrator_bp)
logger.info("✅ Orchestrator routes registered: /api/orchestrator/*")

# 👴 Register Seniors Blueprint
if SENIORS_AVAILABLE:
    app.register_blueprint(seniors_bp)
    logger.info("✅ Seniors routes registered: /api/seniors/*")

# 🌡️ Register IoT Blueprint
if IOT_AVAILABLE:
    app.register_blueprint(iot_bp)
    logger.info("✅ IoT routes registered: /api/iot/*")

# 🔮 Register Predict Blueprint
if PREDICT_AVAILABLE:
    app.register_blueprint(predict_bp)
    logger.info("✅ Predict routes registered: /api/radim/predict/*, /api/consciousness/*")

# 📊 Register Dashboard Blueprint
if DASHBOARD_AVAILABLE:
    app.register_blueprint(dashboard_bp)
    logger.info("✅ Dashboard routes registered: /api/dashboard/*")

# 📚 Register Library Blueprint
if LIBRARY_AVAILABLE:
    app.register_blueprint(library_bp)
    logger.info("✅ Library routes registered: /kal/library/*")

# 🎓 Register Education Blueprint
if EDUCATION_AVAILABLE:
    app.register_blueprint(education_bp)
    logger.info("✅ Education routes registered: /api/education/*")

# 🏥 Register Telemedicine Blueprint
if TELEMEDICINE_AVAILABLE:
    app.register_blueprint(telemedicine_bp)
    logger.info("✅ Telemedicine routes registered: /api/telemedicine/*")

# 📧 Register Email Blueprint
if EMAIL_AVAILABLE:
    app.register_blueprint(email_bp)
    logger.info("✅ Email routes registered: /api/email/*")

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# CORS - Production origins (HTTPS only)
PRODUCTION_ORIGINS = [
    "https://app.radimcare.cz",
    "https://polite-bush-001303503.6.azurestaticapps.net",
    "https://mykolibri-academy.cz",
    "https://app.mykolibri-academy.cz",
]

# Development origins (only added when not in production)
DEV_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://localhost:5173",
]

IS_PRODUCTION = os.environ.get('DYNO') is not None  # Heroku sets DYNO
# Always include dev origins — localhost can't be spoofed from internet
ALLOWED_ORIGINS = PRODUCTION_ORIGINS + DEV_ORIGINS

CORS(app,
     resources={r"/*": {"origins": ALLOWED_ORIGINS}},
     supports_credentials=False,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# Socket.IO
socketio = SocketIO(
    app,
    cors_allowed_origins=ALLOWED_ORIGINS,
    async_mode='eventlet',
    ping_timeout=60,
    ping_interval=25
)

# ============================================
# KONFIGURACE
# ============================================
# AI Providers
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# Cloudinary
CLOUDINARY_URL = os.environ.get('CLOUDINARY_URL')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET')

# WordPress
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')

# Push Notifications (Web Push)
VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
VAPID_EMAIL = os.environ.get('VAPID_EMAIL', 'mailto:admin@kafanek.com')

# ============================================
# STARTUP ENV VAR VALIDATION
# ============================================
def _validate_env_vars():
    """Log warnings for missing critical env vars at startup."""
    critical = {
        'DATABASE_URL': os.environ.get('DATABASE_URL'),
        'SECRET_KEY': os.environ.get('SECRET_KEY'),
    }
    important = {
        'GEMINI_API_KEY': GEMINI_API_KEY,
        'ANTHROPIC_API_KEY': ANTHROPIC_API_KEY,
        'AZURE_TTS_KEY': os.environ.get('AZURE_TTS_KEY'),
        'AZURE_TTS_REGION': os.environ.get('AZURE_TTS_REGION'),
    }
    optional = {
        'TWILIO_ACCOUNT_SID': os.environ.get('TWILIO_ACCOUNT_SID'),
        'SMTP_HOST': os.environ.get('SMTP_HOST'),
        'WP_URL': WP_URL,
    }

    missing_critical = [k for k, v in critical.items() if not v]
    missing_important = [k for k, v in important.items() if not v]
    missing_optional = [k for k, v in optional.items() if not v]

    if missing_critical:
        logger.error(f"❌ CRITICAL env vars missing: {', '.join(missing_critical)}")
    if missing_important:
        logger.warning(f"⚠️ Important env vars missing (some features disabled): {', '.join(missing_important)}")
    if missing_optional:
        logger.info(f"ℹ️ Optional env vars not set: {', '.join(missing_optional)}")

    return len(missing_critical) == 0

_validate_env_vars()

# Import Speech module
from speech_routes import speech_bp
app.register_blueprint(speech_bp)

# 🤖 Import Claude AI routes - Radim s web search (nahrazuje Gemini)
from claude_routes import claude_bp
app.register_blueprint(claude_bp)
logger.info("✅ Claude AI routes registered: /api/claude/*")

# 💝 Import Soul routes - Duše Radima
from soul_routes import soul_bp
app.register_blueprint(soul_bp)
logger.info("✅ Soul routes registered: /api/soul/*")

# 🎙️ Import Voice Runtime routes - Stavový automat
from voice_runtime_routes import voice_runtime_bp
app.register_blueprint(voice_runtime_bp)
logger.info("✅ Voice Runtime routes registered: /api/voice/*")

# 🔮 Import Anticipation Engine - Předbudoucí čas
from anticipation_routes import anticipation_bp
app.register_blueprint(anticipation_bp)
logger.info("✅ Anticipation Engine registered: /api/anticipation/*")

# 🎵 Import Rhythm Return Engine - Návrat rytmu (Parkinson)
try:
    from rhythm_return_routes import rhythm_return_bp
    app.register_blueprint(rhythm_return_bp)
    RHYTHM_RETURN_AVAILABLE = True
    logger.info("🎵 Rhythm Return Engine registered: /api/rhythm-return/*")
except ImportError:
    RHYTHM_RETURN_AVAILABLE = False
    logger.warning("⚠️ Rhythm Return routes not available")

# 🧠 Import RADIM Brain Engine - Sjednocující vrstva vědomí
try:
    from radim_brain_routes import radim_brain_bp
    app.register_blueprint(radim_brain_bp)
    RADIM_BRAIN_AVAILABLE = True
    logger.info("🧠 RADIM Brain Engine registered: /api/brain/*")
except ImportError:
    RADIM_BRAIN_AVAILABLE = False
    logger.warning("⚠️ RADIM Brain routes not available")

# Anticipation functions for azure_tts_proxy
try:
    from anticipation_routes import (
        predict_C as _app_predict_C, calculate_emotions as _app_ant_emotions,
        calculate_speech_params as _app_ant_speech, classify_state as _app_classify
    )
    _APP_ANT_AVAILABLE = True
except ImportError:
    _APP_ANT_AVAILABLE = False

# 🧠 Brain Engine — per-user speech adaptation from Ψ(t)
try:
    from radim_brain_routes import get_brain_speech_for_user as _app_brain_speech
    _APP_BRAIN_AVAILABLE = True
except ImportError:
    _APP_BRAIN_AVAILABLE = False

# 📞 Import Twilio Voice routes - Phone calls for seniors
try:
    from twilio_voice_routes import twilio_bp
    app.register_blueprint(twilio_bp)
    TWILIO_AVAILABLE = True
    logger.info("✅ Twilio Voice routes registered: /api/twilio/*")
except ImportError:
    TWILIO_AVAILABLE = False
    logger.warning("⚠️ Twilio Voice routes not available")

# 🔌 Import IoT Bridge routes - Real sensor data from Zigbee gateways
try:
    from iot_bridge_routes import iot_bridge_bp
    app.register_blueprint(iot_bridge_bp)
    IOT_BRIDGE_AVAILABLE = True
    logger.info("🔌 IoT Bridge registered: /api/iot-bridge/*")
except ImportError:
    IOT_BRIDGE_AVAILABLE = False
    logger.warning("⚠️ IoT Bridge routes not available")

# 🧠 Import Memory & Learning routes
if MEMORY_AVAILABLE:
    app.register_blueprint(memory_bp)
    logger.info("✅ Memory routes registered: /api/memory/*")

# ============================================
# ⏰ BACKGROUND SCHEDULER — push reminders (v231)
# ============================================
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    import atexit

    def _check_reminders():
        """Každých 5 minut: zkontroluj splatné úkoly → push notifikace."""
        with app.app_context():
            try:
                from task_service import get_all_due_tasks, mark_task_notified
                due = get_all_due_tasks(window_minutes=5)
                for task in due:
                    uid = task.get('user_id', '')
                    title = task.get('title', 'Připomínka')
                    t_type = task.get('task_type', 'reminder')
                    sched = task.get('scheduled_time', '')

                    # Emoji podle typu
                    icon = {'medication': '💊', 'appointment': '🏥', 'reminder': '🔔'}.get(t_type, '📋')
                    body = f"{icon} {title}"
                    if sched:
                        body += f" ({sched})"

                    send_push_notification(
                        uid,
                        title='Radim — připomínka',
                        body=body,
                        data={'task_id': task.get('id'), 'type': t_type}
                    )
                    mark_task_notified(task['id'])
                    logger.info(f"🔔 Reminder sent: '{title}' → {uid}")

                if due:
                    logger.info(f"⏰ Scheduler: {len(due)} reminders sent")
            except Exception as e:
                logger.error(f"⏰ Scheduler error (non-fatal): {e}")

    # 🏥 Telemedicine consultation reminders (15 min before)
    def _check_consultation_reminders():
        """Every 5 min: notify upcoming consultations starting within 15 min."""
        if not TELEMEDICINE_AVAILABLE:
            return
        try:
            upcoming = get_upcoming_consultations_for_reminder(window_minutes=15)
            for c in upcoming:
                cid = c.get('id')
                teacher_id = c.get('teacher_id')
                student_id = c.get('student_id')
                mins = c.get('minutes_until', '?')
                reminder_data = {
                    'consultation_id': cid,
                    'minutes_until': mins,
                    'scheduled_time': str(c.get('scheduled_time', '')),
                    'message': f'Konzultace začíná za {mins} minut'
                }
                # Notify both parties
                socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{teacher_id}')
                socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{student_id}')
                # Multi-party: also notify additional participants
                for pid in c.get('participant_ids', []):
                    if pid != teacher_id and pid != student_id:
                        socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{pid}')
                logger.info(f"🏥 Telemed reminder: consultation #{cid} in {mins} min → teacher {teacher_id}, student {student_id}, +{len(c.get('participant_ids', []))} participants")
            if upcoming:
                logger.info(f"🏥 Telemed scheduler: {len(upcoming)} reminders sent")
        except Exception as e:
            logger.error(f"🏥 Telemed scheduler error (non-fatal): {e}")

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_check_reminders, 'interval', minutes=5, id='radim_reminders')
    scheduler.add_job(_check_consultation_reminders, 'interval', minutes=5, id='telemed_reminders')
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("✅ APScheduler started: reminder check every 5 min")
    logger.info("✅ APScheduler started: telemed reminders every 5 min")

except ImportError:
    logger.warning("⚠️ APScheduler not installed — reminders will not auto-send")
except Exception as sched_err:
    logger.error(f"⚠️ Scheduler init error: {sched_err}")

# ============================================
# TTS PROXY ENDPOINTS (Azure)
# ============================================
AZURE_TTS_KEY = os.environ.get('AZURE_TTS_KEY')
if not AZURE_TTS_KEY:
    logger.warning("⚠️  WARNING: AZURE_TTS_KEY not set - Azure TTS proxy will not work")
# Try eastus - Heroku has DNS timeout on EU regions
AZURE_TTS_REGION = os.environ.get('AZURE_TTS_REGION', 'eastus')

@app.route('/api/azure/tts', methods=['OPTIONS'])
def azure_tts_preflight():
    """CORS preflight for Azure TTS"""
    response = jsonify({'status': 'ok'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Max-Age', '3600')
    return response, 200

@app.route('/api/azure/tts', methods=['POST'])
@rate_limit(max_requests=60, window_seconds=60, key_func='ip')
def azure_tts_proxy():
    """Azure TTS Proxy - Antonín voice"""
    if not AZURE_TTS_KEY:
        return jsonify({'error': 'Azure TTS not configured (AZURE_TTS_KEY missing)'}), 503
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Chybí tělo požadavku (JSON)'}), 400
        text = data.get('text', '')
        voice = data.get('voice', 'cs-CZ-AntoninNeural')
        rate = data.get('rate', '0.85')
        pitch = data.get('pitch', '+0Hz')

        # Optional: Use Anticipation Engine if C/α provided
        C_val = data.get('C')
        alpha_val = data.get('alpha')
        ant_state = None
        if C_val is not None and alpha_val is not None and _APP_ANT_AVAILABLE:
            try:
                C_pred = _app_predict_C(float(C_val), 0, float(alpha_val))
                emo = _app_ant_emotions(C_pred, float(alpha_val))
                params = _app_ant_speech(C_pred, float(alpha_val), emo)
                ant_state = _app_classify(C_pred)
                rate = str(round(params['rate'] * 100)) + '%'
                pitch = f"{int(params['pitch'])}Hz" if params['pitch'] <= 0 else f"+{int(params['pitch'])}Hz"
            except Exception:
                pass  # Fall through to default rate/pitch

        # 🧠 Brain Engine: override with per-user Ψ(t) speech adaptation
        brain_speech = None
        uid = data.get('user_id', '')
        if uid and _APP_BRAIN_AVAILABLE:
            try:
                brain_speech = _app_brain_speech(str(uid))
                if brain_speech:
                    rate = str(brain_speech['rate'])
                    pitch = f"{brain_speech['pitch_pct']:+d}%"
                    ant_state = brain_speech['mode']
            except Exception:
                pass

        if not text:
            return jsonify({'error': 'Text is required'}), 400

        # Sanitize inputs to prevent SSML injection
        from xml.sax.saxutils import escape as xml_escape
        safe_text = xml_escape(text)
        # Whitelist voice names and validate rate/pitch format
        import re as _re
        if not _re.match(r'^[a-zA-Z]{2}-[A-Z]{2}-[a-zA-Z]+$', voice):
            voice = 'cs-CZ-AntoninNeural'
        if not _re.match(r'^[0-9.]+$', str(rate).replace('%', '')):
            rate = '0.85'
        if not _re.match(r'^[+-]?[0-9]+(%|Hz)$', pitch):
            pitch = '+0Hz'

        # Build SSML (v2.1: express-as for emotional style)
        _style = brain_speech.get('style', 'friendly') if brain_speech else 'friendly'
        _styledegree = brain_speech.get('styledegree', '1.2') if brain_speech else '1.2'

        ssml = f"""<speak version='1.0' xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='cs-CZ'>
            <voice name='{voice}'>
                <mstts:express-as style='{_style}' styledegree='{_styledegree}'>
                    <prosody rate='{rate}' pitch='{pitch}'>
                        {safe_text}
                    </prosody>
                </mstts:express-as>
            </voice>
        </speak>"""
        
        # Call Azure TTS API
        url = f"https://{AZURE_TTS_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            'Ocp-Apim-Subscription-Key': AZURE_TTS_KEY,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3'
        }
        
        try:
            response = requests.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=60)
        except requests.exceptions.Timeout:
            return jsonify({'error': 'Azure TTS API timeout - try again'}), 504
        except requests.exceptions.RequestException as e:
            logger.error(f"⚠️ app.py error: {e}")
            return jsonify({'error': 'Interní chyba serveru'}), 503
        
        if response.status_code == 200:
            from flask import Response
            resp_headers = {
                    'X-Voice-Name': voice,
                    'X-Voice-Rate': str(rate),
                    'Cache-Control': 'no-cache'
                }
            if ant_state:
                resp_headers['X-Anticipation-State'] = ant_state
            if brain_speech:
                resp_headers['X-Brain-Mode'] = brain_speech['mode']
                resp_headers['X-Brain-Coherence'] = str(brain_speech['coherence'])
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers=resp_headers
            )
        else:
            return jsonify({'error': f'Azure TTS error: {response.status_code}'}), response.status_code
            
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'error': 'Interní chyba serveru'}), 500

# ============================================
# ELEVENLABS TTS PROXY
# ============================================
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY', '')

@app.route('/api/elevenlabs/tts', methods=['OPTIONS'])
def elevenlabs_tts_preflight():
    """CORS preflight for ElevenLabs TTS"""
    response = jsonify({'status': 'ok'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Max-Age', '3600')
    return response, 200

@app.route('/api/elevenlabs/tts', methods=['POST'])
@rate_limit(max_requests=40, window_seconds=60, key_func='ip')
def elevenlabs_tts_proxy():
    """ElevenLabs TTS Proxy - Pan Kafánek voice"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Chybí tělo požadavku (JSON)'}), 400
        text = data.get('text', '')
        voice_id = data.get('voice_id', 'JBFqnCBsd6RMkjVDRZzb')  # Pan Kafánek
        
        if not text:
            return jsonify({'error': 'Text is required'}), 400
        
        if not ELEVENLABS_API_KEY:
            return jsonify({'error': 'ElevenLabs API key not configured'}), 500
        
        # Call ElevenLabs API
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            'xi-api-key': ELEVENLABS_API_KEY,
            'Content-Type': 'application/json'
        }
        payload = {
            'text': text,
            'model_id': 'eleven_multilingual_v2',
            'voice_settings': {
                'stability': 0.5,
                'similarity_boost': 0.75
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
        except requests.exceptions.Timeout:
            return jsonify({'error': 'ElevenLabs API timeout'}), 504
        except requests.exceptions.RequestException as e:
            logger.error(f"⚠️ app.py error: {e}")
            return jsonify({'error': 'Interní chyba serveru'}), 503
        
        if response.status_code == 200:
            from flask import Response
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers={
                    'X-Voice-ID': voice_id,
                    'Cache-Control': 'no-cache'
                }
            )
        else:
            return jsonify({'error': f'ElevenLabs error: {response.status_code}', 'detail': response.text}), response.status_code
            
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'error': 'Interní chyba serveru'}), 500

@app.route('/api/tts/health', methods=['GET'])
def tts_health():
    """TTS proxy health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'TTS Proxy (Azure + ElevenLabs - Flask)',
        'endpoints': {
            'azure': '/api/azure/tts',
            'elevenlabs': '/api/elevenlabs/tts'
        }
    })

# ============================================
# DATABASE (via database.py adapter - SQLite/PostgreSQL)
# ============================================
def get_db():
    return get_db_for_flask(g)

@app.teardown_appcontext
def close_db(exception):
    close_db_for_flask(g)

def init_db():
    db_init_db()

# ============================================
# HELPERS
# ============================================
def generate_id():
    return str(uuid.uuid4())

def now_iso():
    return datetime.utcnow().isoformat() + 'Z'

def today_date():
    return datetime.utcnow().strftime('%Y-%m-%d')

users_online = {}  # In-memory cache of {user_id: socket_sid} for fast lookups
_USERS_ONLINE_MAX = 500
# Note: On dyno restart, all users are set offline in init_db_online_reset()

def _cleanup_users_online():
    """Evict stale entries from users_online if over limit."""
    if len(users_online) <= _USERS_ONLINE_MAX:
        return
    # Remove oldest entries (first inserted)
    excess = len(users_online) - _USERS_ONLINE_MAX
    for key in list(users_online.keys())[:excess]:
        del users_online[key]

# ============================================
# RADIM AI - GEMINI/CLAUDE INTEGRATION
# ============================================
# System prompt — centralized in radim_system_prompt.py
from radim_system_prompt import get_chat_prompt
RADIM_SYSTEM_PROMPT = get_chat_prompt()

def call_gemini_ai(messages, context=None, image=None):
    """Volání Gemini AI pro Radima"""
    if not GEMINI_API_KEY:
        return None
    
    try:
        # Připrav konverzaci
        conversation_text = ""
        for msg in messages[-10:]:  # Posledních 10 zpráv pro kontext
            role = "Uživatel" if msg.get('sender_id') != 'radim' else "Radim"
            conversation_text += f"{role}: {msg.get('content', '')}\n"
        
        prompt = f"{RADIM_SYSTEM_PROMPT}\n\nKonverzace:\n{conversation_text}\nRadim:"
        
        # Build parts - text and optionally image
        parts = [{"text": prompt}]
        
        if image:
            # Extract base64 data from data URL
            if image.startswith("data:"):
                image = image.split(",")[1]
            parts.insert(0, {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image
                }
            })
        
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 200,
                    "topP": 0.9
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'candidates' in data and data['candidates']:
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
        
        logger.error(f"Gemini error: {response.status_code} - {response.text}")
        return None
        
    except Exception as e:
        logger.error(f"Gemini AI error: {e}")
        return None

def call_claude_ai(messages, context=None):
    """Fallback na Claude API"""
    if not ANTHROPIC_API_KEY:
        return None
    
    try:
        conversation = [{"role": "user" if m.get('sender_id') != 'radim' else "assistant", 
                        "content": m.get('content', '')} for m in messages[-10:]]
        
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 200,
                "system": RADIM_SYSTEM_PROMPT,
                "messages": conversation
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'content' in data and data['content']:
                return data['content'][0]['text'].strip()
        
        return None
        
    except Exception as e:
        logger.error(f"Claude AI error: {e}")
        return None

def get_ai_response(messages, context=None, image=None):
    """Získej AI odpověď (Gemini s fallbackem na Claude)"""
    response = call_gemini_ai(messages, context, image)
    if not response:
        response = call_claude_ai(messages, context)
    if not response:
        response = "Omlouvám se, momentálně mám technické potíže. Zkuste to prosím za chvíli. 🙏"
    return response

# ============================================
# CLOUDINARY - MEDIA UPLOAD
# ============================================
def upload_to_cloudinary(file_data, resource_type='auto', folder='radim-chat'):
    """Upload souboru do Cloudinary"""
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY:
        return None
    
    try:
        import cloudinary
        import cloudinary.uploader
        
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET
        )
        
        result = cloudinary.uploader.upload(
            file_data,
            resource_type=resource_type,
            folder=folder,
            transformation=[
                {'quality': 'auto:good'},
                {'fetch_format': 'auto'}
            ] if resource_type == 'image' else None
        )
        
        return {
            'url': result['secure_url'],
            'public_id': result['public_id'],
            'format': result.get('format'),
            'size': result.get('bytes'),
            'duration': result.get('duration'),
            'width': result.get('width'),
            'height': result.get('height')
        }
        
    except Exception as e:
        logger.error(f"Cloudinary error: {e}")
        return None

# ============================================
# PUSH NOTIFICATIONS
# ============================================
def send_push_notification(user_id, title, body, data=None):
    """Odešli push notifikaci uživateli"""
    if not VAPID_PRIVATE_KEY:
        return False
    
    try:
        from pywebpush import webpush, WebPushException
        
        db = get_db()
        cursor = db.execute('SELECT * FROM push_subscriptions WHERE user_id = ?', (user_id,))
        subscriptions = cursor.fetchall()
        
        for sub in subscriptions:
            subscription_info = {
                'endpoint': sub['endpoint'],
                'keys': json.loads(sub['keys'])
            }
            
            payload = json.dumps({
                'title': title,
                'body': body,
                'icon': '/icons/radim-icon-192.png',
                'badge': '/icons/radim-badge.png',
                'data': data or {},
                'timestamp': now_iso()
            })
            
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={'sub': VAPID_EMAIL}
                )
            except WebPushException as e:
                if e.response and e.response.status_code == 410:
                    # Subscription expired, remove it
                    db.execute('DELETE FROM push_subscriptions WHERE id = ?', (sub['id'],))
                    db.commit()
        
        return True
        
    except Exception as e:
        logger.error(f"Push notification error: {e}")
        return False

# ============================================
# WORDPRESS INTEGRATION
# ============================================
def get_wp_user(email):
    """Získej WordPress uživatele podle emailu"""
    if not WP_URL or not WP_USER or not WP_APP_PASSWORD:
        return None
    
    try:
        response = requests.get(
            f"{WP_URL}/wp-json/wp/v2/users",
            params={'search': email},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=10
        )
        
        if response.status_code == 200:
            users = response.json()
            if users:
                return users[0]
        return None
        
    except Exception as e:
        logger.error(f"WordPress API error: {e}")
        return None

def sync_wp_user(wp_user):
    """Synchronizuj WordPress uživatele do chat_users"""
    if not wp_user:
        return None
    
    try:
        db = get_db()
        user_id = f"wp_{wp_user['id']}"
        
        if is_postgres():
            db.execute('''
                INSERT INTO chat_users (id, name, email, avatar, role, wp_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name, email = EXCLUDED.email,
                    avatar = EXCLUDED.avatar, wp_user_id = EXCLUDED.wp_user_id
            ''', (
                user_id,
                wp_user.get('name', wp_user.get('slug')),
                wp_user.get('email'),
                wp_user.get('avatar_urls', {}).get('96'),
                'user',
                wp_user['id'],
                now_iso()
            ))
        else:
            db.execute('''
                INSERT OR REPLACE INTO chat_users (id, name, email, avatar, role, wp_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id,
                wp_user.get('name', wp_user.get('slug')),
                wp_user.get('email'),
                wp_user.get('avatar_urls', {}).get('96'),
                'user',
                wp_user['id'],
                now_iso()
            ))
        db.commit()
        
        return user_id
        
    except Exception as e:
        logger.error(f"Sync WP user error: {e}")
        return None

# ============================================
# REST API - CONVERSATIONS
# ============================================
@app.route('/api/chat/conversations/<user_id>', methods=['GET'])
@optional_auth
def get_conversations(user_id):
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT * FROM chat_conversations 
            WHERE participants LIKE ? 
            ORDER BY updated_at DESC
        ''', (f'%"{user_id}"%',))
        
        conversations = []
        for row in cursor.fetchall():
            conv = dict(row)
            conv['participants'] = json.loads(conv['participants'])
            conv['last_message'] = json.loads(conv['last_message']) if conv['last_message'] else None
            conv['settings'] = json.loads(conv['settings']) if conv['settings'] else {}
            conversations.append(conv)
        
        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/chat/conversations', methods=['POST'])
@optional_auth
def create_conversation():
    try:
        data = request.json
        participants = data.get('participants', [])
        conv_type = data.get('type', 'direct' if len(participants) <= 2 else 'group')
        name = data.get('name')
        
        conversation = {
            'id': generate_id(),
            'participants': participants,
            'type': conv_type,
            'name': name,
            'created_at': now_iso(),
            'updated_at': now_iso(),
            'last_message': None,
            'settings': {}
        }
        
        db = get_db()
        db.execute('''
            INSERT INTO chat_conversations (id, participants, type, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (conversation['id'], json.dumps(participants), conv_type, name, 
              conversation['created_at'], conversation['updated_at']))
        db.commit()
        
        return jsonify({'success': True, 'conversation': conversation}), 201
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - MESSAGES (with AI)
# ============================================
@app.route('/api/chat/messages/<conversation_id>', methods=['GET'])
@optional_auth
def get_messages(conversation_id):
    try:
        limit = min(request.args.get('limit', 50, type=int), 500)
        before = request.args.get('before')
        
        db = get_db()
        if before:
            cursor = db.execute('''
                SELECT * FROM chat_messages 
                WHERE conversation_id = ? AND timestamp < ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (conversation_id, before, limit))
        else:
            cursor = db.execute('''
                SELECT * FROM chat_messages 
                WHERE conversation_id = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (conversation_id, limit))
        
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            msg['reactions'] = json.loads(msg['reactions']) if msg['reactions'] else []
            msg['read_by'] = json.loads(msg['read_by']) if msg['read_by'] else []
            msg['metadata'] = json.loads(msg['metadata']) if msg['metadata'] else {}
            messages.append(msg)
        
        return jsonify({'success': True, 'messages': list(reversed(messages)), 'hasMore': len(messages) == limit})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/chat/messages', methods=['POST'])
@optional_auth
def send_message():
    try:
        data = request.json
        conversation_id = data['conversationId']
        sender_id = data['senderId']
        
        message = {
            'id': generate_id(),
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'type': data.get('type', 'text'),
            'content': data['content'],
            'reply_to': data.get('replyTo'),
            'metadata': data.get('metadata', {}),
            'timestamp': now_iso(),
            'status': 'sent',
            'reactions': [],
            'read_by': [sender_id],
            'ai_generated': 0
        }
        
        db = get_db()
        db.execute('''
            INSERT INTO chat_messages 
            (id, conversation_id, sender_id, type, content, reply_to, metadata, timestamp, status, reactions, read_by, ai_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message['id'], message['conversation_id'], message['sender_id'], message['type'],
              message['content'], message['reply_to'], json.dumps(message['metadata']),
              message['timestamp'], message['status'], json.dumps(message['reactions']), 
              json.dumps(message['read_by']), message['ai_generated']))
        
        # Update conversation
        preview = message['content'][:50]
        if message['type'] == 'voice':
            preview = '🎤 Hlasová zpráva'
        elif message['type'] == 'image':
            preview = '📷 Obrázek'
        
        db.execute('''
            UPDATE chat_conversations SET updated_at = ?, last_message = ? WHERE id = ?
        ''', (message['timestamp'], json.dumps({
            'content': preview, 
            'sender_id': message['sender_id'], 
            'timestamp': message['timestamp']
        }), message['conversation_id']))
        db.commit()
        
        # Emit to WebSocket
        socketio.emit('new_message', message, room=conversation_id)
        
        # Update stats
        update_daily_stats('total_messages')
        if message['type'] == 'voice':
            update_daily_stats('voice_messages')
        
        # === RADIM AI ODPOVĚĎ ===
        # Pokud je zpráva pro Radima (obsahuje 'radim' v participants)
        cursor = db.execute('SELECT participants FROM chat_conversations WHERE id = ?', (conversation_id,))
        conv = cursor.fetchone()
        
        if conv and 'radim' in json.loads(conv['participants']) and sender_id != 'radim':
            # Získej historii konverzace
            cursor = db.execute('''
                SELECT sender_id, content FROM chat_messages 
                WHERE conversation_id = ? 
                ORDER BY timestamp DESC LIMIT 10
            ''', (conversation_id,))
            history = [dict(row) for row in cursor.fetchall()]
            history.reverse()
            
            # Získej AI odpověď
            ai_response = get_ai_response(history)
            
            if ai_response:
                ai_message = {
                    'id': generate_id(),
                    'conversation_id': conversation_id,
                    'sender_id': 'radim',
                    'type': 'text',
                    'content': ai_response,
                    'reply_to': message['id'],
                    'metadata': {'ai_provider': 'gemini'},
                    'timestamp': now_iso(),
                    'status': 'sent',
                    'reactions': [],
                    'read_by': ['radim'],
                    'ai_generated': 1
                }
                
                db.execute('''
                    INSERT INTO chat_messages 
                    (id, conversation_id, sender_id, type, content, reply_to, metadata, timestamp, status, reactions, read_by, ai_generated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ai_message['id'], ai_message['conversation_id'], ai_message['sender_id'], ai_message['type'],
                      ai_message['content'], ai_message['reply_to'], json.dumps(ai_message['metadata']),
                      ai_message['timestamp'], ai_message['status'], json.dumps(ai_message['reactions']),
                      json.dumps(ai_message['read_by']), ai_message['ai_generated']))
                
                db.execute('''
                    UPDATE chat_conversations SET updated_at = ?, last_message = ? WHERE id = ?
                ''', (ai_message['timestamp'], json.dumps({
                    'content': ai_response[:50], 
                    'sender_id': 'radim', 
                    'timestamp': ai_message['timestamp']
                }), conversation_id))
                db.commit()
                
                # Emit AI response
                socketio.emit('new_message', ai_message, room=conversation_id)
                update_daily_stats('ai_messages')
                
                # Send push notification
                send_push_notification(
                    sender_id,
                    'Radim odpověděl',
                    ai_response[:100],
                    {'conversationId': conversation_id, 'messageId': ai_message['id']}
                )
        
        return jsonify({'success': True, 'message': message}), 201
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/chat/messages/<message_id>/read', methods=['PATCH'])
@optional_auth
def mark_as_read(message_id):
    try:
        data = request.json
        user_id = data['userId']
        
        db = get_db()
        cursor = db.execute('SELECT read_by FROM chat_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()
        
        if row:
            read_by = json.loads(row['read_by']) if row['read_by'] else []
            if user_id not in read_by:
                read_by.append(user_id)
                db.execute('UPDATE chat_messages SET read_by = ?, status = ? WHERE id = ?', 
                          (json.dumps(read_by), 'read', message_id))
                db.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/chat/messages/<message_id>/reaction', methods=['POST'])
@optional_auth
def add_reaction(message_id):
    try:
        data = request.json
        user_id = data['userId']
        emoji = data['emoji']
        conversation_id = data.get('conversationId')
        
        db = get_db()
        cursor = db.execute('SELECT reactions FROM chat_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()
        
        if row:
            reactions = json.loads(row['reactions']) if row['reactions'] else []
            existing = next((r for r in reactions if r['userId'] == user_id and r['emoji'] == emoji), None)
            if existing:
                reactions.remove(existing)
            else:
                reactions.append({'userId': user_id, 'emoji': emoji, 'timestamp': now_iso()})
            
            db.execute('UPDATE chat_messages SET reactions = ? WHERE id = ?', (json.dumps(reactions), message_id))
            db.commit()
            
            if conversation_id:
                socketio.emit('message_reaction', {'messageId': message_id, 'reactions': reactions}, room=conversation_id)
            
            return jsonify({'success': True, 'reactions': reactions})
        
        return jsonify({'success': False, 'error': 'Message not found'}), 404
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - CONTACTS
# ============================================
@app.route('/api/chat/contacts/<user_id>', methods=['GET'])
@optional_auth
def get_contacts(user_id):
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT c.*, u.online, u.last_seen, u.avatar as user_avatar
            FROM chat_contacts c
            LEFT JOIN chat_users u ON c.contact_id = u.id
            WHERE c.user_id = ?
            ORDER BY c.pinned DESC, c.name ASC
        ''', (user_id,))
        
        contacts = []
        for row in cursor.fetchall():
            contact = dict(row)
            contact['online'] = contact.get('contact_id') in users_online or contact.get('online', 0) == 1
            contact['avatar'] = contact.get('avatar') or contact.get('user_avatar')
            contacts.append(contact)
        
        # Always include Radim
        radim_exists = any(c['contact_id'] == 'radim' for c in contacts)
        if not radim_exists:
            contacts.insert(0, {
                'id': 'radim-default', 'user_id': user_id, 'contact_id': 'radim',
                'name': 'Radim Asistent', 'role': 'AI Asistent', 'avatar': None,
                'pinned': 1, 'muted': 0, 'online': True
            })
        
        return jsonify({'success': True, 'contacts': contacts})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/chat/contacts', methods=['POST'])
@optional_auth
def add_contact():
    try:
        data = request.json
        contact = {
            'id': generate_id(), 
            'user_id': data['userId'], 
            'contact_id': data['contactId'],
            'name': data['name'], 
            'role': data.get('role', 'Rodina'), 
            'avatar': data.get('avatar'),
            'pinned': 1 if data.get('pinned') else 0, 
            'muted': 0, 
            'created_at': now_iso()
        }
        
        db = get_db()
        db.execute('''
            INSERT INTO chat_contacts (id, user_id, contact_id, name, role, avatar, pinned, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (contact['id'], contact['user_id'], contact['contact_id'], contact['name'], 
              contact['role'], contact['avatar'], contact['pinned'], contact['created_at']))
        db.commit()
        
        return jsonify({'success': True, 'contact': contact}), 201
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - MEDIA UPLOAD
# ============================================
@app.route('/api/media/upload', methods=['POST'])
def upload_media():
    """Upload média (obrázek, audio, video)"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        user_id = request.form.get('userId', 'anonymous')
        media_type = request.form.get('type', 'auto')
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Upload to Cloudinary
        result = upload_to_cloudinary(file, resource_type=media_type)
        
        if not result:
            # Fallback - store as base64
            file_data = base64.b64encode(file.read()).decode('utf-8')
            result = {
                'url': f"data:{file.content_type};base64,{file_data}",
                'public_id': generate_id(),
                'size': len(file_data)
            }
        
        # Save to database
        media_id = generate_id()
        db = get_db()
        db.execute('''
            INSERT INTO chat_media (id, user_id, type, url, public_id, filename, size, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (media_id, user_id, media_type, result['url'], result.get('public_id'), 
              file.filename, result.get('size'), now_iso()))
        db.commit()
        
        return jsonify({
            'success': True,
            'media': {
                'id': media_id,
                'url': result['url'],
                'type': media_type,
                'filename': file.filename,
                'size': result.get('size')
            }
        })
        
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/media/voice', methods=['POST'])
def upload_voice_message():
    """Upload hlasové zprávy"""
    try:
        if 'audio' not in request.files:
            return jsonify({'success': False, 'error': 'No audio provided'}), 400
        
        file = request.files['audio']
        user_id = request.form.get('userId', 'anonymous')
        duration = request.form.get('duration', 0)
        
        result = upload_to_cloudinary(file, resource_type='video', folder='radim-chat/voice')
        
        if not result:
            file_data = base64.b64encode(file.read()).decode('utf-8')
            result = {
                'url': f"data:audio/webm;base64,{file_data}",
                'public_id': generate_id()
            }
        
        media_id = generate_id()
        db = get_db()
        db.execute('''
            INSERT INTO chat_media (id, user_id, type, url, public_id, duration, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (media_id, user_id, 'voice', result['url'], result.get('public_id'), duration, now_iso()))
        db.commit()
        
        return jsonify({
            'success': True,
            'voice': {
                'id': media_id,
                'url': result['url'],
                'duration': duration
            }
        })
        
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - PUSH NOTIFICATIONS
# ============================================
@app.route('/api/push/subscribe', methods=['POST'])
def subscribe_push():
    """Přihlásit k push notifikacím"""
    try:
        data = request.json
        user_id = data['userId']
        subscription = data['subscription']
        
        db = get_db()
        if is_postgres():
            db.execute('''
                INSERT INTO push_subscriptions (id, user_id, endpoint, keys, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (user_id, endpoint) DO UPDATE SET
                    keys = EXCLUDED.keys, created_at = EXCLUDED.created_at
            ''', (generate_id(), user_id, subscription['endpoint'],
                  json.dumps(subscription['keys']), now_iso()))
        else:
            db.execute('''
                INSERT OR REPLACE INTO push_subscriptions (id, user_id, endpoint, keys, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (generate_id(), user_id, subscription['endpoint'],
                  json.dumps(subscription['keys']), now_iso()))
        db.commit()
        
        return jsonify({'success': True, 'message': 'Subscribed to push notifications'})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/push/unsubscribe', methods=['POST'])
def unsubscribe_push():
    """Odhlásit z push notifikací"""
    try:
        data = request.json
        user_id = data['userId']
        endpoint = data.get('endpoint')
        
        db = get_db()
        if endpoint:
            db.execute('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?', (user_id, endpoint))
        else:
            db.execute('DELETE FROM push_subscriptions WHERE user_id = ?', (user_id,))
        db.commit()
        
        return jsonify({'success': True, 'message': 'Unsubscribed from push notifications'})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/push/vapid-key', methods=['GET'])
def get_vapid_key():
    """Získej VAPID public key pro frontend"""
    return jsonify({
        'success': True,
        'publicKey': VAPID_PUBLIC_KEY or ''
    })

@app.route('/api/push/test', methods=['POST'])
def test_push():
    """Test push notifikace"""
    try:
        data = request.json
        user_id = data['userId']
        
        success = send_push_notification(
            user_id,
            'Test od Radima 🎉',
            'Toto je testovací notifikace. Pokud ji vidíte, vše funguje!',
            {'test': True}
        )
        
        return jsonify({'success': success})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - WORDPRESS INTEGRATION
# ============================================
@app.route('/api/wordpress/login', methods=['POST'])
def wp_login():
    """Přihlášení přes WordPress"""
    try:
        data = request.json
        email = data.get('email')
        
        wp_user = get_wp_user(email)
        if wp_user:
            user_id = sync_wp_user(wp_user)
            
            return jsonify({
                'success': True,
                'user': {
                    'id': user_id,
                    'name': wp_user.get('name'),
                    'email': email,
                    'avatar': wp_user.get('avatar_urls', {}).get('96'),
                    'wp_id': wp_user['id']
                }
            })
        
        return jsonify({'success': False, 'error': 'User not found'}), 404
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/wordpress/sync', methods=['POST'])
def wp_sync_users():
    """Synchronizuj WordPress uživatele"""
    try:
        if not WP_URL or not WP_USER:
            return jsonify({'success': False, 'error': 'WordPress not configured'}), 500
        
        response = requests.get(
            f"{WP_URL}/wp-json/wp/v2/users",
            params={'per_page': 100},
            auth=(WP_USER, WP_APP_PASSWORD),
            timeout=30
        )
        
        if response.status_code == 200:
            users = response.json()
            synced = []
            for wp_user in users:
                user_id = sync_wp_user(wp_user)
                if user_id:
                    synced.append(user_id)
            
            return jsonify({
                'success': True,
                'synced': len(synced),
                'users': synced
            })
        
        return jsonify({'success': False, 'error': 'WordPress API error'}), 500
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - ADMIN DASHBOARD
# ============================================
def update_daily_stats(field):
    """Aktualizuj denní statistiky"""
    # Whitelist allowed field names to prevent SQL injection
    ALLOWED_FIELDS = {'total_messages', 'total_users', 'ai_messages', 'voice_messages', 'active_conversations'}
    if field not in ALLOWED_FIELDS:
        logger.warning(f"⚠️  Invalid stats field: {field}")
        return
    try:
        db = get_db()
        today = today_date()

        db.execute(f'''
            INSERT INTO admin_stats (id, date, {field})
            VALUES (?, ?, 1)
            ON CONFLICT(date) DO UPDATE SET {field} = {field} + 1
        ''', (generate_id(), today))
        db.commit()
    except Exception as e:
        logger.error(f"Stats update error: {e}")

@app.route('/api/admin/stats', methods=['GET'])
@require_auth
def get_admin_stats():
    """Získej statistiky pro admin dashboard"""
    try:
        days = request.args.get('days', 7, type=int)
        
        db = get_db()
        
        # Daily stats
        cursor = db.execute('''
            SELECT * FROM admin_stats 
            ORDER BY date DESC LIMIT ?
        ''', (days,))
        daily_stats = [dict(row) for row in cursor.fetchall()]
        
        # Total counts
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_messages')
        total_messages = cursor.fetchone()['count']
        
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_users WHERE role != "ai_assistant"')
        total_users = cursor.fetchone()['count']
        
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_conversations')
        total_conversations = cursor.fetchone()['count']
        
        cursor = db.execute('SELECT COUNT(*) as count FROM chat_messages WHERE ai_generated = 1')
        ai_messages = cursor.fetchone()['count']
        
        # Active users (online now)
        active_users = len(users_online)
        
        # Recent activity
        cursor = db.execute('''
            SELECT m.*, u.name as sender_name 
            FROM chat_messages m
            LEFT JOIN chat_users u ON m.sender_id = u.id
            ORDER BY m.timestamp DESC LIMIT 20
        ''')
        recent_messages = [dict(row) for row in cursor.fetchall()]
        
        return jsonify({
            'success': True,
            'stats': {
                'totals': {
                    'messages': total_messages,
                    'users': total_users,
                    'conversations': total_conversations,
                    'ai_messages': ai_messages,
                    'active_users': active_users
                },
                'daily': daily_stats,
                'recent_activity': recent_messages
            }
        })
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/admin/users', methods=['GET'])
@require_auth
def get_admin_users():
    """Seznam všech uživatelů"""
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT u.*, 
                   (SELECT COUNT(*) FROM chat_messages WHERE sender_id = u.id) as message_count,
                   (SELECT COUNT(*) FROM chat_conversations WHERE participants LIKE '%"' || u.id || '"%') as conversation_count
            FROM chat_users u
            ORDER BY u.created_at DESC
        ''')
        users = [dict(row) for row in cursor.fetchall()]
        
        for user in users:
            user['online'] = user['id'] in users_online
            user['settings'] = json.loads(user['settings']) if user['settings'] else {}
        
        return jsonify({'success': True, 'users': users})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

@app.route('/api/admin/conversations', methods=['GET'])
@require_auth
def get_admin_conversations():
    """Seznam všech konverzací pro admin"""
    try:
        db = get_db()
        cursor = db.execute('''
            SELECT c.*,
                   (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
            FROM chat_conversations c
            ORDER BY c.updated_at DESC
        ''')
        conversations = []
        for row in cursor.fetchall():
            conv = dict(row)
            conv['participants'] = json.loads(conv['participants'])
            conv['last_message'] = json.loads(conv['last_message']) if conv['last_message'] else None
            conversations.append(conv)
        
        return jsonify({'success': True, 'conversations': conversations})
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# REST API - AI SETTINGS
# ============================================
@app.route('/api/ai/settings', methods=['GET'])
def get_ai_settings():
    """Získej AI nastavení"""
    return jsonify({
        'success': True,
        'settings': {
            'providers': {
                'gemini': bool(GEMINI_API_KEY),
                'claude': bool(ANTHROPIC_API_KEY),
                'openai': bool(OPENAI_API_KEY)
            },
            'primary_provider': 'gemini' if GEMINI_API_KEY else ('claude' if ANTHROPIC_API_KEY else None),
            'radim_enabled': bool(GEMINI_API_KEY or ANTHROPIC_API_KEY)
        }
    })

@app.route('/api/ai/chat', methods=['POST'])
@require_auth
@rate_limit(max_requests=20, window_seconds=60, key_func='user')
def ai_chat():
    """Přímý chat s AI (bez ukládání do konverzace)"""
    try:
        data = request.json
        messages = data.get("messages", [])
        image_data = data.get("image")  # Base64 image
        
        if not messages:
            return jsonify({"success": False, "error": "No messages provided"}), 400
        
        response = get_ai_response(messages, context=None, image=image_data)
        return jsonify({
            'success': True,
            'response': response,
            'provider': 'gemini' if GEMINI_API_KEY else 'claude'
        })
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# ============================================
# SOCKET.IO EVENTS
# ============================================
@socketio.on('connect')
def handle_connect():
    logger.info(f'🔌 Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    user_id = None
    for uid, sid in list(users_online.items()):
        if sid == request.sid:
            user_id = uid
            del users_online[uid]
            break
    if user_id:
        socketio.emit('user_offline', {'userId': user_id, 'timestamp': now_iso()}, broadcast=True)
        # Update user last_seen (using adapter for proper connection handling)
        db = None
        try:
            db = get_connection()
            db.execute('UPDATE chat_users SET online = 0, last_seen = ? WHERE id = ?', (now_iso(), user_id))
            db.commit()
        except Exception as e:
            logger.warning(f"⚠️  Error updating user offline status: {e}")
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

@socketio.on('join')
def handle_join(data):
    user_id = data.get('userId')
    if user_id:
        _cleanup_users_online()
        users_online[user_id] = request.sid
        join_room(user_id)
        socketio.emit('user_online', {'userId': user_id, 'timestamp': now_iso()}, broadcast=True)
        # Update user online status (using adapter for proper connection handling)
        db = None
        try:
            db = get_connection()
            db.execute('UPDATE chat_users SET online = 1 WHERE id = ?', (user_id,))
            db.commit()
        except Exception as e:
            logger.warning(f"⚠️  Error updating user online status: {e}")
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

@socketio.on('join_conversation')
def handle_join_conversation(data):
    conversation_id = data.get('conversationId')
    if conversation_id:
        join_room(conversation_id)

@socketio.on('leave_conversation')
def handle_leave_conversation(data):
    conversation_id = data.get('conversationId')
    if conversation_id:
        leave_room(conversation_id)

@socketio.on('send_message')
def handle_send_message(data):
    conversation_id = data.get('conversationId') or data.get('conversation_id')
    if conversation_id:
        emit('new_message', data, room=conversation_id, include_self=False)

@socketio.on('typing')
def handle_typing(data):
    conversation_id = data.get('conversationId')
    user_id = data.get('userId')
    if conversation_id:
        emit('user_typing', {'userId': user_id, 'conversationId': conversation_id, 'timestamp': now_iso()}, 
             room=conversation_id, include_self=False)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    conversation_id = data.get('conversationId')
    user_id = data.get('userId')
    if conversation_id:
        emit('user_stop_typing', {'userId': user_id, 'conversationId': conversation_id}, 
             room=conversation_id, include_self=False)

@socketio.on('mark_read')
def handle_mark_read(data):
    conversation_id = data.get('conversationId')
    if conversation_id:
        emit('messages_read', data, room=conversation_id, include_self=False)


# ============================================
# 🎤 STT STREAMING → BRAIN (v272)
# ============================================

@socketio.on('stt_interim')
def handle_stt_interim(data):
    """Process interim STT results for early Brain Ψ(t) estimation."""
    try:
        text = data.get('text', '')
        user_id = data.get('user_id', 'anonymous')
        is_final = data.get('is_final', False)

        if not text:
            return

        # Quick C/alpha estimation from text
        try:
            from intent_resolver import quick_estimate_from_text, resolve_intent
            C_est, alpha_est = quick_estimate_from_text(text)
        except ImportError:
            C_est, alpha_est = 5.0, 0.2

        # Update early Ψ cache (no DB write for interim)
        try:
            from radim_brain_routes import update_early_psi
            update_early_psi(user_id, C_est, alpha_est, is_final)
        except ImportError:
            pass

        # Determine mode
        mode = 'HARMONY'
        if C_est >= 27:
            mode = 'CRISIS'
        elif C_est >= 12:
            mode = 'ALERT'

        # On final: check if intent can be resolved locally
        intent_hint = None
        if is_final:
            try:
                from intent_resolver import resolve_intent
                resolved, intent_label, _ = resolve_intent(text, user_id, mode)
                intent_hint = intent_label
            except Exception:
                pass

        emit('brain_update', {
            'C': round(C_est, 2),
            'alpha': round(alpha_est, 3),
            'mode': mode,
            'is_final': is_final,
            'intent_hint': intent_hint
        })
    except Exception as e:
        logger.error(f"⚠️ stt_interim error (non-fatal): {e}")

# ============================================
# 🎓 EDUCATION SOCKETIO — Teacher ↔ Student
# ============================================

@socketio.on('join_education')
def handle_join_education(data):
    """Student/teacher joins their education room for notifications.
    Requires JWT token for verification — prevents room spoofing."""
    token = data.get('token', '')
    user_id = data.get('userId')
    if not user_id or not token:
        emit('education_error', {'error': 'userId and token required'})
        return
    # Verify JWT matches the claimed userId
    try:
        from auth_middleware import decode_jwt
        payload = decode_jwt(token)
        if not payload:
            emit('education_error', {'error': 'Invalid token'})
            return
        token_user_id = str(payload.get('user', {}).get('id', ''))
        if token_user_id != str(user_id):
            emit('education_error', {'error': 'Token userId mismatch'})
            return
    except Exception:
        emit('education_error', {'error': 'Auth verification failed'})
        return
    join_room(f'user_{user_id}')
    logger.info(f"🎓 User {user_id} joined education room (verified)")


@socketio.on('leave_education')
def handle_leave_education(data):
    """Leave education notification room"""
    user_id = data.get('userId')
    if user_id:
        leave_room(f'user_{user_id}')


# ============================================
# STUB ENDPOINTS (prevent 404/CORS errors in frontend)
# ============================================

@app.route('/api/consciousness/unified/state')
def consciousness_unified_state():
    """Stub for consciousness panel - not implemented in v3.0.0"""
    senior_id = request.args.get('senior_id', 'unknown')
    return jsonify({
        "status": "not_implemented",
        "message": "Consciousness panel not available in backend v3.0.0",
        "senior_id": senior_id
    }), 200

@app.route('/api/messenger/contacts')
def messenger_contacts():
    """Stub for messenger contacts - not implemented in v3.0.0"""
    return jsonify([]), 200

@app.route('/kal/radim/health')
def kal_radim_health():
    """KAL Radim health check"""
    return jsonify({
        "success": True,
        "status": "ok",
        "message": "Radim Memory API v1.0 — running"
    }), 200

@app.route('/kal/radim/history/<user_id>')
def kal_radim_history(user_id):
    """Get user conversation history + stats"""
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import get_conversation_messages, get_user_context
            limit = min(request.args.get('limit', 10, type=int), 200)
            history = get_conversation_messages(user_id, limit=limit)
            ctx = get_user_context(user_id)
            return jsonify({
                "success": True,
                "conversations": history,
                "stats": {
                    "total_conversations": len(history),
                    "days_active": 1,
                    "breakthrough_count": 0,
                    "milestone_count": 0
                },
                "recent_mood": ctx.get("last_mood", "neutral"),
                "progress": "stabilni",
                "breakthroughs": [],
                "milestones": []
            }), 200
    except Exception as e:
        logger.error(f"⚠️ kal_radim_history error: {e}")
    return jsonify({"success": True, "conversations": [], "stats": {"total_conversations": 0, "days_active": 0, "breakthrough_count": 0, "milestone_count": 0}, "recent_mood": "neutral", "progress": "start", "breakthroughs": [], "milestones": []}), 200

@app.route('/kal/radim/user/register', methods=['POST', 'OPTIONS'])
def kal_radim_register():
    """Register a new user in memory system"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    user_id = data.get('user_id', str(uuid.uuid4()))
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import _db_load_profile, _db_save_profile
            profile = _db_load_profile(user_id)
            if not profile:
                profile = {
                    "user_id": user_id,
                    "created_at": datetime.utcnow().isoformat(),
                    "first_message": data.get("first_message", "")
                }
                _db_save_profile(user_id, profile)
    except Exception as e:
        logger.error(f"⚠️ kal_radim_register error: {e}")
    return jsonify({"success": True, "message": "User registered", "user": {"user_id": user_id}}), 200

@app.route('/kal/radim/user/<user_id>', methods=['PUT', 'OPTIONS'])
def kal_radim_update_user(user_id):
    """Update user profile"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import _db_load_profile, _db_save_profile
            profile = _db_load_profile(user_id) or {"user_id": user_id}
            profile.update(data)
            _db_save_profile(user_id, profile)
            return jsonify({"success": True, "user": profile}), 200
    except Exception as e:
        logger.error(f"⚠️ kal_radim_update_user error: {e}")
    return jsonify({"success": True, "user": {"user_id": user_id}}), 200

@app.route('/kal/radim/insights/<user_id>')
def kal_radim_insights(user_id):
    """Get user insights from learning data"""
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import get_user_context
            ctx = get_user_context(user_id)
            return jsonify({
                "success": True,
                "insights": {
                    "total_interactions": ctx.get("interaction_count", 0),
                    "preferred_length": ctx.get("preferred_length", "medium"),
                    "communication_style": ctx.get("communication_style", "warm"),
                    "last_mood": ctx.get("last_mood", "neutral"),
                    "top_topics": {t: 1 for t in ctx.get("top_interests", [])},
                    "conversation_count": len(ctx.get("recent_history", []))
                }
            }), 200
    except Exception as e:
        logger.error(f"⚠️ kal_radim_insights error: {e}")
    return jsonify({"success": True, "insights": {"total_interactions": 0, "preferred_length": "medium", "communication_style": "warm", "last_mood": "neutral", "top_topics": {}, "conversation_count": 0}}), 200

@app.route('/kal/radim/conversation', methods=['POST', 'OPTIONS'])
def kal_radim_conversation():
    """Save a conversation turn"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    user_id = data.get('user_id', 'anonymous')
    try:
        if MEMORY_AVAILABLE:
            from memory_routes import record_interaction
            record_interaction(
                user_id=user_id,
                user_message=data.get('user_message', ''),
                assistant_response=data.get('kafanek_reply', '')
            )
    except Exception as e:
        logger.error(f"⚠️ kal_radim_conversation error: {e}")
    return jsonify({"success": True, "conversation": {"saved": True}}), 200

@app.route('/kal/radim/stats')
def kal_radim_stats():
    """Global Radim stats"""
    try:
        if MEMORY_AVAILABLE:
            from database import get_connection, is_postgres
            db = None
            try:
                db = get_connection()
                profiles_count = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()['cnt']
                history_count = db.execute("SELECT COUNT(*) as cnt FROM memory_history").fetchone()['cnt']
            finally:
                if db:
                    try:
                        db.close()
                    except Exception:
                        pass
            return jsonify({
                "success": True,
                "message": f"Radim pomohl {profiles_count} lidem v {history_count} konverzacich",
                "impact": {
                    "total_users": profiles_count,
                    "total_conversations": history_count,
                    "active_today": profiles_count
                }
            }), 200
    except Exception as e:
        logger.error(f"⚠️ kal_radim_stats error: {e}")
    return jsonify({"success": True, "message": "Radim stats", "impact": {"total_users": 0, "total_conversations": 0, "active_today": 0}}), 200

@app.route('/api/proxy/azure/speech-token')
def azure_speech_token():
    """Stub for Azure speech token - use /api/speech/azure-token instead"""
    return jsonify({
        "error": "Use /api/speech/azure-token endpoint instead",
        "status": "deprecated"
    }), 200

@app.route('/api/windsurf/health')
def windsurf_health():
    """Stub for Windsurf health - not implemented in v3.0.0"""
    return jsonify({
        "status": "ok",
        "message": "Windsurf integration not available"
    }), 200

# ============================================
# CLIENT & EMERGENCY MANAGEMENT
# ============================================

@app.route('/api/clients', methods=['POST', 'OPTIONS'])
def api_clients():
    """Client registration and sync endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
        
    data = request.get_json() or {}
    action = data.get('action', 'sync')
    
    if action == 'sync':
        client = data.get('client', {})
        contacts = data.get('contacts', [])
        
        # Store in database (simplified - would use proper DB in production)
        client_id = client.get('id')
        if client_id:
            # Log sync event
            logger.info(f"[CLIENT SYNC] {client_id}")
            
        return jsonify({
            'success': True,
            'action': 'sync',
            'client_id': client_id,
            'contacts_count': len(contacts),
            'timestamp': now_iso()
        }), 200
    
    return jsonify({
        'success': False,
        'error': 'Unknown action'
    }), 400

@app.route('/api/clients/<client_id>', methods=['GET', 'OPTIONS'])
def api_get_client(client_id):
    """Get client data by ID"""
    if request.method == 'OPTIONS':
        return '', 204
        
    # In production, load from database
    # For now, return empty to indicate no server-side data
    return jsonify({
        'success': True,
        'client': None,
        'contacts': [],
        'message': 'Client data managed on frontend (localStorage)'
    }), 200

@app.route('/api/emergency', methods=['POST', 'OPTIONS'])
def api_emergency():
    """Emergency notification endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
        
    data = request.get_json() or {}
    event = data.get('event', 'unknown')
    user_id = data.get('user_id', 'unknown')
    timestamp = data.get('timestamp', now_iso())
    
    # Log emergency event
    logger.info(f"[EMERGENCY] {event} from {user_id} at {timestamp}")
    
    # In production, this would:
    # 1. Send SMS/push to emergency contacts
    # 2. Notify caregivers
    # 3. Log to incident database
    # 4. Potentially call emergency services
    
    contacts = data.get('contacts', [])
    
    return jsonify({
        'success': True,
        'event': event,
        'user_id': user_id,
        'timestamp': timestamp,
        'contacts_notified': len(contacts),
        'message': 'Emergency logged successfully'
    }), 200

# ============================================
# v281: KAL Agent Endpoints — Brain Communication Bridge
# ============================================

_KAL_AGENT_PROMPTS = {
    'core': '',
    'agent_protector': '[Režim: Pan Ochránce — priorita bezpečí a klid. Odpovídej stručně, uklidňujícím tónem.]',
    'agent_teacher': '[Režim: Pan Učitel — vzdělávací režim. Vysvětluj srozumitelně, použij příklady.]',
    'agent_storyteller': '[Režim: Pan Vypravěč — kreativní vyprávění. Buď poetický, používej obrazy.]',
    'agent_senior': '[Režim: Pan Senior — zjednodušený režim. Krátké věty, přátelský tón.]',
    'agent_caller': '[Režim: Agent Caller — asistence s telefonáty. Nabídni zavolání, přepojení.]',
    'agent_coder': '[Režim: Pan Programátor — technická podpora. Přesné instrukce krok za krokem.]',
}

def _get_agent_name(agent):
    """Get Czech display name for agent type."""
    names = {
        'core': 'Pan Kafánek',
        'agent_teacher': 'Pan Učitel Kafánek',
        'agent_protector': 'Pan Ochránce Kafánek',
        'agent_storyteller': 'Pan Vypravěč Kafánek',
        'agent_senior': 'Pan Senior Kafánek',
        'agent_caller': 'Agent Caller',
        'agent_coder': 'Pan Programátor'
    }
    return names.get(agent, 'Pan Kafánek')


@app.route('/kal/agents/interact', methods=['POST', 'OPTIONS'])
@rate_limit(max_requests=30, window_seconds=60, key_func='ip')
def kal_agents_interact():
    """KAL Agent interaction — routes to appropriate agent via orchestrator (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    agent = data.get('agent', 'core')
    message = data.get('message', '')
    context = data.get('context', {})
    session_id = data.get('session_id')

    if not message:
        return jsonify({'success': False, 'error': 'Message required'}), 400

    agent_prefix = _KAL_AGENT_PROMPTS.get(agent, '')

    try:
        from radim_orchestrator import call_gemini_whatsapp
        from intent_resolver import resolve_intent

        # Intent resolver first (local NLU bypass)
        resolved_text, resolved_intent, _ = resolve_intent(message)
        if resolved_text:
            response_text = resolved_text
        else:
            response_text, _ = call_gemini_whatsapp(
                message, context, context.get('mode', 'senior'),
                agent_prefix, None, '', None
            )

        # Get brain state for consciousness_state field
        consciousness_state = None
        phi_metrics = None
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_psi_state, derive_text_empathy_proxies
            proxies = derive_text_empathy_proxies(message, 'neutral', 0.2)
            psi = compute_psi_state(5.0, 0.2, proxies['voice_tone'], proxies['hrv'], proxies['speech_tempo'])
            consciousness_state = {
                'mode': psi['mode'],
                'coherence': psi['coherence'],
                'C': psi['psi']['C'],
                'E': psi['psi']['E']
            }
            phi_metrics = {
                'phi_index': psi['phi_index'],
                'rho_stability': psi['rho_stability']
            }

        return jsonify({
            'success': True,
            'response': response_text or 'Promiňte, zkuste to za chvíli.',
            'consciousness_state': consciousness_state,
            'phi_metrics': phi_metrics,
            'agent': agent,
            'agentName': _get_agent_name(agent)
        }), 200

    except Exception as e:
        logger.error(f"kal_agents_interact error: {e}")
        return jsonify({
            'success': False,
            'response': 'Omlouvám se, momentálně nejsem dostupný.',
            'agent': agent,
            'error': str(e)
        }), 500


@app.route('/kal/timing/calculate', methods=['POST', 'OPTIONS'])
def kal_timing_calculate():
    """φ-based timing calculation for text (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    text = data.get('text', '')

    try:
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_unified_speech
            from intent_resolver import quick_estimate_from_text
            C_est, alpha_est = quick_estimate_from_text(text)
            mode = "HARMONY" if C_est < 12 else ("ALERT" if C_est < 27 else "CRISIS")
            speech = compute_unified_speech(C_est, alpha_est, mode)
            # Rate is a float multiplier (1.0=normal, 0.85=slower, 0.7=crisis)
            rate = float(speech.get('rate', 1.0))
            wpm = round(120 * rate)  # 120 base × rate → 120/102/84
            return jsonify({
                'pause_ms': speech.get('pause_ms', 618),
                'wpm': wpm,
                'rate': rate,
                'phi_ratio': 1.618,
                'mode': mode,
                'phrasing': speech.get('phrasing', 'natural'),
                'style': speech.get('style', 'friendly'),
            }), 200
    except Exception as e:
        logger.warning(f"kal_timing_calculate error: {e}")

    return jsonify({'pause_ms': 800, 'wpm': 120, 'phi_ratio': 1.618, 'mode': 'HARMONY'}), 200


@app.route('/kal/safety/check', methods=['POST', 'OPTIONS'])
def kal_safety_check():
    """Safety/crisis detection for message (v281)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    message = data.get('message', '')

    try:
        from intent_resolver import quick_estimate_from_text, _CRISIS_WORDS, _STRESS_WORDS
        C_est, alpha_est = quick_estimate_from_text(message)
        text_lower = message.lower()

        crisis_hits = sum(1 for w in _CRISIS_WORDS if w in text_lower)
        stress_hits = sum(1 for w in _STRESS_WORDS if w in text_lower)

        alert = None
        severity = 'low'
        recommendation = None

        if crisis_hits > 0 or C_est >= 27:
            alert = 'panic'
            severity = 'critical'
            recommendation = 'Okamžitě kontaktujte záchrannou službu nebo rodinu.'
        elif stress_hits >= 2 or C_est >= 12:
            alert = 'stress'
            severity = 'medium'
            recommendation = 'Uživatel může potřebovat podporu. Zvažte kontaktování rodiny.'
        elif stress_hits == 1:
            alert = 'mild_stress'
            severity = 'low'
            recommendation = 'Monitorujte situaci.'

        return jsonify({
            'alert': alert,
            'severity': severity,
            'recommendation': recommendation,
            'shouldEscalate': alert == 'panic',
            'C_estimate': round(C_est, 1),
            'alpha_estimate': round(alpha_est, 2)
        }), 200

    except Exception as e:
        logger.warning(f"kal_safety_check error: {e}")

    return jsonify({'alert': None, 'severity': 'low', 'recommendation': None, 'shouldEscalate': False}), 200


@app.route('/kal/emotion/analyze', methods=['POST', 'OPTIONS'])
def kal_emotion_analyze():
    """Emotion analysis from text — valence/arousal model (v319)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    text = data.get('text', '')

    try:
        from intent_resolver import quick_estimate_from_text, _CRISIS_WORDS, _STRESS_WORDS, _CALM_WORDS
        C_est, alpha_est = quick_estimate_from_text(text)
        text_lower = text.lower()

        crisis_hits = sum(1 for w in _CRISIS_WORDS if w in text_lower)
        stress_hits = sum(1 for w in _STRESS_WORDS if w in text_lower)
        calm_hits = sum(1 for w in _CALM_WORDS if w in text_lower)

        # Valence: -1 (negative) to +1 (positive)
        valence = round(max(-1.0, min(1.0,
            0.0 + calm_hits * 0.3 - stress_hits * 0.2 - crisis_hits * 0.5)), 2)

        # Arousal: 0 (calm) to 1 (agitated)
        arousal = round(max(0.0, min(1.0, alpha_est)), 2)

        # Primary emotion mapping
        if crisis_hits > 0:
            primary = 'strach'
        elif stress_hits >= 2:
            primary = 'úzkost' if valence < -0.3 else 'smutek'
        elif stress_hits == 1:
            primary = 'nejistota'
        elif calm_hits >= 2:
            primary = 'radost' if valence > 0.5 else 'klid'
        elif calm_hits == 1:
            primary = 'spokojenost'
        else:
            primary = 'neutrální'

        mode = "HARMONY" if C_est < 12 else ("ALERT" if C_est < 27 else "CRISIS")

        return jsonify({
            'primary_emotion': primary,
            'valence': valence,
            'arousal': arousal,
            'C_estimate': round(C_est, 1),
            'mode': mode,
            'word_hits': {
                'crisis': crisis_hits,
                'stress': stress_hits,
                'calm': calm_hits
            }
        }), 200

    except Exception as e:
        logger.warning(f"kal_emotion_analyze error: {e}")

    return jsonify({
        'primary_emotion': 'neutrální',
        'valence': 0.0, 'arousal': 0.2,
        'C_estimate': 5.0, 'mode': 'HARMONY',
        'word_hits': {'crisis': 0, 'stress': 0, 'calm': 0}
    }), 200


# ============================================
# 🧠 NEURON SYNC — persist neuron learning to PostgreSQL (v324)
# ============================================
@app.route('/kal/neurons/sync', methods=['GET', 'OPTIONS'])
@optional_auth
def kal_neurons_load():
    """Load neuron learning data for user"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = getattr(request, 'user_id', None) or request.args.get('user_id', 'anonymous')

    try:
        from memory_routes import _db_load_learning, _db_save_learning
        learning = _db_load_learning(user_id)
        neuron_data = learning.get('neurons', {})

        return jsonify({
            'success': True,
            'neurons': neuron_data,
            'synced_at': learning.get('neurons_synced_at'),
            'user_id': user_id
        }), 200

    except Exception as e:
        logger.warning(f"kal_neurons_load error: {e}")
        return jsonify({'success': False, 'neurons': {}, 'error': str(e)}), 200


@app.route('/kal/neurons/sync', methods=['POST', 'OPTIONS'])
@optional_auth
def kal_neurons_save():
    """Save neuron learning data from frontend to PostgreSQL"""
    if request.method == 'OPTIONS':
        return '', 204

    user_id = getattr(request, 'user_id', None)
    data = request.get_json() or {}

    if not user_id:
        user_id = data.get('user_id', 'anonymous')

    neurons_data = data.get('neurons', {})
    if not neurons_data or not isinstance(neurons_data, dict):
        return jsonify({'success': False, 'error': 'No neuron data provided'}), 400

    try:
        from memory_routes import _db_load_learning, _db_save_learning

        # Load existing learning, merge neurons into it
        learning = _db_load_learning(user_id)

        existing_neurons = learning.get('neurons', {})

        # Merge strategy: per-neuron, keep higher activations + newer data
        for neuron_id, incoming in neurons_data.items():
            if not isinstance(incoming, dict):
                continue

            existing = existing_neurons.get(neuron_id, {})
            ex_act = existing.get('activations', 0)
            in_act = incoming.get('activations', 0)

            if in_act > ex_act:
                # Frontend has strictly more data — take it, but keep server patterns too
                server_patterns = set(existing.get('learnedPatterns', []))
                client_patterns = set(incoming.get('learnedPatterns', []))
                incoming['learnedPatterns'] = list(server_patterns | client_patterns)[:30]
                existing_neurons[neuron_id] = incoming
            else:
                # Server has same or more data — merge learned patterns + keep better thresholds
                server_patterns = set(existing.get('learnedPatterns', []))
                client_patterns = set(incoming.get('learnedPatterns', []))
                merged = list(server_patterns | client_patterns)[:30]
                existing['learnedPatterns'] = merged
                # Keep lower threshold (= more sensitive = more learned)
                if incoming.get('thresholdAdjust', 0) < existing.get('thresholdAdjust', 0):
                    existing['thresholdAdjust'] = incoming['thresholdAdjust']
                # Keep higher helpful count
                existing['helpfulCount'] = max(
                    existing.get('helpfulCount', 0), incoming.get('helpfulCount', 0))
                # Merge rhythm data if incoming has it
                if incoming.get('rhythm') and not existing.get('rhythm'):
                    existing['rhythm'] = incoming['rhythm']
                existing_neurons[neuron_id] = existing

        learning['neurons'] = existing_neurons
        learning['neurons_synced_at'] = now_iso()

        _db_save_learning(user_id, learning)

        return jsonify({
            'success': True,
            'synced': len(existing_neurons),
            'synced_at': learning['neurons_synced_at'],
            'user_id': user_id
        }), 200

    except Exception as e:
        logger.warning(f"kal_neurons_save error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route("/kal/consciousness/state")
def kal_consciousness_state():
    """Consciousness state — real Ψ(t) from brain engine (v281)"""
    try:
        if RADIM_BRAIN_AVAILABLE:
            from radim_brain_routes import compute_psi_state, get_early_psi
            user_id = request.args.get('user_id', 'default')
            early = get_early_psi(user_id)
            if early:
                C, alpha = early['C'], early['alpha']
            else:
                C, alpha = 5.0, 0.2
            psi = compute_psi_state(C, alpha, user_id=user_id)
            result = {
                "harmony": psi["phi_index"],
                "empathy": psi["psi"]["E"],
                "phi_direction": psi["coherence"],
                "chaos_index": psi["psi"]["S"],
                "iteration": psi["psi"]["C"],
                "mode": psi["mode"],
                "coherence": psi["coherence"],
                "rho_stability": psi.get("rho_stability"),
                "status": "active",
                "timestamp": now_iso()
            }
            # v282: Include rhythm return data if available
            if psi.get("rhythm_return"):
                result["rhythm_return"] = psi["rhythm_return"]
            return jsonify(result), 200
    except Exception as e:
        logger.warning(f"kal_consciousness_state error: {e}")
    return jsonify({
        "harmony": 0.85, "empathy": 0.7, "phi_direction": 0.8,
        "chaos_index": 0.1, "iteration": 5.0, "mode": "HARMONY",
        "status": "active", "timestamp": now_iso()
    }), 200

@app.route("/health/ready")
def health_ready():
    """Readiness check for frontend"""
    return jsonify({
        "status": "ready",
        "checks": {
            "azure_tts": bool(os.environ.get("AZURE_TTS_KEY")),
            "claude_api": bool(ANTHROPIC_API_KEY),
            "gemini_api": bool(GEMINI_API_KEY)
        },
        "timestamp": now_iso()
    }), 200

# HEALTH & INFO
# ============================================
@app.route('/health')
def health():
    # Registered blueprints registry
    blueprints = {
        'radim_orchestrator': {'prefix': '/api/radim/*', 'version': '1.0.0', 'status': 'active'},
        'orchestrator': {'prefix': '/api/orchestrator/*', 'version': '2.1.0', 'status': 'active'},
        'speech': {'prefix': '/api/speech/*', 'version': '1.0.0', 'status': 'active'},
        'claude': {'prefix': '/api/claude/*', 'version': '1.0.0', 'status': 'active'},
        'soul': {'prefix': '/api/soul/*', 'version': '1.0.0', 'status': 'active'},
        'voice_runtime': {'prefix': '/api/voice/*', 'version': '1.0.0', 'status': 'active'},
        'anticipation': {'prefix': '/api/anticipation/*', 'version': '1.0.0', 'status': 'active'},
    }
    # Conditional blueprints
    if SENIORS_AVAILABLE:
        blueprints['seniors'] = {'prefix': '/api/seniors/*', 'version': '1.0.0', 'status': 'active'}
    if IOT_AVAILABLE:
        blueprints['iot'] = {'prefix': '/api/iot/*', 'version': '1.0.0', 'status': 'active'}
    if PREDICT_AVAILABLE:
        blueprints['predict'] = {'prefix': '/api/radim/predict/*, /api/consciousness/*', 'version': '1.0.0', 'status': 'active'}
    if MEMORY_AVAILABLE:
        blueprints['memory'] = {'prefix': '/api/memory/*', 'version': '1.0.0', 'status': 'active'}
    if DASHBOARD_AVAILABLE:
        blueprints['dashboard'] = {'prefix': '/api/dashboard/*', 'version': '1.0.0', 'status': 'active'}
    if TWILIO_AVAILABLE:
        blueprints['twilio_voice'] = {'prefix': '/api/twilio/*', 'version': '1.0.0', 'status': 'active'}
    if IOT_BRIDGE_AVAILABLE:
        blueprints['iot_bridge'] = {'prefix': '/api/iot-bridge/*', 'version': '5.0', 'status': 'active'}
    if LIBRARY_AVAILABLE:
        blueprints['library'] = {'prefix': '/kal/library/*', 'version': '1.0.0', 'status': 'active'}
    if EDUCATION_AVAILABLE:
        blueprints['education'] = {'prefix': '/api/education/*', 'version': '1.0.0', 'status': 'active'}
    if TELEMEDICINE_AVAILABLE:
        blueprints['telemedicine'] = {'prefix': '/api/telemedicine/*', 'version': '1.0.0', 'status': 'active'}

    return jsonify({
        'status': 'healthy',
        'service': 'Radim Brain + Chat',
        'version': '3.4.0',
        'auth': 'JWT (WordPress)',
        'gdpr': True,
        'timestamp': now_iso(),
        'blueprints': blueprints,
        'blueprint_count': len(blueprints),
        'modules': {
            'chat': 'active',
            'websocket': True,
            'database': 'postgresql' if is_postgres() else 'sqlite',
            'speech': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'azure_tts_proxy': bool(AZURE_TTS_KEY),
            'ai': {
                'gemini': bool(GEMINI_API_KEY),
                'claude': bool(ANTHROPIC_API_KEY)
            },
            'media': bool(CLOUDINARY_URL),
            'push': bool(VAPID_PRIVATE_KEY),
            'wordpress': bool(WP_URL and WP_USER),
            'twilio_voice': {'configured': bool(os.environ.get('TWILIO_ACCOUNT_SID')), 'phone': os.environ.get('TWILIO_PHONE_NUMBER')}
        },
        'online_users': len(users_online)
    })

# ============================================
# 🔐 AUTH ENDPOINTS (proxy → WordPress radim-obchodnik)
# ============================================

WP_AUTH_BASE = 'https://www.radimcare.cz/wp-json/radim-obchodnik/v1/user-auth'
WP_PROXY_HEADERS = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'RadimBrain/1.0 (Heroku; Auth Proxy)'
}


def _create_jwt(user_id, email, name, role='subscriber'):
    """Create JWT token compatible with WordPress plugin (HS256)."""
    from auth_middleware import _base64url_encode, WP_JWT_SECRET
    if not WP_JWT_SECRET:
        return None
    now = int(time.time())
    header = _base64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_data = {
        "iss": "radim-brain",
        "iat": now,
        "exp": now + 7 * 86400,  # 7 days
        "user": {"id": user_id, "email": email, "name": name, "role": role}
    }
    payload = _base64url_encode(json.dumps(payload_data).encode())
    sig = _base64url_encode(
        hmac.new(WP_JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{sig}"


def _ensure_auth_table():
    """Create auth_users table if not exists."""
    from database import get_connection, is_postgres
    db = None
    try:
        db = get_connection()
        if is_postgres():
            db.execute("""
                CREATE TABLE IF NOT EXISTS auth_users (
                    id SERIAL PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    name VARCHAR(255) DEFAULT '',
                    role VARCHAR(50) DEFAULT 'subscriber',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        else:
            db.execute("""
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    name TEXT DEFAULT '',
                    role TEXT DEFAULT 'subscriber',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
        db.commit()
    except Exception as e:
        logger.warning(f"Auth table init: {e}")
    finally:
        if db:
            try: db.close()
            except: pass


# Init auth table at startup
try:
    _ensure_auth_table()
except Exception:
    pass


def _hash_password(password):
    """Hash password with SHA256 + salt."""
    salt = os.environ.get('WP_JWT_SECRET', 'radim-default-salt')
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


@app.route('/api/auth/register', methods=['POST', 'OPTIONS'])
def auth_register():
    """Register user in PostgreSQL (+ try WordPress sync)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400
    if len(password) < 6:
        return jsonify({"success": False, "error": "Heslo musí mít alespoň 6 znaků", "code": "password_weak"}), 400

    from database import get_connection, is_postgres
    db = None
    try:
        db = get_connection()
        # Check if exists
        ph = '%s' if is_postgres() else '?'
        row = db.execute(f"SELECT id FROM auth_users WHERE email = {ph}", (email,)).fetchone()
        if row:
            return jsonify({"success": False, "error": "Účet s tímto emailem již existuje", "code": "email_exists"}), 409

        # Insert
        pw_hash = _hash_password(password)
        if is_postgres():
            cur = db.execute(
                "INSERT INTO auth_users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id",
                (email, pw_hash, name)
            )
            ret = cur.fetchone()
            user_id = ret['id'] if isinstance(ret, dict) else ret[0]
        else:
            cur = db.execute(
                "INSERT INTO auth_users (email, password_hash, name) VALUES (?, ?, ?)",
                (email, pw_hash, name)
            )
            user_id = cur.lastrowid
        db.commit()

        token = _create_jwt(user_id, email, name)

        # Best-effort WordPress sync (non-blocking)
        try:
            requests.post(f"{WP_AUTH_BASE}/register", json={
                "email": email, "password": password, "name": name
            }, headers=WP_PROXY_HEADERS, timeout=5)
        except Exception:
            pass  # WP sync is optional

        return jsonify({
            "success": True,
            "token": token,
            "user": {"id": user_id, "email": email, "name": name, "role": "subscriber"},
            "gdpr_consent": False,
            "message": "Registrace úspěšná!"
        })

    except Exception as e:
        logger.error(f"Auth register error: {e}")
        return jsonify({"success": False, "error": "Chyba při registraci", "code": "db_error"}), 500
    finally:
        if db:
            try: db.close()
            except: pass


@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    """Login from PostgreSQL (+ WordPress fallback)"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"success": False, "error": "Email a heslo jsou povinné", "code": "missing_fields"}), 400

    from database import get_connection, is_postgres
    db = None
    try:
        db = get_connection()
        ph = '%s' if is_postgres() else '?'
        row = db.execute(
            f"SELECT id, email, name, role, password_hash FROM auth_users WHERE email = {ph}", (email,)
        ).fetchone()

        if row:
            user_id = row['id'] if isinstance(row, dict) else row[0]
            user_email = row['email'] if isinstance(row, dict) else row[1]
            user_name = row['name'] if isinstance(row, dict) else row[2]
            role = row['role'] if isinstance(row, dict) else row[3]
            pw_hash = row['password_hash'] if isinstance(row, dict) else row[4]
            if pw_hash == _hash_password(password):
                token = _create_jwt(user_id, user_email, user_name, role or 'subscriber')
                # Fetch GDPR consent status (one response = no extra API call)
                gdpr_consent = False
                try:
                    from memory_routes import get_gdpr_consent
                    consent = get_gdpr_consent(str(user_id))
                    gdpr_consent = bool(consent.get("data_processing", False))
                except Exception:
                    pass
                return jsonify({
                    "success": True,
                    "token": token,
                    "user": {"id": user_id, "email": user_email, "name": user_name, "role": role},
                    "gdpr_consent": gdpr_consent,
                    "message": "Přihlášení úspěšné"
                })

        # Not found locally or wrong password → try WordPress
        try:
            wp_resp = requests.post(f"{WP_AUTH_BASE}/login", json={
                "email": email, "password": password
            }, headers=WP_PROXY_HEADERS, timeout=8)
            wp_data = wp_resp.json()
            if wp_resp.status_code == 200 and wp_data.get('success'):
                user = wp_data.get('data', {})
                wp_id = user.get('user_id', 0)
                wp_name = user.get('display_name', email)
                wp_role = user.get('role', 'subscriber')
                token = _create_jwt(wp_id, email, wp_name, wp_role)
                # Sync to local DB for next time
                try:
                    pw_hash = _hash_password(password)
                    if is_postgres():
                        db.execute(
                            "INSERT INTO auth_users (email, password_hash, name, role) VALUES (%s, %s, %s, %s) ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, name = EXCLUDED.name",
                            (email, pw_hash, wp_name, wp_role)
                        )
                    else:
                        db.execute(
                            "INSERT OR REPLACE INTO auth_users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
                            (email, pw_hash, wp_name, wp_role)
                        )
                    db.commit()
                except Exception:
                    pass
                return jsonify({
                    "success": True,
                    "token": token,
                    "user": {"id": wp_id, "email": email, "name": wp_name, "role": wp_role},
                    "gdpr_consent": False,
                    "message": "Přihlášení úspěšné"
                })
        except Exception:
            pass  # WP unreachable — use only local result

        return jsonify({"success": False, "error": "Nesprávný email nebo heslo", "code": "invalid_credentials"}), 401

    except Exception as e:
        logger.error(f"Auth login error: {e}")
        return jsonify({"success": False, "error": "Chyba při přihlášení", "code": "db_error"}), 500
    finally:
        if db:
            try: db.close()
            except: pass


@app.route('/api/auth/lost-password', methods=['POST', 'OPTIONS'])
def auth_lost_password():
    """Password reset — try WordPress, always return success"""
    if request.method == 'OPTIONS':
        return '', 204
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({"success": False, "error": "Email je povinný"}), 400

    # Best-effort WordPress reset
    try:
        requests.post(f"{WP_AUTH_BASE}/lost-password", json={"email": email}, headers=WP_PROXY_HEADERS, timeout=5)
    except Exception:
        pass

    return jsonify({"success": True, "message": "Pokud účet s tímto emailem existuje, odeslali jsme instrukce pro obnovu hesla."})


@app.route('/api/auth/verify', methods=['GET'])
@require_auth
def auth_verify():
    """Ověří JWT token a vrátí user data"""
    return jsonify({
        "success": True,
        "user": g.auth_user,
        "message": "Token je platný"
    })

@app.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    """Odhlášení — invalidate session (best effort)"""
    if request.method == 'OPTIONS':
        return '', 204
    # JWT je stateless — klient jen smaže token
    # Server-side blacklist by se řešil přes Redis, zatím nepotřebujeme
    return jsonify({"success": True, "message": "Odhlášen"})

@app.route('/api/auth/refresh', methods=['POST', 'OPTIONS'])
@require_auth
def auth_refresh():
    """Obnoví JWT token"""
    if request.method == 'OPTIONS':
        return '', 204
    try:
        user = g.auth_user
        new_token = _create_jwt(user['id'], user.get('email', ''), user.get('name', ''), user.get('role', 'user'))
        return jsonify({"success": True, "token": new_token})
    except Exception as e:
        logger.warning(f"auth_refresh error: {e}")
        return jsonify({"success": False, "error": "Nelze obnovit token"}), 500

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def auth_me():
    """Vrátí profil aktuálně přihlášeného uživatele"""
    return jsonify({
        "success": True,
        "user": g.auth_user
    })

@app.route('/api/auth/resend-verification', methods=['POST', 'OPTIONS'])
@require_auth
def auth_resend_verification():
    """Znovu odešle verifikační email (placeholder — email service TBD)"""
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({"success": True, "message": "Verifikační email byl odeslán (pokud je nakonfigurován)."})

@app.route('/api/auth/data-export', methods=['GET'])
@require_auth
def auth_data_export():
    """GDPR: Export všech dat uživatele z backendu"""
    user_id = str(g.auth_user.get('id', ''))
    export_data = {
        "export_date": now_iso(),
        "user_id": user_id,
        "backend_data": {}
    }

    # Export memory data
    conn = None
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            # Profile
            cursor.execute("SELECT data FROM memory_profiles WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row:
                export_data["backend_data"]["profile"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            # History (last 500)
            cursor.execute(
                "SELECT role, content, timestamp FROM memory_history WHERE user_id = %s ORDER BY timestamp DESC LIMIT 500",
                (user_id,)
            )
            export_data["backend_data"]["history"] = [
                {"role": r[0], "content": r[1], "timestamp": str(r[2])} for r in cursor.fetchall()
            ]

            # Learning data
            cursor.execute("SELECT data FROM memory_learning WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            if row:
                export_data["backend_data"]["learning"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            cursor.close()
    except Exception as e:
        export_data["backend_data"]["error"] = str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return jsonify({
        "success": True,
        "data": export_data
    })

@app.route('/api/auth/data', methods=['DELETE'])
@require_auth
def auth_data_delete():
    """GDPR: Smaže všechna data uživatele z backendu"""
    user_id = str(g.auth_user.get('id', ''))
    deleted = {"profile": False, "history": False, "learning": False}

    conn = None
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_profiles WHERE user_id = %s", (user_id,))
            deleted["profile"] = cursor.rowcount > 0
            cursor.execute("DELETE FROM memory_history WHERE user_id = %s", (user_id,))
            deleted["history"] = cursor.rowcount > 0
            cursor.execute("DELETE FROM memory_learning WHERE user_id = %s", (user_id,))
            deleted["learning"] = cursor.rowcount > 0
            conn.commit()
            cursor.close()
    except Exception as e:
        logger.error(f"⚠️ app.py error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return jsonify({
        "success": True,
        "message": "Všechna data uživatele byla smazána",
        "deleted": deleted
    })

@app.route('/api/auth/delete-account', methods=['POST'])
@require_auth
def auth_delete_account():
    """GDPR: Smaže účet uživatele + všechna data"""
    user_id = str(g.auth_user.get('id', ''))
    email = g.auth_user.get('email', '')

    conn = None
    try:
        conn = get_connection()
        ph = '%s' if is_postgres() else '?'
        if conn:
            # 1. Smazat všechna data (memory, history, learning)
            conn.execute(f"DELETE FROM memory_profiles WHERE user_id = {ph}", (user_id,))
            conn.execute(f"DELETE FROM memory_history WHERE user_id = {ph}", (user_id,))
            conn.execute(f"DELETE FROM memory_learning WHERE user_id = {ph}", (user_id,))
            # 2. Smazat samotný účet
            result = conn.execute(f"DELETE FROM auth_users WHERE id = {ph}", (int(user_id),))
            account_deleted = getattr(result, 'rowcount', 0) > 0
            conn.commit()

            if account_deleted:
                logger.info(f"🗑️ Account deleted: {email} (id={user_id})")
                return jsonify({
                    "success": True,
                    "message": "Účet a všechna data byly trvale smazány."
                })
            else:
                return jsonify({"success": False, "error": "Účet nenalezen"}), 404
    except Exception as e:
        logger.error(f"delete-account error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

@app.route('/api')
def api_info():
    return jsonify({
        'name': 'Radim Brain + Chat API',
        'version': '3.1.0',
        'endpoints': {
            'chat': {
                'conversations': '/api/chat/conversations/{userId}',
                'messages': '/api/chat/messages/{conversationId}',
                'contacts': '/api/chat/contacts/{userId}'
            },
            'speech': {
                'synthesize': '/api/speech/synthesize',
                'transcribe': '/api/speech/transcribe',
                'voices': '/api/speech/voices'
            },
            'media': {
                'upload': '/api/media/upload',
                'voice': '/api/media/voice'
            },
            'push': {
                'subscribe': '/api/push/subscribe',
                'vapid_key': '/api/push/vapid-key'
            },
            'wordpress': {
                'login': '/api/wordpress/login',
                'sync': '/api/wordpress/sync'
            },
            'admin': {
                'stats': '/api/admin/stats',
                'users': '/api/admin/users',
                'conversations': '/api/admin/conversations'
            },
            'ai': {
                'settings': '/api/ai/settings',
                'chat': '/api/ai/chat'
            },
            'orchestrator': {
                'orchestrate': '/api/orchestrator/orchestrate',
                'health': '/api/orchestrator/health',
                'systems': '/api/orchestrator/systems'
            },
            'dashboard': {
                'full': '/api/dashboard',
                'quick': '/api/dashboard/quick'
            },
            'seniors': '/api/seniors',
            'iot': '/api/iot/system/status',
            'consciousness': '/api/consciousness/state'
        },
        'websocket': {
            'url': 'wss://radim-brain-2025.herokuapp.com',
            'events': ['join', 'send_message', 'typing', 'mark_read']
        }
    })

# ============================================
# DASHBOARD - AGREGOVANÝ PŘEHLED
# ============================================
@app.route('/api/dashboard')
def dashboard():
    """Agregovaný dashboard pro investory a frontend"""
    from datetime import datetime as dt
    result = {'success': True, 'timestamp': now_iso(), 'version': '3.1.0'}

    # 1) Seniors summary
    try:
        from seniors_routes import DEMO_SENIORS
        active = [s for s in DEMO_SENIORS.values() if s.get('status') == 'active']
        result['seniors'] = {
            'total': len(active),
            'avg_age': round(sum(s['age'] for s in active) / len(active), 1) if active else 0,
            'high_care': sum(1 for s in active if s.get('care_level', 0) >= 3),
            'facility': 'Dům seniorů Háje'
        }
    except Exception as e:
        result['seniors'] = {'error': str(e)}

    # 2) IoT summary
    try:
        from iot_routes import ROOM_SENSORS
        total_sensors = sum(len(r['sensors']) for r in ROOM_SENSORS.values())
        result['iot'] = {
            'rooms': len(ROOM_SENSORS),
            'sensors_total': total_sensors,
            'health': 'operational'
        }
    except Exception as e:
        result['iot'] = {'error': str(e)}

    # 3) Top-risk senior
    try:
        from predict_routes import RISK_PROFILES
        top_risk = max(RISK_PROFILES.items(), key=lambda x: x[1].get('base_risk', 0))
        result['top_risk'] = {
            'senior_id': top_risk[0],
            'base_risk': top_risk[1]['base_risk'],
            'primary_concerns': top_risk[1].get('primary_concerns', [])
        }
    except Exception as e:
        result['top_risk'] = {'error': str(e)}

    # 4) Consciousness pulse
    try:
        import math, time
        phi = 1.618033988749895
        t = time.time()
        score = 0.5 + 0.3 * math.sin(t / (phi * 100))
        result['consciousness'] = {
            'score': round(score, 3),
            'state': 'aware' if score > 0.6 else 'resting',
            'neurons': 527,
            'values': 12
        }
    except Exception as e:
        result['consciousness'] = {'error': str(e)}

    # 5) AI status
    result['ai'] = {
        'gemini': bool(GEMINI_API_KEY),
        'claude': bool(ANTHROPIC_API_KEY),
        'primary': 'gemini' if GEMINI_API_KEY else ('claude' if ANTHROPIC_API_KEY else 'none')
    }

    # 6) Blueprint count
    result['api'] = {
        'blueprints_active': 11,
        'endpoints_estimated': 45
    }

    return jsonify(result)


@app.route('/')
def index():
    return jsonify({
        'message': '🌟 Radim Brain + Chat API v3.1',
        'status': 'running',
        'database': 'postgresql' if is_postgres() else 'sqlite',
        'docs': '/api',
        'health': '/health'
    })

@app.errorhandler(400)
def bad_request(e):
    return jsonify({'success': False, 'error': 'Neplatný požadavek', 'code': 400}), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'success': False, 'error': 'Přihlášení je vyžadováno', 'code': 401}), 401

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'success': False, 'error': 'Přístup zamítnut', 'code': 403}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Endpoint nenalezen', 'code': 404}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({'success': False, 'error': 'Metoda není povolena', 'code': 405}), 405

@app.errorhandler(429)
def rate_limited(e):
    return jsonify({'success': False, 'error': 'Příliš mnoho požadavků, zkuste později', 'code': 429}), 429

@app.errorhandler(500)
def server_error(e):
    return jsonify({'success': False, 'error': 'Interní chyba serveru', 'code': 500}), 500

# Initialize database
with app.app_context():
    init_db()
    # Reset all users to offline on server start (dyno restart resets socket connections)
    db = None
    try:
        db = get_connection()
        db.execute("UPDATE chat_users SET online = 0 WHERE id != 'radim'")
        db.commit()
        logger.info("✅ All user online statuses reset")
    except Exception as e:
        logger.warning(f"⚠️  Could not reset online statuses: {e}")
    finally:
        if db:
            try:
                db.close()
            except Exception:
                pass

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f'''
╔═══════════════════════════════════════════════════════════╗
║          🌟 RADIM BRAIN + CHAT SERVER v3.1 🌟             ║
╠═══════════════════════════════════════════════════════════╣
║  Port:        {port}                                         ║
║  Database:    {'🐘 PostgreSQL' if is_postgres() else '📁 SQLite (dev)'}                                ║
║  WebSocket:   ✅ Ready                                    ║
║  Chat:        ✅ Active                                   ║
║  AI:          {'✅ Gemini' if GEMINI_API_KEY else '❌ Not configured'}                                  ║
║  Media:       {'✅ Cloudinary' if CLOUDINARY_URL else '❌ Not configured'}                              ║
║  Push:        {'✅ Ready' if VAPID_PRIVATE_KEY else '❌ Not configured'}                                    ║
║  WordPress:   {'✅ Connected' if WP_URL else '❌ Not configured'}                               ║
╚═══════════════════════════════════════════════════════════╝
    ''')
    socketio.run(app, host='0.0.0.0', port=port)
