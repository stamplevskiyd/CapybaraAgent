"""Router for chat and message endpoints."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from capybara.agent.errors import ModelProviderError, ModelUnavailableError
from capybara.agent.model_registry import ModelRegistry
from capybara.api.dependencies import (
    get_chat_repo,
    get_current_user,
    get_message_repo,
    get_model_registry,
    get_owned_chat,
)
from capybara.api.schemas import (
    ChatCreate,
    ChatDetailOut,
    ChatOut,
    ChatUpdate,
    MessageOut,
)
from capybara.db.models import Chat, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> ChatOut:
    """Create a new chat for the current user, optionally with a validated model."""
    if payload.model is not None:
        try:
            await registry.ensure_available(payload.model)
        except (ModelUnavailableError, ModelProviderError) as exc:
            _raise_for_model_error(exc)
    chat = await chats.create(user.id, payload.title, payload.model)
    return ChatOut.model_validate(chat)


@router.get("", response_model=list[ChatOut])
async def list_chats(
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> list[ChatOut]:
    """Return all chats for the current user, ordered by most recently updated."""
    rows = await chats.list(FieldEquals(Chat.user_id, user.id))
    return [ChatOut.model_validate(c) for c in rows]


@router.get("/{chat_id}", response_model=ChatDetailOut)
async def get_chat(
    chat: Annotated[Chat, Depends(get_owned_chat)],
    messages: Annotated[MessageRepo, Depends(get_message_repo)],
) -> ChatDetailOut:
    """Return a chat with its full message history, or 404 if not found or not owned."""
    rows = await messages.list(FieldEquals(Message.chat_id, chat.id))
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
        model=chat.model,
        is_favorite=chat.is_favorite,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageOut.model_validate(m) for m in rows],
    )


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> None:
    """Delete a chat and its messages (cascade); 404 if not owned."""
    await chats.delete(chat)


@router.patch("/{chat_id}", response_model=ChatOut)
async def update_chat(
    payload: ChatUpdate,
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> ChatOut:
    """Update a chat's title, model, and/or favorite flag; 404 if not owned.

    The model, when provided, is validated against the live provider list first
    (409 unavailable / 502 provider down). Title and favorite need no validation.
    """
    if payload.model is not None:
        try:
            await registry.ensure_available(payload.model)
        except (ModelUnavailableError, ModelProviderError) as exc:
            _raise_for_model_error(exc)
    updated = await chats.update(chat, **payload.model_dump(exclude_none=True))
    return ChatOut.model_validate(updated)


def _raise_for_model_error(exc: ModelUnavailableError | ModelProviderError) -> NoReturn:
    """Translate a model error into the matching HTTP error."""
    if isinstance(exc, ModelProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
