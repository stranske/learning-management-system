"""Tests for rubric repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.feedback.models import Rubric, RubricCriterion
from lms.feedback.repository import (
    create_rubric,
    create_rubric_criterion,
    get_rubric,
    update_rubric_criterion,
)
from lms.graphs.repository import create_knowledge_node


def test_rubric_criteria_order_and_score_bounds(db_session: Session) -> None:
    """Rubric criteria preserve order and require positive point values."""
    rubric = create_rubric(
        db_session,
        title="Reasoning quality",
        ownership_scope="personal",
        authoring_actor="user:alice",
        criteria=[
            {
                "criterion_order": 2,
                "description": "Uses source evidence.",
                "max_points": 2,
                "performance_levels": {"full": "Cites a relevant source."},
            },
            {
                "criterion_order": 1,
                "description": "States the conclusion.",
                "max_points": 1,
                "performance_levels": {"full": "Conclusion is explicit."},
            },
        ],
    )
    db_session.commit()

    stored = get_rubric(db_session, rubric.id)
    assert stored is not None
    assert [criterion.criterion_order for criterion in stored.criteria] == [1, 2]
    assert [criterion.max_points for criterion in stored.criteria] == [1, 2]

    with pytest.raises(ValueError, match="criterion order must be unique"):
        create_rubric(
            db_session,
            title="Duplicate orders",
            ownership_scope="personal",
            authoring_actor="user:alice",
            criteria=[
                {
                    "criterion_order": 1,
                    "description": "First",
                    "max_points": 1,
                },
                {
                    "criterion_order": 1,
                    "description": "Second",
                    "max_points": 1,
                },
            ],
        )


def test_rubric_rejects_cross_scope_knowledge_node(db_session: Session) -> None:
    """A personal-scope rubric cannot silently link to an institutional node."""
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional proof standard",
        knowledge_type="judgment",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )

    with pytest.raises(ValueError, match="knowledge node must match"):
        create_rubric(
            db_session,
            title="Personal transfer rubric",
            ownership_scope="personal",
            authoring_actor="user:alice",
            knowledge_node_id=institutional_node.id,
        )


@pytest.mark.parametrize("operation", ["nested", "create", "update"])
@pytest.mark.parametrize(
    ("order", "points", "notice"),
    [
        (0, 1.0, "criterion_order"),
        (-1, 1.0, "criterion_order"),
        (2, 0.0, "max_points"),
        (2, -5.0, "max_points"),
        (2, float("nan"), "max_points"),
        (2, float("inf"), "max_points"),
        (2, float("-inf"), "max_points"),
    ],
)
def test_invalid_criterion_numbers_preserve_session_and_data(
    db_session: Session, operation: str, order: int, points: float, notice: str
) -> None:
    """Invalid input fails before flush or mutation, including nested creation."""
    rubric = create_rubric(
        db_session,
        title="Existing rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
        criteria=[{"criterion_order": 1, "description": "Original", "max_points": 2.0}],
    )
    db_session.commit()
    criterion = rubric.criteria[0]
    with pytest.raises(ValueError, match=notice):
        if operation == "nested":
            create_rubric(
                db_session,
                title="Rejected rubric",
                ownership_scope="personal",
                authoring_actor="user:alice",
                criteria=[
                    {"criterion_order": 1, "description": "Valid", "max_points": 1.0},
                    {"criterion_order": order, "description": "Invalid", "max_points": points},
                ],
            )
        elif operation == "create":
            create_rubric_criterion(
                db_session,
                rubric_id=rubric.id,
                criterion_order=order,
                description="Invalid",
                max_points=points,
            )
        else:
            update_rubric_criterion(
                db_session,
                criterion,
                criterion_order=order,
                description="Rejected change",
                max_points=points,
            )
    # Commit without rollback proves the session has not been poisoned by a failed flush.
    db_session.commit()
    db_session.refresh(criterion)
    assert (criterion.criterion_order, criterion.max_points, criterion.description) == (
        1,
        2.0,
        "Original",
    )
    assert db_session.query(Rubric).count() == 1
    assert db_session.query(RubricCriterion).count() == 1
    added = create_rubric_criterion(
        db_session,
        rubric_id=rubric.id,
        criterion_order=2,
        description="Valid next request",
        max_points=0.5,
    )
    update_rubric_criterion(db_session, added, criterion_order=3, max_points=1.5)
    db_session.commit()
    db_session.refresh(added)
    assert (added.criterion_order, added.max_points) == (3, 1.5)
