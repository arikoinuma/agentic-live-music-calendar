# A7 — testing

**Status:** Plan review
**Date:** October 20, 2026
**Author model:** Claude Sonnet 5.5 (plan, October 20, 2026)
**Reviewer model:** Claude Opus 5.5 (plan review round 1 — pending)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A7 (gaps v0.1-G14, v0.1-G15, v0.1-G16) and §2 point 5; `AGENTS.md`
("Conventions": *Tests state what they prove*, *Comment-only passes must not change code*);
`docs/references/fastapi-style-guide.md` ("Testing", "Linting", Anti-patterns); `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D3` and the mutation checks `M1`–`M9`; elsewhere they are written
`A7-D1`, `A7-M1` and so on (`docs/dev/conventions.md`). Code, tests and code comments write the scoped form even while
implementing this plan: `A7-D3` in `pyproject.toml`, never `D3` (`make designation-check` fails a bare one). Review items are
`A7-PR<round>-<n>` (plan review) and `A7-CR<round>-<n>` (code review). Other plans' IDs carry their scope (`A3-D5`, `A5-CR1-1`,
`A2.1-PR1-10`, `v0.1-G14`). This plan has no key points (`K`): it has no `TODO(Ari)` gaps (see "TODO(Ari) gaps").

**Branch.** `AGENTS.md` names the branch `a7-testing`. This session was assigned `claude/adoring-maxwell-7i6de2`, so the plan,
and later the code, land there. Rename on merge if you want the milestone name.

## Context

A7 was written, in the build plan, as the milestone that adds the missing tests. It isn't that any more. Three of its five
boxes were ticked by A3 and A5 as a side effect of building those milestones tests-first, and the numbers show it. At the
start of this plan (HEAD `bc1308c`, in the cloud sandbox with Postgres up, no MongoDB, no gitignored fixtures):

| Build plan claim | Measured today |
|---|---|
| G14: `agent_worker/` tests "won't even be collected" | `testpaths = ["app", "agent_worker/tests"]` (A2 added it). **883 items collected: 868 pass, 15 skip.** The collection setting still has one open weakness, below |
| G15: mypy on `agent_worker/` has "~11 known errors" | **75 errors in 8 files** (`uv run mypy agent_worker/`). 57 are in `eval/run_eval.py`, 1 is in production code, 17 are in tests. `uv run mypy app/` is clean (31 files) |
| G16: "no test touches the graph, the nodes, the routing logic, or the schemas" | **583 test functions.** One-off `coverage` run (branch coverage on `app/` and `agent_worker/`, minus tests, `eval/` and `local_test.py`): **98% overall; every module of `agent_worker/` is at 95–100%**, and the decision modules (`validation`, `policy`, `reconcile`, `commit`, `artist_match`, `graph`, `trace`, `audit`) are all ≥ 99% |
| "A fake model client so the graph can be tested end to end without Ollama running" | Exists: `tests/fakes.py` `ScriptedCompletions` / `scripted_client()`, used in 11 test modules (plus the shared `reconcile_support.py`), answering `PAGE`, `SPLITTER`, `STATUS` and `ARTIST_MATCH` per script, raising on an unscripted call. (The build plan and `apps/api/AGENTS.md` call it `ScriptedClient`; no such name exists) |

So A7's job is to **finish and lock in**, not to build:

1. **The collection setting is fragile** (v0.1-G14, what is left). `testpaths` lists `agent_worker/tests` only, and the file
   name `local_test.py` matches pytest's default `*_test.py` glob. Widening `testpaths` to the whole package, which is the
   obvious fix for "a test dropped in `eval/` is never collected", makes pytest **import `local_test.py` on every run**
   (CONFIRMED in a scratch copy with a one-line probe: it prints during `--collect-only -s`; the file imports Postgres,
   MongoDB and the worker, and it has no import-time side effect only because A4 moved its work under `if __name__`).
   Narrowing `python_files` to `test_*.py` fixes both at once. And nothing today notices if a test file lands somewhere
   pytest doesn't look.
2. **mypy stops at `app/`** (v0.1-G15). The worker is 22 modules of the most consequential logic in the repo and the gate that
   catches `None`-vs-`int` slips doesn't cover it. Nothing in the 75 errors is a behavior bug, but one of them is a design
   decision to record (`run_eval.py:171`), and 57 are one wrong annotation.
3. **A handful of documented behaviors have no test.** The coverage run lists 27 uncovered statements across `app/` and
   `agent_worker/` (15 of them in `agent_worker/`) and 17 partial branches. Most are defensive or wiring ("What is not
   covered", below). Seven are real rules nobody pinned: the act splitter ignoring out-of-range and duplicate ids, three
   JSON-LD edge cases, the status question's fallback match, the time normalizer's non-string refusal, reconcile's `None`
   guards, and the fetch node's image-file route.
4. **Bookkeeping that went stale:** the build plan's A7 boxes, the "lower bar" paragraph in `apps/api/AGENTS.md`, the CI
   comment on the mypy step, `env-setup.md`'s "11 real type errors", and the `A7` row missing from `conventions.md`.

What A7 is **not**: the pipeline evaluation against labels (A8), the read-route rewrite (A1b), and anything that calls a
model. All of A7 is deterministic and runs in a cloud session; the 15 skips are unchanged by it.

### What A7 delivers

| Item (build plan A7) | Marking | Where it lands |
|---|---|---|
| Fix `testpaths` so `agent_worker/` tests are collected (v0.1-G14) | [written] | `pyproject.toml`: `testpaths = ["app", "agent_worker"]`, `python_files = ["test_*.py"]`; a guard test `app/tests/test_pytest_config.py` |
| Unit tests for the validation checks | [fill-in] (done) | A3: `tests/test_validation.py`. **Ticked, no work** |
| Unit tests for the routing function | [fill-in] (done) | A3: `tests/test_policy.py`, `tests/test_graph.py`. **Ticked, no work** |
| Unit tests for reconcile against a seeded database | [fill-in] (done) | A5: `tests/test_reconcile_*.py`, `test_calendar_reader.py`. **Ticked, no work** |
| A fake model client | [written] | Exists (A3, extended in A5). **Ticked**, with the stale `ScriptedClient` name corrected in the docs and in `fakes.py`'s docstring; two other fakes deliberately left alone (Settled details) |
| Widen mypy to `agent_worker/` in CI and clear the errors (v0.1-G15) | [written] | `[tool.mypy] files`, 75 errors cleared, `make typecheck` and the CI step both run `uv run mypy` |
| *(added)* Close the seven unpinned rules | [written] | New tests in the existing files for each module |
| *(added, D1)* A report-only coverage target | [written] | `coverage` dev dependency, `make coverage`, `.gitignore` |
| *(added, D2)* `Proves:` comments on the 14 older tests that lack one | [written] | `app/tests/` — which of the 14 is D2 |

### Decisions already made (earlier in this project)

- **Tests first, and a test must be able to fail.** Build plan §3; A6 added a "Mutation checks" table as the proof. This plan
  follows it (M1–M9).
- **Real database in tests; dependency/monkeypatch the model client, not the database** (style guide Anti-patterns:
  "Mocking the database in integration tests"). Unchanged: A7 adds no DB mocks. The new tests need no database at all.
- **`app/` never imports from `agent_worker/`** (`apps/api/AGENTS.md`). The guard test lives in `app/tests/` and imports from
  neither; it only inspects files and pytest's own config.
- **Every test opens with a `Proves:` comment; every helper is explained; expectations don't come from the code under test**
  (`AGENTS.md`). The new tests follow it and say where each expected value comes from.
- **`# type: ignore` needs a reason beside it.** 29 exist today in `app/` and `agent_worker/`; the one A7 adds follows suit.

### Departures from the build plan (to apply to `alpha-build-plan.md` when implementing)

1. **G14's fix is smaller than written and one step further:** `agent_worker/tests` is already collected (A2). What A7 does is
   widen to the whole package *safely* (narrow `python_files`) and add the guard test so the setting can't silently regress.
2. **G15's "~11 known errors" was 75** by the time anyone measured, and the milestone's "do this last, once the code has
   stopped moving" is not met: A8 and H1 will still change `eval/` and `extraction.py`. The mypy gate in CI is the answer to
   that (a later change either type-checks or fails the PR), so the milestone is built now rather than waiting.
3. **G16 is closed with evidence** (583 test functions; the coverage figures above), not just ticked.
4. **Three items were added** that the build plan doesn't list: the guard test, the seven coverage-gap tests, and (per D1, D2)
   the coverage target and the `Proves:` pass. Each is small and each is justified in the section that describes it; D1
   and D2 can be declined.
5. **The fake-client box is ticked without consolidating the three fakes** (Settled details). It can be reopened.

## Decisions for Ari

**How to read this section.** Each decision is one question with two options, a scenario, and what each costs. The plan below
is written to the recommended option (A). None of these is ★ (changes how the calendar or the audit trail behaves): A7 changes
no behavior of either. All three change what the repo asks of future work, so they are yours.

| # | Question | Recommendation | Status |
|---|---|---|---|
| D1 | Add a report-only coverage tool (`make coverage`)? | A: yes, no threshold, not in CI | Open |
| D2 | Which older tests get a `Proves:` comment now? | A: `test_health.py` only; the 13 router tests wait for A1b | Open |
| D3 | Does the mypy gate cover tests and the eval harness, or only production code? | A: everything under `agent_worker/` | Open |

---

### D1 — Add a report-only coverage tool?

- **Scenario.** You merge A8 next month and wonder whether a new module is exercised by anything. Today the only way to know is
  to ask an agent to run `uv run --with coverage ...` (which is how the 98% above was made, and why a stray `.coverage` file
  appeared in the working tree and had to be deleted).
- **Option A — yes.** Add `coverage` to the dev dependency group (pinned in `uv.lock`), a `[tool.coverage]` block (branch
  coverage; `source = ["app", "agent_worker"]`; omit tests, `eval/` and `local_test.py`), a `make coverage` target
  (`REQUIRE_DB=1 uv run coverage run -m pytest`, then `coverage report -m --skip-empty`) and a `.coverage` line in `.gitignore`
  (the existing `coverage` entry matches a directory, not the file; CONFIRMED by `git status`). **No threshold, and not in
  `make check` or CI.** A percentage gate invites writing tests to touch lines rather than to prove behavior (the exact thing
  the `Proves:` convention exists to prevent); the report is for reading the "Missing" column, as A7 does below.
- **Option B — no new tool.** The measurement stays in this plan as a one-off; the seven coverage-gap tests land either way.
  Costs nothing now; the next person re-derives the incantation.
- **Why A:** it's four small lines of config and it makes the claim in "Context" re-checkable by anyone, which is this repo's
  "verify, don't assume" standard. If you'd rather not carry the dependency, B loses little.

### D2 — Which older tests get a `Proves:` comment now?

- **Scenario.** `AGENTS.md` requires every test to open with `Proves:`. A scan of all 583 test functions finds **14 without
  one**, all in `app/tests/`: `test_health.py::test_health` and 13 in `test_routers.py` (Track 0, before the convention). But
  A1b will rewrite `test_routers.py` wholesale (async client, a real session, `sample_data.py` deleted), and the expected values
  in those tests come from `sample_data`, which is exactly what A1b removes.
- **Option A — `test_health.py` now; the 13 router tests are A1b's.** The build step adds one comment (comment-only pass,
  verified by comparing syntax trees before and after, per `AGENTS.md`), and adds one sentence to A1b's build-plan bullet:
  "tests it writes or migrates carry `Proves:`". No wasted work, no merge conflict with A1b.
- **Option B — all 14 now.** The convention holds on the day A7 closes; A1b then rewrites 13 of the comments along with the
  tests, and has to read around them.
- **Why A:** the 13 comments would be written against behavior A1b is about to replace. If you want the repo clean of the
  14 on the day A7 is signed off, B is a few minutes of work and is safe.

### D3 — Does the mypy gate cover tests and the eval harness?

- **Scenario.** `reconcile_support.py`, a test helper used by many tests, indexes a dict with an `int | None` (`d.stored_id`).
  At runtime it's fine because an update always names a stored show. mypy objects. Should a test helper be held to that?
- **Option A — yes: `files = ["app", "agent_worker"]`,** which includes `agent_worker/tests/` and `agent_worker/eval/`. Costs
  17 edits in six test files, each verified to change no behavior (table under Step 3), plus the 57 in `run_eval.py` (one
  annotation and one ignore). A typed test helper catches the helper drifting from the code it stands in for, which is the
  failure A5-PR1-15 was about.
- **Option B — production code only:** `exclude = ["agent_worker/(tests|eval)/"]`. One error to fix (`act_split.py:109`), and
  the gate says nothing about 35 test modules or the eval harness. Less friction when writing tests; the 17 errors stay.
- **Why A:** all of it is already fixed on a scratch copy and the suite is unchanged (868 passed, 15 skipped, ruff clean, mypy
  0 errors in 103 files). The ongoing cost is that a new test must type-check, which for the helpers that exist is small.

### Settled details (veto only)

These follow from the build plan or from the decisions above. Listed so nothing is hidden; object to any.

- **`python_files = ["test_*.py"]` and `testpaths = ["app", "agent_worker"]`.** The `*_test.py` default is dropped on
  purpose (`local_test.py`, above). Consequence for future files: a test module must be named `test_*.py`. A new manual script
  should not be, and `apps/api/AGENTS.md` will say so.
- **The guard test lives in `app/tests/test_pytest_config.py`** and reads pytest's effective `testpaths` and `python_files`
  through the `pytestconfig` fixture, so it can't drift from the config it guards.
- **`[tool.mypy] files = ["app", "agent_worker"]` is the single source of truth.** `make typecheck` and the CI step both run
  bare `uv run mypy`. `mypy app/` as an explicit argument still works (an argument overrides `files`).
- **`scripts/` and `migrations/` stay out of the gate.** `scripts/` is clean today (CONFIRMED) and `migrations/env.py` has 22
  errors from Alembic's template (a `**dict` into `context.configure`). Neither is named by v0.1-G15; adding `scripts/` is free
  later.
- **The one new `# type: ignore` is `run_eval.py:171`** (`[arg-type]`, with a two-line reason). The `--legacy` path wraps the
  frozen pre-A2 `VenuePageExtraction` (`eval/legacy.py`, a *different class on purpose*) in a `PageExtractionResult` typed for
  the live one, and its docstring says the path "bypasses the A2.1 entry point on purpose". The alternative, widening
  `PageExtractionResult.extraction` to `BaseModel`, would loosen a production type for a frozen experiment path.
- **`act_split.py:109` is renamed, not ignored.** The loop variable `item` (an `ActSplitItem`) is reassigned to
  `by_id.get(i)` (`ActSplitItem | None`); the second use becomes `answered`. Production code, no behavior change, covered by
  existing tests and by the new splitter test (M1).
- **The two other fakes stay.** `test_extraction.FakeCompletions` (24 call sites) and `test_prompts.FakeCompletions` (6)
  answer *every* call the same way; `ScriptedCompletions` answers from an ordered script and raises on an unscripted call.
  Those are different contracts, and moving 30 call sites to prove nothing new would risk what works. `fakes.py`'s docstring
  already says the first one "keeps its own". Reopen if you want one fake.
- **Not every uncovered statement gets a test** (see "What is not covered, stated plainly").
- **No `TODO(Ari)` gaps.** Every remaining A7 item is [written], and the lesson-bearing ones (validation, routing, reconcile
  tests) were [fill-in] items Ari filled in A3 and A5. Nothing in this plan meets `AGENTS.md`'s bar for a gap ("lines where
  the concept lives, not where most of the typing is"), so none is invented.
- **Cloud vs local.** Everything here runs in a cloud session (no model, no Ollama, no Docker). The sandbox's Node 22 is
  irrelevant: no JS file changes.

## Test approach (written first, watched fail, then made green)

A7 is unusual: its subject is the test suite, and most of its "production" change is configuration. So "tests first" means
three different things, and the plan says which applies where.

| Change | Red first, because | Green when |
|---|---|---|
| The collection setting | the guard test's pattern check **fails** on today's config: the effective `python_files` is pytest's default `["test_*.py", "*_test.py"]`, which matches `agent_worker/local_test.py` | `python_files = ["test_*.py"]` |
| The mypy gate | `uv run mypy agent_worker/` **is** the failing test: 75 errors, recorded at the start of the build | `uv run mypy` exits 0 on `files = ["app", "agent_worker"]` |
| The seven unpinned rules | they can't be red against current code: they pin behavior that already exists. So they're proved able to fail by **mutation** instead (M1–M7): break the line, watch the named test go red, restore | each mutation turns exactly its test red |

### 1. The collection guard (`app/tests/test_pytest_config.py`, new)

Three tests over two small pure helpers, defined in the test file and explained there (`uncollected(files, testpaths, root)`
and `would_import(name, patterns)`). Every expected value is a path or a glob the test itself builds, never read from the
code being guarded.

- `test_every_test_module_is_inside_a_test_path` — walks `apps/api` for `test_*.py` (skipping `.venv`, `node_modules`,
  `__pycache__`, hidden directories) and asserts none lies outside `testpaths`. **Proves:** a test file added under `scripts/`
  or a new top-level package is not silently never run (v0.1-G14's original failure). Green today and after.
- `test_the_file_pattern_matches_only_test_modules` — for every `.py` under `testpaths`, if its name matches any effective
  `python_files` glob it must be named `test_*.py`. **Proves:** a manual script such as `local_test.py` is never imported by
  pytest. **Red today** (the default `*_test.py` matches `local_test.py`); green after the config change. The failure message
  names the file and the pattern.
- `test_the_guards_can_fail` — the negative control: the two helpers are applied to a synthetic `scripts/test_x.py` (reported
  as uncollected) and to `local_test.py` against `["*_test.py"]` (reported as imported), so a guard that always passes can't
  hide.

### 2. The seven unpinned rules (new tests in each module's existing test file)

Each is a plain unit test with no database and no monkeypatching. Where the expected value comes from is stated per test.

| # | Test (file) | Rule it pins | Where the expected value comes from |
|---|---|---|---|
| C1 | `test_act_split.py`: an answer with an out-of-range id, a negative id, and a repeated id | `act_split.py:99–105`: "the first answer for an id wins; ids outside the range are ignored" (`missing_ids` lists the title that got no usable answer) | The module's own stated rule, and the test's hand-written script: three titles, an answer that skips one, repeats another with different acts, and adds ids `-1` and `3` |
| C2a | `test_jsonld.py`: a non-dict entry in the JSON-LD graph | `_is_event` returns False for a non-dict, so the real events beside it are still read | A hand-written `@graph` with a string and a number next to two events |
| C2b | `test_jsonld.py`: an offer whose `price` isn't a number | `_price` skips it and takes the next offer's price (the `continue`), instead of raising | A hand-written two-offer event: `"free-ish"`, then `"15.00"` → `15.0` |
| C2c | `test_jsonld.py`: a start with a UTC offset and an end without one | `_end_time` returns `None` rather than subtracting an aware from a naive datetime (`TypeError`) | Hand-written ISO strings differing only in the offset |
| C3 | `test_status_check.py`: acts that have no identifying words (names too short to have any, like "MO" or "U2", per `status_check.py`'s own docstring) | `_on_page`'s fallback (`status_check.py:100–101`): compare the folded text instead, in both directions (act present → true, absent → false). Reached through the public function that calls it, which the build identifies | A hand-written page text and short-name acts; the build reads `identifying_words` first to choose names that really have none |
| C4 | `test_normalize.py`: a list or dict where a time should be | `normalize_time` raises `ValueError` (not `TypeError`) so Pydantic turns it into a re-ask — the reasoning is in the function's own comment | The comment, and the exception type the test asserts |
| C5 | `test_reconcile_shows.py`: `listings_from(None)` and `excluded_listing_dates` with `None` extraction or `None` validation | no extraction → no listings; either `None` → no protected dates. Both are the "nothing to reconcile" answers (`reconcile.py:254`, `:281`) | An empty list and an empty `frozenset`; the guard clauses themselves say so, and the test builds its non-`None` control case by hand |
| C6 | the file with the fetch tests (found at build): `fetch_node` on a `.png` path | a local image file is read as base64 into `page_content` and `page_html` stays unset (`nodes.py:143–146`) | A one-pixel PNG written to `tmp_path`; the test computes `base64.b64encode(bytes)` itself |

C2b and C2c are the two that are real *decision* logic on the JSON-LD route, the route that carries most of the venues, which
is why they matter most.

### 3. The mypy fixes (no new tests; the existing suite is the check)

Each fix changes types or adds an `assert` that states an invariant; none changes a result. The check is that the whole suite
is unchanged (868 passed, 15 skipped at the start) and that `uv run mypy` goes from 75 errors to 0. **Both were CONFIRMED on a
scratch copy of the tree while writing this plan** (Verification, step 1). The build repeats it on the real tree.

### 4. Mutation checks (the proof the tests can fail)

Run by the build step in a throwaway `git worktree` (removed afterwards). A bare directory copy is **not** enough: some tests
find `docs/dev/audit-queries.sql` from their own path (I hit this while verifying this plan). Each result goes in the
Implementation log.

| # | Break | The test that must go red |
|---|---|---|
| A7-M1 | in `act_split.py`, drop the `0 <=` bound, then separately drop `and item.id not in by_id` | C1 (each mutation turns it red) |
| A7-M2 | in `jsonld._end_time`, delete the `if (start_at.tzinfo is None) != (end_at.tzinfo is None)` return | C2c |
| A7-M3 | in `jsonld._price`, replace `continue` with `return None` | C2b |
| A7-M4 | in `status_check`, make the fallback `return True` | C3 (the "absent → false" half) |
| A7-M5 | in `normalize_time`, delete the `if not isinstance(value, str)` raise | C4 |
| A7-M6 | in `reconcile.listings_from` / `excluded_listing_dates`, delete the `None` guards | C5 |
| A7-M7 | in `nodes.fetch_node`, drop the `IMAGE_SUFFIXES` branch | C6 |
| A7-M8 | restore `python_files` to pytest's default; separately add a stray `scripts/test_probe.py` | the pattern test; the location test |
| A7-M9 | add `x: int = "a"` to a function in `agent_worker/nodes.py` | `uv run mypy` exits non-zero (proves the widened gate can fail) |

### Existing tests that change

| File | Change | Why |
|---|---|---|
| `test_validation.py` | `test_free_together_with_a_price_is_an_error` is parametrized as `("advance", "day")` instead of a `dict` spread | `show(**price)` with `dict[str, float]` could bind to any parameter, including `date`; the case ids change (`15.0-None`, `None-10.0`) |
| `reconcile_support.py` | three `assert … is not None` in `apply_plan`, each with its reason | an insert always carries its listing; an update or removal always names a stored show |
| `test_reconcile_shows.py` | `shows: list[StoredShow] = []` (+ the import, in sorted order) | `[], list(KNOWN)` can't be inferred |
| `test_commit_ops.py` | `lineup: list[dict[str, Any]]` | mixed-value dict literals infer `list[object]` |
| `test_graph_audit.py` | `script: dict[Any, list[Any]]` at two sites | matches `run_traced`'s own parameter type |
| `test_commit_db.py` | `assert rows[-1].detail is not None` and the same for `rows[0]` | `AuditLog.detail` is `dict \| None` |

### What is not covered, stated plainly

- **`main.main()`** (`main.py:187–201`, 4 statements): building the real context and the shutdown. `run_all` and
  `run_venue`, which it calls, are tested (`test_run_venue.py`); `main()` itself runs only under `make worker` and `local_test`.
- **In `app/` (12 statements, none decision logic):** `/health/db` (`app/main.py:44–46`) uses the app's own engine, which is
  `DATABASE_URL`, the *development* database, not `calendar_test`, so a unit test would be testing the developer's machine;
  `sample_data.py:241,256` are the not-found returns A1b deletes with the file; `testing/db.py` (7) is the test-database
  helper's own skip, fail and explicit-URL branches.
- **`calendar_writer._apply`'s second `ShowGone`** (`calendar_writer.py:226`): unreachable. The locked read at line 207
  raises first, and this `session.get` is an identity-map hit on the row that read loaded. Kept as a defensive guard.
- **Four partial branches** (`audit.py:168→172`, `policy.py:220→218`, `extraction.py:375→377`, `nodes.py:325→332`): the
  untaken side is "a `match` with no matching case", "an advice code with no advice text", "the image route with the year rule
  off" and "an escalation with an empty attempt history". Reaching the last needs a state the graph never produces (an
  escalation always follows a recorded attempt). Not worth a contrived test.
- **The 15 skips:** 14 in `test_validation_on_real_pages.py` (the eval fixtures and results are gitignored; CI never runs them,
  `apps/api/AGENTS.md`) and 1 real-MongoDB test (skips without a server locally, fails under `CI`). A local run with Docker up
  has one fewer skip.
- **Live-model behavior.** Nothing in CI calls Ollama or a hosted model, so extraction *quality* is not tested here. That is
  A8 (pipeline evaluation) and H1.
- **Whether the suite catches wrong code in general.** The mutation checks above cover the tests A7 adds. There is no
  mutation-testing tool run over the whole suite (deferred; D1 is the cheaper first step).
- **The frontend.** B5.

### Known gotchas to handle up front

- **Import order.** Adding `StoredShow` to `test_reconcile_shows.py` in the wrong place fails ruff's `I001` (CONFIRMED while
  verifying; it goes between `StoredLineupEntry` and `night_sort_key`).
- **`--collect-only` hides zero-item modules.** pytest's collection tree lists only modules that yield tests, so a module that
  pytest imports but that has no tests is invisible in the output. The hazard in `local_test.py` can only be seen by a
  top-level `print` plus `-s`. This goes in `notes.md`.
- **A coverage run leaves `.coverage` in the working tree** until D1 (A) adds it to `.gitignore`. Delete it after any
  measurement.
- **Shared helper, wide blast radius.** `reconcile_support.py` is used by many tests; run the whole suite after touching it.
- **One pytest at a time:** the DB fixtures drop `calendar_test` (`apps/api/AGENTS.md`), so don't run the mutation checks in
  parallel with the suite.
- **mypy's first run is cold** (~20 s here), and the `files` paths are relative to where mypy is run: always from `apps/api`,
  which the Makefile's `cd $(API_DIR)` already does.

## Implementation steps

### Working protocol

All steps are [written]; there are no gaps to leave open. Order: tests first, then the change that turns them green, then the
bookkeeping. One commit per numbered step so a reviewer can read them one at a time.

### 1. Tests first (written)

1. Record the baselines: `REQUIRE_DB=1 uv run pytest -q` (expect **868 passed, 15 skipped**), `uv run mypy agent_worker/`
   (expect **75 errors in 8 files**), `uv run mypy app/` (clean), `uv run ruff check .` (clean).
2. Write the guard test file. Confirm `test_the_file_pattern_matches_only_test_modules` is red and names `local_test.py`; the
   other two pass.
3. Write C1–C6. They pass at once; watch each go red under its mutation (M1–M7), restore, record.

### 2. The collection setting (written)

`pyproject.toml`: `testpaths = ["app", "agent_worker"]`, `python_files = ["test_*.py"]`, and the comment above it rewritten as a
why-comment (the old one says "A7 widens the rest" and describes the workaround). Expect **the same 883 items** plus the new
ones, the guard green, and `local_test.py` not imported (probe it once, M8, then remove the probe).

### 3. The mypy gate (written)

Fix the 75 errors as follows (all CONFIRMED on a scratch copy: mypy 0 errors in 103 files, ruff clean, 868 passed, 15 skipped):

| Where | Errors | Cause | Fix |
|---|---|---|---|
| `eval/run_eval.py:200–206` | 56 | `flag = {...}` infers `dict[str, object]`, so `**flag` matches no `add_argument` parameter | `flag: dict[str, Any] = {...}` (`Any` is already imported) |
| `eval/run_eval.py:171` | 1 | the `--legacy` path's frozen schema is a different class (see Settled details) | `# type: ignore[arg-type]` with a two-line reason |
| `act_split.py:109` | 1 | loop variable reused with a wider type | rename the second use to `answered` |
| `tests/reconcile_support.py:232–246` | 9 | `Decision.listing` and `.stored_id` are optional | three `assert … is not None`, each with its reason |
| `tests/test_validation.py:271` | 2 | `**dict[str, float]` | parametrize `("advance", "day")` |
| `tests/test_reconcile_shows.py:425` | 1 | uninferable empty list | `shows: list[StoredShow] = []` |
| `tests/test_commit_ops.py:271` | 1 | `list[object]` | `lineup: list[dict[str, Any]]` |
| `tests/test_graph_audit.py:118,133` | 2 | script dict inferred as `dict[ModelMetaclass, object]` | `script: dict[Any, list[Any]]` |
| `tests/test_commit_db.py:182,232` | 2 | `detail` is `dict \| None` | `assert … detail is not None` |
| **Total** | **75** | | |

Then: `[tool.mypy] files = ["app", "agent_worker"]` (with a why-comment); `make typecheck` runs `uv run mypy`; `ci.yml`'s mypy step
runs `uv run mypy` and its comment ("Scoped to app/ — agent_worker/ (Phase 6) is still active WIP…") is replaced by one saying
what the gate now covers; M9.

### 4. The `Proves:` pass (written, comment-only; per D2)

Per D2 option A: one comment on `test_health.py::test_health`. Snapshot the file first, compare syntax trees ignoring comments
and docstrings afterwards (the `AGENTS.md` pattern), then run the suite. Add one sentence to A1b's build-plan bullet.
(Option B: the same for the 13 router tests.)

### 5. Coverage target (written; per D1)

Option A: `coverage` in the dev group (`uv add --dev coverage`, which updates `uv.lock`), the `[tool.coverage.*]` block, the
`make coverage` target and its `help` line, and `.coverage` / `htmlcov/` in `.gitignore`. Run it once and record the totals in
the Implementation log so the figures in "Context" are the figures on the merged tree.

### 6. Docs and bookkeeping (written)

- `docs/dev/alpha-build-plan.md` §5 A7: tick the boxes with the evidence above; add the "Plan and review" paragraph as A2–A6
  have; add the D2 sentence to A1b's bullet. Leave the G14/G15 rows of the gap table as the historical inventory, but the A7
  paragraph says G15's "~11" was 75.
- `docs/dev/conventions.md`: the `A7` row in the scope table.
- `apps/api/AGENTS.md`: Commands (`uv run mypy`), replace the "held to a lower bar" paragraph, `ScriptedClient` →
  `scripted_client()` / `ScriptedCompletions`, and one line on naming test modules `test_*.py`.
- `agent_worker/tests/fakes.py`: the docstring sentence "It is the fake model client that milestone A7 plans, in the one shape
  A3 needs" becomes a statement of what it is.
- `docs/dev/env-setup.md:230`: a dated `[UPDATE OCT 20]` note after "widen the scope once that settles".
- `docs/dev/notes.md`: the `*_test.py` / zero-item-module entry (Known gotchas, above).
- `.github/workflows/ci.yml`: step 3.

## Critical files

| File | Change |
|---|---|
| `apps/api/pyproject.toml` | `testpaths`, `python_files`, `[tool.mypy] files`, comments; D1: `coverage` dev dependency and `[tool.coverage.*]` |
| `apps/api/app/tests/test_pytest_config.py` (new) | The collection guard |
| `apps/api/agent_worker/tests/` | C1–C6 added to `test_act_split`, `test_jsonld`, `test_status_check`, `test_normalize`, `test_reconcile_shows`, and the fetch tests' file; the typing edits in `reconcile_support`, `test_validation`, `test_reconcile_shows`, `test_commit_ops`, `test_graph_audit`, `test_commit_db`; `fakes.py` docstring |
| `apps/api/agent_worker/act_split.py` | One rename (no behavior change) |
| `apps/api/agent_worker/eval/run_eval.py` | One annotation, one ignore with its reason |
| `Makefile`, `.github/workflows/ci.yml` | `uv run mypy`; D1: `make coverage` |
| `.gitignore` | D1: `.coverage`, `htmlcov/` |
| `apps/api/app/tests/test_health.py` | D2: one comment |
| Docs listed in step 6 | Bookkeeping |

No migration, and `app/schemas.py` is untouched, so `make types` / `make fixtures` have nothing to regenerate and there is no
B-track impact. No production behavior changes: the only production-code edit is a variable rename.

## Verification

**In the cloud session (this author's, and the build's):**

1. **Done while writing this plan, on a scratch copy of the tree** (a directory copy with the real `docs/` and `scripts/`
   symlinked in; a worktree for the build): with every fix in the Step 3 table, the `files` setting, `testpaths` and
   `python_files` applied, `mypy` reports **no issues in 103 source files**, `ruff check .` is clean, and `pytest` gives
   **868 passed, 15 skipped**, with **883 items collected** under the new collection settings (the same count as before).
   The build repeats this on the real tree, after the new tests, and records the new totals.
2. `make check`: ruff, mypy (both packages), eslint, `tsc`, pytest with `REQUIRE_DB=1`, Vitest, `contract-check`,
   `designation-check`. Node is 22 here and 24 in CI, so a green JS half in the sandbox is not quite a green CI.
3. M1–M9 run in a worktree and recorded in the Implementation log.
4. `make designation-check BASE=<the commit the branch started from>` exits 0.
5. The comment-only pass (step 4): syntax trees match before and after.
6. `git status` shows no `.coverage`, `htmlcov/` or `.mypy_cache` residue.
7. The draft PR's CI: the Python job's mypy step now checks both packages and must be green.

**Locally (Ari, optional; needs Docker, no Ollama):**

8. `make db-up && make check`. Expect the same suite green with the one Mongo test now running (14 skips instead of 15).
9. Deliberately add `x: int = "a"` to a file in `agent_worker/` and run `make typecheck`: it must fail. Remove it.
10. If D1 is accepted: `make coverage` and read the "Missing" column for one module you know.

## Not doing in A7

- **The pipeline evaluation against labels** (A8): scoring a full graph run, calibrating the 0.8 threshold and the retry cap,
  checking that self-reported confidence correlates with correctness.
- **The read-route rewrite** (A1b), including `test_routers.py` and the `StarletteDeprecationWarning`.
- **A coverage threshold or CI gate**, and a mutation-testing tool over the whole suite.
- **Consolidating the three model fakes.**
- **Stricter mypy** (`disallow_untyped_defs`, `strict`), `scripts/` and `migrations/` in the gate, `filterwarnings = error`.
- **Committing sanitized venue fixtures so CI can run the 14 real-page tests.** That is a copyright and maintenance call for
  A8 or the hosted phase, not a testing-tooling one.
- **End-to-end browser tests.** The frontend's testing is B5's.

## Plan review

*(none yet)*

## Approval

**For Ari to decide before approving:** D1, D2 and D3 above. Also veto-or-accept the Settled details, in particular: narrowing
`python_files` (a manual script can no longer be named `*_test.py` *and* be collected, which is the point), the single new
`# type: ignore`, and leaving the two other model fakes alone.
