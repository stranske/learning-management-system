"""JSONL export and import contract for v1 LMS records."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Table, inspect, select
from sqlalchemy.orm import Session

import lms.audit.models  # noqa: F401  # register metadata
import lms.evidence.models  # noqa: F401  # register metadata
import lms.graphs.models  # noqa: F401  # register metadata
import lms.learners.models  # noqa: F401  # register metadata
import lms.llm.models  # noqa: F401  # register metadata
import lms.prompts.models  # noqa: F401  # register metadata
import lms.sources.models  # noqa: F401  # register metadata
from lms.auth.models import User
from lms.evidence.models import Attempt, EvidenceRecord
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.learners.models import Learner, LearningGoal, learning_goal_nodes
from lms.llm.models import LLMSession
from lms.prompts.models import Prompt, PromptVersion, prompt_source_references
from lms.sources.models import SourceReference

SCHEMA_VERSION = 1
EXPORT_TYPES = (
    "User",
    "Learner",
    "SourceReference",
    "KnowledgeNode",
    "KnowledgeEdge",
    "LearningGoal",
    "Prompt",
    "Attempt",
    "EvidenceRecord",
    "LLMSession",
)

MODEL_BY_TYPE = {
    "User": User,
    "Learner": Learner,
    "SourceReference": SourceReference,
    "KnowledgeNode": KnowledgeNode,
    "KnowledgeEdge": KnowledgeEdge,
    "LearningGoal": LearningGoal,
    "Prompt": Prompt,
    "PromptVersion": PromptVersion,
    "Attempt": Attempt,
    "EvidenceRecord": EvidenceRecord,
    "LLMSession": LLMSession,
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
    Attempt,
    EvidenceRecord,
    LLMSession,
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
}

RELATIONSHIP_KEYS = {
    "LearningGoal": ("target_node_ids",),
    "Prompt": ("source_reference_ids",),
}

PII_FIELDS = {"User": {"email"}}
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
        for row in session.scalars(select(model).order_by(model.id)):
            record_type = model.__name__
            if isinstance(row, LLMSession) and not _export_llm_session(
                row, include_llm_traces=include_llm_traces
            ):
                continue
            payload = _model_to_record(row, include_pii=include_pii)
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


def _model_to_record(row: Any, *, include_pii: str) -> dict[str, Any]:
    mapper = inspect(row).mapper
    record_type = row.__class__.__name__
    record: dict[str, Any] = {}
    redacted_fields = PII_FIELDS.get(record_type, set())
    for column in mapper.columns:
        if include_pii != ALL_VALUE and column.key in redacted_fields:
            continue
        record[column.key] = _dump_value(getattr(row, column.key))
    if isinstance(row, LearningGoal):
        record["target_node_ids"] = [node.id for node in row.target_nodes]
    if isinstance(row, Prompt):
        record["source_reference_ids"] = [reference.id for reference in row.source_references]
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


def _validate_entry_shape(entry: dict[str, Any], *, line_number: int) -> None:
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
            dependency_type = "KnowledgeNode" if key == "target_node_ids" else "SourceReference"
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


def _apply_entries(session: Session, entries: Iterable[dict[str, Any]]) -> None:
    pending_relationships: list[tuple[str, str, list[str]]] = []
    for entry in entries:
        model = MODEL_BY_TYPE[entry["type"]]
        record = dict(entry["record"])
        for key in RELATIONSHIP_KEYS.get(entry["type"], ()):
            pending_relationships.append((entry["type"], record["id"], list(record.pop(key, []))))
        table = model.__table__
        if not isinstance(table, Table):
            raise ExportImportError(f"{entry['type']} does not map to a concrete table")
        values = _coerce_record(table, record)
        session.add(model(**values))
    session.flush()
    for record_type, record_id, related_ids in pending_relationships:
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
