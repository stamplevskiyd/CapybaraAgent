"""Reusable FastAPI dependency functions for sessions, users, repos, and services."""

from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent
from capybara.db.models import User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.services.chat_service import ChatService

LOCAL_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession, committing on success or rolling back on error."""
    maker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Return the seeded local User; raise RuntimeError if migrations have not been run."""
    user = await session.get(User, LOCAL_USER_ID)
    if user is None:
        raise RuntimeError("Local user not seeded — run migrations")
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


def get_chat_service(
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    messages: Annotated[MessageRepo, Depends(get_message_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatService:
    """Return a ChatService wired with the request-scoped repos and agent."""
    return ChatService(chats, messages, agent)
