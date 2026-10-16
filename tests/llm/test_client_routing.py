"""Tests for per-mode model routing through the LLM client wrapper."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import GoldSetEntry, LLMClient
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


@pytest.mark.parametrize("mode_override", [None, "practice"])
@pytest.mark.parametrize(
    ("configured_model", "provider_override", "expected_provider", "expected_model"),
    [
        ("anthropic:claude-haiku-4-5", None, "anthropic", "claude-haiku-4-5"),
        ("anthropic:claude-haiku-4-5", "alt", "alt", "claude-haiku-4-5"),
        ("bare-model", None, "fake", "bare-model"),
        ("bare-model", "alt", "alt", "bare-model"),
    ],
)
def test_replay_routes_configured_provider_and_model(
    configured_model: str,
    provider_override: str | None,
    expected_provider: str,
    expected_model: str,
    mode_override: str | None,
) -> None:
    """Replay shares routing precedence while keeping eval accounting isolated."""
    mode = mode_override or "study-coach"
    client, _ = _make_client(
        {**dict.fromkeys(DEFAULT_MODE_MODELS, "unused-model"), mode: configured_model}
    )
    calls: list[tuple[str, str, str]] = []

    def record_call(provider: str, model: str, prompt: str) -> str:
        calls.append((provider, model, prompt))
        return "replayed response"

    client.providers = {
        name: FakeProvider(
            name=name,
            responder=partial(record_call, name),
        )
        for name in ("fake", "anthropic", "alt")
    }
    # Exhaust the production budget: replay must neither reserve nor debit it.
    client.budget.record(mode, 10_000)
    exports: list[str] = []
    client.trace_exporter = lambda _session, text: exports.append(text)

    response = client.replay(
        GoldSetEntry(
            entry_id="routing-gold",
            mode="study-coach",
            prompt="Explain retrieval practice",
            trace_class="formative",
        ),
        mode_override=mode_override,
        provider_name=provider_override,
    )

    assert calls == [(expected_provider, expected_model, "Explain retrieval practice")]
    assert response.session.provider == expected_provider
    assert response.session.model == expected_model
    assert response.session.mode == mode
    assert response.session.is_replay is True
    assert response.session.external_export_allowed is False
    assert client.budget.spent_micro_usd() == 10_000
    assert client.budget.spent_micro_usd(mode) == 10_000
    assert exports == []


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
    # Without an explicit override, credential detection selects the provider.
    monkeypatch.delenv("LLM_DEFAULT_PROVIDER", raising=False)
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


def test_explicit_provider_override_is_honored(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """An operator can suspend live provider calls without removing the key."""
    from lms.llm import api as llm_api

    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(
        llm_api,
        "get_settings",
        lambda: SimpleNamespace(anthropic_api_key="sk-ant-test"),
    )
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "fake")

    client = llm_api._default_client()

    assert client.config.default_provider == "fake"
    assert isinstance(client.providers["anthropic"], AnthropicProvider)
    assert isinstance(client.providers["fake"], FakeProvider)
    response = client.complete(mode="study-coach", prompt="hello", trace_class="formative")
    assert response.session.provider == "fake"

    monkeypatch.setenv("LLM_MODEL_STUDY_COACH", "anthropic:claude-haiku-4-5")
    llm_api._default_client.cache_clear()
    client = llm_api._default_client()
    assert (
        client.complete(
            mode="study-coach", prompt="hello", trace_class="formative"
        ).session.provider
        == "fake"
    )
    assert (
        client.replay(
            GoldSetEntry(entry_id="fake-override", mode="study-coach", prompt="hello")
        ).session.provider
        == "fake"
    )
    client.providers["anthropic"] = FakeProvider(name="anthropic")
    assert (
        client.complete(
            mode="study-coach", prompt="hello", trace_class="formative", provider_name="anthropic"
        ).session.provider
        == "anthropic"
    )


@pytest.mark.parametrize("override", ["unregistered", "anthropic"])
def test_unregistered_provider_override_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    override: str,
) -> None:
    """The override must exist in the registry built from available keys."""
    from lms.llm import api as llm_api

    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "get_settings", lambda: SimpleNamespace(anthropic_api_key=None))
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", override)

    with pytest.raises(ValueError, match=f"LLM_DEFAULT_PROVIDER='{override}' is not registered"):
        llm_api._default_client()


# ---------------------------------------------------------------------------
# study-coach HTTP route provider selection (issue #763)
# ---------------------------------------------------------------------------


def _seed_published_study_prompt(
    session: Session,
    *,
    stable_locator: str = "source:study-coach-1",
) -> dict[str, str]:
    from lms.graphs.repository import create_knowledge_node
    from lms.learners.repository import create_learner_for_user, create_learning_goal
    from lms.prompts.repository import create_prompt, publish_prompt
    from lms.sources.repository import create_source_reference

    user_id = "user-study-coach-routing"
    node = create_knowledge_node(
        session,
        title="Study coach routing",
        knowledge_type="conceptual",
        scope="personal",
        status="published",
        actor_id=f"user:{user_id}",
    )
    learner = create_learner_for_user(
        session,
        user_id=user_id,
        display_name="Routing Learner",
    )
    goal = create_learning_goal(
        session,
        learner_id=learner.id,
        title="Routing goal",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    source = create_source_reference(
        session,
        source_type="url",
        stable_locator=stable_locator,
        content="study coach routing fixture",
        actor_id=f"user:{user_id}",
    )
    prompt = create_prompt(
        session,
        target_node_id=node.id,
        learning_goal_id=goal.id,
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        body="Explain the routing fixture.",
        source_reference_ids=[source.id],
        authoring_method="human-authored",
        authoring_actor=f"user:{user_id}",
    )
    publish_prompt(session, prompt, reviewing_actor=f"user:{user_id}")
    session.commit()
    return {
        "learner_id": learner.id,
        "prompt_id": prompt.id,
        "stable_locator": stable_locator,
        "source_id": source.id,
    }


def _recording_client(
    *,
    default_provider: str,
    responder: Callable[[str, str, str], str] | None = None,
) -> tuple[LLMClient, dict[str, FakeProvider], list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    def _record(name: str, model: str, prompt: str) -> str:
        calls.append((name, model))
        if responder is not None:
            return responder(name, model, prompt)
        return "Here is a concise explanation tied to the requested learning goal."

    providers = {
        name: FakeProvider(
            name=name,
            responder=partial(_record, name),
        )
        for name in ("fake", "alt")
    }
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "routing-model"),
        global_daily_cap_micro_usd=10_000_000,
        default_provider=default_provider,
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000_000)
    client = LLMClient(config=config, providers=providers, budget=budget)
    return client, providers, calls


def test_http_sessions_rejects_unknown_prompt_before_provider_call(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from lms.llm import api as llm_api

    client, _session_factory = api_client
    recording_client, _, calls = _recording_client(default_provider="alt")
    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording_client)

    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "prompt_id": "missing-prompt-id",
            "user_message": "Explain this.",
        },
    )

    assert response.status_code == 404
    assert calls == []


def test_http_sessions_rejects_unauthorized_source_before_provider_call(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from lms.llm import api as llm_api

    http_client, session_factory = api_client
    with session_factory() as session:
        ids = _seed_published_study_prompt(session)
    recording_client, _, calls = _recording_client(default_provider="alt")
    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording_client)

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "mode": "study-coach",
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this.",
            "source_constraints": ["source:not-linked"],
        },
    )

    assert response.status_code == 422
    assert "unauthorized source references" in response.json()["detail"]
    assert calls == []


def test_http_sessions_rejects_unauthorized_source_before_citation_fallback(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Citation fallback must not run when source references fail the boundary."""
    from lms.llm import api as llm_api

    http_client, session_factory = api_client
    with session_factory() as session:
        ids = _seed_published_study_prompt(session)
    recording_client, _, calls = _recording_client(
        default_provider="alt",
        responder=lambda _name, _model, _prompt: "uncited generated text",
    )
    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording_client)

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "mode": "study-coach",
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this.",
            "source_constraints": ["source:not-linked"],
        },
    )

    assert response.status_code == 422
    assert calls == []


def test_http_sessions_uses_configured_default_provider(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from lms.llm import api as llm_api
    from lms.llm.models import LLMSession

    http_client, session_factory = api_client
    recording_client, _, calls = _recording_client(default_provider="alt")
    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording_client)

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Give me an overview.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [("alt", "routing-model")]
    with session_factory() as session:
        stored = session.get(LLMSession, body["session_id"])
    assert stored is not None
    assert stored.provider == "alt"
    assert stored.model == "routing-model"
    assert stored.cost_micro_usd > 0


def test_http_sessions_citation_fallback_keeps_same_provider(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from lms.llm import api as llm_api
    from lms.llm.models import LLMSession

    http_client, session_factory = api_client
    with session_factory() as session:
        ids = _seed_published_study_prompt(session, stable_locator="source:cited-1")
    recording_client, _, calls = _recording_client(
        default_provider="alt",
        responder=lambda _name, _model, _prompt: "uncited generated text",
    )
    llm_api._default_client.cache_clear()
    request.addfinalizer(llm_api._default_client.cache_clear)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording_client)

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "mode": "study-coach",
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this.",
            "source_constraints": [ids["stable_locator"]],
        },
    )

    assert response.status_code == 200
    assert calls == [("alt", "routing-model"), ("alt", "routing-model")]
    body = response.json()
    assert "unverified" in body["flags"]
    with session_factory() as session:
        stored = session.get(LLMSession, body["session_id"])
    assert stored is not None
    assert stored.provider == "alt"


def test_http_sessions_explicit_fake_override_stays_deterministic(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from lms.llm import api as llm_api
    from lms.llm.models import LLMSession
    from lms.settings import get_settings

    http_client, session_factory = api_client
    request.addfinalizer(llm_api._default_client.cache_clear)
    request.addfinalizer(get_settings.cache_clear)
    monkeypatch.delenv("CLAUDE_API_STRANSKE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "fake")
    get_settings.cache_clear()
    llm_api._default_client.cache_clear()

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Give me an overview.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    with session_factory() as session:
        stored = session.get(LLMSession, body["session_id"])
    assert stored is not None
    assert stored.provider == "fake"
    assert stored.model == "fake-learning-policy"


def test_http_sessions_no_key_mode_stays_deterministic(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Without provider keys, POST /llm/sessions stays on the fake adapter."""
    from lms.llm import api as llm_api
    from lms.llm.models import LLMSession
    from lms.settings import get_settings

    http_client, session_factory = api_client
    request.addfinalizer(llm_api._default_client.cache_clear)
    request.addfinalizer(get_settings.cache_clear)
    monkeypatch.delenv("CLAUDE_API_STRANSKE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_DEFAULT_PROVIDER", raising=False)
    get_settings.cache_clear()
    llm_api._default_client.cache_clear()

    response = http_client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Give me an overview.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    with session_factory() as session:
        stored = session.get(LLMSession, body["session_id"])
    assert stored is not None
    assert stored.provider == "fake"
    assert stored.model == "fake-learning-policy"
    assert body["model"] == "fake-learning-policy"
