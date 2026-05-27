"""HTTP routes for durable feedback records and next actions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.repository import (
    archive_feedback_template,
    archive_rubric,
    create_feedback_action,
    create_feedback_record,
    create_feedback_template,
    create_misconception_pattern,
    create_rubric,
    create_rubric_criterion,
    get_feedback_action,
    get_feedback_record,
    get_feedback_template,
    get_rubric,
    get_rubric_criterion,
    get_rubric_score,
    list_feedback_actions,
    list_feedback_records,
    list_feedback_templates,
    list_misconception_patterns,
    list_rubric_criteria,
    list_rubric_scores,
    list_rubrics,
    render_feedback_template,
    update_rubric,
    update_rubric_criterion,
)
from lms.feedback.schemas import (
    FeedbackActionCreate,
    FeedbackActionRead,
    FeedbackRecordCreate,
    FeedbackRecordRead,
    FeedbackTemplateCreate,
    FeedbackTemplateRead,
    FeedbackTemplateRenderRead,
    FeedbackTemplateRenderRequest,
    MisconceptionPatternCreate,
    MisconceptionPatternRead,
    OwnershipScope,
    RubricCreate,
    RubricCriterionCreate,
    RubricCriterionRead,
    RubricCriterionRootCreate,
    RubricCriterionStatus,
    RubricCriterionUpdate,
    RubricRead,
    RubricScoreCreate,
    RubricScoreRead,
    RubricStatus,
    RubricUpdate,
)
from lms.feedback.scoring import RubricScoringError, score_attempt_with_rubric

router = APIRouter(tags=["feedback"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/feedback", response_model=FeedbackRecordRead, status_code=status.HTTP_201_CREATED)
def create_feedback_route(payload: FeedbackRecordCreate, session: SessionDep) -> FeedbackRecordRead:
    """Create a durable feedback record."""
    data = payload.model_dump()
    if data.get("attempt_id") is not None and session.get(Attempt, data["attempt_id"]) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referenced attempt not found.",
        )
    if (
        data.get("evidence_record_id") is not None
        and session.get(EvidenceRecord, data["evidence_record_id"]) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referenced evidence record not found.",
        )
    record = create_feedback_record(session, **data)
    session.commit()
    session.refresh(record)
    return FeedbackRecordRead.model_validate(record)


@router.get("/feedback", response_model=list[FeedbackRecordRead])
def list_feedback_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    feedback_level: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FeedbackRecordRead]:
    """Return feedback records with learner, attempt, prompt, and level filters."""
    records = list_feedback_records(
        session,
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        feedback_level=feedback_level,
        limit=limit,
    )
    return [FeedbackRecordRead.model_validate(record) for record in records]


@router.get("/feedback/{feedback_record_id}", response_model=FeedbackRecordRead)
def get_feedback_route(feedback_record_id: str, session: SessionDep) -> FeedbackRecordRead:
    """Return one feedback record."""
    record = get_feedback_record(session, feedback_record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    return FeedbackRecordRead.model_validate(record)


@router.post(
    "/feedback-actions",
    response_model=FeedbackActionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback_action_route(
    payload: FeedbackActionCreate, session: SessionDep
) -> FeedbackActionRead:
    """Create a feedback next action."""
    data = payload.model_dump()
    parent_record = None
    if data.get("feedback_record_id") is not None:
        parent_record = get_feedback_record(session, data["feedback_record_id"])
        if parent_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced feedback record not found.",
            )
    action = create_feedback_action(session, **data)
    if parent_record is not None:
        parent_record.next_action_ids = [*(parent_record.next_action_ids or []), action.id]
        session.flush()
    session.commit()
    session.refresh(action)
    return FeedbackActionRead.model_validate(action)


@router.get("/feedback-actions", response_model=list[FeedbackActionRead])
def list_feedback_actions_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    feedback_record_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    action_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    status: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FeedbackActionRead]:
    """Return feedback actions with learner-loop filters."""
    actions = list_feedback_actions(
        session,
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        feedback_record_id=feedback_record_id,
        action_type=action_type,
        status=status,
        limit=limit,
    )
    return [FeedbackActionRead.model_validate(action) for action in actions]


@router.get("/feedback-actions/{feedback_action_id}", response_model=FeedbackActionRead)
def get_feedback_action_route(feedback_action_id: str, session: SessionDep) -> FeedbackActionRead:
    """Return one feedback action."""
    action = get_feedback_action(session, feedback_action_id)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback action not found."
        )
    return FeedbackActionRead.model_validate(action)


@router.post(
    "/feedback/misconceptions",
    response_model=MisconceptionPatternRead,
    status_code=status.HTTP_201_CREATED,
)
def create_misconception_pattern_route(
    payload: MisconceptionPatternCreate,
    session: SessionDep,
) -> MisconceptionPatternRead:
    """Create a deterministic misconception pattern."""
    try:
        pattern = create_misconception_pattern(session, **payload.model_dump())
        session.commit()
        session.refresh(pattern)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return MisconceptionPatternRead.model_validate(pattern)


@router.get("/feedback/misconceptions", response_model=list[MisconceptionPatternRead])
def list_misconception_patterns_route(
    session: SessionDep,
    ownership_scope: Annotated[OwnershipScope | None, Query()] = None,
    target_knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    signature_text: Annotated[str | None, Query(min_length=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[MisconceptionPatternRead]:
    """Return misconception patterns with optional deterministic signature matching."""
    patterns = list_misconception_patterns(
        session,
        ownership_scope=ownership_scope,
        target_knowledge_node_id=target_knowledge_node_id,
        signature_text=signature_text,
        limit=limit,
    )
    return [MisconceptionPatternRead.model_validate(pattern) for pattern in patterns]


@router.post(
    "/feedback-templates",
    response_model=FeedbackTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback_template_route(
    payload: FeedbackTemplateCreate,
    session: SessionDep,
) -> FeedbackTemplateRead:
    """Create reusable deterministic feedback language."""
    try:
        template = create_feedback_template(session, **payload.model_dump())
        session.commit()
        session.refresh(template)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return FeedbackTemplateRead.model_validate(template)


@router.get("/feedback-templates", response_model=list[FeedbackTemplateRead])
def list_feedback_templates_route(
    session: SessionDep,
    ownership_scope: Annotated[OwnershipScope | None, Query()] = None,
    feedback_level: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    action_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    template_status: Annotated[
        str | None, Query(alias="status", min_length=1, max_length=32)
    ] = None,
    knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FeedbackTemplateRead]:
    """Return feedback templates with common authoring filters."""
    templates = list_feedback_templates(
        session,
        ownership_scope=ownership_scope,
        feedback_level=feedback_level,
        action_type=action_type,
        status=template_status,
        knowledge_node_id=knowledge_node_id,
        limit=limit,
    )
    return [FeedbackTemplateRead.model_validate(template) for template in templates]


@router.get("/feedback-templates/{template_id}", response_model=FeedbackTemplateRead)
def get_feedback_template_route(template_id: str, session: SessionDep) -> FeedbackTemplateRead:
    """Return one feedback template."""
    template = get_feedback_template(session, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback template not found."
        )
    return FeedbackTemplateRead.model_validate(template)


@router.post(
    "/feedback-templates/{template_id}/render",
    response_model=FeedbackTemplateRenderRead,
)
def render_feedback_template_route(
    template_id: str,
    payload: FeedbackTemplateRenderRequest,
    session: SessionDep,
) -> FeedbackTemplateRenderRead:
    """Render a feedback template with deterministic placeholder validation."""
    template = get_feedback_template(session, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback template not found."
        )
    try:
        rendered = render_feedback_template(template, payload.values)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return FeedbackTemplateRenderRead(
        template_id=template.id,
        rendered_body=rendered,
        values=payload.values,
    )


@router.post("/feedback-templates/{template_id}/archive", response_model=FeedbackTemplateRead)
def archive_feedback_template_route(
    template_id: str,
    session: SessionDep,
) -> FeedbackTemplateRead:
    """Archive reusable feedback language no longer used for authoring."""
    template = get_feedback_template(session, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback template not found."
        )
    archived = archive_feedback_template(session, template)
    session.commit()
    session.refresh(archived)
    return FeedbackTemplateRead.model_validate(archived)


@router.post(
    "/rubric-scores",
    response_model=RubricScoreRead,
    status_code=status.HTTP_201_CREATED,
)
def create_rubric_score_route(
    payload: RubricScoreCreate,
    session: SessionDep,
) -> RubricScoreRead:
    """Score an attempt against a rubric and preserve partial-credit evidence."""
    data = payload.model_dump()
    try:
        score = score_attempt_with_rubric(session, **data)
        session.commit()
        session.refresh(score)
    except RubricScoringError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    return RubricScoreRead.model_validate(score)


@router.get("/rubric-scores", response_model=list[RubricScoreRead])
def list_rubric_scores_route(
    session: SessionDep,
    rubric_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RubricScoreRead]:
    """Return rubric scores by rubric, attempt, or learner."""
    scores = list_rubric_scores(
        session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        learner_id=learner_id,
        limit=limit,
    )
    return [RubricScoreRead.model_validate(score) for score in scores]


@router.get("/rubric-scores/{rubric_score_id}", response_model=RubricScoreRead)
def get_rubric_score_route(rubric_score_id: str, session: SessionDep) -> RubricScoreRead:
    """Return one rubric score."""
    score = get_rubric_score(session, rubric_score_id)
    if score is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric score not found.")
    return RubricScoreRead.model_validate(score)


@router.post("/rubrics", response_model=RubricRead, status_code=status.HTTP_201_CREATED)
def create_rubric_route(payload: RubricCreate, session: SessionDep) -> RubricRead:
    """Create a rubric with optional nested criteria."""
    data = payload.model_dump()
    criteria = data.pop("criteria")
    try:
        rubric = create_rubric(session, **data, criteria=criteria)
        session.commit()
        session.refresh(rubric)
        rubric = get_rubric(session, rubric.id) or rubric
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RubricRead.model_validate(rubric)


@router.get("/rubrics", response_model=list[RubricRead])
def list_rubrics_route(
    session: SessionDep,
    ownership_scope: Annotated[OwnershipScope | None, Query()] = None,
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    rubric_status: Annotated[RubricStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RubricRead]:
    """Return rubrics with authoring filters."""
    rubrics = list_rubrics(
        session,
        ownership_scope=ownership_scope,
        prompt_id=prompt_id,
        knowledge_node_id=knowledge_node_id,
        status=rubric_status,
        limit=limit,
    )
    return [RubricRead.model_validate(rubric) for rubric in rubrics]


@router.get("/rubrics/{rubric_id}", response_model=RubricRead)
def get_rubric_route(rubric_id: str, session: SessionDep) -> RubricRead:
    """Return one rubric with criteria ordered by criterion_order."""
    rubric = get_rubric(session, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found.")
    return RubricRead.model_validate(rubric)


@router.patch("/rubrics/{rubric_id}", response_model=RubricRead)
def update_rubric_route(
    rubric_id: str,
    payload: RubricUpdate,
    session: SessionDep,
) -> RubricRead:
    """Update mutable rubric metadata."""
    rubric = get_rubric(session, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found.")
    try:
        updated = update_rubric(session, rubric, **payload.model_dump(exclude_unset=True))
        session.commit()
        session.refresh(updated)
        updated = get_rubric(session, updated.id) or updated
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RubricRead.model_validate(updated)


@router.post("/rubrics/{rubric_id}/archive", response_model=RubricRead)
def archive_rubric_route(rubric_id: str, session: SessionDep) -> RubricRead:
    """Archive a rubric and its criteria."""
    rubric = get_rubric(session, rubric_id)
    if rubric is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rubric not found.")
    archived = archive_rubric(session, rubric)
    session.commit()
    session.refresh(archived)
    archived = get_rubric(session, archived.id) or archived
    return RubricRead.model_validate(archived)


@router.post(
    "/rubrics/{rubric_id}/criteria",
    response_model=RubricCriterionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_rubric_criterion_route(
    rubric_id: str,
    payload: RubricCriterionCreate,
    session: SessionDep,
) -> RubricCriterionRead:
    """Create one criterion under a rubric."""
    try:
        criterion = create_rubric_criterion(
            session,
            rubric_id=rubric_id,
            **payload.model_dump(),
        )
        session.commit()
        session.refresh(criterion)
    except ValueError as exc:
        session.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "referenced rubric was not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return RubricCriterionRead.model_validate(criterion)


@router.post(
    "/rubric-criteria",
    response_model=RubricCriterionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_rubric_criterion_root_route(
    payload: RubricCriterionRootCreate,
    session: SessionDep,
) -> RubricCriterionRead:
    """Create one criterion through the top-level rubric-criteria route."""
    data = payload.model_dump()
    rubric_id = data.pop("rubric_id")
    try:
        criterion = create_rubric_criterion(session, rubric_id=rubric_id, **data)
        session.commit()
        session.refresh(criterion)
    except ValueError as exc:
        session.rollback()
        status_code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "referenced rubric was not found"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return RubricCriterionRead.model_validate(criterion)


@router.get("/rubric-criteria", response_model=list[RubricCriterionRead])
def list_rubric_criteria_route(
    session: SessionDep,
    rubric_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    criterion_status: Annotated[RubricCriterionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RubricCriterionRead]:
    """Return rubric criteria with deterministic rubric/order sorting."""
    criteria = list_rubric_criteria(
        session,
        rubric_id=rubric_id,
        status=criterion_status,
        limit=limit,
    )
    return [RubricCriterionRead.model_validate(criterion) for criterion in criteria]


@router.patch(
    "/rubrics/{rubric_id}/criteria/{criterion_id}",
    response_model=RubricCriterionRead,
)
def update_rubric_criterion_route(
    rubric_id: str,
    criterion_id: str,
    payload: RubricCriterionUpdate,
    session: SessionDep,
) -> RubricCriterionRead:
    """Update one criterion under a rubric."""
    criterion = get_rubric_criterion(session, rubric_id, criterion_id)
    if criterion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rubric criterion not found."
        )
    try:
        updated = update_rubric_criterion(
            session,
            criterion,
            **payload.model_dump(exclude_unset=True),
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RubricCriterionRead.model_validate(updated)
