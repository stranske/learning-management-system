"""Markdown note importer for draft knowledge graph seeding."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import mistune
from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_edge, create_knowledge_node
from lms.sources.repository import create_source_reference

_ATX_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$")
_SETEXT_UNDERLINE_RE = re.compile(r"^[ \t]*(?P<mark>=+|-+)[ \t]*$")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkdownHeading:
    """A parsed ATX heading and its source section."""

    file_path: Path
    level: int
    title: str
    start_line: int
    end_line: int
    content: str
    parent_index: int | None

    @property
    def passage_range(self) -> str:
        return f"L{self.start_line}-L{self.end_line}"


@dataclass(frozen=True)
class MarkdownImportSummary:
    """Counts produced by one Markdown import or dry-run."""

    files_scanned: int
    planned_nodes: int
    planned_sources: int
    planned_edges: int
    created_nodes: int = 0
    created_sources: int = 0
    created_edges: int = 0
    dry_run: bool = False

    def to_cli_line(self) -> str:
        verb = "planned" if self.dry_run else "created"
        return (
            f"markdown import {verb}: files={self.files_scanned} "
            f"nodes={self.planned_nodes if self.dry_run else self.created_nodes} "
            f"sources={self.planned_sources if self.dry_run else self.created_sources} "
            f"edges={self.planned_edges if self.dry_run else self.created_edges}"
        )

    def to_cli_summary_lines(self) -> list[str]:
        """Return CLI-friendly summary lines for import and dry-run modes."""
        lines = [self.to_cli_line()]
        if self.dry_run:
            lines.append(
                "planned creates: "
                f"nodes={self.planned_nodes} sources={self.planned_sources} edges={self.planned_edges}"
            )
        return lines


def plan_markdown_notes(path: str | Path, *, limit: int | None = None) -> Sequence[MarkdownHeading]:
    """Return H1/H2 heading sections that would become draft knowledge nodes."""
    files = _markdown_files(Path(path))
    headings: list[MarkdownHeading] = []
    for file_path in files:
        # parent_index from _parse_heading_sections is an index into THAT file's
        # heading list. Rebase it onto the accumulating global list so an H2's
        # prerequisite edge points at the H1 in its own file, not whichever node
        # happens to occupy that index from a previously-imported file.
        base = len(headings)
        for heading in _parse_heading_sections(file_path):
            if heading.parent_index is not None:
                heading = replace(heading, parent_index=heading.parent_index + base)
            headings.append(heading)
            if limit is not None and len(headings) >= limit:
                return headings[:limit]
    return headings


def import_markdown_notes(
    session: Session | None,
    path: str | Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    scope: str = "personal",
    source_visibility: str = "local-only",
    actor_id: str = "system:import-notes",
) -> MarkdownImportSummary:
    """Import Markdown H1/H2 sections as draft nodes with source references."""
    headings = list(plan_markdown_notes(path, limit=limit))
    edge_count = sum(1 for heading in headings if heading.parent_index is not None)
    files_scanned = len({heading.file_path for heading in headings})
    if dry_run:
        return MarkdownImportSummary(
            files_scanned=files_scanned,
            planned_nodes=len(headings),
            planned_sources=len(headings),
            planned_edges=edge_count,
            dry_run=True,
        )
    if session is None:
        raise ValueError("session is required unless dry_run=True")

    node_ids: list[str] = []
    created_edges = 0
    for heading in headings:
        source = create_source_reference(
            session,
            source_type="markdown-file",
            stable_locator=str(heading.file_path),
            passage_range=heading.passage_range,
            content=heading.content,
            source_visibility=source_visibility,
            actor_id=actor_id,
            source_subsystem="markdown-importer",
        )
        node = create_knowledge_node(
            session,
            title=heading.title,
            description=_section_description(heading.content),
            knowledge_type="conceptual",
            scope=scope,
            actor_id=actor_id,
            status="draft",
            provenance="imported",
            imported_from=str(heading.file_path),
            source_reference_id=source.id,
            source_subsystem="markdown-importer",
        )
        node_ids.append(node.id)
        if heading.parent_index is not None and heading.parent_index < len(node_ids):
            # Canonical prerequisite direction is source -> target meaning
            # "source has prerequisite target" (see KnowledgeEdge). A nested
            # subsection depends on its parent section, so the child node is the
            # source and the parent section is the prerequisite target -- the
            # same orientation the CSV importer uses (source=node,
            # target=prerequisite).
            create_knowledge_edge(
                session,
                source_node_id=node.id,
                target_node_id=node_ids[heading.parent_index],
                edge_type="prerequisite",
                scope=scope,
                actor_id=actor_id,
                confidence=0.5,
                status="draft",
                notes=(
                    "Candidate prerequisite inferred from nested Markdown "
                    "headings: the parent section is a prerequisite of its "
                    "nested subsection."
                ),
                source_subsystem="markdown-importer",
            )
            created_edges += 1

    return MarkdownImportSummary(
        files_scanned=files_scanned,
        planned_nodes=len(headings),
        planned_sources=len(headings),
        planned_edges=edge_count,
        created_nodes=len(headings),
        created_sources=len(headings),
        created_edges=created_edges,
    )


def _markdown_files(path: Path) -> list[Path]:
    resolved = path.expanduser()
    if resolved.is_file():
        return [resolved]
    if not resolved.exists():
        raise FileNotFoundError(f"markdown import path does not exist: {path}")
    return sorted(file_path for file_path in resolved.rglob("*.md") if file_path.is_file())


def _parse_heading_sections(file_path: Path) -> list[MarkdownHeading]:
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        LOGGER.warning("skipping non-UTF-8 markdown file %s: %s", file_path, exc)
        return []
    lines = text.splitlines(keepends=True)
    raw = _extract_h1_h2_headings(text=text, lines=lines)

    headings: list[MarkdownHeading] = []
    h1_index: int | None = None
    for raw_index, (level, start_line, title) in enumerate(raw):
        next_boundary = len(lines) + 1
        for candidate_level, candidate_line, _ in raw[raw_index + 1 :]:
            if candidate_level <= level:
                next_boundary = candidate_line
                break
        end_line = max(start_line, next_boundary - 1)
        content = "".join(lines[start_line - 1 : end_line])
        parent_index = h1_index if level == 2 else None
        headings.append(
            MarkdownHeading(
                file_path=file_path,
                level=level,
                title=title,
                start_line=start_line,
                end_line=end_line,
                content=content,
                parent_index=parent_index,
            )
        )
        if level == 1:
            h1_index = len(headings) - 1
    return headings


def _extract_h1_h2_headings(*, text: str, lines: list[str]) -> list[tuple[int, int, str]]:
    """Parse heading tokens with Mistune and map each H1/H2 token to a source line."""
    markdown = mistune.create_markdown(renderer="ast")
    tokens = cast(list[dict[str, Any]], markdown(text))
    raw: list[tuple[int, int, str]] = []
    next_scan_index = 0
    for token in tokens:
        if not isinstance(token, dict):
            continue
        if token.get("type") != "heading":
            continue
        attrs = token.get("attrs", {})
        raw_level = attrs.get("level") if isinstance(attrs, dict) else None
        if raw_level is None:
            raw_level = token.get("level")
        level = int(raw_level or 0)
        if level > 2 or level < 1:
            continue
        title = _extract_heading_text(token).strip()
        if not title:
            continue
        start_line, next_scan_index = _find_heading_line(
            lines=lines,
            level=level,
            title=title,
            start_index=next_scan_index,
        )
        raw.append((level, start_line, title))
    return raw


def _extract_heading_text(token: dict[str, object]) -> str:
    text = token.get("text")
    if isinstance(text, str) and text.strip():
        return _clean_heading_title(text)
    children = token.get("children")
    if not isinstance(children, list):
        return ""
    parts: list[str] = []
    for child in children:
        if isinstance(child, dict):
            raw = child.get("raw")
            if isinstance(raw, str):
                parts.append(raw)
                continue
            text = child.get("text")
            if isinstance(text, str):
                parts.append(text)
    return _clean_heading_title("".join(parts))


def _find_heading_line(
    *,
    lines: list[str],
    level: int,
    title: str,
    start_index: int,
) -> tuple[int, int]:
    for line_index in range(start_index, len(lines)):
        match = _ATX_HEADING_RE.match(lines[line_index])
        if match is not None:
            if len(match.group("marks")) != level:
                continue
            if _clean_heading_title(match.group("title")) != title:
                continue
            return line_index + 1, line_index + 1
        setext_line = _find_setext_heading_line(
            lines=lines,
            line_index=line_index,
            level=level,
            title=title,
        )
        if setext_line is not None:
            return setext_line, line_index + 2
    raise ValueError(f"could not map parsed heading to source line: {title!r}")


def _find_setext_heading_line(
    *,
    lines: list[str],
    line_index: int,
    level: int,
    title: str,
) -> int | None:
    if line_index + 1 >= len(lines):
        return None
    underline = _SETEXT_UNDERLINE_RE.match(lines[line_index + 1])
    if underline is None:
        return None
    mark = underline.group("mark")[0]
    underline_level = 1 if mark == "=" else 2
    if underline_level != level:
        return None
    if _clean_heading_title(lines[line_index]) != title:
        return None
    return line_index + 1


def _clean_heading_title(title: str) -> str:
    return title.strip().rstrip("#").strip()


def _section_description(content: str) -> str | None:
    body_lines = [
        line.strip()
        for line in content.splitlines()[1:]
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not body_lines:
        return None
    return " ".join(body_lines)[:500]
