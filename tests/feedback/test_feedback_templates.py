"""Tests for reusable deterministic feedback templates."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.feedback.repository import (
    archive_feedback_template,
    create_feedback_template,
    list_feedback_templates,
    render_feedback_template,
)
from lms.graphs.repository import create_knowledge_node


def test_render_feedback_template_with_goal_gap_next_action(db_session: Session) -> None:
    """Templates render goal, gap, and next-action placeholders deterministically."""
    node = create_knowledge_node(
        db_session,
        title="Fractions",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    template = create_feedback_template(
        db_session,
        name="Gap coaching",
        template_body="Goal: {goal}\nGap: {gap}\nNext: {next_action}",
        placeholder_schema={"required": ["goal", "gap", "next_action"]},
        feedback_level="coaching",
        action_type="retry",
        ownership_scope="personal",
        status="published",
        authoring_actor="user:alice",
        knowledge_node_ids=[node.id],
    )
    db_session.commit()

    rendered = render_feedback_template(
        template,
        {
            "goal": "Use equivalent fractions",
            "gap": "Explain the common denominator choice",
            "next_action": "Retry with one sentence of rationale",
        },
    )

    assert "Goal: Use equivalent fractions" in rendered
    assert "Gap: Explain the common denominator choice" in rendered
    assert "Next: Retry with one sentence of rationale" in rendered
    assert list_feedback_templates(db_session, knowledge_node_id=node.id)[0].id == template.id


def test_template_rejects_missing_required_placeholder(db_session: Session) -> None:
    """Required placeholder values produce deterministic validation errors."""
    template = create_feedback_template(
        db_session,
        name="Gap coaching",
        template_body="Goal: {goal}\nGap: {gap}\nNext: {next_action}",
        placeholder_schema={"required": ["goal", "gap", "next_action"]},
        feedback_level="coaching",
        action_type="retry",
        ownership_scope="personal",
        authoring_actor="user:alice",
    )

    with pytest.raises(ValueError, match="missing required placeholder values: gap"):
        render_feedback_template(
            template,
            {"goal": "Use evidence", "next_action": "Try again with one citation"},
        )


def test_template_rejects_fixed_ability_labels(db_session: Session) -> None:
    """Template copy avoids persistent trait labels in default feedback language."""
    with pytest.raises(ValueError, match="avoid fixed ability labels"):
        create_feedback_template(
            db_session,
            name="Trait label",
            template_body="You are a weak student. Try {next_action}.",
            placeholder_schema={"required": ["next_action"]},
            feedback_level="coaching",
            action_type="retry",
            ownership_scope="personal",
            authoring_actor="user:alice",
        )


def test_archive_feedback_template_removes_it_from_published_filter(
    db_session: Session,
) -> None:
    """Archived templates remain durable but leave the published authoring set."""
    template = create_feedback_template(
        db_session,
        name="Gap coaching",
        template_body="Next: {next_action}",
        placeholder_schema={"required": ["next_action"]},
        feedback_level="coaching",
        action_type="retry",
        ownership_scope="personal",
        status="published",
        authoring_actor="user:alice",
    )

    archive_feedback_template(db_session, template)

    assert template.status == "archived"
    assert list_feedback_templates(db_session, status="published") == []
