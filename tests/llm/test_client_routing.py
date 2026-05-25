"""Tests for per-mode model routing through the LLM client wrapper."""

from __future__ import annotations

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig, load_llm_config_from_env
from lms.llm.exceptions import LLMError
from lms.llm.providers import FakeProvider


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
