"""Measuring a model: does the extraction process work with a given model? Nothing in this package runs when the agents fetch venues.

What this is: the code behind `make eval-graph` and its siblings, and the older extraction-only tool (`run_eval.py`). A scheduled
fetch never imports it (`tests/model_eval/test_layering.py` enforces that); it is run by a person, on a machine with the model, when
choosing or comparing models and after changing a prompt, a check or the retry policy.

How to read the folder:
- This level holds what the tools share: `labels.py` (the hand-written answer key), `scoring.py` (how one page is counted),
  `validation_recall.py` (which errors validation caught), `capture.py` and `label_draft.py` (saving a venue page and writing its
  label), `captured_pages/` (the saved venue pages, gitignored), `results/` (raw run output, gitignored), and the older
  extraction-only tool (`run_eval.py`, `legacy.py`, `reference.py`).
- `labelled_page_runs/` runs the real extraction pipeline on the labelled pages against a scratch database. Needs the model and Postgres.
- `saved_run_reports/` reads what a run saved: totals, a Markdown report, a comparison, a committable snapshot. Needs only a file.

docs/dev/evaluating-model-performance.md says when to run it and how to read it. docs/dev/implementations/c5.1-model-eval-layout.md
says why the folders are named this way (C5.1-D1 to C5.1-D3).
"""
