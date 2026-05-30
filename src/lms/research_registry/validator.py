"""Load and validate the build-time research registry YAML files."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from lms.research_registry.schemas import (
    EvidenceReview,
    EvidenceSource,
    LearningClaim,
    LearningPrinciple,
    ResearchScan,
)


class ResearchRegistryError(ValueError):
    """Raised when registry YAML is malformed or internally inconsistent."""


@dataclass(frozen=True)
class ResearchRegistry:
    """Validated registry records."""

    principles: tuple[LearningPrinciple, ...]
    claims: tuple[LearningClaim, ...]
    evidence_sources: tuple[EvidenceSource, ...]
    research_scans: tuple[ResearchScan, ...] = ()
    evidence_reviews: tuple[EvidenceReview, ...] = ()


def default_registry_dir() -> Path:
    """Return the repository-local default registry directory."""
    return Path(__file__).resolve().parents[3] / "docs" / "research" / "registry"


def load_registry(registry_dir: Path | None = None) -> ResearchRegistry:
    """Load and validate registry YAML from ``registry_dir``."""
    root = registry_dir or default_registry_dir()
    evidence_sources = _load_collection(root / "evidence-sources.yml", EvidenceSource)
    principles = _load_collection(root / "principles.yml", LearningPrinciple)
    claims = _load_collection(root / "claims.yml", LearningClaim)
    research_scans = _load_collection(root / "research-scans.yml", ResearchScan, required=False)
    evidence_reviews = _load_collection(
        root / "evidence-reviews.yml", EvidenceReview, required=False
    )
    registry = ResearchRegistry(
        principles=tuple(principles),
        claims=tuple(claims),
        evidence_sources=tuple(evidence_sources),
        research_scans=tuple(research_scans),
        evidence_reviews=tuple(evidence_reviews),
    )
    validate_registry(registry)
    return registry


def validate_registry(registry: ResearchRegistry) -> None:
    """Validate cross-references across registry record types."""
    source_ids = _ensure_unique(
        "evidence source", (source.id for source in registry.evidence_sources)
    )
    principle_ids = _ensure_unique("principle", (principle.id for principle in registry.principles))
    claim_ids = _ensure_unique("claim", (claim.id for claim in registry.claims))
    _ensure_unique("research scan", (scan.id for scan in registry.research_scans))
    _ensure_unique("evidence review", (review.id for review in registry.evidence_reviews))

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

    for scan in registry.research_scans:
        for source_id in scan.source_ids:
            if source_id not in source_ids:
                errors.append(f"research scan {scan.id} references unknown source id {source_id}")
        for claim_id in scan.claim_ids:
            if claim_id not in claim_ids:
                errors.append(f"research scan {scan.id} references unknown claim id {claim_id}")

    for review in registry.evidence_reviews:
        if review.evidence_source_id not in source_ids:
            errors.append(
                f"evidence review {review.id} references unknown source id "
                f"{review.evidence_source_id}"
            )
        for claim_id in review.claim_ids:
            if claim_id not in claim_ids:
                errors.append(f"evidence review {review.id} references unknown claim id {claim_id}")

    if errors:
        raise ResearchRegistryError("; ".join(errors))


def _load_collection[
    T: (EvidenceSource, LearningClaim, LearningPrinciple, ResearchScan, EvidenceReview)
](
    path: Path, model_type: type[T], *, required: bool = True
) -> list[T]:
    if not path.exists():
        if not required:
            return []
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


def _parse_record[
    T: (EvidenceSource, LearningClaim, LearningPrinciple, ResearchScan, EvidenceReview)
](
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
