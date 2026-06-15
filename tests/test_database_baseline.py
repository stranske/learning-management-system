"""Tests for database settings, sessions, and baseline migrations."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from lms.db import session as db_session_module
from lms.db.base import Base
from lms.db.session import get_session, make_engine, session_scope
from lms.db.version_table import ensure_version_table_width
from lms.settings import Settings


def test_settings_reads_database_url() -> None:
    settings = Settings(database_url="postgresql+psycopg://user:pass@localhost:5432/test_lms")

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost:5432/test_lms"


def test_settings_normalizes_render_postgres_url_to_psycopg() -> None:
    # Render injects a driverless ``postgresql://`` URL, which SQLAlchemy would
    # route to psycopg2 — a package this project does not install. Pin it to
    # the psycopg 3 driver so engine creation (runtime + Alembic) succeeds.
    settings = Settings(database_url="postgresql://user:pass@db.internal:5432/lms")

    assert settings.database_url == "postgresql+psycopg://user:pass@db.internal:5432/lms"


def test_settings_normalizes_legacy_postgres_scheme() -> None:
    settings = Settings(database_url="postgres://user:pass@db.internal:5432/lms")

    assert settings.database_url == "postgresql+psycopg://user:pass@db.internal:5432/lms"


def test_settings_preserves_explicit_psycopg_driver() -> None:
    url = "postgresql+psycopg://user:pass@db.internal:5432/lms"

    assert Settings(database_url=url).database_url == url


def test_settings_leaves_non_postgres_url_untouched() -> None:
    url = "sqlite+pysqlite:///:memory:"

    assert Settings(database_url=url).database_url == url


def test_make_engine_uses_explicit_url() -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")

    try:
        assert str(engine.url) == "sqlite+pysqlite:///:memory:"
    finally:
        engine.dispose()


def test_ensure_version_table_width_is_noop_on_sqlite() -> None:
    # The widening is Postgres-only (SQLite does not enforce VARCHAR length).
    # On SQLite the helper must do nothing — in particular it must NOT create
    # the alembic_version table, which would mean the postgres-only guard was
    # lost and the migration entrypoint started issuing Postgres DDL elsewhere.
    engine = make_engine("sqlite+pysqlite:///:memory:")

    try:
        with engine.connect() as connection:
            ensure_version_table_width(connection)
            assert not inspect(connection).has_table("alembic_version")
    finally:
        engine.dispose()


def test_session_scope_commits_and_closes(monkeypatch: Any) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(db_session_module, "get_engine", lambda: engine)

    try:
        with session_scope() as session:
            assert session.execute(text("select 1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_session_scope_rolls_back_on_error(monkeypatch: Any) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(db_session_module, "get_engine", lambda: engine)

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE scratch (id INTEGER PRIMARY KEY)"))

        try:
            with session_scope() as session:
                session.execute(text("INSERT INTO scratch (id) VALUES (1)"))
                raise RuntimeError("force rollback")
        except RuntimeError as exc:
            assert str(exc) == "force rollback"

        with engine.connect() as conn:
            remaining = conn.execute(text("SELECT COUNT(*) FROM scratch")).scalar_one()
            assert remaining == 0
    finally:
        engine.dispose()


def test_get_session_yields_request_scoped_session(monkeypatch: Any) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(db_session_module, "get_engine", lambda: engine)

    try:
        session_generator = get_session()
        session = next(session_generator)
        assert session.execute(text("select 1")).scalar_one() == 1
        with suppress(StopIteration):
            next(session_generator)
    finally:
        engine.dispose()


def test_get_session_rolls_back_uncommitted_work(monkeypatch: Any) -> None:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(db_session_module, "get_engine", lambda: engine)

    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE scratch (id INTEGER PRIMARY KEY)"))

        session_generator = get_session()
        session = next(session_generator)
        session.execute(text("INSERT INTO scratch (id) VALUES (1)"))
        with suppress(StopIteration):
            next(session_generator)

        with engine.connect() as conn:
            remaining = conn.execute(text("SELECT COUNT(*) FROM scratch")).scalar_one()
            assert remaining == 0
    finally:
        engine.dispose()


def test_db_session_fixture_is_usable(db_session: Session) -> None:
    result = db_session.execute(text("select 1")).scalar_one()

    assert result == 1


def test_declarative_base_uses_migration_naming_convention() -> None:
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"
    fk_convention = Base.metadata.naming_convention["fk"]
    assert isinstance(fk_convention, str)
    assert fk_convention.startswith("fk_%(table_name)s")


def test_alembic_baseline_revision_is_discoverable() -> None:
    config = Config(Path("alembic.ini"))
    script_directory = ScriptDirectory.from_config(config)

    bases = script_directory.get_bases()
    baseline = script_directory.get_revision("20260525_0001")

    assert bases == ["20260525_0001"]
    assert baseline is not None
    assert baseline.down_revision is None
