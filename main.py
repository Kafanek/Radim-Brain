"""
KAL (Kolibri AI Language) System with AIWU Integration
Advanced AI Assistant for Seniors - Main Application
"""

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
import asyncio
import aiohttp
import json
import logging
import os
import uuid
import time
import redis.asyncio as redis
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import uvicorn
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# V3 ENV VALIDATION: Warn about missing keys (non-critical)
# ============================================================================

REQUIRED_ENV = ["GEMINI_API_KEY"]
missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
if missing:
    print(f"⚠️  Missing ENV variables: {', '.join(missing)}")
    print(f"💡 Check your .env file - some features may be limited")
    # Note: Not raising error - system can work without Gemini in fallback mode

# Import local modules
from integrations.gemini_integration import GeminiIntegration
from core.voice_processor import VoiceProcessor
from core.context_manager import ContextManager
from core.senior_optimizer import SeniorOptimizer
from core.analytics import AnalyticsEngine
from models.requests import VoiceCommandRequest, ContextData, ClaudeAgentRequest
from models.responses import VoiceResponse, AnalyticsResponse, ClaudeAgentResponse
from utils.logger import setup_logger
from utils.security import verify_api_key
from services.speech_service import SpeechService
from services.memory_service import MemoryService
from integrations.vscode_integration import VSCodeIntegration
from integrations.mykolibri_integration import MyKolibriIntegration
from api import therapy_routes, gemini_routes, learning_routes, ai_bridge_routes, news_routes, quiz_routes, radim_routes, auth_routes, gdpr_routes, iot_routes, radim_iot_routes, senior_api_routes, azure_proxy, elevenlabs_proxy, gcal_proxy, harmony_routes, notification_routes, soul_routes, claude_orchestrator
from routers import (
    library, publications, radim_memory, voice_synthesis, quantum_routes, mcp_routes, agent_routes, radim_google, mamba_rag_routes, tts_proxy_routes, consciousness_routes, phi27_routes, values_routes, story_studio, monitoring_dashboard, agents_live_test
)
import windsurf_proxy

# Redis Fallback System
from utils.redis_fallback import redis_adapter

# AI Rodina Kafánků - Multi-Agent System
from services.redis_schema import RedisManager
from services.agent_router import AgentRouter, AgentCapabilities
from services.agent_orchestrator import AgentOrchestrator
from services.agent_manager import AgentManager
from models.agent_models import (
    RouteMessageRequest, CreateSessionRequest, AgentHandoffRequest,
    EmergencyRequest, UpdateSessionActivityRequest,
    RouteMessageResponse, SessionResponse, HandoffResponse,
    EmergencyResponse, HealthResponse as AgentHealthResponse,
    StatsResponse, AgentCapabilitiesResponse, ActiveSessionsResponse
)

# Initialize logger
logger = setup_logger(__name__)

# Redis connection
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global redis_client, orchestrator, redis_manager
    
    # Startup
    logger.info("🚀 Starting KAL-AIWU System...")
    
    # Initialize Redis with fallback support
    await redis_adapter.initialize()
    redis_client = redis_adapter.redis_client  # For backward compatibility
    
    # Initialize services
    await initialize_services()
    
    logger.info("✅ KAL-AIWU System ready!")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down KAL-AIWU System...")
    
    # Graceful shutdown orchestrator
    if orchestrator:
        logger.info("🎭 Shutting down AI Rodina Kafánků...")
        try:
            await orchestrator.shutdown()
            logger.info("✅ Orchestrator shutdown complete")
        except Exception as e:
            logger.error(f"❌ Orchestrator shutdown error: {e}")
    
    # Close Redis connections
    if redis_manager:
        try:
            await redis_manager.close()
            logger.info("✅ RedisManager closed")
        except Exception as e:
            logger.error(f"❌ RedisManager close error: {e}")
    
    # Cleanup Redis adapter (handles both Redis and fallbacks)
    await redis_adapter.cleanup()
    logger.info("✅ Redis adapter cleaned up")

# Initialize FastAPI app
app = FastAPI(
    title="KAL-AIWU System",
    description="Advanced AI Assistant for Seniors with AIWU Integration",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ============================================================================
# V3 MIDDLEWARE: Request ID Tracking
# ============================================================================

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Track requests with unique ID and timing (V3 enhancement)"""
    rid = str(uuid.uuid4())[:8]
    request.state.request_id = rid
    start = time.time()
    
    try:
        response = await call_next(request)
        duration = (time.time() - start) * 1000
        response.headers["X-Request-ID"] = rid
        
        # Log only important requests (skip health checks for noise reduction)
        if not request.url.path.startswith("/health"):
            logger.info(
                f"[{rid}] {request.method} {request.url.path} → "
                f"{response.status_code} ({duration:.0f}ms)"
            )
        
        return response
    except HTTPException as e:
        logger.error(f"[{rid}] HTTPException {e.status_code}: {e.detail}")
        raise
    except Exception as e:
        logger.exception(f"[{rid}] Unhandled error: {e}")
        raise HTTPException(status_code=500, detail="INTERNAL_SERVER_ERROR")

# ============================================================================
# MIDDLEWARE: Compression & CORS
# ============================================================================

app.add_middleware(GZipMiddleware, minimum_size=1000)
# CORS configuration with regex pattern for all local development ports
from fastapi.middleware.cors import CORSMiddleware
import re

class CustomCORSMiddleware(CORSMiddleware):
    """Custom CORS middleware that allows all localhost/127.0.0.1 origins in development"""
    def is_allowed_origin(self, origin: str) -> bool:
        # Production origins
        if origin in self.allow_origins:
            return True
        # Allow all localhost and 127.0.0.1 with any port for development
        if re.match(r"^http://(localhost|127\.0\.0\.1):\d+$", origin):
            return True
        return super().is_allowed_origin(origin)

app.add_middleware(
    CustomCORSMiddleware,
    allow_origins=[
        # Production domains
        "https://mykolibri-academy.cz",
        "https://app.mykolibri-academy.cz",
        "https://app.radimcare.cz",
        "https://polite-bush-001303503.6.azurestaticapps.net",
        # Azure Static Web App
        "https://radimstorage.z6.web.core.windows.net",
        "https://radimdashboard.z6.web.core.windows.net",  # Azure Storage Static Website
        "https://radim-app.azurewebsites.net",
        # Custom domain (Radim Care)
        "https://radimcare.cz",
        "https://www.radimcare.cz",
        "https://app.radimcare.cz",  # New Azure frontend domain
        # Heroku backend
        "https://radim-brain-2025-be1cd52b04dc.herokuapp.com",
        # Local development
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",  # MyKolibri Academy frontend (PRIMARY)
        "http://127.0.0.1:8081",
        "http://localhost:8083",
        "http://127.0.0.1:8083",
        "http://localhost:8084",
        "http://127.0.0.1:8084",
        "http://localhost:8085",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])  # 🔐 Auth System
app.include_router(gdpr_routes.router, prefix="/gdpr", tags=["GDPR"])  # 🛡️ GDPR Compliance

# 🔒 SECURE API PROXIES - API klíče jsou POUZE na backendu!
app.include_router(azure_proxy.router, tags=["Security"])  # 🔒 Azure TTS Proxy
app.include_router(elevenlabs_proxy.router, tags=["Security"])  # 🔒 ElevenLabs TTS Proxy
app.include_router(gcal_proxy.router, tags=["Security"])  # 🔒 Google Calendar Proxy

# 🎵 HARMONY RESONANCE ENGINE - Acoustic therapy system
app.include_router(harmony_routes.router, tags=["Harmony Resonance"])  # 🎵 Acoustic Harmony

app.include_router(therapy_routes.router)
app.include_router(gemini_routes.router)
app.include_router(learning_routes.router)
app.include_router(ai_bridge_routes.router)
app.include_router(library.router, prefix="/kal")  # 📚 E-book Library
app.include_router(publications.router)
# app.include_router(radim_memory.router)  # DEPRECATED - replaced by radim_routes with encryption
app.include_router(radim_routes.router)  # 🐦 GDPR-compliant Encrypted Radim Memory
app.include_router(voice_synthesis.router)
app.include_router(tts_proxy_routes.router)  # 🔒 TTS Proxy (ElevenLabs + Azure)
app.include_router(quantum_routes.router)
app.include_router(mamba_rag_routes.router)  # 🧬 Mamba-RAG Neural Architecture (Fibonacci-optimized)
app.include_router(news_routes.router)
app.include_router(quiz_routes.router)
app.include_router(mcp_routes.router)
app.include_router(agent_routes.router)
app.include_router(agents_live_test.router)  # 🎭 Live Agent Testing
app.include_router(radim_google.router)  # 🔑 Radim Google Services (Sheets, Drive, Calendar)
app.include_router(windsurf_proxy.router, prefix="/api", tags=["Windsurf"])  # 🧠 Windsurf ↔ Radim Brain ↔ Claude Proxy

# 🔍 Supervisor Agent - Monitoring & Optimization
from routers import supervisor_routes
app.include_router(supervisor_routes.router, prefix="/api", tags=["Supervisor"])  # 🔍 MCP Agent Supervisor

# 🧹 Cleanup Agent - System Cleanup
from routers import cleanup_routes
app.include_router(cleanup_routes.router, prefix="/api", tags=["Cleanup"])  # 🧹 Bezpečné čištění systému

# 🎭 Orchestrator Agent - Claude jako AI šéf
from routers import orchestrator_routes
app.include_router(orchestrator_routes.router, prefix="/api", tags=["Orchestrator"])  # 🎭 Claude Orchestrator

# 📊 MCP Dashboard
from fastapi.responses import FileResponse

# Mount dashboards as static files
app.mount("/dashboards", StaticFiles(directory="dashboards"), name="dashboards")

@app.get("/mcp-dashboard")
async def mcp_dashboard():
    """MCP Dashboard - Unified control panel"""
    return FileResponse("mcp_dashboard.html")

@app.get("/radim-dashboard")
async def radim_dashboard():
    """Radim Brain Dashboard - DEPRECATED - Use port 8080 dashboards instead"""
    return JSONResponse(
        status_code=301,
        content={
            "message": "Dashboard byl přesunut",
            "new_urls": {
                "personal": "http://localhost:8080/radim-personal-dashboard.html",
                "technik": "http://localhost:8002/dashboards/radim-technik-dashboard.html",
                "senior": "http://localhost:8080/radim-senior-dashboard.html"
            }
        }
    )

# 🎯 ROLE-BASED DASHBOARDS (deprecated - migrated to new structure)
# Old endpoints removed - use:
# - http://localhost:8080/radim-personal-dashboard.html (personál)
# - http://localhost:8002/dashboards/radim-technik-dashboard.html (technici)
# - http://localhost:8080/radim-senior-dashboard.html (senioři)

app.include_router(iot_routes.router)  # 🏠 IoT Kafánek - Zigbee & Sensor Network
app.include_router(radim_iot_routes.router)  # 🧠 Radim + IoT Integration - Inteligentní Symbióza

# 🌊 IoT CONSCIOUSNESS BRIDGE - Real-time vital signs → consciousness engine
from routers import iot_consciousness_routes
app.include_router(iot_consciousness_routes.router)  # 🌊 IoT → Consciousness Integration (Vital Streams)

app.include_router(notification_routes.router)  # 🔔 Notification System - Real-time alerts for staff
app.include_router(soul_routes.router, tags=["soul"])
app.include_router(claude_orchestrator.router, tags=["claude"]) 
app.include_router(senior_api_routes.router)  # 👴 Senior Management - Production Database & Sensors
app.include_router(consciousness_routes.router)  # 🧠 Consciousness System - FastAPI (Migrated!)
app.include_router(phi27_routes.router)  # 🌌 Φ27 Balance Model - FastAPI (Migrated!)
app.include_router(values_routes.router)  # 💎 Values System - FastAPI (Migrated!)
app.include_router(story_studio.router)  # 📖 Story Studio - AI Storytelling Engine
app.include_router(monitoring_dashboard.router)  # 📊 Monitoring Dashboard - Real-time Metrics

# 🗄️ Azure SQL Database API
from routers import memories_api
app.include_router(memories_api.router)  # 🧠 Memories API - Azure SQL Integration

# 🧠 KAL BRAIN - Centrální neuronová síť
try:
    from api import brain_routes
    app.include_router(brain_routes.router)  # 🧠 Neural Network Integration
    print("✅ KAL Brain routes loaded")
except ImportError as e:
    print(f"⚠️ KAL Brain routes not available: {e}") 

# Global services
gemini_integration: Optional[GeminiIntegration] = None
voice_processor: Optional[VoiceProcessor] = None
context_manager: Optional[ContextManager] = None
senior_optimizer: Optional[SeniorOptimizer] = None
analytics_engine: Optional[AnalyticsEngine] = None
speech_service: Optional[SpeechService] = None
memory_service: Optional[MemoryService] = None
vscode_integration: Optional[VSCodeIntegration] = None
mykolibri_integration: Optional[MyKolibriIntegration] = None

# AI Rodina Kafánků - Agent System
redis_manager: Optional[RedisManager] = None
agent_router: Optional[AgentRouter] = None
orchestrator: Optional[AgentOrchestrator] = None
agent_manager: Optional[AgentManager] = None

async def initialize_services():
    """Initialize all services"""
    global gemini_integration, voice_processor, context_manager
    global senior_optimizer, analytics_engine, speech_service
    global memory_service, vscode_integration, mykolibri_integration
    global redis_manager, agent_router, orchestrator, agent_manager
    
    try:
        # Initialize Gemini Integration
        gemini_integration = GeminiIntegration()
        
        # Initialize other services
        context_manager = ContextManager(redis_client)
        senior_optimizer = SeniorOptimizer()
        analytics_engine = AnalyticsEngine(redis_client)
        speech_service = SpeechService()
        memory_service = MemoryService(redis_client)
        
        # Initialize integrations
        vscode_integration = VSCodeIntegration()
        mykolibri_integration = MyKolibriIntegration()
        
        # Initialize voice processor with all dependencies
        voice_processor = VoiceProcessor(
            gemini_integration=gemini_integration,
            context_manager=context_manager,
            senior_optimizer=senior_optimizer,
            speech_service=speech_service,
            memory_service=memory_service
        )
        
        logger.info("✅ Core services initialized successfully")
        
        # ===== RADIM CONSCIOUSNESS SYSTEM INITIALIZATION =====
        import time
        consciousness_start = time.time()
        
        logger.info("🧠 Initializing Radim Consciousness System...")
        
        from consciousness import (
            get_consciousness_engine,
            get_timing_engine,
            get_harmonic_visualizer,
            get_crisis_detector,
            get_quantum_consciousness_bridge,
            HARMONIC,
            SEQUENCES
        )
        
        # Note: Engines are now lazy-initialized on first use
        # Only import functions here, actual initialization happens on demand
        
        consciousness_end = time.time()
        init_time_ms = (consciousness_end - consciousness_start) * 1000
        
        logger.info(f"✅ Radim Consciousness System ready (lazy init)")
        logger.info(f"   ⏱️  Import time: {init_time_ms:.1f}ms")
        logger.info(f"   💡 Engines will initialize on first use")
        
        # ===== Φ27 & VALUES READY (LAZY INIT) =====
        # Note: Phi27 and Values systems will initialize on first use
        # No eager initialization to keep startup fast
        logger.info("🌌 Φ27 Balance & Values System ready (lazy init)")
        
        # ===== STORY STUDIO INITIALIZATION =====
        logger.info("📖 Initializing Story Studio...")
        
        from routers import story_studio
        
        # Initialize Story Studio with dependencies
        story_studio.initialize_story_studio(
            gemini_integration=gemini_integration,
            memory_service=memory_service
        )
        
        logger.info("  ✅ Story Studio initialized:")
        logger.info("     • AI Engine: Gemini")
        logger.info("     • Templates: 6 categories")
        logger.info("     • TTS: Azure integration")
        logger.info("     • Memory: Personalization enabled")
        
        logger.info("🎉 Story Studio fully initialized!")
        
        # ===== CONVERSATION SESSION MANAGER INITIALIZATION =====
        logger.info("💬 Initializing Conversation Session Manager...")
        
        from services.session_manager import get_session_manager
        from api import gemini_routes
        
        # Initialize AI Rodina Kafánků - Multi-Agent System
        logger.info("🎭 Initializing AI Rodina Kafánků...")
        
        # 1. Initialize RedisManager
        redis_manager = RedisManager()
        await redis_manager.initialize_pool(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD'),
            db=int(os.getenv('REDIS_DB', 0))
        )
        logger.info("✅ RedisManager initialized")
        
        # 2. Initialize AgentRouter
        agent_router = AgentRouter(
            redis_manager=redis_manager,
            mcp_url=os.getenv('MCP_URL', 'http://localhost:3000')
        )
        logger.info("✅ AgentRouter initialized")
        
        # 3. Initialize AgentOrchestrator
        orchestrator = AgentOrchestrator(
            redis_manager=redis_manager,
            agent_router=agent_router,
            session_timeout_minutes=int(os.getenv('SESSION_TIMEOUT_MINUTES', 30))
        )
        logger.info("✅ AgentOrchestrator initialized")
        
        # 4. Start background health monitoring
        asyncio.create_task(
            orchestrator.start_health_monitoring(interval_seconds=300)
        )
        logger.info("✅ Health monitoring started")
        
        # 5. Start event listener
        asyncio.create_task(orchestrator.start_event_listener())
        logger.info("✅ Event listener started")
        
        logger.info("🎉 AI Rodina Kafánků ready!")
        
        # 6. Initialize MCP Task Orchestrator
        from services.radim_memory_service import RadimMemoryService
        from quantum_kafanek.quantum_core import QuantumKafanekBrain
        
        radim_memory_service = RadimMemoryService()
        quantum_brain = QuantumKafanekBrain()
        
        mcp_routes.init_mcp_dependencies(
            radim_memory=radim_memory_service,
            redis_manager=redis_manager,
            quantum_brain=quantum_brain,
            mcp_url=os.getenv('MCP_URL', 'http://localhost:3000')
        )
        logger.info("✅ MCP Task Orchestrator initialized")
        
        # 7. Initialize Agent Manager (AI Rodina Kafánků)
        logger.info("🎭 Initializing AI Rodina Kafánků agents...")
        agent_manager = AgentManager(
            radim_memory=radim_memory_service,
            quantum_brain=quantum_brain,
            redis_manager=redis_manager
        )
        logger.info("✅ AI Rodina Kafánků agents initialized")
        logger.info(f"   Available agents: {', '.join(agent_manager.agents.keys())}")
        
        # Initialize agent routes with agent manager
        agent_routes.init_agent_manager(agent_manager)
        
        # 8. Initialize Session Manager for Radim Chat
        logger.info("💬 Initializing Session Manager for Radim...")
        session_manager_instance = get_session_manager(redis_manager=redis_manager)
        gemini_routes.session_manager = session_manager_instance
        logger.info("✅ Session Manager initialized - Radim won't greet repeatedly!")
        
    except Exception as e:
        logger.error(f"❌ Error initializing services: {e}")
        raise

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "KAL-AIWU System",
        "version": "2.0.0",
        "status": "active",
        "features": [
            "Advanced Voice Processing",
            "Gemini AI Integration", 
            "Senior Optimization",
            "VS Code Integration",
            "Context Memory",
            "Analytics & Learning"
        ],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/api/windsurf/health")
async def windsurf_health_fallback():
    """Windsurf health check - simple fallback endpoint"""
    anthropic_configured = bool(os.getenv("ANTHROPIC_API_KEY"))
    return {
        "status": "healthy" if anthropic_configured else "degraded",
        "service": "Radim Brain",
        "version": "2.0.0",
        "claude_api_configured": anthropic_configured,
        "model": "claude-3-haiku-20240307",
        "message": "Radim Brain ready for Windsurf" if anthropic_configured else "Missing ANTHROPIC_API_KEY",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/dashboard", response_class=HTMLResponse)
async def azure_sql_dashboard():
    """Azure SQL Database Dashboard"""
    try:
        with open("azure_sql_dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dashboard file not found")

# ============================================================================
# V3 HEALTH CHECKS: Kubernetes-friendly liveness & readiness probes
# ============================================================================

@app.get("/health/live")
async def health_live():
    """Liveness probe - is server alive? (V3 enhancement)"""
    return {
        "status": "ok",
        "service": "kal-backend",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health/ready")
async def health_ready():
    """Readiness probe - is server ready? (V3 enhancement)"""
    checks = {
        "redis": bool(redis_client),
        "orchestrator": bool(orchestrator),
        "quantum_brain": True  # Always available
    }
    
    all_ready = checks["redis"] and checks["orchestrator"]
    
    return {
        "status": "ready" if all_ready else "degraded",
        "checks": checks,
        "optional_services": {
            "gemini": bool(gemini_integration),
            "voice": bool(voice_processor)
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================================
# LEGACY HEALTH CHECK: Comprehensive (keeps backward compatibility)
# ============================================================================

@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint for container orchestration"""
    health_status = {
        "status": "healthy",  # Will be set to degraded only if critical services fail
        "service": "KAL-AIWU Pan Kafánek System", 
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": 0,
        "checks": {
            "redis": {"status": "unknown", "latency_ms": 0},
            "aiwu": {"status": "unknown", "api_version": None},
            "database": {"status": "unknown", "connection": False},
            "voice_services": {"status": "unknown", "azure_speech": False},
            "memory_usage": {"status": "ok", "rss_mb": 0}
        },
        "senior_optimizations": {
            "voice_enabled": True,
            "slow_speech_rate": True,
            "large_font_mode": True,
            "simplified_responses": True
        }
    }
    
    try:
        import psutil
        import time
        start_time = time.time()
        
        # Memory usage
        memory_info = psutil.Process().memory_info()
        health_status["checks"]["memory_usage"]["rss_mb"] = round(memory_info.rss / 1024 / 1024, 2)
        
        # Check Redis/Fallback connection with latency
        if redis_adapter:
            redis_start = time.time()
            # Check if using Redis or fallback
            if redis_adapter.use_redis and redis_adapter.redis_client:
                try:
                    redis_ping = await redis_adapter.redis_client.ping()
                    redis_latency = round((time.time() - redis_start) * 1000, 2)
                    health_status["checks"]["redis"] = {
                        "status": "up" if redis_ping else "down",
                        "latency_ms": redis_latency,
                        "mode": "redis"
                    }
                except Exception as e:
                    health_status["checks"]["redis"] = {
                        "status": "error",
                        "latency_ms": 0,
                        "mode": "redis",
                        "error": str(e)
                    }
            else:
                # Using fallback system
                health_status["checks"]["redis"] = {
                    "status": "up",
                    "latency_ms": 0,
                    "mode": "fallback (SQLite + in-memory)"
                }
        else:
            health_status["checks"]["redis"]["status"] = "not_initialized"
        
        # Check Gemini AI
        health_status["checks"]["gemini"] = {
            "status": "configured" if gemini_integration and gemini_integration.gemini_api_key else "not_configured",
            "model": gemini_integration.gemini_model if gemini_integration else None,
            "note": "Google Gemini AI for voice processing"
        }
        
        # Check Azure Speech Services
        azure_speech_key = os.getenv('AZURE_SPEECH_KEY')
        health_status["checks"]["voice_services"] = {
            "status": "configured" if azure_speech_key else "not_configured",
            "azure_speech": bool(azure_speech_key)
        }
        
        # Check database connection (SQLite/Azure SQL via database.py)
        try:
            from database import test_connection
            success, message, details = test_connection()
            if success:
                health_status["checks"]["database"] = {
                    "status": "up",
                    "connection": True,
                    "type": details.get('database', 'unknown')
                }
            else:
                health_status["checks"]["database"] = {
                    "status": "down",
                    "connection": False,
                    "error": message
                }
        except Exception as e:
            health_status["checks"]["database"] = {"status": "down", "connection": False}
            logger.warning(f"Database health check failed: {e}")
        
        # Determine overall health (exclude deprecated services from failure count)
        failed_checks = [
            check_name for check_name, check in health_status["checks"].items() 
            if isinstance(check, dict) and check.get("status") in ["down", "error"]
            and check.get("status") != "deprecated"  # Ignore deprecated services
        ]
        
        if failed_checks:
            health_status["status"] = "degraded" if len(failed_checks) <= 2 else "unhealthy"
            health_status["failed_services"] = failed_checks
        
        # Pan Kafánek specific status
        health_status["pan_kafanek"] = {
            "voice_ready": bool(voice_processor),
            "context_memory": bool(context_manager),
            "senior_optimizer": bool(senior_optimizer),
            "conversation_ready": all([gemini_integration, voice_processor, context_manager])
        }
        
        # RADIM Manifest status
        try:
            from core.radim_constants import PHI, DELTA, R
            from core.radim_values import RADIM_VALUES
            
            health_status["radim_manifest"] = {
                "status": "active",
                "version": "1.0",
                "sacred_numbers": {
                    "phi": round(PHI, 6),
                    "delta": round(DELTA, 6),
                    "radim_number": round(R, 3)
                },
                "values_count": len(RADIM_VALUES),
                "motto": "Jsem postaven na zákonech, které řídí hvězdy i květiny."
            }
        except ImportError:
            health_status["radim_manifest"] = {
                "status": "not_available",
                "note": "RADIM core modules not found"
            }
        
        # AI Agents status
        if agent_manager:
            agent_stats = {}
            for agent_id in ['core', 'agent_teacher', 'agent_protector', 
                           'agent_storyteller', 'agent_senior', 'agent_coder']:
                agent = agent_manager.get_agent(agent_id)
                if agent:
                    agent_stats[agent_id] = {
                        "name": agent.agent_name,
                        "total_interactions": agent.total_interactions,
                        "successful": agent.successful_interactions,
                        "failed": agent.failed_interactions
                    }
            
            health_status["ai_agents"] = {
                "status": "active",
                "total_agents": len(agent_stats),
                "agents": agent_stats
            }
        else:
            health_status["ai_agents"] = {
                "status": "not_initialized"
            }
        
        # Consciousness System health check
        try:
            from consciousness import (
                get_consciousness_engine,
                get_timing_engine,
                get_crisis_detector,
                get_harmonic_visualizer
            )
            
            consciousness = get_consciousness_engine()
            timing = get_timing_engine()
            crisis = get_crisis_detector()
            visualizer = get_harmonic_visualizer()
            
            health_status["checks"]["consciousness"] = {
                "status": "up",
                "components": {
                    "consciousness_engine": {
                        "iteration": consciousness.current_state.iteration,
                        "harmony": round(consciousness.current_state.calculate_harmony(), 3),
                        "empathy": round(consciousness.current_state.empathy, 3),
                        "phi_direction": round(consciousness.current_state.phi_direction, 3)
                    },
                    "timing_engine": {
                        "base_wpm": timing.base_wpm,
                        "base_pause": timing.base_pause,
                        "operational": True
                    },
                    "crisis_detector": {
                        "crisis_points_count": len(crisis.crisis_points),
                        "lucas_nodes_count": len(crisis.lucas_resonance),
                        "initialized": True
                    },
                    "harmonic_visualizer": {
                        "phi": 1.618,
                        "initialized": True
                    }
                },
                "note": "Iterative consciousness n→n+1 system"
            }
            logger.debug("✅ Consciousness health check passed")
            
        except Exception as e:
            health_status["checks"]["consciousness"] = {
                "status": "error",
                "error": str(e),
                "note": "Consciousness system check failed"
            }
            logger.warning(f"⚠️ Consciousness health check failed: {e}")
        
        # Vrátit 200 i při degraded - systém může fungovat bez externích služeb (AIWU, PostgreSQL)
        status_code = 200 if health_status["status"] in ["healthy", "degraded"] else 503
        return JSONResponse(status_code=status_code, content=health_status)
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy", 
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.post("/kal/voice/command", response_model=VoiceResponse)
async def process_voice_command(
    request: VoiceCommandRequest,
    background_tasks: BackgroundTasks
):
    """
    Process voice command with AIWU AI
    Inspired by best-in-class voice assistants
    """
    try:
        logger.info(f"Processing voice command: {request.command[:50]}...")
        
        # Validate services
        if not voice_processor:
            raise HTTPException(status_code=503, detail="Voice processor not available")
        
        # Process the command
        response = await voice_processor.process_command(
            command=request.command,
            user_id=request.userId,
            context=request.context
        )
        
        # Background analytics update
        background_tasks.add_task(
            analytics_engine.log_interaction,
            request.userId,
            request.command,
            response
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error processing voice command: {e}")
        
        # Fallback response for seniors
        fallback_response = VoiceResponse(
            response="Promiňte, právě mám technické potíže. Zkuste to prosím za chvíli znovu.",
            intent="error",
            confidence=0.0,
            engine="fallback",
            priority="high",
            actions=[],
            conversationId=f"error_{datetime.utcnow().timestamp()}",
            context={
                "understood": False,
                "fallback": True,
                "error_type": "processing_error"
            }
        )
        
        return fallback_response

@app.post("/kal/voice/stream")
async def stream_voice_response(request: VoiceCommandRequest):
    """
    Stream real-time voice response (like ChatGPT voice mode)
    """
    async def generate_stream():
        try:
            async for chunk in voice_processor.process_command_stream(
                command=request.command,
                user_id=request.userId,
                context=request.context
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
                
        except Exception as e:
            error_chunk = {
                "type": "error",
                "content": "Došlo k chybě při zpracování",
                "error": str(e)
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={"Cache-Control": "no-cache"}
    )

@app.get("/kal/context/{user_id}")
async def get_user_context(user_id: str):
    """Get user conversation context"""
    if not context_manager:
        raise HTTPException(status_code=503, detail="Context manager not available")
    
    context = await context_manager.get_user_context(user_id)
    return {"success": True, "data": context}

@app.post("/kal/context/{user_id}/reset")
async def reset_user_context(user_id: str):
    """Reset user conversation context"""
    if not context_manager:
        raise HTTPException(status_code=503, detail="Context manager not available")
    
    await context_manager.reset_user_context(user_id)
    return {"success": True, "message": "Context reset"}

@app.get("/kal/analytics/{user_id}", response_model=AnalyticsResponse)
async def get_user_analytics(user_id: str, days: int = 30):
    """Get user interaction analytics"""
    if not analytics_engine:
        raise HTTPException(status_code=503, detail="Analytics engine not available")
    
    analytics = await analytics_engine.get_user_analytics(user_id, days)
    return analytics

@app.post("/kal/vscode/assist")
async def vscode_assistance(request: Dict[str, Any]):
    """
    VS Code integration endpoint
    Provides coding assistance for seniors
    """
    try:
        if not vscode_integration:
            raise HTTPException(status_code=503, detail="VS Code integration not available")
        
        assistance = await vscode_integration.provide_assistance(request)
        return {"success": True, "data": assistance}
        
    except Exception as e:
        logger.error(f"VS Code assistance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/kal/learning/feedback")
async def learning_feedback(
    user_id: str,
    interaction_id: str,
    feedback: Dict[str, Any],
    background_tasks: BackgroundTasks
):
    """
    Learning feedback endpoint
    Improves AI responses based on user feedback
    """
    background_tasks.add_task(
        analytics_engine.process_feedback,
        user_id,
        interaction_id,
        feedback
    )
    
    return {"success": True, "message": "Feedback received"}

@app.get("/kal/senior/preferences/{user_id}")
async def get_senior_preferences(user_id: str):
    """Get senior-specific preferences and optimizations"""
    if not senior_optimizer:
        raise HTTPException(status_code=503, detail="Senior optimizer not available")
    
    preferences = await senior_optimizer.get_user_preferences(user_id)
    return {"success": True, "data": preferences}

@app.post("/kal/senior/preferences/{user_id}")
async def update_senior_preferences(
    user_id: str, 
    preferences: Dict[str, Any]
):
    """Update senior-specific preferences"""
    if not senior_optimizer:
        raise HTTPException(status_code=503, detail="Senior optimizer not available")
    
    await senior_optimizer.update_user_preferences(user_id, preferences)
    return {"success": True, "message": "Preferences updated"}

# ============================================================================
# AI RODINA KAFÁNKŮ - AGENT MANAGEMENT ENDPOINTS
# ============================================================================

@app.post(
    "/kal/agent/route",
    response_model=RouteMessageResponse,
    tags=["AI Rodina Kafánků"],
    summary="Route message to appropriate agent"
)
async def route_message(request: RouteMessageRequest):
    """
    Routes user message to the most appropriate agent based on:
    - Intent analysis (MCP Dialog Manager)
    - Emergency detection
    - User profile (age, preferences)
    - Conversation context
    
    Priority:
    1. 🚨 Emergency → agent_protector
    2. 💊 Health → agent_protector
    3. 📚 Learning → agent_teacher
    4. 📖 Memory → agent_storyteller
    5. 👴 Senior (age 65+) → agent_senior
    6. 🧠 Default → core
    """
    try:
        if not agent_router:
            raise HTTPException(
                status_code=503,
                detail="Agent router not initialized"
            )
        
        logger.info(
            f"Routing message | User: {request.user_id} | "
            f"Message: {request.message[:50]}..."
        )
        
        # Route the message
        target_agent, routing_data = await agent_router.route_message(
            user_id=request.user_id,
            message=request.message,
            context=request.context
        )
        
        # Get agent info
        agent_info = AgentCapabilities.get_agent_info(target_agent)
        
        return RouteMessageResponse(
            success=True,
            target_agent=target_agent,
            agent_name=agent_info.get('name', 'Unknown Agent'),
            agent_emoji=agent_info.get('emoji', '🤖'),
            confidence=routing_data.get('confidence', 0.0),
            intent=routing_data.get('intent'),
            reasoning=routing_data.get('reasoning'),
            enriched_context=routing_data.get('enriched_context', {}),
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Routing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/kal/agent/session",
    response_model=SessionResponse,
    tags=["AI Rodina Kafánků"],
    summary="Create orchestrated session"
)
async def create_agent_session(request: CreateSessionRequest):
    """
    Creates new orchestrated session with:
    - Automatic agent routing
    - Session lifecycle management
    - Context preservation
    - Event broadcasting
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        logger.info(
            f"Creating session | User: {request.user_id} | "
            f"Message: {request.initial_message[:50]}..."
        )
        
        session_id = await orchestrator.create_orchestrated_session(
            user_id=request.user_id,
            initial_message=request.initial_message,
            metadata=request.metadata
        )
        
        # Get session data
        session_data = await orchestrator._get_session_data(session_id)
        
        if not session_data:
            raise HTTPException(
                status_code=500,
                detail="Session created but data not found"
            )
        
        # Get agent info
        agent_info = AgentCapabilities.get_agent_info(
            session_data['current_agent']
        )
        
        return SessionResponse(
            success=True,
            session_id=session_id,
            user_id=request.user_id,
            current_agent=session_data['current_agent'],
            agent_name=agent_info.get('name', 'Unknown Agent'),
            state=session_data['state'],
            created_at=session_data['created_at'],
            last_activity=session_data['last_activity'],
            activity_count=session_data.get('activity_count', 0),
            metadata=session_data.get('metadata', {})
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session creation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/kal/agent/handoff",
    response_model=HandoffResponse,
    tags=["AI Rodina Kafánků"],
    summary="Coordinate agent handoff"
)
async def coordinate_handoff(request: AgentHandoffRequest):
    """
    Smoothly transitions conversation between agents:
    - Preserves context
    - Logs transition
    - Broadcasts event
    - Updates session state
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        # Get current agent
        session_data = await orchestrator._get_session_data(
            request.session_id
        )
        if not session_data:
            raise HTTPException(
                status_code=404,
                detail=f"Session not found: {request.session_id}"
            )
        
        from_agent = session_data['current_agent']
        
        logger.info(
            f"Agent handoff | Session: {request.session_id} | "
            f"{from_agent} → {request.to_agent}"
        )
        
        result = await orchestrator.coordinate_agent_handoff(
            session_id=request.session_id,
            from_agent=from_agent,
            to_agent=request.to_agent,
            context=request.context,
            reason=request.reason
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Handoff failed')
            )
        
        return HandoffResponse(
            success=True,
            session_id=request.session_id,
            from_agent=from_agent,
            to_agent=request.to_agent,
            handoff_context=result['handoff_context'],
            timestamp=datetime.utcnow().isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Handoff failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/kal/agent/emergency",
    response_model=EmergencyResponse,
    tags=["AI Rodina Kafánků"],
    summary="Handle emergency situation"
)
async def handle_agent_emergency(request: EmergencyRequest):
    """
    🚨 PRIORITY ENDPOINT 🚨
    
    Immediately routes to agent_protector for:
    - Health issues
    - Falls/accidents
    - Urgent assistance needed
    
    Interrupts any ongoing conversation.
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        logger.critical(
            f"🚨 EMERGENCY | User: {request.user_id} | "
            f"Type: {request.emergency_type}"
        )
        
        emergency_data = {
            "message": request.message,
            "type": request.emergency_type,
            "severity": request.severity,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        result = await orchestrator.handle_emergency(
            user_id=request.user_id,
            session_id=request.session_id,
            emergency_data=emergency_data
        )
        
        if not result['success']:
            raise HTTPException(
                status_code=500,
                detail=result.get('error', 'Emergency handling failed')
            )
        
        return EmergencyResponse(
            success=True,
            session_id=result['session_id'],
            agent="agent_protector",
            emergency_acknowledged=True,
            timestamp=datetime.utcnow().isoformat(),
            message="Emergency acknowledged. Protector agent activated."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"Emergency handling failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/kal/agent/session/{session_id}",
    tags=["AI Rodina Kafánků"],
    summary="Terminate session"
)
async def terminate_agent_session(
    session_id: str,
    reason: str = "completed"
):
    """Gracefully terminates session and performs cleanup."""
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        logger.info(f"Terminating session: {session_id} | Reason: {reason}")
        
        await orchestrator.terminate_session(session_id, reason)
        
        return {
            "success": True,
            "session_id": session_id,
            "reason": reason,
            "terminated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Termination failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/kal/agent/health",
    response_model=AgentHealthResponse,
    tags=["AI Rodina Kafánků"],
    summary="Get agent health status"
)
async def get_agent_health_status():
    """
    Returns comprehensive health report:
    - Active sessions count
    - Agent-specific metrics
    - Detected issues (timeouts, overloads)
    - Overall system status
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        health_report = await orchestrator.check_agent_health()
        
        # Determine overall status
        issues_count = len(health_report.get('issues', []))
        if issues_count == 0:
            status = "healthy"
            overall_status = "healthy"
        elif issues_count < 5:
            status = "degraded"
            overall_status = "degraded"
        else:
            status = "critical"
            overall_status = "critical"
        
        return AgentHealthResponse(
            status=status,
            timestamp=health_report['timestamp'],
            total_active_sessions=health_report['total_active_sessions'],
            agents=health_report.get('agents', {}),
            issues=health_report.get('issues', []),
            redis_available=bool(redis_manager),
            overall_status=overall_status
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/kal/agent/stats/{user_id}",
    response_model=StatsResponse,
    tags=["AI Rodina Kafánků"],
    summary="Get user statistics"
)
async def get_agent_user_stats(user_id: str):
    """
    Returns user-specific statistics:
    - Total interactions
    - Agent usage distribution
    - Most frequently used agent
    - Routing statistics
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        stats = await orchestrator.get_session_stats(user_id)
        
        return StatsResponse(
            user_id=stats['user_id'],
            total_interactions=stats.get('total_interactions', 0),
            agent_distribution=stats.get('agent_distribution', {}),
            most_used_agent=stats.get('most_used_agent'),
            routing_stats=stats.get('routing_stats', {})
        )
        
    except Exception as e:
        logger.error(f"Stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/kal/agent/capabilities",
    response_model=AgentCapabilitiesResponse,
    tags=["AI Rodina Kafánků"],
    summary="Get all agent capabilities"
)
async def get_agent_capabilities():
    """
    Returns information about all available agents:
    - Agent names and IDs
    - Capabilities and specializations
    - Emoji identifiers
    """
    try:
        agents = AgentCapabilities.list_all_agents()
        
        return AgentCapabilitiesResponse(
            agents=agents,
            total_agents=len(agents),
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Capabilities retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/kal/agent/sessions/active",
    response_model=ActiveSessionsResponse,
    tags=["AI Rodina Kafánků"],
    summary="Get all active sessions"
)
async def get_active_agent_sessions():
    """
    Returns list of all currently active sessions:
    - Session IDs
    - User IDs
    - Current agents
    - Activity status
    """
    try:
        if not orchestrator:
            raise HTTPException(
                status_code=503,
                detail="Orchestrator not initialized"
            )
        
        active_sessions = await orchestrator.get_active_sessions()
        
        return ActiveSessionsResponse(
            success=True,
            total_active=len(active_sessions),
            sessions=active_sessions,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Active sessions retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# CLAUDE DESKTOP INTEGRATION
# ============================================================================

@app.post(
    "/kal/agent/claude",
    response_model=ClaudeAgentResponse,
    tags=["Claude Desktop"],
    summary="Claude Desktop unified endpoint"
)
async def claude_agent_endpoint(request: ClaudeAgentRequest):
    """
    Unified endpoint for Claude Desktop to interact with Radim Brain.
    Provides structured interface for consciousness calculations, agent orchestration,
    and quantum math operations.
    
    Supported tasks:
    - analyze: Consciousness analysis, phi calculations
    - calculate: Quantum math, Fibonacci, golden ratio
    - synthesize: Voice synthesis, TTS generation
    - orchestrate: Multi-agent task coordination
    """
    start_time = time.time()
    
    try:
        task = request.task
        input_data = request.input
        mode = request.mode
        user_id = request.user_id
        
        result = {}
        thinking = {}
        consciousness_state = None
        next_actions = []
        
        # Task routing
        if task == "calculate":
            # Consciousness & Quantum Math calculations
            if "phi" in str(input_data).lower() or "golden" in str(input_data).lower():
                value = input_data.get("value", 100)
                phi = 1.618033988749895
                
                thinking = {
                    "analysis": f"Calculating golden ratio (φ) for value {value}",
                    "formula": "φ = (1 + √5) / 2 ≈ 1.618",
                    "reasoning": "Using Radim's consciousness mathematics"
                }
                
                result = {
                    "phi": phi,
                    "calculation": value * phi,
                    "fibonacci_ratio": True,
                    "consciousness_aligned": True
                }
                
                next_actions = ["store_in_memory", "visualize_result"]
                
            elif "fibonacci" in str(input_data).lower():
                n = input_data.get("n", 10)
                fib_sequence = []
                a, b = 0, 1
                for _ in range(n):
                    fib_sequence.append(a)
                    a, b = b, a + b
                
                thinking = {
                    "analysis": f"Generating Fibonacci sequence of length {n}",
                    "formula": "F(n) = F(n-1) + F(n-2)",
                    "reasoning": "Spiral of growth - one of Radim's three life spirals"
                }
                
                result = {
                    "sequence": fib_sequence,
                    "length": n,
                    "ratios": [fib_sequence[i+1]/fib_sequence[i] if fib_sequence[i] != 0 else 0 
                              for i in range(len(fib_sequence)-1)]
                }
                
                next_actions = ["analyze_ratios", "compare_to_phi"]
        
        elif task == "analyze":
            # Consciousness state analysis
            query = input_data.get("query", "")
            
            thinking = {
                "analysis": f"Analyzing consciousness request: {query}",
                "approach": "Using Radim's 12 values framework",
                "reasoning": "Mapping query to Janečkův Rámec (12 Values)"
            }
            
            # Simple consciousness metrics
            consciousness_state = {
                "alpha": 1.618,  # φ
                "delta": 2.414,  # Silver ratio
                "R": 3.905,      # RADIM constant
                "harmony_level": "balanced",
                "active_values": ["MYŠLENKA", "CÍTĚNÍ", "RESPEKT"]
            }
            
            result = {
                "consciousness_analysis": consciousness_state,
                "recommendation": "Query aligned with Radim's core values",
                "confidence": 0.95
            }
            
            next_actions = ["deepen_analysis", "engage_agents"]
        
        elif task == "orchestrate":
            # Multi-agent orchestration
            objective = input_data.get("objective", "")
            
            thinking = {
                "analysis": f"Orchestrating agents for: {objective}",
                "approach": "AI Rodina Kafánků coordination",
                "reasoning": "Using 5-agent system for complex tasks"
            }
            
            result = {
                "agents_activated": ["supervisor", "orchestrator", "executor"],
                "task_breakdown": ["analyze", "plan", "execute", "verify"],
                "estimated_completion": "2-5 minutes"
            }
            
            next_actions = ["monitor_progress", "collect_results"]
        
        elif task == "synthesize":
            # Voice synthesis (simplified)
            text = input_data.get("text", "")
            
            thinking = {
                "analysis": "Preparing voice synthesis",
                "approach": "Using ElevenLabs via Heroku proxy",
                "reasoning": "Radim's voice with consciousness timing (φ pauses)"
            }
            
            result = {
                "text": text,
                "voice_id": "radim_consciousness",
                "timing": {
                    "short_pause": 1.0,
                    "medium_pause": 1.618,  # φ
                    "long_pause": 2.618     # φ²
                },
                "ready": True
            }
            
            next_actions = ["generate_audio", "apply_phi_timing"]
        
        else:
            # Default/unknown task
            thinking = {
                "analysis": f"Unknown task type: {task}",
                "recommendation": "Use: calculate, analyze, orchestrate, or synthesize"
            }
            result = {
                "error": "Unknown task type",
                "supported_tasks": ["calculate", "analyze", "orchestrate", "synthesize"]
            }
        
        processing_time = time.time() - start_time
        
        return ClaudeAgentResponse(
            status="success" if result.get("error") is None else "error",
            task=task,
            thinking=thinking if mode == "thinking" else None,
            result=result,
            next_actions=next_actions,
            consciousness_state=consciousness_state,
            processing_time=processing_time
        )
        
    except Exception as e:
        logger.error(f"Claude agent endpoint error: {e}")
        processing_time = time.time() - start_time
        
        return ClaudeAgentResponse(
            status="error",
            task=request.task,
            thinking={"error_analysis": str(e)},
            result={"error": str(e)},
            processing_time=processing_time
        )


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/kal/ws/{user_id}")
async def websocket_endpoint(websocket, user_id: str):
    """
    WebSocket endpoint for real-time communication
    Like modern chat applications
    """
    await websocket.accept()
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Process voice command
            if message.get("type") == "voice_command":
                response = await voice_processor.process_command(
                    command=message["command"],
                    user_id=user_id,
                    context=message.get("context", {})
                )
                
                await websocket.send_text(json.dumps({
                    "type": "voice_response",
                    "data": response.dict()
                }))
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("KAL_HOST", "0.0.0.0"),
        port=int(os.getenv("KAL_PORT", 8002)),
        reload=bool(os.getenv("KAL_DEBUG", False)),
        workers=int(os.getenv("WORKERS", 1))
    )
