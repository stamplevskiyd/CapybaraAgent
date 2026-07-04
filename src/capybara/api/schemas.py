"""Pydantic request/response schemas for the chat, user, and auth APIs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """Request body for registering a user."""

    display_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Public user representation — never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    created_at: datetime


class ChatCreate(BaseModel):
    """Payload for creating a new chat."""

    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=128)


class ChatUpdate(BaseModel):
    """Payload for changing a chat's selected model."""

    model: str = Field(min_length=1, max_length=128)


class ModelsOut(BaseModel):
    """Available models for a provider."""

    provider: str
    models: list[str]


class MessageCreate(BaseModel):
    """Payload for sending a message."""

    content: str = Field(min_length=1, max_length=100_000)


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
    model: str | None
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    """Response schema for a chat with its full message list."""

    messages: list[MessageOut]


class LoginRequest(BaseModel):
    """Request body for logging in."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Access token issued on successful login."""

    access_token: str
    token_type: str = "bearer"
