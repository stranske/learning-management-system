"""Client-level source-citation enforcement is boundary-aware (issue #196).

The wrapper must not let a citation id count as "satisfied" when it only
appears as a substring of a longer token; a real, bounded occurrence is
required. These tests exercise the enforcement through ``LLMClient.complete``
rather than the policy helper alone.
"""

from __future__ import annotations

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import LLMConfig
from lms.llm.exceptions import SourceConstraintViolation
from lms.llm.providers import FakeProvider


def _client(response_text: str) -> LLMClient:
    """Build a client whose fake provider always returns ``response_text``."""
    provider = FakeProvider(responder=lambda _model, _prompt: response_text)
    config = LLMConfig(
        mode_models={
            "study-coach": "fake-haiku",
            "practice": "fake-haiku",
            "transfer": "fake-sonnet",
            "authoring-assist": "fake-sonnet",
        },
        global_daily_cap_micro_usd=10_000_000,
        default_provider="fake",
    )
    budget = DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=10_000_000)
    return LLMClient(config=config, providers={"fake": provider}, budget=budget)


def test_complete_rejects_substring_only_citation() -> None:
    # Required citation 'src1' appears only inside 'src12' — not a real citation.
    client = _client("see src12 for the full derivation")

    with pytest.raises(SourceConstraintViolation):
        client.complete(
            mode="practice",
            prompt="x",
            trace_class="ephemeral",
            source_constraints=["src1"],
        )


def test_complete_accepts_bounded_citation() -> None:
    client = _client("per src1 the claim holds")

    response = client.complete(
        mode="practice",
        prompt="x",
        trace_class="ephemeral",
        source_constraints=["src1"],
    )

    assert response.text == "per src1 the claim holds"


@pytest.mark.parametrize("cited", [False, True])
def test_linked_prompt_sources_reach_client_enforcement(api_client, monkeypatch, cited):
    from lms.llm import api as llm_api
    from tests.llm.test_client_routing import _recording_client, _seed_published_study_prompt

    client, factory = api_client
    with factory() as session:
        ids = _seed_published_study_prompt(session, stable_locator="source:required-linked")
    text = "Per source:required-linked, the claim holds." if cited else "An uncited claim."
    recording, _, calls = _recording_client(default_provider="fake", responder=lambda *_: text)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording)
    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this.",
        },
    )
    assert response.status_code == 200
    assert response.json()["flags"] == ([] if cited else ["unverified"])
    # Existing client rejects the uncited constrained call; route's existing
    # unverified fallback is a second call. Valid canonical citation needs one.
    assert len(calls) == (1 if cited else 2)
