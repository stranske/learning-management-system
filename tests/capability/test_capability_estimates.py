"""Tests for target-relative capability estimates."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    list_capability_estimates,
    recompute_capability_estimate,
)
from lms.competencies.repository import create_competency, create_competency_evidence
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user


def _learner(db_session: Session) -> str:
    user = User(
        email="estimate-learner@example.test",
        username="estimate-learner",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    return create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    ).id


def test_capability_estimate_uses_mastery_and_competency_evidence(
    db_session: Session,
) -> None:
    """A persisted target estimate combines node mastery and competency evidence."""
    learner_id = _learner(db_session)
    node = create_knowledge_node(
        db_session,
        title="Explain evidence tradeoffs",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    competency = create_competency(
        db_session,
        title="Evidence-backed judgment",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )
    first = create_evidence_record(
        db_session,
        learner_id=learner_id,
        knowledge_node_id=node.id,
        knowledge_type="judgment",
        normalized_score=0.6,
        validity_scope="Worked-example explanation.",
    )
    second = create_evidence_record(
        db_session,
        learner_id=learner_id,
        knowledge_node_id=node.id,
        knowledge_type="judgment",
        normalized_score=0.9,
        validity_scope="Independent transfer explanation.",
    )
    create_competency_evidence(
        db_session,
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=second.id,
        contribution_weight=0.75,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Reach durable evidence-backed judgment",
        target_node_ids=[node.id],
        target_competency_ids=[competency.id],
        required_evidence_types=["rubric-score", "transfer-case"],
        confidence_threshold=0.55,
    )

    estimate = recompute_capability_estimate(db_session, target_id=target.id)
    db_session.commit()
    breakdown = cast(dict[str, Any], estimate.evidence_breakdown)

    assert estimate.target_id == target.id
    assert estimate.learner_id == learner_id
    assert estimate.current_score > 0.75
    assert estimate.confidence >= 0.49
    assert estimate.weak_node_ids == []
    assert estimate.commentary_redaction_class == "learner-facing-inferred-mastery"
    assert "Current evidence suggests" in estimate.commentary
    assert breakdown["required_evidence_types"] == ["rubric-score", "transfer-case"]
    assert breakdown["target_node_estimates"][0]["last_evidence_id"] == second.id
    assert breakdown["competency_evidence"][0]["evidence_record_ids"] == [second.id]
    assert list_capability_estimates(db_session, target_id=target.id) == [estimate]
    assert first.id != second.id


def test_capability_estimate_reports_low_confidence_for_sparse_evidence(
    db_session: Session,
) -> None:
    """Sparse target evidence stays cautious and exposes weak nodes."""
    learner_id = _learner(db_session)
    node = create_knowledge_node(
        db_session,
        title="Sparse node",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner_id,
        knowledge_node_id=node.id,
        knowledge_type="procedural",
        correctness=True,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Sparse target",
        target_node_ids=[node.id],
        confidence_threshold=0.8,
    )

    estimate = recompute_capability_estimate(db_session, target_id=target.id)

    assert estimate.current_score == 1.0
    assert estimate.confidence < 0.5
    assert estimate.weak_node_ids == [node.id]
    assert "confidence is low" in estimate.commentary
