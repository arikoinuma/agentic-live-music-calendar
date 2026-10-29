# C5 — pipeline evaluation harness

**Status:** Awaiting sign-off
**Date:** October 29, 2026
**Author model:** Claude Sonnet 5.5 (plan, October 29, 2026; written in a cloud session)
**Approval:** Ari, October 29, 2026: accepted the recommendations on D1 to D7 and invoked `/build-milestone` (so Status went from `Awaiting approval` to `Approved` to `Code review` in one session; recorded here at code review, C5-CR1-10).
**Reviewer model:** Claude Opus 5.5 (plan review round 1, October 29, 2026; code review round 1, October 29, 2026)
**Spec:** `docs/dev/alpha-deployment-plan.md` §6 C5 (and Dep-D5, Dep-D15, Dep-D16, §5.2 "Labelling twice"); `docs/dev/alpha-build-plan.md` §5 A8
(the pointer; the items migrated to C5 and C7); `docs/dev/implementations/a2.1-extraction-reliability.md` (A2.1-D1 the tiered standard,
A2.1-D11 the labelling fill-in, A2.1-D13 the year rule); `docs/dev/implementations/a3-validation-and-retry.md` (the verdict, the
retry policy, A3-D5); `docs/dev/implementations/a4-auditability.md` (the staging document per attempt, the `ainvoke`-only graph);
`docs/dev/implementations/a5-reconcile.md` and `a6-commit.md` (what reconcile decides and commit writes);
`docs/arch/arch-initial.md` §7; `docs/references/fastapi-style-guide.md`; `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D7`, the fill-in key points `K1`–`K4` (`K1` the labelling, `K2` the
precision and recall definitions, `K3` the expected database state, `K4` which finding covers which error), and the mutation
checks `M1`–`M8`; elsewhere they are written `C5-D1`, `C5-K1`, `C5-M1` and so on (`docs/dev/conventions.md`). **Code, tests, code
comments and every other document write the scoped form, never the bare one**, and the build step copies from this file, so a
`TODO(Ari)` block cites `C5-K3`, never `K3`. Review items are `C5-PR<round>-<n>` for the plan review and `C5-CR<round>-<n>` for the
code review. Other plans' IDs carry their scope (`A2.1-D1`, `A3-D5`, `Dep-D15`, `v0.1-G6`). `C5` is a new scope: the build adds a
`C5` row to the scope table in `docs/dev/conventions.md`.

## Context

A2.1 built a scorer for **extraction**: `eval/scoring.py` counts a model's answer against hand-written labels by Ari's tiered
standard (A2.1-D1), and `eval/run_eval.py` runs `extract_page` and gates on it. That answers "can the model read a page?" It does not
answer the question the requirements actually ask, which is "does the **pipeline** put correct data in the calendar?" Between the
model and the calendar there are four layers nobody has measured end to end:

| Layer | What it can do to a correct or incorrect extraction | Measured so far? |
|---|---|---|
| **Validation** (`validation.py`, `policy.py`) | Flag an error and force a retry; repair a field (drop an unverifiable image URL); exclude a show; or let it through | Only by hand-picked unit tests and a replay of stored extractions (`test_validation_on_real_pages.py`). Never against labels |
| **The retry loop** (`graph.py`, `policy.plan_for_attempt`) | Change the request and try again, up to the cap, then escalate | Never run against real pages. `run_eval.py` calls `extract_page` only, so **no graph-level retry data exists** (deployment plan C5) |
| **Reconcile** (`reconcile.py`) | Decide insert, update, no-op, soft delete or skip, and withhold removals the guard doubts | Unit and database tests on constructed data; never on a real page's shows |
| **Commit** (`commit.py`, `calendar_writer.py`) | Write the rows, one transaction per show | Same |

C5 adds the instrument: run the real compiled graph over labelled pages and score what comes out at **three points**, the model's
raw answer, the validated extraction that reconcile receives, and the **rows left in the database**, with the same scorer and the same
labels. The differences between those three columns are the point: they say which layer helped and which one hurt. It also records
the **baseline** on the local model (`gemma4-e4b`), so C6 (a hosted model) and C7 (the threshold, the cap, the retry tier, the
confidence check) have a before to compare with.

### What C5 delivers

Items are the five in `alpha-deployment-plan.md` §6 C5, in its order. Markings follow Dep-D15 and the "Respect the marking" rule in
`AGENTS.md`; D6 asks Ari to move the gaps of the second item onto the items that carry the design weight.

| Item (deployment plan C5) | Marking | Where it lands |
|---|---|---|
| Hand-label further pages (also C6's held-out set) | **[fill-in]**, `C5-K1` | `eval/labels.py`; a `held_out` flag on `PageLabel`; a candidate-lines helper `eval/label_draft.py` |
| Promote the harness: score a **full graph run** against the labels: precision and recall on shows found, field accuracy, retry rate | **[fill-in]** as marked; its gap is `C5-K2` (D6) | `eval/graph_run.py` (one page through the graph), `eval/graph_eval.py` (the CLI, the results file, the aggregate), `eval/scoring.py` (structured errors, `headline_rates`) |
| *(added)* Score the database after two runs: inserts, updates, soft deletes | **[fill-in]** (marked by this plan, D6), `C5-K3` | `eval/db_score.py`, `eval/scratch_db.py` |
| *(added)* Validation recall | **[fill-in]** (marked by this plan, D6), `C5-K4` | `eval/validation_recall.py` |
| *(added)* Record the baseline on `gemma4-e4b` | **[written]**, **local only** | Run on Ari's laptop; numbers go in this file's Implementation log |

Everything except the labelling, the model-backed runs and the baseline is deterministic code with fake-model tests, so **the harness
is cloud-buildable**; the labels and the baseline need the gitignored fixtures and Ollama (`AGENTS.md`, "Cloud sessions"). The plan
is written in the cloud, so every fact that only the local model can produce is listed under "Unverified" below.

### Decisions already made (earlier in this project)

- **The standard is tiered and fixed** (A2.1-D1): date and acts 100%, no invented shows, other fields missing at most 1 in 10 and
  wrong never, about one non-music leak per page. `scoring.py` counts exactly these tiers and C5 reuses it unchanged; it does not
  redefine "correct".
- **Labels come from the page text, never from JSON-LD or a model's output**, each row with the `source_line` it was read from
  (`labels.py` docstring). The harness must not make this easier to violate: `label_draft.py` prints candidate lines, not answers (Step 7).
- **A returned show's identity is its date and acts** (A2.1-K2, `scoring.match_shows`); a found show with a missed time is not a
  missed show plus a fabricated one.
- **The graph is `ainvoke`-only and its stores arrive through `WorkerContext`** (A4-D1). The harness hands the real graph a real
  context; it does not call node functions one by one, or the routing, the retry loop and the audit wrapper would not be measured.
- **`main.run_venue` is the one place a venue's cycle is opened, run and closed** (A4-K1). The harness calls it rather than copying it.
- **A cancelled or postponed listing is labelled with its status** (A2.1-D12), but `ShowStatus` has only `active` and `removed`
  (`app/enums.py`) and reconcile `skip`s a cancelled listing with nothing stored (`reconcile.Action.SKIP`). So a labelled cancelled
  show is **expected to be absent** from the database; `C5-K3` has to say so.
- **At temperature 0 an unchanged request returns the same answer** (A2.1's confirmation run: five byte-identical runs;
  `PIPELINE_OPTIONS` sets `temperature=0.0`). Repeated runs of a page are therefore mostly one sample, as `run_eval`'s `runs_identical`
  already records; the harness reports the same flag and defaults to one run.
- **Fixtures and results are gitignored** (`apps/api/.gitignore`); `eval/fixtures/` holds only `.gitkeep` in a cloud checkout.
- **Dep-D16:** Ari assembles more venues and calendar URLs himself; those venues are the candidates for C5's labels.

### Departures from the plan (to apply to `alpha-deployment-plan.md` when implementing)

1. **"Promote `run_eval.py`" becomes a new module beside it** (D1). `run_eval.py` stays the extraction-level tool C6's parity and
   gate runs use; the graph-level harness is `graph_eval.py`. Both score with `scoring.py`.
2. **`PageLabel` gains `held_out`** (D3), so the pages C6 will treat as held-out can be labelled now without C5's baseline looking at them.
3. **`main.run_venue` gains an optional `policy` argument** (D5), the one production-code change, so a run can vary the threshold and the cap
   (the knobs C7 turns) without the harness copying the run lifecycle.
4. **A `C5` scope row in `docs/dev/conventions.md`**, and A8's pointer in `alpha-build-plan.md` ticked.

## Decisions for the user / reviewer

*Each has a recommendation; the plan is written as if they are accepted. D1 to D4 change what gets built or what Ari does; D5 to D7 are
small defaults to veto. Ari's answers go in the Resolution column.*

| ID | Question | Recommendation | Ari's answer |
|---|---|---|---|
| D1 | **One harness or two?** Extend `run_eval.py` with a `--graph` mode, or add `graph_eval.py` | **Two, sharing `scoring.py`.** `run_eval.py` is 728 lines, built around its own `instructor` client hook for counting parse retries, the frozen pre-A2 path and A2's reference metrics; graph runs use the pipeline's client and count retries from `attempt_history`. Bolting a second mode on would make each hard to read. The cost is two CLIs and two results formats, kept close by sharing the scorer and the file conventions (label, provenance, request record, rescore). Departs from the deployment plan's word "promote" |  **Accepted as recommended** (Ari, October 29, 2026). |
| D2 | **What the database is scored in.** A scratch Postgres database the harness creates, or in-memory fakes | **A scratch database `calendar_eval`**, created and migrated by the harness, with the real `PostgresCalendarReader`, `PostgresCalendarWriter` and `PostgresAuditWriter`; only MongoDB staging is replaced by an in-memory stager (staging is not what is scored, and it saves requiring Mongo). Fakes would measure the fake: the soft-delete window, the per-show transaction and the lineup writes are the SQL the item exists to check. The guard is the test fixtures' (name is a constant; refuse a non-local host); `eval/` cannot import `app.testing` because `test_no_testing_imports.py` scans `agent_worker/eval/`, so `scratch_db.py` carries its own ~40-line guard with its own tests. Needs `make db-up` for the Postgres part of a baseline run |  **Accepted as recommended** (Ari, October 29, 2026). |
| D3 | **Held-out pages.** C5's labels and C6's held-out set are "the same job" (§5.2), but scoring a page in C5's baseline shows its errors to whoever then edits a prompt, which is how the gated pages stopped being held-out (A2.1 code review round 2, #2) | **Add `PageLabel.held_out`. Ari marks a share of the new pages held-out (about a third, newest venues or month first). The default sets and the baseline exclude them; `--set held_out` scores them and the results file records that it did.** The first held-out scoring is then C6's, after its changes are frozen. Labelling stays "once" and the pool stays honest. Alternative: no flag, trust discipline, and re-capture a separate held-out set in C6 (labelling twice, which §5.2 warns against) |  **Accepted as recommended** (Ari, October 29, 2026). |
| D4 | **How many pages to label.** The baseline's show-level error rate is 4 in 60, about 1 in 15; C7's confidence-correlation check needs enough *errors*, not enough pages (deployment plan C7: "four errors can't support a correlation") | **Aim for roughly ten further pages, from the venues Ari assembles, with about a third held-out (D3).** Ten pages is about 150 shows and so about 10 errors at the baseline rate, still short of a statistical check (the number needed is a statistician's call, not measured here); the plan says so rather than pretend. C5's done-when does **not** depend on the count; C7's plan sizes the rest, and weakening the model's settings to produce more errors is an option it can take then. This is a labelling-effort choice only Ari can make |  **Accepted as recommended** (Ari, October 29, 2026). |
| D5 | **Vary the retry policy from the harness.** `--threshold`, `--max-attempts`; needs `run_venue(..., policy=)` | **Yes.** Two lines in `main.py` (`initial.model_copy(update={"policy": policy})`) and a test; without it C7 would reimplement the run lifecycle to turn the knobs `RetryPolicy` already exposes ("A8 varies them by passing a different policy", `policy.py`). It also lets a baseline *provoke* the retry loop (a threshold of 0.99 makes low confidence fire), because at temperature 0 on pages the model reads correctly the loop may simply never run, and "0 of N runs retried" is a result but not a measurement of the loop. **Limit:** `aggregate_confidence` returns `None` for the JSON-LD source and `combine` skips `None` (`validation.py:444-457`, `policy.py:137`), so a high threshold provokes retries on **model-route and image pages only**; the provoked retry rate is reported for those routes, never as the whole set's. The policy is built with `dataclasses.replace(DEFAULT_POLICY, ...)` so the configured escalation model is kept |  **Accepted as recommended** (Ari, October 29, 2026). |
| D6 | **Re-mark the second item.** Its three named quantities (precision and recall, field accuracy, retry rate) are mostly formulas once the definition of a false positive is settled, and the design weight in this milestone sits in the added items | **Keep `C5-K2` (what counts as a false positive) as the second item's gap, and mark the two added items [fill-in] with `C5-K3` and `C5-K4`.** Four gaps for the milestone, one to two per item. Alternative: mark the second item [written] and drop `C5-K2` (precision's leak question moves into this table). Dep-D15 allows either; "Respect the marking" means Ari decides |  **Accepted as recommended** (Ari, October 29, 2026). |
| D7 | **Per-attempt scoring.** The final state keeps only the last attempt's extraction, but the in-memory stager sees every attempt's `raw_extraction` | **Score every attempt**, not just the last. It is what lets C7 ask "did attempt 2 fix attempt 1's errors, or just cost tokens", and validation recall (K4) is per attempt anyway: an attempt's findings are about that attempt's extraction |  **Accepted as recommended** (Ari, October 29, 2026). |

## Test approach (written first, watched fail, then made green)

Tests come first (`alpha-build-plan.md` §3). Four kinds of expected value appear in this plan's tests, and each test names its source:
**labels** (hand-written in `labels.py`, from the page text, never from the pipeline), **constructed pages** (a literal page defined in the
test, with the answer that follows from it), **scripted models** (`tests/fakes.py`'s `scripted_client`: the test decides what the model
says, so the failure under test is exact), and **the plan's definitions** (K2 to K4, quoted in the tests' comments). A test that
reads its expectation out of the code it tests cannot catch that code being wrong, so none does: in particular, no test computes an
expected score by calling `score_page` on the thing under test.

Runs in the cloud: everything below except where marked **local**. The database tests use the existing `calendar_test` fixtures
(`app/testing/db.py`) and hand the harness the fixture's session factory; `scratch_db.py` itself is tested for its **guard** (pure) and
exercised for real only by Ari's first local run (Verification 6; a cloud test that creates a second database would need rights the
CI database may not grant; D2).

### 1. Scoring: structured errors, indexes, the rates (`tests/test_scoring.py`, extended)

| Case | Expected | Source of expectation |
|---|---|---|
| `ReturnedShow.from_dump` carries each show's position in the *dump* (before empty-act shows are dropped) | A dump `[show with acts, show with acts: [], show with acts]` gives indexes 0 and 2 | `validation.Finding.show_index` is a position in `state.extraction.shows`, the raw list (`apps/api/AGENTS.md`); the scorer must speak the same positions or validation recall (K4) cannot join them |
| `score_page` returns an `ErrorItem` for each counted error, with its kind and the returned show's index (None for a missed show) | Constructed page: one missed, one acts-wrong, one fabricated, one leak, one wrong time, one missing time | The tiers, A2.1-D1 |
| `PageScore.errors` (the strings) are unchanged | The existing `test_scoring.py` rows still pass unmodified | The strings are read by `run_eval` and stored in old results files |
| **K2**: `headline_rates` on a **constructed page** (not hand-set `PageScore` fields, so an impossible combination cannot arise): 10 labelled shows; the extraction misses 1, gives 1 the wrong acts, adds 1 invented show and 1 listed non-show (a leak) | `score_page` gives returned 11 (9 matched plus 2 extras; `returned` counts every returned show that has acts); found 8 (`labelled - missed - acts_wrong`); recall 8/10; strict precision 8/11; lenient precision 8/10 | The definition in K2 and the counts `score_page` produces from the constructed page (the reviewer ran it: `labelled 10 returned 11 missed 1 acts_wrong 1 fab 1 leaks 1`); red until Ari fills K2 |
| A missed show whose act splitter dropped it (the dump holds a show with `acts: []` on the labelled date) | The `missed` `ErrorItem` carries that dropped show's **raw index**, not `None` | `validation.py` puts `splitter_dropped` and `excluded_no_acts` on that index; the join in K4 needs it (C5-PR1-2) |
| `headline_rates` with nothing labelled and nothing returned | Defined (1.0, 1.0) and not a division error | An empty labelled page returned empty is a perfect score, not a crash |

### 2. One page through the graph (`tests/test_graph_run.py`)

The graph runs for real; the model is `scripted_client`; the stores are `tests/fakes.py`'s recording fakes (no database).

| Case | Expected | Source |
|---|---|---|
| A JSON-LD page of two events, splitter scripted to answer correctly | `PageRun` has attempts 1, not retried, route `jsonld`, raw = validated, and per-attempt list of length 1 | The constructed page |
| Attempt 1's splitter drops an id (error `splitter_dropped`), attempt 2 answers correctly | attempts 2, `retried` true, `recovered` true, tier of attempt 2 `narrowed`, **per-attempt scores differ** (attempt 1 has an acts error or a missed show, attempt 2 none) | A3's retry shape (`test_graph.py` has the script to copy); D7 |
| Every attempt fails | attempts equal the cap, `escalated` true, `validated_extraction` None (committed-column assertions are in §5) | `decide_route`, `escalate_node` |
| The between-pages reset (a real-Postgres test, in §5's file) | After `reset`, `venue` and `metro` rows remain and `show`, `show_artist`, `artist`, `audit_log`, `agent_run` are empty | Step 2; the one destructive statement the harness runs (C5-PR1-12) |
| `RetryPolicy` built from `--threshold`/`--max-attempts` | Equals `dataclasses.replace(DEFAULT_POLICY, ...)`: the configured `escalation_model` is kept | `policy.py`; a fresh `RetryPolicy(...)` would drop it (C5-PR1-12) |
| `policy=RetryPolicy(max_attempts=1)` | One attempt, then escalate, never a second | D5; `decide_route` reads the cap from the policy |
| `run_venue(..., policy=None)` | The state's policy is `DEFAULT_POLICY`: the production path is unchanged | D5 (the behaviour-preserving half; `test_run_venue.py` extended) |
| The stager sees one document per attempt, and its `raw_extraction` is what the per-attempt score reads | Two attempts give two documents | `staging.document_for` (A4) |

### 3. Results file and aggregate (`tests/test_graph_eval.py`)

| Case | Expected |
|---|---|
| A run record stores the raw, validated and committed extractions, each attempt's findings and extraction, the policy, `labels_sha` and the request record | Round-trips through JSON; a **rescore** (`--rescore LABEL`) rebuilds every score from the stored data with no model call and a fresh label file, writing a new file and leaving the original byte-identical (the A2.1-PR1-13 rule `run_eval` already follows) |
| The aggregate sums counts and divides once | Two pages (5 labelled/4 found, 10 labelled/10 found) give recall 14/15, **not** the mean of 0.8 and 1.0 |
| Retry statistics | Runs 3 with attempts 1, 2, 3 give retry rate 2/3, mean attempts 2.0, escalated 1 if the last failed, recovered 1 |
| A page excluded as held-out is absent from the default sets; `--set held_out` includes it and sets `held_out_scored` in the file | `labels.py` flag, D3 |
| `labels_sha` changes when a label changes | A results file says which labels scored it |
| CLI argument parsing (`--label`, `--set`, `--runs`, `--threshold`, `--max-attempts`, `--scenario`, `--rescore`) | Table of argv to namespace |

### 4. Validation recall (`tests/test_validation_recall.py`; K4 rows red until filled)

Cases are constructed `(ErrorItem, [Finding])` pairs, because the definition is what is under test. Source: the definition in K4.

| Case | Expected under the recommended K4 |
|---|---|
| An acts-wrong error on returned show 3; an **error** finding with `show_index=3` | **Caught** |
| The same error; only a **warning** finding (`possible_merge`) on show 3 | **Flagged** (a warning is recorded but does not fail the record) |
| The same error; findings only on show 4 | **Silent** |
| A missed show (no returned show); an error finding `jsonld_under_reported` with `show_index=None` | **Caught** (a page-level finding covers a show nothing was returned for) |
| A missed show; no page-level finding | **Silent** |
| A missed show whose splitter dropped it: the `missed` item carries the dropped show's raw index 2; an error finding `splitter_dropped` and a warning `excluded_no_acts`, both `show_index=2` | **Caught** (the commonest real error; C5-PR1-2) |
| A fabricated show on returned index 5; a warning `act_not_in_title` on index 5 | **Flagged** (a fabricated show with acts can't carry `excluded_no_acts`: an excluded show has no acts, so the scorer never counts it as fabricated) |
| Recomputed findings equal the recorded ones: a scripted two-attempt run | For each attempt, `recompute_findings(document, fixture)`'s **errors** equal that attempt's `AttemptRecord.findings`; the warnings are the extra | Step 4; guards the equivalence (C5-PR1-6) |
| Tally over a mixed list | Counts per class and per `CheckCode`; recall = caught / total errors, with flagged reported beside it, not folded in |

### 5. The database after two runs (`tests/test_db_score.py`, real Postgres; K3 rows red until filled)

The model is scripted (a JSON-LD page, so the act splitter is the only call), the database is `calendar_test`, and the venue row is created in the test.

| Scenario | Expected | Source |
|---|---|---|
| **Same page twice** | Run 1: every show an insert; run 2: every decision `no_op`, **no row changes**, and the committed score of run 2 equals run 1's | `local_test.py`'s stated expectation; A5's idempotence |
| **Disjoint pages** (page A = dates 1 to 6 of one month fetched on the 1st; page B = dates 20 to 25 of the next month, fetched on the 20th; one venue) | Run 2 inserts B's shows and **A's rows survive**: B's window starts at B's `fetched_on` (the 20th), after A's last date | `reconcile.covered_window` starts at `fetched_on` and `removed_by_absence` removes only inside it (`reconcile.py:290-301`, `:600-618`); the trap "a page listing two weeks must not remove week three". Pinned to this shape because with B's dates before A's the window covers A (C5-PR1-4) |
| **Overlapping pages** (page B repeats page A's dates, minus one show A lists, fetched the same day) | The dropped show becomes `removed`; the shared shows are no-ops; **no row appears twice** | The A5 window; K3's rule |
| **Perturbed** (after run 1: set one row's `start_time` to NULL, add one stale row inside the window, delete one row's `show_artist` rows and then the row; then run the same page again) | Run 2: 1 **update** (the time appears later: `test_a_time_that_appears_later_is_an_update`), 1 remove (the stale row, `status = removed`), 1 insert (the deleted row recreated), the rest no-op; rows left equal the labels | The perturbation is the test's own. A changed non-null time is a remove plus an insert (A5-D3; `test_a_time_change_is_a_cancelled_show_plus_a_new_one`), so it would give insert 2, remove 2, update 0 and never exercise an update; a field outside the match key does (C5-PR1-3). Counts asserted with a scripted model |
| **A single page whose label holds a cancelled show** (run once) | Committed column: 0 missed, scored against `scheduled_only(label)`; the cancelled show is absent | `Action.SKIP`; 7th St Entry labels three (C5-PR1-5) |
| A labelled **cancelled** show (`status="cancelled"`) | **Absent** from the committed rows, and not counted missed | `Action.SKIP`; `ShowStatus` has no cancelled value; K3 |
| `committed_extraction` of a removed row | Not in the output (only `active` rows are "left") | `ShowStatus` |
| `committed_extraction` lineup order | Acts in `sequence_number` order, artist names as stored | `calendar_reader.py`'s lineup query orders the same way |
| `scratch_db` guard | Refuses any name but `calendar_eval`, and any non-local host; accepts local `calendar_eval` | The guard mirrors `app/testing/db.py`'s; M7 |

### 6. Labels (`tests/test_labels.py`, extended)

| Case | Expected |
|---|---|
| A `held_out` page is never in `gated_fixtures()`, `informational_fixtures()` or the default sets; `held_out_fixtures()` returns exactly the flagged ones | D3 |
| **Local only, skips where `eval/fixtures/` is empty:** every `.html` or image in `eval/fixtures/` that a venue key in `VENUE_FACTS` would fetch has a `PAGE_LABELS` entry | A capture nobody labelled is a page the harness silently ignores (`select_fixtures` skips unlabelled files by design) |
| `label_draft` on a constructed page prints every distinct visible line once, numbered, with the dated ones flagged, and prints **nothing from structured data** | Step 7 (as built; C5-CR1-7): many pages put the date and the act on different lines, so listing only dated lines would hide the acts; act names that are in the page *text* are fine, names from JSON-LD never |

### What is not covered, stated plainly

- **No test runs the model.** Whether `gemma4-e4b` retries, how often, and what validation lets through are exactly what the baseline measures;
  nothing in the suite asserts them (they would be asserting a measurement).
- **No cloud test creates `calendar_eval`.** The scratch-database creation and migration are exercised by Ari's first local run (Verification 6).
- **The ambiguous-artist model call in reconcile** (`artist_match`) is real model use inside a graph run. The tests script it; whether it fires on real pages is unverified.

### Mutation checks (each must make a named test fail)

| ID | Break | Test that must catch it |
|---|---|---|
| M1 | `ReturnedShow.index` taken after the empty-act filter instead of before | the index test in §1 |
| M2 | The aggregate averages per-page rates instead of summing counts | the 14/15 case in §3 |
| M3 | `run_venue` ignores `policy` | the `max_attempts=1` case in §2 |
| M4 | Only the last attempt is scored | the differing-per-attempt case in §2 |
| M5 | The committed column counts `removed` rows | the removed-row case in §5 |
| M6 | A cancelled show counted missed when absent | the cancelled case in §5 |
| M7 | The scratch guard accepts `calendar_test` | the guard test in §5 |
| M8 | `headline_rates` divides by labelled when returned is zero | the empty-page case in §1 |

## Implementation steps

### Working protocol for [fill-in] steps

Per `AGENTS.md`: write everything around the key points, leave each `TODO(Ari)` as a complete block (key point, near-exact code in a
comment, check), keep its test red, and stop. `/build-milestone` does not fill a block unless Ari names it. After a gap is filled, the
scaffold comes out in the same change. `K1` is data (label rows) and cannot be a red test at handoff; see its step.

### TODO(Ari) gaps

| Key point | File | The idea | Check |
|---|---|---|---|
| `C5-K1` | `eval/labels.py` | Which entries on a new page are shows, and what are their acts: the ground truth | `test_labels.py` (all rows), the local capture-coverage test, and the baseline run itself |
| `C5-K2` | `eval/scoring.py` `headline_rates` | What counts as **found** and as a **false positive**: does a tolerated leak lower precision | `test_scoring.py::test_headline_rates_*` |
| `C5-K3` | `eval/db_score.py` `expected_rows` | What the database **should** hold after each scenario's second run | `test_db_score.py::test_expected_rows_*` |
| `C5-K4` | `eval/validation_recall.py` `coverage` | When does a finding **cover** an error: severity, position, page-level | `test_validation_recall.py::test_coverage_*` |

### Step 1 — structured scoring errors and the rates [written, with C5-K2]

`scoring.py`: add `ReturnedShow.index` (the position in the dump before the empty-act filter; `from_dump` takes it), an `ErrorItem`
dataclass (`kind`: `missed`, `acts_wrong`, `fabricated`, `leak`, `field_wrong`, `field_missing`, `image_wrong`; `field`; `date`; `index`),
and `PageScore.items: list[ErrorItem]` filled alongside the existing `errors` strings, which keep their text. `Matching` already pairs
each labelled show with a returned show; the returned side now carries its index. **A missed show takes the raw index of a dropped
empty-act show on the same date**, when there is one (`score_page` drops empty-act shows before matching, so without this the commonest
error, a show the act splitter dropped, would carry `index=None` and never join to the `splitter_dropped` finding that sits on its real
index; C5-PR1-2). `PageScore.from_dict` rebuilds `ErrorItem`s from their dicts (`cls(**data)` would leave them as dicts) and accepts
old results files that have no `items` (default empty), so `--rescore` of an A2.1 file still works (C5-PR1-12).

`scoring.py` also gains `scheduled_only(label) -> PageLabel`: the label with its cancelled and postponed shows removed. Reconcile
`SKIP`s such a listing and `ShowStatus` has no cancelled value (Decisions), so the **committed column is scored against
`scheduled_only(label)`** on every run, single-page runs included (7th St Entry labels three such shows; against the full label every
run would report three missed for correct behaviour; C5-PR1-5). `C5-K3` uses the same helper.

`headline_rates(score) -> Rates` is a pure function: `Rates(found, labelled, returned, recall, precision, precision_lenient)`.
**`TODO(Ari)` — `C5-K2`:**

```python
# TODO(Ari) — Key point of interest (C5-K2): what counts as FOUND, and whether a tolerated leak is a false positive.
#   Ari's standard (A2.1-D1) makes identity "date and acts", so a show is FOUND when it was matched AND its acts are correct:
#   found = labelled - missed - acts_wrong. Recall is found / labelled. For precision the denominator is every show returned
#   with acts: the standard tolerates about one leak per page, but a leak is still a row in the calendar that is not a show, so
#   the STRICT precision counts it against; the LENIENT figure (precision_lenient) does not, and both are reported so the
#   tolerated case stays visible. (docs/dev/alpha-deployment-plan.md C5; A2.1-D1.)
# To align: copy the Code lines by hand, then run the Check.
# Code:
#   found = score.labelled - score.missed - score.acts_wrong
#   return Rates(
#       found=found, labelled=score.labelled, returned=score.returned,
#       recall=found / score.labelled if score.labelled else 1.0,
#       precision=found / score.returned if score.returned else 1.0,
#       precision_lenient=found / (score.returned - score.leaks) if score.returned - score.leaks else 1.0,
#   )
# Check: test_scoring.py::test_headline_rates_* — the likeliest mistake is `found = labelled - missed` (counting a
#   wrong-acts show as found, which the standard says is an error), or a ZeroDivisionError on an empty page.
raise NotImplementedError("TODO(Ari)")
```

### Step 2 — one page through the graph [written]

`eval/graph_run.py`. `run_page(label, fixture_path, venue_row, ctx_factory, policy) -> PageRun`:

- calls `main.run_venue(VenueFacts(...), ctx, trigger=RunTrigger.MANUAL, calendar_url=str(path), fetched_on=label.captured_on, policy=policy)`.
  `calendar_url` is the fixture path, which `fetch_node` reads as a file; `captured_on` is the label's, so the year rule (A2.1-D13) sees the date the page was captured, as `local_test.py` does;
- the context is `WorkerContext(audit=PostgresAuditWriter(factory), stager=InMemoryStager(), reader=PostgresCalendarReader(factory), writer=PostgresCalendarWriter(factory))`.
  `InMemoryStager` is a ten-line `Stager` that appends each `document_for` document to a list (D2, D7);
- returns a `PageRun` dataclass: the final state's `extraction`, `validated_extraction`, `attempt_history`, `validation`, `reconcile_plan.counts()`, `commit_result`, `escalation_reason`; the per-attempt documents from the stager; the elapsed seconds;
- the rows left: a `committed_rows` callable passed to `run_page` (default `db_score.committed_extraction(factory, venue_id)`, Step 5), scored with `scoring.score_page` against `scoring.scheduled_only(label)` so the committed column uses the same scorer as the other two. Injectable so the §2 tests (recording fakes, no database) pass a stub and assert only raw, validated and per-attempt scores; every committed-column assertion lives in §5's real-Postgres tests (C5-PR1-7).

Three scores per run: **raw** (`extraction`), **validated** (`validated_extraction`), **committed** (rows). The raw and validated columns are `score_page` on `model_dump(mode="json")`, exactly as `run_eval` calls it; a run that escalated has `validated_extraction = None` and an empty database, scored as every labelled show missed, and counted in the escalation rate rather than hidden in recall.

`PageRun.attempts` holds one entry per staged document: the attempt number, tier, route, model, `larger_model_used`, the attempt's extraction score, and the findings the matching `AttemptRecord` produced. Joining a document to its record is by attempt number.

`main.py`: `run_venue(..., policy: RetryPolicy | None = None)`; `initial = initial.model_copy(update={"policy": policy})` when given (D5). Its docstring gains one line; `test_run_venue.py` gains the two rows in §2.

**Between pages** the harness resets the scratch database (`TRUNCATE show_artist, show, artist, audit_log, agent_run RESTART IDENTITY CASCADE`, never `venue` or `metro`) so one page's artists cannot change how the next page's artists are matched. Scenarios (Step 5) do **not** reset between their two runs; that is the point.

### Step 3 — the results file and the aggregate [written]

`eval/graph_eval.py`, modelled on `run_eval.py`'s shape: `--label` names `eval/results/graph-<label>.json` (gitignored), `--set gated|informational|held_out|all`, `--only`, `--runs` (default 1), `--threshold`, `--max-attempts` (D5), `--scenario`, `--rescore LABEL`, `--compare LABEL...`.

The file records everything needed to read it later without re-running: the label, start time, set, the **request record** (`run_eval.request_record`'s prompts and schema hashes, imported, not copied), the request options, the **retry policy**, the model **provenance** (`run_eval.model_provenance`, Ollama's version and the model digest; a hosted model's provenance is C6's to add, and the file says `provenance: null` there), **`labels_sha`** (the SHA-256 of `labels.py`, so a score names the labels it used), whether any held-out page was scored, the harness's own git commit, and every `PageRun` with its raw data. Scores are recomputable from the stored extractions and findings (`--rescore`), so a change to the scorer or a label correction does not need a model call.

The aggregate (all sums of counts, divided once; M2):

| Block | Fields |
|---|---|
| Shows found | per column (raw, validated, committed): labelled, returned, found, missed, acts wrong, fabricated, leaks; `headline_rates` (K2) |
| Field accuracy | per field: stated, correct, missing, wrong, and the missing rate against the 10% tolerance (pooled per run, as `gate` does) |
| The gate | `scoring.gate` on each column, so "does the pipeline meet A2.1-D1" is answered for the committed rows, not only the model's answer |
| The retry loop | runs; runs that retried; retry rate; mean attempts; attempts by tier; reasons (`FailureReason`); retried-and-recovered; escalated; per-attempt found-correct, so the *change* between attempt 1 and the final is visible |
| Validation | the K4 tally (Step 4), per `CheckCode` and in total |
| Database | the scenario results (Step 5) |
| Cost | seconds per page; mean per route (jsonld, model, image) |

### Step 4 — validation recall [fill-in, C5-K4]

`eval/validation_recall.py`. For each attempt: the `ErrorItem`s of that attempt's extraction (Step 1) and the findings that attempt's
`AttemptRecord` holds, **plus that attempt's warnings**. `AttemptRecord.findings` is errors only, the staged document holds no findings
and the validate audit row stores only a warning count, so the warnings are not stored anywhere. They are recomputed, exactly and with
no production change: `recompute_findings(document, fixture_path, fetched_on)` calls the pure `validation.validate_extraction` on
the staged document's `raw_extraction`, `notes` and source (the document's `route`, checked against the `extraction_source` validation
received) with the fixture's HTML and cleaned text (the same inputs `validate_node` passes). A test asserts the recomputed errors equal
the recorded `AttemptRecord.findings` (§4), which also guards the equivalence (C5-PR1-6; U3 is settled).
`coverage(error, findings) -> Coverage` returns `caught`, `flagged` or `silent`; `tally(...)` counts them.
**`TODO(Ari)` — `C5-K4`:**

```python
# TODO(Ari) — Key point of interest (C5-K4): when does a finding COVER an extraction error?
#   Validation "catches" an error only if it would make the pipeline act: an ERROR-severity finding fails the record and
#   triggers a retry (policy.combine, A3-K4); a WARNING is recorded and changes nothing. So the three classes are:
#   caught = an error finding on that show's index (or a page-level error finding, for a show nothing was returned for);
#   flagged = only a warning covers it; silent = nothing does. Report flagged beside caught, never folded into it:
#   "validation noticed" and "validation stopped it" are different claims. (alpha-deployment-plan.md C5, "validation recall".)
# To align: copy the Code lines by hand, then run the Check.
# Code:
#   covering = [f for f in findings if f.show_index == error.index or (f.show_index is None and error.index is None)]
#   if any(f.severity is Severity.ERROR for f in covering):
#       return Coverage.CAUGHT
#   return Coverage.FLAGGED if covering else Coverage.SILENT
# Check: test_validation_recall.py::test_coverage_* (and test_graph_eval.py::test_validation_recall_in_the_aggregate_*) — the likeliest mistakes are treating a page-level finding as covering
#   every error on the page (it covers only a show nothing was returned for), and counting a warning as a catch.
raise NotImplementedError("TODO(Ari)")
```

(The Code shown matches the table in the test approach; whether a page-level finding should also cover an error on a *returned* show,
for example `empty_but_dated`, is a judgement the Check's second case probes, and Ari may widen it.)

### Step 5 — the database after two runs [fill-in, C5-K3]

`eval/scratch_db.py` (guard, `create`, `migrate` through Alembic's programmatic API, `drop`; refuses any name but `calendar_eval` and any non-local host; no import of `app.testing`), and `eval/db_score.py`:

- `committed_extraction(factory, venue_id) -> dict`: the venue's `active` shows as an extraction-shaped dict (`date` and times as ISO strings, `acts` in `sequence_number` order, the prices as `float`, `free_admission`, `image_url`) so `score_page` scores it unchanged **and** the results file serialises (`json.dumps` rejects `Decimal`; `--rescore` reads the same shape; C5-PR1-12). `scoring._same` already compares prices with a cent's tolerance;
- `Scenario`s: `repeat` (the same page twice), `sequence` (two captures of one venue: White Squirrel's August then October), `overlap` (a second capture that repeats the first's dates, minus one show; built by the scenario from a constructed page in the tests, and from a venue's two real captures only if Ari has captures that overlap), `perturbed` (after run 1: set one row's `start_time` to NULL, add one stale row inside the window, delete one row's `show_artist` rows and then the row, run again; a *changed* non-null time would be a remove plus an insert, A5-D3, and never measure an update);
- `expected_rows(scenario, labels) -> list[LabelledShow]` is the key point. **`TODO(Ari)` — `C5-K3`:**

```python
# TODO(Ari) — Key point of interest (C5-K3): what should the database hold after the second run?
#   Not "the second page's labels". Reconcile soft-deletes only inside the window the second fetch covered: from that fetch's
#   date to the latest date the page evidences (A5-D1; reconcile.covered_window and removed_by_absence). So after a SEQUENCE the
#   first page's shows OUTSIDE that window must SURVIVE, those INSIDE it that the second page no longer lists are gone, and a
#   show both pages list is ONE row, not two. The window's end includes the dates of labelled non-shows, because an excluded
#   no-act listing extends what the page evidences. After a PERTURBED run the stale row is gone and the rest equals the labels.
#   A labelled cancelled or postponed show is ABSENT (ShowStatus has no such value and reconcile skips it, A2.1-D12 +
#   reconcile.Action.SKIP): `scoring.scheduled_only`. The expected rows are what a perfect pipeline would leave, and they come
#   from the LABELS, never from running the pipeline.
# To align: copy the Code lines by hand, then run the Check.
# Code:
#   first_live, second_live = scheduled_only(first).shows, scheduled_only(second).shows
#   if scenario in (Scenario.SEQUENCE, Scenario.OVERLAP):
#       dates = [s.date for s in second.shows] + [n.date for n in second.non_shows if n.date]
#       start, end = second.captured_on, max(dates)
#       survivors = [s for s in first_live if not start <= s.date <= end]
#       return survivors + second_live
#   return first_live         # REPEAT and PERTURBED: the one page's live shows
# Check: test_db_score.py::test_expected_rows_* — the likeliest mistakes are returning only the second page's shows for a
#   sequence (that scores the first page's surviving rows as invented shows), concatenating both pages (a show on both is listed
#   twice), or leaving cancelled shows in the list.
raise NotImplementedError("TODO(Ari)")
```

Both the rows left and the per-run reconcile counts (`ReconcilePlan.counts()`) are scored; the action counts are compared with what
the scenario implies (a repeat run must be all `no_op`; the perturbed run's counts are `update=1, remove=1, insert=1`, the rest `no_op`, with the time-to-NULL perturbation of the `Scenario` list above)
and any difference is reported, not asserted by the harness (the tests assert it with scripted models; the harness reports it with the real one).

### Step 6 — the Makefile target and the CLI [written]

`make eval-graph LABEL=<name> [SET=gated|informational|held_out|all] [ONLY=<text>] [RUNS=1] [SCENARIO=repeat|sequence|overlap|perturbed] [THRESHOLD=<float>] [MAX_ATTEMPTS=<int>] [KEEP_DB=1]` runs `uv run python -m agent_worker.eval.graph_eval`. Local only, like `make worker`: needs `make db-up` (Postgres), Ollama, and the gitignored fixtures; **not part of `make check` and not in CI**, because it calls the model. The target's help line says so. The harness creates `calendar_eval` on its own Postgres (the server `DATABASE_URL` points at, local only by the guard) and drops it at the end unless `--keep-db` is given, for reading the rows by hand.

### Step 7 — labelling [fill-in, C5-K1]

*Capture is local: the cloud has no route to venue websites.* Ari captures with `eval/capture.py` (the pipeline's own fetch; Dep-D16's venue list; blocked venues such as the Midway stay out, A2.1-D3), then labels in `labels.py`.

Written around the gap:

- `PageLabel.held_out: bool = False`; `held_out_fixtures()`; `gated_fixtures()` and `informational_fixtures()` exclude held-out pages; `select_fixtures` in both CLIs defaults to excluding them and `--set held_out` includes only them (D3).
- `eval/label_draft.py`: `uv run python -m agent_worker.eval.label_draft <fixture>` prints, from the cleaned page text, every distinct visible line with its line number, the ones that look dated flagged with `>`, as ready-to-paste `source_line` candidates (as built; the first draft said "each dated line", but many pages put the date and the act on different lines). It prints nothing from structured data, so the label stays a human reading of the page text (`labels.py` docstring). This is what A2.1-D11 asked for ("the page's entry lines pasted as `source_line` candidates") as a tool rather than a one-time paste.
- `test_labels.py`'s existing guards (a show per page, a `source_line` per show, no duplicates, facts for every venue, every non-show can match something) apply to the new pages unchanged, plus the local capture-coverage test in §6.

**`TODO(Ari)` — `C5-K1`:** a block at the end of `PAGE_LABELS`:

```python
# TODO(Ari) — Key point of interest (C5-K1): label each new capture, and decide which are held out (C5-D3).
#   A label is what a PERFECT run would produce, read from the page text (never JSON-LD, never a model's output). The judgement is
#   in three places: which entries are shows (karaoke, comedy and recurring headers go in `non_shows`), what the acts are
#   (A2.1-D5's conventions: a tour name is not an act, a night's name is not an act, a named DJ is), and where a title is
#   genuinely ambiguous (`alternatives`). Mark `held_out=True` on about a third of the new pages and do not read their results
#   before C6. (docs/dev/implementations/a2.1-extraction-reliability.md, A2.1-D5 and A2.1-D11; alpha-deployment-plan.md C5, §5.2.)
# To align: run `uv run python -m agent_worker.eval.label_draft eval/fixtures/<capture>.html`, paste the lines you mean as
#   `source_line`s, add the PageLabel, and run the Check.
# Code (a complete worked row; it is the example in A2.1's plan, A2.1-D11, and `test_scoring.py`, not a row in PAGE_LABELS):
#   S(D(2026, 10, 9), ("Slashfire", "Dread Spell", "Couch Potato Massacre"), "Slashfire w. Dread Spell & Couch Potato Massacre",
#     T(21, 0), convention="w./& split", alternatives=(("Slashfire", "Dread Spell & Couch Potato Massacre"),))
# Check: `uv run pytest agent_worker/tests/test_labels.py` (green when every page has shows, each with a source line); then a baseline
#   run over the page. The likeliest mistake is labelling from what the model returned instead of from the page, which makes the
#   score measure agreement with the model rather than correctness.
```

(There is no `raise` placeholder here: labels are data, and an empty `PageLabel` would fail the existing "at least one show" test, which is the check. D4 says how many.)

### Step 8 — the baseline [written, local]

Ari, on the laptop (`make db-up`, Ollama serving the model, fixtures present):

1. `make eval-graph LABEL=c5-baseline SET=all` over the gated and informational pages and the non-held-out new ones; `RUNS=1`, plus `RUNS=2` on two pages to confirm the determinism flag.
2. `make eval-graph LABEL=c5-baseline-seq SCENARIO=sequence` and `SCENARIO=perturbed`, `SCENARIO=repeat`.
3. `make eval-graph LABEL=c5-baseline-retry THRESHOLD=0.99` to provoke the retry loop (D5): the baseline's real retry rate is the first run's; this one shows what the loop does when it does fire, **on model-route and image pages only** (JSON-LD pages carry no confidence, so a threshold cannot fire on them).
4. Copy the numbers into this file's Implementation log (the results files are gitignored): the headline blocks, the model digest, the policy, `labels_sha`, the harness commit and the date. A baseline whose numbers live only in an ignored file is not recorded.

**Rough duration (unverified, from `alpha-build-plan.md` §8 via the deployment plan's C6 text):** 1.5 to 7 minutes a page on the laptop, so about 20 pages is between half an hour and two and a half hours per run; JSON-LD pages are the quick end.

### Step 9 — documentation [written]

- `alpha-deployment-plan.md` C5: tick the items with their evidence; record departures 1 to 4; `alpha-build-plan.md` A8's pointer line gets a C5 status.
- `docs/dev/conventions.md`: a `C5` row in the scope table.
- `apps/api/AGENTS.md` "Agent worker": one paragraph on the harness (the two CLIs, the three columns, the scratch database, "local only, not in `make check`") and the commands.
- `docs/dev/notes.md`: anything non-obvious the first local run turns up (a likely candidate: how `calendar_eval` interacts with the `calendar_dev` data and `DATABASE_URL`).
- This file: the Implementation log, with the baseline.

## Critical files

| File | Change |
|---|---|
| `apps/api/agent_worker/eval/scoring.py` | `ReturnedShow.index`, `ErrorItem`, `PageScore.items`, `Rates`, `headline_rates` (`C5-K2`) |
| `apps/api/agent_worker/eval/graph_run.py` | New: one page through `run_venue`, `PageRun`, `InMemoryStager` |
| `apps/api/agent_worker/eval/graph_eval.py` | New: CLI, results file, aggregate, `--rescore`, `--compare` |
| `apps/api/agent_worker/eval/db_score.py` | New: `committed_extraction`, scenarios, `expected_rows` (`C5-K3`) |
| `apps/api/agent_worker/eval/scratch_db.py` | New: the `calendar_eval` guard, create, migrate, drop |
| `apps/api/agent_worker/eval/validation_recall.py` | New: `coverage` (`C5-K4`), `tally` |
| `apps/api/agent_worker/eval/label_draft.py` | New: candidate `source_line`s |
| `apps/api/agent_worker/eval/labels.py` | `PageLabel.held_out`, `held_out_fixtures()`, the `C5-K1` block |
| `apps/api/agent_worker/main.py` | `run_venue(..., policy=)`, the only change to production code |
| `apps/api/agent_worker/tests/` | `test_graph_run.py`, `test_graph_eval.py`, `test_validation_recall.py`, `test_db_score.py` (new); `test_scoring.py`, `test_labels.py`, `test_run_venue.py` (extended) |
| `Makefile` | `eval-graph` target |
| `docs/dev/conventions.md`, `apps/api/AGENTS.md`, `alpha-deployment-plan.md`, `alpha-build-plan.md` | Step 9 |

Reused, not rewritten: `scoring.score_page`, `match_shows`, `gate`; `run_eval.request_record`, `model_provenance`; `main.run_venue`; `PostgresCalendarReader`, `PostgresCalendarWriter`, `PostgresAuditWriter`; `staging.document_for`; `tests/fakes.py` (`scripted_client`, `jsonld_page`, `event`, `split_answer`, the recording fakes). `eval/` must not import `app.testing` (`test_no_testing_imports.py`).

## Verification

**In the cloud (the build):**

1. `make check` (lint, mypy over `app/` and `agent_worker/`, pytest with Postgres, the contract check, `designation-check`, e2e). Expected at handoff: green except the `C5-K2`, `C5-K3` and `C5-K4` tests, red on purpose; and, until Ari fills them, `make check` is red by design, as it was for earlier `[fill-in]` milestones.
2. Each mutation check M1 to M8 applied by hand, the named test shown failing, then reverted.
3. `make designation-check BASE=<the branch point>`: no bare ID in code, tests or other documents.
4. `uv run pytest app/tests/test_no_testing_imports.py`: green, proving `eval/` imports no test helpers (the test lives in `app/tests/`; it scans `agent_worker/` too).
5. `git diff` on `main.py` shows only the `policy` parameter.

**Locally (Ari, after the gaps are filled):**

6. `make eval-graph LABEL=c5-smoke ONLY=white_squirrel-2026-10-10 RUNS=1`: creates `calendar_eval`, migrates it, runs, prints the three columns, drops it. If creation fails for rights, the error is the guard's or Postgres's and says which.
7. The baseline (Step 8).
8. `--rescore c5-baseline` rebuilds the aggregate with no model call and the original file is byte-identical.

**Done when** (deployment plan): the harness reports precision and recall on shows found, field accuracy, the retry rate, validation recall and the database rows left after two runs, **and the baseline is recorded** (Step 8, in this file). Needs the local model and the gitignored fixtures.

## Unverified (the plan was written in the cloud)

These facts need the laptop; the build marks each one as it is checked, and the plan does not depend on them being as assumed unless stated.

| # | Assumption | Why it matters | What changes if wrong |
|---|---|---|---|
| U1 | *(settled in plan review, C5-PR1-11)* After a White Squirrel `sequence` reconcile leaves August's rows alone | `covered_window` starts at the second fetch's date and `load_request` for the October run reads only its window (`reconcile.py:290-330`, `:600-618`) | Settled from the code; the first local run confirms it with real rows |
| U2 | The baseline retry rate is near zero | At temperature 0 on the four gated pages (56 of 60) most pages pass first time; the threshold-0.99 run exists to provoke the loop | None for the build; "0 of N retried" is reported as such |
| U3 | *(settled in plan review, C5-PR1-6)* Earlier attempts' warnings are not stored anywhere | Not in the staged document, not in the audit row (a count only) | Recomputed by `validate_extraction` from the staged inputs (Step 4); no production change |
| U4 | The ambiguous-artist model call (`artist_match`) fires on real pages | Real model use inside the graph run; its cost and nondeterminism | Counted in the cost block; the reset between pages (Step 2) stops it leaking across pages |
| U5 | The local Postgres role can `CREATE DATABASE` | `scratch_db.create` | The error names it; `--keep-db`/`TEST_DATABASE_URL`-style explicit URL is the fallback, as in `app/testing/db.py` |
| U6 | Per-page duration of 1.5 to 7 minutes (above) | Planning only | None |
| U7 | `eval/fixtures/` on Ari's laptop holds the August and October captures under the names in `labels.py` | The scenarios need White Squirrel's two captures | `select_fixtures` already skips and says so; the scenario is reported "not run" |

## Not doing in C5

- **No change to the thresholds, the cap, the retry tier or the confidence policy.** Measuring them is C7, on the model that ships (Dep-D5).
- **No larger model or hosted inference.** That is C6; the harness uses the pipeline's client, so it follows C6's configurable endpoint with no change, and its provenance block gains a hosted form then.
- **No change to validation, reconcile or commit behaviour**, including closing any gap the baseline exposes. Findings go in the Implementation log and become their own work.
- **No R2 snapshots, no Mongo requirement** (staging is in memory for the harness).
- **No CI job for the model-backed harness.** The deterministic parts are in `make check`; the baseline is local (D2).
- **No quantitative claim that ten pages is enough** (D4).

## Plan review

*(Round 1 is written by `plan-reviewer`, with `model` set to a model other than the author's.)*

### Round 1 — Claude Opus 5.5, October 29, 2026

**Scope:** the plan body as of this round (the file was untracked in the working tree; `main` at `4131ddc`). Plan review only:
no code exists yet.

**What was checked and how.** Read `AGENTS.md`, `apps/api/AGENTS.md`, `alpha-deployment-plan.md` §6 C5 (and Dep-D5, Dep-D15,
Dep-D16, §5.2), and `docs/dev/conventions.md`'s designation rule. I checked every code claim the plan makes against the source:
`eval/scoring.py` (all of it), `eval/labels.py`, `eval/run_eval.py` (the helpers the plan reuses), `validation.py` (types,
`validate_extraction`, `aggregate_confidence`), `policy.py` (`RetryPolicy`, `AttemptRecord`, `combine`, `decide_route`),
`nodes.py` `validate_node`, `graph.py`, `state.py`, `main.run_venue`, `staging.document_for`, `audit.entry_for` (validate
detail), `context.py`, `reconcile.py` (matching, `plan_for_listing`, `covered_window`, `load_request`, `removed_by_absence`,
the guard), `app/testing/db.py`, `app/tests/test_no_testing_imports.py`, `tests/fakes.py`, and the table names in
`app/db/models/`. Commands run, all read-only against the repo:
- `uv run pytest agent_worker/tests/test_reconcile_shows.py::test_a_time_change_is_a_cancelled_show_plus_a_new_one`: passed. It
  confirms that a changed start time is a remove plus an insert (row 3).
- A one-off `uv run python -I -c …` that ran `score_page` on a constructed page with 10 labelled shows, 1 missed, 1 with wrong
  acts, 1 fabricated and 1 leak. Output: `labelled 10 returned 11 missed 1 acts_wrong 1 fab 1 leaks 1` (row 1).
- `check_designations.py`'s `BARE` regex, run in Python over the four `TODO(Ari)` blocks: line 376 gives `['D5', 'D11']` (row 8).
- A ruff probe on a scratch file in the session scratchpad. It found nothing, and no finding rests on it.

No worktree was needed and nothing in the repo was changed apart from this round and the header.

**What holds up.** Departure 3 (`run_venue(..., policy=)`, Dep-D5's knobs) is sound. `state.policy` is the only policy that
`graph.route_after_validate`, `nodes` (`plan_for_attempt`, `combine`) and `decide_route` read, so the two-line change does reach
every consumer (CONFIRMED by grep). Running the real graph through `run_venue` with a real `WorkerContext` matches A4-D1 and
A4-K1. Building the DB tests on the savepoint `async_sessionmaker(bind=db_conn, join_transaction_mode="create_savepoint")` pattern
already exists in `test_audit_writer.py`. Summed counts with a single division (M2) and the held-out flag (D3) are right. The
tests-first structure is in place, each test names its source of expectation, and M1–M8 each name a catching test. The four gaps
fall on the right decisions: K2 decides what counts as a false positive, K3 decides what a perfect database looks like, K4
decides what counts as a catch, and K1 is the labels themselves. No gap is boilerplate. **But the recommended code for K3 and K4
is wrong for cases the plan itself relies on** (rows 2 and 4), and two test expectations contradict the code they test (rows 1
and 3).

**Counts:** 0 blocker, 7 should-fix, 5 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The K2 test case's numbers can't happen, and they contradict K2's own Code.** §1 says "10 labelled, 8 returned, 1 missed, 1 acts-wrong, 1 fabricated, 1 leak → found 7; recall 7/10; strict precision 7/8". In `score_page`, `returned` counts every returned show that has acts, matched ones and extras alike, so 10 labelled with 1 missed gives 9 matched, plus 2 extras, which makes 11 returned. K2's Code (`found = labelled - missed - acts_wrong`) gives 8, not 7. So the right expectations are recall 8/10, strict precision 8/11, lenient 8/10. Fix: restate the case (for example "returned 11; found 8; recall 8/10; strict 8/11; lenient 8/10"), build it as a constructed page and not as hand-set `PageScore` fields, so impossible combinations can't arise, and say where each number comes from. | CONFIRMED: `scoring.py:245-250` (`returned=len(with_acts)`), plus the `score_page` run in the preamble (`returned 11`). | Ari fills K2 exactly as the Code says and the test stays red. Or he "fixes" `found` until it gives 7, which pushes the definition away from A2.1-D1. |  **Fixed.** §1's K2 case is now a constructed page (10 labelled; 1 missed, 1 wrong-acts, 1 invented, 1 leak) with the counts `score_page` produces: returned 11, found 8, recall 8/10, strict 8/11, lenient 8/10; the source is named. |
| 2 | should-fix | **The most common pipeline error, a show the act splitter dropped, would be measured as "silent" by validation recall.** When the splitter drops an id, the show stays in `extraction.shows` with `acts: []`. Validation then records `splitter_dropped` (ERROR) and `excluded_no_acts` (WARNING), both with `show_index` = that position. `score_page` drops empty-act shows before matching, so the label becomes a `missed` `ErrorItem` with `index=None`. K4's Code only lets a page-level finding (`show_index is None`) cover an error with `index=None`, so this error, which validation did catch and which drives §2's retry case, counts as silent. Separately, §4's row "fabricated show on index 5; `excluded_no_acts` on index 5 → flagged" describes a case that can't occur: an excluded show has no acts, so the scorer never makes it a fabricated error. Fix (Step 1): when a labelled show is missed and a dropped empty-act show sits on the same date, the missed `ErrorItem` carries that show's raw index (`ReturnedShow.index` already exists for this). Add a §4 row "missed via a dropped id + `splitter_dropped` on its index → caught". Replace the fabricated/excluded row with a real one, such as a leak or fabricated show on a returned index under `act_not_in_title`. | CONFIRMED by reading: `validation.py:206-210` (`is_excluded` = no acts), `:487-495` (`EXCLUDED_NO_ACTS`, index), `:527-531` (`SPLITTER_DROPPED`, `show_index=missing`), `scoring.py:244-250` (empty-act shows dropped before matching). | The baseline would report the splitter's misses as "validation silent" when the retry loop in fact fired on them. That is the wrong answer to the item's question ("which layer catches which failure") for the error A2.1 found most often. |  **Fixed.** Step 1: a missed show takes the raw index of a dropped empty-act show on its date; §1 gains the row; §4 gains the `splitter_dropped` + `excluded_no_acts` → caught row and replaces the impossible fabricated/excluded row with fabricated + `act_not_in_title` → flagged. |
| 3 | should-fix | **The perturbed scenario's "change one row's start time → 1 update" is wrong: reconcile treats a time change as a remove plus an insert.** Matching is exact on (date, time), and two different non-null times never pair (A5-D3, from the requirements: "that's a time change"). The perturbed run therefore gives insert 2, remove 2, update 0, not `update=1, remove=1, insert=1`. That leaves the C5 item's "updates" with no scenario at all: the White Squirrel sequence covers disjoint windows, and C2's live replay didn't see an in-place update either. Fix: perturb a field that is not part of the key. Set the row's `start_time` to NULL (a time that appears later is an update, `test_a_time_that_appears_later_is_an_update`), or change `end_time`, a price or the lineup. Then correct the §5 table, Step 5's counts and K3's comment to match. | CONFIRMED: `test_reconcile_shows.py:71-79` passes (`["insert", "remove"]`); `reconcile.py:397-410`, `:440`. `alpha-deployment-plan.md` C2 bullet ("an in-place field update was not [observed]"). | §5's perturbed test is red against correct reconcile code. Someone then "fixes" the expectation or reconcile, and the harness still never measures an update. |  **Fixed.** The perturbation sets `start_time` to NULL (a time that appears later is an update); the §5 row, Step 5's scenario list and the counts say why a changed non-null time is a remove plus an insert (A5-D3). The update is now measured. |
| 4 | should-fix | **K3's rule ("after a SEQUENCE the first page's shows must SURVIVE") holds only when the windows don't overlap, and the Code (`live(first) + live(second)`) double-counts.** The real rule is A5-D1's window: the second fetch removes first-page shows dated inside `[second.captured_on, latest date the second page evidences]` that it no longer lists. A show listed on both pages is one row, but the concatenation lists it twice and scores the database as "missed 1". White Squirrel's August (Aug 17–22) and October (Oct 10–14) pages happen to be disjoint and in the past relative to each other, but Ari's new venues (D4, Dep-D16) may not be. §5's "disjoint pages" test has the same gap: if page B lists dates *after* page A's with the same `fetched_on`, the window covers A's dates and A's rows are removed, or withheld by the mass-removal guard. Fix: K3's key point should state the window rule, and the Code should keep `live(first)` shows outside the second page's window plus `live(second)`, with no duplicates by (date, acts). The window end should include labelled non-show dates, because excluded no-act listings extend it (`excluded_listing_dates`). Also pin the §5 disjoint test to "B lists earlier dates than A" (the "two weeks must not remove week three" case) or to B's `fetched_on` coming after A's last date, and add an overlapping-sequence case. | CONFIRMED by reading: `reconcile.py:290-301` (`covered_window` starts at `fetched_on`), `:600-618` (`removed_by_absence`), `:267-287`, `:621-628` (guard); `labels.py:125-183` (the two White Squirrel date ranges). | The decision K3 asks Ari to align with would be the wrong one. For any overlapping pair of captures, a correct pipeline gets scored as missing shows, and a reconcile that removed shows inside the window would still pass. |  **Fixed.** C5-K3's key point and Code state the window rule (second fetch's date to the latest date it evidences, non-show dates included), survivors outside it, no duplicates. §5 pins the disjoint case's shape and adds an overlapping case; `overlap` is a new scenario. |
| 5 | should-fix | **Scored against the full label, every single-page run's committed column would show 7th St Entry's cancelled and postponed shows as missed.** Step 2 scores the rows left with `score_page(label, …)`, but the plan applies "a cancelled show is expected absent" (Decisions bullet, K3) only to scenarios. `seventh_st_entry-2026-10-10.html` (gated) labels three `cancelled`/`postponed` shows. Reconcile `SKIP`s them, so the committed column reports 3 missed on every run and the committed gate fails for a reason that is correct behaviour. Fix: Step 2 scores the committed column against the label with non-`scheduled` shows removed (one helper, shared with K3), and §2 or §5 gets a single-run test that uses a cancelled label. | CONFIRMED by reading: `labels.py:235,247,252`; `reconcile.py:569-574` (`SKIP`); plan Step 2 last bullet. | The headline "does the pipeline meet A2.1-D1 for the committed rows" is wrong on a gated page from the first baseline onward, and the validated-to-committed difference looks like a commit bug. |  **Fixed.** `scoring.scheduled_only(label)` (Step 1); Step 2 scores the committed column against it on every run, K3 uses the same helper; §5 gains the single-page cancelled-show row. |
| 6 | should-fix | **Earlier attempts' warnings aren't where Step 4 says they are, and there is a way to recover them without changing production code.** Step 4 says an earlier attempt's warnings are "in the attempt's staged document". `staging.document_for` runs at the *extract* step and stores `raw_extraction`, `notes`, `route` and so on, but no findings. The validate audit row stores only `"warnings": len(...)`, and `AttemptRecord.findings` holds the errors only. So U3 is already settled in the negative. But `validate_extraction` is a pure function of (the extraction, `source`, `notes`, `fetched_on`, page HTML/text), and the staged document carries the first three per attempt. The harness can therefore recompute every attempt's full findings, exactly, from the stored document and the fixture, with no change to `validate_node`. Fix: Step 4 recomputes findings per attempt this way, plus one test that the recomputed errors equal `AttemptRecord.findings` for a scripted two-attempt run. That test also guards the equivalence. Settle U3 in the plan. Check `route` (`state.route_attempted`) against the `source` validation receives (`state.extraction_source`) when building it. | CONFIRMED by reading: `staging.py:59-73`, `audit.py:154-162`, `nodes.py:240-271`, `policy.py:95-112`. The recomputation is PLAUSIBLE (the inputs are all present; untested). | The plan's fallback ("record error findings only for earlier attempts") would undercount `flagged` for every retried page, and D7's per-attempt validation recall would be incomplete exactly where retries happen. |  **Fixed.** Step 4 recomputes each attempt's findings with `validate_extraction` from the staged document and the fixture; §4 gains the equivalence test; U3 marked settled. No production change. |
| 7 | should-fix | **§2's graph-run tests use the recording fakes, yet assert a committed column that Step 2 reads from Postgres.** §2 says "the stores are `tests/fakes.py`'s recording fakes (no database)", and its rows include "no rows committed, all labelled shows counted missed in the committed column". `FakeWriter` "writes nothing", and Step 2 computes the committed column with `db_score.committed_extraction(factory, venue_id)`. Fix: make the committed-rows source injectable in `run_page` (a callable, with the Postgres one by default), or move the committed-column assertions to §5's real-Postgres tests and keep §2 to raw, validated and per-attempt scores. | CONFIRMED by reading: `tests/fakes.py:264-271`; plan §2 preamble and row 3; Step 2 last bullet. | The §2 tests can't be written as specified. The builder either quietly drops the assertion or gives `run_page` a database dependency in a test the plan calls database-free. |  **Fixed.** `run_page` takes an injectable `committed_rows` callable; §2 asserts only raw, validated and per-attempt scores (and `validated_extraction` None on escalation); committed-column assertions live in §5. |
| 8 | nit | **The K1 block cites bare `D5, D11`.** "(docs/dev/implementations/a2.1-extraction-reliability.md D5, D11; …)" is copied into `labels.py`, and `make designation-check` flags it there, so `make check` and the PR job fail. Write `A2.1-D5, A2.1-D11`. The other three blocks are clean. | CONFIRMED: `scripts/check_designations.py:33` `BARE`, run over plan lines 236-386, gives line 376 `['D5', 'D11']`. | A red designation check on the scaffold PR, for a reason that has nothing to do with the gaps. |  **Fixed.** The K1 block cites `A2.1-D5` and `A2.1-D11`. Verification 3 (`make designation-check`) will confirm. |
| 9 | nit | **K1's "complete worked row, from an existing page" isn't from an existing page.** No `PAGE_LABELS` entry contains the Slashfire row. It comes from A2.1's plan text (`a2.1-extraction-reliability.md:262-264`) and `test_scoring.py:163-170`. Use a real row (for example White Squirrel's `Lord Jeremy …` with its `alternatives`) or say where the example comes from. | CONFIRMED by `grep -rn Slashfire`. | Ari goes looking for a page that isn't there. Small, but K1 is the gap where getting the source right matters most. |  **Fixed.** The block says the worked row is the example from A2.1's plan (A2.1-D11) and `test_scoring.py`, not a `PAGE_LABELS` row. |
| 10 | nit | **The make target and commands don't match how the plan uses them.** Step 6's signature lists `LABEL SET RUNS SCENARIO`, but Step 8 uses `THRESHOLD=0.99` and Verification 6 uses `ONLY=`, so add `THRESHOLD`, `MAX_ATTEMPTS`, `ONLY` and `KEEP_DB`. Verification 4 runs `agent_worker/tests/test_no_testing_imports.py`, but the test is `app/tests/test_no_testing_imports.py`, and there is no `agent_worker` copy. | CONFIRMED: `ls agent_worker/tests`; `app/tests/test_no_testing_imports.py:16-30`. | Copy-pasted commands fail. |  **Fixed.** Step 6's target lists `ONLY`, `THRESHOLD`, `MAX_ATTEMPTS`, `KEEP_DB`, `SET`, `SCENARIO`; Verification 4 points at `app/tests/test_no_testing_imports.py`. |
| 11 | nit | **Two "unverified" items can be settled from the code, and one baseline step does less than it implies.** U1: `covered_window` starts at `fetched_on`, and `load_request` for the October run reads only Oct 10–14, so August rows are neither loaded nor removed. This is settled; move it out of the table and cite `reconcile.py:290-330`, `:600-618`. D5 and Step 8.3: a threshold of 0.99 can't fire on JSON-LD pages, because `aggregate_confidence` returns `None` for the `jsonld` source and `combine` skips `None`. So "provoke the retry loop" only reaches model-route pages. Say so, or the provoked retry rate will be read as the whole set's. | CONFIRMED by reading: `validation.py:444-457`, `policy.py:137`. | Planning noise (U1), and a retry-rate figure that is easy to misread in C7. |  **Fixed.** U1 marked settled with the citation; D5 and Step 8.3 say a threshold provokes retries on model-route and image pages only. |
| 12 | nit | **Small gaps in serialisation and the policy that a build would hit.** (a) `PageScore.from_dict` builds with `cls(**data)`, so a new results file's `items` would come back as dicts. Rebuild `ErrorItem`s, not only default the field to empty. (b) `committed_extraction` should emit prices as `float` and dates and times as ISO strings, so the results file serialises (`json.dumps` rejects `Decimal`) and `--rescore` reads the same shape. (c) Build `--threshold`/`--max-attempts` with `dataclasses.replace(DEFAULT_POLICY, …)`, not `RetryPolicy(...)`, or the configured `escalation_model` is silently dropped. (d) The perturbed scenario's "delete one row" has to delete its `show_artist` rows first (FK). (e) The between-pages reset (Step 2) has no test. A one-line test that the reset leaves `venue` and `metro` and empties the rest would cover the one destructive statement the harness runs. | CONFIRMED by reading: `scoring.py:172-176`, `policy.py:51-74`, `app/db/models/calendar.py:237-238`. | Each is a small build-time surprise or a silently wrong field in a results file. |  **Fixed.** (a) `from_dict` rebuilds `ErrorItem`s (Step 1); (b) `committed_extraction` emits floats and ISO strings (Step 5); (c) the policy uses `dataclasses.replace(DEFAULT_POLICY, ...)` (D5, plus a §2 test); (d) the perturbation deletes `show_artist` rows first (Step 5); (e) a reset test in §2. |

**Rejected:** none. All 12 findings were checked against the code (the reviewer ran the key ones) and accepted.

## Implementation log

### Round 1 — Claude Sonnet 5.5, October 29, 2026 (cloud session)

**Scope.** Diff base `ea6d1e0ae773c705b45b22093a2405ba920a78bc` (the commit that carried the resolved plan), the working tree on top of it; nothing was
committed before the review. Files touched:

- New in `apps/api/agent_worker/eval/`: `graph_run.py`, `graph_eval.py`, `db_score.py`, `scratch_db.py`, `validation_recall.py`, `label_draft.py`.
- Changed: `eval/scoring.py` (index, `ErrorItem`, `items`, `scheduled_only`, `Rates`, `headline_rates`), `eval/labels.py` (`held_out`, `held_out_fixtures()`, the `C5-K1` block), `eval/run_eval.py` (`--set held_out`), `main.py` (`run_venue(..., policy=)`, the only production-code change).
- New tests in `agent_worker/tests/`: `test_graph_run.py`, `test_graph_eval.py`, `test_db_score.py`, `test_scratch_db.py`, `test_validation_recall.py`, `test_label_draft.py`; extended: `test_scoring.py`, `test_labels.py`, `test_run_venue.py`, `test_eval_harness.py`.
- `Makefile` (`eval-graph`), `apps/api/AGENTS.md`, `docs/dev/conventions.md` (the `C5` scope row), `docs/dev/alpha-deployment-plan.md` (C5 status note; no item ticked, the gaps and the baseline are open).

**Departures from the plan, each with its reason.**

1. **Scenarios feed every capture from one fixed path.** Building the OVERLAP test showed reconcile marks a shared show *updated* when the page was fetched from a different file, because `original_url` is one of the columns it compares and the harness passes a fixture's path as the URL. A real venue's captures all come from one URL, so `db_score.run_scenario` copies each page to the same temporary path before it runs (the record keeps the capture's name; `run_page` gained a `name` argument). Not in the plan; it would have made every overlapping pair of real captures report phantom updates.
2. **Validation recall is reported per error kind and with a "findings fired" count, not per `CheckCode` of the covering finding.** `coverage` (C5-K4) returns a class, not the finding that covered the error, and adding the second answer would have duplicated the position logic outside Ari's gap. "Which layer catches which failure" is answered by `by_kind` (e.g. acts_wrong: 3 silent) plus which codes fired.
3. **`validated` is None for an escalated run by an explicit harness rule.** The plan said an escalated run "has `validated_extraction` None", but `validate_node` fills it on every attempt, a failed one included; the harness reports it only when the run reached reconcile (a pass).
4. **`run_eval.py` got `--set held_out`** so both CLIs honour C5-D3 (the plan said both); `--set all` still excludes held-out pages.
5. **The scratch-database path was smoke-tested here, not only left for the laptop.** The plan listed "can the local role CREATE DATABASE" (U5) and "no cloud test creates `calendar_eval`" as local-only. The sandbox's Postgres allowed it, so a one-off script (kept in the session scratchpad, not in the repo) ran the real `evaluate()`: `scratch_db.create`, `migrate`, a scripted-model run, the file write and the drop. The suite still has no test that creates the database.
6. **`test_every_captured_fixture_is_labelled` has an `UNLABELLED_ON_PURPOSE` set** (empty). A capture deliberately not scored (a venue behind a bot challenge) goes there, with the reason, rather than leaving the test red on Ari's laptop. Not in the plan.

**`TODO(Ari)` gaps (all four open; none filled).**

| Key point | Where | One line | Command |
|---|---|---|---|
| C5-K1 | `eval/labels.py:373` | Label the new captures and mark about a third `held_out` | `uv run pytest agent_worker/tests/test_labels.py` (no test is red at handoff: labels are data, see the block) |
| C5-K2 | `eval/scoring.py:365` | What counts as found; does a tolerated leak lower precision | `uv run pytest agent_worker/tests/test_scoring.py agent_worker/tests/test_graph_eval.py -k "headline_rates or summed_counts"` |
| C5-K3 | `eval/db_score.py:257` | What the database should hold after the second run | `uv run pytest agent_worker/tests/test_db_score.py -k expected_rows` |
| C5-K4 | `eval/validation_recall.py:43` | When a finding covers an extraction error | `uv run pytest agent_worker/tests/test_validation_recall.py agent_worker/tests/test_graph_eval.py -k "coverage or tally"` |

Until K2, K3 and K4 are filled, `graph_eval.evaluate` raises `NotImplementedError("TODO(Ari)")` when it first needs one of them (K2 and K4 when aggregating, K3 for `--scenario`), by design.

**Verification.**

- `uv run ruff check .`: clean. `uv run mypy`: clean, 135 files.
- `REQUIRE_DB=1 uv run pytest`: **1054 passed, 16 skipped, 15 failed**. The 15 are exactly the open-gap tests: 3 for K2 (`test_headline_rates_*` x2, `test_rates_are_computed_from_summed_counts_not_averaged_per_page`), 8 for K4 (7 `test_coverage_*`, `test_tally_counts_each_class_*`), 4 for K3 (`test_expected_rows_*`). The 16 skips are the existing fixture-dependent ones plus the new capture-coverage guard. Nothing else fails.
- Each scaffold's own Code lines, applied temporarily and reverted, turn its tests green: K3 (11 of 11 in `test_db_score.py`), K4 (11 of 11 in `test_validation_recall.py`), K2 (the worked page gives found 8, recall 0.8, strict 8/11, lenient 0.8, as the test expects).
- Mutation checks, each applied by hand to a copy and reverted: **M1** to **M8** all make their named test fail (M2 and M8 need K2's Code applied first, and pass with only that applied).
- `make designation-check BASE=ea6d1e0ae773c705b45b22093a2405ba920a78bc`: exit 0 (after fixing two bare IDs in my own `alpha-deployment-plan.md` note). `make contract-check`: current. `make e2e`: 104 passed.
- `make check` stops at its `test` stage while the gaps are red (make halts on the first failing target), so its later stages (`contract-check`, `designation-check`, `e2e`) were run individually, above.
- Smoke run with the three gaps stubbed in a throwaway script and a scripted model: `evaluate()` created and migrated `calendar_eval`, ran a two-event page (attempt 1 drops a title, attempt 2 answers), wrote the file and dropped the database. Output: retry rate 1.0, `errors_first_attempt 1`, `errors_final_attempt 0`, validation recall 1.0 with `splitter_dropped` and `excluded_no_acts` fired, `findings_disagree 0`. `--scenario perturbed` on the real writer: second run `update 1, insert 1, remove 1`, `count_differences []`, rows equal the label.

**Unverified (still local).** U2 (the baseline retry rate), U4 (whether the ambiguous-artist call fires on real pages), U6 (duration), U7 (the laptop's fixture names), the sequence scenario on White Squirrel's real August and October captures, and everything about `gemma4-e4b`. U1, U3 and U5 are settled (see the table).

**Where to look hardest.**

1. `validation_recall.recompute_findings`: it assumes the staged document's `route` equals the `extraction_source` validation received, and round-trips `raw_extraction` through `VenuePageExtraction.model_validate`. Tested for the JSON-LD route only; the model route (status merge, `added_indices`) and the image route are untested, and a drift would show as `findings_disagree > 0` in a results file.
2. `db_score._perturb` and `_expected_counts`: they assume at least two live shows, one with a start time, and that the stale row on the last labelled date falls inside the window.
3. `graph_eval.evaluate`'s scenario branch: the `records` it builds from a scenario's two runs, and the `run` index it assigns.
4. `score_database`'s union of both pages' `non_shows`, and `committed_extraction` always reporting `status: scheduled`.
5. `reset` truncating with `CASCADE`: guarded by `scratch_db`, tested for what it keeps, but it is the harness's one destructive statement.

### Round 2 — Claude Sonnet 5.5, October 29, 2026 (fixes for code review round 1)

**Scope.** The same diff base (`ea6d1e0ae773c705b45b22093a2405ba920a78bc`), the fixes only: `eval/graph_eval.py` (`_scored_in`, scenario tagging, `rescore` of scenarios, `route_mismatches`, `not_run` handling), `eval/db_score.py` (`ScenarioNotRunnable`, `ScenarioResult.not_run`, K3 wording), `eval/graph_run.py` (`route_mismatch`), `eval/scoring.py` (`_dropped_index` docstring), `eval/validation_recall.py` (K4 Check command), tests in `test_graph_eval.py`, `test_db_score.py`, `test_graph_run.py`, and the docs of Step 9 (`alpha-build-plan.md`, `alpha-deployment-plan.md`, `apps/api/AGENTS.md`, `Makefile` comment). Resolutions are in the Code review round below.

**Departure 7 (added in this pass).** `label_draft` prints every distinct visible line, not only the dated ones (code review row 7): the plan text now says so.

**`TODO(Ari)` gaps.** Unchanged: all four open (K1 `eval/labels.py`, K2 `eval/scoring.py`, K3 `eval/db_score.py`, K4 `eval/validation_recall.py`; commands in Round 1's table; the K4 command now also runs `test_graph_eval.py`).

## Code review

*(Written by `plan-reviewer`.)*

### Round 1 — Claude Opus 5.5, October 29, 2026

**Scope:** Implementation log Round 1. That is the working tree against diff base `ea6d1e0ae773c705b45b22093a2405ba920a78bc`
(nothing committed on top; new files are intent-to-add), 25 files, +2785/−26 by `git diff ea6d1e0 --stat`. The four `TODO(Ari)` gaps
(C5-K1 to C5-K4) are open on purpose and are not findings.

**What was checked and how.** Read `AGENTS.md`, `apps/api/AGENTS.md`, the FastAPI style guide's Anti-patterns table, this plan in
full (body, plan review round 1, Implementation log round 1), and every new or changed file in the diff: `scoring.py`, `labels.py`,
`run_eval.py`, `main.py`, `graph_run.py`, `graph_eval.py`, `db_score.py`, `scratch_db.py`, `validation_recall.py`, `label_draft.py`,
and their tests. Checked the code against `nodes.validate_node`, `nodes.extract_node`/`_route_for`, `staging.document_for`,
`reconcile.covered_window`/`load_request`/`plan_for_listing`, `extraction._from_jsonld`, `schemas.VenuePageExtraction` and
`migrations/env.py` (the injected-connection path `scratch_db.migrate` relies on). Commands:
- `REQUIRE_DB=1 uv run pytest`: **15 failed, 1054 passed, 16 skipped**. The 15 failures are exactly the open-gap tests the log lists
  (4 `test_expected_rows_*`, 3 for K2 including `test_rates_are_computed_from_summed_counts_not_averaged_per_page`, 8 for K4).
  CONFIRMED.
- `uv run ruff check .`: clean. `uv run mypy`: no issues in 135 files. `make designation-check BASE=ea6d1e0…`: exit 0, nothing
  listed. CONFIRMED. (`make check` itself stops at its `test` stage while the gaps are red, as the log says. I did not rerun
  `contract-check` or `e2e`, because the diff touches neither `schemas.py` nor the frontend.)
- In a throwaway `git worktree` (the diff applied on `ea6d1e0`, run with the main checkout's venv, removed afterwards), I applied
  mutations **M1** (index taken after the empty-act filter), **M3** (`run_venue` ignores `policy`), **M4** (no per-attempt score),
  **M5** (committed rows include `removed`), **M6** (committed column scored against the full label) and **M7** (guard accepts
  `calendar_test`). Each one made its named test fail. CONFIRMED. I did not reproduce M2 and M8, which need K2 filled; the log's
  claim for them is PLAUSIBLE.
- In the same worktree I added two probe tests, built on `test_db_score.py`'s fixtures, for rows 1 and 2 below. Output is quoted
  in those rows.

Nothing in the repo was changed apart from this round and the header's Status and Reviewer lines.

**What holds up.** The production change is exactly the two-line `policy` parameter (Verification 5), and `state.policy` reaches
the routers (M3 confirmed). The per-attempt join is sound: `document_for` and `AttemptRecord` share `attempt_count`. The recomputed
findings use the same `fetched_on` the run used (`label.captured_on`). `validate_extraction` reads no variant-only field such as
`status`, so `VenuePageExtraction.model_validate` on a JSON-LD dump is a faithful input (PLAUSIBLE for the model and image routes, as
the log itself says). The scratch-database guard holds: the name is a constant, the host must be local, and there is no escape
hatch. `migrate` uses the injected-connection path `env.py` supports. The fixed-path copy in `run_scenario` (departure 1) is a
real catch, because `show_changes` compares `original_url`. The tests name their sources, and the gap tests are red for the right
reason (`NotImplementedError("TODO(Ari)")`). The gap blocks match the plan's Code, with one wording change (row 4).

**Counts:** 0 blocker, 3 should-fix, 7 nit. **Verdict: proceed after fixes.**

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **In a `sequence` scenario, the second run's committed column counts the first page's surviving rows as invented shows, and those records feed the aggregate's committed column and committed gate.** `run_page` scores `committed_extraction(factory, venue.id)` (every active row of the venue) against `scheduled_only(label)` of the page *just run*. After a correct sequence the database still holds page A's shows outside B's window (the behaviour C5-K3 says must happen), so run 2 reports them as `fabricated`. `evaluate` then turns every scenario run into a `records` entry (`graph_eval.py:418`), and `aggregate` sums them into `columns.committed` and `gate.committed`. A single fabrication fails the gate (A2.1-D1). The scenario's correct measure is `database_score`, scored against `expected_rows`. Fix: in scenario mode, score each run's committed column against what the database should hold at that point, which after run 2 is `expected_rows`. Or keep scenario runs out of the per-page `columns`/`gate` aggregate and report them only under `scenarios`. Add a test that a disjoint sequence leaves `fabricated == 0` in whatever committed figure the aggregate reports. | CONFIRMED: worktree probe running `run_scenario(SEQUENCE)` on `test_db_score.py`'s disjoint pages (Oct 20–21, then Nov 20–21) printed `RUN2 committed: {'labelled': 2, 'returned': 4, 'missed': 0, 'fabricated': 2, 'leaks': 0}`. `graph_run.py:168,182-184`; `graph_eval.py:227-228,418`. | `make eval-graph SCENARIO=sequence` on White Squirrel's August and October captures (Step 8.2) reports a committed-column FAIL with invented shows when the pipeline behaved correctly. That is the same "correct behaviour scored as an error" trap C5-PR1-5 closed for cancelled shows. |  **Fixed.** Test first (`test_the_committed_column_leaves_out_a_run_whose_rows_include_an_earlier_page`): `evaluate` tags the second run of a sequence or overlap `committed_scored: False`; the aggregate's committed column and committed gate skip those runs (`_scored_in`); the scenario's `database_score` is the measure for them. Raw, validated and retry statistics still count them. |
| 2 | should-fix | **The `perturbed` scenario crashes the whole evaluation when a page's first run leaves fewer than two rows (for example, it escalated), and no results file is written.** `_perturb` raises `ValueError` when it can't find two active shows, one of them timed. Nothing in `run_scenarios` or `evaluate` catches it. The `finally` drops `calendar_eval`, and the exception escapes before `out_path.write_text`, so every page already run in that invocation is lost. With the real model an escalated first run is an outcome to report, not an infrastructure failure (the module's own rule, `run_pages` docstring: "a model that does [fail] … the graph records those itself"). Fix: when the first run can't be perturbed, record the scenario instance as "not run" with the reason (as U7 already does for a missing capture) and go on to the next page. Add a scripted test where every attempt fails. | CONFIRMED: worktree probe with a splitter that always drops a title, under `run_scenario(PERTURBED)`. The run escalated after 3 attempts, then `ValueError: the perturbed scenario needs at least two active shows, one with a start time` at `db_score.py:176`. `graph_eval.py:413-425` (no handler; file write after the `try`). | On the laptop, Step 8.2's `SCENARIO=perturbed` over every labelled page aborts at the first page that escalates or has a single timed show. A long local run produces nothing. |  **Fixed.** Test first (`test_a_perturbed_scenario_whose_first_run_left_nothing_to_perturb_is_reported_not_raised`, and the runner test): `_perturb` raises `ScenarioNotRunnable`; `run_scenario` returns the first run with `not_run` set; `run_scenarios` records the reason, skips the database score and goes on; the results file is still written. |
| 3 | should-fix | **`--rescore` leaves scenario results stale, so a rescored file contradicts itself.** `rescore` recomputes `data["runs"]` and the aggregate, but not `data["scenarios"][*]["database_score"]` (the `expected_rows` score), and not the per-run scores nested in `data["scenarios"][*]["result"]["runs"]`. After a label correction, the top-level committed column moves and the scenario block keeps the old numbers. Plan §3 says a rescore "rebuilds every score from the stored data". The stored `rows` that `score_database` needs aren't kept either: only the per-run `committed` is, and run 2's `committed` is the final rows, so it can be rebuilt from that. Fix: rescore `database_score` from the last run's stored `committed` and the scenario's page labels, and rescore the nested runs, or drop the nested copies. Extend the rescore test with a scenario entry. | CONFIRMED by reading: `graph_eval.py:244-272` (only `data["runs"]` touched), `:357-361` (what a scenario entry stores). | A corrected label, the reason `--rescore` exists (A2.1-PR1-13), silently doesn't reach the database scores. The scenario figures in a rescored baseline are the old labels' numbers under the new `labels_sha`. |  **Fixed.** Test first (`test_rescore_also_rescores_the_scenarios_database_score`): `rescore` shares `_rescore_run` with the nested scenario runs and recomputes each scenario's `database_score` from the last run's stored rows and the scenario's page labels. |
| 4 | nit | **C5-K3's Check names the wrong symptom.** Returning only the second page's shows for a sequence doesn't score anything as *missing*. The first page's surviving rows are in the database and absent from the expectation, so they score as **fabricated** (row 1's probe shows the same mechanism). The block says "'October shows missing'" (`db_score.py:276`), and `test_expected_rows_after_pages_a_month_apart_hold_both_pages` says "'October missing'". The plan's version said "'August shows missing'", which is wrong the same way and is also a silent wording change from the plan's Code. Fix: "scores the first page's surviving rows as invented shows". | CONFIRMED: `score_page` counts unmatched returned shows as extras (`scoring.py`, `matching.extras` → `fabricated`); probe output in row 1. | Ari aligns with a Check whose failure description doesn't match what he'd see. |  **Fixed.** The K3 Check in `db_score.py`, its test comment and the plan's K3 block now say the first page's surviving rows score as invented shows. |
| 5 | nit | **`_dropped_index` picks the first empty-act show on the date, which may be a correctly excluded non-show rather than the dropped one.** On a JSON-LD page with a non-music listing (acts `[]`, `excluded_no_acts` warning only) and a splitter-dropped show (`splitter_dropped` error) on the same date, the missed label can take the non-show's index. Validation recall then says "flagged" where it should say "caught". Fix: prefer an empty-act show whose index carries a `splitter_dropped` finding, or match the dump's title against the label's `source_line`/acts. Alternatively, note the limit in the docstring. | PLAUSIBLE: `scoring.py:270-281` (date-only match, first wins); `validation.py` puts `splitter_dropped` only on dropped ids. | A small, systematic undercount of `caught` on pages that list non-music nights beside shows. |  **Fixed (documented).** `_dropped_index`'s docstring states the limit (date-only match; a non-music entry on the same date can take the index) and why a dump gives nothing finer to match on; the per-kind table makes any undercount visible. Matching on a title would need the dump to carry one, which it does not. |
| 6 | nit | **`recompute_findings` doesn't check the document's `route` against the source validation received, which Step 4 says it does, and the log doesn't list this as a departure.** It passes `document["route"]` (`state.route_attempted`) as `source`. `validate_node` passes `state.extraction_source`. `_route_for` and `extract_page` decide the route independently, so they agree today, but nothing asserts it. `findings_disagree` would surface a drift on errors, but not on warnings. | CONFIRMED by reading: `validation_recall.py:122-127`; `nodes.py:199,217,246`; plan Step 4 ("checked against the `extraction_source` validation received"). | A future route change (for example, a JSON-LD page falling back to the model) would recompute warnings under the wrong source with no signal. |  **Fixed.** `run_page` compares the final attempt's staged route with `extraction_source` and records `PageRun.route_mismatch`; the aggregate counts `validation.route_mismatches`; a clean run asserts False (`test_graph_run`) and the aggregate counts a True (`test_graph_eval`). Step 4's wording now matches what is checked. |
| 7 | nit | **`label_draft` prints every visible line (dated ones marked `>`), not "each line that contains a date … and nothing else" (Step 7, §6), and this isn't listed as a departure.** The behaviour is arguably better, since many pages put the date and the act on different lines, but it does print act names from the page text. That is allowed (labels are read from the page text), but the plan's §6 row says "prints no act names". | CONFIRMED by reading: `label_draft.py:155-177`; `test_label_draft.py:24-34` (asserts undated lines are listed). | The plan and the tool disagree. A reader of §6 expects a different output. |  **Fixed.** The plan's Step 7 and §6 now describe the tool as built (every distinct visible line, dated ones flagged, nothing from structured data) and say why; recorded as departure 7 in the Implementation log. |
| 8 | nit | **Step 9 is only partly done, and the log doesn't say so.** `alpha-build-plan.md` A8's pointer line has no C5 status (the file isn't in the diff). The C5 note in `alpha-deployment-plan.md` doesn't record departures 1 to 4 (Step 9: "record departures 1 to 4"). The `EVAL_DATABASE_URL` override that `evaluate` reads (`graph_eval.py:408`) isn't documented in `apps/api/AGENTS.md`, the Makefile help or this plan. | CONFIRMED: `git diff ea6d1e0 --stat` (no `alpha-build-plan.md`); `alpha-deployment-plan.md` diff (status note only). | Docs drift. An undocumented environment knob points the harness's server choice somewhere a reader can't find (the guard still forces `calendar_eval` on a local host). |  **Fixed.** `alpha-build-plan.md` A8 has a C5 status line; the deployment plan's C5 note records the departures; `EVAL_DATABASE_URL` is documented in `apps/api/AGENTS.md` and the Makefile comment. |
| 9 | nit | **The `stub_judgements` fixture copies C5-K2's and C5-K4's Code into the tests, so once Ari fills a gap differently, the aggregate tests still test the copy.** The plan explicitly allows Ari to widen K4 (Step 4's note). The one red aggregate test without the stub covers K2 only. Fix: once the gaps are filled, drop the stub (the cleanup pass in `AGENTS.md` step 4 is the natural place), or add one aggregate test of validation recall that uses the real `coverage`. | CONFIRMED by reading: `test_graph_eval.py:40-62`, and the `usefixtures("stub_judgements")` uses. | Ari's actual K4 definition never reaches an aggregate-level test, and a later edit to it can't turn one red. |  **Fixed.** `stub_judgements` is split: `stub_rates` stands in for K2 only, and a new test (`test_validation_recall_in_the_aggregate_follows_the_real_coverage_definition`) uses the real `coverage`, so Ari's K4 reaches an aggregate-level test (red until filled). Dropping the stubs entirely is part of the closed-gap cleanup pass (`AGENTS.md`, step 4). |
| 10 | nit | **The approval isn't recorded in the header.** At the diff base the Status was `Awaiting approval` and the D1–D7 "Ari's answer" cells were empty. The same uncommitted change fills all seven with "Accepted as recommended (Ari, October 29, 2026)" and sets Status to `Code review`, with no `Approved` step in between. The deployment-plan note says Ari approved, which is likely right. But `AGENTS.md` reserves steps 4 and 8 for Ari, and the file is the record. | CONFIRMED: `git diff ea6d1e0 -- docs/dev/implementations/c5-pipeline-eval-harness.md` (Status line and the D1–D7 rows). | Nothing goes wrong if Ari did approve. The point is that the file alone can't show it. Ari confirms, or the header gains a line saying when and how he approved. |  **Fixed.** The header has an `Approval:` line recording when and how Ari approved (accepted D1 to D7 and invoked `/build-milestone`). Ari should confirm it is accurate at sign-off. |

**Rejected:** none. All 10 findings were checked and accepted (rows 1 and 2 reproduced by the reviewer with probe tests; the fixes started from failing tests).

**After the fixes:** `uv run ruff check .` clean; `uv run mypy` clean (135 files); `REQUIRE_DB=1 uv run pytest`: **16 failed, 1059 passed, 16 skipped**. The 16 are the 15 open-gap tests plus the one new test that uses the real `coverage` in the aggregate (`test_validation_recall_in_the_aggregate_follows_the_real_coverage_definition`, red until C5-K4 is filled); the 12 tests added in this pass for rows 1, 2, 3 and 6 are green. `make designation-check BASE=ea6d1e0ae773c705b45b22093a2405ba920a78bc` exit 0; `make contract-check` current. `make e2e` was not rerun: the pass changed no schema, route or frontend file (it passed, 104, before it).
