"""
🧠 RADIM CONTEXT BUILDER v1.0
================================
Centrální modul který propojuje VŠECHNY vrstvy systému
do jednoho kontextového objektu pro LLM.

Flow:
  Input → Short Memory → Long Memory → Rhythm → Coherence
  → Relationship → Acceptance → Meta Observer → Context

Výstup: RadimContext — vše co LLM potřebuje k odpovědi.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# φ, ρ, δ constants
PHI = 1.618034
RHO = 2.016124
DELTA = 2.414214


# ============================================================================
# COHERENCE STATE CLASSIFIER
# ============================================================================

def classify_coherence(phi_index, rho_stability):
    """
    Classify user state from brain engine φ and ρ values.

    φ_index (0-1): How close to golden ratio harmony
    ρ_stability (0-1): How stable the system is

    Returns: 'phi' (calm), 'rho' (flow), 'delta' (stress)
    """
    if phi_index >= 0.7 and rho_stability >= 0.5:
        return 'phi'   # Calm, harmonious
    elif phi_index >= 0.4 or rho_stability >= 0.3:
        return 'rho'   # Flowing, active, normal
    else:
        return 'delta'  # Stressed, dissonant


def coherence_to_voice(state):
    """Map coherence state to voice parameters."""
    profiles = {
        'phi':   {'rate': '-5%',  'pause_ms': 618,  'pitch': '-2%', 'style': 'friendly',  'styledegree': '1.3'},
        'rho':   {'rate': '0%',   'pause_ms': 400,  'pitch': '0%',  'style': 'friendly',  'styledegree': '1.0'},
        'delta': {'rate': '-15%', 'pause_ms': 1000, 'pitch': '-5%', 'style': 'empathetic', 'styledegree': '1.5'},
    }
    return profiles.get(state, profiles['rho'])


def coherence_to_chat(state):
    """Map coherence state to chat response style."""
    styles = {
        'phi':   {'tone': 'calm', 'max_sentences': 4, 'use_emoji': True, 'ask_questions': True},
        'rho':   {'tone': 'natural', 'max_sentences': 6, 'use_emoji': True, 'ask_questions': True},
        'delta': {'tone': 'grounding', 'max_sentences': 3, 'use_emoji': False, 'ask_questions': False},
    }
    return styles.get(state, styles['rho'])


# ============================================================================
# ACCEPTANCE LAYER — how to say "no" respectfully
# ============================================================================

ACCEPTANCE_PATTERNS = {
    'refuse_action': 'Rozumím vašemu přání. Bohužel toto nemohu udělat, ale můžeme zkusit jinou cestu.',
    'refuse_unsafe': 'Chci vám pomoct, ale pro vaši bezpečnost toto raději neuděláme. Co říkáte na alternativu?',
    'user_said_no': 'V pořádku, respektuji vaše rozhodnutí.',
    'user_confused': 'Promiňte, zkusím to říct jednodušeji.',
    'user_angry': 'Rozumím, že to může být frustrující. Jsem tu, kdykoliv budete chtít.',
    'user_wants_stop': 'Dobře, přestávám. Jsem tu, kdykoliv mě budete potřebovat.',
}


def acceptance_response(situation, user_name=None):
    """Get acceptance-based response for difficult situations."""
    base = ACCEPTANCE_PATTERNS.get(situation, ACCEPTANCE_PATTERNS['user_said_no'])
    if user_name:
        base = base.replace('Rozumím', f'{user_name}, rozumím')
    return base


def detect_refusal(message):
    """Detect if user is refusing, stopping, or expressing displeasure."""
    if not message:
        return None
    msg = message.lower().strip()

    if any(w in msg for w in ['přestaň', 'stop', 'dost', 'nechci', 'skonči', 'ticho', 'mlč']):
        return 'user_wants_stop'
    if any(w in msg for w in ['ne ', 'ne,', 'ne.', 'nechci', 'odmítám', 'nebudu']):
        return 'user_said_no'
    if any(w in msg for w in ['nerozumím', 'nechápu', 'co tím', 'jak to']):
        return 'user_confused'
    if any(w in msg for w in ['naštvaný', 'nasraný', 'otravuješ', 'nech mě', 'jdi pryč']):
        return 'user_angry'
    return None


# ============================================================================
# META OBSERVER — watches the entire pipeline
# ============================================================================

_meta_state = {
    'consecutive_errors': 0,
    'last_error_time': None,
    'user_satisfaction': 'unknown',  # positive / neutral / negative
    'response_quality': 'ok',  # ok / degraded / failed
    'healing_active': False,
}


def meta_observe(user_message, response, brain_state=None, healing_events=None):
    """
    Observe the entire interaction and flag issues.

    Returns:
        dict: {quality, warnings, adjustments}
    """
    warnings = []
    adjustments = []

    # Response quality
    if not response or len(response) < 5:
        _meta_state['consecutive_errors'] += 1
        _meta_state['response_quality'] = 'failed'
        warnings.append('empty_response')
    elif response.startswith('Promiňte'):
        _meta_state['response_quality'] = 'degraded'
        warnings.append('fallback_response')
    else:
        _meta_state['consecutive_errors'] = 0
        _meta_state['response_quality'] = 'ok'

    # Detect user dissatisfaction
    refusal = detect_refusal(user_message)
    if refusal:
        _meta_state['user_satisfaction'] = 'negative'
        adjustments.append(f'acceptance:{refusal}')

    # Too many errors → suggest system restart
    if _meta_state['consecutive_errors'] >= 3:
        warnings.append('system_degraded')
        adjustments.append('simplify_all_responses')

    # Brain state anomaly
    if brain_state:
        c = brain_state.get('C', 0)
        if c > 27:
            warnings.append('high_consciousness_load')
            adjustments.append('reduce_complexity')

    return {
        'quality': _meta_state['response_quality'],
        'satisfaction': _meta_state['user_satisfaction'],
        'warnings': warnings,
        'adjustments': adjustments,
        'consecutive_errors': _meta_state['consecutive_errors']
    }


# ============================================================================
# MEMORY COMPRESSION — condense old memories
# ============================================================================

def compress_memory(learning_data):
    """
    Compress old memory entries to save space and improve relevance.

    - C_history: keep last 20, compute running average
    - health_topics: keep only topics mentioned 2+ times or in last 7 days
    - topics: keep top 10 by count
    - agent_observations: keep last 5

    Returns: compressed learning_data dict
    """
    if not learning_data:
        return learning_data

    data = dict(learning_data)

    # C_history: cap at 20
    c_hist = data.get('C_history', [])
    if len(c_hist) > 20:
        data['C_history'] = c_hist[-20:]
        if c_hist:
            data['avg_C'] = round(sum(data['C_history']) / len(data['C_history']), 2)

    # Topics: keep top 10
    topics = data.get('topics', {})
    if len(topics) > 10:
        sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:10]
        data['topics'] = dict(sorted_topics)

    # Health topics: prune old with count=1
    health = data.get('health_topics', {})
    if health:
        today = datetime.utcnow().strftime('%Y-%m-%d')
        pruned = {}
        for name, info in health.items():
            if info.get('count', 0) >= 2 or info.get('last') == today:
                pruned[name] = info
        data['health_topics'] = pruned

    # Agent observations: keep last 5
    obs = data.get('agent_observations', [])
    if len(obs) > 5:
        data['agent_observations'] = obs[-5:]

    return data


def should_forget(key, value, days_since_last=None):
    """
    GDPR + natural forgetting: should this memory be forgotten?

    Forget:
    - Topics not mentioned in 90 days
    - Health topics resolved (not mentioned in 30 days + count < 3)
    - Observations older than 30 days
    """
    if days_since_last is None:
        return False

    if key == 'topic' and days_since_last > 90:
        return True
    if key == 'health_topic' and days_since_last > 30 and (value or {}).get('count', 0) < 3:
        return True
    if key == 'observation' and days_since_last > 30:
        return True

    return False


# ============================================================================
# UNIFIED CONTEXT BUILDER
# ============================================================================

def build_radim_context(user_id, message, brain_state=None, relationship=None,
                         emotional_state=None, learning_data=None):
    """
    Build the COMPLETE context object for LLM.

    This is the SINGLE SOURCE OF TRUTH for everything Radim needs
    to generate a response.

    Returns:
        dict: RadimContext
    """
    # Coherence state from brain
    phi_index = 0.5
    rho_stability = 0.5
    mode = 'HARMONY'
    if brain_state:
        phi_index = brain_state.get('phi_index', 0.5)
        rho_stability = brain_state.get('rho_stability', 0.5)
        mode = brain_state.get('mode', 'HARMONY')

    coherence_state = classify_coherence(phi_index, rho_stability)

    # Acceptance check
    refusal = detect_refusal(message)

    # Time context
    now = datetime.now()
    hour = now.hour
    if hour < 6:
        time_context = 'night'
    elif hour < 12:
        time_context = 'morning'
    elif hour < 18:
        time_context = 'afternoon'
    else:
        time_context = 'evening'

    # Pattern detection from learning
    patterns = []
    if learning_data:
        if learning_data.get('health_topics'):
            active_health = [k for k, v in learning_data['health_topics'].items() if v.get('count', 0) >= 2]
            if active_health:
                patterns.append(f"health:{','.join(active_health[:3])}")
        if learning_data.get('last_mood'):
            patterns.append(f"mood:{learning_data['last_mood']}")

    context = {
        # Identity
        'user_id': user_id,
        'timestamp': now.isoformat(),
        'time_context': time_context,

        # Coherence state (φ–ρ–δ)
        'coherence': {
            'state': coherence_state,
            'phi_index': phi_index,
            'rho_stability': rho_stability,
            'mode': mode,
        },

        # Voice adaptation
        'voice': coherence_to_voice(coherence_state),

        # Chat style
        'chat_style': coherence_to_chat(coherence_state),

        # Relationship
        'relationship': relationship or {'type': 'subscriber', 'trust': 0.0, 'permission_level': 'SUGGEST'},

        # Emotional state
        'emotional': emotional_state or {'confused': False, 'stressed': False},

        # Acceptance
        'acceptance': {
            'refusal_detected': refusal,
            'response': acceptance_response(refusal) if refusal else None,
        },

        # Patterns (from long memory)
        'patterns': patterns,

        # Priorities
        'priorities': _compute_priorities(coherence_state, refusal, emotional_state),
    }

    return context


def _compute_priorities(coherence_state, refusal, emotional_state):
    """Compute response priorities based on all signals."""
    priorities = []

    # Always first: acceptance if user refuses
    if refusal:
        priorities.append('respect_choice')

    # Emotional needs
    if emotional_state and emotional_state.get('stressed'):
        priorities.append('calm_first')
        priorities.append('no_questions')
    elif emotional_state and emotional_state.get('confused'):
        priorities.append('simplify')
        priorities.append('repeat_key')

    # Coherence-driven
    if coherence_state == 'delta':
        priorities.append('grounding')
        priorities.append('short_response')
    elif coherence_state == 'phi':
        priorities.append('natural_flow')

    # Default
    if not priorities:
        priorities.append('helpful')
        priorities.append('warm')

    return priorities


def context_to_prompt_section(context):
    """Convert RadimContext to prompt text section for LLM injection."""
    lines = ["═══ RADIM KONTEXT ═══"]

    c = context.get('coherence', {})
    lines.append(f"Stav: {c.get('state', '?')} (φ={c.get('phi_index', 0):.2f}, ρ={c.get('rho_stability', 0):.2f})")
    lines.append(f"Čas: {context.get('time_context', '?')}")

    cs = context.get('chat_style', {})
    lines.append(f"Styl: {cs.get('tone', '?')}, max {cs.get('max_sentences', 6)} vět")

    rel = context.get('relationship', {})
    lines.append(f"Vztah: {rel.get('type', '?')}, trust={rel.get('trust', 0):.1f}, perm={rel.get('permission_level', '?')}")

    acc = context.get('acceptance', {})
    if acc.get('refusal_detected'):
        lines.append(f"⚠️ Uživatel odmítá: {acc['refusal_detected']}")
        lines.append(f"→ {acc.get('response', '')}")

    prio = context.get('priorities', [])
    if prio:
        lines.append(f"Priority: {', '.join(prio)}")

    patterns = context.get('patterns', [])
    if patterns:
        lines.append(f"Vzory: {', '.join(patterns)}")

    return "\n".join(lines)


logger.info("🧠 Context Builder v1.0 loaded — coherence, acceptance, meta observer, memory compression")
