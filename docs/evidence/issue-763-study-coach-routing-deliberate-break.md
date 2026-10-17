# Deliberate-break evidence for #763 (via #770)

Relates to merged PR #766 and keepalive delivery on `cursor/issue-763`.
This documents the executed fail-to-restore cycle for study-coach HTTP provider
routing in `create_llm_session_route`.

## Break (temporary, not committed)

Temporarily reintroduce forced fake routing on both `client.complete` calls in
`src/lms/llm/api.py` by adding `provider_name="fake"` to the primary turn and
the citation-fallback retry.

## Named failing tests

Command:

```bash
python -m pytest \
  tests/llm/test_client_routing.py::test_http_sessions_uses_configured_default_provider \
  tests/llm/test_client_routing.py::test_http_sessions_citation_fallback_keeps_same_provider \
  -q --no-cov
```

Observed failure (2026-10-17):

```text
FAILED tests/llm/test_client_routing.py::test_http_sessions_uses_configured_default_provider
>       assert calls == [("alt", "routing-model")]
E       AssertionError: assert [('fake', 'routing-model')] == [('alt', 'routing-model')]

FAILED tests/llm/test_client_routing.py::test_http_sessions_citation_fallback_keeps_same_provider
>       assert calls == [("alt", "routing-model"), ("alt", "routing-model")]
E       AssertionError: assert [('fake', 'routing-model'), ('fake', 'routing-model')] == [('alt', 'routing-model'), ('alt', 'routing-model')]
2 failed
```

## Restore

Restore `src/lms/llm/api.py` (remove both `provider_name="fake"` overrides), then
rerun the named command.

Observed restored pass (2026-10-17):

```text
collected 2 items
tests/llm/test_client_routing.py ..                                       [100%]
============================== 2 passed in 0.71s ===============================
```

Production-file cleanup:

```bash
git diff --exit-code -- src/lms/llm/api.py
```

Full routing suite after restore:

```bash
python -m pytest tests/llm/test_client_routing.py -q --no-cov
```

```text
collected 52 items
============================== 52 passed in 3.90s ==============================
```

## Acceptance mapping

- Guard location: `src/lms/llm/api.py` (`create_llm_session_route`).
- Named regression gates:
  - `tests/llm/test_client_routing.py::test_http_sessions_uses_configured_default_provider`
  - `tests/llm/test_client_routing.py::test_http_sessions_citation_fallback_keeps_same_provider`
- The deliberate break proves that reintroducing forced `provider_name="fake"`
  makes `/llm/sessions` ignore a non-fake configured default on both the primary
  turn and the citation-fallback branch.
