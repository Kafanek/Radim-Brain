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
from flask_socketio import SocketIO
from dotenv import load_dotenv
from database import get_db_for_flask, close_db_for_flask, get_connection
from utils import generate_id, now_iso, today_date
from database import init_db as db_init_db, is_postgres, db_context
from auth_middleware import require_auth, require_premium, optional_auth, decode_jwt
from rate_limiter import rate_limit

load_dotenv()

# Import Radim WhatsApp Orchestrator + Service routes
from radim_orchestrator import radim_bp
from radim_service_routes import radim_service_bp

# 🎭 Import Orchestrator Blueprint
from orchestrator_blueprint import orchestrator_bp

# Import Memory & Learning routes
try:
    from memory_routes import memory_bp
    from gdpr_routes import gdpr_bp
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
    from education_assessment_routes import education_assessment_bp
    from education_scenario_routes import education_scenario_bp
    EDUCATION_AVAILABLE = True
except ImportError:
    EDUCATION_AVAILABLE = False
    logger.warning("⚠️ Education routes not available")

# 🏫 Import Education Teacher Dashboard
try:
    from education_teacher_routes import education_teacher_bp
    from education_task_routes import education_task_bp
    EDUCATION_TEACHER_AVAILABLE = True
except ImportError:
    EDUCATION_TEACHER_AVAILABLE = False
    logger.warning("⚠️ Education teacher routes not available")

# 🏥 Import Telemedicine Routes
try:
    from telemedicine_routes import telemedicine_bp, get_upcoming_consultations_for_reminder
    from telemedicine_teacher_routes import telemedicine_teacher_bp
    from telemedicine_multiparty_routes import telemedicine_multiparty_bp
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

# Register Radim Blueprints
app.register_blueprint(radim_bp)
app.register_blueprint(radim_service_bp)

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
    logger.info("✅ Dashboard routes registered: /api/dashboard/*, /api/dashboard/v2/*")

# 📚 Register Library Blueprint
if LIBRARY_AVAILABLE:
    app.register_blueprint(library_bp)
    logger.info("✅ Library routes registered: /kal/library/*")

# 🎓 Register Education Blueprint
if EDUCATION_AVAILABLE:
    app.register_blueprint(education_bp)
    app.register_blueprint(education_assessment_bp)
    app.register_blueprint(education_scenario_bp)
    logger.info("✅ Education routes registered: /api/education/* (3 blueprints)")

# 🏫 Register Education Teacher Dashboard Blueprint
if EDUCATION_TEACHER_AVAILABLE:
    app.register_blueprint(education_teacher_bp)
    app.register_blueprint(education_task_bp)
    logger.info("✅ Education teacher + task routes registered: /api/education/teacher-dashboard/*, /api/education/my-tasks/*")

# 🏥 Register Telemedicine Blueprints
if TELEMEDICINE_AVAILABLE:
    app.register_blueprint(telemedicine_bp)
    app.register_blueprint(telemedicine_teacher_bp)
    app.register_blueprint(telemedicine_multiparty_bp)
    logger.info("✅ Telemedicine routes registered: /api/telemedicine/* (student + teacher + multiparty)")

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
from claude_content_routes import claude_content_bp
from claude_emotion_routes import claude_emotion_bp
app.register_blueprint(claude_bp)
app.register_blueprint(claude_content_bp)
app.register_blueprint(claude_emotion_bp)
logger.info("✅ Claude AI routes registered: /api/claude/* (core + content + emotion)")

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
    from iot_dashboard_routes import iot_dashboard_bp
    app.register_blueprint(iot_bridge_bp)
    app.register_blueprint(iot_dashboard_bp)
    IOT_BRIDGE_AVAILABLE = True
    logger.info("🔌 IoT Bridge registered: /api/iot-bridge/* (2 blueprints)")
except ImportError:
    IOT_BRIDGE_AVAILABLE = False
    logger.warning("⚠️ IoT Bridge routes not available")

# 🧠 Import Memory & Learning routes
if MEMORY_AVAILABLE:
    app.register_blueprint(memory_bp)
    app.register_blueprint(gdpr_bp)
    logger.info("✅ Memory routes registered: /api/memory/*")
    logger.info("✅ GDPR routes registered: /api/memory/gdpr/*")

# KAL Routes (Kolibri Abstraction Layer)
from kal_routes import kal_bp, init_kal_routes
init_kal_routes(memory_available=MEMORY_AVAILABLE, radim_brain_available=RADIM_BRAIN_AVAILABLE)
app.register_blueprint(kal_bp)
logger.info("KAL routes registered: /kal/*")

# Chat Routes (Conversations, Messages, Contacts)
from chat_routes import chat_bp
app.register_blueprint(chat_bp)
logger.info("✅ Chat routes registered: /api/chat/*")

# Auth Routes (Registration, Login, JWT, GDPR)
from auth_routes import auth_bp
app.register_blueprint(auth_bp)
logger.info("✅ Auth routes registered: /api/auth/*")

# TTS Proxy Routes (Azure + ElevenLabs)
from tts_proxy_routes import tts_proxy_bp, init_tts_proxy_routes
init_tts_proxy_routes(
    ant_available=_APP_ANT_AVAILABLE,
    predict_C=_app_predict_C if _APP_ANT_AVAILABLE else None,
    emotions=_app_ant_emotions if _APP_ANT_AVAILABLE else None,
    speech=_app_ant_speech if _APP_ANT_AVAILABLE else None,
    classify=_app_classify if _APP_ANT_AVAILABLE else None,
    brain_available=_APP_BRAIN_AVAILABLE,
    brain_speech=_app_brain_speech if _APP_BRAIN_AVAILABLE else None,
)
app.register_blueprint(tts_proxy_bp)
logger.info("✅ TTS Proxy routes registered: /api/azure/tts, /api/elevenlabs/tts")

# Media & Push + Admin routes registered after helper functions are defined (see below)

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
    # Proactive agent loop — autonomous senior monitoring
    try:
        from agent_loop import run_agent_cycle
        scheduler.add_job(lambda: run_agent_cycle(app), 'interval', minutes=5,
                          id='agent_loop', max_instances=1, misfire_grace_time=120)
        logger.info("✅ Agent loop registered (every 5 min)")
    except ImportError:
        logger.warning("⚠️ agent_loop not available — proactive agent disabled")

    # v390: Morning check-in — call seniors with medication reminders at 8:00 AM
    try:
        from agent_loop import run_morning_checkin
        scheduler.add_job(lambda: run_morning_checkin(app), 'cron', hour=8, minute=0,
                          id='morning_checkin', max_instances=1, misfire_grace_time=600)
        logger.info("✅ Morning check-in registered (daily at 8:00)")
    except ImportError:
        logger.warning("⚠️ morning check-in not available")

    # Daily cleanup — old observations + brain_states
    try:
        from agent_loop import run_daily_cleanup
        scheduler.add_job(lambda: run_daily_cleanup(app), 'cron', hour=3, minute=0,
                          id='daily_cleanup', max_instances=1, misfire_grace_time=3600)
        logger.info("✅ Daily cleanup registered (3:00 AM)")
    except ImportError:
        logger.warning("⚠️ daily cleanup not available")

    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("✅ APScheduler started: 5 jobs (reminders + telemed + agent + morning + cleanup)")

except ImportError:
    logger.warning("⚠️ APScheduler not installed — reminders will not auto-send")
except Exception as sched_err:
    logger.error(f"⚠️ Scheduler init error: {sched_err}")

AZURE_TTS_KEY = os.environ.get('AZURE_TTS_KEY')
AZURE_TTS_REGION = os.environ.get('AZURE_TTS_REGION', 'eastus')

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
# RADIM AI — imported from ai_bridge.py
# ============================================
from ai_bridge import call_gemini_ai, call_claude_ai, get_ai_response

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

# Make send_push available to agent_loop via app.config
app.config['SEND_PUSH_FN'] = send_push_notification

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
# REGISTER BLUEPRINTS THAT DEPEND ON HELPER FUNCTIONS
# (must be after upload_to_cloudinary, send_push_notification etc.)
# ============================================

# Media & Push Notification Routes
from media_push_routes import media_push_bp, init_media_push_routes
init_media_push_routes(
    upload_to_cloudinary=upload_to_cloudinary,
    send_push_notification=send_push_notification,
)
app.register_blueprint(media_push_bp)
logger.info("✅ Media & Push routes registered: /api/media/*, /api/push/*")

# Admin, WordPress, AI Settings, Stubs, Client/Emergency Routes
from admin_routes import admin_bp
app.register_blueprint(admin_bp)
logger.info("✅ Admin routes registered: /api/admin/*, /api/ai/*, /api/wordpress/*")

# update_daily_stats — re-export for backward compat (now in admin_routes.py)
from admin_routes import update_daily_stats

# ============================================
# SOCKET.IO EVENTS — imported from socketio_handlers.py
# ============================================
from socketio_handlers import register_socketio_handlers
register_socketio_handlers(socketio, users_online, _cleanup_users_online)


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
        blueprints['dashboard'] = {'prefix': '/api/dashboard/*, /api/dashboard/v2/*', 'version': '4.0.0', 'status': 'active'}
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

    # v382: Real DB connectivity check
    db_ok = False
    db_latency_ms = None
    try:
        import time as _t
        _t0 = _t.time()
        with db_context() as db:
            db.execute("SELECT 1").fetchone()
        db_latency_ms = round((_t.time() - _t0) * 1000, 1)
        db_ok = True
    except Exception as e:
        logger.error(f"Health check DB fail: {e}")

    status_code = 200 if db_ok else 503

    return jsonify({
        'status': 'healthy' if db_ok else 'degraded',
        'service': 'Radim Brain + Chat',
        'version': '3.5.0',
        'auth': 'JWT (WordPress)',
        'gdpr': True,
        'timestamp': now_iso(),
        'blueprints': blueprints,
        'blueprint_count': len(blueprints),
        'db': {
            'type': 'postgresql' if is_postgres() else 'sqlite',
            'connected': db_ok,
            'latency_ms': db_latency_ms
        },
        'modules': {
            'chat': 'active',
            'websocket': True,
            'speech': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'azure_tts_proxy': bool(AZURE_TTS_KEY),
            'ai': {
                'gemini': bool(GEMINI_API_KEY),
                'claude': bool(ANTHROPIC_API_KEY)
            },
            'media': bool(CLOUDINARY_URL),
            'push': bool(VAPID_PRIVATE_KEY),
            'wordpress': bool(WP_URL and WP_USER),
            'twilio_voice': {'configured': bool(os.environ.get('TWILIO_ACCOUNT_SID')), 'phone': os.environ.get('TWILIO_PHONE_NUMBER')},
            'agent_loop': True
        },
        'online_users': len(users_online)
    }), status_code

# v384: Admin auth guard
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

def _check_admin():
    """Check admin auth via X-Admin-Secret header or ?secret= param."""
    if not ADMIN_SECRET:
        return True  # dev mode — no secret configured
    token = request.headers.get('X-Admin-Secret') or request.args.get('secret')
    return token == ADMIN_SECRET

# v383: Admin IoT simulator
@app.route('/api/admin/iot-simulate', methods=['POST'])
def admin_iot_simulate():
    """Seed IoT devices + 7 days of sensor data for demo_senior_1."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from iot_simulator import run_full_iot_seed
        result = run_full_iot_seed()
        return jsonify({'success': True, **result}), 201
    except Exception as e:
        logger.error(f"IoT simulate error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# v383: Debug personalized prompt (check if agent observations appear)
@app.route('/api/admin/debug-prompt/<user_id>')
def admin_debug_prompt(user_id):
    """Show the personalized system prompt for a user."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from memory_logic import build_personalized_prompt
        prompt = build_personalized_prompt(user_id)
        return jsonify({'user_id': user_id, 'prompt_length': len(prompt), 'prompt': prompt}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# v382: Admin seed demo data
@app.route('/api/admin/seed-demo', methods=['POST'])
def admin_seed_demo():
    """Create demo senior with 7 days of brain_states for agent loop testing."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from seed_demo import seed_demo_data
        result = seed_demo_data()
        return jsonify({'success': True, **result}), 201
    except Exception as e:
        logger.error(f"Seed demo error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# v382: Manual agent loop trigger (full cycle with saves)
@app.route('/api/admin/agent-run', methods=['POST'])
def admin_agent_run():
    """Manually trigger one full agent loop cycle."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from agent_loop import run_agent_cycle
        run_agent_cycle(app)
        # Return observations created in last 5 min
        with db_context() as db:
            if is_postgres():
                rows = db.execute(
                    "SELECT user_id, observation_type, severity, message, action_taken, created_at "
                    "FROM agent_observations WHERE created_at > NOW() - INTERVAL '5 minutes' "
                    "ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT user_id, observation_type, severity, message, action_taken, created_at "
                    "FROM agent_observations WHERE created_at > datetime('now', '-5 minutes') "
                    "ORDER BY created_at DESC"
                ).fetchall()
        obs = [dict(r) for r in rows]
        return jsonify({'success': True, 'observations_created': len(obs), 'observations': obs}), 200
    except Exception as e:
        logger.error(f"Agent run error: {e}")
        return jsonify({'error': str(e)}), 500

# Auth routes — now in auth_routes.py blueprint

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
