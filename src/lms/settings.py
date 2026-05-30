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

    # Auth + session configuration. ``auth_required`` is the master gate that
    # the Render-deployed instance flips on; in local dev / pytest it stays
    # off so the existing local-dev shortcut (``get_or_create_local_dev_user``)
    # keeps working without a real login flow. See docs/architecture/auth.md.
    auth_required: bool = Field(
        default=False,
        description=(
            "When true, unauthenticated requests to non-login UI routes are redirected "
            "to /login and unauthenticated API requests return 401. Enabled on the "
            "deployed instance (Render) via the AUTH_REQUIRED env var; left off for "
            "local dev and the test suite so the local-dev user shortcut keeps working."
        ),
    )
    auth_secret_key: str = Field(
        default="dev-secret-do-not-use-in-production-change-via-env-var",
        description=(
            "Secret key used by Starlette SessionMiddleware to sign session cookies. "
            "MUST be overridden on deployed instances via AUTH_SECRET_KEY; the default "
            "is only safe for local development."
        ),
    )
    session_cookie_name: str = Field(
        default="lms_session",
        description="Name of the signed session cookie set by SessionMiddleware.",
    )
    session_max_age_seconds: int = Field(
        default=60 * 60 * 24 * 14,
        description=(
            "Session cookie max-age in seconds (default: 14 days). Sessions silently "
            "extend on each request via SessionMiddleware's same_site/secure defaults."
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
