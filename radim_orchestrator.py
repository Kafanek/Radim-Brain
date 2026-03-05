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
        record_interaction as _orch_record,
        detect_mood as _orch_detect_mood
    )
    _ORCH_MEMORY_AVAILABLE = True
except ImportError:
    _ORCH_MEMORY_AVAILABLE = False

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

# 🏠 System Prompt v3.0 — domácí asistent s časovým kontextem
try:
    from radim_system_prompt import get_radim_prompt as _sys_get_prompt
    _ORCH_SYS_PROMPT = True
except ImportError:
    _ORCH_SYS_PROMPT = False

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
# KONFIGURACE
# ============================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WP_URL = os.environ.get('WP_URL', 'https://dev.kafanek.com')
WP_USER = os.environ.get('WP_USER')
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD')

# ============================================
# ČESKÉ STÁTNÍ SVÁTKY
# ============================================
_CZECH_HOLIDAYS = {
    (1, 1): "Nový rok / Den obnovy samostatného českého státu",
    (5, 1): "Svátek práce",
    (5, 8): "Den vítězství",
    (7, 5): "Den slovanských věrozvěstů Cyrila a Metoděje",
    (7, 6): "Den upálení mistra Jana Husa",
    (9, 28): "Den české státnosti",
    (10, 28): "Den vzniku samostatného československého státu",
    (11, 17): "Den boje za svobodu a demokracii",
    (12, 24): "Štědrý den",
    (12, 25): "1. svátek vánoční",
    (12, 26): "2. svátek vánoční",
}

def _build_time_context():
    """Sestaví časový kontext pro system prompt (den, hodina, svátek)."""
    try:
        now = datetime.now()
        hour = now.hour

        if 5 <= hour < 12:
            time_of_day = "Je ráno"
        elif 12 <= hour < 18:
            time_of_day = "Je odpoledne"
        elif 18 <= hour < 22:
            time_of_day = "Je večer"
        else:
            time_of_day = "Je noc"

        day_names = ['pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota', 'neděle']
        month_names = ['ledna', 'února', 'března', 'dubna', 'května', 'června',
                       'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']

        # Jmeniny — reuse z claude_routes pokud dostupné
        nameday = "neznámý"
        try:
            from claude_routes import NAMEDAY_CALENDAR
            nameday = NAMEDAY_CALENDAR.get(now.month, {}).get(now.day, "neznámý")
        except ImportError:
            pass

        # Státní svátky
        holiday = _CZECH_HOLIDAYS.get((now.month, now.day), "")
        holiday_note = f"\nDnes je státní svátek: {holiday}." if holiday else ""

        return (f"{time_of_day}. Dnes je {day_names[now.weekday()]} "
                f"{now.day}. {month_names[now.month - 1]} {now.year}. "
                f"Svátek má {nameday}.{holiday_note}")
    except Exception as e:
        print(f"Time context warning: {e}")
        return ""

def _get_dynamic_system_prompt(mode='senior'):
    """Dynamický system prompt s časovým kontextem a rolí asistenta."""
    if _ORCH_SYS_PROMPT:
        try:
            user_type = 'senior' if mode == 'senior' else mode
            if mode == 'rodina':
                user_type = 'caregiver'
            elif mode == 'technik':
                user_type = 'academic'
            return _sys_get_prompt(
                mode='full',
                user_type=user_type,
                time_context=_build_time_context()
            )
        except Exception as e:
            print(f"Dynamic prompt warning: {e}")
    return RADIM_WHATSAPP_PROMPT  # Fallback na starý statický prompt

# ============================================
# RADIM WHATSAPP SYSTEM PROMPT (fallback)
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
MEDICATION_KEYWORDS = ['lék', 'léky', 'tableta', 'tablety', 'prášek', 'prášky', 'prednison',
                       'vzal jsem', 'bral jsem', 'zapomněl', 'medikace', 'dávka', 'dávku',
                       'ibuprofen', 'paralen', 'aspirin', 'inzulín']
HEALTH_KEYWORDS = ['bolí', 'nemohu', 'špatně', 'doktor', 'nemocnice', 'unavený']
SAFETY_KEYWORDS = ['spadl', 'pád', 'nemohu dýchat', 'bolest na hrudi', 'záchranka', '155', '112', 'panika']
STORY_KEYWORDS = ['příběh', 'story', 'instagram', 'facebook', 'pozvánka']

def detect_intent(message):
    """Detekce záměru ze zprávy — safety > medication > health > task > story > chat"""
    msg_lower = message.lower()

    for word in SAFETY_KEYWORDS:
        if word in msg_lower:
            return 'safety'

    for word in MEDICATION_KEYWORDS:
        if word in msg_lower:
            return 'medication'

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
def call_gemini_whatsapp(message, context=None, mode='senior', personalized_prompt='', history=None, anticipation_prompt='', gen_config=None):
    """Volání Gemini s WhatsApp promptem + personalizace + historie + rytmus"""
    if not GEMINI_API_KEY:
        return None, None

    try:
        # 🏠 Dynamický system prompt s časem, rolí, kontextem
        system = _get_dynamic_system_prompt(mode)

        # 🧠 Add personalized prompt from memory (name, interests, style, mood)
        if personalized_prompt:
            system += personalized_prompt

        # 🎵 Add anticipation-driven text rhythm instructions
        if anticipation_prompt:
            system += anticipation_prompt

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

        # Generation config — adjusted by Anticipation Engine
        temperature = gen_config["temperature"] if gen_config else 0.7
        max_tokens = gen_config["max_tokens"] if gen_config else 500

        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
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

        # 📋 Load pending tasks context for AI awareness
        if _ORCH_TASK_SERVICE:
            try:
                tasks_ctx = _ts_context(user_id)
                if tasks_ctx:
                    personalized += tasks_ctx
            except Exception as tc_err:
                print(f"Tasks context warning: {tc_err}")

        # 🎵 Text Rhythm: matematika → styl textu
        anticipation_prompt = ''
        anticipation_meta = None
        gen_config = None
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
                print(f"Text rhythm warning (non-fatal): {tr_err}")

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
                        scheduled_date=payload.get('date'),
                        description=payload.get('description')
                    )
                    if task:
                        action_json['created_task'] = task
                        print(f"📋 AI created task: #{task['id']} '{task['title']}'")

                elif action_type == 'log_health':
                    _ts_log_med(
                        user_id=user_id,
                        medication_name=payload.get('medication', payload.get('name', 'nespecifikováno')),
                        dosage=payload.get('dosage'),
                        notes=payload.get('notes', message[:200])
                    )
                    print(f"💊 AI logged medication for {user_id}")
            except Exception as act_err:
                print(f"Action processing warning: {act_err}")

        # 🧠 Record interaction to memory (save history + update learning)
        if _ORCH_MEMORY_AVAILABLE and text_response != "Promiňte, zkuste to za chvíli. 🙏":
            try:
                _orch_record(user_id, message, text_response)
            except Exception as rec_err:
                print(f"Memory record warning: {rec_err}")

        result = {
            'success': True,
            'response': text_response,
            'radim_action': action_json,
            'intent': intent,
            'mode': mode,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }
        if anticipation_meta:
            result['anticipation'] = anticipation_meta
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@radim_bp.route('/api/radim/tasks', methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
@require_auth
def radim_tasks():
    """📋 Task management endpoint — reálná persistentní implementace"""
    if request.method == 'OPTIONS':
        return '', 204

    auth_user = getattr(g, 'auth_user', None) or {}
    user_id = str(auth_user.get('id', '')) or request.args.get('user_id', 'default-senior')

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

    auth_user = getattr(g, 'auth_user', None) or {}
    user_id = str(auth_user.get('id', '')) or request.args.get('user_id', 'default-senior')

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
