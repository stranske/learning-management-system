"""Tests for capability gap analyses."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    list_gap_analyses,
    recompute_capability_estimate,
)
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user


def _learner(db_session: Session, *, suffix: str) -> str:
    user = User(
        email=f"gap-{suffix}@example.test",
        username=f"gap-{suffix}",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    return create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    ).id


def test_gap_analysis_identifies_missing_transfer_evidence(db_session: Session) -> None:
    """A sparse transfer target produces actionable gap items with node refs."""
    learner_id = _learner(db_session, suffix="missing-transfer")
    node = create_knowledge_node(
        db_session,
        title="Apply evidence in a new case",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Handle a transfer case independently",
        target_node_ids=[node.id],
        required_evidence_types=["transfer-case"],
        confidence_threshold=0.8,
    )
    estimate = recompute_capability_estimate(db_session, target_id=target.id)

    analysis = create_gap_analysis(db_session, estimate_id=estimate.id)

    assert analysis.target_id == target.id
    assert analysis.estimate_id == estimate.id
    assert analysis.learner_id == learner_id
    assert analysis.severity == "high"
    assert analysis.required_evidence == ["transfer-case"]
    assert "collect-initial-evidence" in analysis.recommended_action_types
    assert "transfer-case" in analysis.recommended_action_types
    assert {
        item["gap_type"] for item in analysis.gap_items if item["knowledge_node_id"] == node.id
    } >= {"missing_evidence", "weak_mastery", "transfer_evidence_needed"}
    assert list_gap_analyses(db_session, target_id=target.id) == [analysis]


def test_gap_analysis_uses_nonpunitive_gap_language(db_session: Session) -> None:
    """Gap analysis language describes evidence states, not learner identity."""
    learner_id = _learner(db_session, suffix="nonpunitive")
    node = create_knowledge_node(
        db_session,
        title="Explain tradeoffs with less support",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner_id,
        knowledge_node_id=node.id,
        knowledge_type="judgment",
        normalized_score=0.55,
        hint_used=True,
        support_level="hint",
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Make unsupported evidence tradeoff decisions",
        target_node_ids=[node.id],
        confidence_threshold=0.8,
    )
    estimate = recompute_capability_estimate(db_session, target_id=target.id)

    analysis = create_gap_analysis(db_session, estimate_id=estimate.id)
    rationales = " ".join(str(item["rationale"]).lower() for item in analysis.gap_items)

    assert "support_dependence" in {item["gap_type"] for item in analysis.gap_items}
    assert "independent-practice" in analysis.recommended_action_types
    assert "learner" not in rationales
    assert "failure" not in rationales
    assert "deficient" not in rationales
