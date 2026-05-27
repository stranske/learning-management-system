"""HTTP API for LLM learning sessions."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.feedback.models import FeedbackRecord
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
from lms.llm.models import (
    LearningInteractionSkill,
    LLMFeedbackEvent,
    LLMSession,
    TraceClassName,
)
from lms.llm.providers import FakeProvider
from lms.llm.trace_controls import apply_trace_control

router = APIRouter(prefix="/llm", tags=["llm"])
SessionDep = Annotated[Session, Depends(get_session)]


def _default_allowed_trace_classes() -> list[TraceClassName]:
    return ["formative"]


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
    skill_id: str | None = Field(default=None, max_length=36)
    feedback_record_id: str | None = Field(default=None, max_length=36)
    evidence_record_id: str | None = Field(default=None, max_length=36)


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
    feedback_event_id: str | None = None


class LearningInteractionSkillCreate(BaseModel):
    """Request body for registering a named LLM learning skill."""

    name: str = Field(min_length=1, max_length=120)
    mode: Literal["study-coach", "practice", "transfer", "authoring-assist"]
    policy_version: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    allowed_trace_classes: list[TraceClassName] = Field(
        default_factory=_default_allowed_trace_classes
    )
    source_citation_required: bool = False
    active: bool = True


class LearningInteractionSkillRead(BaseModel):
    """Registered learning interaction skill."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    mode: str
    policy_version: str
    description: str
    allowed_trace_classes: list[str]
    source_citation_required: bool
    active: bool


class LLMFeedbackEventCreate(BaseModel):
    """Request body for recording a per-turn LLM feedback fact."""

    llm_session_id: str = Field(min_length=1, max_length=36)
    learner_id: str = Field(min_length=1, max_length=36)
    skill_id: str | None = Field(default=None, max_length=36)
    feedback_record_id: str | None = Field(default=None, max_length=36)
    evidence_record_id: str | None = Field(default=None, max_length=36)
    event_type: Literal[
        "learning-policy-nudge",
        "feedback-outcome",
        "source-citation-check",
        "manual-review",
    ] = "learning-policy-nudge"
    trace_class: TraceClassName = "formative"
    source_reference_ids: list[str] = Field(default_factory=list)
    unverified: bool = False
    cost_metadata: dict[str, int | str | bool] = Field(default_factory=dict)
    event_summary: str | None = None
    event_body: str | None = None


class LLMFeedbackEventRead(BaseModel):
    """Persisted per-turn feedback fact."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    llm_session_id: str
    learner_id: str
    skill_id: str | None
    feedback_record_id: str | None
    evidence_record_id: str | None
    event_type: str
    trace_class: str
    source_reference_ids: list[str]
    unverified: bool
    cost_metadata: dict[str, object]
    event_summary: str | None
    body_retained: bool


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


def _retain_feedback_body(trace_class: str, body: str | None) -> str | None:
    """Apply Segment 9 defaults: only evidence-grade event facts retain verbatim body."""
    if trace_class == "evidence-grade":
        return body
    return None


def _read_feedback_event(event: LLMFeedbackEvent) -> LLMFeedbackEventRead:
    return LLMFeedbackEventRead(
        id=event.id,
        llm_session_id=event.llm_session_id,
        learner_id=event.learner_id,
        skill_id=event.skill_id,
        feedback_record_id=event.feedback_record_id,
        evidence_record_id=event.evidence_record_id,
        event_type=event.event_type,
        trace_class=event.trace_class,
        source_reference_ids=event.source_reference_ids,
        unverified=event.unverified,
        cost_metadata=event.cost_metadata,
        event_summary=event.event_summary,
        body_retained=event.event_body is not None,
    )


def _validate_feedback_event_links(
    session: Session,
    *,
    llm_session_id: str | None = None,
    skill_id: str | None = None,
    feedback_record_id: str | None = None,
    evidence_record_id: str | None = None,
) -> tuple[LLMSession | None, LearningInteractionSkill | None]:
    llm_session: LLMSession | None = None
    if llm_session_id is not None:
        llm_session = session.get(LLMSession, llm_session_id)
        if llm_session is None:
            raise HTTPException(status_code=404, detail="LLM session not found")
    skill: LearningInteractionSkill | None = None
    if skill_id is not None:
        skill = session.get(LearningInteractionSkill, skill_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="Learning interaction skill not found")
    if feedback_record_id is not None and session.get(FeedbackRecord, feedback_record_id) is None:
        raise HTTPException(status_code=404, detail="Feedback record not found")
    if evidence_record_id is not None and session.get(EvidenceRecord, evidence_record_id) is None:
        raise HTTPException(status_code=404, detail="Evidence record not found")
    return llm_session, skill


def _validate_skill_consistency(
    skill: LearningInteractionSkill,
    *,
    mode: str | None = None,
    trace_class: str | None = None,
) -> None:
    """Reject linking audit rows to an incompatible learning interaction skill."""
    if not skill.active:
        raise HTTPException(
            status_code=422,
            detail="Learning interaction skill is inactive",
        )
    if mode is not None and skill.mode != mode:
        raise HTTPException(
            status_code=422,
            detail="Learning interaction skill mode does not match the requested mode",
        )
    if trace_class is not None and trace_class not in skill.allowed_trace_classes:
        raise HTTPException(
            status_code=422,
            detail="Trace class is not permitted for the linked learning interaction skill",
        )


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


@router.post(
    "/interaction-skills",
    response_model=LearningInteractionSkillRead,
    status_code=201,
)
def create_interaction_skill_route(
    payload: LearningInteractionSkillCreate,
    session: SessionDep,
) -> LearningInteractionSkillRead:
    """Register a named learning interaction skill for LLM policy audit."""
    skill = LearningInteractionSkill(
        name=payload.name,
        mode=payload.mode,
        policy_version=payload.policy_version,
        description=payload.description,
        allowed_trace_classes=list(payload.allowed_trace_classes),
        source_citation_required=payload.source_citation_required,
        active=payload.active,
    )
    session.add(skill)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A learning interaction skill with that name and policy version already exists.",
        ) from exc
    session.refresh(skill)
    return LearningInteractionSkillRead.model_validate(skill)


@router.get("/interaction-skills", response_model=list[LearningInteractionSkillRead])
def list_interaction_skills_route(
    session: SessionDep,
    mode: Literal["study-coach", "practice", "transfer", "authoring-assist"] | None = None,
    active: bool | None = None,
) -> list[LearningInteractionSkillRead]:
    """List registered learning interaction skills."""
    statement = select(LearningInteractionSkill).order_by(
        LearningInteractionSkill.name, LearningInteractionSkill.policy_version
    )
    if mode is not None:
        statement = statement.where(LearningInteractionSkill.mode == mode)
    if active is not None:
        statement = statement.where(LearningInteractionSkill.active.is_(active))
    return [
        LearningInteractionSkillRead.model_validate(skill)
        for skill in session.scalars(statement).all()
    ]


@router.post("/feedback-events", response_model=LLMFeedbackEventRead, status_code=201)
def create_feedback_event_route(
    payload: LLMFeedbackEventCreate,
    session: SessionDep,
) -> LLMFeedbackEventRead:
    """Persist a redacted per-turn LLM feedback event."""
    llm_session, skill = _validate_feedback_event_links(
        session,
        llm_session_id=payload.llm_session_id,
        skill_id=payload.skill_id,
        feedback_record_id=payload.feedback_record_id,
        evidence_record_id=payload.evidence_record_id,
    )
    if (
        llm_session is not None
        and llm_session.learner_id is not None
        and llm_session.learner_id != payload.learner_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Feedback event learner does not match the linked LLM session learner",
        )
    if skill is not None:
        _validate_skill_consistency(skill, trace_class=payload.trace_class)
    event = LLMFeedbackEvent(
        llm_session_id=payload.llm_session_id,
        learner_id=payload.learner_id,
        skill_id=payload.skill_id,
        feedback_record_id=payload.feedback_record_id,
        evidence_record_id=payload.evidence_record_id,
        event_type=payload.event_type,
        trace_class=payload.trace_class,
        source_reference_ids=list(payload.source_reference_ids),
        unverified=payload.unverified,
        cost_metadata=dict(payload.cost_metadata),
        event_summary=payload.event_summary,
        event_body=_retain_feedback_body(payload.trace_class, payload.event_body),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return _read_feedback_event(event)


@router.get("/feedback-events", response_model=list[LLMFeedbackEventRead])
def list_feedback_events_route(
    session: SessionDep,
    learner_id: str | None = None,
    llm_session_id: str | None = None,
    feedback_record_id: str | None = None,
) -> list[LLMFeedbackEventRead]:
    """List persisted per-turn LLM feedback facts."""
    statement = select(LLMFeedbackEvent).order_by(
        LLMFeedbackEvent.created_at.desc(), LLMFeedbackEvent.id
    )
    if learner_id is not None:
        statement = statement.where(LLMFeedbackEvent.learner_id == learner_id)
    if llm_session_id is not None:
        statement = statement.where(LLMFeedbackEvent.llm_session_id == llm_session_id)
    if feedback_record_id is not None:
        statement = statement.where(LLMFeedbackEvent.feedback_record_id == feedback_record_id)
    return [_read_feedback_event(event) for event in session.scalars(statement).all()]


@router.post("/sessions", response_model=LLMSessionRead)
def create_llm_session_route(payload: LLMSessionCreate, session: SessionDep) -> LLMSessionRead:
    """Create and persist a fake-provider study/practice LLM turn."""
    _, skill = _validate_feedback_event_links(
        session,
        skill_id=payload.skill_id,
        feedback_record_id=payload.feedback_record_id,
        evidence_record_id=payload.evidence_record_id,
    )
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
    if skill is not None:
        _validate_skill_consistency(skill, mode=payload.mode, trace_class=decision.trace_class)
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
    event = LLMFeedbackEvent(
        llm_session=response.session,
        learner_id=payload.learner_id,
        skill_id=payload.skill_id,
        feedback_record_id=payload.feedback_record_id,
        evidence_record_id=payload.evidence_record_id,
        event_type=(
            "source-citation-check"
            if flags
            else (
                "learning-policy-nudge"
                if decision.behavior != "productive-learning-turn"
                else "feedback-outcome"
            )
        ),
        trace_class=decision.trace_class,
        source_reference_ids=list(decision.source_constraints),
        unverified=bool(flags),
        cost_metadata={
            "input_tokens": response.session.input_tokens,
            "output_tokens": response.session.output_tokens,
            "cost_micro_usd": response.session.cost_micro_usd,
            "mode": response.session.mode,
        },
        event_summary=decision.next_action,
        event_body=None,
    )
    session.add(event)
    session.commit()
    session.refresh(response.session)
    session.refresh(event)

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
        feedback_event_id=event.id,
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
    if llm_session.learner_id != payload.actor_id:
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
