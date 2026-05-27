"""Tests for persisted LLM learning interaction skills."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.llm.models import LearningInteractionSkill


def test_create_interaction_skill_for_transfer_mode(db_session: Session) -> None:
    """A named transfer-mode interaction skill persists policy and trace constraints."""
    skill = LearningInteractionSkill(
        name="transfer-feedback-synthesis",
        mode="transfer",
        policy_version="segment-10-v1",
        description="Summarize transfer evidence without leaking source text.",
        allowed_trace_classes=["formative", "evidence-grade"],
        source_citation_required=True,
    )
    db_session.add(skill)
    db_session.commit()

    fetched = db_session.get(LearningInteractionSkill, skill.id)

    assert fetched is not None
    assert fetched.mode == "transfer"
    assert fetched.policy_version == "segment-10-v1"
    assert fetched.allowed_trace_classes == ["formative", "evidence-grade"]
    assert fetched.source_citation_required is True
    assert fetched.active is True
