"""HTTP-level gate for the maintenance review loop.

Drives the real ``create_app()`` over the maintenance surfaces with the actual
IPO items: due list -> answer -> grade -> next review scheduled -> dispute.
No direct card-state writes, so this pins the wiring rather than the units.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.cases.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.feedback.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.llm.proposals  # noqa: F401
import lms.maintenance.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.auth.repository import get_or_create_local_dev_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.learners.repository import create_learner_for_user
from lms.main import create_app
from lms.maintenance.drafts import list_pending_drafts, prepare_draft
from lms.maintenance.models import GradeDispute, MaintenanceItem
from lms.maintenance.seeds import ipo_surge_2026
from lms.scheduling.models import SUBJECT_MAINTENANCE_ITEM, ReviewCardState
from lms.ui.maintenance import _float_or_none

MAINTENANCE = "/app/learner/maintenance"


@pytest.mark.parametrize(
    "value", [None, "", " ", "invalid", "nan", "NaN", "inf", "-Infinity", "1e999"]
)
def test_dispute_float_parser_discards_invalid_values(value: str | None) -> None:
    assert _float_or_none(value) is None


@pytest.mark.parametrize(("value", "expected"), [("0", 0.0), ("1", 1.0), (" 0.6 ", 0.6)])
def test_dispute_float_parser_preserves_finite_values(value: str, expected: float) -> None:
    assert _float_or_none(value) == expected


@pytest.fixture
def client_and_items() -> Generator[tuple[TestClient, sessionmaker[Session], str], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        s = factory()
        try:
            yield s
        finally:
            s.close()

    with factory() as session:
        user = get_or_create_local_dev_user(session)
        learner = create_learner_for_user(
            session, user_id=user.id, display_name="Maintenance Learner"
        )
        for spec in ipo_surge_2026.all_items():
            session.add(MaintenanceItem(learner_id=learner.id, status="active", **spec))
        session.commit()
        learner_id = learner.id

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, factory, learner_id
    finally:
        client.close()
        app.dependency_overrides.clear()


def _item(factory: sessionmaker[Session], *, item_type: str) -> MaintenanceItem:
    with factory() as session:
        return session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.item_type == item_type)
        ).first()


def _card(factory: sessionmaker[Session], item_id: str) -> ReviewCardState | None:
    with factory() as session:
        return session.scalars(
            select(ReviewCardState).where(
                ReviewCardState.subject_type == SUBJECT_MAINTENANCE_ITEM,
                ReviewCardState.subject_id == item_id,
            )
        ).first()


def test_due_list_shows_never_reviewed_items(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """All six seeded items are due on day one (3 ideas + 3 anchors)."""
    client, _factory, _learner = client_and_items

    response = client.get(MAINTENANCE)

    assert response.status_code == 200
    assert "US IPO count per year" in response.text
    assert "reference anchor" in response.text
    assert "6 of 6 item(s) due" in response.text


@pytest.mark.parametrize("central_value", [float("nan"), float("inf"), "-Infinity", "invalid"])
@pytest.mark.parametrize("supplied_band", [False, True])
def test_invalid_anchor_draft_preserves_review_queue(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
    central_value: object,
    supplied_band: bool,
) -> None:
    client, factory, learner_id = client_and_items
    spec = next(s for s in ipo_surge_2026.all_items() if s["item_type"] == "reference_anchor")
    with factory() as session:
        existing = prepare_draft(spec, learner_id=learner_id)
        session.add(existing)
        session.commit()
        original = existing.payload.copy()
        invalid_payload = dict(original, central_value=central_value)
        if not supplied_band:
            invalid_payload.pop("typical_low", None)
            invalid_payload.pop("typical_high", None)
        with pytest.raises(ValueError, match="central_value must be a finite number"):
            session.add(prepare_draft(dict(spec, payload=invalid_payload), learner_id=learner_id))
        # Rejection must not require a rollback or poison a subsequent valid write.
        session.add(prepare_draft(spec, learner_id=learner_id))
        session.commit()
        session.expire_all()
        drafts = list_pending_drafts(session, learner_id=learner_id)
        assert len(drafts) == 2
        assert all(draft.item.payload == original for draft in drafts)
        assert existing.payload == original

    queue = client.get(f"{MAINTENANCE}/drafts")
    assert queue.status_code == 200
    assert spec["title"] in queue.text
    assert client.get(MAINTENANCE).status_code == 200


def test_anchor_review_grades_deterministically_and_schedules(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """A roughly-right anchor answer passes on band and books the next review."""
    client, factory, _learner = client_and_items
    anchor = _item(factory, item_type="reference_anchor")
    assert _card(factory, anchor.id) is None

    response = client.post(
        f"{MAINTENANCE}/review",
        data={"item_id": anchor.id, "answer": "about 100 a year"},
    )

    assert response.status_code == 200
    assert "Correct" in response.text
    # The verdict hands back the distribution, not just a mark.
    assert "Dot-Com peak" in response.text
    card = _card(factory, anchor.id)
    assert card is not None and card.due_at is not None
    assert card.review_count == 1


def test_wrong_anchor_answer_still_schedules_but_sooner(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Failing an item must shorten its interval, not drop it from the loop."""
    client, factory, _learner = client_and_items
    anchor = _item(factory, item_type="reference_anchor")

    response = client.post(
        f"{MAINTENANCE}/review", data={"item_id": anchor.id, "answer": "about 400"}
    )

    assert response.status_code == 200
    assert "Not quite" in response.text
    card = _card(factory, anchor.id)
    assert card is not None
    assert card.lapse_count == 1


def test_typicality_question_uses_the_supplied_reading(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """With a current reading, the item asks the comparative question instead."""
    client, factory, _learner = client_and_items
    anchor = _item(factory, item_type="reference_anchor")

    response = client.post(
        f"{MAINTENANCE}/review",
        data={"item_id": anchor.id, "answer": "that's below normal", "reading": "60"},
    )

    assert response.status_code == 200
    assert "Correct" in response.text


def test_idea_review_grades_on_coverage(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Idea items grade on key points and say which grader ran."""
    client, factory, _learner = client_and_items
    idea = _item(factory, item_type="idea")

    response = client.post(
        f"{MAINTENANCE}/review",
        data={"item_id": idea.id, "answer": "I have no idea."},
    )

    assert response.status_code == 200
    assert "Not quite" in response.text
    # The learner is told how the grade was produced.
    assert "Graded by:" in response.text


def test_empty_answer_is_refused_without_scheduling(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """A blank submission must not count as a failed review."""
    client, factory, _learner = client_and_items
    idea = _item(factory, item_type="idea")

    response = client.post(f"{MAINTENANCE}/review", data={"item_id": idea.id, "answer": "  "})

    assert response.status_code == 200
    assert "Write an answer" in response.text
    assert _card(factory, idea.id) is None


def test_dispute_records_feedback_and_reschedules(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Pushback is recorded AND corrects the schedule the bad grade produced."""
    client, factory, _learner = client_and_items
    idea = _item(factory, item_type="idea")
    client.post(f"{MAINTENANCE}/review", data={"item_id": idea.id, "answer": "A partial answer."})
    before = _card(factory, idea.id)
    assert before is not None

    response = client.post(
        f"{MAINTENANCE}/dispute",
        data={
            "item_id": idea.id,
            "answer": "A partial answer.",
            "machine_grade": "0.0",
            "learner_grade": "correct",
            "comment": "It ignored a point I clearly made.",
        },
    )

    assert response.status_code == 200
    assert "rescheduled using your grade" in response.text
    with factory() as session:
        disputes = session.scalars(select(GradeDispute)).all()
    assert len(disputes) == 1
    assert disputes[0].learner_grade == 1.0
    assert disputes[0].comment
    after = _card(factory, idea.id)
    assert after is not None
    assert after.review_count == before.review_count + 1


def test_dispute_without_a_grade_only_records_the_note(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Leaving a note must not silently re-rate the item."""
    client, factory, _learner = client_and_items
    idea = _item(factory, item_type="idea")
    client.post(f"{MAINTENANCE}/review", data={"item_id": idea.id, "answer": "Something."})
    before = _card(factory, idea.id)
    assert before is not None

    client.post(
        f"{MAINTENANCE}/dispute",
        data={
            "item_id": idea.id,
            "answer": "Something.",
            "machine_grade": "0.0",
            "learner_grade": "",
            "comment": "Wording felt harsh.",
        },
    )

    after = _card(factory, idea.id)
    assert after is not None
    assert after.review_count == before.review_count


@pytest.mark.parametrize(
    ("raw_grade", "expected"),
    [("nan", None), ("inf", None), ("-inf", None), ("1e999", None), ("0.6", 0.6)],
)
def test_dispute_persists_only_finite_machine_grades(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
    raw_grade: str,
    expected: float | None,
) -> None:
    client, factory, learner_id = client_and_items
    idea = _item(factory, item_type="idea")

    response = client.post(
        f"{MAINTENANCE}/dispute",
        data={
            "item_id": idea.id,
            "answer": "My answer.",
            "machine_grade": raw_grade,
            "learner_grade": "correct",
            "comment": "Keep this feedback.",
        },
    )

    assert response.status_code == 200
    with factory() as session:
        dispute = session.scalars(select(GradeDispute)).one()
        assert dispute.learner_id == learner_id
        assert dispute.maintenance_item_id == idea.id
        assert dispute.machine_grade == expected
        assert dispute.learner_grade == 1.0
        assert dispute.submitted_answer == "My answer."
        assert dispute.comment == "Keep this feedback."
    card = _card(factory, idea.id)
    assert card is not None and card.review_count == 1


def test_reviewed_item_leaves_the_due_list(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Answering an item removes it from today's queue."""
    client, factory, _learner = client_and_items
    anchor = _item(factory, item_type="reference_anchor")

    client.post(f"{MAINTENANCE}/review", data={"item_id": anchor.id, "answer": "about 100"})
    listing = client.get(MAINTENANCE)

    assert "5 of 6 item(s) due" in listing.text


def test_another_learners_item_is_not_reachable(
    client_and_items: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Items are learner-scoped, matching the ownership model elsewhere."""
    client, factory, _learner = client_and_items
    with factory() as session:
        stranger_learner = create_learner_for_user(
            session,
            user_id=get_or_create_local_dev_user(session).id,
            display_name="Someone else",
        )
        foreign = MaintenanceItem(
            learner_id=stranger_learner.id,
            item_type="idea",
            title="Not yours",
            prompt="Secret",
            payload={"key_points": []},
            status="active",
        )
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id

    assert client.get(f"{MAINTENANCE}/review?item_id={foreign_id}").status_code == 404
