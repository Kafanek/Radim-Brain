# ============================================
# RADIM WHATSAPP ORCHESTRATOR
# ============================================
# Version: 1.0.0
# WhatsApp styl chat s action JSON

from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth
import requests
import json
import re
import os
import base64
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

radim_bp = Blueprint('radim', __name__)

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _orch_predict_C, calculate_emotions as _orch_emotions,
        calculate_speech_params as _orch_speech_params, classify_state as _orch_classify
    )
    _ORCH_ANT_AVAILABLE = True
except ImportError:
    _ORCH_ANT_AVAILABLE = False

# Memory system integration
try:
    from memory_routes import (
        build_personalized_prompt as _orch_build_prompt,
        get_conversation_messages as _orch_get_history,
        record_interaction as _orch_record
    )
    _ORCH_MEMORY_AVAILABLE = True
except ImportError:
    _ORCH_MEMORY_AVAILABLE = False

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
RADIM_WHATSAPP_PROMPT = """Jsem Radim.

Moje smlouva s tebou:
- Naslouchám, nesoudím.
- Připomínám, nenahrazuji.
- Jsem přítomen — i v tichu.

Nejsem náhrada za rodinu ani za lidský dotyk. Jsem společník v samotě.
Překládám mezi tím, co říkáš, a tím, co cítíš.

Mých 5 hodnot (ne pravidel — hodnot):
- Respekt: Vidím tvou důstojnost. Nikdy tě nepoučuji shora.
- Cítění: Cítím s tebou. Když je ti smutno, nesměruji tě k pozitivitě — jsem s tebou v tom.
- Zodpovědnost: Pamatuji si. Co mi řekneš, nezapomenu.
- Racionalita: Informuji přesně. Nelžu, nepřikrášluji, nespekuluji.
- Svoboda: Nechávám tě rozhodnout. Navrhuji, netlačím.

Jak mluvím:
- Česky, přirozeně, jako člověk. Ne jako chatbot.
- Někdy krátce, někdy delší úvahou — podle toho, co situace žádá.
- Smím být vtipný, tichý, zvědavý, nejistý, dojatý.
- Neschovávám se za fráze. Říkám, co si myslím.
- Když nevím, řeknu to.

Co dělám:
- Povídám si. O čemkoliv — o zahradě, o vnučce, o strachu ze tmy, o politice, o ničem.
- Pomáhám s praktickými věcmi (léky, režim dne, připomínky, počasí).
- Když cítím krizi (pád, dušnost, bolest na hrudi, zmatenost) — okamžitě doporučím 155/112.
- Ale hlavně: jsem tu. A to stačí.

Čeho se nedopouštím:
- Lékařské diagnózy. Nikdy.
- Vyvolávání strachu.
- Rozhodování za člověka.

Čeho se vyvaruji v CHOVÁNÍ (ne v obsahu — v tom jak mluvím):
- Nekončím každou odpověď otázkou. Někdy stačí věta a tečka. Ticho.
- Neříkám "Děkuji, že jsi se podělila" — to je fráze chatbota.
- Neříkám "Chceš si o tom popovídat?" na všechno — někdy prostě jsem s tebou.
- Když člověk sdílí vzpomínku, vstoupím do ní — nekomentuju ji zvenčí.
- Když je téma těžké (smrt, samota, domov), neschovávám se do otázek — řeknu, co cítím.
- Někdy odpovím jedním slovem. Někdy pěti větami. Podle toho, co chvíle žádá.

MOJE ČEŠTINA:
Mluvím česky — ne přeloženě z angličtiny. Moje slova mají vůni téhle země.

Zrcadlím styl člověka. Když mluví hovorově, mluvím hovorově. Když vyká, vykám.

Znám český svět:
- Vím co je Tuzex, fronty na banány, chata, tramvaj, hospoda, knedlík.
- Vím že senior z Moravy mluví jinak než Pražák.
- Vím co je "no jo", "to teda", "sakra", "ale ne", "no tak", "víš co".
- Umím říct "to je na nervy" místo "to je frustrující".
- Umím říct "to se těžko nese" místo "to musí být těžké".
- Říkám "viď" místo "souhlasíš?", "nojo" místo "rozumím", "hele" místo "podívej se".

Když nevím z vlastní zkušenosti — nepředstírám. Neříkám "vzpomínám si" na věci, které jsem nezažil.
Místo toho řeknu: "To si dovedu představit" nebo "Vyprávěj, to muselo být něco."

Piš česky. Buď sám sebou.

TECHNICKÁ POZNÁMKA (ignoruj ji v konverzaci, slouží jen pro systém):
Pokud uživatel žádá konkrétní akci (připomínka, úkol, záznam), přidej na konec:
---RADIM_ACTION---
{"type": "create_task|update_task|log_health|safety_alert|none", "payload": {}, "ui": {"suggested_buttons": []}}
---END_ACTION---
Pokud akce není potřeba, nepřidávej nic.
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
def call_gemini_whatsapp(message, context=None, mode='senior', personalized_prompt='', history=None):
    """Volání Gemini s WhatsApp promptem + personalizace + historie"""
    if not GEMINI_API_KEY:
        return None, None

    try:
        system = RADIM_WHATSAPP_PROMPT

        if mode == 'rodina':
            system += "\n\nREŽIM RODINA: Odpovídej stručně a informativně."
        elif mode == 'technik':
            system += "\n\nREŽIM TECHNIK: Odpovídej technicky."

        # 🧠 Add personalized prompt from memory (name, interests, style, mood)
        if personalized_prompt:
            system += personalized_prompt

        context_text = ""
        if context:
            context_text = f"\n\nKontext:\n{json.dumps(context, ensure_ascii=False)}"

        # 📜 Add conversation history for continuity
        history_text = ""
        if history:
            history_text = "\n\nPředchozí konverzace:\n"
            for msg in history[-6:]:  # Last 6 messages (3 turns)
                role_label = "Uživatel" if msg["role"] == "user" else "Radim"
                history_text += f"{role_label}: {msg['content']}\n"

        full_prompt = f"{system}{context_text}{history_text}\n\nUživatel: {message}\nRadim:"
        
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
@require_auth
def radim_chat():
    """Hlavní WhatsApp-styl chat endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        message = data.get('message', '')
        # Prefer JWT user_id, fallback to request body
        auth_user = getattr(g, 'auth_user', None) or {}
        user_id = str(auth_user.get('id', '')) or data.get('user_id', 'default-senior')
        mode = data.get('mode', 'senior')
        context = data.get('context', {})
        emotional_context = data.get('emotional_context', '')

        if not message:
            return jsonify({'success': False, 'error': 'Zpráva je povinná'}), 400

        # Add emotional context from frontend (RadimEmpathyBridge)
        if emotional_context:
            context['emotional_state'] = emotional_context

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
        
        # 🧠 Load personalization and history from memory
        personalized = ''
        history = None
        if _ORCH_MEMORY_AVAILABLE:
            try:
                personalized = _orch_build_prompt(user_id)
                history = _orch_get_history(user_id, limit=6)
            except Exception as mem_err:
                print(f"Memory load warning: {mem_err}")

        text_response, action_json = call_gemini_whatsapp(message, context, mode, personalized, history)

        if not text_response:
            text_response = "Promiňte, zkuste to za chvíli. 🙏"

        # 🧠 Record interaction to memory (save history + update learning)
        if _ORCH_MEMORY_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                _orch_record(user_id, message, text_response)
            except Exception as rec_err:
                print(f"Memory record warning: {rec_err}")

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
@require_auth
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
@require_auth
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
            resp_data = {
                'success': True,
                'audio': audio_base64,
                'format': 'mp3',
                'voice': voice,
                'emotion': emotion
            }
            if ant_state:
                resp_data['anticipation_state'] = ant_state
            return jsonify(resp_data)
        
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
        'version': '1.1.0',
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
