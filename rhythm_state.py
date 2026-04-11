# ============================================
# 🎵 RHYTHM STATE — Unified User State for Multi-Agent Coordination
# ============================================
# Aggregates ALL existing engines into one state object.
# Every agent reads this before deciding whether/how to act.
#
# UserRhythmState = f(brain_state, circadian, anticipation,
#                     social_isolation, cognitive, interaction_history)
# ============================================

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# ============================================
# DATA MODELS
# ============================================

@dataclass
class UserRhythmState:
    """Complete rhythm state of a user at a point in time.

    All values 0.0-1.0 unless noted.
    Computed from existing RadimCare engines — no new data sources needed.
    """
    user_id: str = ''
    timestamp: str = ''

    # Core dimensions
    energy: float = 0.5          # 0=exhausted, 1=energized (from brain C + circadian)
    stress: float = 0.0          # 0=calm, 1=crisis (from anticipation Ĉ trend)
    focus: float = 0.5           # 0=distracted, 1=engaged (from interaction patterns)
    mood: float = 0.5            # 0=negative, 1=positive (from emotional patterns)
    risk: float = 0.0            # 0=safe, 1=danger (from predictive_agent)
    social_need: float = 0.3     # 0=wants solitude, 1=lonely (from isolation agent)
    cognitive_load: float = 0.3  # 0=rested, 1=overloaded (from cognitive assessment)

    # Rhythm context
    rhythm_phase: str = 'unknown'    # morning_rise|active_peak|afternoon_decline|evening_calm|night_rest|disrupted
    interruptibility: float = 0.5    # 0=do not disturb, 1=available (computed)

    # Response preferences (computed from state)
    preferred_tone: str = 'neutral'  # gentle|neutral|encouraging|calm|urgent
    response_length: str = 'medium'  # short|medium|long
    speech_rate: float = 0.9         # 0.7-1.0 (slower in crisis/fatigue)
    pause_ms: int = 400              # 200-1618 (φ-proportioned)
    verbosity: str = 'normal'        # minimal|normal|detailed

    # Meta
    brain_mode: str = 'HARMONY'      # HARMONY|ALERT|CRISIS
    coherence: float = 5.0           # Raw C value (0-10)
    confidence: float = 0.5          # How confident we are in this state

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_crisis(self) -> bool:
        return self.risk > 0.7 or self.brain_mode == 'CRISIS'

    @property
    def should_be_quiet(self) -> bool:
        """Best action might be no action."""
        return (self.interruptibility < 0.3 and
                self.risk < 0.3 and
                self.energy < 0.3)

    @property
    def needs_comfort(self) -> bool:
        return self.mood < 0.3 or self.social_need > 0.7


@dataclass
class AgentDecision:
    """A decision made by one agent."""
    agent_name: str
    should_act: bool = False
    priority: float = 0.5           # 0=low, 1=critical
    action: str = 'none'            # none|speak|remind|alert|escalate|comfort|wait
    message: str = ''               # What to say (Czech)
    reason: str = ''                # Why this decision (for audit)
    confidence: float = 0.5
    tone: str = 'neutral'
    urgency: str = 'normal'         # low|normal|high|critical
    voice_metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UnifiedResponse:
    """Final response composed from agent decisions — one voice of Radim."""
    text: str = ''
    source_agent: str = ''
    tone: str = 'neutral'
    speech_rate: float = 0.9
    pause_ms: int = 400
    verbosity: str = 'normal'
    priority: float = 0.5
    should_speak: bool = True
    audit_trail: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================
# RHYTHM STATE COMPUTATION
# ============================================

def compute_rhythm_state(user_id: str) -> UserRhythmState:
    """Compute UserRhythmState by aggregating ALL existing engines.

    Calls existing code — no new ML or data sources.
    Gracefully degrades if any engine is unavailable.
    """
    state = UserRhythmState(
        user_id=user_id,
        timestamp=datetime.utcnow().isoformat()
    )

    # 1. BRAIN STATE — Ψ(t) = C, E, R, S
    try:
        from database import db_context
        with db_context(commit=False) as db:
            row = db.execute("""
                SELECT coherence, mode, created_at
                FROM brain_states
                WHERE user_id = ? ORDER BY created_at DESC LIMIT 1
            """, (user_id,)).fetchone()
            if row:
                c = float(row[0]) if row[0] else 5.0
                state.coherence = c
                state.brain_mode = row[1] or 'HARMONY'
                state.energy = min(1.0, max(0.0, c / 8.0))  # C 0-8 → energy 0-1
                state.stress = min(1.0, max(0.0, (c - 5.0) / 5.0)) if c > 5.0 else 0.0
                state.confidence += 0.15
    except Exception as e:
        logger.debug(f"Rhythm: brain state unavailable: {e}")

    # 2. CIRCADIAN PHASE — from circadian engine
    try:
        hour = datetime.utcnow().hour
        if 5 <= hour < 9:
            state.rhythm_phase = 'morning_rise'
            state.energy = min(1.0, state.energy + 0.1)
        elif 9 <= hour < 12:
            state.rhythm_phase = 'active_peak'
            state.energy = min(1.0, state.energy + 0.2)
        elif 12 <= hour < 15:
            state.rhythm_phase = 'afternoon_decline'
            state.energy = max(0.0, state.energy - 0.1)
        elif 15 <= hour < 19:
            state.rhythm_phase = 'active_peak'
        elif 19 <= hour < 22:
            state.rhythm_phase = 'evening_calm'
            state.energy = max(0.0, state.energy - 0.15)
        elif hour >= 22 or hour < 5:
            state.rhythm_phase = 'night_rest'
            state.energy = max(0.0, state.energy - 0.3)
            state.interruptibility = 0.1  # Don't bother at night
    except Exception:
        pass

    # 3. PREDICTIVE RISK — from predictive agent
    try:
        from predictive_agent import predict_risk
        risk_data = predict_risk(user_id)
        if risk_data and 'risk_score' in risk_data:
            state.risk = min(1.0, risk_data['risk_score'] / 100.0)
            state.confidence += 0.15
    except Exception as e:
        logger.debug(f"Rhythm: predictive agent unavailable: {e}")

    # 4. SOCIAL ISOLATION — from advanced agents
    try:
        from advanced_agents import SocialIsolationAgent
        iso = SocialIsolationAgent()
        iso_data = iso.compute_score(user_id)
        if iso_data:
            state.social_need = min(1.0, iso_data.get('score', 30) / 100.0)
            state.confidence += 0.1
    except Exception as e:
        logger.debug(f"Rhythm: social isolation unavailable: {e}")

    # 5. COGNITIVE LOAD — from cognitive assessment
    try:
        from cognitive_assessment import compute_cognitive_score
        cog = compute_cognitive_score(user_id)
        if cog and 'score' in cog:
            # High score = good cognition = low load
            state.cognitive_load = max(0.0, 1.0 - (cog['score'] / 100.0))
            state.confidence += 0.1
    except Exception as e:
        logger.debug(f"Rhythm: cognitive assessment unavailable: {e}")

    # 6. INTERACTION PATTERNS — focus & mood from recent history
    try:
        from database import db_context
        with db_context(commit=False) as db:
            # Recent interaction count (last 2h)
            count = db.execute("""
                SELECT COUNT(*) FROM brain_states
                WHERE user_id = ? AND created_at > ?
            """, (user_id, (datetime.utcnow() - timedelta(hours=2)).isoformat())).fetchone()
            interactions = (count[0] or 0) if count else 0
            state.focus = min(1.0, interactions / 10.0)  # 10+ interactions = fully engaged
    except Exception:
        pass

    # 7. COMPUTE DERIVED VALUES
    _compute_preferences(state)

    return state


def _compute_preferences(state: UserRhythmState):
    """Compute response preferences from core dimensions."""

    # Interruptibility = energy × (1 - stress) × time_factor
    time_factor = 0.8 if state.rhythm_phase in ('morning_rise', 'active_peak') else 0.4
    state.interruptibility = max(0.05, min(1.0,
        state.energy * (1.0 - state.stress * 0.5) * time_factor
    ))

    # Crisis overrides
    if state.is_crisis:
        state.interruptibility = 1.0  # Always interrupt for crisis

    # Tone
    if state.risk > 0.7:
        state.preferred_tone = 'urgent'
    elif state.stress > 0.5:
        state.preferred_tone = 'calm'
    elif state.mood < 0.3:
        state.preferred_tone = 'gentle'
    elif state.energy > 0.7:
        state.preferred_tone = 'encouraging'
    else:
        state.preferred_tone = 'neutral'

    # Response length
    if state.cognitive_load > 0.7 or state.energy < 0.3:
        state.response_length = 'short'
        state.verbosity = 'minimal'
    elif state.focus > 0.7 and state.energy > 0.5:
        state.response_length = 'long'
        state.verbosity = 'detailed'
    else:
        state.response_length = 'medium'
        state.verbosity = 'normal'

    # Speech params (φ-proportioned)
    PHI = 1.618
    if state.brain_mode == 'CRISIS':
        state.speech_rate = 0.75
        state.pause_ms = int(1000 * PHI)  # 1618ms
    elif state.brain_mode == 'ALERT':
        state.speech_rate = 0.85
        state.pause_ms = 1000
    elif state.energy < 0.3:
        state.speech_rate = 0.8
        state.pause_ms = int(618 * PHI)   # ~1000ms
    else:
        state.speech_rate = 0.92
        state.pause_ms = 618              # φ base

    # Brain mode label
    if state.risk > 0.7 or state.stress > 0.8:
        state.brain_mode = 'CRISIS'
    elif state.risk > 0.4 or state.stress > 0.5:
        state.brain_mode = 'ALERT'


logger.info("🎵 Rhythm State Engine loaded — aggregates brain, circadian, predictive, social, cognitive signals")
