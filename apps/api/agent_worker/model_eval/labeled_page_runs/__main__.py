"""`python -m agent_worker.model_eval.labeled_page_runs ...`: the command line of the labelled-page runs.

What this is: the entry point `make eval-graph`, `eval-report`, `eval-compare` and `eval-snapshot` call. The code is in
`run_labeled_pages.py` (`main` parses the flags and dispatches to a run, a rescore, a report, a comparison or a snapshot); this file
only lets the package itself be run, so the command names the folder and not one of its modules.

docs/dev/implementations/c5.1-model-eval-layout.md (C5.1-D2).
"""

import sys

from agent_worker.model_eval.labeled_page_runs.run_labeled_pages import main

if __name__ == "__main__":
    sys.exit(main())
