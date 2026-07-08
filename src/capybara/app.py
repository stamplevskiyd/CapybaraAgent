"""FastAPI shell that mounts Chainlit and Capybara custom APIs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from chainlit.utils import mount_chainlit
from fastapi import FastAPI

from capybara.agent.ollama import OllamaAgent
from capybara.chainlit_config import CHAINLIT_PATH, CHAINLIT_TARGET
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker
from capybara.services.event_bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize shared runtime state and dispose it on shutdown."""
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    # Compatibility during the migration: legacy /chats routes still use pydantic-ai.
    app.state.agent = OllamaAgent(settings)
    app.state.event_bus = EventBus()
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Create the FastAPI shell with custom APIs and Chainlit mounted."""
    app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
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
