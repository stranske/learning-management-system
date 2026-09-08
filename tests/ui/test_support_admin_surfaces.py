"""HTML contract tests for support and admin inspection surfaces."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.repository import record_audit_event
from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.capability.models import CapabilityEstimate, CapabilityTarget, GapAnalysis, MaintenancePlan
from lms.evidence.models import EvidenceRecord
from lms.feedback.models import FeedbackAction
from lms.learners.models import Learner
from lms.scheduling.models import ReviewQueueItem
from lms.settings import Settings, get_settings


def _seed_support_signal(session: Session, learner_id: str, kind: str, *, foreign: bool) -> None:
    created_at = datetime(2021 if foreign else 2020, 1, 1, tzinfo=UTC)
    marker = "Private foreign detail" if foreign else "Own support detail"
    if kind == "feedback":
        session.add(
            FeedbackAction(
                learner_id=learner_id,
                action_type="retry",
                status="open",
                title=marker,
                instructions=marker,
                created_at=created_at,
            )
        )
    elif kind == "evidence":
        session.add(
            EvidenceRecord(
                learner_id=learner_id,
                knowledge_node_id="support-node",
                confidence_rating=2,
                support_level="hint",
                created_at=created_at,
            )
        )
    elif kind == "review":
        session.add(
            ReviewQueueItem(
                learner_id=learner_id,
                knowledge_node_id="support-node",
                reason_code="stale",
                reason_explanation=marker,
                due_at=created_at,
                decision_log={},
                created_at=created_at,
            )
        )
    else:
        target = CapabilityTarget(learner_id=learner_id, title=marker)
        session.add(target)
        session.flush()
        estimate = CapabilityEstimate(
            target_id=target.id,
            learner_id=learner_id,
            estimator_version="test",
            current_score=0.4,
            confidence=0.3,
            validity_scope="test",
            evidence_breakdown={},
            commentary=marker,
            created_at=created_at,
        )
        session.add(estimate)
        session.flush()
        if kind == "maintenance":
            # Keep the estimate itself from creating a signal, so this case
            # independently catches a missing maintenance-plan filter.
            estimate.current_score = estimate.confidence = 0.9
            gap = GapAnalysis(
                target_id=target.id,
                estimate_id=estimate.id,
                learner_id=learner_id,
                severity="low",
            )
            session.add(gap)
            session.flush()
            session.add(
                MaintenancePlan(
                    target_id=target.id,
                    gap_analysis_id=gap.id,
                    learner_id=learner_id,
                    status="active",
                    rationale=marker,
                    plan_steps=[{"title": marker, "status": "blocked"}],
                    created_at=created_at,
                )
            )


@pytest.mark.parametrize("kind", ["feedback", "evidence", "estimate", "maintenance", "review"])
@pytest.mark.parametrize("auth_required", [True, False])
@pytest.mark.parametrize("own_signal", [True, False])
def test_support_dashboard_isolates_deployed_learner_signals(
    api_client: tuple[TestClient, sessionmaker[Session]],
    kind: str,
    auth_required: bool,
    own_signal: bool,
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        owner = User(username="support-owner", display_name="Support owner")
        foreign = User(username="support-foreign", display_name="Foreign account")
        session.add_all([owner, foreign])
        session.flush()
        own_learner = Learner(user_id=owner.id, display_name="Own learner")
        foreign_learner = Learner(user_id=foreign.id, display_name="Private foreign learner")
        session.add_all([own_learner, foreign_learner])
        session.flush()
        if own_signal:
            _seed_support_signal(session, own_learner.id, kind, foreign=False)
        # Newer foreign rows must not crowd the owner's signal out of LIMIT 100.
        for _ in range(101 if auth_required else 1):
            _seed_support_signal(session, foreign_learner.id, kind, foreign=True)
        session.commit()

    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=auth_required)
    client.app.dependency_overrides[require_authenticated_user] = lambda: owner
    for params in ({}, {"learner_id": own_learner.id}):
        response = client.get("/app/support", params=params)
        assert response.status_code == 200
        assert ("Own learner" in response.text) is own_signal
        assert ("Private foreign learner" in response.text) is (not auth_required)
        if auth_required:
            assert foreign_learner.id not in response.text
            assert "Private foreign detail" not in response.text
            assert ("No support signals" in response.text) is (not own_signal)
    if auth_required:
        for learner_id in (foreign_learner.id, "missing-learner"):
            denied = client.get("/app/support", params={"learner_id": learner_id})
            assert denied.status_code in {403, 404}
            assert "Private foreign" not in denied.text


def test_support_dashboard_requires_login_when_deployed(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client
    assert isinstance(client.app, FastAPI)
    client.app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    response = client.get("/app/support", follow_redirects=False)
    assert response.status_code in {303, 401}
    assert "Support signals" not in response.text


_RANKING_OR_LABEL_COPY = (
    "rank #",
    "bottom learner",
    "low ability",
    "high ability",
    "surveillance",
)


def test_support_dashboard_shows_reasoned_support_signals_without_rankings(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        user = User(
            username="mira",
            display_name="Mira Patel",
            email="mira@example.test",
        )
        session.add(user)
        session.flush()
        session.add(
            Learner(
                id="learner-support",
                user_id=user.id,
                display_name="Mira Learner",
                timezone="UTC",
                locale="en-US",
            )
        )
        session.add(
            FeedbackAction(
                learner_id="learner-support",
                action_type="retry",
                status="open",
                title="Retry source-backed retrieval",
                instructions="Offer a low-stakes retrieval prompt with a source reminder.",
            )
        )
        session.add(
            EvidenceRecord(
                learner_id="learner-support",
                knowledge_node_id="node-source-use",
                evidence_kind="observed",
                confidence_rating=2,
                reference_accessed=True,
                hint_used=True,
                support_level="hint",
                normalized_score=0.4,
            )
        )
        session.commit()

    response = client.get("/app/support")

    assert response.status_code == 200
    html = response.text
    assert "<h1>Support</h1>" in html
    assert "Mira Learner" in html
    assert "Open feedback action: Retry source-backed retrieval" in html
    assert "Evidence suggests review context: support=hint, confidence=2" in html
    assert "Support/hint/reference metadata present." in html
    assert "support need is not a ranking" in html
    assert "Offer a low-stakes retrieval prompt with a source reminder." in html
    assert 'href="/app/support" aria-current="page"' in html
    lowered = html.lower()
    for phrase in _RANKING_OR_LABEL_COPY:
        assert phrase not in lowered


@pytest.mark.parametrize("api_client", [True], indirect=True)
def test_admin_dashboard_shows_users_audit_and_health_state(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        session.add(
            User(
                username="admin-alex",
                display_name="Alex Admin",
                email="alex@example.test",
            )
        )
        record_audit_event(
            session,
            actor_id="user:admin-alex",
            action="create",
            entity_type="KnowledgeNode",
            entity_id="node-001",
            source_subsystem="author-ui",
            after_summary={"title": "Spacing"},
        )
        session.commit()

    response = client.get("/app/admin")

    assert response.status_code == 200
    html = response.text
    assert "<h1>Admin</h1>" in html
    assert "Alex Admin" in html
    assert "admin-alex" in html
    assert "Create user API" in html
    assert "create KnowledgeNode" in html
    assert "user:admin-alex" in html
    assert "Health: ok" in html
    assert "Permission labels: personal-scope defaults" in html
    assert "Mapped table count" in html
    assert 'href="/app/admin" aria-current="page"' in html


@pytest.mark.parametrize("api_client", [True], indirect=True)
def test_support_and_admin_dashboards_have_empty_states(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    support = client.get("/app/support")
    admin = client.get("/app/admin")

    assert support.status_code == 200
    assert admin.status_code == 200
    assert "No support signals" in support.text
    assert "No users" in admin.text
    assert "No audit events" in admin.text


def test_admin_dashboard_hides_user_management_without_local_identity(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Admin stays reachable but must not advertise unmounted identity routes.

    With ``enable_local_identity_routes`` disabled (the default), the Users
    section and the create-user link are hidden, while the audit/health state
    remains available.
    """
    client, session_factory = api_client
    with session_factory() as session:
        session.add(
            User(
                username="hidden-hank",
                display_name="Hank Hidden",
                email="hank@example.test",
            )
        )
        session.commit()

    response = client.get("/app/admin")

    assert response.status_code == 200
    html = response.text
    assert "<h1>Admin</h1>" in html
    assert "Create user API" not in html
    assert "Hank Hidden" not in html
    assert "Local identity routes disabled" in html
    assert "Health: ok" in html
    assert "Mapped table count" in html
