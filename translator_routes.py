"""
🌐 Translator — Visegrad + English (V4 + EN)
=============================================================================
Senior-friendly translator optimized for the V4 / Visegrad Fund conference.

Supported languages: Czech (cs), Slovak (sk), Polish (pl), Hungarian (hu),
English (en). Auto-detection supported as source.

Pipeline:
    1. Gemini 2.0 Flash (primary — excellent V4 quality, fast, already paid)
    2. MyMemory public API (free fallback — no key required)

Endpoint:
    POST /api/translate
        Body: { text, source, target }
        Returns: { success, translated, source, target, detected_source, provider }

    GET /api/translate/languages
        Returns: { languages: [{code, name, native, tts}] }
"""

import logging
import os
import re

import requests
from flask import Blueprint, jsonify, request

from rate_limiter import rate_limit

logger = logging.getLogger(__name__)

translator_bp = Blueprint("translator", __name__)


# ═══════════════════════════════════════════════════════════════════
# LANGUAGES
# ═══════════════════════════════════════════════════════════════════

LANGUAGES = [
    {"code": "cs", "name": "Čeština",    "native": "Čeština",    "tts": "cs-CZ", "flag": "🇨🇿"},
    {"code": "sk", "name": "Slovenština", "native": "Slovenčina", "tts": "sk-SK", "flag": "🇸🇰"},
    {"code": "pl", "name": "Polština",   "native": "Polski",     "tts": "pl-PL", "flag": "🇵🇱"},
    {"code": "hu", "name": "Maďarština", "native": "Magyar",     "tts": "hu-HU", "flag": "🇭🇺"},
    {"code": "en", "name": "Angličtina", "native": "English",    "tts": "en-US", "flag": "🇬🇧"},
]
LANG_CODES = frozenset(l["code"] for l in LANGUAGES)
LANG_NAME = {l["code"]: l["native"] for l in LANGUAGES}

MAX_INPUT_CHARS = 5000


# ═══════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════

@translator_bp.route("/api/translate/languages", methods=["GET", "OPTIONS"])
def list_languages():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200
    return jsonify({"success": True, "languages": LANGUAGES}), 200


@translator_bp.route("/api/translate", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=60, window_seconds=60, key_func="ip")
def translate():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    source = (data.get("source") or "auto").strip().lower()
    target = (data.get("target") or "").strip().lower()

    if not text:
        return jsonify({"success": False, "error": 'Parametr "text" je povinný.'}), 400
    if len(text) > MAX_INPUT_CHARS:
        return jsonify({
            "success": False,
            "error": f"Text je příliš dlouhý (max {MAX_INPUT_CHARS} znaků).",
        }), 400
    if target not in LANG_CODES:
        return jsonify({
            "success": False,
            "error": f'Cílový jazyk "{target}" není podporovaný. Povolené: {", ".join(sorted(LANG_CODES))}.',
        }), 400
    if source != "auto" and source not in LANG_CODES:
        return jsonify({
            "success": False,
            "error": f'Zdrojový jazyk "{source}" není podporovaný.',
        }), 400

    # If source = target, return as-is (no API call).
    if source != "auto" and source == target:
        return jsonify({
            "success": True,
            "translated": text,
            "source": source,
            "target": target,
            "detected_source": source,
            "provider": "noop",
        }), 200

    # Auto-detect source if needed (for both API path quality + UX).
    detected_source = source if source != "auto" else _quick_detect(text)

    # Short-circuit if detection matches target
    if detected_source == target:
        return jsonify({
            "success": True,
            "translated": text,
            "source": source,
            "target": target,
            "detected_source": detected_source,
            "provider": "noop",
        }), 200

    # 1. Primary: Gemini (best V4 quality, already paid for).
    translated, provider = _translate_gemini(text, detected_source, target)
    # 2. Fallback: MyMemory (free, no key).
    if translated is None:
        translated, provider = _translate_mymemory(text, detected_source, target)

    if translated is None:
        return jsonify({
            "success": False,
            "error": "Překladač je dočasně nedostupný. Zkuste to prosím za chvíli.",
        }), 503

    return jsonify({
        "success": True,
        "translated": translated,
        "source": source,
        "target": target,
        "detected_source": detected_source,
        "provider": provider,
    }), 200


# ═══════════════════════════════════════════════════════════════════
# DETECTION — cheap heuristic (good enough for V4+EN short texts)
# ═══════════════════════════════════════════════════════════════════

_HU_CHARS = set("áéíóöőúüű")
_PL_CHARS = set("ąćęłńóśźż")
_CS_CHARS = set("áčďéěíňóřšťúůýž")
_SK_CHARS = set("áäčďéíĺľňóôŕšťúýž")


def _quick_detect(text: str) -> str:
    """Lightweight language detection. Biased toward V4+EN.

    Returns language code. Defaults to 'en' when no clear signal.
    """
    t = text.lower()
    chars = set(t)

    # Hungarian is very distinctive (many double-acute vowels)
    if chars & _HU_CHARS:
        # Stronger signal: őű distinctively Hungarian
        if any(c in t for c in "őű"):
            return "hu"
        # Could also be CS/SK. Try more Hungarian cues.
        if re.search(r"\b(hogy|nem|van|egy|ami|és|vagy|csak)\b", t):
            return "hu"

    # Polish (unique: ą ę ł ś ź ż)
    if chars & _PL_CHARS:
        return "pl"

    # Czech vs Slovak — both share ěščřž; Slovak uses ô ĺ ľ ŕ, Czech uses ě ř ů
    if any(c in t for c in "ěůř"):
        return "cs"
    if any(c in t for c in "ôĺľŕ"):
        return "sk"
    # Slovak-only words (distinctive vs Czech)
    if re.search(r"\b(som|sme|ste|sú|nie je|pretože|aby|teraz|ako|čo|kde|kto|prečo|ďakujem)\b", t):
        return "sk"
    # Czech-only words
    if re.search(r"\b(jsem|jsme|jste|jsou|není|proto|protože|proč|kdo|děkuji|ahoj)\b", t):
        return "cs"
    if chars & _CS_CHARS or chars & _SK_CHARS:
        return "cs"  # default diacritic => Czech

    # English if all ASCII and common stop words
    if re.search(r"\b(the|is|are|and|for|you|have|with|this|hello|thanks)\b", t):
        return "en"

    return "en"


# ═══════════════════════════════════════════════════════════════════
# GEMINI (primary)
# ═══════════════════════════════════════════════════════════════════

def _translate_gemini(text: str, source: str, target: str):
    """Translate via Gemini 2.0 Flash. Returns (text, provider) or (None, None)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, None

    src_name = LANG_NAME.get(source, source)
    tgt_name = LANG_NAME.get(target, target)

    prompt = (
        f"Translate the following text from {src_name} to {tgt_name}. "
        "Output ONLY the translation — no introduction, no quotation marks, "
        "no notes, no alternatives. Preserve line breaks and punctuation. "
        "If the text is a proper noun, a name, or already in the target language, "
        "return it unchanged.\n\n"
        f"Text:\n{text}"
    )

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 2048,
                "top_p": 0.9,
            },
        )
        if not resp or not getattr(resp, "text", None):
            return None, None
        out = resp.text.strip()
        # Strip any lingering quotes/intro that Gemini sometimes adds
        out = _strip_wrapping_quotes(out)
        if not out:
            return None, None
        return out, "gemini-2.0-flash"
    except Exception as e:
        logger.warning(f"Gemini translate failed: {e}")
        return None, None


def _strip_wrapping_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2:
        if (s[0] == '"' and s[-1] == '"') or (s[0] == '„' and s[-1] == '"'):
            s = s[1:-1].strip()
    return s


# ═══════════════════════════════════════════════════════════════════
# MYMEMORY (fallback — no key, 5000 chars/day per anonymous IP)
# ═══════════════════════════════════════════════════════════════════

def _translate_mymemory(text: str, source: str, target: str):
    """Translate via public MyMemory API. Returns (text, provider) or (None, None)."""
    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={
                "q": text,
                "langpair": f"{source}|{target}",
            },
            timeout=10,
            headers={"User-Agent": "RadimCare/1.0 (senior translator)"},
        )
        if resp.status_code != 200:
            return None, None
        data = resp.json()
        translated = (data.get("responseData") or {}).get("translatedText")
        if not translated:
            return None, None
        # MyMemory sometimes returns uppercase error strings in responseData.
        if "MYMEMORY WARNING" in translated.upper():
            return None, None
        return translated.strip(), "mymemory"
    except Exception as e:
        logger.warning(f"MyMemory translate failed: {e}")
        return None, None


logger.info("🌐 Translator routes loaded: /api/translate")
