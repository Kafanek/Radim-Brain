# ============================================
# KAL HELPERS v1.0.0
# ============================================
# Shared configuration, feature flags, IDOR check,
# and agent prompt mappings for KAL routes.
# Extracted from kal_routes.py for modularity.
# ============================================

import logging
from flask import g, jsonify

logger = logging.getLogger(__name__)

# ============================================================================
# FEATURE FLAGS — set by init_kal_routes()
# ============================================================================

MEMORY_AVAILABLE = False
RADIM_BRAIN_AVAILABLE = False


def init_kal_routes(memory_available=False, radim_brain_available=False):
    """Call from app.py after determining feature availability."""
    global MEMORY_AVAILABLE, RADIM_BRAIN_AVAILABLE
    MEMORY_AVAILABLE = memory_available
    RADIM_BRAIN_AVAILABLE = radim_brain_available


# ============================================================================
# IDOR PROTECTION
# ============================================================================

def check_idor(requested_user_id):
    """v330: Validate authenticated user matches requested user_id.
    Returns None if OK, or error response tuple if IDOR detected.
    Allows 'radim-ai' requests and admins through."""
    auth_user = getattr(g, 'auth_user', None)
    if not auth_user:
        return None  # optional_auth — no token = anonymous access (for senior devices)
    user_role = auth_user.get('role', 'user') if isinstance(auth_user, dict) else 'user'
    auth_id = str(auth_user.get('id', '')) if isinstance(auth_user, dict) else ''
    # Admins bypass IDOR check
    if user_role in ('administrator', 'admin', 'caregiver'):
        return None
    # Check if requesting own data
    if auth_id and str(requested_user_id) != auth_id:
        logger.warning(f"IDOR blocked: user {auth_id} tried to access {requested_user_id}")
        return jsonify({'success': False, 'error': 'Pristup zamitnut'}), 403
    return None


# ============================================================================
# AGENT CONFIGURATION
# ============================================================================

KAL_AGENT_PROMPTS = {
    'core': '',
    'agent_protector': '[Rezim: Pan Ochrance — priorita bezpeci a klid. Odpovidej strucne, uklidnujicim tonem.]',
    'agent_teacher': '[Rezim: Pan Ucitel — vzdelavaci rezim. Vysvetluj srozumitelne, pouzij priklady.]',
    'agent_storyteller': '[Rezim: Pan Vypravec — kreativni vypraveni. Bud poeticky, pouzivej obrazy.]',
    'agent_senior': '[Rezim: Pan Senior — zjednoduseny rezim. Kratke vety, pratelsky ton.]',
    'agent_caller': '[Rezim: Agent Caller — asistence s telefonaty. Nabidni zavolani, prepojeni.]',
    'agent_coder': '[Rezim: Pan Programator — technicka podpora. Presne instrukce krok za krokem.]',
}

KAL_AGENT_NAMES = {
    'core': 'Pan Kafanek',
    'agent_teacher': 'Pan Ucitel Kafanek',
    'agent_protector': 'Pan Ochrance Kafanek',
    'agent_storyteller': 'Pan Vypravec Kafanek',
    'agent_senior': 'Pan Senior Kafanek',
    'agent_caller': 'Agent Caller',
    'agent_coder': 'Pan Programator'
}


def get_agent_name(agent):
    """Get Czech display name for agent type."""
    return KAL_AGENT_NAMES.get(agent, 'Pan Kafanek')


logger.info("✅ KAL Helpers loaded — feature flags, IDOR, agent config")
