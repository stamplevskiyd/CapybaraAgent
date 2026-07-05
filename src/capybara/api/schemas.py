"""Pydantic request/response schemas for the chat, memory, user, and auth APIs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_required_text(value: object) -> object:
    """Strip a text field and reject it when only whitespace remains."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
    return value


def _reject_blank_text(value: str) -> str:
    """Reject a text field that contains only whitespace while preserving the original."""
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class UserCreate(BaseModel):
    """Request body for registering a user."""

    display_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("display_name", "username", mode="before")
    @classmethod
    def _strip_identity_fields(cls, value: object) -> object:
        """Trim public identity fields and reject whitespace-only values."""
        return _strip_required_text(value)

    @field_validator("password")
    @classmethod
    def _password_not_blank(cls, value: str) -> str:
        """Reject whitespace-only passwords without otherwise changing them."""
        return _reject_blank_text(value)


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

    @field_validator("title", "model", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        """Trim optional text fields when provided and reject whitespace-only values."""
        if value is None:
            return None
        return _strip_required_text(value)


class ChatUpdate(BaseModel):
    """Partial update for a chat: any of title, model, or favorite. At least one required."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    is_favorite: bool | None = None

    @field_validator("title", "model", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        """Trim optional text fields when provided and reject whitespace-only values."""
        if value is None:
            return None
        return _strip_required_text(value)

    @model_validator(mode="after")
    def _require_one(self) -> ChatUpdate:
        """Reject an empty patch — at least one field must be provided."""
        if self.title is None and self.model is None and self.is_favorite is None:
            raise ValueError("at least one of title, model, is_favorite must be provided")
        return self


class ModelsOut(BaseModel):
    """Available models for a provider."""

    provider: str
    models: list[str]


class MessageCreate(BaseModel):
    """Payload for sending a message."""

    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        """Reject whitespace-only user messages while preserving intentional spacing."""
        return _reject_blank_text(value)


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
    is_favorite: bool
    created_at: datetime
    updated_at: datetime


class ChatDetailOut(ChatOut):
    """Response schema for a chat with its full message list."""

    messages: list[MessageOut]


class LoginRequest(BaseModel):
    """Request body for logging in."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def _strip_username(cls, value: object) -> object:
        """Trim the login username and reject whitespace-only values."""
        return _strip_required_text(value)

    @field_validator("password")
    @classmethod
    def _login_password_not_blank(cls, value: str) -> str:
        """Reject whitespace-only login passwords."""
        return _reject_blank_text(value)


class TokenResponse(BaseModel):
    """Access token issued on successful login."""

    access_token: str
    token_type: str = "bearer"


FactCategory = Literal["personal", "project", "preference"]


class FactCreate(BaseModel):
    """Payload for creating a manual fact."""

    content: str = Field(min_length=1, max_length=2000)
    category: FactCategory

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        """Reject whitespace-only fact content."""
        return _reject_blank_text(value)


class FactUpdate(BaseModel):
    """Partial update for a fact: content and/or category. At least one required."""

    content: str | None = Field(default=None, min_length=1, max_length=2000)
    category: FactCategory | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _strip_optional_content(cls, value: object) -> object:
        """Trim optional content and reject whitespace-only values."""
        if value is None:
            return None
        return _strip_required_text(value)

    @model_validator(mode="after")
    def _require_one(self) -> FactUpdate:
        """Reject an empty patch — at least one field must be provided."""
        if self.content is None and self.category is None:
            raise ValueError("at least one of content, category must be provided")
        return self


class FactOut(BaseModel):
    """Response schema for a single fact."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime


class MemorySettingsOut(BaseModel):
    """Response schema for the memory auto-capture toggle."""

    auto_capture: bool


class MemorySettingsUpdate(BaseModel):
    """Request schema for updating the memory auto-capture toggle."""

    auto_capture: bool
