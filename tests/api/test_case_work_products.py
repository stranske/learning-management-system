"""Tests for transfer-case work product API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.cases.models import WorkProduct
from lms.cases.repository import create_case
from lms.db.session import get_session
from lms.evidence.repository import get_evidence_record
from lms.feedback.repository import create_rubric
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _seed_case(db_session: Session) -> tuple[str, str]:
    node = create_knowledge_node(
        db_session,
        title="Transfer node",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Transfer rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
        knowledge_node_id=node.id,
    )
    case = create_case(
        db_session,
        title="Client exception case",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=node.id,
        steps=[{"step_order": 1, "title": "Recommend", "prompt": "Recommend the next action."}],
    )
    db_session.commit()
    return case.id, rubric.id


def test_submit_case_work_product(db_session: Session) -> None:
    """The work product API submits, lists, and reads a learner case submission."""
    case_id, rubric_id = _seed_case(db_session)
    client = _client(db_session)

    response = client.post(
        f"/cases/{case_id}/work-products",
        json={
            "learner_id": "learner-1",
            "submission_type": "memo",
            "rubric_id": rubric_id,
            "body": "Recommend granting the exception with the controlling clause cited.",
        },
    )

    assert response.status_code == 201, response.text
    body = cast(dict[str, Any], response.json())
    assert body["case_id"] == case_id
    assert body["learner_id"] == "learner-1"
    assert body["submission_type"] == "memo"
    assert body["status"] == "submitted"
    assert body["rubric_score_id"] is None
    work_product_id = body["id"]

    list_response = client.get(
        f"/cases/{case_id}/work-products", params={"learner_id": "learner-1"}
    )
    assert list_response.status_code == 200, list_response.text
    listed = cast(list[dict[str, Any]], list_response.json())
    assert [item["id"] for item in listed] == [work_product_id]

    get_response = client.get(f"/work-products/{work_product_id}")
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["id"] == work_product_id


def test_submit_case_work_product_ignores_client_status(db_session: Session) -> None:
    """Submitting a work product keeps workflow status server-controlled."""
    case_id, rubric_id = _seed_case(db_session)
    client = _client(db_session)

    response = client.post(
        f"/cases/{case_id}/work-products",
        json={
            "learner_id": "learner-1",
            "submission_type": "memo",
            "rubric_id": rubric_id,
            "body": "Recommend granting the exception with the controlling clause cited.",
            "status": "accepted",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "submitted"


def test_submit_work_product_requires_body_or_artifact(db_session: Session) -> None:
    """A work product without a body or artifact reference is rejected."""
    case_id, _ = _seed_case(db_session)
    client = _client(db_session)

    response = client.post(
        f"/cases/{case_id}/work-products",
        json={"learner_id": "learner-1", "submission_type": "memo"},
    )
    assert response.status_code == 422, response.text


def test_submit_work_product_unknown_case_returns_404(db_session: Session) -> None:
    """Submitting against a missing case returns 404."""
    client = _client(db_session)
    response = client.post(
        "/cases/missing-case/work-products",
        json={
            "learner_id": "learner-1",
            "submission_type": "memo",
            "body": "Body for a case that does not exist.",
        },
    )
    assert response.status_code == 404, response.text


def test_score_case_work_product_records_transfer_evidence(db_session: Session) -> None:
    """The work-product score route records rubric score and transfer evidence."""
    case_id, rubric_id = _seed_case(db_session)
    client = _client(db_session)
    submit_response = client.post(
        f"/cases/{case_id}/work-products",
        json={
            "learner_id": "learner-1",
            "submission_type": "memo",
            "rubric_id": rubric_id,
            "body": "Recommend granting the exception with the controlling clause cited.",
        },
    )
    assert submit_response.status_code == 201, submit_response.text
    work_product_id = submit_response.json()["id"]

    response = client.post(
        f"/work-products/{work_product_id}/score",
        json={
            "scorer_type": "rubric-self",
            "criterion_scores": [{"criterion": "analysis", "points": 3, "max_points": 4}],
            "raw_score": 3.0,
            "max_score": 4.0,
            "transfer_distance": "near",
        },
    )

    assert response.status_code == 201, response.text
    body = cast(dict[str, Any], response.json())
    assert body["work_product_id"] == work_product_id
    assert body["status"] == "scored"
    assert body["rubric_score_id"]
    assert body["evidence_record_id"]
    assert body["normalized_score"] == 0.75
    evidence = get_evidence_record(db_session, body["evidence_record_id"])
    assert evidence is not None
    assert evidence.validity_scope == f"transfer-case:{case_id}"
    assert evidence.transfer_distance == "near"
    work_product = db_session.get(WorkProduct, work_product_id)
    assert work_product is not None
    assert work_product.rubric_score_id == body["rubric_score_id"]


def test_score_case_work_product_rejects_second_terminal_score(db_session: Session) -> None:
    """A scored work product cannot be scored again without a revision loop."""
    case_id, rubric_id = _seed_case(db_session)
    client = _client(db_session)
    work_product_id = client.post(
        f"/cases/{case_id}/work-products",
        json={
            "learner_id": "learner-1",
            "submission_type": "memo",
            "rubric_id": rubric_id,
            "body": "Recommend granting the exception.",
        },
    ).json()["id"]
    payload = {
        "scorer_type": "rubric-self",
        "criterion_scores": [],
        "raw_score": 3.0,
        "max_score": 4.0,
    }

    first = client.post(f"/work-products/{work_product_id}/score", json=payload)
    second = client.post(f"/work-products/{work_product_id}/score", json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 422, second.text
    assert "not in a scoreable state" in second.text
