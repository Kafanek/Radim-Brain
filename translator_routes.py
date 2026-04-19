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

    # If source is EXPLICITLY set == target, short-circuit (user asked for no-op).
    if source != "auto" and source == target:
        return jsonify({
            "success": True,
            "translated": text,
            "source": source,
            "target": target,
            "detected_source": source,
            "provider": "noop",
        }), 200

    # Auto-detect source if needed. With auto, we never short-circuit on
    # detection == target — detection is heuristic and can be wrong. Let
    # Gemini have the final say (it can also confirm the text is already
    # in target language and echo it).
    detected_source = source if source != "auto" else _quick_detect(text)

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

    # Hungarian — strongest signals first
    if any(c in t for c in "őű"):
        return "hu"
    # Common Hungarian words (covers lots of conference chatter)
    if re.search(r"\b(hogy|nem|van|egy|ami|és|vagy|csak|köszönöm|szépen|igen|jó|kérem)\b", t):
        return "hu"
    # Hungarian chars (ö, ü, á, é) without Czech/Slovak/Polish signals
    if (chars & _HU_CHARS) and not any(c in t for c in "čďěňřšťůž"):
        # Check if Polish chars present (they take precedence)
        if not (chars & _PL_CHARS):
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
    """Translate via Gemini 2.0 Flash REST API. Returns (text, provider) or (None, None).

    We call the REST endpoint directly (no google-generativeai SDK on Heroku)
    — same pattern used elsewhere in this codebase.
    """
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
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 2048,
                    "topP": 0.9,
                },
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Gemini translate HTTP {resp.status_code}: {resp.text[:200]}")
            return None, None
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None, None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts:
            return None, None
        out = (parts[0].get("text") or "").strip()
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


# ═══════════════════════════════════════════════════════════════════
# BATCH — translate many short strings in one Gemini call.
# Used by the runtime UI-translator (DOM walker) so switching language
# is one round-trip, not N.
# ═══════════════════════════════════════════════════════════════════

BATCH_MAX_ITEMS = 200
BATCH_MAX_TOTAL_CHARS = 25000


@translator_bp.route("/api/translate/batch", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="ip")
def translate_batch():
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    data = request.get_json(silent=True) or {}
    texts = data.get("texts") or []
    source = (data.get("source") or "cs").strip().lower()
    target = (data.get("target") or "").strip().lower()

    if not isinstance(texts, list) or not texts:
        return jsonify({"success": False, "error": 'Parametr "texts" je prázdný.'}), 400
    if len(texts) > BATCH_MAX_ITEMS:
        return jsonify({
            "success": False,
            "error": f"Příliš mnoho textů (max {BATCH_MAX_ITEMS}).",
        }), 400
    total = sum(len(t or "") for t in texts)
    if total > BATCH_MAX_TOTAL_CHARS:
        return jsonify({
            "success": False,
            "error": f"Celková délka textů překročila limit ({BATCH_MAX_TOTAL_CHARS} znaků).",
        }), 400
    if target not in LANG_CODES:
        return jsonify({"success": False, "error": f'Jazyk "{target}" není podporovaný.'}), 400
    if source not in LANG_CODES and source != "auto":
        return jsonify({"success": False, "error": f'Zdrojový jazyk "{source}" není podporovaný.'}), 400

    # Short-circuit if source == target
    if source == target:
        return jsonify({
            "success": True,
            "translations": list(texts),
            "target": target,
            "provider": "noop",
        }), 200

    # Filter empty / whitespace-only so Gemini doesn't translate nothing
    indexed = [(i, (t or "")) for i, t in enumerate(texts)]
    work = [(i, t.strip()) for i, t in indexed if t and t.strip()]
    translations = list(texts)  # start with originals (blanks stay blank)

    if not work:
        return jsonify({
            "success": True,
            "translations": translations,
            "target": target,
            "provider": "noop",
        }), 200

    out, provider = _translate_gemini_batch([t for _, t in work], source, target)
    if out is None or len(out) != len(work):
        # Gemini failed → fall back to per-item MyMemory (best-effort)
        for idx, (orig_i, src_text) in enumerate(work):
            single, _ = _translate_mymemory(src_text, source if source != "auto" else "cs", target)
            if single:
                translations[orig_i] = single
        return jsonify({
            "success": True,
            "translations": translations,
            "target": target,
            "provider": "mymemory-fallback",
        }), 200

    for (orig_i, _), translated in zip(work, out):
        translations[orig_i] = translated

    return jsonify({
        "success": True,
        "translations": translations,
        "target": target,
        "provider": provider,
    }), 200


def _translate_gemini_batch(texts: list, source: str, target: str):
    """Translate many short strings in one Gemini call.

    Uses a numbered format so Gemini returns a stable list order.
    Returns (list[str], provider) or (None, None) on failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, None

    src_name = LANG_NAME.get(source, source) if source != "auto" else "the source language"
    tgt_name = LANG_NAME.get(target, target)

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"Translate each numbered line from {src_name} to {tgt_name}. "
        "Return ONLY the translations in the same order, same numbering, "
        "one per line. Preserve numbering exactly. Do not skip items. "
        "Do not add commentary. If a line is a proper noun, a brand, or "
        "cannot be translated meaningfully, keep it unchanged.\n\n"
        f"{numbered}"
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 4096,
                    "topP": 0.9,
                },
            },
            timeout=25,
        )
        if resp.status_code != 200:
            logger.warning(f"Gemini batch HTTP {resp.status_code}: {resp.text[:200]}")
            return None, None
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None, None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        raw = (parts[0].get("text") or "").strip() if parts else ""
        if not raw:
            return None, None
        # Parse back numbered lines → list
        result = _parse_numbered_list(raw, expected_count=len(texts))
        if not result:
            return None, None
        return result, "gemini-2.0-flash-batch"
    except Exception as e:
        logger.warning(f"Gemini batch failed: {e}")
        return None, None


def _parse_numbered_list(raw: str, expected_count: int):
    """Parse '1. text\n2. text\n3. text' into list preserving order.

    Gemini sometimes omits the number on continuation lines of a multi-line
    translation — we treat unnumbered lines as part of the previous item.
    """
    items = {}
    current_idx = None
    current_buf = []
    pat = re.compile(r'^\s*(\d+)[\.\)]\s*(.*)$')
    for line in raw.split("\n"):
        m = pat.match(line)
        if m:
            if current_idx is not None:
                items[current_idx] = "\n".join(current_buf).strip()
            current_idx = int(m.group(1)) - 1
            current_buf = [m.group(2).strip()]
        else:
            if current_idx is not None:
                current_buf.append(line.rstrip())
    if current_idx is not None:
        items[current_idx] = "\n".join(current_buf).strip()

    out = []
    for i in range(expected_count):
        out.append(items.get(i, ""))
    # Sanity: at least half should be non-empty, else parsing failed
    non_empty = sum(1 for x in out if x)
    if non_empty < max(1, expected_count // 2):
        return None
    return out


# ═══════════════════════════════════════════════════════════════════
# OCR — extract text from image + translate (Gemini vision)
# ═══════════════════════════════════════════════════════════════════

MAX_IMAGE_BYTES = 6 * 1024 * 1024   # 6 MB
ALLOWED_MIME = frozenset([
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif",
])


@translator_bp.route("/api/translate/ocr", methods=["POST", "OPTIONS"])
@rate_limit(max_requests=20, window_seconds=60, key_func="ip")
def translate_ocr():
    """Extract text from an image and translate it.

    Accepts either:
      - multipart/form-data with `image` file field + `target` form field
      - application/json with {image_base64, mime_type, target}

    Returns: {success, extracted, translated, target, source_detected, provider}.
    """
    if request.method == "OPTIONS":
        return jsonify({"ok": True}), 200

    target = ""
    image_b64 = None
    mime = "image/jpeg"

    # 1. Multipart first (camera uploads naturally use this).
    if request.files.get("image"):
        f = request.files["image"]
        mime = (f.mimetype or "image/jpeg").lower()
        raw = f.read()
        if len(raw) > MAX_IMAGE_BYTES:
            return jsonify({
                "success": False,
                "error": f"Obrázek je příliš velký (max {MAX_IMAGE_BYTES // (1024*1024)} MB).",
            }), 400
        import base64 as _b64
        image_b64 = _b64.b64encode(raw).decode("ascii")
        target = (request.form.get("target") or "").strip().lower()
    else:
        data = request.get_json(silent=True) or {}
        image_b64 = (data.get("image_base64") or "").strip()
        if image_b64.startswith("data:"):
            # strip data URL prefix
            try:
                mime = image_b64.split(";", 1)[0][5:] or mime
                image_b64 = image_b64.split(",", 1)[1]
            except Exception:
                pass
        else:
            mime = (data.get("mime_type") or mime).lower()
        target = (data.get("target") or "").strip().lower()

    if not image_b64:
        return jsonify({"success": False, "error": 'Chybí obrázek ("image" nebo "image_base64").'}), 400
    if mime not in ALLOWED_MIME:
        return jsonify({
            "success": False,
            "error": f"Nepodporovaný typ obrázku: {mime}. Použijte JPEG/PNG/WebP/HEIC.",
        }), 400
    if target not in LANG_CODES:
        return jsonify({
            "success": False,
            "error": f'Cílový jazyk "{target}" není podporovaný.',
        }), 400

    extracted, translated, detected, provider = _gemini_ocr_and_translate(
        image_b64, mime, target,
    )
    if extracted is None:
        return jsonify({
            "success": False,
            "error": "Nepodařilo se přečíst obrázek. Zkuste ostřejší foto.",
        }), 502

    return jsonify({
        "success": True,
        "extracted": extracted,
        "translated": translated,
        "target": target,
        "source_detected": detected,
        "provider": provider,
    }), 200


def _gemini_ocr_and_translate(image_b64: str, mime: str, target: str):
    """One Gemini call that both extracts text and translates.

    Returns (extracted, translated, detected_source, provider) or
    (None, None, None, None) on failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, None, None, None

    tgt_name = LANG_NAME.get(target, target)

    prompt = (
        "You are a visual translator. Read ALL visible text in the image "
        "(signs, menus, documents, screens, labels). Return output in exactly "
        "this format, no extra commentary:\n\n"
        "LANG: <ISO 639-1 code of the detected source language>\n"
        "ORIGINAL:\n<all extracted text, preserving line breaks>\n\n"
        f"TRANSLATED ({tgt_name}):\n<full translation into {tgt_name}>\n\n"
        "If the image contains no readable text, output exactly:\n"
        "LANG: --\nORIGINAL:\n(žádný text)\n\nTRANSLATED:\n(žádný text)"
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={api_key}",
            json={
                "contents": [{
                    "parts": [
                        {"inline_data": {"mime_type": mime, "data": image_b64}},
                        {"text": prompt},
                    ],
                }],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 2048,
                    "topP": 0.9,
                },
            },
            timeout=25,
        )
        if resp.status_code != 200:
            logger.warning(f"Gemini OCR HTTP {resp.status_code}: {resp.text[:200]}")
            return None, None, None, None
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None, None, None, None
        parts = (candidates[0].get("content") or {}).get("parts") or []
        if not parts:
            return None, None, None, None
        raw = (parts[0].get("text") or "").strip()
        return _parse_ocr_response(raw) + ("gemini-2.0-flash-vision",)
    except Exception as e:
        logger.warning(f"Gemini OCR failed: {e}")
        return None, None, None, None


def _parse_ocr_response(raw: str):
    """Split Gemini's formatted output into (extracted, translated, detected)."""
    extracted, translated, detected = "", "", None
    # Tolerate both '\n\n' and '\n' separators; match on labels case-insensitively.
    lang_m = re.search(r'^LANG\s*:\s*([a-z-]{2,5}|--)\s*$', raw, re.IGNORECASE | re.MULTILINE)
    if lang_m:
        code = lang_m.group(1).lower()
        detected = None if code == "--" else code.split("-")[0]

    orig_m = re.search(
        r'ORIGINAL\s*:\s*\n(.*?)(?:\n\s*\n\s*TRANSLATED|$)',
        raw, re.IGNORECASE | re.DOTALL,
    )
    if orig_m:
        extracted = orig_m.group(1).strip()

    tr_m = re.search(
        r'TRANSLATED[^:]*:\s*\n(.*?)\s*$',
        raw, re.IGNORECASE | re.DOTALL,
    )
    if tr_m:
        translated = tr_m.group(1).strip()

    # Fallback: if parsing fails, return the whole raw as both original & translated.
    if not extracted and not translated:
        extracted = raw
        translated = raw

    return extracted, translated, detected


logger.info("🌐 Translator routes loaded: /api/translate + /api/translate/ocr")
