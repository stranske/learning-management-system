"""Tests for verbose evidence records."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from lms.evidence.api import list_evidence_records_route
from lms.evidence.repository import create_attempt, create_evidence_record, list_evidence_records
from lms.evidence.schemas import AttemptCreate, EvidenceRecordRead


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
        "evidence_kind": "observed",
        "demand_level": "medium",
        "knowledge_type": "procedural",
        "time_since_last_attempt_seconds": 3600,
        "response_time_seconds": 51,
        "correctness": True,
        "retrieval_demand": "free-recall",
        "transfer_distance": "near",
        "source_match_quality": "strong",
        "scorer_metadata": {"scorer": "unit-test", "rubric_version": "v1"},
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
    assert record.evidence_kind == "observed"
    assert record.demand_level == "medium"
    assert record.knowledge_type == "procedural"
    assert record.correctness is True
    assert record.confidence_rating == 4
    assert record.reference_accessed is True
    assert record.support_level == "reference"
    assert record.raw_score == 4.0
    assert record.normalized_score == 0.8
    assert record.max_score == 5.0
    partial = cast(dict[str, Any], record.partial_credit_dimensions)
    assert partial["calculation"] == 0.8

    read = EvidenceRecordRead.model_validate(record)
    assert read.id == record.id
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
        scorer_metadata={"source": "mastery-estimator"},
    )
    db_session.commit()

    records = list_evidence_records_route(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
    )

    assert {record.id for record in records} == {observed.id, inferred.id}
    assert {record.evidence_kind for record in records} == {"observed", "inferred"}
