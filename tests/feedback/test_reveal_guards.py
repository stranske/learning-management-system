"""Cross-entity guards on hint and model-answer reveals.

Every branch here refuses a reveal, and each refusal protects something different: a reveal policy
that decides whether a learner may see the answer before attempting, and a set of consistency
checks that stop one learner's attempt being credited against another's. All of them were
unreached.

The reveal policy is the pedagogically load-bearing one. `after-attempt` exists so that seeing the
model answer costs an attempt; if that check ever passes silently, the learning signal is gone and
nothing about the system looks broken — attempts still record, evidence still accumulates, and the
data quietly stops meaning what it says.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt
from lms.feedback.repository import (
    create_hint,
    create_model_answer,
    list_hints,
    list_model_answers,
    reveal_hint,
    reveal_model_answer,
)
from lms.prompts.models import Prompt, PromptVersion


def _prompt(session: Session, body: str = "Explain equivalent fractions.") -> Prompt:
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
    prompt.versions.append(PromptVersion(version_number=1, body=body, created_by="user:alice"))
    session.add(prompt)
    session.flush()
    return prompt


def _attempt(session: Session, *, prompt_id: str, learner_id: str):
    return create_attempt(
        session,
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text="an answer",
        feedback={"goal": "g", "next_action": "n"},
        evidence={"knowledge_node_id": "node-1", "outcome": "correct"},
    )


# ---------------------------------------------------------------------------------------------
# Hint reveals.
# ---------------------------------------------------------------------------------------------


def test_a_hint_reveal_without_an_attempt_records_no_attempt_effects(db_session: Session):
    """The `attempt_id=None` path: a hint read outside an attempt still records the reveal, but
    has no attempt to down-weight."""
    prompt = _prompt(db_session)
    hint = create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="Consider both terms.",
        reveal_order=1,
        authoring_actor="user:alice",
    )

    reveal = reveal_hint(db_session, hint, learner_id="learner-1")

    assert reveal.attempt_id is None
    assert reveal.prompt_id == prompt.id
    assert reveal.learner_id == "learner-1"


def test_a_hint_reveal_against_an_unknown_attempt_is_refused(db_session: Session):
    prompt = _prompt(db_session)
    hint = create_hint(
        db_session, prompt_id=prompt.id, hint_text="h", reveal_order=1, authoring_actor="user:alice"
    )

    with pytest.raises(ValueError, match="referenced attempt was not found"):
        reveal_hint(db_session, hint, learner_id="learner-1", attempt_id="attempt-does-not-exist")


def test_a_hint_reveal_against_another_prompts_attempt_is_refused(db_session: Session):
    """Crediting the hint to an attempt on a different prompt would mark that attempt as
    hint-assisted, permanently weakening evidence for work the hint never touched."""
    prompt = _prompt(db_session)
    other_prompt = _prompt(db_session, body="A different question.")
    hint = create_hint(
        db_session, prompt_id=prompt.id, hint_text="h", reveal_order=1, authoring_actor="user:alice"
    )
    other_attempt = _attempt(db_session, prompt_id=other_prompt.id, learner_id="learner-1")

    with pytest.raises(ValueError, match="attempt does not match the hint prompt"):
        reveal_hint(db_session, hint, learner_id="learner-1", attempt_id=other_attempt.id)


def test_a_hint_reveal_against_another_learners_attempt_is_refused(db_session: Session):
    """The check that keeps one learner's support level out of another's record."""
    prompt = _prompt(db_session)
    hint = create_hint(
        db_session, prompt_id=prompt.id, hint_text="h", reveal_order=1, authoring_actor="user:alice"
    )
    their_attempt = _attempt(db_session, prompt_id=prompt.id, learner_id="learner-2")

    with pytest.raises(ValueError, match="attempt does not match learner"):
        reveal_hint(db_session, hint, learner_id="learner-1", attempt_id=their_attempt.id)


@pytest.mark.parametrize("mismatch", ["prompt", "learner"])
def test_a_refused_hint_reveal_leaves_the_attempt_unmarked(db_session: Session, mismatch):
    """The guards come before the mutation, so a refusal must not half-apply. An attempt marked
    `hint_used` by a reveal that then failed would be down-weighted for support it never got.

    Parametrised over BOTH refusal paths, because a mutation moved above only one of them is
    exactly the kind of change one case would miss. Asserted on the in-memory object rather than
    after `session.refresh()` — a refresh re-reads the row and would discard the very unflushed
    attribute the test is looking for, which makes the check pass against the defect.
    """
    prompt = _prompt(db_session)
    hint = create_hint(
        db_session, prompt_id=prompt.id, hint_text="h", reveal_order=1, authoring_actor="user:alice"
    )
    if mismatch == "prompt":
        other = _prompt(db_session, body="Another question.")
        attempt = _attempt(db_session, prompt_id=other.id, learner_id="learner-1")
    else:
        attempt = _attempt(db_session, prompt_id=prompt.id, learner_id="learner-2")

    with pytest.raises(ValueError):
        reveal_hint(db_session, hint, learner_id="learner-1", attempt_id=attempt.id)

    assert attempt.hint_used is not True


# ---------------------------------------------------------------------------------------------
# Model-answer reveals: the policy.
# ---------------------------------------------------------------------------------------------


def test_the_default_policy_requires_an_attempt_first(db_session: Session):
    """`after-attempt` is what makes seeing the answer cost an attempt. Without it the learner
    reads the answer, the attempt records as correct, and the evidence is worthless."""
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session,
        prompt_id=prompt.id,
        answer_body="Multiply both terms.",
        authoring_actor="user:alice",
    )

    with pytest.raises(ValueError, match="requires a completed attempt"):
        reveal_model_answer(db_session, answer, learner_id="learner-1")


def test_instructor_mode_reveals_without_an_attempt(db_session: Session):
    """The documented escape hatch — and it has to work, or authors cannot review their own
    answers."""
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )

    reveal = reveal_model_answer(db_session, answer, learner_id="user:alice", instructor_mode=True)

    assert reveal.attempt_id is None
    assert reveal.model_answer_id == answer.id


def test_an_instructor_only_answer_is_not_revealed_by_an_attempt(db_session: Session):
    """The stricter policy. An attempt satisfies `after-attempt` but must NOT satisfy
    `instructor-only` — otherwise the two policies are the same policy."""
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session,
        prompt_id=prompt.id,
        answer_body="a",
        authoring_actor="user:alice",
        reveal_policy="instructor-only",
    )
    attempt = _attempt(db_session, prompt_id=prompt.id, learner_id="learner-1")

    with pytest.raises(ValueError, match="requires instructor mode"):
        reveal_model_answer(db_session, answer, learner_id="learner-1", attempt_id=attempt.id)


def test_an_instructor_only_answer_is_revealed_in_instructor_mode(db_session: Session):
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session,
        prompt_id=prompt.id,
        answer_body="a",
        authoring_actor="user:alice",
        reveal_policy="instructor-only",
    )

    reveal = reveal_model_answer(db_session, answer, learner_id="user:alice", instructor_mode=True)
    assert reveal.model_answer_id == answer.id


def test_an_attempt_satisfies_the_after_attempt_policy(db_session: Session):
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )
    attempt = _attempt(db_session, prompt_id=prompt.id, learner_id="learner-1")

    reveal = reveal_model_answer(db_session, answer, learner_id="learner-1", attempt_id=attempt.id)
    assert reveal.attempt_id == attempt.id


# ---------------------------------------------------------------------------------------------
# Model-answer reveals: the same cross-entity checks as hints.
# ---------------------------------------------------------------------------------------------


def test_a_model_answer_reveal_against_an_unknown_attempt_is_refused(db_session: Session):
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )

    with pytest.raises(ValueError, match="referenced attempt was not found"):
        reveal_model_answer(db_session, answer, learner_id="learner-1", attempt_id="nope")


def test_another_prompts_attempt_does_not_unlock_a_model_answer(db_session: Session):
    """Otherwise one attempt anywhere unlocks every answer everywhere, which is the reveal policy
    with no policy left in it."""
    prompt = _prompt(db_session)
    other_prompt = _prompt(db_session, body="Another question.")
    answer = create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )
    other_attempt = _attempt(db_session, prompt_id=other_prompt.id, learner_id="learner-1")

    with pytest.raises(ValueError, match="attempt does not match the model answer prompt"):
        reveal_model_answer(db_session, answer, learner_id="learner-1", attempt_id=other_attempt.id)


def test_another_learners_attempt_does_not_unlock_a_model_answer(db_session: Session):
    """One learner attempting must not open the answer for everybody else on the same prompt."""
    prompt = _prompt(db_session)
    answer = create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )
    their_attempt = _attempt(db_session, prompt_id=prompt.id, learner_id="learner-2")

    with pytest.raises(ValueError, match="attempt does not match learner"):
        reveal_model_answer(db_session, answer, learner_id="learner-1", attempt_id=their_attempt.id)


# ---------------------------------------------------------------------------------------------
# Creation guards and listing filters.
# ---------------------------------------------------------------------------------------------


def test_a_model_answer_for_an_unknown_prompt_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="referenced prompt was not found"):
        create_model_answer(
            db_session, prompt_id="no-such-prompt", answer_body="a", authoring_actor="user:alice"
        )


def test_a_model_answer_citing_an_unknown_rubric_is_refused(db_session: Session):
    """A dangling rubric id would surface much later as a missing scoring guide."""
    prompt = _prompt(db_session)
    with pytest.raises(ValueError, match="referenced rubric was not found"):
        create_model_answer(
            db_session,
            prompt_id=prompt.id,
            answer_body="a",
            authoring_actor="user:alice",
            rubric_id="no-such-rubric",
        )


def test_listing_hints_by_prompt_excludes_other_prompts(db_session: Session):
    """An optional filter that silently does not filter returns another prompt's hints to the
    learner — which is the same as revealing them."""
    prompt = _prompt(db_session)
    other = _prompt(db_session, body="Another question.")
    create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="mine",
        reveal_order=1,
        authoring_actor="user:alice",
    )
    create_hint(
        db_session,
        prompt_id=other.id,
        hint_text="theirs",
        reveal_order=1,
        authoring_actor="user:alice",
    )

    bodies = [hint.hint_text for hint in list_hints(db_session, prompt_id=prompt.id)]
    assert bodies == ["mine"]


def test_listing_hints_without_a_filter_returns_every_prompt(db_session: Session):
    """The unfiltered branch, so the filter above is shown to be doing the work."""
    prompt = _prompt(db_session)
    other = _prompt(db_session, body="Another question.")
    create_hint(
        db_session,
        prompt_id=prompt.id,
        hint_text="mine",
        reveal_order=1,
        authoring_actor="user:alice",
    )
    create_hint(
        db_session,
        prompt_id=other.id,
        hint_text="theirs",
        reveal_order=1,
        authoring_actor="user:alice",
    )

    bodies = {hint.hint_text for hint in list_hints(db_session)}
    assert bodies == {"mine", "theirs"}


def test_listing_model_answers_by_prompt_excludes_other_prompts(db_session: Session):
    prompt = _prompt(db_session)
    other = _prompt(db_session, body="Another question.")
    create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="mine", authoring_actor="user:alice"
    )
    create_model_answer(
        db_session, prompt_id=other.id, answer_body="theirs", authoring_actor="user:alice"
    )

    bodies = [a.answer_body for a in list_model_answers(db_session, prompt_id=prompt.id)]
    assert bodies == ["mine"]


def test_listing_model_answers_does_not_record_a_reveal(db_session: Session):
    """Listing is metadata only. If it counted as a reveal, an author browsing the catalogue
    would burn every learner's attempt gate."""
    from lms.feedback.models import ModelAnswerReveal

    prompt = _prompt(db_session)
    create_model_answer(
        db_session, prompt_id=prompt.id, answer_body="a", authoring_actor="user:alice"
    )
    list_model_answers(db_session, prompt_id=prompt.id)

    assert db_session.query(ModelAnswerReveal).count() == 0
