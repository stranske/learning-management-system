"""HTTP routes for prompt authoring and publication."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.prompts.models import Prompt
from lms.prompts.repository import (
    create_prompt,
    get_prompt,
    list_prompts,
    publish_prompt,
    version_prompt,
)
from lms.prompts.schemas import (
    PromptCreate,
    PromptPublish,
    PromptRead,
    PromptStatus,
    PromptVersionCreate,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
def create_prompt_route(payload: PromptCreate, session: SessionDep) -> PromptRead:
    """Create a source-cited prompt and its first version."""
    try:
        prompt = create_prompt(session, **payload.model_dump())
        session.commit()
        session.refresh(prompt)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return PromptRead.model_validate_prompt(prompt)


@router.get("", response_model=list[PromptRead])
def list_prompts_route(
    session: SessionDep,
    prompt_status: Annotated[
        PromptStatus | None,
        Query(alias="status", description="Optional prompt publication status filter."),
    ] = None,
    learning_goal_id: Annotated[
        str | None,
        Query(min_length=1, max_length=36, description="Optional learning goal filter."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PromptRead]:
    """Return prompts with optional status and learning-goal filters."""
    try:
        prompts = list_prompts(
            session,
            status=prompt_status,
            learning_goal_id=learning_goal_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return [PromptRead.model_validate_prompt(prompt) for prompt in prompts]


@router.get("/{prompt_id}", response_model=PromptRead)
def get_prompt_route(prompt_id: str, session: SessionDep) -> PromptRead:
    """Return a prompt by id."""
    prompt = _load_prompt_or_404(session, prompt_id)
    return PromptRead.model_validate_prompt(prompt)


@router.post("/{prompt_id}/versions", response_model=PromptRead)
def version_prompt_route(
    prompt_id: str,
    payload: PromptVersionCreate,
    session: SessionDep,
) -> PromptRead:
    """Append a new prompt wording version."""
    prompt = _load_prompt_or_404(session, prompt_id)
    try:
        updated = version_prompt(
            session,
            prompt,
            **payload.model_dump(exclude_none=True),
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return PromptRead.model_validate_prompt(updated)


@router.post("/{prompt_id}/publish", response_model=PromptRead)
def publish_prompt_route(
    prompt_id: str,
    payload: PromptPublish,
    session: SessionDep,
) -> PromptRead:
    """Publish a prompt after human review."""
    prompt = _load_prompt_or_404(session, prompt_id)
    try:
        published = publish_prompt(session, prompt, **payload.model_dump())
        session.commit()
        session.refresh(published)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return PromptRead.model_validate_prompt(published)


def _load_prompt_or_404(session: Session, prompt_id: str) -> Prompt:
    prompt = get_prompt(session, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found.")
    return prompt
