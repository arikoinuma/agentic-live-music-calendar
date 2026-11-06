"""Tests that the folders of `agent_worker/model_eval/` mean what their names say (C5.1-D6), and that the paths they compute still resolve.

Milestone C5.1 (docs/dev/implementations/c5.1-model-eval-layout.md). The model evaluation lives inside `agent_worker/` but must stay
apart from the code that runs on every scheduled fetch, and its two halves must stay apart from each other: `saved_run_reports/` only
reads saved results, so it must work without the model or the database that `labeled_page_runs/` needs. Both rules are checked by
reading the imports of every source file with `ast` (the way `app/tests/test_no_testing_imports.py` does), so a violation fails here
instead of surfacing as a missing dependency on a machine that has neither.

How to read it: `imported_modules` lists what a file imports; one test per rule; then the path constants, because moving a module one
folder deeper silently breaks any `Path(__file__).parents[n]` it computes.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

from agent_worker.model_eval import capture, run_eval
from agent_worker.model_eval.labeled_page_runs import scratch_database
from agent_worker.model_eval.saved_run_reports import results_file

API_DIR = Path(__file__).resolve().parents[3]
WORKER_DIR = API_DIR / "agent_worker"
MODEL_EVAL_DIR = WORKER_DIR / "model_eval"


def imported_modules(path: Path) -> set[str]:
    """Every module a source file imports, as absolute dotted names (`from a.b import c` counts `a.b` and `a.b.c`, so a submodule
    import is seen). A relative import (`from ..x import y`) is resolved against the file's own package, so it cannot hide a
    dependency from the rules below."""
    package = list(path.relative_to(API_DIR).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            if module:
                found.add(module)
                found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def test_nothing_that_runs_on_a_scheduled_fetch_imports_the_model_evaluation() -> None:
    # Proves: C5.1-D6, the rule Ari asked the folder layout to make visible. The pipeline and the API are the code that runs when the
    # agents fetch venues; the evaluation measures them from outside and is run by a person. If production code imported it, a
    # production deploy would need the labels and the scratch database tooling, and "what runs every time" would stop being answerable
    # from the folder. The tests and the evaluation itself are excluded (they are allowed to).
    offenders = []
    for root in (API_DIR / "app", WORKER_DIR):
        for path in root.rglob("*.py"):
            if (
                MODEL_EVAL_DIR in path.parents
                or "tests" in path.relative_to(API_DIR).parts
                or path.name == "local_test.py"
            ):
                continue
            if any(
                m == "agent_worker.model_eval" or m.startswith("agent_worker.model_eval.")
                for m in imported_modules(path)
            ):
                offenders.append(str(path.relative_to(API_DIR)))
    assert offenders == []


def test_saved_run_reports_never_import_labeled_page_runs() -> None:
    # Proves: C5.1-D6. `saved_run_reports/` is the half that needs only a saved file, so it must run on a machine with no model and
    # no database (a reviewer's laptop reading a committed snapshot). Importing `labeled_page_runs` would drag in the graph, the
    # database driver and the scratch database code. The other direction is allowed: a run prints its summary with the reports.
    reports = MODEL_EVAL_DIR / "saved_run_reports"
    sources = sorted(reports.glob("*.py"))
    assert sources, "no report modules found; the folder moved?"
    offenders = [
        f"{p.name} imports {m}"
        for p in sources
        for m in imported_modules(p)
        if m == "agent_worker.model_eval.labeled_page_runs"
        or m.startswith("agent_worker.model_eval.labeled_page_runs.")
    ]
    assert offenders == []


def test_importing_the_reports_loads_nothing_from_labeled_page_runs() -> None:
    # Proves: C5.1-D6 in the form that matters, "a report reads on a machine with no model or database". The check above sees only a
    # report module's OWN imports; a shared module (`run_eval`, `labels`, `scoring`, `legacy`) that a report imports could pull the
    # runners in one hop away and that check would still pass. A fresh interpreter imports the three report modules and lists what
    # got loaded, so the whole chain is judged. Expected: no `labeled_page_runs` module in `sys.modules`.
    code = (
        "import sys\n"
        "import agent_worker.model_eval.saved_run_reports.aggregate_scores\n"
        "import agent_worker.model_eval.saved_run_reports.results_file\n"
        "import agent_worker.model_eval.saved_run_reports.markdown_report\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('agent_worker.model_eval.labeled_page_runs'))))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        cwd=API_DIR,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(API_DIR)},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "", f"importing a report loaded the runners: {done.stdout.split()}"


def test_the_paths_computed_from_a_modules_own_location_still_resolve() -> None:
    # Proves: the move one folder deeper did not break the paths built from `__file__`. Each assertion names the thing the path must
    # reach: the committed baselines folder (the snapshots live there and `--snapshot` writes there), the API directory (the scratch
    # database migrations are found from it), and the two gitignored data folders beside the shared modules.
    assert results_file.SNAPSHOT_DIR.is_dir() and results_file.SNAPSHOT_DIR.name == "eval-baselines"
    assert (scratch_database.API_DIR / "pyproject.toml").is_file()
    assert run_eval.RESULTS_DIR == MODEL_EVAL_DIR / "results"
    assert run_eval.CAPTURED_PAGES_DIR == MODEL_EVAL_DIR / "captured_pages" == capture.CAPTURED_PAGES_DIR
