"""Export/import coverage for M5 runtime records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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
import lms.learners.models  # noqa: F401  # register Base.metadata
import lms.llm.models  # noqa: F401  # register Base.metadata
import lms.prompts.models  # noqa: F401  # register Base.metadata
import lms.scheduling.models  # noqa: F401  # register Base.metadata
import lms.sources.models  # noqa: F401  # register Base.metadata
from lms.auth.models import User
from lms.capability.models import CapabilityEstimate, CapabilityTarget, GapAnalysis, MaintenancePlan
from lms.cases.models import Case, CaseStep, DecisionPoint, EvidencePacket
from lms.competencies.models import Competency, CompetencyEvidence
from lms.db.base import Base
from lms.evidence.models import Attempt, EvidenceRecord
from lms.export_import import ExportImportError, export_jsonl, import_jsonl
from lms.feedback.models import (
    FeedbackAction,
    FeedbackRecord,
    MisconceptionPattern,
    Rubric,
    RubricCriterion,
    RubricScore,
)
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner, LearningGoal
from lms.llm.models import LLMSession
from lms.prompts.models import Prompt, PromptVersion
from lms.scheduling.models import (
    RemediationTrigger,
    ReviewPolicy,
    ReviewQueueItem,
    ReviewSchedule,
    SchedulerDecision,
)
from lms.sources.models import SourceReference


def test_export_import_round_trip_m5_runtime_records(tmp_path: Path, db_session: Session) -> None:
    _seed_m5_runtime_records(db_session)

    lines = list(export_jsonl(db_session))
    records = [json.loads(line) for line in lines]

    assert [record["type"] for record in records][-21:] == [
        "Competency",
        "CompetencyEvidence",
        "FeedbackRecord",
        "FeedbackAction",
        "MisconceptionPattern",
        "Rubric",
        "RubricCriterion",
        "RubricScore",
        "Case",
        "CaseStep",
        "EvidencePacket",
        "DecisionPoint",
        "ReviewQueueItem",
        "ReviewPolicy",
        "ReviewSchedule",
        "RemediationTrigger",
        "SchedulerDecision",
        "CapabilityTarget",
        "CapabilityEstimate",
        "GapAnalysis",
        "MaintenancePlan",
    ]
    by_type = {record["type"]: record["record"] for record in records}
    assert by_type["CapabilityTarget"]["target_node_ids"] == ["node-1"]
    assert by_type["CapabilityTarget"]["target_competency_ids"] == ["competency-1"]
    assert by_type["CapabilityEstimate"]["commentary"] == (
        "[redacted: inferred capability commentary]"
    )
    assert by_type["EvidencePacket"]["packet_metadata"] == {}

    path = tmp_path / "m5.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    target_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        dry_run = import_jsonl(target_session, path, dry_run=True)
        applied = import_jsonl(target_session, path, dry_run=False)
        target_session.commit()

        assert dry_run.counts["MaintenancePlan"] == 1
        assert applied.counts["RubricScore"] == 1
        assert target_session.get(MaintenancePlan, "maintenance-plan-1") is not None
        imported_target = target_session.get(CapabilityTarget, "capability-target-1")
        assert imported_target is not None
        assert [node.id for node in imported_target.target_nodes] == ["node-1"]
        assert [competency.id for competency in imported_target.target_competencies] == [
            "competency-1"
        ]
    finally:
        target_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_dry_run_rejects_missing_m5_runtime_dependency(tmp_path: Path, db_session: Session) -> None:
    path = tmp_path / "missing-gap.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "MaintenancePlan",
                "schema_version": 1,
                "record": {
                    "id": "maintenance-plan-1",
                    "target_id": "target-1",
                    "gap_analysis_id": "missing-gap",
                    "learner_id": "learner-1",
                    "status": "active",
                    "plan_steps": [],
                    "schedule_ids": [],
                    "rationale": "test",
                    "ownership_scope": "personal",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    try:
        import_jsonl(db_session, path, dry_run=True)
    except ExportImportError as exc:
        assert "references missing CapabilityTarget:target-1" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected missing M5 dependency failure")


def _seed_m5_runtime_records(session: Session) -> None:
    now = datetime(2026, 5, 26, tzinfo=UTC)
    user = User(id="user-1", username="ada", display_name="Ada")
    learner = Learner(id="learner-1", user_id=user.id, display_name="Ada")
    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator="docs/demo.md#one",
        content_hash="hash",
        source_visibility="local-only",
    )
    node = KnowledgeNode(
        id="node-1",
        title="Node",
        knowledge_type="conceptual",
        ownership_scope="personal",
        status="published",
        provenance="manual",
        source_reference_id=source.id,
    )
    goal = LearningGoal(
        id="goal-1",
        learner_id=learner.id,
        title="Goal",
        knowledge_type="conceptual",
        ownership_scope="personal",
    )
    goal.target_nodes.append(node)
    prompt = Prompt(
        id="prompt-1",
        target_node_id=node.id,
        learning_goal_id=goal.id,
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="author",
    )
    prompt.source_references.append(source)
    prompt_version = PromptVersion(
        id="prompt-version-1",
        prompt_id=prompt.id,
        version_number=1,
        body="Explain the node.",
        created_by="author",
    )
    llm_session = LLMSession(
        id="llm-1",
        mode="practice",
        trace_class="evidence-grade",
        provider="fake",
        model="fake-model",
        learner_id=learner.id,
        response_summary="evidence-grade summary",
        external_export_allowed=True,
    )
    attempt = Attempt(
        id="attempt-1",
        learner_id=learner.id,
        prompt_id=prompt.id,
        response_text="answer",
        feedback={"summary": "needs remediation"},
        llm_session_id=llm_session.id,
    )
    evidence = EvidenceRecord(
        id="evidence-1",
        attempt_id=attempt.id,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        prompt_id=prompt.id,
        prompt_version_id=prompt_version.id,
        correctness=False,
        support_level="hint",
    )
    competency = Competency(
        id="competency-1",
        title="Competency",
        ownership_scope="personal",
        target_knowledge_type="conceptual",
        status="active",
    )
    competency_evidence = CompetencyEvidence(
        id="competency-evidence-1",
        competency_id=competency.id,
        knowledge_node_id=node.id,
        evidence_record_id=evidence.id,
        learner_id=learner.id,
        evidence_role="demonstrates",
    )
    feedback = FeedbackRecord(
        id="feedback-record-1",
        learner_id=learner.id,
        attempt_id=attempt.id,
        prompt_id=prompt.id,
        evidence_record_id=evidence.id,
        feedback_level="remediation",
        goal="Improve transfer",
        observed_evidence="Missed prerequisite.",
        source_feedback={"summary": "retry prerequisite"},
    )
    feedback_action = FeedbackAction(
        id="feedback-action-1",
        feedback_record_id=feedback.id,
        learner_id=learner.id,
        attempt_id=attempt.id,
        prompt_id=prompt.id,
        action_type="prerequisite-remediation",
        title="Review prerequisite",
    )
    pattern = MisconceptionPattern(
        id="pattern-1",
        pattern_label="Prerequisite miss",
        wrong_answer_signature="confuses prior concept",
        diagnosis_text="Review prerequisite node.",
        target_knowledge_node_id=node.id,
        ownership_scope="personal",
        confidence=0.9,
        suggested_feedback_action_type="prerequisite-remediation",
    )
    rubric = Rubric(
        id="rubric-1",
        title="Rubric",
        ownership_scope="personal",
        prompt_id=prompt.id,
        knowledge_node_id=node.id,
        status="draft",
        authoring_actor="author",
    )
    criterion = RubricCriterion(
        id="criterion-1",
        rubric_id=rubric.id,
        criterion_order=1,
        description="Accurate explanation",
        max_points=4,
        performance_levels={"4": "complete"},
    )
    score = RubricScore(
        id="rubric-score-1",
        rubric_id=rubric.id,
        attempt_id=attempt.id,
        learner_id=learner.id,
        scorer_type="rule",
        raw_score=2,
        normalized_score=0.5,
        max_score=4,
        criterion_scores=[{"criterion_id": criterion.id, "score": 2}],
        evidence_record_id=evidence.id,
        feedback_record_id=feedback.id,
    )
    case = Case(
        id="case-1",
        title="Transfer case",
        ownership_scope="personal",
        rubric_id=rubric.id,
        knowledge_node_id=node.id,
        status="draft",
    )
    case_step = CaseStep(
        id="case-step-1",
        case_id=case.id,
        step_order=1,
        title="Choose evidence",
        prompt="Select the relevant evidence.",
    )
    packet = EvidencePacket(
        id="evidence-packet-1",
        case_id=case.id,
        title="Packet",
        source_reference_id=source.id,
        packet_metadata={"local_body": "private packet detail"},
    )
    decision_point = DecisionPoint(
        id="decision-point-1",
        case_step_id=case_step.id,
        evidence_packet_id=packet.id,
        title="Decision",
        prompt="What should happen next?",
        decision_type="free-response",
    )
    queue_item = ReviewQueueItem(
        id="queue-item-1",
        learner_id=learner.id,
        knowledge_node_id=node.id,
        reason_code="remediation",
        reason_explanation="Prerequisite gap",
        due_at=now,
        priority=0.8,
        source_attempt_id=attempt.id,
        source_evidence_record_id=evidence.id,
        decision_log={"source": "test"},
    )
    policy = ReviewPolicy(
        id="review-policy-1",
        name="Remediation",
        policy_version="m5-test",
        reason_code="remediation",
        settings={"interval": "now"},
    )
    schedule = ReviewSchedule(
        id="review-schedule-1",
        learner_id=learner.id,
        knowledge_node_id=node.id,
        review_policy_id=policy.id,
        review_queue_item_id=queue_item.id,
        reason_code="remediation",
        due_at=now,
        policy_version="m5-test",
        source_evidence_record_id=evidence.id,
    )
    trigger = RemediationTrigger(
        id="trigger-1",
        pattern_id=pattern.id,
        knowledge_node_id=node.id,
        trigger_type="failed-prerequisite",
        trigger_rules={"prerequisite_node_id": node.id},
        ownership_scope="personal",
    )
    decision = SchedulerDecision(
        id="scheduler-decision-1",
        learner_id=learner.id,
        knowledge_node_id=node.id,
        review_policy_id=policy.id,
        review_schedule_id=schedule.id,
        review_queue_item_id=queue_item.id,
        source_evidence_record_id=evidence.id,
        reason_code="remediation",
        decision_rationale="Remediate prerequisite.",
        policy_version="m5-test",
        support_level="hint",
        decision_log={"maintenance_plan_id": "maintenance-plan-1"},
    )
    target = CapabilityTarget(
        id="capability-target-1",
        learner_id=learner.id,
        title="Target",
        ownership_scope="personal",
        learning_goal_id=goal.id,
    )
    target.target_nodes.append(node)
    target.target_competencies.append(competency)
    estimate = CapabilityEstimate(
        id="capability-estimate-1",
        target_id=target.id,
        learner_id=learner.id,
        estimator_version="test",
        current_score=0.45,
        confidence=0.7,
        validity_scope="local demo",
        evidence_breakdown={"evidence-1": "weak"},
        commentary="Private inferred capability commentary.",
        commentary_redaction_class="internal-inferred-mastery",
    )
    gap = GapAnalysis(
        id="gap-analysis-1",
        target_id=target.id,
        estimate_id=estimate.id,
        learner_id=learner.id,
        gap_items=[{"type": "remediation", "knowledge_node_id": node.id}],
        severity="medium",
        recommended_action_types=["remediation"],
    )
    plan = MaintenancePlan(
        id="maintenance-plan-1",
        target_id=target.id,
        gap_analysis_id=gap.id,
        learner_id=learner.id,
        plan_steps=[{"type": "remediation", "scheduler_decision_id": decision.id}],
        schedule_ids=[schedule.id],
        rationale="Close the prerequisite gap.",
    )

    session.add_all(
        [
            user,
            learner,
            source,
            node,
            goal,
            prompt,
            prompt_version,
            llm_session,
            attempt,
            evidence,
            competency,
            competency_evidence,
            feedback,
            feedback_action,
            pattern,
            rubric,
            criterion,
            score,
            case,
            case_step,
            packet,
            decision_point,
            queue_item,
            policy,
            schedule,
            trigger,
            decision,
            target,
            estimate,
            gap,
            plan,
        ]
    )
    session.commit()
