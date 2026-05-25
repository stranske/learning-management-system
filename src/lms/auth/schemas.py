"""Pydantic schemas for local auth endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserCreate(BaseModel):
    """Input for creating a local-development user."""

    username: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def require_email_or_username(self) -> UserCreate:
        """Require at least one stable login identifier."""
        if not self.username and not self.email:
            msg = "Either username or email is required."
            raise ValueError(msg)
        return self


class UserRead(BaseModel):
    """Serializable user identity."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None
    username: str | None
    display_name: str
    is_local: bool
    created_at: datetime
    updated_at: datetime
