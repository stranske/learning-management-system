# Deliberate-Break Gate — PR #216 / Issue #196

## Run 1: BREAK (try/except removed — raw RateLimitError escapes)

`AnthropicProvider.complete()` was patched to call `client.messages.create(**call_kwargs)` directly,
bypassing `_create_with_retry`, and then `test_rate_limit_wrapped` was executed:

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.0.3, pluggy-1.6.0
collected 1 item

tests/llm/test_anthropic_provider.py::test_rate_limit_wrapped FAILED     [100%]

=================================== FAILURES ===================================
___________________________ test_rate_limit_wrapped ____________________________

    def test_rate_limit_wrapped() -> None:
        from anthropic import RateLimitError
        client = _ScriptedClient([_make_rate_limit_error()])
        provider = AnthropicProvider(
            api_key="test-key",
            client_factory=lambda _k: client,
            max_retries=2,
            sleep_func=lambda _s: None,
        )
        with pytest.raises(ProviderCallError) as excinfo:
>           provider.complete(
                model="claude-haiku-4-5",
                prompt="trigger a rate limit",
                max_tokens=64,
                timeout_seconds=None,
            )

tests/llm/test_anthropic_provider.py:287:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
src/lms/llm/providers.py:269: in complete
    message = client.messages.create(**call_kwargs)  # DELIBERATE BREAK
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <tests.llm.test_anthropic_provider._ScriptedMessages object at 0x7fc080727c80>
outcome = RateLimitError('rate limited')

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, BaseException):
>           raise outcome
E           anthropic.RateLimitError: rate limited

tests/llm/test_anthropic_provider.py:260: RateLimitError

========================= 1 failed, 1 warning in 0.57s =========================
```

**Result: FAIL** — raw `anthropic.RateLimitError` escapes instead of `ProviderCallError`. Gate confirmed.

---

## Run 2: RESTORED (correct implementation)

`_create_with_retry` call restored in `AnthropicProvider.complete()`:

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.0.3, pluggy-1.6.0
collected 1 item

tests/llm/test_anthropic_provider.py::test_rate_limit_wrapped PASSED     [100%]

========================= 1 passed, 1 warning in 0.45s =========================
```

**Result: PASS** — `ProviderCallError` (an `LLMError`) is raised; raw SDK error is chained as `__cause__`.

---

## Full suite after restore

```
pytest tests/llm/ -q --no-cov
collected 108 items

tests/llm/test_anthropic_provider.py ................
tests/llm/test_authoring_assist.py .........
tests/llm/test_citation_enforcement.py ..
tests/llm/test_client_budget.py ..........
tests/llm/test_client_features.py ......
tests/llm/test_client_routing.py ...........
tests/llm/test_eval_set_schema.py .........
tests/llm/test_feedback_events.py .....
tests/llm/test_interaction_skills.py ....
tests/llm/test_learner_controls.py ....
tests/llm/test_llm_session_model.py ...
tests/llm/test_llm_sessions_migration.py ..
tests/llm/test_source_constraints.py .....
tests/llm/test_study_coach_policy.py ..........
tests/llm/test_trace_controls.py ....
tests/llm/test_trace_redaction.py ........

108 passed, 1 warning in 7.18s
```
