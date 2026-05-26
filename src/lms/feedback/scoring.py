"""Rubric scoring service that preserves partial-credit evidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from lms.evidence.models import Attempt
from lms.evidence.repository import create_evidence_record
from lms.feedback.models import Rubric, RubricScore
from lms.feedback.repository import (
    create_feedback_action,
    create_feedback_record,
    create_rubric_score,
    get_rubric,
)
from lms.prompts.models import Prompt


def score_attempt_with_rubric(
    session: Session,
    *,
    rubric_id: str,
    attempt_id: str,
    scorer_type: str,
    criterion_scores: list[dict[str, Any]],
    scorer_id: str | None = None,
    scorer_version: str | None = None,
    score_metadata: dict[str, Any] | None = None,
    feedback_threshold: float = 0.85,
    remediation_threshold: float = 0.5,
) -> RubricScore:
    """Score an attempt, write linked evidence, and create low-score feedback."""
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise ValueError("referenced attempt was not found")
    rubric = get_rubric(session, rubric_id)
    if rubric is None:
        raise ValueError("referenced rubric was not found")
    if not rubric.criteria:
        raise ValueError("rubric must have at least one criterion before scoring")
    if not criterion_scores:
        raise ValueError("criterion_scores must include at least one criterion score")

    normalized_scores = _normalize_criterion_scores(rubric, criterion_scores)
    raw_score = sum(score["points"] for score in normalized_scores)
    max_score = sum(score["max_points"] for score in normalized_scores)
    normalized_score = raw_score / max_score if max_score else 0.0

    knowledge_node_id = _knowledge_node_id_for_score(session, rubric, attempt)
    evidence = create_evidence_record(
        session,
        learner_id=attempt.learner_id,
        knowledge_node_id=knowledge_node_id,
        attempt_id=attempt.id,
        prompt_id=attempt.prompt_id,
        correctness=normalized_score >= feedback_threshold,
        raw_score=raw_score,
        normalized_score=normalized_score,
        max_score=max_score,
        partial_credit_dimensions={
            "rubric_id": rubric.id,
            "criterion_scores": normalized_scores,
        },
        scorer_metadata={
            "scoring_method": "rubric",
            "scorer_type": scorer_type,
            "scorer_id": scorer_id,
            "scorer_version": scorer_version,
            **(score_metadata or {}),
        },
        validity_scope=rubric.ownership_scope,
        attempt_context=attempt.response_metadata,
    )

    feedback_record_id: str | None = None
    if normalized_score < feedback_threshold:
        feedback_record = create_feedback_record(
            session,
            learner_id=attempt.learner_id,
            attempt_id=attempt.id,
            prompt_id=attempt.prompt_id,
            evidence_record_id=evidence.id,
            feedback_level="remediation" if normalized_score < remediation_threshold else "review",
            goal=f"Improve rubric performance for {rubric.title}",
            observed_evidence=(
                f"Rubric score {raw_score:g}/{max_score:g} "
                f"({normalized_score:.0%}) on {rubric.title}."
            ),
            diagnosis="Rubric score fell below the configured feedback threshold.",
            gap=_lowest_scored_gap(normalized_scores),
            source_feedback={
                "source": "rubric_score",
                "rubric_id": rubric.id,
                "normalized_score": normalized_score,
            },
        )
        action = create_feedback_action(
            session,
            feedback_record_id=feedback_record.id,
            learner_id=attempt.learner_id,
            attempt_id=attempt.id,
            prompt_id=attempt.prompt_id,
            action_type="prerequisite-remediation"
            if normalized_score < remediation_threshold
            else "revision",
            title="Revise the attempt using rubric feedback",
            instructions=_lowest_scored_gap(normalized_scores),
            action_metadata={
                "source": "rubric_score",
                "rubric_id": rubric.id,
                "normalized_score": normalized_score,
            },
        )
        feedback_record.next_action_ids = [action.id]
        feedback_record_id = feedback_record.id

    return create_rubric_score(
        session,
        rubric_id=rubric.id,
        attempt_id=attempt.id,
        learner_id=attempt.learner_id,
        scorer_type=scorer_type,
        scorer_id=scorer_id,
        scorer_version=scorer_version,
        raw_score=raw_score,
        normalized_score=normalized_score,
        max_score=max_score,
        criterion_scores=normalized_scores,
        evidence_record_id=evidence.id,
        feedback_record_id=feedback_record_id,
        score_metadata=score_metadata,
    )


def _normalize_criterion_scores(
    rubric: Rubric,
    criterion_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    criteria_by_id = {
        criterion.id: criterion for criterion in rubric.criteria if criterion.status == "active"
    }
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in criterion_scores:
        criterion_id = str(item.get("criterion_id") or "")
        if criterion_id in seen:
            raise ValueError("criterion_scores must not contain duplicate criterion ids")
        criterion = criteria_by_id.get(criterion_id)
        if criterion is None:
            raise ValueError(f"unknown or inactive rubric criterion id: {criterion_id}")
        points = float(item.get("points", 0))
        if points < 0 or points > criterion.max_points:
            raise ValueError("criterion score points must be within criterion max_points")
        seen.add(criterion_id)
        normalized.append(
            {
                "criterion_id": criterion.id,
                "criterion_order": criterion.criterion_order,
                "description": criterion.description,
                "points": points,
                "max_points": criterion.max_points,
                "rationale": item.get("rationale"),
            }
        )
    return sorted(normalized, key=lambda score: score["criterion_order"])


def _knowledge_node_id_for_score(session: Session, rubric: Rubric, attempt: Attempt) -> str:
    if rubric.knowledge_node_id is not None:
        return rubric.knowledge_node_id
    prompt_id = rubric.prompt_id or attempt.prompt_id
    prompt = session.get(Prompt, prompt_id)
    if prompt is not None:
        return prompt.target_node_id
    raise ValueError("rubric score requires a rubric knowledge node or prompt target")


def _lowest_scored_gap(criterion_scores: list[dict[str, Any]]) -> str:
    lowest = min(
        criterion_scores,
        key=lambda item: item["points"] / item["max_points"] if item["max_points"] else 0,
    )
    return f"Revisit criterion {lowest['criterion_order']}: {lowest['description']}"
