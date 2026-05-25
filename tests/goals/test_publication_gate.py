"""Tests for publication-gated learning targets."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_node, require_published_prompt_target


def test_prompt_target_rejects_draft_node(db_session: Session) -> None:
    """Prompt authoring cannot target draft knowledge nodes."""
    node = create_knowledge_node(
        db_session,
        title="Draft concept",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="draft",
    )

    with pytest.raises(ValueError, match="published knowledge nodes"):
        require_published_prompt_target(db_session, node_id=node.id, scope="personal")


def test_prompt_target_accepts_published_node(db_session: Session) -> None:
    """Published knowledge nodes pass the prompt-target gate."""
    node = create_knowledge_node(
        db_session,
        title="Published concept",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )

    assert require_published_prompt_target(db_session, node_id=node.id, scope="personal") == node
