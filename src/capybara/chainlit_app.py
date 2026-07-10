"""Chainlit callbacks for CapybaraAgent chat runtime."""

from collections.abc import Callable
from uuid import UUID

import chainlit as cl
import jwt
from chainlit.data.base import BaseDataLayer
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers

from capybara.agent.deep_runtime import DeepAgentRunner
from capybara.config import Settings, get_settings
from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token

#: Postgres schema holding Chainlit's data-layer tables, isolated from Capybara's own
#: (notably Chainlit's ``users`` vs. the auth ``users`` table).
CHAINLIT_DB_SCHEMA = "chainlit"


def build_data_layer(settings: Settings) -> SQLAlchemyDataLayer:
    """Build the Chainlit SQLAlchemy data layer scoped to the ``chainlit`` schema.

    Chainlit persists threads/steps/elements/feedbacks (and its own users) here; scoping the
    connection's ``search_path`` keeps those tables out of Capybara's ``public`` schema.
    """
    return SQLAlchemyDataLayer(
        conninfo=settings.database_url,
        connect_args={"server_settings": {"search_path": CHAINLIT_DB_SCHEMA}},
    )


@cl.data_layer
def _data_layer() -> BaseDataLayer:
    """Provide Chainlit's persistence backend so threads/messages survive reconnects."""
    return build_data_layer(_settings if _settings is not None else get_settings())


_runtime_runner: DeepAgentRunner | None = None
_default_model = "llama3.1"
_settings: Settings | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def configure_chainlit_runtime(
    runner: DeepAgentRunner,
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


def _tool_step(name: str) -> cl.Step:
    """Create a Chainlit tool step for a tool call."""
    return cl.Step(name=name, type="tool")


async def stream_agent_message(
    *,
    runner: DeepAgentRunner,
    content: str,
    model: str,
    thread_id: str,
    response: cl.Message,
    new_step: Callable[[str], cl.Step] = _tool_step,
) -> None:
    """Stream one runner response into a Chainlit message.

    Text streams into *response*; tool calls open a Chainlit step on ``tool_start`` and
    finalize it (with the tool's output) on ``tool_end``, correlated by the run id in the
    event payload.
    """
    steps: dict[str, cl.Step] = {}
    async for event in runner.stream(content, model=model, thread_id=thread_id):
        payload = event.payload or {}
        if event.kind == "text" and event.content:
            await response.stream_token(event.content)
        elif event.kind == "tool_start":
            step = new_step(event.name or "tool")
            step.input = payload.get("input", "")
            await step.send()  # type: ignore[no-untyped-call]  # Chainlit's API is untyped
            run_id = payload.get("run_id")
            if run_id is not None:
                steps[str(run_id)] = step
        elif event.kind == "tool_end":
            run_id = payload.get("run_id")
            ended = steps.pop(str(run_id), None) if run_id is not None else None
            if ended is not None:
                ended.output = payload.get("output", "")
                await ended.update()  # type: ignore[no-untyped-call]  # Chainlit's API is untyped
    await response.send()  # type: ignore[no-untyped-call]  # Chainlit's API is untyped


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialize a Chainlit chat session with the default model."""
    cl.user_session.set("model", _default_model)  # type: ignore[no-untyped-call]


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Run one message through DeepAgents and stream it through Chainlit."""
    if _runtime_runner is None:
        raise RuntimeError("DeepAgentRunner is not configured")
    model = cl.user_session.get("model", _default_model)  # type: ignore[no-untyped-call]
    await stream_agent_message(
        runner=_runtime_runner,
        content=message.content,
        model=str(model),
        thread_id=cl.context.session.id,
        response=cl.Message(content=""),
    )
