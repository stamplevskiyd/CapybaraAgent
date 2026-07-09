"""Chainlit callbacks for CapybaraAgent chat runtime."""

from collections.abc import AsyncIterator
from typing import Protocol, cast
from uuid import UUID

import chainlit as cl
import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers

from capybara.agent.deep_runtime import RunnerEvent
from capybara.config import Settings
from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token


class Runner(Protocol):
    """Agent runtime contract consumed by Chainlit callbacks."""

    def stream(
        self,
        content: str,
        *,
        model: str,
        thread_id: str,
    ) -> AsyncIterator[RunnerEvent]:
        """Stream normalized runner events for one user message."""
        ...


class MessageSink(Protocol):
    """Subset of Chainlit Message used by the streaming helper."""

    async def stream_token(self, token: str) -> None:
        """Stream one token into the visible response."""
        ...

    async def send(self) -> None:
        """Finalize the visible response."""
        ...


_runtime_runner: Runner | None = None
_default_model = "llama3.1"
_settings: Settings | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_chainlit_runtime(
    runner: Runner,
    *,
    default_model: str,
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Configure process-level runtime dependencies for Chainlit callbacks.

    *settings* and *sessionmaker* back the header-auth callback; without them auth resolves
    to no user (and per-user tools stay empty).
    """
    global _default_model, _runtime_runner, _settings, _sessionmaker
    _runtime_runner = runner
    _default_model = default_model
    _settings = settings
    _sessionmaker = sessionmaker


async def resolve_user(
    headers: Headers,
    *,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> cl.User | None:
    """Resolve a Chainlit user from the app's ``Authorization: Bearer`` JWT.

    Mirrors the REST ``get_current_user`` dependency so both entry points trust the same
    tokens. Any missing/malformed/invalid token, or a token for a vanished user, yields
    ``None`` (Chainlit then rejects the connection).
    """
    header = headers.get("Authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        user_id = decode_access_token(
            token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
    except jwt.InvalidTokenError:
        return None
    async with sessionmaker() as session:
        user = await UserRepo(session).get(user_id)
    if user is None:
        return None
    return cl.User(identifier=user.username, metadata={"user_id": str(user.id)})


@cl.header_auth_callback
async def header_auth_callback(headers: Headers) -> cl.User | None:
    """Authenticate the Chainlit connection using the app's JWT, or reject it."""
    if _settings is None or _sessionmaker is None:
        return None
    return await resolve_user(headers, settings=_settings, sessionmaker=_sessionmaker)


def current_user_id() -> UUID | None:
    """Return the authenticated user's id for the current Chainlit session, or None.

    Read lazily each turn so a reconnecting/expiring session never binds tools to a stale
    user. Returns None when unauthenticated or when the metadata is missing/malformed.
    """
    user = cl.user_session.get("user")  # type: ignore[no-untyped-call]
    metadata = getattr(user, "metadata", None) or {}
    raw = metadata.get("user_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _configured_runner() -> Runner:
    """Return the runner configured for the current Chainlit session."""
    session_runner = cl.user_session.get("deep_agent_runner")  # type: ignore[no-untyped-call]
    if session_runner is not None and hasattr(session_runner, "stream"):
        return cast(Runner, session_runner)
    if _runtime_runner is None:
        raise RuntimeError("DeepAgentRunner is not configured")
    return _runtime_runner


async def stream_agent_message(
    *,
    runner: Runner,
    content: str,
    model: str,
    thread_id: str,
    response: MessageSink,
) -> None:
    """Stream one runner response into a Chainlit message sink."""
    async for event in runner.stream(content, model=model, thread_id=thread_id):
        if event.kind == "text" and event.content:
            await response.stream_token(event.content)
    await response.send()


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a Chainlit chat session."""
    cl.user_session.set("model", _default_model)  # type: ignore[no-untyped-call]
    if _runtime_runner is not None:
        cl.user_session.set("deep_agent_runner", _runtime_runner)  # type: ignore[no-untyped-call]


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Run one message through DeepAgents and stream it through Chainlit."""
    model = cl.user_session.get("model", _default_model)  # type: ignore[no-untyped-call]
    thread_id = cl.context.session.id
    response = cl.Message(content="")
    await stream_agent_message(
        runner=_configured_runner(),
        content=message.content,
        model=str(model),
        thread_id=thread_id,
        response=response,
    )
