"""
🧒 RADIM VOICE LEARNING v1.0
==============================
Radim se učí jaký hlas funguje pro konkrétního seniora.
Jako dítě které se učí mateřštinu — napodobuje, zkoumá, zpřesňuje.

Sleduje reakce seniora na různé hlasové styly a adaptuje:
- Tempo (rate) — příliš rychlý? zpomalí. Přerušuje? zrychlí.
- Melodičnost (energy) — chválí melodii? přidá. Ignoruje? ubere.
- Pauzy (pause) — neodpovídá? delší. Přerušuje? kratší.
- Zpěv (singing_pref) — líbí se? zpívej častěji.

φ-učení: nový parametr = 61.8% starý + 38.2% nový (konzervativní)

@version 1.0.0
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PHI = 1.618033988749895
PHI_BLEND = 0.618  # 61.8% old + 38.2% new = slow, safe learning


# ============================================
# DEFAULT VOICE PREFERENCES
# ============================================

DEFAULT_PREFS = {
    'preferred_rate': -8,       # % (záporné = pomalejší)
    'preferred_energy': 0.5,    # 0-1 (melodičnost)
    'preferred_pause': 500,     # ms
    'response_to_melody': 0.5,  # 0-1 (pozitivní reakce na melodii)
    'response_to_singing': 0.5, # 0-1 (pozitivní reakce na zpěv)
    'interactions': 0,
    'positive_feedback': 0,
    'negative_feedback': 0,
    'barge_ins': 0,
    'no_responses': 0,
    'last_updated': None,
}


def get_voice_prefs(user_id):
    """Načte voice preferences pro uživatele z memory_learning.

    Returns: dict s voice preferences (DEFAULT_PREFS pokud neexistují)
    """
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(user_id) or {}
        prefs = learning.get('voice_preferences', {})
        # Merge with defaults (handles new fields)
        result = dict(DEFAULT_PREFS)
        result.update(prefs)
        return result
    except Exception as e:
        logger.debug(f"Voice prefs load: {e}")
        return dict(DEFAULT_PREFS)


def save_voice_prefs(user_id, prefs):
    """Uloží voice preferences do memory_learning."""
    try:
        from memory_helpers import db_load_learning, db_save_learning
        learning = db_load_learning(user_id) or {}
        prefs['last_updated'] = datetime.utcnow().isoformat()
        learning['voice_preferences'] = prefs
        db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f"Voice prefs save: {e}")


# ============================================
# LEARNING — zpracování feedbacku
# ============================================

def record_voice_feedback(user_id, event_type, voice_mode=None, details=None):
    """Zaznamenaj událost a adaptuj voice preferences.

    event_type:
        'response_fast'    — senior odpověděl do 5s (hlas byl srozumitelný)
        'response_slow'    — senior odpověděl po 10s+ (možná neslyšel/nerozuměl)
        'no_response'      — senior neodpověděl (15s+)
        'barge_in'         — senior přerušil TTS (příliš pomalé?)
        'positive'         — senior řekl "děkuju/hezké/krásné/super"
        'negative'         — senior řekl "co/nerozumím/znovu/pomaleji"
        'melody_positive'  — pozitivní reakce na melodický hlas
        'melody_negative'  — negativní reakce na melodii
        'singing_positive' — líbil se zpěv
        'singing_negative' — nelíbil se zpěv

    Returns: updated prefs dict
    """
    prefs = get_voice_prefs(user_id)
    prefs['interactions'] += 1

    if event_type == 'response_fast':
        # Hlas byl OK — mírně posilni aktuální nastavení
        pass

    elif event_type == 'response_slow':
        # Možná příliš rychlé nebo nesrozumitelné → zpomal, zvyš volume
        prefs['preferred_rate'] = _phi_blend(prefs['preferred_rate'], prefs['preferred_rate'] - 3)
        prefs['preferred_pause'] = _phi_blend(prefs['preferred_pause'], prefs['preferred_pause'] + 50)

    elif event_type == 'no_response':
        prefs['no_responses'] += 1
        # Výrazně zpomal a zvyš pause
        prefs['preferred_rate'] = _phi_blend(prefs['preferred_rate'], prefs['preferred_rate'] - 5)
        prefs['preferred_pause'] = _phi_blend(prefs['preferred_pause'], prefs['preferred_pause'] + 100)

    elif event_type == 'barge_in':
        prefs['barge_ins'] += 1
        # Senior přerušuje → mluv rychleji, kratší pauzy
        prefs['preferred_rate'] = _phi_blend(prefs['preferred_rate'], prefs['preferred_rate'] + 3)
        prefs['preferred_pause'] = _phi_blend(prefs['preferred_pause'], prefs['preferred_pause'] - 50)

    elif event_type == 'positive':
        prefs['positive_feedback'] += 1
        # Pozitivní → mírně zvyš melodičnost
        prefs['preferred_energy'] = _phi_blend(prefs['preferred_energy'], min(1.0, prefs['preferred_energy'] + 0.05))

    elif event_type == 'negative':
        prefs['negative_feedback'] += 1
        # Negativní → zpomal, sniž melodičnost
        prefs['preferred_rate'] = _phi_blend(prefs['preferred_rate'], prefs['preferred_rate'] - 2)
        prefs['preferred_energy'] = _phi_blend(prefs['preferred_energy'], max(0.1, prefs['preferred_energy'] - 0.05))

    elif event_type == 'melody_positive':
        prefs['response_to_melody'] = _phi_blend(prefs['response_to_melody'], min(1.0, prefs['response_to_melody'] + 0.1))

    elif event_type == 'melody_negative':
        prefs['response_to_melody'] = _phi_blend(prefs['response_to_melody'], max(0.0, prefs['response_to_melody'] - 0.1))

    elif event_type == 'singing_positive':
        prefs['response_to_singing'] = _phi_blend(prefs['response_to_singing'], min(1.0, prefs['response_to_singing'] + 0.1))

    elif event_type == 'singing_negative':
        prefs['response_to_singing'] = _phi_blend(prefs['response_to_singing'], max(0.0, prefs['response_to_singing'] - 0.1))

    # Clamp values
    prefs['preferred_rate'] = max(-30, min(0, prefs['preferred_rate']))
    prefs['preferred_pause'] = max(200, min(1500, prefs['preferred_pause']))
    prefs['preferred_energy'] = max(0.1, min(1.0, prefs['preferred_energy']))

    save_voice_prefs(user_id, prefs)

    if prefs['interactions'] % 20 == 0:
        logger.info(f"🧒 Voice learning [{user_id}]: rate={prefs['preferred_rate']}% "
                     f"energy={prefs['preferred_energy']:.2f} pause={prefs['preferred_pause']}ms "
                     f"(+{prefs['positive_feedback']}/-{prefs['negative_feedback']})")

    return prefs


def _phi_blend(old_val, new_val):
    """φ-vážený blend: 61.8% starý + 38.2% nový.

    Konzervativní učení — velká změna vyžaduje mnoho interakcí.
    """
    return old_val * PHI_BLEND + new_val * (1 - PHI_BLEND)


# ============================================
# APPLY — aplikuj preferences na voice profil
# ============================================

def apply_voice_learning(profile, user_id):
    """Aplikuje naučené voice preferences na voice profil.

    Modifikuje profile dict in-place:
    - rate: přizpůsobí tempu seniora
    - energy: přizpůsobí melodičnosti
    - pause_ms: přizpůsobí délce pauz

    Vyžaduje min. 10 interakcí (jinak vrátí profil beze změny).
    """
    prefs = get_voice_prefs(user_id)
    if prefs['interactions'] < 10:
        return profile  # Nedostatek dat

    # Rate override
    current_rate = int(profile.get('rate', '-8').replace('%', '').replace('+', ''))
    learned_rate = int(prefs['preferred_rate'])
    # Blend profile rate with learned rate
    blended_rate = int(current_rate * 0.5 + learned_rate * 0.5)
    profile['rate'] = f"{blended_rate}%"

    # Pause override
    current_pause = profile.get('pause_ms', 500)
    profile['pause_ms'] = int(current_pause * 0.5 + prefs['preferred_pause'] * 0.5)

    return profile


def should_use_melody(user_id):
    """Měl by Radim používat melodický hlas pro tohoto seniora?

    Returns: True pokud senior má rád melodii (response_to_melody > 0.5)
    """
    prefs = get_voice_prefs(user_id)
    if prefs['interactions'] < 10:
        return True  # Default: zkus melodii
    return prefs['response_to_melody'] > 0.5


def should_sing(user_id):
    """Měl by Radim zpívat pro tohoto seniora?

    Returns: True pokud senior má rád zpěv (response_to_singing > 0.5)
    """
    prefs = get_voice_prefs(user_id)
    if prefs['interactions'] < 10:
        return True  # Default: zkus zpěv
    return prefs['response_to_singing'] > 0.5


logger.info("🧒 Voice Learning v1.0 loaded — φ-blend adaptive per-user preferences")
