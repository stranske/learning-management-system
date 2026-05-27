"""Tests for build-time research registry validation."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from lms.__main__ import main
from lms.research_registry import ResearchRegistryError, load_registry
from lms.research_registry.schemas import (
    ClaimStatus,
    EvidenceLevel,
    LearningClaim,
    LearningPrinciple,
)

REGISTRY_DIR = Path("docs/research/registry")


def test_committed_registry_validates() -> None:
    """Committed seed records validate and include the required seed scope."""
    registry = load_registry(REGISTRY_DIR)

    principle_ids = {principle.id for principle in registry.principles}
    claim_ids = {claim.id for claim in registry.claims}
    source_ids = {source.id for source in registry.evidence_sources}

    assert {
        "principle-evidence-informed-design",
        "principle-retrieval-as-learning",
    } <= principle_ids
    assert {"claim-completion-not-learning", "claim-rereading-fluency-not-mastery"} <= claim_ids
    assert {"how-do-we-learn-ch1", "how-do-we-learn-section-2-3"} <= source_ids


def test_unknown_principle_reference_fails(tmp_path: Path) -> None:
    """Claims cannot point at undefined principle ids."""
    registry_dir = _copy_registry(tmp_path)
    claims_path = registry_dir / "claims.yml"
    claims_path.write_text(
        claims_path.read_text(encoding="utf-8").replace(
            "principle-retrieval-as-learning",
            "principle-does-not-exist",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ResearchRegistryError, match="unknown principle id principle-does-not-exist"
    ):
        load_registry(registry_dir)


def test_schema_allows_deprecated_claim_status_and_evidence_level() -> None:
    """The enums explicitly allow deprecated records from the design model."""
    claim = LearningClaim.model_validate(
        {
            "id": "claim-old-method",
            "statement": "A deprecated learning claim.",
            "principleIds": ["principle-old-method"],
            "sourceIds": [],
            "claimStatus": "deprecated",
            "claimType": "risk-warning",
            "scope": "legacy personalization claims",
            "reviewCadence": "annual",
            "lastReviewedAt": "2026-05-25T00:00:00Z",
        }
    )
    principle = LearningPrinciple.model_validate(
        {
            "id": "principle-old-method",
            "name": "Old method",
            "summary": "A deprecated principle.",
            "mechanism": "Retained only to prevent unsupported reuse.",
            "sourceIds": [],
            "evidenceLevel": "deprecated",
            "confidence": "low",
            "designImplications": ["Do not use for new design decisions."],
            "antiPatterns": [],
            "audiences": ["personal"],
            "createdAt": "2026-05-25T00:00:00Z",
            "updatedAt": "2026-05-25T00:00:00Z",
        }
    )

    assert claim.claim_status is ClaimStatus.DEPRECATED
    assert principle.evidence_level is EvidenceLevel.DEPRECATED


def test_research_api_routes_are_not_added() -> None:
    """The build-time registry must not create runtime /research/* endpoints."""
    from lms import create_app

    schema = create_app().openapi()
    assert not any(path.startswith("/research/") for path in schema["paths"])


def test_cli_validates_registry(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI validates the committed registry and reports record counts."""
    monkeypatch.setattr(sys, "argv", ["lms", "validate-research-registry"])

    main()

    output = capsys.readouterr().out
    assert "research registry valid:" in output
    assert "research scans" in output
    assert "evidence reviews" in output


def test_cli_reports_registry_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI exits nonzero when registry validation fails."""
    registry_dir = _copy_registry(tmp_path)
    claims_path = registry_dir / "claims.yml"
    claims_path.write_text("not: a list\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["lms", "validate-research-registry", "--registry-dir", str(registry_dir)],
    )

    with pytest.raises(SystemExit, match="research registry validation failed"):
        main()


def _copy_registry(tmp_path: Path) -> Path:
    destination = tmp_path / "registry"
    shutil.copytree(REGISTRY_DIR, destination)
    return destination
