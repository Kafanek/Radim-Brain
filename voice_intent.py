# -*- coding: utf-8 -*-
"""
🎙 VOICE INTENT — Sprint AU
Detekce hlasových záměrů ve volném textu seniora.

Místo aby senior musel listovat sekcemi a klikat ▶ Aktivovat,
řekne jen *„Radim, je mi smutno"* nebo *„cítím se silnější"* — a Radim
v dalším chatu navrhne odpovídající životní balík. Senior potvrdí slovem.

Princip:
  - NEINJEKTUJE změnu automaticky
  - Naví ̂ rh = bus emit topic=preset_suggestion → orchestrator
    při příští odpovědi vetká nabídku do textu
  - Senior potvrzuje slovem („ano, prosím" / „ne, díky")
  - Confirmation se detekuje v dalším chatu a teprve TEHDY se preset aplikuje

Etika:
  Žádný preset se nezapíná bez explicitního „ano". Senior vždy ve
  smyčce.
"""

import logging
import re

logger = logging.getLogger(__name__)


# ============================================================================
# INTENT PATTERNS — co spouští návrh kterého balíku
# ============================================================================
# Patterns are matched as substrings on lowercased message.
# Multi-word patterns must hit verbatim (žádný re.search).

PRESET_TRIGGERS = {
    'grief': {
        'patterns': [
            'je mi smutno', 'je mi tezko', 'je mi těžko',
            'truchlim', 'truchlím', 'truchlit',
            'manzel mi zemrel', 'manžel mi zemřel', 'zena mi zemrela', 'žena mi zemřela',
            'chybi mi', 'chybí mi',
            'cítím se prázdně', 'citim se prazdne',
            'jsem opuštěná', 'jsem opustena', 'jsem opuštěný', 'jsem opusteny',
            'nedokáži to', 'nedokazi to', 'nemůžu se přes to přenést',
        ],
        'min_intensity': 1,  # need at least 1 hit
    },
    'recovery': {
        'patterns': [
            'vratil jsem se z nemocnice', 'vrátil jsem se z nemocnice',
            'vratila jsem se z nemocnice', 'vrátila jsem se z nemocnice',
            'po operaci', 'po zakroku', 'po zákroku',
            'jsem v rekonvalescenci', 'rekonvalescence',
            'po chripce', 'po chřipce', 'po nemoci',
            'lekar mi řekl', 'lékař mi řekl',
            'cítím se slabší', 'citim se slabsi',
            'beru nove leky', 'beru nové léky',
        ],
        'min_intensity': 1,
    },
    'strong': {
        'patterns': [
            'cítím se silně', 'citim se silne', 'cítím se silnější',
            'mám energii', 'mam energii',
            'je mi dobře', 'je mi dobre',
            'je mi prima', 'je mi fajn',
            'cítím se výborně', 'citim se vyborne',
            'mám se skvěle', 'mam se skvele',
            'jsem v pohodě', 'jsem v pohode',
        ],
        'min_intensity': 1,
    },
    'rough_days': {
        'patterns': [
            'mám horší dny', 'mam horsi dny',
            'mám horší den', 'mam horsi den',
            'je to teď těžké', 'je to ted tezke',
            'cítím se hůř', 'citim se hur',
            'nemám náladu', 'nemam naladu',
            'jsem unavená', 'jsem unaveny', 'jsem unavený',
            'dnes je to slabší', 'dnes je to slabsi',
        ],
        'min_intensity': 1,
    },
}


# ============================================================================
# CONFIRMATION DETECTION
# ============================================================================

CONFIRM_AFFIRMATIVE = {
    'ano', 'jo', 'jasně', 'jasne', 'samozrejme', 'samozřejmě',
    'aktivuj', 'aktivovat', 'spusť', 'spust',
    'ano prosím', 'ano prosim',
    'budu rád', 'budu rad', 'budu ráda', 'budu rada',
    'pojďme', 'pojdme',
    'platí', 'plati',
    'dobře', 'dobre', 'zapni',
}

CONFIRM_NEGATIVE = {
    'ne', 'nech to', 'nechci', 'nedělej', 'nedelej',
    'ne dik', 'ne díky', 'ne diky',
    'ne prosím', 'ne prosim',
    'pak možná', 'pak mozna', 'pak možná', 'pozdeji', 'později',
    'nevadi', 'nevadí',
    'nepotřebuju', 'nepotrebuju',
    'jen ne teď', 'jen ne ted',
}


# ============================================================================
# DETECTORS
# ============================================================================

def detect_preset_intent(message: str) -> dict | None:
    """Find which preset (if any) this message hints at.

    Returns:
        {
            'preset_id': 'grief' | 'recovery' | 'strong' | 'rough_days',
            'matched': ['je mi smutno', ...],  # patterns that hit
            'confidence': 'high' | 'medium' | 'low',
        }
        or None if no clear hint.
    """
    if not message or not isinstance(message, str):
        return None
    text = message.lower().strip()
    if len(text) < 5:
        return None

    best = None
    best_count = 0

    for preset_id, conf in PRESET_TRIGGERS.items():
        hits = [p for p in conf['patterns'] if p in text]
        if not hits or len(hits) < conf['min_intensity']:
            continue
        if len(hits) > best_count:
            best_count = len(hits)
            best = {
                'preset_id': preset_id,
                'matched': hits,
                'confidence': 'high' if len(hits) >= 2 else (
                    'medium' if len(hits) == 1 and len(hits[0]) > 12 else 'low'
                ),
            }

    return best


def detect_confirmation(message: str) -> str | None:
    """Detect if message is a yes/no to a previously offered preset.

    Returns:
        'yes' | 'no' | None
    """
    if not message:
        return None
    text = message.lower().strip()

    # Strict word-boundary check for short answers
    words = re.findall(r"[\w']+", text)

    for w in words[:5]:  # only look at first few tokens
        if w in CONFIRM_AFFIRMATIVE:
            return 'yes'
        if w in CONFIRM_NEGATIVE:
            return 'no'

    # Multi-word phrase fallback
    for phrase in CONFIRM_AFFIRMATIVE:
        if ' ' in phrase and phrase in text:
            return 'yes'
    for phrase in CONFIRM_NEGATIVE:
        if ' ' in phrase and phrase in text:
            return 'no'

    return None


# ============================================================================
# PRESET SUGGESTION INJECTION (for system prompt)
# ============================================================================

def build_suggestion_text(preset_id: str) -> str:
    """Compose a natural offer text Radim can append to his next reply.

    Soft-spoken so senior doesn't feel pushed.
    """
    OFFERS = {
        'grief': (
            'Slyšel jsem, že vám teď není dobře. Pokud chcete, '
            'mohu zapnout tichý režim — méně oznámení, klidnější tón. '
            'Stačí říct „ano".'
        ),
        'recovery': (
            'Pokud se zotavujete, mohu vám trochu více připomínat léky '
            'a hlídat doktora. Větší písmo, jednodušší rozhraní. '
            'Mám to zapnout? Stačí říct „ano".'
        ),
        'strong': (
            'Rád slyším, že vám je dobře. Pokud chcete, mohu vám teď '
            'dát víc prostoru — méně otázek, svižnější tón. '
            'Řekněte „ano" a zapnu to.'
        ),
        'rough_days': (
            'Vidím, že je to teď trochu těžší. Mohu vám pomoct — '
            'mluvit pomaleji, méně rušit, být víc empatický. '
            'Řekněte „ano" a uděláme to spolu.'
        ),
    }
    return OFFERS.get(preset_id, '')
