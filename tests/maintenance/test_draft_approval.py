"""Gate for the draft approval queue.

Approval is a correctness control, not workflow decoration: source documents
are scanned PDFs with imperfect OCR, so an unverified figure would be
memorised as fact and reinforced for years. These tests pin the properties
that make the queue trustworthy and keep it from becoming a backlog.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
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
from lms.learners.models import Learner
from lms.learners.repository import create_learner_for_user
from lms.main import create_app
from lms.maintenance.drafts import (
    DRAFT_TTL_DAYS,
    PENDING_DRAFT_CAP,
    approve_draft,
    can_accept_drafts,
    count_pending_drafts,
    default_band,
    describe_draft,
    expire_stale_drafts,
    list_pending_drafts,
    prepare_draft,
    reject_draft,
    rejection_guidance,
    reserve_draft_capacity,
)
from lms.maintenance.models import DraftRejection, MaintenanceItem
from lms.maintenance.seeds import ipo_surge_2026
from lms.ui.drafts import _coerce_like

DRAFTS = "/app/learner/maintenance/drafts"


@pytest.mark.parametrize("raw, expected", [("5", 5), (" 0 ", 0), ("-2", -2), ("+12", 12)])
def test_draft_integer_edits_preserve_type(raw: str, expected: int) -> None:
    result = _coerce_like(4, raw)
    assert result == expected
    assert type(result) is int


@pytest.mark.parametrize("raw", ["5.0", "5.5", "1e2", "nan", "inf", "-inf", "1e999"])
def test_draft_integer_edits_ignore_non_integer_text(raw: str) -> None:
    assert _coerce_like(4, raw) is None


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "+Infinity", "-inf", "1e999", "-1e999"])
def test_draft_float_edits_ignore_non_finite_text(raw: str) -> None:
    assert _coerce_like(4.0, raw) is None


@pytest.mark.parametrize(
    "raw, expected", [("5", 5.0), (" 0 ", 0.0), ("-2.5", -2.5), ("1e2", 100.0)]
)
def test_draft_float_edits_preserve_finite_values(raw: str, expected: float) -> None:
    result = _coerce_like(4.0, raw)
    assert result == expected
    assert type(result) is float


@pytest.mark.parametrize("current", [4, 4.0])
@pytest.mark.parametrize("raw", ["", "  ", "invalid"])
def test_draft_numeric_edits_ignore_blank_or_invalid_text(current: object, raw: str) -> None:
    assert _coerce_like(current, raw) is None


@pytest.mark.parametrize("raw, expected", [("true", True), ("0", False)])
def test_draft_boolean_edits_remain_boolean(raw: str, expected: bool) -> None:
    assert _coerce_like(False, raw) is expected


@pytest.fixture
def env() -> Generator[tuple[TestClient, sessionmaker[Session], str], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override() -> Generator[Session, None, None]:
        s = factory()
        try:
            yield s
        finally:
            s.close()

    with factory() as session:
        user = get_or_create_local_dev_user(session)
        learner = create_learner_for_user(session, user_id=user.id, display_name="Drafter")
        for spec in ipo_surge_2026.all_items():
            session.add(prepare_draft(spec, learner_id=learner.id))
        session.commit()
        learner_id = learner.id

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, factory, learner_id
    finally:
        client.close()
        app.dependency_overrides.clear()


def _draft(factory: sessionmaker[Session], *, item_type: str) -> MaintenanceItem:
    with factory() as session:
        return session.scalars(
            select(MaintenanceItem).where(
                MaintenanceItem.item_type == item_type, MaintenanceItem.status == "draft"
            )
        ).first()


def test_drafts_are_never_scheduled_before_approval(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """The whole point: a drafted item must not reach the review loop."""
    client, factory, learner_id = env

    maintenance = client.get("/app/learner/maintenance")

    assert "Nothing due right now" in maintenance.text
    assert count_pending_drafts_for(factory, learner_id) == 6
    # And the maintenance home points at the waiting queue.
    assert "draft(s) awaiting approval" in maintenance.text


def count_pending_drafts_for(factory: sessionmaker[Session], learner_id: str) -> int:
    with factory() as session:
        return count_pending_drafts(session, learner_id=learner_id)


def test_queue_separates_transcribed_fields_from_inferred_judgment(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """The reviewer must see which fields the source supports and which it does not."""
    client, factory, _learner = env
    anchor = _draft(factory, item_type="reference_anchor")

    view = describe_draft(anchor)
    transcribed = {field.name for field in view.transcribed}
    inferred = {field.name for field in view.inferred}

    # The median came from the quoted snippet.
    assert "central_value" in transcribed
    # The band did NOT — it is the drafter's judgment and grades the item for years.
    assert {"typical_low", "typical_high"} <= inferred

    page = client.get(DRAFTS)
    assert "Check against the source" in page.text
    assert "Your judgment — not in the source" in page.text
    # The source snippet is shown so verification is a glance, not a re-read.
    assert "25-year median of IPOs per year is around 100" in page.text


def test_anchors_require_individual_review_and_ideas_do_not(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Risk-tiered rigor: a wrong number is memorised, a weak key point is not."""
    _client, factory, _learner = env
    anchor = _draft(factory, item_type="reference_anchor")
    idea = _draft(factory, item_type="idea")

    assert describe_draft(anchor).needs_individual_review
    assert not describe_draft(idea).needs_individual_review


def test_bulk_approve_takes_ideas_and_refuses_anchors(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Even if an anchor id is submitted to the bulk route, it must not pass."""
    client, factory, learner_id = env
    with factory() as session:
        ids = [
            item.id
            for item in session.scalars(
                select(MaintenanceItem).where(MaintenanceItem.status == "draft")
            ).all()
        ]

    response = client.post(f"{DRAFTS}/approve-ideas", data={"item_id": ids})

    assert response.status_code == 303
    with factory() as session:
        active = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).all()
        still_draft = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "draft")
        ).all()
    assert {item.item_type for item in active} == {"idea"}
    assert {item.item_type for item in still_draft} == {"reference_anchor"}


def test_approving_an_anchor_activates_it_and_it_becomes_due(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Approval is what lets an item enter the loop."""
    client, factory, _learner = env
    anchor = _draft(factory, item_type="reference_anchor")

    response = client.post(f"{DRAFTS}/approve", data={"item_id": anchor.id})

    assert response.status_code == 303
    with factory() as session:
        refreshed = session.get(MaintenanceItem, anchor.id)
    assert refreshed.status == "active"
    assert refreshed.approved_at is not None
    assert refreshed.draft_expires_at is None
    assert "US IPO count per year" in client.get("/app/learner/maintenance").text


def test_edits_made_during_approval_are_applied_and_attributed(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Fixing a band on approval must stick, and be marked as the owner's call."""
    client, factory, _learner = env
    anchor = _draft(factory, item_type="reference_anchor")

    client.post(
        f"{DRAFTS}/approve",
        data={"item_id": anchor.id, "payload.typical_high": "180", "retention_tier": "warm"},
    )

    with factory() as session:
        refreshed = session.get(MaintenanceItem, anchor.id)
    assert refreshed.payload["typical_high"] == 180
    assert refreshed.retention_tier == "warm"
    assert refreshed.field_provenance["typical_high"] == "owner-edited"


@pytest.mark.parametrize(
    "current, raw, expected, edited",
    [
        (4, "5", 5, True),
        (4.0, "5.5", 5.5, True),
        (4, "5.5", 4, False),
        (4, "nan", 4, False),
        (4.0, "nan", 4.0, False),
        (4.0, "inf", 4.0, False),
        (4.0, "-inf", 4.0, False),
        (4.0, "1e999", 4.0, False),
    ],
)
def test_approval_persists_numeric_types_and_ignores_invalid_edits(
    env: tuple[TestClient, sessionmaker[Session], str],
    current: int | float,
    raw: str,
    expected: int | float,
    edited: bool,
) -> None:
    client, factory, _learner = env
    anchor = _draft(factory, item_type="reference_anchor")
    with factory() as session:
        item = session.get(MaintenanceItem, anchor.id)
        assert item is not None
        item.payload = {**item.payload, "typical_high": current}
        original_provenance = item.field_provenance.get("typical_high")
        session.commit()

    response = client.post(
        f"{DRAFTS}/approve", data={"item_id": anchor.id, "payload.typical_high": raw}
    )

    assert response.status_code == 303
    with factory() as session:
        refreshed = session.get(MaintenanceItem, anchor.id)
        assert refreshed is not None
        assert refreshed.status == "active"
        assert refreshed.payload["typical_high"] == expected
        assert type(refreshed.payload["typical_high"]) is type(expected)
        assert refreshed.field_provenance.get("typical_high") == (
            "owner-edited" if edited else original_provenance
        )


def test_rejection_discards_the_item_and_keeps_the_reason(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Reject is one click; the reason is optional but retained when given."""
    client, factory, learner_id = env
    idea = _draft(factory, item_type="idea")

    client.post(f"{DRAFTS}/reject", data={"item_id": idea.id, "reason": "Too vague to grade."})

    with factory() as session:
        assert session.get(MaintenanceItem, idea.id) is None
        rejections = session.scalars(select(DraftRejection)).all()
        assert [r.reason for r in rejections] == ["Too vague to grade."]
        assert rejections[0].disposition == "rejected"
        assert rejection_guidance(session, learner_id=learner_id) == ["Too vague to grade."]


def test_expired_drafts_lapse_instead_of_accumulating(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """A draft you never got to is evidence you did not want it."""
    _client, factory, learner_id = env
    later = datetime.now(UTC) + timedelta(days=DRAFT_TTL_DAYS + 1)

    with factory() as session:
        cleared = expire_stale_drafts(session, learner_id=learner_id, now=later)
        session.commit()
        assert cleared == 6
        assert count_pending_drafts(session, learner_id=learner_id, now=later) == 0
        dispositions = {r.disposition for r in session.scalars(select(DraftRejection)).all()}
    # Lapsing is recorded distinctly from an explicit rejection.
    assert dispositions == {"expired"}


def test_pending_cap_makes_a_backlog_structurally_impossible(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Past the cap, drafting refuses rather than growing the queue."""
    _client, factory, learner_id = env
    with factory() as session:
        assert can_accept_drafts(session, learner_id=learner_id, wanted=1)
        filler = PENDING_DRAFT_CAP - count_pending_drafts(session, learner_id=learner_id)
        for index in range(filler):
            session.add(
                prepare_draft(
                    {
                        "item_type": "idea",
                        "title": f"Filler {index}",
                        "prompt": "?",
                        "payload": {"key_points": []},
                    },
                    learner_id=learner_id,
                )
            )
        session.commit()

        assert count_pending_drafts(session, learner_id=learner_id) == PENDING_DRAFT_CAP
        assert not can_accept_drafts(session, learner_id=learner_id, wanted=1)


def test_default_band_is_a_visible_rule_not_a_hidden_guess() -> None:
    """An anchor without an explicit band gets +/-25%, which the owner can override."""
    low, high = default_band(100)
    assert (low, high) == (75.0, 125.0)

    item = prepare_draft(
        {
            "item_type": "reference_anchor",
            "title": "Bandless",
            "prompt": "?",
            "payload": {"central_value": 80, "metric": "m", "unit": "u"},
        },
        learner_id="L1",
    )

    assert item.payload["typical_low"] == 60.0
    assert item.payload["typical_high"] == 100.0
    assert item.field_provenance["typical_low"] == "inferred"
    assert item.field_provenance["central_value"] == "source"


@pytest.mark.parametrize("central_value", [float("nan"), float("inf"), float("-inf")])
def test_default_band_rejects_non_finite_central_values(central_value: float) -> None:
    with pytest.raises(ValueError, match="central_value must be finite"):
        default_band(central_value)


@pytest.mark.parametrize("fraction", [float("nan"), float("inf"), float("-inf"), 0.0, -0.25])
def test_default_band_rejects_invalid_fractions(fraction: float) -> None:
    with pytest.raises(ValueError, match="fraction must be a positive finite float"):
        default_band(100, fraction=fraction)


@pytest.mark.parametrize(
    ("central_value", "fraction"), [(1e308, 2.0), (-1e308, 2.0), (1.7e308, 0.25)]
)
def test_default_band_rejects_overflow(central_value: float, fraction: float) -> None:
    with pytest.raises(ValueError, match="default band bounds must be finite"):
        default_band(central_value, fraction=fraction)


@pytest.mark.parametrize(
    ("central_value", "expected"),
    [(100.0, (90.0, 110.0)), (-100.0, (-110.0, -90.0)), (0.0, (0.0, 0.0))],
)
def test_default_band_preserves_finite_values(
    central_value: float, expected: tuple[float, float]
) -> None:
    assert default_band(central_value, fraction=0.1) == expected


@pytest.mark.parametrize(
    "central_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        "nan",
        "Infinity",
        "-Infinity",
        "1e999",
        "invalid",
        [],
        pytest.param(10**1000, id="overflowing-integer"),
    ],
)
@pytest.mark.parametrize("supplied_band", [False, True])
def test_prepare_draft_rejects_invalid_central_values(
    central_value: object, supplied_band: bool
) -> None:
    payload = {"central_value": central_value, "metric": "m", "unit": "u"}
    if supplied_band:
        payload.update(typical_low=60.0, typical_high=100.0)
    original = payload.copy()
    with pytest.raises(ValueError, match="central_value must be a finite number"):
        prepare_draft(
            {
                "item_type": "reference_anchor",
                "title": "Invalid",
                "prompt": "?",
                "payload": payload,
            },
            learner_id="L1",
        )
    assert payload == original


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("supplied_band", [False, True])
def test_prepare_draft_requires_central_value(missing: bool, supplied_band: bool) -> None:
    payload: dict[str, object] = {"metric": "m", "unit": "u"}
    if not missing:
        payload["central_value"] = None
    if supplied_band:
        payload.update(typical_low=60.0, typical_high=100.0)
    original = payload.copy()

    with pytest.raises(ValueError, match="central_value must be a finite number"):
        prepare_draft(
            {
                "item_type": "reference_anchor",
                "title": "Invalid",
                "prompt": "?",
                "payload": payload,
            },
            learner_id="L1",
        )

    assert payload == original


@pytest.mark.parametrize("central_value", [80, 80.0, "80"])
@pytest.mark.parametrize("supplied_band", [False, True])
def test_prepare_draft_preserves_finite_central_values(
    central_value: object, supplied_band: bool
) -> None:
    payload = {"central_value": central_value, "metric": "m", "unit": "u"}
    if supplied_band:
        payload.update(typical_low=70.0, typical_high=90.0)
    original = payload.copy()
    item = prepare_draft(
        {"item_type": "reference_anchor", "title": "Finite", "prompt": "?", "payload": payload},
        learner_id="L1",
    )
    assert item.payload["central_value"] == central_value
    assert (item.payload["typical_low"], item.payload["typical_high"]) == (
        (70.0, 90.0) if supplied_band else (60.0, 100.0)
    )
    assert payload == original


def test_prepare_draft_sets_an_expiry() -> None:
    """Every draft is born with a deadline."""
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    item = prepare_draft(
        {"item_type": "idea", "title": "t", "prompt": "?", "payload": {"key_points": []}},
        learner_id="L1",
        now=now,
    )

    assert item.draft_expires_at == now + timedelta(days=DRAFT_TTL_DAYS)
    assert item.status == "draft"


def test_another_learners_draft_is_not_reachable(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, _learner = env
    with factory() as session:
        other = create_learner_for_user(
            session,
            user_id=get_or_create_local_dev_user(session).id,
            display_name="Someone else",
        )
        foreign = prepare_draft(
            {"item_type": "idea", "title": "Not yours", "prompt": "?", "payload": {}},
            learner_id=other.id,
        )
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id

    assert client.post(f"{DRAFTS}/approve", data={"item_id": foreign_id}).status_code == 404
    assert client.post(f"{DRAFTS}/reject", data={"item_id": foreign_id}).status_code == 404


def test_approving_a_nonexistent_draft_is_refused(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, _factory, _learner = env
    assert client.post(f"{DRAFTS}/approve", data={"item_id": "nope"}).status_code == 404


def test_service_level_approve_and_reject_round_trip(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Direct service use mirrors the HTTP behavior."""
    _client, factory, learner_id = env
    with factory() as session:
        drafts = list_pending_drafts(session, learner_id=learner_id)
        assert len(drafts) == 6
        approve_draft(session, item=drafts[0].item)
        reject_draft(session, item=drafts[1].item, reason="nope")
        session.commit()
        assert count_pending_drafts(session, learner_id=learner_id) == 4


@pytest.fixture(params=["sqlite", "postgresql"])
def concurrent_draft_store(request, tmp_path: Path):
    """Use a file DB or an isolated schema on an explicitly supplied test PG."""
    backend = request.param
    schema = "draft_admission_" + uuid.uuid4().hex
    admin = None
    if backend == "postgresql":
        url = os.environ.get("LMS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("LMS_TEST_POSTGRES_URL is needed for real PostgreSQL concurrency")
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'draft-admission.db'}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory() as session:
            user = get_or_create_local_dev_user(session)
            learner = create_learner_for_user(session, user_id=user.id, display_name="Concurrent")
            session.commit()
            learner_id = learner.id
        yield factory, learner_id
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.mark.parametrize("pending,wanted,winners", [(39, 1, 1), (38, 2, 1), (39, 2, 0), (0, 21, 1)])
def test_concurrent_load_respects_pending_draft_cap(
    concurrent_draft_store, pending: int, wanted: int, winners: int
) -> None:
    """Competing full-batch admissions hold the learner lock through commit."""
    factory, learner_id = concurrent_draft_store
    spec = {"item_type": "idea", "title": "Concurrent", "prompt": "?", "payload": {}}
    with factory() as session:
        session.add_all([prepare_draft(spec, learner_id=learner_id) for _ in range(pending)])
        session.commit()
        original_updated = session.get(Learner, learner_id).updated_at

    # Exercise rollback on each real backend before competing for the same slots.
    # Flushing proves rollback releases persisted drafts, not just unsaved objects.
    with factory() as session:
        remaining = PENDING_DRAFT_CAP - pending
        assert reserve_draft_capacity(session, learner_id=learner_id, wanted=remaining)
        session.add_all([prepare_draft(spec, learner_id=learner_id) for _ in range(remaining)])
        session.flush()
        assert count_pending_drafts(session, learner_id=learner_id) == PENDING_DRAFT_CAP
        session.rollback()
    with factory() as session:
        assert count_pending_drafts(session, learner_id=learner_id) == pending
        assert session.get(Learner, learner_id).updated_at == original_updated

    first_checked = threading.Event()
    second_started = threading.Event()
    second_checked = threading.Event()
    release_first = threading.Event()
    results = Queue()

    def load_batch(first: bool) -> None:
        try:
            if not first and not first_checked.wait(timeout=10):
                raise TimeoutError("first loader did not reach admission")
            with factory() as session:
                if not first:
                    second_started.set()
                accepted = reserve_draft_capacity(session, learner_id=learner_id, wanted=wanted)
                if first:
                    first_checked.set()
                else:
                    second_checked.set()
                if accepted:
                    for _ in range(wanted):
                        session.add(prepare_draft(spec, learner_id=learner_id))
                if first and not release_first.wait(timeout=10):
                    raise TimeoutError("first loader was not released")
                session.commit()
                results.put(accepted)
        except Exception as exc:
            results.put(exc)
            first_checked.set()

    threads = [threading.Thread(target=load_batch, args=(first,)) for first in (True, False)]
    for thread in threads:
        thread.start()
    try:
        assert second_started.wait(timeout=10), "second loader did not start"
        stale_admission = second_checked.wait(timeout=0.5)
    finally:
        release_first.set()
        for thread in threads:
            thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    outcomes = [results.get_nowait() for _ in threads]
    assert all(isinstance(value, bool) for value in outcomes), outcomes
    with factory() as session:
        count = count_pending_drafts(session, learner_id=learner_id)
        assert session.get(Learner, learner_id).updated_at == original_updated
    assert count <= PENDING_DRAFT_CAP, (count, outcomes)
    assert sum(outcomes) == winners
    assert count == pending + winners * wanted
    assert not stale_admission, "second admission read before first transaction ended"


def test_cli_load_reserves_the_full_batch(
    env: tuple[TestClient, sessionmaker[Session], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    from contextlib import contextmanager

    import lms.__main__ as cli
    import lms.maintenance.drafts as drafts

    _client, factory, learner_id = env
    calls = []

    @contextmanager
    def scope():
        with factory.begin() as session:
            yield session

    def observe(session, **kwargs):
        calls.append(kwargs)
        return reserve_draft_capacity(session, **kwargs)

    monkeypatch.setattr(cli, "session_scope", scope)
    monkeypatch.setattr(drafts, "reserve_draft_capacity", observe)
    with factory() as session:
        from lms.auth.models import User

        username = session.scalar(select(User.username))
    cli._dispatch_maintenance(
        argparse.Namespace(
            maintenance_command="load-seed",
            seed="ipo_surge_2026",
            username=username,
            activate=False,
        ),
        parser=argparse.ArgumentParser(),
    )
    assert calls == [{"learner_id": learner_id, "wanted": len(ipo_surge_2026.all_items())}]
    with factory() as session:
        assert count_pending_drafts(session, learner_id=learner_id) == 12


def test_reserved_draft_batch_rolls_back_with_outer_transaction(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    _client, factory, learner_id = env
    with factory() as session:
        original_updated = session.get(Learner, learner_id).updated_at
        assert reserve_draft_capacity(session, learner_id=learner_id, wanted=34)
        session.add_all(
            [prepare_draft(ipo_surge_2026.all_items()[0], learner_id=learner_id) for _ in range(34)]
        )
        session.flush()
        assert count_pending_drafts(session, learner_id=learner_id) == 40
        session.rollback()
    with factory() as session:
        assert count_pending_drafts(session, learner_id=learner_id) == 6
        assert session.get(Learner, learner_id).updated_at == original_updated
        assert reserve_draft_capacity(session, learner_id=learner_id, wanted=34)
