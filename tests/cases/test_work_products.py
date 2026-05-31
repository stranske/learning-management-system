"""Tests for transfer-case work product scoring and revision integration."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.cases.models import CaseStep
from lms.cases.repository import (
    create_case,
    create_work_product,
    request_work_product_revision,
    score_work_product,
)
from lms.evidence.repository import list_evidence_records
from lms.feedback.models import RubricScore
from lms.feedback.repository import (
    create_feedback_action,
    create_revision_request,
    create_rubric,
    list_feedback_records,
)
from lms.graphs.repository import create_knowledge_node


def _seed_case_with_rubric(db_session: Session) -> tuple[str, str, str]:
    """Create a published node, personal rubric, and a case linking both."""
    node = create_knowledge_node(
        db_session,
        title="Transfer reasoning",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Transfer rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
        knowledge_node_id=node.id,
    )
    case = create_case(
        db_session,
        title="Assess a policy exception",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=node.id,
        steps=[{"step_order": 1, "title": "Recommend", "prompt": "Recommend the next action."}],
    )
    db_session.commit()
    return node.id, rubric.id, case.id


def test_work_product_scoring_creates_transfer_evidence(db_session: Session) -> None:
    """Scoring a work product records a rubric score and case-scoped transfer evidence."""
    node_id, rubric_id, case_id = _seed_case_with_rubric(db_session)

    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Recommend granting the exception because the controlling clause permits it.",
    )
    db_session.commit()

    score = score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 8, "max_points": 10}],
        raw_score=8.0,
        max_score=10.0,
        transfer_distance="far",
    )
    db_session.commit()

    assert work_product.rubric_score_id == score.id
    assert work_product.status == "scored"
    assert score.evidence_record_id is not None
    assert score.normalized_score == pytest.approx(0.8)

    evidence_records = list_evidence_records(
        db_session, learner_id="learner-1", knowledge_node_id=node_id
    )
    assert len(evidence_records) == 1
    transfer_evidence = evidence_records[0]
    assert transfer_evidence.id == score.evidence_record_id
    assert transfer_evidence.prompt_id == case_id
    assert transfer_evidence.transfer_distance == "far"
    assert transfer_evidence.validity_scope == f"transfer-case:{case_id}"
    assert transfer_evidence.normalized_score == pytest.approx(0.8)


def test_work_product_scoring_aligns_attempt_and_evidence_prompt_ids(
    db_session: Session,
) -> None:
    """Transfer evidence uses the same prompt id as the work-product attempt."""
    node_id, rubric_id, case_id = _seed_case_with_rubric(db_session)
    step_id = db_session.scalar(select(CaseStep.id).where(CaseStep.case_id == case_id))
    assert step_id is not None
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        case_step_id=step_id,
        body="Recommend granting the exception.",
    )
    db_session.commit()

    score = score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 8, "max_points": 10}],
        raw_score=8.0,
        max_score=10.0,
    )
    db_session.commit()

    evidence = list_evidence_records(db_session, learner_id="learner-1", knowledge_node_id=node_id)[
        0
    ]
    assert evidence.attempt_id == score.attempt_id
    assert evidence.prompt_id == step_id


def test_work_product_scoring_requires_a_linked_rubric(db_session: Session) -> None:
    """A work product without a rubric cannot be scored."""
    _, _, case_id = _seed_case_with_rubric(db_session)
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="rationale",
        body="No rubric attached to this submission.",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="requires a linked rubric"):
        score_work_product(
            db_session,
            work_product,
            scorer_type="rubric-local",
            criterion_scores=[],
            raw_score=1.0,
            max_score=2.0,
        )


def test_case_feedback_can_request_work_product_revision(db_session: Session) -> None:
    """Case feedback can open a revision loop that links back to the work product."""
    _, rubric_id, case_id = _seed_case_with_rubric(db_session)

    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Initial recommendation that misreads the controlling clause.",
    )
    score = score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 4, "max_points": 10}],
        raw_score=4.0,
        max_score=10.0,
    )
    db_session.commit()

    feedback_record = list_feedback_records(db_session, attempt_id=score.attempt_id)[0]
    action = create_feedback_action(
        db_session,
        feedback_record_id=feedback_record.id,
        learner_id="learner-1",
        action_type="revision",
        title="Revise the memo to apply the controlling clause correctly.",
    )
    db_session.commit()

    request = request_work_product_revision(
        db_session,
        work_product,
        feedback_record_id=feedback_record.id,
        feedback_action_id=action.id,
    )
    db_session.commit()

    assert request.work_product_id == work_product.id
    assert request.status == "open"
    assert work_product.revision_request_id == request.id
    assert work_product.status == "revision-requested"

    # Opening the request moves the linked revision action into progress.
    db_session.refresh(action)
    assert action.status == "in-progress"


def test_revision_request_create_syncs_work_product_link(db_session: Session) -> None:
    """Generic revision creation keeps the work-product pointer in sync."""
    _, rubric_id, case_id = _seed_case_with_rubric(db_session)
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Initial recommendation that needs revision.",
    )
    db_session.commit()

    request = create_revision_request(
        db_session,
        learner_id="learner-1",
        work_product_id=work_product.id,
    )
    db_session.commit()

    assert request.work_product_id == work_product.id
    assert request.prompt_id == case_id
    assert work_product.revision_request_id == request.id
    assert work_product.status == "revision-requested"


def test_rescore_terminal_product_rejected(db_session: Session) -> None:
    """A second score on a terminal (``scored``) product is rejected with no new evidence."""
    node_id, rubric_id, case_id = _seed_case_with_rubric(db_session)
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Recommend granting the exception.",
    )
    db_session.commit()

    score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 8, "max_points": 10}],
        raw_score=8.0,
        max_score=10.0,
        transfer_distance="far",
    )
    db_session.commit()
    assert work_product.status == "scored"

    with pytest.raises(ValueError, match="not in a scoreable state"):
        score_work_product(
            db_session,
            work_product,
            scorer_type="rubric-local",
            criterion_scores=[{"criterion": "analysis", "points": 9, "max_points": 10}],
            raw_score=9.0,
            max_score=10.0,
            transfer_distance="far",
        )

    # The guard runs before any write, so no second EvidenceRecord/RubricScore appears.
    evidence_records = list_evidence_records(
        db_session, learner_id="learner-1", knowledge_node_id=node_id
    )
    assert len(evidence_records) == 1
    scores = list(
        db_session.scalars(select(RubricScore).where(RubricScore.learner_id == "learner-1"))
    )
    assert len(scores) == 1


def test_rescore_stale_loaded_product_rejected(db_session: Session) -> None:
    """The scoreability guard refreshes persisted state before scoring."""
    node_id, rubric_id, case_id = _seed_case_with_rubric(db_session)
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Recommend granting the exception.",
    )
    db_session.commit()

    stale_session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    stale_session = stale_session_factory()
    try:
        stale_product = stale_session.get(type(work_product), work_product.id)
        assert stale_product is not None
        assert stale_product.status == "submitted"

        score_work_product(
            db_session,
            work_product,
            scorer_type="rubric-local",
            criterion_scores=[{"criterion": "analysis", "points": 8, "max_points": 10}],
            raw_score=8.0,
            max_score=10.0,
            transfer_distance="far",
        )
        db_session.commit()

        assert stale_product.status == "submitted"
        with pytest.raises(ValueError, match="not in a scoreable state"):
            score_work_product(
                stale_session,
                stale_product,
                scorer_type="rubric-local",
                criterion_scores=[{"criterion": "analysis", "points": 9, "max_points": 10}],
                raw_score=9.0,
                max_score=10.0,
                transfer_distance="far",
            )
    finally:
        stale_session.close()

    evidence_records = list_evidence_records(
        db_session, learner_id="learner-1", knowledge_node_id=node_id
    )
    assert len(evidence_records) == 1
    scores = list(
        db_session.scalars(select(RubricScore).where(RubricScore.learner_id == "learner-1"))
    )
    assert len(scores) == 1


def test_revision_rescore_supersedes_prior_score(db_session: Session) -> None:
    """An allowed revision re-score leaves exactly one RubricScore + transfer evidence."""
    node_id, rubric_id, case_id = _seed_case_with_rubric(db_session)
    work_product = create_work_product(
        db_session,
        case_id=case_id,
        learner_id="learner-1",
        submission_type="memo",
        rubric_id=rubric_id,
        body="Initial recommendation that needs revision.",
    )
    db_session.commit()

    first = score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 6, "max_points": 10}],
        raw_score=6.0,
        max_score=10.0,
        transfer_distance="far",
    )
    db_session.commit()
    first_id = first.id
    first_evidence_id = first.evidence_record_id
    assert work_product.status == "scored"

    request_work_product_revision(db_session, work_product)
    db_session.commit()
    assert work_product.status == "revision-requested"

    second = score_work_product(
        db_session,
        work_product,
        scorer_type="rubric-local",
        criterion_scores=[{"criterion": "analysis", "points": 9, "max_points": 10}],
        raw_score=9.0,
        max_score=10.0,
        transfer_distance="far",
    )
    db_session.commit()

    assert work_product.status == "scored"
    assert work_product.rubric_score_id == second.id
    assert second.id != first_id

    evidence_records = list_evidence_records(
        db_session, learner_id="learner-1", knowledge_node_id=node_id
    )
    assert len(evidence_records) == 1
    assert evidence_records[0].id == second.evidence_record_id
    assert evidence_records[0].id != first_evidence_id

    scores = list(
        db_session.scalars(select(RubricScore).where(RubricScore.learner_id == "learner-1"))
    )
    assert len(scores) == 1
    assert scores[0].id == second.id
