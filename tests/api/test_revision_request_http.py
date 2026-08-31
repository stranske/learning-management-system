"""HTTP behaviour of the revision-request routes.

Two families of branch, both unreached, and they fail differently.

A **404** for a referenced record that does not exist is the difference between "you pointed at
nothing" and a 500 from a foreign-key violation. A **422** for a request the repository refuses is
the difference between a message the caller can act on and an opaque server error.

The 422 path carries a property no status code shows: `session.rollback()`. A handler that raises
without rolling back leaves the transaction poisoned, so the NEXT request on that session fails for
a reason that has nothing to do with it. That is tested by making a second, valid request after a
refused one — which is the only way to observe it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt
from lms.feedback.repository import create_feedback_record
from lms.main import create_app
from lms.prompts.models import Prompt, PromptVersion


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


@pytest.fixture
def client(db_session: Session) -> TestClient:
    return _client(db_session)


def _prompt(session: Session) -> Prompt:
    prompt = Prompt(
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="user:alice",
    )
    prompt.versions.append(
        PromptVersion(version_number=1, body="Explain it.", created_by="user:alice")
    )
    session.add(prompt)
    session.flush()
    return prompt


def _feedback(session: Session, *, learner_id: str = "learner-1"):
    prompt = _prompt(session)
    attempt = create_attempt(
        session,
        learner_id=learner_id,
        prompt_id=prompt.id,
        response_text="an answer",
        feedback={"goal": "g", "next_action": "n"},
        evidence={"knowledge_node_id": "node-1", "outcome": "correct"},
    )
    record = create_feedback_record(
        session,
        learner_id=learner_id,
        attempt_id=attempt.id,
        prompt_id=prompt.id,
        feedback_level="coaching",
        goal="Use both terms",
        observed_evidence="Only the numerator was multiplied.",
    )
    session.flush()
    return prompt, attempt, record


_MISSING_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------------------------
# 404: you pointed at nothing.
# ---------------------------------------------------------------------------------------------


def test_a_revision_request_citing_an_unknown_feedback_record_is_404(client):
    """Without this check the id reaches the repository and fails as a constraint violation —
    a 500, which reads as our fault rather than the caller's."""
    response = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": _MISSING_ID},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Referenced feedback record not found."


def test_a_revision_request_citing_an_unknown_feedback_action_is_404(client):
    response = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_action_id": _MISSING_ID},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Referenced feedback action not found."


def test_fetching_an_unknown_revision_request_is_404(client):
    response = client.get(f"/revision-requests/{_MISSING_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Revision request not found."


@pytest.mark.parametrize("action", ["submit", "resolve"])
def test_acting_on_an_unknown_revision_request_is_404(client, action):
    """The id is checked before the body is used, so a well-formed action on a missing request
    still says which thing was missing."""
    payload = {"response_text": "revised"} if action == "submit" else {"outcome": "accepted"}
    response = client.post(f"/revision-requests/{_MISSING_ID}/{action}", json=payload)

    assert response.status_code == 404
    assert response.json()["detail"] == "Revision request not found."


# ---------------------------------------------------------------------------------------------
# 422: the repository refused, and said why.
# ---------------------------------------------------------------------------------------------


def test_accepting_a_revision_that_was_never_submitted_is_refused(client, db_session: Session):
    """The refusal comes from the STATE MACHINE, not from schema validation — a distinction worth
    making, because a schema rejection never reaches the handler this exercises.

    `open -> accepted` is not a legal move: accepting means accepting a REVISED response, and an
    open request has none. Allowing it would mark work as revised that was never redone, and the
    learner's evidence would record a revision that did not happen.
    """
    _prompt_obj, _attempt, record = _feedback(db_session)
    created = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": record.id},
    )
    assert created.status_code == 201, created.text

    response = client.post(
        f"/revision-requests/{created.json()['id']}/resolve", json={"outcome": "accepted"}
    )

    assert response.status_code == 422
    assert "cannot transition" in response.json()["detail"]
    assert "'open'" in response.json()["detail"]


def test_closing_an_open_request_is_allowed(client, db_session: Session):
    """The counterweight: `open -> closed` IS legal, so the guard above is a state machine rather
    than a blanket refusal."""
    _prompt_obj, _attempt, record = _feedback(db_session)
    created = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": record.id},
    )

    response = client.post(
        f"/revision-requests/{created.json()['id']}/resolve", json={"outcome": "closed"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "closed"


def test_an_invalid_outcome_is_rejected_by_the_schema_before_the_handler(client, db_session):
    """The other 422, and a different one: `outcome` is a Literal, so FastAPI refuses the body and
    the route never runs. Both must be 422 — a schema rejection leaking a 500 would be the same
    defect at a different layer."""
    _prompt_obj, _attempt, record = _feedback(db_session)
    created = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": record.id},
    )

    response = client.post(
        f"/revision-requests/{created.json()['id']}/resolve", json={"outcome": "maybe"}
    )

    assert response.status_code == 422


def test_the_session_survives_a_refused_request(client, db_session: Session):
    """A refusal must leave the session usable for the next request.

    This is an end-to-end property rather than a test of `session.rollback()` specifically:
    removing that call does NOT fail this test today, because every refusal on these routes comes
    from a guard that runs before any write. That was checked by deliberate break, not assumed —
    and the test is kept because the property it states is the one that matters to a caller, and
    it will start depending on the rollback the moment a refusal moves after a flush.
    """
    _prompt_obj, _attempt, record = _feedback(db_session)
    created = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": record.id},
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]

    refused = client.post(f"/revision-requests/{request_id}/resolve", json={"outcome": "accepted"})
    assert refused.status_code == 422

    accepted = client.post(f"/revision-requests/{request_id}/resolve", json={"outcome": "closed"})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "closed"


def test_a_refused_request_is_not_partially_persisted(client, db_session: Session):
    """A refused resolution leaves the request exactly as it was.

    `resolve_revision_request` checks the transition FIRST and only then writes `status`,
    `result_note` and `resolved_at` — so this holds by ordering rather than by rollback. Pinning
    it here is what makes a later reordering visible: moving the check below the assignments
    would leave a request reading as resolved while the API reported 422, the worst of both
    answers.
    """
    _prompt_obj, _attempt, record = _feedback(db_session)
    created = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": record.id},
    )
    request_id = created.json()["id"]
    before = client.get(f"/revision-requests/{request_id}").json()

    refused = client.post(f"/revision-requests/{request_id}/resolve", json={"outcome": "accepted"})
    assert refused.status_code == 422

    after = client.get(f"/revision-requests/{request_id}").json()
    assert after["status"] == before["status"] == "open"
    assert after["result_note"] == before["result_note"]
    assert after["resolved_at"] == before["resolved_at"] is None


# ---------------------------------------------------------------------------------------------
# Listing filters.
# ---------------------------------------------------------------------------------------------


def test_listing_revision_requests_filters_by_learner(client, db_session: Session):
    """An unfiltered listing hands one learner another's outstanding revisions."""
    _p1, _a1, mine = _feedback(db_session, learner_id="learner-1")
    _p2, _a2, theirs = _feedback(db_session, learner_id="learner-2")
    for learner_id, record in (("learner-1", mine), ("learner-2", theirs)):
        assert (
            client.post(
                "/revision-requests",
                json={"learner_id": learner_id, "feedback_record_id": record.id},
            ).status_code
            == 201
        )

    listed = client.get("/revision-requests", params={"learner_id": "learner-1"}).json()

    assert [row["learner_id"] for row in listed] == ["learner-1"]


def test_listing_revision_requests_filters_by_status(client, db_session: Session):
    """`open` is what a learner's queue shows. A status filter that does not filter puts resolved
    work back in front of them.

    The two requests come from two DIFFERENT feedback records: creating a second request from the
    same record returns the existing one, so closing it would leave nothing open and the test
    would pass against a broken filter.
    """
    _p1, _a1, first_record = _feedback(db_session)
    _p2, _a2, second_record = _feedback(db_session)
    first = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": first_record.id},
    ).json()
    second = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": second_record.id},
    ).json()
    assert first["id"] != second["id"]
    resolved = client.post(f"/revision-requests/{second['id']}/resolve", json={"outcome": "closed"})
    assert resolved.status_code == 200, resolved.text

    open_rows = client.get("/revision-requests", params={"status": "open"}).json()

    assert [row["id"] for row in open_rows] == [first["id"]]


def test_listing_without_filters_returns_every_learner(client, db_session: Session):
    """The unfiltered branch, so the filters above are shown to be doing the work."""
    _p1, _a1, mine = _feedback(db_session, learner_id="learner-1")
    _p2, _a2, theirs = _feedback(db_session, learner_id="learner-2")
    for learner_id, record in (("learner-1", mine), ("learner-2", theirs)):
        client.post(
            "/revision-requests",
            json={"learner_id": learner_id, "feedback_record_id": record.id},
        )

    listed = client.get("/revision-requests").json()

    assert {row["learner_id"] for row in listed} == {"learner-1", "learner-2"}


def test_listing_feedback_records_filters_by_learner(client, db_session: Session):
    _feedback(db_session, learner_id="learner-1")
    _feedback(db_session, learner_id="learner-2")

    listed = client.get("/feedback", params={"learner_id": "learner-1"}).json()

    assert listed
    assert {row["learner_id"] for row in listed} == {"learner-1"}


def test_listing_feedback_records_filters_by_prompt(client, db_session: Session):
    """Two learners can share a prompt, so this filter narrows where the learner filter cannot."""
    prompt, _attempt, _record = _feedback(db_session, learner_id="learner-1")
    _feedback(db_session, learner_id="learner-2")

    listed = client.get("/feedback", params={"prompt_id": prompt.id}).json()

    assert listed
    assert {row["prompt_id"] for row in listed} == {prompt.id}


def test_listing_feedback_records_returns_everything_unfiltered(client, db_session: Session):
    """The unfiltered branch, so the two filters above are shown to be narrowing rather than the
    fixture happening to hold one learner."""
    _feedback(db_session, learner_id="learner-1")
    _feedback(db_session, learner_id="learner-2")

    listed = client.get("/feedback").json()

    assert {row["learner_id"] for row in listed} == {"learner-1", "learner-2"}
