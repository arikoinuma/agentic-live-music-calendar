"""Production code never imports the test helpers, the sample world included (C2-M7).

No database. After C2 the routes read Postgres, but every route test runs on the sample world, so a route
that quietly fell back to `app.testing.sample_data` would pass them all. This test is what stops that: it
parses the production modules and fails on any import of `app.testing`.
"""

import ast
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]

# Production code = everything under these two packages except the test and harness parts named below.
# `agent_worker/local_test.py` is a manual script for a human (apps/api/AGENTS.md), and the worker's
# `tests/` hold tests. Skipping a directory is by name, so a new production module is checked by default.
PACKAGES = ("app", "agent_worker")
NOT_PRODUCTION_DIRS = {"tests", "testing", "__pycache__"}
NOT_PRODUCTION_FILES = {"local_test.py"}


def _production_modules() -> list[Path]:
    found = []
    for package in PACKAGES:
        for path in (API_DIR / package).rglob("*.py"):
            relative = path.relative_to(API_DIR / package)
            if NOT_PRODUCTION_DIRS & set(relative.parts) or path.name in NOT_PRODUCTION_FILES:
                continue
            found.append(path)
    return found


def _imports_testing(path: Path) -> bool:
    """True if the module imports `app.testing`, in any of the forms (`import`, `from`, `from app import testing`)."""
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            if any(alias.name == "app.testing" or alias.name.startswith("app.testing.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.testing" or module.startswith("app.testing."):
                return True
            if module == "app" and any(alias.name == "testing" for alias in node.names):
                return True
    return False


def test_the_scan_finds_the_production_modules() -> None:
    # Proves: the scan is looking at something. If a path change made `_production_modules` return nothing, the test
    # below would pass for the wrong reason. The routers and the worker's graph are modules that must be among them.
    names = {path.name for path in _production_modules()}
    assert {"shows.py", "queries.py", "graph.py", "main.py"} <= names


def test_no_production_module_imports_app_testing() -> None:
    # Proves (C2-M7): nothing under `app/` or `agent_worker/` outside the tests and harness imports `app.testing`.
    # Fails if a router adds `from app.testing import sample_data`.
    offenders = [str(path.relative_to(API_DIR)) for path in _production_modules() if _imports_testing(path)]
    assert offenders == []
