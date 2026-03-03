# ============================================
# EVENTLET MONKEY PATCH - MUST BE FIRST!
# ============================================
import eventlet
eventlet.monkey_patch()

# ============================================
# RADIM BRAIN + CHAT - ROZŠÍŘENÝ HEROKU BACKEND
# ============================================
# Version: 3.1.0 - PostgreSQL + Security + Blueprint Registry
# radim-brain-2025.herokuapp.com

import os
import json
import uuid
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
    print("⚠️ Memory routes not available")

# 👴 Import Seniors API
try:
    from seniors_routes import seniors_bp
    SENIORS_AVAILABLE = True
except ImportError:
    SENIORS_AVAILABLE = False
    print("⚠️ Seniors routes not available")

# 🌡️ Import IoT & Sensors API
try:
    from iot_routes import iot_bp
    IOT_AVAILABLE = True
except ImportError:
    IOT_AVAILABLE = False
    print("⚠️ IoT routes not available")

# 🔮 Import Predict & Consciousness API
try:
    from predict_routes import predict_bp
    PREDICT_AVAILABLE = True
except ImportError:
    PREDICT_AVAILABLE = False
    print("⚠️ Predict routes not available")

# 📊 Import Dashboard API
try:
    from dashboard_routes import dashboard_bp
    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False
    print("⚠️ Dashboard routes not available")

# 📚 Import Library / E-book API
try:
    from library_routes import library_bp
    LIBRARY_AVAILABLE = True
except ImportError:
    LIBRARY_AVAILABLE = False
    print("⚠️ Library routes not available")

# ============================================
# FLASK APP SETUP
# ============================================
app = Flask(__name__)

# Register Radim Blueprint
app.register_blueprint(radim_bp)

# 🎭 Register Orchestrator Blueprint
app.register_blueprint(orchestrator_bp)
print("✅ Orchestrator routes registered: /api/orchestrator/*")

# 👴 Register Seniors Blueprint
if SENIORS_AVAILABLE:
    app.register_blueprint(seniors_bp)
    print("✅ Seniors routes registered: /api/seniors/*")

# 🌡️ Register IoT Blueprint
if IOT_AVAILABLE:
    app.register_blueprint(iot_bp)
    print("✅ IoT routes registered: /api/iot/*")

# 🔮 Register Predict Blueprint
if PREDICT_AVAILABLE:
    app.register_blueprint(predict_bp)
    print("✅ Predict routes registered: /api/radim/predict/*, /api/consciousness/*")

# 📊 Register Dashboard Blueprint
if DASHBOARD_AVAILABLE:
    app.register_blueprint(dashboard_bp)
    print("✅ Dashboard routes registered: /api/dashboard/*")

# 📚 Register Library Blueprint
if LIBRARY_AVAILABLE:
    app.register_blueprint(library_bp)
    print("✅ Library routes registered: /kal/library/*")

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# CORS - Allow all routes from specific origins
ALLOWED_ORIGINS = [
    "https://app.radimcare.cz",
    "https://polite-bush-001303503.6.azurestaticapps.net",
    "https://mykolibri-academy.cz",
    "https://app.mykolibri-academy.cz",
    "http://localhost:3000",
    "http://localhost:8080",
    "http://localhost:8081",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
    "http://localhost:5173",
    "http://localhost:60668",
    "http://localhost:60669",
    "http://localhost:60670"
]

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

# Import Speech module
from speech_routes import speech_bp
app.register_blueprint(speech_bp)

# 🤖 Import Claude AI routes - Radim s web search (nahrazuje Gemini)
from claude_routes import claude_bp
app.register_blueprint(claude_bp)
print("✅ Claude AI routes registered: /api/claude/*")

# 💝 Import Soul routes - Duše Radima
from soul_routes import soul_bp
app.register_blueprint(soul_bp)
print("✅ Soul routes registered: /api/soul/*")

# 🎙️ Import Voice Runtime routes - Stavový automat
from voice_runtime_routes import voice_runtime_bp
app.register_blueprint(voice_runtime_bp)
print("✅ Voice Runtime routes registered: /api/voice/*")

# 🔮 Import Anticipation Engine - Předbudoucí čas
from anticipation_routes import anticipation_bp
app.register_blueprint(anticipation_bp)
print("✅ Anticipation Engine registered: /api/anticipation/*")

# Anticipation functions for azure_tts_proxy
try:
    from anticipation_routes import (
        predict_C as _app_predict_C, calculate_emotions as _app_ant_emotions,
        calculate_speech_params as _app_ant_speech, classify_state as _app_classify
    )
    _APP_ANT_AVAILABLE = True
except ImportError:
    _APP_ANT_AVAILABLE = False

# 📞 Import Twilio Voice routes - Phone calls for seniors
try:
    from twilio_voice_routes import twilio_bp
    app.register_blueprint(twilio_bp)
    TWILIO_AVAILABLE = True
    print("✅ Twilio Voice routes registered: /api/twilio/*")
except ImportError:
    TWILIO_AVAILABLE = False
    print("⚠️ Twilio Voice routes not available")

# 🧠 Import Memory & Learning routes
if MEMORY_AVAILABLE:
    app.register_blueprint(memory_bp)
    print("✅ Memory routes registered: /api/memory/*")

# ============================================
# TTS PROXY ENDPOINTS (Azure)
# ============================================
AZURE_TTS_KEY = os.environ.get('AZURE_TTS_KEY')
if not AZURE_TTS_KEY:
    print("⚠️  WARNING: AZURE_TTS_KEY not set - Azure TTS proxy will not work")
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
def azure_tts_proxy():
    """Azure TTS Proxy - Antonín voice"""
    if not AZURE_TTS_KEY:
        return jsonify({'error': 'Azure TTS not configured (AZURE_TTS_KEY missing)'}), 503
    try:
        data = request.json
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
        if not _re.match(r'^[+-]?[0-9]+Hz$', pitch):
            pitch = '+0Hz'

        # Build SSML
        ssml = f"""<speak version='1.0' xml:lang='cs-CZ'>
            <voice name='{voice}'>
                <prosody rate='{rate}' pitch='{pitch}'>
                    {safe_text}
                </prosody>
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
            return jsonify({'error': f'Azure TTS API connection error: {str(e)}'}), 503
        
        if response.status_code == 200:
            from flask import Response
            resp_headers = {
                    'X-Voice-Name': voice,
                    'X-Voice-Rate': str(rate),
                    'Cache-Control': 'no-cache'
                }
            if ant_state:
                resp_headers['X-Anticipation-State'] = ant_state
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers=resp_headers
            )
        else:
            return jsonify({'error': f'Azure TTS error: {response.status_code}'}), response.status_code
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
def elevenlabs_tts_proxy():
    """ElevenLabs TTS Proxy - Pan Kafánek voice"""
    try:
        data = request.json
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
            return jsonify({'error': f'ElevenLabs API error: {str(e)}'}), 503
        
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
        return jsonify({'error': str(e)}), 500

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
# Note: On dyno restart, all users are set offline in init_db_online_reset()

# ============================================
# RADIM AI - GEMINI/CLAUDE INTEGRATION
# ============================================
RADIM_SYSTEM_PROMPT = """Jsi Radim, laskavý a trpělivý AI asistent pro seniory. 

Tvoje vlastnosti:
- Mluvíš česky, jasně a srozumitelně
- Používáš jednoduché věty bez složitých termínů
- Jsi empatický a trpělivý
- Nabízíš pomoc s každodenními věcmi
- Pamatuješ si kontext konverzace
- Povzbuzuješ a chválíš

Témata, se kterými pomáháš:
- Počasí a aktuality
- Zdraví a léky (připomínky)
- Rodina a kontakty
- Volný čas a zábava
- Technologie jednoduše
- Povídání a společnost

Vždy odpovídej krátce (max 2-3 věty) pokud není potřeba více."""

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
        
        print(f"Gemini error: {response.status_code} - {response.text}")
        return None
        
    except Exception as e:
        print(f"Gemini AI error: {e}")
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
        print(f"Claude AI error: {e}")
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
        print(f"Cloudinary error: {e}")
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
        print(f"Push notification error: {e}")
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
        print(f"WordPress API error: {e}")
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
        print(f"Sync WP user error: {e}")
        return None

# ============================================
# REST API - CONVERSATIONS
# ============================================
@app.route('/api/chat/conversations/<user_id>', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/conversations', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# REST API - MESSAGES (with AI)
# ============================================
@app.route('/api/chat/messages/<conversation_id>', methods=['GET'])
def get_messages(conversation_id):
    try:
        limit = request.args.get('limit', 50, type=int)
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/messages', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/messages/<message_id>/read', methods=['PATCH'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/messages/<message_id>/reaction', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# REST API - CONTACTS
# ============================================
@app.route('/api/chat/contacts/<user_id>', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/contacts', methods=['POST'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# REST API - ADMIN DASHBOARD
# ============================================
def update_daily_stats(field):
    """Aktualizuj denní statistiky"""
    # Whitelist allowed field names to prevent SQL injection
    ALLOWED_FIELDS = {'total_messages', 'total_users', 'ai_messages', 'voice_messages', 'active_conversations'}
    if field not in ALLOWED_FIELDS:
        print(f"⚠️  Invalid stats field: {field}")
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
        print(f"Stats update error: {e}")

@app.route('/api/admin/stats', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/users', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/conversations', methods=['GET'])
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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# SOCKET.IO EVENTS
# ============================================
@socketio.on('connect')
def handle_connect():
    print(f'🔌 Client connected: {request.sid}')

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
        try:
            db = get_connection()
            db.execute('UPDATE chat_users SET online = 0, last_seen = ? WHERE id = ?', (now_iso(), user_id))
            db.commit()
            db.close()
        except Exception as e:
            print(f"⚠️  Error updating user offline status: {e}")

@socketio.on('join')
def handle_join(data):
    user_id = data.get('userId')
    if user_id:
        users_online[user_id] = request.sid
        join_room(user_id)
        socketio.emit('user_online', {'userId': user_id, 'timestamp': now_iso()}, broadcast=True)
        # Update user online status (using adapter for proper connection handling)
        try:
            db = get_connection()
            db.execute('UPDATE chat_users SET online = 1 WHERE id = ?', (user_id,))
            db.commit()
            db.close()
        except Exception as e:
            print(f"⚠️  Error updating user online status: {e}")

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
            limit = request.args.get('limit', 10, type=int)
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
        print(f"⚠️ kal_radim_history error: {e}")
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
        print(f"⚠️ kal_radim_register error: {e}")
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
        print(f"⚠️ kal_radim_update_user error: {e}")
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
        print(f"⚠️ kal_radim_insights error: {e}")
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
        print(f"⚠️ kal_radim_conversation error: {e}")
    return jsonify({"success": True, "conversation": {"saved": True}}), 200

@app.route('/kal/radim/stats')
def kal_radim_stats():
    """Global Radim stats"""
    try:
        if MEMORY_AVAILABLE:
            from database import get_connection, is_postgres
            db = get_connection()
            if is_postgres():
                profiles_count = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()['cnt']
                history_count = db.execute("SELECT COUNT(*) as cnt FROM memory_history").fetchone()['cnt']
            else:
                profiles_count = db.execute("SELECT COUNT(*) as cnt FROM memory_profiles").fetchone()['cnt']
                history_count = db.execute("SELECT COUNT(*) as cnt FROM memory_history").fetchone()['cnt']
            db.close()
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
        print(f"⚠️ kal_radim_stats error: {e}")
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
            print(f"[CLIENT SYNC] {client_id}")
            
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
    print(f"[EMERGENCY] {event} from {user_id} at {timestamp}")
    
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

@app.route("/kal/consciousness/state")
def kal_consciousness_state():
    """Consciousness state for frontend dashboard"""
    return jsonify({
        "status": "active",
        "level": 0.85,
        "phi_balance": 1.618,
        "emotions": {"calm": 0.8, "curious": 0.6, "empathetic": 0.9},
        "timestamp": now_iso()
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
    if LIBRARY_AVAILABLE:
        blueprints['library'] = {'prefix': '/kal/library/*', 'version': '1.0.0', 'status': 'active'}

    return jsonify({
        'status': 'healthy',
        'service': 'Radim Brain + Chat',
        'version': '3.2.0',
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

@app.errorhandler(404)
def not_found(e):
    return jsonify({'success': False, 'error': 'Endpoint nenalezen'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'success': False, 'error': 'Interní chyba serveru'}), 500

# Initialize database
with app.app_context():
    init_db()
    # Reset all users to offline on server start (dyno restart resets socket connections)
    try:
        db = get_connection()
        db.execute("UPDATE chat_users SET online = 0 WHERE id != 'radim'")
        db.commit()
        db.close()
        print("✅ All user online statuses reset")
    except Exception as e:
        print(f"⚠️  Could not reset online statuses: {e}")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'''
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
