# Deliberate-break evidence for #695 (via #717)

Relates to merged PR #709 and source issue #695. This documents the executed
fail-to-restore cycle for the explicit provider override in
`load_runtime_llm_config`.

## Break (temporary, not committed)

At baseline head `1713687c857e6a62ec26d6ed042d0b0cf96c9168`, temporarily replace the
override-aware fields in `src/lms/llm/config.py`:

```python
default_provider=override if override is not None else default_provider,
force_fake_provider=override == "fake",
```

with the former unconditional provider selection:

```python
default_provider=default_provider,
```

## Named failing test

Command:

```bash
uv run pytest tests/llm/test_client_routing.py::test_explicit_provider_override_is_honored -q --no-cov
```

Observed failure (2026-09-26):

```text
FAILED tests/llm/test_client_routing.py::test_explicit_provider_override_is_honored
>       assert client.config.default_provider == "fake"
E       AssertionError: assert 'anthropic' == 'fake'
1 failed
```

## Restore

Restore the override-aware fields exactly, then rerun the named command.

Result: **1 passed**. A production-file cleanup check also passed:

```bash
git diff --exit-code -- src/lms/llm/config.py
```

An independent `local_verify.py` replay produced the same red/green result by
overlaying the current test onto PR #709's first parent
(`025d07c3721e91dfeffdfa02e07d59ddd58c321a`): the named node failed against
that pre-fix implementation and passed against current `main`.

## Acceptance mapping

- Guard location: `src/lms/llm/config.py` (`load_runtime_llm_config`).
- Named regression gate:
  `tests/llm/test_client_routing.py::test_explicit_provider_override_is_honored`.
- The deliberate break proves that `LLM_DEFAULT_PROVIDER=fake` must override
  credential-derived `anthropic` routing while keeping both providers registered.
- Closes the post-merge verifier evidence gap recorded in #717 for #695/#709.
