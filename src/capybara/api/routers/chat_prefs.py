"""Router for per-thread chat preferences (favorite, selected model)."""

from uuid import UUID

from fastapi import APIRouter, status

from capybara.api.dependencies import CurrentUser, Sessionmaker
from capybara.api.schemas import ChatPrefOut, ChatPrefUpsert
from capybara.commands.chat_pref.delete import DeleteChatPref
from capybara.commands.chat_pref.list import ListChatPrefs
from capybara.commands.chat_pref.upsert import UpsertChatPref

router = APIRouter(prefix="/chat-prefs", tags=["chat-prefs"])


@router.get("")
async def list_chat_prefs(user: CurrentUser, sessionmaker: Sessionmaker) -> list[ChatPrefOut]:
    """Return the current user's chat prefs, to merge into the Chainlit thread list."""
    prefs = await ListChatPrefs(sessionmaker, user_id=user.id).execute()
    return [ChatPrefOut.model_validate(p) for p in prefs]


@router.put("/{thread_id}")
async def upsert_chat_pref(
    thread_id: UUID,
    body: ChatPrefUpsert,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> ChatPrefOut:
    """Set a thread's favorite flag and selected model for the current user."""
    pref = await UpsertChatPref(
        sessionmaker,
        user_id=user.id,
        thread_id=thread_id,
        is_favorite=body.is_favorite,
        model=body.model,
        mode=body.mode,
    ).execute()
    return ChatPrefOut.model_validate(pref)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_pref(
    thread_id: UUID,
    user: CurrentUser,
    sessionmaker: Sessionmaker,
) -> None:
    """Delete a thread's pref (called when its chat is deleted)."""
    await DeleteChatPref(sessionmaker, user_id=user.id, thread_id=thread_id).execute()
