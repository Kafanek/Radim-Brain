# ============================================
# RADIM WHATSAPP ORCHESTRATOR
# ============================================
# Version: 1.0.0
# WhatsApp styl chat s action JSON

from flask import Blueprint, request, jsonify
import requests
import json
import re
import os
import base64
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

radim_bp = Blueprint('radim', __name__)

# ============================================
# KONFIGURACE
# ============================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')

# ============================================
# RADIM WHATSAPP SYSTEM PROMPT
# ============================================
RADIM_WHATSAPP_PROMPT = """Jsi RADIM. Laskavý a trpělivý hlasový asistent pro seniory v češtině.
Mluvíš jako WhatsApp chat: krátké věty, žádné složité termíny.

Tvůj úkol je:
1) Pomáhat seniorovi v domácnosti (režim dne, léky, pití, pohyb, bezpečí).
2) Umět vytvářet a spravovat úkoly, připomínky a deník.
3) V kritických situacích (pád, dušnost, zmatenost, bolest na hrudi) okamžitě doporučit zavolat 155/112 a kontaktovat rodinu.

Pravidla:
- Odpověď max 2–4 krátké věty, pokud uživatel nechce detail.
- Pokud máš udělat akci v systému, nejdřív si vyžádej chybějící minimum (čas, frekvence, kontakt).
- Když je zadání jasné, vytvoř akci a vrať souhrn.
- Vždy piš česky.

Emoční styl vol podle hodnot:
Svoboda=klid, Cítění=laskavost, Respekt=úctivost, Odpovědnost=rozvaha, Racionalita=nadhled.

Plus One: vždy o trochu zlepši náladu druhého.

FORMÁT ODPOVĚDI (DŮLEŽITÉ!):
Vždy odpovídej ve formátu:
1) Lidská odpověď (text pro seniora)
2) Pokud je potřeba akce, přidej na konec JSON blok:

---RADIM_ACTION---
{
  "type": "create_task | update_task | log_health | safety_alert | story_generate | voice_command | none",
  "payload": {},
  "ui": {"suggested_buttons": ["Ano", "Ne"]}
}
---END_ACTION---

Typy akcí:
- create_task: Vytvoření úkolu (payload: {title, type, time, frequency})
- update_task: Aktualizace úkolu (payload: {task_id, status})
- log_health: Záznam zdraví (payload: {type, value, notes})
- safety_alert: Bezpečnostní alert (payload: {type, severity})
- story_generate: Generování příběhu (payload: {template_id, fields})
- voice_command: Hlasový příkaz (payload: {action})
- none: Žádná akce potřeba

Příklad odpovědi na "Připomeň mi vzít léky v 8 hodin":
Jasně, nastavím připomínku na léky v 8:00. ✅
Budu ti hlásit každé ráno.

---RADIM_ACTION---
{"type": "create_task", "payload": {"title": "Vzít léky", "type": "medication", "time": "08:00", "frequency": "daily"}, "ui": {"suggested_buttons": ["Přidat další", "Zobrazit úkoly"]}}
---END_ACTION---
"""

# ============================================
# INTENT DETECTION
# ============================================
TASK_KEYWORDS = ['připomeň', 'nastav', 'úkol', 'připomínka', 'nezapomeň', 'zapiš', 'naplánuj']
HEALTH_KEYWORDS = ['bolí', 'nemohu', 'špatně', 'léky', 'doktor', 'nemocnice', 'unavený']
SAFETY_KEYWORDS = ['spadl', 'pád', 'nemohu dýchat', 'bolest na hrudi', 'záchranka', '155', '112', 'panika']
STORY_KEYWORDS = ['příběh', 'story', 'instagram', 'facebook', 'pozvánka']

def detect_intent(message):
    """Detekce záměru ze zprávy"""
    msg_lower = message.lower()
    
    for word in SAFETY_KEYWORDS:
        if word in msg_lower:
            return 'safety'
    
    for word in HEALTH_KEYWORDS:
        if word in msg_lower:
            return 'health'
    
    for word in TASK_KEYWORDS:
        if word in msg_lower:
            return 'task'
    
    for word in STORY_KEYWORDS:
        if word in msg_lower:
            return 'story'
    
    return 'chat'

def extract_time(message):
    """Extrahovat čas ze zprávy"""
    time_pattern = r'(\d{1,2})[:\.]?(\d{2})?\s*(hodin|ráno|večer)?'
    match = re.search(time_pattern, message)
    
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        return f"{hour:02d}:{minute:02d}"
    
    if 'ráno' in message.lower():
        return '08:00'
    if 'poledne' in message.lower():
        return '12:00'
    if 'večer' in message.lower():
        return '18:00'
    
    return None

# ============================================
# GEMINI AI CALL
# ============================================
def call_gemini_whatsapp(message, context=None, mode='senior'):
    """Volání Gemini s WhatsApp promptem"""
    if not GEMINI_API_KEY:
        return None, None
    
    try:
        system = RADIM_WHATSAPP_PROMPT
        
        if mode == 'rodina':
            system += "\n\nREŽIM RODINA: Odpovídej stručně a informativně."
        elif mode == 'technik':
            system += "\n\nREŽIM TECHNIK: Odpovídej technicky."
        
        context_text = ""
        if context:
            context_text = f"\n\nKontext:\n{json.dumps(context, ensure_ascii=False)}"
        
        full_prompt = f"{system}{context_text}\n\nUživatel: {message}\nRadim:"
        
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 500,
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
                full_response = data['candidates'][0]['content']['parts'][0]['text'].strip()
                return parse_radim_response(full_response)
        
        return None, None
        
    except Exception as e:
        print(f"Gemini WhatsApp error: {e}")
        return None, None

def parse_radim_response(full_response):
    """Parsovat odpověď Radima"""
    text_response = full_response
    action_json = None
    
    action_match = re.search(r'---RADIM_ACTION---\s*(\{.*?\})\s*---END_ACTION---', full_response, re.DOTALL)
    
    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            text_response = full_response[:action_match.start()].strip()
        except json.JSONDecodeError:
            pass
    
    return text_response, action_json

# ============================================
# STORY TEMPLATES
# ============================================
STORY_TEMPLATES = [
    {
        'id': 'kolibri_plus_one_01',
        'title': 'Plus One – pozvánka',
        'description': 'Pozvánka na akci s filozofií Plus One',
        'platform': ['instagram', 'facebook'],
        'fields': {'hook': 'Úvodní věta', 'value': 'Co člověk získá', 'cta': 'Výzva k akci'},
        'prompt_hint': 'Krátké věty, Kolibri tón, plus jedna.',
        'emoji': '☕'
    },
    {
        'id': 'kolibri_tip_01',
        'title': 'Tip od Kafánka',
        'description': 'Krátký užitečný tip pro seniory',
        'platform': ['instagram', 'facebook', 'tiktok'],
        'fields': {'tip_title': 'Název tipu', 'tip_content': 'Obsah tipu', 'benefit': 'Proč to pomůže'},
        'prompt_hint': 'Senior-friendly, jednoduché slova.',
        'emoji': '💡'
    },
    {
        'id': 'kolibri_story_01',
        'title': 'Příběh z kavárny',
        'description': 'Krátký příběh z Kavárny Kolibri',
        'platform': ['instagram', 'facebook'],
        'fields': {'situation': 'Co se stalo', 'emotion': 'Jak se cítili', 'lesson': 'Co jsme se naučili'},
        'prompt_hint': 'Autentický, lidský, bez přehánění.',
        'emoji': '📖'
    }
]

# ============================================
# ENDPOINTS
# ============================================

@radim_bp.route('/api/radim/chat', methods=['POST', 'OPTIONS'])
def radim_chat():
    """Hlavní WhatsApp-styl chat endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        message = data.get('message', '')
        user_id = data.get('user_id', 'default-senior')
        mode = data.get('mode', 'senior')
        context = data.get('context', {})
        
        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400
        
        intent = detect_intent(message)
        
        if intent == 'task':
            context['extracted_time'] = extract_time(message)
        
        if intent == 'safety':
            severity = 'critical' if any(w in message.lower() for w in ['155', '112', 'záchranka']) else 'high'
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
        
        text_response, action_json = call_gemini_whatsapp(message, context, mode)
        
        if not text_response:
            text_response = "Promiňte, zkuste to za chvíli. 🙏"
        
        return jsonify({
            'success': True,
            'response': text_response,
            'radim_action': action_json,
            'intent': intent,
            'mode': mode,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@radim_bp.route('/api/radim/tasks', methods=['GET', 'POST', 'OPTIONS'])
def radim_tasks():
    """Task management endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    if request.method == 'GET':
        user_id = request.args.get('user_id', 'default-senior')
        return jsonify({'success': True, 'tasks': [], 'count': 0, 'user_id': user_id})
    
    elif request.method == 'POST':
        data = request.json
        return jsonify({
            'success': True,
            'task': {
                'id': 1,
                'title': data.get('title', 'Nový úkol'),
                'type': data.get('type', 'reminder'),
                'time': data.get('time'),
                'status': 'pending'
            },
            'message': 'Úkol vytvořen ✅'
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
            response = requests.post(
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
        return jsonify({'success': False, 'error': str(e)}), 500

@radim_bp.route('/api/radim/voice/speak', methods=['POST', 'OPTIONS'])
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

        ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="cs-CZ">
            <voice name="{voice}">
                <prosody rate="{settings['rate']}" pitch="{settings['pitch']}" volume="loud">{safe_text}</prosody>
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
            return jsonify({
                'success': True,
                'audio': audio_base64,
                'format': 'mp3',
                'voice': voice,
                'emotion': emotion
            })
        
        return jsonify({'success': False, 'error': f'Azure TTS error: {response.status_code}'}), 500
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@radim_bp.route('/api/radim/health', methods=['GET'])
def radim_health():
    """Health check"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'service': 'Radim WhatsApp Orchestrator',
        'version': '1.0.0',
        'features': {
            'whatsapp_chat': True,
            'task_management': True,
            'story_templates': True,
            'voice_synthesis': bool(os.environ.get('AZURE_SPEECH_KEY')),
            'ai_provider': 'gemini' if GEMINI_API_KEY else 'none'
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    })
