"""Formative interaction policy for study-coach and practice sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PolicyMode = Literal["study-coach", "practice"]

ANSWER_SEEKING_TERMS = (
    "answer",
    "solve it",
    "give me the solution",
    "what is the result",
    "tell me",
)
ORIENTATION_TERMS = (
    "explain",
    "why",
    "overview",
    "orient",
    "teach me",
)


@dataclass(frozen=True)
class InteractionContext:
    """Learner/session context used for deterministic policy decisions."""

    mode: PolicyMode
    learner_id: str
    user_message: str
    prompt_id: str | None = None
    mastery_context: str | None = None
    source_constraints: tuple[str, ...] = ()
    assessment_restricted: bool = False
    retrieval_active: bool = False
    hint_count: int = 0
    confidence_rating: int | None = None
    recent_attempt_correct: bool | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """Instructional policy outcome attached to an LLM turn."""

    behavior: str
    learning_risk: str
    next_action: str
    response_style: str
    direct_answer_allowed: bool
    trace_class: str = "formative"
    disabled_supports: tuple[str, ...] = ()
    source_constraints: tuple[str, ...] = ()
    flags: tuple[str, ...] = field(default_factory=tuple)


def decide_interaction_policy(context: InteractionContext) -> PolicyDecision:
    """Return a deterministic formative policy decision for one learner turn."""
    message = context.user_message.lower()
    answer_seeking = any(term in message for term in ANSWER_SEEKING_TERMS)
    orientation_request = any(term in message for term in ORIENTATION_TERMS)
    weak_high_confidence = (
        context.confidence_rating is not None
        and context.confidence_rating >= 4
        and context.recent_attempt_correct is False
    )
    overusing_hints = context.hint_count >= 2

    disabled_supports: tuple[str, ...] = ()
    if context.assessment_restricted:
        disabled_supports = ("hints", "direct-feedback")

    if context.retrieval_active and answer_seeking:
        return PolicyDecision(
            behavior="answer-seeking-during-retrieval",
            learning_risk="retrieval-practice-bypass",
            next_action="Ask the learner to attempt recall first, then offer a small cue.",
            response_style="retrieval-nudge",
            direct_answer_allowed=False,
            disabled_supports=disabled_supports,
            source_constraints=context.source_constraints,
        )

    if overusing_hints:
        return PolicyDecision(
            behavior="overuse-of-hints",
            learning_risk="support-dependence",
            next_action="Fade hints and ask for an unaided partial response.",
            response_style="hint-fade",
            direct_answer_allowed=False,
            disabled_supports=disabled_supports,
            source_constraints=context.source_constraints,
        )

    if weak_high_confidence:
        return PolicyDecision(
            behavior="high-confidence-with-weak-evidence",
            learning_risk="miscalibrated-confidence",
            next_action="Ask for evidence, counterexample, or a confidence check.",
            response_style="calibration-nudge",
            direct_answer_allowed=False,
            disabled_supports=disabled_supports,
            source_constraints=context.source_constraints,
        )

    if orientation_request and not context.assessment_restricted:
        return PolicyDecision(
            behavior="orientation-request",
            learning_risk="low",
            next_action="Give a concise explanation, then ask for active recall.",
            response_style="direct-explanation",
            direct_answer_allowed=True,
            disabled_supports=disabled_supports,
            source_constraints=context.source_constraints,
        )

    if context.assessment_restricted:
        return PolicyDecision(
            behavior="assessment-restricted-learning-turn",
            learning_risk="assessment-integrity",
            next_action="Ask for recall or reasoning without giving the direct answer.",
            response_style="assessment-nudge",
            direct_answer_allowed=False,
            disabled_supports=disabled_supports,
            source_constraints=context.source_constraints,
        )

    return PolicyDecision(
        behavior="productive-learning-turn",
        learning_risk="low",
        next_action="Answer briefly and ask for the learner's next attempt.",
        response_style="guided-response",
        direct_answer_allowed=True,
        disabled_supports=disabled_supports,
        source_constraints=context.source_constraints,
    )


def build_policy_prompt(context: InteractionContext, decision: PolicyDecision) -> str:
    """Build the provider prompt from policy, source, and learner context."""
    constraints = ", ".join(decision.source_constraints) or "none"
    supports = ", ".join(decision.disabled_supports) or "none"
    return "\n".join(
        [
            f"Mode: {context.mode}",
            f"Learner: {context.learner_id}",
            f"Prompt id: {context.prompt_id or 'none'}",
            f"Policy behavior: {decision.behavior}",
            f"Response style: {decision.response_style}",
            f"Direct answer allowed: {decision.direct_answer_allowed}",
            f"Disabled supports: {supports}",
            f"Source constraints: {constraints}",
            f"Mastery context: {context.mastery_context or 'not provided'}",
            "Learner message:",
            context.user_message,
        ]
    )


def flag_uncited_claims(text: str, source_constraints: tuple[str, ...]) -> tuple[str, ...]:
    """Flag source-constrained output that omits required source identifiers."""
    if not source_constraints:
        return ()
    missing = [source_id for source_id in source_constraints if source_id not in text]
    return ("unverified",) if missing else ()
