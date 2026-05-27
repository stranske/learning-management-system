"""Tests for prompt hints, model answers, and reveal support signals."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt
from lms.feedback.repository import (
    create_hint,
    create_model_answer,
    learner_safe_source_citations,
    list_hints,
    reveal_hint,
    reveal_model_answer,
)
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.repository import create_source_reference


def _prompt(db_session: Session) -> Prompt:
    public_ref = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.test/fractions",
        content="Fraction source",
        actor_id="user:alice",
        source_visibility="public",
    )
    local_ref = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator="/Users/teacher/private/fractions.md",
        content="Local source",
        actor_id="user:alice",
        source_visibility="local-only",
    )
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
        source_references=[public_ref, local_ref],
    )
    prompt.versions.append(
        PromptVersion(
            version_number=1, body="Explain equivalent fractions.", created_by="user:alice"
        )
    )
    db_session.add(prompt)
    db_session.flush()
    return prompt


def test_hint_reveal_marks_attempt_and_evidence_hint_used(db_session: Session) -> None:
    """Hint reveals down-weight support-sensitive attempt and evidence signals."""
    prompt = _prompt(db_session)
    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id=prompt.id,
        response_text="I multiplied only the numerator.",
        feedback={"goal": "Equivalent fractions", "next_action": "Use both terms"},
        evidence={
            "knowledge_node_id": "node-1",
            "correctness": False,
            "normalized_score": 0.25,
            "max_score": 1,
        },
    )
    hint = create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="Scale the numerator and denominator by the same factor.",
        reveal_order=1,
        support_level="hint",
        authoring_actor="user:alice",
    )

    reveal = reveal_hint(
        db_session,
        hint,
        learner_id="learner-1",
        attempt_id=attempt.id,
        initiated_by="learner",
    )
    db_session.refresh(attempt)
    evidence = attempt.evidence_records[0]

    assert reveal.hint_id == hint.id
    assert attempt.hint_used is True
    assert attempt.support_level == "hint"
    assert evidence.hint_used is True
    assert evidence.support_level == "hint"


def test_model_answer_requires_attempt_before_reveal_by_default(db_session: Session) -> None:
    """Learners cannot reveal model answers before submitting work."""
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session,
        prompt_id=prompt.id,
        answer_body="Multiply numerator and denominator by the same factor.",
        authoring_actor="user:alice",
    )

    with pytest.raises(ValueError, match="requires a completed attempt"):
        reveal_model_answer(db_session, answer, learner_id="learner-1")

    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id=prompt.id,
        response_text="I tried before viewing the model answer.",
        feedback={"goal": "Equivalent fractions"},
    )
    reveal = reveal_model_answer(
        db_session,
        answer,
        learner_id="learner-1",
        attempt_id=attempt.id,
    )

    assert reveal.model_answer_id == answer.id
    assert reveal.attempt_id == attempt.id


def test_ordered_hints_hide_local_only_source_locators(db_session: Session) -> None:
    """Learner-facing hint citations preserve public sources and redact local locators."""
    prompt = _prompt(db_session)
    second = create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="Second hint",
        reveal_order=2,
        authoring_actor="user:alice",
    )
    first = create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="First hint",
        reveal_order=1,
        authoring_actor="user:alice",
    )

    assert [hint.id for hint in list_hints(db_session, prompt_id=prompt.id)] == [
        first.id,
        second.id,
    ]

    citations = learner_safe_source_citations(db_session, prompt.id)
    assert any(
        citation["stable_locator"] == "https://example.test/fractions" for citation in citations
    )
    assert not any(
        citation["stable_locator"] == "/Users/teacher/private/fractions.md"
        for citation in citations
    )
