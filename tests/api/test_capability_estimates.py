"""Tests for capability estimate API routes."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.api import (
    get_capability_estimate_route,
    list_capability_estimates_route,
    recompute_capability_estimate_route,
)
from lms.capability.repository import create_capability_target
from lms.capability.schemas import CapabilityEstimateRecompute
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user


def test_recompute_capability_estimate_for_personal_target(db_session: Session) -> None:
    """The API recomputes, persists, and reads target-relative estimates."""
    user = User(
        email="estimate-api@example.test",
        username="estimate-api",
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
        title="Explain tradeoffs",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="conceptual",
        normalized_score=0.85,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner.id,
        title="Explain tradeoffs",
        target_node_ids=[node.id],
    )
    db_session.commit()
    payload = cast(
        dict[str, Any],
        recompute_capability_estimate_route(
            payload=CapabilityEstimateRecompute(target_id=target.id),
            session=db_session,
        ),
    )
    assert payload["target_id"] == target.id
    assert payload["learner_id"] == learner.id
    assert payload["current_score"] == 0.85
    assert payload["commentary_redaction_class"] == "learner-facing-inferred-mastery"
    assert "Current evidence suggests" in payload["commentary"]

    list_payload = list_capability_estimates_route(session=db_session, target_id=target.id)
    assert [item["id"] for item in list_payload] == [payload["id"]]

    detail_payload = get_capability_estimate_route(
        estimate_id=str(payload["id"]),
        session=db_session,
    )
    assert detail_payload["id"] == payload["id"]
