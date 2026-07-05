"""Reusable FastAPI dependency functions for sessions, users, repos, and services."""

from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent
from capybara.config import Settings
from capybara.db.models import Chat, Fact, User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.fact_repo import FactRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo
from capybara.security.tokens import decode_access_token
from capybara.services.auth_service import AuthService
from capybara.services.chat_service import ChatService
from capybara.services.memory_service import MemoryService
from capybara.services.user_service import UserService

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


def get_user_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRepo:
    """Return a UserRepo bound to the current request session."""
    return UserRepo(session)


def get_user_service(
    users: Annotated[UserRepo, Depends(get_user_repo)],
) -> UserService:
    """Return a UserService wired with the request-scoped UserRepo."""
    return UserService(users)


def get_auth_service(
    users: Annotated[UserRepo, Depends(get_user_repo)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthService:
    """Return an AuthService wired with the request-scoped UserRepo and JWT config."""
    return AuthService(
        users,
        secret=settings.jwt_secret,
        ttl_minutes=settings.jwt_ttl_minutes,
        algorithm=settings.jwt_algorithm,
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    users: Annotated[UserRepo, Depends(get_user_repo)],
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
    user = await users.get(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_chat_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChatRepo:
    """Return a ChatRepo bound to the current request session."""
    return ChatRepo(session)


def get_message_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageRepo:
    """Return a MessageRepo bound to the current request session."""
    return MessageRepo(session)


def get_agent(request: Request) -> BaseAgent:
    """Return the BaseAgent stored on app state."""
    return cast(BaseAgent, request.app.state.agent)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the app-wide async sessionmaker from lifespan state."""
    return cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)


async def get_owned_chat(
    chat_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
) -> Chat:
    """Return the chat if it belongs to the current user, else 404."""
    chat = await chats.get(chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def get_memory_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> MemoryService:
    """Return a MemoryService that owns short-lived sessions from the app sessionmaker."""
    return MemoryService(sessionmaker, agent, settings)


def get_fact_repo(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FactRepo:
    """Return a FactRepo bound to the current request session."""
    return FactRepo(session)


async def get_owned_fact(
    fact_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    facts: Annotated[FactRepo, Depends(get_fact_repo)],
) -> Fact:
    """Return the fact if it belongs to the current user, else 404."""
    fact = await facts.get(fact_id)
    if fact is None or fact.user_id != user.id:
        raise HTTPException(status_code=404, detail="Fact not found")
    return fact


def get_chat_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
) -> ChatService:
    """Return a ChatService that owns short-lived sessions and carries the recall tool."""
    return ChatService(sessionmaker, agent, memory_service)
