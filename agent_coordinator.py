# ============================================
# 🎭 AGENT COORDINATOR — Multi-Agent Orchestration
# ============================================
# 6 specialized agents, 1 voice (Radim).
# Each agent evaluates the same UserRhythmState.
# Coordinator picks the best action — or no action.
#
# Agents call EXISTING engines (no new ML).
# ============================================

import logging
from datetime import datetime
from typing import List, Optional
from rhythm_state import UserRhythmState, AgentDecision

logger = logging.getLogger(__name__)

PHI = 1.618


# ============================================
# AGENT BASE CLASS
# ============================================

class BaseAgent:
    """Every agent inherits this. Evaluates rhythm state and proposes action."""

    name: str = 'base'
    base_priority: float = 0.5

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        """Evaluate state and optionally user input. Return decision."""
        return AgentDecision(agent_name=self.name)

    def should_act(self, state: UserRhythmState) -> bool:
        """Quick check — should this agent even evaluate?"""
        return True

    def get_priority(self, state: UserRhythmState) -> float:
        """Dynamic priority based on rhythm state."""
        return self.base_priority


# ============================================
# 1. SAFETY AGENT — highest priority, crisis handling
# ============================================

class SafetyAgent(BaseAgent):
    name = 'safety'
    base_priority = 1.0  # Always highest

    def should_act(self, state: UserRhythmState) -> bool:
        return True  # Safety ALWAYS evaluates — user input might be crisis

    def get_priority(self, state: UserRhythmState) -> float:
        if state.is_crisis:
            return 1.0
        return 0.8 + state.risk * 0.2

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        logger.info(f"🛡️ SafetyAgent.evaluate(input='{user_input[:30]}', risk={state.risk})")
        if not user_input:
            # No input — check proactive safety from state only
            if state.risk > 0.7:
                return AgentDecision(
                    agent_name=self.name, should_act=True, priority=0.95,
                    action='alert',
                    message='Radim zjistil zvýšené riziko. Jak se cítíte?',
                    reason=f"High risk: {state.risk:.2f}",
                    confidence=state.confidence, tone='gentle', urgency='high'
                )
            return AgentDecision(agent_name=self.name, should_act=False, reason='No safety concern')

        lower = user_input.lower()

        # 1. KEYWORD CHECK FIRST — fastest, most reliable
        crisis_words = ['spadl', 'upadl', 'nemůžu vstát', 'pomoc', 'záchrank',
                        'bolí na hrudi', 'nemůžu dýchat', 'omdlel', 'krev',
                        'bezvědomí', '155', '112', 'nehoda', 'zranění', 'zlomenina']
        # Sprint AO.6: digit-only words use word-boundary regex so phone
        # numbers like "603111222" don't match the substring "112". Text
        # words keep substring match so 'spadl' still catches 'spadl jsem'.
        import re as _re_safety
        def _match_crisis(w, txt):
            if w.isdigit():
                return bool(_re_safety.search(r'\b' + _re_safety.escape(w) + r'\b', txt))
            return w in txt
        matched = [w for w in crisis_words if _match_crisis(w, lower)]
        if matched:
            return AgentDecision(
                agent_name=self.name, should_act=True, priority=1.0,
                action='escalate',
                message='Jsem tady s vámi. Zůstaňte v klidu. Potřebujete záchranku? Stiskněte nouzové tlačítko nebo řekněte "zavolej záchranku".',
                reason=f'Crisis keyword: {matched[:2]}',
                confidence=0.85, tone='calm', urgency='critical'
            )

        # 2. SCENARIO ENGINE — deeper analysis (may have false negatives)
        try:
            from scenario_engine import detect_scenario
            scenario = detect_scenario(user_input, user_id=state.user_id)
            if scenario:
                sev = scenario.get('severity', '')
                is_critical = sev in ('critical', 'high') or (isinstance(sev, (int, float)) and sev >= 5)
                if is_critical:
                    return AgentDecision(
                        agent_name=self.name, should_act=True, priority=1.0,
                        action='escalate',
                        message=scenario.get('response', 'Jsem tady. Jste v bezpečí.'),
                        reason=f"Scenario: {scenario.get('type', 'unknown')}",
                        confidence=0.9, tone='calm', urgency='critical'
                    )
        except Exception:
            pass

        # 3. Proactive safety from rhythm state
        if state.risk > 0.7:
            return AgentDecision(
                agent_name=self.name, should_act=True, priority=0.95,
                action='alert',
                message='Radim zjistil zvýšené riziko. Jak se cítíte?',
                reason=f"High risk: {state.risk:.2f}",
                confidence=state.confidence, tone='gentle', urgency='high'
            )

        return AgentDecision(agent_name=self.name, should_act=False, reason='No safety concern')


# ============================================
# 2. CARE AGENT — health, medication, vitals
# ============================================

class CareAgent(BaseAgent):
    name = 'care'
    base_priority = 0.8

    def should_act(self, state: UserRhythmState) -> bool:
        return True  # Always evaluates (medication reminders)

    def get_priority(self, state: UserRhythmState) -> float:
        if state.cognitive_load > 0.7:
            return 0.9  # High priority when confused
        return self.base_priority

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        # Check health/medication intent
        if user_input:
            lower = user_input.lower()
            health_words = ['lék', 'léky', 'prášky', 'bolí', 'bolest', 'hlava', 'břicho',
                            'nevolnost', 'závrat', 'teplota', 'horečka', 'kašel', 'dýchání']
            if any(w in lower for w in health_words):
                # Check drug interactions
                try:
                    from drug_interactions import check_user_interactions
                    warnings = check_user_interactions(state.user_id)
                    if warnings:
                        return AgentDecision(
                            agent_name=self.name,
                            should_act=True,
                            priority=0.85,
                            action='speak',
                            message='Pozor na kombinaci léků: ' + warnings[0]['warning'],
                            reason='Drug interaction detected',
                            confidence=0.8,
                            tone='calm',
                            urgency='high'
                        )
                except Exception:
                    pass

                # General health concern
                return AgentDecision(
                    agent_name=self.name,
                    should_act=True,
                    priority=0.75,
                    action='speak',
                    message='',  # AI will handle the health question
                    reason=f'Health keyword detected: {[w for w in health_words if w in lower][:2]}',
                    confidence=0.7,
                    tone='gentle' if 'bolí' in lower else 'calm',
                    urgency='normal'
                )

        # Proactive: cognitive decline
        if state.cognitive_load > 0.7:
            return AgentDecision(
                agent_name=self.name,
                should_act=True,
                priority=0.7,
                action='comfort',
                message='Zdá se, že jste unavený. Co takhle si odpočinout?',
                reason=f"High cognitive load: {state.cognitive_load:.2f}",
                tone='gentle',
                urgency='low'
            )

        return AgentDecision(agent_name=self.name, should_act=False)


# ============================================
# 3. COORDINATOR AGENT — main brain, anticipation
# ============================================

class CoordinatorAgent(BaseAgent):
    name = 'coordinator'
    base_priority = 0.6

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        """Main routing — if no specialized agent handles it, coordinator does."""
        if not user_input:
            return AgentDecision(agent_name=self.name, should_act=False)

        # This is the "default" — pass to AI chat
        return AgentDecision(
            agent_name=self.name,
            should_act=True,
            priority=0.5,
            action='speak',
            message='',  # Will be filled by AI
            reason='Default routing to AI chat',
            confidence=0.6,
            tone=state.preferred_tone,
            urgency='normal'
        )


# ============================================
# 4. DAILY LIFE AGENT — routine, tasks, time
# ============================================

class DailyLifeAgent(BaseAgent):
    name = 'daily'
    base_priority = 0.4

    def should_act(self, state: UserRhythmState) -> bool:
        # Don't interrupt at night
        return state.rhythm_phase != 'night_rest'

    def get_priority(self, state: UserRhythmState) -> float:
        if state.rhythm_phase == 'morning_rise':
            return 0.6  # Morning routine more important
        return self.base_priority

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        if user_input:
            lower = user_input.lower()
            if any(w in lower for w in ['úkol', 'připomínka', 'co mám', 'plán']):
                return AgentDecision(
                    agent_name=self.name,
                    should_act=True,
                    priority=0.5,
                    action='speak',
                    message='',
                    reason='Task/plan intent detected',
                    tone='neutral'
                )

        return AgentDecision(agent_name=self.name, should_act=False)


# ============================================
# 5. SOCIAL AGENT — relationships, loneliness
# ============================================

class SocialAgent(BaseAgent):
    name = 'social'
    base_priority = 0.3

    def should_act(self, state: UserRhythmState) -> bool:
        return state.social_need > 0.5

    def get_priority(self, state: UserRhythmState) -> float:
        return min(0.7, self.base_priority + state.social_need * 0.4)

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        if state.social_need > 0.7 and state.interruptibility > 0.4:
            return AgentDecision(
                agent_name=self.name,
                should_act=True,
                priority=0.5,
                action='suggest',
                message='Už jste dlouho nemluvil s rodinou. Chcete někomu zavolat?',
                reason=f"High social need: {state.social_need:.2f}",
                tone='gentle',
                urgency='low'
            )

        return AgentDecision(agent_name=self.name, should_act=False)


# ============================================
# 6. GROWTH AGENT — learning, skills, progress
# ============================================

class GrowthAgent(BaseAgent):
    name = 'growth'
    base_priority = 0.2  # Lowest — never urgent

    def should_act(self, state: UserRhythmState) -> bool:
        # Only when user is relaxed and engaged
        return (state.energy > 0.4 and
                state.stress < 0.3 and
                state.focus > 0.3 and
                state.rhythm_phase in ('active_peak', 'morning_rise'))

    def evaluate(self, state: UserRhythmState, user_input: str = '') -> AgentDecision:
        if self.should_act(state) and state.interruptibility > 0.6:
            return AgentDecision(
                agent_name=self.name,
                should_act=True,
                priority=0.2,
                action='suggest',
                message='Co takhle krátký kvíz? Pomůže udržet paměť v kondici.',
                reason='Good conditions for learning activity',
                tone='encouraging',
                urgency='low'
            )

        return AgentDecision(agent_name=self.name, should_act=False)


# ============================================
# DECISION ENGINE — picks best action from all agents
# ============================================

ALL_AGENTS = [
    SafetyAgent(),
    CareAgent(),
    CoordinatorAgent(),
    DailyLifeAgent(),
    SocialAgent(),
    GrowthAgent(),
]


def evaluate_all_agents(state: UserRhythmState, user_input: str = '') -> List[AgentDecision]:
    """Run all agents, return sorted decisions."""
    decisions = []
    for agent in ALL_AGENTS:
        try:
            if agent.should_act(state):
                decision = agent.evaluate(state, user_input)
                decision.priority = agent.get_priority(state)
                decisions.append(decision)
        except Exception as e:
            logger.warning(f"Agent {agent.name} error: {e}")
            decisions.append(AgentDecision(
                agent_name=agent.name,
                should_act=False,
                reason=f"Error: {e}"
            ))

    # Sort by priority (highest first)
    decisions.sort(key=lambda d: d.priority, reverse=True)
    return decisions


def pick_best_action(state: UserRhythmState, user_input: str = '') -> Optional[AgentDecision]:
    """Pick the single best action — or None if silence is best."""
    decisions = evaluate_all_agents(state, user_input)

    # Filter to only agents that want to act
    active = [d for d in decisions if d.should_act]

    if not active:
        # Check if we should proactively do something
        if state.should_be_quiet:
            logger.info(f"🤫 All agents quiet — user should rest (energy={state.energy:.2f})")
            return None
        # Default to coordinator if user said something
        if user_input:
            return AgentDecision(
                agent_name='coordinator',
                should_act=True,
                priority=0.5,
                action='speak',
                message='',
                reason='No agent claimed input — routing to AI',
                tone=state.preferred_tone
            )
        return None

    # Safety always wins
    safety = next((d for d in active if d.agent_name == 'safety'), None)
    if safety and safety.priority > 0.8:
        logger.info(f"🛡️ Safety agent takes over: {safety.reason}")
        _emit_decision_to_bus(state, safety)
        return safety

    # Otherwise highest priority
    best = active[0]
    logger.info(f"🎭 Best agent: {best.agent_name} (priority={best.priority:.2f}, action={best.action})")
    _emit_decision_to_bus(state, best)
    return best


def _emit_decision_to_bus(state, decision):
    """Sprint AG.4.7: log coordinator's chosen agent + action to bus.

    This closes the feedback loop: anticipation/agent_loop can see
    what the chat-time coordinator decided and avoid duplicate alerts
    if the action was already taken (e.g. safety_agent fired a crisis
    response — agent_loop next cycle sees the decision and dedupes).
    """
    try:
        from agent_bus import emit as _bus_emit
        if not state or not getattr(state, 'user_id', None):
            return
        # severity mirrors decision urgency
        urgency_map = {'low': 'info', 'normal': 'info', 'high': 'warning',
                       'critical': 'crisis'}
        severity = urgency_map.get(getattr(decision, 'urgency', 'normal'), 'info')
        _bus_emit(
            user_id=state.user_id,
            sender=f'coordinator.{decision.agent_name}',
            kind='decision',
            severity=severity,
            topic=f'action:{decision.action}',
            payload={
                'agent': decision.agent_name,
                'action': decision.action,
                'priority': round(float(decision.priority or 0), 3),
                'urgency': getattr(decision, 'urgency', 'normal'),
                'reason': (decision.reason or '')[:200],
                'tone': decision.tone,
                'message': (decision.message or '')[:200],
            },
        )
    except Exception:
        # Bus failure must never block coordinator response.
        pass


logger.info("🎭 Agent Coordinator loaded — 6 agents (safety, care, coordinator, daily, social, growth)")
# v10.9.1 — force rebuild Mon Apr 13 00:26:20 CEST 2026
