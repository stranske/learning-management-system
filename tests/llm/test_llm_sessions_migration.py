"""Migration tests for the llm_sessions table."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from lms.settings import get_settings


def test_alembic_upgrade_head_creates_llm_sessions_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``alembic upgrade head`` should materialize the llm_sessions table."""
    db_path = tmp_path / "migration.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(db_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "llm_sessions" in tables

        check_constraints = inspector.get_check_constraints("llm_sessions")
        names = {c["name"] for c in check_constraints}
        assert "ck_llm_sessions_trace_class_valid" in names
        assert "ck_llm_sessions_mode_valid" in names
        assert "ck_llm_sessions_coaching_intensity_valid" in names
        assert "ck_llm_sessions_trace_control_state_valid" in names
        columns = {column["name"] for column in inspector.get_columns("llm_sessions")}
        assert {
            "coaching_intensity",
            "trace_control_state",
            "transcript_deleted_at",
        }.issubset(columns)
    finally:
        engine.dispose()


def test_llm_sessions_trace_class_constraint_rejects_unknown_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trace_class CHECK constraint blocks values outside the enum."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    db_path = tmp_path / "constraints.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")

    engine = create_engine(db_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO llm_sessions ("
                        "id, mode, trace_class, provider, model, "
                        "input_tokens, output_tokens, cost_micro_usd, "
                        "redaction_applied, redacted_span_count, "
                        "external_export_allowed, is_replay, created_at"
                        ") VALUES ("
                        "'bad-1', 'study-coach', 'not-a-class', 'fake', 'fake-model', "
                        "0, 0, 0, 0, 0, 1, 0, CURRENT_TIMESTAMP"
                        ")"
                    )
                )
    finally:
        engine.dispose()
