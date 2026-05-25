"""CSV graph importer for KnowledgeNode and prerequisite edge bootstrap."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_edge, create_knowledge_node
from lms.sources.repository import create_source_reference

REQUIRED_COLUMNS: tuple[str, ...] = (
    "title",
    "knowledge_type",
    "prerequisites",
    "ownership_scope",
    "status",
    "source_locator",
)
OPTIONAL_COLUMNS: tuple[str, ...] = ("source_range", "description")
PREREQUISITE_SEPARATORS: tuple[str, ...] = ("|", ";")


@dataclass(frozen=True)
class CsvGraphImportSummary:
    """Counts produced by one CSV graph import pass."""

    nodes: int
    edges: int
    source_references: int
    dry_run: bool


@dataclass(frozen=True)
class CsvGraphRow:
    """Validated CSV graph row."""

    row_number: int
    title: str
    knowledge_type: str
    prerequisites: tuple[str, ...]
    ownership_scope: str
    status: str
    source_locator: str
    source_range: str | None
    description: str | None
    raw: dict[str, str]


class CsvGraphImportError(ValueError):
    """Raised when a CSV graph file cannot be imported safely."""


def import_csv_graph(
    session: Session,
    csv_path: str | Path,
    *,
    dry_run: bool = False,
    actor_id: str = "system:csv-graph-importer",
) -> CsvGraphImportSummary:
    """Import KnowledgeNode rows and prerequisite edges from a CSV file."""
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = _load_rows(csv_file)
    edge_count = sum(len(row.prerequisites) for row in rows)
    if dry_run:
        return CsvGraphImportSummary(
            nodes=len(rows),
            edges=edge_count,
            source_references=len(rows),
            dry_run=True,
        )

    nodes_by_key: dict[tuple[str, str], str] = {}
    for row in rows:
        source_reference = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator=row.source_locator,
            passage_range=row.source_range,
            content=_row_content(row),
            actor_id=actor_id,
            source_subsystem="csv-graph-importer",
        )
        node = create_knowledge_node(
            session,
            title=row.title,
            description=row.description,
            knowledge_type=row.knowledge_type,
            scope=row.ownership_scope,
            status=row.status,
            provenance="imported",
            imported_from=str(path),
            source_reference_id=source_reference.id,
            actor_id=actor_id,
            source_subsystem="csv-graph-importer",
        )
        nodes_by_key[_node_key(row.ownership_scope, row.title)] = node.id

    for row in rows:
        source_node_id = nodes_by_key[_node_key(row.ownership_scope, row.title)]
        for prerequisite_title in row.prerequisites:
            target_node_id = nodes_by_key[_node_key(row.ownership_scope, prerequisite_title)]
            create_knowledge_edge(
                session,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                edge_type="prerequisite",
                scope=row.ownership_scope,
                actor_id=actor_id,
                status="draft",
                source_subsystem="csv-graph-importer",
            )

    return CsvGraphImportSummary(
        nodes=len(rows),
        edges=edge_count,
        source_references=len(rows),
        dry_run=False,
    )


def _load_rows(csv_file: TextIO) -> list[CsvGraphRow]:
    reader = csv.DictReader(csv_file)
    fieldnames = tuple(reader.fieldnames or ())
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise CsvGraphImportError(
            "CSV graph import missing required columns: " + ", ".join(missing_columns)
        )

    rows: list[CsvGraphRow] = []
    seen_keys: set[tuple[str, str]] = set()
    for row_number, raw_row in enumerate(reader, start=2):
        normalized = {key: (value or "").strip() for key, value in raw_row.items() if key}
        row = CsvGraphRow(
            row_number=row_number,
            title=_require_cell(normalized, "title", row_number),
            knowledge_type=_require_cell(normalized, "knowledge_type", row_number),
            prerequisites=_split_prerequisites(normalized.get("prerequisites", "")),
            ownership_scope=_require_cell(normalized, "ownership_scope", row_number),
            status=_require_cell(normalized, "status", row_number),
            source_locator=_require_cell(normalized, "source_locator", row_number),
            source_range=normalized.get("source_range") or None,
            description=normalized.get("description") or None,
            raw=normalized,
        )
        key = _node_key(row.ownership_scope, row.title)
        if key in seen_keys:
            raise CsvGraphImportError(
                f"row {row_number}: duplicate title {row.title!r} in "
                f"ownership scope {row.ownership_scope!r}"
            )
        seen_keys.add(key)
        rows.append(row)

    if not rows:
        raise CsvGraphImportError("CSV graph import requires at least one data row")

    keys = {_node_key(row.ownership_scope, row.title) for row in rows}
    missing_references: list[str] = []
    for row in rows:
        for prerequisite_title in row.prerequisites:
            if _node_key(row.ownership_scope, prerequisite_title) not in keys:
                missing_references.append(
                    f"row {row.row_number}: {row.title!r} references unknown prerequisite "
                    f"{prerequisite_title!r} in scope {row.ownership_scope!r}"
                )
    if missing_references:
        raise CsvGraphImportError("; ".join(missing_references))
    return rows


def _require_cell(row: dict[str, str], column: str, row_number: int) -> str:
    value = row.get(column, "")
    if not value:
        raise CsvGraphImportError(f"row {row_number}: required column {column!r} is blank")
    return value


def _split_prerequisites(value: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    for separator in PREREQUISITE_SEPARATORS:
        if separator in value:
            return tuple(part.strip() for part in value.split(separator) if part.strip())
    return (value.strip(),)


def _node_key(scope: str, title: str) -> tuple[str, str]:
    return (scope.casefold(), title.casefold())


def _row_content(row: CsvGraphRow) -> str:
    return json.dumps(row.raw, sort_keys=True, separators=(",", ":"))
