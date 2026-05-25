"""Repository helpers for learner attempts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from sqlalchemy import select

from lms.evidence.models import Attempt, EvidenceRecord


def create_attempt(
    session: Session,
    *,
    learner_id: str,
    prompt_id: str,
    response_text: str,
    feedback: dict[str, Any],
    confidence_rating: int | None = None,
    reference_accessed: bool = False,
    hint_used: bool = False,
    support_level: str = "none",
    elapsed_seconds: int | None = None,
    llm_session_id: str | None = None,
    scoring: dict[str, Any] | None = None,
) -> Attempt:
    """Persist a learner attempt with structured feedback."""
    if not feedback.get("next_action"):
        raise ValueError("structured feedback requires next_action")
    attempt = Attempt(
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text=response_text,
        confidence_rating=confidence_rating,
        reference_accessed=reference_accessed,
        hint_used=hint_used,
        support_level=support_level,
        elapsed_seconds=elapsed_seconds,
        feedback=feedback,
        llm_session_id=llm_session_id,
    )
    session.add(attempt)
    session.flush()
    if scoring is not None:
        scoring = dict(scoring)
        scoring.setdefault("learner_id", learner_id)
        scoring.setdefault("prompt_id", prompt_id)
        scoring["attempt_id"] = attempt.id
        scoring["confidence_rating"] = confidence_rating
        scoring["hint_used"] = hint_used
        scoring["reference_accessed"] = reference_accessed
        scoring["support_level"] = support_level
        scoring["response_time_seconds"] = elapsed_seconds
        create_evidence_record(session, **scoring)
    return attempt


def get_attempt(session: Session, attempt_id: str) -> Attempt | None:
    """Return an attempt by stable id."""
    return session.get(Attempt, attempt_id)


def create_evidence_record(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    prompt_id: str,
    demand_level: str,
    knowledge_type: str,
    prompt_version_id: str | None = None,
    attempt_id: str | None = None,
    evidence_kind: str = "observed",
    time_since_last_attempt_seconds: int | None = None,
    response_time_seconds: int | None = None,
    correctness: bool | None = None,
    confidence_rating: int | None = None,
    hint_used: bool = False,
    reference_accessed: bool = False,
    support_level: str = "none",
    retrieval_demand: str | None = None,
    transfer_distance: str | None = None,
    source_match_quality: str | None = None,
    scorer_id: str | None = None,
    scorer_version: str | None = None,
    raw_score: float | None = None,
    normalized_score: float | None = None,
    max_score: float | None = None,
    partial_credit_dimensions: dict[str, float] | None = None,
    item_difficulty_estimate: float | None = None,
    attempt_context: dict[str, object] | None = None,
    validity_scope: str = "attempt",
    answer_artifact_ref: str | None = None,
) -> EvidenceRecord:
    """Persist one verbose evidence record."""
    if raw_score is not None and max_score is not None and raw_score > max_score:
        raise ValueError("raw_score cannot exceed max_score")
    record = EvidenceRecord(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        attempt_id=attempt_id,
        evidence_kind=evidence_kind,
        demand_level=demand_level,
        knowledge_type=knowledge_type,
        time_since_last_attempt_seconds=time_since_last_attempt_seconds,
        response_time_seconds=response_time_seconds,
        correctness=correctness,
        confidence_rating=confidence_rating,
        hint_used=hint_used,
        reference_accessed=reference_accessed,
        support_level=support_level,
        retrieval_demand=retrieval_demand,
        transfer_distance=transfer_distance,
        source_match_quality=source_match_quality,
        scorer_id=scorer_id,
        scorer_version=scorer_version,
        raw_score=raw_score,
        normalized_score=normalized_score,
        max_score=max_score,
        partial_credit_dimensions=partial_credit_dimensions,
        item_difficulty_estimate=item_difficulty_estimate,
        attempt_context=attempt_context,
        validity_scope=validity_scope,
        answer_artifact_ref=answer_artifact_ref,
    )
    session.add(record)
    session.flush()
    return record


def list_evidence_records(
    session: Session,
    *,
    learner_id: str | None = None,
    knowledge_node_id: str | None = None,
    evidence_kind: str | None = None,
    limit: int = 100,
) -> list[EvidenceRecord]:
    """List evidence records with learner/node filters."""
    statement = select(EvidenceRecord)
    if learner_id is not None:
        statement = statement.where(EvidenceRecord.learner_id == learner_id)
    if knowledge_node_id is not None:
        statement = statement.where(EvidenceRecord.knowledge_node_id == knowledge_node_id)
    if evidence_kind is not None:
        statement = statement.where(EvidenceRecord.evidence_kind == evidence_kind)
    statement = statement.order_by(EvidenceRecord.recorded_at.desc(), EvidenceRecord.id).limit(
        limit
    )
    return list(session.scalars(statement))
