"""Repository tests for prompt version source snapshots and drift status."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.prompts.models import Prompt, PromptVersion
from lms.prompts.repository import (
    acknowledge_prompt_drift,
    create_prompt,
    get_prompt,
    prompt_drift_status,
)
from lms.sources.repository import (
    create_source_reference,
    rehash_source_reference,
    scan_source_references,
)


def _seed_graph_and_source(session: Session, tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Return ids dict and the markdown note path for drift scenarios."""
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
    ids = {
        "node_id": node.id,
        "goal_id": goal.id,
        "source_id": source.id,
        "note_path": str(note),
    }
    return ids, note


def _create_draft_prompt(
    session: Session,
    ids: dict[str, str],
    *,
    body: str,
) -> Prompt:
    prompt = create_prompt(
        session,
        target_node_id=ids["node_id"],
        learning_goal_id=ids["goal_id"],
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        body=body,
        source_reference_ids=[ids["source_id"]],
        authoring_method="human-authored",
        authoring_actor="user:alice",
    )
    session.commit()
    return prompt


def _reload_prompt(session: Session, prompt_id: str) -> Prompt:
    loaded = get_prompt(session, prompt_id)
    assert loaded is not None
    return loaded


def test_create_prompt_captures_source_snapshots(db_session: Session, tmp_path: Path) -> None:
    """New prompt versions capture immutable hashes for each linked source."""
    ids, _note = _seed_graph_and_source(db_session, tmp_path)
    prompt = _create_draft_prompt(db_session, ids, body="First prompt")
    loaded = _reload_prompt(db_session, prompt.id)
    version = loaded.versions[0]
    assert len(version.source_snapshots) == 1
    snapshot = version.source_snapshots[0]
    assert snapshot.source_reference_id == ids["source_id"]
    assert snapshot.content_hash == loaded.source_references[0].content_hash
    assert prompt_drift_status(loaded) == "current"


def test_prompt_versions_keep_source_hash_and_flag_drift_per_prompt(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Shared sources flag each prompt independently; acknowledgement is per prompt."""
    ids, note = _seed_graph_and_source(db_session, tmp_path)
    prompt_a = _create_draft_prompt(db_session, ids, body="Prompt A")
    prompt_b = _create_draft_prompt(db_session, ids, body="Prompt B")
    loaded_a = _reload_prompt(db_session, prompt_a.id)
    loaded_b = _reload_prompt(db_session, prompt_b.id)
    snapshot_hash_a = loaded_a.versions[0].source_snapshots[0].content_hash
    snapshot_hash_b = loaded_b.versions[0].source_snapshots[0].content_hash

    note.write_text("# Heading\nchanged passage\n", encoding="utf-8")
    scan_source_references(db_session, base_path=tmp_path, actor_id="system:test")
    db_session.commit()

    reloaded_a = _reload_prompt(db_session, prompt_a.id)
    reloaded_b = _reload_prompt(db_session, prompt_b.id)
    assert prompt_drift_status(reloaded_a) == "stale"
    assert prompt_drift_status(reloaded_b) == "stale"

    source = reloaded_a.source_references[0]
    rehash_source_reference(db_session, source, actor_id="user:alice", base_path=tmp_path)
    db_session.commit()

    after_rehash_a = _reload_prompt(db_session, prompt_a.id)
    after_rehash_b = _reload_prompt(db_session, prompt_b.id)
    assert prompt_drift_status(after_rehash_a) == "stale"
    assert prompt_drift_status(after_rehash_b) == "stale"
    assert after_rehash_a.versions[0].source_snapshots[0].content_hash == snapshot_hash_a
    assert after_rehash_b.versions[0].source_snapshots[0].content_hash == snapshot_hash_b

    acknowledge_prompt_drift(db_session, after_rehash_a, actor_id="user:bob")
    db_session.commit()

    final_a = _reload_prompt(db_session, prompt_a.id)
    final_b = _reload_prompt(db_session, prompt_b.id)
    assert prompt_drift_status(final_a) == "current"
    assert prompt_drift_status(final_b) == "stale"


def test_legacy_prompt_versions_without_snapshots_report_unknown_hash(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Pre-snapshot prompt versions surface unknown drift until acknowledged."""
    ids, _note = _seed_graph_and_source(db_session, tmp_path)
    prompt = _create_draft_prompt(db_session, ids, body="Legacy prompt")
    loaded = db_session.scalar(
        select(Prompt)
        .options(
            selectinload(Prompt.source_references),
            selectinload(Prompt.drift_acknowledgements),
            selectinload(Prompt.versions).selectinload(PromptVersion.source_snapshots),
        )
        .where(Prompt.id == prompt.id)
    )
    assert loaded is not None
    loaded.versions[0].source_snapshots.clear()
    db_session.commit()

    reloaded = _reload_prompt(db_session, prompt.id)
    assert not reloaded.versions[0].source_snapshots
    assert prompt_drift_status(reloaded) == "unknown"


def test_prompt_drift_status_reloads_after_session_close(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Drift state is durable across a fresh ORM load."""
    ids, note = _seed_graph_and_source(db_session, tmp_path)
    prompt = _create_draft_prompt(db_session, ids, body="Fresh session prompt")
    note.write_text("# Heading\nedited once\n", encoding="utf-8")
    scan_source_references(db_session, base_path=tmp_path, actor_id="system:test")
    db_session.commit()
    db_session.expire_all()

    reloaded = _reload_prompt(db_session, prompt.id)
    assert prompt_drift_status(reloaded) == "stale"
