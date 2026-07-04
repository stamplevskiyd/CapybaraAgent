"""Router for chat and message endpoints."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from capybara.api.dependencies import (
    get_chat_repo,
    get_chat_service,
    get_current_user,
    get_message_repo,
    get_owned_chat,
)
from capybara.api.schemas import (
    ChatCreate,
    ChatDetailOut,
    ChatOut,
    MessageCreate,
    MessageOut,
)
from capybara.db.models import Chat, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatNotFoundError, ChatService
from capybara.services.events import Delta, Done

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> ChatOut:
    """Create a new chat for the current user."""
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
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageOut.model_validate(m) for m in rows],
    )


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: UUID,
    payload: MessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Accept a user message, stream the LLM reply via SSE, and persist both messages.

    Ownership is checked and the user message is saved up front on a short-lived
    session; the LLM stream then runs holding no DB connection.  This endpoint does
    not take a request-scoped session — ChatService owns its own session lifecycle.
    """
    try:
        history = await service.begin_turn(user.id, chat_id, payload.content)
    except ChatNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        ) from None

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, payload.content, history):
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Done):
                    yield _sse(
                        "done",
                        {"message_id": event.message_id, "usage": event.usage},
                    )
        except Exception:  # surface a generic SSE error, never a broken stream
            logger.exception("chat stream failed for chat %s", chat_id)
            yield _sse("error", {"message": "Internal server error while streaming the reply"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
