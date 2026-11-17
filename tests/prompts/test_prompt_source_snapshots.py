"""Tests for prompt version source snapshots and drift acknowledgements."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

import lms.prompts.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.prompts.models import (
    UNKNOWN_HASH_ALGORITHM,
    UNKNOWN_SOURCE_HASH,
    Prompt,
    PromptDriftAcknowledgement,
    PromptVersion,
    PromptVersionSourceSnapshot,
)
from lms.sources.models import SourceReference


def test_alembic_snapshot_migration_is_registered() -> None:
    """The snapshot migration chains from the knowledge-edge revision."""
    script_directory = ScriptDirectory.from_config(Config(Path("alembic.ini")))
    revision = script_directory.get_revision("20261117_0038")
    assert revision is not None
    assert revision.down_revision == "20261117_0037"


def test_legacy_prompt_versions_have_no_source_snapshots(db_session: Session) -> None:
    """Pre-migration prompt versions remain valid without snapshot rows."""
    source = SourceReference(
        source_type="internal-note",
        stable_locator="note:legacy",
        content_hash="abc123",
        hash_algorithm="sha256",
    )
    prompt = Prompt(
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="factual",
        intended_cognitive_action="recall",
        demand_level="low",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="user:alice",
        source_references=[source],
    )
    version = PromptVersion(version_number=1, body="Legacy prompt", created_by="user:alice")
    prompt.versions.append(version)
    db_session.add(prompt)
    db_session.flush()

    assert not version.source_snapshots
    assert UNKNOWN_SOURCE_HASH == "unknown"
    assert UNKNOWN_HASH_ALGORITHM == "unknown"


def test_prompt_version_source_snapshot_round_trip(db_session: Session) -> None:
    """Snapshot rows persist immutable source hashes per prompt version."""
    source = SourceReference(
        source_type="internal-note",
        stable_locator="note:snapshot",
        content_hash="hash-v1",
        hash_algorithm="sha256",
    )
    prompt = Prompt(
        target_node_id="node-2",
        learning_goal_id="goal-2",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="user:bob",
        source_references=[source],
    )
    version = PromptVersion(version_number=1, body="Snapshotted prompt", created_by="user:bob")
    prompt.versions.append(version)
    db_session.add(prompt)
    db_session.flush()
    version.source_snapshots.append(
        PromptVersionSourceSnapshot(
            source_reference=source,
            content_hash=source.content_hash,
            hash_algorithm=source.hash_algorithm,
        )
    )
    db_session.commit()

    loaded = db_session.scalar(select(PromptVersion).where(PromptVersion.id == version.id))
    assert loaded is not None
    assert len(loaded.source_snapshots) == 1
    snapshot = loaded.source_snapshots[0]
    assert snapshot.content_hash == "hash-v1"
    assert snapshot.hash_algorithm == "sha256"
    assert snapshot.source_reference_id == source.id


def test_prompt_drift_acknowledgement_is_per_prompt_version(db_session: Session) -> None:
    """Drift acknowledgements tie to one prompt and version pair."""
    source = SourceReference(
        source_type="internal-note",
        stable_locator="note:ack",
        content_hash="hash-ack",
        hash_algorithm="sha256",
    )
    prompt = Prompt(
        target_node_id="node-3",
        learning_goal_id="goal-3",
        knowledge_type="factual",
        intended_cognitive_action="recall",
        demand_level="low",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="user:carol",
        source_references=[source],
    )
    version = PromptVersion(version_number=1, body="Ack prompt", created_by="user:carol")
    prompt.versions.append(version)
    db_session.add(prompt)
    db_session.flush()

    prompt.drift_acknowledgements.append(
        PromptDriftAcknowledgement(
            prompt_version_id=version.id,
            acknowledged_by="user:carol",
        )
    )
    db_session.commit()

    loaded = db_session.scalar(select(Prompt).where(Prompt.id == prompt.id))
    assert loaded is not None
    assert len(loaded.drift_acknowledgements) == 1
    assert loaded.drift_acknowledgements[0].prompt_version_id == version.id


def test_new_tables_exist_on_fresh_metadata_create_all() -> None:
    """SQLAlchemy metadata includes the new snapshot tables."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    table_names = set(inspect(engine).get_table_names())
    assert "prompt_version_source_snapshots" in table_names
    assert "prompt_drift_acknowledgements" in table_names
