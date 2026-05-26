"""Tests for ReviewPolicy persistence and the /review-policies route."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app
from lms.scheduling.models import ReviewPolicy
from lms.scheduling.repository import get_or_create_review_policy


def test_get_or_create_review_policy_returns_existing_active_row(db_session: Session) -> None:
    """Repeated calls with the same identity return the same active policy row."""
    first = get_or_create_review_policy(
        db_session,
        reason_code="due-review",
        policy_version="v1",
        name="Due review v1",
        settings={"ramp": [1, 3, 7]},
        knowledge_type="conceptual",
        ownership_scope="personal",
    )
    db_session.commit()

    second = get_or_create_review_policy(
        db_session,
        reason_code="due-review",
        policy_version="v1",
        name="Due review v1 (duplicate)",
        settings={"ramp": [1, 3, 7]},
        knowledge_type="conceptual",
        ownership_scope="personal",
    )

    assert second.id == first.id
    rows = db_session.scalars(
        select(ReviewPolicy).where(
            ReviewPolicy.reason_code == "due-review",
            ReviewPolicy.policy_version == "v1",
        )
    ).all()
    assert len(rows) == 1


def test_get_or_create_review_policy_partial_unique_index_blocks_duplicate_actives(
    db_session: Session,
) -> None:
    """A second active row with the same identity must raise IntegrityError."""
    get_or_create_review_policy(
        db_session,
        reason_code="due-review",
        policy_version="v1",
        name="Due review v1",
        settings={"ramp": [1, 3, 7]},
        knowledge_type="conceptual",
        ownership_scope="personal",
    )
    db_session.commit()

    duplicate = ReviewPolicy(
        name="Conflict",
        policy_version="v1",
        reason_code="due-review",
        knowledge_type="conceptual",
        ownership_scope="personal",
        settings={"ramp": [1, 3, 7]},
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_get_or_create_review_policy_recovers_from_concurrent_insert(
    db_session: Session,
) -> None:
    """When a peer wins the race, the helper re-queries and returns the winner."""
    winner = ReviewPolicy(
        name="winner",
        policy_version="v1",
        reason_code="due-review",
        knowledge_type="conceptual",
        ownership_scope="personal",
        settings={"ramp": [1, 3, 7]},
    )
    db_session.add(winner)
    db_session.commit()

    # Force the SELECT inside get_or_create to miss the existing row, simulating a
    # racing transaction that committed between our SELECT and our INSERT.
    original_scalar = db_session.scalar
    select_calls = {"count": 0}

    def first_select_misses(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
        select_calls["count"] += 1
        if select_calls["count"] == 1:
            return None
        return original_scalar(stmt, *args, **kwargs)

    db_session.scalar = first_select_misses  # type: ignore[method-assign,assignment]
    try:
        result = get_or_create_review_policy(
            db_session,
            reason_code="due-review",
            policy_version="v1",
            name="loser",
            settings={"ramp": [1, 3, 7]},
            knowledge_type="conceptual",
            ownership_scope="personal",
        )
    finally:
        db_session.scalar = original_scalar  # type: ignore[method-assign]

    assert result.id == winner.id


def _make_app_with_overridden_session(session_factory: sessionmaker[Session]):  # type: ignore[no-untyped-def]
    def override_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_session
    return app


def test_review_policies_endpoint_returns_active_records_with_filters() -> None:
    """GET /review-policies returns serialized active rows with filters honored."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as session:
        active_due = ReviewPolicy(
            name="Active due-review",
            policy_version="v1",
            reason_code="due-review",
            knowledge_type="conceptual",
            ownership_scope="personal",
            settings={"ramp": [1, 3, 7]},
        )
        active_remediation = ReviewPolicy(
            name="Active remediation",
            policy_version="v1",
            reason_code="remediation",
            knowledge_type=None,
            ownership_scope=None,
            settings={"strategy": "retry"},
        )
        retired_due = ReviewPolicy(
            name="Retired due-review",
            policy_version="v0",
            reason_code="due-review",
            knowledge_type="factual",
            ownership_scope="personal",
            settings={"ramp": [2]},
            is_active=False,
        )
        session.add_all([active_due, active_remediation, retired_due])
        session.commit()

    app = _make_app_with_overridden_session(session_factory)
    client = TestClient(app)
    try:
        all_active = client.get("/review-policies")
        assert all_active.status_code == 200
        active_payload = all_active.json()
        assert {row["name"] for row in active_payload} == {
            "Active due-review",
            "Active remediation",
        }
        for row in active_payload:
            assert row["is_active"] is True
            for required in ("id", "policy_version", "reason_code", "settings"):
                assert required in row

        filtered = client.get("/review-policies", params={"reason_code": "due-review"})
        assert filtered.status_code == 200
        filtered_payload = filtered.json()
        assert [row["name"] for row in filtered_payload] == ["Active due-review"]

        include_retired = client.get(
            "/review-policies",
            params={"active_only": "false", "reason_code": "due-review"},
        )
        assert include_retired.status_code == 200
        retired_payload = include_retired.json()
        retired_names = sorted(row["name"] for row in retired_payload)
        assert retired_names == ["Active due-review", "Retired due-review"]

        limited = client.get("/review-policies", params={"limit": 1})
        assert limited.status_code == 200
        assert len(limited.json()) == 1
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
