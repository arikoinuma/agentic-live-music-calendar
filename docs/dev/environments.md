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
| Railway | none | *not built* | environment `staging`, source `main`, public domain `kind-spontaneity-staging.up.railway.app`; worker services `worker` and `worker-shell` (C8) | environment `production`, source `production`; worker service `worker-prod` (C11 Step 5, November 24, 2026) |
| Neon | Docker Postgres | branch `dev`, schema only (no rows), at `d7b3c2a91e45`, the head of `main` (upgraded November 23, 2026, C10-D5) | branch `staging`, seeded, at `d7b3c2a91e45` | default branch, at `829af2c3f26f` (the head of the `production` branch; two revisions behind `main` until C11 promotes), seeded |
| Atlas | Docker Mongo | user `calendar_dev` on database `calendar_dev` (created on first write) | user `calendar_staging` on `calendar_staging` | user `calendar_prod` on `calendar` (nothing writes to it yet) |
| Database login role | `postgres` | `calendar_dev` | `calendar_staging` | `calendar_prod` |
| Data | seed or a copied dump | not loaded (schema only) | seeded, then reset from production once it holds real data (C3-D10) | real |

**Checks recorded (October 28, 2026).** Production: `/health` shows `app_env: prod`, `/metro` answers, pre-deploy
migration ran. Staging: `/health` shows `staging`, `/health/db` up, `/metro` answers; setting `APP_ENV=prod` on the
staging service failed the deploy (the startup check) and was reverted. The Vercel health page shows Frontend and API
environment agreeing on Preview (`staging`) and on Production (`prod`). The `production` branch is protected by a
ruleset (no deletion, no force push, no bypass); a delete from a clone was rejected. Atlas isolation was probed for
all three users. **Not measured:** Neon's behaviour on archiving and the first request after a wake; Atlas pause
behaviour (left to C8; the worker's runbook, [The worker on Railway](#the-worker-on-railway-c8), says to check the cluster first). **Known gaps:** the Vercel "Development" `APP_ENV` row should read `local` (not confirmed), and
the `dev`-branch Preview override waits for the `dev` branch.

**Checks recorded (November 9, 2026, C3.1).** Feature flags are merged and deployed (`feature_flags` appears in the API's
`/health`). Ari validated that `/health` reflects `FLAG_WORKER_SCHEDULED_RUNS` when the variable is set on the deployed
service. **Skipped by decision:** the typo refusal on a hosted service (the local tests cover it). **Deferred to the
first web flag:** Vercel's treatment of the `FLAG_*` wildcard in `turbo.json` (the build warning only names variables
that are set on Vercel, and none is). Production's proof is at promotion (C3.1-D20).

**Checks recorded (November 18, 2026, C8, staging).** Staging has two worker services: `worker` (cron `0 10 * * *`,
source `main`, built from `Dockerfile.worker`, restart policy Never) and `worker-shell` (idle, `sleep infinity`, for a console).
*Environment:* Atlas Network Access is now `0.0.0.0/0` (it held only the laptop's IP; Railway Hobby has no fixed egress IP, C8-U6);
the cluster is MongoDB **8.0.37** (local Docker is 7.0, A4-D3); the Railway CLI is 5.71.0, which has `railway cron list` and
`railway cron run` (5.47.1 had neither, C8-U4); staging's database had migration `d7b3c2a91e45` before the first run.
*Observed:* the nightly cron ran every day from November 13 and, with the flag off, logged
`scheduled run skipped: feature flag worker.scheduled_runs is off` and exited in 3 to 8 s (`EXITED`). A deploy never started the
command by itself (seven worker deploys; the first run on each came from Run now or the schedule, C8-U1). A malformed
`FLAG_WORKER_SCHEDULED_RUNS=yes` crashed the container at startup with `Settings`' refusal (`CRASHED`, exit 1, no I/O); a
`MODEL_BASE_URL` of `http://localhost:1/v1` was refused by the endpoint check (`CRASHED`, no I/O); neither was retried (C8-U2).
A cron service has no console between runs (C8-U8), so `worker-shell` exists (C8-U9). *Real runs* (all `staging`, `finished_at`
set, `failed=0`): run 1, `--trigger manual --venue 1` from `worker-shell`, 20.9 s, 11 shows inserted; runs 2 to 5, `manual`, all
four venues, 142.2 s (venue 1: 1 update and 10 no-ops; the others 24, 11 and 9 inserts); runs 6 to 9, **`scheduled` with
`FLAG_WORKER_SCHEDULED_RUNS=true` on the worker, started with Run now, `feature_flags = {"worker.scheduled_runs": true}`**,
109.2 s, 1 update and the rest no-ops. DeepInfra reported **$0.00752** for the three model sessions. The flag was then deleted and
the next run was a skip again. `msp.staging.pebblebeats.com` shows the shows. **Not done:** production's worker (the plan's Step 11);
the first run through the laptop command `make worker-hosted` (it needs `RAILWAY_PROJECT_ID`; the fake-process tests cover it; first run November 19, 2026, C9, below);
the staging API's build log came back empty from the CLI, so U3's second half (the API still builds without a
Dockerfile) is **not checked**: read its latest build log in the dashboard.

**Checks recorded (November 19, 2026, C9, staging).** Page snapshots are merged (PR 117, commit `192cff7`) and live on staging.
*Environment:* bucket `r2-pebble-staging` (public access off, no `r2.dev` URL, no custom domain), the four `R2_*` variables on `worker`
and `worker-shell`, and the **default** endpoint `https://<account id>.r2.cloudflarestorage.com`. The Cloudflare account asked for a payment
method (C9-U2). *Observed:* the first laptop run, `make worker-hosted ENV=staging VENUE=1`, stopped at the C9-D8 preflight with exit 2 and
`kind=config`, `code=NoSuchBucket`, **before the start line and any venue**: the endpoint in the variable was a non-default one the dashboard
offered for the US, and a bucket created with the default location does not exist at it. With the default endpoint the preflight passed and
the run was clean. Run 10 (`--venue 1`, 16.8 s, `failed=0`) and runs 11 to 14 (all four venues, 173.3 s, `failed=0`, `manual`, from the
laptop with staging's variables) each have a fetch row with a `snapshot_key` and `detail.snapshot`; the start lines read
`snapshots=r2-pebble-staging`. The objects, in bytes: `venues/1/2026-11-19-run-10.html` 98423, `venues/1/2026-11-19-run-11.html` 98423
(the same page twice, so two objects, as C9-D5 intends), `venues/2/...-run-12.html` 200078, `venues/3/...-run-13.html` 896151,
`venues/4/...-run-14.html` 124802: 1,417,877 in all. *The check that matters:* the object for run 10 read back with `get_object` from
`worker-shell` (so from Railway's network) is 98423 bytes with SHA-256 `df5b5bf9c3bfb6fdb07423f43f9ea9f5fc7a40408339649080fad99e8eaa2a2d`, equal
to `detail.snapshot.sha256`. `fetches_without_snapshots` returned no rows for run 10 and for runs 10 to 14; `snapshot_storage_by_month`
gave one row, 2026-11, 5 snapshots, 1,417,877 bytes. The bucket holds 4 folders and 5 files, matching.
*Sizing (C9-D10):* one daily run of these four venues is about 1.32 MB, about two thirds of it Mortimer's page (896 KB), so about 0.48 GB
a year; twelve venues of the same average would be about 1.4 GB a year, against the free 10 GB. *Not done, and why:* the **write from inside**
Railway's container (only a read from `worker-shell` was run; the write came from the laptop, so C9-U4's read half is proven and its write
half carries to the first scheduled run with the flag on, C11); the bucket's **aggregate size against `snapshot_storage_by_month`**
(Cloudflare's dashboard has no single screen with the bucket's total size or object count, so only the folder and file counts were
compared); production's bucket (C11). **Unexplained:** an object downloaded through the Cloudflare dashboard was 99829 bytes with a different
hash, 1406 bytes larger than the stored object; it is not a line-ending conversion (removing every carriage return did not restore the
hash). The read-back is the check that was trusted; do not hash a dashboard download.

**Checks recorded (November 23, 2026, C10, staging).** The shared secret is merged (PR 120) and live on staging; production's pair and its proof
are C11's (C10-D1). *Set before the merge (C10-D13):* `API_SHARED_SECRET` on the staging **API** service (Railway service `kind-spontaneity`) and on
Vercel Preview (all branches, Sensitive). It was first set on `worker` and `worker-shell` by mistake and moved to the API service; the worker never
reads it. *Observed, with no header:* `/metro` and `/health/db` answered **401** with `{"detail":"Missing or invalid API secret"}`, `/health` answered
**200** (`app_env: staging`, no secret in the body), and `/openapi.json` and `/docs` answered **404** (the schema is switched off outside local and dev,
C10-D2). *With the header:* the right value answered **200** on `/metro` and a wrong one **401** (C10-U1: Railway's edge passes `X-Api-Secret` through
unchanged). The staging calendar renders after the gate, its `/health` page reads "API data access: ok", and Vercel's runtime log shows
`[api] GET /metro -> 200` (C10-U2: the Preview-scope variable reaches the staging deployment and a server component reads it per request). A PR preview
built after the variable was set built and deployed, and Vercel's "variable not in turbo.json" warning is gone. **Not run:** C10-U3 (deleting the
variable on staging to watch the redeploy fail while the old one keeps serving): the lifespan refusal is covered by `test_api_guard.py` (C10-T6), and the
Railway half stays unverified until someone does it. *The ruleset (C10-D4):* `Basic Protection` now requires six checks, read back with `gh api` on
November 23, 2026: `Python (apps/api)`, `JS (turbo lint + check-types + test)`, `Contract (schemas.py -> TypeScript)`, `E2E (Playwright, real API on sample
data)`, `Designations (scoped IDs)` and `Worker image (docker build and run)` (C10-U4).
*Migration parity (C10-D5):* `make rehearse-migration ENV=dev` passed on a copy of dev (it was at `67609c405218`; it ran `829af2c3f26f`, `c4a1e5b7d903`,
`d7b3c2a91e45`; the copy was deleted), then the same three upgrades ran on dev itself. `alembic current`: **dev** `d7b3c2a91e45` (head), **staging**
`d7b3c2a91e45` (head), **production** `829af2c3f26f`. Rows: dev has 0 venues and no metro row (never seeded: C3-D10 says dev is seeded and it is not; seeding
it has no consumer until dev gets a service, so it stays schema-only, C10-D5); staging has 4 venues and one metro, `msp`; production has 4 venues and
one metro (Minneapolis/St. Paul; it has no `slug` column yet, so it was read with `select *`). Staging and production hold the **same four venues**, ids 1 to
4: The White Squirrel Bar, 7th St Entry, Mortimer's, The Terminal Bar. **Production is two migrations behind `main` by design:** its branch lacks `c4a1e5b7d903`
(`metro slug`, which changes a populated table) and `d7b3c2a91e45`, and C11's promotion runs both in the API's pre-deploy, after a rehearsal on a copy
(`make rehearse-migration ENV=prod`). *Cost note:* Neon's free plan suspended the project for compute hours during these checks (each manual SQL session keeps
compute awake for minutes, and the rehearsal's copies count); the $5 add-on gives 250 CU-hours and is the cheaper option at this size, so revisit it from the
Usage page at C11's burn-in.

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
| `R2_ENDPOINT_URL` | unset (snapshots off), or a bucket made for the laptop | unset (dev has no worker, C9-D3) | worker: `https://<Cloudflare account id>.r2.cloudflarestorage.com` | worker: same form, at C11 | Where the worker stores each fetched page (C9). The API does not need it. All four `R2_*` rows are set together or not at all: a hosted worker refuses to start without them (exit 2), and a laptop with some but not all refuses too (`snapshot_config_problem`, C9-D8). Must start `https://`. |
| `R2_ACCESS_KEY_ID` | unset | unset | worker: the Access Key ID of the staging bucket's token | worker: production's own, at C11 | From an Object Read & Write token scoped to that one bucket, created in the Cloudflare dashboard (C9 Step 6). |
| `R2_SECRET_ACCESS_KEY` | unset | unset | worker: the same token's Secret Access Key | worker: production's own, at C11 | A secret, shown **once** when the token is created: copy it into your password manager at that moment. A `SecretStr` in `Settings`, so a repr or a traceback cannot print it. Never inline in a command or pasted in chat. |
| `R2_BUCKET` | unset (snapshots off; the normal laptop setting), or `…-local` to exercise the write on purpose (never `…-dev`, `…-staging` or `…-prod`) | `…-dev` when dev gets a worker | worker: `<prefix>-staging` | worker: `<prefix>-prod`, at C11 | One private bucket per environment (Dep-D10), no public access. A hosted worker's bucket must END in `-<APP_ENV>`, and a laptop's must not end `-dev`, `-staging` or `-prod` (C9-D9, C9-CR1-3): a copied variable set would otherwise write one environment's pages into another's bucket. |
| `API_SHARED_SECRET` | unset (the API serves openly), or any value to try the guard by hand | unset (no hosted dev API yet) | **API service** (not `worker` or `worker-shell`): `openssl rand -hex 32`, the same value as Vercel Preview's | the API service's own value, created at C11 (C10-D1) | A secret, kept in your password manager; never pasted in chat or inline in a command. A hosted API (`APP_ENV` `dev`, `staging` or `prod`) **refuses to start** without one of at least 32 characters (C10-D9); unset on a laptop means open. A `SecretStr` in `Settings`, so a repr or a traceback cannot print it. [The shared secret (C10)](#the-shared-secret-c10) says what it protects and how to rotate it. |
| `RAILWAY_ENVIRONMENT_NAME` | n/a | set by Railway (`dev`) | set by Railway (`staging`) | set by Railway (`production`) | Never set by hand: it cannot be copied between environments, which is why the platform check trusts it. |
<!-- settings-inventory:end -->

Variables the API's `Settings` does not read (the frontend's, and the other side of a variable `Settings` does read):

| Variable | Where | Value by environment | Notes |
|---|---|---|---|
| `APP_ENV` | Vercel | `staging` on every Preview branch, `dev` on branch `dev`, `prod` on Production, `local` in `.env.local` | Validated by `getAppEnv()` against `VERCEL_ENV` and the branch (C3-D7). |
| `API_BASE_URL` | Vercel | the matching Railway API (Preview defaults to staging's, once it exists) | Server-only, never `NEXT_PUBLIC_`. |
| `SITE_ZONE` | Vercel | unset until a domain is attached; then `staging.pebblebeats.com` on branch `main`; Production stays unset until C11 (`pebblebeats.com`) | Server-only. The environment's own zone (C4-D2): hosts inside it are `<slug>.<zone>`; hosts outside it (`*.vercel.app`, `localhost`) use the default metro. Also the base of every canonical URL and JSON-LD `url` (C4-D8); unset means none are emitted. |
| `SITE_GATE_PASSWORD` | Vercel | a long random value on every Preview branch (staging, and every PR preview, which is also `staging`); unset on Production and local | Server-only secret, never committed or pasted in chat. A gated environment (staging, dev) with this unset answers 503 by design (C4-D6). Changing it logs everyone out (the cookie is an HMAC keyed by it), but only on deployments built after the change: Vercel applies an edited variable to new deployments, so an older preview URL keeps the old password. Declared in `turbo.json`'s `globalPassThroughEnv` with the other two request-time variables, or Vercel's build warns that it "WILL NOT be available". |
| `DEFAULT_METRO_SLUG` | Vercel | unset everywhere; the code default is `msp` | Optional (C4-D2). A set value that is not a valid, non-reserved slug makes the proxy answer 503 (C4-PR1-4). |
| `FLAG_*` | Railway, Vercel | per flag | Feature flags (C3.1): one variable per flag, listed in [Feature flags](#feature-flags-c31) below. They are NOT `Settings` fields and do not belong in `apps/api/.env`. |
| `API_SHARED_SECRET` | Vercel | **Preview, all branches** (every PR preview, `dev` and staging): the same value as staging's API service, marked Sensitive; Production: C11's, created before the promotion (C10-D1); local: unset | Server-only, never `NEXT_PUBLIC_`; read per call by `lib/api.ts` and sent as `X-Api-Secret` (C10-D10). The Railway side is the settings-inventory row above. Vercel applies a changed variable to NEW deployments only, so redeploy after changing it. |

## The shared secret (C10)

The API has no users: its one caller is the Next.js server, and everything it serves is public calendar data. But a Railway
URL is reachable from the whole internet, so without a check anyone could read the API directly, get around the staging
gate (which protects pages only) and make Neon run queries. C10 adds one shared secret (`docs/dev/implementations/c10-wiring-and-guard-rails.md`,
C10-D6 to C10-D10).

* **The header.** `X-Api-Secret: <the secret>` (the raw value, not `Bearer`). `lib/api.ts`'s `send()` adds it to every call, in that
  one place, from `API_SHARED_SECRET` read per request. The API's dependency (`app/security.py`) answers **401** `{"detail": "Missing or invalid API secret"}`
  for a missing, a wrong and an unreadable header alike.
* **What is open.** Only `GET /health` (Railway's deploy check and the status page call it with no header, and it touches no database).
  Everything else is guarded by default, including `/health/db`, which does a database round trip; a test (`test_api_guard.py`, C10-T3)
  fails if a documented route answers anything but 401 without the header. `/docs`, `/redoc` and `/openapi.json` are served on a laptop
  and in dev only (C10-D2).
* **Unset.** On a laptop (`APP_ENV` `local`) an unset secret means the API is open, so `make dev` needs nothing. A hosted API
  (`dev`, `staging`, `prod`) **refuses to start** without a secret of at least 32 characters, and if one somehow runs without it, it
  answers 401 to everything (C10-D9). Railway keeps the previous deployment serving when a new one fails to start.
* **Generate one.** `openssl rand -hex 32` (64 characters). Put it in your password manager first. Never paste it in chat, a commit or a
  command line that lands in shell history.
* **Where it is set.** The settings inventory above: the Railway **API** service of the environment (not `worker`, not `worker-shell`) and
  Vercel (Preview, all branches, for staging; Production at C11), the **same** value on both sides of an environment. **Set the variables
  before the merge that deploys the guard**: the new API refuses to start without it, and a new frontend with no secret is refused by a guarded API.
* **Rotation.** The API accepts one value, so a rotation has a short window of 401s on the pages (they show the error page, never data):
  (1) generate the new value and store it; (2) set it on the Railway API service (it redeploys); (3) set it on Vercel and **redeploy**
  (a changed variable applies to new deployments only); (4) check the proof below. The window runs from step 2 taking effect to step 3
  finishing, so do both in one sitting. A leaked value is rotated the same way.
* **The one-command check.** With the secret read from your password manager (`read -rs API_SECRET`), against an environment's API address:
  `curl -s -o /dev/null -w "%{http_code}\n" <api>/metro` should print **401**, the same with `-H "X-Api-Secret: $API_SECRET"` **200**, and `<api>/health` **200**
  with no header. Staging's page `/health` also shows an "API data access" row (`ok`, `refused` or `unavailable`); production's reads
  `not checked`, because that page is public and the probe is a database round trip (C10-D3).

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
* **production.** `/health` hides them (`feature_flags` is `null`: the route is public and stays open after C10, because the deploy check needs it, and whether the cron is
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
  `__Host-gate` cookie for 30 days. There is no rate limit and no per-user login, and the Railway API has its own
  shared-secret guard since C10 ([The shared secret (C10)](#the-shared-secret-c10)), so the gate protects the pages only.
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

* **`dev` is meant to be seeded** (as built it is schema-only, and C10-D5 left it that way): the venue seed plus the sample world, with deliberate edge-case records added where a test
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
  Do not run `upgrade head` on it; the tables already exist. (`dev` has since been brought to head the normal way, with a
  rehearsal and then `upgrade head`, on November 23, 2026, C10-D5; the stamp is only for a branch whose tables exist
  but whose `alembic_version` is empty.)

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

The script asks for the environment role's password with a **hidden prompt** (the RAW password, not the percent-encoded text inside
`DATABASE_URL`), so it needs a real terminal: from a tool that has no terminal it stops with `EOFError`. The first `neonctl projects list` also
asks for a default organization and, if you accept, writes a `.neon` file into the directory (it is git-ignored). `NEON_PROJECT_ID` must be
in the same shell as the command; prefixing it on the command line (`NEON_PROJECT_ID=... make rehearse-migration ENV=dev`) cannot miss.

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

*C8 (`docs/dev/implementations/c8-worker-on-railway.md`). The code (the image, the gate, the laptop command) is in the
repository. **Staging has run it hosted since November 12–18, 2026** (the checks are under "Current state"); **production has
no worker service yet** when this was written (the plan's Step 11; it is `worker-prod` since C11 Step 5, below). The `C8-U1` to `C8-U9` labels are the plan's unverified Railway facts; each is
marked below with what was observed.*

### The service (one per environment: `staging`, and `production`; `dev` has no Railway environment, C3-D1, C8-D1)

The image is `apps/api/Dockerfile.worker`, never a file named `Dockerfile` (that name would switch the **API** service,
rooted at the same directory, to a Docker build: C8-D10, C8-U3). Set by hand under the service's Settings and Variables;
never "copy variables from Production" (C3-D4).

| Setting | Value | Why |
|---|---|---|
| Name | **`worker` in staging, `worker-prod` in production** | `make worker-hosted` selects the service by these names (C8-D3; `SERVICE_FOR_ENV` in `scripts/hosted_worker.py`). They differ because **Railway service names are unique across the whole project, not per environment**: the staging worker holds `worker`, so creating production's as `worker` was refused ("already exists", C11 Step 5) and it is `worker-prod` (GH-123). A new environment's worker needs its own name, added to that map. |
| Source branch | `main` (staging), `production` (production) | As the API services. A worker service is created only after its branch holds `Dockerfile.worker` and the scheduled-run gate (C8-D13, C8-U1). |
| Root Directory | `apps/api` | The build context; `.dockerignore` is read from here. |
| Variable `RAILWAY_DOCKERFILE_PATH` | `Dockerfile.worker` | Selects the file; service variables are not build arguments. |
| Cron schedule | `0 10 * * *` (UTC: 4 a.m. in Minneapolis in winter, 5 a.m. in summer) | C8-D5. Staging gets the same schedule with the flag off (a clean skip shows as `EXITED` in `railway cron list`; a startup refusal shows as `CRASHED`) and production's is gated until C11 (C8-D9). |
| Start command | none: the image's `CMD` is `python -m agent_worker.main --trigger scheduled` | C8-D4: the flag gates exactly this trigger, so a run Railway starts by itself is a logged skip while the flag is off. |
| Restart policy | Never | A failed run must not be retried into a loop. **Observed November 18, 2026 (C8-U2):** after an exit 1 (a malformed flag) and an exit 2 (a localhost model URL), each run had exactly one container start and one `railway cron list` row: "Never" is honoured. |
| Healthcheck, pre-deploy command | none | It is not a web service, and only the API migrates (C8-D9). |

Variables: `APP_ENV` (`staging` or `prod`), `DATABASE_URL` (the **same** `calendar_<env>` login role as that environment's API),
`MONGODB_URI` and `MONGODB_DATABASE` (`calendar_staging`; `calendar` for production), `MODEL_BASE_URL`, `MODEL_PROVIDER`,
`MODEL_NAME` and `MODEL_API_KEY` (the environment's own DeepInfra key), and, since C9, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY` and `R2_BUCKET` (that environment's own bucket and token; the worker **refuses to start, exit 2, without
all four**, and a skipped scheduled run still checks them, so set them BEFORE merging C9: `c9-r2-snapshots.md` "The ordering
trap"): the values are in the secrets inventory above.
**`FLAG_WORKER_SCHEDULED_RUNS` is not set**, so scheduled runs are off; arm it with exactly `true` **on the worker service, not
the API's** (the API runs no gate). A misspelled or malformed `FLAG_*` value makes the container fail at startup, which on a
cron service shows on its next run, not at deploy (`Settings` refuses it, C3.1-D12).

### `worker-shell`: the idle service that gives a console (staging only; C8-U8, C8-U9)

A cron service has **no running container between runs, so its Console tab has nothing to open** (C8-U8, observed November 18,
2026; `railway ssh` needs a running instance too). So staging has a second service, **`worker-shell`**: the same repository,
branch `main`, Root Directory `apps/api` and `RAILWAY_DOCKERFILE_PATH=Dockerfile.worker`, the same variables as `worker`
(eight until C9 added the four `R2_*`; and no flag), **no cron schedule**, and the custom start command `sleep infinity`, which replaces the image's `CMD`. Observed
(C8-U9): it stays **Online** and its Console tab gives a root shell in `/app`. **Not recorded:** what the idle container costs
over a few days (read Railway's usage page and write it here), and whether the variables are Railway reference variables
(`${{worker.NAME}}`) or copies. A merge to `main` redeploys it and ends a run in progress. **Production gets none in C8**
(C8-D15): it would hold production's secrets in a shell with no typed confirmation; that is a C11 decision.

### Starting a run

| How | Where it runs | Use it for |
|---|---|---|
| The cron schedule | Railway's container | The daily run, once the flag is `true` (C11 for production). With the flag off it logs `scheduled run skipped: feature flag worker.scheduled_runs is off`, writes nothing and exits 0. |
| `make worker-hosted ENV=staging\|prod [VENUE=<id>]` | **This machine**, with that service's variables | The quick manual run (C8-D3). It executes the files checked out here, so it refuses unless the tree is clean and `HEAD` is `origin/main` (staging) or `origin/production` (prod), prints the commit, selects the service `worker` (staging) or `worker-prod` (prod), and asks for `production` to be typed for prod. Needs the Railway CLI signed in and `RAILWAY_PROJECT_ID` in the shell (not a secret: Project ID under the project's Settings in the dashboard, or `railway list`). Records `trigger='manual'`; ignores the flag. |
| `worker-shell`'s **Console** tab | Railway's container | A manual run in the real image, on Railway's network (C8-D15): all venues or one (`--venue`). Observed working on staging; the runbook below is what was typed. |
| **Run now** in the dashboard, or `railway cron run -s worker -e staging --yes` (CLI 5.71.0; production's is `-s worker-prod -e production`) | Railway's container | The container's own command, `--trigger scheduled`, **immediately**: with the flag off a logged skip, with it on a real run (observed both). It cannot pass `--trigger manual` or `--venue`. Needs a deploy to be current, so apply staged variable changes with Deploy first. |

**Console runbook** (in `worker-shell`; verified on staging November 18, 2026. Every command names the interpreter and the
directory instead of relying on `PATH` or the image's `ENV`, because a shell's `PATH` is not known to match the image's. The
image still puts its virtual environment on `PATH` and `/app` on `PYTHONPATH`):

```bash
cd /app && /app/.venv/bin/python -m agent_worker.main --help      # proves the image and its libraries
cd /app && nohup /app/.venv/bin/python -m agent_worker.main --trigger manual --venue 3 > /tmp/run.log 2>&1 &
tail -f /tmp/run.log                    # Ctrl-C stops the tail, not the run
```

* `nohup` and `&` so a closed browser tab does not end the run. **The record of a console run is `agent_run`,
  `audit_log` and the Atlas document**; the run's own output is in the file you redirected it to. `make db-shell`
  cannot reach a hosted database: read the results in **Neon's SQL editor** (dashboard, the environment's branch), which needs no
  connection string. `agent_run` has no `status` column; a run is over when `finished_at` is set.
* Check the Atlas cluster is running first: the free cluster pauses after weeks without a connection and has to be resumed
  by hand (C1; C8-D8). The worker's "MongoDB did not answer" message says so on a hosted environment.
* **Dashboard logs look blank.** The worker's JSON lines carry their text in an `event` field, and Railway's log viewer shows `message`,
  so every line appears empty (observed; the CSV export shows the text under `attributes`). Read hosted logs with the CLI:
  `railway logs -p <project> -s worker -e staging --since <UTC time> --until <UTC time>`; `railway cron list -s worker -e staging`
  gives each run's time, status and duration and prints that command. **For production use `-s worker-prod -e production`** (the service names differ, above).
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
