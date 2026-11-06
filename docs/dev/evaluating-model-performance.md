# Evaluating model performance: the sequence of checks

How to measure the pipeline with the C5 harness, in an order that gives the same answers for the local model today and for the hosted model in C6 and C7. The tools are `make eval-graph` (run), `make eval-report` (read one run), `make eval-compare` (line runs up), all on a machine with the labelled fixtures (a laptop; the cloud has none). Design and findings: `docs/dev/implementations/c5-pipeline-eval-harness.md`. How the labels get made: `docs/dev/adding-eval-venues.md`.

**The point of a fixed sequence** is comparison. A number only means something against another number measured the same way, so the sequence changes the *model* and keeps everything else still.

## When to run it

| Situation | Run |
|---|---|
| A new or different model (a hosted provider, a larger splitter model, C6) | The whole sequence, as a new label. |
| A prompt, validation or retry-policy change | Steps 1 to 4 and 6; compare with the last label. |
| New labelled pages | Step 2 over the new pages; remember their results are not comparable with earlier labels (`labels_sha` differs). |
| Checking that nothing broke | Step 1 (the smoke test). |

## What stays fixed, so runs are comparable

- **The labels.** Every results file records `labels_sha`. Two runs with different values were scored against different labels, and `eval-compare` prints it so that shows. Change labels deliberately, and say so in the log.
- **The pages.** Use the same `SET`. `all` is the gated and informational pages and never includes held-out ones.
- **The policy.** Use the pipeline's defaults (confidence threshold 0.8, cap 3) except in the step that varies it on purpose (step 6).
- **One run at a time.** The harness drops and recreates its scratch database `calendar_eval` at the start. A second run started meanwhile wipes the first one's.
- **The model's identity.** Note the model and its digest (they are in the results file's `provenance` block for a local model). A hosted run needs its provider, model name and version written down by hand until C6 records them.

## The sequence

Run from the repo root. Times are from the first local baseline (November 4, 2026); a different model or machine will differ.

| # | Step | Command | Time | Read |
|---|---|---|---|---|
| 0 | **Prepare** | `git pull`, `make check`; start Postgres (`make db-up`) and the model server (Ollama, or the hosted key in `.env`) | minutes | `make check` green. Note the model and, for Ollama, the digest. |
| 1 | **Smoke test** | `make eval-graph LABEL=<m>-smoke ONLY=white_squirrel-2026-10-10` | ~2 min | It completes, and the report's header shows the model you meant. The seconds are your timing estimate. |
| 2 | **Main run** | `make eval-graph LABEL=<m>-baseline SET=all` | ~30 min (local) | `make eval-report LABEL=<m>-baseline`: headline, pages, validation recall. |
| 3 | **Sequence scenarios** | `make eval-graph LABEL=<m>-seq SCENARIO=sequence` | ~10 min | Report's Scenarios section: the rows left against what a perfect pipeline would leave. `invented 0` means the soft-delete window held. |
| 4 | **Perturbed scenario** | `make eval-graph LABEL=<m>-perturbed ONLY=white_squirrel-2026-10-10 SCENARIO=perturbed` | ~3 min | Update 1, remove 1, insert at least 1. A line saying the extraction changed between runs is the model's, not reconcile's. |
| 5 | **Repeatability** | `make eval-graph LABEL=<m>-repeat ONLY=white_squirrel-2026-10-10 RUNS=3`, and the same for one model-route page (`ONLY=mortimers`) | ~5 to 20 min | The report's Repeatability lines: identical, or DIFFERENT. Differences mean a single run is a weak sample. |
| 6 | **Forced retries (optional)** | `make eval-graph LABEL=<m>-forced SET=all RUNS=5 FORCE_RETRIES=1 ESCALATION_MODEL=none`, then again with `ESCALATION_MODEL=<a larger model's id>` | ~1.5 h (hosted) | `FORCE_RETRIES=1` fails every model-judged attempt for low confidence (threshold 1.01, above any confidence the schema allows), so every model-route page runs all three tiers and "What each retry changed" can say what each tier did against the run-to-run noise (C7-D3). `ESCALATION_MODEL=none` clears any `ESCALATION_MODEL_NAME` the environment sets; check the header says which. Structured pages have no confidence and pass attempt 1. The old way, `THRESHOLD=0.99`, fires on almost nothing on the hosted model (C7-F2). |
| 7 | **Policy questions** | `make eval-policy LABELS="<label> <label>" OUT=<m>-policy.md` | seconds | C7's three tables over the labels read together: confidence against correctness, the threshold sweep, and what each retry changed, each with its pre-registered reading (C7-R1 to C7-R4). Refused when the labels' `labels_sha` differ. Pass the unescalated and escalated forced labels together to compare the escalation model with none. |
| 8 | **Compare** | `make eval-compare LABELS="<old> <new>"` | seconds | The same rows for both: recall, precision, gate, retry rate, validation recall. |
| 9 | **Record** | `make eval-report LABEL=<m>-baseline OUT=<m>-baseline.md ERRORS=1` for each label that matters, and `make eval-snapshot LABEL=<m>-baseline` | seconds | Paste the report into the milestone's Implementation log, with the model and digest, and commit the snapshot (below). |

**Snapshots.** The raw results files are gitignored (they hold the venues' page text and every extraction, and a hosted run's request options must never reach git). `make eval-snapshot` writes a slim summary to `docs/dev/eval-baselines/<label>.json` that is safe to commit: scores, aggregate, scenarios, model, policy and the prompt's hashes, without extractions or page text. `eval-report` and `eval-compare` fall back to it when the raw file is gone, so a baseline survives a new laptop. Commit one for a run that matters and name it in the milestone's log. `--rescore` needs the raw file.

`make eval-graph` also takes `SET=gated|informational|held_out|all`, `ONLY=<text>`, `RUNS=<n>`, `THRESHOLD=<x>`, `MAX_ATTEMPTS=<n>`, `FORCE_RETRIES=1` (not with `THRESHOLD`), `ESCALATION_MODEL=<id>|none` and `KEEP_DB=1`; `make help` lists them. `OUT` is relative to `apps/api`.

**A file from before C7** has no per-attempt confidences, seconds or tokens, so its report says to rescore it instead of printing the policy tables. `--rescore <label>` fills the confidences and the seconds of attempts 2 onward from the stored documents (no model call); tokens cannot be recovered.

**Held-out pages** (`held_out=True` in `labels.py`) are scored once, in C6, after the changes are frozen: `SET=held_out`. They are the only honest test of generalization, so they are not part of any routine run, and nobody should read their results before then.

## How to read a report

| Section | The question it answers | Watch for |
|---|---|---|
| **Header** | What produced these numbers? | A different `labels_sha`, model, policy or prompt sha than the run you are comparing with. |
| **Headline** | Raw (the model), validated (what reconcile receives), committed (the rows in the database): where does accuracy move? | Raw, validated and committed equal means nothing downstream helps or hurts. Committed lower than validated means escalated runs, which commit nothing. |
| **The retry loop** | Did it fire, and did it help? | `errors first attempt` equal to `final attempt` means the retries changed nothing on net. |
| **Validation recall** | Of the model's errors, how many did a check notice? | `silent` is the dangerous column: nothing noticed. Flagged means only a warning, which never changes the verdict. Read the note under it when pages were retried. |
| **Field accuracy** | Are start times, end times, prices and the rest within the standard? | `WRONG` (never allowed) or `over 10% missing`. |
| **Pages** | Which pages carry the errors? | Counts are missed/wrong acts/invented/leaks. Gated pages (G) decide the gate; informational ones (i) never do. |
| **Retried pages** | What did each attempt do? | A later attempt with more errors than the first, or a correct page escalated. |
| **Scenarios** | What does the database hold after two runs? | `invented` above 0; a removal that should not have happened. |
| **Gate failures** | Which gated pages break Ari's standard? | The standard allows no wrong acts, no invented shows, and no missed shows on gated pages (A2.1-D1). |
| **Confidence and correctness** (C7-Q4) | Is a show the model is less sure of more often wrong? | Rows are attempt 1's kept, model-judged shows only; a bucket under 10 rows is shown but not compared; the reading is C7-R1's. The excluded shows' line is where low values usually go: they never reach the record's confidence. |
| **Threshold sweep** (C7-Q1) | What would each threshold have done to attempt 1? | `missed` = a page that failed the standard and would not have retried; `false alarm` = a correct page sent to a retry (and, at the cap, to escalation, which commits nothing). |
| **What each retry changed** (C7-Q3, C7-Q2) | Did each tier fix more than a resample would? | A page's mean errors must move by more than its noise band (the SD of attempt 1's errors across runs); a tier helps only on two pages and hurting none (C7-R3). A forced attempt 2 sends the splitter the same request, so this measures a generic hint plus a resample. |
| **Validation recall: stopped** | How many errors sat on an attempt that failed for any reason? | In a forced run every model-judged attempt fails for low confidence, which is no finding, so `silent` alone would swallow everything (C7-D8). |

## Pitfalls that have already cost time

- **A scenario run's closing summary lines** (recall, precision, gate) mix its two runs and mean little. Use the report's Scenarios section.
- **The informational pages are weak by design** (Terminal Bar, Zhora, the posters). The overall recall includes them, so it is not comparable with A2.1's gated 56 of 60. Compare gated pages with gated pages.
- **Temperature 0 does not make the model repeatable.** One run of a page can pass or fail by chance. For anything that will be quoted as a result, run step 5 or use several runs.
- **A line copied from a very long terminal line can lose a space.** Write the report to a file (`OUT=`) instead of copying it from the terminal.
- **Confidence is not correctness.** The threshold run rejected a page with no errors and accepted pages with several. Do not tune the threshold from one run (C7 owns that question).

## For a hosted model (C6)

Run steps 0 to 5 with the same labels, set and policy, then compare against the local labels with step 7. What does not carry over yet: `provenance` is recorded for Ollama only (write the provider, model and version in the log by hand until C6 records them), and cost per page is not recorded (tokens in and out should be noted from the provider's dashboard). Duration per page is recorded and is the number to compare.

## Checklist

- [ ] `make check` is green and the labels are the ones you mean to score against.
- [ ] Only one harness run is going.
- [ ] Smoke test passed; the report header shows the right model.
- [ ] Main run, scenarios and repeatability done, each with its own label.
- [ ] Reports written to files and pasted into the milestone log, with the model, its digest and `labels_sha`.
- [ ] Held-out pages untouched unless this is the C6 scoring.
