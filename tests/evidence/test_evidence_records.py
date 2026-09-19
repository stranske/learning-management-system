"""Tests for verbose evidence records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.evidence.api import list_evidence_records_route
from lms.evidence.models import EVIDENCE_KINDS, EvidenceRecord
from lms.evidence.repository import create_attempt, create_evidence_record, list_evidence_records
from lms.evidence.schemas import AttemptCreate, AttemptEvidenceCreate, EvidenceRecordRead
from lms.settings import Settings


def _local_route_dependencies() -> tuple[User, Settings]:
    """Supply the explicit dependencies required by direct route tests."""
    return cast(User, None), Settings(auth_required=False)


def _attempt_payload() -> dict[str, object]:
    return {
        "learner_id": "learner-1",
        "prompt_id": "prompt-1",
        "response_text": "The answer is 42 because I substituted the known value.",
        "response_metadata": {"input_mode": "typed"},
        "confidence_rating": 4,
        "reference_accessed": True,
        "hint_used": False,
        "support_level": "reference",
        "elapsed_seconds": 51,
        "feedback": {
            "goal": "Apply substitution",
            "observed_evidence": "Chose the right variable and substituted correctly.",
            "gap": "Needs clearer unit labeling.",
            "next_action": "Practice two substitution prompts with units.",
        },
    }


def _evidence_payload() -> dict[str, object]:
    return {
        "knowledge_node_id": "node-1",
        "prompt_version_id": "prompt-version-1",
        "timestamp": datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
        "evidence_kind": "observed",
        "demand_level": "medium",
        "knowledge_type": "procedural",
        "time_since_last_attempt_seconds": 3600,
        "response_time_seconds": 51,
        "correctness": True,
        "retrieval_demand": "free-recall",
        "transfer_distance": "near",
        "source_match_quality": "strong",
        "scorer_type": "auto",
        "scorer_id": "unit-test",
        "scorer_version": "v1",
        "scoring_method": "partial-credit",
        "raw_score": 4.0,
        "normalized_score": 0.8,
        "max_score": 5.0,
        "partial_credit_dimensions": {"setup": 1.0, "calculation": 0.8},
        "item_difficulty_estimate": 0.35,
        "attempt_context": {"surface": "api-test"},
        "validity_scope": "single prompt attempt",
        "answer_artifact_ref": "artifact://attempts/1",
    }


def test_evidence_record_roundtrip_full_schema(db_session: Session) -> None:
    """Attempt scoring creates and reads back the verbose evidence schema."""
    payload = _attempt_payload()
    payload["evidence"] = _evidence_payload()
    attempt = create_attempt(db_session, **AttemptCreate.model_validate(payload).model_dump())
    db_session.commit()

    records = list_evidence_records(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
    )

    assert len(records) == 1
    record = records[0]
    assert record.attempt_id == attempt.id
    assert record.prompt_id == "prompt-1"
    assert record.prompt_version_id == "prompt-version-1"
    assert record.timestamp.replace(tzinfo=UTC) == datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
    assert record.evidence_kind == "observed"
    assert record.demand_level == "medium"
    assert record.knowledge_type == "procedural"
    assert record.correctness is True
    assert record.confidence_rating == 4
    assert record.reference_accessed is True
    assert record.support_level == "reference"
    assert record.scorer_type == "auto"
    assert record.scorer_id == "unit-test"
    assert record.scorer_version == "v1"
    assert record.scoring_method == "partial-credit"
    assert record.raw_score == 4.0
    assert record.normalized_score == 0.8
    assert record.max_score == 5.0
    partial = cast(dict[str, Any], record.partial_credit_dimensions)
    assert partial["calculation"] == 0.8

    read = EvidenceRecordRead.model_validate(record)
    assert read.id == record.id
    assert read.timestamp.replace(tzinfo=UTC) == datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
    assert read.answer_artifact_ref == "artifact://attempts/1"


def test_observed_and_inferred_evidence_are_distinct(db_session: Session) -> None:
    """Observed and inferred evidence kinds can coexist for the same learner/node."""
    observed = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        evidence_kind="observed",
        correctness=True,
        normalized_score=1.0,
    )
    inferred = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        evidence_kind="inferred",
        normalized_score=0.72,
        scorer_type="auto",
    )
    db_session.commit()

    current_user, settings = _local_route_dependencies()
    records = list_evidence_records_route(
        db_session,
        current_user,
        settings,
        learner_id="learner-1",
        knowledge_node_id="node-1",
    )

    assert {record.id for record in records} == {observed.id, inferred.id}
    assert {record.evidence_kind for record in records} == {"observed", "inferred"}


def test_binary_and_partial_credit_records_roundtrip(db_session: Session) -> None:
    """Binary and partial-credit evidence rows can coexist and roundtrip."""
    binary = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        evidence_kind="observed",
        correctness=True,
        raw_score=1.0,
        normalized_score=1.0,
        max_score=1.0,
        scoring_method="binary",
    )
    partial_credit = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        evidence_kind="observed",
        correctness=False,
        raw_score=3.0,
        normalized_score=0.75,
        max_score=4.0,
        partial_credit_dimensions={"setup": 1.0, "calculation": 0.5, "units": 0.5},
        scoring_method="partial-credit",
    )
    db_session.commit()

    records = list_evidence_records(db_session, learner_id="learner-1", knowledge_node_id="node-1")
    by_id = {record.id: record for record in records}

    assert by_id[binary.id].partial_credit_dimensions is None
    assert by_id[binary.id].normalized_score == 1.0
    assert by_id[binary.id].scoring_method == "binary"
    partial = cast(dict[str, Any], by_id[partial_credit.id].partial_credit_dimensions)
    assert partial["calculation"] == 0.5
    assert by_id[partial_credit.id].normalized_score == 0.75
    assert by_id[partial_credit.id].scoring_method == "partial-credit"


def test_scorer_type_check_constraint_rejects_invalid(db_session: Session) -> None:
    """Repository validation rejects invalid scorer types before persistence."""
    with pytest.raises(ValueError, match="unknown scorer_type 'unknown-scorer'"):
        create_evidence_record(
            db_session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            evidence_kind="observed",
            normalized_score=1.0,
            scorer_type="unknown-scorer",
        )

    assert db_session.is_active
    assert not db_session.new
    assert db_session.query(EvidenceRecord).count() == 0


def _evidence_record_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "learner_id": "learner-1",
        "knowledge_node_id": "node-1",
        "evidence_kind": "observed",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("raw_score", -1.0, "raw_score must be non-negative"),
        ("raw_score", float("nan"), "raw_score must be non-negative"),
        ("max_score", 0.0, "max_score must be a positive number"),
        ("max_score", -2.0, "max_score must be a positive number"),
        ("evidence_kind", "invalid", "unknown evidence_kind 'invalid'"),
        ("item_difficulty_estimate", 1.5, "item_difficulty_estimate must be between 0.0 and 1.0"),
        ("item_difficulty_estimate", -0.1, "item_difficulty_estimate must be between 0.0 and 1.0"),
        ("demand_level", "extreme", "unknown demand_level 'extreme'"),
        ("knowledge_type", "mystery", "unknown knowledge_type 'mystery'"),
        ("scoring_method", "curve", "unknown scoring_method 'curve'"),
        ("support_level", "invalid", "unknown support_level 'invalid'"),
        ("confidence_rating", 0, "confidence_rating must be between 1 and 5"),
        (
            "time_since_last_attempt_seconds",
            -1,
            "time_since_last_attempt_seconds must be non-negative",
        ),
        ("response_time_seconds", -3, "response_time_seconds must be non-negative"),
    ],
)
def test_create_evidence_record_rejects_invalid_metadata_without_poisoning_session(
    db_session: Session, field: str, value: object, message: str
) -> None:
    """Direct repository callers get a domain error before any persistence."""
    kwargs = _evidence_record_kwargs(**{field: value})

    with pytest.raises(ValueError, match=message) as exc_info:
        create_evidence_record(db_session, **kwargs)

    if field == "evidence_kind":
        assert f"expected one of {EVIDENCE_KINDS}" in str(exc_info.value)
    assert db_session.is_active
    assert not db_session.new
    assert db_session.query(EvidenceRecord).count() == 0

    valid = create_evidence_record(db_session, **_evidence_record_kwargs())
    db_session.commit()
    assert valid.id is not None
    assert db_session.query(EvidenceRecord).count() == 1


def test_attempt_evidence_validation_rejects_invalid_scores() -> None:
    """Schema validation rejects invalid binary/partial-credit score shapes."""
    with pytest.raises(ValueError):
        AttemptEvidenceCreate(
            knowledge_node_id="node-1",
            normalized_score=1.25,
        )

    with pytest.raises(ValueError):
        AttemptEvidenceCreate(
            knowledge_node_id="node-1",
            raw_score=-0.5,
            partial_credit_dimensions={"criterion_a": 0.5},
        )
