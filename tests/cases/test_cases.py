"""Tests for transfer case shell repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.cases.repository import add_decision_point, add_evidence_packet, create_case, get_case
from lms.feedback.repository import create_rubric
from lms.graphs.repository import create_knowledge_node


def test_case_steps_are_ordered_and_scope_checked(db_session: Session) -> None:
    """Case shell steps are deterministic and links must stay in the same scope."""
    personal_node = create_knowledge_node(
        db_session,
        title="Transfer reasoning",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional policy",
        knowledge_type="judgment",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Transfer rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
    )

    case = create_case(
        db_session,
        title="Assess a policy exception",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=personal_node.id,
        steps=[
            {
                "step_order": 2,
                "title": "Recommend",
                "prompt": "Recommend the next action.",
            },
            {
                "step_order": 1,
                "title": "Triage",
                "prompt": "Identify the key facts.",
            },
        ],
    )
    db_session.commit()

    stored = get_case(db_session, case.id)
    assert stored is not None
    assert [step.step_order for step in stored.steps] == [1, 2]
    assert stored.knowledge_node_id == personal_node.id
    assert stored.rubric_id == rubric.id

    with pytest.raises(ValueError, match="knowledge node must exist and match"):
        create_case(
            db_session,
            title="Invalid cross-scope case",
            ownership_scope="personal",
            knowledge_node_id=institutional_node.id,
        )

    with pytest.raises(ValueError, match="case step order must be unique"):
        create_case(
            db_session,
            title="Duplicate step order",
            ownership_scope="personal",
            steps=[
                {"step_order": 1, "title": "A", "prompt": "First."},
                {"step_order": 1, "title": "B", "prompt": "Second."},
            ],
        )


def test_decision_point_links_to_case_step_and_evidence_packet(db_session: Session) -> None:
    """Decision points are stored against a step and optional same-case evidence packet."""
    case = create_case(
        db_session,
        title="Choose evidence",
        ownership_scope="personal",
        steps=[{"step_order": 1, "title": "Read", "prompt": "Read the packet."}],
    )
    packet = add_evidence_packet(
        db_session,
        case_id=case.id,
        title="Evidence packet",
        summary="Relevant case evidence.",
        packet_metadata={"source": "fixture"},
    )
    decision = add_decision_point(
        db_session,
        case_step_id=case.steps[0].id,
        evidence_packet_id=packet.id,
        title="Select the controlling fact",
        prompt="Which fact controls the recommendation?",
        decision_type="evidence-selection",
        options=[{"label": "Contract language", "value": "contract"}],
    )
    db_session.commit()

    assert decision.evidence_packet_id == packet.id
    stored = get_case(db_session, case.id)
    assert stored is not None
    assert stored.steps[0].decision_points[0].title == "Select the controlling fact"

    other_case = create_case(
        db_session,
        title="Other case",
        ownership_scope="personal",
        steps=[{"step_order": 1, "title": "Other", "prompt": "Other prompt."}],
    )
    with pytest.raises(ValueError, match="same case"):
        add_decision_point(
            db_session,
            case_step_id=other_case.steps[0].id,
            evidence_packet_id=packet.id,
            title="Invalid cross-case link",
            prompt="This should fail.",
            decision_type="single-choice",
        )

