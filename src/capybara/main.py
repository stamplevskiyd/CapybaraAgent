"""FastAPI application factory and lifespan management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from capybara.agent.ollama import OllamaAgent
from capybara.config import get_settings
from capybara.db.engine import create_engine, create_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise engine, sessionmaker, and agent on startup; dispose engine on shutdown."""
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.agent = OllamaAgent(settings)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application with all routers."""
    fastapi_app = FastAPI(title="CapybaraAgent", lifespan=lifespan)
    from capybara.api.routers import chats, health, users

    fastapi_app.include_router(health.router)
    fastapi_app.include_router(chats.router)
    fastapi_app.include_router(users.router)
    return fastapi_app


app = create_app()
