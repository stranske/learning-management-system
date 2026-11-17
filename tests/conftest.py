"""Shared pytest fixtures for LMS tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401  # register Base.metadata
import lms.capability.models  # noqa: F401  # register Base.metadata
import lms.cases.models  # noqa: F401  # register Base.metadata
import lms.competencies.models  # noqa: F401  # register Base.metadata
import lms.evidence.models  # noqa: F401  # register Base.metadata
import lms.feedback.models  # noqa: F401  # register Base.metadata
import lms.graphs.models  # noqa: F401  # register Base.metadata
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401  # register Base.metadata
import lms.llm.proposals  # noqa: F401  # register Base.metadata
import lms.maintenance.models  # noqa: F401  # register Base.metadata
import lms.prompts.models  # noqa: F401  # register Base.metadata
import lms.scheduling.models  # noqa: F401  # register Base.metadata
import lms.sources.models  # noqa: F401  # register Base.metadata
from lms.db.base import Base
from lms.graphs.models import KnowledgeNode
from lms.learners.models import LearningGoal
from lms.prompts.models import Prompt, PromptVersion
from lms.prompts.repository import publish_prompt
from lms.sources.models import SourceReference


@pytest.fixture
def db_session() -> Generator[Session]:
    """Provide an isolated SQLAlchemy session for model-level tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def published_prompt(db_session: Session) -> Prompt:
    """Persist a versioned prompt for attempt-context and delayed-scoring tests."""
    node = KnowledgeNode(
        id="node-1",
        title="Algebra",
        knowledge_type="procedural",
        ownership_scope="personal",
        status="published",
    )
    goal = LearningGoal(
        id="goal-1",
        learner_id="learner-1",
        title="Explain algebra",
        knowledge_type="procedural",
        ownership_scope="personal",
        target_nodes=[node],
    )
    prompt = Prompt(
        id="prompt-1",
        target_node=node,
        learning_goal=goal,
        knowledge_type="procedural",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        authoring_method="human-authored",
        authoring_actor="author-1",
        source_references=[
            SourceReference(
                id="source-1",
                source_type="markdown-file",
                stable_locator="docs/algebra.md",
                content_hash="hash-1",
                source_visibility="public",
                drift_status="current",
            )
        ],
        versions=[
            PromptVersion(
                id="prompt-version-1",
                version_number=1,
                body="Explain the algebra step.",
                created_by="author-1",
            )
        ],
    )
    db_session.add(prompt)
    db_session.flush()
    publish_prompt(db_session, prompt, reviewing_actor="reviewer-1")
    db_session.commit()
    return prompt
