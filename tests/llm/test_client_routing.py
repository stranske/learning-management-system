"""Tests for per-mode model routing through the LLM client wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig, load_llm_config_from_env
from lms.llm.exceptions import BudgetExceeded, LLMError
from lms.llm.providers import AnthropicProvider, FakeProvider, build_default_providers

# ---------------------------------------------------------------------------
# Minimal stub for AnthropicProvider tests (no real network calls)
# ---------------------------------------------------------------------------


@dataclass
class _StubUsage:
    input_tokens: int = 10
    output_tokens: int = 5


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


@dataclass
class _StubMessage:
    content: list[_StubTextBlock]
    usage: _StubUsage
    id: str = "msg_routing_stub"
    stop_reason: str = "end_turn"


class _StubMessagesNS:
    def create(self, **kwargs: Any) -> _StubMessage:
        return _StubMessage(
            content=[_StubTextBlock(text="stub-routing-response")],
            usage=_StubUsage(),
        )


class _StubAnthropicClient:
    def __init__(self) -> None:
        self.messages = _StubMessagesNS()


def _make_client(mode_models: dict[str, str]) -> tuple[LLMClient, FakeProvider]:
    provider = FakeProvider()
    config = LLMConfig(
        mode_models=mode_models,
        global_daily_cap_micro_usd=10_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(
        mode_caps_micro_usd={},
        global_cap_micro_usd=10_000,
    )
    return LLMClient(config=config, providers={"fake": provider}, budget=budget), provider


def test_mode_resolves_model_from_config() -> None:
    """Each LLM mode resolves to the configured model id without code changes."""
    client, _ = _make_client(
        {
            "study-coach": "fake-coach",
            "practice": "fake-practice",
            "transfer": "fake-transfer",
            "authoring-assist": "fake-authoring",
        }
    )

    coach = client.complete(mode="study-coach", prompt="hello", trace_class="formative")
    transfer = client.complete(mode="transfer", prompt="hello", trace_class="formative")

    assert coach.session.model == "fake-coach"
    assert transfer.session.model == "fake-transfer"


def test_unknown_mode_raises() -> None:
    client, _ = _make_client({mode: f"fake-{mode}" for mode in DEFAULT_MODE_MODELS})
    with pytest.raises(LLMError):
        client.complete(mode="invalid-mode", prompt="hi", trace_class="formative")


def test_load_llm_config_from_env_uses_env_overrides() -> None:
    """``LLM_MODEL_<MODE>`` env vars override the per-mode default."""
    env = {
        "LLM_MODEL_STUDY_COACH": "env-coach",
        "LLM_MODEL_TRANSFER": "env-transfer",
        "LLM_DAILY_CAP_MICRO_USD": "12345",
    }

    config = load_llm_config_from_env(env)

    assert config.mode_models["study-coach"] == "env-coach"
    assert config.mode_models["transfer"] == "env-transfer"
    # Modes not overridden fall back to defaults.
    assert config.mode_models["practice"] == DEFAULT_MODE_MODELS["practice"]
    assert config.global_daily_cap_micro_usd == 12345


def test_load_llm_config_honors_render_budget_usd_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_DAILY_CAP_MICRO_USD", raising=False)
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "2.50")

    config = load_llm_config_from_env()

    assert config.global_daily_cap_micro_usd == 2_500_000


@pytest.mark.parametrize(
    ("budget_usd", "expected_micro_usd"),
    [("0", 0), ("0.000001", 1), ("1.000001", 1_000_001), ("0.0000019", 1)],
)
def test_render_budget_conversion_uses_decimal_precision(
    budget_usd: str, expected_micro_usd: int
) -> None:
    config = load_llm_config_from_env({"LLM_DAILY_BUDGET_USD": budget_usd})

    assert config.global_daily_cap_micro_usd == expected_micro_usd


@pytest.mark.parametrize("micro_usd", ["0", "12345"])
def test_micro_usd_budget_override_takes_precedence(micro_usd: str) -> None:
    config = load_llm_config_from_env(
        {"LLM_DAILY_CAP_MICRO_USD": micro_usd, "LLM_DAILY_BUDGET_USD": "invalid"}
    )

    assert config.global_daily_cap_micro_usd == int(micro_usd)


@pytest.mark.parametrize("budget_usd", ["", "invalid", "NaN", "Infinity", "-Infinity", "-0.01"])
def test_render_budget_rejects_invalid_values(budget_usd: str) -> None:
    with pytest.raises(ValueError, match="LLM_DAILY_BUDGET_USD"):
        load_llm_config_from_env({"LLM_DAILY_BUDGET_USD": budget_usd})


def test_missing_budget_preserves_default_cap() -> None:
    assert load_llm_config_from_env({}).global_daily_cap_micro_usd == 200_000


def test_provider_kwarg_overrides_default_provider() -> None:
    """Callers can route to a non-default provider per call."""
    provider_default = FakeProvider(name="default")
    provider_alt = FakeProvider(name="alt")
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "fake-model"),
        global_daily_cap_micro_usd=10_000,
        default_provider="default",
    )
    budget = DailyBudgetTracker(
        mode_caps_micro_usd={},
        global_cap_micro_usd=10_000,
    )
    client = LLMClient(
        config=config,
        providers={"default": provider_default, "alt": provider_alt},
        budget=budget,
    )

    response = client.complete(
        mode="study-coach",
        prompt="hi",
        trace_class="formative",
        provider_name="alt",
    )

    assert response.session.provider == "alt"


# ---------------------------------------------------------------------------
# provider:model parsing (acceptance criterion 2)
# ---------------------------------------------------------------------------


def test_provider_and_model_for_splits_colon_notation() -> None:
    """``provider:model`` strings are split into (provider, model)."""
    config = LLMConfig(
        mode_models={**dict(DEFAULT_MODE_MODELS), "study-coach": "anthropic:claude-sonnet-4-5"},
        global_daily_cap_micro_usd=10_000,
        default_provider="fake",
    )
    provider_name, model = config.provider_and_model_for("study-coach")
    assert provider_name == "anthropic"
    assert model == "claude-sonnet-4-5"


def test_provider_and_model_for_bare_model_returns_none_provider() -> None:
    """Bare model strings (no colon) return ``None`` for provider."""
    config = LLMConfig(
        mode_models=dict(DEFAULT_MODE_MODELS),
        global_daily_cap_micro_usd=10_000,
        default_provider="fake",
    )
    provider_name, model = config.provider_and_model_for("study-coach")
    assert provider_name is None
    assert model == DEFAULT_MODE_MODELS["study-coach"]


# ---------------------------------------------------------------------------
# Anthropic provider routing (acceptance criterion 1)
# ---------------------------------------------------------------------------


def test_resolved_provider_is_fake_when_no_api_key() -> None:
    """Without an API key, build_default_providers selects FakeProvider for study-coach."""
    providers, default_provider = build_default_providers(anthropic_api_key=None)
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "fake-model"),
        global_daily_cap_micro_usd=10_000,
        default_provider=default_provider,
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000)
    client = LLMClient(config=config, providers=providers, budget=budget)

    response = client.complete(mode="study-coach", prompt="test", trace_class="formative")

    assert isinstance(providers[default_provider], FakeProvider)
    assert response.session.provider == "fake"


def test_resolved_provider_is_anthropic_and_model_is_sonnet_when_key_set() -> None:
    """With key set (SDK mocked), resolved provider is AnthropicProvider and model is claude-sonnet-4-5."""
    stub_client = _StubAnthropicClient()
    providers, default_provider = build_default_providers(anthropic_api_key="sk-ant-test")
    # Replace the real AnthropicProvider with a stub-backed one.
    providers["anthropic"] = AnthropicProvider(
        api_key="sk-ant-test",
        client_factory=lambda _key: stub_client,
    )
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "anthropic:claude-sonnet-4-5"),
        # Use a generous cap: AnthropicProvider has no preflight-rate attrs so
        # _estimate_cost falls back to the 1000/4000 micro-USD heuristic.
        global_daily_cap_micro_usd=10_000_000,
        default_provider=default_provider,
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000_000)
    client = LLMClient(config=config, providers=providers, budget=budget)

    response = client.complete(mode="study-coach", prompt="test", trace_class="formative")

    assert isinstance(providers["anthropic"], AnthropicProvider)
    assert response.session.provider == "anthropic"
    assert response.session.model == "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# env-var provider selection (acceptance criterion 4)
# ---------------------------------------------------------------------------


def test_default_provider_selectable_via_llm_default_provider_env() -> None:
    """``LLM_DEFAULT_PROVIDER`` selects default_provider with no source edit required."""
    config = load_llm_config_from_env({"LLM_DEFAULT_PROVIDER": "anthropic"})
    assert config.default_provider == "anthropic"


def test_default_provider_is_fake_when_env_var_absent() -> None:
    """Without ``LLM_DEFAULT_PROVIDER``, default_provider falls back to ``fake``."""
    config = load_llm_config_from_env({})
    assert config.default_provider == "fake"


def test_default_api_client_honors_mode_model_env_override(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """The API route default client keeps Segment 10 per-mode env overrides."""
    from lms.llm import api as llm_api
    from lms.settings import get_settings

    request.addfinalizer(llm_api._default_client.cache_clear)
    request.addfinalizer(get_settings.cache_clear)

    monkeypatch.delenv("CLAUDE_API_STRANSKE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODEL_STUDY_COACH", "fake-env-coach")
    get_settings.cache_clear()
    llm_api._default_client.cache_clear()

    client = llm_api._default_client()

    assert client.config.mode_models["study-coach"] == "fake-env-coach"
    assert client.config.mode_models["practice"] == "fake-learning-policy"


@pytest.mark.parametrize("api_key", [None, "test-api-factory-key"])
@pytest.mark.parametrize(
    ("micro_cap", "usd_cap", "expected_cap"),
    [(None, None, 200_000), (None, "0.375", 375_000), ("12345", "0.375", 12345), ("0", "0.375", 0)],
)
def test_default_api_client_applies_runtime_policy(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    api_key: str | None,
    micro_cap: str | None,
    usd_cap: str | None,
    expected_cap: int,
) -> None:
    from lms.llm import api as llm_api

    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "get_settings", lambda: SimpleNamespace(anthropic_api_key=api_key))
    for mode in DEFAULT_MODE_MODELS:
        monkeypatch.delenv(f"LLM_MODEL_{mode.upper().replace('-', '_')}", raising=False)
    for name, value in (
        ("LLM_DAILY_CAP_MICRO_USD", micro_cap),
        ("LLM_DAILY_BUDGET_USD", usd_cap),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    # Credential-driven provider choice wins over a contradictory env default.
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "fake" if api_key else "anthropic")
    monkeypatch.setenv("LLM_MODEL_STUDY_COACH", "api-override-coach")

    client = llm_api._default_client()

    expected_provider = "anthropic" if api_key else "fake"
    expected_default = "claude-haiku-4-5" if api_key else "fake-learning-policy"
    assert client.config.default_provider == expected_provider
    assert isinstance(client.providers["fake"], FakeProvider)
    assert ("anthropic" in client.providers) == bool(api_key)
    if api_key:
        assert isinstance(client.providers["anthropic"], AnthropicProvider)
    assert client.config.model_for("study-coach") == "api-override-coach"
    for mode in ("practice", "transfer", "authoring-assist"):
        assert client.config.model_for(mode) == expected_default
    assert client.config.global_daily_cap_micro_usd == expected_cap
    assert client.budget.global_cap_micro_usd == expected_cap
    # Exercise the constructed tracker at the boundary without provider traffic.
    reservation = client.budget.reserve("study-coach", expected_cap)
    with pytest.raises(BudgetExceeded, match="global daily cap"):
        client.budget.reserve("practice", 1)
    client.budget.release(reservation)
