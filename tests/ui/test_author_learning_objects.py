"""HTML contract tests for the authoring surfaces (issue #110, Surface 3/4)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.learners.models import LearningGoal
from lms.learners.repository import create_learner_for_user
from lms.prompts.models import Prompt
from lms.sources.repository import create_source_reference


def _seed_learner_and_source(session: Session) -> tuple[str, str]:
    learner = create_learner_for_user(
        session,
        user_id="user-1",
        display_name="Author One",
    )
    source = create_source_reference(
        session,
        source_type="url",
        stable_locator="https://example.test/source",
        actor_id="author-1",
        content="grounding passage",
    )
    session.commit()
    return learner.id, source.id


def _create_node(
    client: TestClient,
    *,
    title: str,
    scope: str,
    status: str = "published",
    knowledge_type: str = "conceptual",
) -> None:
    response = client.post(
        "/app/author/knowledge/nodes",
        data={
            "title": title,
            "description": "",
            "knowledge_type": knowledge_type,
            "scope": scope,
            "status": status,
            "actor_id": "author-1",
        },
    )
    assert response.status_code == 200
    assert "Knowledge node created" in response.text


def test_author_can_create_goal_node_edge_and_prompt_from_ui(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, source_id = _seed_learner_and_source(session)

    _create_node(client, title="Photosynthesis basics", scope="personal")
    _create_node(client, title="Cellular respiration", scope="personal")

    with session_factory() as session:
        nodes = {node.title: node.id for node in session.scalars(select(KnowledgeNode)).all()}
    node_a = nodes["Photosynthesis basics"]
    node_b = nodes["Cellular respiration"]

    edge_response = client.post(
        "/app/author/knowledge/edges",
        data={
            "source_node_id": node_a,
            "target_node_id": node_b,
            "edge_type": "prerequisite",
            "scope": "personal",
            "target_scope": "personal",
            "confidence": "0.8",
            "status": "draft",
            "actor_id": "author-1",
        },
    )
    assert edge_response.status_code == 200
    assert "Knowledge edge created" in edge_response.text

    goal_response = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Understand metabolism",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": [node_a, node_b],
        },
    )
    assert goal_response.status_code == 200
    assert "Learning goal created" in goal_response.text

    with session_factory() as session:
        goal_id = session.scalars(select(LearningGoal)).one().id

    prompt_response = client.post(
        "/app/author/prompts",
        data={
            "learner_id": learner_id,
            "learning_goal_id": goal_id,
            "target_node_id": node_a,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "authoring_method": "human-authored",
            "authoring_actor": "author-1",
            "source_reference_ids": [source_id],
            "body": "Explain how photosynthesis supplies inputs for respiration.",
        },
    )
    assert prompt_response.status_code == 200
    assert "Prompt created" in prompt_response.text
    assert "Provenance: human-authored" in prompt_response.text

    with session_factory() as session:
        assert len(session.scalars(select(KnowledgeNode)).all()) == 2
        edges = session.scalars(select(KnowledgeEdge)).all()
        assert len(edges) == 1
        assert edges[0].source_node_id == node_a
        assert edges[0].target_node_id == node_b
        goal = session.scalars(select(LearningGoal)).one()
        assert {node.id for node in goal.target_nodes} == {node_a, node_b}
        prompts = session.scalars(select(Prompt)).all()
        assert len(prompts) == 1
        assert prompts[0].target_node_id == node_a
        assert prompts[0].learning_goal_id == goal_id
        assert prompts[0].status == "draft"
        assert {source.id for source in prompts[0].source_references} == {source_id}


def test_author_ui_blocks_cross_scope_normal_edge(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client
    _create_node(client, title="Personal note", scope="personal")
    _create_node(client, title="Institutional standard", scope="institutional")

    with _session_factory() as session:
        nodes = {node.title: node.id for node in session.scalars(select(KnowledgeNode)).all()}
    personal_id = nodes["Personal note"]
    institutional_id = nodes["Institutional standard"]

    response = client.post(
        "/app/author/knowledge/edges",
        data={
            "source_node_id": personal_id,
            "target_node_id": institutional_id,
            "edge_type": "prerequisite",
            "scope": "personal",
            "target_scope": "institutional",
            "status": "draft",
            "actor_id": "author-1",
        },
    )

    assert response.status_code == 200
    assert "Knowledge edge created" not in response.text
    assert "cross-scope" in response.text
    assert 'aria-invalid="true"' in response.text

    with _session_factory() as session:
        assert session.scalars(select(KnowledgeEdge)).all() == []


def test_author_ui_surfaces_validation_feedback(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        learner_id, _ = _seed_learner_and_source(session)

    _create_node(client, title="Draft topic", scope="personal", status="draft")
    with session_factory() as session:
        draft_id = session.scalars(select(KnowledgeNode)).one().id

    bad_goal = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Premature goal",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": [draft_id],
        },
    )
    assert bad_goal.status_code == 200
    assert "published" in bad_goal.text
    assert 'aria-invalid="true"' in bad_goal.text
    with session_factory() as session:
        assert session.scalars(select(LearningGoal)).all() == []

    _create_node(client, title="Published topic", scope="personal", status="published")
    with session_factory() as session:
        published_id = next(
            node.id
            for node in session.scalars(select(KnowledgeNode)).all()
            if node.title == "Published topic"
        )
    good_goal = client.post(
        "/app/author/goals",
        data={
            "learner_id": learner_id,
            "title": "Sound goal",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "active",
            "target_node_ids": [published_id],
        },
    )
    assert "Learning goal created" in good_goal.text
    with session_factory() as session:
        goal_id = session.scalars(select(LearningGoal)).one().id

    missing_source = client.post(
        "/app/author/prompts",
        data={
            "learner_id": learner_id,
            "learning_goal_id": goal_id,
            "target_node_id": published_id,
            "knowledge_type": "conceptual",
            "intended_cognitive_action": "explain",
            "demand_level": "medium",
            "expected_answer_form": "short-text",
            "authoring_method": "human-authored",
            "authoring_actor": "author-1",
            "body": "Explain the concept.",
        },
    )
    assert missing_source.status_code == 200
    assert "source reference" in missing_source.text
    assert 'aria-invalid="true"' in missing_source.text
    with session_factory() as session:
        assert session.scalars(select(Prompt)).all() == []


def test_author_surfaces_show_empty_states_and_no_curriculum_text(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    knowledge = client.get("/app/author/knowledge")
    goals = client.get("/app/author/goals")
    prompts = client.get("/app/author/prompts")

    assert knowledge.status_code == 200
    assert "No knowledge nodes yet" in knowledge.text
    assert "No knowledge edges yet" in knowledge.text

    assert goals.status_code == 200
    assert "No learning goals yet" in goals.text

    assert prompts.status_code == 200
    assert "No prompts yet" in prompts.text
    assert "No source references yet" in prompts.text

    for page in (knowledge.text, goals.text, prompts.text):
        assert "Course" not in page
        assert "Module" not in page
        assert "Lesson" not in page
        assert "curriculum" not in page
