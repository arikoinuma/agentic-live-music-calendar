"""Run the real extraction pipeline on hand-labelled venue pages, and score what comes out.

What this is: the half of `model_eval` that DOES things. It drives `main.run_venue` (the same cycle the scheduled worker runs) against
a scratch Postgres database, `calendar_eval`, once per page or per two-run scenario, and scores the model's raw answer, the validated
extraction and the rows left in the database against the labels. Needs the model, Postgres and the captured pages, so it is local
only and not part of `make check`.

How to read it: `run_one_page.py` (one page through the graph), `two_run_scenarios.py` (repeat, sequence, overlap, perturbed and what
the database should hold after them), `scratch_database.py` and `scratch_calendar_rows.py` (the throwaway database and its rows),
`run_labeled_pages.py` (the runners and the command line; `__main__.py` lets `python -m` name this folder).

It may use `saved_run_reports`; that folder never imports this one.
"""
