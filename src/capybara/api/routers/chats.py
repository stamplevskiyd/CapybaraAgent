"""Router for chat and message endpoints."""

import json
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
)
from capybara.api.schemas import (
    ChatCreate,
    ChatDetailOut,
    ChatOut,
    MessageCreate,
    MessageOut,
)
from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done, Error

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> ChatOut:
    """Create a new chat for the current user."""
    chat = await chats.create(user.id, payload.title)
    return ChatOut.model_validate(chat)


@router.get("", response_model=list[ChatOut])
async def list_chats(
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> list[ChatOut]:
    """Return all chats for the current user, ordered by most recently updated."""
    rows = await chats.list_for_user(user.id)
    return [ChatOut.model_validate(c) for c in rows]


@router.get("/{chat_id}", response_model=ChatDetailOut)
async def get_chat(
    chat_id: UUID,
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    messages: Annotated[MessageRepo, Depends(get_message_repo)],
) -> ChatDetailOut:
    """Return a chat with its full message history, or 404 if not found."""
    chat = await chats.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    rows = await messages.list_for_chat(chat_id)
    return ChatDetailOut(
        id=chat.id,
        title=chat.title,
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
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Accept a user message, stream the LLM reply via SSE, and persist both messages."""
    if await chats.get(chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, payload.content):
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Done):
                    yield _sse(
                        "done",
                        {"message_id": event.message_id, "usage": event.usage},
                    )
                elif isinstance(event, Error):
                    yield _sse("error", {"message": event.message})
        except Exception as exc:  # surface as SSE error, never a broken stream
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
