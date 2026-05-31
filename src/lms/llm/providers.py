"""Provider adapter interface, in-process fake, and real Anthropic adapter.

The LLM wrapper handles budget preflight, trace classification, and token/cost
normalization on top of small per-provider adapters. Real provider adapters
(currently Anthropic; OpenAI and Bedrock are future work) implement the same
``complete`` interface; unit tests use ``FakeProvider`` to stay deterministic
and network-free.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from lms.llm.exceptions import ProviderCallError


@lru_cache(maxsize=1)
def _anthropic_error_types() -> tuple[tuple[type[BaseException], ...], tuple[type[BaseException], ...]]:
    """Resolve ``(wrappable, retryable)`` anthropic SDK error classes.

    Imported lazily and cached so the module still loads when ``anthropic`` is
    not installed (the SDK is a declared runtime dependency, but unit tests run
    against stub clients). ``wrappable`` is the SDK's base ``APIError`` — any
    provider error is re-raised as :class:`ProviderCallError`. ``retryable`` is
    the subset worth a bounded retry (rate limits, timeouts, connection drops,
    5xx). Empty tuples (SDK absent) make ``except ()`` a no-op so raw errors
    propagate rather than being silently swallowed.
    """
    try:
        import anthropic
    except Exception:  # pragma: no cover - SDK is a declared dependency
        return (), ()

    base = getattr(anthropic, "APIError", None)
    wrappable = (base,) if isinstance(base, type) else ()
    retryable = tuple(
        cls
        for cls in (
            getattr(anthropic, "RateLimitError", None),
            getattr(anthropic, "APITimeoutError", None),
            getattr(anthropic, "APIConnectionError", None),
            getattr(anthropic, "InternalServerError", None),
        )
        if isinstance(cls, type)
    )
    return wrappable, retryable


def _is_retryable_provider_error(
    exc: BaseException,
    retryable_types: tuple[type[BaseException], ...],
) -> bool:
    """Decide whether a provider error is transient enough to retry.

    Retries the known transient SDK error classes, plus anything carrying a
    429 or 5xx ``status_code`` (covers SDK versions whose status subclasses are
    not enumerated above).
    """
    if retryable_types and isinstance(exc, retryable_types):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or 500 <= status < 600)


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
        if max_tokens is not None:
            text = " ".join(text.split()[:max_tokens])
        output_tokens = max(1, len(text.split()))
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


# Anthropic pricing table (USD per million tokens) used for cost normalization.
# Values reflect public Anthropic API pricing as of 2026-05. The table is small
# and explicit so a new model can be added by editing one entry rather than
# touching the adapter logic. Unknown models fall back to ``_DEFAULT_PRICE``
# (matches Sonnet pricing) so a typo or a freshly-released model still produces
# a reasonable budget estimate.
_ANTHROPIC_PRICES_USD_PER_MTOKENS: Mapping[str, tuple[float, float]] = {
    # (input_usd_per_mtokens, output_usd_per_mtokens)
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-7": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "claude-3-5-haiku-20241022": (1.00, 5.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-opus-20240229": (15.00, 75.00),
}
_DEFAULT_PRICE: tuple[float, float] = (3.00, 15.00)


def _anthropic_cost_micro_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> int:
    """Compute the cost of a completion in micro-USD using the price table.

    Micro-USD (1e-6 USD) is the LMS-wide accounting unit because integer math
    avoids float-drift in budget preflight comparisons.
    """
    input_price, output_price = _ANTHROPIC_PRICES_USD_PER_MTOKENS.get(model, _DEFAULT_PRICE)
    # price is USD per million tokens; convert to micro-USD per token:
    # (USD/M tokens) * 1e6 micro/USD / 1e6 tokens/M = micro-USD per token.
    input_micro_per_token = input_price
    output_micro_per_token = output_price
    return int(round(input_tokens * input_micro_per_token + output_tokens * output_micro_per_token))


@dataclass
class AnthropicProvider:
    """Real-network provider that calls Anthropic's Messages API.

    Construction is lazy: the SDK client is built on the first ``complete``
    call so the provider can be registered alongside ``FakeProvider`` without
    requiring the ``anthropic`` package or a valid API key at import time.
    Unit tests pass a stub ``client_factory`` to avoid both.
    """

    api_key: str
    name: str = "anthropic"
    input_token_cost_micro_usd: int = int(_DEFAULT_PRICE[0])
    output_token_cost_micro_usd: int = int(_DEFAULT_PRICE[1])
    client_factory: Callable[[str], Any] | None = None
    # max_tokens default for calls that don't specify one; Anthropic requires
    # the field on every Messages request.
    default_max_tokens: int = 1024
    # Bounded retry for transient provider failures (rate limits, timeouts,
    # 5xx). ``max_retries`` is the number of *additional* attempts after the
    # first, so the default issues up to 3 calls. Backoff is exponential from
    # ``retry_backoff_seconds``. ``sleep_func`` is injectable so tests run
    # without real delays.
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    sleep_func: Callable[[float], None] = time.sleep
    _client: Any = field(default=None, init=False, repr=False)

    def _build_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory(self.api_key)
        # Local import keeps the SDK as a runtime-only dependency and lets the
        # rest of the module load even when ``anthropic`` is not installed.
        from anthropic import Anthropic

        return Anthropic(api_key=self.api_key)

    def _client_or_build(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def _create_with_retry(self, client: Any, call_kwargs: dict[str, Any]) -> Any:
        """Call ``client.messages.create`` with bounded retry and error wrapping.

        Transient SDK errors (rate limits, timeouts, connection drops, 5xx) are
        retried with exponential backoff up to ``max_retries`` times; any SDK
        error that remains is re-raised as :class:`ProviderCallError` so callers
        never see a raw ``anthropic.APIError``. Non-SDK exceptions (e.g. a bug
        in our own code) are left to propagate unwrapped.
        """
        wrappable_types, retryable_types = _anthropic_error_types()
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                return client.messages.create(**call_kwargs)
            except wrappable_types as exc:
                is_last = attempt + 1 >= attempts
                if not is_last and _is_retryable_provider_error(exc, retryable_types):
                    self.sleep_func(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise ProviderCallError(
                    f"anthropic completion failed after {attempt + 1} attempt(s): "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        # Unreachable: the loop either returns on success or raises on the final
        # attempt, but keep an explicit guard so the method never returns None.
        raise ProviderCallError("anthropic completion exhausted retries")  # pragma: no cover

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None,
        timeout_seconds: float | None,
    ) -> ProviderResponse:
        client = self._client_or_build()
        # Anthropic's SDK accepts ``timeout`` as a top-level kwarg on each call;
        # ``None`` means "use the SDK default" so we only pass it when set.
        call_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens if max_tokens is not None else self.default_max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if timeout_seconds is not None:
            call_kwargs["timeout"] = timeout_seconds
        message = self._create_with_retry(client, call_kwargs)

        # The SDK returns a list of content blocks; the common case is one
        # ``TextBlock`` whose ``.text`` is the model output. We concatenate
        # all text blocks defensively so multi-block responses don't truncate.
        text_parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if text is not None:
                text_parts.append(text)
        text = "".join(text_parts)

        usage = getattr(message, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        cost_micro_usd = _anthropic_cost_micro_usd(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        return ProviderResponse(
            text=text,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micro_usd=cost_micro_usd,
            raw_metadata={
                "timeout_seconds": timeout_seconds,
                "stop_reason": getattr(message, "stop_reason", None),
                "message_id": getattr(message, "id", None),
            },
        )


def build_default_providers(
    *,
    anthropic_api_key: str | None = None,
    fake_responder: Callable[[str, str], str] | None = None,
) -> tuple[dict[str, ProviderAdapter], str]:
    """Build the standard provider registry and pick the default name.

    Returns ``(providers, default_provider_name)``.

    The fake provider is always registered so unit tests and budget-preflight
    paths can target it explicitly. When ``anthropic_api_key`` is provided,
    ``AnthropicProvider`` is registered too and becomes the default; otherwise
    the default falls back to the fake provider so dev environments without
    keys still produce deterministic output.
    """
    fake = FakeProvider(responder=fake_responder) if fake_responder is not None else FakeProvider()
    providers: dict[str, ProviderAdapter] = {fake.name: fake}
    default = fake.name
    if anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(api_key=anthropic_api_key)
        default = "anthropic"
    return providers, default
