"""Tests for structured-output validation and source-constraint enforcement."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.exceptions import SourceConstraintViolation, StructuredOutputValidationError
from lms.llm.providers import FakeProvider


def _client(responder: Callable[[str, str], str] | None = None) -> LLMClient:
    provider = FakeProvider(
        responder=responder or (lambda _model, prompt: f"echo:{prompt}"),
    )
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "fake-model"),
        global_daily_cap_micro_usd=10_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000)
    return LLMClient(config=config, providers={"fake": provider}, budget=budget)


class _Schema:
    """Minimal Pydantic-style schema for testing structured-output validation."""

    value: str

    @classmethod
    def model_validate_json(cls, payload: str) -> _Schema:
        import json

        data = json.loads(payload)
        obj = cls()
        obj.value = data["value"]
        return obj


def test_structured_output_valid_response_is_returned() -> None:
    """A JSON response that satisfies the schema is parsed and returned."""
    client = _client(responder=lambda _m, _p: '{"value": "ok"}')

    response = client.complete(
        mode="study-coach",
        prompt="give structured answer",
        trace_class="formative",
        structured_output_schema=_Schema,
    )

    assert response.structured_output is not None
    assert response.structured_output.value == "ok"


def test_structured_output_invalid_response_raises() -> None:
    """A response that does not conform to the schema raises StructuredOutputValidationError."""
    client = _client(responder=lambda _m, _p: "not json at all")

    with pytest.raises(StructuredOutputValidationError, match="failed validation"):
        client.complete(
            mode="study-coach",
            prompt="give structured answer",
            trace_class="formative",
            structured_output_schema=_Schema,
        )


def test_source_constraints_all_present_succeeds() -> None:
    """A response that contains all required citations passes source-constraint enforcement."""
    client = _client(responder=lambda _m, _p: "See ref-A and ref-B for details.")

    response = client.complete(
        mode="study-coach",
        prompt="cite the sources",
        trace_class="evidence-grade",
        source_constraints=["ref-A", "ref-B"],
    )

    assert response.text == "See ref-A and ref-B for details."


def test_source_constraints_missing_citation_raises() -> None:
    """A response missing a required citation raises SourceConstraintViolation."""
    client = _client(responder=lambda _m, _p: "Here is my answer with only ref-A.")

    with pytest.raises(SourceConstraintViolation, match="ref-B"):
        client.complete(
            mode="study-coach",
            prompt="cite the sources",
            trace_class="evidence-grade",
            source_constraints=["ref-A", "ref-B"],
        )


def test_response_summary_truncated_for_long_text() -> None:
    """Responses longer than 400 chars are truncated in the session summary."""
    long_text = "x" * 500
    client = _client(responder=lambda _m, _p: long_text)

    response = client.complete(mode="practice", prompt="q", trace_class="ephemeral")

    assert response.session.response_summary is not None
    assert response.session.response_summary.endswith("...")
    assert len(response.session.response_summary) == 403  # 400 chars + "..."


def test_fake_provider_truncates_text_when_max_tokens_is_set() -> None:
    client = _client(responder=lambda _m, _p: "one two three four")

    response = client.complete(
        mode="practice",
        prompt="short",
        trace_class="ephemeral",
        max_tokens=2,
    )

    assert response.text == "one two"
    assert response.provider_response.output_tokens == 2
