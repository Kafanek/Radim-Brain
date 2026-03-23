"""
🤝 RELATIONSHIP ENGINE v1.0
============================
Srdce Radim Agent — identifikuje KDO je uživatel, jaký je VZTAH,
kolik DŮVĚRY si Radim zasloužil, a jak se má chovat.

Inspirace: Konfuciánský framework
- ren (仁) péče — závisí na vulnerability
- yi (義) správnost — závisí na brain mode
- li (禮) respekt — vždy vysoký
- zhi (智) moudrost — roste s interakcemi
- xin (信) důvěra — earned over time

Permission levels:
- SUGGEST: "Chcete zavolat dceru?" (trust < 0.3)
- ASSIST:  "Vytáčím dceru..." + confirm (trust 0.3-0.7)
- EXECUTE: auto action + notify (trust > 0.7 OR crisis)
"""

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# RELATIONSHIP TYPES — base profiles
# ============================================================================

RELATIONSHIP_PROFILES = {
    'senior': {
        'care': 0.9, 'patience': 0.9, 'formality': 0.7,
        'vulnerability': 0.8, 'response_speed': 'slow',
        'description': 'Zranitelný uživatel — maximální péče a trpělivost'
    },
    'caregiver': {
        'care': 0.5, 'patience': 0.5, 'formality': 0.4,
        'vulnerability': 0.1, 'response_speed': 'normal',
        'description': 'Profesionál — věcný, efektivní, podporující'
    },
    'family': {
        'care': 0.7, 'patience': 0.6, 'formality': 0.3,
        'vulnerability': 0.3, 'response_speed': 'normal',
        'description': 'Rodina — vřelý, přátelský, sdílný'
    },
    'customer': {
        'care': 0.5, 'patience': 0.5, 'formality': 0.6,
        'vulnerability': 0.1, 'response_speed': 'fast',
        'description': 'Zákazník — efektivní, zdvořilý, goal-oriented'
    },
    'admin': {
        'care': 0.3, 'patience': 0.3, 'formality': 0.2,
        'vulnerability': 0.0, 'response_speed': 'fast',
        'description': 'Administrátor — technický, stručný'
    },
    'subscriber': {
        'care': 0.6, 'patience': 0.6, 'formality': 0.5,
        'vulnerability': 0.3, 'response_speed': 'normal',
        'description': 'Nový uživatel — přátelský, objevující'
    },
}

# Role mapping from auth_users.role → relationship type
ROLE_TO_TYPE = {
    'subscriber': 'subscriber',
    'senior': 'senior',
    'premium': 'senior',       # Premium users are typically seniors
    'teacher': 'caregiver',
    'admin': 'admin',
    'administrator': 'admin',
    'caregiver': 'caregiver',
    'family': 'family',
}


# ============================================================================
# CORE FUNCTIONS
# ============================================================================

def identify_relationship(user_id, auth_role=None, learning_data=None, profile_data=None):
    """
    Identify relationship type, trust level, and behavioral parameters.

    Args:
        user_id: str
        auth_role: str from auth_users.role (optional, fetched if None)
        learning_data: dict from memory_learning.data (optional)
        profile_data: dict from memory_profiles.data (optional)

    Returns:
        dict with: type, trust, vulnerability, familiarity, permission_level,
                   confucian, response_style, description
    """
    # Determine base type from role
    role = auth_role or 'subscriber'
    rel_type = ROLE_TO_TYPE.get(role, 'subscriber')
    profile = RELATIONSHIP_PROFILES.get(rel_type, RELATIONSHIP_PROFILES['subscriber'])

    # Compute trust
    trust = compute_trust(learning_data or {})

    # Compute familiarity
    interactions = (learning_data or {}).get('interaction_count', 0)
    familiarity = min(1.0, interactions / 30)  # Familiar after ~30 interactions

    # Vulnerability — higher for seniors, elderly
    age_group = (profile_data or {}).get('age_group', '')
    vulnerability = profile['vulnerability']
    if age_group in ('75+', '80+', '85+'):
        vulnerability = min(1.0, vulnerability + 0.2)
    if (profile_data or {}).get('memory_support'):
        vulnerability = min(1.0, vulnerability + 0.15)
    if (profile_data or {}).get('hearing') in ('impaired', 'severely_impaired'):
        vulnerability = min(1.0, vulnerability + 0.1)

    # Permission level
    permission = get_permission_level(trust, rel_type)

    # Confucian context
    confucian = compute_confucian(trust, vulnerability, familiarity, rel_type)

    # Response style adjustments
    style = {
        'care_level': profile['care'],
        'patience': profile['patience'],
        'formality': profile['formality'],
        'speed': profile['response_speed'],
        'repeat_key_info': vulnerability > 0.6,
        'use_simple_words': vulnerability > 0.5,
        'max_sentences': 6 if vulnerability > 0.5 else 10,
    }

    result = {
        'type': rel_type,
        'trust': round(trust, 2),
        'vulnerability': round(vulnerability, 2),
        'familiarity': round(familiarity, 2),
        'permission_level': permission,
        'confucian': confucian,
        'response_style': style,
        'description': profile['description'],
    }

    logger.debug(f"Relationship for {user_id}: type={rel_type}, trust={trust:.2f}, perm={permission}")
    return result


def compute_trust(learning_data):
    """
    Compute trust score (0.0 to 1.0) based on interaction history.

    Trust grows with:
    - Number of interactions (40% weight)
    - Time since first interaction (30% weight)
    - Positive feedback ratio (30% weight)

    Trust never exceeds 1.0.
    """
    interactions = learning_data.get('interaction_count', 0)
    successful = learning_data.get('successful_interactions', 0)
    first_interaction = learning_data.get('first_interaction')
    crisis_count = learning_data.get('crisis_count', 0)

    # Interaction factor (0-1): saturates at 50 interactions
    interaction_factor = min(1.0, interactions / 50)

    # Time factor (0-1): saturates at 30 days
    time_factor = 0.0
    if first_interaction:
        try:
            first = datetime.fromisoformat(str(first_interaction).replace('Z', '+00:00'))
            days = (datetime.now(first.tzinfo) - first).days if first.tzinfo else (datetime.now() - first).days
            time_factor = min(1.0, max(0, days) / 30)
        except Exception:
            pass

    # Feedback factor (0-1): ratio of successful interactions
    feedback_factor = 0.5  # Default neutral
    if interactions > 5:
        feedback_factor = min(1.0, successful / max(1, interactions))

    # Crisis penalty: each crisis reduces trust slightly
    crisis_penalty = min(0.3, crisis_count * 0.05)

    trust = (
        interaction_factor * 0.4 +
        time_factor * 0.3 +
        feedback_factor * 0.3
    ) - crisis_penalty

    return max(0.0, min(1.0, trust))


def compute_confucian(trust, vulnerability, familiarity, rel_type):
    """
    Compute Confucian virtue scores (ren, yi, li, zhi, xin).

    Each virtue adapts to the relationship context:
    - ren (care): higher for vulnerable users
    - yi (correctness): stable, slightly lower in crisis
    - li (respect): always high (≥0.8)
    - zhi (wisdom): grows with familiarity
    - xin (trust): directly from compute_trust()
    """
    return {
        'ren': round(min(1.0, 0.5 + vulnerability * 0.5), 2),   # Care
        'yi': round(0.8, 2),                                       # Correctness (stable)
        'li': round(max(0.8, 1.0 - vulnerability * 0.1), 2),      # Respect (always high)
        'zhi': round(min(1.0, 0.3 + familiarity * 0.7), 2),       # Wisdom (grows)
        'xin': round(trust, 2),                                     # Trust (earned)
    }


def get_permission_level(trust, rel_type='subscriber'):
    """
    Determine what Radim is allowed to do autonomously.

    SUGGEST: only recommend actions, user must confirm
    ASSIST:  show what's happening, user can cancel
    EXECUTE: auto-execute with notification

    Crisis situations always escalate to EXECUTE for safety.
    """
    if rel_type == 'admin':
        return 'EXECUTE'  # Admin always has full permissions

    if trust < 0.3:
        return 'SUGGEST'
    elif trust < 0.7:
        return 'ASSIST'
    else:
        return 'EXECUTE'


def build_relationship_prompt(relationship):
    """
    Build a prompt section describing the relationship context.
    Injected into the personalized system prompt.
    """
    if not relationship:
        return ""

    conf = relationship.get('confucian', {})
    style = relationship.get('response_style', {})

    lines = [
        "═══ VZTAHOVÝ KONTEXT ═══",
        f"Typ vztahu: {relationship['type']} — {relationship.get('description', '')}",
        f"Důvěra: {relationship['trust']:.1f}/1.0 (oprávnění: {relationship['permission_level']})",
        f"Zranitelnost: {relationship['vulnerability']:.1f}, Obeznámenost: {relationship['familiarity']:.1f}",
        f"Konfuciánské ctnosti: péče(ren)={conf.get('ren',0):.1f}, "
        f"respekt(li)={conf.get('li',0):.1f}, důvěra(xin)={conf.get('xin',0):.1f}",
    ]

    # Behavioral instructions
    if style.get('repeat_key_info'):
        lines.append("→ Opakuj klíčové informace (vysoká zranitelnost)")
    if style.get('use_simple_words'):
        lines.append("→ Používej jednoduchá slova a krátké věty")
    if relationship['permission_level'] == 'SUGGEST':
        lines.append("-> POUZE navrhuj akce, ptej se 'chcete, abych...?'")
    elif relationship['permission_level'] == 'ASSIST':
        lines.append("→ Ukazuj co děláš, dej možnost zrušit")

    return "\n".join(lines)


# ============================================================================
# PERSISTENCE — save/load relationship to memory_learning
# ============================================================================

def save_relationship(user_id, relationship):
    """Save relationship data to memory_learning JSONB."""
    try:
        from memory_helpers import db_load_learning, db_save_learning
        learning = db_load_learning(user_id)
        learning['relationship'] = {
            'type': relationship['type'],
            'trust_score': relationship['trust'],
            'vulnerability': relationship['vulnerability'],
            'familiarity': relationship['familiarity'],
            'permission_level': relationship['permission_level'],
            'confucian': relationship.get('confucian', {}),
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }
        db_save_learning(user_id, learning)
    except Exception as e:
        logger.debug(f"Save relationship error: {e}")


def load_relationship(user_id):
    """Load cached relationship from memory_learning."""
    try:
        from memory_helpers import db_load_learning
        learning = db_load_learning(user_id)
        return learning.get('relationship')
    except Exception:
        return None


logger.info("🤝 Relationship Engine v1.0 loaded — Confucian framework active")
