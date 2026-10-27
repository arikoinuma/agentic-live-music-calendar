# Hosted-state re-validation (C1)

The result of milestone C1 in `alpha-deployment-plan.md` §6: what the hosted
services actually look like, checked by hand on the dates below, with secrets
redacted. Each row is **Verified** (observed), a **Finding** (observed, and it
changes something), or **Open** (not checked yet). The plan's §1.1 and §1.2 list
what was assumed before this file existed.

Never paste a connection string or password here. For Neon, reach the database
with a one-command override (`DATABASE_URL=… uv run alembic current`), never by
editing `apps/api/.env`, and use the `postgresql+asyncpg://` prefix without the
`sslmode` / `channel_binding` query parameters (`docs/dev/notes.md`).

## Summary

| Provider | Status | Result |
|---|---|---|
| Neon | Finding | Branch was archived for inactivity; it holds no tables and no migrations |
| Atlas (MongoDB) | Finding | Cluster had paused and was restarted by hand; one user; M0 limits recorded |
| Railway | Verified, cost pending | Hobby plan, one environment, healthy; variables are `DATABASE_URL` and `MODEL_NAME`; usage too new to project |
| Vercel | Finding | Production has `API_BASE_URL`; Preview is disabled with no variables |
| GitHub ruleset | Verified | `main` requires all five checks |
| DeepInfra | Verified | Account created |
| Cloudflare (R2) | Deferred | Not needed until C9 |
| Domain | Deferred | Not chosen (Dep-D7); everything proceeds on `*.vercel.app` |

## Neon

Checked October 22, 2026.

- **Branch state:** the branch showed as archived due to inactivity. The first
  connection from the laptop succeeded and woke it.
- **Migrations:** `alembic current` printed nothing after its two `INFO` lines,
  so no revision is recorded. `env-setup.md` had left Neon on the first
  migration; in fact it is on none.
- **Tables:** `select count(*) from information_schema.tables where
  table_schema = 'public'` returned `0`. Per-table row counts are therefore
  moot: there are no tables.
- **Consequence:** the production API's `/health/db` passing says nothing about
  the schema, because it only runs `SELECT 1`. C2's pre-merge step has to run
  `alembic upgrade head` and the seed against the right Neon branch before the
  routers move onto Postgres (`alpha-deployment-plan.md` §5.2, C2). Dep-D12's
  expectation of "an empty calendar until a worker run populates Neon" holds,
  with the added fact that there is no schema at all yet.
- **Credentials:** the database password was pasted into a chat session during
  this check. Reset it in Neon (Roles → reset password) before C2 puts data
  there, then update Railway's `DATABASE_URL`.
- **Open:** compute hours used, branch count and the plan's limits (free tier),
  and whether idle pooled connections keep the compute awake (Dep-D9).
- **C2, October 27, 2026 (reported by Ari; `c2-api-reads-database.md`, step 10):** the production Neon
  branch was migrated and seeded with the one-command override from the C2 branch (`alembic upgrade head`,
  then `scripts.seed`), and the seed data is present. This branch's API, run locally against Neon, answered
  the route checks as expected: the metro and the seeded venues, and empty shows, artists and months (the
  empty calendar Dep-D12 accepts until a worker run). The password reset from the Credentials note above is
  reported done; whether Railway's `DATABASE_URL` was updated to match is not recorded here. Not recorded:
  the `alembic current` revision and the venue count, which the C2 plan expects to be `67609c405218` and
  four (The White Squirrel Bar, 7th St Entry, Mortimer's, The Terminal Bar).

## Atlas (MongoDB)

Checked October 22, 2026.

- **Cluster state:** Finding. The M0 cluster had paused and had to be restarted
  by hand; it is running now. This confirms the plan's worry (§1.2, Risks): a
  worker's first hosted run after a quiet spell would fail on connect. C3
  checks it again, and C8's plan has to say what keeps it from pausing or how a
  run copes.
- **Users:** one database user, `arikoinuma_db_user`.
- **Free-tier limits (M0):** 512 MB storage, shared RAM and vCPU, 500 maximum
  connections, no auto-scaling, no backups unless added at $3.00/month, no
  uptime SLA. Flex (from $0.011/hour, capped at $30/month, 5 GB) is the next
  tier up and not needed. Dep-D10's database-per-environment on one cluster
  fits if the total stays under 512 MB (raw staging documents only, no page
  snapshots; those go to R2 in C9).

## Railway

Partly checked October 22, 2026: signed in, subscribed to the $5 Hobby plan, one
environment (Production). A second environment can be added with variables
copied from Production; not done yet, because it would change the usage being
measured for the cost finding.

- **Status:** Verified. The service is Active and deployed the latest changes.
  The CLI was not used; these were read from the dashboard.
- **Variables:** Verified. Two exist in Production, `DATABASE_URL` and
  `MODEL_NAME` (values not recorded). No `MONGODB_URI`, which a hosted worker
  needs (§1.1, "Worker and Mongo"), and no shared secret (C10).
- **Healthcheck path:** Verified empty. Railway isn't polling the API, so
  nothing on a timer keeps Neon awake from that side.
- **Health:** Verified. `/health` and `/health/db` both returned the success
  response. `/health/db` only runs `SELECT 1`, and Neon has no tables
  (see Neon above), so it is not evidence of a usable schema.
- **Usage:** the billing period is October 22 to November 22, started today.
  Current usage is $0.02 ($0.0186 for the `agentic-live-music-calendar-api`
  project) against $5.00 included, estimated bill $0.02. This is a few hours of
  an idle API, so it **cannot be projected yet**: re-read it after several days
  and take the daily rate. The Hobby plan includes up to 8 GB RAM, 8 vCPU and
  100 GB shared disk.
- [ ] Re-read usage after a few days, with "Show Breakdown" open, to see which
      resource (memory, CPU, network) the idle API is spending on
- [ ] Whether an idle service can sleep, and what a second environment's service
      adds (an always-on API per environment; not verified)

## Vercel

Partly checked October 22, 2026: Preview and Development environments are
available (the plan allows no custom ones, as §1.1 says) but not configured and
have no domain.

- **Production:** Verified. `API_BASE_URL` is set.
- **Preview:** Finding. No variables are set and the environment is disabled.
  This matches §1.1's diagnosis that every preview build failed on a missing
  `API_BASE_URL`. C3 sets it for Preview.

## GitHub

- **Verified.** The `main` ruleset ("Basic Protection", 25204705) now requires
  all five checks: Python, JS, Contract, E2E and Designations. The first save
  attempt on October 22, 2026 did not take because the browser session was not
  fully signed in to GitHub; the second did (updated 22:36, read back with
  `gh api repos/<owner>/<repo>/rulesets/25204705`). It still has no `production`
  branch rule; that is C3's (Dep-D8).

## Free-tier limits

- **Neon (Free plan, per project):** 1 GB storage, autoscaling to 2 CU,
  **100 compute hours a month**, 10 branches. The Build plan ($10/month) has
  always-on compute, 250 compute hours and 5 GB.
- **Atlas M0:** see Atlas above.
- **Railway Hobby:** $5.00 usage included, 8 GB RAM, 8 vCPU, 100 GB shared disk.
- **R2:** deferred to C9.
- **Dep-D9's open question (idle connections): Verified, October 22, 2026.**
  100 compute hours is about four days of one always-on compute at 1 CU, so
  it mattered whether the API's pooled asyncpg connections keep Neon's compute
  awake. They don't. After a `/health/db` call on the Railway API, Neon's
  Monitoring page showed compute active for about four minutes and then
  inactive again, the same shape as the earlier bursts (about three minutes each
  after the `alembic` check and the SQL editor), while the API stayed deployed
  with its pool. Allocation during a burst was 0.25 CU, using about 0.01 vCPU.
  If Neon counts compute hours as CU times hours, 100 hours is about 400 hours
  of wall-clock time at 0.25 CU, so the "four days" above is the 1 CU worst case,
  not what this branch allocates; confirm that on Neon's usage page. Compute hours are
  therefore spent only on real queries, so idle environments cost nothing from
  the 100 hours. Not yet known: how many hours a daily worker run uses, and
  whether anything periodic (a Railway health check, a Vercel prerender)
  touches the database and keeps waking it. Read the compute-hours meter after
  a day to see the baseline.

## Cost finding (Dep-D9)

Not written yet. It needs the Railway usage numbers and Neon's limits above.
