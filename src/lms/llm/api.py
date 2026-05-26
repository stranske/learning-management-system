"""HTTP API for LLM learning sessions."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.llm.authoring_assist import ProposalDraft, propose_authoring_drafts
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
from lms.llm.models import LLMSession
from lms.llm.providers import FakeProvider
from lms.llm.trace_controls import apply_trace_control

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
    coaching_intensity: Literal["full", "light", "quiet"] = "full"


class LLMSessionRead(BaseModel):
    """Response for a persisted LLM learning turn."""

    session_id: str
    mode: str
    trace_class: str
    coaching_intensity: str
    model: str
    cost_micro_usd: int
    cost_summary: dict[str, int]
    external_export_allowed: bool
    trace_control_state: str
    response_text: str
    policy_decision: dict[str, object]
    flags: list[str]


@lru_cache(maxsize=1)
def _default_client() -> LLMClient:
    provider = FakeProvider(
        responder=lambda _model, prompt: (
            prompt
            if "Mode: authoring-assist" in prompt
            else (
                "Try a retrieval attempt first, then compare it with the linked source."
                if "retrieval-nudge" in prompt
                else "Here is a concise explanation tied to the requested learning goal."
            )
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


class AuthoringAssistProposeRequest(BaseModel):
    """Request body for an authoring-assist proposal call."""

    source_reference_id: str = Field(min_length=1, max_length=36)
    target_node_id: str = Field(min_length=1, max_length=36)
    learning_goal_id: str = Field(min_length=1, max_length=36)
    actor_id: str = Field(min_length=1, max_length=255)
    related_node_title: str = Field(min_length=1, max_length=255)
    related_node_knowledge_type: str = Field(min_length=1, max_length=32)
    prompt_body: str = Field(min_length=1)
    prompt_knowledge_type: str = Field(min_length=1, max_length=32)
    prompt_intended_cognitive_action: str = Field(min_length=1, max_length=32)
    prompt_demand_level: str = Field(min_length=1, max_length=32)
    prompt_expected_answer_form: str = Field(min_length=1, max_length=32)
    related_node_description: str | None = None
    edge_type: str | None = Field(default=None, max_length=32)
    learner_id: str | None = Field(default=None, max_length=36)


class AuthoringAssistProposeResponse(BaseModel):
    """Persisted proposal identifiers returned to the caller."""

    llm_proposal_id: str
    llm_session_id: str
    llm_model: str
    knowledge_node_id: str
    knowledge_edge_id: str | None
    prompt_id: str
    node_status: str
    node_provenance: str
    prompt_status: str
    prompt_authoring_method: str


class LLMTraceControlRequest(BaseModel):
    """Learner keep/forget action for a retained LLM trace."""

    action: Literal["keep", "forget"]
    actor_id: str = Field(min_length=1, max_length=255)


class LLMTraceControlRead(BaseModel):
    """Trace-control result for a stored LLM session."""

    session_id: str
    trace_class: str
    trace_control_state: str
    response_summary_retained: bool
    external_export_allowed: bool


@router.post(
    "/authoring-assist/propose",
    response_model=AuthoringAssistProposeResponse,
)
def authoring_assist_propose_route(
    payload: AuthoringAssistProposeRequest,
    session: SessionDep,
) -> AuthoringAssistProposeResponse:
    """Create draft authoring-assist proposals routed through the LLM wrapper."""
    client = _default_client()
    try:
        result = propose_authoring_drafts(
            session,
            client=client,
            source_reference_id=payload.source_reference_id,
            target_node_id=payload.target_node_id,
            learning_goal_id=payload.learning_goal_id,
            actor_id=payload.actor_id,
            draft=ProposalDraft(
                related_node_title=payload.related_node_title,
                related_node_knowledge_type=payload.related_node_knowledge_type,
                prompt_body=payload.prompt_body,
                prompt_knowledge_type=payload.prompt_knowledge_type,
                prompt_intended_cognitive_action=payload.prompt_intended_cognitive_action,
                prompt_demand_level=payload.prompt_demand_level,
                prompt_expected_answer_form=payload.prompt_expected_answer_form,
                related_node_description=payload.related_node_description,
                edge_type=payload.edge_type,
            ),
            learner_id=payload.learner_id,
        )
    except (SourceConstraintViolation, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    session.refresh(result.llm_proposal)
    return AuthoringAssistProposeResponse(
        llm_proposal_id=result.llm_proposal.id,
        llm_session_id=result.llm_session.id,
        llm_model=result.llm_proposal.llm_model,
        knowledge_node_id=result.knowledge_node.id,
        knowledge_edge_id=result.knowledge_edge.id if result.knowledge_edge is not None else None,
        prompt_id=result.prompt.id,
        node_status=result.knowledge_node.status,
        node_provenance=result.knowledge_node.provenance,
        prompt_status=result.prompt.status,
        prompt_authoring_method=result.prompt.authoring_method,
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
        coaching_intensity=payload.coaching_intensity,
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
            coaching_intensity=payload.coaching_intensity,
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
            coaching_intensity=payload.coaching_intensity,
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
        coaching_intensity=response.session.coaching_intensity,
        model=response.session.model,
        cost_micro_usd=response.session.cost_micro_usd,
        cost_summary={
            "input_tokens": response.session.input_tokens,
            "output_tokens": response.session.output_tokens,
            "cost_micro_usd": response.session.cost_micro_usd,
        },
        external_export_allowed=response.session.external_export_allowed,
        trace_control_state=response.session.trace_control_state,
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


@router.post("/sessions/{session_id}/trace-control", response_model=LLMTraceControlRead)
def control_llm_trace_route(
    session_id: str,
    payload: LLMTraceControlRequest,
    session: SessionDep,
) -> LLMTraceControlRead:
    """Apply a learner keep/forget override to one persisted LLM session."""
    llm_session = session.get(LLMSession, session_id)
    if llm_session is None:
        raise HTTPException(status_code=404, detail="LLM session not found")
    try:
        apply_trace_control(
            session,
            llm_session,
            action=payload.action,
            actor_id=payload.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    session.refresh(llm_session)
    return LLMTraceControlRead(
        session_id=llm_session.id,
        trace_class=llm_session.trace_class,
        trace_control_state=llm_session.trace_control_state,
        response_summary_retained=llm_session.response_summary is not None,
        external_export_allowed=llm_session.external_export_allowed,
    )
