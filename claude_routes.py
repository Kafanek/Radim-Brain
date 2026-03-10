"""
🤖 CLAUDE AI ROUTES - Flask Blueprint
Kompletní AI služba s web search pro seniory
Nahrazuje Gemini - chat, zprávy, počasí, kvíz, příběhy

Version: 1.1.0 (Flask) + Emotion Analysis
"""

import os
import json
import re
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth, optional_auth

# Anthropic Claude SDK
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️ Anthropic SDK not installed. Run: pip install anthropic")

logger = logging.getLogger(__name__)

# Intent Resolver (v272 — local NLU)
try:
    from intent_resolver import resolve_intent as _cl_resolve_intent
    _CL_INTENT_RESOLVER = True
except ImportError:
    _CL_INTENT_RESOLVER = False

# Anticipation Engine integration
try:
    from anticipation_routes import (
        predict_C as _cl_predict_C, calculate_emotions as _cl_ant_emotions,
        calculate_speech_params as _cl_ant_speech, classify_state as _cl_classify,
        C_HARMONY as _CL_C_HARMONY, C_ALERT as _CL_C_ALERT, C_MAX as _CL_C_MAX
    )
    _CL_ANT_AVAILABLE = True
except ImportError:
    _CL_ANT_AVAILABLE = False

# Memory persistence
try:
    from memory_routes import record_interaction, get_conversation_messages, get_user_context, get_personalized_system_prompt, detect_mood as _cl_detect_mood
    _CL_MEMORY_AVAILABLE = True
except ImportError:
    _CL_MEMORY_AVAILABLE = False

# 🎵 Text Rhythm Engine — matematika řídí styl textu
try:
    from text_rhythm import (
        estimate_C_alpha_from_text as _cl_tr_estimate,
        calculate_text_params as _cl_tr_calc,
        build_anticipation_prompt as _cl_tr_prompt,
        get_anticipation_metadata as _cl_tr_meta,
        get_adjusted_generation_config as _cl_tr_gen_config
    )
    _CL_TEXT_RHYTHM = True
except ImportError:
    _CL_TEXT_RHYTHM = False

# DB access for memory notes
try:
    from database import get_connection, is_postgres
    _CL_DB_AVAILABLE = True
except ImportError:
    _CL_DB_AVAILABLE = False

# Flask Blueprint
claude_bp = Blueprint('claude', __name__, url_prefix='/api/claude')

# ============================================================================
# CONFIGURATION
# ============================================================================

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
CLAUDE_MODEL = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-6-20250514')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# České jmeniny - kompletní kalendář
NAMEDAY_CALENDAR = {
    1: {1: 'Nový rok', 2: 'Karina', 3: 'Radmila', 4: 'Diana', 5: 'Dalimil', 6: 'Tři králové', 7: 'Vilma', 8: 'Čestmír', 9: 'Vladan', 10: 'Břetislav', 11: 'Bohdana', 12: 'Pravoslav', 13: 'Edita', 14: 'Radovan', 15: 'Alice', 16: 'Ctirad', 17: 'Drahoslav', 18: 'Vladislav', 19: 'Doubravka', 20: 'Ilona', 21: 'Běla', 22: 'Slavomír', 23: 'Zdeněk', 24: 'Milena', 25: 'Miloš', 26: 'Zora', 27: 'Ingrid', 28: 'Otýlie', 29: 'Zdislava', 30: 'Robin', 31: 'Marika'},
    2: {1: 'Hynek', 2: 'Nela', 3: 'Blažej', 4: 'Jarmila', 5: 'Dobromila', 6: 'Vanda', 7: 'Veronika', 8: 'Milada', 9: 'Apolena', 10: 'Mojmír', 11: 'Božena', 12: 'Slavěna', 13: 'Věnceslav', 14: 'Valentýn', 15: 'Jiřina', 16: 'Ljuba', 17: 'Miloslava', 18: 'Gizela', 19: 'Patrik', 20: 'Oldřich', 21: 'Lenka', 22: 'Petr', 23: 'Svatopluk', 24: 'Matěj', 25: 'Liliana', 26: 'Dorota', 27: 'Alexandr', 28: 'Lumír', 29: 'Horymír'},
    3: {1: 'Bedřich', 2: 'Anežka', 3: 'Kamil', 4: 'Stela', 5: 'Kazimír', 6: 'Miroslav', 7: 'Tomáš', 8: 'Gabriela', 9: 'Františka', 10: 'Viktorie', 11: 'Anděla', 12: 'Řehoř', 13: 'Růžena', 14: 'Rút', 15: 'Ida', 16: 'Elena', 17: 'Vlastimil', 18: 'Eduard', 19: 'Josef', 20: 'Světlana', 21: 'Radek', 22: 'Leona', 23: 'Ivona', 24: 'Gabriel', 25: 'Marián', 26: 'Emanuel', 27: 'Dita', 28: 'Soňa', 29: 'Taťána', 30: 'Arnošt', 31: 'Kvido'},
    4: {1: 'Hugo', 2: 'Erika', 3: 'Richard', 4: 'Ivana', 5: 'Miroslava', 6: 'Vendula', 7: 'Heřman', 8: 'Ema', 9: 'Dušan', 10: 'Darja', 11: 'Izabela', 12: 'Julius', 13: 'Aleš', 14: 'Vincenc', 15: 'Anastázie', 16: 'Irena', 17: 'Rudolf', 18: 'Valérie', 19: 'Rostislav', 20: 'Marcela', 21: 'Alexandra', 22: 'Evženie', 23: 'Vojtěch', 24: 'Jiří', 25: 'Marek', 26: 'Oto', 27: 'Jaroslav', 28: 'Vlastislav', 29: 'Robert', 30: 'Blahoslav'},
    5: {1: 'Svátek práce', 2: 'Zikmund', 3: 'Alexej', 4: 'Květoslav', 5: 'Klaudie', 6: 'Radoslav', 7: 'Stanislav', 8: 'Den vítězství', 9: 'Ctibor', 10: 'Blažena', 11: 'Svatava', 12: 'Pankrác', 13: 'Servác', 14: 'Bonifác', 15: 'Žofie', 16: 'Přemysl', 17: 'Aneta', 18: 'Nataša', 19: 'Ivo', 20: 'Zbyšek', 21: 'Monika', 22: 'Emil', 23: 'Vladimír', 24: 'Jana', 25: 'Viola', 26: 'Filip', 27: 'Valdemar', 28: 'Vilém', 29: 'Maxim', 30: 'Ferdinand', 31: 'Kamila'},
    6: {1: 'Laura', 2: 'Jarmil', 3: 'Tamara', 4: 'Dalibor', 5: 'Dobroslav', 6: 'Norbert', 7: 'Iveta', 8: 'Medard', 9: 'Stanislava', 10: 'Gita', 11: 'Bruno', 12: 'Antonie', 13: 'Antonín', 14: 'Roland', 15: 'Vít', 16: 'Zbyněk', 17: 'Adolf', 18: 'Milan', 19: 'Leoš', 20: 'Květa', 21: 'Alois', 22: 'Pavla', 23: 'Zdeňka', 24: 'Jan', 25: 'Ivan', 26: 'Adriana', 27: 'Ladislav', 28: 'Lubomír', 29: 'Petr a Pavel', 30: 'Šárka'},
    7: {1: 'Jaroslava', 2: 'Patricie', 3: 'Radomír', 4: 'Prokop', 5: 'Cyril a Metoděj', 6: 'Jan Hus', 7: 'Bohuslava', 8: 'Nora', 9: 'Drahoslava', 10: 'Libuše', 11: 'Olga', 12: 'Bořek', 13: 'Markéta', 14: 'Karolína', 15: 'Jindřich', 16: 'Luboš', 17: 'Martina', 18: 'Drahomíra', 19: 'Čeněk', 20: 'Ilja', 21: 'Vítězslav', 22: 'Magdaléna', 23: 'Libor', 24: 'Kristýna', 25: 'Jakub', 26: 'Anna', 27: 'Věroslav', 28: 'Viktor', 29: 'Marta', 30: 'Bořivoj', 31: 'Ignác'},
    8: {1: 'Oskar', 2: 'Gustav', 3: 'Miluše', 4: 'Dominik', 5: 'Kristián', 6: 'Oldřiška', 7: 'Lada', 8: 'Soběslav', 9: 'Roman', 10: 'Vavřinec', 11: 'Zuzana', 12: 'Klára', 13: 'Alena', 14: 'Alan', 15: 'Hana', 16: 'Jáchym', 17: 'Petra', 18: 'Helena', 19: 'Ludvík', 20: 'Bernard', 21: 'Johana', 22: 'Bohuslav', 23: 'Sandra', 24: 'Bartoloměj', 25: 'Radim', 26: 'Luděk', 27: 'Otakar', 28: 'Augustýn', 29: 'Evelína', 30: 'Vladěna', 31: 'Pavlína'},
    9: {1: 'Linda', 2: 'Adéla', 3: 'Bronislav', 4: 'Jindřiška', 5: 'Boris', 6: 'Boleslav', 7: 'Regína', 8: 'Mariana', 9: 'Daniela', 10: 'Irma', 11: 'Denisa', 12: 'Marie', 13: 'Lubor', 14: 'Radka', 15: 'Jolana', 16: 'Ludmila', 17: 'Naděžda', 18: 'Kryštof', 19: 'Zita', 20: 'Oleg', 21: 'Matouš', 22: 'Darina', 23: 'Berta', 24: 'Jaromír', 25: 'Zlata', 26: 'Andrea', 27: 'Jonáš', 28: 'Václav', 29: 'Michal', 30: 'Jeroným'},
    10: {1: 'Igor', 2: 'Olivie', 3: 'Bohumil', 4: 'František', 5: 'Eliška', 6: 'Hanuš', 7: 'Justýna', 8: 'Věra', 9: 'Štefan', 10: 'Marina', 11: 'Andrej', 12: 'Marcel', 13: 'Renáta', 14: 'Agáta', 15: 'Tereza', 16: 'Havel', 17: 'Hedvika', 18: 'Lukáš', 19: 'Michaela', 20: 'Vendelín', 21: 'Brigita', 22: 'Sabina', 23: 'Teodor', 24: 'Nina', 25: 'Beáta', 26: 'Erik', 27: 'Šarlota', 28: 'Den vzniku ČSR', 29: 'Silvie', 30: 'Tadeáš', 31: 'Štěpánka'},
    11: {1: 'Felix', 2: 'Památka zesnulých', 3: 'Hubert', 4: 'Karel', 5: 'Miriam', 6: 'Liběna', 7: 'Saskie', 8: 'Bohumír', 9: 'Bohdan', 10: 'Evžen', 11: 'Martin', 12: 'Benedikt', 13: 'Tibor', 14: 'Sáva', 15: 'Leopold', 16: 'Otmar', 17: 'Den svobody', 18: 'Romana', 19: 'Alžběta', 20: 'Nikola', 21: 'Albert', 22: 'Cecílie', 23: 'Klement', 24: 'Emílie', 25: 'Kateřina', 26: 'Artur', 27: 'Xenie', 28: 'René', 29: 'Zina', 30: 'Ondřej'},
    12: {1: 'Iva', 2: 'Blanka', 3: 'Svatoslav', 4: 'Barbora', 5: 'Jitka', 6: 'Mikuláš', 7: 'Ambrož', 8: 'Květoslava', 9: 'Vratislav', 10: 'Julie', 11: 'Dana', 12: 'Simona', 13: 'Lucie', 14: 'Lýdie', 15: 'Radana', 16: 'Albína', 17: 'Daniel', 18: 'Miloslav', 19: 'Ester', 20: 'Dagmar', 21: 'Natálie', 22: 'Šimon', 23: 'Vlasta', 24: 'Štědrý den', 25: 'Boží hod', 26: 'Štěpán', 27: 'Žaneta', 28: 'Bohumila', 29: 'Judita', 30: 'David', 31: 'Silvestr'}
}

# System prompt pro Radima — centralized in radim_system_prompt.py
from radim_system_prompt import get_radim_prompt, RADIM_SYSTEM_PROMPT_CS
from radim_shared import build_time_context_string

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_claude_client():
    """Get Anthropic client with 25s timeout (under Heroku 30s limit)"""
    if not ANTHROPIC_AVAILABLE:
        return None
    if not ANTHROPIC_API_KEY:
        return None
    return Anthropic(api_key=ANTHROPIC_API_KEY, timeout=25.0)

def call_gemini_fallback(prompt, system_prompt="", max_tokens=1024):
    """Gemini fallback when Claude API is unavailable (e.g. credits exhausted)"""
    if not GEMINI_API_KEY:
        return None
    try:
        import requests as req
        parts = [{"text": f"{system_prompt}\n\n{prompt}" if system_prompt else prompt}]
        resp = req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": max_tokens,
                    "topP": 0.9
                }
            },
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            if 'candidates' in data and data['candidates']:
                return data['candidates'][0]['content']['parts'][0]['text'].strip()
        logger.warning(f"Gemini fallback error: {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"Gemini fallback exception: {e}")
        return None

def is_credit_error(error):
    """Check if the error is an Anthropic credit balance error"""
    error_str = str(error).lower()
    return 'credit balance' in error_str or 'billing' in error_str

def get_today_info():
    """Get today's date info — delegates to radim_shared."""
    from radim_shared import build_time_context, get_nameday
    tc = build_time_context()
    return {
        "date": f"{tc['date_str']} {tc['year']}",
        "day_name": tc["day_name"].capitalize(),
        "nameday": tc["nameday"] or "Neznámý",
        "iso_date": datetime.now().strftime("%Y-%m-%d")
    }

def extract_text_from_response(response):
    """Extract text from Claude response"""
    text_parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            text_parts.append(block.text)
    return "\n".join(text_parts)

def get_greeting():
    """Získat pozdrav podle denní doby — delegates to radim_shared"""
    from radim_shared import get_greeting as _shared_greeting
    return _shared_greeting(with_emoji=True)

# ============================================================================
# ROUTES
# ============================================================================

@claude_bp.route('/health', methods=['GET'])
def health_check():
    """Health check for Claude AI service"""
    return jsonify({
        "status": "healthy" if ANTHROPIC_API_KEY else "degraded",
        "service": "claude-ai",
        "timestamp": datetime.utcnow().isoformat()
    })

@claude_bp.route('/nameday', methods=['GET'])
def get_nameday():
    """Získat dnešní svátek"""
    info = get_today_info()
    return jsonify({
        "success": True,
        "date": info["date"],
        "nameday": info["nameday"],
        "timestamp": datetime.utcnow().isoformat()
    })

@claude_bp.route('/chat', methods=['POST'])
@require_auth
def chat_with_radim():
    """
    💬 Hlavní chat endpoint s Claude + Web Search
    """
    try:
        data = request.get_json() or {}
        message = data.get('message', '')
        # Prefer JWT user_id, fallback to request body
        auth_user = getattr(g, 'auth_user', None) or {}
        user_id = str(auth_user.get('id', '')) or data.get('user_id', 'anonymous')
        use_search = data.get('use_search', True)
        emotional_context = data.get('emotional_context', '')
        
        if not message:
            return jsonify({
                "success": False,
                "response": "Prosím, napište mi nějakou zprávu.",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        client = get_claude_client()
        
        if not client:
            # Fallback bez AI
            return jsonify({
                "success": True,
                "response": f"Promiňte, AI služba je momentálně nedostupná. Zkuste to prosím později. Dnes má svátek {get_today_info()['nameday']}.",
                "intent": "fallback",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        # System prompt — centralized from radim_system_prompt.py
        time_ctx = build_time_context_string()
        system = get_radim_prompt(mode='full', user_type='senior', time_context=time_ctx)

        # 🧠 Personalize from learning data (name, interests, style, mood)
        if _CL_MEMORY_AVAILABLE:
            try:
                system = get_personalized_system_prompt(user_id, system)
            except Exception as pers_err:
                logger.warning(f"Personalization failed (non-fatal): {pers_err}")

        # 💚 Add emotional context from frontend (RadimEmpathyBridge)
        if emotional_context:
            system += f"\n\n═══ EMOČNÍ KONTEXT (aktuální stav uživatele) ═══\n{emotional_context}"

        # 🎵 Text Rhythm: matematika → styl textu
        anticipation_meta = None
        gen_config_override = None
        if _CL_TEXT_RHYTHM:
            try:
                C_val = data.get('C')
                alpha_val = data.get('alpha')

                if C_val is not None and alpha_val is not None:
                    C = float(C_val)
                    alpha = float(alpha_val)
                else:
                    mood = _cl_detect_mood(message) if _CL_MEMORY_AVAILABLE else "neutral"
                    C, alpha = _cl_tr_estimate(message, mood)

                text_result = _cl_tr_calc(C, alpha)
                system += _cl_tr_prompt(text_result)
                anticipation_meta = _cl_tr_meta(text_result)
                gen_config_override = _cl_tr_gen_config(text_result)
            except Exception as tr_err:
                logger.warning(f"Text rhythm in claude chat (non-fatal): {tr_err}")

        # 📜 Build messages array with conversation history
        messages = []
        if _CL_MEMORY_AVAILABLE:
            try:
                history_msgs = get_conversation_messages(user_id, limit=10)
                messages.extend(history_msgs)
            except Exception as hist_err:
                logger.warning(f"History load failed (non-fatal): {hist_err}")
        messages.append({"role": "user", "content": message})

        # 🎯 Intent Resolver: short-circuit simple queries locally (v272)
        if _CL_INTENT_RESOLVER:
            try:
                _ir_text, _ir_intent, _ir_meta = _cl_resolve_intent(message, user_id)
                if _ir_text:
                    logger.info(f"Intent '{_ir_intent}' resolved locally for user={user_id}")
                    result = {
                        "success": True,
                        "response": _ir_text,
                        "intent": _ir_intent,
                        "source": "local",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    if anticipation_meta:
                        result["anticipation"] = anticipation_meta
                    return jsonify(result)
            except Exception as ir_err:
                logger.warning(f"Intent resolver warning (non-fatal): {ir_err}")

        # Volání Claude API
        max_tokens = gen_config_override["max_tokens"] if gen_config_override else 1024
        api_kwargs = {
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages
        }
        
        # Web search tool (volitelný)
        if use_search:
            api_kwargs["tools"] = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3
            }]
        
        response = client.messages.create(**api_kwargs)
        
        text = extract_text_from_response(response)

        # 🧠 Record interaction to memory (save history + update learning)
        if _CL_MEMORY_AVAILABLE:
            try:
                record_interaction(user_id, message, text)
            except Exception as mem_err:
                logger.warning(f"Memory record failed (non-fatal): {mem_err}")

        # Detekovat intent
        intent = "general"
        msg_lower = message.lower()
        if any(w in msg_lower for w in ["počasí", "teplota", "prší"]):
            intent = "weather"
        elif any(w in msg_lower for w in ["zprávy", "novinky"]):
            intent = "news"
        elif any(w in msg_lower for w in ["kvíz", "otázky"]):
            intent = "quiz"
        elif any(w in msg_lower for w in ["příběh", "povídka"]):
            intent = "story"
        
        logger.info(f"Chat | User: {user_id} | Intent: {intent} | Memory: {_CL_MEMORY_AVAILABLE}")
        
        result = {
            "success": True,
            "response": text,
            "intent": intent,
            "timestamp": datetime.utcnow().isoformat()
        }
        if anticipation_meta:
            result["anticipation"] = anticipation_meta
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        # Gemini fallback on credit/billing errors
        if is_credit_error(e):
            info = get_today_info()
            time_ctx = f"Dnes je {info['day_name']} {info['date']}. Svátek má {info['nameday']}."
            system = get_radim_prompt(mode='full', user_type='senior', time_context=time_ctx)
            gemini_text = call_gemini_fallback(message, system)
            if gemini_text:
                # Record Gemini fallback interaction too
                if _CL_MEMORY_AVAILABLE:
                    try:
                        record_interaction(user_id, message, gemini_text)
                    except Exception:
                        pass
                return jsonify({
                    "success": True,
                    "response": gemini_text,
                    "intent": "general",
                    "source": "gemini_fallback",
                    "timestamp": datetime.utcnow().isoformat()
                })
        return jsonify({
            "success": False,
            "response": "Promiňte, něco se pokazilo. Zkuste to prosím znovu.",
            "intent": "error",
            "timestamp": datetime.utcnow().isoformat()
        })

@claude_bp.route('/news', methods=['POST'])
@require_auth
def get_news():
    """📰 Získat aktuální české zprávy"""
    category = 'general'
    count = 5
    try:
        data = request.get_json() or {}
        category = data.get('category', 'general')
        count = data.get('count', 5)
        
        client = get_claude_client()
        info = get_today_info()
        
        if not client:
            # Fallback - lokální zprávy
            return jsonify({
                "success": True,
                "category": category,
                "articles": get_fallback_news(category),
                "ai_summary": "Lokální zprávy (AI nedostupná)",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        category_queries = {
            "politics": "české politické zprávy dnes",
            "sports": "český sport zprávy hokej fotbal",
            "health": "zdraví zprávy tipy pro seniory",
            "culture": "kultura Praha divadlo koncerty",
            "science": "věda technika zajímavosti Česko",
            "local": "Praha zprávy doprava události",
            "general": "hlavní české zprávy dnes"
        }
        
        query = category_queries.get(category, category_queries["general"])
        
        system = f"""Vyhledej {count} aktuálních českých zpráv z kategorie: {category}.
        
FORMÁT (pouze JSON pole):
[
  {{"title": "Titulek", "description": "Popis", "source": "Zdroj"}}
]

Dnešní datum: {info['date']}"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": f"Vyhledej zprávy: {query}"}]
        )
        
        text = extract_text_from_response(response)
        
        # Parse JSON
        articles = []
        try:
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                articles = json.loads(json_match.group())
        except Exception:
            articles = [{"title": f"Zprávy z {category}", "description": text[:200], "source": "Claude AI"}]
        
        return jsonify({
            "success": True,
            "category": category,
            "articles": articles,
            "ai_summary": f"{len(articles)} zpráv ke dni {info['date']}",
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"News error: {e}")
        # Gemini fallback on credit errors
        if is_credit_error(e):
            info = get_today_info()
            gemini_text = call_gemini_fallback(
                f"Vyhledej {count if 'count' in dir() else 5} aktuálních českých zpráv z kategorie: {category}. Dnešní datum: {info['date']}. Odpověz jako JSON pole [{{'title':'...','description':'...','source':'...'}}]",
                max_tokens=2048
            )
            if gemini_text:
                try:
                    json_match = re.search(r'\[.*\]', gemini_text, re.DOTALL)
                    if json_match:
                        articles = json.loads(json_match.group())
                        return jsonify({
                            "success": True,
                            "category": category,
                            "articles": articles,
                            "ai_summary": f"Zprávy via Gemini",
                            "source": "gemini_fallback",
                            "timestamp": datetime.utcnow().isoformat()
                        })
                except Exception:
                    pass
        return jsonify({
            "success": True,
            "category": category,
            "articles": get_fallback_news(category),
            "timestamp": datetime.utcnow().isoformat()
        })

@claude_bp.route('/weather', methods=['GET'])
@require_auth
def get_weather():
    """🌤️ Získat aktuální počasí"""
    location = request.args.get('location', 'Praha')
    
    try:
        client = get_claude_client()
        
        if not client:
            return jsonify(get_fallback_weather(location))
        
        system = """Vyhledej aktuální počasí a odpověz pouze JSON:
{"temperature": 5, "condition": "Oblačno", "humidity": 75, "wind": 12, "forecast": "Odpoledne déšť."}"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=system,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": f"Aktuální počasí v {location}?"}]
        )
        
        text = extract_text_from_response(response)
        
        # Parse JSON
        weather = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                weather = json.loads(json_match.group())
        except Exception:
            weather = {"condition": "Informace nedostupná"}
        
        return jsonify({
            "success": True,
            "location": location,
            "temperature": weather.get("temperature"),
            "condition": weather.get("condition", "Neznámé"),
            "humidity": weather.get("humidity"),
            "wind": weather.get("wind"),
            "forecast": weather.get("forecast"),
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return jsonify(get_fallback_weather(location))

@claude_bp.route('/quiz', methods=['POST'])
@require_auth
def generate_quiz():
    """🎮 Vygenerovat kvíz"""
    topic = 'general'
    try:
        data = request.get_json() or {}
        topic = data.get('topic', 'general')
        difficulty = data.get('difficulty', 'easy')
        count = data.get('count', 5)
        
        system = f"""Vytvoř {count} kvízových otázek pro seniory.
Téma: {topic}, Obtížnost: {difficulty}

FORMÁT (pouze JSON):
[{{"question": "Otázka?", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, "correct": "A", "explanation": "Vysvětlení."}}]"""

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=2048,
                    system=system,
                    messages=[{"role": "user", "content": f"Vytvoř kvíz na téma: {topic}"}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude quiz failed: {claude_err}")

        # Gemini fallback
        if not text:
            gemini_text = call_gemini_fallback(
                f"Vytvoř kvíz na téma: {topic}",
                system,
                2048
            )
            if gemini_text:
                text = gemini_text

        # Parse questions from AI response
        questions = []
        if text:
            try:
                json_match = re.search(r'\[.*\]', text, re.DOTALL)
                if json_match:
                    questions = json.loads(json_match.group())
            except Exception:
                pass

        # Static fallback if no AI response
        if not questions:
            questions = get_fallback_quiz(topic)

        return jsonify({
            "success": True,
            "topic": topic,
            "questions": questions,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Quiz error: {e}")
        return jsonify({
            "success": True,
            "topic": topic,
            "questions": get_fallback_quiz(topic),
            "timestamp": datetime.utcnow().isoformat()
        })

@claude_bp.route('/story', methods=['POST'])
@require_auth
def generate_story():
    """📖 Vygenerovat příběh"""
    theme = 'nature'
    try:
        data = request.get_json() or {}
        theme = data.get('theme', 'nature')
        length = data.get('length', 'short')
        style = data.get('style', 'relaxing')
        
        length_words = {"short": "100-150", "medium": "200-300", "long": "400-500"}

        system = f"""Vyprávěj {style} příběh pro seniory.
Téma: {theme}, Délka: {length_words.get(length, '150')} slov.
Česká jména a místa. Pozitivní a uklidňující.

FORMÁT (pouze JSON):
{{"title": "Název", "content": "Text příběhu..."}}"""

        text = None

        # Try Claude first
        client = get_claude_client()
        if client:
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": f"Vyprávěj příběh na téma: {theme}"}]
                )
                text = extract_text_from_response(response)
            except Exception as claude_err:
                logger.warning(f"Claude story failed: {claude_err}")

        # Gemini fallback
        if not text:
            gemini_text = call_gemini_fallback(
                f"Vyprávěj příběh na téma: {theme}",
                system,
                1024
            )
            if gemini_text:
                text = gemini_text

        # Static fallback
        if not text:
            return jsonify({
                "success": True,
                "title": "Procházka parkem",
                "content": "Bylo krásné jarní ráno. Pan Josef vyšel na svou oblíbenou procházku do parku. Slunce hřálo a ptáci zpívali. U rybníčku potkal svého starého přítele Karla a společně si povídali o starých časech. Byl to krásný den.",
                "theme": theme,
                "timestamp": datetime.utcnow().isoformat()
            })

        story = {}
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                story = json.loads(json_match.group())
        except Exception:
            story = {"title": f"Příběh o {theme}", "content": text}

        return jsonify({
            "success": True,
            "title": story.get("title", "Příběh"),
            "content": story.get("content", text),
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Story error: {e}")
        return jsonify({
            "success": False,
            "title": "Chyba",
            "content": "Nepodařilo se vytvořit příběh.",
            "theme": theme,
            "timestamp": datetime.utcnow().isoformat()
        })

@claude_bp.route('/dashboard-data', methods=['GET'])
@require_auth
def get_dashboard_data():
    """📊 Všechna data pro dashboard"""
    info = get_today_info()
    
    result = {
        "success": True,
        "date": info["date"],
        "day_name": info["day_name"],
        "nameday": info["nameday"],
        "weather": None,
        "greeting": get_greeting(),
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Použít fallback weather (rychlé, bez Claude API)
    try:
        fallback = get_fallback_weather("Praha")
        result["weather"] = {
            "temperature": fallback.get("temperature"),
            "condition": fallback.get("condition"),
            "humidity": fallback.get("humidity"),
            "wind": fallback.get("wind")
        }
    except Exception:
        pass
    
    return jsonify(result)


# ============================================================================
# EMOTION ANALYSIS (pro RadimConsciousnessEngine)
# ============================================================================

@claude_bp.route('/analyze-emotion', methods=['POST'])
@require_auth
def analyze_emotion():
    """
    🧠 Analyzuj emoce v textu pro RadimConsciousnessEngine
    Vrací strukturované emoce s intenzitou 0-1
    """
    try:
        data = request.get_json() or {}
        text = data.get('text', '')
        context = data.get('context', 'senior_care')
        
        if not text:
            return jsonify({
                "success": False,
                "error": "Text is required",
                "emotions": {}
            })
        
        client = get_claude_client()
        
        if not client:
            return jsonify({
                "success": True,
                "emotions": analyze_emotions_local(text),
                "source": "local",
                "timestamp": datetime.utcnow().isoformat()
            })
        
        system = """Analyzuj emoce v textu seniora. Vrať POUZE JSON:
{
  "joy": 0.0-1.0,
  "sadness": 0.0-1.0,
  "fear": 0.0-1.0,
  "hope": 0.0-1.0,
  "calm": 0.0-1.0,
  "tension": 0.0-1.0,
  "curiosity": 0.0-1.0,
  "gratitude": 0.0-1.0,
  "loneliness": 0.0-1.0,
  "confusion": 0.0-1.0,
  "dominant_emotion": "název",
  "needs_empathy": true/false,
  "crisis_level": 0-10
}

Kontext: Péče o seniory. Buď citlivý k implicitním emocím."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": f"Analyzuj emoce: {text}"}]
        )
        
        result_text = extract_text_from_response(response)
        
        emotions = {}
        try:
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                emotions = json.loads(json_match.group())
        except Exception:
            emotions = analyze_emotions_local(text)
        
        logger.info(f"Emotion analysis | Dominant: {emotions.get('dominant_emotion', 'unknown')}")
        
        return jsonify({
            "success": True,
            "emotions": emotions,
            "source": "claude",
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Emotion analysis error: {e}")
        return jsonify({
            "success": True,
            "emotions": analyze_emotions_local(text if text else ''),
            "source": "fallback",
            "timestamp": datetime.utcnow().isoformat()
        })


def analyze_emotions_local(text):
    """Lokální emoční analýza (fallback)"""
    if not text:
        return {}
    
    lower = text.lower()
    
    patterns = {
        "joy": ["skvělé", "výborně", "super", "krásné", "radost", "šťastný", "hurá", "děkuji", "líbí"],
        "sadness": ["smutný", "smutná", "bolí", "chybí", "osamělý", "samota", "pláču", "těžké", "ztráta"],
        "fear": ["bojím", "strach", "úzkost", "panika", "děsí", "obávám", "nervózní"],
        "hope": ["doufám", "věřím", "zlepší", "lépe", "naděje", "těším"],
        "calm": ["klid", "pohoda", "relaxuji", "odpočinek", "dobře", "v pohodě"],
        "tension": ["problém", "stres", "napětí", "nejde", "nefunguje", "zlost", "naštvaný"],
        "curiosity": ["zajímá", "proč", "jak", "co je", "vysvětli", "nevím"],
        "gratitude": ["děkuji", "díky", "vděčný", "oceňuji", "pomohl"],
        "loneliness": ["sám", "sama", "nikdo", "opuštěný", "izolace"],
        "confusion": ["nechápu", "zmatený", "nevím", "jak to", "co mám"]
    }
    
    emotions = {}
    max_emotion = ("neutral", 0)
    
    for emotion, words in patterns.items():
        matches = sum(1 for w in words if w in lower)
        intensity = min(1.0, matches * 0.25)
        emotions[emotion] = intensity
        if intensity > max_emotion[1]:
            max_emotion = (emotion, intensity)
    
    emotions["dominant_emotion"] = max_emotion[0]
    emotions["needs_empathy"] = emotions.get("sadness", 0) > 0.3 or emotions.get("fear", 0) > 0.3
    emotions["crisis_level"] = int(min(10, (emotions.get("fear", 0) + emotions.get("sadness", 0)) * 10))
    
    return emotions


@claude_bp.route('/consciousness-state', methods=['POST'])
@require_auth
def get_consciousness_state():
    """
    🧠 Získat doporučení pro stav vědomí
    """
    try:
        data = request.get_json() or {}
        emotions = data.get('emotions', {})

        harmony = calculate_harmony(emotions)
        # Accept crisis_level from top-level OR nested in emotions
        crisis_level = data.get('crisis_level', emotions.get('crisis_level', 0))

        # Convert crisis_level (0-10) to C (0-40) for Anticipation Engine
        # crisis_level 0→C=5, 3→C=12, 7→C=27, 10→C=40
        C_estimated = 5 + crisis_level * 3.5
        alpha_estimated = min(1.0, crisis_level / 10.0)

        # Use Anticipation Engine for speech params if available
        anticipation_data = None
        if _CL_ANT_AVAILABLE:
            try:
                C_pred = _cl_predict_C(C_estimated, 0, alpha_estimated)
                ant_emo = _cl_ant_emotions(C_pred, alpha_estimated)
                ant_params = _cl_ant_speech(C_pred, alpha_estimated, ant_emo)
                ant_state = _cl_classify(C_pred)

                speech_params = {
                    "rate": ant_params["rate"],
                    "pitch": ant_params["pitch"],
                    "pause_ms": ant_params["pause_ms"],
                    "empathy_level": ant_params["empathy"],
                    "anticipation_state": ant_state,
                    "C": round(C_estimated, 1),
                    "alpha": round(alpha_estimated, 2)
                }
                anticipation_data = {
                    "state": ant_state,
                    "emotions": {k: round(v, 3) for k, v in ant_emo.items()},
                    "adjustments": ant_params.get("adjustments", {})
                }
            except Exception as ae:
                logger.warning(f"Anticipation in consciousness-state (non-fatal): {ae}")
                speech_params = {
                    "rate": 0.9 if crisis_level < 3 else 0.75,
                    "pitch": 0 if crisis_level < 5 else -2,
                    "pause_ms": 300 + (crisis_level * 50),
                    "empathy_level": min(1.0, 0.5 + (emotions.get('sadness', 0) + emotions.get('fear', 0)) * 0.5)
                }
        else:
            speech_params = {
                "rate": 0.9 if crisis_level < 3 else 0.75,
                "pitch": 0 if crisis_level < 5 else -2,
                "pause_ms": 300 + (crisis_level * 50),
                "empathy_level": min(1.0, 0.5 + (emotions.get('sadness', 0) + emotions.get('fear', 0)) * 0.5)
            }

        suggestions = []
        if crisis_level >= 7:
            suggestions.append({"type": "offer", "text": "Chcete zavolat někomu blízkému?", "action": "contact_family"})
            suggestions.append({"type": "offer", "text": "Mohu vám nabídnout dýchací cvičení?", "action": "breathing"})
        elif crisis_level >= 4:
            suggestions.append({"type": "offer", "text": "Chcete si o tom promluvit?", "action": "talk"})

        result = {
            "success": True,
            "harmony": harmony,
            "crisis_level": crisis_level,
            "speech_params": speech_params,
            "suggestions": suggestions,
            "dominant_emotion": emotions.get('dominant_emotion', 'neutral'),
            "timestamp": datetime.utcnow().isoformat()
        }
        if anticipation_data:
            result["anticipation"] = anticipation_data

        return jsonify(result)

    except Exception as e:
        logger.error(f"Consciousness state error: {e}")
        return jsonify({
            "success": False,
            "error": "Interní chyba služby",
            "harmony": 0.5,
            "crisis_level": 0,
            "speech_params": {"rate": 0.9, "pitch": 0, "pause_ms": 300, "empathy_level": 0.5},
            "suggestions": []
        })


def calculate_harmony(emotions):
    """Vypočítej harmonii z emocí"""
    positive = (emotions.get('joy', 0) + emotions.get('hope', 0) + 
                emotions.get('calm', 0) + emotions.get('gratitude', 0)) / 4
    negative = (emotions.get('sadness', 0) + emotions.get('fear', 0) + 
                emotions.get('tension', 0) + emotions.get('loneliness', 0)) / 4
    return max(0, min(1, positive - negative + 0.5))


@claude_bp.route('/memory/save', methods=['POST'])
@require_auth
def save_memory_note():
    """📝 Uložit poznámku do paměti (persisted to PostgreSQL)"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id', 'anonymous')
        note_type = data.get('type', 'observation')
        content = data.get('content', '')

        if not content:
            return jsonify({"success": False, "error": "Empty content"}), 400

        # Persist via memory_routes (saves to DB)
        if _CL_MEMORY_AVAILABLE:
            record_interaction(user_id, f"[{note_type}] {content[:500]}", "Poznámka uložena.")

        logger.info(f"Memory note saved | User: {user_id} | Type: {note_type}")

        return jsonify({
            "success": True,
            "persisted": _CL_MEMORY_AVAILABLE,
            "note_id": f"note_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "message": "Poznámka uložena",
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Memory save error: {e}")
        return jsonify({"success": False, "error": "Nepodařilo se uložit vzpomínku"})


@claude_bp.route('/memory/recall', methods=['POST'])
@require_auth
def recall_memory():
    """🔍 Vybavit si vzpomínky (from PostgreSQL)"""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id', 'anonymous')
        limit = data.get('limit', 20)

        memories = []
        context = {}

        if _CL_MEMORY_AVAILABLE:
            messages = get_conversation_messages(user_id, limit=limit)
            memories = messages
            context = get_user_context(user_id)

        return jsonify({
            "success": True,
            "memories": memories,
            "context": context,
            "count": len(memories),
            "message": f"{len(memories)} vzpomínek nalezeno" if memories else "Paměť zatím prázdná",
            "timestamp": datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error(f"Memory recall error: {e}")
        return jsonify({"success": False, "error": "Nepodařilo se vybavit vzpomínky", "memories": []})


# ============================================================================
# FALLBACK DATA
# ============================================================================

def get_fallback_news(category):
    """Lokální fallback zprávy"""
    news = {
        "politics": [
            {"title": "Vláda schválila sociální podporu", "description": "Rozšíření příspěvků pro seniory.", "source": "ČTK"},
            {"title": "Prezident Pavel v Bruselu", "description": "Summit EU o bezpečnosti.", "source": "iDNES"}
        ],
        "sports": [
            {"title": "Hokejisté vyhráli turnaj", "description": "Zlatá medaile pro ČR.", "source": "Sport.cz"},
            {"title": "Sparta v Lize mistrů", "description": "Vítězství 2:1.", "source": "iSport"}
        ],
        "health": [
            {"title": "Očkování proti chřipce", "description": "Zdarma pro seniory 65+.", "source": "VZP"},
            {"title": "Prevence je základ", "description": "Pravidelné prohlídky.", "source": "MZ ČR"}
        ],
        "culture": [
            {"title": "Národní divadlo: premiéra", "description": "Prodaná nevěsta.", "source": "Kultura.cz"},
            {"title": "Výstava Muchy", "description": "Retrospektiva v Praze.", "source": "Aktuálně.cz"}
        ],
        "science": [
            {"title": "Nová exoplaneta", "description": "Objev českých astronomů.", "source": "Akademie věd"},
            {"title": "AI v medicíně", "description": "Diagnostika s 95% přesností.", "source": "Tech.cz"}
        ],
        "local": [
            {"title": "Metro D se staví", "description": "Otevření v 2027.", "source": "Praha.eu"},
            {"title": "Farmářské trhy", "description": "Každou sobotu.", "source": "Pražský deník"}
        ]
    }
    return news.get(category, news["politics"])

def get_fallback_weather(location):
    """Lokální fallback počasí"""
    import random
    month = datetime.now().month
    
    if month in [12, 1, 2]:
        temp = random.randint(-5, 3)
        condition = "Zataženo"
    elif month in [3, 4, 5]:
        temp = random.randint(8, 16)
        condition = "Polojasno"
    elif month in [6, 7, 8]:
        temp = random.randint(22, 30)
        condition = "Jasno"
    else:
        temp = random.randint(6, 14)
        condition = "Oblačno"
    
    return {
        "success": True,
        "location": location,
        "temperature": temp,
        "condition": condition,
        "humidity": random.randint(50, 85),
        "wind": random.randint(5, 20),
        "timestamp": datetime.utcnow().isoformat()
    }

def get_fallback_quiz(topic):
    """Lokální fallback kvíz"""
    return [
        {
            "question": "Který hrad je největší na světě?",
            "options": {"A": "Pražský hrad", "B": "Windsor", "C": "Versailles", "D": "Kreml"},
            "correct": "A",
            "explanation": "Pražský hrad je podle Guinessovy knihy rekordů největší hradní komplex."
        },
        {
            "question": "Která řeka protéká Prahou?",
            "options": {"A": "Morava", "B": "Vltava", "C": "Labe", "D": "Odra"},
            "correct": "B",
            "explanation": "Vltava je nejdelší řeka v České republice."
        }
    ]


# ============================================================================
# LOGGING
# ============================================================================

print("✅ Claude AI Blueprint loaded - /api/claude/* endpoints ready")
print("🧠 Emotion Analysis endpoint: /api/claude/analyze-emotion")
print("🧠 Consciousness State endpoint: /api/claude/consciousness-state")
print("📝 Memory endpoints: /api/claude/memory/save, /api/claude/memory/recall")
