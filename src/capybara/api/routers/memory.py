"""Router for memory (facts) CRUD and settings."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from capybara.api.dependencies import get_current_user, get_memory_service, get_owned_fact
from capybara.api.schemas import (
    FactCreate,
    FactOut,
    FactUpdate,
    MemorySettingsOut,
    MemorySettingsUpdate,
)
from capybara.db.models import Fact, User
from capybara.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


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
    fact = await service.add_fact(user.id, payload.content, payload.category)
    return FactOut.model_validate(fact)


@router.patch("/facts/{fact_id}", response_model=FactOut)
async def update_fact(
    payload: FactUpdate,
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> FactOut:
    """Update a fact's content and/or category (404 if not owned); re-embeds on content change."""
    updated = await service.update_fact(
        user.id, fact.id, content=payload.content, category=payload.category
    )
    assert updated is not None  # get_owned_fact already verified ownership
    return FactOut.model_validate(updated)


@router.delete("/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(
    fact: Annotated[Fact, Depends(get_owned_fact)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> None:
    """Delete a fact owned by the current user (404 if not owned)."""
    await service.delete_fact(user.id, fact.id)


@router.get("/settings", response_model=MemorySettingsOut)
async def get_memory_settings(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemorySettingsOut:
    """Return the current user's auto-capture toggle."""
    return MemorySettingsOut(auto_capture=await service.get_auto_capture(user.id))


@router.patch("/settings", response_model=MemorySettingsOut)
async def update_memory_settings(
    payload: MemorySettingsUpdate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemorySettingsOut:
    """Update the current user's auto-capture toggle."""
    value = await service.set_auto_capture(user.id, payload.auto_capture)
    return MemorySettingsOut(auto_capture=value)
