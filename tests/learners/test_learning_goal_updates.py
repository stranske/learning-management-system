"""Partial updates to a learning goal, where `None` means "leave this alone".

`update_learning_goal` takes every field as optional and falls back to the goal's current value.
That shape has one characteristic failure: a broken fallback silently BLANKS a field the caller
never mentioned, and the write succeeds. Nothing raises, and the goal simply loses its status or
its knowledge type.

Its validation is the other half. The choices are checked against the RESULTING values rather
than the supplied ones, so changing one field cannot leave the goal in a combination no code path
would have accepted at creation.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.repository import create_local_user
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import (
    create_learner_for_user,
    create_learning_goal,
    update_learning_goal,
)


@pytest.fixture()
def goal(db_session: Session):
    user = create_local_user(db_session, username="ada", display_name="Ada Lovelace")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Ada")
    node = create_knowledge_node(
        db_session,
        title="Retrieval practice",
        knowledge_type="procedural",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    return create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Original title",
        knowledge_type="procedural",
        target_node_ids=[node.id],
        ownership_scope="personal",
        status="active",
    )


# ---------------------------------------------------------------------------------------------
# Each field changes on its own, and nothing else moves with it.
# ---------------------------------------------------------------------------------------------


def test_the_title_changes_alone(db_session: Session, goal) -> None:
    update_learning_goal(db_session, goal, title="New title")
    assert goal.title == "New title"
    assert goal.knowledge_type == "procedural"
    assert goal.ownership_scope == "personal"
    assert goal.status == "active"


def test_the_status_changes_alone(db_session: Session, goal) -> None:
    update_learning_goal(db_session, goal, status="paused")
    assert goal.status == "paused"
    assert goal.title == "Original title"
    assert goal.knowledge_type == "procedural"


def test_the_knowledge_type_changes_alone(db_session: Session, goal) -> None:
    update_learning_goal(db_session, goal, knowledge_type="conceptual")
    assert goal.knowledge_type == "conceptual"
    assert goal.status == "active"


def test_an_update_that_supplies_nothing_changes_nothing(db_session: Session, goal) -> None:
    """The purest form of the fallback bug: every field must survive a no-op call.

    A broken fallback shows up here as a goal that loses its status or knowledge type after an
    update that named neither.
    """
    before = (goal.title, goal.knowledge_type, goal.ownership_scope, goal.status)
    update_learning_goal(db_session, goal)
    assert (goal.title, goal.knowledge_type, goal.ownership_scope, goal.status) == before


def test_several_fields_change_together(db_session: Session, goal) -> None:
    update_learning_goal(
        db_session, goal, title="Both", knowledge_type="factual", status="completed"
    )
    assert goal.title == "Both"
    assert goal.knowledge_type == "factual"
    assert goal.status == "completed"


# ---------------------------------------------------------------------------------------------
# Validation, against the resulting values rather than the supplied ones.
# ---------------------------------------------------------------------------------------------


def test_an_unknown_knowledge_type_is_refused(db_session: Session, goal) -> None:
    with pytest.raises(ValueError, match="unknown knowledge type"):
        update_learning_goal(db_session, goal, knowledge_type="telepathic")


def test_an_unknown_status_is_refused(db_session: Session, goal) -> None:
    with pytest.raises(ValueError, match="unknown goal status"):
        update_learning_goal(db_session, goal, status="nearly-done")


def test_an_unknown_ownership_scope_is_refused(db_session: Session, goal) -> None:
    with pytest.raises(ValueError, match="unknown ownership scope"):
        update_learning_goal(db_session, goal, ownership_scope="communal")


def test_a_refused_update_leaves_the_goal_untouched(db_session: Session, goal) -> None:
    """Validation runs BEFORE any assignment, so a rejected call cannot half-apply.

    Assigning first and validating second would leave the goal carrying the new title alongside
    its old status — a state no creation path could produce.
    """
    with pytest.raises(ValueError):
        update_learning_goal(db_session, goal, title="Should not stick", status="bogus")
    assert goal.title == "Original title"
    assert goal.status == "active"


def test_the_error_names_the_value_and_the_alternatives(db_session: Session, goal) -> None:
    """An operator fixing a bad payload needs to know what was wrong and what is allowed."""
    with pytest.raises(ValueError) as excinfo:
        update_learning_goal(db_session, goal, status="bogus")
    message = str(excinfo.value)
    assert "bogus" in message
    assert "active" in message, "the permitted values must be listed"


@pytest.mark.parametrize("status", ["active", "paused", "completed", "archived"])
def test_every_declared_status_is_accepted(status: str, db_session: Session, goal) -> None:
    """The constant is the contract. A declared value the validator rejects is a status no
    learner can ever reach."""
    update_learning_goal(db_session, goal, status=status)
    assert goal.status == status


@pytest.mark.parametrize(
    "knowledge_type",
    ["factual", "conceptual", "procedural", "judgment", "metacognitive", "social", "compliance"],
)
def test_every_declared_knowledge_type_is_accepted(
    knowledge_type: str, db_session: Session, goal
) -> None:
    update_learning_goal(db_session, goal, knowledge_type=knowledge_type)
    assert goal.knowledge_type == knowledge_type
