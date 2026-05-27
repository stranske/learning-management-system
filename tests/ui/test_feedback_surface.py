"""Tests for learner feedback, hint, model-answer, and revision UI."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.repository import create_attempt
from lms.feedback.repository import (
    create_feedback_action,
    create_hint,
    create_model_answer,
    create_rubric,
    create_rubric_score,
    list_feedback_records,
    list_revision_requests,
)
from lms.graphs.models import KnowledgeNode
from lms.prompts.models import Prompt, PromptVersion


def _seed_feedback_context(
    session_factory: sessionmaker[Session],
) -> tuple[str, str, str]:
    with session_factory() as session:
        node = KnowledgeNode(
            id="node-feedback",
            title="Equation checks",
            knowledge_type="procedural",
            ownership_scope="personal",
            status="published",
        )
        session.add(node)
        prompt = Prompt(
            target_node_id=node.id,
            learning_goal_id="goal-feedback",
            knowledge_type="procedural",
            intended_cognitive_action="explain",
            demand_level="medium",
            expected_answer_form="short-text",
            status="draft",
            authoring_method="human-authored",
            authoring_actor="author-ui",
        )
        prompt.versions.append(
            PromptVersion(
                version_number=1,
                body="Explain how you checked the equation solution.",
                created_by="author-ui",
            )
        )
        session.add(prompt)
        session.flush()
        attempt = create_attempt(
            session,
            learner_id="learner-1",
            prompt_id=prompt.id,
            response_text="I solved x = 4 but did not check it.",
            confidence_rating=3,
            feedback={
                "goal": "Check equation solutions",
                "observed_evidence": "Solved the equation but skipped substitution.",
                "diagnosis": "The solving step is present.",
                "gap": "The answer was not substituted back into the original equation.",
                "next_action": "Revise with a substitution check.",
            },
        )
        records = list_feedback_records(session, attempt_id=attempt.id)
        record = records[0]
        action = create_feedback_action(
            session,
            feedback_record_id=record.id,
            learner_id="learner-1",
            attempt_id=attempt.id,
            prompt_id=prompt.id,
            action_type="revision",
            title="Revise with a substitution check.",
            instructions="Show the check after solving.",
        )
        record.next_action_ids = [action.id]
        rubric = create_rubric(
            session,
            title="Equation explanation rubric",
            ownership_scope="personal",
            authoring_actor="author-ui",
            prompt_id=prompt.id,
            status="published",
            criteria=[
                {
                    "criterion_order": 1,
                    "description": "Shows the substitution check",
                    "max_points": 2.0,
                    "performance_levels": {},
                }
            ],
        )
        create_rubric_score(
            session,
            rubric_id=rubric.id,
            attempt_id=attempt.id,
            learner_id="learner-1",
            scorer_type="rule",
            raw_score=1.0,
            normalized_score=0.5,
            max_score=2.0,
            criterion_scores=[
                {
                    "criterion_id": rubric.criteria[0].id,
                    "criterion_order": 1,
                    "description": "Shows the substitution check",
                    "points": 1.0,
                    "max_points": 2.0,
                    "rationale": "The check is missing from the response.",
                }
            ],
            feedback_record_id=record.id,
        )
        hint = create_hint(
            session,
            prompt_id=prompt.id,
            hint_text="Substitute the value back into the original equation.",
            reveal_order=1,
            authoring_actor="author-ui",
        )
        model_answer = create_model_answer(
            session,
            prompt_id=prompt.id,
            answer_body="The solution checks because both sides evaluate to 9.",
            authoring_actor="author-ui",
        )
        session.commit()
        return record.id, hint.id, model_answer.id


def test_feedback_view_shows_goal_gap_next_action_and_rubric_breakdown(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    feedback_id, _, _ = _seed_feedback_context(session_factory)

    response = client.get(f"/app/learner/feedback/{feedback_id}")

    assert response.status_code == 200
    assert "Check equation solutions" in response.text
    assert "The answer was not substituted back" in response.text
    assert "Revise with a substitution check." in response.text
    assert "Shows the substitution check" in response.text
    assert "1.0 / 2.0 points" in response.text
    assert "The solution checks because" not in response.text


def test_hint_reveal_updates_feedback_view_without_exposing_model_answer(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    feedback_id, hint_id, _ = _seed_feedback_context(session_factory)

    response = client.post(f"/app/learner/feedback/{feedback_id}/hints/{hint_id}/reveal")

    assert response.status_code == 200
    assert "Hint revealed: Substitute the value back" in response.text
    assert "The solution checks because" not in response.text


def test_revision_request_can_be_submitted_from_feedback_view(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    feedback_id, _, _ = _seed_feedback_context(session_factory)

    response = client.post(
        f"/app/learner/feedback/{feedback_id}/revision",
        data={
            "response_text": "Revised: x = 4 checks because both sides equal 9.",
            "confidence_rating": "4",
        },
    )

    assert response.status_code == 200
    assert "Revision submitted. Status: submitted." in response.text
    with session_factory() as session:
        revisions = list_revision_requests(session, feedback_record_id=feedback_id)
        assert len(revisions) == 1
        assert revisions[0].status == "submitted"
        assert revisions[0].revised_attempt_id is not None
