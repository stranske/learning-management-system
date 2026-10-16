"""Exceptions raised by the LLM client wrapper."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for LLM client failures the wrapper enforces locally."""


class BudgetExceeded(LLMError):  # noqa: N818 - issue #25 mandates this name
    """Raised when a call's projected cost would exceed a configured cap.

    The wrapper hard-kills the call before any provider request is issued so
    fail-closed budget posture is observable in tests.
    """


class SourceConstraintViolation(LLMError):  # noqa: N818 - paired with BudgetExceeded
    """Raised when a mode requires source citations and the response omits them.

    The provider call that failed citation checks is already budget-committed.
    Callers that retry (for example citation-fallback on the study-coach route)
    must fold these billable fields into the persisted turn without charging the
    budget for the failed attempt again.
    """

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_micro_usd: int = 0,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_micro_usd = cost_micro_usd
        self.provider = provider
        self.model = model


class ProviderCallError(LLMError):
    """Raised when an underlying provider API call fails.

    Wraps provider-SDK errors (rate limits, timeouts, transient 5xx,
    connection failures) — after any bounded retries are exhausted — so call
    sites can catch a single :class:`LLMError` type instead of importing and
    handling SDK-specific exception classes. The original SDK error is chained
    via ``__cause__``.
    """


class StructuredOutputValidationError(LLMError):
    """Raised when the model response cannot be validated against the schema."""
