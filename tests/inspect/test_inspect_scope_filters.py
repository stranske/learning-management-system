"""Inspect overview scope filtering coverage."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.auth.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.api.inspect import learner_overview_route
from lms.db.base import Base
from lms.graphs.models import KnowledgeNode
from lms.learners.models import LearningGoal
from lms.prompts.models import Prompt
from lms.sources.models import SourceReference


def test_overview_honors_ownership_scope_for_prompts_and_sources() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = session_factory()
    try:
        node_personal = KnowledgeNode(
            id="node-personal-overview",
            title="Personal Overview Node",
            knowledge_type="factual",
            ownership_scope="personal",
        )
        node_institutional = KnowledgeNode(
            id="node-institutional-overview",
            title="Institutional Overview Node",
            knowledge_type="factual",
            ownership_scope="institutional",
        )
        goal_personal = LearningGoal(
            id="goal-personal-overview",
            learner_id="learner-overview",
            title="Personal Goal",
            knowledge_type="factual",
            ownership_scope="personal",
        )
        goal_institutional = LearningGoal(
            id="goal-institutional-overview",
            learner_id="learner-overview",
            title="Institutional Goal",
            knowledge_type="factual",
            ownership_scope="institutional",
        )
        source_personal = SourceReference(
            id="source-personal-overview",
            source_type="internal-note",
            stable_locator="notes://personal",
            content_hash="a" * 64,
            source_visibility="public",
            drift_status="current",
        )
        source_institutional = SourceReference(
            id="source-institutional-overview",
            source_type="internal-note",
            stable_locator="notes://institutional",
            content_hash="b" * 64,
            source_visibility="public",
            drift_status="current",
        )
        source_unlinked = SourceReference(
            id="source-unlinked-overview",
            source_type="internal-note",
            stable_locator="notes://unlinked",
            content_hash="c" * 64,
            source_visibility="public",
            drift_status="current",
        )
        prompt_personal = Prompt(
            id="prompt-personal-overview",
            target_node_id=node_personal.id,
            learning_goal_id=goal_personal.id,
            knowledge_type="factual",
            intended_cognitive_action="recall",
            demand_level="medium",
            expected_answer_form="short-text",
            status="draft",
            authoring_method="human-authored",
            authoring_actor="author-1",
        )
        prompt_institutional = Prompt(
            id="prompt-institutional-overview",
            target_node_id=node_institutional.id,
            learning_goal_id=goal_institutional.id,
            knowledge_type="factual",
            intended_cognitive_action="recall",
            demand_level="medium",
            expected_answer_form="short-text",
            status="draft",
            authoring_method="human-authored",
            authoring_actor="author-2",
        )
        prompt_personal.source_references.append(source_personal)
        prompt_institutional.source_references.append(source_institutional)
        session.add_all(
            [
                node_personal,
                node_institutional,
                goal_personal,
                goal_institutional,
                source_personal,
                source_institutional,
                source_unlinked,
                prompt_personal,
                prompt_institutional,
            ]
        )
        session.commit()

        personal_payload = learner_overview_route(
            "learner-overview",
            session,
            ownership_scope="personal",
        )
        institutional_payload = learner_overview_route(
            "learner-overview",
            session,
            ownership_scope="institutional",
        )

        assert {row["id"] for row in personal_payload["prompt_provenance"]} == {
            "prompt-personal-overview"
        }
        assert {row["id"] for row in institutional_payload["prompt_provenance"]} == {
            "prompt-institutional-overview"
        }
        assert {row["id"] for row in personal_payload["source_drift"]} == {
            "source-personal-overview",
            "source-unlinked-overview",
        }
        assert {row["id"] for row in institutional_payload["source_drift"]} == {
            "source-institutional-overview",
            "source-unlinked-overview",
        }
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
