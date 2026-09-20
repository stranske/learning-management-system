"""Concurrency recovery for :func:`get_or_seed_card_state`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from lms.scheduling import card_state as card_state_module
from lms.scheduling import fsrs_engine
from lms.scheduling.card_state import get_or_seed_card_state
from lms.scheduling.models import SUBJECT_KNOWLEDGE_NODE, ReviewCardState

LEARNER_ID = "learner-race"
SUBJECT_ID = "node-race"


@pytest.mark.parametrize("retention_tier", [fsrs_engine.HOT, "not-a-tier"])
def test_concurrent_first_seed_returns_winning_row(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, retention_tier: str
) -> None:
    """Recover an identity race while preserving unrelated constraint failures."""
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    real_get_card_state = card_state_module.get_card_state
    calls = {"count": 0}
    winner: dict[str, str] = {}

    def racing_get_card_state(session: Session, **kwargs: Any) -> ReviewCardState | None:
        calls["count"] += 1
        if calls["count"] == 1:
            # Stand in for a concurrent transaction that committed the same
            # learner/subject pair after our SELECT and before our flush.
            peer_session = session_factory()
            try:
                peer_row = ReviewCardState(
                    learner_id=LEARNER_ID,
                    subject_type=SUBJECT_KNOWLEDGE_NODE,
                    subject_id=SUBJECT_ID,
                    retention_tier=fsrs_engine.COLD,
                    card_state=fsrs_engine.new_card_state(),
                )
                peer_session.add(peer_row)
                peer_session.commit()
                winner["id"] = peer_row.id
            finally:
                peer_session.close()
            return None
        return real_get_card_state(session, **kwargs)

    monkeypatch.setattr(card_state_module, "get_card_state", racing_get_card_state)

    if retention_tier == "not-a-tier":
        real_flush = db_session.flush
        failures: list[IntegrityError] = []

        def capture_flush(*args: Any, **kwargs: Any) -> None:
            try:
                real_flush(*args, **kwargs)
            except IntegrityError as error:
                failures.append(error)
                raise

        monkeypatch.setattr(db_session, "flush", capture_flush)
        with pytest.raises(IntegrityError, match="review_card_retention_tier_valid") as exc:
            get_or_seed_card_state(
                db_session,
                learner_id=LEARNER_ID,
                subject_id=SUBJECT_ID,
                retention_tier=retention_tier,
            )

        assert exc.value is failures[0]
        assert calls["count"] == 1
        assert db_session.is_active
        saved = real_get_card_state(db_session, learner_id=LEARNER_ID, subject_id=SUBJECT_ID)
        assert saved is not None
        assert saved.id == winner["id"]
        assert saved.retention_tier == fsrs_engine.COLD
        assert saved not in db_session.dirty
        db_session.flush()
        return

    result = get_or_seed_card_state(
        db_session,
        learner_id=LEARNER_ID,
        subject_id=SUBJECT_ID,
        retention_tier=retention_tier,
    )

    assert result.id == winner["id"]
    # The loser's requested tier is reconciled onto the winning row rather than
    # silently dropped, matching the existing-row branch.
    assert result.retention_tier == fsrs_engine.HOT
    assert calls["count"] == 2
    db_session.flush()
    db_session.refresh(result)
    assert result.retention_tier == fsrs_engine.HOT


def test_seed_still_raises_on_unrelated_integrity_error(db_session: Session) -> None:
    """A violation that is not the learner/subject race must still propagate."""
    with pytest.raises(IntegrityError):
        get_or_seed_card_state(
            db_session,
            learner_id=LEARNER_ID,
            subject_id=SUBJECT_ID,
            retention_tier="not-a-tier",
        )


@pytest.mark.parametrize("diagnostic_field", ["sqlstate", "pgcode"])
@pytest.mark.parametrize(
    ("sqlstate", "constraint", "recoverable"),
    [
        ("23505", "ux_review_card_states_learner_subject", True),
        ("23505", "review_card_states_pkey", False),
        ("23514", "review_card_retention_tier_valid", False),
    ],
)
def test_postgres_recovery_requires_the_identity_constraint(
    monkeypatch: pytest.MonkeyPatch,
    diagnostic_field: str,
    sqlstate: str,
    constraint: str,
    recoverable: bool,
) -> None:
    original = Exception("database constraint violation")
    monkeypatch.setattr(original, diagnostic_field, sqlstate, raising=False)
    monkeypatch.setattr(
        original, "diag", SimpleNamespace(constraint_name=constraint), raising=False
    )

    assert (
        card_state_module._is_card_identity_conflict(IntegrityError("INSERT", {}, original))
        is recoverable
    )
