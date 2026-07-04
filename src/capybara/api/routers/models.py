"""Router for listing available LLM models."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.base import BaseAgent, ModelProviderError
from capybara.api.dependencies import get_agent, get_current_user
from capybara.api.schemas import ModelsOut
from capybara.db.models import User

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsOut)
async def list_models(
    _user: Annotated[User, Depends(get_current_user)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ModelsOut:
    """Return the models currently available from the provider (Ollama)."""
    try:
        names = await agent.list_models()
    except ModelProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ModelsOut(provider="ollama", models=names)
