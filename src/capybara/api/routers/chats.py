"""Router for chat and message endpoints."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from capybara.api.dependencies import (
    get_chat_repo,
    get_chat_service,
    get_current_user,
    get_message_repo,
    get_owned_chat,
    get_session,
)
from capybara.api.schemas import (
    ChatCreate,
    ChatDetailOut,
    ChatOut,
    MessageCreate,
    MessageOut,
)
from capybara.db.models import Chat, User
from capybara.filters import FieldEquals, OwnedByUser
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService
from capybara.services.events import Delta, Done, Error

logger = logging.getLogger(__name__)

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
    rows = await chats.list(OwnedByUser(user.id))
    return [ChatOut.model_validate(c) for c in rows]


@router.get("/{chat_id}", response_model=ChatDetailOut)
async def get_chat(
    chat: Annotated[Chat, Depends(get_owned_chat)],
    messages: Annotated[MessageRepo, Depends(get_message_repo)],
) -> ChatDetailOut:
    """Return a chat with its full message history, or 404 if not found or not owned."""
    rows = await messages.list(FieldEquals("chat_id", chat.id))
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
    chat: Annotated[Chat, Depends(get_owned_chat)],
    payload: MessageCreate,
    service: Annotated[ChatService, Depends(get_chat_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    """Accept a user message, stream the LLM reply via SSE, and persist both messages."""
    chat_id = chat.id
    # Release the request DB connection before the (potentially slow) LLM stream:
    # the auth/ownership reads are done, and the turn itself runs on its own
    # short-lived sessions inside ChatService.  Otherwise this connection would
    # be pinned for the whole stream and exhaust the pool under load.
    await session.commit()

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
        except Exception:  # surface a generic SSE error, never a broken stream
            logger.exception("chat stream failed for chat %s", chat_id)
            yield _sse("error", {"message": "Internal server error while streaming the reply"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
