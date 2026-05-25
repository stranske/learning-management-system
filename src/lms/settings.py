"""Application settings for the LMS backend."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    database_url: str = Field(
        default="postgresql+psycopg://lms:lms@localhost:5432/lms",
        description="SQLAlchemy database URL for the LMS Postgres database.",
    )
    database_echo: bool = Field(
        default=False,
        description="Enable SQLAlchemy SQL echo logging for local debugging.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
