"""Audit log model and repository helper tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.audit.repository import AUDITED_ENTITY_TYPES, list_audit_events, record_audit_event


def test_record_authoring_event(db_session: Session) -> None:
    """The helper persists a single audit event with all required fields."""
    event = record_audit_event(
        db_session,
        actor_id="user:alice",
        action="create",
        entity_type="SourceReference",
        entity_id="src-001",
        source_subsystem="research-importer",
        before_summary=None,
        after_summary={"title": "Quantum Mechanics, 3e", "doi": "10.1234/qm"},
    )
    db_session.commit()

    assert event.id is not None
    db_session.expire_all()
    stored = db_session.get(AuditLog, event.id)
    assert stored is not None
    assert stored.actor_id == "user:alice"
    assert stored.action == "create"
    assert stored.entity_type == "SourceReference"
    assert stored.entity_id == "src-001"
    assert stored.before_summary is None
    assert stored.after_summary == {"title": "Quantum Mechanics, 3e", "doi": "10.1234/qm"}
    assert stored.source_subsystem == "research-importer"
    assert stored.occurred_at is not None


def test_record_audit_event_sets_default_timestamp(db_session: Session) -> None:
    """When ``occurred_at`` is omitted the helper stamps a UTC-aware time."""
    before = datetime.now(UTC) - timedelta(seconds=1)
    event = record_audit_event(
        db_session,
        actor_id="system",
        action="update",
        entity_type="Prompt",
        entity_id="prompt-7",
        source_subsystem="api",
        after_summary={"version": 2},
    )
    db_session.commit()

    after = datetime.now(UTC) + timedelta(seconds=1)
    db_session.expire_all()
    stored = db_session.get(AuditLog, event.id)
    assert stored is not None
    assert stored.occurred_at.tzinfo is not None
    assert before <= stored.occurred_at <= after


def test_list_audit_events_filters_by_entity_type(db_session: Session) -> None:
    """``list_audit_events`` returns only rows that match the entity filter."""
    record_audit_event(
        db_session,
        actor_id="user:alice",
        action="create",
        entity_type="SourceReference",
        entity_id="src-001",
        source_subsystem="research-importer",
    )
    record_audit_event(
        db_session,
        actor_id="user:bob",
        action="create",
        entity_type="KnowledgeNode",
        entity_id="node-001",
        source_subsystem="graph-importer",
    )
    record_audit_event(
        db_session,
        actor_id="user:alice",
        action="update",
        entity_type="SourceReference",
        entity_id="src-001",
        source_subsystem="research-importer",
    )
    db_session.commit()

    only_sources = list_audit_events(db_session, entity_type="SourceReference")

    assert {event.entity_type for event in only_sources} == {"SourceReference"}
    assert len(only_sources) == 2


def test_list_audit_events_filters_by_actor(db_session: Session) -> None:
    """``list_audit_events`` returns only rows that match the actor filter."""
    record_audit_event(
        db_session,
        actor_id="user:alice",
        action="create",
        entity_type="Prompt",
        entity_id="p-1",
        source_subsystem="api",
    )
    record_audit_event(
        db_session,
        actor_id="user:carol",
        action="update",
        entity_type="Prompt",
        entity_id="p-1",
        source_subsystem="api",
    )
    db_session.commit()

    only_carol = list_audit_events(db_session, actor_id="user:carol")

    assert [event.actor_id for event in only_carol] == ["user:carol"]


def test_list_audit_events_orders_newest_first(db_session: Session) -> None:
    """Results come back in reverse chronological order."""
    base = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    record_audit_event(
        db_session,
        actor_id="user:alice",
        action="create",
        entity_type="Rubric",
        entity_id="rub-1",
        source_subsystem="api",
        occurred_at=base,
    )
    record_audit_event(
        db_session,
        actor_id="user:alice",
        action="update",
        entity_type="Rubric",
        entity_id="rub-1",
        source_subsystem="api",
        occurred_at=base + timedelta(hours=1),
    )
    db_session.commit()

    events = list_audit_events(db_session, entity_type="Rubric")

    assert [event.action for event in events] == ["update", "create"]


def test_audited_entity_types_match_plan() -> None:
    """The documented audited entities match the Milestone 2 audit-log spec."""
    expected = {"KnowledgeNode", "KnowledgeEdge", "Prompt", "SourceReference", "Rubric"}
    assert expected == AUDITED_ENTITY_TYPES


def test_audit_events_table_is_created_by_base_metadata(db_session: Session) -> None:
    """``Base.metadata.create_all`` creates ``audit_events`` with required columns."""
    bind = db_session.bind
    assert bind is not None
    inspector = inspect(bind)
    assert "audit_events" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("audit_events")}
    expected_columns = {
        "id",
        "actor_id",
        "action",
        "entity_type",
        "entity_id",
        "before_summary",
        "after_summary",
        "source_subsystem",
        "occurred_at",
    }
    assert expected_columns.issubset(columns)


def test_alembic_audit_events_migration_is_registered() -> None:
    """The audit_events Alembic revision sits on top of user/learner tables."""
    config = Config(Path("alembic.ini"))
    script_directory = ScriptDirectory.from_config(config)

    revision_id = "20260525_0003"
    revision = script_directory.get_revision(revision_id)
    assert revision is not None
    assert revision.down_revision == "20260525_0002"
    assert revision_id in {script.revision for script in script_directory.walk_revisions()}
