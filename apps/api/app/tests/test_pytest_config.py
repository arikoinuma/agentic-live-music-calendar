"""Guards on how pytest finds the tests, so a test can't silently stop running (or a script start running).

HOW TO READ THIS FILE
  The two settings that decide what pytest runs live in `pyproject.toml`: `testpaths` (which directories it
  walks) and `python_files` (which file names it treats as test modules). Both fail quietly. A test file
  outside `testpaths` (or under a directory `norecursedirs` skips) is never run and nothing says so (v0.1-G14, the
  original gap). A file whose name matches
  `python_files` is *imported* by pytest on every run, even if it holds no tests: `agent_worker/local_test.py`
  is a manual script against a real database, and pytest's default `*_test.py` glob matches it.

  Sections, in order:
    1. Two small pure helpers, so the checks can be tested against made-up paths.
    2. The guards, run against the real tree and the settings pytest is actually using.
    3. The negative control: the helpers do report a problem when given one.

  These tests read `testpaths` and `python_files` from pytest's own config (the `pytestconfig` fixture), not
  from `pyproject.toml` directly, so they cannot drift from the settings they guard. They live in `app/tests/`
  but import nothing from `agent_worker/`: they only look at file names (`apps/api/AGENTS.md`: `app/` never
  imports from the worker).

Source: docs/dev/implementations/a7-testing.md, "Test approach" section 1.
"""

import fnmatch
from pathlib import Path

import pytest

# Directories that can hold .py files that are not ours: virtualenvs, caches, vendored packages. A directory
# whose name starts with "." (.venv, .mypy_cache, .git) is skipped too.
IGNORED_DIRS = {"node_modules", "__pycache__"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def python_files_under(root: Path) -> list[Path]:
    """Every `.py` file below `root`, skipping hidden directories, `node_modules` and `__pycache__`.

    The walk is the same for both guards below, on purpose: the pattern guard must not depend on `testpaths`,
    or it would be blind to a script that sits outside today's `testpaths` and only starts being imported when
    someone widens them.
    """
    found: list[Path] = []
    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts[:-1]
        if any(part.startswith(".") or part in IGNORED_DIRS for part in parts):
            continue
        found.append(path)
    return sorted(found)


def uncollected(
    files: list[Path], testpaths: list[str], root: Path, norecursedirs: list[str] | tuple[str, ...] = ()
) -> list[Path]:
    """The `test_*.py` files in `files` that pytest would never collect: outside every directory in `testpaths`
    (relative to `root`), or under a directory whose name matches a `norecursedirs` glob.

    The second case matters because pytest skips directories such as `build`, `dist` and `*.egg` by default even
    inside `testpaths`, so a test dropped in `agent_worker/build/` would pass a testpaths-only check and still never
    run (A7-CR1-5).
    """
    roots = [root / testpath for testpath in testpaths]

    def skipped_dir(f: Path) -> bool:
        return any(fnmatch.fnmatch(part, glob) for part in f.relative_to(root).parts[:-1] for glob in norecursedirs)

    return [
        f for f in files
        if f.name.startswith("test_") and (not any(f.is_relative_to(r) for r in roots) or skipped_dir(f))
    ]


def would_import(name: str, patterns: list[str]) -> str | None:
    """The first of pytest's `python_files` globs that file name `name` matches, or None if it matches none."""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return pattern
    return None


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


def test_every_test_module_is_inside_a_test_path(pytestconfig: pytest.Config) -> None:
    # Proves (v0.1-G14): no `test_*.py` file in `apps/api` lies outside `testpaths` or under a directory pytest's
    # `norecursedirs` skips (`build`, `dist`, ...). A test added under `scripts/`, a new top-level package or an
    # `agent_worker/build/` would otherwise be written, committed and never run, with a green suite as the only
    # evidence. The expected set is empty by construction, so the failure message names the stray files.
    files = python_files_under(pytestconfig.rootpath)
    testpaths = [str(p) for p in pytestconfig.getini("testpaths")]
    skipped_dirs = [str(p) for p in pytestconfig.getini("norecursedirs")]
    stray = uncollected(files, testpaths, pytestconfig.rootpath, skipped_dirs)
    assert stray == [], f"test files pytest would never collect (testpaths {testpaths}): {[str(f) for f in stray]}"


def test_the_file_pattern_matches_only_test_modules(pytestconfig: pytest.Config) -> None:
    # Proves (v0.1-G14): the only files pytest's `python_files` globs match are named `test_*.py`. A manual
    # script such as `agent_worker/local_test.py` (it opens real databases and expects a real model) is therefore
    # never imported by a test run, whatever `testpaths` says. This walks the whole tree rather than `testpaths`,
    # so it is red on a config that only widens `testpaths` and leaves pytest's default `*_test.py` glob in place.
    patterns = [str(p) for p in pytestconfig.getini("python_files")]
    files = python_files_under(pytestconfig.rootpath)
    offenders = [
        f"{f.relative_to(pytestconfig.rootpath)} (matches {pattern!r})"
        for f in files
        if not f.name.startswith("test_") and (pattern := would_import(f.name, patterns))
    ]
    assert offenders == [], f"pytest would import these as test modules: {offenders}"


# ---------------------------------------------------------------------------
# The negative control
# ---------------------------------------------------------------------------


def test_the_guards_can_fail(tmp_path: Path) -> None:
    # Proves: the two helpers do report a problem when there is one, so a guard that can never fail doesn't pass
    # the real tree by accident. The paths are made up here (nothing is read from the real config): a test
    # file under `scripts/` is outside `testpaths = ["app", "agent_worker"]`, one under `app/tests/` is inside,
    # and `local_test.py` matches the old default glob `*_test.py` but not `test_*.py`.
    outside = tmp_path / "scripts" / "test_x.py"
    inside = tmp_path / "app" / "tests" / "test_y.py"
    assert uncollected([outside, inside], ["app", "agent_worker"], tmp_path) == [outside]

    # A file inside `testpaths` but under a directory pytest never recurses into (`build`, by default) is not
    # collected either: it counts as uncollected too (A7-CR1-5).
    skipped = tmp_path / "agent_worker" / "build" / "test_z.py"
    assert uncollected([skipped, inside], ["app", "agent_worker"], tmp_path, norecursedirs=["build", "*.egg"]) == [skipped]
    assert uncollected([skipped], ["app", "agent_worker"], tmp_path, norecursedirs=[]) == []

    assert would_import("local_test.py", ["test_*.py", "*_test.py"]) == "*_test.py"
    assert would_import("local_test.py", ["test_*.py"]) is None
    assert would_import("test_graph.py", ["test_*.py"]) == "test_*.py"
