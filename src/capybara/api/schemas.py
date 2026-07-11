"""Pydantic request/response schemas for the memory, MCP, user, and auth APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)


def _strip_required_text(value: object) -> object:
    """Strip a text value and reject it when only whitespace remains."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped
    return value


def _reject_blank_text(value: str) -> str:
    """Reject text that contains only whitespace while preserving the original."""
    if not value.strip():
        raise ValueError("must not be blank")
    return value


#: Text stripped on input; whitespace-only values are rejected before length checks.
TrimmedText = Annotated[str, BeforeValidator(_strip_required_text)]
#: Text kept verbatim (intentional spacing preserved); whitespace-only values are rejected.
NonBlankText = Annotated[str, AfterValidator(_reject_blank_text)]


class UserCreate(BaseModel):
    """Request body for registering a user."""

    display_name: TrimmedText = Field(min_length=1, max_length=128)
    username: TrimmedText = Field(min_length=3, max_length=64)
    password: NonBlankText = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    """Public user representation — never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    created_at: datetime


class ModelsOut(BaseModel):
    """Available models for a provider."""

    provider: str
    models: list[str]


class LoginRequest(BaseModel):
    """Request body for logging in."""

    username: TrimmedText = Field(min_length=1, max_length=64)
    password: NonBlankText = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Access token issued on successful login."""

    access_token: str
    token_type: str = "bearer"


FactCategory = Literal["personal", "project", "preference"]
AgentMode = Literal["fast", "smart"]


class FactCreate(BaseModel):
    """Payload for creating a manual fact."""

    content: NonBlankText = Field(min_length=1, max_length=2000)
    category: FactCategory


class FactUpdate(BaseModel):
    """Partial update for a fact: content and/or category. At least one required."""

    content: TrimmedText | None = Field(default=None, min_length=1, max_length=2000)
    category: FactCategory | None = None

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


class McpServerCreate(BaseModel):
    """Payload to attach an MCP server."""

    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)


class McpServerUpdate(BaseModel):
    """Partial update for an MCP server. At least one field must be provided."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1)
    headers: dict[str, str] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _require_one(self) -> McpServerUpdate:
        """Reject an empty patch."""
        if self.name is None and self.url is None and self.headers is None and self.enabled is None:
            raise ValueError("at least one field must be provided")
        return self


class McpToolUpdate(BaseModel):
    """Payload to toggle a tool's enabled flag."""

    enabled: bool


class McpToolOut(BaseModel):
    """Response schema for a single discovered MCP tool."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    enabled: bool


class McpServerOut(BaseModel):
    """Response schema for an MCP server with its tools.

    Note: ``headers`` is intentionally omitted — auth headers are secrets and are
    write-only over the API (never echoed back in responses).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    enabled: bool
    last_connected_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    tools: list[McpToolOut]


class ChatPrefOut(BaseModel):
    """Response schema for a thread's per-user preferences."""

    model_config = ConfigDict(from_attributes=True)

    thread_id: UUID
    is_favorite: bool
    model: str | None
    mode: AgentMode


class ChatPrefUpsert(BaseModel):
    """Request schema to set a thread's favorite flag, selected model, and agent mode."""

    is_favorite: bool = False
    model: str | None = Field(default=None, max_length=200)
    mode: AgentMode = "fast"
