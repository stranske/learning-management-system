"""Pydantic schemas for learner endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LearnerCreate(BaseModel):
    """Input for creating a learner profile."""

    user_id: str
    display_name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    locale: str = Field(default="en-US", min_length=1, max_length=20)


class LearnerRead(BaseModel):
    """Serializable learner profile."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    display_name: str
    timezone: str
    locale: str
    created_at: datetime
    updated_at: datetime
