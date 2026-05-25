"""Tests for the trace redactor + classification posture."""

from __future__ import annotations

from collections.abc import Callable

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.models import LLMSession
from lms.llm.providers import FakeProvider
from lms.llm.redaction import REDACTED, redact_pii


def _client_with_responder(
    responder: Callable[[str, str], str],
) -> tuple[LLMClient, list[tuple[LLMSession, str]]]:
    provider = FakeProvider(responder=responder)
    config = LLMConfig(
        mode_models=dict.fromkeys(DEFAULT_MODE_MODELS, "fake-model"),
        global_daily_cap_micro_usd=10_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(
        mode_caps_micro_usd={},
        global_cap_micro_usd=10_000,
    )
    exports: list[tuple[LLMSession, str]] = []

    def _exporter(session: LLMSession, payload: str) -> None:
        exports.append((session, payload))

    client = LLMClient(
        config=config,
        providers={"fake": provider},
        budget=budget,
        trace_exporter=_exporter,
    )
    return client, exports


def test_redact_pii_replaces_emails_phones_and_ssn() -> None:
    sample = "Contact me at user@example.com or 555-123-4567 (SSN 123-45-6789)."

    result = redact_pii(sample)

    assert REDACTED in result.text
    assert "user@example.com" not in result.text
    assert "555-123-4567" not in result.text
    assert "123-45-6789" not in result.text
    assert {"email", "phone", "ssn"}.issubset(set(result.redacted_kinds))
    assert result.redacted_count >= 3


def test_redactor_runs_before_external_export() -> None:
    """The wrapper redacts the trace payload before invoking the exporter."""
    leaky = "Reach out at private@example.org for follow-up."
    client, exports = _client_with_responder(lambda _model, _prompt: leaky)

    response = client.complete(
        mode="study-coach",
        prompt="who can I reach for help?",
        trace_class="formative",
    )

    assert response.text == leaky  # caller still receives the model response
    assert response.redaction is not None
    assert response.session.redaction_applied is True
    assert response.session.redacted_span_count >= 1
    assert exports, "expected the exporter to be invoked for formative traces"
    exported_session, exported_payload = exports[-1]
    assert "private@example.org" not in exported_payload
    assert REDACTED in exported_payload
    assert exported_session.trace_class == "formative"


def test_high_signal_loss_demotes_to_ephemeral_and_skips_export() -> None:
    """If redaction strips most of the payload the trace is held locally."""
    mostly_pii = "alice@x.com bob@y.com carol@z.com dave@q.com"
    client, exports = _client_with_responder(lambda _model, _prompt: mostly_pii)

    response = client.complete(
        mode="study-coach",
        prompt="contacts please",
        trace_class="formative",
    )

    assert response.session.trace_class == "ephemeral"
    assert response.session.external_export_allowed is False
    assert exports == []


def test_ephemeral_trace_class_never_exports_verbatim() -> None:
    client, exports = _client_with_responder(lambda _model, _prompt: "ok")

    response = client.complete(
        mode="practice",
        prompt="hi",
        trace_class="ephemeral",
    )

    assert response.session.trace_class == "ephemeral"
    assert response.session.external_export_allowed is False
    assert exports == []


def test_replay_does_not_consume_production_budget() -> None:
    """Replay returns a response without recording spend into the tracker."""
    from lms.llm.client import GoldSetEntry

    client, exports = _client_with_responder(lambda _model, prompt: f"echo:{prompt}")

    entry = GoldSetEntry(
        entry_id="gold-1",
        mode="study-coach",
        prompt="explain photosynthesis",
        trace_class="ephemeral",
    )

    response = client.replay(entry)

    assert response.session.is_replay is True
    assert client.budget.spent_micro_usd() == 0
    assert exports == []  # replay never exports
