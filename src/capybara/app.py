"""FastAPI shell that mounts Chainlit and Capybara custom APIs."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from chainlit.utils import mount_chainlit
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from capybara.agent.deep_runtime import (
    DeepAgentRunner,
    McpServerSpec,
    build_fast_graph,
    build_graph,
)
from capybara.agent.deep_tools import UserToolProvider
from capybara.agent.model_registry import ModelRegistry
from capybara.chainlit_app import configure_chainlit_runtime, current_user_id
from capybara.commands.chat_settings.get import GetChatSettings
from capybara.commands.fact.recall import RecallFacts
from capybara.commands.mcp.tool_specs import ListEnabledToolSpecs
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.db.models import ChatSettings, Fact

#: Where the Chainlit runtime is mounted, and the shim it loads. The shim (not
#: chainlit_app.py itself) is the target because Chainlit executes the target file as a
#: separate module instance — see capybara/chainlit_target.py.
CHAINLIT_PATH = "/chainlit"
CHAINLIT_TARGET = "src/capybara/chainlit_target.py"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared runtime state and dispose it on shutdown."""
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    sessionmaker = create_sessionmaker(engine)
    app.state.sessionmaker = sessionmaker
    model_registry = ModelRegistry(settings)
    app.state.model_registry = model_registry

    # Per-turn command adapters: the agent layer depends on these narrow callables,
    # not on the command classes.
    async def recall(user_id: UUID, query: str) -> list[Fact]:
        return await RecallFacts(
            sessionmaker, model_registry, settings, user_id=user_id, query=query
        ).execute()

    async def mcp_specs(user_id: UUID) -> list[McpServerSpec]:
        return await ListEnabledToolSpecs(sessionmaker, user_id=user_id).execute()

    async def pref_lookup(user_id: UUID, thread_id: UUID) -> ChatSettings | None:
        return await GetChatSettings(sessionmaker, user_id=user_id, thread_id=thread_id).execute()

    # Build the agent graph per turn so the selected model and the current user's
    # memory/MCP tools can be injected; the user is resolved from the authenticated
    # Chainlit session.
    tool_provider = UserToolProvider(recall, mcp_specs, get_user_id=current_user_id)
    # One process-wide checkpointer carries conversation state across per-turn graph
    # rebuilds (keyed by thread_id). In-memory for now: history for the model resets on
    # restart, while Chainlit's data layer keeps the visible transcript.
    checkpointer = InMemorySaver()

    def graph_factory(tools, model, mode):  # type: ignore[no-untyped-def]
        """Build the turn's graph: the Fast react loop or the Smart DeepAgents graph."""
        build = build_fast_graph if mode == "fast" else build_graph
        return build(model_registry, tools, model=model, checkpointer=checkpointer)

    app.state.deep_agent_runner = DeepAgentRunner(graph_factory, tool_provider=tool_provider)
    configure_chainlit_runtime(
        app.state.deep_agent_runner,
        default_model=settings.default_model,
        settings=settings,
        sessionmaker=sessionmaker,
        pref_lookup=pref_lookup,
    )
    try:
        yield
    finally:
        await model_registry.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    """Create the FastAPI shell with custom APIs and Chainlit mounted."""
    app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
    # Chainlit signs its own session cookie with this secret once any auth callback is
    # registered; reuse the app's JWT secret so local runs need no extra configuration.
    os.environ.setdefault("CHAINLIT_AUTH_SECRET", get_settings().jwt_secret)
    from capybara.api.routers import (
        auth,
        chat_settings,
        health,
        mcp,
        memory,
        models,
        users,
    )

    app.include_router(health.router)
    app.include_router(chat_settings.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)
    app.include_router(models.router)
    app.include_router(users.router)
    app.include_router(auth.router)
    mount_chainlit(app=app, target=CHAINLIT_TARGET, path=CHAINLIT_PATH)
    return app
