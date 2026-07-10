"""Router for per-thread chat preferences (favorite, selected model)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from capybara.api.dependencies import get_chat_pref_service, get_current_user
from capybara.api.schemas import ChatPrefOut, ChatPrefUpsert
from capybara.db.models import User
from capybara.services.chat_pref_service import ChatPrefService

router = APIRouter(prefix="/chat-prefs", tags=["chat-prefs"])


@router.get("")
async def list_chat_prefs(
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatPrefService, Depends(get_chat_pref_service)],
) -> list[ChatPrefOut]:
    """Return the current user's chat prefs, to merge into the Chainlit thread list."""
    prefs = await service.list_prefs(user.id)
    return [ChatPrefOut.model_validate(p) for p in prefs]


@router.put("/{thread_id}")
async def upsert_chat_pref(
    thread_id: UUID,
    body: ChatPrefUpsert,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatPrefService, Depends(get_chat_pref_service)],
) -> ChatPrefOut:
    """Set a thread's favorite flag and selected model for the current user."""
    pref = await service.upsert(user.id, thread_id, is_favorite=body.is_favorite, model=body.model)
    return ChatPrefOut.model_validate(pref)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_pref(
    thread_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatPrefService, Depends(get_chat_pref_service)],
) -> None:
    """Delete a thread's pref (called when its chat is deleted)."""
    await service.delete(user.id, thread_id)
