"""Router for memory (facts) CRUD."""

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from capybara.agent.errors import EmbeddingModelUnavailableError, ModelProviderError
from capybara.api.dependencies import CurrentUser, Registry, Sessionmaker
from capybara.api.schemas import FactCreate, FactOut, FactUpdate
from capybara.commands.fact.create import CreateFact
from capybara.commands.fact.delete import DeleteFact
from capybara.commands.fact.list import ListFacts
from capybara.commands.fact.update import UpdateFact

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
async def list_facts(user: CurrentUser, sessionmaker: Sessionmaker) -> list[FactOut]:
    """Return the current user's facts, newest first."""
    rows = await ListFacts(sessionmaker, user_id=user.id).execute()
    return [FactOut.model_validate(f) for f in rows]


@router.post("/facts", status_code=status.HTTP_201_CREATED, response_model=FactOut)
async def create_fact(
    payload: FactCreate,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
    registry: Registry,
) -> FactOut:
    """Embed and store a new manual fact for the current user."""
    command = CreateFact(
        sessionmaker,
        registry,
        user_id=user.id,
        content=payload.content,
        category=payload.category,
    )
    try:
        fact = await command.execute()
    except (EmbeddingModelUnavailableError, ModelProviderError) as exc:
        _raise_for_embed_error(exc)
    return FactOut.model_validate(fact)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    fact_id: UUID,
    payload: FactUpdate,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
    registry: Registry,
) -> FactOut:
    """Update a fact's content and/or category (404 if not owned); re-embeds new content."""
    command = UpdateFact(sessionmaker, registry, user_id=user.id, fact_id=fact_id, patch=payload)
    try:
        updated = await command.execute()
    except (EmbeddingModelUnavailableError, ModelProviderError) as exc:
        _raise_for_embed_error(exc)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
    return FactOut.model_validate(updated)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact_id: UUID,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> None:
    """Delete a fact owned by the current user (404 if not owned)."""
    if not await DeleteFact(sessionmaker, user_id=user.id, fact_id=fact_id).execute():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fact not found")
