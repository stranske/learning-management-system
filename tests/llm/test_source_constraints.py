"""Tests for source-constrained LLM policy output."""

from __future__ import annotations

from lms.llm.interaction_policy import flag_uncited_claims


def test_uncited_claim_is_flagged_unverified() -> None:
    flags = flag_uncited_claims(
        "Photosynthesis converts light into stored chemical energy.",
        ("source:biology-note-1",),
    )

    assert "unverified" in flags
