"""Provider adapter interface and in-process fake for unit tests.

The wrapper handles token/cost normalization on top of small per-provider
adapters. Real provider adapters (Anthropic, OpenAI, Bedrock) implement the
same ``complete`` interface; unit tests use ``FakeProvider`` to avoid network
calls and stable across CI environments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ProviderResponse:
    """Normalized completion result returned by a provider adapter."""

    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)


class ProviderAdapter(Protocol):
    """Minimal provider interface the wrapper calls into."""

    name: str

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> ProviderResponse:
        """Issue a single completion call and return normalized accounting."""
        ...


@dataclass
class FakeProvider:
    """In-process provider used by unit tests and the replay surface.

    Callers pass a ``responder`` callback that returns the response text for a
    given (model, prompt) pair; cost and token counts are deterministic so tests
    can assert budget preflight precisely.
    """

    name: str = "fake"
    responder: Callable[[str, str], str] = field(
        default=lambda _model, prompt: f"echo:{prompt}",
    )
    input_token_cost_micro_usd: int = 1
    output_token_cost_micro_usd: int = 4

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> ProviderResponse:
        text = self.responder(model, prompt)
        input_tokens = max(1, len(prompt.split()))
        output_tokens = max(1, len(text.split()))
        if max_tokens is not None:
            output_tokens = min(output_tokens, max_tokens)
        cost_micro_usd = (
            input_tokens * self.input_token_cost_micro_usd
            + output_tokens * self.output_token_cost_micro_usd
        )
        return ProviderResponse(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micro_usd=cost_micro_usd,
            raw_metadata={"timeout_seconds": timeout_seconds},
        )
