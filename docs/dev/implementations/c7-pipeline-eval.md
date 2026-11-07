# C7 — pipeline evaluation on the shipped model

**Status:** Awaiting sign-off (Steps 1 to 10 done; the defaults decided by Ari November 6, 2026 (threshold 0.8, cap 2, no escalation model), applied and code-reviewed in two rounds with every finding resolved; Ari also decided November 6 to keep the final-attempt sentence off the cap's last attempt, as shipped; the DeepInfra spend after C7 is unread)
**Date:** November 6, 2026
**Author model:** Claude Opus 5.5 (plan, November 6, 2026; written in a local session, with the saved C5 and C6 results files on disk)
**Reviewer model:** Claude Sonnet 5.5 (plan review round 1, November 6, 2026); code review round 1: Claude Sonnet 5.5 (November 6, 2026); code review round 2: Claude Opus 5.5 (November 6, 2026)
**Spec:** `docs/dev/alpha-deployment-plan.md` §6 C7 (and Dep-D5, Dep-D13, Dep-D15, §5.1 row C7); `docs/dev/alpha-build-plan.md` §5 A8
(the pointer); `docs/dev/implementations/a3-validation-and-retry.md` (A3-D5 the escalation tier, A3-D9 the confidence signal and
the 0.8 threshold, A3-D11 the policy on the state, A3-K4 `combine`, A3-K5 `plan_for_attempt`); `docs/dev/implementations/c5-pipeline-eval-harness.md`
(C5-D4 how many errors C7 needs, C5-D5 the policy flags, C5-D7 per-attempt scoring, Implementation log Rounds 4, 5 and 7: C5-F1,
C5-F4, C5-F6, C5-F10 to C5-F14); `docs/dev/implementations/c6-hosted-inference.md` (C6-D4 what escalation swaps, C6-D8 held-out
discipline, Rounds 4, 8 and 10); `docs/dev/implementations/c6.1-embedded-events-reader.md` (C6.1-D7, which pages are still held out);
`docs/arch/arch-initial.md` §7 ("Validation and retry") and §11 ("Review flag for uncertain act splits", "Production run-health
monitoring"); `docs/dev/evaluating-model-performance.md`; `apps/api/agent_worker/model_eval/README.md`;
`docs/references/fastapi-style-guide.md`; `apps/api/AGENTS.md`

**Designations.** Inside this plan the decisions are `D1`–`D9`, the fill-in key points `K1`–`K3`, the questions C7 answers `Q1`–`Q4`,
the pre-registered readings `R1`–`R4` (one per question), the measured facts `F1`–`F6` and the mutation checks `M1`–`M7`; elsewhere they
are written `C7-D1`, `C7-K1`, `C7-Q1`, `C7-R1`, `C7-F1`, `C7-M1` and so on (`docs/dev/conventions.md`). **Code, tests, code comments and
every other document write the scoped form, never the bare one**, and the build step copies from this file, so a `TODO(Ari)` block cites
`C7-K2`, never `K2`. Review items are `C7-PR<round>-<n>` for the plan review and `C7-CR<round>-<n>` for the code review. Other plans' IDs
carry their scope (`A3-D9`, `C5-F11`, `C6-D8`, `Dep-D13`). `C7` is a new scope: the build adds a `C7` row to the scope table in
`docs/dev/conventions.md`.

## Context

A3 built the retry policy with three numbers nobody had measured: a **confidence threshold** of 0.8 (the literal in the old router,
A3-D9), an **attempt cap** of 3 (`arch-initial.md` §7), and a **third tier** that swaps in a larger model (A3-D5), which on the laptop
reran the same model. A3 left the questions to A8, and A8's second half became this milestone (Dep-D5). They are model-dependent, so they
waited for the shipped model. C6 chose it: `google/gemma-4-26B-A4B-it` on DeepInfra for every role, temperature 0, no escalation model
(`c6-hosted-inference.md`, Round 10).

The four questions, as the deployment plan words them:

| ID | Question | Deployment plan bullet |
|---|---|---|
| Q1 | Is 0.8 the right confidence threshold? | 1 |
| Q2 | Is 3 the right attempt cap? | 1 |
| Q3 | Does the escalating retry recover failures or only cost tokens, and does tier 3 help once it is a real larger model? | 1 |
| Q4 | Does the model's self-reported confidence correlate with correctness against the labels? | 2 |

Bullet 3 changes the defaults or confirms them, with the numbers recorded. **Done when** each of Q1 to Q3 is answered with data and the
policy is changed or confirmed.

### What is already measured (read from the saved results files, November 6, 2026)

Before writing this plan the author read the raw results files C5 and C6 left on the laptop (gitignored, `model_eval/results/`) with a
throwaway script in the session scratchpad, joining each returned show's `confidence` to the scorer's error items at that show's index.
No model was called. These are facts the design rests on; the build re-derives them with the real instrument (Step 7), so none is quoted as
a result.

| ID | Fact | Evidence |
|---|---|---|
| F1 | **At the default policy the hosted model never retries.** 0 retries in 45 page-runs: `c6-confirm-gated` (25) and `c6-confirm-heldout` (20); also 0 in `c6-hosted-baseline`. The retry loop, the cap and tier 3 have never run on the shipped model. | `aggregate.retry` of each file: `retried 0`, `attempts_by_tier {initial: N}` (CONFIRMED) |
| F2 | **The hosted model's confidence is coarse and high.** Every model-route value is one of 0.5, 0.8, 0.9, 1.0. Mortimer's is 0.9 on all 35 show-instances; Turf Club 0.9 or 1.0; 7th St Entry mostly 0.9 or 1.0. | Same files, per-show `confidence` in each staged `raw_extraction` (CONFIRMED) |
| F3 | **Its low values fall on shows the pipeline then drops.** The only values under 0.9 (7th St Entry, 0.5 or 0.8 on three shows in three of five runs) are on shows with no acts, which validation excludes (`excluded_no_acts`) before `aggregate_confidence` takes its minimum over kept shows. So the record's confidence never fell below 0.8 and nothing could retry. | `c6-confirm-gated`, 7th St Entry, shows 8, 15, 21: `acts: []` (CONFIRMED); `validation.aggregate_confidence` takes kept shows only (read) |
| F4 | **Confidence does not mark the hosted model's errors.** On Icehouse (model route, 47 shows) all 255 show-instances are 1.0, and 98 of the shows returned with acts (the kept shows, K1's population) carry an error; a further 14 are dropped shows (`acts: []`) the scorer reports as `missed` with their index, which K1 leaves out because validation excludes them (C7-PR1-1, C7-PR1-12). Turf Club's two wrong shows are 0.9, as are 15 correct ones. | `c6-confirm-heldout`, `c6-confirm-gated` (CONFIRMED by the author and by the reviewer; one venue dominates, see "What is not covered") |
| F5 | **On the shipped route, confidence is not about acts.** The model route is title split (`PIPELINE_CONFIG.title_split=True`): the page model returns each listing's date, time, prices, verbatim title and a `confidence`; the act splitter turns titles into acts and returns **no confidence** (`act_split.ActSplitItem` has `id`, `title`, `acts`). So a show's confidence is the page model's opinion of the listing, and the dominant error kind (wrong acts: C5-F1, C6 Round 10 misses 1, 2 and 5) is made by a call that reports none. The structured route has no confidence at all (`aggregate_confidence` returns None for it). | `extraction._shows_from_listings`, `act_split.py`, `validation.aggregate_confidence` (read) |
| F6 | **On the local model, retrying did not help on net and confidence did not track correctness** (18 errors before and 18 after on the retried pages; a clean poster escalated, pages with errors accepted). | C5-F10, C5-F11 (`c5-baseline-retry`) |

Two further facts shape how the retry runs are read:

- **A hosted retry is also a resample.** DeepInfra does not honour `seed` (C6 Round 2), and Turf Club drops its second act in 1 run of 5
  (C6 Round 10, miss 5). An attempt 2 with fewer errors than attempt 1 may be the hint working or the dice. The instrument therefore
  measures the **noise floor**: how much attempt 1 of one run differs from attempt 1 of another, with no hint (K3 is used for both).
- **What a retry actually changes depends on why it failed.** A failure for low confidence puts one sentence in the *page* hint ("return
  only what the page states", `policy._REASON_ADVICE`) and nothing in the *splitter* hint until the last attempt, which adds the
  final-attempt sentence ("copy each act's name exactly as the title writes it"). The checks that would target the splitter
  (`splitter_dropped`, an error; `act_not_in_title`, a warning) fire on almost none of the real errors (C5-F1: 0 of 24 caught; C6 Round 8:
  1 catch in about 150 runs). So on the shipped route, tier 2 changes the request the act errors come from only indirectly, and tier 3
  changes it with the final sentence and, when one is configured, a larger model.
- **So what C7 can test of Q3 is narrower than the question** (C7-PR1-11). On the shipped route a forced attempt 2 sends the splitter a
  byte-identical request (an empty splitter hint), so any change in act errors at tier 2 is a resample; the page model gets one generic
  sentence. The production path that retries with a *specific* hint (a check error whose finding messages become the hint) is not exercised,
  because on the shipped model it never fires (F1). A negative answer to Q3 therefore means "a generic low-confidence hint plus a resample, and
  at tier 3 the final sentence plus a larger model, do not recover the errors", **not** "the escalating retry cannot recover failures". The
  log words the answer that way, and R2 inherits the scope.

### What C7 delivers

| Item (deployment plan C7) | Marking | Where it lands |
|---|---|---|
| Q1–Q3 with the harness: the threshold, the cap, the retry and its tier 3 | **[fill-in]** as marked; gaps `C7-K2` (what a threshold would have done) and `C7-K3` (what a retry changed) | `model_eval/saved_run_reports/policy_questions.py` (new, pure), two harness flags, per-attempt confidence and tokens in the results file, a report |
| Q4, confidence against correctness | **[fill-in]** as marked; gap `C7-K1` (which shows count as wrong) | the same module |
| Update the retry policy's defaults if the data says so, and record the numbers | **[written]**, after Ari's answer at Step 9 | `agent_worker/policy.py` (only if a number changes), `docs/dev/environments.md` (only if an escalation model is adopted), the docs listed in Step 10 |
| The measurement runs | **[written]**, **local only** (DeepInfra key, the gitignored captured pages, Postgres) | Ari's laptop; numbers in this file's Implementation log, snapshots in `docs/dev/eval-baselines/` |

The code is deterministic and tested with constructed records and the scripted client, so it is cloud-buildable; the runs are not
(`AGENTS.md`, "Cloud sessions").

### Decisions already made (earlier in this project)

- **The standard is A2.1-D1's and C7 does not redefine it.** A gate error is a missed show, a wrong act list or an invented show on a gated
  page; a wrong field is never allowed; a missing field is tolerated at most 1 in 10.
- **A verdict, not a float** (A3-K4): a check error fails a record whatever the confidence; low confidence fails it only when nothing else
  has; None confidence is no evidence. C7 measures the threshold inside that rule and does not reopen it.
- **The policy is varied by passing a different `RetryPolicy`** (A3-D11, C5-D5): `run_venue(..., policy=)`, built on `DEFAULT_POLICY` with
  `dataclasses.replace` so the configured escalation model is kept (`run_labeled_pages.build_policy`).
- **Every attempt is scored** (C5-D7), from its staged document; validation's findings are recomputed from the document, a pure function
  (C5-PR1-6). C7 extends the same recomputation to the attempt's confidence.
- **Escalation swaps the page, splitter and status models together; the matcher keeps its own** (C6-D4). Escalating only the failing call is
  "a policy change that belongs to C7" (C6-D4); see D7.
- **The `ACT_NOT_IN_TITLE` check stays a warning** (C6 Round 8, Step 10) unless new evidence says otherwise; C7 does not revisit it.
- **Held-out discipline** (C6-D8): a held-out page is scored once per configuration; a page whose misses motivated a change is burned. Ginkgo
  Coffee and Icehouse are burned and Hook & Ladder is no longer held out (C6 Round 10, C6.1-D7); Dakota is the one page still held out.
- **One harness run at a time**; the raw results files never reach git; snapshots are committed (`evaluating-model-performance.md`).

### Departures from the deployment plan

1. **The threshold is answered mostly offline.** The threshold only decides whether an attempt fails; it does not change what attempt 1
   extracts. So one run at the default policy, with each attempt's confidence recorded, says what *any* threshold would have done to attempt 1
   (K2), without a run per threshold. What a retry then does is Q3's measurement, which needs real runs.
2. **Retries are forced, not provoked.** C5 provoked them with a threshold of 0.99 (C5-D5). On the hosted model that would fire on almost
   nothing (F2, F3). C7 adds `--force-retries`, which fails every model-judged attempt for low confidence (D3), so the retry's effect is
   measured on every model-route page instead of on the few that happen to dip.
3. **Of the held-out set, only Icehouse is run** (D1): the other three are structured-route pages that cannot inform any of the questions.

## Decisions for the user / reviewer

*Each has a recommendation, and the plan is written as if it is accepted. D1, D2, D4, D5 and D9 are Ari's; D3, D6, D7 and D8 are defaults
to veto.*

| ID | Question | Recommendation |
|---|---|---|
| D1 **[Ari]** | **Which pages.** Q4 needs errors, and on the hosted model the errors sit mostly in the held-out and informational pages (Icehouse, Hook & Ladder, Terminal Bar). Tuning a policy number on Dakota spends the last held-out page. | **`SET=all` (gated and informational), plus the held-out set restricted to Icehouse (`SET=held_out ONLY=icehouse`), as separate labels read together** (C7-PR1-8). Icehouse is the only held-out page on a model-judged route, and it is already burned. Dakota, Ginkgo and Hook & Ladder are structured-route pages: their confidence is None, they raise no check errors (C6 Round 10), and they pass attempt 1 even in a forced run (D3), so scoring them again would cost money and Dakota's held-out status for no information. **Dakota stays unscored by C7 and no `labels.py` note is needed.** Their default-policy behaviour is already on record in `c6-confirm-heldout`, which Step 7 rescores without a model call. The next honest test of a policy number is C11's burn-in sample |
| D2 **[Ari]** | **The escalation model for the tier-3 measurement.** C6 measured two larger models as splitters, under the prompt rules before `c6-prompt-v4`: `google/gemma-4-31B-it` (about 2x slower, the same misses) and `Qwen/Qwen3-235B-A22B-Instruct-2507` (worse, 2.7x slower). Neither has run as a whole-attempt escalation, and neither under the current prompts. | **`google/gemma-4-31B-it`.** Same family as the shipped model, so the act conventions the prompt was written for carry over; the price is still a fraction of a cent a page. Ari confirms the id is still served (`/v1/models`) before Step 8. A second candidate is run only if D5's rule R3 says the first one is close |
| D3 | **How to force a retry.** A threshold above 1.0 makes every model-judged attempt fail for low confidence (the schema caps confidence at 1, `ge=0, le=1`), with no production change. An oracle that fails an attempt whenever the *labels* show an error would measure retry's ceiling, but needs the pipeline to see labels | **`--force-retries` on the harness (Makefile `FORCE_RETRIES=1`), which sets the threshold to a named constant `FORCED_THRESHOLD = 1.01` and is recorded in the results file and the report header.** No oracle: production code must not import labels (`test_layering.py`), and the hint an oracle could honestly give is the same low-confidence sentence. **Limits, stated in the report:** the structured route has no confidence, so it is never forced (2 of 5 gated pages, 3 of 4 held-out); a forced page always escalates and commits nothing, so only its per-attempt columns are read; the low-confidence hint is the only tier-2 hint a forced run can test (see Context) |
| D4 **[Ari]** | **Budget.** | **$5 of DeepInfra spend for C7**, read off the dashboard before and after (C6 spent $0.40 in all). The plan's runs are estimated at well under $1 (PLAUSIBLE: about $0.001 a page-attempt on the 26B, Round 8 of C6; the 31B tier costs more per token and appears only on attempt 3). Stop and report if the dashboard passes the budget |
| D5 **[Ari]** | **The readings, fixed before the numbers exist.** A small, clustered sample can be read to support almost anything after the fact. | **Accept R1 to R4 below as the rules that turn the measurements into a recommendation.** Ari still decides at Step 9; the rules decide what the author recommends, and the log says where a rule was not followed and why |
| D6 | **Tokens per attempt in the graph harness.** C5 recorded seconds only (C5 Round 7); C6 added a token counter to `run_eval` only. "Or only cost tokens" needs tokens per attempt | **Yes**, reusing `run_eval.RunCounters` and its completion hook (already registered on the pipeline's `instructor_client` when the harness imports `run_eval`). The per-run counter is set around `run_page`; the in-memory stager reads it at each `stage()`, so the difference between two stagings is one attempt's extraction calls (page, splitter, status). Reconcile's matcher calls come after the last staging and are reported as the run's remainder. None, never 0, when no response carried `usage` |
| D7 | **Escalate only the failing call** (C6-D4 left it to C7) | **Not in C7.** It is a design change, and the data C7 collects (does tier 3 help at all, R3) decides whether it is worth one. If R3 says tier 3 helps, the log proposes it as a follow-up with the numbers |
| D8 | **The validation ideas C5 handed to C7** (C5-F4 a reverse title check, C5-F6 a name-like title triggering a retry, C5-F14 a "failed for any reason" column in validation recall) | **F14 yes; F4 and F6 no.** F14 is a reporting change that forced runs need to be read at all (every forced attempt fails for low confidence and has no finding, so "silent" would swallow everything): validation recall gains a `stopped` count, errors on an attempt that failed for any reason. F4 and F6 are new checks, a validation milestone of their own. C7 still informs them: **if forced retries do not fix act errors (R3), a check that triggers a retry cannot help either, and the right home for those signals is the review flag (`arch-initial.md` §11), not the retry loop.** The log says which way the data points |
| D9 **[Ari]** | **Q4's sample, decided now rather than after the readings** (C7-PR1-7). On the saved hosted runs, R1 will very likely read "not enough evidence": outside Icehouse there are 2 wrong kept show-instances (Turf Club), and Icehouse is one confidence value (1.0). C5-D4 left the sizing to this plan. | **Accept the likely "not enough evidence" now, and do not label more pages for C7.** F5 already gives the structural answer: on the shipped route the confidence is the page model's opinion of a listing, and the splitter that makes the act errors reports none, so even a well-calibrated number could not route the dominant error kind. Labeling two or three more model-route pages (hours of Ari's time) would most likely confirm that. **To widen the evidence for free**, the report adds a clearly labeled **secondary table** from the saved hosted graph runs under older prompts (`c6-hosted-baseline`, `c61-icehouse`, `c61-icehouse-price`, `c61-split-before`, `c61-split-after`, rescored; structured-route pages in them give no rows), never pooled with the primary one, since the prompt differs. Alternative: Ari labels further model-route pages before Step 7, and R1 is read on those |

## The readings (pre-registered, D5)

Written before any C7 run, so the numbers cannot choose their own interpretation.

**Three definitions, used everywhere below** (C7-PR1-2). They are written once, in `policy_questions.py`, and the gaps decide the first two:

- **A wrong show** (Q4's unit, K1): a *kept, model-judged* show (one that reaches the record's confidence: not excluded by validation, not
  added by the status merge, not on the structured route) that carries an error of a kind A2.1-D1 says should not be in the calendar as
  written: wrong acts, invented, a non-music leak, a wrong field or image. A missing field is not wrong (tolerated, 1 in 10). A leak is
  wrong *for this question* although the gate tolerates one a page: the question is whether this row is right, not whether the page passes.
- **A page-run that should retry** (K2): its attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (any missed, wrong-acts,
  invented show or wrong field; more than one leak; a field over 10% missing), on a gated page. The sweep calls the scorer's own gate, so the
  standard is not re-coded. Informational pages are reported on their own line.
- **An error count** (K3, R3, R4): the error items of the kinds above plus `missed`, i.e. every kind except `field_missing`, counted per
  page-run.

**The noise band** (C7-PR1-10). For each page, the population standard deviation of attempt 1's error count across that page's runs (5 runs, on the same
label). It is what the same request resampled already moves by, since a hosted retry is also a resample. **Amended in code review, before any C7 run
(C7-CR1-1):** a change must also exceed a floor of **0.5 errors a run** (`MIN_EFFECT`), because a page whose attempt 1 gives the same count in every
run has a band of exactly 0, and one run differing by one error would otherwise read as "helps" or "hurts". **Ari confirms this amendment at sign-off
(D5 is his).** And an attempt is compared with attempt 1 **of the same runs**, the ones that reached it (C7-CR1-2).

| ID | Question | Reading |
|---|---|---|
| R1 | Q4: does confidence correlate? | Over the wrong-show rows (K1), buckets by confidence value, a bucket compared only when it holds at least 10 instances. **Yes** only if the wrong rate of the lowest compared bucket is at least twice the highest's **and** that holds on at least two venues separately. **No** if the rate is flat or inverted. **Not enough evidence** if fewer than 20 wrong instances come from venues other than the largest contributor, or fewer than two buckets reach 10 instances. "Holds on a venue" applies the same 10-row minimum inside that venue (two of its own values with 10 or more rows each), stated in code review (C7-CR1-3). The 20 and the 10 are judgement, not statistics: below them a rate turns on one or two shows. No p-values: the instances are not independent (the same show five times, one page's layout). The secondary table (D9) is read by the same rule and reported, never pooled |
| R2 | Q1: is 0.8 right? | From the threshold sweep (K2) on attempt 1 of the default runs: a threshold `t` is **better** than 0.8 only if it sends more should-retry page-runs to a retry (caught) **and** R3 says a retry helps. If R3 says it does not, no threshold helps, and the recommendation is to **confirm 0.8 and document it as inert on the shipped model** (it costs nothing when it never fires), not to tune it to noise, with R3's scope (Context) carried into the wording. Lowering it to 0 is offered only if 0.8 is shown to send correct pages to escalation (false alarms that throw data away, C5-F13) |
| R3 | Q3: does the retry recover? | From the forced runs, **per page**: attempt `k` **helps on a page** when the page's mean error count at attempt `k` is lower than at attempt 1 (over the same runs) by more than the page's noise band and by more than 0.5 (C7-CR1-1), and **hurts** when higher by as much. Tier 2 **helps** if attempt 2 helps on at least two pages and hurts on none; tier 3 likewise, comparing attempt 3 with attempt 2, run once without and once with the escalation model, and the escalated tier must also beat the unescalated one by the same rule. Two pages, so that Icehouse cannot carry it alone. Otherwise "only costs": report seconds and tokens per attempt. K3's fixed and introduced counts are reported beside it as the description of *what* moved. Adopt an escalation model in the defaults (`ESCALATION_MODEL_NAME` per environment) only if tier 3 with it helps. The answer is worded within the scope the Context states |
| R4 | Q2: is 3 right? | **Keep 3** unless attempt 3 hurts (R3's rule) on any page and helps on none (then recommend 2: the last attempt is pure cost). Recommend 4 only if attempt 3 helps on at least two pages; a fourth attempt is not run in C7 unless that happens. Note beside it: at the default threshold the cap matters only when a check error fires, which F1 says almost never happens |

## Test approach (written first, watched fail, then made green)

Tests come first (`alpha-build-plan.md` §3). The expected values come from **constructed run records** (literal attempts, confidences
and error items written in the test, with the answer that follows from them), **scripted models** (`tests/fakes.py`'s `scripted_client`), and
**the plan's definitions** (K1 to K3, quoted in the tests' comments). No test computes its expectation with the function it tests. Everything
runs in the cloud; nothing calls DeepInfra or Ollama.

### 1. Confidence against correctness (`tests/model_eval/test_policy_questions.py`; K1 rows red until filled)

| Case | Expected | Source |
|---|---|---|
| An attempt on the model route: shows at indexes 0 to 4 with confidences 1.0, 0.9, 0.9, 0.5, 1.0; judged indexes 0, 1, 2, 4 (3 was excluded for no acts); error items `acts_wrong` at 1, `field_missing` at 2, `missed` with index 3, `missed` with index None | Rows `(1.0, correct)`, `(0.9, wrong)`, `(0.9, correct)`, `(1.0, correct)`; the excluded show 3 and the index-less miss give no row | K1: only judged shows reach the record's confidence (`validation.aggregate_confidence`; C7-PR1-1); `field_missing` is tolerated, so not wrong |
| **An excluded, unlabeled show with a low confidence** (the real 7th St Entry shape, F3): index 2 at 0.5, `acts: []`, not judged, no error item | No row for it | C7-PR1-1: scoring it "correct" would fill the lowest bucket with shows the pipeline discards and invert Q4 |
| A status-merge show (in `notes["added_indices"]`, placeholder 1.0) | No row | `validation.aggregate_confidence` skips it |
| The same with `fabricated`, `leak`, `field_wrong`, `image_wrong` items on judged shows | Each makes its show wrong | K1; the leak is wrong for this question although the gate tolerates one a page ("The readings", definitions) |
| An attempt on the structured route (and one stored as `"jsonld"`), with placeholder confidences 1.0 recorded | No rows | F5: the route's 1.0 is a placeholder (`extraction._from_structured`); K1 reads the route through `policy.stored_route` (C7-PR1-3) |
| The image route | Rows, like the model route | The poster's confidence is the model's |
| Buckets over rows from two venues | Count and wrong rate per confidence value, in total and per venue; a bucket under 10 instances is shown but not compared; the R1 verdict reads "not enough evidence" when fewer than 20 wrong rows come from outside the largest venue | R1 |
| The excluded shows' confidences | Reported in their own line (correct exclusions and wrong ones, the latter being `missed` with an index), never in R1's buckets | F3: where the model's low values actually go |
| An older results file with no `show_confidences` | The section says "not recorded (rescore to fill it)" and does not crash | Older files load (C5 rule) |

### 2. The threshold sweep (same file; K2 rows red until filled)

| Case | Expected | Source |
|---|---|---|
| Attempt-1 records `(reasons, confidence, fails the standard)`: `([], 0.9, yes)`, `([], 0.9, no)`, `([], None, yes)`, `(["check_errors"], 1.0, yes)`, `([], 0.5, no)` at `t = 0.95` | Cells: caught, false alarm, missed, caught, false alarm | K2's definition; None confidence never fails (A3-K4) |
| "Fails the standard" comes from `scoring.gate` on that page's attempt-1 score: a page with two leaks and nothing else fails; one leak alone does not; one wrong time fails | yes, no, yes | A2.1-D1 as `scoring.gate` encodes it (C7-PR1-2): the sweep never re-codes the standard |
| The same at `t = 0.8` | missed, quiet, missed, caught, false alarm | K2 |
| `low_confidence` in the stored reasons is ignored and recomputed at each `t` | A record failed at 0.8 only for low confidence, confidence 0.85, is quiet at `t = 0.5` | The sweep asks what *another* threshold would have done |
| **The mirror agrees with production:** for a table of `ValidationResult`s (check errors or not, extraction failed or not, unreadable or not, confidence None, 0.79, 0.8, 0.81) and thresholds 0.5, 0.8, 0.81, 1.01, `would_fail(reasons, result.confidence, t)`, where `reasons` are the reasons `combine` gives at threshold 0 (so no `low_confidence`), equals `policy.combine(result, replace(DEFAULT_POLICY, confidence_threshold=t)).verdict is Verdict.FAILED` | Equal on every row | `policy.combine` is the production rule and a different unit from `would_fail` (K2, which `sweep_cell` calls; C7-PR1-5); the test pins that the mirror never drifts (M3) |
| A page with gate errors on an informational page | Counted, but in a separate "informational" line from the gated cells | A2.1-D2: informational pages never gate |

### 3. What a retry changed (same file; K3 rows red until filled)

| Case | Expected | Source |
|---|---|---|
| Attempt 1 items `acts_wrong 2026-11-13`, `acts_wrong 2026-11-14`, `missed 2026-11-20`; attempt 2 items `acts_wrong 2026-11-14` (at a different index), `fabricated 2026-11-22` | fixed 2, introduced 1, kept 1 | K3: an error's identity is `(kind, date, field)`, never `index`, because positions shift between attempts |
| Two `acts_wrong` on one date in attempt 1, one in attempt 2 | fixed 1, kept 1 | K3: a multiset, not a set (two shows on one date) |
| `field_missing` items | Not counted | The error-count definition ("The readings") |
| A `field_wrong` (time) introduced on attempt 2 | introduced 1 | C7-PR1-2: a retry that makes a field wrong is a retry that hurt |
| K3 between runs: three runs of one page, attempt 1 each, with items A; A; A and B | Churn per pair of runs (0 + 1 + 1) / 3, reported as description | K3 applied between runs |
| The noise band and R3's per-page rule: a page's attempt-1 error counts over 5 runs 20, 18, 19, 21, 20 (mean 19.6, population sd 1.02) and attempt-2 counts 19, 18, 20, 20, 19 (mean 19.2, against 19.6) | Neither helps nor hurts (0.4 is inside the band); with attempt-2 counts 17 each (mean 17, 2.6 lower) it helps | R3's rule; the expected values are worked from the numbers in the row |
| R3's verdict over pages: helps on one page only | "does not help" (two pages needed) | R3: Icehouse cannot carry it alone (C7-PR1-10) |
| Per tier: forced runs with attempts initial, narrowed, larger_model | Transitions 1→2 and 2→3, each with fixed, introduced, seconds and tokens; tier 3 split by `larger_model_used` | R3, R4 |

### 4. The harness records what the questions need (`tests/model_eval/test_run_one_page.py`, `test_run_labeled_pages.py`, extended)

| Case | Expected | Source |
|---|---|---|
| A scripted model-route run with one no-acts listing | Each `AttemptResult` has `confidence` (the minimum over judged shows), `show_confidences` (one per raw show, by index, as the model gave it) and `judged_indices` (every index except validation's `excluded` and the status merge's `added_indices`) | F3, C7-PR1-1: K1 needs to know which shows the record's confidence covers |
| The recomputed confidence equals `AttemptRecord.confidence` on a fresh run | Equal, and a disagreement is counted like `findings_disagree`; on a rescored file, where `recorded_confidence` is None (the staging document does not carry it), **no disagreement is counted** | The C5-PR1-6 self-check, extended; C7-PR1-4 |
| A structured-route run | `confidence` None; `show_confidences` as stored (placeholder 1.0s); K1 drops them by route | F5, C7-PR1-3 |
| Per-attempt seconds | `seconds` on each attempt: attempt 1 from the run's start (`run_page` records it) to its staging, attempt `n` from staging `n-1` to staging `n`; on a rescored file, attempts 2 onward from the stored `staged_at` values and attempt 1 None | C7-PR1-6. Each span includes the previous attempt's validation, which is milliseconds |
| `--force-retries` on a scripted model-route page | attempts = cap, tiers initial, narrowed, larger_model, escalated, `policy.confidence_threshold == FORCED_THRESHOLD` in the record, every attempt scored | D3 |
| `--force-retries` on a scripted structured page | 1 attempt, passed | D3's limit: no confidence, nothing to force |
| `--escalation-model none` with `ESCALATION_MODEL_NAME` set in the environment | `policy.escalation_model is None` | C7-PR1-14: a run meant to be unescalated must be able to say so |
| `--escalation-model X` | `policy.escalation_model == "X"`, and attempt 3 is `larger_model_used` with model X on the page, splitter and status calls (the scripted client records `model` per call) | C6-D4; the flag must not drop the default's other fields (`build_policy`) |
| Neither flag | The policy equals `DEFAULT_POLICY` (no change to a default run) | C5-D5 |
| Tokens: scripted completions carrying `usage` on a two-attempt run | `tokens` per attempt, summing with `tokens_after_last_attempt` to the run total; a run whose completions carry no `usage` records None, not 0 | D6 |
| `--rescore` of a stored record without the new fields | Fills `confidence`, `show_confidences` and `judged_indices` from the staged documents and the fixture (no model call), leaves `tokens` and `recorded_confidence` absent | Lets `c6-confirm-*` be read without a rerun; the original file stays byte-identical (A2.1-PR1-13) |
| Validation recall's `stopped` column (D8, C5-F14) | An error on an attempt failed for low confidence with no finding is `silent` and `stopped`; on a passed attempt, `silent` and not `stopped` | D8 |

### 5. Reports and snapshots (`test_markdown_report.py`, `test_results_file.py`, extended)

| Case | Expected |
|---|---|
| A results file with the new fields | The report has "Confidence and correctness", "Threshold sweep" and "What each retry changed" sections, and the header says `forced retries` when the threshold is `FORCED_THRESHOLD` |
| `make eval-policy LABELS="a b"` | The three tables pooled over both files, with a line per label naming its `labels_sha`, and a refusal (exit 2) when the `labels_sha` values differ |
| The snapshot keeps `confidence`, `show_confidences` and `tokens` and still carries no page text, extraction or request secret | The existing scan test, extended |

### What is not covered, stated plainly

- **No test runs a model.** Whether confidence tracks correctness and whether a retry helps are the measurements; a test asserting them would
  be asserting a result.
- **The sample is small and clustered.** About eight model-route or image pages carry confidence, and one (Icehouse) holds most of the
  hosted model's errors. R1 is written for that, and the report prints every table per venue as well as pooled.

### Mutation checks (each must make a named test fail)

| ID | Mutation | Caught by |
|---|---|---|
| M1 | K1 counts `field_missing` as wrong | §1 first row |
| M2 | K1 keeps structured-route shows, or keeps shows outside `judged_indices` | §1 structured row; §1 excluded-show row |
| M3 | The sweep's mirror uses `<=` instead of `<` | §2 mirror row (confidence 0.8 at `t = 0.8`) |
| M4 | The sweep trusts the stored `low_confidence` reason | §2 third row |
| M5 | K3 includes `index` in an error's identity | §3 first row |
| M6 | K3 uses a set | §3 second row |
| M7 | `--escalation-model` builds a fresh `RetryPolicy` | §4 "neither flag" and escalation rows |

## Implementation steps

### Working protocol for [fill-in] steps

As in C5: the build writes everything around each gap, leaves the `TODO(Ari)` block with its key point, code and check, and the placeholder
raises `NotImplementedError("TODO(Ari)")`, so the K-rows above stay red. The build does not fill them (`AGENTS.md`, "[fill-in] tasks").
Steps 7 to 10 need the gaps filled, so the build stops after Step 6 and hands off; Ari fills the gaps, the cleanup pass follows his commit,
and then the measurement steps run.

### TODO(Ari) gaps

| Key point | File | What the lines decide |
|---|---|---|
| **C7-K1**: which shows confidence is judged on, and which of them are wrong | `saved_run_reports/policy_questions.py`, `confidence_rows(route, show_confidences, judged_indices, items)` | Only the shows the record's confidence covers (judged: not excluded, not status-merge placeholders, not the structured route), because that is what routes; among them, the kinds that make the row wrong as written (wrong acts, invented, a leak, a wrong field or image). The membership of `WRONG_KINDS` is written inside the gap (C7-PR1-2) |
| **C7-K2**: what a threshold would have done to attempt 1 | `policy_questions.py`, `would_fail(reasons, confidence, t)` and `sweep_cell` | A page-run "would" retry at `t` when it failed for any reason other than low confidence, or its confidence is under `t` (None never); it "should" when its attempt 1 fails the standard as `scoring.gate` judges it. The four cells are the confusion table R2 reads |
| **C7-K3**: what a retry changed | `policy_questions.py`, `transition` | An error is the same error in two attempts when its kind, date and field match, counted as a multiset; positions are not identity. Used both between attempts (the retry's effect) and between runs (the noise floor) |

Scaffolds, for the build to paste (each placeholder raises):

```python
# TODO(Ari) — Key point of interest: Q4 asks whether the confidence the pipeline ROUTES on tracks correctness, so the rows are the shows
#   that confidence covers: judged shows only (validation's exclusions and the status merge's placeholders never reach
#   `aggregate_confidence`), and no structured-route rows, whose 1.0 is a placeholder (C7-F3, C7-F5; c7-pipeline-eval.md, C7-K1,
#   C7-PR1-1). Among them a row is wrong when it should not be in the calendar as written; a missing field is tolerated (A2.1-D1).
# Code:
#   if policy.stored_route(route) not in ("model", "image"):
#       return []
#   WRONG_KINDS = {"acts_wrong", "fabricated", "leak", "field_wrong", "image_wrong"}
#   wrong = {i.index for i in items if i.kind in WRONG_KINDS and i.index is not None}
#   return [(show_confidences[i], i not in wrong) for i in judged_indices if show_confidences[i] is not None]
# Check: test_policy_questions.py::test_confidence_rows_* — counting field_missing as wrong (C7-M1), keeping structured or excluded rows (C7-M2).
raise NotImplementedError("TODO(Ari)")
```

```python
# TODO(Ari) — Key point of interest: the sweep asks what ANOTHER threshold would have done, so the stored low_confidence reason is
#   dropped and recomputed at t, exactly as policy.combine would (A3-K4; C7-K2). "Should retry" is the A2.1-D1 standard on attempt 1, as
#   the scorer's own gate judges it, so the standard is never re-coded here.
# Code (would_fail):
#   other = [r for r in reasons if r != "low_confidence"]
#   return bool(other) or (confidence is not None and confidence < t)
# Code (sweep_cell):
#   would = would_fail(reasons, confidence, t)
#   should = not scoring.gate({0: [first_attempt_score]}).passed
#   return {(True, True): "caught", (True, False): "false_alarm", (False, True): "missed", (False, False): "quiet"}[(would, should)]
# Check: test_policy_questions.py::test_sweep_* and test_sweep_mirror_agrees_with_combine — `<=` (C7-M3), trusting the stored reason (C7-M4).
raise NotImplementedError("TODO(Ari)")
```

```python
# TODO(Ari) — Key point of interest: the same error in two attempts is the same kind on the same date and field, counted as a multiset;
#   the index is a position in that attempt's list and shifts when a show is added or dropped (C7-K3). The same comparison between two
#   runs' first attempts describes how much a resample moves (a hosted retry is also a resample: seed is not honoured). Every kind but
#   field_missing counts, so a retry that makes a field wrong shows as one that hurt.
# Code:
#   before = Counter((i.kind, i.date, i.field) for i in first if i.kind != "field_missing")
#   after = Counter((i.kind, i.date, i.field) for i in second if i.kind != "field_missing")
#   return Transition(fixed=sum((before - after).values()), introduced=sum((after - before).values()), kept=sum((before & after).values()))
# Check: test_policy_questions.py::test_transition_* — the index in the key (C7-M5), a set instead of a Counter (C7-M6).
raise NotImplementedError("TODO(Ari)")
```

### Step 1 — tests first [written]

Every test in the Test approach, watched failing for the stated reason (the K rows on `NotImplementedError`, the rest on a missing name or
field).

### Step 2 — per-attempt confidence and tokens in the harness [written]

- `validation_recall.py`: `recompute_validation(document, *, page_html, fetched_on) -> ValidationResult` (the body `recompute_findings` already
  has); `recompute_findings` returns its findings. The kept shows' minimum is `result.confidence`.
- `run_one_page.py`: `AttemptResult` gains `confidence: float | None`, `show_confidences: list[float | None]` (as the model gave them, by raw
  index), `judged_indices: list[int]` (every raw index minus `result.excluded` and `notes["added_indices"]`), `recorded_confidence` (from
  `AttemptRecord`; None when not recorded), `seconds: float | None` and `tokens: dict[str, int] | None`, all defaulted so older files load.
  `run_page` records its start and sets a fresh `run_eval.RunCounters` in its context var around `run_venue`; `InMemoryStager.stage` snapshots
  the counters and the clock (D6, C7-PR1-6). `PageRun` gains `tokens_after_last_attempt`.
- `run_labeled_pages._rescore_run` fills `confidence`, `show_confidences`, `judged_indices` and the `staged_at`-based seconds from each staged
  document when they are missing (the fixture is already read there).
- `aggregate_scores`: `_validation` gains `stopped` (D8) and `confidence_disagree`, counted only where `recorded_confidence` is not None
  (C7-PR1-4).

### Step 3 — the two flags [written]

`run_labeled_pages`: `--force-retries` and `--escalation-model NAME` (`none` means no escalation model, whatever the environment sets: C7-PR1-14); `build_policy(threshold, max_attempts, *, force=False,
escalation_model=None)` keeps `dataclasses.replace(DEFAULT_POLICY, ...)`. `--force-retries` with `--threshold` is refused (two answers to one
question). `FORCED_THRESHOLD = 1.01` lives beside `build_policy` with a comment saying why it is above 1 (the schema's `le=1`). Makefile
`eval-graph` gains `FORCE_RETRIES=1` and `ESCALATION_MODEL=<id>|none`, and `make help`'s usage line lists them. An escalation model must be one the
configured endpoint serves (`policy.RetryPolicy.escalation_model`'s comment); a wrong id fails on attempt 3 with the provider's error, which the
attempt records.

### Step 4 — the analysis module [fill-in, C7-K1 to C7-K3]

`saved_run_reports/policy_questions.py` (pure; reads run records only; must not import `labeled_page_runs`, which the existing layering test
enforces):

- `confidence_rows` (K1), `buckets(rows_by_venue, min_size=10)`, `excluded_confidences`, `r1_verdict`.
- `would_fail` and `sweep_cell` (K2), `sweep(records, thresholds=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0))`, gated and informational kept
  apart.
- `transition` (K3), `retry_effect(records)` per tier transition with fixed, introduced, seconds and tokens; `noise_band(records)` per page
  (the standard deviation of attempt-1 error counts across runs); `r3_verdict` and `r4_verdict` applying the per-page rule ("The readings").

Module docstring in the house style: what it is, how to read it, which reading (R1 to R4) each table feeds.

### Step 5 — the report and the pooled command [written]

`markdown_report.py` gains the three sections for one file. `run_labeled_pages --policy-report LABEL... [--out FILE]` pools several labels
(refusing mismatched `labels_sha`); `make eval-policy LABELS="…" [OUT=…]`. `results_file.slim` keeps the new numeric fields.

### Step 6 — documents for the instrument [written]

`docs/dev/evaluating-model-performance.md`: step 6 ("Retry loop") becomes "Forced retries" (`FORCE_RETRIES=1`, with and without
`ESCALATION_MODEL`), a new step "Policy questions" (`make eval-policy`), and the reading table gains the three sections. `model_eval/README.md`
and `apps/api/AGENTS.md` name `policy_questions.py`. `docs/dev/conventions.md` gains the `C7` row. **The build stops here and hands off the
three gaps** (with `uv run pytest agent_worker/tests/model_eval/test_policy_questions.py` as the command).

### Step 7 — the default runs [written; local, after the gaps are filled]

On the shipped configuration (`docs/dev/environments.md`'s values as a one-command override, the key from `apps/api/.env`), pipeline defaults:

```
make eval-graph LABEL=c7-defaults SET=all RUNS=5 ESCALATION_MODEL=none
make eval-graph LABEL=c7-defaults-icehouse SET=held_out ONLY=icehouse RUNS=5 ESCALATION_MODEL=none
make eval-policy LABELS="c7-defaults c7-defaults-icehouse" OUT=c7-defaults-policy.md
```

Check each report header shows `escalation_model: None` and the expected `labels_sha` (C7-PR1-14). Cross-check, no model: `--rescore
c6-confirm-gated` and `--rescore c6-confirm-heldout`, then `eval-policy` over the rescored labels; the tables should tell the same story as F1
to F4 (K1 counts Icehouse's 98 wrong kept shows; the 14 dropped ones appear in the excluded-confidences line). Then the secondary table (D9):
rescore the older hosted labels it names and run `eval-policy` over them as their own group. Commit the two snapshots.

**No edit to `labels.py` from Step 7 to Step 9** (C7-PR1-9): `labels_sha` hashes the whole file, and `eval-policy` refuses to pool labels whose
shas differ. If a label must change, stop, change it, rescore every C7 label, and say so in the log.

### Step 8 — the forced runs [written; local]

```
make eval-graph LABEL=c7-forced SET=all RUNS=5 FORCE_RETRIES=1 ESCALATION_MODEL=none
make eval-graph LABEL=c7-forced-icehouse SET=held_out ONLY=icehouse RUNS=5 FORCE_RETRIES=1 ESCALATION_MODEL=none
make eval-graph LABEL=c7-forced-escalated SET=all RUNS=5 FORCE_RETRIES=1 ESCALATION_MODEL=google/gemma-4-31B-it
make eval-graph LABEL=c7-forced-escalated-icehouse SET=held_out ONLY=icehouse RUNS=5 FORCE_RETRIES=1 ESCALATION_MODEL=google/gemma-4-31B-it
make eval-policy LABELS="c7-forced c7-forced-icehouse" OUT=c7-forced-policy.md
make eval-policy LABELS="c7-forced-escalated c7-forced-escalated-icehouse" OUT=c7-forced-escalated-policy.md
make eval-policy LABELS="c7-forced c7-forced-icehouse c7-forced-escalated c7-forced-escalated-icehouse" OUT=c7-forced-all-policy.md
```

The last command reads both groups together, which is what prints R3's escalated-against-unescalated line (added in the build, Implementation log
Round 1, Departure 7).

Check the headers: `forced retries`, and `escalation_model` None in the first two and the 31B in the last two.

Structured pages pass on attempt 1 in these runs (D3) and cost only their one attempt. Read the dashboard spend before and after (D4).
Commit the snapshots.

### Step 9 — the readings and Ari's decision [written; a gate inside the build]

Apply R1 to R4 to the tables and write, in the Implementation log: the tables, each reading's outcome, the recommendation for each default
(threshold, cap, escalation model), and the deviations from a rule if any. **Ari decides the defaults.** The build stops here until he answers;
his answer goes in the log with the date.

### Step 10 — apply and record [written]

- **If a number changes:** `policy.py` (`RetryPolicy`'s defaults, with a why-comment citing the C7 reading), a test first in `test_policy.py`
  pinning the new default, and `make check`. An adopted escalation model is a per-environment value: `ESCALATION_MODEL_NAME` in
  `docs/dev/environments.md` (the doc test reads it) and in each environment's Railway variables at C8, not a code default (`config.py` keeps it
  optional, A3-D5).
- **If confirmed:** the comments that say "A8 checks whether the number is right" (`policy.py`) say what C7 found instead.
- Either way: `arch-initial.md` §7 "Validation and retry" gets a dated note with the numbers; `alpha-deployment-plan.md` C7 checkboxes and a
  status line; `alpha-build-plan.md` A8's pointer; the C5 hand-offs (C5-F4, C5-F6, C5-F14) marked with where they went (D8).

## Critical files

| File | Change |
|---|---|
| `apps/api/agent_worker/model_eval/saved_run_reports/policy_questions.py` | New: K1 to K3 and the tables |
| `apps/api/agent_worker/model_eval/labeled_page_runs/run_one_page.py` | `AttemptResult` fields; token counters around `run_venue`; stager snapshots |
| `apps/api/agent_worker/model_eval/labeled_page_runs/run_labeled_pages.py` | `--force-retries`, `--escalation-model`, `--policy-report`; `build_policy`; rescore fills confidence |
| `apps/api/agent_worker/model_eval/validation_recall.py` | `recompute_validation` |
| `apps/api/agent_worker/model_eval/saved_run_reports/{aggregate_scores,markdown_report,results_file}.py` | `stopped`, `confidence_disagree`; the report sections; the snapshot fields |
| `apps/api/agent_worker/model_eval/run_eval.py` | None expected: `RunCounters` and the hook are reused as they are (if the build needs to export a name, it is a one-line change) |
| `apps/api/agent_worker/tests/model_eval/test_policy_questions.py` | New |
| `apps/api/agent_worker/tests/model_eval/test_run_one_page.py`, `test_run_labeled_pages.py`, `test_markdown_report.py`, `test_results_file.py` | Extended |
| `Makefile` | `eval-graph` flags, `eval-policy` |
| `apps/api/agent_worker/policy.py` | Only at Step 10, only if a default changes (comments either way) |
| `docs/dev/evaluating-model-performance.md`, `apps/api/agent_worker/model_eval/README.md`, `apps/api/AGENTS.md`, `docs/dev/conventions.md` | Step 6 |
| `docs/arch/arch-initial.md` §7, `docs/dev/alpha-deployment-plan.md` C7, `docs/dev/alpha-build-plan.md` A8, `docs/dev/environments.md` (if adopted) | Step 10 |

The pipeline itself (`validation.py`, `graph.py`, `nodes.py`, `extraction.py`) does not change. No `schemas.py` change, so no `make types`.

## Verification

1. After Step 6, `make check` fails **only** on the named K tests (each on `NotImplementedError("TODO(Ari)")`), and everything else in it
   passes; the build lists those tests (C7-PR1-13). After the gaps are filled, `make check` is green.
2. `make designation-check BASE=<the merge-base with main>`: no bare `K1`, `R2` or `F4` in code, tests or other documents.
3. The mutation checks M1 to M7, applied by hand once and reverted, each fail their named test.
4. **Local:** the C6 cross-check (Step 7) reproduces F1 to F4 from the rescored files.
5. **Local:** the snapshots of Steps 7 and 8 contain no page text and no API key (the snapshot scan test, and a `grep` for the key's first
   characters over `docs/dev/eval-baselines/`).
6. **Local:** a forced run's report header says `forced retries` and its tier table shows `larger_model_used` on attempt 3 only in the
   escalated labels.

## Unverified

- **That the 31B id is still served on DeepInfra** (D2): checked by Ari before Step 8.
- **Run times.** Estimated from C6: a default `SET=all RUNS=5` about 25 to 35 minutes, Icehouse alone about 10; a forced run roughly triples
  the model-route pages' time (Icehouse at about 116 s an attempt is the long pole), and the escalated tier adds the 31B's slower third attempt.
  Recorded as measured.
- **That the completion hook sees the graph's calls.** `run_eval.register_hooks(instructor_client)` runs at import on the pipeline's client, and
  nodes run in threads that copy the context (`trace.audited`); the build's scripted test (§4, tokens row) confirms both before any run relies
  on them.
- **That DeepInfra's `usage` covers the splitter and status calls.** C6 Round 8 recorded tokens from `run_eval`, which makes the same calls; the
  graph harness has not.

## Not doing in C7

- **New validation checks** (C5-F4, C5-F6) and promoting `ACT_NOT_IN_TITLE` (D8; C6 Round 8).
- **Escalating only the failing call** (D7).
- **A confidence field on the act splitter** or the review flag for uncertain splits: deferred in `arch-initial.md` §11. C7's Q4 answer is
  evidence for or against it, recorded in the log.
- **New labels or captures.** If R1 reads "not enough evidence", the log says so and asks Ari whether to label more model-route pages (C5-D4
  left the sizing to C7); C7's done-when is still met, because "not enough evidence, so confidence is not used to route" is an answer with data.
- **Production monitoring of retry rate and confidence** (`arch-initial.md` §11, run-health monitoring).

## Plan review

### Round 1 — Claude Sonnet 5.5, November 6, 2026

**Scope:** the plan body as it stands in the untracked file `docs/dev/implementations/c7-pipeline-eval.md`, a plan review only (no code exists). Checked against the deployment plan's C7 section and Dep-D5, Dep-D13 and Dep-D15, and the docs and code the plan cites.

**What was checked and how:** I read `AGENTS.md`, `apps/api/AGENTS.md` (via the repo instructions), the C7 section of `alpha-deployment-plan.md`, C5-D4 and C5-F14, C6-D8, the A3 decision rows, `arch-initial.md` §11, and the code the steps touch: `policy.py` (all of it), `validation.aggregate_confidence`, `extraction._shows_from_listings` and the status-merge note `added_indices`, `staging.document_for`, `scoring.py` (`ErrorItem`, `score_page`, `_dropped_index`, `gate`, `LEAKS_PER_PAGE`), `validation_recall.py`, `saved_run_reports/aggregate_scores.py`, `labeled_page_runs/run_one_page.py` and `run_labeled_pages.py` (`build_policy`, `rescore`, `_rescore_run`, `run_pages`, `parse_args`), `run_eval.RunCounters` and its hook, `run_eval.labels_sha`, `labels.py` (the `held_out` flags), the `eval-graph` Makefile target, and `test_layering.py`. I re-derived F1 to F4 from the gitignored results files with a throwaway script in the session scratchpad (no model called, no hosted service touched, no worktree needed). **F1, F2, F3 CONFIRMED** exactly as stated (0 retries in 45 page-runs; every model-route confidence is 0.5, 0.8, 0.9 or 1.0; the only values under 0.9 are the three no-acts 7th St Entry shows in three of five runs). **F4 CONFIRMED with one correction:** Icehouse has 255 show-instances, all 1.0, and 98 returned-with-acts shows carry an error, but a further 14 are dropped shows (`acts: []`) that the scorer reports as `missed` with that show's index, so K1 would count 112 wrong (finding 12). The plan's test tables were also checked by hand: the §2 sweep cells at t = 0.95 and 0.8, the §3 transition and noise-floor examples, and the §1 first row all come out as the plan states, given the scaffolds. The gaps (K1 to K3) are at the right places in kind; finding 2 asks that K1's membership list itself sit inside the gap. I did not run `make check` (no code to check).

**Counts:** 1 blocker, 10 should-fix, 3 nit. **Verdict: proceed after fixes.** The design is sound and its facts hold. The blocker is that K1 as scaffolded would build the confidence-against-correctness table out of the wrong population of shows, which on the real data puts the lowest-confidence bucket entirely of correct-by-exclusion shows and inverts the very signal Q4 asks about. The should-fix rows are mostly places where a pre-registered reading or a test is not yet operational (R1, R3, `would_fail`, per-attempt seconds), two decisions that are Ari's to look at again (rows 7 and 8), and one ordering trap that would make the pooled report refuse its own files (row 9).

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | blocker | **K1's rows are every raw show's confidence, but the confidence the pipeline routes on covers only a subset, and the subset is exactly where the low values are.** `show_confidences` is "one per raw show, by index" and `confidence_rows` keeps every non-None one. But `aggregate_confidence` takes the minimum over the kept shows only, excluding the status merge's added shows (placeholder 1.0, `notes["added_indices"]`) and, upstream, the no-acts shows validation excludes. The plan's own F3 says the low values sit on those excluded shows. A no-acts show that no label expects is not in `items` at all, so K1 calls it "correct". | CONFIRMED: `graph-c6-confirm-gated`, 7th St Entry, per-show `(confidence, wrong, has_acts)` per run: `(0.5, False, False)` x3 in runs 0 and 1, `(0.8, False, False)` x3 in run 3, all other kept shows 0.9 or 1.0 and none wrong. `validation.py:536-549` and `extraction.py:336-338` (`added_indices`). | The lowest-confidence bucket (R1's numerator) is made entirely of shows the pipeline discards, scored as correct. R1 would read "inverted" or "flat" for a reason that has nothing to do with the model's calibration, and status-merge placeholders (1.0) would dilute the top bucket. Q4 is answered wrongly, silently. | **Fixed.** K1's population is now the judged shows only, the ones `aggregate_confidence` covers: the harness records `judged_indices` (raw indices minus `excluded` and `added_indices`), and `confidence_rows(route, show_confidences, judged_indices, items)` keeps only those. The excluded shows' confidences get their own report line, never R1's buckets. New §1 rows: the real 7th St Entry shape (an excluded, unlabeled 0.5 show gives no row) and a status-merge placeholder; M2 extended; K1 scaffold rewritten. |
| 2 | should-fix | **"Wrong" and "gate error" are three different sets across K1, K2 and K3, the constants are undefined, and K1 contradicts the standard on leaks.** K1: `WRONG_KINDS` = missed-with-index, acts_wrong, fabricated, leak, field_wrong, image_wrong (test table, §1 row 2, cites "wrong never"). K2's `gate_errors` and K3's `GATE_KINDS` are missed, acts_wrong, fabricated only (the same three as `aggregate_scores._errors_of`). But A2.1-D1 tolerates up to one leak per page (`scoring.LEAKS_PER_PAGE = 1`, `gate`), so a leak is not "wrong never"; and `gate` fails any wrong field, so K3 would not see a retry that introduced a wrong price or time. The scaffolds use `WRONG_KINDS` and `GATE_KINDS` without defining them, and the membership of `WRONG_KINDS` is the actual decision K1 is meant to carry, yet it sits outside the gap. | CONFIRMED by reading: plan §1 table row 2, K1/K2/K3 scaffolds; `scoring.py:38` and `scoring.py:418-460` (`gate`); `aggregate_scores.py:67-69`. | R1 counts a tolerated leak as an error; R3 cannot see the field errors the validator's own checks target (`free_with_price`); R2's "page-runs with errors" and R3's "errors" are different populations; the build has to invent the two constants. | **Fixed.** "The readings" opens with three named definitions used everywhere: a wrong show (K1: wrong acts, invented, leak, wrong field or image on a judged show; a leak counts as wrong *for this question*, and the text says why the gate tolerates one), a should-retry page-run (K2: attempt 1 fails `scoring.gate` itself, so leaks over one and wrong fields count and the standard is not re-coded), and an error count (K3: every kind but `field_missing`). `WRONG_KINDS` is now inside K1's scaffold; `GATE_KINDS` is gone; new §2 row (gate-based should) and §3 row (an introduced wrong field counts). |
| 3 | should-fix | **`confidence_rows` has no route input, so the structured-route test row and mutation M2 cannot work as written.** The K1 code is `confidence_rows(show_confidences, items)` and drops only `None`. The test row ("an attempt on the structured route, and one stored as `jsonld`: no rows", source `policy.stored_route`) and M2 ("K1 keeps structured-route shows") assume the function sees the route. If the harness writes `None` for every structured show (§4 row 3), K1 has nothing to do with the route and M2 cannot fail any test of K1; if K1 is to drop them, its signature needs the route. `--rescore` has the same gap: its row fills `show_confidences` from the staged document, whose structured shows carry the placeholder 1.0 unless the rescore nulls them. | CONFIRMED by reading: plan §1 table rows 3, M2, §4 row 8; `extraction.py:378-395` (`confidence=1.0` on the structured route); `run_labeled_pages._rescore_run` (reads `document["raw_extraction"]` only). | Either M2 passes silently on a wrong K1, or a rescored c6 file feeds placeholder 1.0s into the buckets (the Step 7 cross-check would then not reproduce F2 to F4). | **Fixed.** `confidence_rows` takes the route and drops anything not `model` or `image` via `policy.stored_route`; the harness and the rescore store confidences as the model gave them (placeholder 1.0s included), so K1 alone decides, and M2 can fail. |
| 4 | should-fix | **`recorded_confidence` defaults to None, so a rescored file reports a confidence disagreement on every model-route attempt.** Step 2 adds `recorded_confidence` "defaulted so older files load" and `aggregate_scores._validation` gains `confidence_disagree`. `AttemptRecord.confidence` is not in the staging document, so `--rescore` cannot fill it, and the recomputed confidence (0.9, say) will not equal the default None. Compare the existing `errors != recorded_errors` self-check, which works only because those files carry both. | CONFIRMED by reading: `staging.document_for` (no confidence field), plan Step 2, §4 row 2; `aggregate_scores.py:_validation`. | The Step 7 cross-check over the rescored c6 files shows `confidence_disagree` equal to the number of model-route attempts, which reads as a drift in `validate_node` that is not there. | **Fixed.** `recorded_confidence` None means not recorded; `confidence_disagree` counts only attempts where it is present (Step 2), and a §4 row asserts no disagreement on a rescored file. |
| 5 | should-fix | **The mirror test names `would_fail(...)`, which is in no step and is not in K2's scaffold.** §2's mirror row compares `would_fail(...)` with `policy.combine(...)` over `ValidationResult`s; Step 4 lists `sweep_cell` only, and K2's scaffold inlines the rule on `(reasons, confidence, gate_errors)`. The two have different inputs (a `ValidationResult` against a stored reasons list). The mirror is the test that catches M3, so whether it lives inside the gap (and `sweep_cell` calls it) or beside it decides what Ari writes. | CONFIRMED by reading: plan §2 row 4, Step 4, K2 scaffold. | The build invents the function's signature, and the test that pins the one-line mirror either does not compile or tests a function Ari never touched. | **Fixed.** `would_fail(reasons, confidence, t)` is a named function inside K2, `sweep_cell` calls it, Step 4 lists both, and the mirror test feeds it the reasons `combine` gives at threshold 0. |
| 6 | should-fix | **"Seconds per attempt" is promised in the retry tables and has no source.** §3's last row and Step 4's `retry_effect` give each transition "fixed, introduced, seconds and tokens", and D6 says C5 recorded seconds only per run. Step 2's `AttemptResult` additions are `confidence`, `show_confidences`, `recorded_confidence` and `tokens`; none is seconds. The staged document does carry `staged_at`, so attempt N's duration is the difference of two stagings, but the first attempt needs the run's start, which is not on the record. | CONFIRMED by reading: plan §3, Step 2, D6; `staging.document_for` (`staged_at`); `PageRun.seconds` is whole-run only. | "Only costs tokens" (Q3) is half-answered: R3's fallback is "report its seconds and tokens per attempt", and the seconds column is empty or invented at build time. | **Fixed.** `AttemptResult.seconds`: attempt 1 from `run_page`'s recorded start to its staging, later attempts between stagings (the stager snapshots the clock); a rescore derives attempts 2 onward from `staged_at` and leaves attempt 1 None. §4 row added; the small validation overlap is stated. |
| 7 | should-fix | **R1 will almost certainly read "not enough evidence" on the data that exists, and the plan does not say so up front or decide what that triggers.** R1 needs 20 wrong show-instances from outside the largest venue. Outside Icehouse the saved hosted runs hold 2 (Turf Club, one run). Icehouse itself is one bucket (all 255 at 1.0), so "lowest bucket at least twice the highest" is undefined there. R1 also has no minimum size for a bucket: the 0.5 and 0.8 buckets hold 3 shows each. C5-D4 left sizing "to C7's plan", and the plan answers it only with "ask Ari afterwards". The 20 is not justified either. **Ari's call, flag at approval:** accept the predictable "not enough evidence, so confidence is not used to route" (and say so now), or widen the sample before the readings are fixed, for example by also reading the earlier hosted extraction-level runs (`c6-hosted-first`, `c6-prompt-v2` and `v3`, under older prompts, with more errors on non-Icehouse venues) as a labelled secondary table. | CONFIRMED: counts above from `graph-c6-confirm-gated` and `graph-c6-confirm-heldout`; C5-D4 text; plan R1, "Not doing in C7" bullet 4. | A pre-registered reading whose outcome is known from the first rescore is not a test; the log then reads as hedged, and the single bucket and tiny buckets can make "yes" or "no" appear from three shows. | **Fixed, and put to Ari as D9.** The plan now says up front that R1 will very likely read "not enough evidence" and recommends accepting that (F5 gives the structural reason), with a free secondary table from older hosted graph runs, read by the same rule and never pooled. R1 gains a minimum bucket size of 10 and says that 20 and 10 are judgement, not statistics. Alternative for Ari: label more model-route pages before Step 7. |
| 8 | should-fix | **D1 spends the last held-out page (Dakota) and re-scores Ginkgo and Hook & Ladder, for no information.** The plan itself says Dakota is structured-route, confidence None, check errors it does not raise: it "cannot inform the threshold or Q4 at all". All three structured held-out pages pass on attempt 1 in every forced run (D3), so they add cost and nothing else. The only held-out page that can inform C7 is Icehouse, already burned. `run_labeled_pages` has `--only`, so `make eval-graph ... SET=held_out ONLY=icehouse` runs it alone. The default-policy held-out evidence is already in `c6-confirm-heldout`, which Step 7's rescore reads for free. **Ari's decision (D1 is marked `[Ari]`):** use `ONLY=icehouse` for the three held-out runs and leave Dakota unscored by C7, which also removes the `labels.py` note (finding 9). | CONFIRMED by reading: plan D1, D3 ("structured pages pass on attempt 1"), `parse_args` (`--only`), `select_fixtures`; `graph-c6-confirm-heldout` page list (Dakota, Ginkgo, Hook & Ladder structured, Icehouse model); C6-D8 (iii). | One of the project's few remaining honest-test pages is consumed so that three structured pages can pass three times, and a later "held out" claim has to carry an exception. | **Fixed (D1's recommendation changed; still Ari's).** The held-out runs are `SET=held_out ONLY=icehouse`; Dakota, Ginkgo and Hook & Ladder are not run, since their default behaviour is already in `c6-confirm-heldout`, which Step 7 rescores. Dakota stays held out and the `labels.py` note is dropped. Departure 3 and the run-time estimate are updated. |
| 9 | should-fix | **The planned `labels.py` Dakota note changes `labels_sha`, and `make eval-policy` refuses to pool files with different shas.** D1 says to record in `labels.py` that C7 scored Dakota. `labels_sha` is the sha-256 of the whole file, and Step 5 makes `eval-policy` exit 2 on differing `labels_sha`. If the note is added between Step 7 and Step 8, `c7-defaults` and `c7-forced` no longer share a sha, and a pooled re-run of any pair straddling the edit is refused. The plan puts the edit nowhere in the steps. | CONFIRMED: `run_eval.labels_sha` (`labels.py` read as bytes), `results_file.labels_sha`, plan D1, Step 5, the `make eval-policy` row of §5. The same trap already bit C6.1 (`notes.md`, "labels_sha changes"). | The report meant to answer Q1 to Q3 refuses its own inputs, or the note lands mid-measurement and the runs are not comparable. | **Fixed.** The Dakota note is gone (row 8), and Step 7 adds a rule: no `labels.py` edit from Step 7 to Step 9; if one is unavoidable, rescore every C7 label after it and say so. |
| 10 | should-fix | **R3's "beyond the noise floor" is not an operational test, and Icehouse can carry R3 alone.** The noise floor is the mean of `fixed + introduced` between pairs of attempt-1s (§3: "(0 + 1 + 1) / 3"), while "tier 2 helps" is "errors fixed minus introduced positive". A net change is compared with a churn count: for unordered pairs of runs the expected net is zero by symmetry, so the floor the retry should be measured against is the spread of the net, not the mean of the churn. The plan also says nothing about the unit (per page, per page-run, pooled), nor does it do for R3 what R1 does for the largest venue: Icehouse alone is about 98 to 112 errors a run, every other page about 0 to 2, so a pooled R3 is a statement about one page. | CONFIRMED by reading: plan R3, §3 noise-floor row; error counts from `graph-c6-confirm-heldout` and `-gated` as above. | R3 can say "helps" or "does not help" depending on which statistic the build picks after seeing the numbers, which is what D5 exists to prevent. | **Fixed.** R3 is per page: attempt `k` helps on a page when its mean error count is lower than attempt 1's by more than the page's noise band (the population standard deviation of attempt-1 errors across runs), and hurts in the mirror case. A tier helps only if it helps on at least two pages and hurts on none, so Icehouse cannot carry it. K3's fixed and introduced counts are kept as the description, not the test. R4 uses the same rule. Worked §3 rows added. |
| 11 | should-fix | **R3 and R4 will be negative by construction for the dominant error kind, and the plan should say what that does and does not show.** The plan notes the facts (Context: the splitter gets no hint until the last attempt; checks that target it fire almost never) but R3 still reads "Otherwise 'only costs'". On the shipped route, attempt 2 sends the splitter a byte-identical request (empty splitter hint, `policy.retry_hint`), so a change in act errors at tier 2 can only be a resample, and the one page hint it receives is a generic sentence. A negative R3 therefore says "a generic low-confidence sentence plus a resample does not recover errors", not "the escalating retry does not recover failures", and the production path that actually retries (a check error with its finding messages as the hint) is untested because F1 says it never fires. Q3's done-when wording ("does the escalating-prompt retry actually recover failures") needs this scoping, and R2 inherits it (R2 says no threshold helps if R3 says retries do not). | CONFIRMED by reading: `policy.retry_hint` and `plan_for_attempt` (lines 238-258, 286-310); `policy._REASON_ADVICE`; plan Context, D3 "Limits", R2, R3. | The log would record "retry only costs tokens" as a finding about the retry loop and Ari would carry it into the review-flag decision (D8) on that basis. | **Fixed.** A new Context bullet scopes what C7 can test of Q3: on the shipped route a forced tier 2 sends the splitter a byte-identical request, and the specific-hint path never fires, so a negative result means the generic hint plus a resample (and the final sentence plus a larger model at tier 3) do not recover errors, not that the escalating retry cannot. R2 and R3 carry that wording into the log. |
| 12 | nit | **F4's "98 carry an error" is the with-acts count; K1 will count 112.** The other 14 Icehouse show-instances are dropped (`acts: []`) shows the scorer reports as `missed` with their index, which K1 treats as wrong. The Step 7 cross-check "should tell the same story as F1 to F4" will not match F4's 98 unless the table says which population it counts. | CONFIRMED: `graph-c6-confirm-heldout`, Icehouse runs 0 to 4, wrong with acts 20, 18, 19, 21, 20 (= 98) plus dropped-and-missed 3, 3, 3, 2, 3 (= 14). | The cross-check fails on a number that is right under a different definition. | **Fixed.** F4 now names both populations: 98 wrong kept shows (K1's) and 14 dropped shows reported as `missed`, which K1 leaves out. Step 7's cross-check says which one to expect. |
| 13 | nit | **Verification 1 says `make check` is green with the K-rows red.** Pytest is part of `make check` and a red test fails it. | CONFIRMED by reading: Verification 1; `AGENTS.md` ("push the scaffold with its tests red"). | The build reports a contradiction it cannot satisfy; say instead that the only failures are the named K tests. | **Fixed.** Verification 1: after Step 6, `make check` fails only on the named K tests, which the build lists; green after the gaps are filled. |
| 14 | nit | **`--escalation-model` cannot turn off an escalation model that `.env` sets.** `build_policy(..., escalation_model=None)` means "no flag", and `DEFAULT_POLICY` reads `ESCALATION_MODEL_NAME` from settings. If it is set on the laptop, the plain `c7-forced` label silently runs a larger model on attempt 3 and R3's with-and-without comparison collapses. | CONFIRMED by reading: `policy.py` (`DEFAULT_POLICY = RetryPolicy(escalation_model=settings.escalation_model_name)`), plan Step 3, Step 8. | Easy to avoid: Step 7 and Step 8 should say to check the results header's `policy.escalation_model` is null for `c7-defaults` and `c7-forced`. | **Fixed.** `--escalation-model none` (Makefile `ESCALATION_MODEL=none`) forces no escalation model whatever the environment sets (§4 row added); every unescalated run in Steps 7 and 8 passes it, and both steps say to check `escalation_model` in the report header. |

Rejected: none. Two rows carry a decision that is Ari's: row 7 (D9, Q4's sample) and row 8 (D1, which pages). The resolutions change the readings (R1, R3) and K1's population substantially, so a second review round may be worth it; that is Ari's call (not run).

## Implementation log

### Round 1 — Claude Opus 5.5, November 6, 2026 (Steps 1 to 6; the build stops for the gaps)

**Scope.** Diff base `8c90a38` (the `main` merge of PR 94); nothing committed, so the scope is the working tree on branch
`c7-pipeline-eval` (`git diff 8c90a38` plus the untracked files below). Files touched:

- New: `apps/api/agent_worker/model_eval/saved_run_reports/policy_questions.py`, `apps/api/agent_worker/tests/model_eval/test_policy_questions.py`.
- Harness: `model_eval/validation_recall.py` (`recompute_validation`), `labeled_page_runs/run_one_page.py` (the C7 attempt fields, the stager's
  clock and token marks, the hook registration), `labeled_page_runs/run_labeled_pages.py` (`build_policy`, `--force-retries`,
  `--escalation-model`, `--policy-report`, the rescore fill), `saved_run_reports/aggregate_scores.py` (`stopped`, `confidence_disagree`),
  `saved_run_reports/markdown_report.py` (the forced header, the three sections, `policy_report`).
- Tests extended: `test_run_one_page.py`, `test_run_labeled_pages.py`, `test_aggregate_scores.py`, `test_markdown_report.py`, `test_results_file.py`.
- `Makefile` (`FORCE_RETRIES`, `ESCALATION_MODEL`, `eval-policy`); docs: `docs/dev/evaluating-model-performance.md`, `docs/dev/conventions.md`
  (the `C7` scope row, and `Q`/`R` forms), `apps/api/agent_worker/model_eval/README.md`, `apps/api/AGENTS.md`.
- Not touched: the pipeline (`validation.py`, `policy.py`, `graph.py`, `nodes.py`, `extraction.py`), `schemas.py`, `labels.py`, `run_eval.py`.

**Departures from the plan, each with its reason.**

1. **The token hooks were not on the pipeline's client.** The plan (D6, and "Unverified") assumed `run_eval.register_hooks` already covered the
   graph's calls. It does not: `run_eval` builds its own client with `llm.build_clients` and registers on that, while the nodes call
   `nodes.instructor_client` (another `build_clients` result). `run_page` now attaches the hooks to `nodes.instructor_client`, once per client
   (`run_one_page._count_calls_on`; a client without `on`, like the plain scripted one, is left alone). `run_eval.py` is unchanged. The token
   test uses a scripted client that takes hooks the way instructor's does, so the registration path itself is tested.
2. **`FORCED_THRESHOLD` lives in `saved_run_reports/policy_questions.py`**, not beside `build_policy`: the report reads it to say "forced
   retries", and `saved_run_reports/` may not import `labeled_page_runs/` (`test_layering.py`). `run_labeled_pages` imports it from there.
3. **`AttemptResult.excluded_indices` added** beside `judged_indices`. The excluded-confidences line (§1) must tell validation's exclusions
   apart from the status merge's placeholders, and `judged_indices` alone cannot.
4. **C7-Q4's rows and the sweep read attempt 1 only.** The plan did not say which attempts. Attempt 1 is what production sends first, with
   the shipped model and no hint; a forced run's later attempts carry a hint and, at tier 3, perhaps another model, so pooling them would
   answer a different question.
5. **The rescore recomputes the confidence fields every time** (the plan said "when they are missing"): they are a pure function of the staged
   document, like the scores, so a rescore cannot disagree with a fresh run. Seconds are filled only when missing, so a fresh file keeps its
   attempt-1 seconds.
6. **The report shows the three policy sections only for a file that carries the C7 fields** (`policy_questions.confidence_recorded`); an
   older file gets one line saying to rescore it. This is the plan's "not recorded" row, applied to all three sections, and it keeps the
   existing report tests off the open gaps (a retried page in an old file would otherwise call C7-K3).
7. **The retry section groups records by escalation model**, so `make eval-policy` over the unescalated and escalated forced labels together
   prints R3's last clause (`escalation_effects`: the escalated attempt 3 against the unescalated one). Step 8 therefore needs one more
   command than it lists: `make eval-policy LABELS="c7-forced c7-forced-icehouse c7-forced-escalated c7-forced-escalated-icehouse"
   OUT=c7-forced-all-policy.md`.
8. **C7-K2 is two `TODO(Ari)` blocks** (`would_fail` and `sweep_cell`), one key point; the scaffold in the plan held both functions' code in
   one block.
9. **Report-layout tests use a stand-in for the gaps.** `test_markdown_report.py`'s `filled_gaps` fixture monkeypatches C7-K1 to C7-K3 with
   the plan's definitions in their simplest form, so the sections' layout is tested while the gaps are open (and those tests stay green). The
   cleanup pass after Ari's commit should delete the fixture and let the two tests use the real functions.
10. **Test order.** `test_policy_questions.py` was written first and watched failing (ImportError on the missing module, then
    `NotImplementedError` on the gaps); writing it caught one wrong test input (the C7-R1 "yes" case had 16, not 20, wrong rows outside the
    largest venue, which is test data, not code). The §4 and §5 tests were written alongside the harness code; they were then confirmed to
    fail against the unchanged `run_one_page.py` (ImportError on `confidence_fields`).
11. Smaller: `--force-retries` with `--threshold` is refused twice, by `main` (exit 2, before the endpoint check) and by `build_policy`
    (ValueError); `stopped` counts every scored error item on a failed attempt, the same population as the recall tally; per-attempt seconds
    are rounded to 0.01.

**`TODO(Ari)` gaps: all three open** (none filled by Claude).

| Key point | Where | Tests |
|---|---|---|
| C7-K1 | `policy_questions.py:81` (`confidence_rows`) | the §1 rows of `test_policy_questions.py` |
| C7-K2 | `policy_questions.py:211` (`would_fail`) and `:228` (`sweep_cell`) | the §2 rows, including the 128-row mirror against `policy.combine` |
| C7-K3 | `policy_questions.py:283` (`transition`) | the §3 transition, churn and `retry_effect` rows |

Command: `cd apps/api && uv run pytest agent_worker/tests/model_eval/test_policy_questions.py`.

**Verification.**

- `make check`: `lint` and `typecheck` pass; `test` reports **153 failed, 1335 passed**, and every failure is in `test_policy_questions.py`
  on `NotImplementedError: TODO(Ari)` (`pytest ... | grep '^E '` gives that one line 153 times; plan Verification 1). `make check` stops at
  `test`, so its last three targets were run on their own: `make -k contract-check designation-check BASE=8c90a38 e2e` exits 0 (Playwright
  107 passed).
- `make designation-check BASE=8c90a38`: exit 0 (four bare `K1`/`K3` were found on the first pass and scoped; a comment-only fix inside new
  code, re-checked by the full run above).
- **With the gaps filled in a scratch copy** (each block's Code lines pasted in by a script, the file restored afterwards): all 167 tests in
  `test_policy_questions.py` pass.
- **Mutation checks C7-M1 to C7-M7** (on the filled copy, each reverted): all caught, each by its named test (M1, M2 both ways, M3 by the
  mirror, M4, M5, M6, M7 by the escalation-flag test).
- **Dry run of Step 7's cross-check** (gaps filled in the scratch copy, no model): `--rescore c6-confirm-gated` and `--rescore c6-confirm-heldout`,
  then `--policy-report` over both. It reproduces F1 to F4: confidence 0.9 holds 142 rows with 2 wrong (Turf Club), 1.0 holds 352 rows with
  98 wrong (all Icehouse); C7-R1 reads "not enough evidence" (2 wrong rows outside Icehouse); the excluded line shows 0.5 (6) and 0.8 (3) as
  correct exclusions and 1.0 as 23 correct and 14 missed (Icehouse's dropped shows); no page made a second attempt. The sweep at 0.95 would
  have sent 8 correct page-runs to a retry and caught 1. These are not C7's results (Step 7 reruns them on the filled code); they show the
  instrument reads the saved files as the plan expects. The rescored files are gitignored.
- Not run: anything that calls a model (Steps 7 and 8 are Ari's, after the gaps).

**Where to look hardest.**

- **Token counting in a real run.** The scripted test exercises the hook through `nodes.instructor_client`, the ContextVar and the node
  threads, but the real instructor client has not been driven by it; the first real run should show non-null `tokens` (plan "Unverified").
- **`_spans` and the stager's marks under a scenario**, where one stager serves two `run_page` calls (`first_document` slices both lists).
- **`judged_indices` against `aggregate_confidence`.** They are computed separately; `confidence_disagree` and the first test in §4 are the
  only guards that the recorded confidence covers the same shows.
- **R1 and R3 as code against their text in "The readings"** (`r1_verdict`'s order of checks, `page_effects`' use of attempt 1's band for the
  3-vs-2 comparison, `r4_verdict`'s literal reading).
- **`excluded_confidences`** joins a `missed` item to an excluded show by `scoring._dropped_index`, whose date-only match has a known limit
  (C5-CR1-5).

### Round 2 — Claude Opus 5.5, November 6, 2026 (code review round 1's fixes)

**Scope.** The same working tree (diff base `8c90a38`, nothing committed), changed since Round 1 in: `saved_run_reports/policy_questions.py`
(`MIN_EFFECT` and `_effect`, `page_effects` over the same runs, the sweep's `structured` line, a spelling), `saved_run_reports/markdown_report.py`
(the structured line and the gated table's intro), `saved_run_reports/aggregate_scores.py` (`confidence_disagree` by key), `Makefile` (the
`eval-graph` comment), the tests (`test_policy_questions.py`: three new; `test_aggregate_scores.py`: one new; `test_markdown_report.py`: one
assertion), and this plan (the noise band, R1 and R3 text, Step 8's pooled command, the Resolution column).

**What changed, by finding.** C7-CR1-1: a change in a page's mean error count must exceed `max(noise band, 0.5)`; this amends R3 (and R4,
which uses R3's rule) **before any C7 run**, and is Ari's to confirm (D5). C7-CR1-2: `page_effects` compares attempt `k` with attempt 1 over the
runs that reached `k`. C7-CR1-3: R1's per-venue minimum written into the plan, code unchanged. C7-CR1-4: structured-route attempts are swept on
their own line. C7-CR1-5 and C7-CR1-6: spelling and the Makefile comment. C7-CR1-7: the red tests are listed below; `confidence_disagree` keys on
the presence of `recorded_confidence`. Each code fix had its test written first and watched failing (with the gaps filled in the scratch copy,
the four new tests failed and the other 182 in the two modules passed).

**`TODO(Ari)` gaps: still all open**, at `policy_questions.py:88` (C7-K1, `confidence_rows`), `:218` (C7-K2, `would_fail`), `:235` (C7-K2,
`sweep_cell`) and `:295` (C7-K3, `transition`). The cleanup pass after Ari's commit also drops the `# noqa: F401` on the `Counter` import (the
C7-K3 code uses it) and deletes `test_markdown_report.py`'s `filled_gaps` fixture.

**The red tests**, all in `test_policy_questions.py`, all on `NotImplementedError: TODO(Ari)` (154 in all): C7-K1:
`test_confidence_rows_are_the_judged_shows_and_only_errors_make_a_row_wrong`, `test_an_excluded_low_confidence_show_gives_no_row`,
`test_a_status_merge_placeholder_gives_no_row`, `test_each_wrong_kind_makes_its_show_wrong` (x5), `test_structured_route_shows_give_no_rows`
(x2), `test_image_route_shows_give_rows`, `test_rows_by_venue_reads_attempt_one_of_each_run_and_maps_fixtures_to_venues`. C7-K2:
`test_sweep_cells` (x5), `test_sweep_should_retry_is_the_scorers_own_gate`, `test_sweep_recomputes_low_confidence_at_each_threshold`,
`test_sweep_mirror_agrees_with_combine` (x128), `test_the_sweep_keeps_gated_and_informational_pages_apart`,
`test_the_sweep_puts_structured_route_pages_on_their_own_line`. C7-K3: `test_transition_matches_errors_by_kind_date_and_field_not_index`,
`test_transition_is_a_multiset`, `test_transition_ignores_missing_fields_and_counts_a_new_wrong_field`, `test_churn_between_runs_is_the_mean_over_pairs`,
`test_retry_effect_reports_each_transition_with_seconds_and_tokens`.

**Verification.** See the end of code review round 1 for the suite result after the fixes. With the gaps filled in the scratch copy:
`agent_worker/tests/model_eval` 376 passed, and the mutation script was re-run: C7-M1 to C7-M7 (M2 both ways) are each still caught by its named test.

### Round 3 — Claude Opus 5.5, November 6, 2026 (the gaps closed, and the cleanup pass)

**Scope.** The same working tree (diff base `8c90a38`); committed with this round as the build's first commit on `c7-pipeline-eval`.

**`TODO(Ari)` gaps: all three filled by Ari** (C7-K1 `confidence_rows`, C7-K2 `would_fail` and `sweep_cell`, C7-K3 `transition`), with the
plan's Code lines. The cleanup pass (AGENTS.md, "[fill-in] tasks", step 4) then:

- rewrote each block in `policy_questions.py` as a plain why-comment (the `TODO(Ari)` marker, the labels and the K3 block's leftover
  "To align / Code / Check" lines gone; the reasoning and the K-forms kept), dropped the `noqa: F401` on `Counter`, and reworded the two
  docstring lines that spoke of gaps (`policy_questions.py`'s module docstring, `test_policy_questions.py`'s module docstring and one
  `Proves:` line). Comment-only, checked as one: the syntax trees of both files, docstrings removed, are identical before and after;
- deleted `test_markdown_report.py`'s `filled_gaps` fixture (a code change, made apart from the comment pass): the two report tests now run
  on the real C7-K1 to C7-K3, with their expectations unchanged.

**Verification.** `uv run pytest agent_worker/tests/model_eval`: 376 passed with Ari's code, before and after the cleanup. `make check`: exit 0
(pytest 1492 passed, vitest 525 passed, Playwright 107 passed, `designation-check` and `contract-check` clean).

**What is left of C7** is Steps 7 to 10: local only (the DeepInfra key, the gitignored captured pages, Postgres), with three things for Ari
before or during them: confirm C7-CR1-1's floor on R3 (0.5 errors a run, D5), confirm `google/gemma-4-31B-it` is still served before Step 8
(D2), and decide the defaults at Step 9.

### Round 4 — Claude Sonnet 5.5, November 6, 2026 (Steps 7 to 9: the measurement runs, the readings and the recommendation; the build stops here for Ari's decision on the defaults)

**Scope.** Diff base `a55aa87` (Round 3's commit). Commits since: `751543e` (the Step 7 snapshots `docs/dev/eval-baselines/c7-defaults.json`
and `c7-defaults-icehouse.json`), `0a5d8a2` (the Step 8 snapshots `c7-forced.json`, `c7-forced-icehouse.json`, `c7-forced-escalated.json`,
`c7-forced-escalated-icehouse.json`), and the merge of `main` (PR 96) described in Departure 1. No code or label change in the runs' own
commits: every C7 run records harness commit `751543ef16` and `labels_sha` `e49e570663`. This round changes only this file.

**Before any model call** (Ari, this session): confirmed the C7-CR1-1 floor on R3 (`MIN_EFFECT` = 0.5 stays; no code change); confirmed
`google/gemma-4-31B-it` is still served on DeepInfra (D2); DeepInfra spend before C7 was "under $1" (no exact figure given). The dashboard
spend after C7 has **not been read** (the author cannot); the token totals are at the end of Verification.

**Departures from the plan and from the rules, each with its reason.**

1. **The merge of `main` landed after Step 8, not during it.** Ari's pull of `main` (PR 96, which includes PQR1-1's `ruff format` at 120
   columns) left a half-done merge in the working tree while the Step 8 chain was running, and it touched `labels.py`, `validation.py`,
   `extraction.py`, `prompts.py` and `policy.py`. The last forced run would have started on the merged code, with a different `labels_sha`.
   With Ari's go-ahead the unresolved merge was aborted, the six conflicts were resolved in a separate worktree (all layout: the C7 side
   kept, then `ruff format`; the `Makefile` `.PHONY` line keeps `eval-policy` and `format`; one N806 lint fix in `policy_questions.py`, a
   local constant renamed lowercase), and the result landed as `d536114` after the last run finished. **`labels.py` is reformatted by the
   merge, so its hash changes, but no label's content did and none of the C7 results files was rescored: all seven carry `e49e570663`.**
   The plan's "no edit to `labels.py` from Step 7 to Step 9" held for every run; the merge came after the last one. Checks on the merged
   tree: the defaults report and the pooled forced report are byte-identical to the pre-merge ones; `uv run pytest` 1524 passed with no skips
   (the real-page tests run here); `make lint typecheck` pass. `make check` (vitest, Playwright) has not been run since the merge.
2. **C7-R1 does not say which labels it is read on, and its "no" does not cover a ratio between 1 and 2.** The plan's R1 reads "over the
   wrong-show rows" without naming the default runs or the forced runs (R2 and the sweep name the default runs). Attempt 1 of a forced run
   sends the same requests as a default run (forcing changes the verdict, not the extraction), so every label gives attempt-1 rows. I report
   **every table, and do not pick one after seeing the numbers**: the Step 7 defaults table reads "not enough evidence"; every other table
   reads "no"; no table reads "yes". And R1's text defines "no" as "flat or inverted" and "yes" as at least twice as high on two venues; a
   pooled ratio in between (the forced pool: 0.26 against 0.20) fits neither, and `r1_verdict` returns "no" for it. I applied the code's
   output and name the gap here for Ari.
3. **The D9 secondary table was run on rescored files** (`c6-hosted-baseline`, `c61-icehouse`, `c61-icehouse-price`, `c61-split-before`,
   `c61-split-after`) and, with the cross-check, was not written to a snapshot (the plan asks for snapshots of the C7 labels only). The
   rescored files are gitignored.
4. **R4 reads differently for the two forced configurations, and I recommend the one that ships.** See R4 below.
5. **A fourth attempt was not run.** R4 says one is "not run in C7 unless" attempt 3 helps on two pages; that happens only in the escalated
   configuration, which R3 rejects, so I did not spend a run on it. It is Ari's to ask for (Decisions for Ari, 3).

**`TODO(Ari)` gaps:** none open (all three were filled in Round 3).

**Runs** (one at a time, each in the background, the report header checked after each; `ESCALATION_MODEL=none` and the hosted settings as
one-command overrides: `MODEL_BASE_URL=https://api.deepinfra.com/v1/openai MODEL_PROVIDER=openai_compatible
MODEL_NAME=google/gemma-4-26B-A4B-it`, the key from `apps/api/.env`, never on a command line).

| label | pages | runs | policy in the header | wall time (local) |
|---|---|---|---|---|
| `c7-smoke` (not kept) | Mortimer's | 1 | threshold 0.8, cap 3, escalation none | 14 s; attempt 1 carried tokens 3,529 / 974 and seconds 13.6, so the hook on the real client works |
| `c7-defaults` | `SET=all`, 10 pages | 50 | threshold 0.8, cap 3, escalation none | about 15 min |
| `c7-defaults-icehouse` | held-out Icehouse | 5 | same | about 14 min |
| `c7-forced` | `SET=all` | 50 | threshold 1.01 (forced retries), cap 3, escalation none | about 54 min |
| `c7-forced-icehouse` | Icehouse | 5 | same | about 27 min |
| `c7-forced-escalated` | `SET=all` | 50 | forced, escalation model `google/gemma-4-31B-it` | about 70 min |
| `c7-forced-escalated-icehouse` | Icehouse | 5 | same | about 81 min |

Headers: `forced retries` appears on the four forced labels and on no other; `escalation_model` is None on the first two forced labels and
`google/gemma-4-31B-it` on the last two; every attempt-3 record has tier `larger_model` in all four forced labels, but `larger_model_used` is true only in the two escalated
labels (35 of 35 and 5 of 5 third attempts) and in no other label (Verification 6); `labels_sha` `e49e570663` on all seven. No `retried` page in either default
label (0 retries in 55 page-runs).

**The tables.** The `eval-policy` outputs, pasted from the files the commands wrote (headings demoted three levels).

*Step 7, the default runs (`make eval-policy LABELS="c7-defaults c7-defaults-icehouse"`):*

#### Policy questions: c7-defaults, c7-defaults-icehouse

- c7-defaults: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- c7-defaults-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none

##### Confidence and correctness (C7-Q4)

Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). A value is compared only with 10 or more rows.

| confidence | rows | wrong | wrong rate | compared | per venue (wrong/rows) |
|---|---|---|---|---|---|
| 0.9 | 44 | 1 | 0.02 | yes | icehouse 0/4; mortimers 0/35; terminal 1/5 |
| 0.95 | 4 | 0 | 0.00 | no | terminal 0/4 |
| 1 | 549 | 117 | 0.21 | yes | icehouse 101/223; seventh_st_entry 0/150; terminal 16/91; turf_club 0/85 |

- C7-R1: **not enough evidence** (17 wrong rows outside the largest contributor (icehouse); C7-R1 needs 20)
- excluded shows' confidences, never in the buckets: 1.0: 27 correct, 13 missed

##### Threshold sweep (C7-Q1)

Attempt 1 of each model-judged run (model and image routes). Would retry = failed for a reason other than low confidence, or confidence under the threshold; should retry = attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (C7-K2).

| threshold | caught | false alarm | missed | quiet |
|---|---|---|---|---|
| 0.5 | 0 | 0 | 5 | 15 |
| 0.6 | 0 | 0 | 5 | 15 |
| 0.7 | 0 | 0 | 5 | 15 |
| 0.8 | 0 | 0 | 5 | 15 |
| 0.85 | 0 | 0 | 5 | 15 |
| 0.9 | 0 | 0 | 5 | 15 |
| 0.95 | 2 | 5 | 3 | 10 |
| 1 | 2 | 5 | 3 | 10 |

- informational pages (never gate), caught/false alarm/missed/quiet: 0.5: 0/0/9/11; 0.6: 0/0/9/11; 0.7: 0/0/9/11; 0.8: 0/0/9/11; 0.85: 0/0/9/11; 0.9: 0/0/9/11; 0.95: 1/4/8/7; 1: 1/8/8/3
- structured-route pages (no confidence, so no threshold can catch their errors; C7-CR1-4), caught/false alarm/missed/quiet: 0.5: 0/0/5/10; 0.6: 0/0/5/10; 0.7: 0/0/5/10; 0.8: 0/0/5/10; 0.85: 0/0/5/10; 0.9: 0/0/5/10; 0.95: 0/0/5/10; 1: 0/0/5/10

##### What each retry changed (C7-Q3, C7-Q2)

No page made a second attempt.

*Step 8, the forced runs, pooled over all four labels (`make eval-policy LABELS="c7-forced c7-forced-icehouse c7-forced-escalated
c7-forced-escalated-icehouse"`; it prints both escalation groups and R3's escalated-against-unescalated line):*

#### Policy questions: c7-forced, c7-forced-icehouse, c7-forced-escalated, c7-forced-escalated-icehouse

- c7-forced: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model none
- c7-forced-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model none
- c7-forced-escalated: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model google/gemma-4-31B-it
- c7-forced-escalated-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model google/gemma-4-31B-it

##### Confidence and correctness (C7-Q4)

Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). A value is compared only with 10 or more rows.

| confidence | rows | wrong | wrong rate | compared | per venue (wrong/rows) |
|---|---|---|---|---|---|
| 0.8 | 3 | 0 | 0.00 | no | icehouse 0/3 |
| 0.9 | 98 | 25 | 0.26 | yes | icehouse 16/18; mortimers 0/70; terminal 9/10 |
| 0.95 | 10 | 0 | 0.00 | yes | terminal 0/10 |
| 1 | 1079 | 218 | 0.20 | yes | icehouse 182/429; seventh_st_entry 0/300; terminal 36/180; turf_club 0/170 |

- C7-R1: **no** (pooled slope does not hold; venues where it holds: ['terminal', 'icehouse'])
- excluded shows' confidences, never in the buckets: 0.8: 1 correct, 0 missed, 0.9: 2 correct, 2 missed, 1.0: 37 correct, 27 missed

##### Threshold sweep (C7-Q1)

Attempt 1 of each model-judged run (model and image routes). Would retry = failed for a reason other than low confidence, or confidence under the threshold; should retry = attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (C7-K2).

| threshold | caught | false alarm | missed | quiet |
|---|---|---|---|---|
| 0.5 | 0 | 0 | 10 | 30 |
| 0.6 | 0 | 0 | 10 | 30 |
| 0.7 | 0 | 0 | 10 | 30 |
| 0.8 | 0 | 0 | 10 | 30 |
| 0.85 | 2 | 0 | 8 | 30 |
| 0.9 | 2 | 0 | 8 | 30 |
| 0.95 | 2 | 10 | 8 | 20 |
| 1 | 2 | 10 | 8 | 20 |

- informational pages (never gate), caught/false alarm/missed/quiet: 0.5: 0/0/25/15; 0.6: 0/0/25/15; 0.7: 0/0/25/15; 0.8: 0/0/25/15; 0.85: 0/0/25/15; 0.9: 0/0/25/15; 0.95: 9/1/16/14; 1: 9/11/16/4
- structured-route pages (no confidence, so no threshold can catch their errors; C7-CR1-4), caught/false alarm/missed/quiet: 0.5: 0/0/10/20; 0.6: 0/0/10/20; 0.7: 0/0/10/20; 0.8: 0/0/10/20; 0.85: 0/0/10/20; 0.9: 0/0/10/20; 0.95: 0/0/10/20; 1: 0/0/10/20

##### What each retry changed (C7-Q3, C7-Q2)

Errors are every kind but field_missing; an error is the same in two attempts when its kind, date and field match (C7-K3). Noise band = the population SD of attempt 1's errors across a page's runs; an attempt helps on a page when its mean is lower by more than the band, and a tier helps when it helps on two pages and hurts on none (C7-R3). On the shipped route a forced attempt 2 sends the splitter the same request, so this measures a generic hint plus a resample, not the specific-hint path.

###### Escalation model: none

| transition | runs | fixed | introduced | kept | mean seconds | tokens (prompt/completion) |
|---|---|---|---|---|---|---|
| 1 to 2 | 40 | 9 | 8 | 131 | 41.0 | 205918/113926 |
| 2 to 3 (same model) | 40 | 14 | 22 | 125 | 39.3 | 207993/113758 |

| page | noise band | churn | errors at 1 | at 2 | at 3 | 2 vs 1 | 3 vs 2 |
|---|---|---|---|---|---|---|---|
| Archives_ Events - The White Squirrel Bar.html | 0.00 | 0.00 | 0.0 | - | - | - | - |
| Events — Zhora Darling.html | 0.00 | 0.00 | 2.0 | - | - | - | - |
| Terminal Bar – The Terminal Bar.html | 0.00 | 0.00 | 3.0 | 3.0 | 3.0 | neither | neither |
| icehouse-2026-11-05.html | 0.49 | 0.80 | 23.6 | 23.6 | 23.6 | neither | neither |
| mortimers-2026-10-10.html | 0.00 | 0.00 | 0.0 | 0.0 | 0.0 | neither | neither |
| seventh_st_entry-2026-10-10.html | 0.00 | 0.00 | 0.0 | 0.0 | 0.0 | neither | neither |
| terminal-2026-10-10.html | 0.49 | 0.60 | 0.6 | 0.6 | 0.2 | neither | neither |
| terminal_bar_show_1.png | 0.00 | 0.00 | 0.0 | 0.6 | 1.0 | hurts | neither |
| terminal_bar_show_2.webp | 0.40 | 0.40 | 0.8 | 0.0 | 0.0 | helps | neither |
| turf_club-2026-11-04.html | 0.00 | 0.00 | 0.0 | 0.0 | 1.6 | neither | hurts |
| white_squirrel-2026-10-10.html | 0.00 | 0.00 | 0.0 | - | - | - | - |

- C7-R3 tier 2: **does not help**; tier 3: **does not help**
- C7-R4 (the cap): **2 (attempt 3 hurts on a page and helps on none)**

###### Escalation model: google/gemma-4-31B-it

| transition | runs | fixed | introduced | kept | mean seconds | tokens (prompt/completion) |
|---|---|---|---|---|---|---|
| 1 to 2 | 40 | 11 | 5 | 133 | 42.7 | 205694/109243 |
| 2 to 3 (larger model) | 40 | 94 | 20 | 44 | 141.4 | 207975/131666 |

| page | noise band | churn | errors at 1 | at 2 | at 3 | 2 vs 1 | 3 vs 2 |
|---|---|---|---|---|---|---|---|
| Archives_ Events - The White Squirrel Bar.html | 0.00 | 0.00 | 0.0 | - | - | - | - |
| Events — Zhora Darling.html | 0.00 | 0.00 | 2.0 | - | - | - | - |
| Terminal Bar – The Terminal Bar.html | 0.00 | 0.00 | 3.0 | 3.0 | 0.0 | neither | helps |
| icehouse-2026-11-05.html | 0.40 | 2.60 | 24.2 | 23.8 | 12.0 | neither | helps |
| mortimers-2026-10-10.html | 0.00 | 0.00 | 0.0 | 0.0 | 0.0 | neither | neither |
| seventh_st_entry-2026-10-10.html | 0.00 | 0.00 | 0.0 | 0.0 | 0.8 | neither | hurts |
| terminal-2026-10-10.html | 0.49 | 0.60 | 0.6 | 0.4 | 0.0 | neither | neither |
| terminal_bar_show_1.png | 0.00 | 0.00 | 0.0 | 0.4 | 0.0 | neither | neither |
| terminal_bar_show_2.webp | 0.00 | 0.00 | 1.0 | 0.0 | 0.0 | helps | neither |
| turf_club-2026-11-04.html | 0.00 | 0.00 | 0.0 | 0.0 | 0.0 | neither | neither |
| white_squirrel-2026-10-10.html | 0.00 | 0.00 | 0.0 | - | - | - | - |

- C7-R3 tier 2: **does not help**; tier 3: **does not help**
- C7-R4 (the cap): **4 (attempt 3 helps on two or more pages; a fourth attempt would need its own run)**

- google/gemma-4-31B-it at attempt 3 against no escalation model: {'Terminal Bar – The Terminal Bar.html': 'helps', 'mortimers-2026-10-10.html': 'neither', 'seventh_st_entry-2026-10-10.html': 'hurts', 'terminal-2026-10-10.html': 'neither', 'terminal_bar_show_1.png': 'helps', 'terminal_bar_show_2.webp': 'neither', 'turf_club-2026-11-04.html': 'helps', 'icehouse-2026-11-05.html': 'helps'}; **does not help**

*Supplementary, not in the plan: the confidence table over attempt 1 of all six labels (the two default and the four forced), since
Departure 2 says R1 names no label. Same shape, 1,787 rows:*

#### Policy questions: c7-defaults, c7-defaults-icehouse, c7-forced, c7-forced-icehouse, c7-forced-escalated, c7-forced-escalated-icehouse

- c7-defaults: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- c7-defaults-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- c7-forced: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model none
- c7-forced-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model none
- c7-forced-escalated: labels_sha e49e570663; set all; runs 50; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model google/gemma-4-31B-it
- c7-forced-escalated-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 1.01 (forced retries), cap 3, escalation model google/gemma-4-31B-it

##### Confidence and correctness (C7-Q4)

Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). A value is compared only with 10 or more rows.

| confidence | rows | wrong | wrong rate | compared | per venue (wrong/rows) |
|---|---|---|---|---|---|
| 0.8 | 3 | 0 | 0.00 | no | icehouse 0/3 |
| 0.9 | 142 | 26 | 0.18 | yes | icehouse 16/22; mortimers 0/105; terminal 10/15 |
| 0.95 | 14 | 0 | 0.00 | yes | terminal 0/14 |
| 1 | 1628 | 335 | 0.21 | yes | icehouse 283/652; seventh_st_entry 0/450; terminal 52/271; turf_club 0/255 |

- C7-R1: **no** (pooled slope does not hold; venues where it holds: ['terminal'])
- excluded shows' confidences, never in the buckets: 0.8: 1 correct, 0 missed, 0.9: 2 correct, 2 missed, 1.0: 64 correct, 40 missed

*Step 7's cross-check, no model call: `--rescore c6-confirm-gated` and `--rescore c6-confirm-heldout`, then `eval-policy` over the two.
It reproduces C7-F1 to C7-F4 (the third section, "No page made a second attempt", is omitted):*

#### Policy questions: rescore-c6-confirm-gated, rescore-c6-confirm-heldout

- rescore-c6-confirm-gated: labels_sha e49e570663; set gated; runs 25; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- rescore-c6-confirm-heldout: labels_sha e49e570663; set held_out; runs 20; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none

##### Confidence and correctness (C7-Q4)

Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). A value is compared only with 10 or more rows.

| confidence | rows | wrong | wrong rate | compared | per venue (wrong/rows) |
|---|---|---|---|---|---|
| 0.9 | 142 | 2 | 0.01 | yes | mortimers 0/35; seventh_st_entry 0/90; turf_club 2/17 |
| 1 | 352 | 98 | 0.28 | yes | icehouse 98/224; seventh_st_entry 0/60; turf_club 0/68 |

- C7-R1: **not enough evidence** (2 wrong rows outside the largest contributor (icehouse); C7-R1 needs 20)
- excluded shows' confidences, never in the buckets: 0.5: 6 correct, 0 missed, 0.8: 3 correct, 0 missed, 1.0: 23 correct, 14 missed

##### Threshold sweep (C7-Q1)

Attempt 1 of each model-judged run (model and image routes). Would retry = failed for a reason other than low confidence, or confidence under the threshold; should retry = attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (C7-K2).

| threshold | caught | false alarm | missed | quiet |
|---|---|---|---|---|
| 0.5 | 0 | 0 | 6 | 14 |
| 0.6 | 0 | 0 | 6 | 14 |
| 0.7 | 0 | 0 | 6 | 14 |
| 0.8 | 0 | 0 | 6 | 14 |
| 0.85 | 0 | 0 | 6 | 14 |
| 0.9 | 0 | 0 | 6 | 14 |
| 0.95 | 1 | 8 | 5 | 6 |
| 1 | 1 | 8 | 5 | 6 |

- informational pages (never gate), caught/false alarm/missed/quiet: 0.5: 0/0/0/0; 0.6: 0/0/0/0; 0.7: 0/0/0/0; 0.8: 0/0/0/0; 0.85: 0/0/0/0; 0.9: 0/0/0/0; 0.95: 0/0/0/0; 1: 0/0/0/0
- structured-route pages (no confidence, so no threshold can catch their errors; C7-CR1-4), caught/false alarm/missed/quiet: 0.5: 0/0/15/10; 0.6: 0/0/15/10; 0.7: 0/0/15/10; 0.8: 0/0/15/10; 0.85: 0/0/15/10; 0.9: 0/0/15/10; 0.95: 0/0/15/10; 1: 0/0/15/10

*D9's secondary table, own group, never pooled with the C7 labels (rescored `c6-hosted-baseline`, `c61-icehouse`, `c61-icehouse-price`,
`c61-split-before`, `c61-split-after`; older prompts; the third section, "No page made a second attempt", is omitted):*

#### Policy questions: rescore-c6-hosted-baseline, rescore-c61-icehouse, rescore-c61-icehouse-price, rescore-c61-split-before, rescore-c61-split-after

- rescore-c6-hosted-baseline: labels_sha e49e570663; set all; runs 10; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- rescore-c61-icehouse: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- rescore-c61-icehouse-price: labels_sha e49e570663; set held_out; runs 5; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- rescore-c61-split-before: labels_sha e49e570663; set gated; runs 15; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none
- rescore-c61-split-after: labels_sha e49e570663; set gated; runs 15; model google/gemma-4-26B-A4B-it; policy: threshold 0.8, cap 3, escalation model none

##### Confidence and correctness (C7-Q4)

Attempt 1 of each run; one row per show the record's confidence covers (kept, model-judged: not excluded, not a status-merge placeholder, not the structured route). Wrong = wrong acts, invented, a leak, a wrong field or image (C7-K1). A value is compared only with 10 or more rows.

| confidence | rows | wrong | wrong rate | compared | per venue (wrong/rows) |
|---|---|---|---|---|---|
| 0.9 | 92 | 2 | 0.02 | yes | icehouse 0/4; mortimers 0/40; seventh_st_entry 0/30; terminal 0/1; turf_club 2/17 |
| 0.95 | 1 | 1 | 1.00 | no | terminal 1/1 |
| 1 | 757 | 200 | 0.26 | yes | icehouse 192/450; mortimers 0/7; seventh_st_entry 3/180; terminal 0/18; turf_club 5/102 |

- C7-R1: **not enough evidence** (11 wrong rows outside the largest contributor (icehouse); C7-R1 needs 20)
- excluded shows' confidences, never in the buckets: 0.9: 3 correct, 2 missed, 1.0: 41 correct, 24 missed

##### Threshold sweep (C7-Q1)

Attempt 1 of each model-judged run (model and image routes). Would retry = failed for a reason other than low confidence, or confidence under the threshold; should retry = attempt 1 fails the A2.1-D1 standard as `scoring.gate` judges it (C7-K2).

| threshold | caught | false alarm | missed | quiet |
|---|---|---|---|---|
| 0.5 | 0 | 0 | 17 | 14 |
| 0.6 | 0 | 0 | 17 | 14 |
| 0.7 | 0 | 0 | 17 | 14 |
| 0.8 | 0 | 0 | 17 | 14 |
| 0.85 | 0 | 0 | 17 | 14 |
| 0.9 | 0 | 0 | 17 | 14 |
| 0.95 | 4 | 6 | 13 | 8 |
| 1 | 4 | 6 | 13 | 8 |

- informational pages (never gate), caught/false alarm/missed/quiet: 0.5: 0/0/1/3; 0.6: 0/0/1/3; 0.7: 0/0/1/3; 0.8: 0/0/1/3; 0.85: 0/0/1/3; 0.9: 0/0/1/3; 0.95: 0/1/1/2; 1: 1/1/0/2
- structured-route pages (no confidence, so no threshold can catch their errors; C7-CR1-4), caught/false alarm/missed/quiet: 0.5: 0/0/2/13; 0.6: 0/0/2/13; 0.7: 0/0/2/13; 0.8: 0/0/2/13; 0.85: 0/0/2/13; 0.9: 0/0/2/13; 0.95: 0/0/2/13; 1: 0/0/2/13

**The readings, applied as written.**

| Reading | Outcome | How |
|---|---|---|
| **C7-R1** (Q4) | **Not enough evidence on the Step 7 default runs; "no" on every other table; "yes" on none.** | Defaults: 17 wrong kept rows outside Icehouse, 20 needed (Terminal Bar 16 of 91 at confidence 1.0 and 1 of 5 at 0.9). Forced pool: confidence 0.9 holds 98 rows at 0.26 wrong against 0.20 at 1.0; the pooled slope is under 2x and the code returns "no". All six labels' attempt 1: 0.9 holds 142 rows at 0.18 wrong against 0.21 at 1.0, which is flat or inverted: "no". See Departure 2. |
| **C7-R2** (Q1) | **Confirm 0.8; document it as inert on the shipped model. Not tuned, and not lowered.** | Both sweeps catch nothing at any threshold up to 0.8 (default runs: 0 caught, 5 missed, 15 quiet; forced pool: 0 caught, 10 missed). Raising it to 0.85 to 1.0 would catch 2 of the 5 or 10 should-retry gated page-runs (the forced pool: 2 caught and 0 false alarms at 0.85 and 0.9, then 10 false alarms at 0.95 and 1), but R3 says a retry does not help, so by R2 no threshold is better. 0.8 sends no correct page to a retry (0 false alarms in both sweeps, at every threshold up to 0.9 in the defaults), so the "lower it to 0" clause does not apply. |
| **C7-R3** (Q3) | **Tier 2 does not help. Tier 3 does not help, with no escalation model or with the 31B.** The escalated tier does not beat the unescalated one by the rule. | Per page, over the same runs, noise band and the 0.5 floor. **Tier 2, no escalation:** helps on `terminal_bar_show_2.webp` (0.8 to 0.0), hurts on `terminal_bar_show_1.png` (0.0 to 0.6), neither elsewhere. **Tier 2, 31B group:** helps on `terminal_bar_show_2.webp` (1.0 to 0.0) only. **Tier 3, no escalation:** hurts on `turf_club` (0.0 to 1.6), helps on none. **Tier 3, 31B:** helps on Terminal Bar (3.0 to 0.0) and Icehouse (23.8 to 12.0), **hurts on 7th St Entry (0.0 to 0.8)**; two pages helped, but "hurts on none" fails. **31B against none at attempt 3:** helps on Terminal Bar, `terminal_bar_show_1.png`, Turf Club and Icehouse, hurts on 7th St Entry: does not help for the same reason. |
| **C7-R4** (Q2) | **2 for the configuration that ships (no escalation model): attempt 3 hurts on a page (Turf Club) and helps on none. For the 31B group the literal text gives 4** (attempt 3 helps on two pages), which R3 has rejected. | Taken as written. At the default threshold the cap matters only when a check error fires, and C7-F1 says that has not happened in 100 default page-runs (45 saved, 55 here). |

**What changed and what it cost, as description (not a rule).** From the pooled forced report: with no escalation model, attempt 2 fixed
9 errors and introduced 8 (131 kept), and attempt 3 fixed 14 and introduced 22 (125 kept). With the 31B at attempt 3 the counts are 94
fixed, 20 introduced and 44 kept: the larger model changes far more than a resample does. Icehouse's mean errors a run halve (23.8 to 12.0)
and Terminal Bar's go to 0. The price: 141.4 s a page-attempt against 39.3 s (3.6x), and 131,666 completion tokens over 40 runs against
113,758 (the prompt tokens are about the same, 207,975 against 207,993). The one regression that fails R3 is systematic, not noise: in 4 of
5 runs the 31B returns seven acts for 7th St Entry's 2026-10-31 listing where the label has four (it adds `INTERNET KIDS`, `Visa_Card` and
`Wizard.Imma`; read from the saved attempts' error items), and the unescalated third attempt does not. Turf Club's tier-3 "hurt" without the
larger model (0.0 to 1.6) is the same page that drops a second act in some runs (C6 Round 10, miss 5), so a resample explains part of it.
A forced run commits nothing, so none of this says what a production retry would commit.

**The recommendation for each default, worded within the Q3 scope the Context states** (a generic low-confidence hint plus a resample
at tier 2, and at tier 3 the final-attempt sentence plus a larger model; the production path that retries on a specific check finding is
not exercised, C7-F1):

1. **Confidence threshold: confirm 0.8 and document it as inert on the shipped model.** It has never fired on this model; the data give no
   threshold that is better; changing it would be tuning to noise. A comment in `policy.py` replaces "A8 checks whether the number is right".
2. **Attempt cap: R4 reads 2 for the configuration that ships, because attempt 3 without an escalation model only adds the final-attempt
   sentence and, in the forced runs, hurt Turf Club and helped nothing.** The figure is small (one page, a resample) and the cap is inert
   at the default threshold, so keeping 3 costs nothing today; changing to 2 follows the rule and removes a tier that exists only for an
   escalation model nobody has adopted. Ari decides, with a lean to the rule.
3. **Escalation model: do not adopt one.** R3 does not clear `google/gemma-4-31B-it`: it does not help by the rule, although it halves
   Icehouse's errors and clears Terminal Bar, and the one page that fails it, 7th St Entry, gets the same wrong act list in 4 of 5 runs.
   The tier-3 answer is "this larger model, on a forced retry, does not recover the errors on net", **not** "a larger model cannot help".
4. **Q4: confidence is not used to route** (R1 never reads "yes"; the page model's opinion covers the listing, and the splitter that makes
   the dominant error reports none, C7-F5). This is the evidence arch-initial.md §11 asked for on the review flag: act-split uncertainty
   belongs in the review flag, not the retry loop (D8), because a retry that triggers on a check does not help either (R3, tier 2).

**Decisions for Ari (the build stops here).**

1. **The three defaults:** threshold 0.8 (confirm, document as inert); cap 3 or 2 (R4 says 2); escalation model none.
2. **R1's sample (Departure 2):** accept "no" on the forced and pooled tables and "not enough evidence" on the defaults, or ask for more
   labeled model-route pages (D9, C5-D4). Terminal Bar's 0.9 rows (9 of 10 wrong in the forced pool) and Icehouse's (16 of 18) point the
   expected way inside each venue, but each is a handful of rows and Mortimer's (70 rows, all right at 0.9) flattens the pool.
3. **A second escalation candidate or a fourth attempt:** D2 allows a second candidate only if R3 says the first is close, and R4 allows
   a fourth attempt only if attempt 3 helps on two pages. Neither was run. The 31B result is "two pages helped, one regressed
   systematically", which is arguably close; each extra pair of escalated runs is about two and a half hours and, by the token counts, well under a
   dollar. I did not decide this for you.
4. **Read the DeepInfra dashboard** and tell me the spend. The runs used 1,508,565 prompt and 824,554 completion tokens in all (smoke
   included), 31B calls among them; at DeepInfra's listed prices that is plausibly well under $1 (PLAUSIBLE, not read), against the $5 budget.

**Verification.**

- Every run's report header checked as listed above; the pooled forced report prints both escalation groups and R3's last line.
- Cross-check (no model): the rescored `c6-confirm-gated` and `c6-confirm-heldout` reproduce C7-F1 to C7-F4 (Icehouse 98 wrong kept rows
  at confidence 1.0, 14 dropped shows in the excluded line, no second attempts), as the dry run in Round 1 did.
- The snapshots hold no API key: the first 8 characters of the key in `apps/api/.env`, searched with `grep -rl` over
  `docs/dev/eval-baselines/` (after the Step 7 snapshots and again after the Step 8 ones), match nothing (exit 1). The snapshot-scan test
  in the suite also passes.
- After the merge: `uv run pytest` 1524 passed; `make lint` and `make typecheck` pass. Not run since the merge: vitest, Playwright
  (`make check` in full), which Step 10 runs. `make designation-check` ran clean on the merge worktree before landing (`BASE=8c90a38`).
- Token totals (prompt / completion): smoke 3,529 / 974; `c7-defaults` 172,537 / 70,537; `c7-defaults-icehouse` 53,317 / 48,542;
  `c7-forced` 479,177 / 195,412; `c7-forced-icehouse` 160,570 / 150,753; `c7-forced-escalated` 478,827 / 205,680;
  `c7-forced-escalated-icehouse` 160,608 / 152,656.

**Where to look hardest.**

- **Departure 2 (R1).** Whether "no" is the right word for a pooled ratio between 1 and 2, and which label R1 was meant to be read on.
  Nothing in the code or the plan settles it; I reported all of it and chose none.
- **R3's "hurts on none" clause against one page's systematic regression.** The verdict on the escalation model turns on 7th St Entry's
  0.8, which crosses the 0.5 floor in four of five runs and so is not noise. Ari may judge that the clause is too strict for this case;
  the rule says otherwise and I applied it.
- **R4's two answers.** The recommendation of 2 rests on the unescalated group, one page (Turf Club) and a resample.
- **Icehouse is a burned page** and dominates the error counts in every table.

### Round 5 — Claude Sonnet 5.5, November 6, 2026 (Step 10: Ari's decision on the defaults, and applying it)

**Ari's decision (November 6, 2026, in the session, after reading Round 4):** "I accept your recommendation in terms of the default. Keep
threshold at 0.8, cap the retry to 2, and no escalation model." So: **confidence threshold 0.8 (kept; inert on the shipped model, C7-R2), attempt
cap 3 → 2 (C7-R4), no escalation model (C7-R3)**. His other remarks (C7-R1's sample, a second escalation candidate, a fourth attempt) were not
taken up: he said the next step for accuracy is to enhance extraction by navigating to each show's detail page, which "we already made notes
of". That is a separate piece of work (see the hand-off at the end), not part of C7. The DeepInfra spend after C7 was not given to me; it stays
open as Round 4 lists it.

**Scope.** Diff base `3355717` (Round 4's commit); the commit that carries this round is the one after it. Files touched:

- Code: `apps/api/agent_worker/policy.py` (`RetryPolicy.max_attempts` 3 → 2, the comments on all three fields and the module docstring say what C7
  found); `apps/api/agent_worker/model_eval/labeled_page_runs/run_labeled_pages.py` (one `--force-retries` help string).
- Tests: `tests/test_policy.py` (the default pinned, written first and watched failing), `tests/fakes.py` (a shared `THREE_ATTEMPTS`
  policy), `tests/test_graph.py`, `tests/test_graph_audit.py`, `tests/test_audit_queries.py`, `tests/model_eval/test_run_one_page.py` (nine tests
  that exercise the three-tier loop now ask for a cap of 3 explicitly).
- Docs (the Step 10 list): `docs/arch/arch-initial.md` §7 (a dated note with the numbers, and the cap text), `docs/dev/alpha-deployment-plan.md` C7
  (checkboxes ticked, a status line), `docs/dev/alpha-build-plan.md` A8 (its status line), `docs/dev/implementations/c5-pipeline-eval-harness.md`
  (C5-F4 and C5-F6 marked not built, C5-F14 marked built, each with where it went, C7-D8), `docs/dev/environments.md` (`ESCALATION_MODEL_NAME`:
  leave it unset), `docs/dev/evaluating-model-performance.md` (cap 2; step 6 now passes `MAX_ATTEMPTS=3`), `Makefile` (a comment).

**Departures and consequences, each named.**

1. **A cap of 2 makes tier 3 unreachable by default.** `plan_for_attempt` plans the larger-model tier only for `attempt >= 3`, so under the new
   default no escalation model is used even if `ESCALATION_MODEL_NAME` is set; `environments.md` and `policy.py` say so. Not a bug: it is what
   "no escalation model" and "cap 2" together mean, and a measurement run restores tier 3 with `--max-attempts 3`.
2. **The "last attempt" sentences are no longer sent in production.** `retry_hint(history, final=attempt >= 3)` adds "This is the last attempt…"
   to the page and splitter hints on attempt 3 and later, not on "the last attempt the cap allows". Under a cap of 2, attempt 2 is the last one
   but carries only the findings and the low-confidence advice. **I did not change this**: it would be a design change Ari did not decide, and
   C7 found no evidence the sentence helps (tier 2 did not help; tier 3 without a larger model hurt Turf Club). If a later milestone wants the
   sentence on whichever attempt is last, `final` should read `attempt >= policy.max_attempts`, with a test. For the code reviewer.
3. **Nine existing tests pinned the old default** and failed on the change (the three-tier loop through `compiled_graph`, the escalation row, the
   forced-retry tests). They were changed to ask for the cap they exercise (`fakes.THREE_ATTEMPTS`, and `build_policy(None, 3, …)` in the forced-retry
   tests) rather than rewritten, because they pin the machinery arch-initial.md §7 specifies, which a measurement run still uses. Their
   expected values did not change. One new assertion pins the default itself (`test_default_policy_matches_the_documented_numbers`), and its
   expected 2 comes from Ari's decision above, not from the code.
4. **Step 8's commands as written would now run two tiers, not three.** `build_policy` keeps the cap from `DEFAULT_POLICY`, so a forced run
   without `MAX_ATTEMPTS=3` stops after attempt 2. Round 4's runs happened before this change and are unaffected. `evaluating-model-performance.md`
   step 6, the Makefile comment and the `--force-retries` help string now say to pass `MAX_ATTEMPTS=3`.
5. **Not done.** No fourth-attempt run and no second escalation candidate (Round 4, Decisions for Ari, 3). No new labels (Round 4, 2). The
   DeepInfra dashboard spend is unread. The `policy.py` comments cite the pre-registered rules by their scoped IDs.

**Verification.**

- Test first: `test_default_policy_matches_the_documented_numbers` fails on `max_attempts == 3` before the change; green after.
- The full Python suite on the default change alone: 9 failed, 1515 passed; each of the nine named above; after making them explicit, 1524 passed.
- `make check`: exit 0 (ruff, mypy 158 files, pytest 1524, vitest 525, `contract-check`, `designation-check`, Playwright 107). `make designation-check
  BASE=8c90a38` is part of it.
- The doc test over `environments.md` (`app/tests/test_environments_doc.py`) passes with the edited note.

**Where to look hardest.**

- Departure 2: whether the last-attempt sentence should follow the cap. It is untested at cap 2 and I did not decide it.
- That the nine explicit-cap tests still prove what their comments say (they now pass `THREE_ATTEMPTS`; none of their expectations moved).
- `policy.py`'s comment on `max_attempts` states what C7 measured: check its numbers against Round 4 (100 default page-runs, no retry; attempt 3 hurt Turf Club).
- That nothing else reads `DEFAULT_POLICY.max_attempts` and assumes 3 (a `grep` for `max_attempts` found only `decide_route`, the harness's `build_policy`, the report header and tests).

### Round 6 — Claude Sonnet 5.5, November 6, 2026 (code review round 2's fixes)

**Scope.** `git diff b124c3a`: `policy.py`, `nodes.py`, `state.py`, `llm.py` (comments only), `tests/test_run_venue.py` and `tests/test_prompts.py` (comments only), `tests/test_graph.py` (one new test), `docs/arch/arch-initial.md`, `docs/dev/alpha-build-plan.md` and this plan.

**What changed, by finding.** C7-CR2-1, 3 and 5: comments and doc wording, checked as a comment-only pass (syntax trees without docstrings equal `b124c3a`'s for the six Python files). C7-CR2-2: the three "last attempt" comments are accurate, a test pins the shipped behavior, and the decision is Ari's. C7-CR2-4: `test_the_shipped_default_makes_two_attempts_then_escalates`, mutation-checked both ways.

**Verification.** `make check` exit 0 after the fixes (ruff, mypy, pytest 1525 passed, vitest 525, `contract-check`, `designation-check`, Playwright 107). Mutation checks on the new test: the default put back to 3 fails it, and `final=attempt >= policy.max_attempts` fails it; both reverted.

**Decided by Ari, November 6, 2026 (C7-CR2-2): keep as shipped.** The question was: should the last attempt the cap allows carry the "This is the last attempt…" sentences? Today attempt 2, the last under the shipped cap, does not. C7's evidence leans against sending it (tier 3 without a larger model, which carries it, hurt Turf Club), so I left it. To change it later: `final=attempt >= policy.max_attempts` in `plan_for_attempt`, and flip the second assertion of the new test. Nothing changed in code.

## Code review

### Round 1 — Claude Sonnet 5.5, November 6, 2026

**Scope:** the Implementation log's Round 1 (Steps 1 to 6): the working tree on branch `c7-pipeline-eval` against diff base `8c90a38` (`git diff 8c90a38`, 15 files, plus the untracked `policy_questions.py`, `test_policy_questions.py` and this plan). The three `TODO(Ari)` gaps (C7-K1, C7-K2, C7-K3) are open by design and are not findings.

**What was checked and how.** Read the plan in full (Context, D1 to D9, the readings, the test approach, the steps) and every changed file: `run_one_page.py` (`confidence_fields`, `staged_seconds`, `_spans`, the stager marks, `_count_calls_on`), `run_labeled_pages.py` (`build_policy`, the two flags, `_rescore_run`, `policy_report`), `validation_recall.py`, `aggregate_scores.py`, `markdown_report.py`, `policy_questions.py` in full, the tests, the Makefile and the four docs. Also read `run_eval.RunCounters`/`register_hooks` and `llm.py` to check Departure 1 (the graph's client is a different object from `run_eval`'s: CONFIRMED, `run_eval.py:99` builds its own pair).

- **`make lint` and `make typecheck`: exit 0** (CONFIRMED). `uv run pytest` excluding `test_policy_questions.py`: 1321 passed (CONFIRMED). `test_policy_questions.py`: 153 failed, 14 passed, and the failures are the gaps' tests only: 128 parametrized `test_sweep_mirror_agrees_with_combine` rows plus the `confidence_rows`, `sweep_*`, `transition_*`, `churn`, `rows_by_venue` and `retry_effect` tests that call a gap (CONFIRMED). No failure is for any other reason.
- **Gaps filled in a scratch copy** (a copy of `apps/api` in the session scratchpad, the four `Code:` blocks pasted in; no git worktree and no change to the repository): `agent_worker/tests/model_eval` passes, 371 tests (the one failure there is `test_layering` looking for `docs/dev/eval-baselines` relative to the copy, an artefact of the copy). CONFIRMED.
- **Mutation checks in that copy, each reverted:** M1 (field_missing counted wrong) 1 test fails; M2 (route filter removed) 2 fail; M3 (`<=`) 2 fail; M4 (stored reasons trusted) 1 fails; M5 (index in the key) 1 fails. CONFIRMED. M6 and M7 not re-run (the log reports them; `test_transition_is_a_multiset` and the escalation-flag test are the named catchers, and both read correctly).
- **The dry-run cross-check reproduced** in the copy: `--rescore c6-confirm-gated` and `c6-confirm-heldout`, then `--policy-report` over both. Output matches the log and F1 to F4: confidence 0.9 holds 142 rows with 2 wrong, 1.0 holds 352 rows with 98 wrong (all Icehouse), C7-R1 "not enough evidence", the excluded line shows 0.5 (6) and 0.8 (3) correct and 1.0 as 23 correct and 14 missed, "No page made a second attempt". CONFIRMED.
- `make designation-check BASE=8c90a38`: exit 0 (CONFIRMED). I did not run `make e2e` or the rest of `make check`; the changed code does not touch the web app.
- **Gaps:** K1 (population and wrong-kinds), K2 (`would_fail` and `sweep_cell`) and K3 (`transition`) are at the decisions that carry weight; the K2 split into two blocks is Departure 8 and is fine. Each block has key point, code and check, and each placeholder raises. The one thing a reader of the scaffold may trip on: `Counter` carries a `# noqa: F401` that the cleanup pass must drop (the log's cleanup note should say so; it says only to delete the `filled_gaps` fixture).

**Counts:** 0 blocker, 1 should-fix, 6 nit. **Verdict: proceed after fixes.** The harness changes are sound and well tested: the confidence population (`judged_indices` and `excluded_indices`) is recorded by the right function, the rescore reproduces the saved files, the flags keep the other policy fields, the pooled report refuses mismatched `labels_sha`, and the token hooks are attached to the client the nodes really use (Departure 1 is a correct catch). The one should-fix is in the pre-registered R3/R4 rule itself, which the code implements faithfully but which misfires on exactly the pages that dominate the sample; it is cheap to fix now and impossible to fix honestly after the numbers exist.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **The noise band is 0 for any page whose attempt 1 gives the same error count in every run, so a single run's difference at attempt 2 or 3 reads as "helps" or "hurts" on that page.** R3's rule is "mean at attempt k differs from attempt 1's mean by more than the page's noise band", and the band is the population SD of attempt 1's error counts across the page's runs (`noise_band`, `_effect`: `before - after > band`). Most pages in the sample are stable (Mortimers, 7th St Entry, Turf Club have 0 to 2 errors; the hosted model is also very repeatable on them: C6 Round 10 saw Turf Club's second act dropped in 1 run of 5). For a stable page the band is exactly 0.0, so the mean over 5 runs moving by 0.2 (one run differing by one error) crosses it. | CONFIRMED in the scratch copy with the real functions: five runs with attempt-1 counts `[1,1,1,1,1]` and attempt-2 counts `[1,1,1,1,0]` give `noise_band == {'turf.html': 0.0}` and `page_effects == {'turf.html': 'helps'}`; counts `[0]*5` against `[0,0,0,0,1]` give `'hurts'`. `policy_questions.py` `_effect` and `noise_band`; plan R3, R4, test row "noise band" (only exercises a band of 1.02). | A forced run is a resample (DeepInfra ignores `seed`), so one noisy run on a quiet page is expected. R3's tier-helps condition requires "hurts on none", so one such flip disqualifies a tier that fixed Icehouse and a second page; R4 recommends 2 when attempt 3 "hurts on a page and helps on none", which one flip on one quiet page can trigger. The rule that D5 pre-registers to stop the numbers choosing their reading would then be chosen by single-run flips on the quietest pages. | **Fixed** (the rule amended before any C7 run; Ari confirms at sign-off, D5). `policy_questions.MIN_EFFECT = 0.5`: `_effect` needs a move greater than `max(band, MIN_EFFECT)`, used by `page_effects` and `escalation_effects`. Test first: `test_a_quiet_page_needs_more_than_one_runs_flip_to_count` (one flip in five runs is "neither"; three errors over five runs counts). The plan's noise-band paragraph and R3 state the floor, with its reason. |
| 2 | nit | **`page_effects` compares attempt 1's mean over all runs with attempt `k`'s mean over only the runs that reached `k`.** `mean_errors(records, before)` and `mean_errors(records, after)` each average whatever runs have that attempt. In a forced run a model-route page whose attempt 1 keeps no show has confidence None (no evidence, A3-K4), passes, and never makes attempt 2; in a default-policy file the runs that retry are the worse ones. The two means then cover different runs. | PLAUSIBLE, from `page_effects`, `mean_errors` and A3-K4. The same-population comparison (attempt 1 over only the runs that also made attempt `k`) is a two-line change. | Selection bias in the direction of "helps" (the runs that retried were the worse ones at attempt 1), small on forced runs but real on the c7-defaults label if it is ever pooled into the retry section. | **Fixed.** `page_effects` takes both means over the runs that reached both attempts; the band stays attempt 1 over all runs. Test first: `test_an_attempt_is_compared_with_attempt_one_of_the_same_runs`. `escalation_effects` compares two different sets of runs, so nothing can be paired there (its docstring says so). |
| 3 | nit | **R1's "holds on at least two venues separately" applies the 10-row minimum per venue per value, which the plan does not say and which makes "yes" close to unreachable.** `r1_verdict` builds `buckets({v: rows}, min_size)` for each venue and needs two compared values in it. The plan's R1 states the minimum for "a bucket" and the venue clause separately. On the hosted model's coarse values (F2) a venue with two values of 10 or more rows each is rare (Turf Club is 0.9 or 1.0 at 17 and 68 in the saved files; Mortimers is one value). | PLAUSIBLE, from `r1_verdict` and plan R1. The saved files already give "not enough evidence" first, so no number changes today. | When R1 is read on new data the log could say "no" where the plan's wording allowed "yes" on a smaller per-venue bucket, or the reverse; the choice is not recorded. | **Fixed** (stated, code unchanged): R1 now says the 10-row minimum applies inside a venue too. That is the stricter reading, and with this sample R1 reads "not enough evidence" before the clause is reached (D9). |
| 4 | nit | **The sweep's table pools structured-route pages, which no threshold can ever catch.** `sweep` counts every page-run; a structured page with an error is `missed` at every threshold because its confidence is None. In the dry run the 21 gated "missed" at 0.8 are 20 Icehouse (confidence 1.0) and 1 other, so the effect is small today, but the table reads as "the threshold missed these" when for those pages there is no threshold to set. | PLAUSIBLE, from `sweep` and `would_fail` (None never fails). | The R2 numbers (caught against should-retry) are diluted by pages outside the question; comparing thresholds is unaffected. A line in the report or a route split would say which. | **Fixed.** `sweep` puts structured-route attempts on a `structured` line of their own, whatever their gating, and the report prints it with the reason; the gated table's intro says "model-judged runs". Test first: `test_the_sweep_puts_structured_route_pages_on_their_own_line`; the report test asserts the line. |
| 5 | nit | **Spelling.** New prose uses "labelled" in `policy_questions.py:187` (the `excluded_confidences` docstring) and `test_policy_questions.py:188`; the repo rule is "labeled" for new text. | CONFIRMED by `grep -n labelled` on the two files (identifiers such as `LabelledShow` and the scorer's `labelled=` keyword are existing names and stay). | Convention only (AGENTS.md "Spell it labeled"). | **Fixed.** "labeled" in the `excluded_confidences` docstring and the test comment. |
| 6 | nit | **The Makefile comment above `eval-graph` still lists the old options.** `Makefile` lines 98 to 100 name `THRESHOLD, MAX_ATTEMPTS, KEEP_DB=1`; the usage line below was updated to add `FORCE_RETRIES` and `ESCALATION_MODEL` but the comment was not. | CONFIRMED by reading `Makefile:97-102`. | A reader of the comment misses two options. | **Fixed.** The comment above `eval-graph` names `FORCE_RETRIES=1` and `ESCALATION_MODEL=<id>|none`, with what each does. |
| 7 | nit | **Two small honesty points in the log and the self-check.** (a) Verification 1 and C7-PR1-13 ask that the build list the red tests; the log gives the count (153) and the groups by gap, not the test names (the 128 mirror rows are one parametrized test). (b) `AttemptResult.recorded_confidence` is None both for "not recorded" and for "recorded as None" (the structured route), so `confidence_disagree` cannot flag a drift where production recorded None and the recompute gives a number. | (a) CONFIRMED by reading the log; the failing names are `test_sweep_mirror_agrees_with_combine` x128, `test_sweep_cells` x5, `test_each_wrong_kind_makes_its_show_wrong` x5, `test_structured_route_shows_give_no_rows` x2, and 13 single tests. (b) PLAUSIBLE, from `_attempt_result` and `_validation`. | (a) The plan's own check cannot be ticked from the log. (b) A narrow blind spot in a self-check; the structured route has no confidence to drift. | **Fixed.** (a) The Implementation log's Round 2 lists the red tests by name. (b) `confidence_disagree` now compares wherever the attempt carries a `recorded_confidence` key (every fresh C7 attempt, so a recorded None against a recomputed number counts) and skips only attempts without it (pre-C7 files, rescored). Test first: `test_a_confidence_recorded_as_none_is_still_compared`. |

Rejected: none (this is the reviewer's round; the Resolution column is the author's).

**Resolution (author, Claude Opus 5.5, November 6, 2026).** All seven fixed, none rejected; the details are in Implementation log Round 2.
Test suite after the fixes: `make check`'s `lint` and `typecheck` pass; `test` (`REQUIRE_DB=1 uv run pytest`) reports 154 failed, 1338 passed, every failure on
`NotImplementedError: TODO(Ari)` in `test_policy_questions.py`; `contract-check`, `designation-check BASE=8c90a38` and `e2e` (107 passed) pass when run on their own.
With the gaps filled in a scratch copy, `agent_worker/tests/model_eval` passes (376). Finding 1 changes a pre-registered reading (R3, and so R4), which
D5 makes Ari's: he confirms it at sign-off. No second review round was run; the fixes are small and each has its own test.

Rejected: none.

### Round 2 — Claude Opus 5.5, November 6, 2026

**Scope:** Implementation log Round 5 (Step 10, Ari's decision applied: `RetryPolicy.max_attempts` 3 → 2, threshold 0.8 kept, no escalation model). The diff is commit `b124c3a` against its parent `3355717` (`git diff 3355717 b124c3a`, 16 files: `policy.py`, one help string in `run_labeled_pages.py`, six test files, the Makefile comment, and the Step 10 docs). No `TODO(Ari)` gaps are in scope.

**What was checked and how.**

- Read the plan's readings (R1 to R4), Steps 9 and 10, Implementation log Rounds 4 and 5, and the whole diff. Read the code around it that the diff leaves alone: `policy.py` (`decide_route`, `retry_hint`, `_FINAL_*_ADVICE`, `plan_for_attempt`), `nodes.escalate_node`, `state.VenueGraphState`, `llm.py`, `app/config.py`, and every comment or doc outside the implementation plans that names the cap or tier 3 (`git grep` for "3 attempts", "3-attempt", "cap of 3", "tier 3", "third attempt" and similar).
- Checked the numbers in the `policy.py` comments and the `arch-initial.md` §7 note against Round 4: no retry in 100 default page-runs (45 saved plus 55 new), attempt 2 fixed 9 and introduced 8, attempt 3 without a larger model fixed 14 and introduced 22, the 31B fixed 94 and introduced 20, 7th St Entry regressed in 4 of 5 runs, 3.6x the seconds. All match (CONFIRMED by reading).
- **`make check` at `b124c3a`: exit 0** (ruff, mypy 158 files, pytest 1524 passed, vitest 525 passed, contract-check, designation-check, Playwright 107 passed). CONFIRMED.
- **`make designation-check BASE=3355717` and `BASE=8c90a38`: both exit 0.** CONFIRMED.
- **Experiments in a throwaway `git worktree` at `b124c3a`, removed afterwards** (`git worktree list` shows only the main tree; `git status` is clean apart from this round):
  - The explicit caps undone (`THREE_ATTEMPTS = DEFAULT_POLICY`, `RetryPolicy(escalation_model=...)` without `max_attempts=3`, `build_policy(None, None, ...)`): `agent_worker/tests` gives **9 failed**, 1225 passed. That is the count Round 5 reports, so the explicit caps are what keeps those tests on the three-tier path. CONFIRMED.
  - The default put back to 3 with the new test in place: exactly one failure, `test_policy.py::test_default_policy_matches_the_documented_numbers`. So the test pins the decision, as Round 5 says. CONFIRMED.
  - `plan_for_attempt` changed to `retry_hint(history, final=attempt >= policy.max_attempts)` (Round 5's Departure 2 alternative): **all 1234 pass.** Nothing in the suite pins what the shipped default sends on its last attempt. CONFIRMED (finding 2).
- The nine changed tests still prove what their `Proves:` comments say. Their expected values did not move, and each one now names the cap it runs under. `test_graph.run_graph`, `test_graph_audit.run_traced` and `test_run_one_page.run_scripted` now default to `THREE_ATTEMPTS`, so no graph-level test runs at the shipped cap (finding 4).

**Counts:** 0 blocker, 2 should-fix, 3 nit. **Verdict: proceed after fixes.** The change matches Ari's decision and stays inside Step 10. The default has a test that was written first. The tests that exercise the three-tier machinery ask for that machinery explicitly instead of being weakened, and the measurement docs tell a forced run to pass `MAX_ATTEMPTS=3`. Both should-fix rows are comments the cap change made false. One of them (finding 2) sits on a behavior question that Round 5 rightly left open and that Ari should see before sign-off.

| # | Sev | Finding | Evidence | What goes wrong | Resolution |
|---|---|---|---|---|---|
| 1 | should-fix | **Production comments still say the cap is 3.** `nodes.escalate_node`'s docstring says the node is reached when "validate_node's retry cap is exhausted (3 attempts, per the architecture doc)". `state.py`'s `attempt_count` comment says "Retries are capped at 3 per the architecture doc", and quotes the old arch sentence that the diff rewrote. Two tests outside the diff carry the same stale claim: `test_run_venue.py:240-241` ("under the default cap of 3 the same page would be tried three times") and, as A3-D7's reasoning, `llm.py:70-72` and `test_prompts.py:333` ("The graph's own 3-attempt cap multiplies it … 36 calls"; at a cap of 2 the ceiling is 2 x 12 = 24). `policy.decide_route` (line 202) and `state.py:99` still say A8 varies the cap, while the diff updated the module docstring to say C7. | CONFIRMED by `git grep` and reading: `nodes.py:400-401`, `state.py:86-89`, `state.py:99`, `policy.py:202`, `test_run_venue.py:240-241`, `llm.py:70-72`, `test_prompts.py:333`. Round 5's search covered the identifier `max_attempts` only, not prose. | A reader of the escalate node or the state comes away with the wrong cap, and the `test_run_venue` comment states a default that the code no longer has. The repo's comments are meant to be trusted (AGENTS.md, "Comments explain why"). Fix it as a comment-only pass: say "the policy's cap (2 since C7-R4)" where it is current fact, and mark A3-D7's arithmetic as of A3 (or redo it for 2). |  **Fixed**, comment-only: `nodes.escalate_node`'s docstring and `state.py`'s `attempt_count` and `policy` comments name the policy's cap (2 since C7-R4, 3 before) and C7 as the one who varies it; `policy.decide_route`'s comment says a measurement run (C7) varies the cap; `llm.py`'s and `test_prompts.py`'s A3-D7 arithmetic is marked as of the time (3), with the ceiling now 2 x 12 = 24; `test_run_venue.py`'s comment says the default cap is 2 and would count two attempts. Checked as a comment-only pass: the syntax trees, with docstrings removed, equal `HEAD`'s for all six files. |
| 2 | should-fix | **The "last attempt" comments are now false at the shipped cap, and that behavior has no test.** `retry_hint`'s docstring says "`final` marks the last attempt". The `_FINAL_*_ADVICE` block says "What the last attempt adds", and `plan_for_attempt` says "The last attempt adds a sentence of its own, so it differs from attempt 2". Under `DEFAULT_POLICY` the last attempt is now attempt 2, and it never carries the sentence. The sentence goes only to attempt 3 or later, which the default never reaches (Round 5, Departure 2, which states this correctly and leaves the behavior alone). No test pins either reading: switching to `final=attempt >= policy.max_attempts` keeps all 1234 worker tests green. **Whether the last attempt the cap allows should carry the sentence is Ari's decision** (it changes what production sends). C7 gives weak evidence against sending it: tier 3 without a larger model, which carries it, hurt Turf Club (C7-R3). | CONFIRMED: `policy.py:232`, `:246`, `:311`, `:317`. Mutation experiment in the worktree (above). | The comments describe a guarantee ("the last attempt differs because of this sentence") that production no longer gets. A later change to the cap, or to `final`, has no test to fail either way, so a future reader cannot tell which behavior is meant. Fix: reword the three comments to "attempt 3 and later (the last attempt under a cap of 3)", put the question to Ari, and add a test that pins whichever answer he gives, for example that attempt 2's hints under `DEFAULT_POLICY` do not contain "This is the last attempt". |  **Fixed in part; the decision is Ari's and still open.** The three comments (`_FINAL_*_ADVICE` block, `retry_hint`'s docstring, `plan_for_attempt`) now say the sentence goes to attempt 3 and later, which is the last attempt only under a cap of 3, and cite this finding. Behavior unchanged. A graph-level test pins what ships today (`test_graph.py::test_the_shipped_default_makes_two_attempts_then_escalates`: attempt 2 does not contain "This is the last attempt"); mutation-checked both ways (cap back to 3: fails; `final=attempt >= policy.max_attempts`: fails). If Ari wants the sentence on the cap's last attempt, the change is `final=attempt >= policy.max_attempts` plus flipping that assertion. |
| 3 | nit | **"Attempt 3 only adds the final-attempt sentence and a resample" generalizes from the forced runs.** `retry_hint` builds the hint from every earlier attempt's reasons and findings, so in production attempt 3 also carries whatever new finding attempt 2 failed on. The claim holds only when both earlier attempts failed for the same reason, as every forced attempt did (low confidence). The `policy.py` `max_attempts` comment and the `arch-initial.md` §7 note both state it unqualified. | CONFIRMED by reading `policy.py:260-269` (the loop over `history`) against `policy.py:72-73` and `arch-initial.md:181`. | It overstates what C7 measured, which the plan's Context bullet (C7-PR1-11) takes care to scope. Add "in the forced runs" (or "when attempt 2 failed for the same reason") in both places. |  **Fixed.** `policy.py`'s `max_attempts` comment and `arch-initial.md` §7's note say "in the forced runs" and add that in production attempt 3 also carries the findings attempt 2 failed on. |
| 4 | nit | **No graph-level test runs at the shipped cap.** The helpers that drive the graph (`test_graph.run_graph`, `test_graph_audit.run_traced`, `test_run_one_page.run_scripted`) now default to `THREE_ATTEMPTS`. The shipped default is covered only in pieces: the value is pinned (`test_default_policy_matches_the_documented_numbers`), `decide_route` is tested at a cap of 3 (`test_policy.POLICY`), and `run_venue` honors a passed cap of 1 (`test_run_venue`). Nothing runs `DEFAULT_POLICY` through `compiled_graph` and sees attempt 1 "initial", attempt 2 "narrowed", then escalation. | CONFIRMED by reading the three helpers in the diff and `test_run_venue.py:234-256`. | Low risk, since the pieces compose. But the one configuration production runs is the one no end-to-end test exercises, and finding 2's test would fit naturally there. One test (`run_graph(..., policy=DEFAULT_POLICY)` with a splitter that always drops a show: two attempts, tiers `["initial", "narrowed"]`, escalated) closes it. |  **Fixed.** The new test above runs `DEFAULT_POLICY` through `compiled_graph`: two attempts, tiers `["initial", "narrowed"]`, escalated. |
| 5 | nit | **Small doc wording.** (a) `arch-initial.md` §7 line 177 still says each attempt "escalates in approach … (adjusted prompt, then a larger model)", unqualified. Under the shipped defaults only the adjusted prompt runs. The note below it explains this, but the sentence a reader meets first does not. (b) `alpha-build-plan.md` A8's line is headed "**Status (November 4, 2026):**" and now carries a November 6 fact inside it. A separate dated line would keep the shared doc append-only (AGENTS.md, "Parallel tracks"). (c) `policy.py:69-70`: "no default run of 100 page-runs ever retried" reads as if a run held 100 page-runs; "none of 100 default page-runs retried" says it plainly. | CONFIRMED by reading the three lines. | Minor misreadings only. |  **Fixed.** (a) `arch-initial.md` §7 line 177 now says only the adjusted prompt runs under the shipped C7 defaults; (b) `alpha-build-plan.md` A8 keeps the November 4 line as it was and gains a separate November 6 line; (c) `policy.py` reads "none of 100 default page-runs retried". |

Rejected: none (this is the reviewer's round; the Resolution column is the author's). Finding 2 carries a decision that is Ari's: whether the last attempt the cap allows should get the final-attempt sentence.

**Resolution (author, Claude Sonnet 5.5, November 6, 2026).** All five fixed, none rejected; finding 2's behavior question stays open for Ari and is the one thing to answer at sign-off. Details in Implementation log Round 6. `make check` after the fixes: see Round 6.

Rejected: none.
