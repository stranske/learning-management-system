"""JSONL export and import contract for v1 LMS records."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Table, inspect, select
from sqlalchemy.orm import Session, selectinload

import lms.audit.models  # noqa: F401  # register metadata
import lms.capability.models  # noqa: F401  # register metadata
import lms.cases.models  # noqa: F401  # register metadata
import lms.competencies.models  # noqa: F401  # register metadata
import lms.evidence.models  # noqa: F401  # register metadata
import lms.feedback.models  # noqa: F401  # register metadata
import lms.graphs.models  # noqa: F401  # register metadata
import lms.learners.models  # noqa: F401  # register metadata
import lms.llm.models  # noqa: F401  # register metadata
import lms.prompts.models  # noqa: F401  # register metadata
import lms.scheduling.models  # noqa: F401  # register metadata
import lms.sources.models  # noqa: F401  # register metadata
from lms.auth.models import User
from lms.capability.models import (
    CapabilityEstimate,
    CapabilityTarget,
    GapAnalysis,
    MaintenancePlan,
    capability_target_competencies,
    capability_target_nodes,
)
from lms.cases.models import Case, CaseStep, DecisionPoint, EvidencePacket
from lms.competencies.models import Competency, CompetencyEvidence
from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.models import (
    FeedbackAction,
    FeedbackRecord,
    MisconceptionPattern,
    Rubric,
    RubricCriterion,
    RubricScore,
)
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.learners.models import Learner, LearningGoal, learning_goal_nodes
from lms.llm.models import LLMSession
from lms.prompts.models import Prompt, PromptVersion, prompt_source_references
from lms.scheduling.models import (
    RemediationTrigger,
    ReviewPolicy,
    ReviewQueueItem,
    ReviewSchedule,
    SchedulerDecision,
)
from lms.sources.models import SourceReference

SCHEMA_VERSION = 1

MODEL_BY_TYPE = {
    "User": User,
    "Learner": Learner,
    "SourceReference": SourceReference,
    "KnowledgeNode": KnowledgeNode,
    "KnowledgeEdge": KnowledgeEdge,
    "LearningGoal": LearningGoal,
    "Prompt": Prompt,
    "PromptVersion": PromptVersion,
    "LLMSession": LLMSession,
    "Attempt": Attempt,
    "EvidenceRecord": EvidenceRecord,
    "Competency": Competency,
    "CompetencyEvidence": CompetencyEvidence,
    "FeedbackRecord": FeedbackRecord,
    "FeedbackAction": FeedbackAction,
    "MisconceptionPattern": MisconceptionPattern,
    "Rubric": Rubric,
    "RubricCriterion": RubricCriterion,
    "RubricScore": RubricScore,
    "Case": Case,
    "CaseStep": CaseStep,
    "EvidencePacket": EvidencePacket,
    "DecisionPoint": DecisionPoint,
    "ReviewQueueItem": ReviewQueueItem,
    "ReviewPolicy": ReviewPolicy,
    "ReviewSchedule": ReviewSchedule,
    "RemediationTrigger": RemediationTrigger,
    "SchedulerDecision": SchedulerDecision,
    "CapabilityTarget": CapabilityTarget,
    "CapabilityEstimate": CapabilityEstimate,
    "GapAnalysis": GapAnalysis,
    "MaintenancePlan": MaintenancePlan,
}

EXPORT_ORDER = (
    User,
    Learner,
    SourceReference,
    KnowledgeNode,
    KnowledgeEdge,
    LearningGoal,
    Prompt,
    PromptVersion,
    LLMSession,
    Attempt,
    EvidenceRecord,
    Competency,
    CompetencyEvidence,
    FeedbackRecord,
    FeedbackAction,
    MisconceptionPattern,
    Rubric,
    RubricCriterion,
    RubricScore,
    Case,
    CaseStep,
    EvidencePacket,
    DecisionPoint,
    ReviewQueueItem,
    ReviewPolicy,
    ReviewSchedule,
    RemediationTrigger,
    SchedulerDecision,
    CapabilityTarget,
    CapabilityEstimate,
    GapAnalysis,
    MaintenancePlan,
)

DEPENDENCIES = {
    "Learner": {"user_id": "User"},
    "KnowledgeNode": {"source_reference_id": "SourceReference"},
    "KnowledgeEdge": {
        "source_node_id": "KnowledgeNode",
        "target_node_id": "KnowledgeNode",
    },
    "LearningGoal": {"learner_id": "Learner"},
    "Prompt": {
        "target_node_id": "KnowledgeNode",
        "learning_goal_id": "LearningGoal",
    },
    "PromptVersion": {"prompt_id": "Prompt"},
    "Attempt": {
        "learner_id": "Learner",
        "prompt_id": "Prompt",
        "llm_session_id": "LLMSession",
    },
    "EvidenceRecord": {
        "attempt_id": "Attempt",
        "learner_id": "Learner",
        "knowledge_node_id": "KnowledgeNode",
        "prompt_id": "Prompt",
        "prompt_version_id": "PromptVersion",
    },
    "LLMSession": {
        "learner_id": "Learner",
        "parent_session_id": "LLMSession",
    },
    "CompetencyEvidence": {
        "competency_id": "Competency",
        "knowledge_node_id": "KnowledgeNode",
        "evidence_record_id": "EvidenceRecord",
        "learner_id": "Learner",
    },
    "FeedbackRecord": {
        "learner_id": "Learner",
        "attempt_id": "Attempt",
        "prompt_id": "Prompt",
        "evidence_record_id": "EvidenceRecord",
    },
    "FeedbackAction": {
        "feedback_record_id": "FeedbackRecord",
        "learner_id": "Learner",
        "attempt_id": "Attempt",
        "prompt_id": "Prompt",
    },
    "MisconceptionPattern": {"target_knowledge_node_id": "KnowledgeNode"},
    "Rubric": {
        "prompt_id": "Prompt",
        "knowledge_node_id": "KnowledgeNode",
    },
    "RubricCriterion": {"rubric_id": "Rubric"},
    "RubricScore": {
        "rubric_id": "Rubric",
        "attempt_id": "Attempt",
        "learner_id": "Learner",
        "evidence_record_id": "EvidenceRecord",
        "feedback_record_id": "FeedbackRecord",
    },
    "Case": {
        "rubric_id": "Rubric",
        "knowledge_node_id": "KnowledgeNode",
    },
    "CaseStep": {"case_id": "Case"},
    "EvidencePacket": {
        "case_id": "Case",
        "source_reference_id": "SourceReference",
    },
    "DecisionPoint": {
        "case_step_id": "CaseStep",
        "evidence_packet_id": "EvidencePacket",
    },
    "ReviewQueueItem": {
        "learner_id": "Learner",
        "knowledge_node_id": "KnowledgeNode",
        "source_attempt_id": "Attempt",
        "source_evidence_record_id": "EvidenceRecord",
    },
    "ReviewSchedule": {
        "learner_id": "Learner",
        "knowledge_node_id": "KnowledgeNode",
        "review_policy_id": "ReviewPolicy",
        "review_queue_item_id": "ReviewQueueItem",
        "source_evidence_record_id": "EvidenceRecord",
    },
    "RemediationTrigger": {
        "pattern_id": "MisconceptionPattern",
        "knowledge_node_id": "KnowledgeNode",
    },
    "SchedulerDecision": {
        "learner_id": "Learner",
        "knowledge_node_id": "KnowledgeNode",
        "review_policy_id": "ReviewPolicy",
        "review_schedule_id": "ReviewSchedule",
        "review_queue_item_id": "ReviewQueueItem",
        "source_evidence_record_id": "EvidenceRecord",
    },
    "CapabilityTarget": {
        "learner_id": "Learner",
        "learning_goal_id": "LearningGoal",
    },
    "CapabilityEstimate": {
        "target_id": "CapabilityTarget",
        "learner_id": "Learner",
    },
    "GapAnalysis": {
        "target_id": "CapabilityTarget",
        "estimate_id": "CapabilityEstimate",
        "learner_id": "Learner",
    },
    "MaintenancePlan": {
        "target_id": "CapabilityTarget",
        "gap_analysis_id": "GapAnalysis",
        "learner_id": "Learner",
    },
}

RELATIONSHIP_KEYS = {
    "LearningGoal": ("target_node_ids",),
    "Prompt": ("source_reference_ids",),
    "CapabilityTarget": ("target_node_ids", "target_competency_ids"),
}

PII_FIELDS = {"User": {"email"}}
SOURCE_CONTENT_FIELDS = {"body", "content", "raw_content", "source_content", "text"}
DEFAULT_REDACTED_FIELDS = {
    "CapabilityEstimate": {"commentary"},
    "EvidencePacket": {"packet_metadata"},
}
REDACTED_FIELD_VALUES: dict[tuple[str, str], Any] = {
    ("CapabilityEstimate", "commentary"): "[redacted: inferred capability commentary]",
    ("EvidencePacket", "packet_metadata"): {},
}
ALL_VALUE = "all"


class ExportImportError(ValueError):
    """Raised when a JSONL import/export contract is invalid."""


@dataclass(frozen=True)
class ImportSummary:
    """Counts returned by dry-run and apply imports."""

    dry_run: bool
    counts: dict[str, int]


def export_jsonl(
    session: Session,
    *,
    include_llm_traces: str = "evidence-grade-only",
    include_source_content: str = "public-only",
    include_pii: str = "never",
    confirm_all: bool = False,
) -> Iterator[str]:
    """Yield typed JSONL records in dependency order."""
    _validate_redaction_flags(
        include_llm_traces=include_llm_traces,
        include_source_content=include_source_content,
        include_pii=include_pii,
        confirm_all=confirm_all,
    )
    for model in EXPORT_ORDER:
        statement = _export_statement(model)
        for row in session.scalars(statement):
            record_type = model.__name__
            if isinstance(row, LLMSession) and not _export_llm_session(
                row, include_llm_traces=include_llm_traces
            ):
                continue
            payload = _model_to_record(
                row,
                include_pii=include_pii,
                include_source_content=include_source_content,
            )
            yield json.dumps(
                {
                    "type": record_type,
                    "schema_version": SCHEMA_VERSION,
                    "record": payload,
                },
                sort_keys=True,
            )


def export_to_path(session: Session, path: Path, **kwargs: Any) -> int:
    """Write export JSONL to ``path`` and return the number of records."""
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for line in export_jsonl(session, **kwargs):
            handle.write(f"{line}\n")
            count += 1
    return count


def import_jsonl(
    session: Session,
    path: Path,
    *,
    dry_run: bool,
) -> ImportSummary:
    """Validate or apply a JSONL import file."""
    entries = _load_entries(path)
    _validate_import(session, entries)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["type"]] = counts.get(entry["type"], 0) + 1
    if dry_run:
        return ImportSummary(dry_run=True, counts=counts)
    try:
        _apply_entries(session, entries)
        session.flush()
    except Exception:
        session.rollback()
        raise
    return ImportSummary(dry_run=False, counts=counts)


def _validate_redaction_flags(
    *,
    include_llm_traces: str,
    include_source_content: str,
    include_pii: str,
    confirm_all: bool,
) -> None:
    values = (include_llm_traces, include_source_content, include_pii)
    if ALL_VALUE in values and not confirm_all:
        raise ExportImportError("redaction value 'all' requires --yes-i-mean-it")


def _export_llm_session(session: LLMSession, *, include_llm_traces: str) -> bool:
    if include_llm_traces == ALL_VALUE:
        return True
    return session.trace_class == "evidence-grade" and session.external_export_allowed


def _export_statement(model: type[Any]) -> Any:
    statement = select(model).order_by(model.id)
    if model is LearningGoal:
        return statement.options(selectinload(LearningGoal.target_nodes))
    if model is Prompt:
        return statement.options(selectinload(Prompt.source_references))
    if model is CapabilityTarget:
        return statement.options(
            selectinload(CapabilityTarget.target_nodes),
            selectinload(CapabilityTarget.target_competencies),
        )
    return statement


def _model_to_record(row: Any, *, include_pii: str, include_source_content: str) -> dict[str, Any]:
    mapper = inspect(row).mapper
    record_type = row.__class__.__name__
    record: dict[str, Any] = {}
    pii_fields = set(PII_FIELDS.get(record_type, set()))
    redacted_fields = set()
    if include_source_content != ALL_VALUE:
        redacted_fields.update(DEFAULT_REDACTED_FIELDS.get(record_type, set()))
    source_content_fields = set()
    if record_type == "SourceReference" and include_source_content != ALL_VALUE:
        source_content_fields = SOURCE_CONTENT_FIELDS
    for column in mapper.columns:
        if include_pii != ALL_VALUE and column.key in pii_fields:
            continue
        if column.key in source_content_fields:
            continue
        if column.key in redacted_fields:
            record[column.key] = REDACTED_FIELD_VALUES[(record_type, column.key)]
            continue
        record[column.key] = _dump_value(getattr(row, column.key))
    if isinstance(row, LearningGoal):
        record["target_node_ids"] = [node.id for node in row.target_nodes]
    if isinstance(row, Prompt):
        record["source_reference_ids"] = [reference.id for reference in row.source_references]
    if isinstance(row, CapabilityTarget):
        record["target_node_ids"] = [node.id for node in row.target_nodes]
        record["target_competency_ids"] = [competency.id for competency in row.target_competencies]
    return record


def _dump_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _load_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ExportImportError(f"line {line_number}: invalid JSON") from exc
            _validate_entry_shape(entry, line_number=line_number)
            entries.append(entry)
    return entries


def _validate_entry_shape(entry: Any, *, line_number: int) -> None:
    if not isinstance(entry, dict):
        raise ExportImportError(f"line {line_number}: entry must be an object")
    record_type = entry.get("type")
    if record_type not in MODEL_BY_TYPE:
        raise ExportImportError(f"line {line_number}: unknown type {record_type!r}")
    if entry.get("schema_version") != SCHEMA_VERSION:
        raise ExportImportError(f"line {line_number}: unsupported schema_version")
    record = entry.get("record")
    if not isinstance(record, dict):
        raise ExportImportError(f"line {line_number}: record must be an object")
    if not isinstance(record.get("id"), str):
        raise ExportImportError(f"line {line_number}: record.id must be a string")


def _validate_import(session: Session, entries: Sequence[dict[str, Any]]) -> None:
    seen: dict[str, set[str]] = {record_type: set() for record_type in MODEL_BY_TYPE}
    for entry in entries:
        record_type = entry["type"]
        record = entry["record"]
        record_id = record["id"]
        if record_id in seen[record_type]:
            raise ExportImportError(f"duplicate import record {record_type}:{record_id}")
        seen[record_type].add(record_id)
        model = MODEL_BY_TYPE[record_type]
        if session.get(model, record_id) is not None:
            raise ExportImportError(f"{record_type}:{record_id} already exists")

    for entry in entries:
        record_type = entry["type"]
        record = entry["record"]
        for field, dependency_type in DEPENDENCIES.get(record_type, {}).items():
            dependency_id = record.get(field)
            if dependency_id is None:
                continue
            if not _id_exists(session, dependency_type, dependency_id, seen):
                raise ExportImportError(
                    f"{record_type}:{record['id']} references missing "
                    f"{dependency_type}:{dependency_id}"
                )
        for key in RELATIONSHIP_KEYS.get(record_type, ()):
            values = record.get(key, [])
            if not isinstance(values, list):
                raise ExportImportError(f"{record_type}:{record['id']} {key} must be a list")
            dependency_type = _relationship_dependency_type(key)
            for dependency_id in values:
                if not isinstance(dependency_id, str) or not _id_exists(
                    session, dependency_type, dependency_id, seen
                ):
                    raise ExportImportError(
                        f"{record_type}:{record['id']} references missing "
                        f"{dependency_type}:{dependency_id}"
                    )


def _id_exists(
    session: Session,
    record_type: str,
    record_id: str,
    imported: dict[str, set[str]],
) -> bool:
    if record_id in imported[record_type]:
        return True
    return session.get(MODEL_BY_TYPE[record_type], record_id) is not None


def _relationship_dependency_type(key: str) -> str:
    if key in {"target_node_ids", "knowledge_node_ids"}:
        return "KnowledgeNode"
    if key == "target_competency_ids":
        return "Competency"
    if key == "source_reference_ids":
        return "SourceReference"
    raise ExportImportError(f"unsupported relationship key {key!r}")


def _apply_entries(session: Session, entries: Iterable[dict[str, Any]]) -> None:
    pending_relationships: list[tuple[str, str, str, list[str]]] = []
    for entry in entries:
        model = MODEL_BY_TYPE[entry["type"]]
        record = dict(entry["record"])
        for key in RELATIONSHIP_KEYS.get(entry["type"], ()):
            pending_relationships.append(
                (entry["type"], key, record["id"], list(record.pop(key, [])))
            )
        table = model.__table__
        if not isinstance(table, Table):
            raise ExportImportError(f"{entry['type']} does not map to a concrete table")
        values = _coerce_record(table, record)
        session.add(model(**values))
    session.flush()
    for record_type, key, record_id, related_ids in pending_relationships:
        if record_type == "LearningGoal":
            _insert_associations(
                session,
                learning_goal_nodes,
                left_column="learning_goal_id",
                right_column="knowledge_node_id",
                left_id=record_id,
                right_ids=related_ids,
            )
        elif record_type == "Prompt":
            _insert_associations(
                session,
                prompt_source_references,
                left_column="prompt_id",
                right_column="source_reference_id",
                left_id=record_id,
                right_ids=related_ids,
            )
        elif record_type == "CapabilityTarget" and key == "target_node_ids":
            _insert_associations(
                session,
                capability_target_nodes,
                left_column="capability_target_id",
                right_column="knowledge_node_id",
                left_id=record_id,
                right_ids=related_ids,
            )
        elif record_type == "CapabilityTarget" and key == "target_competency_ids":
            _insert_associations(
                session,
                capability_target_competencies,
                left_column="capability_target_id",
                right_column="competency_id",
                left_id=record_id,
                right_ids=related_ids,
            )


def _coerce_record(table: Table, record: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    columns = {column.key: column for column in table.columns}
    for key, value in record.items():
        column = columns.get(key)
        if column is None:
            continue
        values[key] = _coerce_value(column, value)
    return values


def _coerce_value(column: Column[Any], value: Any) -> Any:
    if value is None:
        return None
    python_type: type[Any] | None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        python_type = None
    if python_type is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _insert_associations(
    session: Session,
    table: Table,
    *,
    left_column: str,
    right_column: str,
    left_id: str,
    right_ids: Sequence[str],
) -> None:
    for right_id in right_ids:
        session.execute(
            table.insert().values(
                {
                    left_column: left_id,
                    right_column: right_id,
                }
            )
        )
