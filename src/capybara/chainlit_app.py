"""Chainlit callbacks for CapybaraAgent chat runtime."""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

import chainlit as cl
import jwt
from chainlit.data.base import BaseDataLayer
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.types import ThreadDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers

from capybara.agent.deep_runtime import DeepAgentRunner
from capybara.config import Settings, get_settings
from capybara.db.models import ChatPref
from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token

#: Look up a thread's saved prefs for a user (wired to the GetChatPref command).
PrefLookup = Callable[[UUID, UUID], Awaitable[ChatPref | None]]

logger = logging.getLogger(__name__)

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
_pref_lookup: PrefLookup | None = None


def configure_chainlit_runtime(
    runner: DeepAgentRunner,
    *,
    default_model: str,
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    pref_lookup: PrefLookup | None = None,
) -> None:
    """Configure process-level runtime dependencies for Chainlit callbacks.

    *settings* and *sessionmaker* back the header-auth callback; without them auth resolves
    to no user (and per-user tools stay empty). *pref_lookup* resolves each thread's saved
    model; without it every turn uses *default_model*.
    """
    global _default_model, _runtime_runner, _settings, _sessionmaker, _pref_lookup
    _runtime_runner = runner
    _default_model = default_model
    _settings = settings
    _sessionmaker = sessionmaker
    _pref_lookup = pref_lookup


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
    mode: str = "fast",
    new_step: Callable[[str], cl.Step] = _tool_step,
) -> None:
    """Stream one runner response into a Chainlit message.

    Text streams into *response*; tool calls open a Chainlit step on ``tool_start`` and
    finalize it (with the tool's output) on ``tool_end``, correlated by the run id in the
    event payload. *mode* selects the runtime (``"fast"`` react loop vs ``"smart"``
    DeepAgents); it defaults to ``"fast"`` (the product default) — ``on_message`` always
    passes an explicit resolved mode, so this default only matters to callers that omit it.
    """
    steps: dict[str, cl.Step] = {}
    async for event in runner.stream(content, model=model, thread_id=thread_id, mode=mode):
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


async def selected_model(metadata: dict[str, object] | None, thread_id: str) -> str:
    """Resolve the model for one turn.

    Precedence: the model the client sent with this very message (the only channel that
    exists before a brand-new thread has prefs), then the thread's saved pref, then the
    configured default.
    """
    candidate = (metadata or {}).get("model")
    if isinstance(candidate, str) and candidate:
        return candidate
    user_id = current_user_id()
    if _pref_lookup is not None and user_id is not None:
        try:
            pref = await _pref_lookup(user_id, UUID(thread_id))
        except ValueError:  # non-UUID thread id — nothing saved for it by definition
            pref = None
        if pref is not None and pref.model:
            return pref.model
    return _default_model


#: Valid agent modes; anything else resolves to the default.
_AGENT_MODES = ("fast", "smart")


async def selected_mode(metadata: dict[str, object] | None, thread_id: str) -> str:
    """Resolve the agent mode for one turn.

    Precedence mirrors ``selected_model``: the mode sent with this message, then the
    thread's saved pref, then the default ``"fast"``. An unknown value resolves to the
    default rather than raising.
    """
    candidate = (metadata or {}).get("mode")
    if isinstance(candidate, str) and candidate in _AGENT_MODES:
        return candidate
    user_id = current_user_id()
    if _pref_lookup is not None and user_id is not None:
        try:
            pref = await _pref_lookup(user_id, UUID(thread_id))
        except ValueError:  # non-UUID thread id — nothing saved for it by definition
            pref = None
        if pref is not None and pref.mode in _AGENT_MODES:
            return pref.mode
    return "fast"


@cl.on_chat_resume
async def on_chat_resume(thread: ThreadDict) -> None:
    """Accept resuming a persisted thread.

    The visible transcript is restored by the data layer; the agent's own context lives in
    the checkpointer keyed by this thread's id, so the conversation continues where it
    left off (within one process for the in-memory checkpointer).
    """


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Run one message through DeepAgents and stream it through Chainlit."""
    if _runtime_runner is None:
        raise RuntimeError("DeepAgentRunner is not configured")
    # The session's thread id (not the session id): stable across reconnects and equal to
    # the id the client uses for the thread's prefs and history.
    thread_id = cl.context.session.thread_id
    model = await selected_model(message.metadata, thread_id)
    mode = await selected_mode(message.metadata, thread_id)
    try:
        await stream_agent_message(
            runner=_runtime_runner,
            content=message.content,
            model=model,
            mode=mode,
            thread_id=thread_id,
            response=cl.Message(content=""),
        )
    except Exception:
        # Surface a readable failure instead of a dead spinner — with a local-first stack
        # the usual cause is Ollama being down or the selected model not being pulled.
        logger.exception("chat turn failed (model=%s)", model)
        await cl.ErrorMessage(
            content=(
                f"The agent could not complete this turn with model {model!r}. "
                "Check that Ollama is running and the selected model is installed."
            )
        ).send()  # type: ignore[no-untyped-call]  # Chainlit's API is untyped
