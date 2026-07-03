"""Pydantic request/response schemas for the chat and user APIs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """Request body for registering a user."""

    display_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    """Public user representation — never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    created_at: datetime


class ChatCreate(BaseModel):
    """Payload for creating a new chat."""

    title: str | None = None


class MessageCreate(BaseModel):
    """Payload for sending a message."""

    content: str


class MessageOut(BaseModel):
    """Response schema for a single message."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    model: str | None
    incomplete: bool
    created_at: datetime


class ChatOut(BaseModel):
    """Response schema for a chat summary."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    """Response schema for a chat with its full message list."""

    messages: list[MessageOut]
