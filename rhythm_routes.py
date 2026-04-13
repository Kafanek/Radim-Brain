# ============================================
# 🎵 RHYTHM API — Multi-Agent Coordination Endpoints
# ============================================

import logging
from flask import Blueprint, request, jsonify
from auth_middleware import optional_auth

logger = logging.getLogger(__name__)

rhythm_bp = Blueprint('rhythm', __name__, url_prefix='/api/rhythm')


@rhythm_bp.route('/state/<user_id>', methods=['GET'])
@optional_auth
def get_rhythm_state(user_id):
    """Get current UserRhythmState — aggregated from all engines."""
    try:
        from rhythm_state import compute_rhythm_state
        state = compute_rhythm_state(user_id)
        return jsonify({'success': True, **state.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@rhythm_bp.route('/evaluate', methods=['POST'])
@optional_auth
def evaluate_input():
    """Evaluate user input through multi-agent coordinator.

    Body: { "user_id": "...", "message": "Bolí mě hlava" }
    Returns: agent decision + unified response + audit trail
    """
    data = request.json or {}
    user_id = data.get('user_id', '')
    message = data.get('message', '') or data.get('user_input', '')

    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        from rhythm_state import compute_rhythm_state
        from agent_coordinator import pick_best_action, evaluate_all_agents
        from response_composer import compose_response

        # 1. Compute rhythm state
        state = compute_rhythm_state(user_id)

        # 2. All agents evaluate
        all_decisions = evaluate_all_agents(state, message)

        # 3. Pick best action
        best = pick_best_action(state, message)

        # 4. Compose unified response
        response = compose_response(best, state)

        return jsonify({
            'success': True,
            'rhythm_state': state.to_dict(),
            'response': response.to_dict(),
            'all_decisions': [d.to_dict() for d in all_decisions],
            'winning_agent': best.agent_name if best else 'none',
        })
    except Exception as e:
        logger.warning(f"Rhythm evaluate error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@rhythm_bp.route('/agents', methods=['GET'])
def list_agents():
    """List all agents with their current status."""
    try:
        from agent_coordinator import ALL_AGENTS
        agents = []
        for agent in ALL_AGENTS:
            agents.append({
                'name': agent.name,
                'base_priority': agent.base_priority,
                'class': agent.__class__.__name__,
            })
        return jsonify({'success': True, 'agents': agents, 'count': len(agents)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@rhythm_bp.route('/skills/<user_id>', methods=['GET'])
@optional_auth
def get_skills(user_id):
    """Get skill progress from existing skill_map engine."""
    try:
        from skill_map import compute_all_skills
        skills = compute_all_skills(user_id)
        return jsonify({'success': True, 'skills': skills})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
