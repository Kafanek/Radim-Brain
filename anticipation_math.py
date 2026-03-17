# ============================================
# 🔮 ANTICIPATION MATH v1.0.0
# ============================================
# Mathematical constants, functions, and emotion model
# for the Anticipation Engine.
# Extracted from anticipation_routes.py for modularity.
# ============================================

import math
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PHI = 1.618033988749895  # Zlatý řez φ
PSI = 0.618033988749895  # 1/φ

# Prahy vědomí
C_HARMONY = 12   # Pod tímto = harmonie
C_ALERT = 27     # Nad tímto = krize
C_MAX = 40       # Maximum

# Cílové hodnoty
C_TARGET = 18    # Cílové C*
ALPHA_TARGET = 0.4  # Cílové α*
E_CALM_TARGET = 0.6  # Cílová úroveň klidu

# Koeficienty pro predikci
K1 = 1.0
K2 = 7.5
LAMBDA_C = 0.3
LAMBDA_ALPHA = 0.3
GAMMA = 0.5

# Baseline C/α per modality
BASELINE_AMBIENT = {'C': 5.0, 'alpha': 0.0}
BASELINE_PHONE = {'C': 5.0, 'alpha': 0.2}
BASELINE_CHAT = {'C': 5.0, 'alpha': 0.1}

# Koeficienty pro řízení řeči
K_EMP = 0.15
K_RATE = 0.02
K_PITCH = 0.5
K_PAUSE = 15

# Limity řeči
RATE_MIN = 0.7
RATE_MAX = 1.1
PITCH_MIN = -4
PITCH_MAX = 2
PAUSE_MIN = 100
PAUSE_MAX = 800
EMPATHY_MIN = 0.3
EMPATHY_MAX = 1.0


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
    HARMONY: C < 12, ALERT: 12 ≤ C < 27, CRISIS: C ≥ 27
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
    C_norm = C / C_MAX

    e_tension = sigmoid(C_norm + alpha, k=3, x0=0.5)
    e_fear = sigmoid(C_norm * 1.5 + alpha * 0.5, k=4, x0=0.7)
    e_hope = sigmoid(1 - C_norm - alpha * 0.5, k=3, x0=0.3)
    e_calm = 1 - e_tension
    e_joy = sigmoid(1 - C_norm * 1.2 - alpha * 0.8, k=4, x0=0.4)
    e_sadness = sigmoid(C_norm + abs(alpha - 0.5), k=2, x0=0.6)

    return {
        "tension": clamp(e_tension * (1 + memory_factor * 0.2), 0, 1),
        "fear": clamp(e_fear * (1 + memory_factor * 0.1), 0, 1),
        "hope": clamp(e_hope * (1 - memory_factor * 0.1), 0, 1),
        "calm": clamp(e_calm * (1 - memory_factor * 0.15), 0, 1),
        "joy": clamp(e_joy * (1 - memory_factor * 0.1), 0, 1),
        "sadness": clamp(e_sadness * (1 + memory_factor * 0.15), 0, 1)
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


def calculate_speech_params(C_predicted, alpha_predicted, emotions_predicted, current_params=None):
    """
    Výpočet parametrů řeči na základě predikce
    """
    if current_params is None:
        current_params = {
            "empathy": 0.7,
            "rate": 0.9,
            "pitch": 0,
            "pause_ms": 300
        }

    delta_C = max(0, C_predicted - C_TARGET)
    delta_fear = max(0, emotions_predicted["fear"] - 0.3)

    new_empathy = current_params["empathy"] + K_EMP * delta_fear
    new_rate = current_params["rate"] * (1 - K_RATE * delta_C)
    new_pitch = current_params["pitch"] - K_PITCH * delta_C
    new_pause = current_params["pause_ms"] + K_PAUSE * delta_C

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


def detect_breakpoints(C_current, C_predicted):
    """
    Detekce bodů rozpoznání (přechody přes prahy)
    B_12: přechod přes 12, B_27: přechod přes 27
    """
    breakpoints = []

    if C_current < C_HARMONY and C_predicted >= C_HARMONY:
        breakpoints.append({
            "type": "B_12", "direction": "up",
            "message": "⚠️ Opouštíme harmonii - zvýšit pozornost",
            "action": "increase_empathy"
        })

    if C_current >= C_HARMONY and C_predicted < C_HARMONY:
        breakpoints.append({
            "type": "B_12", "direction": "down",
            "message": "✅ Vstupujeme do harmonie",
            "action": "normalize"
        })

    if C_current < C_ALERT and C_predicted >= C_ALERT:
        breakpoints.append({
            "type": "B_27", "direction": "up",
            "message": "🚨 KRIZE - aktivovat krizový protokol",
            "action": "crisis_protocol"
        })

    if C_current >= C_ALERT and C_predicted < C_ALERT:
        breakpoints.append({
            "type": "B_27", "direction": "down",
            "message": "📉 Opouštíme krizi - pokračovat v deeskalaci",
            "action": "continue_deescalation"
        })

    return breakpoints


def generate_orchestrator_instructions(C_current, C_predicted, state_current, state_predicted, emotions, breakpoints):
    """Generuje instrukce pro Claude orchestrátora"""
    instructions = []

    instructions.append(f"Aktuální stav: {state_current} (C={C_current:.1f})")
    instructions.append(f"Predikovaný stav: {state_predicted} (Ĉ={C_predicted:.1f})")

    if breakpoints:
        for bp in breakpoints:
            instructions.append(f"🔔 {bp['message']}")

    if emotions["fear"] > 0.5:
        instructions.append("⚠️ Vysoký strach - použij uklidňující tón, nabídni dechové cvičení")
    if emotions["sadness"] > 0.6:
        instructions.append("💙 Detekován smutek - projev empatii, zeptej se na pocity")
    if emotions["joy"] > 0.7:
        instructions.append("☀️ Radostná nálada - udržuj pozitivitu, můžeš být veselejší")
    if emotions["tension"] > 0.6:
        instructions.append("🔴 Vysoké napětí - mluv pomalu, nabídni přestávku")

    if state_predicted == "CRISIS":
        instructions.append("🚨 KRIZOVÝ PROTOKOL: Maximální empatie, pomalá řeč, nabídni kontakt na opatrovníka")
    elif state_predicted == "ALERT":
        instructions.append("⚡ POZOR: Monitoruj situaci, připrav deeskalační techniky")
    else:
        instructions.append("✅ HARMONIE: Normální konverzace, můžeš být hravější")

    return " | ".join(instructions)


logger.info("✅ Anticipation Math loaded — constants, prediction, emotions, speech params")
