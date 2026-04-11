# ============================================
# 🎙️ RESPONSE COMPOSER — One Voice of Radim
# ============================================
# Takes agent decisions + rhythm state → unified response.
# Ensures Radim always sounds like ONE person, not a committee.
#
# Adapts: tone, length, speech rate, pauses, empathy level.
# Uses existing: voice_filter.py, text_rhythm.py, radim_system_prompt.py
# ============================================

import logging
from typing import Optional
from rhythm_state import UserRhythmState, AgentDecision, UnifiedResponse

logger = logging.getLogger(__name__)

PHI = 1.618


def compose_response(
    decision: Optional[AgentDecision],
    state: UserRhythmState,
    ai_response: str = ''
) -> UnifiedResponse:
    """Compose unified Radim response from agent decision + rhythm state.

    Args:
        decision: The winning agent's decision (or None for silence)
        state: Current user rhythm state
        ai_response: Text from AI chat (if coordinator routed to AI)

    Returns:
        UnifiedResponse ready for TTS + frontend display
    """
    if decision is None:
        return UnifiedResponse(
            text='',
            source_agent='none',
            should_speak=False,
            audit_trail=[{'agent': 'none', 'reason': 'Silence is best action'}]
        )

    # Start with agent's message or AI response
    text = decision.message or ai_response or ''

    # Adapt text to rhythm state
    text = _adapt_text(text, state, decision)

    # Compute voice metadata
    speech_rate = state.speech_rate
    pause_ms = state.pause_ms
    tone = decision.tone or state.preferred_tone

    # Build audit trail
    audit = [{
        'agent': decision.agent_name,
        'action': decision.action,
        'priority': round(decision.priority, 2),
        'reason': decision.reason,
        'tone': tone,
        'rhythm_phase': state.rhythm_phase,
        'energy': round(state.energy, 2),
        'stress': round(state.stress, 2),
    }]

    return UnifiedResponse(
        text=text,
        source_agent=decision.agent_name,
        tone=tone,
        speech_rate=speech_rate,
        pause_ms=pause_ms,
        verbosity=state.verbosity,
        priority=decision.priority,
        should_speak=bool(text) and decision.action != 'wait',
        audit_trail=audit
    )


def _adapt_text(text: str, state: UserRhythmState, decision: AgentDecision) -> str:
    """Adapt text to user's current state — length, complexity, empathy."""

    if not text:
        return text

    # Short responses when tired/overloaded
    if state.response_length == 'short' and len(text) > 100:
        # Truncate at sentence boundary
        sentences = text.split('. ')
        if len(sentences) > 2:
            text = '. '.join(sentences[:2]) + '.'

    # Add empathy prefix for emotional states
    if state.needs_comfort and decision.tone in ('gentle', 'calm'):
        empathy_prefixes = [
            'Jsem tady s vámi. ',
            'Rozumím. ',
            'To je v pořádku. ',
        ]
        import random
        if not any(text.startswith(p) for p in empathy_prefixes):
            text = random.choice(empathy_prefixes) + text

    # Crisis: make text actionable and clear
    if state.is_crisis:
        if not any(w in text.lower() for w in ['155', '112', 'pomoc', 'záchrank']):
            text += ' Pokud potřebujete pomoc, stiskněte nouzové tlačítko.'

    return text


def compose_proactive(
    state: UserRhythmState,
    agent_name: str,
    message: str,
    action: str = 'speak'
) -> UnifiedResponse:
    """Compose a proactive (unsolicited) response from an agent.

    Used by agent_loop scheduled tasks — not user-initiated.
    """
    # Don't proactively speak if user should rest
    if state.should_be_quiet and action != 'alert':
        return UnifiedResponse(
            text='',
            source_agent=agent_name,
            should_speak=False,
            audit_trail=[{'agent': agent_name, 'reason': 'User should rest — suppressed'}]
        )

    return UnifiedResponse(
        text=message,
        source_agent=agent_name,
        tone=state.preferred_tone,
        speech_rate=state.speech_rate,
        pause_ms=state.pause_ms,
        verbosity=state.verbosity,
        should_speak=True,
        audit_trail=[{
            'agent': agent_name,
            'action': action,
            'proactive': True,
            'rhythm_phase': state.rhythm_phase,
            'interruptibility': round(state.interruptibility, 2),
        }]
    )


logger.info("🎙️ Response Composer loaded — unifies agent decisions into Radim's voice")
