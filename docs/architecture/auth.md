# Authentication architecture

> Status: v1 — single-user password login via Argon2 + signed-cookie sessions.
> Last updated: 2026-05-30 alongside issue #180.

## Decision

**Argon2id password authentication with Starlette `SessionMiddleware`** (signed
cookies via `itsdangerous`). One credentialed user gates the deployed
instance; the local-dev shortcut user remains in place for tests and dev.

## Why this and not the alternatives

| Option | Why we picked / rejected |
|---|---|
| **Argon2id password (chosen)** | Simple to operate, no outbound email dependency, OWASP-recommended algorithm, transparent rehash path when cost params change. |
| Magic-link email | Better UX in theory, but requires a configured outbound email provider and adds a moving part. Reserved for a later milestone if the UX matters. |
| OAuth / OIDC (Google, GitHub) | Right answer for a multi-user public surface. Overkill for v1, which is single-user. Adds a third-party dependency and identity-provider lock-in we don't need yet. |
| SSO / institutional | Out of scope until the analyst-training pilot (M7+) actually has institutional users. |

## Surface

- `GET /login` — Pico-styled login form. Honors a `next=<path>` query param to
  redirect to the originally requested route after a successful login.
- `POST /login` — credential check. On success: writes the user's stable id
  into the session and 303s to `next` (validated same-origin). On failure:
  re-renders the form with a generic error message (we deliberately don't say
  whether the username or password was wrong, to avoid username enumeration).
- `POST /logout` — clears the session and 303s to `/login`. POST-only by
  design (OWASP CSRF guidance).

The form lives in `src/lms/auth/login.py`. The auth dependency
`require_authenticated_user` is the gate that downstream routers can use to
require a logged-in user.

## Session storage

Sessions are **server-signed cookies**, not server-side DB rows. Starlette's
`SessionMiddleware` ships them via `itsdangerous`; we only put the user's
stable id (`user_id`) into the payload, never PII. The cookie is signed with
`AUTH_SECRET_KEY` (rotatable from the Render dashboard) and carries:

- `same_site=lax` — sufficient for a same-origin app, robust against
  cross-site POST CSRF for the login/logout flows.
- `https_only=True` when `AUTH_REQUIRED=true` (deployed mode); falls back to
  `False` for local dev so cookies work on `http://localhost`.
- Default max age: 14 days, re-extended on each request.

A DB-backed session table is a follow-up if/when we need server-side
revocation, cross-device session inspection, or a security audit log. For
single-user v1 it's not justified.

## Gates

`Settings.auth_required` (env var: `AUTH_REQUIRED`) is the master switch.

- `auth_required=false` (local dev, tests): `require_authenticated_user`
  returns the deterministic local-dev user, preserving the pre-auth contract.
  No password is needed.
- `auth_required=true` (deployed instance): `require_authenticated_user`
  reads the session cookie. Missing/invalid session → 401 for JSON callers,
  302 redirect to `/login?next=...` for HTML callers.

The HTML-vs-JSON disambiguation is based on the request's `Accept` header.

## Password handling

- Hashing: `argon2-cffi`'s `PasswordHasher` with library defaults
  (`time_cost=3`, `memory_cost=64 MiB`, `parallelism=4`). One shared hasher
  instance is reused.
- Storage: `users.password_hash` column (nullable `String(255)`), added in
  alembic migration `20260530_0028_user_password_hash`.
- Transparent rehash on login: when a stored hash's cost parameters are below
  current defaults, the verifier rehashes and persists silently. Users never
  see this and never need to reset.

## Bootstrap

A fresh deployment starts with **no credentialed users**. The first time you
deploy you must create one. The recommended path:

```bash
# On Render: open a Shell to the running service, then:
python -m lms auth create-user --username you --display-name "Tim" --password
# Enter the password when prompted.
```

`lms auth create-user` writes a hashed credential via
`lms.auth.repository.create_local_user(..., password=...)` and exits. A
follow-up command (`lms auth set-password`) lets you rotate the password
without recreating the row.

The bootstrap commands live in `src/lms/__main__.py` (see the `auth`
subparser); they are usable locally too (`docker compose exec app python -m
lms auth create-user ...`).

## What's deliberately NOT in v1

- **Self-service signup.** Users are created via the CLI. The web form is
  login-only.
- **Email verification.** No mail dependency.
- **Multi-factor.** Single password.
- **Password reset.** Use `lms auth set-password` from a shell.
- **Lockout / rate-limit on failed attempts.** Defer until there's a reason
  to believe the deployment is under attack.

These are all reasonable follow-ups when use case justifies them.
