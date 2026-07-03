"""Reusable FastAPI dependency functions for sessions, users, repos, and services."""

from collections.abc import AsyncGenerator
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capybara.agent.base import BaseAgent
from capybara.db.models import Chat, User
from capybara.repositories.chat_repo import ChatRepo
from capybara.repositories.message_repo import MessageRepo
from capybara.repositories.user_repo import UserRepo
from capybara.services.chat_service import ChatService
from capybara.services.user_service import UserService


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


async def get_current_user() -> User:
    """Resolve the authenticated user — 401 until the login slice exists."""
    raise HTTPException(status_code=401, detail="Authentication required")


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


def get_chat_service(
    chats: Annotated[ChatRepo, Depends(get_chat_repo)],
    messages: Annotated[MessageRepo, Depends(get_message_repo)],
    agent: Annotated[BaseAgent, Depends(get_agent)],
) -> ChatService:
    """Return a ChatService wired with the request-scoped repos and agent."""
    return ChatService(chats, messages, agent)
