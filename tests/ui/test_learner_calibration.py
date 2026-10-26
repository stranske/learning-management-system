"""Learner calibration uses scored evidence and the authenticated identity seam."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import User
from lms.auth.passwords import hash_password
from lms.evidence.repository import create_evidence_record
from lms.learners.models import Learner
from lms.settings import Settings, get_settings


def test_learner_calibration_page_shows_bucket_accuracy(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api_client
    with factory() as session:
        for index in range(5):
            create_evidence_record(
                session,
                learner_id="learner-over",
                knowledge_node_id="node-1",
                confidence_rating=5,
                correctness=index == 0,
                response_time_seconds=30,
            )
        create_evidence_record(
            session,
            learner_id="another-learner",
            knowledge_node_id="node-1",
            confidence_rating=2,
            correctness=True,
        )
        session.commit()
    response = client.get("/app/learner/calibration?learner_id=learner-over")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<th scope="row">5/5</th><td>5</td><td>20%</td>' in response.text
    assert "30 seconds</td><td>Yes</td>" in response.text
    assert "Scored records: 5. Overconfidence flagged: Yes." in response.text
    assert '<th scope="row">2/5</th>' not in response.text
    dashboard = client.get("/app/learner?learner_id=learner-over")
    assert 'href="/app/learner/calibration?learner_id=learner-over"' in dashboard.text


def test_learner_calibration_empty_state(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client
    response = client.get("/app/learner/calibration?learner_id=empty")
    assert response.status_code == 200
    assert "No calibration evidence yet" in response.text
    assert "Scored records: 0" in response.text
    assert "<table>" not in response.text


def test_learner_calibration_requires_session_and_ownership(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api_client
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    with factory() as session:
        owner = User(
            username="owner",
            display_name="Owner",
            is_local=False,
            password_hash=hash_password("calibration-password"),
        )
        other = User(username="other", display_name="Other", is_local=False)
        session.add_all([owner, other])
        session.flush()
        own = Learner(user_id=owner.id, display_name="Owner")
        foreign = Learner(user_id=other.id, display_name="Other")
        session.add_all([own, foreign])
        session.commit()
        own_id, foreign_id = own.id, foreign.id
    path = "/app/learner/calibration"
    assert client.get(path).status_code == 401
    browser = client.get(path, headers={"Accept": "text/html"}, follow_redirects=False)
    assert browser.status_code == 302
    assert browser.headers["location"].startswith("/login?")
    login = client.post(
        "/login",
        data={"username": "owner", "password": "calibration-password"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get(path).status_code == 200
    assert client.get(path, params={"learner_id": own_id}).status_code == 200
    assert client.get(path, params={"learner_id": foreign_id}).status_code == 403
    assert client.get(path, params={"learner_id": "missing"}).status_code == 403
