"""Pydantic schemas for local auth endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserCreate(BaseModel):
    """Input for creating a local-development user."""

    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email_shape(cls, value: str | None) -> str | None:
        """Reject obvious non-address strings without adding a runtime dependency."""
        if value is None:
            return value
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must contain a local part and domain")
        local, domain = value.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("email must contain a local part and domain")
        return value


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
