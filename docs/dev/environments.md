# Environments

What each environment is, which variables it carries, and the procedures that keep the three apart. The plan that
produced it is `docs/dev/implementations/c3-environments-and-deploy.md`; decisions are cited in the scoped form
(`C3-D4`). **No secret values appear here, ever**: names, shapes and where they are set.

## Current state (read this first)

*As of October 28, 2026, after the C3 runbook (Steps 3–7):* **production and staging are live** in every layer. `dev`
exists as a Neon branch, a login role and an Atlas user, but has **no Railway service** (C3-D1 keeps it on demand until
something needs it; Step 6.9 and Step 8 were skipped by decision). Anything marked *not built* does not exist yet.

| Layer | `local` | `dev` | `staging` | `prod` |
|---|---|---|---|---|
| Git branch | any | `dev` (the lane, below; the branch is not created yet) | `main` | `production` |
| Vercel | `make dev` | Preview, branch `dev` (no branch override set yet) | Preview (`main` and every PR branch), `API_BASE_URL` = staging's API | Production (Production Branch `production`) |
| Railway | none | *not built* | environment `staging`, source `main`, public domain `kind-spontaneity-staging.up.railway.app` | environment `production`, source `production` |
| Neon | Docker Postgres | branch `dev`, schema only, stamped at `67609c405218` | branch `staging`, seeded, at `829af2c3f26f` | default branch, at `829af2c3f26f`, seeded |
| Atlas | Docker Mongo | user `calendar_dev` on database `calendar_dev` (created on first write) | user `calendar_staging` on `calendar_staging` | user `calendar_prod` on `calendar` (nothing writes to it yet) |
| Database login role | `postgres` | `calendar_dev` | `calendar_staging` | `calendar_prod` |
| Data | seed or a copied dump | not loaded (schema only) | seeded, then reset from production once it holds real data (C3-D10) | real |

**Checks recorded (October 28, 2026).** Production: `/health` shows `app_env: prod`, `/metro` answers, pre-deploy
migration ran. Staging: `/health` shows `staging`, `/health/db` up, `/metro` answers; setting `APP_ENV=prod` on the
staging service failed the deploy (the startup check) and was reverted. The Vercel health page shows Frontend and API
environment agreeing on Preview (`staging`) and on Production (`prod`). The `production` branch is protected by a
ruleset (no deletion, no force push, no bypass); a delete from a clone was rejected. Atlas isolation was probed for
all three users. **Not measured:** Neon's behaviour on archiving and the first request after a wake; Atlas pause
behaviour (left to C8). **Known gaps:** the Vercel "Development" `APP_ENV` row should read `local` (not confirmed), and
the `dev`-branch Preview override waits for the `dev` branch.

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
| `SITE_ZONE` | Vercel | unset until a domain is attached; then `staging.pebblebeats.com` on branch `main`; Production stays unset until C11 (`pebblebeats.com`) | Server-only. The environment's own zone (C4-D2): hosts inside it are `<slug>.<zone>`; hosts outside it (`*.vercel.app`, `localhost`) use the default metro. Also the base of every canonical URL and JSON-LD `url` (C4-D8); unset means none are emitted. |
| `SITE_GATE_PASSWORD` | Vercel | a long random value on every Preview branch (staging, and every PR preview, which is also `staging`); unset on Production and local | Server-only secret, never committed or pasted in chat. A gated environment (staging, dev) with this unset answers 503 by design (C4-D6). Changing it logs everyone out (the cookie is an HMAC keyed by it). |
| `DEFAULT_METRO_SLUG` | Vercel | unset everywhere; the code default is `msp` | Optional (C4-D2). A set value that is not a valid, non-reserved slug makes the proxy answer 503 (C4-PR1-4). |
| `FLAG_*` | Railway, Vercel | reserved | Added by C3.1. |
| `R2_*` | Railway | reserved | One bucket and token per environment (C9). |
| DeepInfra key | Railway | reserved | One key per environment (C6, C8). |
| `API_SHARED_SECRET` | Railway, Vercel | reserved | C10. |

## Previews on Vercel (C3-D11)

Hobby has no custom environments, so "dev" and "staging" are branch-scoped Preview configurations: Preview
variables default to the staging values for every branch, and the `dev` branch overrides them. A PR preview
therefore reads the staging API, which is read-only to the browser.

## Hosts, the gate and `noindex` (C4)

Each metro is its own subdomain of an environment's zone. The zone is the part of the domain the environment owns;
its apex is the bare zone name.

| Environment | Zone | Apex | A metro's host |
|---|---|---|---|
| production (C11, not attached yet) | `pebblebeats.com` | `pebblebeats.com` | `msp.pebblebeats.com` |
| staging | `staging.pebblebeats.com` | `staging.pebblebeats.com` | `msp.staging.pebblebeats.com` |
| dev | not set up (C4-D10) | | |

What `proxy.ts` does with a request, in this order (the order is `C4-K2`): refuse (503) if `APP_ENV` is unreadable, a
gated environment has no password, or `DEFAULT_METRO_SLUG` is set but malformed; redirect the apex and any malformed or reserved host to the default metro's host
(no login needed: nothing from the database is revealed); show the password form to anyone without the cookie (staging
and dev only); only then, for a slug that is not the default, ask the API whether it is a real metro. Every response from
a non-production environment carries `X-Robots-Tag: noindex, nofollow`.

* **The gate is a courtesy, not security.** One shared password (`SITE_GATE_PASSWORD`), remembered by a host-only
  `__Host-gate` cookie for 30 days. There is no rate limit and no per-user login, and the Railway API stays public
  until C10, so the gate protects the pages only.
* **Attaching a domain removes Vercel's own login from that host.** Vercel's protection covers `*.vercel.app` only
  (`alpha-deployment-plan.md` §1.1), so the gate is staging's only protection once `msp.staging.pebblebeats.com` is
  attached. Prove it on the `*.vercel.app` URL first (C4 Step 5).
* **Never attach `msp.pebblebeats.com` or the apex to Production before C11** (Dep-D11): that makes production public.
* **Adding a metro** is a database row (the seed) plus its DNS; the slug must be 3 to 32 characters, start with a
  letter, use lowercase letters, digits and hyphens, and not be in `apps/calendar/lib/reserved-slugs.json`.

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
* **What a reset does (verified October 28, 2026, on `staging`):** the host and connection string stay the same.
  **The role is dropped**: `select rolname from pg_roles where rolname like 'calendar_%'` returned no rows right
  after the reset, and table ownership is back with the parent's owner (`neondb_owner`). A login attempted soon
  after the reset appeared to work, which was misleading (probably a session or connection that still held the old
  role), so check `pg_roles`, not a login. After every reset, run the whole "Neon roles" sequence again: create the
  role **with the same password** (so Railway's `DATABASE_URL` for that environment stays valid), then the two
  grants and the ownership block (the script does all of it). Without it the pre-deploy migration fails with "must be owner of table", and
  the service cannot log in at all.
* **A schema-only branch** (how `dev` was made) has the tables but an empty `alembic_version`, so `alembic current`
  prints nothing. Stamp it once with the override form: `APP_ENV=dev DATABASE_URL=… uv run alembic stamp 67609c405218`.
  Do not run `upgrade head` on it; the tables already exist.

## Rehearsing a migration (C4-PR1-9)

A migration that passes on the local test database can still fail on a hosted branch: the hosted branch has real rows,
its own login role and table ownership (C3-PR1-2 was exactly that). The rehearsal runs the pending migrations against a
**copy** first. It creates a short-lived Neon branch from the environment's branch (set to expire by itself), runs
`alembic upgrade head` against it **as that environment's own role**, shows the result, and deletes the copy. It never
touches the real branch, and it refuses to run the migration if the new branch reports the parent's host.

```bash
# once per machine
npm install -g neon                    # the Neon CLI (an older `neonctl` install also works: same tool, either name)
neonctl login                          # or export NEON_API_KEY in the shell
export NEON_PROJECT_ID=...             # the Neon project id (or pass --project-id)

# every rehearsal, from the repository root
make rehearse-migration ENV=staging ARGS='--sql "select slug from metro"'
```

The migration runs from an **empty temporary directory** and is given only `APP_ENV`, `DATABASE_URL`, a placeholder
`MODEL_NAME` and `PYTHONPATH`, so it **never reads your `apps/api/.env`**. That file is unrelated to a hosted branch,
and on the first real run it broke the rehearsal (a local `MODEL_API_KEY` that `Settings` does not know is rejected as
an extra input) and its value was echoed into the error. Output is also scrubbed of any `input_value=...` a validation
error prints. (A normal `make migrate` or `make api` still fails on such a key until `Settings` learns it or you remove
it from `.env`; that is a local mismatch, not a rehearsal problem.)

It asks for the environment role's password (typed hidden), or reads `NEON_ROLE_PASSWORD` from the shell. That is the
password in the environment's `DATABASE_URL` on Railway: the role was created in SQL (C3-D9), so the Neon API cannot
reveal it. It is never put on a command line and is scrubbed from anything printed.

| Option | Meaning |
|---|---|
| `ENV=staging\|dev\|prod` | Which environment's migration to rehearse. `staging` and `dev` copy their own branch; `prod` copies the project's default branch (production's). |
| `--parent NAME` | Copy a different branch instead. |
| `--sql "select ..."` | One SELECT to run after the upgrade, to look at the result. Anything but a single SELECT is refused. |
| `--keep` | Leave the copy for inspection (it still expires). The output prints the command that deletes it. |
| `--ttl-minutes N` / `--no-expiry` | How long Neon keeps the copy before deleting it itself (default 120), or none if your plan rejects `--expires-at`. |

Exit status: **0** the migration worked; **1** it failed or a guard rail refused (the cause is the first line after
`FAILED:`); **3** the result stands but the copy could not be deleted, so one is left and will expire on its own (the
output names it and the time).

**The CLI's two names.** The Neon CLI is published as `neon` (the name the Neon Claude plugin tells you to install) and
as `neonctl` (the older name; the `neonctl` package still installs both). They are the same tool (both 8.14.0 on
npm, identical commands), and the script uses whichever is on `PATH`; set `NEON_CLI` to force one. The plugin's own
branching guidance (`neon-postgres-branches`) recommends the same pattern as this script: a normal branch for testing
a migration against real data, created with `--expires-at`, and deleted afterwards.

**What was and was not verified (October 30, 2026).** neon.com's documentation could not be reached from the cloud
session, so the commands and flags are from `neonctl --help` (8.14.0): `connection-string [branch] --role-name
--project-id`, `branches create --name --parent --project-id --expires-at --no-secrets`, `branches delete <name>
--project-id`. The sequence was run end to end with a stand-in `neonctl` and a local Postgres (five migrations applied
under `APP_ENV=staging` as a `calendar_staging` role, then the copy deleted; a wrong password failed cleanly and still
deleted the copy), and the logic is covered by `app/tests/test_migration_rehearsal.py`. **First real run (Ari,
October 30, 2026): the Neon half worked.** `--expires-at` was accepted, the new branch had its own host, and the copy
was deleted; the Alembic step then failed on his local `.env` (fixed above). **Not yet confirmed:** that the copy
inherits the `calendar_<env>` role and its password from the parent (the login happens in the Alembic step, which has
not yet got that far on real Neon; the script's hint names this if it fails).

The smoke test also found a bug in `migrations/env.py`: a `%` in `DATABASE_URL` (any role password containing `@`, `:`,
`/` or `#`, once percent-encoded) crashed Alembic with "invalid interpolation syntax". Fixed, with a regression test
(`app/tests/test_alembic_env.py`).

## Neon roles (C3-D9)

A role belongs to a branch, and a child branch inherits its parent's roles when created. So create each
environment's role **after** branching, on its own branch, and make it the **owner of that branch's tables**
(the tables belong to the role that migrated them, and a new role cannot `ALTER` them, which would fail the
pre-deploy migration).

**Create the role in SQL, not the console, and use the script.** A role made in the console is a member of
`neon_superuser` and `neondb_owner` has no admin rights over it, so `GRANT <role> TO neondb_owner` is refused
(`permission denied to grant role`) and ownership cannot be handed over. A role created by `neondb_owner` in SQL
is a plain role. The sequence is `restore_role` in `apps/api/app/db/neon_roles.py` (tested in
`app/tests/test_neon_roles.py`), run from the laptop for the branch you are on:

```bash
source .hosted-env.sh && neon_restore_role staging      # or dev, prod
```

It asks for the `neondb_owner` password (to connect), then makes you type the environment name before changing
anything. It asks for the role's password **only if the role is missing** (after a reset), and that must be the one
the environment's `DATABASE_URL` already holds. A role that exists keeps its password; restoring ownership never
touches it, so a typo cannot break a running service. To change a password on purpose, run the separate
`neon_restore_role staging --set-password` and update that environment's `DATABASE_URL` to match. Under the hood,
in this order, in one transaction:

1. `create role calendar_<env> login password …`, only if the role is missing;
2. `grant calendar_<env> to current_user`: `ALTER … OWNER TO x` needs the right to `SET ROLE x`;
3. `grant create on schema public to calendar_<env>`: a new table owner needs `CREATE` on the schema;
4. `alter table … owner to` and `alter type … owner to` for every table and enum type in `public`.

The script is `apps/api/scripts/restore_neon_role.py`; it takes the owner connection from `NEON_OWNER_URL` in the
shell, never from `.env`. `.hosted-env.sh` is a local, uncommitted helper (`neon_restore_role` is in it).

I did not use `REASSIGN OWNED BY neondb_owner`: it also moves ownership of the database itself, which is more
than wanted. Check as the new role with a real table query and a rolled-back DDL probe (the SQL Editor always runs
as `neondb_owner`, so run these from the laptop with the role's URL; `.hosted-env.sh` is the local helper, not in
the repo):

```sql
select count(*) from venue;
begin; alter table agent_run add column _probe int; rollback;
```

`/health/db` runs `SELECT 1` and cannot see a privilege failure; use a table-backed route (`/metro`).

## Railway service settings (set in the dashboard, per service)

There is no `railway.toml`: Railway deprecated Config as Code, a service that has never used it cannot opt in, and the file
was ignored when tried (C3 Step 6.5; `notes.md`). Each API service (production, and staging when it is created) needs these
three set by hand under its Settings:

| Setting | Value | Why |
|---|---|---|
| Start command | `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` | `$PORT` is assigned by Railway; `0.0.0.0` so its proxy can reach it. |
| Healthcheck path | `/health` | Answers without a database query, so a deploy check does not wake Neon, and a failing check makes Railway keep the old deployment when the new one refuses to start (the `APP_ENV` startup rule). Never `/health/db`. |
| Pre-deploy command | `uv run alembic upgrade head` | Migrates before the new code starts, and stops the deploy if it fails. Verified on production: `uv` is on its PATH and the direct Neon host accepts DDL. |

Railway's replacement, Infrastructure as Code (`.railway/railway.ts`), documents no pre-deploy setting, so it is not used.
Old config files stop being read on 2026-12-01; none exists here.

## Cutover order (production, C3 Step 6)

This is where C3 can break production. The order is the plan; the full text is in the plan file.

1. Create the `production` branch at the tip of `main`.
2. Railway production: set `APP_ENV=prod`, change `DATABASE_URL` to the `calendar_prod` role, set the dashboard
   health-check path to `/health` (it is empty today). Check `/health` and `/metro`.
3. Point Railway production's source at the `production` branch.
4. Vercel Production: `APP_ENV=prod`; then merge the C3 PR to `main`.
5. Fast-forward `production` to `main` (`git push origin main:production`); the API deploys, and `/health` must say `prod`.
   Set the pre-deploy command in the service's dashboard (below) so it migrates; there is no config file.
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
