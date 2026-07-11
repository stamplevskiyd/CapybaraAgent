"""FastAPI shell that mounts Chainlit and Capybara custom APIs."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from chainlit.utils import mount_chainlit
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from capybara.agent.deep_runtime import DeepAgentRunner, build_graph
from capybara.agent.deep_tools import CompositeToolProvider, McpToolProvider, MemoryToolProvider
from capybara.agent.model_registry import ModelRegistry
from capybara.chainlit_app import configure_chainlit_runtime, current_user_id
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.services.chat_pref_service import ChatPrefService
from capybara.services.mcp_service import McpService
from capybara.services.memory_service import MemoryService

#: Where the Chainlit runtime is mounted and the module defining its callbacks.
CHAINLIT_PATH = "/chainlit"
CHAINLIT_TARGET = "src/capybara/chainlit_app.py"


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
    # App-wide services (each owns short-lived sessions) back the per-user tools.
    memory_service = MemoryService(sessionmaker, model_registry, settings)
    app.state.memory_service = memory_service
    mcp_service = McpService(sessionmaker)
    app.state.mcp_service = mcp_service
    # Build the agent graph per turn so the selected model and the current user's memory/MCP
    # tools can be injected; the user is resolved from the authenticated Chainlit session.
    tool_provider = CompositeToolProvider(
        MemoryToolProvider(memory_service, get_user_id=current_user_id),
        McpToolProvider(mcp_service, get_user_id=current_user_id),
    )
    # One process-wide checkpointer carries conversation state across per-turn graph
    # rebuilds (keyed by thread_id). In-memory for now: history for the model resets on
    # restart, while Chainlit's data layer keeps the visible transcript.
    checkpointer = InMemorySaver()
    app.state.deep_agent_runner = DeepAgentRunner(
        lambda tools, model: build_graph(
            model_registry, tools, model=model, checkpointer=checkpointer
        ),
        tool_provider=tool_provider,
    )
    configure_chainlit_runtime(
        app.state.deep_agent_runner,
        default_model=settings.default_model,
        settings=settings,
        sessionmaker=sessionmaker,
        chat_pref_service=ChatPrefService(sessionmaker),
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
        chat_prefs,
        health,
        mcp,
        memory,
        models,
        users,
    )

    app.include_router(health.router)
    app.include_router(chat_prefs.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)
    app.include_router(models.router)
    app.include_router(users.router)
    app.include_router(auth.router)
    mount_chainlit(app=app, target=CHAINLIT_TARGET, path=CHAINLIT_PATH)
    return app
