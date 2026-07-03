"""Router for the /health endpoint."""

import httpx
from fastapi import APIRouter, Request

router = APIRouter()


async def ollama_is_up(base_url: str) -> bool:
    """Return True if the Ollama server at base_url responds with HTTP 200."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(base_url)
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Return API status and Ollama availability."""
    base_url: str = request.app.state.settings.ollama_base_url
    up = await ollama_is_up(base_url)
    return {"status": "ok", "ollama": "up" if up else "down"}
