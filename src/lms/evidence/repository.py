"""Repository helpers for learner attempts and evidence records."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import (
    DEMAND_LEVELS,
    EVIDENCE_KINDS,
    SCORER_TYPES,
    SCORING_METHODS,
    SUPPORT_LEVELS,
    Attempt,
    EvidenceRecord,
)
from lms.evidence.scoring import resolved_normalized_score
from lms.graphs.models import KNOWLEDGE_TYPES
from lms.learners.models import Learner


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


def _value_or_default(value: Any, default: Any) -> Any:
    """Treat explicit None in dumped payloads the same as a missing value."""
    return default if value is None else value


def _resolved_normalized_score(
    *,
    normalized_score: float | None,
    raw_score: float | None,
    max_score: float | None,
) -> float | None:
    """Prefer valid normalized scores, then valid raw/max ratios; skip invalid signals.

    Scores must be finite and within 0..1; ratios require a positive maximum.
    Return None when neither scoring signal is usable.
    """
    return resolved_normalized_score(
        normalized_score=normalized_score, raw_score=raw_score, max_score=max_score
    )


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
    evidence_record: EvidenceRecord | None = None
    if evidence is not None and _has_scoring_signal(evidence):
        evidence_record = create_evidence_record(
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
            response_time_seconds=_value_or_default(
                evidence.get("response_time_seconds"), elapsed_seconds
            ),
            correctness=evidence.get("correctness"),
            confidence_rating=confidence_rating,
            reference_accessed=reference_accessed,
            hint_used=hint_used,
            support_level=support_level,
            retrieval_demand=evidence.get("retrieval_demand"),
            transfer_distance=evidence.get("transfer_distance"),
            source_match_quality=evidence.get("source_match_quality"),
            scorer_type=evidence.get("scorer_type"),
            scorer_id=evidence.get("scorer_id"),
            scorer_version=evidence.get("scorer_version"),
            scoring_method=evidence.get("scoring_method"),
            scorer_metadata=evidence.get("scorer_metadata"),
            raw_score=evidence.get("raw_score"),
            normalized_score=evidence.get("normalized_score"),
            max_score=evidence.get("max_score"),
            partial_credit_dimensions=evidence.get("partial_credit_dimensions"),
            item_difficulty_estimate=evidence.get("item_difficulty_estimate"),
            attempt_context=_value_or_default(evidence.get("attempt_context"), response_metadata),
            validity_scope=evidence.get("validity_scope"),
            answer_artifact_ref=evidence.get("answer_artifact_ref"),
        )
    from lms.feedback.repository import promote_attempt_feedback

    promote_attempt_feedback(
        session,
        attempt,
        evidence_record_id=evidence_record.id if evidence_record is not None else None,
    )
    return attempt


def get_attempt(session: Session, attempt_id: str) -> Attempt | None:
    """Return an attempt by stable id."""
    return session.get(Attempt, attempt_id)


def get_attempt_for_user(session: Session, *, attempt_id: str, user_id: str) -> Attempt | None:
    """Return an attempt only when its learner belongs to the user."""
    statement = (
        select(Attempt)
        .join(Learner, Attempt.learner_id == Learner.id)
        .where(Attempt.id == attempt_id, Learner.user_id == user_id)
    )
    return session.scalar(statement)


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
    scorer_type: str | None = None,
    scorer_id: str | None = None,
    scorer_version: str | None = None,
    scoring_method: str | None = None,
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
    """Validate evidence metadata before persisting an observed or inferred signal."""
    if evidence_kind not in EVIDENCE_KINDS:
        raise ValueError(
            f"unknown evidence_kind {evidence_kind!r}; expected one of {EVIDENCE_KINDS}"
        )
    if demand_level is not None and demand_level not in DEMAND_LEVELS:
        raise ValueError(f"unknown demand_level {demand_level!r}; expected one of {DEMAND_LEVELS}")
    if knowledge_type is not None and knowledge_type not in KNOWLEDGE_TYPES:
        raise ValueError(
            f"unknown knowledge_type {knowledge_type!r}; expected one of {KNOWLEDGE_TYPES}"
        )
    if scorer_type is not None and scorer_type not in SCORER_TYPES:
        raise ValueError(f"unknown scorer_type {scorer_type!r}; expected one of {SCORER_TYPES}")
    if scoring_method is not None and scoring_method not in SCORING_METHODS:
        raise ValueError(
            f"unknown scoring_method {scoring_method!r}; expected one of {SCORING_METHODS}"
        )
    if support_level not in SUPPORT_LEVELS:
        raise ValueError(
            f"unknown support_level {support_level!r}; expected one of {SUPPORT_LEVELS}"
        )
    if confidence_rating is not None and not 1 <= confidence_rating <= 5:
        raise ValueError("confidence_rating must be between 1 and 5")
    if raw_score is not None and (not math.isfinite(raw_score) or raw_score < 0):
        raise ValueError("raw_score must be non-negative")
    if max_score is not None and (not math.isfinite(max_score) or max_score <= 0):
        raise ValueError("max_score must be a positive number")
    if item_difficulty_estimate is not None and (
        not math.isfinite(item_difficulty_estimate) or not 0.0 <= item_difficulty_estimate <= 1.0
    ):
        raise ValueError("item_difficulty_estimate must be between 0.0 and 1.0")
    if time_since_last_attempt_seconds is not None and time_since_last_attempt_seconds < 0:
        raise ValueError("time_since_last_attempt_seconds must be non-negative")
    if response_time_seconds is not None and response_time_seconds < 0:
        raise ValueError("response_time_seconds must be non-negative")

    resolved_normalized_score = _resolved_normalized_score(
        normalized_score=normalized_score,
        raw_score=raw_score,
        max_score=max_score,
    )
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
        scorer_type=scorer_type,
        scorer_id=scorer_id,
        scorer_version=scorer_version,
        scoring_method=scoring_method,
        scorer_metadata=scorer_metadata,
        raw_score=raw_score,
        normalized_score=resolved_normalized_score,
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


def get_evidence_record_for_user(
    session: Session, *, evidence_record_id: str, user_id: str
) -> EvidenceRecord | None:
    """Return evidence only when its learner belongs to the user."""
    statement = (
        select(EvidenceRecord)
        .join(Learner, EvidenceRecord.learner_id == Learner.id)
        .where(EvidenceRecord.id == evidence_record_id, Learner.user_id == user_id)
    )
    return session.scalar(statement)


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
