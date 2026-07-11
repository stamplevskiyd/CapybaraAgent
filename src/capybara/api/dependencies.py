"""Reusable FastAPI dependencies: session, settings, auth, and app-state singletons.

Commands take their dependencies explicitly, so routers only need these few
building blocks; the ``Annotated`` aliases keep endpoint signatures short.
"""

from collections.abc import AsyncGenerator
from typing import Annotated, cast

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.model_registry import ModelRegistry
from capybara.config import Settings
from capybara.db.models import User
from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Yield an AsyncSession, committing on success or rolling back on error."""
    maker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_settings_dep(request: Request) -> Settings:
    """Return app-wide Settings from lifespan state."""
    return cast(Settings, request.app.state.settings)


def get_model_registry(request: Request) -> ModelRegistry:
    """Return the ModelRegistry stored on app state."""
    return cast(ModelRegistry, request.app.state.model_registry)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the app-wide async sessionmaker from lifespan state."""
    return cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> User:
    """Resolve the authenticated user from the Bearer JWT; 401 if missing/invalid/expired."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        user_id = decode_access_token(
            credentials.credentials, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = await UserRepo(session).get(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Sessionmaker = Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)]
Registry = Annotated[ModelRegistry, Depends(get_model_registry)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
