"""Tests for rubric repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.feedback.repository import create_rubric, get_rubric
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
