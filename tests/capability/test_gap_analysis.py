"""Tests for capability gap analyses."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.models import GapAnalysis
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    list_gap_analyses,
    recompute_capability_estimate,
)
from lms.cases.repository import create_case, create_work_product, score_work_product
from lms.evidence.repository import create_evidence_record
from lms.feedback.repository import create_rubric
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


def test_gap_analysis_clears_transfer_evidence_needed_after_case_score(
    db_session: Session,
) -> None:
    """A scored work product closes the transfer-evidence gap for that node."""
    learner_id = _learner(db_session, suffix="transfer-closed")
    node = create_knowledge_node(
        db_session,
        title="Apply a policy in a transfer case",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Transfer evidence rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
        knowledge_node_id=node.id,
    )
    case = create_case(
        db_session,
        title="Review a client exception",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=node.id,
        status="published",
        steps=[{"step_order": 1, "title": "Recommend", "prompt": "Recommend a path."}],
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Handle transfer case evidence",
        target_node_ids=[node.id],
        required_evidence_types=["transfer-case"],
        confidence_threshold=0.8,
    )
    create_evidence_record(
        db_session,
        learner_id=learner_id,
        knowledge_node_id=node.id,
        knowledge_type="judgment",
        normalized_score=0.85,
        support_level="hint",
        hint_used=True,
    )
    initial_estimate = recompute_capability_estimate(db_session, target_id=target.id)
    initial_analysis = create_gap_analysis(db_session, estimate_id=initial_estimate.id)

    initial_gap_types = {item["gap_type"] for item in initial_analysis.gap_items}
    assert "transfer_evidence_needed" in initial_gap_types

    work_product = create_work_product(
        db_session,
        case_id=case.id,
        learner_id=learner_id,
        submission_type="memo",
        rubric_id=rubric.id,
        body="Recommend the exception path and explain the policy tradeoff.",
    )
    score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-self",
        criterion_scores=[{"criterion": "transfer", "points": 3, "max_points": 4}],
        raw_score=3.0,
        max_score=4.0,
        transfer_distance="near",
    )

    updated_estimate = recompute_capability_estimate(db_session, target_id=target.id)
    updated_analysis = create_gap_analysis(db_session, estimate_id=updated_estimate.id)

    updated_gap_types = {item["gap_type"] for item in updated_analysis.gap_items}
    assert "transfer_evidence_needed" not in updated_gap_types
    assert "transfer-case" not in updated_analysis.recommended_action_types
    node_rows = updated_estimate.evidence_breakdown["target_node_estimates"]
    assert node_rows[0]["has_transfer_evidence"] is True


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
    gap_types = {item["gap_type"] for item in analysis.gap_items}
    rationales = " ".join(str(item["rationale"]).lower() for item in analysis.gap_items)

    assert "low_confidence_evidence" in gap_types
    assert "stale_evidence" not in gap_types
    assert "support_dependence" in gap_types
    assert "collect-stronger-evidence" in analysis.recommended_action_types
    assert "independent-practice" in analysis.recommended_action_types
    assert "confidence coverage" in rationales
    assert "stale" not in rationales
    assert "learner" not in rationales
    assert "failure" not in rationales
    assert "deficient" not in rationales


def test_gap_analysis_scope_contract_is_personal_only() -> None:
    """Gap analyses expose one clear ownership-scope invariant."""
    constraint_names = {
        constraint.name
        for constraint in GapAnalysis.__table__.constraints
        if constraint.name is not None
    }

    assert "ck_gap_analyses_personal_scope_only" in constraint_names
    assert "ck_gap_analyses_ownership_scope_valid" not in constraint_names
