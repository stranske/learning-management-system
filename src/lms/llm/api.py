"""HTTP API for LLM learning sessions."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.exceptions import SourceConstraintViolation
from lms.llm.interaction_policy import (
    InteractionContext,
    build_policy_prompt,
    decide_interaction_policy,
    flag_uncited_claims,
)
from lms.llm.providers import FakeProvider

router = APIRouter(prefix="/llm", tags=["llm"])
SessionDep = Annotated[Session, Depends(get_session)]


class LLMSessionCreate(BaseModel):
    """Request body for a single formative LLM turn."""

    learner_id: str = Field(min_length=1, max_length=36)
    mode: Literal["study-coach", "practice"] = "study-coach"
    user_message: str = Field(min_length=1)
    prompt_id: str | None = Field(default=None, max_length=36)
    mastery_context: str | None = None
    source_constraints: list[str] = Field(default_factory=list)
    assessment_restricted: bool = False
    retrieval_active: bool = False
    hint_count: int = Field(default=0, ge=0)
    confidence_rating: int | None = Field(default=None, ge=1, le=5)
    recent_attempt_correct: bool | None = None


class LLMSessionRead(BaseModel):
    """Response for a persisted LLM learning turn."""

    session_id: str
    mode: str
    trace_class: str
    response_text: str
    policy_decision: dict[str, object]
    flags: list[str]


@lru_cache(maxsize=1)
def _default_client() -> LLMClient:
    provider = FakeProvider(
        responder=lambda _model, prompt: (
            "Try a retrieval attempt first, then compare it with the linked source."
            if "retrieval-nudge" in prompt
            else "Here is a concise explanation tied to the requested learning goal."
        )
    )
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "fake-learning-policy"),
        global_daily_cap_micro_usd=1_000_000,
        default_provider="fake",
    )
    return LLMClient(
        config=config,
        providers={"fake": provider},
        budget=DailyBudgetTracker(
            mode_caps_micro_usd={},
            global_cap_micro_usd=1_000_000,
        ),
    )


@router.post("/sessions", response_model=LLMSessionRead)
def create_llm_session_route(payload: LLMSessionCreate, session: SessionDep) -> LLMSessionRead:
    """Create and persist a fake-provider study/practice LLM turn."""
    context = InteractionContext(
        mode=payload.mode,
        learner_id=payload.learner_id,
        user_message=payload.user_message,
        prompt_id=payload.prompt_id,
        mastery_context=payload.mastery_context,
        source_constraints=tuple(payload.source_constraints),
        assessment_restricted=payload.assessment_restricted,
        retrieval_active=payload.retrieval_active,
        hint_count=payload.hint_count,
        confidence_rating=payload.confidence_rating,
        recent_attempt_correct=payload.recent_attempt_correct,
    )
    decision = decide_interaction_policy(context)
    client = _default_client()
    prompt = build_policy_prompt(context, decision)
    flags: tuple[str, ...] = ()
    try:
        response = client.complete(
            mode=payload.mode,
            prompt=prompt,
            trace_class=decision.trace_class,
            source_constraints=decision.source_constraints,
            learner_id=payload.learner_id,
            prompt_template_version="study-coach-policy-v1",
            provider_name="fake",
        )
        flags = flag_uncited_claims(response.text, decision.source_constraints)
    except SourceConstraintViolation:
        response = client.complete(
            mode=payload.mode,
            prompt=prompt,
            trace_class=decision.trace_class,
            learner_id=payload.learner_id,
            prompt_template_version="study-coach-policy-v1",
            provider_name="fake",
        )
        flags = ("unverified",)
    session.add(response.session)
    session.commit()
    session.refresh(response.session)

    return LLMSessionRead(
        session_id=response.session.id,
        mode=response.session.mode,
        trace_class=response.session.trace_class,
        response_text=response.text,
        policy_decision={
            "behavior": decision.behavior,
            "learning_risk": decision.learning_risk,
            "next_action": decision.next_action,
            "response_style": decision.response_style,
            "direct_answer_allowed": decision.direct_answer_allowed,
            "disabled_supports": list(decision.disabled_supports),
        },
        flags=list(flags),
    )
