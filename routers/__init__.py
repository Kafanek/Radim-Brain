"""
RadimCare Backend Routers
"""

from .tts_proxy_routes import router as tts_proxy_router
from .claude_ai_routes import router as claude_ai_router
from .orchestrator_routes import router as orchestrator_router

__all__ = [
    'tts_proxy_router',
    'claude_ai_router',
    'orchestrator_router'
]
