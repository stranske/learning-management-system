"""Tests for the real Anthropic LLM provider adapter (issue #179).

These tests do not contact the real Anthropic API. The adapter accepts a
``client_factory`` callable so unit tests can inject a stub SDK client whose
``messages.create`` returns a synthesized response shaped like the real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lms.llm.providers import (
    AnthropicProvider,
    FakeProvider,
    ProviderResponse,
    build_default_providers,
)

# --- Stub Anthropic SDK shapes ----------------------------------------------


@dataclass
class _StubUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


@dataclass
class _StubMessage:
    content: list[_StubTextBlock]
    usage: _StubUsage
    id: str = "msg_test_123"
    stop_reason: str = "end_turn"


class _StubMessagesNamespace:
    """Stand-in for ``Anthropic().messages``.

    The real SDK exposes ``client.messages.create(...)``; we record every call
    so tests can assert routing details (model, max_tokens, message body, etc.).
    """

    def __init__(
        self,
        *,
        response_text: str = "Stub response from Anthropic.",
        input_tokens: int = 42,
        output_tokens: int = 17,
    ) -> None:
        self.response_text = response_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _StubMessage:
        self.calls.append(kwargs)
        return _StubMessage(
            content=[_StubTextBlock(text=self.response_text)],
            usage=_StubUsage(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
            ),
        )


class _StubClient:
    def __init__(
        self,
        *,
        response_text: str = "Stub response from Anthropic.",
        input_tokens: int = 42,
        output_tokens: int = 17,
    ) -> None:
        self.messages = _StubMessagesNamespace(
            response_text=response_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _stub_factory(
    *,
    response_text: str = "Stub response from Anthropic.",
    input_tokens: int = 42,
    output_tokens: int = 17,
) -> Any:
    """Return a ``client_factory`` callable suitable for AnthropicProvider."""
    client = _StubClient(
        response_text=response_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    # The provider invokes factory(api_key); we ignore the key but keep the
    # signature compatible so the production path stays identical to tests.
    return lambda _api_key: client


# --- Tests -------------------------------------------------------------------


def test_anthropic_provider_routes_call_to_messages_create() -> None:
    factory = _stub_factory()
    provider = AnthropicProvider(api_key="test-key", client_factory=factory)

    response = provider.complete(
        model="claude-haiku-4-5",
        prompt="Tell me about retrieval practice.",
        max_tokens=256,
        timeout_seconds=15.0,
    )

    assert isinstance(response, ProviderResponse)
    assert response.text == "Stub response from Anthropic."
    assert response.model == "claude-haiku-4-5"
    assert response.provider == "anthropic"
    assert response.input_tokens == 42
    assert response.output_tokens == 17
    # cost > 0 means the price table was consulted (rather than silently
    # falling through to a zero default)
    assert response.cost_micro_usd > 0


def test_anthropic_provider_passes_model_max_tokens_and_messages() -> None:
    factory = _stub_factory()
    provider = AnthropicProvider(api_key="test-key", client_factory=factory)
    # Trigger the call so the stub records the kwargs
    provider.complete(
        model="claude-sonnet-4-7",
        prompt="Explain spaced retrieval.",
        max_tokens=512,
        timeout_seconds=30.0,
    )
    # The stub client is built lazily on first use; reach into the provider
    # to verify the recorded call.
    client = provider._client  # noqa: SLF001  (test introspection is intentional)
    call = client.messages.calls[0]
    assert call["model"] == "claude-sonnet-4-7"
    assert call["max_tokens"] == 512
    assert call["messages"] == [{"role": "user", "content": "Explain spaced retrieval."}]
    assert call["timeout"] == 30.0


def test_anthropic_provider_omits_timeout_when_not_set() -> None:
    factory = _stub_factory()
    provider = AnthropicProvider(api_key="test-key", client_factory=factory)
    provider.complete(
        model="claude-haiku-4-5",
        prompt="No timeout please.",
        max_tokens=None,
        timeout_seconds=None,
    )
    client = provider._client  # noqa: SLF001
    call = client.messages.calls[0]
    assert "timeout" not in call
    # max_tokens defaults to the dataclass default_max_tokens when caller passes None
    assert call["max_tokens"] == provider.default_max_tokens


def test_anthropic_provider_unknown_model_uses_default_price() -> None:
    factory = _stub_factory(input_tokens=1_000, output_tokens=500)
    provider = AnthropicProvider(api_key="test-key", client_factory=factory)
    response = provider.complete(
        model="claude-some-future-model",
        prompt="Boundary test.",
        max_tokens=64,
        timeout_seconds=None,
    )
    # Default price is (3.00, 15.00) USD per million tokens =>
    # 1000 input tokens * 3.0 micro/token + 500 output tokens * 15.0 micro/token
    # = 3000 + 7500 = 10500 micro-USD
    assert response.cost_micro_usd == 10_500


def test_anthropic_provider_handles_empty_content_list() -> None:
    """If the model returns no text blocks, the adapter returns empty text rather than crashing."""
    client = _StubClient()
    client.messages = _StubMessagesNamespace()
    # Override create to return an empty content list
    client.messages.create = lambda **_kwargs: _StubMessage(  # type: ignore[method-assign]
        content=[],
        usage=_StubUsage(input_tokens=5, output_tokens=0),
    )
    provider = AnthropicProvider(api_key="test-key", client_factory=lambda _k: client)
    response = provider.complete(
        model="claude-haiku-4-5",
        prompt="empty",
        max_tokens=8,
        timeout_seconds=None,
    )
    assert response.text == ""
    assert response.input_tokens == 5
    assert response.output_tokens == 0


def test_anthropic_provider_concatenates_multiple_text_blocks() -> None:
    """Defensive: multi-block responses preserve every text block in order."""
    client = _StubClient()
    client.messages = _StubMessagesNamespace()
    client.messages.create = lambda **_kwargs: _StubMessage(  # type: ignore[method-assign]
        content=[
            _StubTextBlock(text="First block. "),
            _StubTextBlock(text="Second block."),
        ],
        usage=_StubUsage(input_tokens=10, output_tokens=20),
    )
    provider = AnthropicProvider(api_key="test-key", client_factory=lambda _k: client)
    response = provider.complete(
        model="claude-haiku-4-5",
        prompt="multi-block",
        max_tokens=64,
        timeout_seconds=None,
    )
    assert response.text == "First block. Second block."


# --- build_default_providers ------------------------------------------------


def test_build_default_providers_returns_fake_when_no_key() -> None:
    providers, default = build_default_providers(anthropic_api_key=None)
    assert default == "fake"
    assert set(providers.keys()) == {"fake"}
    assert isinstance(providers["fake"], FakeProvider)


def test_build_default_providers_registers_anthropic_when_key_set() -> None:
    providers, default = build_default_providers(anthropic_api_key="sk-ant-test-key")
    assert default == "anthropic"
    assert set(providers.keys()) == {"fake", "anthropic"}
    assert isinstance(providers["anthropic"], AnthropicProvider)
    assert providers["anthropic"].api_key == "sk-ant-test-key"
    assert providers["anthropic"].input_token_cost_micro_usd == 3
    assert providers["anthropic"].output_token_cost_micro_usd == 15


def test_build_default_providers_accepts_custom_fake_responder() -> None:
    """A custom responder lets API-level call sites keep their domain-specific stub text."""

    def custom(_model: str, prompt: str) -> str:
        return f"custom:{prompt}"

    providers, default = build_default_providers(
        anthropic_api_key=None,
        fake_responder=custom,
    )
    fake = providers["fake"]
    assert default == "fake"
    response = fake.complete(
        model="fake-model",
        prompt="hello",
        max_tokens=None,
        timeout_seconds=None,
    )
    assert response.text == "custom:hello"


@pytest.mark.parametrize(
    "env_var",
    ["CLAUDE_API_STRANSKE", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
)
def test_settings_reads_anthropic_key_from_any_documented_env_var(
    env_var: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three documented env var names resolve to ``settings.anthropic_api_key``."""
    # Clear all aliases so we test one at a time
    for name in ("CLAUDE_API_STRANSKE", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env_var, "sk-ant-from-" + env_var)

    # Settings caches via lru_cache; rebuild a fresh instance via the class
    from lms.settings import Settings

    settings = Settings()
    assert settings.anthropic_api_key == "sk-ant-from-" + env_var


def test_public_anthropic_key_helper_reads_documented_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lms.settings import read_anthropic_api_key_from_env

    for name in ("CLAUDE_API_STRANSKE", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-public-helper")

    assert read_anthropic_api_key_from_env() == "sk-ant-public-helper"
