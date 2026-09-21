# Configuration ownership

The running LMS reads its LLM provider, model, and budget settings from
environment variables in `src/lms/llm/config.py`. It does not load the JSON
files in this directory. `LLM_DEFAULT_PROVIDER=fake` selects the in-process
provider even when an Anthropic key is present; an unset value uses credential
detection. A value absent from the registered provider map raises an error.

The files here support the agent fleet, CI, and maintenance tools:

| File | Reader or purpose |
| --- | --- |
| `model_registry.json` | `tools/` model registry and `.github/` agent checks |
| `model_selection_policy.json` | `tools/` model benchmark and freshness checks |
| `llm_slots.json` | `tools/` slot checks and `.github/` agent routing |
| `source_of_truth_docs.yml` | documentation drift maintenance script |
| `coverage-baseline.json` | CI coverage guard and trend tools |

These files are metadata for development and automation. Editing them does not
change a running application's LLM routing.
