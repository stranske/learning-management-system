# Deploying the LMS on Render

The repo ships a Render Blueprint (`render.yaml`) that provisions a FastAPI
web service + a Postgres database. This guide walks the one-time setup; after
that, `git push origin main` redeploys automatically.

## One-time setup

### 1. Connect the repo

1. Sign in to <https://dashboard.render.com>.
2. **New +** → **Blueprint**.
3. Connect this repository (`stranske/learning-management-system`).
4. Render reads `render.yaml` and shows the planned resources: one web
   service, one Postgres database. Click **Apply**.

Render creates both resources, generates `AUTH_SECRET_KEY` automatically
(`generateValue: true` in the Blueprint), and links `DATABASE_URL` to the new
DB via `fromDatabase`.

### 2. Set the secret env vars

In the Render dashboard, open the **learning-management-system** service →
**Environment** tab → **Add**. These are the variables marked `sync: false`
in `render.yaml`:

| Variable | Required? | Notes |
|---|---|---|
| `CLAUDE_API_STRANSKE` | Optional | Anthropic API key. Required only if the deployed study-coach actually calls Claude. Without it, FakeProvider remains the default. |
| `LANGSMITH_API_KEY` | Optional | LangSmith tracing key. Leave unset to skip exports. |
| `LLM_DAILY_BUDGET_USD` | Optional | Daily LLM budget cap. Defaults to the value in `src/lms/settings.py` when unset. |

Click **Save changes**. Render redeploys with the new env.

### 3. Create the first user

Render starts the service with `AUTH_REQUIRED=true`, so you'll need a real
credential to log in. There are no pre-seeded users.

1. In the dashboard, open the service → **Shell** tab.
2. Run:

   ```bash
   python -m lms auth create-user --username YOURNAME --display-name "Your Name" --password
   ```

3. Enter a strong password when prompted. The hash is stored via Argon2; the
   plaintext is never logged.

You can also seed via a local one-shot script if you'd prefer not to use the
Render shell — point `DATABASE_URL` at the Render Postgres connection string
(visible in the DB's **Connect** tab) and run the same `python -m lms auth
create-user` command locally. The hash ends up in the same row either way.

### 4. Visit the app

The service URL is shown at the top of the Render dashboard for the service —
something like `https://learning-management-system.onrender.com`. Open it,
log in with the user you just created, and you should land on the learner
shell.

Update `README.md` "Development Workflow" with the URL once it stabilizes.

## Routine operations

### Redeploys

Render's GitHub integration auto-deploys every push to `main`. The Blueprint's
`preDeployCommand: alembic upgrade head` runs before the new instance accepts
traffic, so schema changes go out cleanly.

### Rolling back

In the dashboard, open the service → **Deploys** tab → click an earlier
deploy → **Rollback to this version**. Migrations that have already run
won't be rolled back automatically — Alembic doesn't downgrade by default.
If a deploy contains a destructive migration you want to undo, write a new
`alembic revision --autogenerate -m "revert ..."` that re-runs the previous
state, commit, and let the next deploy carry it.

### Free-tier behavior

- **Web service**: sleeps after 15 minutes of inactivity; cold-start is
  ~30 seconds on wake. Upgrade to the Starter plan (currently ~$7/mo) for
  no-sleep behavior.
- **Postgres**: free DBs currently have a 90-day retention policy. Before
  that window closes, either upgrade to a paid plan or export the data via
  `pg_dump` against the connection string from the **Connect** tab.

### Custom domain (optional)

Render offers `Settings → Custom Domains → Add`. Point a CNAME at the Render
hostname; certs are issued automatically.

## Troubleshooting

- **`502 Bad Gateway` immediately after deploy**: check the **Logs** tab for
  uvicorn startup errors. Common cause: `alembic upgrade head` failed during
  preDeploy. Fix the migration, push, redeploy.
- **Login form returns 401 with valid credentials**: check
  `users.password_hash` is non-null for that row. If you created the user via
  the API rather than the bootstrap CLI, the hash may not have been set.
- **Session doesn't persist**: confirm `AUTH_SECRET_KEY` is stable. Rotating
  it invalidates every existing session.
