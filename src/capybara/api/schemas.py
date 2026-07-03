"""Pydantic request/response schemas for the chat API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
