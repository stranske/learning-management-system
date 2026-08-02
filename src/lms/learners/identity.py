"""Resolve which learner profile a request acts on.

Every learner-scoped surface used to default to the literal query parameter
``learner_id=learner-1`` with no ownership check, which left a deployed
(``AUTH_REQUIRED=true``) instance with no path from the signed-in user to a
learner profile at all. This module is the single seam that binds learner
identity to the authenticated user:

- When no ``learner_id`` is supplied, the acting learner is the signed-in
  user's own profile, created on first need so the documented
  ``create-user -> login`` flow lands on a usable home.
- When an explicit ``learner_id`` is supplied in deployed mode, it must
  belong to the signed-in user. Local dev / tests (``auth_required=False``)
  keep the historical permissive behavior so existing fixtures that pass
  arbitrary ids keep working.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.auth.login import SessionDep, SettingsDep, require_authenticated_user
from lms.auth.models import User
from lms.learners.repository import get_learner, get_or_create_learner_for_user
from lms.settings import Settings

CurrentUserDep = Annotated[User, Depends(require_authenticated_user)]


def resolve_learner_id(
    session: Session,
    *,
    user: User,
    settings: Settings,
    requested: str | None = None,
) -> str:
    """Return the learner id this request may act on.

    Commits when a learner profile is created on first resolution — the
    request-scoped :func:`lms.db.session.get_session` intentionally leaves
    commits to handlers, and first-visit provisioning must survive the
    request.
    """
    if requested:
        if settings.auth_required:
            learner = get_learner(session, learner_id=requested)
            if learner is None or learner.user_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="That learner profile does not belong to the signed-in user.",
                )
        return requested
    learner, created = get_or_create_learner_for_user(
        session,
        user_id=user.id,
        display_name=user.display_name or user.username,
    )
    if created:
        session.commit()
    return learner.id


def _learner_id_from_query(
    session: SessionDep,
    settings: SettingsDep,
    current_user: CurrentUserDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """FastAPI dependency: resolve the optional ``learner_id`` query param."""
    return resolve_learner_id(session, user=current_user, settings=settings, requested=learner_id)


LearnerIdDep = Annotated[str, Depends(_learner_id_from_query)]

__all__ = ["CurrentUserDep", "LearnerIdDep", "resolve_learner_id"]
