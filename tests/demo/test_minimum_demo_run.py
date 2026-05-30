"""Tests for ``lms demo run`` — the real-persistence Minimum Demo path (#181).

These tests verify two properties the issue spec calls out explicitly:

1. The seed writes real rows through the actual repository writers, not the
   smoke fixture's hard-coded dataclasses. We assert this by querying the
   persistence layer via ``select(...)`` and matching the issue's count
   thresholds (≥10 source references, ≥30 prompts, ≥1 attempt+evidence per
   prompt, ≥4 distinct REASON_CODES).

2. The printed summary numbers equal the DB query results — proving no
   hard-coded tuples leak into the live path. We do this by running the
   seed, then by comparing the live summary's field values against direct
   ``select(count(...))`` queries against the same session.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Register all model modules so Base.metadata.create_all picks them up.
import lms.audit.models  # noqa: F401
import lms.cases.models  # noqa: F401
import lms.competencies.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.feedback.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.llm.proposals  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.demo import compute_live_demo_summary, render_live_demo_summary
from lms.demo_seed import (
    SEED_NOTE_COUNT,
    SEED_PROMPT_COUNT,
    SEED_REASON_CODES,
    seed_minimum_demo,
)
from lms.evidence.models import Attempt, EvidenceRecord
from lms.llm.models import LLMSession
from lms.prompts.models import Prompt
from lms.scheduling.models import ReviewQueueItem
from lms.sources.models import SourceReference


@pytest.fixture
def demo_session() -> Generator[Session, None, None]:
    """An in-memory SQLite session with the full schema applied."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_demo_run_writes_real_rows_through_repositories(demo_session: Session) -> None:
    """The seeder produces real rows that meet the issue's count thresholds."""
    result = seed_minimum_demo(demo_session)
    demo_session.commit()

    # Issue acceptance criterion: ≥10 source references.
    source_count = demo_session.scalar(select(func.count(SourceReference.id))) or 0
    assert source_count >= 10, source_count
    assert source_count == SEED_NOTE_COUNT, "seed dimensions drifted"

    # ≥30 prompts.
    prompt_count = demo_session.scalar(select(func.count(Prompt.id))) or 0
    assert prompt_count >= 30, prompt_count
    assert prompt_count == SEED_PROMPT_COUNT, "seed dimensions drifted"

    # ≥1 attempt + ≥1 evidence per prompt.
    attempt_count = demo_session.scalar(select(func.count(Attempt.id))) or 0
    evidence_count = demo_session.scalar(select(func.count(EvidenceRecord.id))) or 0
    assert attempt_count >= prompt_count, (attempt_count, prompt_count)
    assert evidence_count >= prompt_count, (evidence_count, prompt_count)
    # Stronger: exactly one attempt + one evidence per prompt in the seeder.
    assert attempt_count == prompt_count
    assert evidence_count == prompt_count

    # All seeded reason codes are present and they're valid DB codes.
    codes_rows = demo_session.execute(
        select(ReviewQueueItem.reason_code).distinct().order_by(ReviewQueueItem.reason_code)
    ).all()
    codes = {row[0] for row in codes_rows}
    # The issue lists conceptual codes (some from the smoke fixture's fake
    # vocabulary). We assert the production-schema equivalents: each of the
    # four codes seeded by demo_seed.SEED_REASON_CODES must be present.
    for code in SEED_REASON_CODES:
        assert code in codes, f"missing reason code: {code}"
    assert len(codes) >= 4

    # SeedResult bookkeeping matches.
    assert len(result.source_reference_ids) == SEED_NOTE_COUNT
    assert len(result.prompt_ids) == SEED_PROMPT_COUNT
    assert len(result.attempt_ids) == SEED_PROMPT_COUNT
    assert len(result.evidence_record_ids) == SEED_PROMPT_COUNT
    assert len(result.review_queue_item_ids) == len(SEED_REASON_CODES)
    assert len(result.llm_session_ids) >= 1


def test_demo_run_summary_counts_match_direct_db_queries(demo_session: Session) -> None:
    """The printed live summary equals what the DB actually holds — no hardcoded tuples."""
    seed_minimum_demo(demo_session)
    demo_session.commit()

    summary = compute_live_demo_summary(demo_session)

    # Each summary field must equal a fresh count() query against the same DB.
    assert summary.source_reference_count == (
        demo_session.scalar(select(func.count(SourceReference.id))) or 0
    )
    assert summary.prompt_count == (demo_session.scalar(select(func.count(Prompt.id))) or 0)
    assert summary.attempt_count == (demo_session.scalar(select(func.count(Attempt.id))) or 0)
    assert summary.evidence_record_count == (
        demo_session.scalar(select(func.count(EvidenceRecord.id))) or 0
    )

    distinct_codes = sorted(
        row[0] for row in demo_session.execute(select(ReviewQueueItem.reason_code).distinct()).all()
    )
    assert summary.review_reason_codes == tuple(distinct_codes)

    inspect_count = demo_session.scalar(
        select(func.count(func.distinct(EvidenceRecord.knowledge_node_id)))
    )
    assert summary.inspect_row_count == (inspect_count or 0)

    coach_count = demo_session.scalar(
        select(func.count(LLMSession.id)).where(LLMSession.mode == "study-coach")
    )
    assert summary.study_coach_session_count == (coach_count or 0)

    cost_total = demo_session.scalar(
        select(func.coalesce(func.sum(LLMSession.cost_micro_usd), 0)).where(
            LLMSession.mode == "study-coach"
        )
    )
    assert summary.daily_cost_micro_usd == int(cost_total or 0)


def test_demo_run_summary_renders_in_smoke_compatible_format(demo_session: Session) -> None:
    """The live renderer's line shape matches the smoke renderer (one entry per requirement)."""
    seed_minimum_demo(demo_session)
    demo_session.commit()

    summary = compute_live_demo_summary(demo_session)
    rendered = render_live_demo_summary(summary)

    # The header explicitly distinguishes ``run`` from ``smoke`` so log
    # consumers can tell which path produced the output.
    assert rendered.startswith("minimum demo run: ok")
    # Every required count line is present.
    expected_count_keys = (
        "notes=",
        "prompts=",
        "attempts=",
        "evidence_rows=",
        "review_queue_reason_codes=",
        "inspect_rows=",
        "study_coach_sessions=",
        "daily_cost_micro_usd=",
    )
    for key in expected_count_keys:
        assert key in rendered, f"missing line for {key}"

    # And the numeric values must match the summary dataclass (so the
    # renderer can't sneak in a constant).
    assert f"notes={summary.source_reference_count}" in rendered
    assert f"prompts={summary.prompt_count}" in rendered
    assert f"attempts={summary.attempt_count}" in rendered
    assert f"evidence_rows={summary.evidence_record_count}" in rendered
    assert f"inspect_rows={summary.inspect_row_count}" in rendered
    assert f"study_coach_sessions={summary.study_coach_session_count}" in rendered
    assert f"daily_cost_micro_usd={summary.daily_cost_micro_usd}" in rendered


def test_demo_run_evidence_rows_each_have_a_knowledge_node(demo_session: Session) -> None:
    """Inspect mastery sits on knowledge_node_id — each evidence row must populate it.

    This guards a wiring property: if the seeder ever stops passing
    ``knowledge_node_id`` to ``create_attempt(... evidence=...)``, the Inspect
    surface would see zero rows even though ``EvidenceRecord`` rows exist.
    """
    seed_minimum_demo(demo_session)
    demo_session.commit()

    rows = demo_session.execute(select(EvidenceRecord.id, EvidenceRecord.knowledge_node_id)).all()
    assert len(rows) > 0
    for evidence_id, node_id in rows:
        assert node_id, f"evidence {evidence_id} missing knowledge_node_id"
