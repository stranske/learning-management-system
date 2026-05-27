"""Contract tests for author-side learning object routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import User
from lms.graphs.models import KnowledgeNode
from lms.graphs.repository import create_knowledge_node
from lms.learners.models import LearningGoal
from lms.learners.repository import create_learner_for_user
from lms.sources.repository import create_source_reference


def test_author_can_create_goal_node_edge_and_prompt_from_ui(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        user = User(username="author", display_name="Author")
        session.add(user)
        session.flush()
        learner = create_learner_for_user(
            session,
            user_id=user.id,
            display_name="Demo learner",
        )
        source = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="demo://source/one",
            content="prototype source",
            actor_id="test-author",
        )
        session.commit()
        learner_id = learner.id
        source_id = source.id

    node_response = client.post(
        "/app/author/knowledge/nodes",
        data={
            "title": "Explain spaced retrieval",
            "description": "Learner can explain why retrieval spacing matters.",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "published",
            "source_reference_id": source_id,
        },
    )
    assert node_response.status_code == 200
    assert "Knowledge node saved." in node_response.text
    assert "Explain spaced retrieval" in node_response.text

    with session_factory() as session:
        node_id = session.query(KnowledgeNode).filter_by(title="Explain spaced retrieval").one().id

    goal_response = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Master retrieval practice",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": node_id,
        },
    )
    assert goal_response.status_code == 200
    assert "Goal saved." in goal_response.text
    assert "Master retrieval practice" in goal_response.text

    with session_factory() as session:
        goal_id = session.query(LearningGoal).filter_by(title="Master retrieval practice").one().id

    prompt_response = client.post(
        "/app/author/prompts",
        data={
            "learning_goal_id": goal_id,
            "target_node_id": node_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "source_reference_ids": source_id,
            "authoring_actor": "test-author",
            "body": "Explain why spaced retrieval helps memory.",
        },
    )
    assert prompt_response.status_code == 200
    assert "Prompt saved as draft." in prompt_response.text
    assert "Explain why spaced retrieval helps memory." in prompt_response.text
    assert "provenance Provenance: human-authored; author test-author" in prompt_response.text
    assert "drift current" in client.get("/app/author/prompts").text


def test_author_ui_blocks_cross_scope_normal_edge(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        personal = create_knowledge_node(
            session,
            title="Personal node",
            knowledge_type="conceptual",
            scope="personal",
            actor_id="test-author",
            status="published",
        )
        institutional = create_knowledge_node(
            session,
            title="Institutional node",
            knowledge_type="conceptual",
            scope="institutional",
            actor_id="test-author",
            status="published",
        )
        session.commit()
        personal_id = personal.id
        institutional_id = institutional.id

    response = client.post(
        "/app/author/knowledge/edges",
        data={
            "source_node_id": personal_id,
            "target_node_id": institutional_id,
            "ownership_scope": "personal",
            "target_scope": "institutional",
            "edge_type": "prerequisite",
            "status": "draft",
            "confidence": "0.7",
        },
    )

    assert response.status_code == 200
    assert "cross-scope edges require is_graph_reference=True" in response.text
