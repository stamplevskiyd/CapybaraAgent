from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatCreate(BaseModel):
    title: str | None = None


class MessageCreate(BaseModel):
    content: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    model: str | None
    incomplete: bool
    created_at: datetime


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    messages: list[MessageOut]
