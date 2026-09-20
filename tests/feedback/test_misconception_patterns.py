"""Tests for deterministic misconception pattern matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from lms.feedback.models import MisconceptionPattern
from lms.feedback.repository import create_misconception_pattern, list_misconception_patterns
from lms.graphs.repository import create_knowledge_edge, create_knowledge_node


def test_pattern_matches_wrong_answer_signature(db_session: Session) -> None:
    """A configured signature can be matched without an LLM classifier."""
    node = create_knowledge_node(
        db_session,
        title="Solving linear equations",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    pattern = create_misconception_pattern(
        db_session,
        pattern_label="Combines unlike terms",
        wrong_answer_signature="adds denominator to numerator",
        diagnosis_text="The answer treats denominator addition as an equivalent operation.",
        target_knowledge_node_id=node.id,
        ownership_scope="personal",
        confidence=0.8,
        suggested_feedback_action_type="prerequisite-remediation",
    )
    db_session.commit()

    matches = list_misconception_patterns(
        db_session,
        ownership_scope="personal",
        target_knowledge_node_id=node.id,
        signature_text="Student adds denominator to numerator before simplifying.",
    )

    assert [match.id for match in matches] == [pattern.id]
    assert matches[0].suggested_feedback_action_type == "prerequisite-remediation"


def test_oldest_matching_pattern_survives_limit(db_session: Session) -> None:
    """Limit applies to matches, not to the newest candidate rows."""
    oldest = create_misconception_pattern(
        db_session,
        pattern_label="Oldest matching pattern",
        wrong_answer_signature="adds denominator",
        diagnosis_text="Oldest matching pattern must remain reachable.",
        target_knowledge_node_id=None,
        ownership_scope="personal",
        suggested_feedback_action_type="prerequisite-remediation",
    )
    base = datetime(2024, 1, 1, tzinfo=UTC)
    oldest.created_at = base
    for index in range(5):
        pattern = create_misconception_pattern(
            db_session,
            pattern_label=f"Newer nonmatch {index}",
            wrong_answer_signature=f"unrelated signature {index}",
            diagnosis_text="This pattern does not match the answer.",
            target_knowledge_node_id=None,
            ownership_scope="personal",
            suggested_feedback_action_type="prerequisite-remediation",
        )
        pattern.created_at = base + timedelta(days=index + 1)
    db_session.commit()

    matches = list_misconception_patterns(
        db_session,
        ownership_scope="personal",
        signature_text="Student adds denominator to numerator.",
        limit=3,
    )
    assert [pattern.id for pattern in matches] == [oldest.id]


def test_signature_branch_ordering_is_deterministic(db_session: Session) -> None:
    """Tied timestamps sort by ID in the signature branch too."""
    tied = datetime(2024, 1, 1, tzinfo=UTC)
    ids = [
        "00000000-0000-0000-0000-000000000003",
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    db_session.add_all(
        [
            MisconceptionPattern(
                id=pattern_id,
                pattern_label=f"Matching pattern {index}",
                wrong_answer_signature=f"matching signature {index}",
                diagnosis_text="Tied timestamp exercises the ID tiebreaker.",
                target_knowledge_node_id=None,
                ownership_scope="personal",
                suggested_feedback_action_type="prerequisite-remediation",
                created_at=tied,
            )
            for index, pattern_id in enumerate(ids)
        ]
    )
    db_session.commit()

    results = [
        [
            pattern.id
            for pattern in list_misconception_patterns(
                db_session,
                ownership_scope="personal",
                signature_text=(
                    "All matching signature 0, matching signature 1, matching signature 2."
                ),
                limit=3,
            )
        ]
        for _ in range(2)
    ]

    expected_ids = sorted(ids)
    assert results == [expected_ids, expected_ids]


def test_pattern_rejects_cross_scope_knowledge_node(db_session: Session) -> None:
    """Pattern-to-node links require an explicit matching ownership scope."""
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional prerequisite",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )

    with pytest.raises(
        ValueError, match="match ownership scope or have a published graph reference"
    ):
        create_misconception_pattern(
            db_session,
            pattern_label="Cross-scope link",
            wrong_answer_signature="wrong denominator",
            diagnosis_text="Scope mismatch must be explicit elsewhere.",
            target_knowledge_node_id=institutional_node.id,
            ownership_scope="personal",
            suggested_feedback_action_type="prerequisite-remediation",
        )


def test_pattern_allows_cross_scope_knowledge_node_with_graph_reference(
    db_session: Session,
) -> None:
    """A published graph reference is the explicit cross-scope exception."""
    personal_node = create_knowledge_node(
        db_session,
        title="Learner fraction gap",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional fraction prerequisite",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    create_knowledge_edge(
        db_session,
        source_node_id=personal_node.id,
        target_node_id=institutional_node.id,
        edge_type="prerequisite",
        scope="personal",
        target_scope="institutional",
        is_graph_reference=True,
        status="published",
        actor_id="user:alice",
    )

    pattern = create_misconception_pattern(
        db_session,
        pattern_label="Cross-scope graph reference",
        wrong_answer_signature="wrong denominator",
        diagnosis_text="The personal gap references an institutional prerequisite.",
        target_knowledge_node_id=institutional_node.id,
        ownership_scope="personal",
        suggested_feedback_action_type="prerequisite-remediation",
    )

    assert pattern.target_knowledge_node_id == institutional_node.id
    assert pattern.ownership_scope == "personal"
