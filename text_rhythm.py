# -*- coding: utf-8 -*-
"""
🎵 TEXT RHYTHM ENGINE v1.0.0
Anticipation Engine → Text Style Instructions

Stejná matematika, která řídí hlas (rate, pitch, pause),
teď řídí i STYL textu (délka, složitost, empatie, rytmus).

φ = 1.618 (Zlatý řez) — Fibonacci konvergence
Prahy: HARMONY (C<12), ALERT (12≤C<27), CRISIS (C≥27)
"""

import math
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)

# ============================================================================
# IMPORT MATEMATIKY Z ANTICIPATION ENGINE
# ============================================================================

try:
    from anticipation_routes import (
        predict_C as _ant_predict_C,
        calculate_emotions as _ant_emotions,
        calculate_speech_params as _ant_speech_params,
        classify_state as _ant_classify,
        PHI, PSI,
        C_HARMONY, C_ALERT, C_MAX, C_TARGET,
        clamp
    )
    _ANT_AVAILABLE = True
    logger.info("✅ Text Rhythm: Anticipation Engine connected")
except ImportError:
    _ANT_AVAILABLE = False
    PHI = 1.618033988749895
    PSI = 0.618033988749895
    C_HARMONY = 12
    C_ALERT = 27
    C_MAX = 40
    C_TARGET = 18

    def clamp(v, lo, hi):
        return max(lo, min(v, hi))

    logger.warning("⚠️ Text Rhythm: Anticipation Engine not available, using fallback")


# ============================================================================
# KEYWORD SETS (shodné s twilio_voice_routes.py)
# ============================================================================

_CRISIS_WORDS = {
    'pomoc', 'help', 'bolest', 'spadl', 'sos', 'umírám', 'záchranku',
    'nemohu dýchat', 'nemůžu dýchat', 'bolest na hrudi', 'záchranka',
    '155', '112', 'infarkt', 'mrtvice', 'bezvědomí', 'krev'
}

_STRESS_WORDS = {
    'strach', 'bojím', 'nervózní', 'nemocný', 'unavený', 'problém',
    'bolí', 'nespím', 'samota', 'sám', 'smutný', 'osamělý', 'úzkost',
    'panika', 'špatně', 'nemůžu', 'trápí', 'nevím', 'ztracený'
}

_CALM_WORDS = {
    'děkuji', 'díky', 'hezky', 'dobře', 'krásně', 'fajn', 'prima',
    'skvěle', 'výborně', 'pohoda', 'šťastný', 'radost', 'super',
    'báječné', 'nádherné', 'klidný', 'spokojený'
}


# ============================================================================
# TEXT PARAMS BY STATE — Fibonacci/φ driven
# ============================================================================

_TEXT_PARAMS = {
    "HARMONY": {
        "max_sentences": 5,
        "sentence_structure": "fibonacci",   # 1+1+2+3
        "complexity": "natural",
        "empathy_level": "warm",
        "word_choice": "rich",
        "tone": "přátelský, klidný, může být hravý a vtipný",
        "golden_ratio_split": PSI,            # 0.618
        "max_words_per_sentence": 20,
        "temperature_hint": 0.7,
        "max_tokens": 500,
    },
    "ALERT": {
        "max_sentences": 3,
        "sentence_structure": "even",         # 1+1+1
        "complexity": "simple",
        "empathy_level": "high",
        "word_choice": "clear",
        "tone": "klidný, uklidňující, empatický",
        "golden_ratio_split": 0.5,
        "max_words_per_sentence": 12,
        "temperature_hint": 0.5,
        "max_tokens": 250,
    },
    "CRISIS": {
        "max_sentences": 1,
        "sentence_structure": "single",       # 1
        "complexity": "minimal",
        "empathy_level": "maximum",
        "word_choice": "basic",
        "tone": "hluboce klidný, bezpečný, ochranný, jasný",
        "golden_ratio_split": 1.0,
        "max_words_per_sentence": 8,
        "temperature_hint": 0.3,
        "max_tokens": 80,
    }
}


# ============================================================================
# HLAVNÍ FUNKCE
# ============================================================================

def estimate_C_alpha_from_text(message: str, mood: str = "neutral",
                                user_baseline_C: float = None) -> Tuple[float, float]:
    """
    Odvod C a α z textu zprávy a detekované nálady.
    Fallback, když klient nepošle explicitní C/α.

    Args:
        message: Text zprávy uživatele
        mood: Detekovaná nálada ("neutral", "anxious", "sad", "happy")
        user_baseline_C: Personalizované baseline C z profilu (None = default 5.0)

    Returns:
        (C, alpha) tuple
    """
    C = user_baseline_C if user_baseline_C is not None else 5.0
    alpha = 0.2

    text_lower = message.lower()

    # Hledej klíčová slova (i víceslovná)
    crisis_hits = sum(1 for w in _CRISIS_WORDS if w in text_lower)
    stress_hits = sum(1 for w in _STRESS_WORDS if w in text_lower)
    calm_hits = sum(1 for w in _CALM_WORDS if w in text_lower)

    C += crisis_hits * 8
    C += stress_hits * 3
    C -= calm_hits * 2

    # Mood factor
    mood_C = {"anxious": 8, "sad": 5, "neutral": 0, "happy": -3}
    C += mood_C.get(mood, 0)

    C = clamp(C, 0, C_MAX)

    # Alpha
    if crisis_hits > 0:
        alpha = 0.8
    elif stress_hits > 0:
        alpha = 0.5
    elif calm_hits > 0:
        alpha = 0.1

    mood_alpha = {"anxious": 0.6, "sad": 0.4, "neutral": 0.2, "happy": 0.1}
    alpha = max(alpha, mood_alpha.get(mood, 0.2))

    return round(C, 2), round(alpha, 3)


def calculate_text_params(C: float, alpha: float) -> Dict[str, Any]:
    """
    Jádro: přeloží C/α na parametry stylu textu.
    Používá STEJNÝ predict_C a classify_state jako hlas.
    """
    if _ANT_AVAILABLE:
        C_predicted = _ant_predict_C(C, 0, alpha)
        emotions = _ant_emotions(C_predicted, alpha)
        speech_params = _ant_speech_params(C_predicted, alpha, emotions)
        state = _ant_classify(C_predicted)
    else:
        # Minimální fallback bez Anticipation Engine
        C_predicted = C
        if C < C_HARMONY:
            state = "HARMONY"
        elif C < C_ALERT:
            state = "ALERT"
        else:
            state = "CRISIS"
        emotions = {}
        speech_params = {}

    # Základní parametry pro tento stav
    params = _TEXT_PARAMS[state].copy()

    # Fine-tune podle emočního vektoru
    if emotions:
        # Vysoký strach → zkrátit odpověď
        if emotions.get("fear", 0) > 0.5 and state != "CRISIS":
            params["max_sentences"] = max(1, params["max_sentences"] - 1)
            params["empathy_level"] = "high"

        # Vysoká radost v HARMONY → může být rozvinutější
        if emotions.get("joy", 0) > 0.7 and state == "HARMONY":
            params["max_sentences"] = min(6, params["max_sentences"] + 1)
            params["tone"] += ", může být humorný"

        # Vysoký smutek → vždy maximální empatie
        if emotions.get("sadness", 0) > 0.5:
            params["empathy_level"] = "maximum" if state == "CRISIS" else "high"
            params["tone"] = "hluboce empatický, přítomný, žádné fráze"

        # Vysoké napětí → zpomalení
        if emotions.get("tension", 0) > 0.6 and state != "CRISIS":
            params["max_sentences"] = max(2, params["max_sentences"] - 1)

    return {
        "state": state,
        "params": params,
        "C": round(C_predicted, 2),
        "alpha": round(alpha, 3),
        "emotions": {k: round(v, 3) for k, v in emotions.items()} if emotions else {},
        "speech_params": speech_params
    }


def build_anticipation_prompt(text_result: Dict[str, Any]) -> str:
    """
    Generuje instrukce do system promptu — řídí STYL textu.

    AI neví o C/α — dostane jen přirozené pokyny ke stylu.
    Injektuje se do promptu jako personalizace.
    """
    state = text_result["state"]
    params = text_result["params"]
    emotions = text_result.get("emotions", {})

    lines = [""]
    lines.append("═══ RYTMUS ODPOVĚDI ═══")

    if state == "HARMONY":
        lines.append(f"Uživatel je v klidu. Odpovídej přirozeně, až {params['max_sentences']} vět.")
        if params.get("sentence_structure") == "fibonacci":
            lines.append("Rytmus: krátká myšlenka → potvrzení → rozvinutí → závěr s teplem.")
            lines.append("Jádro zprávy v prvních dvou třetinách, zbytek je spojení a blízkost.")
        lines.append(f"Tón: {params['tone']}.")
        if emotions.get("joy", 0) > 0.6:
            lines.append("Uživatel je veselý — buď lehčí, hravější.")

    elif state == "ALERT":
        lines.append(f"Uživatel je napjatý. Maximálně {params['max_sentences']} krátké věty.")
        lines.append("Slova jednoduchá, srozumitelná, bez cizích výrazů.")
        lines.append("Struktura: empatie → informace → návrh.")
        lines.append(f"Tón: {params['tone']}.")
        if emotions.get("fear", 0) > 0.5:
            lines.append("Detekován strach — nabídni uklidnění nebo dechové cvičení.")
        if emotions.get("tension", 0) > 0.6:
            lines.append("Vysoké napětí — mluv pomalu a klidně.")

    elif state == "CRISIS":
        lines.append("⚠️ KRIZOVÝ REŽIM: JEDNA věta. Jasná, jednoduchá, bezpečná.")
        lines.append(f"Tón: {params['tone']}.")
        lines.append("Žádné otázky. Jasný pokyn nebo ujištění.")
        lines.append("Při zdravotní krizi → doporuč 155/112.")

    lines.append("═══════════════════════")

    return "\n".join(lines)


def get_anticipation_metadata(text_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Metadata pro response JSON — frontend může stylovat UI.
    """
    state = text_result["state"]
    params = text_result["params"]

    style_hints = {
        "HARMONY": {"color": "green", "animation": "gentle-pulse", "typing_speed": "normal"},
        "ALERT": {"color": "yellow", "animation": "steady", "typing_speed": "slow"},
        "CRISIS": {"color": "red", "animation": "calm-breathe", "typing_speed": "very-slow"},
    }

    return {
        "state": state,
        "C": text_result["C"],
        "alpha": text_result["alpha"],
        "emotions": text_result.get("emotions", {}),
        "text_params": {
            "max_sentences": params["max_sentences"],
            "complexity": params["complexity"],
            "empathy_level": params["empathy_level"],
            "fibonacci_rhythm": params.get("sentence_structure") == "fibonacci",
            "golden_ratio_split": params.get("golden_ratio_split", PSI),
        },
        "speech_params": text_result.get("speech_params", {}),
        "style_hints": style_hints.get(state, style_hints["HARMONY"]),
        "phi": PHI,
    }


def get_adjusted_generation_config(text_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upravené parametry generování — max_tokens a temperature podle stavu.
    """
    params = text_result["params"]
    return {
        "max_tokens": params.get("max_tokens", 500),
        "temperature": params.get("temperature_hint", 0.7),
    }


def enforce_crisis_limits(text: str, text_result: Dict[str, Any]) -> str:
    """
    Hard enforcement limitů textu PO generování AI odpovědi.

    AI je instruováno dodržovat limity, ale toto garantuje:
    - ALERT: max 3 věty
    - CRISIS: max 1 věta, max 8 slov

    V HARMONY režimu se neomezuje — AI má svobodu.

    Args:
        text: Vygenerovaný text od AI
        text_result: Výstup z calculate_text_params()

    Returns:
        Oříznutý text respektující limity stavu
    """
    import re

    state = text_result.get("state", "HARMONY")

    if state == "HARMONY":
        return text  # Žádné omezení

    params = text_result.get("params", {})
    max_sentences = params.get("max_sentences", 5)
    max_words = params.get("max_words_per_sentence", 20)

    # Rozděl na věty
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    if len(sentences) > max_sentences:
        sentences = sentences[:max_sentences]
        logger.info(f"✂️ Crisis enforcement: trimmed to {max_sentences} sentence(s) [{state}]")

    if state == "CRISIS":
        # Jedna věta, max 8 slov
        first = sentences[0] if sentences else text
        words = first.split()
        if len(words) > max_words:
            first = ' '.join(words[:max_words])
            if not first.endswith(('.', '!', '?')):
                first += '.'
            logger.info(f"✂️ Crisis enforcement: trimmed to {max_words} words")
        return first

    return ' '.join(sentences)
