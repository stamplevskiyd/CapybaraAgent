"""Router for chat and message endpoints."""

import logging
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import ModelMessage
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

from capybara.agent.base import BaseAgent, ModelProviderError, ModelUnavailableError
from capybara.api.dependencies import (
    get_agent,
    get_chat_repo,
    get_chat_service,
    get_current_user,
    get_memory_service,
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
from capybara.api.sse import SSE_HEADERS, format_sse
from capybara.db.models import Chat, Message, User
from capybara.filters import FieldEquals
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import (
    ChatNotFoundError,
    ChatService,
    NoUserMessageError,
    TurnLockLease,
)
from capybara.services.events import Delta, Done, ToolCall, ToolResult
from capybara.services.memory_service import MemoryService, schedule_extraction

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


def _raise_for_model_error(exc: ModelUnavailableError | ModelProviderError) -> NoReturn:
    """Translate a model error into the matching HTTP error."""
    if isinstance(exc, ModelProviderError):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _raise_for_turn_error(exc: BaseException) -> NoReturn:
    """Map a turn-preparation failure to its HTTP error; re-raise anything unexpected."""
    if isinstance(exc, ChatNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat not found"
        ) from None
    if isinstance(exc, NoUserMessageError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No user message to regenerate"
        ) from None
    if isinstance(exc, ModelUnavailableError | ModelProviderError):
        _raise_for_model_error(exc)
    raise exc


class TurnStreamingResponse(StreamingResponse):
    """SSE response that guarantees the turn-lock lease is released.

    Streams that started release the lease in the generator's ``finally``; this
    response-level ``finally`` covers the one path the generator cannot see — a client
    that disconnects before the body iterator is first pulled (on ASGI >= 2.4 the
    header send raises and neither the generator body nor the background task runs).
    Without it the lease would leak and every later send to the chat would deadlock.
    """

    def __init__(
        self,
        content: AsyncIterable[str],
        lease: TurnLockLease,
        background: BackgroundTask | None = None,
    ) -> None:
        """Wrap *content* as an SSE stream that owns *lease* until the response ends."""
        super().__init__(
            content, media_type="text/event-stream", headers=SSE_HEADERS, background=background
        )
        self._lease = lease

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the response, releasing the lease on every exit path."""
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._lease.release()


async def _turn_event_stream(
    service: ChatService,
    lease: TurnLockLease,
    chat_id: UUID,
    model: str,
    content: str,
    history: list[ModelMessage],
    user_id: UUID,
    *,
    title_source: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for one streamed turn, releasing the turn lease at the end.

    When *title_source* is given (first turn of a chat) a title frame is emitted after
    the reply, still under the lease. Stream failures surface as a generic SSE error
    frame, never a broken stream.
    """
    try:
        async for event in service.stream_turn(chat_id, model, content, history, user_id=user_id):
            if isinstance(event, Delta):
                yield format_sse("delta", {"text": event.text})
            elif isinstance(event, ToolCall):
                yield format_sse(
                    "tool-call", {"id": event.id, "name": event.name, "args": event.args}
                )
            elif isinstance(event, ToolResult):
                yield format_sse("tool-result", {"id": event.id, "result": event.result})
            elif isinstance(event, Done):
                yield format_sse("done", {"message_id": event.message_id, "usage": event.usage})
        if title_source is not None:
            title = await service.generate_title(chat_id, title_source)
            if title:
                yield format_sse("title", {"title": title})
    except Exception:  # surface a generic SSE error, never a broken stream
        logger.exception("chat stream failed for chat %s", chat_id)
        yield format_sse("error", {"message": "Internal server error while streaming the reply"})
    finally:
        lease.release()


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: UUID,
    payload: MessageCreate,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    memory: Annotated[MemoryService, Depends(get_memory_service)],
) -> StreamingResponse:
    """Accept a user message, stream the LLM reply via SSE, and persist both messages.

    Ownership is checked and the user message is saved up front on a short-lived
    session; the LLM stream then runs holding no DB connection.  This endpoint does
    not take a request-scoped session — ChatService owns its own session lifecycle.

    The per-chat turn lock is held from before the user message is written until the
    stream finishes persisting the reply, so concurrent sends/regenerations on the same
    chat never interleave. The lease is released here if preparing the turn fails, in
    the stream's ``finally`` once it runs, and by the response itself as a last resort.
    """
    lease = await service.acquire_turn_lock(chat_id)
    try:
        model, history = await service.begin_turn(user.id, chat_id, payload.content)
    except BaseException as exc:
        lease.release()
        _raise_for_turn_error(exc)
    return TurnStreamingResponse(
        _turn_event_stream(
            service,
            lease,
            chat_id,
            model,
            payload.content,
            history,
            user.id,
            # First turn → derive a title without delaying the answer.
            title_source=payload.content if not history else None,
        ),
        lease=lease,
        background=BackgroundTask(schedule_extraction, memory, user.id, chat_id),
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

    Holds the per-chat turn lock across delete → stream → persist so it cannot race a
    concurrent send or regenerate on the same chat. The lease is released here if
    preparation fails, in the stream's ``finally`` once it runs, and by the response
    itself as a last resort.
    """
    lease = await service.acquire_turn_lock(chat_id)
    try:
        model, last_user_content, history = await service.regenerate_turn(user.id, chat_id)
    except BaseException as exc:
        lease.release()
        _raise_for_turn_error(exc)
    return TurnStreamingResponse(
        _turn_event_stream(service, lease, chat_id, model, last_user_content, history, user.id),
        lease=lease,
    )
