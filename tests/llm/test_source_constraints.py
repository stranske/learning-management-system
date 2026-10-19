"""Tests for source-constrained LLM policy output."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.llm.interaction_policy import flag_uncited_claims
from lms.main import create_app
from tests.llm.test_client_routing import _seed_published_study_prompt


def test_uncited_claim_is_flagged_unverified() -> None:
    flags = flag_uncited_claims(
        "Photosynthesis converts light into stored chemical energy.",
        ("source:biology-note-1",),
    )

    assert "unverified" in flags


def test_cited_claim_is_not_flagged() -> None:
    flags = flag_uncited_claims(
        "Per source:biology-note-1, photosynthesis stores chemical energy.",
        ("source:biology-note-1",),
    )

    assert flags == ()


def test_substring_only_citation_is_rejected() -> None:
    """A citation that appears only as a substring of a longer identifier does
    not satisfy the constraint (boundary-aware matching, issue #196)."""
    # 'src1' occurs only inside 'src12' — not a real, distinct citation.
    flags = flag_uncited_claims("Refer to src12 for the derivation.", ("src1",))

    assert "unverified" in flags


def test_bounded_citation_among_other_text_is_accepted() -> None:
    """An exact citation flanked by non-identifier characters is accepted."""
    flags = flag_uncited_claims("As shown in src1, the result holds.", ("src1",))

    assert flags == ()


@contextmanager
def _client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_post_llm_sessions_sets_unverified_flag_when_sources_missing(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        ids = _seed_published_study_prompt(session, stable_locator="source:required-1")
    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "mode": "study-coach",
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this concept briefly.",
            "source_constraints": [ids["stable_locator"]],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "unverified" in body["flags"]


@pytest.mark.parametrize("caller", ["omitted", "id", "locator"])
def test_linked_prompt_omitted_or_alias_constraints_cannot_disable_citations(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    caller: str,
) -> None:
    from lms.llm import api as llm_api
    from lms.llm.models import LLMFeedbackEvent
    from tests.llm.test_client_routing import _recording_client

    client, factory = api_client
    with factory() as session:
        ids = _seed_published_study_prompt(session, stable_locator="source:approved-linked")
    prompts: list[str] = []

    def answer(_provider: str, _model: str, prompt: str) -> str:
        prompts.append(prompt)
        return "An uncited explanation."

    recording, _, calls = _recording_client(default_provider="fake", responder=answer)
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording)
    payload = {
        "learner_id": ids["learner_id"],
        "prompt_id": ids["prompt_id"],
        "user_message": "Explain this.",
    }
    if caller != "omitted":
        payload["source_constraints"] = [
            ids["source_id"] if caller == "id" else ids["stable_locator"]
        ]
    response = client.post("/llm/sessions", json=payload)
    assert response.status_code == 200
    assert response.json()["flags"] == ["unverified"]
    assert calls and all(ids["stable_locator"] in prompt for prompt in prompts)
    with factory() as session:
        event = session.query(LLMFeedbackEvent).one()
        assert event.source_reference_ids == [ids["stable_locator"]]
        assert event.unverified


def test_caller_subset_cannot_remove_another_linked_source(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lms.llm import api as llm_api
    from lms.llm.models import LLMFeedbackEvent
    from lms.prompts.models import Prompt
    from lms.sources.repository import create_source_reference
    from tests.llm.test_client_routing import _recording_client

    client, factory = api_client
    with factory() as session:
        ids = _seed_published_study_prompt(session, stable_locator="source:approved-one")
        source = create_source_reference(
            session,
            source_type="url",
            stable_locator="source:approved-two",
            content="Second source",
            actor_id="user:user-study-coach-routing",
        )
        prompt = session.get(Prompt, ids["prompt_id"])
        assert prompt is not None
        prompt.source_references.append(source)
        session.commit()
    recording, _, _ = _recording_client(
        default_provider="fake", responder=lambda *_: "Per source:approved-one, this holds."
    )
    monkeypatch.setattr(llm_api, "_default_client", lambda: recording)
    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "prompt_id": ids["prompt_id"],
            "user_message": "Explain this.",
            "source_constraints": [ids["source_id"]],
        },
    )
    assert response.status_code == 200
    assert response.json()["flags"] == ["unverified"]
    with factory() as session:
        assert session.query(LLMFeedbackEvent).one().source_reference_ids == [
            "source:approved-one",
            "source:approved-two",
        ]


@pytest.mark.parametrize("unknown_prompt", [False, True])
def test_bad_linked_context_is_rejected_before_provider_resolution(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    unknown_prompt: bool,
) -> None:
    from lms.llm import api as llm_api

    client, factory = api_client
    with factory() as session:
        ids = _seed_published_study_prompt(session)
    resolutions: list[bool] = []

    def forbidden_client():
        resolutions.append(True)
        raise AssertionError("Provider must not be resolved")

    monkeypatch.setattr(llm_api, "_default_client", forbidden_client)
    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": ids["learner_id"],
            "prompt_id": "missing" if unknown_prompt else ids["prompt_id"],
            "user_message": "Explain this.",
            "source_constraints": ["source:unrelated"],
        },
    )
    assert response.status_code == (404 if unknown_prompt else 422)
    assert resolutions == []
