# -*- coding: utf-8 -*-
"""
🤖 AI MODEL CONFIG — central source of truth

Single env var GEMINI_MODEL controls which model all 29+ call sites use.
A/B testing models = one Heroku config:set, no code change, no redeploy.

Default: gemini-2.5-flash
  Reason: proven multilingual (better Czech), $0.30/$2.50 per 1M tokens,
  fits pilot budget at ~$19/month for 100 active users.

Upgrade candidates:
  gemini-3-flash       — +7% reasoning, +meaningful multilingual, ~$22/mo
  gemini-3.1-flash-lite — cheaper but quality regression for empathy
  gemini-3.1-pro       — flagship, ~4× more expensive (only for vision/long ctx)

Usage:
  from ai_config import GEMINI_MODEL, GEMINI_API_URL
  model = genai.GenerativeModel(GEMINI_MODEL)
  url = GEMINI_API_URL  # already includes the model
"""

import os
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Model selection — env var overrides default
# ============================================================================

DEFAULT_GEMINI_MODEL = 'gemini-2.5-flash'

GEMINI_MODEL = os.environ.get('GEMINI_MODEL', DEFAULT_GEMINI_MODEL).strip()

# Validate against known good list — typo in env var shouldn't silently break
KNOWN_GEMINI_MODELS = {
    # Legacy
    'gemini-1.5-flash', 'gemini-1.5-pro',
    'gemini-2.0-flash', 'gemini-2.0-flash-exp',
    # Current proven (April 2026)
    'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.5-pro',
    # Latest (April 2026)
    'gemini-3-flash', 'gemini-3-flash-preview',
    'gemini-3.1-flash-lite', 'gemini-3.1-pro',
}

if GEMINI_MODEL not in KNOWN_GEMINI_MODELS:
    logger.warning(
        f"⚠️ GEMINI_MODEL='{GEMINI_MODEL}' není v whitelistu. "
        f"Pokud je to nový model, přidej do KNOWN_GEMINI_MODELS. "
        f"Pokračuju s tímto názvem (Google API rozhodne)."
    )
else:
    logger.info(f"🤖 Using Gemini model: {GEMINI_MODEL}")


# ============================================================================
# REST API endpoint helpers — most call sites use raw HTTP
# ============================================================================

GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'


def gemini_url(api_key: str, action: str = 'generateContent') -> str:
    """Build Gemini REST API URL with current model + key.

    Args:
        api_key: GEMINI_API_KEY value
        action: 'generateContent' (default) or 'streamGenerateContent'

    Returns:
        Full URL ready for POST.
    """
    return f"{GEMINI_API_BASE}/{GEMINI_MODEL}:{action}?key={api_key}"


# Convenience constant for code that wants a one-liner
GEMINI_API_URL_TEMPLATE = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={{key}}"


# ============================================================================
# Model labels — for analytics and audit logs ("which model said what")
# ============================================================================

def model_label_for_audit() -> str:
    """Human-readable label that lands in audit_log.detail."""
    return GEMINI_MODEL


def model_family() -> str:
    """Coarse-grained tier for analytics: 'flash' | 'pro' | 'flash-lite'."""
    m = GEMINI_MODEL.lower()
    if 'flash-lite' in m: return 'flash-lite'
    if 'flash' in m:      return 'flash'
    if 'pro' in m:        return 'pro'
    return 'unknown'
