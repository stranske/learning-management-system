"""Learner feedback, hint reveal, and revision UI tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.evidence.models import Attempt
from lms.feedback.models import HintReveal, ModelAnswerReveal, RevisionRequest, Rubric, RubricScore
from lms.feedback.repository import (
    create_feedback_action,
    create_feedback_record,
    create_hint,
    create_model_answer,
)
from lms.learners.models import Learner
from lms.prompts.models import Prompt
from lms.settings import Settings, get_settings


def _seed_private_feedback(session: Session) -> tuple[User, User, dict[str, str]]:
    owner = User(username="feedback-owner", display_name="Owner")
    foreign = User(username="feedback-foreign", display_name="Foreign")
    session.add_all([owner, foreign])
    session.flush()
    learner = Learner(id="learner-1", user_id=owner.id, display_name="Owner learner")
    session.add(learner)
    prompt = _prompt()
    session.add(prompt)
    session.flush()
    attempt = _attempt(prompt.id)
    session.add(attempt)
    session.flush()
    record = create_feedback_record(
        session,
        learner_id=learner.id,
        attempt_id=attempt.id,
        prompt_id=prompt.id,
        goal="Private feedback goal",
        observed_evidence="Private diagnostic evidence",
    )
    hint = create_hint(
        session,
        prompt_id=prompt.id,
        hint_text="Private hint",
        reveal_order=1,
        authoring_actor="author-1",
    )
    answer = create_model_answer(
        session,
        prompt_id=prompt.id,
        answer_body="Private model answer",
        authoring_actor="author-1",
    )
    session.commit()
    base = f"/app/learner/feedback/{record.id}"
    return (
        owner,
        foreign,
        {
            "detail": base,
            "hint": f"{base}/hints/{hint.id}/reveal",
            "answer": f"{base}/model-answers/{answer.id}/reveal",
            "revision": f"{base}/revision",
        },
    )


def _assert_no_feedback_mutations(session: Session) -> None:
    assert session.query(HintReveal).count() == 0
    assert session.query(ModelAnswerReveal).count() == 0
    assert session.query(RevisionRequest).count() == 0
    attempt = session.query(Attempt).one()
    assert attempt.hint_used is False
    assert attempt.response_text == "Initial response"


@pytest.mark.parametrize("route", ["detail", "hint", "answer", "revision"])
def test_feedback_surface_rejects_foreign_learner_access(
    api_client: tuple[TestClient, sessionmaker[Session]],
    route: str,
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _, foreign, paths = _seed_private_feedback(session)
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    client.app.dependency_overrides[require_authenticated_user] = lambda: foreign

    response = client.request(
        "GET" if route == "detail" else "POST",
        paths[route],
        data={"response_text": "Forged revision", "confidence_rating": "4"},
    )

    assert response.status_code == 404
    assert "Private" not in response.text
    with session_factory() as session:
        _assert_no_feedback_mutations(session)


@pytest.mark.parametrize("auth_required", [True, False])
@pytest.mark.parametrize("route", ["detail", "hint", "answer", "revision"])
def test_feedback_surface_allows_owner_and_local_access(
    api_client: tuple[TestClient, sessionmaker[Session]],
    route: str,
    auth_required: bool,
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        owner, foreign, paths = _seed_private_feedback(session)
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=auth_required)
    client.app.dependency_overrides[require_authenticated_user] = lambda: (
        owner if auth_required else foreign
    )

    response = client.request(
        "GET" if route == "detail" else "POST",
        paths[route],
        data={"response_text": "Authorized revision", "confidence_rating": "4"},
    )

    assert response.status_code == 200
    assert {
        "detail": "Private diagnostic evidence",
        "hint": "Hint revealed: Private hint",
        "answer": "Model answer revealed: Private model answer",
        "revision": "Revision submitted. Status: submitted.",
    }[route] in response.text
    with session_factory() as session:
        assert session.query(HintReveal).count() == int(route == "hint")
        assert session.query(ModelAnswerReveal).count() == int(route == "answer")
        assert session.query(RevisionRequest).count() == int(route == "revision")
        assert session.query(Attempt).count() == 1 + int(route == "revision")


@pytest.mark.parametrize("route", ["detail", "hint", "answer", "revision"])
@pytest.mark.parametrize("accept, status", [("text/html", 302), ("application/json", 401)])
def test_feedback_surface_requires_login(
    api_client: tuple[TestClient, sessionmaker[Session]],
    route: str,
    accept: str,
    status: int,
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _, _, paths = _seed_private_feedback(session)
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)

    response = client.request(
        "GET" if route == "detail" else "POST",
        paths[route],
        data={"response_text": "Anonymous revision"},
        headers={"Accept": accept},
        follow_redirects=False,
    )

    assert response.status_code == status
    assert "Private" not in response.text
    with session_factory() as session:
        _assert_no_feedback_mutations(session)


def test_feedback_view_shows_goal_gap_next_action_and_rubric_breakdown(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        prompt = _prompt()
        session.add(prompt)
        session.flush()
        attempt = _attempt(prompt.id)
        session.add(attempt)
        session.flush()
        record = create_feedback_record(
            session,
            learner_id="learner-1",
            attempt_id=attempt.id,
            prompt_id=prompt.id,
            feedback_level="remediation",
            goal="Use source evidence to explain the decision",
            observed_evidence="The response named a conclusion without evidence.",
            diagnosis="The answer needs a cited reason.",
            gap="Missing source-backed reasoning",
        )
        create_feedback_action(
            session,
            learner_id="learner-1",
            feedback_record_id=record.id,
            attempt_id=attempt.id,
            prompt_id=prompt.id,
            action_type="revision",
            title="Revise with one cited reason",
            instructions="Add the source-backed reason before resubmitting.",
        )
        rubric = Rubric(
            title="Evidence use",
            ownership_scope="personal",
            status="published",
            authoring_actor="author-1",
            reviewing_actor="reviewer-1",
        )
        session.add(rubric)
        session.flush()
        session.add(
            RubricScore(
                rubric_id=rubric.id,
                attempt_id=attempt.id,
                learner_id="learner-1",
                scorer_type="deterministic",
                raw_score=2,
                normalized_score=0.5,
                max_score=4,
                criterion_scores=[
                    {
                        "description": "Uses source evidence",
                        "points": 2,
                        "max_points": 4,
                        "rationale": "Names the source to add next.",
                    }
                ],
            )
        )
        session.commit()
        record_id = record.id

    response = client.get(f"/app/learner/feedback/{record_id}")

    assert response.status_code == 200
    html = response.text
    assert "Use source evidence to explain the decision" in html
    assert "Missing source-backed reasoning" in html
    assert "Revise with one cited reason" in html
    assert "Uses source evidence" in html
    assert "2 / 4 points" in html
    assert "lazy" not in html.lower()
    assert "bad learner" not in html.lower()


def test_hint_reveal_updates_feedback_view_without_exposing_model_answer(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        prompt = _prompt()
        session.add(prompt)
        session.flush()
        attempt = _attempt(prompt.id)
        session.add(attempt)
        session.flush()
        record = create_feedback_record(
            session,
            learner_id="learner-1",
            attempt_id=attempt.id,
            prompt_id=prompt.id,
            goal="Connect the answer to evidence",
            observed_evidence="The response was partly supported.",
            gap="Needs one citation",
        )
        hint = create_hint(
            session,
            prompt_id=prompt.id,
            hint_text="Look for the sentence that names the cause.",
            reveal_order=1,
            authoring_actor="author-1",
        )
        create_model_answer(
            session,
            prompt_id=prompt.id,
            answer_body="Hidden complete model answer.",
            authoring_actor="author-1",
        )
        session.commit()
        record_id = record.id
        hint_id = hint.id
        attempt_id = attempt.id

    response = client.post(f"/app/learner/feedback/{record_id}/hints/{hint_id}/reveal")

    assert response.status_code == 200
    assert "Hint revealed: Look for the sentence that names the cause." in response.text
    assert "Hidden complete model answer." not in response.text
    with session_factory() as session:
        loaded_attempt = session.get(Attempt, attempt_id)
        assert loaded_attempt is not None
        assert loaded_attempt.hint_used is True


def test_revision_request_can_be_submitted_from_feedback_view(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        prompt = _prompt()
        session.add(prompt)
        session.flush()
        attempt = _attempt(prompt.id)
        session.add(attempt)
        session.flush()
        record = create_feedback_record(
            session,
            learner_id="learner-1",
            attempt_id=attempt.id,
            prompt_id=prompt.id,
            goal="Revise with a clearer reason",
            observed_evidence="The initial response was incomplete.",
            gap="Needs a revised explanation",
        )
        session.commit()
        record_id = record.id

    response = client.post(
        f"/app/learner/feedback/{record_id}/revision",
        data={
            "response_text": "I revised the answer with a cited explanation.",
            "confidence_rating": "4",
        },
    )

    assert response.status_code == 200
    assert "Revision submitted. Status: submitted." in response.text
    assert "submitted" in response.text
    with session_factory() as session:
        revised = (
            session.query(Attempt)
            .filter_by(response_text="I revised the answer with a cited explanation.")
            .one()
        )
        assert revised.confidence_rating == 4


def _prompt() -> Prompt:
    return Prompt(
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="author-1",
    )


def _attempt(prompt_id: str) -> Attempt:
    return Attempt(
        learner_id="learner-1",
        prompt_id=prompt_id,
        response_text="Initial response",
        feedback={"goal": "Improve the response", "next_action": "Revise"},
    )
