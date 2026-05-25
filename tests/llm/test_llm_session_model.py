"""ORM-level tests for the LLMSession SQLAlchemy model."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.llm.models import LLMSession


def test_llm_session_round_trip(db_session: Session) -> None:
    """A valid LLMSession persists and round-trips through the ORM."""
    session = LLMSession(
        mode="study-coach",
        trace_class="formative",
        provider="fake",
        model="fake-haiku",
        input_tokens=12,
        output_tokens=34,
        cost_micro_usd=46,
        redaction_applied=True,
        redacted_span_count=2,
        external_export_allowed=False,
    )
    db_session.add(session)
    db_session.commit()

    fetched = db_session.get(LLMSession, session.id)
    assert fetched is not None
    assert fetched.trace_class == "formative"
    assert fetched.mode == "study-coach"
    assert fetched.redaction_applied is True
    assert fetched.external_export_allowed is False


def test_llm_session_rejects_unknown_trace_class(db_session: Session) -> None:
    """SQLAlchemy emits the CHECK constraint on a bad trace_class."""
    bad = LLMSession(
        mode="study-coach",
        trace_class="not-a-class",
        provider="fake",
        model="fake-haiku",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_llm_session_rejects_unknown_mode(db_session: Session) -> None:
    bad = LLMSession(
        mode="brainstorm",
        trace_class="formative",
        provider="fake",
        model="fake-haiku",
    )
    db_session.add(bad)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
