"""
🔮 ANTICIPATION ENGINE — Routes v1.1.0
===========================================================
API endpoints for the Anticipation Engine.
Math + constants in anticipation_math.py.

Routes:
  GET  /api/anticipation/health
  POST /api/anticipation/predict
  POST /api/anticipation/speech-adjust
  GET  /api/anticipation/history
"""

import sqlite3
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
from flask import Blueprint, request, jsonify, g
import logging

logger = logging.getLogger(__name__)

# Flask Blueprint
anticipation_bp = Blueprint('anticipation', __name__, url_prefix='/api/anticipation')

# ============================================================================
# IMPORTS FROM MATH MODULE (+ re-exports for backward compat)
# ============================================================================

from anticipation_math import (
    # Constants
    PHI, PSI, C_HARMONY, C_ALERT, C_MAX,
    C_TARGET, ALPHA_TARGET, E_CALM_TARGET,
    K1, K2, LAMBDA_C, LAMBDA_ALPHA, GAMMA,
    BASELINE_AMBIENT, BASELINE_PHONE, BASELINE_CHAT,
    K_EMP, K_RATE, K_PITCH, K_PAUSE,
    RATE_MIN, RATE_MAX, PITCH_MIN, PITCH_MAX,
    PAUSE_MIN, PAUSE_MAX, EMPATHY_MIN, EMPATHY_MAX,
    # Functions
    sigmoid, clamp,
    calculate_trend, predict_C, predict_alpha,
    classify_state, calculate_emotions,
    calculate_speech_params, get_adjustment_reason,
    detect_breakpoints, generate_orchestrator_instructions,
)

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
    conn = None
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()

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
        logger.info("✅ Anticipation tables initialized")
    except Exception as e:
        logger.error(f"⚠️ Anticipation tables init error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


init_anticipation_tables()


# ============================================================================
# ROUTES
# ============================================================================

@anticipation_bp.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({
        "success": True,
        "service": "Anticipation Engine",
        "version": "1.1.0",
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

    Input: {C, alpha, C_prev, alpha_prev, trend_C, trend_alpha, user_id, current_speech}
    Output: {current, predicted, trends, speech_params, breakpoints, orchestrator_instructions}
    """
    try:
        data = request.get_json(silent=True) or {}

        C_current = float(data.get('C', 10))
        alpha_current = float(data.get('alpha', 0.3))
        C_prev = float(data.get('C_prev', C_current))
        alpha_prev = float(data.get('alpha_prev', alpha_current))
        trend_C_prev = float(data.get('trend_C', 0))
        trend_alpha_prev = float(data.get('trend_alpha', 0))
        user_id = data.get('user_id', 'global')
        current_speech = data.get('current_speech')

        # 1. Trendy
        trend_C = calculate_trend(C_current, C_prev, trend_C_prev, LAMBDA_C)
        trend_alpha = calculate_trend(alpha_current, alpha_prev, trend_alpha_prev, LAMBDA_ALPHA)

        # 2. Predikce
        C_predicted = predict_C(C_current, trend_C, alpha_current)
        alpha_predicted = predict_alpha(alpha_current, trend_alpha)

        # 3. Klasifikace
        state_current = classify_state(C_current)
        state_predicted = classify_state(C_predicted)

        # 4. Emoce
        emotions_current = calculate_emotions(C_current, alpha_current)
        emotions_predicted = calculate_emotions(C_predicted, alpha_predicted)

        # 5. Parametry řeči
        speech_params = calculate_speech_params(C_predicted, alpha_predicted, emotions_predicted, current_speech)

        # 6. Breakpoints
        breakpoints = detect_breakpoints(C_current, C_predicted)

        # 7. Instrukce
        orchestrator_instructions = generate_orchestrator_instructions(
            C_current, C_predicted, state_current, state_predicted,
            emotions_predicted, breakpoints
        )

        # Save to DB
        conn = None
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
        except Exception as db_error:
            logger.error(f"⚠️ DB save error: {db_error}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

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
        logger.error(f"❌ Anticipation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@anticipation_bp.route('/speech-adjust', methods=['POST'])
def speech_adjust():
    """
    🗣️ Rychlý endpoint pro úpravu řeči
    Input: {text, C, alpha, emotion_hint}
    Output: {ssml, params, voice, state, emotions}
    """
    try:
        data = request.get_json(silent=True) or {}

        text = data.get('text', '')
        C = float(data.get('C', 10))
        alpha = float(data.get('alpha', 0.3))

        if not text:
            return jsonify({"success": False, "error": "Text is required"}), 400

        C_predicted = predict_C(C, 0, alpha)
        emotions = calculate_emotions(C_predicted, alpha)
        speech_params = calculate_speech_params(C_predicted, alpha, emotions)

        rate_percent = int(speech_params["rate"] * 100)
        pitch_hz = f"{speech_params['pitch']:+.0f}Hz" if speech_params["pitch"] != 0 else "+0Hz"

        safe_text = xml_escape(text)
        ssml = f"""<speak version='1.0' xml:lang='cs-CZ'>
    <voice name='cs-CZ-AntoninNeural'>
        <prosody rate='{rate_percent}%' pitch='{pitch_hz}'>
            {safe_text}
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
        logger.error(f"⚠️ Speech adjust error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500


@anticipation_bp.route('/history', methods=['GET'])
def get_history():
    """📊 Historie stavů anticipace"""
    try:
        user_id = request.args.get('user_id', 'global')
        limit = request.args.get('limit', 50, type=int)

        conn = None
        try:
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
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        history = []
        for row in rows:
            history.append({
                "C": row[0], "alpha": row[1],
                "trend_C": row[2], "trend_alpha": row[3],
                "predicted_C": row[4], "predicted_alpha": row[5],
                "state": row[6], "predicted_state": row[7],
                "speech": {
                    "empathy": row[8], "rate": row[9],
                    "pitch": row[10], "pause_ms": row[11]
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
        logger.error(f"⚠️ History error: {e}")
        return jsonify({"success": False, "error": "Interní chyba serveru"}), 500


# ============================================================================
# STARTUP
# ============================================================================
logger.info("🔮 Anticipation Engine v1.1.0 loaded — /api/anticipation/*")
logger.info(f"   φ = {PHI}, Thresholds: HARMONY<{C_HARMONY}, ALERT<{C_ALERT}, CRISIS≥{C_ALERT}")
logger.info("   Math module: anticipation_math.py")
