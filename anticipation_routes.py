"""
🔮 ANTICIPATION ENGINE - Předbudoucí čas pro Speech Agenta
===========================================================
Algoritmus predikce emocí a adaptivního řízení řeči

Matematický model:
- Trendy: T^C_t, T^α_t (EMA)
- Predikce: Ĉ_{t+1} = C_t + k1*T^C + k2*(α - 0.5)
- Stavy: HARMONY (<12), ALERT (12-27), CRISIS (≥27)
- Řízení: empatie, rate, pitch, pause

Orchestrátor: Claude AI
Cíl: Harmonický stav C* ≤ 18, α* ≤ 0.4

Version: 1.0.0
Author: Radim Brain Team
"""

import os
import json
import math
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, g

# Flask Blueprint
anticipation_bp = Blueprint('anticipation', __name__, url_prefix='/api/anticipation')

# ============================================================================
# CONSTANTS - Matematické konstanty
# ============================================================================

PHI = 1.618033988749895  # Zlatý řez φ
PSI = 0.618033988749895  # 1/φ

# Prahy vědomí
C_HARMONY = 12   # Pod tímto = harmonie
C_ALERT = 27     # Nad tímto = krize
C_MAX = 40       # Maximum

# Cílové hodnoty (kam chceme směřovat)
C_TARGET = 18    # Cílové C*
ALPHA_TARGET = 0.4  # Cílové α*
E_CALM_TARGET = 0.6  # Cílová úroveň klidu

# Koeficienty pro predikci
K1 = 1.0      # Váha trendu vědomí
K2 = 7.5      # Váha stresu na vědomí (5-10)
LAMBDA_C = 0.3   # EMA faktor pro trend C
LAMBDA_ALPHA = 0.3  # EMA faktor pro trend α
GAMMA = 0.5   # Faktor pro predikci α

# Koeficienty pro řízení řeči
K_EMP = 0.15   # Koeficient empatie
K_RATE = 0.02  # Koeficient tempa
K_PITCH = 0.5  # Koeficient výšky hlasu (semitones)
K_PAUSE = 15   # Koeficient pauzy (ms)

# Limity řeči
RATE_MIN = 0.7
RATE_MAX = 1.1
PITCH_MIN = -4  # semitones
PITCH_MAX = 2
PAUSE_MIN = 100  # ms
PAUSE_MAX = 800
EMPATHY_MIN = 0.3
EMPATHY_MAX = 1.0

# ============================================================================
# DATABASE
# ============================================================================

DATABASE = 'radim_brain.db'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

def init_anticipation_tables():
    """Initialize anticipation database tables"""
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        # State history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS anticipation_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT DEFAULT 'global',
                C REAL NOT NULL,
                alpha REAL NOT NULL,
                trend_C REAL DEFAULT 0,
                trend_alpha REAL DEFAULT 0,
                predicted_C REAL,
                predicted_alpha REAL,
                state TEXT,
                predicted_state TEXT,
                empathy REAL DEFAULT 0.7,
                rate REAL DEFAULT 0.9,
                pitch REAL DEFAULT 0,
                pause_ms INTEGER DEFAULT 300,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Emotion vectors table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS anticipation_emotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_id INTEGER,
                e_tension REAL,
                e_fear REAL,
                e_hope REAL,
                e_calm REAL,
                e_joy REAL,
                e_sadness REAL,
                is_predicted BOOLEAN DEFAULT FALSE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (state_id) REFERENCES anticipation_state(id)
            )
        ''')
        
        # Recognition points (body rozpoznání)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS anticipation_breakpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                breakpoint_type TEXT,
                C_before REAL,
                C_after REAL,
                action_taken TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Anticipation tables initialized")
    except Exception as e:
        print(f"⚠️ Anticipation tables init error: {e}")

init_anticipation_tables()

# ============================================================================
# MATHEMATICAL FUNCTIONS
# ============================================================================

def sigmoid(x, k=1, x0=0):
    """Sigmoid funkce: σ(x) = 1 / (1 + e^(-k*(x-x0)))"""
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if x < x0 else 1.0

def clamp(value, min_val, max_val):
    """Omezení hodnoty do intervalu"""
    return max(min_val, min(max_val, value))

def calculate_trend(current, previous, trend_prev, lambda_factor):
    """
    Exponenciální klouzavý průměr trendu
    T_t = (1 - λ) * T_{t-1} + λ * ΔX_t
    """
    delta = current - previous
    return (1 - lambda_factor) * trend_prev + lambda_factor * delta

def predict_C(C_current, trend_C, alpha_current):
    """
    Predikce vědomí Ĉ_{t+1}
    Ĉ_{t+1} = C_t + k1 * T^C_t + k2 * (α_t - 0.5)
    """
    predicted = C_current + K1 * trend_C + K2 * (alpha_current - 0.5)
    return clamp(predicted, 0, C_MAX)

def predict_alpha(alpha_current, trend_alpha):
    """
    Predikce stresu α̂_{t+1}
    α̂_{t+1} = α_t + γ * T^α_t
    """
    predicted = alpha_current + GAMMA * trend_alpha
    return clamp(predicted, 0, 1)

def classify_state(C):
    """
    Klasifikace stavu vědomí
    HARMONY: C < 12
    ALERT: 12 ≤ C < 27
    CRISIS: C ≥ 27
    """
    if C < C_HARMONY:
        return "HARMONY"
    elif C < C_ALERT:
        return "ALERT"
    else:
        return "CRISIS"

def calculate_emotions(C, alpha, memory_factor=0.5):
    """
    Výpočet emočního vektoru E_t = g(C_t, α_t, memory)
    
    Vrací: {tension, fear, hope, calm, joy, sadness}
    """
    # Normalizované C do [0, 1]
    C_norm = C / C_MAX
    
    # Tension: roste s C a α
    e_tension = sigmoid(C_norm + alpha, k=3, x0=0.5)
    
    # Fear: vysoké při vysokém C a α
    e_fear = sigmoid(C_norm * 1.5 + alpha * 0.5, k=4, x0=0.7)
    
    # Hope: klesá s C, roste s nízkou α
    e_hope = sigmoid(1 - C_norm - alpha * 0.5, k=3, x0=0.3)
    
    # Calm: opak tension
    e_calm = 1 - e_tension
    
    # Joy: nízké C, nízká α
    e_joy = sigmoid(1 - C_norm * 1.2 - alpha * 0.8, k=4, x0=0.4)
    
    # Sadness: vysoké C, střední α
    e_sadness = sigmoid(C_norm + abs(alpha - 0.5), k=2, x0=0.6)
    
    # Memory factor moduluje emoce
    return {
        "tension": clamp(e_tension * (1 + memory_factor * 0.2), 0, 1),
        "fear": clamp(e_fear * (1 + memory_factor * 0.1), 0, 1),
        "hope": clamp(e_hope * (1 - memory_factor * 0.1), 0, 1),
        "calm": clamp(e_calm * (1 - memory_factor * 0.15), 0, 1),
        "joy": clamp(e_joy * (1 - memory_factor * 0.1), 0, 1),
        "sadness": clamp(e_sadness * (1 + memory_factor * 0.15), 0, 1)
    }

def calculate_speech_params(C_predicted, alpha_predicted, emotions_predicted, current_params=None):
    """
    Výpočet parametrů řeči na základě predikce
    
    Pravidla:
    - Vysoké C nebo fear → zvýšit empatii, snížit tempo, prohloubit hlas, prodloužit pauzy
    - Nízké C a calm → normální parametry
    """
    # Výchozí parametry
    if current_params is None:
        current_params = {
            "empathy": 0.7,
            "rate": 0.9,
            "pitch": 0,
            "pause_ms": 300
        }
    
    # Odchylky od cílových hodnot
    delta_C = max(0, C_predicted - C_TARGET)
    delta_fear = max(0, emotions_predicted["fear"] - 0.3)
    
    # Nové parametry
    new_empathy = current_params["empathy"] + K_EMP * delta_fear
    new_rate = current_params["rate"] * (1 - K_RATE * delta_C)
    new_pitch = current_params["pitch"] - K_PITCH * delta_C
    new_pause = current_params["pause_ms"] + K_PAUSE * delta_C
    
    # Clamp do limitů
    return {
        "empathy": round(clamp(new_empathy, EMPATHY_MIN, EMPATHY_MAX), 2),
        "rate": round(clamp(new_rate, RATE_MIN, RATE_MAX), 2),
        "pitch": round(clamp(new_pitch, PITCH_MIN, PITCH_MAX), 1),
        "pause_ms": int(clamp(new_pause, PAUSE_MIN, PAUSE_MAX)),
        "adjustments": {
            "delta_C": round(delta_C, 2),
            "delta_fear": round(delta_fear, 2),
            "reason": get_adjustment_reason(C_predicted, emotions_predicted)
        }
    }

def get_adjustment_reason(C_predicted, emotions):
    """Lidsky čitelný důvod úpravy"""
    if C_predicted >= C_ALERT:
        return "Blíží se krizový stav - maximální empatie a klid"
    elif C_predicted >= C_HARMONY:
        if emotions["fear"] > 0.5:
            return "Detekován strach - zpomalení a uklidnění"
        elif emotions["tension"] > 0.6:
            return "Vysoké napětí - jemný přístup"
        else:
            return "Mírně zvýšená pozornost"
    else:
        if emotions["joy"] > 0.6:
            return "Radostná nálada - udržet pozitivitu"
        else:
            return "Harmonický stav - normální tempo"

def detect_breakpoints(C_current, C_predicted):
    """
    Detekce bodů rozpoznání (přechody přes prahy)
    
    B_12: přechod přes 12 (konec harmonie)
    B_27: přechod přes 27 (začátek krize)
    """
    breakpoints = []
    
    # Přechod přes 12 (opouštíme harmonii)
    if C_current < C_HARMONY and C_predicted >= C_HARMONY:
        breakpoints.append({
            "type": "B_12",
            "direction": "up",
            "message": "⚠️ Opouštíme harmonii - zvýšit pozornost",
            "action": "increase_empathy"
        })
    
    # Návrat pod 12 (vstupujeme do harmonie)
    if C_current >= C_HARMONY and C_predicted < C_HARMONY:
        breakpoints.append({
            "type": "B_12",
            "direction": "down",
            "message": "✅ Vstupujeme do harmonie",
            "action": "normalize"
        })
    
    # Přechod přes 27 (vstupujeme do krize)
    if C_current < C_ALERT and C_predicted >= C_ALERT:
        breakpoints.append({
            "type": "B_27",
            "direction": "up",
            "message": "🚨 KRIZE - aktivovat krizový protokol",
            "action": "crisis_protocol"
        })
    
    # Návrat pod 27 (opouštíme krizi)
    if C_current >= C_ALERT and C_predicted < C_ALERT:
        breakpoints.append({
            "type": "B_27",
            "direction": "down",
            "message": "📉 Opouštíme krizi - pokračovat v deeskalaci",
            "action": "continue_deescalation"
        })
    
    return breakpoints

# ============================================================================
# ROUTES
# ============================================================================

@anticipation_bp.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        "success": True,
        "service": "Anticipation Engine",
        "version": "1.0.0",
        "phi": PHI,
        "thresholds": {
            "harmony": C_HARMONY,
            "alert": C_ALERT,
            "max": C_MAX
        },
        "timestamp": datetime.utcnow().isoformat()
    })


@anticipation_bp.route('/predict', methods=['POST'])
def predict():
    """
    🔮 Hlavní endpoint pro predikci předbudoucnosti
    
    Input:
    {
        "C": 15.5,           # Aktuální vědomí
        "alpha": 0.45,       # Aktuální stres
        "C_prev": 14.0,      # Předchozí vědomí (volitelné)
        "alpha_prev": 0.4,   # Předchozí stres (volitelné)
        "trend_C": 0.5,      # Předchozí trend C (volitelné)
        "trend_alpha": 0.1,  # Předchozí trend α (volitelné)
        "user_id": "global", # ID uživatele (volitelné)
        "current_speech": {  # Aktuální parametry řeči (volitelné)
            "empathy": 0.7,
            "rate": 0.9,
            "pitch": 0,
            "pause_ms": 300
        }
    }
    
    Output:
    {
        "success": true,
        "current": { C, alpha, state, emotions },
        "predicted": { C, alpha, state, emotions },
        "speech_params": { empathy, rate, pitch, pause_ms },
        "breakpoints": [...],
        "orchestrator_instructions": "..."
    }
    """
    try:
        data = request.get_json() or {}
        
        # Aktuální stav
        C_current = float(data.get('C', 10))
        alpha_current = float(data.get('alpha', 0.3))
        
        # Předchozí stav (pro trend)
        C_prev = float(data.get('C_prev', C_current))
        alpha_prev = float(data.get('alpha_prev', alpha_current))
        
        # Předchozí trendy
        trend_C_prev = float(data.get('trend_C', 0))
        trend_alpha_prev = float(data.get('trend_alpha', 0))
        
        # User ID
        user_id = data.get('user_id', 'global')
        
        # Aktuální parametry řeči
        current_speech = data.get('current_speech')
        
        # 1. Vypočítat trendy
        trend_C = calculate_trend(C_current, C_prev, trend_C_prev, LAMBDA_C)
        trend_alpha = calculate_trend(alpha_current, alpha_prev, trend_alpha_prev, LAMBDA_ALPHA)
        
        # 2. Predikce
        C_predicted = predict_C(C_current, trend_C, alpha_current)
        alpha_predicted = predict_alpha(alpha_current, trend_alpha)
        
        # 3. Klasifikace stavů
        state_current = classify_state(C_current)
        state_predicted = classify_state(C_predicted)
        
        # 4. Emoce - aktuální a predikované
        emotions_current = calculate_emotions(C_current, alpha_current)
        emotions_predicted = calculate_emotions(C_predicted, alpha_predicted)
        
        # 5. Parametry řeči
        speech_params = calculate_speech_params(C_predicted, alpha_predicted, emotions_predicted, current_speech)
        
        # 6. Body rozpoznání
        breakpoints = detect_breakpoints(C_current, C_predicted)
        
        # 7. Instrukce pro orchestrátora (Claude)
        orchestrator_instructions = generate_orchestrator_instructions(
            C_current, C_predicted,
            state_current, state_predicted,
            emotions_predicted, breakpoints
        )
        
        # Uložit stav do databáze
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO anticipation_state 
                (user_id, C, alpha, trend_C, trend_alpha, predicted_C, predicted_alpha, 
                 state, predicted_state, empathy, rate, pitch, pause_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, C_current, alpha_current, trend_C, trend_alpha,
                  C_predicted, alpha_predicted, state_current, state_predicted,
                  speech_params["empathy"], speech_params["rate"],
                  speech_params["pitch"], speech_params["pause_ms"]))
            conn.commit()
            conn.close()
        except Exception as db_error:
            print(f"⚠️ DB save error: {db_error}")
        
        return jsonify({
            "success": True,
            "current": {
                "C": round(C_current, 2),
                "alpha": round(alpha_current, 3),
                "state": state_current,
                "emotions": {k: round(v, 3) for k, v in emotions_current.items()}
            },
            "predicted": {
                "C": round(C_predicted, 2),
                "alpha": round(alpha_predicted, 3),
                "state": state_predicted,
                "emotions": {k: round(v, 3) for k, v in emotions_predicted.items()}
            },
            "trends": {
                "C": round(trend_C, 3),
                "alpha": round(trend_alpha, 4)
            },
            "speech_params": speech_params,
            "breakpoints": breakpoints,
            "orchestrator_instructions": orchestrator_instructions,
            "phi": PHI,
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        print(f"❌ Anticipation error: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@anticipation_bp.route('/speech-adjust', methods=['POST'])
def speech_adjust():
    """
    🗣️ Rychlý endpoint pro úpravu řeči
    Používá se při každém promluvy Radima
    
    Input:
    {
        "text": "Dobrý den, jak se máte?",
        "C": 15,
        "alpha": 0.4,
        "emotion_hint": "greeting"  # volitelné
    }
    
    Output:
    {
        "ssml": "<speak>...</speak>",
        "params": { rate, pitch, pause_ms, empathy },
        "voice": "cs-CZ-AntoninNeural"
    }
    """
    try:
        data = request.get_json() or {}
        
        text = data.get('text', '')
        C = float(data.get('C', 10))
        alpha = float(data.get('alpha', 0.3))
        emotion_hint = data.get('emotion_hint', 'neutral')
        
        if not text:
            return jsonify({"success": False, "error": "Text is required"}), 400
        
        # Predikce
        C_predicted = predict_C(C, 0, alpha)  # Bez trendu pro rychlost
        emotions = calculate_emotions(C_predicted, alpha)
        
        # Parametry řeči
        speech_params = calculate_speech_params(C_predicted, alpha, emotions)
        
        # Generovat SSML
        rate_percent = int(speech_params["rate"] * 100)
        pitch_hz = f"{speech_params['pitch']:+.0f}Hz" if speech_params["pitch"] != 0 else "+0Hz"
        
        ssml = f"""<speak version='1.0' xml:lang='cs-CZ'>
    <voice name='cs-CZ-AntoninNeural'>
        <prosody rate='{rate_percent}%' pitch='{pitch_hz}'>
            {text}
        </prosody>
    </voice>
</speak>"""
        
        return jsonify({
            "success": True,
            "ssml": ssml,
            "params": speech_params,
            "voice": "cs-CZ-AntoninNeural",
            "state": classify_state(C_predicted),
            "emotions": {k: round(v, 2) for k, v in emotions.items()},
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@anticipation_bp.route('/history', methods=['GET'])
def get_history():
    """
    📊 Historie stavů anticipace
    """
    try:
        user_id = request.args.get('user_id', 'global')
        limit = request.args.get('limit', 50, type=int)
        
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT C, alpha, trend_C, trend_alpha, predicted_C, predicted_alpha,
                   state, predicted_state, empathy, rate, pitch, pause_ms, timestamp
            FROM anticipation_state
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (user_id, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            history.append({
                "C": row[0],
                "alpha": row[1],
                "trend_C": row[2],
                "trend_alpha": row[3],
                "predicted_C": row[4],
                "predicted_alpha": row[5],
                "state": row[6],
                "predicted_state": row[7],
                "speech": {
                    "empathy": row[8],
                    "rate": row[9],
                    "pitch": row[10],
                    "pause_ms": row[11]
                },
                "timestamp": row[12]
            })
        
        return jsonify({
            "success": True,
            "history": history,
            "count": len(history),
            "user_id": user_id
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def generate_orchestrator_instructions(C_current, C_predicted, state_current, state_predicted, emotions, breakpoints):
    """
    Generuje instrukce pro Claude orchestrátora
    """
    instructions = []
    
    # Základní stav
    instructions.append(f"Aktuální stav: {state_current} (C={C_current:.1f})")
    instructions.append(f"Predikovaný stav: {state_predicted} (Ĉ={C_predicted:.1f})")
    
    # Body rozpoznání
    if breakpoints:
        for bp in breakpoints:
            instructions.append(f"🔔 {bp['message']}")
    
    # Emoční doporučení
    if emotions["fear"] > 0.5:
        instructions.append("⚠️ Vysoký strach - použij uklidňující tón, nabídni dechové cvičení")
    if emotions["sadness"] > 0.6:
        instructions.append("💙 Detekován smutek - projev empatii, zeptej se na pocity")
    if emotions["joy"] > 0.7:
        instructions.append("☀️ Radostná nálada - udržuj pozitivitu, můžeš být veselejší")
    if emotions["tension"] > 0.6:
        instructions.append("🔴 Vysoké napětí - mluv pomalu, nabídni přestávku")
    
    # Stav-specifické instrukce
    if state_predicted == "CRISIS":
        instructions.append("🚨 KRIZOVÝ PROTOKOL: Maximální empatie, pomalá řeč, nabídni kontakt na opatrovníka")
    elif state_predicted == "ALERT":
        instructions.append("⚡ POZOR: Monitoruj situaci, připrav deeskalační techniky")
    else:
        instructions.append("✅ HARMONIE: Normální konverzace, můžeš být hravější")
    
    return " | ".join(instructions)


# ============================================================================
# LOGGING
# ============================================================================

print("🔮 Anticipation Engine loaded - /api/anticipation/* endpoints ready")
print("   Predict: POST /api/anticipation/predict")
print("   Speech Adjust: POST /api/anticipation/speech-adjust")
print("   History: GET /api/anticipation/history")
print(f"   φ = {PHI}, Thresholds: HARMONY<{C_HARMONY}, ALERT<{C_ALERT}, CRISIS≥{C_ALERT}")
