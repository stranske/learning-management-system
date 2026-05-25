"""Single client wrapper for every LLM call in the system.

The wrapper is the enforcement point for budgets, traces, redaction, source
constraints, and structured-output validation. Per the project plan, any LLM
call site MUST go through this client; provider routing, cost accounting, and
LangSmith export decisions are all centralized here so model decisions remain a
one-line change.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.config import LLMConfig
from lms.llm.exceptions import (
    BudgetExceeded,
    LLMError,
    SourceConstraintViolation,
    StructuredOutputValidationError,
)
from lms.llm.models import LLM_MODES, TRACE_CLASSES, LLMSession
from lms.llm.providers import ProviderAdapter, ProviderResponse
from lms.llm.redaction import RedactionResult, redact_pii

_EPHEMERAL_DEMOTION_THRESHOLD = 0.5


@runtime_checkable
class StructuredOutputSchema(Protocol):
    """Pydantic-style schema with a ``model_validate_json`` classmethod."""

    @classmethod
    def model_validate_json(cls, payload: str) -> Any: ...


@dataclass
class GoldSetEntry:
    """A stored eval input/expected pair for :meth:`LLMClient.replay`."""

    entry_id: str
    mode: str
    prompt: str
    trace_class: str = "ephemeral"
    expected_text: str | None = None
    source_constraints: Sequence[str] = field(default_factory=tuple)


@dataclass
class LLMResponse:
    """Result returned to callers of :meth:`LLMClient.complete`."""

    text: str
    session: LLMSession
    provider_response: ProviderResponse
    structured_output: Any | None = None
    redaction: RedactionResult | None = None


@dataclass
class LLMClient:
    """The single entry point for outbound LLM calls."""

    config: LLMConfig
    providers: dict[str, ProviderAdapter]
    budget: DailyBudgetTracker
    redactor: Callable[[str], RedactionResult] = redact_pii
    trace_exporter: Callable[[LLMSession, str], None] | None = None

    def complete(
        self,
        *,
        mode: str,
        prompt: str,
        trace_class: str,
        structured_output_schema: type[StructuredOutputSchema] | None = None,
        source_constraints: Sequence[str] | None = None,
        max_tokens: int | None = None,
        learner_id: str | None = None,
        prompt_template_version: str | None = None,
        provider_name: str | None = None,
    ) -> LLMResponse:
        """Issue a completion call with full enforcement pre/post.

        Order of operations:

        1. Validate ``mode`` and ``trace_class``.
        2. Resolve the provider/model via config.
        3. Budget preflight (per-mode + global). Raises :class:`BudgetExceeded`
           before issuing the provider request.
        4. Provider call.
        5. Token/cost normalization and accounting.
        6. Local PII redaction on the trace payload.
        7. Trace-class demotion if redaction loses too much signal.
        8. Structured-output validation.
        9. Source-constraint enforcement.
        10. Optional external trace export (skipped when the trace is held
            locally as ``ephemeral`` or when ``external_export_allowed`` is
            false).
        """
        self._validate_mode(mode)
        self._validate_trace_class(trace_class)

        model = self.config.model_for(mode)
        provider = self._resolve_provider(provider_name)

        projected_cost = self._estimate_cost(provider, prompt=prompt, max_tokens=max_tokens)
        self.budget.preflight(mode, projected_cost)

        provider_response = provider.complete(
            model=model,
            prompt=prompt,
            max_tokens=max_tokens,
            timeout_seconds=self.config.default_timeout_seconds,
        )

        self.budget.record(mode, provider_response.cost_micro_usd)

        redaction = self.redactor(provider_response.text)
        external_export_allowed = trace_class != "ephemeral"
        effective_trace_class = trace_class
        if redaction.applied and redaction.signal_loss_ratio >= _EPHEMERAL_DEMOTION_THRESHOLD:
            effective_trace_class = "ephemeral"
            external_export_allowed = False

        structured_output: Any | None = None
        if structured_output_schema is not None:
            try:
                structured_output = structured_output_schema.model_validate_json(
                    provider_response.text
                )
            except Exception as exc:  # noqa: BLE001 - re-raised as wrapper error
                raise StructuredOutputValidationError(
                    f"structured output for mode '{mode}' failed validation: {exc}"
                ) from exc

        if source_constraints:
            missing = [
                citation
                for citation in source_constraints
                if citation not in provider_response.text
            ]
            if missing:
                raise SourceConstraintViolation(
                    f"mode '{mode}' requires citations {list(source_constraints)}; "
                    f"missing: {missing}"
                )

        session = LLMSession(
            mode=mode,
            trace_class=effective_trace_class,
            provider=provider_response.provider,
            model=provider_response.model,
            prompt_template_version=prompt_template_version,
            learner_id=learner_id,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            cost_micro_usd=provider_response.cost_micro_usd,
            redaction_applied=redaction.applied,
            redacted_span_count=redaction.redacted_count,
            external_export_allowed=external_export_allowed,
            response_summary=_summarize(redaction.text),
            is_replay=False,
        )

        if external_export_allowed and self.trace_exporter is not None:
            self.trace_exporter(session, redaction.text)

        return LLMResponse(
            text=provider_response.text,
            session=session,
            provider_response=provider_response,
            structured_output=structured_output,
            redaction=redaction,
        )

    def replay(
        self,
        gold_set_entry: GoldSetEntry,
        *,
        mode_override: str | None = None,
        provider_name: str | None = None,
    ) -> LLMResponse:
        """Re-run a gold-set entry without writing to production accounting.

        Replay isolates eval traffic from the production budget tracker so a
        regression sweep does not exhaust the daily cap, and never writes
        traces to LangSmith.
        """
        mode = mode_override or gold_set_entry.mode
        self._validate_mode(mode)
        self._validate_trace_class(gold_set_entry.trace_class)

        provider = self._resolve_provider(provider_name)
        model = self.config.model_for(mode)
        provider_response = provider.complete(
            model=model,
            prompt=gold_set_entry.prompt,
            max_tokens=None,
            timeout_seconds=self.config.default_timeout_seconds,
        )
        redaction = self.redactor(provider_response.text)

        session = LLMSession(
            mode=mode,
            trace_class=gold_set_entry.trace_class,
            provider=provider_response.provider,
            model=provider_response.model,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            cost_micro_usd=provider_response.cost_micro_usd,
            redaction_applied=redaction.applied,
            redacted_span_count=redaction.redacted_count,
            external_export_allowed=False,
            response_summary=_summarize(redaction.text),
            is_replay=True,
        )

        return LLMResponse(
            text=provider_response.text,
            session=session,
            provider_response=provider_response,
            redaction=redaction,
        )

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in LLM_MODES:
            raise LLMError(f"unknown mode '{mode}'; valid modes: {LLM_MODES}")

    @staticmethod
    def _validate_trace_class(trace_class: str) -> None:
        if trace_class not in TRACE_CLASSES:
            raise LLMError(f"unknown trace_class '{trace_class}'; valid: {TRACE_CLASSES}")

    def _resolve_provider(self, provider_name: str | None) -> ProviderAdapter:
        name = provider_name or self.config.default_provider
        try:
            return self.providers[name]
        except KeyError as exc:
            raise LLMError(f"no provider adapter registered for '{name}'") from exc

    @staticmethod
    def _estimate_cost(provider: ProviderAdapter, *, prompt: str, max_tokens: int | None) -> int:
        """Conservative preflight cost estimate used for budget preflight.

        Falls back to a length-based heuristic so the preflight is meaningful
        even when the adapter does not expose a structured pricing model.
        """
        input_tokens = max(1, len(prompt.split()))
        output_tokens = max_tokens if max_tokens is not None else max(64, input_tokens)
        input_rate = getattr(provider, "input_token_cost_micro_usd", 1_000)
        output_rate = getattr(provider, "output_token_cost_micro_usd", 4_000)
        return input_tokens * input_rate + output_tokens * output_rate


def _summarize(text: str, *, limit: int = 400) -> str | None:
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


__all__ = [
    "BudgetExceeded",
    "GoldSetEntry",
    "LLMClient",
    "LLMResponse",
    "SourceConstraintViolation",
    "StructuredOutputValidationError",
]
