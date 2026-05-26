"""Tests for rubric scoring API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _rubric_score_fixture(db_session: Session, client: TestClient) -> tuple[str, str, list[str]]:
    node = create_knowledge_node(
        db_session,
        title="Evidence-based explanation",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    attempt = create_attempt(
        db_session,
        learner_id="learner-api",
        prompt_id="prompt-api",
        response_text="My answer includes a claim but limited evidence.",
        feedback={
            "goal": "Explain with evidence",
            "observed_evidence": "Attempt submitted.",
            "next_action": "Add a citation.",
        },
    )
    db_session.commit()

    response = client.post(
        "/rubrics",
        json={
            "title": "Explanation rubric",
            "ownership_scope": "personal",
            "knowledge_node_id": node.id,
            "authoring_actor": "user:alice",
            "criteria": [
                {
                    "criterion_order": 1,
                    "description": "States a claim.",
                    "max_points": 2,
                },
                {
                    "criterion_order": 2,
                    "description": "Uses evidence.",
                    "max_points": 3,
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    rubric = cast(dict[str, Any], response.json())
    return rubric["id"], attempt.id, [criterion["id"] for criterion in rubric["criteria"]]


def test_post_rubric_score_returns_criterion_breakdown(db_session: Session) -> None:
    """POST /rubric-scores returns normalized criterion-level scoring data."""
    client = _client(db_session)
    rubric_id, attempt_id, criterion_ids = _rubric_score_fixture(db_session, client)

    response = client.post(
        "/rubric-scores",
        json={
            "rubric_id": rubric_id,
            "attempt_id": attempt_id,
            "scorer_type": "human",
            "scorer_id": "teacher-1",
            "criterion_scores": [
                {"criterion_id": criterion_ids[0], "points": 2, "rationale": "Clear claim."},
                {"criterion_id": criterion_ids[1], "points": 1, "rationale": "Thin evidence."},
            ],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["rubric_id"] == rubric_id
    assert body["attempt_id"] == attempt_id
    assert body["raw_score"] == 3
    assert body["max_score"] == 5
    assert body["normalized_score"] == 0.6
    assert body["criterion_scores"][0]["criterion_order"] == 1
    assert body["criterion_scores"][1]["description"] == "Uses evidence."
    assert body["evidence_record_id"]
    assert body["feedback_record_id"]

    list_response = client.get("/rubric-scores", params={"attempt_id": attempt_id})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [body["id"]]


def test_post_rubric_score_rejects_invalid_criterion_id(db_session: Session) -> None:
    """POST /rubric-scores rejects criterion ids outside the selected rubric."""
    client = _client(db_session)
    rubric_id, attempt_id, _criterion_ids = _rubric_score_fixture(db_session, client)

    response = client.post(
        "/rubric-scores",
        json={
            "rubric_id": rubric_id,
            "attempt_id": attempt_id,
            "scorer_type": "human",
            "criterion_scores": [{"criterion_id": "missing-criterion", "points": 1}],
        },
    )

    assert response.status_code == 422
    assert "unknown or inactive rubric criterion id" in response.json()["detail"]
