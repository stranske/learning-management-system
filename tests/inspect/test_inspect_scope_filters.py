"""Inspect overview scope filtering coverage."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.auth.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.api.inspect import learner_overview_route
from lms.auth.models import User
from lms.db.base import Base
from lms.evidence.repository import create_evidence_record
from lms.graphs.models import KnowledgeNode
from lms.learners.models import LearningGoal
from lms.prompts.models import Prompt
from lms.scheduling.models import ReviewQueueItem, SchedulerDecision
from lms.settings import Settings
from lms.sources.models import SourceReference


def test_overview_honors_ownership_scope_for_every_panel() -> None:
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
        due_at = datetime(2026, 5, 31, 15, 0, tzinfo=UTC)
        queue_personal = ReviewQueueItem(
            learner_id="learner-overview",
            knowledge_node_id=node_personal.id,
            reason_code="due-review",
            reason_explanation="Personal review due.",
            due_at=due_at,
            priority=0.9,
            status="pending",
            decision_log={"scope": "personal"},
        )
        queue_institutional = ReviewQueueItem(
            learner_id="learner-overview",
            knowledge_node_id=node_institutional.id,
            reason_code="remediation",
            reason_explanation="Institutional remediation due.",
            due_at=due_at,
            priority=0.8,
            status="pending",
            decision_log={"scope": "institutional"},
        )
        decision_personal = SchedulerDecision(
            learner_id="learner-overview",
            knowledge_node_id=node_personal.id,
            reason_code="due-review",
            decision_rationale="Personal cadence selected.",
            policy_version="2026.05",
            knowledge_type="factual",
            ownership_scope="personal",
            support_level="none",
            decision_log={"scope": "personal"},
        )
        decision_institutional = SchedulerDecision(
            learner_id="learner-overview",
            knowledge_node_id=node_institutional.id,
            reason_code="remediation",
            decision_rationale="Institutional remediation selected.",
            policy_version="2026.05",
            knowledge_type="factual",
            ownership_scope="institutional",
            support_level="hint",
            decision_log={"scope": "institutional"},
        )
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
                queue_personal,
                queue_institutional,
                decision_personal,
                decision_institutional,
            ]
        )
        session.flush()
        for node in (node_personal, node_institutional):
            create_evidence_record(
                session,
                learner_id="learner-overview",
                knowledge_node_id=node.id,
                confidence_rating=5,
                correctness=node.ownership_scope == "personal",
            )
        session.commit()

        personal_payload = learner_overview_route(
            "learner-overview",
            session,
            current_user=User(
                username="local-inspect", display_name="Local Inspect", is_local=True
            ),
            settings=Settings(auth_required=False),
            ownership_scope="personal",
        )
        institutional_payload = learner_overview_route(
            "learner-overview",
            session,
            current_user=User(
                username="local-inspect", display_name="Local Inspect", is_local=True
            ),
            settings=Settings(auth_required=False),
            ownership_scope="institutional",
        )

        for scope, payload in (
            ("personal", personal_payload),
            ("institutional", institutional_payload),
        ):
            assert {r["knowledge_node_id"] for r in payload["recent_evidence"]} == {
                "node-" + scope + "-overview"
            }
            assert {r["knowledge_node_id"] for r in payload["mastery"]} == {
                "node-" + scope + "-overview"
            }
            assert payload["calibration"]["sample_size"] == 1
            assert payload["calibration"]["buckets"][0]["observed_accuracy"] == (
                1.0 if scope == "personal" else 0.0
            )
            assert {event["knowledge_node_id"] for event in payload["scheduler"]["events"]} == {
                "node-" + scope + "-overview"
            }
            assert {
                decision["knowledge_node_id"] for decision in payload["scheduler"]["decisions"]
            } == {"node-" + scope + "-overview"}
            assert payload["scheduler"]["ownership_scope"] == scope
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
