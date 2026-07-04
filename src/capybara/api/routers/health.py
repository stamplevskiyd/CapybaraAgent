"""Router for the /health endpoint."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from capybara.api.dependencies import get_settings_dep
from capybara.config import Settings

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
async def health(settings: Annotated[Settings, Depends(get_settings_dep)]) -> dict[str, str]:
    """Return API status and Ollama availability."""
    up = await ollama_is_up(settings.ollama_base_url)
    return {"status": "ok", "ollama": "up" if up else "down"}
