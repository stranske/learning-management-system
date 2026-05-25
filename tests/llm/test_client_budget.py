"""Tests for the LLM client wrapper's budget preflight kill-switch."""

from __future__ import annotations

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import LLMConfig
from lms.llm.exceptions import BudgetExceeded
from lms.llm.providers import FakeProvider, ProviderResponse


def _client(*, global_cap_micro_usd: int, mode_caps: dict[str, int] | None = None) -> LLMClient:
    provider = FakeProvider()
    config = LLMConfig(
        mode_models={
            "study-coach": "fake-haiku",
            "practice": "fake-haiku",
            "transfer": "fake-sonnet",
            "authoring-assist": "fake-sonnet",
        },
        global_daily_cap_micro_usd=global_cap_micro_usd,
        per_mode_daily_cap_micro_usd=mode_caps or {},
        default_provider="fake",
    )
    budget = DailyBudgetTracker(
        mode_caps_micro_usd=mode_caps or {},
        global_cap_micro_usd=global_cap_micro_usd,
    )
    return LLMClient(config=config, providers={"fake": provider}, budget=budget)


def test_budget_preflight_blocks_over_cap_call() -> None:
    """A call whose projected cost exceeds the daily cap is hard-killed."""
    client = _client(global_cap_micro_usd=10)

    with pytest.raises(BudgetExceeded):
        client.complete(
            mode="study-coach",
            prompt="explain compound interest with a worked example",
            trace_class="formative",
        )

    assert client.budget.spent_micro_usd() == 0


def test_budget_preflight_allows_under_cap_call_and_records_actual_spend() -> None:
    """Calls under the cap go through and accumulate per-mode and global spend."""
    client = _client(global_cap_micro_usd=10_000)

    response = client.complete(
        mode="practice",
        prompt="three quick recall items on cell respiration",
        trace_class="formative",
    )

    assert response.session.cost_micro_usd > 0
    assert client.budget.spent_micro_usd() == response.session.cost_micro_usd
    assert client.budget.spent_micro_usd("practice") == response.session.cost_micro_usd


def test_per_mode_cap_blocks_even_when_global_cap_has_room() -> None:
    """The tighter of global and per-mode caps wins."""
    client = _client(
        global_cap_micro_usd=10_000,
        mode_caps={"study-coach": 5},
    )

    with pytest.raises(BudgetExceeded):
        client.complete(
            mode="study-coach",
            prompt="walk me through the proof",
            trace_class="formative",
        )

    assert client.budget.spent_micro_usd() == 0


class _UnpricedProvider:
    name = "unpriced"

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> ProviderResponse:
        return ProviderResponse(
            text="ok",
            model=model,
            provider=self.name,
            input_tokens=max(1, len(prompt.split())),
            output_tokens=1,
            cost_micro_usd=1,
            raw_metadata={"timeout_seconds": timeout_seconds},
        )


def test_unpriced_provider_uses_fail_closed_preflight_estimate() -> None:
    provider = _UnpricedProvider()
    config = LLMConfig(
        mode_models={
            "study-coach": "unpriced-model",
            "practice": "unpriced-model",
            "transfer": "unpriced-model",
            "authoring-assist": "unpriced-model",
        },
        global_daily_cap_micro_usd=10_000,
        default_provider="unpriced",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000)
    client = LLMClient(config=config, providers={"unpriced": provider}, budget=budget)

    with pytest.raises(BudgetExceeded):
        client.complete(
            mode="study-coach",
            prompt="short prompt",
            trace_class="formative",
        )

    assert client.budget.spent_micro_usd() == 0
