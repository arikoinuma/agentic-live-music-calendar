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
| 6 | **Retry loop (optional)** | `make eval-graph LABEL=<m>-retry THRESHOLD=0.99` | ~60 min (local) | The report's Retried pages table: do later attempts have fewer errors than the first? |
| 7 | **Compare** | `make eval-compare LABELS="<old> <new>"` | seconds | The same rows for both: recall, precision, gate, retry rate, validation recall. |
| 8 | **Record** | `make eval-report LABEL=<m>-baseline OUT=<m>-baseline.md ERRORS=1` for each label that matters | seconds | Paste the report into the milestone's Implementation log (the results files are gitignored), with the model and digest. |

`make eval-graph` also takes `SET=gated|informational|held_out|all`, `ONLY=<text>`, `RUNS=<n>`, `THRESHOLD=<x>`, `MAX_ATTEMPTS=<n>` and `KEEP_DB=1`; `make help` lists them. `OUT` is relative to `apps/api`.

**Held-out pages** (`held_out=True` in `labels.py`) are scored once, in C6, after the changes are frozen: `SET=held_out`. They are the only honest test of generalization, so they are not part of any routine run, and nobody should read their results before then.

## How to read a report

| Section | The question it answers | Watch for |
|---|---|---|
| **Header** | What produced these numbers? | A different `labels_sha`, model or policy than the run you are comparing with. |
| **Headline** | Raw (the model), validated (what reconcile receives), committed (the rows in the database): where does accuracy move? | Raw, validated and committed equal means nothing downstream helps or hurts. Committed lower than validated means escalated runs, which commit nothing. |
| **The retry loop** | Did it fire, and did it help? | `errors first attempt` equal to `final attempt` means the retries changed nothing on net. |
| **Validation recall** | Of the model's errors, how many did a check notice? | `silent` is the dangerous column: nothing noticed. Flagged means only a warning, which never changes the verdict. Read the note under it when pages were retried. |
| **Pages** | Which pages carry the errors? | Counts are missed/wrong acts/invented/leaks. Gated pages (G) decide the gate; informational ones (i) never do. |
| **Retried pages** | What did each attempt do? | A later attempt with more errors than the first, or a correct page escalated. |
| **Scenarios** | What does the database hold after two runs? | `invented` above 0; a removal that should not have happened. |
| **Gate failures** | Which gated pages break Ari's standard? | The standard allows no wrong acts, no invented shows, and no missed shows on gated pages (A2.1-D1). |

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
