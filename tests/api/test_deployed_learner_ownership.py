"""Regression coverage for deployed learner-resource ownership boundaries."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import suppress
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.auth.passwords import hash_password
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.models import FeedbackRecord
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner, LearnerReflection, LearningGoal
from lms.main import create_app
from lms.settings import Settings, get_settings


def _deployed_client(
    *, auth_required: bool = True
) -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    owner = User(username="owner", display_name="Owner", is_local=False)
    other_user = User(username="other", display_name="Other", is_local=False)
    session.add_all([owner, other_user])
    session.flush()
    owner_learner = Learner(user_id=owner.id, display_name="Owner learner")
    other_learner = Learner(user_id=other_user.id, display_name="Other learner")
    session.add_all([owner_learner, other_learner])
    session.flush()
    foreign_attempt = Attempt(
        learner_id=other_learner.id,
        prompt_id="foreign-prompt",
        response_text="private response text",
        feedback={
            "goal": "Foreign private goal",
            "observed_evidence": "Foreign private evidence",
            "next_action": "Keep private",
        },
    )
    owner_attempt = Attempt(
        learner_id=owner_learner.id,
        prompt_id="owner-prompt",
        response_text="owner response text",
        feedback={
            "goal": "Owner goal",
            "observed_evidence": "Owner evidence",
            "next_action": "Keep learning",
        },
    )
    owner_feedback = FeedbackRecord(
        learner_id=owner_learner.id,
        feedback_level="coaching",
        goal="Owner goal",
        observed_evidence="Owner evidence",
        source_feedback={},
    )
    foreign_feedback = FeedbackRecord(
        learner_id=other_learner.id,
        feedback_level="coaching",
        goal="Foreign goal",
        observed_evidence="Foreign evidence",
        source_feedback={},
    )
    foreign_evidence = EvidenceRecord(
        learner_id=other_learner.id,
        knowledge_node_id="private-node",
        validity_scope="private evidence scope",
    )
    session.add_all(
        [
            foreign_attempt,
            owner_attempt,
            owner_feedback,
            foreign_feedback,
            foreign_evidence,
        ]
    )
    session.commit()

    def override_session() -> Generator[Session, None, None]:
        yield session

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(auth_required=auth_required)
    app.dependency_overrides[require_authenticated_user] = lambda: owner
    try:
        with TestClient(app) as client:
            client.owner_learner_id = owner_learner.id  # type: ignore[attr-defined]
            client.other_learner_id = other_learner.id  # type: ignore[attr-defined]
            client.foreign_attempt_id = foreign_attempt.id  # type: ignore[attr-defined]
            client.owner_attempt_id = owner_attempt.id  # type: ignore[attr-defined]
            client.foreign_evidence_id = foreign_evidence.id  # type: ignore[attr-defined]
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_authenticated_user_cannot_fetch_another_learners_attempt() -> None:
    """Foreign object IDs must not reveal a response body in deployed mode."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        foreign = client.get(f"/attempts/{client.foreign_attempt_id}")  # type: ignore[attr-defined]
        missing = client.get("/attempts/not-a-real-attempt")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() == {"detail": "Attempt not found."}
        assert "private response text" not in foreign.text
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_can_fetch_own_attempt() -> None:
    """Deployed ownership checks preserve legitimate learner access."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        response = client.get(f"/attempts/{client.owner_attempt_id}")  # type: ignore[attr-defined]
        assert response.status_code == 200
        assert response.json()["response_text"] == "owner response text"
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_probe_another_learners_evidence() -> None:
    """Foreign and nonexistent evidence ids have the same deployed response."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        foreign = client.get(  # type: ignore[attr-defined]
            f"/evidence-records/{client.foreign_evidence_id}"
        )
        missing = client.get("/evidence-records/not-a-real-evidence-record")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() == {"detail": "Evidence record not found."}
        assert "private evidence scope" not in foreign.text
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_list_another_learners_feedback() -> None:
    """A foreign learner filter cannot disclose another learner's feedback."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        foreign = client.get(f"/feedback?learner_id={client.other_learner_id}")  # type: ignore[attr-defined]
        assert foreign.status_code in {403, 404}
        own = client.get(f"/feedback?learner_id={client.owner_learner_id}")  # type: ignore[attr-defined]
        assert own.status_code == 200
        assert [record["goal"] for record in own.json()] == ["Owner goal"]
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_create_feedback_rejects_cross_learner_attempt_reference() -> None:
    """A user who owns multiple learners cannot cross-link attempt references."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    owner = User(username="owner", display_name="Owner", is_local=False)
    session.add(owner)
    session.flush()
    first_learner = Learner(user_id=owner.id, display_name="First learner")
    second_learner = Learner(user_id=owner.id, display_name="Second learner")
    session.add_all([first_learner, second_learner])
    session.flush()
    second_attempt = Attempt(
        learner_id=second_learner.id,
        prompt_id="second-prompt",
        response_text="second learner response",
        feedback={
            "goal": "Second goal",
            "observed_evidence": "Second evidence",
            "next_action": "Continue",
        },
    )
    session.add(second_attempt)
    session.commit()

    def override_session() -> Generator[Session, None, None]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    app.dependency_overrides[require_authenticated_user] = lambda: owner
    try:
        with TestClient(app) as client:
            response = client.post(
                "/feedback",
                json={
                    "learner_id": first_learner.id,
                    "attempt_id": second_attempt.id,
                    "goal": "First goal",
                    "observed_evidence": "First evidence",
                },
            )
            assert response.status_code == 422
            assert response.json()["detail"] == "Referenced attempt belongs to a different learner."
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_authenticated_user_cannot_read_another_learners_mastery_estimates() -> None:
    """Mastery reads hide foreign evidence and preserve the owner's estimates."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        owner_learner_id = client.owner_learner_id  # type: ignore[attr-defined]
        other_learner_id = client.other_learner_id  # type: ignore[attr-defined]
        session.add_all(
            [
                EvidenceRecord(
                    learner_id=owner_learner_id,
                    knowledge_node_id="owner-mastery-node",
                    normalized_score=0.7,
                ),
                EvidenceRecord(
                    learner_id=other_learner_id,
                    knowledge_node_id="foreign-mastery-node",
                    normalized_score=0.9,
                ),
            ]
        )
        session.commit()

        foreign = client.get(f"/learners/{other_learner_id}/mastery-estimates")
        missing = client.get("/learners/not-a-real-learner/mastery-estimates")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() == {"detail": "Learner resource not found."}
        assert "foreign-mastery-node" not in foreign.text

        own = client.get(f"/learners/{owner_learner_id}/mastery-estimates")
        assert own.status_code == 200
        [estimate] = own.json()
        assert estimate["learner_id"] == owner_learner_id
        assert estimate["knowledge_node_id"] == "owner-mastery-node"
        assert estimate["evidence_count"] == 1
        assert estimate["current_estimate"] == 0.7
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_read_another_learners_inspect_overview() -> None:
    """Inspect rejects foreign IDs while retaining the owner's actual evidence."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        owner_id = client.owner_learner_id  # type: ignore[attr-defined]
        foreign_id = client.other_learner_id  # type: ignore[attr-defined]
        record = EvidenceRecord(
            learner_id=owner_id,
            knowledge_node_id="owner-inspect-node",
            normalized_score=0.7,
        )
        session.add(record)
        session.commit()

        for scope in ("personal", "institutional"):
            params = {"ownership_scope": scope}
            foreign = client.get(f"/inspect/learners/{foreign_id}/overview", params=params)
            missing = client.get("/inspect/learners/not-a-real-learner/overview", params=params)
            assert foreign.status_code == missing.status_code == 404
            assert foreign.json() == missing.json() == {"detail": "Learner resource not found."}
            assert "private-node" not in foreign.text

            own = client.get(f"/inspect/learners/{owner_id}/overview", params=params)
            assert own.status_code == 200
            assert own.json()["learner_id"] == owner_id
            assert own.json()["ownership_scope"] == scope
            [evidence] = own.json()["recent_evidence"]
            assert evidence["id"] == record.id
            assert evidence["knowledge_node_id"] == "owner-inspect-node"
            assert evidence["normalized_score"] == 0.7
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_read_another_learners_inspect_calibration() -> None:
    """Calibration authorizes the learner before aggregating or filtering evidence."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        owner_id = client.owner_learner_id  # type: ignore[attr-defined]
        foreign_id = client.other_learner_id  # type: ignore[attr-defined]
        session.add_all(
            [
                EvidenceRecord(
                    learner_id=owner_id,
                    knowledge_node_id="owner-calibration-node",
                    normalized_score=0.7,
                    confidence_rating=4,
                ),
                EvidenceRecord(
                    learner_id=foreign_id,
                    knowledge_node_id="foreign-calibration-node",
                    normalized_score=0.1,
                    confidence_rating=5,
                ),
            ]
        )
        session.commit()

        for params in ({}, {"knowledge_node_id": "owner-calibration-node"}):
            foreign = client.get(f"/inspect/learners/{foreign_id}/calibration", params=params)
            missing = client.get("/inspect/learners/not-a-real-learner/calibration", params=params)
            assert foreign.status_code == missing.status_code == 404
            assert foreign.json() == missing.json() == {"detail": "Learner resource not found."}

            own = client.get(f"/inspect/learners/{owner_id}/calibration", params=params)
            assert own.status_code == 200
            payload = own.json()
            assert payload["learner_id"] == owner_id
            assert payload["knowledge_node_id"] == params.get("knowledge_node_id")
            assert payload["sample_size"] == 1
            assert payload["overconfident"] is False
            [bucket] = payload["buckets"]
            assert bucket["confidence_rating"] == 4
            assert bucket["count"] == 1
            assert bucket["observed_accuracy"] == 0.7
    finally:
        with suppress(StopIteration):
            next(fixture)


def _rubric_payload(session: Session, attempt_id: str) -> dict[str, Any]:
    """Build a usable rubric so ownership tests exercise real grading data."""
    from lms.feedback.repository import create_rubric
    from lms.graphs.repository import create_knowledge_node

    node = create_knowledge_node(
        session,
        title="Ownership grading",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:owner",
        status="published",
    )
    rubric = create_rubric(
        session,
        title="Ownership rubric",
        ownership_scope="personal",
        authoring_actor="user:owner",
        knowledge_node_id=node.id,
        criteria=[{"criterion_order": 1, "description": "Uses evidence", "max_points": 2}],
    )
    session.commit()
    return {
        "rubric_id": rubric.id,
        "attempt_id": attempt_id,
        "scorer_type": "human",
        "criterion_scores": [{"criterion_id": rubric.criteria[0].id, "points": 1}],
    }


def _seed_rubric_score(session: Session, attempt_id: str) -> str:
    """Persist a real score outside HTTP to seed either user's private data."""
    from lms.feedback.scoring import score_attempt_with_rubric

    payload = _rubric_payload(session, attempt_id)
    score = score_attempt_with_rubric(session, **payload)
    session.commit()
    return score.id


def test_authenticated_user_cannot_list_another_learners_rubric_scores() -> None:
    """Every list shape protects foreign scores while retaining actual owned rows."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        foreign_id = _seed_rubric_score(session, client.foreign_attempt_id)  # type: ignore[attr-defined]
        own_id = _seed_rubric_score(session, client.owner_attempt_id)  # type: ignore[attr-defined]
        foreign = client.get(
            "/rubric-scores", params={"attempt_id": client.foreign_attempt_id}  # type: ignore[attr-defined]
        )
        missing = client.get("/rubric-scores", params={"attempt_id": "missing-attempt"})
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        foreign_learner = client.get(
            "/rubric-scores", params={"learner_id": client.other_learner_id}  # type: ignore[attr-defined]
        )
        assert foreign_learner.status_code in {403, 404}
        mixed_filter = client.get(
            "/rubric-scores",
            params={
                "attempt_id": client.owner_attempt_id,  # type: ignore[attr-defined]
                "learner_id": client.other_learner_id,  # type: ignore[attr-defined]
            },
        )
        assert mixed_filter.status_code in {403, 404}
        from lms.feedback.models import RubricScore

        foreign_score = session.get(RubricScore, foreign_id)
        assert foreign_score is not None
        for params in (
            {},
            {"learner_id": client.owner_learner_id},  # type: ignore[attr-defined]
            {"attempt_id": client.owner_attempt_id},  # type: ignore[attr-defined]
            {
                "attempt_id": client.owner_attempt_id,  # type: ignore[attr-defined]
                "learner_id": client.owner_learner_id,  # type: ignore[attr-defined]
            },
            {"limit": 1},
        ):
            own = client.get("/rubric-scores", params=params)
            assert own.status_code == 200
            assert [score["id"] for score in own.json()] == [own_id]
        rubric_only = client.get("/rubric-scores", params={"rubric_id": foreign_score.rubric_id})
        assert rubric_only.status_code == 200
        assert rubric_only.json() == []
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_post_rubric_score_for_foreign_attempt() -> None:
    """Reject foreign grading before any score, evidence, or feedback write."""
    from lms.feedback.models import RubricScore

    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        payload = _rubric_payload(session, client.foreign_attempt_id)  # type: ignore[attr-defined]
        models = (RubricScore, EvidenceRecord, FeedbackRecord)
        counts = [session.query(model).count() for model in models]
        foreign = client.post("/rubric-scores", json=payload)
        missing = client.post("/rubric-scores", json={**payload, "attempt_id": "missing-attempt"})
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert [session.query(model).count() for model in models] == counts
        own = client.post(
            "/rubric-scores",
            json={**payload, "attempt_id": client.owner_attempt_id},  # type: ignore[attr-defined]
        )
        assert own.status_code == 201, own.text
        assert own.json()["learner_id"] == client.owner_learner_id  # type: ignore[attr-defined]
        assert own.json()["normalized_score"] == 0.5
        assert own.json()["evidence_record_id"]
        assert own.json()["feedback_record_id"]
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_get_another_learners_rubric_score() -> None:
    """Foreign score IDs match missing IDs; owned direct reads still return grades."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        foreign_id = _seed_rubric_score(session, client.foreign_attempt_id)  # type: ignore[attr-defined]
        own_id = _seed_rubric_score(session, client.owner_attempt_id)  # type: ignore[attr-defined]
        foreign = client.get(f"/rubric-scores/{foreign_id}")
        missing = client.get("/rubric-scores/missing-score")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        own = client.get(f"/rubric-scores/{own_id}")
        assert own.status_code == 200
        assert own.json()["id"] == own_id
        assert own.json()["normalized_score"] == 0.5
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_rubric_attempt_filter_supports_a_second_owned_learner() -> None:
    """An owned attempt selects its learner instead of silently using the default."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        primary = session.get(Learner, client.owner_learner_id)  # type: ignore[attr-defined]
        assert primary is not None
        second = Learner(user_id=primary.user_id, display_name="Second owned learner")
        session.add(second)
        session.flush()
        attempt = Attempt(
            learner_id=second.id, prompt_id="second-prompt", response_text="Second", feedback={}
        )
        session.add(attempt)
        session.commit()
        score_id = _seed_rubric_score(session, attempt.id)
        for params in ({"attempt_id": attempt.id}, {"learner_id": second.id}):
            response = client.get("/rubric-scores", params=params)
            assert response.status_code == 200
            assert [score["id"] for score in response.json()] == [score_id]
        mismatched = client.get(
            "/rubric-scores", params={"attempt_id": attempt.id, "learner_id": primary.id}
        )
        assert mismatched.status_code == 200
        assert mismatched.json() == []
        own = client.get(f"/rubric-scores/{score_id}")
        assert own.status_code == 200
    finally:
        with suppress(StopIteration):
            next(fixture)


def _seed_capability_chain(session: Session, learner_id: str) -> dict[str, str]:
    """Persist real target-derived records, including scheduler side effects."""
    from lms.capability.repository import (
        create_capability_target,
        create_gap_analysis,
        create_maintenance_plan,
        recompute_capability_estimate,
    )
    from lms.graphs.repository import create_knowledge_node

    node = create_knowledge_node(
        session,
        title="Private capability",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=learner_id,
        status="published",
    )
    target = create_capability_target(
        session, learner_id=learner_id, title="Private target", target_node_ids=[node.id]
    )
    estimate = recompute_capability_estimate(session, target_id=target.id)
    analysis = create_gap_analysis(session, estimate_id=estimate.id)
    plan = create_maintenance_plan(session, gap_analysis_id=analysis.id)
    session.commit()
    return {
        "targets": target.id,
        "estimates": estimate.id,
        "gap-analyses": analysis.id,
        "maintenance-plans": plan.id,
        "node": node.id,
    }


def test_authenticated_user_cannot_list_another_learners_capability_estimates() -> None:
    """All collections reject foreign learner filters and scope omitted filters."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        own = _seed_capability_chain(session, client.owner_learner_id)  # type: ignore[attr-defined]
        foreign = _seed_capability_chain(session, client.other_learner_id)  # type: ignore[attr-defined]
        for route in ("estimates", "targets", "gap-analyses", "maintenance-plans"):
            response = client.get(f"/capability/{route}", params={"learner_id": client.other_learner_id})  # type: ignore[attr-defined]
            missing = client.get(f"/capability/{route}", params={"learner_id": "missing-learner"})
            assert response.status_code == missing.status_code == 403
            assert response.json() == missing.json()
            for params in ({}, {"limit": 1}, {"learner_id": client.owner_learner_id}):  # type: ignore[attr-defined]
                allowed = client.get(f"/capability/{route}", params=params)
                assert allowed.status_code == 200, allowed.text
                assert [item["id"] for item in allowed.json()] == [own[route]]
                assert foreign[route] not in allowed.text
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_get_foreign_capability_estimate_by_id() -> None:
    """Every direct ID read hides foreign records with the missing-ID response."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        own = _seed_capability_chain(session, client.owner_learner_id)  # type: ignore[attr-defined]
        foreign = _seed_capability_chain(session, client.other_learner_id)  # type: ignore[attr-defined]
        for route in ("estimates", "targets", "gap-analyses", "maintenance-plans"):
            denied = client.get(f"/capability/{route}/{foreign[route]}")
            missing = client.get(f"/capability/{route}/missing-record")
            assert denied.status_code == missing.status_code == 404
            assert denied.json() == missing.json() == {"detail": "Learner resource not found."}
            allowed = client.get(f"/capability/{route}/{own[route]}")
            assert allowed.status_code == 200, allowed.text
            assert allowed.json()["id"] == own[route]
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_write_foreign_capability_records() -> None:
    """Deny target edits and derived writes before records or schedules change."""
    from lms.capability.models import (
        CapabilityEstimate,
        CapabilityTarget,
        GapAnalysis,
        MaintenancePlan,
    )
    from lms.scheduling.models import ReviewQueueItem, ReviewSchedule, SchedulerDecision

    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        own = _seed_capability_chain(session, client.owner_learner_id)  # type: ignore[attr-defined]
        foreign = _seed_capability_chain(session, client.other_learner_id)  # type: ignore[attr-defined]
        models = (
            CapabilityTarget,
            CapabilityEstimate,
            GapAnalysis,
            MaintenancePlan,
            ReviewSchedule,
            ReviewQueueItem,
            SchedulerDecision,
        )
        counts = [session.query(model).count() for model in models]
        target_payload = {
            "learner_id": client.other_learner_id,  # type: ignore[attr-defined]
            "title": "Intrusion",
            "target_node_ids": [foreign["node"]],
        }
        denied = client.post("/capability/targets", json=target_payload)
        missing = client.post(
            "/capability/targets", json={**target_payload, "learner_id": "missing"}
        )
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json()
        for route, field, parent in (
            ("estimates", "target_id", "targets"),
            ("gap-analyses", "estimate_id", "estimates"),
            ("maintenance-plans", "gap_analysis_id", "gap-analyses"),
        ):
            denied = client.post(f"/capability/{route}", json={field: foreign[parent]})
            missing = client.post(f"/capability/{route}", json={field: "missing"})
            assert denied.status_code == missing.status_code == 404
            assert denied.json() == missing.json()
        for method, suffix, payload in (
            ("PATCH", "", {"title": "Intrusion"}),
            ("POST", "/archive", None),
        ):
            denied = client.request(
                method, f"/capability/targets/{foreign['targets']}{suffix}", json=payload
            )
            missing = client.request(method, f"/capability/targets/missing{suffix}", json=payload)
            assert denied.status_code == missing.status_code == 404
            assert denied.json() == missing.json()
        session.expire_all()
        target = session.get(CapabilityTarget, foreign["targets"])
        assert target is not None and target.title == "Private target" and target.status == "active"
        assert [session.query(model).count() for model in models] == counts

        # The owner can still create the complete planning chain and edit/archive it.
        created = client.post(
            "/capability/targets",
            json={
                **target_payload,
                "learner_id": client.owner_learner_id,  # type: ignore[attr-defined]
                "target_node_ids": [own["node"]],
            },
        )
        assert created.status_code == 201, created.text
        target_id = created.json()["id"]
        parent_id = target_id
        for route, field in (
            ("estimates", "target_id"),
            ("gap-analyses", "estimate_id"),
            ("maintenance-plans", "gap_analysis_id"),
        ):
            created = client.post(f"/capability/{route}", json={field: parent_id})
            assert created.status_code == 201, created.text
            assert created.json()["learner_id"] == client.owner_learner_id  # type: ignore[attr-defined]
            parent_id = created.json()["id"]
        updated = client.patch(f"/capability/targets/{target_id}", json={"title": "Allowed"})
        assert updated.status_code == 200 and updated.json()["title"] == "Allowed"
        archived = client.post(f"/capability/targets/{target_id}/archive")
        assert archived.status_code == 200 and archived.json()["status"] == "archived"
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_capability_parent_filters_support_owned_learners_and_reject_foreign_ids() -> None:
    """Parent-only filters preserve second profiles, without leaking foreign IDs."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        primary = session.get(Learner, client.owner_learner_id)  # type: ignore[attr-defined]
        assert primary is not None
        second = Learner(user_id=primary.user_id, display_name="Second profile")
        session.add(second)
        session.commit()
        own = _seed_capability_chain(session, second.id)
        foreign = _seed_capability_chain(session, client.other_learner_id)  # type: ignore[attr-defined]
        filters = (
            ("estimates", "target_id", "targets"),
            ("gap-analyses", "target_id", "targets"),
            ("gap-analyses", "estimate_id", "estimates"),
            ("maintenance-plans", "target_id", "targets"),
            ("maintenance-plans", "gap_analysis_id", "gap-analyses"),
        )
        for route, field, parent in filters:
            for params in ({field: own[parent]}, {field: own[parent], "learner_id": second.id}):
                allowed = client.get(f"/capability/{route}", params=params)
                assert allowed.status_code == 200, allowed.text
                assert [item["id"] for item in allowed.json()] == [own[route]]
            for learner_filter in ({}, {"learner_id": primary.id}):
                denied = client.get(
                    f"/capability/{route}", params={field: foreign[parent], **learner_filter}
                )
                missing = client.get(
                    f"/capability/{route}", params={field: "missing", **learner_filter}
                )
                assert denied.status_code == missing.status_code == 404
                assert denied.json() == missing.json()
            mismatched = client.get(
                f"/capability/{route}", params={field: own[parent], "learner_id": primary.id}
            )
            assert mismatched.status_code == 200 and mismatched.json() == []
        mixed = client.get(
            "/capability/gap-analyses",
            params={"target_id": own["targets"], "estimate_id": foreign["estimates"]},
        )
        assert mixed.status_code == 404
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_capability_collections_reject_empty_id_filters() -> None:
    """An explicitly empty identity filter must not become an omitted filter."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        for route, fields in (
            ("targets", ("learner_id",)),
            ("estimates", ("learner_id", "target_id")),
            ("gap-analyses", ("learner_id", "target_id", "estimate_id")),
            ("maintenance-plans", ("learner_id", "target_id", "gap_analysis_id")),
        ):
            for field in fields:
                response = client.get(f"/capability/{route}", params={field: ""})
                assert response.status_code == 422, (route, field, response.text)
                assert response.json()["detail"][0]["loc"] == ["query", field]
    finally:
        with suppress(StopIteration):
            next(fixture)


_LEARNER_ROUTE_CASES = [
    ("GET", "learning-goals", 200),
    ("POST", "learning-goals", 201),
    ("GET", "knowledge-profile", 200),
    ("PATCH", "learning-goals/{goal_id}", 200),
    ("POST", "reflections", 201),
    ("GET", "reflections", 200),
    ("GET", "learning-goals/{goal_id}/progress", 200),
]


@pytest.mark.parametrize("method,route,success_status", _LEARNER_ROUTE_CASES)
@pytest.mark.parametrize("access", ["foreign", "owner", "local-foreign"])
def test_learner_routes_enforce_ownership_without_changing_local_access(
    method: str, route: str, success_status: int, access: str
) -> None:
    fixture = _deployed_client(auth_required=access != "local-foreign")
    client, session = next(fixture)
    try:
        learner_id = (
            client.owner_learner_id if access == "owner" else client.other_learner_id
        )  # type: ignore[attr-defined]
        node = KnowledgeNode(
            title="Published concept",
            knowledge_type="conceptual",
            ownership_scope="personal",
            status="published",
        )
        goal = LearningGoal(
            learner_id=learner_id,
            title="Private learning goal",
            knowledge_type="conceptual",
            ownership_scope="personal",
            target_nodes=[node],
        )
        reflection = LearnerReflection(
            learner_id=learner_id,
            prompt="Private prompt",
            response="Private reflection",
        )
        session.add_all([goal, reflection])
        session.commit()
        before_goals = session.query(LearningGoal).count()
        before_reflections = session.query(LearnerReflection).count()
        payload = None
        if method == "POST" and route == "learning-goals":
            payload = {
                "title": "New goal",
                "knowledge_type": "conceptual",
                "target_node_ids": [node.id],
                "ownership_scope": "personal",
            }
        elif method == "PATCH":
            payload = {"title": "Changed goal"}
        elif method == "POST":
            payload = {"prompt": "New prompt", "response": "New reflection"}
        suffix = route.format(goal_id=goal.id)
        request_kwargs = {"json": payload} if payload is not None else {}
        response = client.request(method, f"/learners/{learner_id}/{suffix}", **request_kwargs)
        if access == "foreign":
            missing = client.request(method, f"/learners/nonexistent/{suffix}", **request_kwargs)
            assert response.status_code == missing.status_code == 404
            assert response.json() == missing.json() == {"detail": "Learner resource not found."}
            session.expire_all()
            assert session.query(LearningGoal).count() == before_goals
            assert session.query(LearnerReflection).count() == before_reflections
            assert goal.title == "Private learning goal"
            assert reflection.response == "Private reflection"
        else:
            assert response.status_code == success_status, response.text
            result = response.json()
            if route == "learning-goals" and method == "GET":
                assert [item["title"] for item in result] == ["Private learning goal"]
            elif route == "reflections" and method == "GET":
                assert [item["response"] for item in result] == ["Private reflection"]
            else:
                assert result["learner_id"] == learner_id
            if method == "PATCH":
                session.refresh(goal)
                assert goal.title == "Changed goal"
            elif method == "POST":
                model = LearningGoal if route == "learning-goals" else LearnerReflection
                before = before_goals if route == "learning-goals" else before_reflections
                assert session.query(model).count() == before + 1
    finally:
        with suppress(StopIteration):
            next(fixture)


@pytest.mark.parametrize("access", ["foreign", "missing", "owner", "local-foreign"])
def test_create_learner_enforces_signed_in_user_and_preserves_local_access(access: str) -> None:
    fixture = _deployed_client(auth_required=access != "local-foreign")
    client, session = next(fixture)
    try:
        learner_id = (
            client.owner_learner_id if access == "owner" else client.other_learner_id
        )  # type: ignore[attr-defined]
        learner = session.get(Learner, learner_id)
        assert learner is not None
        user_id = "missing-user" if access == "missing" else learner.user_id
        before = session.query(Learner).count()
        response = client.post(
            "/learners", json={"user_id": user_id, "display_name": "New profile"}
        )
        if access in {"foreign", "missing"}:
            assert response.status_code == 403
            assert response.json() == {"detail": "Cannot create a learner for another user."}
            assert session.query(Learner).count() == before
        else:
            assert response.status_code == 201, response.text
            assert response.json()["user_id"] == user_id
            assert session.query(Learner).count() == before + 1
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_learner_ownership_uses_real_login_session() -> None:
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        owner_learner = session.get(Learner, client.owner_learner_id)  # type: ignore[attr-defined]
        assert owner_learner is not None
        owner = session.get(User, owner_learner.user_id)
        assert owner is not None
        owner.password_hash = hash_password("ownership-test-password")
        session.commit()
        client.app.dependency_overrides.pop(require_authenticated_user)  # type: ignore[attr-defined]
        own_url = f"/learners/{owner_learner.id}/learning-goals"
        assert client.get(own_url).status_code == 401
        login = client.post(
            "/login",
            data={"username": owner.username, "password": "ownership-test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        assert client.get(own_url).status_code == 200
        foreign = client.get(f"/learners/{client.other_learner_id}/learning-goals")  # type: ignore[attr-defined]
        assert foreign.status_code == 404
        created = client.post("/learners", json={"user_id": owner.id, "display_name": "Owned"})
        assert created.status_code == 201
        assert created.json()["user_id"] == owner.id
    finally:
        with suppress(StopIteration):
            next(fixture)


def _seed_owned_work_products(client: TestClient, session: Session) -> dict[str, Any]:
    """Seed scoreable owner and foreign submissions through real repositories."""
    from datetime import UTC, datetime, timedelta

    from lms.cases.repository import create_case, create_work_product
    from lms.feedback.repository import create_rubric

    node = KnowledgeNode(
        title="Shared transfer concept",
        knowledge_type="judgment",
        ownership_scope="personal",
        status="published",
    )
    session.add(node)
    session.flush()
    rubric = create_rubric(
        session,
        title="Shared transfer rubric",
        ownership_scope="personal",
        authoring_actor="user:owner",
        knowledge_node_id=node.id,
    )
    case = create_case(
        session,
        title="Public transfer definition",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=node.id,
        steps=[{"step_order": 1, "title": "Analyze", "prompt": "Explain the decision."}],
    )
    products = {}
    for index, (access, learner_id) in enumerate(
        [
            ("owner", client.owner_learner_id),  # type: ignore[attr-defined]
            ("foreign", client.other_learner_id),  # type: ignore[attr-defined]
        ]
    ):
        product = create_work_product(
            session,
            case_id=case.id,
            case_step_id=case.steps[0].id,
            learner_id=learner_id,
            rubric_id=rubric.id,
            submission_type="memo",
            body=f"{access} confidential submission",
        )
        product.submitted_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
        products[access] = product
    session.commit()
    return products


@pytest.mark.parametrize("route", ["submit", "get", "score"])
@pytest.mark.parametrize("access", ["foreign", "missing", "owner", "local-foreign"])
def test_work_product_routes_enforce_ownership(route: str, access: str) -> None:
    """Reject foreign and missing resources before reading text or writing evidence."""
    from lms.cases.models import WorkProduct
    from lms.feedback.models import RubricScore

    fixture = _deployed_client(auth_required=access != "local-foreign")
    client, session = next(fixture)
    try:
        products = _seed_owned_work_products(client, session)
        product = products["owner" if access == "owner" else "foreign"]
        product_id = "missing-product" if access == "missing" else product.id
        learner_id = "missing-learner" if access == "missing" else product.learner_id
        models = (WorkProduct, RubricScore, EvidenceRecord, Attempt)
        before = {model: session.query(model).count() for model in models}
        if route == "submit":
            response = client.post(
                f"/cases/{product.case_id}/work-products",
                json={
                    "learner_id": learner_id,
                    "submission_type": "memo",
                    "body": "New submission",
                    "rubric_id": product.rubric_id,
                },
            )
        elif route == "score":
            response = client.post(
                f"/work-products/{product_id}/score",
                json={"scorer_type": "rubric-self", "raw_score": 3.0, "max_score": 4.0},
            )
        else:
            response = client.get(f"/work-products/{product_id}")
        session.expire_all()
        if access in {"foreign", "missing"}:
            assert response.status_code == 404, response.text
            assert response.json() == {"detail": "Learner resource not found."}
            assert "confidential submission" not in response.text
            assert {model: session.query(model).count() for model in models} == before
            assert product.status == "submitted"
            assert product.rubric_score_id is None
            assert product.body == "foreign confidential submission"
        else:
            assert response.status_code == (200 if route == "get" else 201), response.text
            if route == "get":
                assert response.json()["body"] == product.body
            elif route == "submit":
                assert response.json()["learner_id"] == learner_id
                assert session.query(WorkProduct).count() == before[WorkProduct] + 1
            else:
                assert product.status == "scored"
                assert product.rubric_score_id == response.json()["rubric_score_id"]
                evidence = session.get(EvidenceRecord, response.json()["evidence_record_id"])
                assert evidence is not None and evidence.learner_id == learner_id
                assert session.query(RubricScore).count() == before[RubricScore] + 1
    finally:
        with suppress(StopIteration):
            next(fixture)


@pytest.mark.parametrize("auth_required", [True, False])
def test_work_product_lists_scope_before_filters_and_limit(auth_required: bool) -> None:
    """Deployed lists default to the owner while local unfiltered lists retain all rows."""
    fixture = _deployed_client(auth_required=auth_required)
    client, session = next(fixture)
    try:
        products = _seed_owned_work_products(client, session)
        own, foreign = products["owner"], products["foreign"]
        url = f"/cases/{own.case_id}/work-products"
        response = client.get(url)
        assert response.status_code == 200, response.text
        expected = [own.id] if auth_required else [foreign.id, own.id]
        assert [row["id"] for row in response.json()] == expected
        limited = client.get(
            url, params={"limit": 1, "status": "submitted", "case_step_id": own.case_step_id}
        )
        assert limited.status_code == 200
        assert [row["id"] for row in limited.json()] == expected[:1]
        assert client.get(url, params={"status": "scored"}).json() == []
        for learner_id in (foreign.learner_id, "missing-learner"):
            filtered = client.get(url, params={"learner_id": learner_id})
            if auth_required:
                assert filtered.status_code == 404
                assert filtered.json() == {"detail": "Learner resource not found."}
            else:
                assert filtered.status_code == 200
                ids = [foreign.id] if learner_id == foreign.learner_id else []
                assert [row["id"] for row in filtered.json()] == ids
        owned = client.get(url, params={"learner_id": own.learner_id})
        assert owned.status_code == 200
        assert [row["id"] for row in owned.json()] == [own.id]
        assert client.get(url, params={"learner_id": ""}).status_code == 422
        # Shared case definitions remain readable in both modes.
        assert client.get(f"/cases/{own.case_id}").status_code == 200
        assert own.case_id in [row["id"] for row in client.get("/cases").json()]
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_work_product_ownership_uses_real_login_session() -> None:
    """The actual login dependency protects all four case submission routes."""
    fixture = _deployed_client()
    client, session = next(fixture)
    try:
        products = _seed_owned_work_products(client, session)
        own, foreign = products["owner"], products["foreign"]
        learner = session.get(Learner, own.learner_id)
        assert learner is not None
        owner = session.get(User, learner.user_id)
        assert owner is not None
        owner.password_hash = hash_password("case-test-password")
        session.commit()
        client.app.dependency_overrides.pop(require_authenticated_user)  # type: ignore[attr-defined]
        requests = [
            ("GET", f"/cases/{own.case_id}/work-products", {}),
            ("GET", f"/work-products/{own.id}", {}),
            (
                "POST",
                f"/cases/{own.case_id}/work-products",
                {"json": {"learner_id": own.learner_id, "submission_type": "memo", "body": "Own"}},
            ),
            (
                "POST",
                f"/work-products/{own.id}/score",
                {"json": {"scorer_type": "rubric-self", "raw_score": 3.0, "max_score": 4.0}},
            ),
        ]
        for method, url, kwargs in requests:
            assert client.request(method, url, **kwargs).status_code == 401
        login = client.post(
            "/login",
            data={"username": owner.username, "password": "case-test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        for method, url, kwargs in requests:
            response = client.request(method, url, **kwargs)
            assert response.status_code == (200 if method == "GET" else 201), response.text
        assert client.get(f"/work-products/{foreign.id}").status_code == 404
        listed = client.get(f"/cases/{own.case_id}/work-products").json()
        assert listed and all(row["learner_id"] == own.learner_id for row in listed)
    finally:
        with suppress(StopIteration):
            next(fixture)
