"""Learner keep/forget controls for LLM session traces."""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.auth.models import utc_now
from lms.llm.models import LLMSession

TraceControlAction = Literal["keep", "forget"]


def apply_trace_control(
    session: Session,
    llm_session: LLMSession,
    *,
    action: TraceControlAction,
    actor_id: str,
) -> LLMSession:
    """Apply a learner trace-retention override to one LLM session.

    ``forget`` deletes the locally retained response summary and disables
    external export while leaving any structured evidence or attempts that point
    at the session untouched. ``keep`` marks eligible non-ephemeral traces for
    retention without changing their trace class.
    """
    before = _audit_summary(llm_session)
    if action == "forget":
        llm_session.response_summary = None
        llm_session.external_export_allowed = False
        llm_session.trace_control_state = "forgotten"
        llm_session.transcript_deleted_at = utc_now()
    elif action == "keep":
        if llm_session.trace_class == "ephemeral":
            raise ValueError("ephemeral traces cannot be marked for verbatim retention")
        llm_session.trace_control_state = "kept"
    else:
        raise ValueError(f"unknown trace control action {action!r}")

    record_audit_event(
        session,
        actor_id=actor_id,
        action=f"llm_trace_{action}",
        entity_type="LLMSession",
        entity_id=llm_session.id,
        source_subsystem="llm-trace-controls",
        before_summary=before,
        after_summary=_audit_summary(llm_session),
    )
    return llm_session


def _audit_summary(llm_session: LLMSession) -> dict[str, object]:
    return {
        "trace_class": llm_session.trace_class,
        "trace_control_state": llm_session.trace_control_state,
        "response_summary_retained": llm_session.response_summary is not None,
        "external_export_allowed": llm_session.external_export_allowed,
        "transcript_deleted_at": (
            llm_session.transcript_deleted_at.isoformat()
            if llm_session.transcript_deleted_at is not None
            else None
        ),
    }
