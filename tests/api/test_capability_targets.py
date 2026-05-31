"""Tests for capability target API route handlers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.api import (
    archive_capability_target_route,
    create_capability_target_route,
    list_capability_targets_route,
    update_capability_target_route,
)
from lms.capability.repository import create_capability_target
from lms.capability.schemas import CapabilityTargetCreate, CapabilityTargetUpdate
from lms.competencies.repository import create_competency
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal


def _fixtures(db_session: Session) -> dict[str, str]:
    user = User(
        email="api-learner@example.test",
        username="api-learner",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    )
    node = create_knowledge_node(
        db_session,
        title="Explain evidence tradeoffs",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Evidence reasoning",
        knowledge_type="judgment",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    competency = create_competency(
        db_session,
        title="Evidence-backed judgment",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )
    db_session.commit()
    return {
        "learner_id": learner.id,
        "node_id": node.id,
        "goal_id": goal.id,
        "competency_id": competency.id,
    }


def test_create_personal_capability_target_with_nodes_and_competencies(
    db_session: Session,
) -> None:
    """The route helper creates and lists personal capability targets."""
    ids = _fixtures(db_session)

    payload = CapabilityTargetCreate(
        learner_id=ids["learner_id"],
        title="Reach evidence-backed judgment",
        learning_goal_id=ids["goal_id"],
        target_node_ids=[ids["node_id"]],
        target_competency_ids=[ids["competency_id"]],
        required_evidence_types=["rubric-score"],
        confidence_threshold=0.82,
    )
    created = cast(dict[str, Any], create_capability_target_route(payload=payload, session=db_session))

    assert created["ownership_scope"] == "personal"
    assert created["learner_id"] == ids["learner_id"]
    assert created["target_node_ids"] == [ids["node_id"]]
    assert created["target_competency_ids"] == [ids["competency_id"]]

    listed = list_capability_targets_route(session=db_session, learner_id=ids["learner_id"])
    assert [item["id"] for item in listed] == [created["id"]]


def test_capability_target_rejects_institutional_scope_request(db_session: Session) -> None:
    """Institutional target creation is rejected by schema validation."""
    ids = _fixtures(db_session)

    with pytest.raises(ValidationError):
        CapabilityTargetCreate(
            learner_id=ids["learner_id"],
            title="Institutional target",
            ownership_scope="institutional",
            target_node_ids=[ids["node_id"]],
        )


def test_patch_and_archive_capability_target(db_session: Session) -> None:
    """The route helpers update and archive target records."""
    ids = _fixtures(db_session)
    target = create_capability_target(
        db_session,
        learner_id=ids["learner_id"],
        title="Initial target",
        target_node_ids=[ids["node_id"]],
    )
    db_session.commit()

    patch_response = update_capability_target_route(
        target_id=target.id,
        payload=CapabilityTargetUpdate(
            title="Revised target",
            required_evidence_types=["attempt"],
        ),
        session=db_session,
    )
    assert patch_response["title"] == "Revised target"

    archive_response = archive_capability_target_route(target_id=target.id, session=db_session)
    assert archive_response["status"] == "archived"
