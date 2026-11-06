# PQR1-2: documentation cleanup

**Status:** PR open
**Date:** November 6, 2026
**Scope:** PQR1-2, PQR1-3 (Ari named it "a documentation cleanup")
**Sources:** both in `docs/dev/review/2026-11-06-python-code-quality-review.md`, §3 Details rows PQR1-2 and PQR1-3 (also
§7 step 1, the first-impression pass)
**Tier:** T0 — a comment-only pass (syntax trees compared before and after) plus a new README; no code behavior changes
**Author model:** Claude Opus 5.5 (record, comment pass and README, November 6, 2026; cloud session)
**Reviewer model:** Claude Sonnet 5.5 (code review round 1, November 6, 2026)
**Branch / PR:** `claude/happy-knuth-edh3br` (designated by the cloud session, restarted from `main` after PR 93 merged; a fast-forward) / PR link once opened

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `PQR1-2-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`).

## Issues

### PQR1-2: tutorial scaffolding and stale "not yet" comments in the most-read files

**What's wrong** (the review's row, checked against the code at the diff base). Comments addressed to a learner, or no longer
true, in:
- `app/main.py`: the router comment says the routes exist "before the database does" (they've read the DB since C2), and
  `health_db` has a numbered "Steps:" tutorial ending "You don't need to catch exceptions yet".
- `app/config.py`: "declare a field named `database_url`…", "Use SettingsConfigDict(env_file=…)", and "instantiate the
  class once at module load time, e.g.:".
- `agent_worker/state.py`: the Pydantic-vs-TypedDict note ends "reconsider if it turns out awkward once you're actually
  wiring add_node… in the next step", and the `venue_name` note says "The worker doesn't read the database yet (A4/A5)".
  `agent_worker/main.py` has read the venue row and passed these fields in since then.
- `app/schemas.py`: the module docstring says "No route returns them yet".
- `app/routers/venues.py`: a lecture on `is None` vs `== "None"`.
- `app/routers/common.py`: "Worth knowing as a general Python point".

**What "fixed" means:** one comment-only pass, following the step-4 procedure for closed `TODO(Ari)` gaps. Keep the
*why*, drop the instructions and the history. Verify with a syntax-tree comparison, then `make check`.

### PQR1-3: `apps/api/README.md` is empty

**What's wrong:** `wc -c apps/api/README.md` gives 0, and `pyproject.toml` declares it as the package readme. It's the
first page a visitor to `apps/api/` sees on GitHub.

**What "fixed" means:** a short README covering what the two halves are (`app/`, `agent_worker/`), how to run, test and
check them, and links to `AGENTS.md` and `docs/`.

## Approach

T0. Rewrite each flagged comment as a plain why-comment in its neighbours' style, verified by a docstring-free AST dump
of all six files before and after (byte-identical). Write the README from the Makefile, `pyproject.toml` and
`apps/api/AGENTS.md`, so every command in it is one that exists. No `TODO(Ari)` gaps, and no code changes.

## Implementation log

### Round 1

- **Scope:** diff base `2b1b8f760a9bedde01953b72df8ddaec3ddf283e` (`main` after PR 93 merged), working tree. Files:
  `app/main.py`, `app/config.py`, `agent_worker/state.py`, `app/schemas.py`, `app/routers/venues.py`,
  `app/routers/common.py`, `apps/api/README.md` and this record.
- **Failed first** (the check that shows the problem): a `grep` for the nine flagged phrases found all nine at the base
  (`Steps:`, "You don't need to catch", "stub routes exist before", "declare a field named", "instantiate the class
  once", "reconsider if it turns out", "doesn't read the database yet", "certainly not", "Worth knowing as a general").
  The schemas.py phrase wraps across a line, so it was confirmed by reading the file. `wc -c README.md` gave 0. After the
  pass, the same grep finds none.
- **PQR1-2, what changed** (comments only):
  - `main.py`: the router comment now says why every route appearing in `/openapi.json` matters (`make types`). The
    `health_db` tutorial is two sentences on why a failure is deliberately left to become a 500.
  - `config.py`: the `model_config` comment states the precedence (real environment variables over `.env`) and why the
    path is relative. `database_url` says why it has no default. The closing comment says why there is one shared instance.
  - `state.py`: the Pydantic-vs-TypedDict note keeps its reasoning and drops "reconsider… in the next step". The
    `venue_name` note now names `agent_worker/main.py` as what reads the row.
  - `schemas.py`: the module docstring says the routes return these models, and how they reach the frontend's types and fixtures.
  - `venues.py`: the 404 comment says why (the declared `responses`) and keeps the type-narrowing point.
  - `common.py`: the annotation comment keeps the mypy reason (dict invariance) and drops "worth knowing".
- **PQR1-3, what changed:** a new `apps/api/README.md` covering what's in the directory (a table of `app/`,
  `agent_worker/`, `model_eval/`, `migrations/`, `scripts/`), running it, testing and checks, and what to read next.
  Every command in it exists in the root `Makefile`.
- **Departures from the approach:** none.
- **Verification:**
  - Comment-only pass: a docstring-free `ast.dump` of the six files is byte-identical before and after (`cmp`: identical).
  - `make check`: exit 0. ruff clean; mypy clean (156 files); pytest 1280 passed, 20 skipped; vitest 525 passed; e2e 107 passed.
  - `make designation-check BASE=2b1b8f7`: clean.
  - Committed as work in progress before this review, so the scope is the commit range `2b1b8f7..HEAD`.
- **Noticed, not in scope:**
  - The root `Makefile`'s `setup` help text says "install deps, start Postgres, migrate" but the target also seeds
    (found through CR1-3). A one-line fix for the same follow-up.
  - `apps/api/AGENTS.md` still says `agent_worker/` imports "the ORM models once A1 lands" (A1 landed long ago).
    That's a stale "not yet" in a doc rather than in code, and it fits a follow-up docs pass.
  - `app/main.py` still has no module docstring, and the health routes lack return types. Those are PQR1-6 and PQR1-15,
    deliberately left for their own run, since adding a docstring or an annotation isn't comment-only.
- **Where to look hardest:** whether any rewritten comment now says something untrue (for example the `.env` precedence
  claim in `config.py`), and whether the README's commands and descriptions match the Makefile and the code.

## Code review

### Round 1

**Scope.** Code review of Implementation log Round 1: commit range `2b1b8f7..HEAD`, eight files (six comment edits in
`apps/api`, the new `apps/api/README.md`, this record). Tier T0 is right: no code behavior, schema or convention changes.

**Checked, and how.**
- Re-ran the comment-only check independently: a docstring-free `ast.dump` of the six Python files at `2b1b8f7` against
  the working tree, run from a script in the scratchpad. All six are identical (CONFIRMED). The log's claim holds.
- Read every rewritten comment against the code it sits on. `config.py`: real environment variables over `.env` is
  pydantic-settings' documented precedence (PLAUSIBLE, not run). `state.py`: `agent_worker/main.py` does read the venue
  row and metro timezone and pass them in (`load_venues`, `Metro.timezone`; CONFIRMED). `schemas.py`: the "routes return
  them" claim is true. `venues.py`: `responses=NOT_FOUND` is on the route (CONFIRMED). `common.py`: the invariance claim is
  correct.
- README against the repo: every `make` target (`setup`, `api`, `seed`, `worker`, `check`, `test`, `db-up`, `VENUE=`)
  exists in the `Makefile`; `help` exists; MongoDB is in `docker-compose.yml`; `requires-python >=3.13`; `.env.example`
  exists; `REQUIRE_DB=1` is what makes `make test` refuse skipped DB tests; the pipeline order matches `graph.py`
  (CONFIRMED). All `scripts/` descriptions match the files present.
- `make designation-check BASE=2b1b8f7`: clean (CONFIRMED). I did not rerun `make check`; the log's result is the
  author's and the diff has no code change, so I take the AST result as the evidence that matters.
- Working tree clean apart from this round.

**Counts.** 0 blocker, 0 should-fix, 3 nit. **Verdict: proceed** (the nits are optional).

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| CR1-1 | nit | The README says `app/` "never imports from" `agent_worker/`. That is true of production code only. `app/tests/test_staging_is_write_only.py:17` imports `agent_worker.staging`. The source rule (`apps/api/AGENTS.md:12-13`) is stated the same loose way, so this copies it, but a README is where a first-time reader takes it literally. | `apps/api/README.md` table row for `agent_worker/`; `grep -rn agent_worker apps/api/app` shows the test import. CONFIRMED. | A reader who greps finds a counterexample and distrusts the rest. Saying "`app/`'s non-test code never imports it" avoids that. | **Fixed.** The README row now says production code in `app/` never imports `agent_worker/`, and that one test in `app/tests/` does, to check staging. |
| CR1-2 | nit | Several new lines run well past the 120-column wrapping used elsewhere in the touched files: the README table rows, the `.env` paragraph (136 characters), the "Read next" architecture bullet (135), and the `schemas.py` docstring line ending "...reasoning behind the shapes." (127). The `schemas.py` docstring now has one long line after short wrapped ones. | `git diff -U0 2b1b8f7..HEAD -- apps` filtered for lines over 121 characters. CONFIRMED. | No functional effect and ruff does not flag it (`pyproject.toml` sets no `line-length` rule that fires). Only a wrapping inconsistency in a pass whose point is polish. Table rows are fine to leave long. | **Fixed** for prose. The `.env` paragraph and the "Read next" bullet are wrapped at 120 columns, and the `schemas.py` docstring line is rewrapped (the AST dump is still identical). The README table rows stay long, because a Markdown table row can't wrap. |
| CR1-3 | nit | The README's Running section says `make setup` installs dependencies, starts Postgres and migrates, but the Makefile's `setup` also runs `make seed` (`Makefile:38`), and the README then lists `make seed` as a separate step after it. A new reader will think they must run it. | `Makefile:31-38`, README "Running it" code block. CONFIRMED. | Harmless, since `seed` is safe to re-run (Makefile help text), but the README's own comment on `make setup` is incomplete, and it is the one command a new contributor runs first. | **Fixed.** `make setup` now reads "install dependencies, start the databases, migrate and seed" (`Makefile:38`), and `make seed` is described as a safe re-seed, matching its `make help` text. |

Rejected: (none; the author's side fills this in.)

Rejected: none.

**After the fixes:** the docstring-free AST dump of the six Python files is still identical to the base. `make check`:
exit 0 (ruff, mypy clean; pytest 1280 passed, 20 skipped; vitest 525 passed; e2e 107 passed). `make designation-check
BASE=2b1b8f7`: clean.
