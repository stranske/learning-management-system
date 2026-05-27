"""Tests for the request-to-revised-submission revision loop."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt, get_attempt, list_evidence_records
from lms.feedback.models import FeedbackRecord, RevisionRequest
from lms.feedback.repository import (
    create_feedback_action,
    create_revision_request,
    list_feedback_records,
    list_revision_requests,
    resolve_revision_request,
    submit_revision_request,
)
from lms.graphs.models import KnowledgeNode
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _seed_feedback(db_session: Session) -> tuple[str, FeedbackRecord]:
    """Create an original attempt and return its id and promoted feedback record."""
    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id="prompt-1",
        response_text="First attempt isolated x but skipped the check.",
        feedback={
            "goal": "Solve the equation and verify the solution.",
            "observed_evidence": "Isolated x correctly.",
            "gap": "Did not substitute the solution back in.",
            "next_action": "Retry with a required substitution check.",
        },
    )
    db_session.commit()
    records = list_feedback_records(db_session, attempt_id=attempt.id)
    assert records
    return attempt.id, records[0]


def test_revision_request_creates_revised_attempt_and_feedback_link(db_session: Session) -> None:
    """Submitting a revision records a standard attempt linked back to the feedback."""
    original_attempt_id, feedback_record = _seed_feedback(db_session)

    request = create_revision_request(
        db_session,
        learner_id="learner-1",
        feedback_record_id=feedback_record.id,
    )
    db_session.commit()

    assert request.status == "open"
    assert request.feedback_record_id == feedback_record.id
    assert request.prompt_id == "prompt-1"
    assert request.original_attempt_id == original_attempt_id

    submit_revision_request(
        db_session,
        request,
        response_text="Revised: substituted the solution back and confirmed it checks out.",
        confidence_rating=4,
    )
    db_session.commit()

    assert request.status == "submitted"
    assert request.submitted_at is not None
    assert request.revised_attempt_id is not None
    assert request.revised_attempt_id != original_attempt_id

    revised_attempt = get_attempt(db_session, request.revised_attempt_id)
    assert revised_attempt is not None
    assert revised_attempt.learner_id == "learner-1"
    assert revised_attempt.prompt_id == "prompt-1"

    # The revised attempt promotes a standard feedback record mastery/scheduler code can read.
    revised_feedback = list_feedback_records(db_session, attempt_id=request.revised_attempt_id)
    assert len(revised_feedback) == 1


def test_revision_request_status_transitions_are_validated(db_session: Session) -> None:
    """A revision request may only follow valid open->submitted->resolved transitions."""
    _, feedback_record = _seed_feedback(db_session)
    request = create_revision_request(
        db_session,
        learner_id="learner-1",
        feedback_record_id=feedback_record.id,
    )
    db_session.commit()

    # Cannot accept before a revised response is submitted.
    with pytest.raises(ValueError, match="cannot transition revision request from 'open'"):
        resolve_revision_request(db_session, request, outcome="accepted")
    assert request.status == "open"

    submit_revision_request(db_session, request, response_text="Revised answer with the check.")
    db_session.commit()
    assert request.status == "submitted"

    # Cannot submit twice.
    with pytest.raises(ValueError, match="cannot transition revision request from 'submitted'"):
        submit_revision_request(db_session, request, response_text="Another revision.")

    resolve_revision_request(db_session, request, outcome="accepted", result_note="Correct now.")
    db_session.commit()
    assert request.status == "accepted"
    assert request.resolved_at is not None
    assert request.scheduler_hook is not None
    assert request.scheduler_hook["reason_code"] == "due-review"
    assert request.scheduler_hook["trigger"] == "revision-accepted"

    # Accepted is terminal.
    with pytest.raises(ValueError, match="cannot transition revision request from 'accepted'"):
        resolve_revision_request(db_session, request, outcome="closed")


def test_revision_request_rejects_learner_mismatch(db_session: Session) -> None:
    """A revision request cannot be opened for a learner other than the feedback learner."""
    _, feedback_record = _seed_feedback(db_session)
    with pytest.raises(ValueError, match="learner must match the feedback record learner"):
        create_revision_request(
            db_session,
            learner_id="learner-2",
            feedback_record_id=feedback_record.id,
        )


def test_revision_request_requires_context_linkage(db_session: Session) -> None:
    """A learner-only revision request is rejected before it can become an orphan."""
    with pytest.raises(ValueError, match="must link to feedback"):
        create_revision_request(db_session, learner_id="learner-1")

    client = _client(db_session)
    resp = client.post("/revision-requests", json={"learner_id": "learner-1"})
    assert resp.status_code == 422, resp.text


def test_revision_request_rejects_inconsistent_action_record_link(
    db_session: Session,
) -> None:
    """The linked revision action must belong to the linked feedback record."""
    original_attempt_id, feedback_record = _seed_feedback(db_session)
    _, other_record = _seed_feedback(db_session)
    action = create_feedback_action(
        db_session,
        feedback_record_id=feedback_record.id,
        learner_id="learner-1",
        attempt_id=original_attempt_id,
        prompt_id="prompt-1",
        action_type="revision",
        title="Revise your answer with the substitution check.",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="must belong to the linked feedback record"):
        create_revision_request(
            db_session,
            learner_id="learner-1",
            feedback_record_id=other_record.id,
            feedback_action_id=action.id,
        )


def test_closing_a_failed_revision_stages_remediation_hook(db_session: Session) -> None:
    """Closing an unaccepted revision stages remediation rather than review scheduling."""
    _, feedback_record = _seed_feedback(db_session)
    request = create_revision_request(
        db_session, learner_id="learner-1", feedback_record_id=feedback_record.id
    )
    submit_revision_request(db_session, request, response_text="Second try still misses the check.")
    resolve_revision_request(db_session, request, outcome="closed", result_note="Still incorrect.")
    db_session.commit()

    assert request.status == "closed"
    assert request.scheduler_hook is not None
    assert request.scheduler_hook["reason_code"] == "remediation"
    assert request.scheduler_hook["trigger"] == "revision-failed"


def test_new_request_supersedes_prior_active_request(db_session: Session) -> None:
    """Opening a fresh request for the same feedback supersedes the prior active one."""
    _, feedback_record = _seed_feedback(db_session)
    first = create_revision_request(
        db_session, learner_id="learner-1", feedback_record_id=feedback_record.id
    )
    db_session.commit()
    second = create_revision_request(
        db_session, learner_id="learner-1", feedback_record_id=feedback_record.id
    )
    db_session.commit()
    db_session.refresh(first)

    assert first.status == "superseded"
    assert second.status == "open"


def test_new_request_supersedes_all_prior_active_requests(db_session: Session) -> None:
    """Superseding active requests is not capped by the public list default limit."""
    _, feedback_record = _seed_feedback(db_session)
    for _ in range(101):
        db_session.add(
            RevisionRequest(
                learner_id="learner-1",
                feedback_record_id=feedback_record.id,
                prompt_id="prompt-1",
                status="open",
            )
        )
    db_session.commit()

    current = create_revision_request(
        db_session, learner_id="learner-1", feedback_record_id=feedback_record.id
    )
    db_session.commit()

    active = list_revision_requests(
        db_session,
        feedback_record_id=feedback_record.id,
        statuses=("open", "submitted"),
        limit=None,
    )
    assert active == [current]


def test_revision_requests_visible_from_feedback_detail_route(db_session: Session) -> None:
    """Revision loop state is visible from the adjacent feedback detail route via the API."""
    original_attempt_id, feedback_record = _seed_feedback(db_session)
    action = create_feedback_action(
        db_session,
        feedback_record_id=feedback_record.id,
        learner_id="learner-1",
        attempt_id=original_attempt_id,
        prompt_id="prompt-1",
        action_type="revision",
        title="Revise your answer with the substitution check.",
    )
    db_session.commit()

    client = _client(db_session)

    create_resp = client.post(
        "/revision-requests",
        json={
            "learner_id": "learner-1",
            "feedback_record_id": feedback_record.id,
            "feedback_action_id": action.id,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    request_id = create_resp.json()["id"]

    # Opening a request moves the linked revision action into progress.
    db_session.refresh(action)
    assert action.status == "in-progress"

    submit_resp = client.post(
        f"/revision-requests/{request_id}/submit",
        json={"response_text": "Revised answer that substitutes the solution back."},
    )
    assert submit_resp.status_code == 200, submit_resp.text
    assert submit_resp.json()["status"] == "submitted"

    resolve_resp = client.post(
        f"/revision-requests/{request_id}/resolve",
        json={"outcome": "accepted", "result_note": "Correct now."},
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    assert resolve_resp.json()["status"] == "accepted"

    detail_resp = client.get(f"/feedback/{feedback_record.id}/revision-requests")
    assert detail_resp.status_code == 200, detail_resp.text
    body = detail_resp.json()
    assert len(body) == 1
    assert body[0]["id"] == request_id
    assert body[0]["status"] == "accepted"

    # Accepting the request completes the linked revision action.
    db_session.refresh(action)
    assert action.status == "completed"


def test_revision_request_submit_accepts_evidence_payload(db_session: Session) -> None:
    """The submit API can create scored evidence for the revised attempt."""
    _, feedback_record = _seed_feedback(db_session)
    node = KnowledgeNode(
        title="Linear equations",
        knowledge_type="procedural",
        ownership_scope="personal",
        status="published",
    )
    db_session.add(node)
    request = create_revision_request(
        db_session,
        learner_id="learner-1",
        feedback_record_id=feedback_record.id,
    )
    db_session.commit()

    client = _client(db_session)
    submit_resp = client.post(
        f"/revision-requests/{request.id}/submit",
        json={
            "response_text": "Revised answer that includes the substitution check.",
            "confidence_rating": 5,
            "evidence": {
                "knowledge_node_id": node.id,
                "correctness": True,
                "normalized_score": 1.0,
            },
        },
    )
    assert submit_resp.status_code == 200, submit_resp.text
    revised_attempt_id = submit_resp.json()["revised_attempt_id"]
    assert revised_attempt_id is not None

    evidence_records = list_evidence_records(
        db_session, learner_id="learner-1", knowledge_node_id=node.id
    )
    assert len(evidence_records) == 1
    assert evidence_records[0].attempt_id == revised_attempt_id
    assert evidence_records[0].correctness is True


def test_revision_request_create_rejects_missing_feedback_record(db_session: Session) -> None:
    """The create route returns 404 when the referenced feedback record is absent."""
    client = _client(db_session)
    resp = client.post(
        "/revision-requests",
        json={"learner_id": "learner-1", "feedback_record_id": "missing-record"},
    )
    assert resp.status_code == 404, resp.text
