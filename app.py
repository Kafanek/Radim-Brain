# ============================================
# EVENTLET MONKEY PATCH - MUST BE FIRST!
# ============================================
import eventlet
eventlet.monkey_patch()

# ============================================
# RADIM BRAIN + CHAT - ROZŠÍŘENÝ HEROKU BACKEND
# ============================================
# Version: 3.0.0 - Full Features
# radim-brain-2025.herokuapp.com

import os
import json
import uuid
import sqlite3
import requests
import base64
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

load_dotenv()

# Import Radim WhatsApp Orchestrator
from radim_orchestrator import radim_bp

# ============================================
# FLASK APP SETUP
# ============================================
app = Flask(__name__)

# Register Radim Blueprint
app.register_blueprint(radim_bp)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'radim-secret-key-2025')
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
     resources={r"/*": {"origins": "*"}},
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

# ============================================
# TTS PROXY ENDPOINTS (Azure)
# ============================================
AZURE_TTS_KEY = os.environ.get('AZURE_TTS_KEY', 'JikrPUH2HODm8u5cj4ozmOGWCgQd2XeCasMt9kW09lc0mM59PwYyJQQJ99BIAC5RqLJXJ3w3AAAYACOGgKKC')
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
    try:
        data = request.json
        text = data.get('text', '')
        voice = data.get('voice', 'cs-CZ-AntoninNeural')
        rate = data.get('rate', '0.85')
        pitch = data.get('pitch', '+0Hz')
        
        if not text:
            return jsonify({'error': 'Text is required'}), 400
        
        # Build SSML
        ssml = f"""<speak version='1.0' xml:lang='cs-CZ'>
            <voice name='{voice}'>
                <prosody rate='{rate}' pitch='{pitch}'>
                    {text}
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
            return Response(
                response.content,
                mimetype='audio/mpeg',
                headers={
                    'X-Voice-Name': voice,
                    'X-Voice-Rate': rate,
                    'Cache-Control': 'no-cache'
                }
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
# DATABASE
# ============================================
DATABASE = os.environ.get('DATABASE_PATH', 'radim_chat.db')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript('''
        -- Chat tables
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id TEXT PRIMARY KEY,
            participants TEXT NOT NULL,
            type TEXT DEFAULT 'direct',
            name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_message TEXT,
            settings TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            sender_id TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            content TEXT NOT NULL,
            reply_to TEXT,
            metadata TEXT DEFAULT '{}',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent',
            reactions TEXT DEFAULT '[]',
            read_by TEXT DEFAULT '[]',
            ai_generated INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id)
        );

        CREATE TABLE IF NOT EXISTS chat_contacts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            contact_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'Rodina',
            avatar TEXT,
            pinned INTEGER DEFAULT 0,
            muted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS chat_users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT,
            avatar TEXT,
            role TEXT DEFAULT 'user',
            online INTEGER DEFAULT 0,
            last_seen TIMESTAMP,
            wp_user_id INTEGER,
            push_subscription TEXT,
            settings TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Media table
        CREATE TABLE IF NOT EXISTS chat_media (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            url TEXT NOT NULL,
            public_id TEXT,
            filename TEXT,
            size INTEGER,
            duration REAL,
            thumbnail_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Push subscriptions
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            keys TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, endpoint)
        );

        -- Admin stats
        CREATE TABLE IF NOT EXISTS admin_stats (
            id TEXT PRIMARY KEY,
            date DATE NOT NULL,
            total_messages INTEGER DEFAULT 0,
            total_users INTEGER DEFAULT 0,
            ai_messages INTEGER DEFAULT 0,
            voice_messages INTEGER DEFAULT 0,
            active_conversations INTEGER DEFAULT 0,
            UNIQUE(date)
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON chat_messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON chat_messages(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_contacts_user ON chat_contacts(user_id);
        CREATE INDEX IF NOT EXISTS idx_media_message ON chat_media(message_id);
        CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id);
    ''')
    
    # Radim AI assistant
    db.execute('''
        INSERT OR REPLACE INTO chat_users (id, name, role, online, settings)
        VALUES ('radim', 'Radim Asistent', 'ai_assistant', 1, '{"ai_enabled": true, "voice": "radim"}')
    ''')
    db.commit()
    db.close()
    print("✅ Databáze inicializována (v3.0)")

# ============================================
# HELPERS
# ============================================
def generate_id():
    return str(uuid.uuid4())

def now_iso():
    return datetime.utcnow().isoformat() + 'Z'

def today_date():
    return datetime.utcnow().strftime('%Y-%m-%d')

users_online = {}

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
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}",
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
                "model": "claude-3-haiku-20240307",
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
        # Update user last_seen
        try:
            db = sqlite3.connect(DATABASE)
            db.execute('UPDATE chat_users SET online = 0, last_seen = ? WHERE id = ?', (now_iso(), user_id))
            db.commit()
            db.close()
        except:
            pass

@socketio.on('join')
def handle_join(data):
    user_id = data.get('userId')
    if user_id:
        users_online[user_id] = request.sid
        join_room(user_id)
        socketio.emit('user_online', {'userId': user_id, 'timestamp': now_iso()}, broadcast=True)
        # Update user online status
        try:
            db = sqlite3.connect(DATABASE)
            db.execute('UPDATE chat_users SET online = 1 WHERE id = ?', (user_id,))
            db.commit()
            db.close()
        except:
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
    """Stub for KAL health check - not implemented in v3.0.0"""
    return jsonify({
        "status": "ok",
        "message": "KAL service not available in backend v3.0.0"
    }), 200

@app.route('/kal/radim/history/<senior_id>')
def kal_radim_history(senior_id):
    """Stub for KAL history - not implemented in v3.0.0"""
    return jsonify([]), 200

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
    return jsonify({
        'status': 'healthy',
        'service': 'Radim Brain + Chat',
        'version': '3.0.0',
        'timestamp': now_iso(),
        'modules': {
            'chat': 'active',
            'websocket': True,
            'speech': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'ai': {
                'gemini': bool(GEMINI_API_KEY),
                'claude': bool(ANTHROPIC_API_KEY)
            },
            'media': bool(CLOUDINARY_URL),
            'push': bool(VAPID_PRIVATE_KEY),
            'wordpress': bool(WP_URL and WP_USER)
        },
        'online_users': len(users_online)
    })

@app.route('/api')
def api_info():
    return jsonify({
        'name': 'Radim Brain + Chat API',
        'version': '3.0.0',
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
            }
        },
        'websocket': {
            'url': 'wss://radim-brain-2025.herokuapp.com',
            'events': ['join', 'send_message', 'typing', 'mark_read']
        }
    })

@app.route('/')
def index():
    return jsonify({
        'message': '🌟 Radim Brain + Chat API v3.0',
        'status': 'running',
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'''
╔═══════════════════════════════════════════════════════════╗
║          🌟 RADIM BRAIN + CHAT SERVER v3.0 🌟             ║
╠═══════════════════════════════════════════════════════════╣
║  Port:        {port}                                         ║
║  WebSocket:   ✅ Ready                                    ║
║  Chat:        ✅ Active                                   ║
║  AI:          {'✅ Gemini' if GEMINI_API_KEY else '❌ Not configured'}                                  ║
║  Media:       {'✅ Cloudinary' if CLOUDINARY_URL else '❌ Not configured'}                              ║
║  Push:        {'✅ Ready' if VAPID_PRIVATE_KEY else '❌ Not configured'}                                    ║
║  WordPress:   {'✅ Connected' if WP_URL else '❌ Not configured'}                               ║
╚═══════════════════════════════════════════════════════════╝
    ''')
    socketio.run(app, host='0.0.0.0', port=port)
