"""SQLAlchemy engine and session construction."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from lms.settings import get_settings


def make_engine(database_url: str | None = None, *, echo: bool | None = None) -> Engine:
    """Create a SQLAlchemy engine from settings or an explicit URL."""
    settings = get_settings()
    return create_engine(
        database_url or settings.database_url,
        echo=settings.database_echo if echo is None else echo,
        future=True,
        pool_pre_ping=True,
    )


@lru_cache
def get_engine() -> Engine:
    """Return the configured runtime engine."""
    return make_engine()


SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Generator[Session]:
    """Provide a transactional session scope for scripts and services."""
    session = SessionLocal(bind=get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session]:
    """FastAPI dependency that yields a request-scoped database session."""
    with session_scope() as session:
        yield session
