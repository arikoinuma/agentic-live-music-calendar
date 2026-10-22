# A7 — testing

**Status:** Done (Ari sign off) - Oct 21, 2026
**Date:** October 20, 2026
**Author model:** Claude Sonnet 5.5 (plan, October 20, 2026)
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 20, 2026; code review round 1, October 20, 2026)
**Spec:** `docs/dev/alpha-build-plan.md` §5 A7 (gaps v0.1-G14, v0.1-G15, v0.1-G16) and §2 point 5; `AGENTS.md`
("Conventions": *Tests state what they prove*, *Comment-only passes must not change code*);
`docs/references/fastapi-style-guide.md` ("Testing", "Linting", Anti-patterns); `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D3` and the mutation checks `M1`–`M10`; elsewhere they are written
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
   covered", below). Six groups of real rules are unpinned (eight tests below): the act splitter ignoring out-of-range and duplicate ids, three
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
| *(added)* Close the six groups of unpinned rules (eight tests) | [written] | New tests in the existing files for each module |
| *(added, D1)* A report-only coverage target | [written] | `coverage` dev dependency, `make coverage`, `.gitignore` |
| *(added, D2)* `Proves:` comments on the 14 older tests that lack one | [written] | `app/tests/` — which of the 14 is D2 |

### Decisions already made (earlier in this project)

- **Tests first, and a test must be able to fail.** Build plan §3; A6 added a "Mutation checks" table as the proof. This plan
  follows it (M1–M10).
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
4. **Three items were added** that the build plan doesn't list: the guard test, the eight coverage-gap tests, and (per D1, D2)
   the coverage target and the `Proves:` pass. Each is small and each is justified in the section that describes it; D1
   and D2 can be declined.
5. **The fake-client box is ticked without consolidating the three fakes** (Settled details). It can be reopened.

## Decisions for Ari

**How to read this section.** Each decision is one question with two options, a scenario, and what each costs. The plan below
is written to the recommended option (A for D1 and D3, B for D2). None of these is ★ (changes how the calendar or the audit trail behaves): A7 changes
no behavior of either. All three change what the repo asks of future work, so they are yours.

| # | Question | Recommendation | Status |
|---|---|---|---|
| D1 | Add a report-only coverage tool (`make coverage`)? | A: yes, no threshold, not in CI | **Decided A** (Ari, Oct 20) |
| D2 | Which older tests get a `Proves:` comment now? | B: all 14 now (revised in plan review; A was `test_health.py` only) | **Decided B** (Ari, Oct 20) |
| D3 | Does the mypy gate cover tests and the eval harness, or only production code? | A: everything under `agent_worker/` | **Decided A** (Ari, Oct 20) |

---

### D1 — Add a report-only coverage tool?

- **Scenario.** You merge A8 next month and wonder whether a new module is exercised by anything. Today the only way to know is
  to ask an agent to run `uv run --with coverage ...` (which is how the 98% above was made, and why a stray `.coverage` file
  appeared in the working tree and had to be deleted).
- **Option A — yes.** Add `coverage` to the dev dependency group (pinned in `uv.lock`), a `[tool.coverage]` block (branch
  coverage; `source = ["app", "agent_worker"]`; omit tests, `eval/` and `local_test.py`), a `make coverage` target
  (`REQUIRE_DB=1 uv run coverage run -m pytest`, then `coverage report -m --skip-empty`) and a `.coverage` line in `.gitignore`
  (the existing `coverage` pattern matches a file or directory named exactly `coverage`, not `.coverage`; CONFIRMED by `git status` and `git check-ignore`). **No threshold, and not in
  `make check` or CI.** A percentage gate invites writing tests to touch lines rather than to prove behavior (the exact thing
  the `Proves:` convention exists to prevent); the report is for reading the "Missing" column, as A7 does below.
- **Option B — no new tool.** The measurement stays in this plan as a one-off; the eight coverage-gap tests land either way.
  Costs nothing now; the next person re-derives the incantation.
- **Why A:** it's four small lines of config and it makes the claim in "Context" re-checkable by anyone, which is this repo's
  "verify, don't assume" standard. If you'd rather not carry the dependency, B loses little.

### D2 — Which older tests get a `Proves:` comment now?

- **Scenario.** `AGENTS.md` requires every test to open with `Proves:`. A scan of all 583 test functions finds **14 without
  one**, all in `app/tests/`: `test_health.py::test_health` and 13 in `test_routers.py` (Track 0, before the convention).
  `test_routers.py`'s own docstring says its tests deliberately avoid data and pin "the behavior that A1b must not break when it
  swaps the bodies for real queries: the URLs, the filter semantics, and the error codes". Several are data-free
  (`test_non_integer_id_is_422`, `test_invalid_ranges_are_rejected`, `test_openapi_exposes_the_response_schemas`, the envelope
  test); a few use sample ids (`/shows/2`, artist 1 third on a bill). A1b changes the client (`TestClient` →
  `httpx.AsyncClient`) and some of those ids, not what most of the tests prove (A7-PR1-4).
- **Option A — `test_health.py` now; the 13 router tests are A1b's.** One comment (comment-only pass, verified by comparing
  syntax trees before and after, per `AGENTS.md`), plus one sentence in A1b's build-plan bullet: "tests it writes or migrates
  carry `Proves:`". Cost: 13 tests stay out of the convention until A1b, which is not scheduled.
- **Option B — all 14 now.** The convention holds on the day A7 closes. The comments say what each test pins (URL, filter
  semantics, error code) and, for the few that read sample ids, say that the expected value comes from `sample_data`
  (`AGENTS.md`: "say where the expected values come from"); A1b then touches only those few. Cost: a short comment-only pass
  over 14 tests.
- **Why B (revised after plan review):** I first recommended A on the belief that the router tests' expectations all came from
  `sample_data` and would be rewritten. The file says otherwise: most of what they pin survives A1b, so the comments would
  mostly carry over. A is still safe if you'd rather keep A7 out of `test_routers.py`.

### D3 — Does the mypy gate cover tests and the eval harness?

- **Scenario.** `reconcile_support.py`, a test helper used by many tests, indexes a dict with an `int | None` (`d.stored_id`).
  At runtime it's fine because an update always names a stored show. mypy objects. Should a test helper be held to that?
- **Option A — yes: `files = ["app", "agent_worker"]`,** which includes `agent_worker/tests/` and `agent_worker/eval/`. Costs
  17 edits in six test files, each verified to change no behavior (table under Step 3), plus the 57 in `run_eval.py` (one
  annotation and one ignore). A typed test helper catches the helper drifting from the code it stands in for, which is the
  failure A5-PR1-15 was about.
- **Option B — production code only:** `exclude = ["agent_worker/(tests|eval)/"]`. One error to fix (`act_split.py:109`), and
  the gate says nothing about 35 test modules or the eval harness. Less friction when writing tests; the 17 errors stay.
- **A limit either option shares:** mypy here doesn't check the bodies of unannotated functions (no `check_untyped_defs`), so an unannotated test such as `test_health` is outside the gate. Turning that on is a stricter-mypy decision, listed under "Not doing".
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
| The eight coverage-gap tests | they can't be red against current code: they pin behavior that already exists. So they're proved able to fail by **mutation** instead (M1–M7 and M10): break the line, watch the named test go red, restore | each mutation turns exactly its test red |

### 1. The collection guard (`app/tests/test_pytest_config.py`, new)

Three tests over two small pure helpers, defined in the test file and explained there (`uncollected(files, testpaths, root)`
and `would_import(name, patterns)`). Every expected value is a path or a glob the test itself builds, never read from the
code being guarded.

- `test_every_test_module_is_inside_a_test_path` — walks `apps/api` for `test_*.py` (skipping `.venv`, `node_modules`,
  `__pycache__`, hidden directories) and asserts none lies outside `testpaths`. **Proves:** a test file added under `scripts/`
  or a new top-level package is not silently never run (v0.1-G14's original failure). Green today and after.
- `test_the_file_pattern_matches_only_test_modules` — walks the **same tree as the location test** (`pytestconfig.rootpath`,
  minus `.venv`, `node_modules`, `__pycache__` and hidden directories), not just `testpaths`, and asserts that any `.py` file
  whose name matches an effective `python_files` glob is named `test_*.py`. **Proves:** a manual script such as `local_test.py`
  is never imported by pytest, now or after a later widening of `testpaths` alone. **Red today** (the default `*_test.py`
  matches `local_test.py` wherever it sits); green after the config change. Walking only `testpaths` would be green today,
  because today's `testpaths` is `agent_worker/tests`, which doesn't contain `local_test.py` (A7-PR1-1, CONFIRMED by the
  reviewer with a scratch test). The failure message names the file and the pattern.
- `test_the_guards_can_fail` — the negative control: the two helpers are applied to a synthetic `scripts/test_x.py` (reported
  as uncollected) and to `local_test.py` against `["*_test.py"]` (reported as imported), so a guard that always passes can't
  hide.

### 2. The unpinned rules: six groups, eight tests (new tests in each module's existing test file)

Each is a plain unit test with no database and no monkeypatching. Where the expected value comes from is stated per test.

| # | Test (file) | Rule it pins | Where the expected value comes from |
|---|---|---|---|
| C1 | `test_act_split.py`: an answer with an out-of-range id, a negative id, and a repeated id | `act_split.py:99–105`: "the first answer for an id wins; ids outside the range are ignored" (`missing_ids` lists the title that got no usable answer) | The module's own stated rule, and the test's hand-written script: three titles, an answer that skips one, repeats another with different acts, and adds ids `-1` and `3` |
| C2a | `test_jsonld.py`: a non-dict entry in the JSON-LD graph | `_is_event` returns False for a non-dict, so the real events beside it are still read | A hand-written `@graph` with a string and a number next to two events |
| C2b | `test_jsonld.py`: an offer whose `price` isn't a number | `_offer_price` skips it and takes the next offer's price (the `continue`), instead of raising | A hand-written two-offer event: `"free-ish"`, then `"15.00"` → `15.0` |
| C2c | `test_jsonld.py`: a start with a UTC offset and an end without one | `_end_time` returns `None` rather than subtracting an aware from a naive datetime (`TypeError`) | Hand-written ISO strings differing only in the offset |
| C3 | `test_status_check.py`: acts that have no identifying words (names too short to have any, like "MO" or "U2", per `status_check.py`'s own docstring) | `_on_page`'s fallback (`status_check.py:100–101`): compare the folded text instead, in both directions (act present → true, absent → false). **This is a substring test, not a word test:** `['MO']` is "on the page" of "Oct 24: Lizzo at the Armory" (`armory` contains `mo`; CONFIRMED by the reviewer). The test pins substring behavior and its comment says so; the "absent" page must hold no occurrence of the name inside any word (`['U2']` against "Oct 24: Lizzo" is false). Reached through the public function that calls it, which the build identifies | A hand-written page text and short-name acts; the build reads `identifying_words` first to choose names that really have none |
| C4 | `test_normalize.py`: a list or dict where a time should be | `normalize_time` raises `ValueError` (not `TypeError`) so Pydantic turns it into a re-ask — the reasoning is in the function's own comment | The comment, and the exception type the test asserts |
| C5 | `test_reconcile_removal.py` (where the existing `listings_from` test lives): `listings_from(None)` and `excluded_listing_dates` with `None` extraction or `None` validation | no extraction → no listings; either `None` → no protected dates. Both are the "nothing to reconcile" answers (`reconcile.py:254`, `:281`) | An empty list and an empty `frozenset`; the guard clauses themselves say so, and the test builds its non-`None` control case by hand |
| C6 | the file with the fetch tests (found at build): `fetch_node` on a `.png` path | a local image file is read as base64 into `page_content` and `page_html` stays unset (`nodes.py:143–146`) | A one-pixel PNG written to `tmp_path`; the test computes `base64.b64encode(bytes)` itself |

**What a mutation can prove for C1 (A7-PR1-2).** The range half (`0 <= item.id < len(titles)`) is *redundant by construction*:
`by_id` is read only through `by_id.get(i)` for `i` in `range(len(titles))`, so an out-of-range id stored in it is never read.
Dropping the bound leaves every output unchanged (CONFIRMED by the reviewer), so no test can turn red on it. C1 still includes
ids `-1` and `3` (they document the rule and would catch a change that did read `by_id` another way), but only the duplicate
half, `and item.id not in by_id` (first answer wins), is mutation-provable. M1 is that mutation alone. No production change
for it in A7.

C2b and C2c are the two that are real *decision* logic on the JSON-LD route, the route that carries most of the venues, which
is why they matter most.

### 3. The mypy fixes (no new tests; the existing suite is the check)

Each fix changes types or adds an `assert` that states an invariant; none changes a result. The check is that the whole suite
is unchanged (868 passed, 15 skipped at the start) and that `uv run mypy` goes from 75 errors to 0. **Both were CONFIRMED on a
scratch copy of the tree while writing this plan** (Verification, step 1). The build repeats it on the real tree.

### 4. Mutation checks (the proof the tests can fail)

Run by the build step in a throwaway `git worktree` (removed afterwards). A bare directory copy is **not** enough: some tests
find `docs/dev/audit-queries.sql` from their own path (I hit this while verifying this plan), and the worktree needs
`apps/api/.env` copied in (it is gitignored, and `Settings()` fails at import without it). `uv` creates the worktree's own
`.venv` on first run. Each result goes in the Implementation log.

| # | Break | The test that must go red |
|---|---|---|
| A7-M1 | in `act_split.py`, drop `and item.id not in by_id` (a repeated id then overwrites the first answer). Dropping the `0 <=` / `< len(titles)` bound is **not** a valid mutation: it changes nothing observable (above) | C1 |
| A7-M2 | in `jsonld._end_time`, delete the `if (start_at.tzinfo is None) != (end_at.tzinfo is None)` return | C2c |
| A7-M3 | in `jsonld._offer_price`, replace `continue` with `return None` | C2b |
| A7-M4 | in `status_check`, make the fallback `return True` | C3 (the "absent → false" half) |
| A7-M5 | in `normalize_time`, delete the `if not isinstance(value, str)` raise | C4 |
| A7-M6 | in `reconcile.listings_from` / `excluded_listing_dates`, delete the `None` guards | C5 |
| A7-M7 | in `nodes.fetch_node` (`nodes.py:145`), drop the `IMAGE_SUFFIXES` branch. The uses at `:161` and `:176` are the extract side and belong to other tests | C6 |
| A7-M8 | restore `python_files` to pytest's default; separately add a stray `scripts/test_probe.py` | the pattern test; the location test |
| A7-M9 | add `x: int = "a"` at module level or inside an **annotated** function in `agent_worker/nodes.py` (mypy does not check the bodies of unannotated functions here; a probe inside one printed an `annotation-unchecked` note and exited 0) | `uv run mypy` exits non-zero (proves the widened gate can fail) |
| A7-M10 | in `jsonld._is_event`, delete the `if not isinstance(item, dict): return False` guard (a string or number in `@graph` then raises `AttributeError` on `.get`) | C2a |

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
- **The range half of the act splitter's id filter** (`act_split.py:104`): redundant by construction, so unobservable (C1 note, A7-PR1-2).
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
- **A worktree has no `.env`.** Copy `apps/api/.env` into it before the first run, or every test fails at import with
  `model_name Field required` (A7-PR1-10).
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
3. Write C1–C6 (eight tests). They pass at once; watch each go red under its mutation (M1–M7 and M10), restore, record. M1's range half is the one mutation that cannot go red (below).

### 2. The collection setting (written)

`pyproject.toml`: `testpaths = ["app", "agent_worker"]`, `python_files = ["test_*.py"]`, and the comment above it rewritten as a
why-comment (the old one says "A7 widens the rest" and describes the workaround). Expect **the same 883 items** plus the new
ones, the guard green, and `local_test.py` not imported (probe it once, M8, then remove the probe).

### 3. The mypy gate (written)

Fix the 75 errors as follows (all CONFIRMED on a scratch copy: mypy 0 errors in 103 files, ruff clean, 868 passed, 15 skipped):

| Where | Errors | Cause | Fix |
|---|---|---|---|
| `eval/run_eval.py:199–206` | 56 | `flag = {...}` infers `dict[str, object]`, so `**flag` matches no `add_argument` parameter | `flag: dict[str, Any] = {...}` (`Any` is already imported) |
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

Per D2 option B: a `Proves:` comment on `test_health.py::test_health` and the 13 tests in `test_routers.py`. Snapshot both files
first, compare syntax trees ignoring comments and docstrings afterwards (the `AGENTS.md` pattern), then run the suite. (Option
A: `test_health.py` only, plus one sentence in A1b's build-plan bullet: "tests it writes or migrates carry `Proves:`".)

### 5. Coverage target (written; per D1)

Option A: `coverage` in the dev group (`uv add --dev coverage`, which updates `uv.lock`), the `[tool.coverage.*]` block, the
`make coverage` target and its `help` line, and `.coverage` / `htmlcov/` in `.gitignore`. Run it once and record the totals in
the Implementation log so the figures in "Context" are the figures on the merged tree.

### 6. Docs and bookkeeping (written)

- `docs/dev/alpha-build-plan.md` §5 A7: tick the boxes with the evidence above; add the "Plan and review" paragraph as A2–A6
  have; under D2 option A only, add the "tests it writes or migrates carry `Proves:`" sentence to A1b's bullet. Leave the G14/G15 rows of the gap table as the historical inventory, but the A7
  paragraph says G15's "~11" was 75.
- `docs/dev/conventions.md`: the `A7` row in the scope table.
- `apps/api/AGENTS.md`: Commands (`uv run mypy`), replace the "held to a lower bar" paragraph, `ScriptedClient` →
  `scripted_client()` / `ScriptedCompletions`, and one line on naming test modules `test_*.py`.
- `agent_worker/tests/fakes.py`: the docstring sentence "It is the fake model client that milestone A7 plans, in the one shape
  A3 needs" becomes a statement of what it is, and the stale `ScriptedClient` on `fakes.py:5`, `test_graph.py:7` and
  `test_graph_audit.py:4` (module docstrings) becomes `scripted_client()` / `ScriptedCompletions` (A7-PR1-6).
- `agent_worker/local_test.py:9`: its docstring says "(Not collected by pytest: `pyproject.toml` scopes `testpaths`.)" Once Step 2
  lands that is false; the reason becomes "`python_files` is `test_*.py`" (A7-PR1-5). A comment-only edit.
- `docs/dev/env-setup.md:230`: a dated `[UPDATE OCT 20]` note after "widen the scope once that settles".
- `docs/dev/notes.md`: the `*_test.py` / zero-item-module entry (Known gotchas, above).
- `.github/workflows/ci.yml`: step 3.

## Critical files

| File | Change |
|---|---|
| `apps/api/pyproject.toml` | `testpaths`, `python_files`, `[tool.mypy] files`, comments; D1: `coverage` dev dependency and `[tool.coverage.*]` |
| `apps/api/app/tests/test_pytest_config.py` (new) | The collection guard |
| `apps/api/agent_worker/tests/` | C1–C6 added to `test_act_split`, `test_jsonld`, `test_status_check`, `test_normalize`, `test_reconcile_removal`, and the fetch tests' file; the typing edits in `reconcile_support`, `test_validation`, `test_reconcile_shows`, `test_commit_ops`, `test_graph_audit`, `test_commit_db`; docstrings in `fakes.py`, `test_graph.py`, `test_graph_audit.py` |
| `apps/api/agent_worker/local_test.py` | Docstring only: why pytest doesn't collect it |
| `apps/api/agent_worker/act_split.py` | One rename (no behavior change) |
| `apps/api/agent_worker/eval/run_eval.py` | One annotation, one ignore with its reason |
| `Makefile`, `.github/workflows/ci.yml` | `uv run mypy`; D1: `make coverage` |
| `.gitignore` | D1: `.coverage`, `htmlcov/` |
| `apps/api/app/tests/test_health.py`, `test_routers.py` | D2: `Proves:` comments (comment-only) |
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
3. M1–M10 run in a worktree and recorded in the Implementation log.
4. `make designation-check BASE=<the commit the branch started from>` exits 0.
5. The comment-only pass (step 4): syntax trees match before and after.
6. `git status` shows no `.coverage`, `htmlcov/` or `.mypy_cache` residue.
7. The draft PR's CI: the Python job's mypy step now checks both packages and must be green.

**Locally (Ari, optional; needs Docker, no Ollama):**

8. `make db-up && make check`. Expect the same suite green with the one Mongo test now running (14 skips instead of 15).
9. Deliberately add `x: int = "a"` at module level (or inside an annotated function) in a file in `agent_worker/` and run `make typecheck`: it must fail. Remove it. (Inside an unannotated function mypy only prints a note and passes.)
10. If D1 is accepted: `make coverage` and read the "Missing" column for one module you know.

## Not doing in A7

- **The pipeline evaluation against labels** (A8): scoring a full graph run, calibrating the 0.8 threshold and the retry cap,
  checking that self-reported confidence correlates with correctness.
- **The read-route rewrite** (A1b), including `test_routers.py` and the `StarletteDeprecationWarning`.
- **A coverage threshold or CI gate**, and a mutation-testing tool over the whole suite.
- **Consolidating the three model fakes.**
- **Stricter mypy** (`check_untyped_defs`, `disallow_untyped_defs`, `strict`), `scripts/` and `migrations/` in the gate, `filterwarnings = error`.
- **Committing sanitized venue fixtures so CI can run the 14 real-page tests.** That is a copyright and maintenance call for
  A8 or the hosted phase, not a testing-tooling one.
- **End-to-end browser tests.** The frontend's testing is B5's.

## Plan review

### Round 1 — Claude Opus 5.5, October 20, 2026

**Scope.** The plan as committed in `b521d14` ("A7: draft the testing implementation plan"), 431 lines. The author committed
it while this review was running; the reviewed text and the committed file are the same. Plan review only, so no code
exists yet. The `*(none yet)*` placeholder under this heading was replaced by this round.

**What was checked and how.**
- **Docs read:** `AGENTS.md` ([fill-in] tasks; Implementation plans; Conventions); `apps/api/AGENTS.md`;
  `docs/references/fastapi-style-guide.md` (Testing, Linting, Anti-patterns); build plan §1.3 (v0.1-G14–v0.1-G16), §2
  point 5, §3, §5 A7; `docs/dev/conventions.md` (scope table, forms); `docs/dev/env-setup.md:230`.
- **Code read:** `apps/api/pyproject.toml`, `conftest.py`, `Makefile` (`typecheck`, `test`, `check`), `.github/workflows/ci.yml`,
  `.gitignore`, `agent_worker/act_split.py`, `sources/jsonld.py`, `status_check.py`, `normalize.py`, `reconcile.py`
  (`listings_from`, `excluded_listing_dates`), `nodes.py` (`fetch_node`), `eval/run_eval.py:150–215`, `local_test.py`,
  `tests/fakes.py`, and every test-side mypy error site in the Step 3 table.
- **Reproduced, in a throwaway `git worktree` of `bc1308c` (with `apps/api/.env` copied in; removed afterwards):**
  - Baseline `REQUIRE_DB=1 uv run pytest`: **868 passed, 15 skipped**; `--collect-only`: **883**. CONFIRMED.
  - `uv run mypy agent_worker/`: **75 errors in 8 files** (57 `run_eval.py`, 1 `act_split.py`, 17 in six test files, per-file
    counts as in the Step 3 table); `uv run mypy app/`: clean, 31 files. CONFIRMED.
  - Branch coverage with the plan's source/omit: **98% total, 27 missed statements (15 in `agent_worker/`, 12 in `app/`), 17
    partial branches**, every missed line exactly as listed in "Context" and "What is not covered". CONFIRMED.
  - `local_test.py` with a top-level `print` probe: **not imported** under today's config; **imported** with
    `testpaths = ["app", "agent_worker"]` and default `python_files`; **not imported** once `python_files = ["test_*.py"]`;
    item count 883 in all three. CONFIRMED.
  - Every Step 3 fix applied as written, plus `files = ["app", "agent_worker"]`: `uv run mypy` **no issues in 103 source files**,
    `ruff check .` clean (with `StoredShow` placed between `StoredLineupEntry` and `night_sort_key`), suite **868 passed, 15
    skipped**, parametrize ids `[15.0-None]` / `[None-10.0]`; `uv run mypy <one file>` checks only that file. CONFIRMED.
  - Counts: 583 test functions, 14 without `Proves:` (exactly `test_health` + 13 in `test_routers.py`, via an AST scan),
    29 `# type: ignore` in `app/` + `agent_worker/`, `ScriptedCompletions`/`scripted_client` in 11 test modules plus
    `reconcile_support.py`, `coverage` absent from `uv.lock`. CONFIRMED.
  - The guard test's pattern check, the C1 mutations, the C3 fallback and the M9 probe: see findings 1, 2, 8, 9.

**Counts.** 0 blocker, 5 should-fix, 6 nit.

**Verdict: proceed after fixes.** The measurements in "Context" all reproduce, and the mypy work is exactly as described. The
should-fixes are in the tests-first proof: one guard test that is not red today, one mutation that can't fail, one new test
with no mutation, and the D2 scenario put to Ari. No `TODO(Ari)` gap is the right call: every remaining item is
configuration, bookkeeping or a pinning test, and none of them is where a concept lives.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | `test_the_file_pattern_matches_only_test_modules` is **green on today's config**, not red. As specified it walks ".py under `testpaths`", and today's `testpaths` is `["app", "agent_worker/tests"]`, which doesn't contain `agent_worker/local_test.py`. Test approach row 1 and Step 1.2 ("confirm … is red and names `local_test.py`") both rely on the red. Fix: walk the same tree as the location test (`pytestconfig.rootpath`, minus `.venv`/hidden/`__pycache__`) and assert no file whose name matches an effective `python_files` glob is named anything but `test_*.py`. That is red today (`local_test.py` matches `*_test.py` anywhere), green after, and it no longer depends on `testpaths`, so it also catches a future widening of `testpaths` alone. | CONFIRMED: a scratch test implementing the plan's wording in `app/tests/` printed `TESTPATHS ['app', 'agent_worker/tests'] PATTERNS ['test_*.py', '*_test.py']` and **passed** on `bc1308c`. | The build's first tests-first step fails its own check, and the build either rewrites the test ad hoc or records a guard that was never seen red. | **Fixed.** The pattern check now walks the same tree as the location test (`pytestconfig.rootpath`, minus `.venv`/hidden/`__pycache__`), not `testpaths`, so it is red on today's config and also catches a later widening of `testpaths` alone (Test approach §1, with the reason recorded). Step 1.2 is now true as written. |
| 2 | should-fix | **A7-M1's first mutation can't turn C1 red.** Dropping `0 <=` (or the `< len(titles)` bound) in `act_split.py:104` leaves every output unchanged: `by_id` is read only through `by_id.get(i)` for `i in range(len(titles))`, so an out-of-range id stored in it is never read. The range filter is unobservable; only `and item.id not in by_id` (first answer wins) is. Fix: say so in C1 and M1 (the range half is pinned by C1's assertions but is not mutation-provable, because the alignment loop already ignores those ids), keep the duplicate mutation, and list the range check under "What is not covered" as redundant-by-construction. Don't change production code for it in A7. | CONFIRMED: a C1-shaped test (three titles, ids `-1` and `3`, a repeated id 0 with different acts, id 1 skipped) **passed** with `0 <=` removed and with `< len(titles)` removed, and **failed** with `and item.id not in by_id` removed. | The build records "each mutation turns it red" for a mutation that survives, or spends time hunting a test that can't exist. | **Fixed.** C1 gets a note that the range half is redundant by construction; A7-M1 is the duplicate-id mutation only (with a line saying the bound mutation is not valid); the range check is listed under "What is not covered". No production change. |
| 3 | should-fix | **C2a has no mutation, and the count is off.** The Test approach says the new tests are "proved able to fail by mutation instead (M1–M7)" and "each mutation turns exactly its test red", but M1–M7 map to C1, C2c, C2b, C3, C4, C5, C6: nothing breaks `_is_event`'s `isinstance(item, dict)` guard (`jsonld.py:67–68`). Fix: add a mutation (delete that guard; a string or number in `@graph` then raises `AttributeError` on `.get`) and renumber or append it. Also reconcile "seven unpinned rules" (Context point 3, the delivers table, Departure 4) with what is listed: six rule groups, eight tests (C1, C2a–c, C3–C6). | CONFIRMED (table read against §2's C-list); the proposed mutation's effect is PLAUSIBLE (`str.get` doesn't exist). | One new test is never shown able to fail, which is the standard build plan §3 and A6's mutation table set. | **Fixed.** A7-M10 added for C2a (delete `_is_event`'s `isinstance(item, dict)` guard); the Test approach row, Step 1.3, Verification step 3 and the Designations paragraph now say M1–M10. The count is reconciled to "six groups, eight tests" in Context, the delivers table, Departure 4, D1, the Test approach and the §2 heading. |
| 4 | should-fix | **D2's scenario misdescribes `test_routers.py`.** It says the 13 tests' "expected values … come from `sample_data`, which is exactly what A1b removes", and that comments would be "written against behavior A1b is about to replace". The module docstring says the opposite: the tests deliberately avoid data and pin "the behavior that A1b must not break when it swaps the bodies for real queries: the URLs, the filter semantics, and the error codes". Several are data-free (`test_non_integer_id_is_422`, `test_invalid_ranges_are_rejected`, `test_openapi_exposes_the_response_schemas`, the envelope test); a few use sample ids (`/shows/2`, artist 1 third on a bill). Fix: restate the scenario accurately (A1b changes the client and some fixture ids, not what most of these tests prove), and re-weigh A vs B for Ari on that basis. The recommendation may well stay A. | CONFIRMED: `app/tests/test_routers.py:1–13` and the 13 test bodies. | Ari decides D2 on a reason that doesn't hold; under B he'd be told the comments are wasted when most would carry over to A1b unchanged. | **Fixed.** D2's scenario restated from `test_routers.py`'s own docstring (most of what it pins survives A1b; a few tests use sample ids). With that, I changed the recommendation from A to **B** (all 14 now), and updated the decision table, the header sentence, Step 4, Step 6 and Critical files to match. Ari's choice is still open; A stays described as safe. |
| 5 | should-fix | **`local_test.py`'s docstring becomes false** and isn't in Step 6 or Critical files: "(Not collected by pytest: `pyproject.toml` scopes `testpaths`.)" After Step 2 `testpaths` covers `agent_worker/` and the reason is `python_files`. Fix: add it to Step 6 (one sentence: not collected because `python_files` is `test_*.py`, A7). `conftest.py`'s "from A7, agent_worker/" stays true. | CONFIRMED: `agent_worker/local_test.py:9`. | The one file the setting exists to protect states the wrong mechanism, so a future reader "simplifying" `python_files` back to the default has the comment on their side. | **Fixed.** Step 6 and Critical files now list `local_test.py:9`'s docstring (comment-only edit: the reason becomes `python_files`). |
| 6 | nit | The stale `ScriptedClient` name is in three more places than Step 6 lists: `fakes.py:5` (the sentence before the one Step 6 rewrites), `test_graph.py:7` and `test_graph_audit.py:4` (module docstrings). Add them to the `ScriptedClient` correction in Step 6 and Critical files. | CONFIRMED: `grep -rn ScriptedClient` over `.py`/`.md`. | The rename lands half-done, and Context's "no such name exists" is still contradicted in the tests. | **Fixed.** Step 6 lists `fakes.py:5`, `test_graph.py:7` and `test_graph_audit.py:4`; Critical files lists the three files' docstrings. |
| 7 | nit | Name and line slips the build will trip over: the JSON-LD price helper is `_offer_price`, not `_price` (C2b, A7-M3); `IMAGE_SUFFIXES` is used at `nodes.py:145`, `:161` and `:176`, and A7-M7 means only the `fetch_node` one at `:145`; the 56 `run_eval.py` errors are at lines 199–206 (eight calls), not 200–206; the existing `listings_from` test is in `test_reconcile_removal.py`, so C5 may sit better there than in `test_reconcile_shows.py`. | CONFIRMED: `jsonld.py:163`, `nodes.py` grep, the mypy output by line, `test_reconcile_removal.py:21,162`. | Small: a misnamed mutation target or an M7 applied to the wrong branch (the extract-side ones change a different test). | **Fixed.** `_offer_price` in C2b and A7-M3; A7-M7 names `nodes.py:145` and says `:161` and `:176` are other tests'; the `run_eval.py` row reads 199–206; C5 moved to `test_reconcile_removal.py` (Critical files updated). The typing edit stays in `test_reconcile_shows.py` (Step 3 table). |
| 8 | nit | **C3's fallback is a substring test.** `_on_page` checks `fold_text(a) in fold_text(page_text)`, so `["MO"]` is "on the page" of "Oct 24: Lizzo at the Armory" (`armory` contains `mo`). C3's "absent → false" text must contain no occurrence of the short name inside any word, and the test should say it pins substring semantics (or the plan should record that this is a known looseness, not pin it as word matching). | CONFIRMED: `_on_page(['MO'], 'Oct 24: Lizzo at the Armory')` → `True`; `_on_page(['U2'], 'Oct 24: Lizzo')` → `False`. | A natural-looking "absent" page makes C3 fail on correct code, or the test's comment claims a word match the code doesn't do. | **Fixed.** C3's row now says the fallback is a substring test (`['MO']` is on the page of "…at the Armory"), that the test pins that and says so in its comment, and that the "absent" text must hold no occurrence of the name inside any word. |
| 9 | nit | **A7-M9 and local Verification step 9 need an annotated function.** mypy doesn't check the bodies of unannotated functions here (no `check_untyped_defs`), so `x: int = "a"` inside an unannotated `def` prints a note and exits 0. Say "in an annotated function (or at module level)". The same limit bounds D3 option A: an unannotated test (`test_health` has no `-> None`) isn't type-checked by the widened gate; worth one clause in D3. | CONFIRMED: a probe file with the line in an unannotated and an annotated function gave one `annotation-unchecked` note and one `[assignment]` error. | The mutation that proves the gate can fail passes by accident, or Ari's local check looks like a broken gate. | **Fixed.** A7-M9 and local Verification step 9 say module level or an annotated function, with the reason; D3 gets a bullet on the limit (unannotated bodies, `test_health`), and "Not doing" names `check_untyped_defs`. |
| 10 | nit | The worktree protocol (Test approach §4, Known gotchas) should also say to copy `apps/api/.env` into the worktree: it's gitignored, and `Settings()` fails at import without it (nothing in the cloud shell's environment sets `DATABASE_URL`/`MODEL_NAME`). `uv` creates the worktree's own `.venv` on first run. | CONFIRMED: with `.env` moved away, `pytest app/tests/test_health.py` fails with `model_name Field required`. | The first mutation run fails for an unrelated reason. | **Fixed.** The worktree protocol (Test approach §4) and Known gotchas both say to copy `apps/api/.env` in and that `uv` creates the worktree's `.venv`. |
| 11 | nit | D1's reason for the `.coverage` line is imprecise: the existing `.gitignore` `coverage` pattern matches any file *or* directory named `coverage`; it misses `.coverage` because the name differs, not because it only matches directories. The conclusion (add `.coverage`) is right. | CONFIRMED: `git check-ignore -v apps/api/coverage` matches `.gitignore:16`; `apps/api/.coverage` does not. | None beyond a wrong sentence in the record. | **Fixed.** D1's sentence now says the existing pattern matches a file or directory named exactly `coverage`, not `.coverage`. |

**Rejected:** none. All 11 findings were reproduced by the reviewer (CONFIRMED) and are accepted.

**Resolution notes.** The one change to what Ari is asked: D2's recommendation moved from A to B (finding 4). The other fixes are local to the test approach, the mutation table and the doc steps, and add no step. I did not re-run the reviewer's scratch experiments; the edits change wording and step lists, not any measured fact. A round 2 is not warranted: nothing was rejected or reworked.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 20, 2026

**Scope.** Diff base **`e52ec4c`** (the plan with its review round and resolution, the commit before the build began).
Commit range `e52ec4c..HEAD`, six commits, one per plan step: `bc5ce0b` (step 1, tests first), `1a64894` (2, collection
setting), `2d319c1` (3, mypy gate), `8ac991a` (4, `Proves:` pass), `630f584` (5, coverage target), `dc98f05` (6, docs). The
reviewer's scope is the committed tree; `git diff e52ec4c..HEAD` is 31 files, +493 −43 (the `uv.lock` change is +86 for one
package). Files touched, by area:
- **Config and CI:** `apps/api/pyproject.toml` (`testpaths`, `python_files`, `[tool.mypy] files`, `[tool.coverage.*]`,
  `coverage` dev dependency), `apps/api/uv.lock`, `Makefile` (`typecheck`, new `coverage` target, `clean`),
  `.github/workflows/ci.yml` (mypy step), `.gitignore`.
- **New test file:** `apps/api/app/tests/test_pytest_config.py` (3 tests).
- **New coverage-gap tests:** `test_act_split.py` (C1), `test_jsonld.py` (C2a–c), `test_status_check.py` (C3), `test_normalize.py`
  (C4), `test_reconcile_removal.py` (C5), `test_extraction.py` (C6).
- **Typing edits (tests):** `reconcile_support.py`, `test_validation.py`, `test_reconcile_shows.py`, `test_commit_ops.py`,
  `test_graph_audit.py`, `test_commit_db.py`.
- **Production code:** `agent_worker/act_split.py` (one rename, `item` → `answered`), `agent_worker/eval/run_eval.py` (one
  annotation, one `# type: ignore[arg-type]` with its reason). Nothing else in `app/` or `agent_worker/` outside `tests/`.
- **Comment-only:** `app/tests/test_health.py` and `test_routers.py` (`Proves:` comments, 14 tests); docstrings in
  `agent_worker/local_test.py`, `tests/fakes.py`, `tests/test_graph.py`, `tests/test_graph_audit.py`.
- **Docs:** `docs/dev/alpha-build-plan.md` (A7 section), `docs/dev/conventions.md`, `docs/dev/env-setup.md`,
  `docs/dev/notes.md`, `apps/api/AGENTS.md`, and this file (Status, Approval).

**Departures from the plan.**
1. **Commits.** The `build-milestone` skill says not to commit unless Ari asks; the repository's stop hook asks for work to
   be committed and pushed to the session branch, and the plan said "one commit per numbered step". So the steps are six
   commits on `claude/adoring-maxwell-7i6de2`, and the reviewer gets the commit range. Nothing is merged and no PR is open.
2. **Counts differ from the plan's by the new test file.** mypy checks **104** files (the plan's 103 plus
   `test_pytest_config.py`). Items collected: **896** = 883 + 13 (3 guard tests, 8 gap-test functions, +2 from parametrized
   cases in C2c and C4). Test functions: 594 (583 + 11).
3. **`run_eval.py` got a two-line comment** on the `flag: dict[str, Any]` annotation (the plan said "annotate"); and the
   `# type: ignore[arg-type]` has to sit on the line with the `extraction=result` argument (mypy reports the argument's line),
   so the call stays on one line.
4. **A7-M8 and A7-M9 were run as described, with two details.** M8's regression was tried on a worktree copy of the final
   `pyproject.toml` with the `python_files` line deleted; M9's probe was at module level (`PROBE_M9: int = "a"` appended to
   `nodes.py`), the form the plan's review allowed.
5. **D2 = B** (decided by Ari), so A1b's bullet in the build plan is unchanged (the sentence was option A's).
6. **The build plan's A7 section says "in code review, awaiting sign-off"** and has an unticked `Sign-off — Ari` line, to be
   changed when Ari signs off.
7. **The mutation runner is not in the repo.** It was a throwaway script in the session scratchpad; its results are below.

**`TODO(Ari)` gaps.** None. Every A7 item is [written] (plan, "Settled details"). Nothing is open for Ari to fill.

**Verification** (cloud sandbox: Postgres up, no MongoDB, no Ollama, no gitignored fixtures; Node 22, CI uses 24):
- **Baselines before any change:** `REQUIRE_DB=1 uv run pytest` 868 passed, 15 skipped; `uv run mypy agent_worker/` **75 errors
  in 8 files**; `uv run mypy app/` clean (31 files); ruff clean. As the plan said.
- **Tests first:** the guard's pattern test was **red** on the old config, naming `agent_worker/local_test.py (matches
  '*_test.py')`; the other two passed. The eight gap tests passed at once and were proved able to fail by mutation, in a
  throwaway worktree (removed afterwards, `apps/api/.env` copied in), each turning exactly its test red and nothing else:

  | # | Mutation | Test that went red |
  |---|---|---|
  | A7-M1 | `act_split`: drop `and item.id not in by_id` | `test_the_first_answer_for_an_id_wins_and_ids_outside_the_range_are_ignored` |
  | A7-M1 (range) | `act_split`: drop both bounds | **stayed green**, as the plan's review (A7-PR1-2) said it would |
  | A7-M2 | `jsonld._end_time`: delete the zone-mismatch return | both cases of `test_an_end_whose_zone_differs_from_the_starts_is_not_taken` |
  | A7-M3 | `jsonld._offer_price`: `continue` → `return None` | `test_an_unparseable_offer_price_is_skipped_for_the_next_offer` |
  | A7-M4 | `status_check._on_page`: fallback `return True` | `test_an_answer_with_only_short_names_is_added_only_if_the_page_contains_them` |
  | A7-M5 | `normalize_time`: delete the non-string raise | both cases of `test_a_time_that_is_not_text_is_refused_with_a_value_error` |
  | A7-M6 | `listings_from` / `excluded_listing_dates`: delete each `None` guard (two runs) | `test_no_extraction_or_no_validation_means_no_listings_and_no_protected_dates` (both runs) |
  | A7-M7 | `fetch_node` (`nodes.py:145`): `if False:` for the image branch | `test_fetch_node_reads_a_local_image_as_base64_and_leaves_the_html_unset` |
  | A7-M10 | `jsonld._is_event`: delete the `isinstance(item, dict)` guard | `test_a_non_object_entry_in_a_block_is_skipped_not_fatal` |
  | A7-M8a | `python_files` back to the default | `test_the_file_pattern_matches_only_test_modules`; and an import probe printed once (imported) under it, zero times under the built config |
  | A7-M8b | a stray `scripts/test_probe.py` | `test_every_test_module_is_inside_a_test_path` |
  | A7-M9 | `PROBE_M9: int = "a"` appended to `nodes.py` | `uv run mypy` exits non-zero: `nodes.py:350 ... [assignment]` |

- **mypy:** `uv run mypy` → **no issues in 104 source files** (was 75 errors); `make typecheck` (mypy + `next typegen` and
  `tsc`) green.
- **`make check BASE=e52ec4c`, exit 0:** ruff clean; mypy 0/104; pytest **881 passed, 15 skipped** (the one Mongo test and 14 real-page
  tests skip here); Vitest 337 passed; `make contract-check` "current"; `make designation-check BASE=e52ec4c` exit 0.
- **Comment-only passes verified by syntax trees** (docstrings and comments ignored, snapshot before, compare after): step 4
  (`test_health.py`, `test_routers.py`) and the four docstring edits in step 6 (`local_test.py`, `fakes.py`, `test_graph.py`,
  `test_graph_audit.py`): all match. A scan of all 594 test functions finds **0 without `Proves:`** (was 14).
- **`make coverage`:** 99% total, **17 missed statements (was 27) and 9 partial branches (was 17)**; what is still missed is
  exactly the list under "What is not covered". No `.coverage` or `htmlcov/` residue in `git status` (ignored).
- **Not verified here:** the draft PR's CI (the Python job's mypy step now runs a bare `uv run mypy`; `ci.yml` parses as
  YAML), a local run with Docker up (14 skips instead of 15), and `make coverage` on Ari's machine.

**Where to look hardest.**
1. **`app/tests/test_pytest_config.py`:** is the walk's skip-list right (hidden directories, `node_modules`, `__pycache__`)? The
   pattern test deliberately walks all of `apps/api`, not `testpaths`; it would flag any future `*_test.py` helper module outside
   `tests/` too. Is that the right strictness?
2. **The `Proves:` comments in `test_routers.py`.** I wrote them from the tests and the contract; two make claims about future
   work ("A1b's seed must leave 999 and 99 unused", "A1b's ORDER BY must keep" the untimed-last rule). The ordering rule is the
   router's own (api-contract.md has no ordering section), so check I haven't overstated it.
3. **C3 pins the substring looseness** of `_on_page`'s fallback (`['MO']` passes against "…at the Armory"). That was in the plan
   (A7-PR1-8), but a test that asserts a known weakness could be read as endorsing it; the comment says it doesn't.
4. **`reconcile_support.py` asserts** (three `assert … is not None`): they add failure modes to a helper many tests share. The
   suite is unchanged, but a reviewer should confirm each invariant (an insert carries its listing; an update or removal names
   a stored show) holds for every caller.
5. **The `pyproject.toml` comments** (they are the only record, in code, of why `python_files` is narrowed), and the build
   plan's A7 paragraph (its numbers: 881/15, 896, 104, 99%, 17 and 27).
6. **The mypy gate's limit** (unannotated bodies unchecked): documented in `pyproject.toml` and `apps/api/AGENTS.md`, not fixed.

## Code review

### Round 1 — Claude Opus 5.5, October 20, 2026

**Scope.** Implementation log round 1: `git diff e52ec4c..HEAD` on `claude/adoring-maxwell-7i6de2` (HEAD `132ae29`; the six step
commits `bc5ce0b`..`dc98f05` plus the log commit), 31 files. Read in full: every changed file except `uv.lock` (checked with
`uv lock --check` and by its one new package, `coverage 7.16.2`). No `TODO(Ari)` gaps exist, so none is reported.

**What was checked and how.**
- **Docs read:** root `AGENTS.md` (Conventions; Implementation plans); `apps/api/AGENTS.md`; `docs/references/fastapi-style-guide.md`
  (Testing, Anti-patterns); `docs/dev/api-contract.md` §2–§5 (for the router `Proves:` citations); `docs/dev/conventions.md`;
  the A7 section of `alpha-build-plan.md`; this plan in full, including plan review round 1 and the Implementation log.
- **`make check BASE=e52ec4c` on the branch:** exit 0. ruff clean; `uv run mypy` **no issues in 104 source files**; pytest
  **881 passed, 15 skipped**; Vitest 337 passed; contract "current"; `make designation-check BASE=e52ec4c` exit 0. CONFIRMED.
- **In a throwaway `git worktree` of HEAD** (`apps/api/.env` copied in; removed afterwards, `git worktree list` shows only the
  main tree), one pytest at a time:
  - **Baseline:** with `apps/api` checked out at `e52ec4c`, `uv run mypy agent_worker/` → **Found 75 errors in 8 files**. CONFIRMED.
  - **Mutations, each against the full suite (`REQUIRE_DB=1 uv run pytest`):** A7-M1 (drop `and item.id not in by_id`) → only C1
    red; the range-only mutation → **881 passed** (stays green, as A7-PR1-2 said); A7-M2 → both C2c cases red; A7-M3 (line 171
    `continue` → `return None`) → only C2b red; A7-M4 (fallback `return True`) → only C3 red; A7-M5 → both C4 cases red; A7-M6,
    run as two separate mutations (the `listings_from` guard, then the `excluded_listing_dates` guard) → only C5 red each time;
    A7-M7 (`if False:` for `fetch_node`'s image branch) → only C6 red; A7-M10 → only C2a red. Every one "exactly its test, nothing
    else" (880 or 879 passed beside it). CONFIRMED.
  - **A7-M8a** (delete the `python_files` line) → the pattern test red, naming `agent_worker/local_test.py (matches '*_test.py')`;
    **A7-M8b** (`scripts/test_probe.py`) → `test_every_test_module_is_inside_a_test_path` red; **A7-M9** (`PROBE_M9: int = "a"`
    appended to `nodes.py`) → `uv run mypy` exit 1, one `[assignment]` error. CONFIRMED.
  - `uv run pytest --collect-only` → **896 tests collected**; the only non-`tests/` matches for `test_*.py` / `*_test.py` /
    `conftest.py` in `apps/api` are the root `conftest.py` and `local_test.py`. CONFIRMED.
  - **`make coverage`:** 881 passed, 15 skipped; **TOTAL 2518 statements, 17 missed, 9 partial branches, 99%**; the missed lines
    are exactly `main.py:187–193,197,201`, `calendar_writer.py:226`, `app/main.py:44–46`, `sample_data.py:241,256`,
    `testing/db.py` (7), and the four partials named in "What is not covered". `.coverage` shows as ignored (`!!`). CONFIRMED.
- **Comment-only edits, by AST comparison with docstrings stripped** (a scratch script, not in the repo): `test_health.py`,
  `test_routers.py`, `local_test.py`, `fakes.py`, `test_graph.py` (`e52ec4c` vs HEAD), `test_graph_audit.py` (`dc98f05~1` vs
  `dc98f05`, since step 3 also typed it) and `test_routers.py` (`8ac991a~1` vs `8ac991a`): **all MATCH**. `act_split.py` differs,
  as it should (the rename). CONFIRMED.
- **`Proves:` scan** (AST, every `test_*` function in `app/` and `agent_worker/`): **594 functions, 0 missing**. CONFIRMED.
- **"Where to look hardest":** (1) the walk's skip list: see finding 5; the strictness of flagging any `*_test.py` anywhere is
  right (it is the convention `apps/api/AGENTS.md` now states). (2) the router comments: finding 2; "999 and 99 are above every
  id" holds (max show/venue/artist ids in `sample_data` are 26/4/10), and the untimed-last rule is the router's own
  (`shows._ordering`'s docstring), not overstated as a rule, only uncited. (3) C3: finding 1. (4) the three `reconcile_support`
  asserts: every `ShowDecision` construction in `reconcile.py` was read: inserts come only from `plan_for_listing.decide`,
  which always passes `listing=listing`; updates and removals always pass `stored_id=stored.id` / `show.id` (`StoredShow.id:
  int`); the two hand-built `ShowDecision`s in tests (`test_audit_entries.py:54`, `test_reconcile_audit.py:40`) never reach
  `apply_plan`. The invariants hold. CONFIRMED. (5) `pyproject.toml` comments are accurate; the build-plan numbers check out
  except one word (finding 3). (6) the gate's limit: four unannotated functions remain outside it (`app/main.py` `health`,
  `health_db`; `test_health`; `test_commit_ops.a_mixed_plan`), consistent with "Not doing". Not a finding.
- **Anti-patterns table:** no DB mocks added, no `TestClient`→async change, no production `assert`; the new `# type: ignore`
  carries its reason. Nothing applies.

**Counts.** 0 blocker, 0 should-fix, 5 nit.

**Verdict: proceed.** Every number in the log reproduces (75 → 0 mypy errors on 104 files, 881/15, 896 collected, 594 functions,
17/9 coverage), every mutation turns exactly its test red, and the comment-only edits are comment-only. The nits are wording and
one edge of the location guard.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | nit | **C3 pins the substring looseness, but the code still claims the opposite.** `_on_page`'s docstring says it is "the check that keeps a status answer from ever adding a show the page doesn't list", and C3's third case now asserts that it *does* add one (`['MO']` against "…at the Armory"). The looseness is recorded only inside a test. For a two-letter name it guards almost nothing: "mo" is in "more", "month", "Mortimer's". Fix (comment-only): a sentence in `_on_page`'s docstring saying the short-name fallback is a substring test, plus where the follow-up lives if Ari wants one (A8 or H1). | CONFIRMED: `status_check.py:93–101` (docstring and fallback); A7-M4 run above; `normalize.identifying_words` keeps words of three letters or more. | A reader of `status_check.py` trusts a guarantee the code doesn't give, and the only record of the gap is a test that will look "wrong" to whoever fixes the fallback. | **Fixed.** `_on_page`'s docstring now says the short-name fallback is a substring test ("mo" is on the page of "more", "month", "Armory"), that C3 pins it as it is, and that tightening it to whole words is a follow-up for A8 or H1. Docstring only; syntax trees match. |
| 2 | nit | **Two router `Proves:` comments cite a source that doesn't state the rule.** `test_invalid_ranges_are_rejected` says "(api-contract.md §2)", but §2 states no 422 for an end before the start and mentions `MAX_RANGE` only for `upcoming=true`. The rules are `app/routers/shows.py:105–111`. `test_shows_are_ordered_by_date_then_time` says "A1b's ORDER BY must keep" the untimed-last rule and cites nothing; its source is `shows._ordering`'s docstring. Fix: cite the router (and, for ordering, `_ordering`) in place of, or beside, the contract. | CONFIRMED: `api-contract.md:27–56` read; `grep -n "422\|MAX_RANGE" docs/dev/api-contract.md` matches only lines 47–48 (the `upcoming` paragraph). | A1b reads these comments as the spec and goes looking in the contract for a rule that isn't there. The convention is "cite the source of a decision". | **Fixed.** `test_invalid_ranges_are_rejected` now cites the router (`app/routers/shows.py`'s two 422 checks) and says the contract mentions `MAX_RANGE` only for `upcoming=true`; the ordering test cites `shows._ordering`'s docstring. Comment-only; syntax trees match. |
| 3 | nit | The build plan's A7 paragraph says "pin **eight unpinned rules**"; the bullet beneath it and this plan say eight tests for **six** rules. | CONFIRMED: `alpha-build-plan.md:254` vs `:262`. | A wrong count in the record, which A7-PR1-3 had already reconciled once in the plan. | **Fixed.** `alpha-build-plan.md`'s A7 paragraph reads "six unpinned rules (eight tests)". |
| 4 | nit | **The "Decisions for Ari" table still reads `Open`** for D1–D3, though "Approval" records all three as decided (Ari, October 20). A6's table was updated to "**Decided A** (Ari, Oct 20)". Fix: set the Status column to Decided A / Decided B / Decided A. | CONFIRMED: this file, lines 103–105 and the "Approval" section; `a6-commit.md:112–114`. | Someone skimming the table (or the sign-off) sees three open decisions on a milestone that is built. | **Fixed.** The decision table's Status column reads Decided A / Decided B / Decided A (Ari, Oct 20). |
| 5 | nit | **The location guard doesn't model pytest's `norecursedirs`.** pytest skips directories named `build`, `dist`, `venv`, `*.egg` (and others) by default, so a `test_*.py` under, say, `agent_worker/build/` is inside `testpaths`, passes the guard, and is never collected. Fix: in `uncollected` (or the walk), treat a file whose path has a part matching any `pytestconfig.getini("norecursedirs")` glob as uncollected, and add that case to the negative control. | CONFIRMED in the worktree: `agent_worker/build/test_probe.py` holding a failing test → `test_pytest_config.py` 3 passed, and `--collect-only` lists no `build/test_probe`. | Narrow (a directory with one of those names inside a package is unlikely), but it is exactly the "silently never run" failure the guard exists for, and the guard's docstring promises it can't happen. | **Fixed, test first.** The negative control gained a `build/` case with `norecursedirs` and was red (`TypeError`: no such parameter); then `uncollected` gained a `norecursedirs` parameter, the location guard passes `pytestconfig.getini("norecursedirs")`, and its docstring and `Proves:` say so. With a probe `agent_worker/build/test_probe.py` the location guard is now red (A7-M11); probe removed. |

**Rejected:** none. All five nits were reproduced or confirmed by the reviewer and are accepted.

**Test-suite result after the fixes:** `make check BASE=e52ec4c` exit 0: ruff clean; `uv run mypy` no issues in 104 source files; pytest **881 passed, 15 skipped** (same count as before the fixes: finding 5 extended an existing test, it added none); Vitest 337 passed; `make contract-check` current; `make designation-check BASE=e52ec4c` exit 0. Comment-only edits (findings 1 and 2) checked by syntax trees, docstrings ignored: `status_check.py` and `test_routers.py` match. A7-M11 (a probe `test_*.py` under `agent_worker/build/`) turns `test_every_test_module_is_inside_a_test_path` red; the probe was removed. Not re-run: the other mutations (the code under them did not change).

Round 2 is not warranted: 0 blocker and 0 should-fix, nothing rejected or reworked.

## Approval

**For Ari to decide before approving:** D1, D2 and D3 above. Also veto-or-accept the Settled details, in particular: narrowing
`python_files` (a manual script can no longer be named `*_test.py` *and* be collected, which is the point), the single new
`# type: ignore`, and leaving the two other model fakes alone.

**Ari, October 20, 2026: approved the plan** ("The implementation plan is approved. I accept the recommendations on all 3
decisions."), then ran `/build-milestone`, which set the status to `Approved` at step 0. Decided as recommended: **D1 = A** (a
report-only coverage target), **D2 = B** (all 14 older tests get a `Proves:` comment now; revised from A in plan review),
**D3 = A** (mypy covers tests and `eval/`). The Settled details stand as written.

**Ari, October 21, 2026: signed off. A7 is Done.** Ari ran the local verification (including the deliberate type-error check on the widened mypy gate) and flipped the milestone to Done. Code review round 1 (0 blocker, 0 should-fix, 5 nits) was resolved on October 20; no `TODO(Ari)` gaps existed.
