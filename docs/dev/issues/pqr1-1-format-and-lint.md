# PQR1-1: auto-format the Python code and broaden the lint rules

**Status:** Code review
**Date:** November 6, 2026
**Scope:** PQR1-1, PQR1-7
**Sources:** both in `docs/dev/review/2026-11-06-python-code-quality-review.md`, §3 Details rows PQR1-1 and PQR1-7 (and §7 steps 1–2)
**Tier:** T0 — formatting and lint configuration (the README's T0 list names both). The handful of lint fixes are
local, behavior-preserving rewrites, and the full suite verifies them
**Author model:** Claude Opus 5.5 (record, formatting, lint config and fixes, November 6, 2026; cloud session)
**Reviewer model:** (code review round 1, pending)
**Branch / PR:** `claude/happy-knuth-edh3br` (designated by the cloud session, restarted from `main` after PR 94 merged; a fast-forward) / PR link once opened

**Designations.** Review items here are bare (`CR1-2`). Outside this record they are `PQR1-1-CR1-2`
(`docs/dev/issues/README.md`, `docs/dev/conventions.md`). Ruff rule codes (`E501`, `S101`) are not designations. Where
the designation check would read them as one, the line carries `designation-ok`.

## Issues

### PQR1-1: the code isn't auto-formatted, and CI doesn't check it

No `line-length` was configured, so ruff assumed 88 while the code is written at about 120. CI (`.github/workflows/ci.yml`)
ran only `ruff check`. **Fixed means:** `[tool.ruff] line-length = 120`, one `ruff format` run as its own commit,
verified by an AST comparison, and `ruff format --check` in CI and in `make lint`.

### PQR1-7: only ruff's default rules are on

The default is `E4`, `E7`, `E9`, `F`. **Fixed means:** the select list from the review, `per-file-ignores` for tests,
and the real hits fixed.

## Approach

T0, in two commits, so the formatting can be audited on its own:

1. **Formatting only.** Set `line-length`, run `ruff format`, and compare a docstring-insensitive AST dump of every
   tracked `.py` file before and after, plus every docstring after whitespace normalization.
2. **Lint configuration and fixes.** The review's select list. Each remaining hit is either fixed, waived on its line
   with a reason (`# noqa: <code> - <why>`), or waived for a path in `per-file-ignores` with a comment. Then add the
   format check to CI and `make lint`, plus a `make format` target.

**Scope boundary, a choice made here:** PQR1-7's list of "real hits" includes the single-letter `l` (E741) and the
exception names without an `Error` suffix (N818). Those are findings PQR1-18 and PQR1-17 in their own right, and fixing
them means renames across files. So they're waived only for the files they fire in, with a comment saying to remove
the waiver when those findings land. That keeps the rules on everywhere else.

## Implementation log

### Round 1

- **Scope:** diff base `8c90a38902a0f73bd8d04a7c2c5825325a4862bb` (`main` after PR 94 merged). Commit 1 is `1fc85ab`
  (formatting only). Commit 2 (lint config and fixes, plus this record) is committed as work in progress before this
  review, so the scope is the commit range `8c90a38..HEAD`.
- **Failed first:**
  - `uv run ruff format --check .` at the base: **129 files would be reformatted** (107 at `line-length = 120`).
  - `ruff check` with the new rules before any fix: 1,823 hits. 1,781 were `S101` in tests; the remaining 42 are listed below.
- **Commit 1, PQR1-1 formatting** (`1fc85ab`, 108 files):
  - `[tool.ruff] line-length = 120`, then `ruff format`.
  - **Verified:** the AST dump is identical for 166 of 167 files, and docstrings are identical for all of them. The one
    exception is `test_embedded_events_on_real_page.py`. The formatter had split a long `assert` and moved its
    `# type: ignore[arg-type]` onto a line where it no longer applied, and mypy failed. A `plan` variable now holds
    the argument, so the ignore stays on its line. The same happened in `test_validation_on_real_pages.py`, where the
    ignore was moved back to the `source=` argument it applies to (an AST no-op).
  - Four string-literal lines that the formatter moved (`labels.py`, three `argparse` help strings in `run_eval.py`)
    hold bare IDs. They're a documented known exception, so they got `designation-ok`.
- **Commit 2, PQR1-7 rules, and the PQR1-1 CI step:**
  - `pyproject.toml`: `select = ["E", "W", "F", "I", "B", "UP", "SIM", "C4", "RET", "RUF", "N", "ASYNC", "DTZ", "S"]`.
    Ignored everywhere, with a reason: `E501` (the formatter owns code width; long why-comments are deliberate) and
    `RUF001`–`RUF003` (the prose deliberately uses typographic characters).
  - `per-file-ignores`, each commented:
    - tests: `S101`, `S105`, `S108`, `S603`, `ASYNC240`
    - `conftest.py`: `S101`
    - test support and developer tools (`app/testing/`, `model_eval/`, `local_test.py`): `S101`
    - `N818` and `E741`, only in the six files they fire in (deferred to PQR1-17 and PQR1-18)
  - **Fixed:**
    - `C416` ×2: reverted to a noqa (see the departures)
    - `RUF005`: list unpacking
    - `SIM108`: a ternary in `normalize.py`
    - `SIM300`: the yoda condition
    - `RUF043`: a raw, escaped `match=` pattern
    - `RUF100` ×2: removed two stale `noqa: TRY004`
    - `DTZ001` in `test_commit_ops.py`: aware timestamps
  - **Waived on the line, with a reason:**
    - five `S101` invariant `assert`s in `calendar_writer.py`, `commit.py` and `nodes.py`. They narrow types for
      mypy, and nothing runs under `python -O` (checked with grep)
    - `S105` (`Verdict.PASS`)
    - `S607` (`git` from PATH)
    - `S608` ×2 (a fixed table tuple; an allowlisted role)
    - `S603` (an argv list, no shell)
    - `ASYNC240` (one small eval fixture read)
    - `ASYNC250` (the confirmation prompt)
    - `E402` ×2 (an import placed after a safety check on purpose)
    - `DTZ001` in `test_clock.py` (naive on purpose)
  - **CI / Makefile:** a `ruff format` step in `ci.yml`, `make lint` now runs `ruff format --check`, and a new `make format`.
    `apps/api/README.md` and `apps/api/AGENTS.md` mention it.
- **Departures from the approach:**
  - `C416` in `test_db_schema.py`: the suggested `dict(rows)` failed mypy (a `CursorResult` isn't typed as an iterable
    of pairs), so the comprehensions stay, with a `noqa` saying why.
  - Commit 1 includes the one small code change described above.
- **Verification:**
  - `make check`: exit 0. ruff clean and 171 files formatted; mypy clean (156 files); pytest 1280 passed, 20 skipped;
    vitest 525 passed; e2e 107 passed.
  - `make designation-check BASE=8c90a38`: clean.
  - Moved suppression comments: mypy would flag a moved `type: ignore` that it needed, and ruff's `RUF100` flags an
    unused `noqa`. Both pass. No `pragma: no cover` line changed.
- **Noticed, not in scope:**
  - `mypy` doesn't set `warn_unused_ignores`, so a `type: ignore` that no longer suppresses anything goes unnoticed.
    Turning it on would have caught the formatter moving one.
  - The old `"agent_worker/model_eval/run_eval.py" = ["BLE001"]` waiver refers to a rule (`BLE`) that isn't selected, so
    it does nothing.
- **Where to look hardest:**
  - whether any of the line waivers should be a fix instead, above all the five production `assert`s
  - whether the E501 and RUF001–003 global ignores are acceptable
  - the commit-1 AST claim (`1fc85ab` alone can be checked against `8c90a38`)

## Code review
