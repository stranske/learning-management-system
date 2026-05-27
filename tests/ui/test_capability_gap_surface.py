"""HTML contract tests for the personal capability and gap-analysis surface."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    create_maintenance_plan,
    recompute_capability_estimate,
)
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user
from lms.ui.capability_gap import (
    CAPABILITY_PATH,
    ESTIMATES_PATH,
    GAP_PATH,
    PLAN_PATH,
    TARGETS_PATH,
)

# Institutional-scope controls and permanent-verdict language that must never
# appear in the personal M6 surface.
_INSTITUTIONAL_CONTROLS = (
    "institutional",
    "manager approval",
    "manager-approval",
    "certification snapshot",
    "recertification",
    "pass/fail",
    "permanent pass",
)


def _seed_learner_with_low_evidence(session: Session) -> tuple[str, str]:
    """Create a learner with one personal node and a single low-score attempt."""
    user = User(
        email="capability@example.test",
        username="capability-learner",
        display_name="Capability Learner",
    )
    session.add(user)
    session.flush()
    learner = create_learner_for_user(
        session,
        user_id=user.id,
        display_name="Capability Learner",
    )
    node = create_knowledge_node(
        session,
        title="Explain spacing effects",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="conceptual",
        normalized_score=0.4,
        correctness=False,
    )
    return learner.id, node.id


def _hidden_value(html: str, name: str) -> str:
    match = re.search(rf"name='{name}' value='([^']+)'", html)
    assert match is not None, f"expected a hidden {name} field in the rendered surface"
    return match.group(1)


def test_capability_surface_creates_target_estimate_gap_and_plan(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        session.commit()

    # Overview starts empty but offers the personal node for selection.
    overview = client.get(f"{CAPABILITY_PATH}?learner_id={learner_id}")
    assert overview.status_code == 200
    assert "No capability targets yet" in overview.text
    assert "Set a capability target" in overview.text
    assert node_id in overview.text

    # Create the personal capability target through the form.
    created = client.post(
        TARGETS_PATH,
        data={
            "learner_id": learner_id,
            "title": "Explain spacing effects",
            "target_node_ids": [node_id],
            "required_evidence_types": "rubric-score",
            "confidence_threshold": "0.8",
        },
    )
    assert created.status_code == 200
    assert "Explain spacing effects" in created.text
    assert "No current estimate yet" in created.text
    target_id = _hidden_value(created.text, "target_id")

    # Recompute the estimate and show the evidence breakdown.
    estimate_resp = client.post(ESTIMATES_PATH, data={"target_id": target_id})
    assert estimate_resp.status_code == 200
    assert "Current capability estimate" in estimate_resp.text
    assert "Current evidence score" in estimate_resp.text
    assert "Evidence breakdown" in estimate_resp.text
    assert "evidence count" in estimate_resp.text
    estimate_id = _hidden_value(estimate_resp.text, "estimate_id")

    # Generate a gap analysis and group the gap items.
    gap_resp = client.post(GAP_PATH, data={"target_id": target_id, "estimate_id": estimate_id})
    assert gap_resp.status_code == 200
    assert "Current gaps" in gap_resp.text
    assert "Weak mastery" in gap_resp.text
    gap_analysis_id = _hidden_value(gap_resp.text, "gap_analysis_id")

    # Create the maintenance plan with scheduled next steps.
    plan_resp = client.post(
        PLAN_PATH, data={"target_id": target_id, "gap_analysis_id": gap_analysis_id}
    )
    assert plan_resp.status_code == 200
    assert "Maintenance plan" in plan_resp.text
    assert "Step 1:" in plan_resp.text
    assert "Scheduled in your review queue." in plan_resp.text
    # Steps link into the review queue and the attempt flow.
    assert 'href="/app/learner/review"' in plan_resp.text
    assert "/app/learner/attempts" in plan_resp.text


def test_capability_surface_uses_current_evidence_language(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        target = create_capability_target(
            session,
            learner_id=learner_id,
            title="Explain spacing effects",
            target_node_ids=[node_id],
            required_evidence_types=["rubric-score"],
            confidence_threshold=0.8,
        )
        estimate = recompute_capability_estimate(session, target_id=target.id)
        analysis = create_gap_analysis(session, estimate_id=estimate.id)
        create_maintenance_plan(session, gap_analysis_id=analysis.id)
        target_id = target.id
        session.commit()

    response = client.get(f"{TARGETS_PATH}/{target_id}")

    assert response.status_code == 200
    html = response.text
    # Cautious present-tense, personal-scope framing.
    assert "Personal scope only." in html
    assert "Current evidence score" in html
    assert "present snapshot, not a permanent certification" in html
    # Institutional-scope controls and permanent-verdict controls are absent.
    lowered = html.lower()
    for phrase in _INSTITUTIONAL_CONTROLS:
        assert phrase not in lowered


def test_capability_surface_hides_institutional_controls_on_create_form(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, _node_id = _seed_learner_with_low_evidence(session)
        session.commit()

    response = client.get(f"{CAPABILITY_PATH}?learner_id={learner_id}")

    assert response.status_code == 200
    html = response.text
    assert "Set a capability target" in html
    # No scope selector / no institutional or ownership_scope control is offered.
    assert "ownership_scope" not in html
    assert 'name="scope"' not in html
    lowered = html.lower()
    for phrase in _INSTITUTIONAL_CONTROLS:
        assert phrase not in lowered


def test_capability_target_create_preserves_zero_confidence_threshold(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        session.commit()

    created = client.post(
        TARGETS_PATH,
        data={
            "learner_id": learner_id,
            "title": "Zero threshold target",
            "target_node_ids": [node_id],
            "confidence_threshold": "0.0",
        },
    )

    assert created.status_code == 200
    assert "Zero threshold target" in created.text
    assert "Confidence threshold: <strong>0%</strong>" in created.text


def test_gap_analysis_action_renders_created_analysis_target(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        source_target = create_capability_target(
            session,
            learner_id=learner_id,
            title="Source target",
            target_node_ids=[node_id],
        )
        other_target = create_capability_target(
            session,
            learner_id=learner_id,
            title="Other target",
            target_node_ids=[node_id],
        )
        estimate = recompute_capability_estimate(session, target_id=source_target.id)
        source_target_id = source_target.id
        other_target_id = other_target.id
        estimate_id = estimate.id
        session.commit()

    response = client.post(
        GAP_PATH,
        data={"target_id": other_target_id, "estimate_id": estimate_id},
    )

    assert response.status_code == 200
    assert "Source target" in response.text
    assert f"name='target_id' value='{source_target_id}'" in response.text
    assert "Other target" not in response.text


def test_capability_surface_empty_states_guide_next_step(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        target = create_capability_target(
            session,
            learner_id=learner_id,
            title="Explain spacing effects",
            target_node_ids=[node_id],
            required_evidence_types=["rubric-score"],
            confidence_threshold=0.8,
        )
        target_id = target.id
        session.commit()

    overview = client.get(f"{CAPABILITY_PATH}?learner_id=empty-learner")
    assert overview.status_code == 200
    assert "No capability targets yet" in overview.text
    assert "Set a personal capability target below" in overview.text

    detail = client.get(f"{TARGETS_PATH}/{target_id}")
    assert detail.status_code == 200
    # A target without an estimate yet tells the learner what to do next.
    assert "No current estimate yet" in detail.text
    assert "once you have collected evidence" in detail.text
    assert "No gap analysis yet" in detail.text
    assert "No maintenance-plan steps yet" in detail.text


def test_capability_target_detail_not_found(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    response = client.get(f"{TARGETS_PATH}/nonexistent-target-id")

    assert response.status_code == 200
    assert "Capability target not found" in response.text


def test_capability_target_create_empty_title_returns_error(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        session.commit()

    response = client.post(
        TARGETS_PATH,
        data={
            "learner_id": learner_id,
            "title": "",
            "target_node_ids": [node_id],
        },
    )

    assert response.status_code == 200
    assert "Enter a title" in response.text
    assert "Set a capability target" in response.text


def test_gap_analysis_action_shows_error_on_invalid_estimate(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        target = create_capability_target(
            session,
            learner_id=learner_id,
            title="Error surface test",
            target_node_ids=[node_id],
        )
        target_id = target.id
        session.commit()

    response = client.post(
        GAP_PATH,
        data={"target_id": target_id, "estimate_id": "nonexistent-estimate-id"},
    )

    assert response.status_code == 200
    assert "Error surface test" in response.text
    assert "capability estimate was not found" in response.text


def test_overview_shows_target_cards_for_learner_with_targets(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, node_id = _seed_learner_with_low_evidence(session)
        create_capability_target(
            session,
            learner_id=learner_id,
            title="My first capability target",
            target_node_ids=[node_id],
        )
        session.commit()

    response = client.get(f"{CAPABILITY_PATH}?learner_id={learner_id}")

    assert response.status_code == 200
    assert "My first capability target" in response.text
    assert f"{TARGETS_PATH}/" in response.text
