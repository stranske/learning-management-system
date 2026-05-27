"""HTML contract tests for the learner home dashboard surface."""

from __future__ import annotations

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
from lms.feedback.repository import create_feedback_action
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user
from lms.scheduling.service import seed_new_learning_item

_FIXED_LABEL_OR_ACCELERATION = (
    "low ability",
    "high ability",
    "advanced learner",
    "slow learner",
    "learn faster",
    "10x",
)
_PUNITIVE = (
    "you are behind",
    "failing",
    "must catch up",
    "lazy",
    "low ability",
)


def test_dashboard_shows_next_actions_reviews_and_recent_evidence(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        create_feedback_action(
            session,
            learner_id="learner-1",
            action_type="retry",
            title="Revisit the retrieval-practice prompt",
            instructions="Try the prompt again without opening the reference.",
        )
        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-spacing",
            knowledge_type="conceptual",
            normalized_score=0.9,
            correctness=True,
        )
        seed_new_learning_item(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-spacing",
        )
        session.commit()

    response = client.get("/app/learner?learner_id=learner-1")

    assert response.status_code == 200
    html = response.text
    # Next actions
    assert "Next actions" in html
    assert "Revisit the retrieval-practice prompt" in html
    # Due reviews
    assert "Due reviews" in html
    assert "new-learning" in html
    # Recent evidence
    assert "Recent evidence" in html
    assert "node-spacing" in html
    # Mastery shows model attribution and evidence count
    assert "Deterministic placeholder policy inspired by FSRS 4.5" in html
    assert "evidence count 1" in html
    # Links into attempt flow and review queue
    assert 'href="/learn"' in html
    assert 'href="/app/learner/review"' in html
    # Shared shell + mobile viewport (M6-001)
    assert 'name="viewport"' in html
    assert 'href="/static/ui/app.css"' in html
    assert 'href="/app/learner" aria-current="page"' in html
    lowered = html.lower()
    for phrase in _FIXED_LABEL_OR_ACCELERATION:
        assert phrase not in lowered


def test_dashboard_empty_states_are_specific_and_nonpunitive(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    response = client.get("/app/learner?learner_id=empty-learner")

    assert response.status_code == 200
    html = response.text
    assert "You have no open follow-up actions right now." in html
    assert "Nothing is due for review today." in html
    assert "No attempts are recorded yet." in html
    assert "You have not set any learning goals yet." in html
    assert "Mastery estimates appear once you have collected evidence." in html
    assert "No capability targets yet." in html
    assert "No maintenance-plan steps yet." in html
    assert 'name="viewport"' in html
    lowered = html.lower()
    for phrase in _PUNITIVE:
        assert phrase not in lowered


def test_dashboard_shows_capability_targets_and_maintenance_plan_steps(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        user = User(
            email="dashboard@example.test",
            username="dashboard-learner",
            display_name="Dashboard Learner",
        )
        session.add(user)
        session.flush()
        learner = create_learner_for_user(
            session,
            user_id=user.id,
            display_name="Dashboard Learner",
        )
        node = create_knowledge_node(
            session,
            title="Explain remediation tradeoffs",
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
            normalized_score=0.35,
            correctness=False,
        )
        target = create_capability_target(
            session,
            learner_id=learner.id,
            title="Explain remediation tradeoffs",
            target_node_ids=[node.id],
            required_evidence_types=["rubric-score"],
            confidence_threshold=0.8,
        )
        estimate = recompute_capability_estimate(session, target_id=target.id)
        analysis = create_gap_analysis(session, estimate_id=estimate.id)
        create_maintenance_plan(session, gap_analysis_id=analysis.id)
        learner_id = learner.id
        session.commit()

    response = client.get(f"/app/learner?learner_id={learner_id}")

    assert response.status_code == 200
    html = response.text
    assert "Capability targets" in html
    assert "Explain remediation tradeoffs" in html
    assert "Maintenance plan" in html
    assert "Step 1:" in html
