"""Router for memory (facts) CRUD and settings."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.errors import EmbeddingModelUnavailableError, ModelProviderError
from capybara.api.dependencies import get_current_user, get_memory_service, get_owned_fact
from capybara.api.schemas import FactCreate, FactOut, FactUpdate
from capybara.db.models import Fact, User
from capybara.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


def _raise_for_embed_error(exc: EmbeddingModelUnavailableError | ModelProviderError) -> NoReturn:
    """Translate an embedding failure into an actionable HTTP error.

    A missing embedding model is a fixable configuration issue (503 + how to fix); a
    provider that cannot be reached is an upstream outage (502).
    """
    if isinstance(exc, EmbeddingModelUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/facts", response_model=list[FactOut])
async def list_facts(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> list[FactOut]:
    """Return the current user's facts, newest first."""
    rows = await service.list_facts(user.id)
    return [FactOut.model_validate(f) for f in rows]


@router.post("/facts", status_code=status.HTTP_201_CREATED, response_model=FactOut)
async def create_fact(
    payload: FactCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> FactOut:
    """Embed and store a new manual fact for the current user."""
    try:
        fact = await service.add_fact(user.id, payload.content, payload.category)
    except (EmbeddingModelUnavailableError, ModelProviderError) as exc:
        _raise_for_embed_error(exc)
    return FactOut.model_validate(fact)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    payload: FactUpdate,
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> FactOut:
    """Update a fact's content and/or category (404 if not owned); re-embeds on content change."""
    try:
        updated = await service.update_fact(
            user.id, fact.id, content=payload.content, category=payload.category
        )
    except (EmbeddingModelUnavailableError, ModelProviderError) as exc:
        _raise_for_embed_error(exc)
    if updated is None:
        # The fact vanished between the ownership check and the service's own re-read
        # (e.g. a concurrent delete) — surface the same 404 as get_owned_fact would.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
    return FactOut.model_validate(updated)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    """Delete a fact owned by the current user (404 if not owned)."""
    await service.delete_fact(user.id, fact.id)
