"""Application settings for the LMS backend."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def read_anthropic_api_key_from_env() -> str | None:
    """Read the Anthropic API key from any of the documented env var names.

    Pydantic's ``AliasChoices`` handles this for the field declaration below;
    this helper is public so non-Settings call sites (e.g. CLI utilities)
    can resolve the same key without instantiating ``Settings``.
    """
    for name in ("CLAUDE_API_STRANSKE", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    return None


_read_anthropic_api_key_from_env = read_anthropic_api_key_from_env


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

    @field_validator("database_url")
    @classmethod
    def _pin_psycopg_driver(cls, value: str) -> str:
        """Pin driverless Postgres URLs to the psycopg (v3) driver.

        Render injects ``DATABASE_URL`` as ``postgresql://…`` (and some
        platforms still emit the legacy ``postgres://``), which SQLAlchemy maps
        to the **psycopg2** dialect. This project only ships psycopg 3
        (``psycopg[binary]``), so a driverless URL makes both the runtime engine
        (``lms.db.session.make_engine``) and the Alembic ``upgrade head``
        pre-deploy step raise ``ModuleNotFoundError: No module named 'psycopg2'``
        — the observed Render pre-deploy failure. Rewriting the scheme to
        ``postgresql+psycopg://`` selects the installed driver. URLs that already
        name a driver (``postgresql+psycopg://``, ``sqlite+pysqlite://``, …) are
        left untouched.
        """
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

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

    # LLM provider configuration. When ``anthropic_api_key`` is set, the LLM
    # client wrapper registers the Anthropic provider and uses it as the
    # default; when unset, the wrapper falls back to ``FakeProvider`` so dev
    # environments without keys still produce deterministic output. The field
    # accepts three env-var spellings (CLAUDE_API_STRANSKE is the project-owner
    # convention; ANTHROPIC_API_KEY is the SDK convention; CLAUDE_API_KEY is
    # an alias) so it works in both Render-deployed and local-dev contexts.
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "anthropic_api_key",
            "claude_api_stranske",
            "claude_api_key",
            "CLAUDE_API_STRANSKE",
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
        ),
        description=(
            "Anthropic API key for the live LLM provider. Leave unset in CI / unit "
            "tests to keep the fake provider as the default."
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
