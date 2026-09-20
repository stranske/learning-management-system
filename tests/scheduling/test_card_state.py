"""Concurrency recovery for :func:`get_or_seed_card_state`."""

from __future__ import annotations

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


def test_concurrent_first_seed_returns_winning_row(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A peer that wins the insert race must be re-queried, not raised at."""
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

    result = get_or_seed_card_state(
        db_session,
        learner_id=LEARNER_ID,
        subject_id=SUBJECT_ID,
        retention_tier=fsrs_engine.HOT,
    )

    assert result.id == winner["id"]
    # The loser's requested tier is reconciled onto the winning row rather than
    # silently dropped, matching the existing-row branch.
    assert result.retention_tier == fsrs_engine.HOT
    assert calls["count"] == 2


def test_seed_still_raises_on_unrelated_integrity_error(db_session: Session) -> None:
    """A violation that is not the learner/subject race must still propagate."""
    with pytest.raises(IntegrityError):
        get_or_seed_card_state(
            db_session,
            learner_id=LEARNER_ID,
            subject_id=SUBJECT_ID,
            retention_tier="not-a-tier",
        )
