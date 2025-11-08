from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import anthropic
import os

router = APIRouter()

# Initialize Anthropic client
api_key = os.getenv("CLAUDE_API_KEY")
if not api_key:
    raise ValueError("CLAUDE_API_KEY environment variable is not set")

client = anthropic.Anthropic(api_key=api_key)


class WindsurfRequest(BaseModel):
    """Request model for Windsurf proxy endpoint"""
    prompt: str


class WindsurfResponse(BaseModel):
    """Response model for Windsurf proxy endpoint"""
    response: str


@router.post("/windsurf", response_model=WindsurfResponse)
async def windsurf_proxy(request_data: WindsurfRequest):
    """
    Proxy endpoint for Windsurf IDE integration with Claude API.

    Forwards user prompts to Claude and returns the generated response.

    Args:
        request_data: Contains the user prompt

    Returns:
        WindsurfResponse: Contains the Claude-generated response

    Raises:
        HTTPException: If the API request fails
    """
    if not request_data.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[{"role": "user", "content": request_data.prompt}],
        )
        return {"response": response.content[0].text}
    except anthropic.APIError as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {str(e)}")
