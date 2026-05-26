"""Tests for learner keep/forget trace controls."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.evidence.repository import create_attempt
from lms.llm.models import LLMSession
from lms.llm.trace_controls import apply_trace_control

from .test_study_coach_policy import _client


def _session_row() -> LLMSession:
    return LLMSession(
        mode="study-coach",
        trace_class="formative",
        provider="fake",
        model="fake-learning-policy",
        learner_id="learner-1",
        coaching_intensity="full",
        input_tokens=10,
        output_tokens=20,
        cost_micro_usd=130,
        response_summary="verbatim local coaching transcript",
        external_export_allowed=True,
    )


def test_forget_deletes_verbatim_transcript_but_preserves_evidence(
    db_session: Session,
) -> None:
    llm_session = _session_row()
    db_session.add(llm_session)
    db_session.flush()
    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id="prompt-1",
        llm_session_id=llm_session.id,
        response_text="attempt answer",
        confidence_rating=4,
        feedback={"next_action": "review the source"},
        evidence={
            "knowledge_node_id": "node-1",
            "correctness": True,
            "normalized_score": 1.0,
        },
    )

    apply_trace_control(
        db_session,
        llm_session,
        action="forget",
        actor_id="learner-1",
    )
    db_session.commit()
    db_session.expire_all()

    stored_session = db_session.get(LLMSession, llm_session.id)
    assert stored_session is not None
    assert stored_session.response_summary is None
    assert stored_session.trace_control_state == "forgotten"
    assert stored_session.external_export_allowed is False
    assert stored_session.transcript_deleted_at is not None

    stored_attempt = db_session.get(type(attempt), attempt.id)
    assert stored_attempt is not None
    assert stored_attempt.llm_session_id == llm_session.id
    assert len(stored_attempt.evidence_records) == 1

    audit = db_session.query(AuditLog).filter_by(entity_id=llm_session.id).one()
    assert audit.action == "llm_trace_forget"
    assert audit.after_summary is not None
    assert audit.after_summary["response_summary_retained"] is False


def test_keep_marks_formative_trace_for_retention(db_session: Session) -> None:
    llm_session = _session_row()
    db_session.add(llm_session)
    db_session.flush()

    apply_trace_control(
        db_session,
        llm_session,
        action="keep",
        actor_id="learner-1",
    )

    assert llm_session.trace_control_state == "kept"
    assert llm_session.response_summary == "verbatim local coaching transcript"
    assert llm_session.external_export_allowed is True


def test_trace_control_endpoint_forgets_session_summary() -> None:
    with _client() as (client, session_factory):
        create_response = client.post(
            "/llm/sessions",
            json={
                "learner_id": "learner-1",
                "mode": "study-coach",
                "user_message": "Can you explain this?",
            },
        )
        session_id = create_response.json()["session_id"]

        forget_response = client.post(
            f"/llm/sessions/{session_id}/trace-control",
            json={"action": "forget", "actor_id": "learner-1"},
        )

        assert forget_response.status_code == 200
        body = forget_response.json()
        assert body["trace_control_state"] == "forgotten"
        assert body["response_summary_retained"] is False
        assert body["external_export_allowed"] is False

        with session_factory() as session:
            stored = session.get(LLMSession, session_id)
        assert stored is not None
        assert stored.response_summary is None
