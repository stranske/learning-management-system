"""Repository tests for prompt version source snapshots on create."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.prompts.repository import create_prompt, get_prompt, prompt_drift_status
from lms.sources.repository import create_source_reference


def _seed_graph_and_source(session: Session, tmp_path: Path) -> dict[str, str]:
    note = tmp_path / "shared.md"
    note.write_text("# Heading\noriginal passage\n", encoding="utf-8")
    node = create_knowledge_node(
        session,
        title="Shared node",
        knowledge_type="conceptual",
        scope="personal",
        status="published",
        actor_id="user:alice",
    )
    learner = create_learner_for_user(session, user_id="user-alice", display_name="Alice")
    goal = create_learning_goal(
        session,
        learner_id=learner.id,
        title="Shared goal",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    source = create_source_reference(
        session,
        source_type="markdown-file",
        stable_locator=str(note),
        passage_range="L2-L2",
        actor_id="user:alice",
    )
    session.commit()
    return {
        "node_id": node.id,
        "goal_id": goal.id,
        "source_id": source.id,
    }


def test_create_prompt_captures_source_snapshots(db_session: Session, tmp_path: Path) -> None:
    """New prompt versions capture immutable hashes for each linked source."""
    ids = _seed_graph_and_source(db_session, tmp_path)
    prompt = create_prompt(
        db_session,
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        body="First prompt",
        source_reference_ids=[ids["source_id"]],
        authoring_method="human-authored",
        authoring_actor="user:alice",
    )
    db_session.commit()
    loaded = get_prompt(db_session, prompt.id)
    assert loaded is not None
    version = loaded.versions[0]
    assert len(version.source_snapshots) == 1
    snapshot = version.source_snapshots[0]
    assert snapshot.source_reference_id == ids["source_id"]
    assert snapshot.content_hash == loaded.source_references[0].content_hash
    assert prompt_drift_status(loaded) == "current"
