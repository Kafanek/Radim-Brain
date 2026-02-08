"""
🎭 RADIM ORCHESTRATOR ROUTES
Claude jako orchestrátor celého systému Radim Brain

Endpoint: /api/orchestrator/*
Version: 2.0.0
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio
import aiohttp
import os
import json
import logging
import time

logger = logging.getLogger(__name__)

router = APIRouter()

# ============================================================================
# KONFIGURACE
# ============================================================================
HEROKU_URL = os.getenv(
    'HEROKU_URL', 
    'https://radim-brain-2025-be1cd52b04dc.herokuapp.com'
)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# ============================================================================
# MODELY
# ============================================================================

class OrchestrateRequest(BaseModel):
    """Request pro orchestraci"""
    action: str = Field(..., description="Akce: analyze, fix, deploy, monitor, chat, health_all")
    target: Optional[str] = Field(None, description="Cílový systém: backend, wordpress, frontend, all")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict)
    user_id: Optional[str] = Field(default="claude-desktop")
    priority: Optional[str] = Field(default="normal", description="normal, high, critical")


class OrchestrateResponse(BaseModel):
    """Response z orchestrace"""
    success: bool
    action: str
    result: Dict[str, Any]
    thinking: Optional[Dict[str, Any]] = None
    next_actions: List[str] = []
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    processing_time_ms: float = 0


# ============================================================================
# HELPER FUNKCE
# ============================================================================

async def fetch_url(url: str, method: str = "GET", data: dict = None, timeout: int = 15) -> dict:
    """Asynchronní HTTP request s timeoutem"""
    try:
        async with aiohttp.ClientSession() as session:
            kwargs = {"timeout": aiohttp.ClientTimeout(total=timeout)}
            if data:
                kwargs["json"] = data
            
            async with getattr(session, method.lower())(url, **kwargs) as resp:
                if resp.content_type == 'application/json':
                    return {"status": resp.status, "data": await resp.json()}
                else:
                    return {"status": resp.status, "data": await resp.text()}
    except asyncio.TimeoutError:
        return {"status": 0, "error": "timeout"}
    except Exception as e:
        return {"status": 0, "error": str(e)}


async def check_all_systems() -> Dict[str, Any]:
    """Kontrola všech systémů najednou"""
    checks = {}
    
    # Paralelní kontrola
    tasks = {
        "heroku_backend": fetch_url(f"{HEROKU_URL}/health"),
        "heroku_consciousness": fetch_url(f"{HEROKU_URL}/api/consciousness/state"),
        "heroku_agents": fetch_url(f"{HEROKU_URL}/kal/agent/health"),
    }
    
    # WordPress checks (pokud je nakonfigurován)
    wp_url = os.getenv('WP_URL')
    if wp_url:
        tasks["wordpress"] = fetch_url(f"{wp_url}/wp-json/kafanek-brain/v1/health")
    
    results = await asyncio.gather(
        *[tasks[key] for key in tasks],
        return_exceptions=True
    )
    
    for i, key in enumerate(tasks):
        if isinstance(results[i], Exception):
            checks[key] = {"status": "error", "error": str(results[i])}
        else:
            result = results[i]
            checks[key] = {
                "status": "ok" if result.get("status") == 200 else "error",
                "http_status": result.get("status"),
                "data": result.get("data") if result.get("status") == 200 else None,
                "error": result.get("error")
            }
    
    # Celkový status
    ok_count = sum(1 for v in checks.values() if v["status"] == "ok")
    total = len(checks)
    
    return {
        "systems": checks,
        "summary": {
            "total": total,
            "healthy": ok_count,
            "failed": total - ok_count,
            "overall": "healthy" if ok_count == total else "degraded" if ok_count > 0 else "critical"
        }
    }


async def get_heroku_logs(lines: int = 50) -> Dict[str, Any]:
    """Získání logů z Heroku (pokud je API key)"""
    heroku_api_key = os.getenv('HEROKU_API_KEY')
    app_name = os.getenv('HEROKU_APP_NAME', 'radim-brain-2025')
    
    if not heroku_api_key:
        return {
            "available": False,
            "message": "HEROKU_API_KEY not set - cannot fetch logs directly",
            "alternative": "Use 'heroku logs --tail' from CLI"
        }
    
    try:
        # Heroku Log Drains API
        result = await fetch_url(
            f"https://api.heroku.com/apps/{app_name}/log-sessions",
            method="POST",
            data={"lines": lines, "tail": False},
            timeout=10
        )
        
        if result.get("status") == 201:
            log_url = result["data"].get("logplex_url")
            if log_url:
                log_content = await fetch_url(log_url, timeout=10)
                return {"available": True, "logs": log_content.get("data", "")}
        
        return {"available": False, "error": result.get("error", "Unknown error")}
        
    except Exception as e:
        return {"available": False, "error": str(e)}


async def analyze_with_ai(context: str, question: str) -> str:
    """Analýza pomocí Gemini AI"""
    if not GEMINI_API_KEY:
        return "AI analýza nedostupná (chybí GEMINI_API_KEY)"
    
    prompt = f"""Jsi Radim Brain orchestrátor. Analyzuj následující data a odpověz stručně česky.

Kontext:
{context}

Otázka: {question}

Odpověz strukturovaně:
1. Stav systému
2. Nalezené problémy
3. Doporučené akce
"""
    
    try:
        result = await fetch_url(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}",
            method="POST",
            data={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500}
            },
            timeout=30
        )
        
        if result.get("status") == 200:
            data = result["data"]
            if "candidates" in data:
                return data["candidates"][0]["content"]["parts"][0]["text"]
        
        return f"AI analýza selhala: {result.get('error', 'unknown')}"
        
    except Exception as e:
        return f"AI analýza error: {e}"


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/orchestrator/orchestrate", response_model=OrchestrateResponse)
async def orchestrate(request: OrchestrateRequest):
    """
    🎭 Hlavní orchestrační endpoint
    
    Akce:
    - health_all: Kontrola všech systémů
    - analyze: AI analýza stavu/problému
    - monitor: Real-time monitoring
    - chat: Orchestrovaný chat přes agenty
    - fix: Návrh opravy (analyze + suggest)
    - deploy: Deployment info
    """
    start_time = time.time()
    action = request.action
    result = {}
    thinking = {}
    next_actions = []
    
    try:
        # =============================================
        # HEALTH ALL - Kontrola všech systémů
        # =============================================
        if action == "health_all":
            health_data = await check_all_systems()
            
            thinking = {
                "approach": "Paralelní kontrola všech komponent",
                "checked": list(health_data["systems"].keys())
            }
            
            result = health_data
            
            if health_data["summary"]["failed"] > 0:
                next_actions = ["analyze", "fix"]
            else:
                next_actions = ["monitor"]
        
        # =============================================
        # ANALYZE - AI analýza
        # =============================================
        elif action == "analyze":
            target = request.target or "all"
            
            # Nejdřív získáme data
            health_data = await check_all_systems()
            
            # AI analýza
            analysis = await analyze_with_ai(
                context=json.dumps(health_data, indent=2, default=str),
                question=request.params.get("question", f"Analyzuj stav systému {target}")
            )
            
            thinking = {
                "approach": "Health check → AI analýza → doporučení",
                "target": target,
                "ai_used": "gemini-2.0-flash-exp"
            }
            
            result = {
                "health": health_data["summary"],
                "analysis": analysis,
                "target": target
            }
            
            next_actions = ["fix", "monitor", "deploy"]
        
        # =============================================
        # MONITOR - Real-time monitoring
        # =============================================
        elif action == "monitor":
            # Získáme metriky
            health = await check_all_systems()
            
            # Agent stats
            agents_result = await fetch_url(f"{HEROKU_URL}/kal/agent/health")
            
            # Consciousness state
            consciousness_result = await fetch_url(f"{HEROKU_URL}/api/consciousness/state")
            
            thinking = {
                "approach": "Agregace metrik ze všech systémů",
                "sources": ["health", "agents", "consciousness"]
            }
            
            result = {
                "health": health["summary"],
                "agents": agents_result.get("data") if agents_result.get("status") == 200 else "unavailable",
                "consciousness": consciousness_result.get("data") if consciousness_result.get("status") == 200 else "unavailable",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            next_actions = ["analyze", "health_all"]
        
        # =============================================
        # CHAT - Orchestrovaný chat
        # =============================================
        elif action == "chat":
            message = request.params.get("message", "")
            mode = request.params.get("mode", "senior")
            
            if not message:
                raise HTTPException(status_code=400, detail="Parametr 'message' je povinný")
            
            # Pošleme na Radim chat endpoint
            chat_result = await fetch_url(
                f"{HEROKU_URL}/api/radim/chat",
                method="POST",
                data={
                    "message": message,
                    "user_id": request.user_id,
                    "mode": mode
                }
            )
            
            thinking = {
                "approach": f"Chat přes Radim orchestrátor (mode: {mode})",
                "backend": HEROKU_URL
            }
            
            if chat_result.get("status") == 200:
                result = chat_result["data"]
            else:
                result = {"error": chat_result.get("error", "Chat failed"), "fallback": True}
            
            next_actions = ["chat"]  # Pokračování konverzace
        
        # =============================================
        # FIX - Návrh opravy
        # =============================================
        elif action == "fix":
            target = request.target or "all"
            problem = request.params.get("problem", "")
            
            # Získáme stav
            health_data = await check_all_systems()
            
            # AI navrhne opravu
            fix_analysis = await analyze_with_ai(
                context=json.dumps({
                    "health": health_data,
                    "problem": problem,
                    "target": target
                }, indent=2, default=str),
                question=f"Navrhni konkrétní opravu pro: {problem or 'všechny nalezené problémy'}"
            )
            
            thinking = {
                "approach": "Diagnóza → AI analýza → návrh opravy",
                "target": target,
                "problem": problem
            }
            
            result = {
                "health": health_data["summary"],
                "fix_suggestion": fix_analysis,
                "target": target
            }
            
            next_actions = ["deploy", "health_all"]
        
        # =============================================
        # LOGS - Získání logů
        # =============================================
        elif action == "logs":
            lines = request.params.get("lines", 50)
            logs = await get_heroku_logs(lines)
            
            thinking = {
                "approach": "Heroku Log Session API",
                "lines_requested": lines
            }
            
            result = logs
            next_actions = ["analyze"]
        
        # =============================================
        # UNKNOWN ACTION
        # =============================================
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"Neznámá akce: {action}. Podporované: health_all, analyze, monitor, chat, fix, logs"
            )
        
        processing_time = (time.time() - start_time) * 1000
        
        return OrchestrateResponse(
            success=True,
            action=action,
            result=result,
            thinking=thinking,
            next_actions=next_actions,
            processing_time_ms=round(processing_time, 2)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Orchestrate error: {e}")
        processing_time = (time.time() - start_time) * 1000
        return OrchestrateResponse(
            success=False,
            action=action,
            result={"error": str(e)},
            processing_time_ms=round(processing_time, 2)
        )


@router.get("/orchestrator/health")
async def orchestrator_health():
    """Quick health check orchestrátoru"""
    return {
        "status": "healthy",
        "service": "Radim Orchestrator",
        "version": "2.0.0",
        "capabilities": ["health_all", "analyze", "monitor", "chat", "fix", "logs"],
        "heroku_url": HEROKU_URL,
        "ai_available": bool(GEMINI_API_KEY),
        "claude_available": bool(ANTHROPIC_API_KEY),
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/orchestrator/systems")
async def get_systems_status():
    """Rychlý přehled všech systémů"""
    return await check_all_systems()
