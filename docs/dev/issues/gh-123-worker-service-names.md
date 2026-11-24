# GH-123: `make worker-hosted ENV=prod` cannot find the production worker

**Status:** Code review
**Date:** November 24, 2026
**Scope:** GH-123
**Sources:** GH-123 → https://github.com/arikoinuma/agentic-live-music-calendar/issues/123 (no comments); found by C11 Step 5,
`docs/dev/implementations/c11-go-live.md` (Implementation log)
**Tier:** T1 — one script's behavior changes (which Railway service name it passes), the fix is the one the issue names, and
nothing touches `app/schemas.py`, the API contract, a migration or a repo-wide convention
**Author model:** Claude Sonnet 5.5 (record, fix, tests and docs, November 24, 2026; local session, in a git worktree
of `origin/main` so the shared checkout on `c11-go-live` was never switched)
**Reviewer model:** _(code review round 1: pending)_
**Branch / PR:** `issue-gh-123-worker-service-names` / _(PR link once opened)_

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `GH-123-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`).

## Issues

### GH-123: the script hardcodes the service name `worker` for both environments

**What's wrong.** `apps/api/scripts/hosted_worker.py` has one constant, `SERVICE = "worker"`, and passes it as `railway run
-s worker -e <environment>` for staging and for prod. `docs/dev/environments.md` ("The worker on Railway (C8)", the *Name*
row) says the service "must be called `worker` in each Railway environment". Railway service names are unique across the
project, so creating the production worker on November 24, 2026 (C11 Step 5) was refused with "already exists" (the staging
worker holds `worker`) and the production service was named **`worker-prod`**. `make worker-hosted ENV=prod` therefore runs
`railway run -s worker -e production`, which cannot find its service.

**Evidence** (from the issue): `hosted_worker.py:58` (`SERVICE = "worker"`) and `:151` (the `railway run` argv);
`scripts/tests/test_hosted_worker.py` asserts the `worker` name in the argv; `railway cron list -s worker-prod -e production`
works, and the production worker has run once (a logged skip, flag off).

**Why it matters.** C11 Step 6 (the first real production run) and C11-D9 (manual production runs use the laptop command
and its guards: the typed `production`, a clean tree, `HEAD` at `origin/production`) depend on this command. Without the fix
the only way to run production by hand is a bare `railway run`, which has none of those guards.

**What "fixed" means** (the issue's proposed fix):
1. A per-environment service-name map in the script: `staging` → `worker`, `prod` → `worker-prod`.
2. A test that fails first.
3. Every doc that says "`worker` in each environment" corrected.
4. The fix must reach the `production` branch (the script refuses a production run unless `HEAD` is `origin/production`),
   so after Ari merges it to `main`, a second promotion follows (C11's "Later promotions"). **That promotion is not part of
   this run**: the C11 session handles it, and this run promotes nothing.

**Not in scope** (told by the task): the `c11-go-live` branch and its plan file `docs/dev/implementations/c11-go-live.md`.
Its text that repeats the old name (see "Noticed, not in scope") is left for the C11 session.

## Approach

**Tier T1, with the reason above.** In `hosted_worker.py` replace the single `SERVICE = "worker"` with
`SERVICE_FOR_ENV = {"staging": "worker", "prod": "worker-prod"}`, next to the two maps it joins (`BRANCH_FOR_ENV`,
`RAILWAY_ENV`), and use `SERVICE_FOR_ENV[env]` in the `railway run` argv. The map is keyed by this project's environment
name, like its neighbours; the unknown-environment refusal still comes first, so the lookup cannot raise `KeyError`. The
module docstring's "must be called `worker` in each Railway environment" becomes the two names and the reason (Railway
service names are unique across a project).

**Tests first** (`scripts/tests/test_hosted_worker.py`, "The command that runs"): add one test that `prod` passes
`-s worker-prod -e production` and that staging still passes `-s worker`; it fails against the current script, which passes
`worker` for prod. Add one structural test that every environment `launch` accepts has a service name and that no two
environments share one (the exact mistake Railway refused: two environments cannot both hold `worker`, because the names are
unique across the project), so a third environment added later to `BRANCH_FOR_ENV` without a service name fails a test
instead of a production run. The existing staging test already asserts `worker` and stays as it is.

**Docs.** `environments.md`: the *Name* row of "The service" table (both names, and why), the Railway row of the
environments table (line 17: add `worker-prod`), the "Starting a run" table (production's `railway cron` form), the staging-only
`railway logs` / `railway cron list` lines get "(production: `-s worker-prod -e production`)" where they would otherwise be
copied into production, and the "no worker service yet" sentence in the C8 preface is left as written (it is a dated
status). `notes.md`: one entry (Railway service names are unique across the project; this is how it surfaced).
`alpha-deployment-plan.md` C11 list item "Create production's `worker`": amended to name `worker-prod`. `c8-worker-on-railway.md`:
three rows (D3, the test row, Step 11) get a dated "Amended by GH-123" note; the plan is signed off, so the original text
stays and the amendment is appended, as C9's amendments to C8 are. The C11 plan is untouched (above).

**Verification.** `make check`, `make designation-check BASE=<diff base>`. No migration, no schema change, no Railway
account needed: the tests fake `git` and `railway`. **Local check pending:** none for the code. Whether Railway accepts
`-s worker-prod -e production` is shown by the issue's own `railway cron list -s worker-prod -e production`; the first real
`make worker-hosted ENV=prod` is C11 Step 6, which Ari runs.

## Implementation log

### Round 1

- **Scope:** diff base `b9fc6d8` (`origin/main` at the start of this run, the merge of PR 122). Work is on one commit on
  top of it (pushed before the code review; the review's scope is `b9fc6d8..HEAD`). Files touched:
  `apps/api/scripts/hosted_worker.py`, `apps/api/scripts/tests/test_hosted_worker.py`, `docs/dev/environments.md`,
  `docs/dev/notes.md`, `docs/dev/alpha-deployment-plan.md`, `docs/dev/implementations/c8-worker-on-railway.md` (three
  amendments), and this record. Nothing under `apps/calendar`, no migration, no `schemas.py`.
- **GH-123:** `SERVICE = "worker"` is replaced by `SERVICE_FOR_ENV = {"staging": "worker", "prod": "worker-prod"}`, and the
  `railway run` argv takes `SERVICE_FOR_ENV[env]`. The module docstring's "must be called `worker` in each Railway
  environment" now states the two names and why. **Failed first:** `test_each_environment_selects_its_own_railway_service`
  (`AssertionError: prod … assert 'worker' == 'worker-prod'`) and
  `test_every_environment_the_command_accepts_has_its_own_service_name` (`AttributeError: … no attribute
  'SERVICE_FOR_ENV'`); `uv run pytest scripts/tests/test_hosted_worker.py` was 2 failed, 21 passed before the fix and is
  23 passed after. The existing staging test (`-s worker`) was unchanged and stayed green.
- **Docs corrected:** `environments.md` (the environments table's Railway cell, the *Name* row of "The service", the
  `make worker-hosted` row and the Run now row in "Starting a run", the `railway logs`/`cron list` runbook line, and the C8
  preface's "no worker service yet"); `notes.md` (a new entry, and a pointer from the log-viewer entry);
  `alpha-deployment-plan.md` (the C11 checklist item that creates production's worker); `c8-worker-on-railway.md` (D3,
  the `hosted_worker` test row and Step 11, each amended in place and dated, original text kept).
- **Departures from the approach:** none in the code. In the Approach I said the C8 plan gets "three rows" amended and
  the `make worker-hosted` row of `environments.md` was not listed; both are now done. `c11-go-live.md` is untouched, as
  the task required.
- **Verification** (worktree of `origin/main`, `.env` copied from `.env.example`):
  - `make check`: ruff check and format-check, eslint, mypy and tsc **passed**; pytest **1794 passed, 19 skipped**;
    the calendar's vitest **631 passed**; `contract-check` passed. **`make e2e` did not run its tests**: its `next build`
    stopped with `SecurityFatalError: Your version of Next.js is affected by a known security vulnerability` (Next 16.4.1,
    advisory lookup at `registry.npmjs.org`). That is not caused by this diff (no JS file is touched; CI on `main` passed
    this afternoon at 20:00Z with the same `next` version, so the advisory is newer than that run). Treat the e2e check
    as **not run here**; CI on the PR is the check for it.
  - `make designation-check BASE=b9fc6d8`: passes (re-run after the commit; see Round 1's end below).
  - **Local check pending:** the first real `make worker-hosted ENV=prod`, which is C11 Step 6 and Ari's. It needs
    `origin/production` to contain this change (a second promotion) and the Railway CLI signed in. The tests fake the CLI,
    so they prove the argv (`-s worker-prod -e production`), not that Railway accepts it; the issue's own
    `railway cron list -s worker-prod -e production` is the evidence that the name exists.
- **Where to look hardest:** (1) that the doc edits did not leave a place that still says production's service is `worker`
  (the plan's grep was `-s worker`, `` `worker` `` and "each Railway environment"); `worker-shell` is staging-only and
  correctly keeps its name. (2) The second test's `set(SERVICE_FOR_ENV) == set(BRANCH_FOR_ENV)` pins a coupling between two
  maps in one module; is that over-specified or the right guard? (3) The `make worker-hosted` output names the commit and
  the Railway environment but not the service; I left it so, to keep the change small.

## Code review
