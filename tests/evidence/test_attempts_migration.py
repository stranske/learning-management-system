"""Migration tests for the attempts table."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from lms.settings import get_settings


def test_alembic_upgrade_head_creates_attempts_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrading to head should materialize the attempts table."""
    db_path = tmp_path / "migration.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(db_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        columns = {column["name"]: column for column in inspect(engine).get_columns("attempts")}
        assert columns["prompt_version_id"]["nullable"] is True
        assert columns["task_context"]["nullable"] is True
    finally:
        engine.dispose()

    assert "attempts" in tables


def test_alembic_upgrade_head_creates_evidence_records_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrading to head should materialize verbose evidence records."""
    db_path = tmp_path / "migration.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(db_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "evidence_records" in tables


def test_attempt_context_migration_preserves_unknown_legacy_rows_and_downgrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20260924_0036")
    engine = create_engine(db_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO attempts (id, learner_id, prompt_id, response_text, feedback) "
                    "VALUES ('legacy-1', 'learner-1', 'prompt-1', 'Old answer', '{}')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT prompt_version_id, task_context, response_text FROM attempts "
                    "WHERE id = 'legacy-1'"
                )
            ).one()
        assert row == (None, None, "Old answer")
        indexes = inspect(engine).get_indexes("attempts")
        assert any(index["column_names"] == ["prompt_version_id"] for index in indexes)
        foreign_keys = inspect(engine).get_foreign_keys("attempts")
        assert any(fk["referred_table"] == "prompt_versions" for fk in foreign_keys)
        command.downgrade(config, "20260924_0036")
        assert "task_context" not in {
            column["name"] for column in inspect(engine).get_columns("attempts")
        }
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM attempts")).scalar_one() == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()
