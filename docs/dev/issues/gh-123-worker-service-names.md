# GH-123: `make worker-hosted ENV=prod` cannot find the production worker

**Status:** PR open
**Date:** November 24, 2026
**Scope:** GH-123
**Sources:** GH-123 → https://github.com/arikoinuma/agentic-live-music-calendar/issues/123 (no comments); found by C11 Step 5,
`docs/dev/implementations/c11-go-live.md` (Implementation log)
**Tier:** T1 — one script's behavior changes (which Railway service name it passes), the fix is the one the issue names, and
nothing touches `app/schemas.py`, the API contract, a migration or a repo-wide convention
**Author model:** Claude Sonnet 5.5 (record, fix, tests and docs, November 24, 2026; local session, in a git worktree
of `origin/main` so the shared checkout on `c11-go-live` was never switched)
**Reviewer model:** Claude Opus 5.5 (code review round 1, November 24, 2026)
**Branch / PR:** `issue-gh-123-worker-service-names` / _(PR link once opened)_

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `GH-123-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`).

## Issues

### GH-123: the script hardcodes the service name `worker` for both environments

**What's wrong.** `apps/api/scripts/hosted_worker.py` has one constant, `SERVICE = "worker"`, and passes it as `railway run
-s worker -e <environment>` for staging and for prod. `docs/dev/environments.md` ("The worker on Railway (C8)", the *Name*
row) says the service "must be called `worker` in each Railway environment". Creating the production worker on November 24,
2026 (C11 Step 5) as a second service named `worker` was refused with "already exists" (the staging worker holds `worker`),
so the production service was named **`worker-prod`** (the issue puts it as "service names are unique across the project";
code review CR1-1 narrowed the docs to what was observed). `make worker-hosted ENV=prod` therefore runs
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
module docstring's "must be called `worker` in each Railway environment" becomes the two names and the reason (a second service named `worker` was refused).

**Tests first** (`scripts/tests/test_hosted_worker.py`, "The command that runs"): add one test that `prod` passes
`-s worker-prod -e production` and that staging still passes `-s worker`; it fails against the current script, which passes
`worker` for prod. Add one structural test that every environment `launch` accepts has a service name (and a Railway
environment name), so a third environment added later to `BRANCH_FOR_ENV` without them fails a test instead of a production
run. (As first written it also asserted that no two environments share a name; CR1-1 removed that half, which stated a
Railway rule nobody had observed.) The existing staging test already asserts `worker` and stays as it is.

**Docs.** `environments.md`: the *Name* row of "The service" table (both names, and why), the Railway row of the
environments table (line 17: add `worker-prod`), the "Starting a run" table (production's `railway cron` form), the staging-only
`railway logs` / `railway cron list` lines get "(production: `-s worker-prod -e production`)" where they would otherwise be
copied into production, and the "no worker service yet" sentence in the C8 preface is left as written (it is a dated
status). `notes.md`: one entry (a second service named `worker` was refused; this is how it surfaced).
`alpha-deployment-plan.md` C11 list item "Create production's `worker`": amended to name `worker-prod`. `c8-worker-on-railway.md`:
three rows (D3, the test row, Step 11) get a dated "Amended by GH-123" note; the plan is signed off, so the original text
stays and the amendment is appended, as the dated amendments in `alpha-deployment-plan.md` are. The C11 plan is untouched (above).

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
  the `hosted_worker` test row and Step 11, each with the original text kept and a dated "Amended by GH-123" clause appended: CR1-2 found the first draft had rewritten two
  of the three in place, and Round 2's fixes restored them; Step 8a got a clause too, CR1-3).
- **Departures from the approach:** none in the code. Two doc edits the Approach did not plan: the C8 preface sentence in
  `environments.md` ("no worker service yet") was edited, not left as written, because it would otherwise read as current
  after Step 5; and `notes.md`'s log-viewer entry got a one-line pointer, so a reader who copies its `-s worker` command
  for production is sent to the right name. `c11-go-live.md` is untouched, as the task required.
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

### Round 1 (Claude Opus 5.5, November 24, 2026)

**Scope.** Implementation log Round 1: `git diff b9fc6d8..HEAD` (one commit, `f82016f`), seven files:
`apps/api/scripts/hosted_worker.py`, `apps/api/scripts/tests/test_hosted_worker.py`, `docs/dev/environments.md`,
`docs/dev/notes.md`, `docs/dev/alpha-deployment-plan.md`, `docs/dev/implementations/c8-worker-on-railway.md` and this record.
`docs/dev/implementations/c11-go-live.md` was out of scope for this run, so I read it only (from the `c11-go-live` branch, with
`git show`, for its Step 5(a) to 5(c) observations) and do not report its old-name text.

**What was checked, and how.**
- Read `AGENTS.md`, `docs/dev/issues/README.md`, this record in full, the FastAPI style guide's Anti-patterns table (none
  applies: no routes, no async, no settings), and the full diff.
- **Fail-first, CONFIRMED:** in a throwaway `git worktree` at `b9fc6d8` (since removed), with the new
  `test_hosted_worker.py` dropped in and `.env` copied from `.env.example`: **2 failed, 21 passed**
  (`AssertionError: prod … assert 'worker' == 'worker-prod'`, and `AttributeError: … no attribute 'SERVICE_FOR_ENV'`),
  which matches the log. On `HEAD`: `uv run pytest scripts/tests/test_hosted_worker.py` gives **23 passed**.
- **Python half of `make check`, CONFIRMED on `HEAD`:** `ruff check` and `ruff format --check` clean, `mypy` clean (174
  files), `REQUIRE_DB=1 uv run pytest` **1794 passed, 19 skipped**; `make contract-check` current;
  `make designation-check BASE=b9fc6d8` exits 0 with no bare designations. Not run: eslint, tsc, vitest (no JS file in the
  diff) and `make e2e` (the known `next build` advisory stop, unrelated to this diff, per the task).
- **The code:** `launch` refuses an unknown environment against `BRANCH_FOR_ENV` (`hosted_worker.py:113`) before
  `SERVICE_FOR_ENV[env]` is read (`:155`), so the lookup cannot raise `KeyError` for any accepted environment as long as
  the keys match, which the second test pins. The argv change is the only behavior change. The fix is the one GH-123 names,
  and T1 is the right tier (no contract, migration, security design or convention).
- **Stale names:** `git grep` across tracked files (excluding `c11-go-live.md` and this record) for `-s worker`,
  `` `worker` `` on lines that mention production, and "each Railway environment". No doc still gives `-s worker -e
  production` as a command. The remaining production-`worker` wording is in finding 3.
- **Doc claims against the code:** `environments.md:519` and `:554` (the *Name* row and the `make worker-hosted` row) match
  `SERVICE_FOR_ENV` and the argv; `notes.md:887–895` matches the code's history; the test's expected names match C11 Step
  5(c)'s observed `railway cron run -s worker-prod -e production`. The general rule the docs state about Railway is
  finding 1.
- **The C8 amendments:** compared each of the three rows before and after (finding 2), and searched the C8 plan for the
  "C9's amendments to C8" the Approach cites as the pattern.
- **Local check pending:** correctly left as pending (the first real `make worker-hosted ENV=prod` is C11 Step 6), not
  reported as verified.

**Counts:** 0 blocker, 2 should-fix, 4 nit. **Verdict: proceed after fixes.** The code and its tests are right. The
should-fix items are about what the docs teach: a Railway rule stated more broadly than what was observed, and two C8 rows
that were rewritten rather than amended.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The docs state a broader Railway rule than was observed.** What C11 Step 5(a) observed is narrow: creating a *new, second* service named `worker` (for production) was refused because the project already has a service of that name. The diff turns this into a general rule that two environments cannot share a worker name: "the two cannot share one" (`hosted_worker.py:27–28`), "unique across the whole project, not per environment" (`:58–61`, `environments.md:519`), "A new environment's worker needs its own name" (`environments.md:519`), "The same rule applies to a future environment's worker" (`notes.md:894`), and the second test calls name-uniqueness "the rule Railway enforces" (`test_hosted_worker.py:138`). But this project's own API looks like **one** service with an instance in each environment: the staging API is the Railway service `kind-spontaneity` (`environments.md:82`), and its domain `kind-spontaneity-staging.up.railway.app` (`environments.md:17`) follows Railway's `<service>-<environment>` pattern. That is the model C8-D3 assumed for `worker`. If it holds, the existing `worker` service could have been added to the production environment under the same name, and "needs its own name" is wrong as a rule. | PLAUSIBLE (no Railway access here; reasoned from `environments.md:17`, `:82` and C11 Step 5(a)'s wording, read with `git show c11-go-live:docs/dev/implementations/c11-go-live.md`). The code itself is CONFIRMED right for the services that exist today. | `notes.md` is where the repo keeps lessons that last, so a wrong rule there spreads. A future dev worker, or a production `worker-shell`, would be created as yet another separately named service and added to the map when it could have been an environment instance of the existing service. The uniqueness assertion would also block a valid setup, one `worker` service across environments, and its comment would say Railway forbids it. **Fix:** say what was observed: creating a new service named `worker` was refused because the name belongs to the project's existing (staging) `worker` service, so production's worker is a separate service, `worker-prod`. Mark as unverified whether a service can instead have an instance in each environment, as the API seems to. In the test, describe the uniqueness half as this project's current setup, not as Railway's rule (or drop that half). Leave the code unchanged. Whether to keep `worker-prod` or move production onto `worker` is not something this record has to decide. | **Fixed.** The docs now say only what was observed: creating a second service named `worker` was refused, so production's is its own service, `worker-prod`; whether one service could instead have an instance per environment (as the API seems to) is marked not tried. Reworded in `hosted_worker.py` (docstring and the `SERVICE_FOR_ENV` comment), `environments.md` (*Name* row), `notes.md` (entry retitled), `alpha-deployment-plan.md`, the C8 D3 clause and this record. The uniqueness half of the structural test is removed (it would have blocked a valid one-service setup), and the first test's comment no longer cites a Railway rule. Code unchanged. |
| 2 | should-fix | **Two of the three C8 amendments rewrite the signed-off text, where the record says they were appended and dated.** The Approach (`:69–70`) says each row gets "a dated 'Amended by GH-123' note; … the original text stays and the amendment is appended". The log (`:98`) says "each amended in place and dated, original text kept". D3 (`c8-worker-on-railway.md:61`) does this correctly: the original `-s worker` stays, followed by a bold, dated "amended by GH-123, November 24, 2026" clause. **The test row (`:90`)** replaces "`-s worker`" with "`-s worker` (staging) or `-s worker-prod` (prod; GH-123)", with no date and no "amended" marker, so it reads as if C8 specified `worker-prod`. **Step 11 (`:112`)** replaces "Create the production `worker` service the same way" with "Create the production worker service the same way **but named `worker-prod`** …". The name C8 planned is gone, and there is no date or "amended" marker (only "C11 Step 5, GH-123"). Also, the Approach's precedent "as C9's amendments to C8 are" does not exist: searching `c8-worker-on-railway.md` for "mended" finds only this diff's D3 clause, C8's own "Done when (amended from the deployment plan by D1)" (`:115`) and a sign-off note about the deployment plan's checklist (`:298`). The dated-amendment pattern is `alpha-deployment-plan.md`'s (for example `:352`, "*(Amended by C9-D3, November 18, 2026: …)*"). | CONFIRMED (`git diff b9fc6d8..HEAD -- docs/dev/implementations/c8-worker-on-railway.md`; the search above). | A signed-off plan is the record of what was decided at the time. Two of its rows now give a decision C8 never made, and the Implementation log describes the change inaccurately to the person signing off. **Fix:** in both rows, restore the original wording and append a "*(Amended by GH-123, November 24, 2026: production's service is `worker-prod`; …)*" clause, as D3 does. In the Approach, point to `alpha-deployment-plan.md`'s amendments rather than "C9's amendments to C8". Make the log's line match. | **Fixed.** `c8-worker-on-railway.md` rows 90 (test row) and 112 (Step 11) restored to the signed-off text from `b9fc6d8`, each with a dated "*(Amended by GH-123, November 24, 2026: …)*" clause appended, as D3 does. The Approach now cites `alpha-deployment-plan.md`'s amendments as the pattern, and the log line is accurate. |
| 3 | nit | **Some places still say production's worker is the cron `worker`, or plan a production `worker-shell` under that name.** C8 Step 8a (`c8-worker-on-railway.md:109`): "if (a) held, its cron `worker` (Step 11) already has the same console", where "its" means production's. C8 D15 (5) (`:63`) and the open C11 checklist item `alpha-deployment-plan.md:378` ("Decide whether production gets an idle `worker-shell`") name a production `worker-shell`, which the same refusal would block. `notes.md:894` says so, but the checklist where Ari will act on it does not. | CONFIRMED (`git grep` for the backticked name `worker`, filtered to lines that mention production; `c11-go-live.md` excluded by scope). | Someone following the C11 checklist creates `worker-shell` in production, is refused as at Step 5, and has to rediscover the reason. **Fix:** a dated amendment clause on Step 8a, and in the `alpha-deployment-plan.md:378` item, "(a production shell needs its own name too, see `notes.md`)". Word both to fit finding 1's resolution. | **Fixed**, except D15. Step 8a (`c8-worker-on-railway.md`) got a dated amendment clause (production's cron service is `worker-prod`; a production `worker-shell` would probably need its own name: unverified). The open C11 checklist item in `alpha-deployment-plan.md` and `notes.md` say the same. C8 D15 (5) is left as written: it decides whether production gets a shell, not what it is called, and the checklist where Ari acts on it now carries the warning. |
| 4 | nit | **The "Departures from the approach" bullet lists the wrong things.** It names "three rows" of the C8 plan (which the Approach already planned) and the `make worker-hosted` row. It leaves out two real departures: the C8 preface sentence in `environments.md:505`, which the Approach (`:66–68`) said would be "left as written" but was edited ("when this was written … it is `worker-prod` since C11 Step 5"), and the pointer added to `notes.md`'s log-viewer entry (`notes.md:843`), where the Approach planned "one entry". | CONFIRMED (the record's `:64–70` against `:94–101` and the diff). | Small, but the log is the handoff to the reviewer and to Ari's sign-off, and these two edits are exactly what it should flag. **Fix:** list the preface edit and the `notes.md` pointer as departures, each with a reason, and drop "three rows". | **Fixed.** The log's Departures now list the `environments.md` C8-preface edit and the `notes.md` pointer, each with its reason, and drop "three rows". |
| 5 | nit | **The structural test pins `SERVICE_FOR_ENV` against `BRANCH_FOR_ENV` but leaves out `RAILWAY_ENV`, which `launch` also indexes by environment** (`hosted_worker.py:143`, `:155`), so it has the same `KeyError`-at-launch hazard. On the log's question (2): pinning the maps to each other is the right guard, not over-specified. It is cheap, it catches the real mistake of adding an environment to one map and forgetting another, and the comment says why. | CONFIRMED (reading `hosted_worker.py:56–62`, `:113–155` and `test_hosted_worker.py:135–143`). | A third environment added to `BRANCH_FOR_ENV` and `SERVICE_FOR_ENV` but not to `RAILWAY_ENV` passes this test and fails at launch, which is the failure the test says it prevents. **Fix:** `assert set(SERVICE_FOR_ENV) == set(BRANCH_FOR_ENV) == set(RAILWAY_ENV)`, with the comment updated. | **Fixed.** `test_every_environment_the_command_accepts_has_a_branch_a_railway_environment_and_a_service` asserts `RAILWAY_ENV` and `SERVICE_FOR_ENV` both have exactly `BRANCH_FOR_ENV`'s keys (`test_hosted_worker.py`). Passes; it is a guard with no behavior change, so there was no failing state to show. |
| 6 | nit | **Optional (the log's question (3)): the line printed before the production prompt does not name the service.** `hosted_worker.py:143` prints the commit and the Railway environment, and the guards then ask Ari to type `production`. Adding `service {SERVICE_FOR_ENV[env]!r}` to that line would show `worker-prod` on screen before he confirms. | CONFIRMED (reading `:143–150`). | The impact is low: a wrong name makes `railway run` fail before the worker starts. But the service is now the one selector that differs per environment and is not printed, and the cost is one f-string plus one assertion on `said` in the existing prod test. Leaving it out is a reasonable choice. | **Fixed.** The line printed before the run (and so before the typed `production`) now ends `…Railway environment 'production', service 'worker-prod'.` (`hosted_worker.py`). Test first: an assertion on that line was added to `test_each_environment_selects_its_own_railway_service`; with the old `hosted_worker.py` restored it failed (1 failed, 22 passed), with the change 23 passed. |

**Rejected:** none.

**Test suite after the fixes** (worktree of `origin/main`): `uv run pytest scripts/tests/test_hosted_worker.py` 23 passed. Full
`make check`: ruff, mypy, tsc and eslint pass; pytest **1794 passed, 19 skipped**; vitest 631 passed; `contract-check` passed;
`make e2e` stops at `next build` with the same Next.js security-advisory error as before the fixes (unrelated to this diff,
**not run here**; the PR's CI is its check). `make designation-check BASE=b9fc6d8` passes.
