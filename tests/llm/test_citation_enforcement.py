"""Client-level source-citation enforcement is boundary-aware (issue #196).

The wrapper must not let a citation id count as "satisfied" when it only
appears as a substring of a longer token; a real, bounded occurrence is
required. These tests exercise the enforcement through ``LLMClient.complete``
rather than the policy helper alone.
"""

from __future__ import annotations

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import LLMConfig
from lms.llm.exceptions import SourceConstraintViolation
from lms.llm.providers import FakeProvider


def _client(response_text: str) -> LLMClient:
    """Build a client whose fake provider always returns ``response_text``."""
    provider = FakeProvider(responder=lambda _model, _prompt: response_text)
    config = LLMConfig(
        mode_models={
            "study-coach": "fake-haiku",
            "practice": "fake-haiku",
            "transfer": "fake-sonnet",
            "authoring-assist": "fake-sonnet",
        },
        global_daily_cap_micro_usd=10_000_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000_000)
    return LLMClient(config=config, providers={"fake": provider}, budget=budget)


def test_complete_rejects_substring_only_citation() -> None:
    # Required citation 'src1' appears only inside 'src12' — not a real citation.
    client = _client("see src12 for the full derivation")

    with pytest.raises(SourceConstraintViolation):
        client.complete(
            mode="practice",
            prompt="x",
            trace_class="ephemeral",
            source_constraints=["src1"],
        )


def test_complete_accepts_bounded_citation() -> None:
    client = _client("per src1 the claim holds")

    response = client.complete(
        mode="practice",
        prompt="x",
        trace_class="ephemeral",
        source_constraints=["src1"],
    )

    assert response.text == "per src1 the claim holds"
