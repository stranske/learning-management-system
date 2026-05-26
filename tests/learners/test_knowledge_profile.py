"""Tests for the learner knowledge-profile computed view."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401  # register Base.metadata
import lms.evidence.models  # noqa: F401  # register Base.metadata
import lms.graphs.models  # noqa: F401  # register Base.metadata
import lms.learners.models  # noqa: F401  # register Base.metadata
import lms.sources.models  # noqa: F401  # register Base.metadata
from lms.auth.repository import create_local_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.models import KnowledgeNode
from lms.learners.repository import create_learner_for_user
from lms.main import create_app


@contextmanager
def _client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        session.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_published_node(session: Session, *, title: str, ownership_scope: str) -> KnowledgeNode:
    node = KnowledgeNode(
        title=title,
        knowledge_type="conceptual",
        ownership_scope=ownership_scope,
        status="published",
    )
    session.add(node)
    session.flush()
    return node


def _create_learner(session: Session, *, username: str) -> str:
    user = create_local_user(session, username=username, display_name=username.title())
    learner = create_learner_for_user(session, user_id=user.id, display_name=username.title())
    session.flush()
    return learner.id


def test_knowledge_profile_summarizes_mastery_and_support_dependence() -> None:
    with _client() as (client, session):
        learner_id = _create_learner(session, username="grace")
        node = _create_published_node(
            session,
            title="Recursion fundamentals",
            ownership_scope="personal",
        )
        node_id = node.id
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=node_id,
            normalized_score=0.4,
            support_level="hint",
            hint_used=True,
            demand_level="low",
        )
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=node_id,
            normalized_score=0.6,
            support_level="reference",
            reference_accessed=True,
            demand_level="low",
        )
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=node_id,
            normalized_score=0.85,
            support_level="none",
            demand_level="medium",
        )
        session.commit()

        response = client.get(f"/learners/{learner_id}/knowledge-profile")

    assert response.status_code == 200
    profiles = response.json()
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["learner_id"] == learner_id
    assert profile["ownership_scope"] == "personal"
    assert profile["knowledge_node_id"] == node_id
    assert profile["knowledge_node_title"] == "Recursion fundamentals"
    assert profile["evidence_count"] == 3
    assert profile["last_evidence_id"]
    assert profile["last_evidence_at"]
    assert 0.5 <= profile["current_estimate"] <= 0.9
    assert profile["confidence"] > 0.0
    support = profile["support_dependence"]
    assert support["last_support_level"] == "none"
    assert support["hint_use_count"] == 1
    assert support["reference_access_count"] == 1
    assert support["support_level_counts"]["hint"] == 1
    assert support["support_level_counts"]["reference"] == 1
    assert support["support_level_counts"]["none"] == 1
    assert profile["next_evidence_needed"] in {"stretch", "maintain", "consolidate"}


def test_knowledge_profile_filters_by_ownership_scope() -> None:
    with _client() as (client, session):
        learner_id = _create_learner(session, username="ada")
        personal_node = _create_published_node(
            session,
            title="Personal study unit",
            ownership_scope="personal",
        )
        institutional_node = _create_published_node(
            session,
            title="Org-wide compliance unit",
            ownership_scope="institutional",
        )
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=personal_node.id,
            normalized_score=0.5,
        )
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=institutional_node.id,
            normalized_score=0.9,
        )
        session.commit()

        personal_response = client.get(
            f"/learners/{learner_id}/knowledge-profile",
            params={"ownership_scope": "personal"},
        )
        institutional_response = client.get(
            f"/learners/{learner_id}/knowledge-profile",
            params={"ownership_scope": "institutional"},
        )

    assert personal_response.status_code == 200
    personal_profiles = personal_response.json()
    assert [p["knowledge_node_id"] for p in personal_profiles] == [personal_node.id]
    assert all(p["ownership_scope"] == "personal" for p in personal_profiles)

    assert institutional_response.status_code == 200
    institutional_profiles = institutional_response.json()
    assert [p["knowledge_node_id"] for p in institutional_profiles] == [institutional_node.id]
    assert all(p["ownership_scope"] == "institutional" for p in institutional_profiles)
