# ============================================
# 🧠 CLAUDE EMOTION ROUTES v1.0.0
# ============================================
# Emotion analysis + consciousness state endpoints.
# Extracted from claude_routes.py for modularity.
# ============================================

import json
import re
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify
from auth_middleware import require_auth

logger = logging.getLogger(__name__)

# Anticipation Engine
try:
    from anticipation_routes import (
        predict_C as _cl_predict_C, calculate_emotions as _cl_ant_emotions,
        calculate_speech_params as _cl_ant_speech, classify_state as _cl_classify
    )
    _CL_ANT_AVAILABLE = True
except ImportError:
    _CL_ANT_AVAILABLE = False

claude_emotion_bp = Blueprint('claude_emotion', __name__, url_prefix='/api/claude')


# ============================================
# LOCAL EMOTION ANALYSIS (fallback)
# ============================================

def analyze_emotions_local(text):
    """Lokální emoční analýza (fallback bez AI)"""
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


def calculate_harmony(emotions):
    """Vypočítej harmonii z emocí"""
    positive = (emotions.get('joy', 0) + emotions.get('hope', 0) +
                emotions.get('calm', 0) + emotions.get('gratitude', 0)) / 4
    negative = (emotions.get('sadness', 0) + emotions.get('fear', 0) +
                emotions.get('tension', 0) + emotions.get('loneliness', 0)) / 4
    return max(0, min(1, positive - negative + 0.5))


# ============================================
# ROUTES
# ============================================

@claude_emotion_bp.route('/analyze-emotion', methods=['POST'])
@require_auth
def analyze_emotion():
    """
    🧠 Analyzuj emoce v textu pro RadimConsciousnessEngine
    Vrací strukturované emoce s intenzitou 0-1
    """
    text = ''
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

        # Try Claude API
        from claude_routes import get_claude_client, extract_text_from_response
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


@claude_emotion_bp.route('/consciousness-state', methods=['POST'])
@require_auth
def get_consciousness_state():
    """
    🧠 Získat doporučení pro stav vědomí
    """
    try:
        data = request.get_json() or {}
        emotions = data.get('emotions', {})

        harmony = calculate_harmony(emotions)
        crisis_level = data.get('crisis_level', emotions.get('crisis_level', 0))

        # Convert crisis_level (0-10) to C (0-40)
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


logger.info("✅ Claude Emotion routes loaded — /api/claude/analyze-emotion, /api/claude/consciousness-state")
