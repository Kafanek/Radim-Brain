# ============================================
# RADIM VOICE RUNTIME ENGINE
# ============================================
# Matematický engine pro hlasový runtime
# C(t), κ(t), α(t) - stavové metriky
# 5-stavový automat řízení

import os
import json
import math
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from auth_middleware import require_auth

logger = logging.getLogger(__name__)

voice_runtime_bp = Blueprint('voice_runtime', __name__, url_prefix='/api/voice')

# ============================================
# MATEMATICKÉ KONSTANTY (RADIM String Model)
# ============================================
PHI = 1.618033988749895      # Zlatý řez φ
DELTA = 2.414213562373095    # Stříbrný řez δ
RADIM_R = 3.906              # RADIM konstanta

# Fibonacci sekvence pro timing
FIBONACCI = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89]

# Prahy pro stavy
THRESHOLD_HARMONY = 12       # C < 12 = HARMONIE
THRESHOLD_ALERT = 27         # 12 <= C < 27 = ALERT
# C >= 27 = KRIZE

# ============================================
# STAVOVÝ AUTOMAT
# ============================================
STATES = {
    'IDLE': 'idle',
    'WAKE_DETECTED': 'wake_detected',
    'LISTENING': 'listening', 
    'THINKING': 'thinking',
    'SPEAKING': 'speaking'
}

# Session storage: in-memory cache backed by PostgreSQL
_sessions_cache = {}


def _load_session_from_db(session_id):
    """Load session from DB, return dict or None."""
    try:
        from database import get_db, close_db
        db = get_db()
        row = db.execute(
            'SELECT state, "C", kappa, alpha, last_tts_text, conversation, wake_count, created_at '
            'FROM voice_sessions WHERE session_id = %s',
            (session_id,)
        ).fetchone()
        close_db()
        if row:
            conv = row['conversation']
            if isinstance(conv, str):
                conv = json.loads(conv)
            return {
                'state': row['state'] or STATES['IDLE'],
                'C': float(row['C'] or 5.0),
                'kappa': float(row['kappa'] or 0.8),
                'alpha': float(row['alpha'] or 0.0),
                'last_tts_text': row['last_tts_text'] or '',
                'conversation': conv if conv else [],
                'wake_count': int(row['wake_count'] or 0),
                'created': str(row['created_at'] or datetime.now().isoformat()),
            }
    except Exception as e:
        logger.warning(f"DB load session {session_id} (non-fatal): {e}")
    return None


def save_session(session_id):
    """Persist session to DB (call after key changes)."""
    session = _sessions_cache.get(session_id)
    if not session:
        return
    try:
        from database import get_db, close_db, is_postgres
        db = get_db()
        conv_json = json.dumps(session['conversation'][-50:])  # Keep last 50 messages
        if is_postgres():
            db.execute(
                'INSERT INTO voice_sessions (session_id, state, "C", kappa, alpha, last_tts_text, conversation, wake_count, updated_at) '
                'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP) '
                'ON CONFLICT (session_id) DO UPDATE SET '
                'state=EXCLUDED.state, "C"=EXCLUDED."C", kappa=EXCLUDED.kappa, alpha=EXCLUDED.alpha, '
                'last_tts_text=EXCLUDED.last_tts_text, conversation=EXCLUDED.conversation, '
                'wake_count=EXCLUDED.wake_count, updated_at=CURRENT_TIMESTAMP',
                (session_id, session['state'], session['C'], session['kappa'],
                 session['alpha'], session['last_tts_text'], conv_json, session['wake_count'])
            )
        else:
            db.execute(
                'INSERT OR REPLACE INTO voice_sessions '
                '(session_id, state, C, kappa, alpha, last_tts_text, conversation, wake_count, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                (session_id, session['state'], session['C'], session['kappa'],
                 session['alpha'], session['last_tts_text'], conv_json, session['wake_count'])
            )
        db.commit()
        close_db()
    except Exception as e:
        logger.warning(f"DB save session {session_id} (non-fatal): {e}")


def get_session(session_id):
    """Get or create session (cache + DB backed)."""
    if session_id not in _sessions_cache:
        # Try loading from DB first
        db_session = _load_session_from_db(session_id)
        if db_session:
            _sessions_cache[session_id] = db_session
        else:
            # Use shared baseline from Anticipation Engine
            try:
                from anticipation_routes import BASELINE_AMBIENT
                _bl = BASELINE_AMBIENT
            except ImportError:
                _bl = {'C': 5.0, 'alpha': 0.0}
            _sessions_cache[session_id] = {
                'state': STATES['IDLE'],
                'C': _bl['C'],
                'kappa': 0.8,
                'alpha': _bl['alpha'],
                'last_tts_text': '',
                'conversation': [],
                'wake_count': 0,
                'created': datetime.now().isoformat(),
            }
    return _sessions_cache[session_id]


# Legacy alias
sessions = _sessions_cache

# ============================================
# MATEMATICKÝ ENGINE
# ============================================

def compute_C(sensors: dict, bio: dict) -> float:
    """
    Výpočet C(t) - míra zatížení systému
    
    Vstupy:
    - sensors: {noise, light, temperature, motion}
    - bio: {heart_rate, stress_indicator, activity}
    """
    # Základní hodnota
    C = 5.0
    
    # Senzorové příspěvky
    noise = sensors.get('noise', 30)  # dB
    light = sensors.get('light', 50)  # lux normalized 0-100
    temp = sensors.get('temperature', 22)  # °C
    
    # Bio příspěvky
    hr = bio.get('heart_rate', 70)
    stress = bio.get('stress_indicator', 0.3)
    
    # Výpočet zátěže
    if noise > 60:
        C += (noise - 60) * 0.3
    if light < 20 or light > 80:
        C += abs(50 - light) * 0.1
    if temp < 18 or temp > 26:
        C += abs(22 - temp) * 0.5
    
    # Bio faktory
    if hr > 90:
        C += (hr - 90) * 0.2
    C += stress * 15
    
    return min(max(C, 0), 50)  # Omezení 0-50

def compute_kappa(C: float, alpha: float, prev_kappa: float) -> float:
    """
    Výpočet κ(t) - koherence systému
    
    κ(t+1) = κ(t) + f(α) - g(C)
    
    f = stabilizační funkce (φ-modulovaná)
    g = zátěžová funkce
    """
    # Stabilizační funkce
    f = alpha * PHI * 0.1
    
    # Zátěžová funkce
    g = (C / 50) * 0.15
    
    # Nová koherence
    kappa = prev_kappa + f - g
    
    # Omezení 0-1
    return min(max(kappa, 0), 1)

def compute_alpha(state: str, user_intent: str) -> float:
    """
    Výpočet α(t) - regulační zásah
    
    Závisí na stavu a záměru uživatele
    """
    base_alpha = 0.0
    
    if state == 'HARMONIE':
        base_alpha = 0.1
    elif state == 'ALERT':
        base_alpha = 0.5
    elif state == 'KRIZE':
        base_alpha = 1.0
    
    # Modifikace podle záměru
    if 'pomoc' in user_intent.lower() or 'help' in user_intent.lower():
        base_alpha += 0.3
    if 'uklidni' in user_intent.lower() or 'relax' in user_intent.lower():
        base_alpha += 0.2
        
    return min(base_alpha, 1.0)

def get_system_state(C: float) -> str:
    """Určení stavu systému podle C"""
    if C < THRESHOLD_HARMONY:
        return 'HARMONIE'
    elif C < THRESHOLD_ALERT:
        return 'ALERT'
    else:
        return 'KRIZE'

def get_tts_params(system_state: str) -> dict:
    """Parametry TTS podle stavu"""
    if system_state == 'HARMONIE':
        return {
            'rate': 1.0,
            'pitch': '+0Hz',
            'style': 'friendly',
            'max_sentences': 5,
            'pause_ms': int(1000 * (1/PHI))  # ~618ms
        }
    elif system_state == 'ALERT':
        return {
            'rate': 0.85,
            'pitch': '-5Hz',
            'style': 'calm',
            'max_sentences': 3,
            'pause_ms': int(1000 * 1)  # 1000ms
        }
    else:  # KRIZE
        return {
            'rate': 0.7,
            'pitch': '-10Hz',
            'style': 'soothing',
            'max_sentences': 1,
            'pause_ms': int(1000 * PHI)  # ~1618ms
        }

# ============================================
# RELEVANCE CLASSIFIER
# ============================================

RADIM_KEYWORDS = [
    'radim', 'radime', 'ahoj', 'pomoc', 'help',
    'počasí', 'weather', 'čas', 'time', 'datum', 'date',
    'připomeň', 'remind', 'nastav', 'set',
    'zavolej', 'call', 'zpráva', 'message',
    'světlo', 'light', 'teplota', 'temperature',
    'televize', 'tv', 'rádio', 'radio',
    'léky', 'medicine', 'doktor', 'doctor',
    'jídlo', 'food', 'pití', 'drink',
    'cvičení', 'exercise', 'procházka', 'walk',
    'rodina', 'family', 'vnuk', 'vnučka',
    'sos', 'emergency', 'nouzové', 'bolest', 'pain'
]

IGNORE_PATTERNS = [
    'reklama', 'advertisement', 'sponzor',
    'předpověď počasí na obrazovce',  # TV weather
    'zprávy dne', 'news of the day'  # TV news
]

def compute_relevance(text: str, context: dict = None) -> float:
    """
    Výpočet relevance dotazu pro Radima
    
    Returns: 0.0 - 1.0
    """
    text_lower = text.lower()
    score = 0.0
    
    # Přímé oslovení Radima
    if 'radim' in text_lower or 'radime' in text_lower:
        score += 0.5
    
    # Klíčová slova
    keyword_hits = sum(1 for kw in RADIM_KEYWORDS if kw in text_lower)
    score += min(keyword_hits * 0.15, 0.4)
    
    # Negativní vzory (TV, reklama)
    for pattern in IGNORE_PATTERNS:
        if pattern in text_lower:
            score -= 0.3
    
    # Krátké příkazy jsou často relevantní
    words = text.split()
    if 2 <= len(words) <= 10:
        score += 0.1
    
    # Velmi dlouhý text = pravděpodobně TV
    if len(words) > 30:
        score -= 0.2
    
    return max(0.0, min(1.0, score))

# ============================================
# ECHO SIMILARITY (AEC)
# ============================================

def compute_echo_similarity(text: str, last_tts: str) -> float:
    """
    Detekce echo - podobnost s posledním TTS výstupem
    
    Returns: 0.0 - 1.0 (>0.75 = echo)
    """
    if not last_tts:
        return 0.0
    
    text_words = set(text.lower().split())
    tts_words = set(last_tts.lower().split())
    
    if not tts_words:
        return 0.0
    
    intersection = text_words & tts_words
    union = text_words | tts_words
    
    # Jaccard similarity
    if not union:
        return 0.0
    
    return len(intersection) / len(union)

# ============================================
# API ENDPOINTS
# ============================================

@voice_runtime_bp.route('/health', methods=['GET'])
def voice_health():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'service': 'RADIM Voice Runtime',
        'version': '1.1.0',
        'anticipation_engine': _ANT_AVAILABLE,
        'constants': {
            'phi': PHI,
            'delta': DELTA,
            'radim_r': RADIM_R
        },
        'thresholds': {
            'harmony': THRESHOLD_HARMONY,
            'alert': THRESHOLD_ALERT
        }
    })

@voice_runtime_bp.route('/metrics', methods=['POST'])
@require_auth
def compute_metrics():
    """
    Hlavní endpoint pro výpočet metrik
    
    Input:
    {
        "session_id": "...",
        "sensors": {"noise": 40, "light": 60, "temperature": 22},
        "bio": {"heart_rate": 72, "stress_indicator": 0.2},
        "user_text": "Radime, jaké je počasí?"
    }
    
    Output:
    {
        "C": 8.5,
        "kappa": 0.85,
        "alpha": 0.2,
        "system_state": "HARMONIE",
        "relevance": 0.75,
        "should_respond": true,
        "tts_params": {...}
    }
    """
    try:
        data = request.json or {}
        
        session_id = data.get('session_id', 'default')
        sensors = data.get('sensors', {})
        bio = data.get('bio', {})
        user_text = data.get('user_text', '')
        
        session = get_session(session_id)
        
        # Výpočet metrik
        C = compute_C(sensors, bio)
        system_state = get_system_state(C)
        alpha = compute_alpha(system_state, user_text)
        kappa = compute_kappa(C, alpha, session['kappa'])
        
        # Relevance
        relevance = compute_relevance(user_text)
        
        # Echo check
        echo_sim = compute_echo_similarity(user_text, session['last_tts_text'])
        is_echo = echo_sim > 0.75
        
        # Rozhodnutí o odpovědi
        should_respond = relevance >= 0.6 and not is_echo
        
        # TTS parametry
        tts_params = get_tts_params(system_state)
        
        # Update session
        session['C'] = C
        session['kappa'] = kappa
        session['alpha'] = alpha

        # Persist to DB on significant state changes
        if should_respond or system_state != 'HARMONIE':
            save_session(session_id)

        return jsonify({
            'C': round(C, 2),
            'kappa': round(kappa, 3),
            'alpha': round(alpha, 2),
            'system_state': system_state,
            'relevance': round(relevance, 2),
            'echo_similarity': round(echo_sim, 2),
            'is_echo': is_echo,
            'should_respond': should_respond,
            'tts_params': tts_params,
            'fibonacci_pause_ms': FIBONACCI[5] * 100  # 500ms base
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@voice_runtime_bp.route('/state', methods=['POST'])
@require_auth
def update_state():
    """
    Update stavového automatu
    
    Input:
    {
        "session_id": "...",
        "event": "wake_detected|voice_valid|speech_end|response_ready|tts_done",
        "data": {...}
    }
    """
    try:
        data = request.json or {}
        session_id = data.get('session_id', 'default')
        event = data.get('event', '')
        event_data = data.get('data', {})
        
        session = get_session(session_id)
        current_state = session['state']
        new_state = current_state
        
        # Stavový automat přechody
        if current_state == STATES['IDLE']:
            if event == 'wake_detected':
                new_state = STATES['WAKE_DETECTED']
                session['wake_count'] += 1
                
        elif current_state == STATES['WAKE_DETECTED']:
            if event == 'voice_valid':
                new_state = STATES['LISTENING']
            elif event == 'voice_invalid' or event == 'timeout':
                new_state = STATES['IDLE']
                
        elif current_state == STATES['LISTENING']:
            if event == 'speech_end':
                new_state = STATES['THINKING']
            elif event == 'timeout':
                new_state = STATES['IDLE']
                
        elif current_state == STATES['THINKING']:
            if event == 'response_ready':
                new_state = STATES['SPEAKING']
                session['last_tts_text'] = event_data.get('text', '')
                
        elif current_state == STATES['SPEAKING']:
            if event == 'tts_done':
                new_state = STATES['IDLE']
        
        session['state'] = new_state

        # Persist on state transitions
        if current_state != new_state:
            save_session(session_id)

        return jsonify({
            'previous_state': current_state,
            'current_state': new_state,
            'event': event,
            'session': {
                'C': session['C'],
                'kappa': session['kappa'],
                'wake_count': session['wake_count']
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@voice_runtime_bp.route('/session/<session_id>', methods=['GET'])
@require_auth
def get_session_info(session_id):
    """Získat informace o session"""
    session = get_session(session_id)
    return jsonify({
        'session_id': session_id,
        'state': session['state'],
        'metrics': {
            'C': session['C'],
            'kappa': session['kappa'],
            'alpha': session['alpha']
        },
        'system_state': get_system_state(session['C']),
        'wake_count': session['wake_count'],
        'created': session['created']
    })

@voice_runtime_bp.route('/prompt', methods=['GET'])
def get_claude_prompt():
    """
    Vrátí system prompt pro Claude Voice Runtime
    """
    prompt = """Jsi RADIM, hlasový agent pro seniory a chytré prostředí.
Odpovídáš pouze na dotazy, které prošly wakewordem „Radime?" a relevance filtrem.
Nikdy neodpovídáš na televizi ani cizí rozhovor.
Máš k dispozici stavové metriky z matematického enginu: C(t), κ(t), α(t), stav {HARMONIE, ALERT, KRIZE}.
Tyto metriky jsou pravda. Nikdy si je nevymýšlíš a nikdy je neupravuješ.
Tvůj úkol: vytvořit krátkou, lidskou a bezpečnou odpověď.

* HARMONIE (C<12): přátelsky, normálně dlouhé věty.
* ALERT (12≤C<27): zpomal, zkrať věty, navrhni mikro-intervenci (30–90 s).
* KRIZE (C≥27): 1 instrukce, pauza, opakuj, možnost eskalace (pečující/SOS).

Pokud dotaz není o uživateli, jeho prostředí, bezpečí nebo Radim systému, odpověď je: mlčet (RETURN: NO_RESPONSE).

Matematické konstanty:
φ (zlatý řez) = 1.618034
δ (stříbrný řez) = 2.414214
R (RADIM konstanta) = 3.906

Vždy vracej JSON:
{ "speak": true/false, "text": "…", "action": "…", "confidence": 0..1 }
Pokud speak=false, text prázdný."""
    
    return jsonify({
        'prompt': prompt,
        'version': '1.0.0',
        'constants': {
            'phi': PHI,
            'delta': DELTA,
            'radim_r': RADIM_R
        }
    })

# ============================================
# HLASOVÝ CHAT - OPTIMALIZOVANÝ PRO TTS
# ============================================

import requests
from xml.sax.saxutils import escape as xml_escape

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# ============================================
# ANTICIPATION ENGINE INTEGRATION
# ============================================
try:
    from anticipation_routes import (
        predict_C as ant_predict_C, calculate_emotions as ant_calculate_emotions,
        calculate_speech_params as ant_calculate_speech_params,
        classify_state as ant_classify_state
    )
    _ANT_AVAILABLE = True
except ImportError:
    _ANT_AVAILABLE = False

# Systémový prompt optimalizovaný pro hlasové odpovědi
VOICE_SYSTEM_PROMPT = """Jsi Radim, milý a trpělivý hlasový asistent pro české seniory.

PRAVIDLA PRO ODPOVĚDI:
1. Odpovídej VŽDY česky
2. Maximálně 2-3 krátké věty
3. NIKDY nepoužívej emotikony, hvězdičky ani speciální znaky
4. NIKDY nepoužívej odrážky ani číslované seznamy
5. Mluv jako kamarád - jednoduše a přátelsky
6. Používej běžná česká slova bez cizích termínů
7. Vykej uživateli (Vy, Vám, Váš)

STYL:
- Přátelský a klidný
- Trpělivý a empatický
- Jasný a srozumitelný
- Bez zbytečného balastu

PŘÍKLADY DOBRÝCH ODPOVĚDÍ:
- "Ano, rád pomohu. Co potřebujete?"
- "Počasí je dnes příjemné, asi patnáct stupňů a svítí sluníčko."
- "Rozumím. Zkuste to znovu pomaleji, budu poslouchat."

PŘÍKLADY ŠPATNÝCH ODPOVĚDÍ (nepoužívej):
- "Rád pomohu!" (emotikony)
- "První bod, Druhý bod" (seznamy)
- "Důležité: informace" (markdown)

Dnešní datum: {date}
Svátek má: {nameday}"""

def get_voice_ai_response(messages, context=None):
    """Získat AI odpověď optimalizovanou pro hlasový výstup"""
    from datetime import datetime
    
    now = datetime.now()
    day_names = ['pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota', 'neděle']
    month_names = ['ledna', 'února', 'března', 'dubna', 'května', 'června', 'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']
    # Use real nameday calendar
    try:
        from claude_routes import NAMEDAY_CALENDAR
        nameday = NAMEDAY_CALENDAR.get(now.month, {}).get(now.day, 'Neznámý')
    except ImportError:
        nameday = 'Neznámý'
    date_str = f"{day_names[now.weekday()]}, {now.day}. {month_names[now.month-1]} {now.year}"
    
    system_prompt = VOICE_SYSTEM_PROMPT.format(date=date_str, nameday=nameday)
    
    # Zkusit Gemini
    if GEMINI_API_KEY:
        try:
            conversation = "\n".join([f"{'Uživatel' if m.get('role') == 'user' else 'Radim'}: {m.get('content', '')}" for m in messages[-6:]])
            prompt = f"{system_prompt}\n\nKonverzace:\n{conversation}\n\nRadim:"
            
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 100,
                        "topP": 0.9
                    }
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'candidates' in data and data['candidates']:
                    text = data['candidates'][0]['content']['parts'][0]['text'].strip()
                    text = clean_for_tts(text)
                    return {'response': text, 'provider': 'gemini', 'success': True}
        except Exception as e:
            print(f"Gemini voice error: {e}")
    
    # Fallback na Claude
    if ANTHROPIC_API_KEY:
        try:
            api_messages = [{"role": m.get('role', 'user'), "content": m.get('content', '')} for m in messages[-6:]]
            
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 100,
                    "system": system_prompt,
                    "messages": api_messages
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'content' in data and data['content']:
                    text = data['content'][0]['text'].strip()
                    text = clean_for_tts(text)
                    return {'response': text, 'provider': 'claude', 'success': True}
        except Exception as e:
            print(f"Claude voice error: {e}")
    
    return {'response': 'Omlouvám se, zkuste to prosím znovu.', 'provider': 'fallback', 'success': False}

def clean_for_tts(text):
    """Vyčistit text pro TTS"""
    import re
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001F900-\U0001F9FF"
        u"\U00002600-\U000026FF"
        u"\U00002700-\U000027BF"
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub('', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\*\-]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

@voice_runtime_bp.route('/chat', methods=['POST'])
@require_auth
def voice_chat():
    """Hlasový chat optimalizovaný pro TTS.
    Now integrates Anticipation Engine for adaptive speech parameters."""
    try:
        data = request.json or {}
        messages = data.get('messages', [])
        session_id = data.get('session_id', 'default')
        sensors = data.get('sensors', {})
        bio = data.get('bio', {})

        if not messages:
            return jsonify({'success': False, 'error': 'No messages'}), 400

        session = get_session(session_id)

        # Compute metrics from sensors/bio if provided
        C = session['C']
        alpha = session['alpha']
        if sensors or bio:
            C = compute_C(sensors, bio)
            system_state = get_system_state(C)
            user_text = messages[-1].get('content', '') if messages else ''
            alpha = compute_alpha(system_state, user_text)
            kappa = compute_kappa(C, alpha, session['kappa'])
            session['C'] = C
            session['alpha'] = alpha
            session['kappa'] = kappa

        # Get AI response
        result = get_voice_ai_response(messages)
        response_text = result.get('response', '')

        session['last_tts_text'] = response_text
        session['conversation'].append({'role': 'user', 'content': messages[-1].get('content', '')})
        session['conversation'].append({'role': 'assistant', 'content': response_text})
        save_session(session_id)  # Persist after each chat exchange

        # ============================================
        # ANTICIPATION ENGINE: Adaptive TTS params
        # ============================================
        tts_data = get_tts_params(get_system_state(C))  # Base from voice runtime
        ssml = None

        if _ANT_AVAILABLE and response_text:
            try:
                C_pred = ant_predict_C(C, 0, alpha)
                emotions = ant_calculate_emotions(C_pred, alpha)
                ant_params = ant_calculate_speech_params(C_pred, alpha, emotions)
                state = ant_classify_state(C_pred)

                # Override tts_data with anticipation params
                tts_data['rate'] = ant_params['rate']
                tts_data['pitch'] = f"{ant_params['pitch']:+.0f}Hz"
                tts_data['pause_ms'] = ant_params['pause_ms']
                tts_data['empathy'] = ant_params['empathy']
                tts_data['state'] = state
                tts_data['anticipation'] = True

                # Generate SSML
                rate_pct = int(ant_params['rate'] * 100)
                pitch_hz = f"{ant_params['pitch']:+.0f}Hz" if ant_params['pitch'] != 0 else "+0Hz"
                safe_text = xml_escape(response_text)
                ssml = (f"<speak version='1.0' xml:lang='cs-CZ'>"
                        f"<voice name='cs-CZ-AntoninNeural'>"
                        f"<prosody rate='{rate_pct}%' pitch='{pitch_hz}'>"
                        f"{safe_text}</prosody></voice></speak>")
            except Exception as ae:
                logger.warning(f"Anticipation in /chat (non-fatal): {ae}")

        result['tts_params'] = tts_data
        if ssml:
            result['ssml'] = ssml
        result['metrics'] = {
            'C': round(C, 2),
            'alpha': round(alpha, 3),
            'system_state': get_system_state(C)
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

print("✅ Voice Runtime routes registered: /api/voice/*")
