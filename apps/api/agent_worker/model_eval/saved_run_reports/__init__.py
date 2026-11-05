"""Read what a run saved: totals, a Markdown report, a side-by-side comparison, a committable snapshot.

What this is: the half of `model_eval` that only READS. Everything here works on a saved results file (or a committed snapshot), so it
needs no model, database or captured pages, and runs on any machine.

How to read it: `aggregate_scores.py` (the numbers computed from the run records), `results_file.py` (the file's shape, where it lives,
loading it, and the slim snapshot), `markdown_report.py` (the report, the comparison table and the closing summary).

It never imports `labelled_page_runs` (`tests/model_eval/test_layering.py` enforces that).
"""
