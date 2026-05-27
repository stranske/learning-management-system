"""Authoring surface tests for rubrics, feedback templates, and cases."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def test_author_can_create_rubric_template_and_case(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    rubric_response = client.post(
        "/app/author/rubrics",
        data={
            "title": "Evidence rubric",
            "description": "Scores evidence quality.",
            "ownership_scope": "personal",
            "status": "draft",
            "authoring_actor": "author-1",
            "criterion_order": "1",
            "criterion_description": "Cites the most relevant source.",
            "max_points": "4",
            "validity_scope": "case",
            "performance_levels": '{"meets": "Cites a durable source"}',
        },
    )

    assert rubric_response.status_code == 200
    assert "Rubric created." in rubric_response.text
    assert "Evidence rubric" in rubric_response.text
    assert "personal scope; draft; 1 criteria" in rubric_response.text

    template_response = client.post(
        "/app/author/feedback-templates",
        data={
            "name": "Citation coaching",
            "template_body": "Use {source} before revising {next_action}.",
            "required_placeholders": "source,next_action",
            "feedback_level": "coaching",
            "action_type": "revision",
            "ownership_scope": "personal",
            "status": "draft",
            "authoring_actor": "author-1",
        },
    )

    assert template_response.status_code == 200
    assert "Feedback template created." in template_response.text
    assert "Citation coaching" in template_response.text
    assert "next_action, source" in template_response.text

    case_response = client.post(
        "/app/author/cases",
        data={
            "title": "Transfer case",
            "description": "Practice evidence transfer.",
            "ownership_scope": "personal",
            "status": "draft",
            "step_order": "1",
            "step_title": "Review evidence",
            "step_prompt": "Choose the strongest citation.",
            "expected_work_product": "rationale",
            "evidence_title": "Source packet",
            "evidence_summary": "Two candidate citations.",
            "packet_metadata": '{"source": "fixture"}',
            "decision_title": "Citation decision",
            "decision_prompt": "Which source should support the answer?",
            "decision_type": "single-choice",
            "decision_options": '[{"label": "Primary source", "value": "primary"}]',
        },
    )

    assert case_response.status_code == 200
    assert "Case created." in case_response.text
    assert "Transfer case" in case_response.text
    assert "personal scope; draft; 1 steps; 1 evidence packets" in case_response.text
    assert "simulation" not in case_response.text.lower()


def test_template_preview_renders_placeholder_values(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client
    client.post(
        "/app/author/feedback-templates",
        data={
            "name": "Gap coaching",
            "template_body": "Address {gap} by {next_action}.",
            "required_placeholders": "gap,next_action",
            "feedback_level": "coaching",
            "action_type": "retry",
            "ownership_scope": "personal",
            "status": "published",
            "authoring_actor": "author-1",
        },
    )
    page = client.get("/app/author/feedback-templates")
    template_id = (
        page.text.split("Template preview</label>", maxsplit=1)[1]
        .split('<option value="', maxsplit=1)[1]
        .split('"', maxsplit=1)[0]
    )

    preview_response = client.post(
        "/app/author/feedback-templates/preview",
        data={
            "template_id": template_id,
            "values_json": '{"gap": "missing citation", "next_action": "revise paragraph"}',
        },
    )

    assert preview_response.status_code == 200
    assert "Preview rendered." in preview_response.text
    assert "Address missing citation by revise paragraph." in preview_response.text


def test_author_pages_include_mobile_shell_markup(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    for route, heading in [
        ("/app/author/rubrics", "Rubrics"),
        ("/app/author/feedback-templates", "Feedback templates"),
        ("/app/author/cases", "Cases"),
    ]:
        response = client.get(route)

        assert response.status_code == 200
        assert 'name="viewport"' in response.text
        assert f"<h1>{heading}</h1>" in response.text
        assert 'href="/static/ui/app.css"' in response.text
