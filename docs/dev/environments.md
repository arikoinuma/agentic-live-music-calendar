# Environments

What each environment is, which variables it carries, and the procedures that keep the three apart. The plan that
produced it is `docs/dev/implementations/c3-environments-and-deploy.md`; decisions are cited in the scoped form
(`C3-D4`). **No secret values appear here, ever**: names, shapes and where they are set.

## Current state (read this first)

*As of October 28, 2026, before the dashboard steps of C3 are done:* only **production** exists in every layer. The
`staging` and `dev` rows below are the target, and each line becomes a fact when Ari records it (with the date) as
the runbook steps in the plan are completed. Anything marked *target* has not been built.

| Layer | `local` | `dev` | `staging` | `prod` |
|---|---|---|---|---|
| Git branch | any | `dev` (the lane, below) | `main` | `production` |
| Vercel | `make dev` | Preview, branch `dev` | Preview (`main` and every PR branch) | Production (Production Branch `production` once cut over) |
| Railway | none | environment `dev` (*target*) | environment `staging` (*target*) | environment `production` (exists) |
| Neon | Docker Postgres | branch `dev` (*target*) | branch `staging` (*target*) | default branch (exists, migrated, seeded) |
| Atlas | Docker Mongo | database `calendar_dev` (*target*) | database `calendar_staging` (*target*) | database `calendar` (*target*; nothing writes to it yet) |
| Database login role | `postgres` | `calendar_dev` | `calendar_staging` | `calendar_prod` |
| Data | seed or a copied dump | seeded (C3-D10) | seeded, then reset from production once it holds real data (C3-D10) | real |

## How a process knows where it is (C3-D3, C3-D4)

`APP_ENV` is `local`, `dev`, `staging` or `prod` (default `local`). At startup `app/config.py` refuses to build
`Settings` unless the claim agrees with where the process really is, in four independent ways: the database host
(local vs hosted), Railway's own `RAILWAY_ENVIRONMENT_NAME`, the database login role (`calendar_<env>`), and the
MongoDB database name (`calendar` for `prod`, `calendar_<env>` otherwise; checked only when the MongoDB URI is hosted, so a laptop that keeps its Docker `MONGODB_URI` is not refused over a database name). The point: Railway's "copy variables
from Production" copies `DATABASE_URL` and `APP_ENV=prod` together, and a staging service would then write to
production. The platform's own variable is not copied, so the check catches it.

**Reaching a hosted database from the laptop** is a one-command override that names its target, never an edit of
`apps/api/.env`:

```bash
APP_ENV=prod DATABASE_URL=postgresql+asyncpg://calendar_prod:...@<neon host>/neondb uv run alembic upgrade head
```

The URL carries no `sslmode` or `channel_binding` (`docs/dev/notes.md`). A command that also points at Atlas sets `MONGODB_DATABASE=calendar_<env>` (`calendar` for `prod`) next to `MONGODB_URI`.

**The frontend** needs `APP_ENV=local` in `apps/calendar/.env.local` (`scripts/cloud-setup.sh` writes it; on a laptop add the line by hand), or `/health` shows "Frontend environment: unavailable".

## Secrets inventory

Variable × environment, no values. "set" means the environment must set it; "unset" means it must not (the default
is right); "n/a" means the environment does not use it. The first table is every variable `Settings`
(`apps/api/app/config.py`) reads, and `app/tests/test_environments_doc.py` fails if it drifts from the class.

<!-- settings-inventory:start -->
| Variable | local | dev | staging | prod | Notes |
|---|---|---|---|---|---|
| `APP_ENV` | unset (`local`) | `dev` | `staging` | `prod` | The claim the startup check verifies (C3-D4). |
| `DATABASE_URL` | Docker Postgres | `calendar_dev` role, `dev` branch | `calendar_staging` role, `staging` branch | `calendar_prod` role, default branch | `postgresql+asyncpg://`, no `sslmode`/`channel_binding`. The role name is the marker the check reads. |
| `MODEL_NAME` | `gemma4-e4b-32k` | set | set | set | Until C6/C8 move extraction to DeepInfra it names an Ollama model, so a hosted value is a placeholder. |
| `ESCALATION_MODEL_NAME` | unset | unset | unset | unset | Optional larger model for the third retry (C6). |
| `MONGODB_URI` | Docker Mongo | Atlas user limited to `calendar_dev` | Atlas user limited to `calendar_staging` | Atlas user limited to `calendar` | The API does not need it; the worker refuses to start without it (C8). |
| `MONGODB_DATABASE` | unset (`calendar`) | `calendar_dev` | `calendar_staging` | `calendar` (the default) | The default is production's name, which is why the check requires the others to set it (C3-PR1-7). |
| `LOG_FORMAT` | unset (`auto`) | unset | unset | unset | `auto` picks JSON off a terminal. |
| `RAILWAY_ENVIRONMENT_NAME` | n/a | set by Railway (`dev`) | set by Railway (`staging`) | set by Railway (`production`) | Never set by hand: it cannot be copied between environments, which is why the platform check trusts it. |
<!-- settings-inventory:end -->

Variables the API's `Settings` does not read (the frontend's, and rows reserved for later milestones):

| Variable | Where | Value by environment | Notes |
|---|---|---|---|
| `APP_ENV` | Vercel | `staging` on every Preview branch, `dev` on branch `dev`, `prod` on Production, `local` in `.env.local` | Validated by `getAppEnv()` against `VERCEL_ENV` and the branch (C3-D7). |
| `API_BASE_URL` | Vercel | the matching Railway API (Preview defaults to staging's, once it exists) | Server-only, never `NEXT_PUBLIC_`. |
| `FLAG_*` | Railway, Vercel | reserved | Added by C3.1. |
| `R2_*` | Railway | reserved | One bucket and token per environment (C9). |
| DeepInfra key | Railway | reserved | One key per environment (C6, C8). |
| `API_SHARED_SECRET` | Railway, Vercel | reserved | C10. |

## Previews on Vercel (C3-D11)

Hobby has no custom environments, so "dev" and "staging" are branch-scoped Preview configurations: Preview
variables default to the staging values for every branch, and the `dev` branch overrides them. A PR preview
therefore reads the staging API, which is read-only to the browser.

## The `dev` lane (Dep-D8)

`dev` is a branch that exists to try something hosted before it is merged. Rule: **a branch's migration is applied
to `dev`'s database only**, never to staging's or production's, until the branch has merged. When the lane moves
to a branch with a different migration set, reset `dev` first (below).

## Data in the lower environments (C3-D10)

* **`dev` is seeded**: the venue seed plus the sample world, with deliberate edge-case records added where a test
  needs them. Deterministic and disposable. To reload it, reset the Neon `dev` branch from its parent, then run
  the seed against it with the override form above and `APP_ENV=dev`.
* **`staging` is seeded the same way until production holds real data**, then refreshed by **reset from parent** so
  it is a rehearsal on production-shaped data. A reset copies **Postgres only**: audit rows copied from production
  name MongoDB staging documents that exist only in production's Atlas database. Those ids dangle in staging and
  that is accepted, because nothing reads a staging document back (`test_staging_is_write_only.py`).
  `agent_run.app_env` tells a copied run from one that happened there.
* *To confirm on the first reset, then record here:* that the connection string and compute endpoint survive,
  whether the per-branch role (`calendar_staging`) survives, and who owns the tables afterwards. If the role or
  its ownership does not survive, the reset procedure re-creates both.

## Neon roles (C3-D9)

A role belongs to a branch, and a child branch inherits its parent's roles when created. So create each
environment's role **after** branching, on its own branch, and make it the **owner of that branch's tables**
(the tables belong to the role that migrated them, and a new role cannot `ALTER` them, which would fail the
pre-deploy migration). Check as the new role with a real table query and a rolled-back DDL probe:

```sql
select count(*) from venue;
begin; alter table agent_run add column _probe int; rollback;
```

`/health/db` runs `SELECT 1` and cannot see a privilege failure; use a table-backed route (`/metro`).

## Cutover order (production, C3 Step 6)

This is where C3 can break production. The order is the plan; the full text is in the plan file.

1. Create the `production` branch at the tip of `main`.
2. Railway production: set `APP_ENV=prod`, change `DATABASE_URL` to the `calendar_prod` role, set the dashboard
   health-check path to `/health` (it is empty today). Check `/health` and `/metro`.
3. Point Railway production's source at the `production` branch.
4. Vercel Production: `APP_ENV=prod`; then merge the C3 PR to `main`.
5. Fast-forward `production` to `main`; set Railway's config file path to `/apps/api/railway.toml` (from the
   repository root); the API deploys, migrates, and `/health` must say `prod`.
6. Move Vercel's Production Branch to `production`.
7. Create Railway `staging` with each variable set by hand (not copied), source `main`.
8. Point Vercel Preview's `API_BASE_URL` at staging's API.
9. `dev`, when wanted.

## Neon–Vercel integration (Dep-D14, C3-D12)

**Skipped, and unrelated to whether a non-prod environment exists.** The integration creates a throwaway Neon
branch per Vercel preview and injects its `DATABASE_URL` into that preview. The Next.js app never connects to
Postgres (only the Railway API does), so the branch would be created and nothing would read it. Staging and dev
are built without it: Neon branches by hand, Railway environments, and branch-scoped Vercel variables.
**Revisit when** ephemeral per-PR environments are wanted (`arch-initial.md` section 9, Phase 2), because that is
the only case where each preview needs its own database.
