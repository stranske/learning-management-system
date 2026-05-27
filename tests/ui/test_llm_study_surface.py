"""HTML contract tests for the learner LLM study surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.llm.models import LLMSession


def test_llm_study_surface_get_renders_start_form(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.get("/app/learner/llm-study")

    assert response.status_code == 200
    html = response.text
    assert 'action="/app/learner/llm-study/sessions"' in html
    assert 'name="user_message"' in html
    assert 'name="mode"' in html
    assert 'name="coaching_intensity"' in html


def test_llm_study_surface_shows_trace_class_cost_and_model(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.post(
        "/app/learner/llm-study/sessions",
        data={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Please explain retrieval practice.",
            "coaching_intensity": "full",
        },
    )

    assert response.status_code == 200
    html = response.text
    assert "Trace class" in html
    assert "formative" in html
    assert "fake-learning-policy" in html
    assert "micro-USD" in html
    assert "Policy decision" in html


def test_llm_study_surface_applies_forget_control(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_session(session, session_id="sess-forget", learner_id="learner-1")

    response = client.post(
        "/app/learner/llm-study/sessions/sess-forget/trace-control",
        data={"learner_id": "learner-1", "action": "forget"},
    )

    assert response.status_code == 200
    html = response.text
    assert "Trace forgotten." in html
    assert "Retained response summary" in html
    # The retained verbatim body must never be rendered back to the learner.
    assert "A retained formative summary." not in html

    with session_factory() as session:
        stored = session.get(LLMSession, "sess-forget")
        assert stored is not None
        assert stored.trace_control_state == "forgotten"
        assert stored.response_summary is None
        assert stored.external_export_allowed is False


def test_llm_study_surface_flags_uncited_claims_as_unverified(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.post(
        "/app/learner/llm-study/sessions",
        data={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Explain the main idea.",
            "coaching_intensity": "full",
            "source_constraints": "source-xyz",
        },
    )

    assert response.status_code == 200
    assert "unverified" in response.text


def test_llm_study_surface_documents_formative_and_ephemeral_trace_handling(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.get("/app/learner/llm-study")

    assert response.status_code == 200
    html = response.text
    assert "Trace handling" in html
    assert "formative" in html
    assert "ephemeral" in html
    assert "never exported" in html


def test_llm_study_surface_forget_unknown_session_shows_error(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.post(
        "/app/learner/llm-study/sessions/missing/trace-control",
        data={"learner_id": "learner-1", "action": "forget"},
    )

    assert response.status_code == 200
    assert "LLM session not found" in response.text


def test_llm_study_surface_keep_disabled_for_ephemeral_trace(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_session(
            session,
            session_id="sess-ephemeral",
            learner_id="learner-1",
            trace_class="ephemeral",
        )

    response = client.post(
        "/app/learner/llm-study/sessions/sess-ephemeral/trace-control",
        data={"learner_id": "learner-1", "action": "keep"},
    )

    assert response.status_code == 200
    assert "ephemeral traces cannot be marked for verbatim retention" in response.text


def _seed_session(
    session: Session,
    *,
    session_id: str,
    learner_id: str,
    trace_class: str = "formative",
) -> None:
    session.add(
        LLMSession(
            id=session_id,
            mode="study-coach",
            trace_class=trace_class,
            provider="fake",
            model="fake-learning-policy",
            learner_id=learner_id,
            coaching_intensity="full",
            input_tokens=5,
            output_tokens=9,
            cost_micro_usd=41,
            external_export_allowed=True,
            response_summary="A retained formative summary.",
            trace_control_state="default",
        )
    )
    session.commit()
