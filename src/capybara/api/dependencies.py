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
from capybara.services.chat_service import ChatService, ChatTurnLocks
from capybara.services.event_bus import EventBus
from capybara.services.mcp_service import McpService
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


def get_event_bus(request: Request) -> EventBus:
    """Return the app-wide EventBus, lazily creating it if the lifespan did not run.

    Lazy creation keeps tests that override other app-state dependencies working without
    starting the lifespan, while production sets it once in ``main.lifespan``.
    """
    bus = getattr(request.app.state, "event_bus", None)
    if bus is None:
        bus = EventBus()
        request.app.state.event_bus = bus
    return cast(EventBus, bus)


def get_memory_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    event_bus: Annotated[EventBus, Depends(get_event_bus)],
) -> MemoryService:
    """Return a MemoryService that owns short-lived sessions and can publish events."""
    return MemoryService(sessionmaker, agent, settings, event_bus)


def get_mcp_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
) -> McpService:
    """Return an McpService that owns short-lived sessions from the app sessionmaker."""
    return McpService(sessionmaker)


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


def get_chat_turn_locks(request: Request) -> ChatTurnLocks:
    """Return the app-wide per-chat turn-lock registry, lazily creating it if absent.

    Lazy creation mirrors ``get_event_bus`` so tests that override other app-state
    dependencies without running the lifespan still share one registry per app.
    """
    locks = getattr(request.app.state, "chat_turn_locks", None)
    if locks is None:
        locks = ChatTurnLocks()
        request.app.state.chat_turn_locks = locks
    return cast(ChatTurnLocks, locks)


def get_chat_service(
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
    memory_service: Annotated[MemoryService, Depends(get_memory_service)],
    turn_locks: Annotated[ChatTurnLocks, Depends(get_chat_turn_locks)],
    mcp_service: Annotated[McpService, Depends(get_mcp_service)],
) -> ChatService:
    """Return a ChatService wired with recall, MCP toolsets, and the shared turn locks."""
    return ChatService(sessionmaker, agent, memory_service, turn_locks, mcp_service=mcp_service)
