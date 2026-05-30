# LLM Provider Live-Verification Gate

This document records the manual gate that must pass before a real Anthropic provider
deployment is considered production-ready.  Run it once per deployment with a live
`CLAUDE_API_STRANSKE` (or `ANTHROPIC_API_KEY`) configured.

## Purpose

The live gate confirms three things that unit tests cannot:

1. The real Anthropic API accepts the request and returns a non-empty response.
2. The LMS budget preflight executes before the network call (no free ride on API errors).
3. PII redaction is applied to the response before it leaves the enforcement layer
   (`response.redaction.applied` is observable even when no PII is present).

## No-Train Configuration

All requests in this system use the Anthropic API with the default model parameters.
Anthropic's **standard API** does not use inputs or outputs to train models.
See [Anthropic's privacy policy](https://www.anthropic.com/privacy) for confirmation.
There is no special header or flag required; the standard `client.messages.create()`
path already applies the no-training policy.

## Prerequisites

- `CLAUDE_API_STRANSKE` or `ANTHROPIC_API_KEY` set in the shell environment.
- Application dependencies installed (`uv sync` or equivalent).
- A running Postgres database (or `DATABASE_URL` pointing to one).

## One-Call Smoke Test

Run the `authoring-assist propose` CLI subcommand, which exercises the full enforcement
stack (budget preflight → provider call → redaction → cost accounting):

```bash
CLAUDE_API_STRANSKE=<your-key> python -m lms authoring-assist propose \
  --related-node-title "Spaced Repetition" \
  --related-node-knowledge-type "declarative" \
  --related-node-description "The spacing effect in long-term memory consolidation." \
  --prompt-body "Which of the following best describes the spacing effect?" \
  --prompt-knowledge-type "declarative" \
  --prompt-cognitive-action "remember" \
  --prompt-demand-level "low" \
  --prompt-answer-form "multiple-choice" \
  --edge-type "assesses" \
  --source-reference <source-ref-id> \
  --target-node <node-id> \
  --learning-goal <goal-id> \
  --actor-id <actor-id>
```

Expected output contains:

```
authoring-assist proposal complete: proposal=<uuid> node=<uuid> prompt=<uuid> model=claude-haiku-4-5
```

## Verification Checklist

- [ ] Command exits `0`.
- [ ] `model=` in the output names a real Anthropic model (not `fake-*`).
- [ ] No `BudgetExceeded` error on first run (confirms budget preflight executed and
      the daily cap is not exhausted).
- [ ] Re-running with `CLAUDE_API_STRANSKE` unset falls back to `fake-authoring-model`
      in the output — confirming `FakeProvider` is the no-key default.

## study-coach Routing Check

To verify the `study-coach` mode routes to Anthropic when a key is present, inspect the
`LLM_DEFAULT_PROVIDER` environment variable path:

```python
from lms.llm.config import load_llm_config_from_env
import os

config = load_llm_config_from_env(dict(os.environ))
print(config.default_provider)   # "anthropic" when key present, "fake" otherwise
```

## Redaction Observable

The `LLMResponse.redaction` field is always populated (never `None`) after a real call.
To confirm redaction ran:

```python
from lms.llm.api import _default_client
client = _default_client()
resp = client.complete(mode="study-coach", prompt="hello", trace_class="ephemeral")
assert resp.redaction is not None
print("redaction.applied:", resp.redaction.applied)
```

`applied` will be `False` for a benign prompt but the field's presence confirms the
enforcement layer executed.

## Owner

Run by the repository owner against their own key before merging a provider-wiring PR.
Results are recorded in the PR description (see the PR that closes issue #179).
