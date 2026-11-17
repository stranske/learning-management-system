"""Migration tests for the attempts table."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from lms.auth.models import User, utc_now
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner, LearningGoal
from lms.prompts.models import Prompt, PromptVersion
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
        # Even a matching, currently published prompt cannot establish which
        # version or task metadata a historical attempt originally presented.
        with Session(engine) as session:
            prompt = Prompt(
                id="prompt-1",
                target_node=KnowledgeNode(
                    title="Algebra", knowledge_type="procedural", ownership_scope="personal"
                ),
                learning_goal=LearningGoal(
                    title="Explain algebra",
                    knowledge_type="procedural",
                    ownership_scope="personal",
                    learner=Learner(
                        display_name="Learner",
                        user=User(username="legacy-learner", display_name="Learner"),
                    ),
                ),
                knowledge_type="procedural",
                intended_cognitive_action="explain",
                demand_level="high",
                expected_answer_form="short-text",
                authoring_method="human-authored",
                authoring_actor="author-1",
                status="published",
                reviewing_actor="reviewer-1",
                approval_timestamp=utc_now(),
                versions=[
                    PromptVersion(
                        id=f"version-{number}",
                        version_number=number,
                        body=f"Wording {number}",
                        created_by="author-1",
                    )
                    for number in (1, 2)
                ],
            )
            session.add(prompt)
            session.commit()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO attempts (id, learner_id, prompt_id, response_text, feedback) "
                    "VALUES (:id, 'learner-1', :prompt_id, 'Old answer', '{}')"
                ),
                [
                    {"id": "legacy-1", "prompt_id": "prompt-1"},
                    {"id": "legacy-2", "prompt_id": "synthetic-prompt"},
                ],
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT prompt_version_id, task_context, response_text FROM attempts "
                    "ORDER BY id"
                )
            ).all()
        assert [tuple(row) for row in rows] == [
            (None, None, "Old answer"),
            (None, None, "Old answer"),
        ]
        indexes = inspect(engine).get_indexes("attempts")
        assert any(index["column_names"] == ["prompt_version_id"] for index in indexes)
        foreign_keys = inspect(engine).get_foreign_keys("attempts")
        assert any(
            fk["constrained_columns"] == ["prompt_version_id"]
            and fk["referred_table"] == "prompt_versions"
            and fk["referred_columns"] == ["id"]
            and fk["options"]["ondelete"] == "RESTRICT"
            for fk in foreign_keys
        )
        command.downgrade(config, "20260924_0036")
        assert {"task_context", "prompt_version_id"}.isdisjoint(
            column["name"] for column in inspect(engine).get_columns("attempts")
        )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM attempts")).scalar_one() == 2
    finally:
        engine.dispose()
        get_settings.cache_clear()
