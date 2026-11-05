# model_eval: measuring a model

**Nothing in this folder runs when the agents fetch venues.** It is run by a person, on a machine with the model, to answer one question: *does our extraction process work with this model?* Use it when choosing or comparing models, and after changing a prompt, a check or the retry policy.

A test enforces the boundary: `tests/model_eval/test_layering.py` fails if any production module (`app/` or `agent_worker/`, outside this folder and the tests) imports `model_eval`.

## Where the checks that DO run every time live

They are not here. They live at the root of `agent_worker/`:

| Module | What it does on every scheduled fetch |
|---|---|
| `validation.py` | Plausibility checks on what the model returned (blank act, implausible date, a free show with a price, and the rest). Decides nothing. |
| `policy.py` | Turns the checks into a verdict (passed, confirmed empty, failed) and decides retry, change of approach, or escalate. |
| `reconcile.py`, `commit.py` | What changes in the calendar, the guard that holds back a mass removal, and the writes. |
| `trace.py`, `audit.py` | The audit trail of every step. |

Those checks can only judge whether output *looks* right; they have no answer key. This folder has one (`labels.py`), so it can say how often the output is *actually* right, and how often the every-run checks notice when it is not. (The first baseline found they noticed 0 of 24 errors: `docs/dev/implementations/c5-pipeline-eval-harness.md`.) Surfacing the every-run signals to a person is a deferred decision: `docs/arch/arch-initial.md` §11, "Production run-health monitoring".

## What is in the folder

| Where | Group | What it is | Needs |
|---|---|---|---|
| `labels.py` | answer key | Hand-written ground truth: for each captured page, which shows it lists and who the acts are, and which entries are not shows. Pages flagged `held_out` are in no default set; their first scoring is C6's. | nothing |
| `scoring.py` | answer key | How one page is counted against its label, and Ari's tiered accuracy standard. | nothing |
| `validation_recall.py` | answer key | Which of the model's errors a validation check noticed (caught, flagged, silent). | nothing |
| `capture.py` | answer key | Saves a venue's calendar page into `captured_pages/`, exactly as the pipeline fetches it. | network |
| `label_draft.py` | answer key | Lists a captured page's visible lines, numbered, to help write a label by hand. Decides nothing. | nothing |
| `captured_pages/` | data (gitignored) | The saved venue pages. | |
| `results/` | data (gitignored) | Raw output of runs. Holds page text, so it is never committed. | |
| **`labeled_page_runs/`** | **runs** | Runs the real extraction pipeline on the labeled pages against a scratch Postgres database, and scores the model's answer, what validation passed on, and the rows left behind. | the model, Postgres, `captured_pages/` |
| **`saved_run_reports/`** | **reads** | Turns a saved run into totals, a Markdown report, a side-by-side comparison, or a committable snapshot. | only a saved file |
| `run_eval.py`, `legacy.py`, `reference.py` | older tool | The earlier extraction-level tool: it asks only whether the model can *read a page* (no validation, no database). Left as it was. `legacy.py` is the frozen pre-A2 schema and prompt, `reference.py` a few hand-written facts per page. | the model |

`labeled_page_runs/` has the files `run_one_page.py` (one page through the graph), `two_run_scenarios.py` (run twice and check the database: repeat, sequence, overlap, perturbed), `scratch_database.py` and `scratch_calendar_rows.py` (the throwaway database `calendar_eval` and its rows), and `run_labeled_pages.py` (the runners, `--rescore` and the command line). `saved_run_reports/` has `aggregate_scores.py`, `results_file.py` and `markdown_report.py`.

## Running it

From the repo root (the Makefile targets keep their names):

```
make eval-graph LABEL=<name> SET=all        # run (about 30 minutes on the local model)
make eval-report LABEL=<name>               # read one run
make eval-compare LABELS="<old> <new>"      # line two runs up
make eval-snapshot LABEL=<name>             # write a slim summary you can commit
```

The order to run things in, and how to read a report, is `docs/dev/evaluating-model-performance.md`. Adding a venue or a new capture to the labeled pool is `docs/dev/adding-eval-venues.md`.

## Rules and things that bite

- **`saved_run_reports/` never imports `labeled_page_runs/`** (a test enforces it), so a report reads on any machine, including one with no model or database.
- **`labels_sha` is a hash of the whole of `labels.py`**, comments included, and every results file and committed baseline records it. Editing that file, even a comment, makes the next run look incomparable with the baselines. See `docs/dev/notes.md`.
- **Two stored names are older than this layout**: the key `"fixture"` in results files and the committed baselines (it names a captured page), and `"labelled"` (the count of labeled shows). They stay, so old files still load. The spelling follow-up is deferred: `docs/arch/arch-initial.md` §11.
- **One run at a time.** A run drops and recreates `calendar_eval`; a second run started meanwhile wipes the first one's.
- **Held-out pages are untouched** until C6 scores them once, after its changes are frozen.

## Where the reasoning is

`docs/dev/implementations/c5-pipeline-eval-harness.md` (what the harness measures and what the first baseline found) and `docs/dev/implementations/c5.1-model-eval-layout.md` (why the folders are laid out this way, with the old-to-new name table).
