"""Tests for deterministic misconception pattern matching."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.feedback.repository import create_misconception_pattern, list_misconception_patterns
from lms.graphs.repository import create_knowledge_node


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

    with pytest.raises(ValueError, match="knowledge node must match ownership scope"):
        create_misconception_pattern(
            db_session,
            pattern_label="Cross-scope link",
            wrong_answer_signature="wrong denominator",
            diagnosis_text="Scope mismatch must be explicit elsewhere.",
            target_knowledge_node_id=institutional_node.id,
            ownership_scope="personal",
            suggested_feedback_action_type="prerequisite-remediation",
        )
