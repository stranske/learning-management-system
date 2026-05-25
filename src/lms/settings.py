"""Application settings for the LMS backend."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    database_url: str = Field(
        default="postgresql+psycopg://localhost:5432/lms_dev",
        description=(
            "SQLAlchemy database URL for the LMS Postgres database. The default has no "
            "embedded credentials so missing local configuration fails loudly; set "
            "DATABASE_URL in a private .env file or environment secret."
        ),
    )
    database_echo: bool = Field(
        default=False,
        description="Enable SQLAlchemy SQL echo logging for local debugging.",
    )
    enable_local_identity_routes: bool = Field(
        default=False,
        description=(
            "Expose local-development user and learner creation routes. Keep disabled "
            "for production deployments."
        ),
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
