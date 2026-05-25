"""Repository helpers for learner attempts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from lms.evidence.models import Attempt


def create_attempt(
    session: Session,
    *,
    learner_id: str,
    prompt_id: str,
    response_text: str,
    feedback: dict[str, Any],
    confidence_rating: int | None = None,
    reference_accessed: bool = False,
    hint_used: bool = False,
    support_level: str = "none",
    elapsed_seconds: int | None = None,
    llm_session_id: str | None = None,
) -> Attempt:
    """Persist a learner attempt with structured feedback."""
    if not feedback.get("next_action"):
        raise ValueError("structured feedback requires next_action")
    attempt = Attempt(
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text=response_text,
        confidence_rating=confidence_rating,
        reference_accessed=reference_accessed,
        hint_used=hint_used,
        support_level=support_level,
        elapsed_seconds=elapsed_seconds,
        feedback=feedback,
        llm_session_id=llm_session_id,
    )
    session.add(attempt)
    session.flush()
    return attempt


def get_attempt(session: Session, attempt_id: str) -> Attempt | None:
    """Return an attempt by stable id."""
    return session.get(Attempt, attempt_id)
