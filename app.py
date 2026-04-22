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

# 📺 Import TV Proxy Blueprint
try:
    from tv_proxy_routes import tv_proxy_bp
    TV_PROXY_AVAILABLE = True
except ImportError:
    TV_PROXY_AVAILABLE = False

# 👨‍👩‍👧 Import Family Routes
try:
    from family_routes import family_bp
    FAMILY_AVAILABLE = True
except ImportError:
    FAMILY_AVAILABLE = False

# 🌉 Import Agent Bridge (reactive↔proactive + live risk)
try:
    from agent_bridge import agent_bridge_bp
    AGENT_BRIDGE_AVAILABLE = True
except ImportError:
    AGENT_BRIDGE_AVAILABLE = False

# 📰 Import News Routes
try:
    from news_routes import news_bp as news_api_bp
    NEWS_API_AVAILABLE = True
except ImportError:
    NEWS_API_AVAILABLE = False

# 🎵 Import Rhythm Multi-Agent Routes
try:
    from rhythm_routes import rhythm_bp
    RHYTHM_AVAILABLE = True
except ImportError:
    RHYTHM_AVAILABLE = False

# 🤖 Import Health Agent
try:
    from radim_health_agent import health_agent_bp
    HEALTH_AGENT_AVAILABLE = True
except ImportError:
    HEALTH_AGENT_AVAILABLE = False

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

# v10.12: Gzip compression — reduces JSON/HTML transfer by ~60%
try:
    from flask_compress import Compress
    Compress(app)
    logger.info("✅ Gzip compression enabled (flask-compress)")
except ImportError:
    logger.debug("flask-compress not installed — no compression")

# Register Radim Blueprints
app.register_blueprint(radim_bp)
app.register_blueprint(radim_service_bp)

# 🎭 Register Orchestrator Blueprint
app.register_blueprint(orchestrator_bp)

# 📺 Register TV Proxy Blueprint
if TV_PROXY_AVAILABLE:
    app.register_blueprint(tv_proxy_bp)
    logger.info("✅ TV proxy registered: /api/tv/*")

# 👨‍👩‍👧 Register Family Routes
if FAMILY_AVAILABLE:
    app.register_blueprint(family_bp)
    logger.info("✅ Family routes registered: /api/family/*")

# 📅 Register Calendar Routes
try:
    from calendar_routes import calendar_bp
    app.register_blueprint(calendar_bp)
    logger.info("✅ Calendar routes registered: /api/calendar/*")
except ImportError as e:
    logger.warning(f"⚠️ Calendar routes not available: {e}")

# 🌉 Register Agent Bridge
if AGENT_BRIDGE_AVAILABLE:
    app.register_blueprint(agent_bridge_bp)
    logger.info("✅ Agent Bridge registered: /api/bridge/*")

# 📰 Register News API
if NEWS_API_AVAILABLE:
    app.register_blueprint(news_api_bp)
    logger.info("✅ News API registered: /api/news/*")

# 🎵 Register Rhythm Multi-Agent API
if RHYTHM_AVAILABLE:
    app.register_blueprint(rhythm_bp)
    logger.info("✅ Rhythm Multi-Agent registered: /api/rhythm/*")

# 🤖 Register Health Agent
if HEALTH_AGENT_AVAILABLE:
    app.register_blueprint(health_agent_bp)
    logger.info("✅ Health Agent registered: /api/agent/*")
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
    "https://brain.radimcare.cz",
    "https://radimcare-app.pages.dev",
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
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]

IS_PRODUCTION = os.environ.get('DYNO') is not None  # Heroku sets DYNO
# v10.9: Only include dev origins in non-production
if IS_PRODUCTION:
    ALLOWED_ORIGINS = PRODUCTION_ORIGINS
    logger.info(f"CORS: production mode — {len(PRODUCTION_ORIGINS)} origins")
else:
    ALLOWED_ORIGINS = PRODUCTION_ORIGINS + DEV_ORIGINS
    logger.info(f"CORS: dev mode — {len(PRODUCTION_ORIGINS) + len(DEV_ORIGINS)} origins")

CORS(app,
     resources={r"/*": {"origins": ALLOWED_ORIGINS}},
     supports_credentials=False,
     allow_headers=["Content-Type", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])

# ═══════════════════════════════════════
# v10.9: SECURITY HEADERS — production hardening
# ═══════════════════════════════════════
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # /api/browser/proxy must be iframe-embeddable — the route sets its own
    # frame policy (ALLOWALL + frame-ancestors *). Don't override it here.
    if not request.path.startswith('/api/browser/proxy'):
        response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


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

# 💓 RTCF — Radim Temporal Coherence Framework (the heartbeat)
try:
    from rtcf_bridge import ENABLE_RTCF
    RTCF_AVAILABLE = True
    logger.info(f"💓 RTCF available (enabled={ENABLE_RTCF})")
except ImportError:
    RTCF_AVAILABLE = False
    ENABLE_RTCF = False

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

# Sprint L — AI assist endpoints (suggest_replies, translate, summarize, extract_event)
try:
    from ai_assist_routes import ai_assist_bp
    app.register_blueprint(ai_assist_bp)
    logger.info("✅ AI assist routes registered: /api/ai/assist")
except Exception as _e:
    logger.warning(f"⚠ ai_assist_routes not loaded: {_e}")

# Survey Routes (Dotazníky za odměnu)
try:
    from survey_routes import survey_bp
    app.register_blueprint(survey_bp)
    logger.info("✅ Survey routes registered: /api/surveys/*")
    # Init survey DB tables
    with app.app_context():
        from database import db_context
        from database_schema import init_survey_schema
        with db_context(commit=True) as db:
            init_survey_schema(db)
except Exception as e:
    logger.warning(f"⚠️ Survey routes: {e}")

# Medical Team Routes (Shared care coordination)
try:
    from medical_team import medical_bp
    app.register_blueprint(medical_bp)
    logger.info("✅ Medical Team routes registered: /api/medical/*")
except Exception as e:
    logger.warning(f"⚠️ Medical Team routes: {e}")

try:
    from home_assistant import ha_bp
    app.register_blueprint(ha_bp)
    logger.info("✅ Home Assistant routes registered: /api/ha/*")
except Exception as e:
    logger.warning(f"⚠️ Home Assistant routes: {e}")

try:
    from predictive_agent import prediction_bp
    app.register_blueprint(prediction_bp)
    logger.info("✅ Predictive Agent routes registered: /api/predict/*")
except Exception as e:
    logger.warning(f"⚠️ Predictive Agent routes: {e}")

try:
    from advanced_agents import agents_bp
    app.register_blueprint(agents_bp)
    logger.info("✅ Advanced Agents routes registered: /api/agents/*")
except Exception as e:
    logger.warning(f"⚠️ Advanced Agents routes: {e}")

try:
    from survey_engine import survey_engine_bp
    app.register_blueprint(survey_engine_bp)
    from survey_telemetry import telemetry_bp as survey_telemetry_bp
    app.register_blueprint(survey_telemetry_bp)
    logger.info("✅ Survey Engine + Telemetry routes registered")
except Exception as e:
    logger.warning(f"⚠️ Survey Engine/Telemetry: {e}")

try:
    from scenario_engine import scenario_bp
    app.register_blueprint(scenario_bp)
    from anticipation_engine import anticipation_bp
    app.register_blueprint(anticipation_bp)
    from circadian_engine import circadian_bp
    app.register_blueprint(circadian_bp)
    from personal_growth import growth_bp
    app.register_blueprint(growth_bp)
    from skill_map import skill_bp
    app.register_blueprint(skill_bp)
    logger.info("✅ Scenario + Anticipation + Circadian + Growth + SkillMap routes registered")
except Exception as e:
    logger.warning(f"⚠️ Survey Engine routes: {e}")

# Audit Log Routes
try:
    from audit_log import audit_bp
    app.register_blueprint(audit_bp)
    logger.info("✅ Audit Log routes registered: /api/audit/*")
except Exception as e:
    logger.warning(f"⚠️ Audit routes: {e}")

# Care Plan Routes (Plán péče)
try:
    from care_plan import care_plan_bp
    app.register_blueprint(care_plan_bp)
    logger.info("✅ Care Plan routes registered: /api/care-plan/*")
except Exception as e:
    logger.warning(f"⚠️ Care Plan routes: {e}")

try:
    from help_routes import help_bp
    app.register_blueprint(help_bp)
    logger.info("✅ Help routes registered: /api/help/*")
except Exception as e:
    logger.warning(f"⚠️ Help routes: {e}")

try:
    from stories_routes import stories_bp
    app.register_blueprint(stories_bp)
    logger.info("✅ Stories routes registered: /api/stories/*")
except Exception as e:
    logger.warning(f"⚠️ Stories routes: {e}")

try:
    from notes_routes import notes_bp
    app.register_blueprint(notes_bp)
    logger.info("✅ Notes routes registered: /api/notes/*")
except Exception as e:
    logger.warning(f"⚠️ Notes routes: {e}")

try:
    from gallery_routes import gallery_bp
    app.register_blueprint(gallery_bp)
    logger.info("✅ Gallery routes registered: /api/gallery/* (upload|photos|caption|animate|family)")
except Exception as e:
    logger.warning(f"⚠️ Gallery routes: {e}")

try:
    from growth_routes import growth_bp
    app.register_blueprint(growth_bp)
    logger.info("✅ Growth routes registered: /api/growth/* (relationship|memories|mood|moments|narrative|intents|skillmap)")
except Exception as e:
    logger.warning(f"⚠️ Growth routes: {e}")

try:
    from experience_routes import experience_bp
    app.register_blueprint(experience_bp)
    logger.info("✅ Experience routes registered: /api/experience/* — Radimův Odkaz")
except Exception as e:
    logger.warning(f"⚠️ Experience routes: {e}")

try:
    from caregiver_routes import caregiver_bp
    app.register_blueprint(caregiver_bp)
    logger.info("✅ Caregiver routes registered: /api/caregiver/* — family + pro partner view")
except Exception as e:
    logger.warning(f"⚠️ Caregiver routes: {e}")

try:
    from calls_routes import calls_bp
    app.register_blueprint(calls_bp)
    logger.info("✅ Calls routes registered: /api/calls/* — log + history + safe-to-call + quick-dial")
except Exception as e:
    logger.warning(f"⚠️ Calls routes: {e}")

try:
    from education_progress_routes import education_progress_bp
    app.register_blueprint(education_progress_bp)
    logger.info("✅ Education progress routes registered: /api/education/progress|stats|quiz-result|family|certificate")
except Exception as e:
    logger.warning(f"⚠️ Education progress routes: {e}")

try:
    from library_progress_routes import library_progress_bp
    app.register_blueprint(library_progress_bp)
    logger.info("✅ Library progress routes registered: /api/library/progress|bookmark|favorite|family|continue-reading")
except Exception as e:
    logger.warning(f"⚠️ Library progress routes: {e}")

try:
    from internet_routes import internet_bp
    app.register_blueprint(internet_bp)
    logger.info("✅ Internet routes registered: /api/internet/favorite|favorites|history|search|translate|family")
except Exception as e:
    logger.warning(f"⚠️ Internet routes: {e}")

try:
    from translator_progress_routes import translator_progress_bp
    app.register_blueprint(translator_progress_bp)
    logger.info("✅ Translator progress routes registered: /api/translator/history|favorite|favorites|family")
except Exception as e:
    logger.warning(f"⚠️ Translator progress routes: {e}")

try:
    from email_security_routes import email_security_bp
    app.register_blueprint(email_security_bp)
    logger.info("✅ Email security routes registered: /api/email/scan|flag-family|block|blocklist")
except Exception as e:
    logger.warning(f"⚠️ Email security routes: {e}")

try:
    from email_inbox_routes import email_inbox_bp
    app.register_blueprint(email_inbox_bp)
    logger.info("✅ Email inbox routes registered: /api/email/account|inbox|message|mark-read")
except Exception as e:
    logger.warning(f"⚠️ Email inbox routes: {e}")

try:
    from ha_scenes_routes import ha_scenes_bp
    app.register_blueprint(ha_scenes_bp)
    logger.info("✅ HA scenes+emergency+family routes registered: /api/ha/scenes|emergency|family/*")
except Exception as e:
    logger.warning(f"⚠️ HA scenes routes: {e}")

# FHIR Adapter (HL7 FHIR R4 export)
try:
    from fhir_adapter import fhir_bp
    app.register_blueprint(fhir_bp)
    logger.info("✅ FHIR routes registered: /api/fhir/*")
except Exception as e:
    logger.warning(f"⚠️ FHIR routes: {e}")

# Ops Quality (monitoring, error tracking, retention)
try:
    from ops_quality import ops_bp
    app.register_blueprint(ops_bp)
    logger.info("✅ Ops Quality routes registered: /api/ops/*")
except Exception as e:
    logger.warning(f"⚠️ Ops routes: {e}")

# Pilot Mode (templates, invite, export)
try:
    from pilot_mode import pilot_bp
    app.register_blueprint(pilot_bp)
    logger.info("✅ Pilot Mode routes registered: /api/pilot/*")
except Exception as e:
    logger.warning(f"⚠️ Pilot routes: {e}")

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

# v10.34: Browser Agent — safe read-only web browsing for seniors + agent tool
try:
    from browser_agent_routes import browser_agent_bp
    from browser_agent import ENABLE_BROWSER_AGENT as _BROWSER_FLAG
    app.register_blueprint(browser_agent_bp)
    BROWSER_AGENT_AVAILABLE = True
    logger.info(f"🌐 Browser Agent routes registered: /api/browser/* (enabled={_BROWSER_FLAG})")
except ImportError as e:
    BROWSER_AGENT_AVAILABLE = False
    logger.warning(f"⚠️ Browser Agent not available: {e}")

# v10.36: Safe Web Agent — GDPR-first senior-facing privacy layer over Browser Agent v10.34
try:
    from browser_agent_safe_routes import safe_web_bp
    from browser_agent_safe import ENABLE_SAFE_WEB_AGENT as _SAFE_WEB_FLAG
    app.register_blueprint(safe_web_bp)
    SAFE_WEB_AGENT_AVAILABLE = True
    logger.info(f"🛡️ Safe Web Agent routes registered: /api/safe-web/* (enabled={_SAFE_WEB_FLAG})")
except ImportError as e:
    SAFE_WEB_AGENT_AVAILABLE = False
    logger.warning(f"⚠️ Safe Web Agent not available: {e}")

# v10.49: Translator — V4 + EN (CZ, SK, PL, HU, EN) for Visegrad Fund conference
try:
    from translator_routes import translator_bp
    app.register_blueprint(translator_bp)
    TRANSLATOR_AVAILABLE = True
    logger.info("🌐 Translator routes registered: /api/translate (Gemini → MyMemory)")
except ImportError as e:
    TRANSLATOR_AVAILABLE = False
    logger.warning(f"⚠️ Translator not available: {e}")

# v10.37: In-app notifications + SOS + family account linking
try:
    from notification_routes import notification_bp
    from family_link_routes import family_link_bp
    app.register_blueprint(notification_bp)
    app.register_blueprint(family_link_bp)
    NOTIFICATIONS_AVAILABLE = True
    logger.info("🔔 Notifications + Family link routes registered: /api/notifications/*, /api/family/link/*, /api/sos/trigger")
except ImportError as e:
    NOTIFICATIONS_AVAILABLE = False
    logger.warning(f"⚠️ Notifications/Family link not available: {e}")

# v10.38: Contacts (phone book) with optional FamilyLink pairing
try:
    from contacts_routes import contacts_bp
    app.register_blueprint(contacts_bp)
    CONTACTS_AVAILABLE = True
    logger.info("📞 Contacts routes registered: /api/contacts/*")
except ImportError as e:
    CONTACTS_AVAILABLE = False
    logger.warning(f"⚠️ Contacts not available: {e}")

# v10.41: Onboarding wizard + welcome email
try:
    from onboarding_routes import onboarding_bp
    app.register_blueprint(onboarding_bp)
    ONBOARDING_AVAILABLE = True
    logger.info("🎯 Onboarding routes registered: /api/onboarding/*")
except ImportError as e:
    ONBOARDING_AVAILABLE = False
    logger.warning(f"⚠️ Onboarding not available: {e}")

# v10.41: System status dashboard for admins
try:
    from system_status_routes import system_status_bp
    app.register_blueprint(system_status_bp)
    SYSTEM_STATUS_AVAILABLE = True
    logger.info("📊 System status routes registered: /api/system/status")
except ImportError as e:
    SYSTEM_STATUS_AVAILABLE = False
    logger.warning(f"⚠️ System status not available: {e}")

# v10.45: Long-term memory + proactive recall
try:
    from memory_long_term_routes import memory_lt_bp
    app.register_blueprint(memory_lt_bp)
    MEMORY_LT_AVAILABLE = True
    logger.info("🧠 Long-term memory + proactive routes registered: /api/memory/long-term, /api/proactive/recall")
except ImportError as e:
    MEMORY_LT_AVAILABLE = False
    logger.warning(f"⚠️ Long-term memory routes not available: {e}")

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
                # Notify both parties — SocketIO (live app) + WebPush (backgrounded)
                socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{teacher_id}')
                socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{student_id}')
                # Multi-party: also notify additional participants
                participant_ids = c.get('participant_ids', [])
                for pid in participant_ids:
                    if pid != teacher_id and pid != student_id:
                        socketio.emit('telemedicine_reminder', reminder_data, room=f'user_{pid}')

                # v10.64 Sprint A+B: WebPush pipeline via notify()
                try:
                    from notification_helpers import notify as _notify
                    title = f"📹 Konzultace za {mins} min"
                    body = f"Vaše telekonzultace brzy začíná (#{cid})."
                    for to_uid in [teacher_id, student_id] + list(participant_ids):
                        if to_uid and to_uid not in (teacher_id,) if to_uid != teacher_id else True:
                            pass  # noop — keep all
                    for to_uid in set([teacher_id, student_id] + list(participant_ids)):
                        if not to_uid:
                            continue
                        _notify(to_user_id=to_uid, type='reminder',
                                title=title, body=body, severity='warning',
                                data={'consultation_id': cid, 'minutes_until': mins})
                except Exception as push_err:
                    logger.debug(f"Telemed push skipped (non-fatal): {push_err}")

                logger.info(f"🏥 Telemed reminder: consultation #{cid} in {mins} min → teacher {teacher_id}, student {student_id}, +{len(participant_ids)} participants")
            if upcoming:
                logger.info(f"🏥 Telemed scheduler: {len(upcoming)} reminders sent")
        except Exception as e:
            logger.error(f"🏥 Telemed scheduler error (non-fatal): {e}")

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_check_reminders, 'interval', minutes=5, id='radim_reminders')
    scheduler.add_job(_check_consultation_reminders, 'interval', minutes=5, id='telemed_reminders')

    # v10.60: Sprint F — medical appointment reminders (every 10 min) + daily symptom trend check
    try:
        from medical_team import appointment_reminder_cron, symptom_trend_alert_cron
        scheduler.add_job(appointment_reminder_cron, 'interval', minutes=10,
                          id='appointment_reminders', max_instances=1, misfire_grace_time=120)
        scheduler.add_job(symptom_trend_alert_cron, 'cron', hour=8, minute=30,
                          id='symptom_trend_alerts', misfire_grace_time=3600)
        logger.info("✅ Medical Sprint F cron jobs registered (appt reminders 10-min, symptom trends 8:30)")
    except Exception as e:
        logger.warning(f"⚠️ Medical Sprint F cron registration failed: {e}")

    # v10.70: Calendar Sprint C — 24h and 1h event reminders
    try:
        from calendar_routes import calendar_reminder_cron
        scheduler.add_job(calendar_reminder_cron, 'interval', minutes=10,
                          id='calendar_reminders', max_instances=1, misfire_grace_time=120)
        logger.info("✅ Calendar reminders registered (every 10 min, 24h+1h before events)")
    except Exception as e:
        logger.warning(f"⚠️ Calendar reminder cron registration failed: {e}")
    # Proactive agent loop — autonomous senior monitoring
    try:
        from agent_loop import run_agent_cycle
        scheduler.add_job(lambda: run_agent_cycle(app), 'interval', minutes=5,
                          id='agent_loop', max_instances=1, misfire_grace_time=120)
        logger.info("✅ Agent loop registered (every 5 min)")
    except ImportError:
        logger.warning("⚠️ agent_loop not available — proactive agent disabled")

    # v10.40: SOS escalation engine — every 10 s walks unresolved events through stages
    try:
        from sos_escalator import run_escalator_tick, is_enabled as sos_enabled
        if sos_enabled():
            scheduler.add_job(lambda: run_escalator_tick(app), 'interval', seconds=10,
                              id='sos_escalator', max_instances=1, misfire_grace_time=30)
            logger.info("🆘 SOS escalator registered (every 10 s)")
        else:
            logger.info("🆘 SOS escalator disabled via SOS_ESCALATION env")
    except ImportError:
        logger.warning("⚠️ sos_escalator not available")

    # v10.45: Weekly long-term memory summarization (Sunday 4:00 AM)
    try:
        from memory_summarization import run_weekly_summarization
        scheduler.add_job(lambda: run_weekly_summarization(app), 'cron',
                          day_of_week='sun', hour=4, minute=7,
                          id='memory_weekly_summary',
                          max_instances=1, misfire_grace_time=3600)
        logger.info("🧠 Weekly memory summarization registered (Sun 04:07)")
    except ImportError:
        logger.warning("⚠️ memory_summarization not available")

    # HA P2 — abnormal night activity detection (every 15 min; self-skips
    # outside 23:00–05:00) + daily maintenance check at 09:30
    try:
        from ha_background_jobs import run_night_activity_check, run_maintenance_check
        scheduler.add_job(
            lambda: run_night_activity_check(app), 'interval', minutes=15,
            id='ha_night_activity', max_instances=1, misfire_grace_time=300
        )
        scheduler.add_job(
            lambda: run_maintenance_check(app), 'cron',
            hour=9, minute=30, id='ha_maintenance',
            max_instances=1, misfire_grace_time=1800
        )
        logger.info("🏠 HA background jobs registered (night: every 15m, maintenance: daily 09:30)")
    except ImportError:
        logger.warning("⚠️ ha_background_jobs not available")
    except Exception as e:
        logger.warning(f"⚠️ HA background jobs registration failed: {e}")

    # Radimův Odkaz — royalty scheduler + scheduled messages release
    try:
        from experience_routes import register_scheduler_jobs as register_exp_jobs
        register_exp_jobs(scheduler)
    except ImportError:
        logger.warning("⚠️ experience_routes scheduler not available")
    except Exception as e:
        logger.warning(f"⚠️ Experience scheduler registration failed: {e}")

    # Pečovatel — daily narrative precompute at 22:00
    try:
        from caregiver_routes import register_scheduler_jobs as register_cg_jobs
        register_cg_jobs(scheduler)
    except ImportError:
        logger.warning("⚠️ caregiver_routes scheduler not available")
    except Exception as e:
        logger.warning(f"⚠️ Caregiver scheduler registration failed: {e}")

    # v10.45: Daily proactive recall — hooked into morning checkin time
    # Runs at 08:12 (7 min after morning_checkin so meds prompt goes first)
    try:
        from proactive_engine import run_daily_recall
        scheduler.add_job(lambda: run_daily_recall(app), 'cron',
                          hour=8, minute=12,
                          id='proactive_recall',
                          max_instances=1, misfire_grace_time=1800)
        logger.info("💡 Daily proactive recall registered (08:12)")
    except ImportError:
        logger.warning("⚠️ proactive_engine not available")

    # v390: Morning check-in — call seniors with medication reminders at 8:00 AM
    try:
        from agent_loop import run_morning_checkin
        scheduler.add_job(lambda: run_morning_checkin(app), 'cron', hour=8, minute=0,
                          id='morning_checkin', max_instances=1, misfire_grace_time=600)
        logger.info("✅ Morning check-in registered (daily at 8:00)")
    except ImportError:
        logger.warning("⚠️ morning check-in not available")

    # v10.57: Morning news briefing — webpush top 3 stories at 08:05
    try:
        from news_briefing_job import run_morning_news_briefing
        scheduler.add_job(lambda: run_morning_news_briefing(app), 'cron',
                          hour=8, minute=5,
                          id='morning_news_briefing',
                          max_instances=1, misfire_grace_time=1800)
        logger.info("✅ Morning news briefing registered (daily at 8:05)")
    except ImportError as e:
        logger.warning(f"⚠️ news briefing not available: {e}")

    # Daily cleanup — old observations + brain_states
    try:
        from agent_loop import run_daily_cleanup
        scheduler.add_job(lambda: run_daily_cleanup(app), 'cron', hour=3, minute=0,
                          id='daily_cleanup', max_instances=1, misfire_grace_time=3600)
        logger.info("✅ Daily cleanup registered (3:00 AM)")
    except ImportError:
        logger.warning("⚠️ daily cleanup not available")

    # v445: Daily engagement (positive proactive interaction, 14:00)
    try:
        from agent_loop import run_daily_engagement
        scheduler.add_job(lambda: run_daily_engagement(app), 'cron', hour=14, minute=0,
                          id='daily_engagement', max_instances=1, misfire_grace_time=1800)
        logger.info("✅ Daily engagement registered (14:00)")
    except ImportError:
        logger.warning("⚠️ daily engagement not available")

    # v446: Daily summary email to caregivers (20:00)
    try:
        from agent_loop import run_daily_summary
        scheduler.add_job(lambda: run_daily_summary(app), 'cron', hour=20, minute=0,
                          id='daily_summary', max_instances=1, misfire_grace_time=1800)
        logger.info("✅ Daily summary registered (20:00)")
    except ImportError:
        logger.warning("⚠️ daily summary not available")

    # v10.32: Weekly family reports (Sunday 18:00) — activates WeeklyReportAgent
    try:
        from agent_loop import run_weekly_reports
        scheduler.add_job(lambda: run_weekly_reports(app), 'cron',
                          day_of_week='sun', hour=18, minute=0,
                          id='weekly_reports', max_instances=1, misfire_grace_time=3600)
        logger.info("✅ Weekly reports registered (Sunday 18:00)")
    except ImportError:
        logger.warning("⚠️ weekly reports not available")

    # 🤖 Health Agent — autonomous monitoring + auto-fix (every 15 min)
    try:
        from radim_health_agent import run_health_check, run_summary_report
        def _run_health_agent():
            try:
                with app.app_context():
                    result = run_health_check()
                    logger.info(f"🤖 Health Agent: {result.get('status')} in {result.get('turns', '?')} turns")
            except Exception as e:
                logger.warning(f"🤖 Health Agent error (non-fatal): {e}")

        def _run_summary_report():
            try:
                with app.app_context():
                    result = run_summary_report()
                    logger.info(f"🤖 Summary Report: {result.get('status')} in {result.get('turns', '?')} turns")
            except Exception as e:
                logger.warning(f"🤖 Summary Report error (non-fatal): {e}")

        scheduler.add_job(_run_health_agent, 'interval', minutes=15,
                          id='health_agent', max_instances=1, misfire_grace_time=300)
        # 48h summary report — runs at 9:00 every other day (Mon, Wed, Fri)
        scheduler.add_job(_run_summary_report, 'cron', day_of_week='mon,wed,fri', hour=9, minute=0,
                          id='summary_report', max_instances=1, misfire_grace_time=3600)
        logger.info("✅ Health Agent registered (15 min) + Summary Report (Mon/Wed/Fri 9:00)")
    except ImportError:
        logger.warning("⚠️ Health Agent not available")

    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("✅ APScheduler started: 9 jobs")

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
    # v10.22: Calendar schema
    try:
        from database_schema import init_calendar_schema
        with db_context(commit=True) as _db:
            init_calendar_schema(_db)
    except Exception as e:
        logger.debug(f"Calendar schema init: {e}")

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


@app.route("/health/scaling")
def scaling_stats():
    """⚡ Scaling optimization stats — TTS cache, AI cache, DB pool."""
    try:
        from scaling_optimizations import get_optimization_stats
        stats = get_optimization_stats()
        # Add DB pool info
        try:
            from database import _pg_pool
            if _pg_pool:
                stats['db_pool'] = {
                    'min': _pg_pool.minconn,
                    'max': _pg_pool.maxconn,
                    'closed': _pg_pool.closed
                }
        except Exception:
            pass
        return jsonify({'success': True, **stats})
    except ImportError:
        return jsonify({'success': False, 'error': 'Scaling module not loaded'}), 503


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
            # Core (required)
            'chat': 'active',
            'websocket': True,
            'speech': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'azure_tts_proxy': bool(AZURE_TTS_KEY),
            'ai': {'gemini': bool(GEMINI_API_KEY), 'claude': bool(ANTHROPIC_API_KEY)},
            'push': bool(VAPID_PRIVATE_KEY),
            'twilio_voice': {'configured': bool(os.environ.get('TWILIO_ACCOUNT_SID')), 'phone': os.environ.get('TWILIO_PHONE_NUMBER')},
            'agent_loop': True,
            # Optional (not required for production)
            'media': 'cloudinary' if CLOUDINARY_URL else 'not_configured',
            'wordpress': 'connected' if (WP_URL and WP_USER) else 'not_configured',
        },
        'online_users': len(users_online),
        'self_healing': _get_healing_status()
    }), status_code


def _get_healing_status():
    """Get self-healing circuit breaker status for /health endpoint."""
    try:
        from self_healing import get_system_health
        h = get_system_health()
        return {
            'overall': h.get('overall', 'unknown'),
            'circuits': {name: info['state'] for name, info in h.get('circuits', {}).items()},
        }
    except ImportError:
        return {'overall': 'unavailable'}

# v10.9: Admin auth guard — NO dev mode bypass
ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')

def _check_admin():
    """Check admin auth via X-Admin-Secret header OR JWT admin role.

    Supports:
    1. X-Admin-Secret header (for scripts/CLI)
    2. JWT with role=administrator (for frontend admin module)

    OPTIONS preflight always passes (CORS requirement).
    """
    # Always allow OPTIONS (CORS preflight)
    if request.method == 'OPTIONS':
        return True

    # Method 1: X-Admin-Secret header
    if ADMIN_SECRET:
        token = request.headers.get('X-Admin-Secret', '')
        if token and hmac.compare_digest(token, ADMIN_SECRET):
            return True

    # Method 2: JWT with admin role
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        try:
            from auth_middleware import decode_jwt
            payload = decode_jwt(auth_header.split(' ', 1)[1])
            if payload and payload.get('user', {}).get('role') in ('administrator', 'admin'):
                return True
        except Exception:
            pass

    return False

# v383: Admin IoT simulator
@app.route('/api/admin/iot-simulate', methods=['POST', 'OPTIONS'])
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
@app.route('/api/admin/debug-prompt/<user_id>', methods=['GET', 'OPTIONS'])
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
@app.route('/api/admin/seed-demo', methods=['POST', 'OPTIONS'])
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
@app.route('/api/admin/news-briefing-test', methods=['POST', 'OPTIONS'])
def admin_news_briefing_test():
    """Manually trigger morning news briefing push.

    Same payload/pipeline as the 08:05 cron — webpushes the top 3 general
    articles to every push_subscriptions row. Returns summary of send result.
    """
    if request.method == 'OPTIONS':
        return '', 204
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        from news_briefing_job import run_morning_news_briefing
        result = run_morning_news_briefing(app)
        return jsonify({'success': True, 'result': result}), 200
    except Exception as e:
        logger.error(f"News briefing test error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/agent-run', methods=['POST', 'OPTIONS'])
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

@app.route('/api/admin/agents-status', methods=['GET', 'OPTIONS'])
def admin_agents_status():
    """Full status of all agents — for admin dashboard.

    Shows:
    - Scheduler jobs (11 registered): when last run, next run
    - Per-agent observation counts (24h / 7d)
    - Active users being monitored
    - Telemetry summary

    Accessible via X-Admin-Secret header OR OPTIONS (public CORS).
    """
    # OPTIONS = public (CORS preflight returns full response)
    # GET = requires admin secret
    if request.method == 'GET' and not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        from datetime import datetime as _dt, timedelta
        result = {
            'success': True,
            'timestamp': now_iso(),
            'version': '3.5.1',
            'agents': {},
            'scheduler': {'jobs': []},
            'activity': {},
        }

        # 1. Scheduler jobs (from APScheduler global, if accessible)
        try:
            from app import scheduler as _sched
            for job in _sched.get_jobs():
                result['scheduler']['jobs'].append({
                    'id': job.id,
                    'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger),
                })
        except Exception as _:
            # Fallback — list expected jobs statically
            result['scheduler']['jobs'] = [
                {'id': 'agent_loop', 'trigger': 'interval 5min'},
                {'id': 'radim_reminders', 'trigger': 'interval 5min'},
                {'id': 'telemed_reminders', 'trigger': 'interval 5min'},
                {'id': 'health_agent', 'trigger': 'interval 15min'},
                {'id': 'morning_checkin', 'trigger': 'cron 8:00'},
                {'id': 'daily_engagement', 'trigger': 'cron 14:00'},
                {'id': 'daily_summary', 'trigger': 'cron 20:00'},
                {'id': 'daily_cleanup', 'trigger': 'cron 3:00'},
                {'id': 'summary_report', 'trigger': 'cron Mon/Wed/Fri 9:00'},
                {'id': 'weekly_reports', 'trigger': 'cron Sun 18:00'},
            ]

        # 2. Per-agent observation counts (from agent_observations)
        # Map observation_type → agent name
        AGENT_MAP = {
            'c_trend_rising': 'CoreDetector',
            'activity_drop': 'CoreDetector',
            'vital_anomaly': 'CoreDetector',
            'no_interaction': 'CoreDetector',
            'fall_detected': 'CoreDetector',
            'fall_suspected': 'CoreDetector',
            'sleep_poor': 'SleepAgent',
            'isolation_critical': 'SocialIsolationAgent',
            'isolation_high': 'SocialIsolationAgent',
            'medication_low': 'MedicationTracker',
            'prediction_critical': 'PredictiveAgent',
            'prediction_high': 'PredictiveAgent',
            'survey_risk': 'SurveyEngine',
            'anticipation_anomaly': 'AnticipationEngine',
            'environment_cold': 'HAEnvironment',
            'environment_hot': 'HAEnvironment',
            # v10.34: Browser Agent observation types
            'web_fetch': 'BrowserAgent',
            'web_click': 'BrowserAgent',
            'web_find': 'BrowserAgent',
            'web_blocked': 'BrowserAgent',
            'web_error': 'BrowserAgent',
            'web_close': 'BrowserAgent',
        }

        with db_context() as db:
            # 24h observations by type
            if is_postgres():
                obs_rows = db.execute(
                    "SELECT observation_type, severity, COUNT(*) as cnt "
                    "FROM agent_observations "
                    "WHERE created_at > NOW() - INTERVAL '24 hours' "
                    "GROUP BY observation_type, severity"
                ).fetchall()
                # 7d totals
                week_rows = db.execute(
                    "SELECT observation_type, COUNT(*) as cnt "
                    "FROM agent_observations "
                    "WHERE created_at > NOW() - INTERVAL '7 days' "
                    "GROUP BY observation_type"
                ).fetchall()
                # Last observation timestamp
                last_row = db.execute(
                    "SELECT MAX(created_at) as last FROM agent_observations"
                ).fetchone()
                # Active users (brain_states last 24h)
                active_row = db.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states "
                    "WHERE created_at > NOW() - INTERVAL '24 hours'"
                ).fetchone()
                # Total seniors monitored
                total_row = db.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states"
                ).fetchone()
                # Recent observations for feed
                recent = db.execute(
                    "SELECT user_id, observation_type, severity, message, created_at "
                    "FROM agent_observations ORDER BY created_at DESC LIMIT 15"
                ).fetchall()
            else:
                obs_rows = db.execute(
                    "SELECT observation_type, severity, COUNT(*) as cnt FROM agent_observations "
                    "WHERE created_at > datetime('now', '-24 hours') "
                    "GROUP BY observation_type, severity"
                ).fetchall()
                week_rows = db.execute(
                    "SELECT observation_type, COUNT(*) as cnt FROM agent_observations "
                    "WHERE created_at > datetime('now', '-7 days') GROUP BY observation_type"
                ).fetchall()
                last_row = db.execute("SELECT MAX(created_at) as last FROM agent_observations").fetchone()
                active_row = db.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states "
                    "WHERE created_at > datetime('now', '-24 hours')"
                ).fetchone()
                total_row = db.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states").fetchone()
                recent = db.execute(
                    "SELECT user_id, observation_type, severity, message, created_at "
                    "FROM agent_observations ORDER BY created_at DESC LIMIT 15"
                ).fetchall()

        # Aggregate by agent
        agents_agg = {}
        def _key(row, k, idx):
            return row.get(k) if isinstance(row, dict) else (row[idx] if len(row) > idx else None)

        for r in obs_rows:
            t = _key(r, 'observation_type', 0)
            sev = _key(r, 'severity', 1)
            cnt = int(_key(r, 'cnt', 2) or 0)
            agent_name = AGENT_MAP.get(t, 'Other')
            if agent_name not in agents_agg:
                agents_agg[agent_name] = {'name': agent_name, 'observations_24h': 0, 'observations_7d': 0,
                                           'by_severity': {}, 'types': []}
            agents_agg[agent_name]['observations_24h'] += cnt
            agents_agg[agent_name]['by_severity'][sev or 'unknown'] = \
                agents_agg[agent_name]['by_severity'].get(sev or 'unknown', 0) + cnt
            if t and t not in agents_agg[agent_name]['types']:
                agents_agg[agent_name]['types'].append(t)

        for r in week_rows:
            t = _key(r, 'observation_type', 0)
            cnt = int(_key(r, 'cnt', 1) or 0)
            agent_name = AGENT_MAP.get(t, 'Other')
            if agent_name in agents_agg:
                agents_agg[agent_name]['observations_7d'] += cnt
            elif agent_name == 'Other' or agent_name not in agents_agg:
                agents_agg[agent_name] = agents_agg.get(agent_name, {
                    'name': agent_name, 'observations_24h': 0, 'observations_7d': cnt,
                    'by_severity': {}, 'types': [t] if t else []
                })
                if 'observations_7d' not in agents_agg[agent_name]:
                    agents_agg[agent_name]['observations_7d'] = cnt

        # Add idle agents (never generated observations but are scheduled/wired)
        ALL_AGENTS = [
            ('PredictiveAgent', 'Predikce krize na 24h'),
            ('SleepAgent', 'Analýza spánku z IoT motion'),
            ('SocialIsolationAgent', 'Míra sociální izolace'),
            ('MedicationTracker', 'Adherence léků'),
            ('LearningAgent', 'Per-user adaptace thresholds'),
            ('WeatherAgent', 'Weather-aware návrhy'),
            ('WeeklyReportAgent', 'Týdenní reporty rodině'),
            ('SurveyEngine', 'Multi-signal risk'),
            ('AnticipationEngine', 'Prediktivní Ĉ_{t+1}'),
            ('CircadianEngine', 'Denní rytmus + routine shifts'),
            ('EmergencyProtocol', 'Crisis automation'),
            ('CoreDetector', 'C-trend, activity, vitals, falls'),
            ('HAEnvironment', 'Home Assistant teplota/světlo'),
            ('HealthAgent', 'Self-healing (15 min)'),
            ('BrowserAgent', 'Bezpečné čtení webu (Wikipedie, Novinky, ČT, Počasí)'),
        ]
        for agent_name, desc in ALL_AGENTS:
            if agent_name not in agents_agg:
                agents_agg[agent_name] = {
                    'name': agent_name, 'description': desc,
                    'observations_24h': 0, 'observations_7d': 0,
                    'by_severity': {}, 'types': []
                }
            else:
                agents_agg[agent_name]['description'] = desc

        result['agents'] = agents_agg

        # Activity summary
        result['activity'] = {
            'active_users_24h': int(_key(active_row, 'cnt', 0) or 0) if active_row else 0,
            'total_users_tracked': int(_key(total_row, 'cnt', 0) or 0) if total_row else 0,
            'last_observation_at': str(_key(last_row, 'last', 0) or '') if last_row else None,
            'total_observations_24h': sum(a['observations_24h'] for a in agents_agg.values()),
            'total_observations_7d': sum(a['observations_7d'] for a in agents_agg.values()),
        }

        # Recent feed (last 15)
        result['recent_observations'] = [
            {
                'user_id': _key(r, 'user_id', 0),
                'type': _key(r, 'observation_type', 1),
                'severity': _key(r, 'severity', 2),
                'message': (_key(r, 'message', 3) or '')[:120],
                'at': str(_key(r, 'created_at', 4) or ''),
                'agent': AGENT_MAP.get(_key(r, 'observation_type', 1), 'Other'),
            } for r in recent
        ]

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Agents status error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/crisis-demo', methods=['POST', 'OPTIONS'])
def admin_crisis_demo():
    """Live crisis demo for conference: simulate fall → full pipeline.

    POST body (optional):
    {
        "user_id": "demo_senior_1",      # default: demo_senior_1
        "scenario": "fall",               # fall | vital | silence
        "call_phone": false,              # actually call (default: false = dry run)
        "ha_actions": false               # actually trigger HA (default: false)
    }

    Returns timeline of all actions taken.
    """
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        user_id = data.get('user_id', 'demo_senior_1')
        scenario = data.get('scenario', 'fall')
        do_call = data.get('call_phone', False)
        do_ha = data.get('ha_actions', False)

        timeline = []
        import time as _time

        # Step 1: Build observation
        scenarios = {
            'fall': {
                'type': 'fall_detected',
                'severity': 'crisis',
                'message': f'⚠️ Detekován pád seniora {user_id}. Akcelerometr: 4.2G impact.',
                'details': {'sensor': 'accelerometer', 'value': 4.2, 'threshold': 3.0}
            },
            'vital': {
                'type': 'vital_anomaly',
                'severity': 'crisis',
                'message': f'🚨 SpO2 pod 88% pro {user_id}. Možná hypoxie.',
                'details': {'sensor': 'spo2', 'value': 88, 'threshold': 90}
            },
            'silence': {
                'type': 'no_interaction',
                'severity': 'alert',
                'message': f'🔕 {user_id} neinteragoval 12+ hodin.',
                'details': {'hours_silent': 12, 'threshold': 8}
            }
        }
        obs = scenarios.get(scenario, scenarios['fall'])
        timeline.append({'t': 0, 'action': 'observation_created', 'detail': obs['message']})

        # Step 2: Save observation to DB
        from database import db_context, db_insert, is_postgres
        with db_context(commit=True) as db:
            db_insert(db, 'agent_observations',
                      ['user_id', 'observation_type', 'severity', 'message', 'action_taken', 'details'],
                      [user_id, obs['type'], obs['severity'], obs['message'], 'demo_crisis_flow',
                       json.dumps(obs.get('details', {}))])
        timeline.append({'t': 1, 'action': 'db_saved', 'detail': 'Observation saved to agent_observations'})

        # Step 3: Inject into memory (so Radim mentions it in next chat)
        try:
            from agent_loop import _inject_into_memory
            _inject_into_memory(user_id, obs)
            timeline.append({'t': 2, 'action': 'memory_injected', 'detail': 'Crisis context injected into personalized prompt'})
        except Exception as e:
            timeline.append({'t': 2, 'action': 'memory_inject_failed', 'detail': str(e)})

        # Step 4: Push notification to senior
        try:
            from agent_loop import _push_to_senior
            _push_to_senior(user_id, obs, app)
            timeline.append({'t': 3, 'action': 'push_sent', 'detail': 'Push notification sent to senior device'})
        except Exception as e:
            timeline.append({'t': 3, 'action': 'push_skipped', 'detail': str(e)})

        # Step 5: Alert caregiver
        try:
            from agent_loop import _alert_caregiver
            _alert_caregiver(user_id, obs, app)
            timeline.append({'t': 4, 'action': 'caregiver_alerted', 'detail': 'Caregiver notified via push + email'})
        except Exception as e:
            timeline.append({'t': 4, 'action': 'caregiver_alert_skipped', 'detail': str(e)})

        # Step 6: Route to medical team
        try:
            from agent_loop import _route_to_medical_team
            _route_to_medical_team(user_id, obs, app)
            timeline.append({'t': 5, 'action': 'medical_team_routed', 'detail': 'Alert routed to coordinator + caregiver roles'})
        except Exception as e:
            timeline.append({'t': 5, 'action': 'medical_route_skipped', 'detail': str(e)})

        # Step 7: Phone call (optional — only if presenter wants live call)
        if do_call:
            try:
                from agent_loop import _call_senior
                _call_senior(user_id, obs)
                timeline.append({'t': 6, 'action': 'phone_call_initiated', 'detail': 'Proactive call via Twilio'})
            except Exception as e:
                timeline.append({'t': 6, 'action': 'phone_call_failed', 'detail': str(e)})
        else:
            timeline.append({'t': 6, 'action': 'phone_call_skipped', 'detail': 'Dry run — set call_phone=true to actually call'})

        # Step 8: Home Assistant actions — real HA if connected, else scripted mock for conference
        # Conference mode: ha_mock=true returns realistic scripted responses even without HA hardware
        ha_mock = data.get('ha_mock', False)
        ha_actions_log = []
        if do_ha or ha_mock:
            try:
                # Try real HA first
                from home_assistant import HA_URL, HA_TOKEN
                ha_connected = bool(HA_URL and HA_TOKEN)

                if do_ha and ha_connected:
                    from agent_loop import _ha_crisis_actions
                    _ha_crisis_actions(user_id, obs)
                    ha_actions_log = [
                        {'device': 'all_lights', 'action': 'on', 'brightness': 100, 'source': 'real_ha'},
                        {'device': 'front_door', 'action': 'unlock', 'source': 'real_ha'},
                        {'device': 'covers_all', 'action': 'open', 'source': 'real_ha'},
                    ]
                    timeline.append({'t': 7, 'action': 'ha_actions_executed',
                                     'detail': 'Real HA: lights 100%, door unlocked, covers opened',
                                     'actions': ha_actions_log})
                else:
                    # Mock mode — scripted response for conference demo without HA hardware
                    ha_actions_log = [
                        {'device': 'obyvak_svetlo', 'name': 'Obývák — světlo', 'action': 'on',
                         'brightness': 100, 'duration_ms': 200, 'source': 'mock'},
                        {'device': 'kuchyn_svetlo', 'name': 'Kuchyň — světlo', 'action': 'on',
                         'brightness': 100, 'duration_ms': 180, 'source': 'mock'},
                        {'device': 'loznice_svetlo', 'name': 'Ložnice — světlo', 'action': 'on',
                         'brightness': 80, 'duration_ms': 220, 'source': 'mock'},
                        {'device': 'chodba_svetlo', 'name': 'Chodba — světlo', 'action': 'on',
                         'brightness': 100, 'duration_ms': 150, 'source': 'mock'},
                        {'device': 'vchodove_dvere', 'name': 'Vchodové dveře', 'action': 'unlock',
                         'duration_ms': 400, 'source': 'mock'},
                        {'device': 'obyvak_rolety', 'name': 'Obývák — rolety', 'action': 'open',
                         'duration_ms': 800, 'source': 'mock'},
                    ]
                    timeline.append({'t': 7, 'action': 'ha_actions_mock',
                                     'detail': 'HA mock: 4 lights ON, door unlocked, covers opened (hardware arrives next week)',
                                     'actions': ha_actions_log})
            except Exception as e:
                timeline.append({'t': 7, 'action': 'ha_actions_failed', 'detail': str(e)})
        else:
            timeline.append({'t': 7, 'action': 'ha_actions_skipped',
                             'detail': 'Dry run — set ha_actions=true (real) or ha_mock=true (scripted)'})

        # Step 9: Generate TTS crisis greeting (for playback demo)
        tts_greeting = None
        try:
            from voice_filter import build_radim_ssml
            crisis_text = "Zaznamenal jsem pád. Jste v pořádku? Pokud potřebujete pomoc, řekněte pomoc nebo stiskněte červené tlačítko."
            # v10.29: RTCF Beat Engine voice modifiers for crisis playback
            _rtcf_voice = None
            try:
                from brain_speech import get_brain_speech_for_user
                _bs = get_brain_speech_for_user(user_id)
                if _bs:
                    _rtcf_voice = _bs.get('rtcf_voice')
            except Exception:
                pass
            tts_greeting = build_radim_ssml(crisis_text, mode='CRISIS', user_id=user_id,
                                            rtcf_voice=_rtcf_voice)
            timeline.append({'t': 8, 'action': 'tts_crisis_ssml',
                             'detail': f'CRISIS voice SSML generated (rtcf_voice={"yes" if _rtcf_voice else "no"})'})
        except Exception as e:
            timeline.append({'t': 8, 'action': 'tts_ssml_failed', 'detail': str(e)})

        # v10.30: Conference-friendly narrative for stage presentation
        narrative = [
            {'t_ms': 0,     'event': 'detection', 'text': obs['message']},
            {'t_ms': 1500,  'event': 'brain_analysis', 'text': 'Radim vyhodnocuje situaci — Ψ(t) stav přepnut na CRISIS'},
            {'t_ms': 3000,  'event': 'memory_context', 'text': 'Krizový kontext injektován do paměti pro budoucí konverzace'},
            {'t_ms': 4500,  'event': 'push_senior', 'text': 'Notifikace na zařízení seniora'},
            {'t_ms': 6000,  'event': 'caregiver_alert', 'text': 'Pečovatel / rodina notifikováni (push + email + SMS)'},
            {'t_ms': 8000,  'event': 'medical_team', 'text': 'Alert směřován do lékařského týmu (coordinator + caregiver)'},
            {'t_ms': 10000, 'event': 'phone_call', 'text': 'Radim volá seniorovi: „Zaznamenal jsem pád. Jste v pořádku?"'},
            {'t_ms': 12000, 'event': 'ha_lights', 'text': '💡 Světla: obývák, kuchyň, ložnice, chodba — 100 %'},
            {'t_ms': 13000, 'event': 'ha_door', 'text': '🔓 Vchodové dveře odemčeny (pro záchranku)'},
            {'t_ms': 14000, 'event': 'ha_covers', 'text': '🪟 Rolety otevřeny (viditelnost zvenčí)'},
            {'t_ms': 15000, 'event': 'voice_response', 'text': 'Radim mluví uklidňujícím hlasem (CRISIS mode: -20% rate, 1200ms pauzy)'},
        ]

        return jsonify({
            'success': True,
            'scenario': scenario,
            'user_id': user_id,
            'severity': obs['severity'],
            'timeline': timeline,
            'tts_ssml': tts_greeting,
            'ha_actions': ha_actions_log,
            'narrative': narrative,
            'narrative_duration_ms': 15000,
            'mode': 'mock' if ha_mock else ('live' if do_ha else 'dry_run'),
            'next_steps': [
                'Chat with senior → Radim will mention the crisis in context',
                'Check /api/admin/debug-prompt/' + user_id + ' to see injected memory',
                'Set call_phone=true to actually call the senior',
                'Set ha_actions=true to trigger Home Assistant (real hardware)',
                'Set ha_mock=true for scripted demo without hardware (conference)'
            ]
        }), 200
    except Exception as e:
        logger.error(f"Crisis demo error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/whatsapp-send', methods=['POST', 'OPTIONS'])
def admin_whatsapp_send():
    """Send a proactive WhatsApp message to a senior.

    POST body:
    {
        "user_id": "senior_id",         # looks up phone from profile
        "phone": "+420123456789",       # OR direct phone (overrides user_id lookup)
        "message": "Dobrý den, tady Radim...",
        "reason": "check_in"            # check_in | alert | crisis | reminder
    }
    """
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        message = data.get('message')
        if not message:
            return jsonify({'error': 'message is required'}), 400

        phone = data.get('phone')
        user_id = data.get('user_id')
        reason = data.get('reason', 'check_in')

        if phone:
            from twilio_voice_helpers import send_whatsapp_message
            result = send_whatsapp_message(phone, message, user_id=user_id)
        elif user_id:
            from twilio_voice_helpers import send_proactive_whatsapp
            result = send_proactive_whatsapp(user_id, message, reason=reason)
        else:
            return jsonify({'error': 'Either user_id or phone is required'}), 400

        status_code = 200 if result.get('success') else 400
        return jsonify(result), status_code
    except Exception as e:
        logger.error(f"WhatsApp send error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/financial-dashboard', methods=['GET', 'OPTIONS'])
def admin_financial_dashboard():
    """Financial savings dashboard — how much Radim saves per senior.

    Calculates: prevented hospitalizations, reduced caregiver hours,
    medication adherence value, emergency response savings.

    Query params:
        user_id — specific senior (default: all)
        months  — lookback period (default: 3)
    """
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_id = request.args.get('user_id')
        months = int(request.args.get('months', 3))

        with db_context() as db:
            # Count crisis interventions (prevented hospitalizations)
            if user_id:
                crisis_rows = db.execute(
                    "SELECT severity, COUNT(*) as cnt FROM agent_observations "
                    "WHERE user_id = ? GROUP BY severity", (user_id,)
                ).fetchall()
                interaction_count = db.execute(
                    "SELECT COUNT(*) FROM brain_states WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
            else:
                crisis_rows = db.execute(
                    "SELECT severity, COUNT(*) as cnt FROM agent_observations "
                    "GROUP BY severity"
                ).fetchall()
                interaction_count = db.execute(
                    "SELECT COUNT(*) FROM brain_states"
                ).fetchone()[0]

        # Aggregate by severity
        severity_counts = {r[0]: r[1] for r in crisis_rows}
        crisis_count = severity_counts.get('crisis', 0)
        alert_count = severity_counts.get('alert', 0)
        warning_count = severity_counts.get('warning', 0)

        # Czech healthcare cost model (2025 prices, CZK)
        HOSPITAL_DAY_COST = 12500       # Avg cost per hospital day
        AVG_HOSPITAL_STAY = 5           # Days per preventable admission
        CAREGIVER_HOUR_COST = 350       # Professional caregiver hourly rate
        EMERGENCY_CALL_COST = 8500      # Ambulance dispatch cost
        MEDICATION_ERROR_COST = 4200    # Avg cost of medication non-adherence event

        # Savings model
        prevented_hospitalizations = max(1, crisis_count // 3)  # ~1 in 3 crises would lead to hospitalization
        hospital_savings = prevented_hospitalizations * HOSPITAL_DAY_COST * AVG_HOSPITAL_STAY

        caregiver_hours_saved = interaction_count * 0.25  # Each AI interaction saves ~15 min caregiver time
        caregiver_savings = int(caregiver_hours_saved * CAREGIVER_HOUR_COST)

        emergency_prevented = alert_count // 2  # Half of alerts would become emergencies without AI
        emergency_savings = emergency_prevented * EMERGENCY_CALL_COST

        medication_adherence = warning_count // 4  # Medication reminders prevent ~25% of events
        medication_savings = medication_adherence * MEDICATION_ERROR_COST

        total_savings = hospital_savings + caregiver_savings + emergency_savings + medication_savings

        # Radim cost (Heroku $7 + Azure TTS ~$20 + Gemini ~$15/month)
        radim_monthly_cost = 42  # USD → ~1000 CZK
        radim_total_cost = radim_monthly_cost * months * 24  # CZK approx

        roi = round(total_savings / max(radim_total_cost, 1), 1)

        return jsonify({
            'success': True,
            'period_months': months,
            'user_id': user_id or 'all',
            'interactions': interaction_count,
            'observations': {
                'crisis': crisis_count,
                'alert': alert_count,
                'warning': warning_count
            },
            'savings_czk': {
                'prevented_hospitalizations': {'count': prevented_hospitalizations, 'savings': hospital_savings},
                'caregiver_hours_saved': {'hours': round(caregiver_hours_saved, 1), 'savings': caregiver_savings},
                'emergency_prevented': {'count': emergency_prevented, 'savings': emergency_savings},
                'medication_adherence': {'events': medication_adherence, 'savings': medication_savings},
                'total': total_savings
            },
            'cost_czk': radim_total_cost,
            'roi_multiplier': roi,
            'summary': f"Radim ušetřil {total_savings:,} Kč za {months} měsíců. ROI: {roi}×."
        }), 200
    except Exception as e:
        logger.error(f"Financial dashboard error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/status', methods=['GET', 'OPTIONS'])
def admin_status():
    """Comprehensive system status — all subsystems at a glance."""
    if not _check_admin():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        status = {"timestamp": now_iso(), "version": "3.5.0"}

        with db_context() as db:
            # Active users (brain_states last 24h)
            if is_postgres():
                active = db.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states WHERE created_at > NOW() - INTERVAL '24 hours'"
                ).fetchone()
                obs = db.execute(
                    "SELECT COUNT(*) as cnt FROM agent_observations WHERE created_at > NOW() - INTERVAL '24 hours'"
                ).fetchone()
                total_bs = db.execute("SELECT COUNT(*) as cnt FROM brain_states").fetchone()
                total_profiles = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()
                total_iot = db.execute("SELECT COUNT(*) as cnt FROM iot_sensor_data").fetchone()
                recent_obs = db.execute(
                    "SELECT user_id, observation_type, severity, message, created_at "
                    "FROM agent_observations ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
            else:
                active = db.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM brain_states WHERE created_at > datetime('now', '-24 hours')"
                ).fetchone()
                obs = db.execute(
                    "SELECT COUNT(*) as cnt FROM agent_observations WHERE created_at > datetime('now', '-24 hours')"
                ).fetchone()
                total_bs = db.execute("SELECT COUNT(*) as cnt FROM brain_states").fetchone()
                total_profiles = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()
                total_iot = db.execute("SELECT COUNT(*) as cnt FROM iot_sensor_data").fetchone()
                recent_obs = db.execute(
                    "SELECT user_id, observation_type, severity, message, created_at "
                    "FROM agent_observations ORDER BY created_at DESC LIMIT 5"
                ).fetchall()

        status["users"] = {
            "active_24h": (active['cnt'] or active[0]) if active else 0,
            "total_profiles": (total_profiles['cnt'] or total_profiles[0]) if total_profiles else 0,
        }
        status["brain"] = {
            "total_states": (total_bs['cnt'] or total_bs[0]) if total_bs else 0,
        }
        status["agent_loop"] = {
            "observations_24h": (obs['cnt'] or obs[0]) if obs else 0,
            "recent": [dict(r) for r in (recent_obs or [])],
        }
        status["iot"] = {
            "total_readings": (total_iot['cnt'] or total_iot[0]) if total_iot else 0,
        }
        status["channels"] = {
            "chat": True,
            "twilio": bool(os.environ.get('TWILIO_ACCOUNT_SID')),
            "whatsapp": bool(os.environ.get('TWILIO_PHONE_NUMBER')),
            "push": bool(os.environ.get('VAPID_PUBLIC_KEY')),
            "azure_tts": bool(os.environ.get('AZURE_SPEECH_KEY')),
        }
        status["scheduler"] = {
            "agent_loop": "every 5 min",
            "morning_checkin": "daily 8:00",
            "daily_cleanup": "daily 3:00",
            "reminders": "every 5 min",
            "telemed": "every 5 min",
        }

        return jsonify(status), 200
    except Exception as e:
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
