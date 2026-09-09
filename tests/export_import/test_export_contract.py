"""Tests for the v1 typed JSONL export contract."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import DateTime, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from tests.export_import.test_m5_export_contract import _seed_m5_runtime_records

from lms.audit.models import AuditLog, UTCDateTime
from lms.auth.models import User
from lms.cases.models import WorkProduct
from lms.db.base import Base
from lms.evidence.models import Attempt
from lms.export_import import (
    EXPORT_ORDER,
    MODEL_BY_TYPE,
    ExportImportError,
    export_jsonl,
    import_jsonl,
)
from lms.feedback.models import (
    FeedbackTemplate,
    Hint,
    HintReveal,
    ModelAnswer,
    ModelAnswerReveal,
    RevisionRequest,
)
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.learners.models import LearnerReflection
from lms.llm.models import LearningInteractionSkill, LLMFeedbackEvent, LLMSession
from lms.llm.proposals import LLMProposal
from lms.maintenance.models import DraftRejection, GradeDispute, MaintenanceItem
from lms.scheduling.models import ReviewCardState
from lms.sources.models import SourceReference


def test_export_emits_jsonl_typed_records_in_dependency_order(db_session: Session) -> None:
    user = User(id="user-1", email="ada@example.com", username="ada", display_name="Ada")
    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator="docs/demo.md#one",
        content_hash="hash",
        source_visibility="local-only",
    )
    parent = KnowledgeNode(
        id="node-1",
        title="Parent",
        knowledge_type="factual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
        source_reference_id=source.id,
    )
    child = KnowledgeNode(
        id="node-2",
        title="Child",
        knowledge_type="factual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
    )
    edge = KnowledgeEdge(
        id="edge-1",
        source_node_id=parent.id,
        target_node_id=child.id,
        edge_type="prerequisite",
        source_scope="personal",
        target_scope="personal",
        status="published",
    )
    db_session.add_all([user, source, parent, child, edge])
    db_session.commit()

    records = [json.loads(line) for line in export_jsonl(db_session)]

    assert [record["type"] for record in records] == [
        "User",
        "SourceReference",
        "KnowledgeNode",
        "KnowledgeNode",
        "KnowledgeEdge",
    ]
    assert records[0]["schema_version"] == 1
    assert records[0]["record"]["id"] == "user-1"
    assert "email" not in records[0]["record"]


def test_export_requires_confirmation_for_all_pii(db_session: Session) -> None:
    db_session.add(User(id="user-1", email="ada@example.com", username="ada", display_name="Ada"))
    db_session.commit()

    try:
        list(export_jsonl(db_session, include_pii="all"))
    except ExportImportError as exc:
        assert "requires --yes-i-mean-it" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected confirmation failure")


@pytest.mark.parametrize("include_pii", ["never", "all"])
@pytest.mark.parametrize("include_source_content", ["public-only", "all"])
@pytest.mark.parametrize("include_llm_traces", ["evidence-grade-only", "all"])
def test_export_excludes_password_hash_and_users_remain_importable(
    db_session: Session,
    tmp_path: Path,
    include_pii: str,
    include_source_content: str,
    include_llm_traces: str,
) -> None:
    password_hash = "synthetic-password-hash-for-export-regression"
    user = User(
        id="user-with-password",
        email="ada@example.com",
        username="ada",
        display_name="Ada",
        password_hash=password_hash,
    )
    db_session.add(user)
    db_session.commit()

    lines = list(
        export_jsonl(
            db_session,
            include_pii=include_pii,
            include_source_content=include_source_content,
            include_llm_traces=include_llm_traces,
            confirm_all="all" in (include_pii, include_source_content, include_llm_traces),
        )
    )
    assert len(lines) == 1
    record = json.loads(lines[0])["record"]
    assert "password_hash" not in record
    assert password_hash not in lines[0]
    assert ("email" in record) == (include_pii == "all")
    db_session.refresh(user)
    assert user.password_hash == password_hash

    path = tmp_path / "users.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            summary = import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            imported = destination.get(User, user.id)
            assert summary.counts == {"User": 1}
            assert imported is not None
            assert imported.username == user.username
            assert imported.password_hash is None
    finally:
        engine.dispose()


M5_M6_MODELS = (
    Hint,
    HintReveal,
    ModelAnswer,
    ModelAnswerReveal,
    RevisionRequest,
    FeedbackTemplate,
    WorkProduct,
    LearnerReflection,
)


@pytest.fixture
def m5_m6_records(db_session: Session) -> list[str]:
    """Export real persisted records with every new foreign key populated."""
    _seed_m5_runtime_records(db_session)
    db_session.add_all(
        [
            Hint(
                id="hint-1",
                prompt_id="prompt-1",
                hint_text="Recall the prerequisite.",
                reveal_order=1,
                authoring_actor="author",
                source_citation_metadata={"page": 2},
            ),
            HintReveal(
                id="hint-reveal-1",
                hint_id="hint-1",
                learner_id="learner-1",
                prompt_id="prompt-1",
                attempt_id="attempt-1",
                initiated_by="learner",
            ),
            ModelAnswer(
                id="answer-1",
                prompt_id="prompt-1",
                rubric_id="rubric-1",
                answer_body="A complete explanation.",
                authoring_actor="author",
                source_citation_metadata={"page": 3},
            ),
            ModelAnswerReveal(
                id="answer-reveal-1",
                model_answer_id="answer-1",
                learner_id="learner-1",
                prompt_id="prompt-1",
                attempt_id="attempt-1",
                initiated_by="instructor",
            ),
            RevisionRequest(
                id="revision-1",
                learner_id="learner-1",
                feedback_record_id="feedback-record-1",
                feedback_action_id="feedback-action-1",
                prompt_id="prompt-1",
                original_attempt_id="attempt-1",
                revised_attempt_id="attempt-1",
                work_product_id="work-1",
                result_note="Revise the rationale.",
                scheduler_hook={"next": "review"},
            ),
            FeedbackTemplate(
                id="template-1",
                name="Coaching",
                template_body="Review {goal}.",
                placeholder_schema={"goal": "string"},
                feedback_level="coaching",
                action_type="revision",
                ownership_scope="personal",
                authoring_actor="author",
                misconception_pattern_id="pattern-1",
                feedback_action_id="feedback-action-1",
                knowledge_node_ids=["node-1"],
            ),
            WorkProduct(
                id="work-1",
                case_id="case-1",
                case_step_id="case-step-1",
                learner_id="learner-1",
                rubric_id="rubric-1",
                prompt_id="prompt-1",
                submission_type="rationale",
                body="My revised rationale.",
                rubric_score_id="rubric-score-1",
                revision_request_id="revision-1",
            ),
            LearnerReflection(
                id="reflection-1",
                learner_id="learner-1",
                knowledge_node_id="node-1",
                prompt="What changed?",
                response="I connected the prerequisite.",
            ),
        ]
    )
    db_session.commit()
    return list(export_jsonl(db_session))


def test_export_contract_includes_m5_m6_domain_entities(
    m5_m6_records: list[str],
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in m5_m6_records]
    expected_types = {model.__name__ for model in M5_M6_MODELS}
    assert expected_types <= MODEL_BY_TYPE.keys(), "missing entity type in import registry"
    assert expected_types <= {record["type"] for record in records}, "missing entity type in export"
    by_type = {record["type"]: record["record"] for record in records}
    positions = {record["type"]: i for i, record in enumerate(records)}
    type_by_table = {model.__tablename__: model.__name__ for model in MODEL_BY_TYPE.values()}
    for model in M5_M6_MODELS:
        # Verify emitted order against the actual schema, independently of DEPENDENCIES.
        for fk in model.__table__.foreign_keys:
            assert positions[type_by_table[fk.column.table.name]] < positions[model.__name__]

    path = tmp_path / "m5-m6.jsonl"
    path.write_text("\n".join(m5_m6_records) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            dry_run = import_jsonl(destination, path, dry_run=True)
            applied = import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            assert dry_run.counts == applied.counts
            for model in M5_M6_MODELS:
                assert applied.counts[model.__name__] == 1
                assert destination.get(model, by_type[model.__name__]["id"]) is not None
            restored = {
                entry["type"]: entry["record"]
                for entry in map(json.loads, export_jsonl(destination))
            }
            # Includes IDs, FK/soft links, text, JSON metadata and timestamps.
            for record_type in expected_types:
                assert restored[record_type] == by_type[record_type]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "model,field",
    [
        (model, fk.parent.name)
        for model in M5_M6_MODELS
        for fk in sorted(model.__table__.foreign_keys, key=lambda fk: fk.parent.name)
    ]
    + [
        (HintReveal, "learner_id"),
        (HintReveal, "prompt_id"),
        (ModelAnswerReveal, "learner_id"),
        (ModelAnswerReveal, "prompt_id"),
        (RevisionRequest, "learner_id"),
        (RevisionRequest, "prompt_id"),
        (RevisionRequest, "work_product_id"),
        (WorkProduct, "learner_id"),
        (WorkProduct, "prompt_id"),
        (FeedbackTemplate, "knowledge_node_ids"),
    ],
)
def test_import_rejects_missing_m5_m6_dependency(
    m5_m6_records: list[str],
    tmp_path: Path,
    model: type[Base],
    field: str,
) -> None:
    records = [json.loads(line) for line in m5_m6_records]
    entry = next(record for record in records if record["type"] == model.__name__)
    entry["record"][field] = (
        ["missing-parent"] if field == "knowledge_node_ids" else "missing-parent"
    )
    path = tmp_path / "missing-parent.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            for dry_run in (True, False):
                with pytest.raises(
                    ExportImportError,
                    match=f"{model.__name__}:.*references missing .*:missing-parent",
                ):
                    import_jsonl(destination, path, dry_run=dry_run)
                assert destination.get(User, "user-1") is None
    finally:
        engine.dispose()


MAINTENANCE_LLM_MODELS = (
    LearningInteractionSkill,
    AuditLog,
    MaintenanceItem,
    GradeDispute,
    DraftRejection,
    ReviewCardState,
    LLMFeedbackEvent,
    LLMProposal,
)


@pytest.fixture
def maintenance_llm_records(db_session: Session) -> list[str]:
    """Export real persisted rows for the maintenance, dispute and LLM entities."""
    _seed_m5_runtime_records(db_session)
    now = datetime(2026, 6, 1, tzinfo=UTC)
    db_session.add_all(
        [
            KnowledgeNode(
                id="node-2",
                title="Second",
                knowledge_type="conceptual",
                ownership_scope="personal",
                status="published",
                provenance="manual",
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            KnowledgeEdge(
                id="edge-1",
                source_node_id="node-1",
                target_node_id="node-2",
                edge_type="prerequisite",
                source_scope="personal",
                target_scope="personal",
                status="published",
            ),
            LearningInteractionSkill(
                id="skill-1",
                name="Socratic prompting",
                mode="practice",
                policy_version="2026-06-01",
                description="Ask before telling.",
                allowed_trace_classes=["evidence-grade"],
                source_citation_required=True,
            ),
            AuditLog(
                id=1,
                actor_id="author",
                action="update",
                entity_type="KnowledgeNode",
                entity_id="node-1",
                before_summary={"title": "Node"},
                after_summary={"title": "Node"},
                source_subsystem="authoring",
                occurred_at=now,
            ),
            MaintenanceItem(
                id="maintenance-item-1",
                learner_id="learner-1",
                item_type="reference_anchor",
                title="IPO count distribution",
                prompt="Where does a 400-IPO year sit?",
                source_reference_id="source-1",
                source_locator_hint="docs/demo.md#one",
                subject_label="US IPO market",
                retention_tier="warm",
                precision_mode="band",
                status="active",
                payload={"bands": [{"label": "typical", "low": 80, "high": 150}]},
                field_provenance={"bands": "source"},
                approved_at=now,
                content_as_of=now,
            ),
            GradeDispute(
                id="grade-dispute-1",
                learner_id="learner-1",
                maintenance_item_id="maintenance-item-1",
                evidence_record_id="evidence-1",
                submitted_answer="About 100 a year, 1999 was roughly 400.",
                machine_grade=0.4,
                learner_grade=0.9,
                comment="Band membership was correct.",
            ),
            DraftRejection(
                id="draft-rejection-1",
                learner_id="learner-1",
                item_type="idea",
                title="Rejected draft",
                subject_label="US IPO market",
                source_locator_hint="docs/demo.md#two",
                reason="Figure could not be verified against the source.",
                disposition="rejected",
            ),
            ReviewCardState(
                id="review-card-1",
                learner_id="learner-1",
                subject_type="maintenance_item",
                subject_id="maintenance-item-1",
                retention_tier="warm",
                card_state={"stability": 3.5, "difficulty": 5.0},
                stability=3.5,
                difficulty=5.0,
                due_at=now,
                last_review_at=now,
                review_count=2,
                lapse_count=1,
            ),
            LLMFeedbackEvent(
                id="llm-feedback-event-1",
                llm_session_id="llm-1",
                learner_id="learner-1",
                skill_id="skill-1",
                feedback_record_id="feedback-record-1",
                evidence_record_id="evidence-1",
                event_type="feedback-outcome",
                trace_class="evidence-grade",
                source_reference_ids=["source-1"],
                cost_metadata={"tokens": 42},
                event_summary="Nudged toward the prerequisite.",
                event_body="Full turn body.",
            ),
            LLMProposal(
                id="llm-proposal-1",
                llm_session_id="llm-1",
                llm_model="fake-model",
                proposed_by="author",
                knowledge_node_id="node-1",
                knowledge_edge_id="edge-1",
                prompt_id="prompt-1",
                source_reference_id="source-1",
            ),
        ]
    )
    db_session.commit()
    return list(export_jsonl(db_session))


def test_export_registry_covers_every_mapped_model() -> None:
    """Every mapped entity must be exportable; a new model must not be silently dropped."""
    mapped_types = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    registered_types = set(MODEL_BY_TYPE)
    assert mapped_types - registered_types == set(), "mapped model missing from MODEL_BY_TYPE"
    exported_types = {model.__name__ for model in EXPORT_ORDER}
    assert mapped_types - exported_types == set(), "mapped model missing from EXPORT_ORDER"
    assert registered_types == exported_types
    assert len(EXPORT_ORDER) == len(MODEL_BY_TYPE) == len(mapped_types)


def test_export_contract_includes_maintenance_dispute_and_llm_entities(
    maintenance_llm_records: list[str],
    tmp_path: Path,
) -> None:
    records = [json.loads(line) for line in maintenance_llm_records]
    expected_types = {model.__name__ for model in MAINTENANCE_LLM_MODELS}
    assert expected_types <= MODEL_BY_TYPE.keys(), "missing entity type in import registry"
    assert expected_types <= {record["type"] for record in records}, "missing entity type in export"
    by_type = {record["type"]: record["record"] for record in records}
    positions = {record["type"]: i for i, record in enumerate(records)}
    type_by_table = {model.__tablename__: model.__name__ for model in MODEL_BY_TYPE.values()}
    for model in MAINTENANCE_LLM_MODELS:
        # Verify emitted order against the actual schema, independently of DEPENDENCIES.
        for fk in model.__table__.foreign_keys:
            assert positions[type_by_table[fk.column.table.name]] < positions[model.__name__]

    path = tmp_path / "maintenance-llm.jsonl"
    path.write_text("\n".join(maintenance_llm_records) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            dry_run = import_jsonl(destination, path, dry_run=True)
            applied = import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            assert dry_run.counts == applied.counts
            for model in MAINTENANCE_LLM_MODELS:
                assert applied.counts[model.__name__] == 1
                assert destination.get(model, by_type[model.__name__]["id"]) is not None
            restored = {
                entry["type"]: entry["record"]
                for entry in map(json.loads, export_jsonl(destination))
            }
            # Includes IDs, FK/soft links, text, JSON payloads and timestamps.
            for record_type in expected_types:
                assert restored[record_type] == by_type[record_type]
    finally:
        engine.dispose()


@pytest.fixture
def all_model_records(db_session: Session) -> list[str]:
    """Seed exactly one row of every mapped model and export the full stream."""
    _seed_m5_runtime_records(db_session)
    node_two = KnowledgeNode(
        id="node-2",
        title="Second",
        knowledge_type="conceptual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
    )
    db_session.add(node_two)
    db_session.flush()
    edge = KnowledgeEdge(
        id="edge-1",
        source_node_id="node-1",
        target_node_id="node-2",
        edge_type="prerequisite",
        source_scope="personal",
        target_scope="personal",
        status="published",
    )
    db_session.add_all(
        [
            edge,
            Hint(
                id="hint-1",
                prompt_id="prompt-1",
                hint_text="Recall the prerequisite.",
                reveal_order=1,
                authoring_actor="author",
                source_citation_metadata={"page": 2},
            ),
            HintReveal(
                id="hint-reveal-1",
                hint_id="hint-1",
                learner_id="learner-1",
                prompt_id="prompt-1",
                attempt_id="attempt-1",
                initiated_by="learner",
            ),
            ModelAnswer(
                id="answer-1",
                prompt_id="prompt-1",
                rubric_id="rubric-1",
                answer_body="A complete explanation.",
                authoring_actor="author",
                source_citation_metadata={"page": 3},
            ),
            ModelAnswerReveal(
                id="answer-reveal-1",
                model_answer_id="answer-1",
                learner_id="learner-1",
                prompt_id="prompt-1",
                attempt_id="attempt-1",
                initiated_by="instructor",
            ),
            RevisionRequest(
                id="revision-1",
                learner_id="learner-1",
                feedback_record_id="feedback-record-1",
                feedback_action_id="feedback-action-1",
                prompt_id="prompt-1",
                original_attempt_id="attempt-1",
                revised_attempt_id="attempt-1",
                work_product_id="work-1",
                result_note="Revise the rationale.",
                scheduler_hook={"next": "review"},
            ),
            FeedbackTemplate(
                id="template-1",
                name="Coaching",
                template_body="Review {goal}.",
                placeholder_schema={"goal": "string"},
                feedback_level="coaching",
                action_type="revision",
                ownership_scope="personal",
                authoring_actor="author",
                misconception_pattern_id="pattern-1",
                feedback_action_id="feedback-action-1",
                knowledge_node_ids=["node-1"],
            ),
            WorkProduct(
                id="work-1",
                case_id="case-1",
                case_step_id="case-step-1",
                learner_id="learner-1",
                rubric_id="rubric-1",
                prompt_id="prompt-1",
                submission_type="rationale",
                body="My revised rationale.",
                rubric_score_id="rubric-score-1",
                revision_request_id="revision-1",
            ),
            LearnerReflection(
                id="reflection-1",
                learner_id="learner-1",
                knowledge_node_id="node-1",
                prompt="What changed?",
                response="I connected the prerequisite.",
            ),
        ]
    )
    db_session.commit()
    now = datetime(2026, 6, 1, tzinfo=UTC)
    db_session.add_all(
        [
            LearningInteractionSkill(
                id="skill-1",
                name="Socratic prompting",
                mode="practice",
                policy_version="2026-06-01",
                description="Ask before telling.",
                allowed_trace_classes=["evidence-grade"],
                source_citation_required=True,
            ),
            AuditLog(
                id=1,
                actor_id="author",
                action="update",
                entity_type="KnowledgeNode",
                entity_id="node-1",
                before_summary={"title": "Node"},
                after_summary={"title": "Node"},
                source_subsystem="authoring",
                occurred_at=now,
            ),
            MaintenanceItem(
                id="maintenance-item-1",
                learner_id="learner-1",
                item_type="reference_anchor",
                title="IPO count distribution",
                prompt="Where does a 400-IPO year sit?",
                source_reference_id="source-1",
                source_locator_hint="docs/demo.md#one",
                subject_label="US IPO market",
                retention_tier="warm",
                precision_mode="band",
                status="active",
                payload={"bands": [{"label": "typical", "low": 80, "high": 150}]},
                field_provenance={"bands": "source"},
                approved_at=now,
                content_as_of=now,
            ),
            GradeDispute(
                id="grade-dispute-1",
                learner_id="learner-1",
                maintenance_item_id="maintenance-item-1",
                evidence_record_id="evidence-1",
                submitted_answer="About 100 a year, 1999 was roughly 400.",
                machine_grade=0.4,
                learner_grade=0.9,
                comment="Band membership was correct.",
            ),
            DraftRejection(
                id="draft-rejection-1",
                learner_id="learner-1",
                item_type="idea",
                title="Rejected draft",
                subject_label="US IPO market",
                source_locator_hint="docs/demo.md#two",
                reason="Figure could not be verified against the source.",
                disposition="rejected",
            ),
            ReviewCardState(
                id="review-card-1",
                learner_id="learner-1",
                subject_type="maintenance_item",
                subject_id="maintenance-item-1",
                retention_tier="warm",
                card_state={"stability": 3.5, "difficulty": 5.0},
                stability=3.5,
                difficulty=5.0,
                due_at=now,
                last_review_at=now,
                review_count=2,
                lapse_count=1,
            ),
            LLMFeedbackEvent(
                id="llm-feedback-event-1",
                llm_session_id="llm-1",
                learner_id="learner-1",
                skill_id="skill-1",
                feedback_record_id="feedback-record-1",
                evidence_record_id="evidence-1",
                event_type="feedback-outcome",
                trace_class="evidence-grade",
                source_reference_ids=["source-1"],
                cost_metadata={"tokens": 42},
                event_summary="Nudged toward the prerequisite.",
                event_body="Full turn body.",
            ),
            LLMProposal(
                id="llm-proposal-1",
                llm_session_id="llm-1",
                llm_model="fake-model",
                proposed_by="author",
                knowledge_node_id="node-1",
                knowledge_edge_id="edge-1",
                prompt_id="prompt-1",
                source_reference_id="source-1",
            ),
        ]
    )
    db_session.commit()
    return list(export_jsonl(db_session))


def _normalize_timestamp_strings(model: type[Base], record: dict[str, Any]) -> dict[str, Any]:
    """Collapse tz-aware/naive ISO timestamp spellings of the same instant.

    ``DateTime(timezone=True)`` columns round-trip through SQLite without a
    reliable tzinfo annotation: whether a freshly-loaded attribute keeps its
    ``+00:00`` suffix depends on SQLAlchemy's internal postfetch bookkeeping,
    not on any data actually being lost. Comparing instants rather than raw
    strings keeps the contract test meaningful without asserting on that
    incidental formatting.
    """
    datetime_fields = {
        column.key
        for column in inspect(model).columns
        if isinstance(column.type, (DateTime, UTCDateTime))
    }
    normalized = {}
    for key, value in record.items():
        if key in datetime_fields and isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                normalized[key] = value
            else:
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(UTC).replace(tzinfo=None)
                normalized[key] = parsed.isoformat()
        else:
            normalized[key] = value
    return normalized


@pytest.mark.parametrize("version", ["2026-06-01", "20260601", "2026-06-01T00:00:00"])
def test_round_trip_normalization_preserves_non_datetime_strings(version: str) -> None:
    record = {"policy_version": version}
    assert _normalize_timestamp_strings(LearningInteractionSkill, record) == record


@pytest.mark.parametrize("model, field", [(LLMSession, "created_at"), (AuditLog, "occurred_at")])
def test_round_trip_normalization_compares_datetime_instants(model: type[Base], field: str) -> None:
    aware = {field: "2026-06-01T01:00:00+01:00"}
    naive = {field: "2026-06-01T00:00:00"}
    assert _normalize_timestamp_strings(model, aware) == naive
    assert _normalize_timestamp_strings(model, naive) == naive


def test_export_import_round_trip_preserves_every_mapped_model(
    all_model_records: list[str],
    tmp_path: Path,
) -> None:
    """A full export/import/export cycle must lose no data for any of the 48 models."""
    records = [json.loads(line) for line in all_model_records]
    mapped_types = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    exported_types = {record["type"] for record in records}
    assert exported_types == mapped_types, "every mapped model must appear in a full export"

    path = tmp_path / "all-models.jsonl"
    path.write_text("\n".join(all_model_records) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            dry_run = import_jsonl(destination, path, dry_run=True)
            applied = import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            assert dry_run.counts == applied.counts
            for model_name in mapped_types:
                assert applied.counts[model_name] == (2 if model_name == "KnowledgeNode" else 1)
            restored = [json.loads(line) for line in export_jsonl(destination)]
            assert len(restored) == len(records)
            for original, reloaded in zip(records, restored, strict=True):
                assert reloaded["type"] == original["type"]
                assert reloaded["schema_version"] == original["schema_version"]
                assert _normalize_timestamp_strings(
                    MODEL_BY_TYPE[reloaded["type"]], reloaded["record"]
                ) == _normalize_timestamp_strings(
                    MODEL_BY_TYPE[original["type"]], original["record"]
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "model,field",
    [
        (model, fk.parent.name)
        for model in MAINTENANCE_LLM_MODELS
        for fk in sorted(model.__table__.foreign_keys, key=lambda fk: fk.parent.name)
    ]
    + [
        (GradeDispute, "evidence_record_id"),
        (LLMFeedbackEvent, "learner_id"),
    ],
)
def test_import_rejects_missing_maintenance_llm_dependency(
    maintenance_llm_records: list[str],
    tmp_path: Path,
    model: type[Base],
    field: str,
) -> None:
    records = [json.loads(line) for line in maintenance_llm_records]
    entry = next(record for record in records if record["type"] == model.__name__)
    entry["record"][field] = "missing-parent"
    path = tmp_path / "missing-parent.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            for dry_run in (True, False):
                with pytest.raises(
                    ExportImportError,
                    match=f"{model.__name__}:.*references missing .*:missing-parent",
                ):
                    import_jsonl(destination, path, dry_run=dry_run)
                assert destination.get(User, "user-1") is None
    finally:
        engine.dispose()


def test_import_rejects_wrong_id_type_per_model(
    maintenance_llm_records: list[str],
    tmp_path: Path,
) -> None:
    """The audit log is integer-keyed; every other entity keeps its string id contract."""
    records = [json.loads(line) for line in maintenance_llm_records]
    assert isinstance(next(r for r in records if r["type"] == "AuditLog")["record"]["id"], int)

    for record_type, replacement, message in (
        ("AuditLog", "1", "record.id must be an integer"),
        ("MaintenanceItem", 1, "record.id must be a string"),
    ):
        mutated = [dict(record, record=dict(record["record"])) for record in records]
        next(r for r in mutated if r["type"] == record_type)["record"]["id"] = replacement
        path = tmp_path / f"bad-id-{record_type}.jsonl"
        path.write_text(
            "\n".join(json.dumps(record) for record in mutated) + "\n", encoding="utf-8"
        )
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            Base.metadata.create_all(engine)
            with (
                Session(engine) as destination,
                pytest.raises(ExportImportError, match=message),
            ):
                import_jsonl(destination, path, dry_run=True)
        finally:
            engine.dispose()


@pytest.mark.parametrize("trace_class,allowed", [("ephemeral", True), ("evidence-grade", False)])
@pytest.mark.parametrize("include_all", [False, True])
def test_export_filters_children_of_excluded_llm_session(
    maintenance_llm_records: list[str],
    db_session: Session,
    tmp_path: Path,
    trace_class: str,
    allowed: bool,
    include_all: bool,
) -> None:
    parent = db_session.get(LLMSession, "llm-1")
    assert parent is not None
    parent.trace_class = trace_class
    parent.external_export_allowed = allowed
    db_session.commit()
    records = list(
        export_jsonl(
            db_session,
            include_llm_traces="all" if include_all else "evidence-grade-only",
            confirm_all=include_all,
        )
    )
    types = {json.loads(line)["type"] for line in records}
    attempt = next(
        json.loads(line)["record"] for line in records if json.loads(line)["type"] == "Attempt"
    )
    assert attempt["llm_session_id"] == ("llm-1" if include_all else None)
    original = db_session.get(Attempt, "attempt-1")
    assert original is not None and original.llm_session_id == "llm-1"
    for record_type in ("LLMSession", "LLMFeedbackEvent", "LLMProposal"):
        assert (record_type in types) is include_all
    path = tmp_path / "filtered.jsonl"
    path.write_text("\n".join(records) + "\n")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            import_jsonl(destination, path, dry_run=False)
            destination.commit()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "record_type,changes",
    [
        ("ReviewCardState", {"subject_id": "missing-parent"}),
        ("ReviewCardState", {"subject_type": "knowledge_node", "subject_id": "missing-parent"}),
        ("ReviewCardState", {"subject_type": "knowledge_node", "subject_id": "maintenance-item-1"}),
        ("ReviewCardState", {"subject_type": "invalid"}),
        ("ReviewCardState", {"subject_id": None}),
        ("ReviewCardState", {"subject_id": []}),
        ("LLMFeedbackEvent", {"source_reference_ids": ["source-1", "missing-parent"]}),
        ("LLMFeedbackEvent", {"source_reference_ids": "source-1"}),
        ("LLMFeedbackEvent", {"source_reference_ids": [None]}),
        ("LLMFeedbackEvent", {"source_reference_ids": [[]]}),
    ],
)
def test_import_rejects_invalid_new_soft_links_without_writes(
    maintenance_llm_records: list[str],
    tmp_path: Path,
    record_type: str,
    changes: dict[str, object],
) -> None:
    records = [json.loads(line) for line in maintenance_llm_records]
    next(r for r in records if r["type"] == record_type)["record"].update(changes)
    path = tmp_path / "invalid-soft-link.jsonl"
    path.write_text("\n".join(map(json.dumps, records)) + "\n")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            for dry_run in (True, False):
                with pytest.raises(ExportImportError):
                    import_jsonl(destination, path, dry_run=dry_run)
                assert destination.get(User, "user-1") is None
                assert destination.get(AuditLog, 1) is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "subject_type,subject_id",
    [("knowledge_node", "node-1"), ("maintenance_item", "maintenance-item-1")],
)
def test_import_preserves_valid_new_soft_links(
    maintenance_llm_records: list[str],
    tmp_path: Path,
    subject_type: str,
    subject_id: str,
) -> None:
    records = [json.loads(line) for line in maintenance_llm_records]
    next(r for r in records if r["type"] == "ReviewCardState")["record"].update(
        subject_type=subject_type, subject_id=subject_id
    )
    path = tmp_path / "valid-soft-link.jsonl"
    path.write_text("\n".join(map(json.dumps, records)) + "\n")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as destination:
            import_jsonl(destination, path, dry_run=False)
            destination.commit()
            destination.expire_all()
            card = destination.get(ReviewCardState, "review-card-1")
            feedback = destination.get(LLMFeedbackEvent, "llm-feedback-event-1")
            assert card is not None and card.subject_id == subject_id
            assert feedback is not None and feedback.source_reference_ids == ["source-1"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("sequence_ahead", [False, True])
def test_postgres_audit_import_allows_next_generated_insert(
    tmp_path: Path, sequence_ahead: bool
) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or make_url(database_url).get_backend_name() != "postgresql":
        pytest.skip("Set a PostgreSQL DATABASE_URL to exercise audit sequence recovery")
    schema = f"lms_export_test_{uuid4().hex}"
    url = make_url(database_url)
    admin_engine = create_engine(url)
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    record = {
        "id": 1,
        "actor_id": "author",
        "action": "update",
        "entity_type": "KnowledgeNode",
        "entity_id": "node-1",
        "source_subsystem": "authoring",
        "occurred_at": "2026-06-01T00:00:00+00:00",
    }
    path = tmp_path / "audit.jsonl"
    path.write_text(json.dumps({"type": "AuditLog", "schema_version": 1, "record": record}) + "\n")
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        table = AuditLog.__table__
        assert isinstance(table, Table)
        table.create(engine)
        with Session(engine) as destination:
            if sequence_ahead:
                destination.execute(
                    text("SELECT setval(pg_get_serial_sequence('audit_events', 'id'), 50, true)")
                )
            import_jsonl(destination, path, dry_run=True)
            assert destination.get(AuditLog, 1) is None
            import_jsonl(destination, path, dry_run=False)
            destination.commit()
            new_event = AuditLog(
                actor_id="author",
                action="create",
                entity_type="KnowledgeNode",
                entity_id="node-2",
                source_subsystem="authoring",
            )
            destination.add(new_event)
            destination.commit()
            assert new_event.id > (50 if sequence_ahead else 1)
            assert destination.get(AuditLog, 1) is not None
    finally:
        engine.dispose()
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            admin_engine.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def foreign_key_import_engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    """Exercise imports with real foreign-key enforcement on both backends."""
    if request.param == "sqlite":
        engine = create_engine("sqlite+pysqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            assert conn.scalar(text("PRAGMA foreign_keys")) == 1
        try:
            Base.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()
        return
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or make_url(database_url).get_backend_name() != "postgresql":
        pytest.skip("Set PostgreSQL DATABASE_URL to exercise session foreign keys")
    schema = f"lms_parent_test_{uuid4().hex}"
    url = make_url(database_url)
    admin_engine = create_engine(url)
    engine = create_engine(url.update_query_dict({"options": f"-csearch_path={schema}"}))
    try:
        with admin_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        try:
            with admin_engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            admin_engine.dispose()


@pytest.mark.parametrize("include_all", [False, True])
def test_export_retains_eligible_trace_with_optional_excluded_parent(
    foreign_key_import_engine: Engine,
    db_session: Session,
    tmp_path: Path,
    include_all: bool,
) -> None:
    parent = LLMSession(
        id="z-private",
        mode="practice",
        trace_class="ephemeral",
        provider="fake",
        model="fake",
        external_export_allowed=False,
    )
    child = LLMSession(
        id="a-public",
        mode="practice",
        trace_class="evidence-grade",
        provider="fake",
        model="fake",
        parent_session_id=parent.id,
        external_export_allowed=True,
    )
    db_session.add(parent)
    db_session.flush()
    db_session.add(child)
    db_session.commit()
    records = list(
        export_jsonl(
            db_session,
            include_llm_traces="all" if include_all else "evidence-grade-only",
            confirm_all=include_all,
        )
    )
    exported = [json.loads(line)["record"] for line in records]
    assert exported[0]["id"] == child.id
    assert exported[0]["parent_session_id"] == (parent.id if include_all else None)
    assert len(exported) == (2 if include_all else 1)
    assert child.parent_session_id == parent.id
    path = tmp_path / "trace-parent.jsonl"
    path.write_text("\n".join(records) + "\n")
    with Session(foreign_key_import_engine) as destination:
        import_jsonl(destination, path, dry_run=True)
        assert destination.get(LLMSession, child.id) is None
        import_jsonl(destination, path, dry_run=False)
        destination.commit()
        destination.expire_all()
        restored_child = destination.get(LLMSession, child.id)
        assert restored_child is not None
        assert restored_child.parent_session_id == (parent.id if include_all else None)
        assert (destination.get(LLMSession, parent.id) is not None) == include_all
