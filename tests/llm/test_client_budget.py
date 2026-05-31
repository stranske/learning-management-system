"""Tests for the LLM client wrapper's budget preflight kill-switch."""

from __future__ import annotations

import threading

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import LLMConfig
from lms.llm.exceptions import BudgetExceeded, ProviderCallError
from lms.llm.providers import AnthropicProvider, FakeProvider, ProviderResponse


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


# --- preflight output-cost projection (issue #196) --------------------------


def test_estimate_cost_projects_output_from_default_max_tokens_when_none() -> None:
    """With ``max_tokens=None`` the preflight projects the provider's
    ``default_max_tokens`` worth of output, not a 64-token floor."""
    provider = AnthropicProvider(api_key="k", client_factory=lambda _k: object())
    # AnthropicProvider: input rate 3, output rate 15, default_max_tokens 1024.
    cost = LLMClient._estimate_cost(provider, prompt="one two three", max_tokens=None)

    assert cost == 3 * 3 + 1024 * 15
    # Strictly larger than the prior max(64, input) floor would have produced.
    assert cost > 3 * 3 + 64 * 15


def test_estimate_cost_fallback_rates_on_micro_usd_scale() -> None:
    """An adapter lacking explicit cost attrs estimates on the 3/15 scale,
    not the old ~300x-inflated (1_000, 4_000)."""

    class _Bare:
        name = "bare"

    cost = LLMClient._estimate_cost(_Bare(), prompt="a b", max_tokens=10)
    # input_tokens=2 * 3 + output 10 * 15 = 6 + 150 = 156
    assert cost == 2 * 3 + 10 * 15


# --- atomic budget reservation (issue #196) ---------------------------------


def test_commit_reconciles_reservation_to_actual_cost() -> None:
    tracker = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000)
    reservation = tracker.reserve("practice", 500)
    # Optimistic debit is visible while the call is in flight.
    assert tracker.spent_micro_usd() == 500
    tracker.commit(reservation, 120)
    assert tracker.spent_micro_usd() == 120
    assert tracker.spent_micro_usd("practice") == 120


def test_release_refunds_reservation_and_is_idempotent() -> None:
    tracker = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000)
    reservation = tracker.reserve("practice", 500)
    tracker.release(reservation)
    assert tracker.spent_micro_usd() == 0
    # A second settle (release or commit) on the same reservation is a no-op.
    tracker.release(reservation)
    tracker.commit(reservation, 999)
    assert tracker.spent_micro_usd() == 0


def test_concurrent_reservations_cannot_both_pass_against_stale_spend() -> None:
    """Two threads racing to reserve cannot both pass preflight and overspend.

    With a 100 cap and two 60 reservations, 60+60=120 would breach the cap;
    the lock must let exactly one succeed. Without holding the lock across the
    check-and-debit, both could read 0 and both reserve.
    """
    tracker = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=100)
    barrier = threading.Barrier(2)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()  # release both threads simultaneously to maximize contention
        try:
            tracker.reserve("study-coach", 60)
            outcome = "ok"
        except BudgetExceeded:
            outcome = "blocked"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["blocked", "ok"]
    assert tracker.spent_micro_usd() == 60


def test_failed_provider_call_refunds_budget_reservation() -> None:
    """If the provider call raises, the reservation is released, not retained."""

    class _FailingProvider:
        name = "failing"
        input_token_cost_micro_usd = 3
        output_token_cost_micro_usd = 15
        default_max_tokens = 1024

        def complete(
            self,
            *,
            model: str,
            prompt: str,
            max_tokens: int | None,
            timeout_seconds: float | None,
        ) -> ProviderResponse:
            raise ProviderCallError("boom")

    config = LLMConfig(
        mode_models={
            "study-coach": "failing-model",
            "practice": "failing-model",
            "transfer": "failing-model",
            "authoring-assist": "failing-model",
        },
        global_daily_cap_micro_usd=10_000_000,
        default_provider="failing",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000_000)
    client = LLMClient(config=config, providers={"failing": _FailingProvider()}, budget=budget)

    with pytest.raises(ProviderCallError):
        client.complete(mode="practice", prompt="hello", trace_class="formative")

    assert client.budget.spent_micro_usd() == 0
