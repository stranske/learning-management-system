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
    """Raised when a mode requires source citations and the response omits them."""


class StructuredOutputValidationError(LLMError):
    """Raised when the model response cannot be validated against the schema."""
