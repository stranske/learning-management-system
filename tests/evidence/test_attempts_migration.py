"""Migration tests for the attempts table."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

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
    finally:
        engine.dispose()

    assert "attempts" in tables
