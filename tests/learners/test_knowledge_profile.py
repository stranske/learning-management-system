"""Tests for learner knowledge profiles."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.auth.repository import create_local_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, knowledge_profile_for_learner
from lms.main import create_app


def test_knowledge_profile_summarizes_mastery_and_support_dependence(
    db_session: Session,
) -> None:
    """A profile row combines mastery estimate, evidence volume, and support markers."""
    user = create_local_user(db_session, username="ada", display_name="Ada Lovelace")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Ada")
    node = create_knowledge_node(
        db_session,
        title="Retrieval practice",
        knowledge_type="procedural",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    first = create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="procedural",
        correctness=True,
        hint_used=True,
        support_level="hint",
    )
    second = create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="procedural",
        normalized_score=1.0,
        reference_accessed=True,
        support_level="reference",
    )
    db_session.commit()

    profile = knowledge_profile_for_learner(
        db_session,
        learner_id=learner.id,
        ownership_scope="personal",
    )
    items = cast(list[dict[str, Any]], profile["items"])

    assert profile["learner_id"] == learner.id
    assert profile["ownership_scope"] == "personal"
    assert items == [
        {
            "learner_id": learner.id,
            "ownership_scope": "personal",
            "knowledge_node_id": node.id,
            "knowledge_node_title": "Retrieval practice",
            "knowledge_type": "procedural",
            "current_estimate": 1.0,
            "confidence": 0.59,
            "evidence_count": 2,
            "last_evidence_id": second.id,
            "support_dependence_markers": [
                "hint_used",
                "reference_accessed",
                "support_level:hint",
                "support_level:reference",
            ],
            "has_transfer_evidence": False,
            "next_evidence_needed": "independent transfer evidence",
            "generated_at": items[0]["generated_at"],
        }
    ]
    assert first.id != second.id


def test_knowledge_profile_marks_transfer_case_evidence(db_session: Session) -> None:
    """Transfer-case evidence satisfies the profile's transfer-evidence signal."""
    user = create_local_user(db_session, username="mary", display_name="Mary Somerville")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Mary")
    node = create_knowledge_node(
        db_session,
        title="Apply retrieval in a new case",
        knowledge_type="judgment",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="judgment",
        normalized_score=0.9,
        support_level="none",
        transfer_distance="near",
        validity_scope="transfer-case:case-1",
    )
    db_session.commit()

    profile = knowledge_profile_for_learner(
        db_session,
        learner_id=learner.id,
        ownership_scope="personal",
    )
    items = cast(list[dict[str, Any]], profile["items"])

    assert len(items) == 1
    assert items[0]["knowledge_node_id"] == node.id
    assert items[0]["has_transfer_evidence"] is True
    assert items[0]["next_evidence_needed"] == "more evidence to raise confidence"


def test_knowledge_profile_filters_by_ownership_scope(db_session: Session) -> None:
    """Knowledge profiles do not leak institutional nodes into personal scope."""
    user = create_local_user(db_session, username="grace", display_name="Grace Hopper")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Grace")
    personal_node = create_knowledge_node(
        db_session,
        title="Personal concept",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional concept",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=personal_node.id,
        knowledge_type="conceptual",
        normalized_score=0.8,
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=institutional_node.id,
        knowledge_type="conceptual",
        normalized_score=0.9,
    )
    db_session.commit()

    personal_profile = knowledge_profile_for_learner(
        db_session,
        learner_id=learner.id,
        ownership_scope="personal",
    )
    institutional_profile = knowledge_profile_for_learner(
        db_session,
        learner_id=learner.id,
        ownership_scope="institutional",
    )
    personal_items = cast(list[dict[str, Any]], personal_profile["items"])
    institutional_items = cast(list[dict[str, Any]], institutional_profile["items"])

    assert [item["knowledge_node_id"] for item in personal_items] == [personal_node.id]
    assert [item["knowledge_node_id"] for item in institutional_items] == [institutional_node.id]


def test_knowledge_profile_route_filters_personal_scope_by_default() -> None:
    """The HTTP route defaults to personal scope and excludes institutional nodes."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    setup_session = session_factory()
    user = create_local_user(setup_session, username="maria", display_name="Maria Mitchell")
    learner = create_learner_for_user(setup_session, user_id=user.id, display_name="Maria")
    personal_node = create_knowledge_node(
        setup_session,
        title="Personal node",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    institutional_node = create_knowledge_node(
        setup_session,
        title="Institutional node",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        setup_session,
        learner_id=learner.id,
        knowledge_node_id=personal_node.id,
        knowledge_type="conceptual",
        normalized_score=0.75,
    )
    create_evidence_record(
        setup_session,
        learner_id=learner.id,
        knowledge_node_id=institutional_node.id,
        knowledge_type="conceptual",
        normalized_score=0.95,
    )
    learner_id = learner.id
    personal_node_id = personal_node.id
    institutional_node_id = institutional_node.id
    setup_session.commit()
    setup_session.close()

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.get(f"/learners/{learner_id}/knowledge-profile")
        scoped_response = client.get(
            f"/learners/{learner_id}/knowledge-profile?ownership_scope=institutional"
        )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["ownership_scope"] == "personal"
    assert [item["knowledge_node_id"] for item in response.json()["items"]] == [personal_node_id]
    assert scoped_response.status_code == 200
    assert [item["knowledge_node_id"] for item in scoped_response.json()["items"]] == [
        institutional_node_id
    ]
