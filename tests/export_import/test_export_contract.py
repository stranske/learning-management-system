"""Tests for the v1 typed JSONL export contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.export_import.test_m5_export_contract import _seed_m5_runtime_records

from lms.auth.models import User
from lms.cases.models import WorkProduct
from lms.db.base import Base
from lms.export_import import MODEL_BY_TYPE, ExportImportError, export_jsonl, import_jsonl
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
            with pytest.raises(
                ExportImportError, match=f"{model.__name__}:.*references missing .*:missing-parent"
            ):
                import_jsonl(destination, path, dry_run=True)
            assert destination.get(User, "user-1") is None
    finally:
        engine.dispose()
