"""
🔒 TTS Proxy Routes - Bezpečné proxy pro ElevenLabs a Azure TTS
Frontend volá tyto endpointy místo přímého volání external APIs
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tts-proxy"])

# ============================================================================
# REQUEST MODELS
# ============================================================================

class AzureTTSRequest(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    voice: Optional[str] = Field("cs-CZ-AntoninNeural", description="Azure voice name")
    rate: Optional[str] = Field("0.85", description="Speech rate")
    pitch: Optional[str] = Field("+0Hz", description="Pitch adjustment")

# ============================================================================
# CORS PREFLIGHT HANDLERS (OPTIONS)
# ============================================================================

@router.options("/azure/tts")
async def azure_tts_preflight():
    """
    🔓 CORS Preflight for Azure TTS
    
    Handles OPTIONS requests for CORS preflight
    """
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "https://app.radimcare.cz",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
        }
    )

@router.options("/elevenlabs/tts")
async def elevenlabs_tts_preflight():
    """
    🔓 CORS Preflight for ElevenLabs TTS
    
    Handles OPTIONS requests for CORS preflight
    """
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "https://app.radimcare.cz",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "3600",
        }
    )

# ============================================================================
# AZURE TTS PROXY ENDPOINT
# ============================================================================

@router.post("/azure/tts")
async def azure_tts_proxy(request: AzureTTSRequest):
    """
    🎤 Azure TTS Proxy
    
    Přeposílá požadavek na Azure Cognitive Services TTS s API klíčem ze serveru
    """
    try:
        import aiohttp
        
        api_key = os.getenv(
            'AZURE_TTS_KEY',
            'JikrPUH2HODm8u5cj4ozmOGWCgQd2XeCasMt9kW09lc0mM59PwYyJQQJ99BIAC5RqLJXJ3w3AAAYACOGgKKC'
        )
        region = os.getenv('AZURE_TTS_REGION', 'northeurope')  # Heroku DNS fix
        
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        
        headers = {
            'Ocp-Apim-Subscription-Key': api_key,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-128kbitrate-mono-mp3'
        }
        
        # Build SSML
        ssml = f"""<speak version='1.0' xml:lang='cs-CZ'>
            <voice name='{request.voice}'>
                <prosody rate='{request.rate}' pitch='{request.pitch}'>
                    {request.text}
                </prosody>
            </voice>
        </speak>"""
        
        # Heroku DNS fix: Použít timeout a retry
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, data=ssml.encode('utf-8')) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Azure TTS API error: {response.status} - {error_text}")
                    raise HTTPException(status_code=response.status, detail=f"Azure TTS API error: {error_text}")
                
                audio_data = await response.read()
                
                # Return audio stream directly
                return Response(
                    content=audio_data,
                    media_type='audio/mpeg',
                    headers={
                        'Content-Type': 'audio/mpeg',
                        'Accept-Ranges': 'bytes',
                        'Access-Control-Allow-Origin': '*',
                        'X-Voice-Name': request.voice,
                        'X-Voice-Rate': request.rate,
                        'X-Voice-Pitch': request.pitch,
                        'Cache-Control': 'no-cache'
                    }
                )
                
    except Exception as e:
        logger.error(f"Azure TTS proxy error: {e}")
        raise HTTPException(status_code=500, detail=f"Azure TTS synthesis failed: {str(e)}")


# ============================================================================
# HEALTH CHECK
# ============================================================================

@router.get("/tts/health")
async def tts_proxy_health():
    """Health check pro TTS proxy endpoints"""
    return {
        'status': 'healthy',
        'service': 'TTS Proxy (Azure)',
        'endpoints': {
            'azure': '/api/azure/tts'
        }
    }
