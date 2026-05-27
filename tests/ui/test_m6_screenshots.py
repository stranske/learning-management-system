"""HTML snapshot tests for every M6 web-prototype surface.

These tests render each M6 surface through the FastAPI ``TestClient`` and write
the rendered HTML to ``docs/screenshots/`` as a committed artifact. They are the
required, browser-free smoke layer for M6: they document each surface's layout
and empty/sparse-data state and prove every surface carries mobile viewport
metadata. The richer visual + accessibility harness (Playwright) is scaffolded
separately in :mod:`tests.ui.test_playwright_smoke` and stays deferred until a
later milestone activates it. See ``docs/development/web-prototype.md`` for the
trade-off rationale.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.audit.repository import record_audit_event
from lms.auth.models import User, utc_now
from lms.capability.repository import (
    create_capability_target,
    recompute_capability_estimate,
)
from lms.cases.repository import create_case
from lms.evidence.models import Attempt
from lms.evidence.repository import create_evidence_record
from lms.feedback.models import FeedbackAction
from lms.feedback.repository import create_feedback_record, create_rubric
from lms.graphs.repository import create_knowledge_node
from lms.learners.models import Learner
from lms.learners.repository import create_learning_goal
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.models import SourceReference

SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "docs" / "screenshots"

# Static M6 surfaces keyed by snapshot slug. Each renders without a seeded path
# parameter; the feedback-detail surface is appended at runtime once a feedback
# record id is known.
M6_SURFACES: tuple[tuple[str, str], ...] = (
    ("learner-dashboard", "/app/learner"),
    ("learn-attempt", "/learn?prompt_id=prompt-1"),
    ("attempt-flow", "/app/learner/attempts?prompt_id=prompt-1"),
    ("review-queue", "/app/learner/reviews"),
    ("feedback", "/app/learner/feedback"),
    ("llm-study", "/app/learner/llm-study"),
    ("capability-gap", "/app/learner/capability"),
    ("author-home", "/app/author"),
    ("author-goals", "/app/author/goals"),
    ("author-knowledge", "/app/author/knowledge"),
    ("author-prompts", "/app/author/prompts"),
    ("author-rubrics", "/app/author/rubrics"),
    ("author-feedback-templates", "/app/author/feedback-templates"),
    ("author-cases", "/app/author/cases"),
    ("author-graph", "/app/author/graph"),
    ("support", "/app/support"),
    ("admin", "/app/admin"),
)

FEEDBACK_DETAIL_SLUG = "feedback-detail"

_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    flags=re.IGNORECASE,
)

# Every snapshot slug the suite is expected to produce, used as the contract for
# the artifact-existence and viewport-metadata assertions.
EXPECTED_SLUGS: tuple[str, ...] = tuple(slug for slug, _ in M6_SURFACES) + (FEEDBACK_DETAIL_SLUG,)

# A learner whose id matches the surfaces' default ``learner_id`` query so the
# default routes render the seeded learner's own evidence.
_LEARNER_ID = "learner-1"


def _seed_representative_data(session: Session) -> str:
    """Seed sparse but representative data for the M6 surfaces.

    Returns the id of a seeded feedback record so the feedback-detail surface can
    be rendered against real data.
    """
    user = User(username="rae", display_name="Rae Learner", email="rae@example.test")
    session.add(user)
    session.flush()
    session.add(
        Learner(
            id=_LEARNER_ID,
            user_id=user.id,
            display_name="Rae Learner",
            timezone="UTC",
            locale="en-US",
        )
    )
    session.flush()

    node = create_knowledge_node(
        session,
        title="Explain spacing effects",
        description="A representative published node for demo snapshots.",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    goal = create_learning_goal(
        session,
        learner_id=_LEARNER_ID,
        title="Use spacing to retain key ideas",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
        status="active",
    )

    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator="https://example.test/source",
        passage_range="L1-L4",
        content_hash="hash-123",
        source_visibility="public",
        drift_status="current",
    )
    prompt = Prompt(
        id="prompt-1",
        target_node_id=node.id,
        learning_goal_id=goal.id,
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="published",
        authoring_method="human-authored",
        authoring_actor="author-1",
        reviewing_actor="reviewer-1",
        approval_timestamp=utc_now(),
        source_references=[source],
    )
    prompt.versions.append(
        PromptVersion(
            version_number=1,
            body="Explain the retrieval practice idea.",
            created_by="author-1",
        )
    )
    session.add(prompt)
    session.flush()

    attempt = Attempt(
        learner_id=_LEARNER_ID,
        prompt_id=prompt.id,
        response_text="Spacing reviews strengthen recall over time.",
        confidence_rating=3,
        feedback={"goal": "Improve the response", "next_action": "Revise"},
    )
    session.add(attempt)
    session.flush()

    record = create_feedback_record(
        session,
        learner_id=_LEARNER_ID,
        attempt_id=attempt.id,
        prompt_id=prompt.id,
        feedback_level="remediation",
        goal="Use source evidence to explain the decision",
        observed_evidence="The response named a conclusion without evidence.",
        gap="Missing source-backed reasoning",
    )
    session.add(
        FeedbackAction(
            learner_id=_LEARNER_ID,
            feedback_record_id=record.id,
            action_type="revision",
            status="open",
            title="Revise with one cited reason",
            instructions="Add the source-backed reason before resubmitting.",
        )
    )

    create_evidence_record(
        session,
        learner_id=_LEARNER_ID,
        knowledge_node_id=node.id,
        knowledge_type="conceptual",
        confidence_rating=2,
        reference_accessed=True,
        hint_used=True,
        support_level="hint",
        normalized_score=0.4,
        correctness=False,
    )

    target = create_capability_target(
        session,
        learner_id=_LEARNER_ID,
        title="Apply spacing in a study plan",
        target_node_ids=[node.id],
    )
    recompute_capability_estimate(session, target_id=target.id)

    create_rubric(
        session,
        title="Evidence use",
        description="Scores whether a response cites supporting evidence.",
        ownership_scope="personal",
        status="published",
        authoring_actor="author-1",
        criteria=[
            {
                "criterion_order": 1,
                "description": "Uses source evidence",
                "max_points": 4.0,
                "validity_scope": None,
                "performance_levels": {"meets": "Complete and sourced"},
            }
        ],
    )
    create_case(
        session,
        title="Plan a spaced review",
        description="A sparse demo transfer case.",
        ownership_scope="personal",
        rubric_id=None,
        knowledge_node_id=None,
        status="draft",
        steps=[
            {
                "step_order": 1,
                "title": "Draft a plan",
                "prompt": "Outline a spaced-review schedule for one topic.",
                "expected_work_product": "memo",
            }
        ],
        evidence_packets=[
            {
                "title": "Source notes",
                "summary": "Representative evidence packet.",
                "packet_metadata": {"source": "author"},
            }
        ],
    )

    record_audit_event(
        session,
        actor_id="user:rae",
        action="create",
        entity_type="KnowledgeNode",
        entity_id=node.id,
        source_subsystem="author-ui",
        after_summary={"title": "Explain spacing effects"},
    )

    session.commit()
    return record.id


def _render_surfaces(client: TestClient, session_factory: sessionmaker[Session]) -> dict[str, str]:
    """Seed data, render every M6 surface, write artifacts, and return the HTML.

    The returned mapping is keyed by snapshot slug so callers can assert on the
    rendered markup without re-reading the files from disk.
    """
    with session_factory() as session:
        feedback_record_id = _seed_representative_data(session)

    surfaces = list(M6_SURFACES) + [
        (FEEDBACK_DETAIL_SLUG, f"/app/learner/feedback/{feedback_record_id}")
    ]

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    rendered: dict[str, str] = {}
    for slug, path in surfaces:
        response = client.get(path)
        assert response.status_code == 200, f"{slug} ({path}) returned {response.status_code}"
        html = _snapshot_html(response.text)
        (SCREENSHOT_DIR / f"m6-{slug}.html").write_text(html, encoding="utf-8")
        rendered[slug] = html
    return rendered


def _snapshot_html(html: str) -> str:
    """Remove per-run UUID values so committed snapshots stay idempotent."""
    return _UUID_PATTERN.sub("snapshot-id", html)


@pytest.mark.parametrize("api_client", [True], indirect=True)
def test_m6_surface_html_snapshot_artifacts_exist(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    _render_surfaces(client, session_factory)

    for slug in EXPECTED_SLUGS:
        artifact = SCREENSHOT_DIR / f"m6-{slug}.html"
        assert artifact.is_file(), f"missing HTML snapshot artifact for {slug}"
        assert artifact.read_text(encoding="utf-8").lstrip().startswith("<!doctype html>")


@pytest.mark.parametrize("api_client", [True], indirect=True)
def test_all_m6_surfaces_include_mobile_viewport(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    rendered = _render_surfaces(client, session_factory)

    assert set(rendered) == set(EXPECTED_SLUGS)
    for slug, html in rendered.items():
        assert 'name="viewport"' in html, f"{slug} is missing mobile viewport metadata"
        assert "width=device-width" in html, f"{slug} viewport is not mobile-width"


def _load_playwright_smoke_module() -> ModuleType:
    """Import the Playwright smoke scaffold by path without installing it as a package."""
    path = Path(__file__).with_name("test_playwright_smoke.py")
    spec = importlib.util.spec_from_file_location("m6_playwright_smoke_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_playwright_smoke_is_importable_and_skipped_by_default() -> None:
    # Importing the module (which never imports playwright at module scope) proves
    # the scaffold is importable without the deferred [visual] dependency.
    module = _load_playwright_smoke_module()
    assert callable(module.test_learner_dashboard_renders_at_mobile_width)

    mark = module.playwright_only.mark
    assert mark.name == "skipif"
    assert mark.kwargs["reason"] == (
        "Playwright harness scaffolded; activate with PLAYWRIGHT_AVAILABLE=1"
    )
    # Skipped by default: the skip condition is truthy exactly when the activation
    # flag is unset in the environment.
    assert bool(mark.args[0]) == (not os.environ.get("PLAYWRIGHT_AVAILABLE"))
