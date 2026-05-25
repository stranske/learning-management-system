# Security Assumptions

Status: Milestone 0 baseline for the local/private prototype.

This document records the initial security and privacy posture before implementation work begins. It is intentionally modest: v1 starts as a local/private learning prototype, but the data model and operational boundaries must not block later institutional deployment.

## Canonical Design Sources

- [Project plan: Governance, Security, And Audit](../product/project-plan.md#governance-security-and-audit)
- [Project plan: Phase 1 minimum core](../product/project-plan.md#phase-1-minimum-core)
- [Project plan: Export and import contract](../product/project-plan.md#export-and-import-contract-v1)
- [Early design decisions: Segment 7, Stack, Governance, And Implementation](../product/early-design-decisions.md#segment-7-stack-governance-and-implementation)
- [Early design decisions: Segment 9, Privacy And LLM Trace Classification](../product/early-design-decisions.md#segment-9-privacy-and-llm-trace-classification)

## Deployment And Data Boundary

The first release assumes a local/private deployment for the project owner. Personal learning data and firm or institution-owned training data remain separate by default:

- Personal learning records may include private notes, reflection, attempts, prompt responses, source references, and LLM traces.
- Institutional training data may later include firm content, role-based learning paths, manager-visible progress, audit records, and assessment evidence.
- When firm or institutional content enters scope, the preferred posture is separate deployments and databases rather than one multi-tenant database.
- If a shared deployment is introduced later, `ownership_scope` and future Postgres row-level security become hard boundaries, not only application conventions.

## Secrets And Environment Variables

The repository includes `.env.example` for local shape only. It must contain placeholders, example values, or empty values, never live credentials.

Required local/private configuration:

| Setting | Purpose | Local handling | GitHub secret name |
| --- | --- | --- | --- |
| `DATABASE_URL` | Postgres connection string | Local `.env` only | `DATABASE_URL` |
| `ANTHROPIC_API_KEY` | Default LLM provider key | Local `.env` only | `ANTHROPIC_API_KEY` |
| `OPENAI_API_KEY` | Optional provider key for eval/replay | Local `.env` only | `OPENAI_API_KEY` |
| `LANGSMITH_API_KEY` | Trace and eval export | Local `.env` only | `LANGSMITH_API_KEY` |
| `LLM_DAILY_BUDGET_USD` | Budget kill-switch threshold | Non-secret value allowed | `LLM_DAILY_BUDGET_USD` |
| `LLM_MODEL_STUDY_COACH` | Study-coach model route | Non-secret value allowed | `LLM_MODEL_STUDY_COACH` |
| `LLM_MODEL_PRACTICE` | Practice model route | Non-secret value allowed | `LLM_MODEL_PRACTICE` |
| `LMS_SESSION_SECRET` | Local auth/session signing | Local `.env` only | `LMS_SESSION_SECRET` |

GitHub Actions should read secrets from repository or environment secrets. They should not echo provider keys, database URLs, session secrets, or trace payloads into logs.

## Local-Only Source Policy

`SourceReference.source_visibility` controls whether source bodies can leave the local system:

- `public` source references may be included in default exports when their license and product policy allow it.
- `local-only` source references export metadata by default, but their source bodies are excluded from default export bundles.
- Default exports must not include local-only source bodies, verbatim formative or ephemeral LLM transcripts, or PII-flagged fields.
- Any command that includes local-only source content or all LLM traces must require explicit user intent.

This keeps personal research notes usable in the prototype without treating every note body as repo-safe or export-safe material.

## LLM Trace Handling

Every `LLMSession` declares a trace class:

- `evidence-grade`: assessment-mode attempts and rubric feedback retained with supporting evidence.
- `formative`: study-coach, practice, and exploration traces retained for a configurable review/evaluation window.
- `ephemeral`: off-topic or sensitive sessions not exported verbatim.

The LLM client wrapper is the enforcement point. Classification and PII redaction happen locally before any external trace export. If redaction would remove too much instructional signal, the trace is demoted to `ephemeral` and held locally without verbatim external export.

LangSmith export is enabled only after trace classification, redaction, and retention settings are configured for the target environment.

## Identity And SSO Readiness

v1 uses local authentication assumptions. The schema should still preserve a future SSO path:

- User records should avoid provider-specific identity assumptions.
- Auth decisions should reference stable internal user IDs.
- Institutional deployments should be able to add external identity provider IDs without rewriting learning evidence.
- Role and ownership boundaries should be explicit enough for future manager, author, learner, and administrator roles.

## Checklist After GitHub Repo Creation

- [ ] Create repository or environment secrets for `DATABASE_URL`, provider API keys, LangSmith, and session signing.
- [ ] Confirm `.env.example` contains placeholders only.
- [ ] Configure any CI job that needs LLM access to use budget caps and non-verbose logging.
- [ ] Confirm default export settings exclude `local-only` source bodies and non-evidence-grade transcript text.
- [ ] Confirm trace export is disabled or privacy-configured before enabling LangSmith in CI or hosted environments.
