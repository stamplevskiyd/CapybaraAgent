"""FastAPI shell that mounts Chainlit and Capybara custom APIs."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from chainlit.utils import mount_chainlit
from fastapi import FastAPI

from capybara.agent.deep_runtime import DeepAgentRunner, build_graph
from capybara.agent.deep_tools import CompositeToolProvider, McpToolProvider, MemoryToolProvider
from capybara.agent.model_registry import ModelRegistry
from capybara.agent.ollama import OllamaAgent
from capybara.chainlit_app import configure_chainlit_runtime, current_user_id
from capybara.chainlit_config import CHAINLIT_PATH, CHAINLIT_TARGET
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.services.event_bus import EventBus
from capybara.services.mcp_service import McpService
from capybara.services.memory_service import MemoryService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared runtime state and dispose it on shutdown."""
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    sessionmaker = create_sessionmaker(engine)
    app.state.sessionmaker = sessionmaker
    # Compatibility during the migration: legacy /chats routes still use pydantic-ai.
    app.state.agent = OllamaAgent(settings)
    app.state.model_registry = ModelRegistry(settings)
    app.state.event_bus = EventBus()
    # App-wide services (each owns short-lived sessions) back the per-user tools.
    memory_service = MemoryService(sessionmaker, app.state.agent, settings, app.state.event_bus)
    app.state.memory_service = memory_service
    mcp_service = McpService(sessionmaker)
    app.state.mcp_service = mcp_service
    # Build the agent graph per turn so the selected model and the current user's memory/MCP
    # tools can be injected; the user is resolved from the authenticated Chainlit session.
    tool_provider = CompositeToolProvider(
        MemoryToolProvider(memory_service, get_user_id=current_user_id),
        McpToolProvider(mcp_service, get_user_id=current_user_id),
    )
    app.state.deep_agent_runner = DeepAgentRunner(
        graph_factory=lambda tools, model: build_graph(settings, tools, model=model),
        tool_provider=tool_provider,
    )
    configure_chainlit_runtime(
        app.state.deep_agent_runner,
        default_model=settings.default_model,
        settings=settings,
        sessionmaker=sessionmaker,
    )
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Create the FastAPI shell with custom APIs and Chainlit mounted."""
    app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
    # Chainlit signs its own session cookie with this secret once any auth callback is
    # registered; reuse the app's JWT secret so local runs need no extra configuration.
    os.environ.setdefault("CHAINLIT_AUTH_SECRET", get_settings().jwt_secret)
    from capybara.api.routers import auth, chats, events, health, mcp, memory, models, users

    app.include_router(health.router)
    app.include_router(chats.router)
    app.include_router(events.router)
    app.include_router(memory.router)
    app.include_router(mcp.router)
    app.include_router(models.router)
    app.include_router(users.router)
    app.include_router(auth.router)
    mount_chainlit(app=app, target=CHAINLIT_TARGET, path=CHAINLIT_PATH)
    return app
