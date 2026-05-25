"""Repository helpers for learner attempts and evidence records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import Attempt, EvidenceRecord


def _has_scoring_signal(evidence: dict[str, Any]) -> bool:
    """Return whether evidence includes correctness or scoring fields."""
    scoring_keys = (
        "correctness",
        "raw_score",
        "normalized_score",
        "max_score",
        "partial_credit_dimensions",
    )
    return any(evidence.get(key) is not None for key in scoring_keys)


def create_attempt(
    session: Session,
    *,
    learner_id: str,
    prompt_id: str,
    response_text: str,
    feedback: dict[str, Any],
    response_metadata: dict[str, Any] | None = None,
    confidence_rating: int | None = None,
    reference_accessed: bool = False,
    hint_used: bool = False,
    support_level: str = "none",
    elapsed_seconds: int | None = None,
    llm_session_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> Attempt:
    """Persist a learner attempt with structured feedback."""
    attempt = Attempt(
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text=response_text,
        response_metadata=response_metadata,
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
    if evidence is not None and _has_scoring_signal(evidence):
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=evidence["knowledge_node_id"],
            attempt_id=attempt.id,
            prompt_id=prompt_id,
            prompt_version_id=evidence.get("prompt_version_id"),
            timestamp=evidence.get("timestamp"),
            evidence_kind=evidence.get("evidence_kind", "observed"),
            demand_level=evidence.get("demand_level"),
            knowledge_type=evidence.get("knowledge_type"),
            time_since_last_attempt_seconds=evidence.get("time_since_last_attempt_seconds"),
            response_time_seconds=evidence.get("response_time_seconds", elapsed_seconds),
            correctness=evidence.get("correctness"),
            confidence_rating=confidence_rating,
            reference_accessed=reference_accessed,
            hint_used=hint_used,
            support_level=support_level,
            retrieval_demand=evidence.get("retrieval_demand"),
            transfer_distance=evidence.get("transfer_distance"),
            source_match_quality=evidence.get("source_match_quality"),
            scorer_metadata=evidence.get("scorer_metadata"),
            raw_score=evidence.get("raw_score"),
            normalized_score=evidence.get("normalized_score"),
            max_score=evidence.get("max_score"),
            partial_credit_dimensions=evidence.get("partial_credit_dimensions"),
            item_difficulty_estimate=evidence.get("item_difficulty_estimate"),
            attempt_context=evidence.get("attempt_context", response_metadata),
            validity_scope=evidence.get("validity_scope"),
            answer_artifact_ref=evidence.get("answer_artifact_ref"),
        )
    return attempt


def get_attempt(session: Session, attempt_id: str) -> Attempt | None:
    """Return an attempt by stable id."""
    return session.get(Attempt, attempt_id)


def create_evidence_record(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    attempt_id: str | None = None,
    prompt_id: str | None = None,
    prompt_version_id: str | None = None,
    timestamp: datetime | None = None,
    evidence_kind: str = "observed",
    demand_level: str | None = None,
    knowledge_type: str | None = None,
    time_since_last_attempt_seconds: int | None = None,
    response_time_seconds: int | None = None,
    correctness: bool | None = None,
    confidence_rating: int | None = None,
    reference_accessed: bool = False,
    hint_used: bool = False,
    support_level: str = "none",
    retrieval_demand: str | None = None,
    transfer_distance: str | None = None,
    source_match_quality: str | None = None,
    scorer_metadata: dict[str, Any] | None = None,
    raw_score: float | None = None,
    normalized_score: float | None = None,
    max_score: float | None = None,
    partial_credit_dimensions: dict[str, Any] | None = None,
    item_difficulty_estimate: float | None = None,
    attempt_context: dict[str, Any] | None = None,
    validity_scope: str | None = None,
    answer_artifact_ref: str | None = None,
) -> EvidenceRecord:
    """Persist a verbose observed or inferred evidence signal."""
    record = EvidenceRecord(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        prompt_version_id=prompt_version_id,
        timestamp=timestamp,
        evidence_kind=evidence_kind,
        demand_level=demand_level,
        knowledge_type=knowledge_type,
        time_since_last_attempt_seconds=time_since_last_attempt_seconds,
        response_time_seconds=response_time_seconds,
        correctness=correctness,
        confidence_rating=confidence_rating,
        reference_accessed=reference_accessed,
        hint_used=hint_used,
        support_level=support_level,
        retrieval_demand=retrieval_demand,
        transfer_distance=transfer_distance,
        source_match_quality=source_match_quality,
        scorer_metadata=scorer_metadata,
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


def get_evidence_record(session: Session, evidence_record_id: str) -> EvidenceRecord | None:
    """Return one evidence record by id."""
    return session.get(EvidenceRecord, evidence_record_id)


def list_evidence_records(
    session: Session,
    *,
    learner_id: str | None = None,
    knowledge_node_id: str | None = None,
    limit: int = 100,
) -> Sequence[EvidenceRecord]:
    """List evidence records, optionally filtered by learner and node."""
    statement = select(EvidenceRecord)
    if learner_id is not None:
        statement = statement.where(EvidenceRecord.learner_id == learner_id)
    if knowledge_node_id is not None:
        statement = statement.where(EvidenceRecord.knowledge_node_id == knowledge_node_id)
    statement = statement.order_by(EvidenceRecord.observed_at.desc(), EvidenceRecord.id).limit(
        limit
    )
    return list(session.scalars(statement))
