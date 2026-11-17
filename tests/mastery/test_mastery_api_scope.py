"""Mixed-scope regression tests for learner mastery and calibration routes."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.analytics.calibration import calibration_all_scopes, calibration_for_learner
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.models import KnowledgeNode
from lms.main import create_app
from lms.mastery.service import (
    mastery_estimates_all_scopes,
    mastery_estimates_for_learner,
    mastery_estimates_with_evidence_all_scopes,
    mastery_estimates_with_evidence_for_learner,
)


@pytest.fixture
def mixed_scope_session(db_session: Session) -> Session:
    for scope in ("personal", "institutional"):
        db_session.add(
            KnowledgeNode(
                id=f"{scope}-node",
                title=f"{scope} topic",
                knowledge_type="factual",
                ownership_scope=scope,
            )
        )
        db_session.flush()
        create_evidence_record(
            db_session,
            learner_id="mixed",
            knowledge_node_id=f"{scope}-node",
            confidence_rating=5,
            correctness=scope == "personal",
        )
    db_session.commit()
    return db_session


@pytest.fixture
def mixed_scope_client(mixed_scope_session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: mixed_scope_session
    with TestClient(app) as client:
        yield client


def test_rest_mastery_defaults_to_personal_scope(mixed_scope_client: TestClient) -> None:
    response = mixed_scope_client.get("/learners/mixed/mastery-estimates")

    assert response.status_code == 200
    assert [row["knowledge_node_id"] for row in response.json()] == ["personal-node"]


def test_rest_mastery_respects_institutional_scope(mixed_scope_client: TestClient) -> None:
    response = mixed_scope_client.get(
        "/learners/mixed/mastery-estimates", params={"ownership_scope": "institutional"}
    )

    assert response.status_code == 200
    assert [row["knowledge_node_id"] for row in response.json()] == ["institutional-node"]


@pytest.mark.parametrize(
    "path",
    ["/learners/mixed/mastery-estimates", "/app/learner", "/app/learner/calibration"],
)
def test_learner_routes_reject_invalid_scope(mixed_scope_client: TestClient, path: str) -> None:
    response = mixed_scope_client.get(path, params={"learner_id": "mixed", "ownership_scope": "all"})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "scope_params, expected, excluded, accuracy",
    [
        ({}, "personal", "institutional", "100%"),
        ({"ownership_scope": "institutional"}, "institutional", "personal", "0%"),
    ],
)
def test_learner_html_scopes_mastery_and_calibration(
    mixed_scope_client: TestClient,
    scope_params: dict[str, str],
    expected: str,
    excluded: str,
    accuracy: str,
) -> None:
    params = {"learner_id": "mixed", **scope_params}
    dashboard = mixed_scope_client.get("/app/learner", params=params)
    assert dashboard.status_code == 200
    mastery_panel = dashboard.text.split('id="mastery"', 1)[1].split("</section>", 1)[0]
    assert f"{expected} topic" in mastery_panel
    assert f"{excluded} topic" not in mastery_panel

    calibration = mixed_scope_client.get("/app/learner/calibration", params=params)
    assert calibration.status_code == 200
    assert "Scored records: 1." in calibration.text
    assert f'<th scope="row">5/5</th><td>1</td><td>{accuracy}</td>' in calibration.text

    if scope_params:
        query = "learner_id=mixed&amp;ownership_scope=institutional"
        assert f'href="/app/learner/calibration?{query}"' in dashboard.text
        assert f'href="/app/learner?{query}"' in calibration.text


def test_all_scope_aggregations_tag_estimates_and_calibration(mixed_scope_session: Session) -> None:
    estimates, evidence = mastery_estimates_with_evidence_all_scopes(mixed_scope_session, "mixed")
    expected = {"personal-node": "personal", "institutional-node": "institutional"}
    for rows in (estimates, mastery_estimates_all_scopes(mixed_scope_session, "mixed")):
        assert {row["knowledge_node_id"]: row["ownership_scope"] for row in rows} == expected
    assert {node_id: len(records) for node_id, records in evidence.items()} == {
        node_id: 1 for node_id in expected
    }

    calibration = calibration_all_scopes(mixed_scope_session, "mixed")
    assert {
        row["ownership_scope"]: (row["sample_size"], row["buckets"][0]["observed_accuracy"])
        for row in calibration
    } == {"personal": (1, 1.0), "institutional": (1, 0.0)}


@pytest.mark.parametrize(
    "aggregate",
    [
        mastery_estimates_for_learner,
        mastery_estimates_with_evidence_for_learner,
        calibration_for_learner,
    ],
)
def test_scoped_aggregations_reject_unknown_scope(
    db_session: Session, aggregate: Callable[..., object]
) -> None:
    with pytest.raises(ValueError, match="unknown ownership scope"):
        aggregate(db_session, "mixed", scope="all")
