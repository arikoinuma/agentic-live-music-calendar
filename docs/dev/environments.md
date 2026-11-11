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
behaviour (left to C8; the worker's runbook, [The worker on Railway](#the-worker-on-railway-c8), says to check the cluster first). *C8 (November 9, 2026): the worker image and the laptop and console ways to start a run are in the
repository; no Railway worker service exists yet.* **Known gaps:** the Vercel "Development" `APP_ENV` row should read `local` (not confirmed), and
the `dev`-branch Preview override waits for the `dev` branch.

**Checks recorded (November 9, 2026, C3.1).** Feature flags are merged and deployed (`feature_flags` appears in the API's
`/health`). Ari validated that `/health` reflects `FLAG_WORKER_SCHEDULED_RUNS` when the variable is set on the deployed
service. **Skipped by decision:** the typo refusal on a hosted service (the local tests cover it). **Deferred to the
first web flag:** Vercel's treatment of the `FLAG_*` wildcard in `turbo.json` (the build warning only names variables
that are set on Vercel, and none is). Production's proof is at promotion (C3.1-D20).

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
| `MODEL_NAME` | `gemma4-e4b-32k` | `google/gemma-4-26B-A4B-it` (the model C6 chose, November 5, 2026) | same | same | The page model, and the default for every other call. On the API services it is only a placeholder (the API never calls a model); on a worker it is the provider's model id (C6-D2). |
| `MODEL_BASE_URL` | Ollama's `http://localhost:11434/v1`, set in `apps/api/.env` (no default in code, Ari's comment on PR 80) | worker: `https://api.deepinfra.com/v1/openai` | worker: `https://api.deepinfra.com/v1/openai` | worker: `https://api.deepinfra.com/v1/openai` | One endpoint for every call site (C6-D2). Unset on the API services. A worker with none set refuses to start, and so does a hosted worker pointing at localhost (C6-PR1-1, Ari's comment on PR 80). |
| `MODEL_API_KEY` | unset (placeholder) | worker: its own key | worker: its own key | worker: its own key | A secret, one DeepInfra key per environment (C6-PR1-7, Dep-D10). Put it in `apps/api/.env` on the laptop for a hosted run; never inline in a command. |
| `MODEL_PROVIDER` | unset (`ollama`) | worker: `openai_compatible` | worker: `openai_compatible` | worker: `openai_compatible` | Decides which provider-specific request options are sent (C6-D5). |
| `SPLITTER_MODEL_NAME` | unset | unset | unset | unset | The act splitter's own model, e.g. a larger one (A2.1-E1, C6); unset means `MODEL_NAME`. C6 left it unset in every environment, so the splitter uses `MODEL_NAME` (`arch-initial.md` §7). |
| `STATUS_MODEL_NAME` | unset | unset | unset | unset | The cancelled/postponed question's own model; unset means `MODEL_NAME`. |
| `MATCHER_MODEL_NAME` | unset | unset | unset | unset | Reconcile's ambiguous-artist question's own model; unset means `MODEL_NAME`. |
| `ESCALATION_MODEL_NAME` | unset | unset | unset | unset | Optional larger model for the third retry; replaces the page, splitter and status models (C6-D4). It must exist on the configured endpoint. **Leave it unset (C7, November 6, 2026):** the 31B did not pass the pre-registered rule, and the shipped attempt cap is 2, so a third attempt, the only one that uses it, never runs. |
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
| `SITE_GATE_PASSWORD` | Vercel | a long random value on every Preview branch (staging, and every PR preview, which is also `staging`); unset on Production and local | Server-only secret, never committed or pasted in chat. A gated environment (staging, dev) with this unset answers 503 by design (C4-D6). Changing it logs everyone out (the cookie is an HMAC keyed by it), but only on deployments built after the change: Vercel applies an edited variable to new deployments, so an older preview URL keeps the old password. Declared in `turbo.json`'s `globalPassThroughEnv` with the other two request-time variables, or Vercel's build warns that it "WILL NOT be available". |
| `DEFAULT_METRO_SLUG` | Vercel | unset everywhere; the code default is `msp` | Optional (C4-D2). A set value that is not a valid, non-reserved slug makes the proxy answer 503 (C4-PR1-4). |
| `FLAG_*` | Railway, Vercel | per flag | Feature flags (C3.1): one variable per flag, listed in [Feature flags](#feature-flags-c31) below. They are NOT `Settings` fields and do not belong in `apps/api/.env`. |
| `R2_*` | Railway | reserved | One bucket and token per environment (C9). |
| `API_SHARED_SECRET` | Railway, Vercel | reserved | C10. |

## Feature flags (C3.1)

A **feature flag** is a named on/off switch for a behavior that must differ between environments, or be switchable
without a code change. (The word "flag" alone keeps its other meaning: a user flagging a wrong listing,
`arch-initial.md` §7.) It is deliberately small (Dep-D17): a registry in code, one function to read a flag, one
variable per environment. No database table, no vendor, no percentage rollouts, and **a change takes a restart or a
redeploy**: Railway redeploys a service when a variable changes (`notes.md`), and Vercel applies a changed variable to
new deployments only. A runaway production worker is stopped with Railway's controls, not a flag.

Design record: `docs/dev/implementations/c3.1-feature-flags.md`. The registry is `apps/api/app/flags.py`.

### The flags

<!-- flags-inventory:start -->
| Variable | Read by | local | dev | staging | prod | Meaning |
|---|---|---|---|---|---|---|
| `FLAG_WORKER_SCHEDULED_RUNS` | Python (the worker's gate; the API shows it in `/health`) | unset (off) | no service yet | unset (off) | unset (off) | `worker.scheduled_runs`. A worker started with `--trigger scheduled` runs only when this is `true`; off, it logs one line and exits 0, so a Railway cron service can exist without doing work. `--trigger manual` ignores it. Owner Ari, created November 9, 2026. Removal: once production's scheduled run has run unattended for a month after C11 and nobody has needed the off switch (C3.1-D1, Dep-D17). |
<!-- flags-inventory:end -->

`make flags` lists every flag with its owner, creation date and removal condition; `make flags ARGS=--effective` shows
this process's values and whether each came from the environment or the default; `make flags ARGS=--check` is the
hygiene check CI also runs as a test (`app/tests/test_flag_hygiene.py`).

### Rules

* **A value is exactly `true` or `false`**, lower case. `True`, `1`, `yes` and the empty string are refused. An
  **unset** variable falls through to the next level; a **set** one never does, even when it is malformed, so a
  half-typed value in a dashboard cannot quietly read as the default.
* **Precedence:** a per-metro override, then the environment's value, then the registry default. A flag with
  `scope="metro"` accepts `FLAG_<NAME>__<SLUG>` (`FLAG_X__NEW_YORK` for the slug `new-york`: upper case, the hyphen
  written `_`). Nothing uses an override yet; the rule and its tests exist so the second metro does not invent one.
* **A bad variable stops the process at startup**, as `Settings` refuses an unknown key: a `FLAG_*` variable that names
  no registered flag (the message lists the real ones, so a typo is visible), a metro override on a flag that takes
  none, a flag the receiving code base does not read (a Python flag set on Vercel would do nothing while looking set),
  or a malformed value. On Railway a failed startup keeps the old deployment (C3 Step 6), so a typo fails the deploy.
  The web side reports the same problems on the status page (and throws only when a flag is read, never at import).
* **Values come from the process environment only, never from `apps/api/.env`.** `Settings` refuses unknown `.env`
  keys, so a `FLAG_*` line there stops the process by design (pydantic-settings reads a `.env` key into the model and
  ignores an unknown *process* variable; both behaviors were checked by experiment on November 9, 2026).
* **On a laptop, set a flag on the one command that reads it**: `FLAG_WORKER_SCHEDULED_RUNS=true make worker`, or
  `FLAG_X=true make api` / `make web`. **Never for `make dev` or the end-to-end run**, which start the API and the web
  app from one shell and would refuse each other's variables once a flag has only one surface.

### Adding, reading and removing a flag

1. Add an entry to `FLAGS` in `apps/api/app/flags.py`: name (`area.some_name`), description, scope, `surfaces`
   (`python`, `web` or both), default, **owner**, **created**, and the **removal condition**. The registry refuses an
   entry with any of those empty.
2. Read it with `is_enabled("area.some_name")` (Python) or `isEnabled("area.some_name")` (`apps/calendar/lib/flags.ts`).
   **The name must be a string literal** at the call site: the hygiene check finds reads by scanning for it. A flag the
   web reads needs `make types`, which regenerates `lib/flag-registry.ts`.
3. Add its variable to the inventory block above (the test compares both ways) and `make flags ARGS=--check`.
4. To remove one: delete the reads, then the entry, then its row, then unset the variable in each dashboard.

### Checking a flag in each environment

* **local and dev.** There is no hosted `dev` service (C3-D1), and the module has no environment logic (a value comes
  from the variable, never from `APP_ENV`), so `dev` is covered by the tests running the same rule and by the
  inventory row. Set a flag on a command to see it: `FLAG_WORKER_SCHEDULED_RUNS=true make flags ARGS=--effective`.
* **staging.** `GET <staging API>/health` lists the effective values (`feature_flags`).
* **production.** `/health` hides them (`feature_flags` is `null`: the route is public until C10, and whether the cron is
  armed is operational state). The proof is at the first promotion that carries C3.1 and C8: C8's skip run logs the flag
  as off. A direct read, once production has the code: run `scripts.flags --effective` with the production API service's
  variables through `railway run`, from an empty directory with `uv run --project apps/api`.

## Previews on Vercel (C3-D11)

Hobby has no custom environments, so "dev" and "staging" are branch-scoped Preview configurations: Preview
variables default to the staging values for every branch, and the `dev` branch overrides them. A PR preview
therefore reads the staging API, which is read-only to the browser.

## Hosts, the gate and `noindex` (C4)

Each metro is its own subdomain of an environment's zone. The zone is the part of the domain the environment owns;
its apex is the bare zone name.

| Environment | Zone | Apex | A metro's host |
|---|---|---|---|
| production (C11; only `pebblebeats.com` and `www` are attached, see below) | `pebblebeats.com` | `pebblebeats.com` | `msp.pebblebeats.com` (not attached) |
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
* **`msp.pebblebeats.com` and a production zone wait for C11** (Dep-D11). **Departure from C4's plan (Ari, November 2,
  2026):** `pebblebeats.com` (a 308 to `www`) and `www.pebblebeats.com` are attached to Production and stay that way. The
  plan said to attach nothing to Production. They serve the production deployment, which is public, ungated and sends
  no `X-Robots-Tag`. **Production keeps no `SITE_ZONE` until C11.** With a zone of `pebblebeats.com`, `www` is a reserved
  slug, so `www.pebblebeats.com` would count as a bad host and redirect to `msp.pebblebeats.com`, which is not attached.
* **Adding a metro** is a database row (the seed) plus its DNS; the slug must be 3 to 32 characters, start with a
  letter, use lowercase letters, digits and hyphens, and not be in `apps/calendar/lib/reserved-slugs.json`.

### As built (verified November 2, 2026)

**Vercel project domains.** `staging.pebblebeats.com`, `msp.staging.pebblebeats.com` and `*.staging.pebblebeats.com`,
each bound to Git branch `main` (Preview); `pebblebeats.com` (308 to `www`) and `www.pebblebeats.com` on Production;
the project's `*.vercel.app` name on Production. Namecheap's DNS points at Vercel, and Vercel reports every entry as
Valid Configuration. `SITE_ZONE=staging.pebblebeats.com` is set for Preview on `main` only (the apex redirect below
only works with it); `SITE_GATE_PASSWORD` is set for all Preview branches.

**Checked with no cookie** (Claude, from the cloud session, through Vercel's share link; Ari did the login):

| Request | Result |
|---|---|
| `https://staging.pebblebeats.com/venues` (the apex) | 307 to `https://msp.staging.pebblebeats.com/venues`, with `X-Robots-Tag: noindex, nofollow`; no login needed |
| `https://www.staging.pebblebeats.com/venues` (reserved word) | 307 to `https://msp.staging.pebblebeats.com/venues` |
| `https://msp.staging.pebblebeats.com/venues` | the password form (`/gate`), `noindex, nofollow`, canonical `https://msp.staging.pebblebeats.com/gate` |
| `https://foo.staging.pebblebeats.com/venues` (an unknown slug) | the same password form: nothing about which metros exist is shown before the gate |
| Login on `msp.staging.pebblebeats.com` (Ari) | works; the calendar loads |
| Login on `foo.staging.pebblebeats.com/gate` (Ari; the cookie is host-only, so each host asks once) | after the password, redirected to `msp.staging.pebblebeats.com`: the API said `foo` is not a live metro (the order is gate first, then the liveness check, C4-K2) |
| `https://kind-spontaneity-staging.up.railway.app/metro` (Ari; this is the API on Railway, the website has no `/metro` route) | `{"id":1,"name":"Minneapolis/St. Paul","timezone":"America/Chicago","slug":"msp"}`: the slug migration ran on staging |
| A `*.vercel.app` preview (Ari, and Claude without a cookie) | the password form; so Vercel's `host` header is the public host, which C4's code relied on |
| `https://www.pebblebeats.com/health` (Production) | loads with no gate and no `X-Robots-Tag`; frontend and API environments both `prod` |

**Limits found.**

* **Hobby accepts a wildcard bound to a branch** (`*.staging.pebblebeats.com` on `main`), so the decoy host C4 allowed
  for is not needed (Dep-D7's open question, answered).
* **A wildcard covers one label.** `a.b.staging.pebblebeats.com` (two labels) fails with `ERR_CONNECTION_CLOSED`: no
  certificate covers it, so the request never reaches the proxy. The bad-host redirect in the code (and its unit test) is
  therefore reachable only for one-label hosts such as `www.` and other reserved words. Accepted: a two-label host is never
  a link we publish.
* **A changed `SITE_GATE_PASSWORD` reaches only deployments built after the change.** An older preview URL keeps the old
  password, and a browser holding that deployment's `__Host-gate` cookie is still let in. Test the gate on the newest
  deployment, in a private window.
* **Production is still the pre-C4 build.** The `production` branch had not been fast-forwarded (C4 Step 4.6): 48
  commits behind `main` on November 2, 2026. Until it is, Production has no proxy, no gate code and no `metro.slug`,
  and its Railway pre-deploy migration for the slug has not run. Promote API first, then the frontend, as Step 4 says.


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

If the environment role **cannot log in to the copy**, the script says why instead of leaving you with "password
authentication failed" (Postgres gives that same message for a wrong password and for a role that does not exist):
it connects to the copy as the branch owner and checks `pg_roles`, then prints one of three diagnoses: the role is
**missing** on the copy (Neon did not carry it over), it **exists but cannot log in**, or it **exists and can log in**,
so the password typed is wrong. The usual slip for the last one is typing the percent-encoded text from a connection
string (`%40` for `@`) instead of the raw password.

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
deleted the copy), and the logic is covered by `scripts/tests/test_rehearse_migration.py`. **Real Neon (Ari,
October 30, 2026): it works.** The third run passed end to end on a copy of staging: `--expires-at` was accepted, the
copy had its own host, `calendar_staging` logged in on the copy (so **Neon does carry a SQL-created role and its
password into a child branch**), `alembic upgrade head` ran `829af2c3f26f -> c4a1e5b7d903 (metro slug)`, the check
`select slug from metro` returned `msp`, and the copy was deleted. The two earlier failures were both on our side:
a local `.env` key that `Settings` forbids (fixed above), and a login failure on the copy whose cause was never read
off the output (the third run, with the raw password, passed; a typed percent-encoded password is the likely
cause, not confirmed).

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
is a plain role. The sequence is `restore_role` in `apps/api/scripts/restore_neon_role.py` (tested in
`scripts/tests/test_restore_neon_role.py`), run from the laptop for the branch you are on:

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

## The worker on Railway (C8)

*Written from the C8 plan (`docs/dev/implementations/c8-worker-on-railway.md`) before any worker service exists. The code
(the image, the gate, the laptop command) is in the repository; **creating the services is the plan's Steps 8 to 12, Ari's
dashboard work, and nothing below is recorded as done until those steps are.** Facts about Railway that are not verified
are the plan's `C8-U1` to `C8-U9`; each is marked resolved there when its step has run.*

### The service (one per environment: `staging`, and `production`; `dev` has no Railway environment, C3-D1, C8-D1)

The image is `apps/api/Dockerfile.worker`, never a file named `Dockerfile` (that name would switch the **API** service,
rooted at the same directory, to a Docker build: C8-D10, C8-U3). Set by hand under the service's Settings and Variables;
never "copy variables from Production" (C3-D4).

| Setting | Value | Why |
|---|---|---|
| Name | `worker` | `make worker-hosted` selects the service by this name (C8-D3). |
| Source branch | `main` (staging), `production` (production) | As the API services. A worker service is created only after its branch holds `Dockerfile.worker` and the scheduled-run gate (C8-D13, C8-U1). |
| Root Directory | `apps/api` | The build context; `.dockerignore` is read from here. |
| Variable `RAILWAY_DOCKERFILE_PATH` | `Dockerfile.worker` | Selects the file; service variables are not build arguments. |
| Cron schedule | `0 10 * * *` (UTC: 4 a.m. in Minneapolis in winter, 5 a.m. in summer) | C8-D5. Staging gets the same schedule with the flag off (expected, not observed: a service with no schedule is a one-shot process that Railway would show as crashed) and production's is gated until C11 (C8-D9). |
| Start command | none: the image's `CMD` is `python -m agent_worker.main --trigger scheduled` | C8-D4: the flag gates exactly this trigger, so a run Railway starts by itself is a logged skip while the flag is off. |
| Restart policy | Never | A failed run must not be retried into a loop (C8-U2 is checked by the plan's Step 9). |
| Healthcheck, pre-deploy command | none | It is not a web service, and only the API migrates (C8-D9). |

Variables: `APP_ENV` (`staging` or `prod`), `DATABASE_URL` (the **same** `calendar_<env>` login role as that environment's API),
`MONGODB_URI` and `MONGODB_DATABASE` (`calendar_staging`; `calendar` for production), `MODEL_BASE_URL`, `MODEL_PROVIDER`,
`MODEL_NAME` and `MODEL_API_KEY` (the environment's own DeepInfra key): the values are in the secrets inventory above.
**`FLAG_WORKER_SCHEDULED_RUNS` is not set**, so scheduled runs are off; arm it with exactly `true` **on the worker service, not
the API's** (the API runs no gate). A misspelled or malformed `FLAG_*` value makes the container fail at startup, which on a
cron service shows on its next run, not at deploy (`Settings` refuses it, C3.1-D12).

### Starting a run

| How | Where it runs | Use it for |
|---|---|---|
| The cron schedule | Railway's container | The daily run, once the flag is `true` (C11 for production). With the flag off it logs `scheduled run skipped: feature flag worker.scheduled_runs is off`, writes nothing and exits 0. |
| `make worker-hosted ENV=staging\|prod [VENUE=<id>]` | **This machine**, with that service's variables | The quick manual run (C8-D3). It executes the files checked out here, so it refuses unless the tree is clean and `HEAD` is `origin/main` (staging) or `origin/production` (prod), prints the commit, and asks for `production` to be typed for prod. Needs the Railway CLI signed in and `RAILWAY_PROJECT_ID` in the shell. Records `trigger='manual'`; ignores the flag. |
| The service's **Console** tab | Railway's container | A manual run in the real image, on Railway's network (C8-D15). Needs a **running** deployment: whether a cron service has one between runs is C8-U8, and if not the plan adds an idle `worker-shell` service (C8-U9). |

**Console runbook** (*written before any worker service exists; whether Railway's console is a login shell, and which
directory it starts in, are not known (C8-U8), so every command names the interpreter and the directory instead of relying
on `PATH` or the image's `ENV`. The image still puts its virtual environment on `PATH` and `/app` on `PYTHONPATH`, which
covers a shell that inherits them*):

```bash
cd /app && /app/.venv/bin/python -m agent_worker.main --help      # proves the image and its libraries
cd /app && nohup /app/.venv/bin/python -m agent_worker.main --trigger manual --venue 3 > /tmp/run.log 2>&1 &
tail -f /tmp/run.log                    # Ctrl-C stops the tail, not the run
```

**How to check C8-U8 and C8-U9** (the plan's Step 8a): between two ticks of the cron `worker`, open its **Console** tab. If it
gives a shell with the worker's variables, U8 holds; run the first command above to confirm the image. If it does not (no running
deployment), add the idle `worker-shell` service of the same image with the start command `sleep infinity`, and repeat there (U9:
what it costs, and whether it can share the worker's variables by reference). Record the result against `C8-U8` and `C8-U9`.

* `nohup` and `&` so a closed browser tab does not end the run. **The record of a console run is `agent_run`,
  `audit_log` and the Atlas document, not Railway's deployment log** (expected: a shell session's output is probably not in it; unobserved): `make db-shell`
  cannot reach a hosted database, so use the saved queries in `docs/dev/audit-queries.sql` through the one-command override above.
* Check the Atlas cluster is running first: the free cluster pauses after weeks without a connection and has to be resumed
  by hand (C1; C8-D8). The worker's "MongoDB did not answer" message says so on a hosted environment.
* A redeploy ends a run in progress: a merge to `main` redeploys staging's worker. The shell holds the service's secrets,
  so do not run `printenv` where it is recorded or shared. Production's console path is created at C11 (C8-D15).

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
