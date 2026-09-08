"""Repository utility regression tests."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability import repository
from lms.capability.repository import _as_float, _as_int
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user


def test_as_int_handles_float_strings() -> None:
    assert _as_int("3.0") == 3
    assert _as_int("3.5") == 3
    assert _as_int("x") == 0
    assert _as_int(True) == 0


def test_as_int_handles_non_finite_strings() -> None:
    # int(float("inf")) raises OverflowError and int(float("nan")) raises ValueError;
    # the helper must return 0 for these rather than propagating.
    assert _as_int("inf") == 0
    assert _as_int("-inf") == 0
    assert _as_int("Infinity") == 0
    assert _as_int("nan") == 0
    assert _as_int(float("inf")) == 0
    assert _as_int(float("nan")) == 0


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        "nan",
        float("inf"),
        float("-inf"),
        "Infinity",
        "-inf",
        "1e10000",
        "not-a-number",
        "",
        "  ",
        None,
        [],
        {},
        10**1000,
    ],
    ids=[
        "nan",
        "nan-string",
        "inf",
        "negative-inf",
        "infinity-string",
        "negative-inf-string",
        "overflow-string",
        "invalid-string",
        "empty",
        "whitespace",
        "null",
        "list",
        "dict",
        "overflow-int",
    ],
)
def test_as_float_handles_nan_and_invalid_strings_safely(value: object) -> None:
    assert _as_float(value) == 0.0


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, 0.0),
        (0.75, 0.75),
        ("0.75", 0.75),
        (" 1e-2 ", 0.01),
        (-2, -2.0),
        (True, 1.0),
        (False, 0.0),
    ],
)
def test_as_float_preserves_finite_inputs(value: object, expected: float) -> None:
    assert _as_float(value) == expected


@pytest.mark.parametrize("source", ["profile", "mastery"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "nan", "invalid"])
def test_invalid_mastery_values_remain_visible_in_capability_gaps(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, source: str, value: object
) -> None:
    user = User(email="finite@example.test", username="finite", display_name="Learner")
    db_session.add(user)
    db_session.flush()
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Learner")
    node = create_knowledge_node(
        db_session,
        title="Finite mastery",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    target = repository.create_capability_target(
        db_session,
        learner_id=learner.id,
        title="Finite target",
        target_node_ids=[node.id],
    )
    # Inject malformed legacy/provider rows at the two numeric input boundaries;
    # target lookup, estimate persistence, and gap generation use the real repository.
    row = {
        "knowledge_node_id": node.id,
        "current_estimate": value,
        "confidence": value,
        "evidence_count": 1,
    }
    monkeypatch.setattr(
        repository,
        "knowledge_profile_for_learner",
        lambda *args, **kwargs: {"items": [row] if source == "profile" else []},
    )
    monkeypatch.setattr(
        repository,
        "mastery_estimates_for_learner",
        lambda *args, **kwargs: [row] if source == "mastery" else [],
    )

    estimate = repository.recompute_capability_estimate(db_session, target_id=target.id)
    analysis = repository.create_gap_analysis(db_session, estimate_id=estimate.id)
    db_session.commit()
    db_session.expire_all()

    assert estimate.current_score == 0.0
    assert estimate.confidence == 0.0
    assert estimate.weak_node_ids == [node.id]
    weak_gaps = [item for item in analysis.gap_items if item["gap_type"] == "weak_mastery"]
    assert len(weak_gaps) == 1
    assert weak_gaps[0]["knowledge_node_id"] == node.id
    assert weak_gaps[0]["current_estimate"] == 0.0
    assert weak_gaps[0]["confidence"] == 0.0
