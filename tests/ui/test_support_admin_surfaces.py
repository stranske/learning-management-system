"""HTML contract tests for support and admin inspection surfaces."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.repository import record_audit_event
from lms.auth.models import User
from lms.evidence.models import EvidenceRecord
from lms.feedback.models import FeedbackAction
from lms.learners.models import Learner

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
