"""Tests for ResearchScan and EvidenceReview registry records."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lms.research_registry import ResearchRegistryError, load_registry
from lms.research_registry.schemas import (
    EvidenceReview,
    EvidenceReviewStatus,
    ResearchDecision,
    ResearchScan,
)

REGISTRY_DIR = Path("docs/research/registry")


def test_research_scan_references_existing_claims_and_sources() -> None:
    """Committed research scans resolve against existing claim and source ids."""
    registry = load_registry(REGISTRY_DIR)

    assert registry.research_scans
    source_ids = {source.id for source in registry.evidence_sources}
    claim_ids = {claim.id for claim in registry.claims}
    for scan in registry.research_scans:
        assert isinstance(scan, ResearchScan)
        assert isinstance(scan.decision, ResearchDecision)
        for source_id in scan.source_ids:
            assert source_id in source_ids
        for claim_id in scan.claim_ids:
            assert claim_id in claim_ids


def test_evidence_review_rejects_missing_source_id(tmp_path: Path) -> None:
    """Evidence reviews cannot reference an unknown evidence source id."""
    registry_dir = _copy_registry(tmp_path)
    reviews_path = registry_dir / "evidence-reviews.yml"
    reviews_path.write_text(
        reviews_path.read_text(encoding="utf-8").replace(
            "evidenceSourceId: roediger-karpicke-2006",
            "evidenceSourceId: source-does-not-exist",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResearchRegistryError, match="unknown source id source-does-not-exist"):
        load_registry(registry_dir)


def test_research_scan_rejects_missing_claim_reference(tmp_path: Path) -> None:
    """Research scans cannot reference an unknown claim id."""
    registry_dir = _copy_registry(tmp_path)
    scans_path = registry_dir / "research-scans.yml"
    scans_path.write_text(
        scans_path.read_text(encoding="utf-8").replace(
            "claim-rereading-fluency-not-mastery",
            "claim-does-not-exist",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ResearchRegistryError, match="unknown claim id claim-does-not-exist"):
        load_registry(registry_dir)


def test_evidence_review_schema_parses_camel_case_fields() -> None:
    """The EvidenceReview schema parses the camel-case YAML field names."""
    review = EvidenceReview.model_validate(
        {
            "id": "review-example",
            "evidenceSourceId": "how-do-we-learn-ch1",
            "claimIds": ["claim-completion-not-learning"],
            "reviewStatus": "pending",
            "reliabilityNotes": "Paraphrased reliability note.",
            "limitations": "Paraphrased limitation note.",
            "decision": "monitor",
            "reviewedAt": "2026-05-25T00:00:00Z",
        }
    )

    assert review.review_status is EvidenceReviewStatus.PENDING
    assert review.decision is ResearchDecision.MONITOR
    assert review.evidence_source_id == "how-do-we-learn-ch1"


def test_missing_optional_registry_files_validate(tmp_path: Path) -> None:
    """A registry without the new files still validates (the records are optional)."""
    registry_dir = _copy_registry(tmp_path)
    (registry_dir / "research-scans.yml").unlink()
    (registry_dir / "evidence-reviews.yml").unlink()

    registry = load_registry(registry_dir)

    assert registry.research_scans == ()
    assert registry.evidence_reviews == ()


def _copy_registry(tmp_path: Path) -> Path:
    destination = tmp_path / "registry"
    shutil.copytree(REGISTRY_DIR, destination)
    return destination
