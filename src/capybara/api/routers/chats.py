"""Router for chat and message endpoints."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from capybara.agent.base import BaseAgent, ModelProviderError, ModelUnavailableError
from capybara.api.dependencies import (
    get_agent,
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
    ChatUpdate,
    MessageCreate,
    MessageOut,
)
from capybara.db.models import Chat, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatNotFoundError, ChatService, NoUserMessageError
from capybara.services.events import Delta, Done

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ChatOut)
async def create_chat(
    payload: ChatCreate,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatOut:
    """Create a new chat for the current user, optionally with a validated model."""
    if payload.model is not None:
        try:
            await agent.ensure_available(payload.model)
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


@router.patch("/{chat_id}", response_model=ChatOut)
async def update_chat(
    payload: ChatUpdate,
    chat: Annotated[Chat, Depends(get_owned_chat)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatOut:
    """Update a chat's title, model, and/or favorite flag; 404 if not owned.

    The model, when provided, is validated against the live provider list first
    (409 unavailable / 502 provider down). Title and favorite need no validation.
    """
    if payload.model is not None:
        try:
            await agent.ensure_available(payload.model)
        except (ModelUnavailableError, ModelProviderError) as exc:
            _raise_for_model_error(exc)
    updated = await chats.update(chat, **payload.model_dump(exclude_none=True))
    return ChatOut.model_validate(updated)


def _sse(event: str, data: dict[str, object]) -> str:
    """Format a single SSE frame as ``event: <name>`` / ``data: <json>``."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _raise_for_model_error(exc: ModelUnavailableError | ModelProviderError) -> NoReturn:
    """Translate a model error into the matching HTTP error."""
    if isinstance(exc, ModelProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# Headers that every SSE streaming response must carry.  Applied to both
# send_message and regenerate so the Vite dev proxy, nginx, and the browser
# all know this is a live stream and must not buffer chunks.
_SSE_HEADERS: dict[str, str] = {
    # Prevent the Vite dev proxy and browser fetch from buffering the
    # response — chunks must arrive incrementally so assistant tokens
    # appear in real time rather than all at once (or not at all).
    "Cache-Control": "no-cache",
    # Disable nginx upstream buffering in production.
    "X-Accel-Buffering": "no",
    # Keep the TCP connection open for the duration of the stream.
    "Connection": "keep-alive",
}


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
        model, history = await service.begin_turn(user.id, chat_id, payload.content)
    except ChatNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        ) from None
    except (ModelUnavailableError, ModelProviderError) as exc:
        _raise_for_model_error(exc)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, model, payload.content, history):
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

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/{chat_id}/messages/regenerate")
async def regenerate_message(
    chat_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Delete the trailing assistant reply and stream a fresh one via SSE.

    No new user message is written — this endpoint regenerates the assistant
    reply for the last existing user message.  Ownership is verified and the
    old assistant row(s) are removed before any SSE bytes are sent.
    """
    try:
        model, last_user_content, history = await service.regenerate_turn(user.id, chat_id)
    except ChatNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        ) from None
    except NoUserMessageError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No user message to regenerate"
        ) from None
    except (ModelUnavailableError, ModelProviderError) as exc:
        _raise_for_model_error(exc)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_turn(chat_id, model, last_user_content, history):
                if isinstance(event, Delta):
                    yield _sse("delta", {"text": event.text})
                elif isinstance(event, Done):
                    yield _sse(
                        "done",
                        {"message_id": event.message_id, "usage": event.usage},
                    )
        except Exception:  # surface a generic SSE error, never a broken stream
            logger.exception("regenerate stream failed for chat %s", chat_id)
            yield _sse("error", {"message": "Internal server error while streaming the reply"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
