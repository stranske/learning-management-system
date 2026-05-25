"""Load and validate the build-time research registry YAML files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from lms.research_registry.schemas import EvidenceSource, LearningClaim, LearningPrinciple


class ResearchRegistryError(ValueError):
    """Raised when registry YAML is malformed or internally inconsistent."""


@dataclass(frozen=True)
class ResearchRegistry:
    """Validated registry records."""

    principles: tuple[LearningPrinciple, ...]
    claims: tuple[LearningClaim, ...]
    evidence_sources: tuple[EvidenceSource, ...]


def default_registry_dir() -> Path:
    """Return the repository-local default registry directory."""
    return Path(__file__).resolve().parents[3] / "docs" / "research" / "registry"


def load_registry(registry_dir: Path | None = None) -> ResearchRegistry:
    """Load and validate registry YAML from ``registry_dir``."""
    root = registry_dir or default_registry_dir()
    evidence_sources = _load_collection(root / "evidence-sources.yml", EvidenceSource)
    principles = _load_collection(root / "principles.yml", LearningPrinciple)
    claims = _load_collection(root / "claims.yml", LearningClaim)
    registry = ResearchRegistry(
        principles=tuple(principles),
        claims=tuple(claims),
        evidence_sources=tuple(evidence_sources),
    )
    validate_registry(registry)
    return registry


def validate_registry(registry: ResearchRegistry) -> None:
    """Validate cross-references across registry record types."""
    source_ids = _ensure_unique(
        "evidence source", (source.id for source in registry.evidence_sources)
    )
    principle_ids = _ensure_unique("principle", (principle.id for principle in registry.principles))
    _ensure_unique("claim", (claim.id for claim in registry.claims))

    errors: list[str] = []
    for principle in registry.principles:
        for source_id in principle.source_ids:
            if source_id not in source_ids:
                errors.append(f"principle {principle.id} references unknown source id {source_id}")

    for claim in registry.claims:
        for principle_id in claim.principle_ids:
            if principle_id not in principle_ids:
                errors.append(f"claim {claim.id} references unknown principle id {principle_id}")
        for source_id in claim.source_ids:
            if source_id not in source_ids:
                errors.append(f"claim {claim.id} references unknown source id {source_id}")

    if errors:
        raise ResearchRegistryError("; ".join(errors))


def _load_collection[T: (EvidenceSource, LearningClaim, LearningPrinciple)](
    path: Path, model_type: type[T]
) -> list[T]:
    if not path.exists():
        raise ResearchRegistryError(f"registry file missing: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ResearchRegistryError(f"{path}: invalid YAML: {exc}") from exc

    if not isinstance(raw, list):
        raise ResearchRegistryError(f"{path}: expected a YAML list of records")

    records: list[T] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ResearchRegistryError(f"{path}: record {index} must be a mapping")
        records.append(_parse_record(path, index, item, model_type))
    return records


def _parse_record[T: (EvidenceSource, LearningClaim, LearningPrinciple)](
    path: Path, index: int, item: dict[str, Any], model_type: type[T]
) -> T:
    try:
        return model_type.model_validate(item)
    except ValidationError as exc:
        raise ResearchRegistryError(f"{path}: record {index} failed validation: {exc}") from exc


def _ensure_unique(kind: str, ids: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for record_id in ids:
        if not isinstance(record_id, str):
            raise ResearchRegistryError(f"{kind} id must be a string: {record_id!r}")
        if record_id in seen:
            duplicates.add(record_id)
        seen.add(record_id)
    if duplicates:
        raise ResearchRegistryError(f"duplicate {kind} ids: {', '.join(sorted(duplicates))}")
    return seen
