"""Pydantic schemas for local auth endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    """Input for creating a local-development user."""

    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class UserRead(BaseModel):
    """Serializable user identity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None
    username: str
    display_name: str
    is_local: bool
    created_at: datetime
    updated_at: datetime
