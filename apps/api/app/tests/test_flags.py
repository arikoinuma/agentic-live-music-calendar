"""Tests for the feature-flag registry and resolver in `app/flags.py` (C3.1-T1 to C3.1-T4, C3.1-T6).

HOW TO READ THIS
  `app/flags.py` is a small pure core (`resolve_value`, `read_flag`, `environment_problems`) with thin wrappers
  (`is_enabled`, `effective_flags`) that bind it to the real registry and `os.environ`. The tests are in four
  sections: the registry is well formed (C3.1-T1), the resolution rule as a table (C3.1-T2, which is where the
  `C3.1-K1` gap is checked), the reading functions (C3.1-T3) and the startup problems (C3.1-T4); `effective_flags`
  is last (C3.1-T6).

  **Where the expected values come from.** The resolution, read and startup tables are in
  `apps/calendar/lib/flag-cases.json`, written by hand from C3.1-D9, C3.1-D10 and C3.1-D12. The same file drives
  the TypeScript twin (`lib/flags.test.ts`), so the two languages are checked against one set of answers rather than
  each against its own reading of the rule. Its `flags` section is a registry of its own, because the real one holds a
  single Python-only flag and the cases need a metro-scoped flag, a web-only flag and an unread one. No expected
  value here is computed by the code under test.
"""

import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app import flags
from app.flags import (
    FLAGS,
    Flag,
    FlagValueError,
    UnknownFlagError,
    build_registry,
    effective_flags,
    env_key,
    environment_problems,
    is_enabled,
    metro_key,
    parse_flag_value,
    read_flag,
    resolve_value,
)

CASES_FILE = Path(__file__).resolve().parents[4] / "apps" / "calendar" / "lib" / "flag-cases.json"
CASES: dict[str, Any] = json.loads(CASES_FILE.read_text())


def case_flag(entry: dict[str, Any]) -> Flag:
    """A `Flag` from a case-table entry. The table carries only what the rule reads; the rest is filler."""
    return Flag(
        name=entry["name"],
        description="a flag from the shared case table",
        scope=entry["scope"],
        surfaces=tuple(entry["surfaces"]),
        default=entry["default"],
        owner="tests",
        created=datetime.date(2026, 11, 9),
        removal="never: it exists only in the case table",
    )


# The table's own registry (C3.1-D6), by name.
CASE_FLAGS = build_registry(case_flag(entry) for entry in CASES["flags"])


@pytest.fixture(autouse=True)
def isolate_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves nothing itself: it keeps a developer's exported `FLAG_*` variables out of the tests that read the
    # real `os.environ` (`is_enabled`, `effective_flags`), so a laptop gives the same result as CI.
    for name in list(os.environ):
        if name.startswith("FLAG_"):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# The registry is well formed (C3.1-T1)
# ---------------------------------------------------------------------------


def test_the_real_registry_is_well_formed() -> None:
    # Proves (C3.1-T1, C3.1-D6, C3.1-D18): every registered flag has a valid name, scope and surfaces, a non-empty
    # owner, description and removal condition, and a date; no two names map to one variable. `Flag.__post_init__`
    # refuses most of this at import, so this test is the readable statement of the rule, and the only place the
    # `created` date is checked. It applies to the REAL `FLAGS` only: the case table's registry has fillers.
    assert FLAGS, "the registry is empty"
    variables = [env_key(name) for name in FLAGS]
    assert len(variables) == len(set(variables))
    for name, flag in FLAGS.items():
        assert name == flag.name
        assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*", name)
        assert "__" not in name
        assert flag.scope in ("environment", "metro")
        assert flag.surfaces and set(flag.surfaces) <= {"python", "web"}
        assert flag.owner.strip() and flag.description.strip() and flag.removal.strip()
        assert isinstance(flag.created, datetime.date)


def test_no_metro_scoped_flag_is_read_by_python_yet() -> None:
    # Proves (C3.1-T1, C3.1-D15): the run record is one snapshot of environment-level values taken at start, which
    # is only the run's value while no Python-readable flag is `metro`-scoped. The first one must make
    # `start_run` take the venue's metro slug; this test then fails and says so, instead of the record silently
    # being wrong for a venue whose metro has an override.
    metro_in_python = [name for name, flag in FLAGS.items() if flag.scope == "metro" and "python" in flag.surfaces]
    assert metro_in_python == [], f"{metro_in_python}: make PostgresAuditWriter.start_run take the venue's metro first"


@pytest.mark.parametrize(
    "bad_name",
    ["worker", "Worker.x", "worker.Scheduled", "worker.a__b", "a.b.c", "worker.", ".x", "1worker.x", "worker._x"],
)
def test_a_malformed_name_is_refused(bad_name: str) -> None:
    # Proves (C3.1-D6): the name pattern is enforced at construction. A name containing `__` would break the
    # split at the first `__` that tells a metro override from a flag's own variable.
    with pytest.raises(ValueError, match="flag name"):
        Flag(
            name=bad_name,
            description="d",
            scope="environment",
            surfaces=("python",),
            default=False,
            owner="o",
            created=datetime.date(2026, 11, 9),
            removal="r",
        )


def test_two_names_that_map_to_one_variable_are_refused() -> None:
    # Proves (C3.1-D6): `a.b_c` and `a_b.c` both map to FLAG_A_B_C, so setting that variable would be ambiguous.
    # The registry refuses the pair when it is built, not when somebody sets the variable.
    def make(name: str) -> Flag:
        return Flag(name, "d", "environment", ("python",), False, "o", datetime.date(2026, 11, 9), "r")

    with pytest.raises(ValueError, match="FLAG_A_B_C"):
        build_registry([make("a.b_c"), make("a_b.c")])
    with pytest.raises(ValueError, match="twice"):
        build_registry([make("a.b"), make("a.b")])


def test_the_variable_names() -> None:
    # Proves (C3.1-D6, C3.1-D10): the name-to-variable mapping, with literals written from the plan: `.` becomes
    # `_`, the name is upper-cased, and a metro slug's hyphen becomes `_` after a double underscore.
    assert env_key("worker.scheduled_runs") == "FLAG_WORKER_SCHEDULED_RUNS"
    assert metro_key("worker.scheduled_runs", "msp") == "FLAG_WORKER_SCHEDULED_RUNS__MSP"
    assert metro_key("demo.scoped", "new-york") == "FLAG_DEMO_SCOPED__NEW_YORK"


@pytest.mark.parametrize(("raw", "expected"), [("true", True), ("false", False)])
def test_parse_flag_value_accepts_exactly_true_and_false(raw: str, expected: bool) -> None:
    # Proves (C3.1-D9): the two accepted spellings. Everything else is in the resolution table below.
    assert parse_flag_value("FLAG_X", raw) is expected


@pytest.mark.parametrize("raw", ["", "True", "FALSE", "1", "0", "yes", "no", " true", "true "])
def test_parse_flag_value_refuses_everything_else(raw: str) -> None:
    # Proves (C3.1-D9): no lenient spelling is accepted, including the empty string and surrounding spaces. The
    # message names the variable so the fix is findable.
    with pytest.raises(FlagValueError, match="FLAG_X"):
        parse_flag_value("FLAG_X", raw)


# ---------------------------------------------------------------------------
# C3.1-K1: the resolution rule, as a table (C3.1-T2). Red until the gap in `resolve_value` is filled.
# ---------------------------------------------------------------------------


def _expect(expect: Any, run: Any) -> None:
    """Assert `run()` gives the boolean `expect`, or raises `FlagValueError` containing `expect["error"]`."""
    if isinstance(expect, dict):
        with pytest.raises(FlagValueError, match=re.escape(expect["error"])):
            run()
    else:
        assert run() is expect


@pytest.mark.parametrize("case", CASES["resolution"], ids=lambda c: c["id"])
def test_resolution_follows_the_shared_table(case: dict[str, Any]) -> None:
    # Proves (C3.1-T2, C3.1-K1, C3.1-D9, C3.1-D10): the most specific level that is SET wins (metro override,
    # then the environment's value, then the default); an UNSET level defers; a SET level that is not
    # `true`/`false` raises and does not fall through; an override is looked up only for a `metro`-scoped flag
    # and only when a metro is given. The cases are `flag-cases.json`'s `resolution` section, hand-written, and the
    # TypeScript twin runs the same file. The likeliest mistakes each turn a named row red: reading an empty value
    # as unset ("the empty string is set, not unset"), checking the environment before the override ("a metro
    # override beats the environment value"), and consulting an override for an environment-scoped flag ("an
    # override on an environment-scoped flag is ignored").
    flag = CASE_FLAGS[case["flag"]]
    _expect(case["expect"], lambda: resolve_value(flag, case["environ"], case["metro"]))


# ---------------------------------------------------------------------------
# Reading (C3.1-T3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES["read"], ids=lambda c: c["id"])
def test_read_flag_follows_the_shared_table(case: dict[str, Any]) -> None:
    # Proves (C3.1-T3, C3.1-D6, C3.1-D8): a name that is unregistered, or registered but not read by this code
    # base, raises `UnknownFlagError` at the call instead of answering `False`; a readable one resolves, with the
    # metro passed through. The `surface` argument is what lets the web-only rows run on the Python side.
    def run() -> bool:
        return read_flag(case["name"], CASE_FLAGS, case["environ"], metro=case["metro"], surface=case["surface"])

    if case["expect"] == "unknown":
        with pytest.raises(UnknownFlagError):
            run()
    else:
        assert run() is case["expect"]


def test_is_enabled_reads_the_real_registry_and_the_environment_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T3, C3.1-D6): `is_enabled` answers from the real registry (the default is off) and from
    # `os.environ` AT THE CALL, not at import, so a test or a restarted process sees the variable it was given.
    # A module that cached the environment at import would pass the first assert and fail the second.
    monkeypatch.delenv("FLAG_WORKER_SCHEDULED_RUNS", raising=False)
    assert is_enabled("worker.scheduled_runs") is False
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    assert is_enabled("worker.scheduled_runs") is True


def test_is_enabled_refuses_an_unknown_name() -> None:
    # Proves (C3.1-T3, C3.1-D6): a typo in a name is an error at the call site. Returning `False` for an unknown
    # name would make a mistyped gate look like a flag that is simply off.
    with pytest.raises(UnknownFlagError, match=r"worker\.scheduled_run"):
        is_enabled("worker.scheduled_run")


def test_is_enabled_passes_the_metro_through(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T3): `metro` reaches the resolver. The real registry holds no metro-scoped flag, so the seam is
    # patched: a registry with one is swapped in, and the override variable for "msp" is set.
    scoped = CASE_FLAGS["demo.scoped"]
    monkeypatch.setattr(flags, "FLAGS", {"demo.scoped": scoped})
    monkeypatch.setenv("FLAG_DEMO_SCOPED__MSP", "true")
    assert is_enabled("demo.scoped", metro="msp") is True
    assert is_enabled("demo.scoped") is False


# ---------------------------------------------------------------------------
# Startup problems (C3.1-T4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES["startup"], ids=lambda c: c["id"])
def test_startup_problems_follow_the_shared_table(case: dict[str, Any]) -> None:
    # Proves (C3.1-T4, C3.1-D12): the startup rule as a table. An unregistered variable is refused (and the message
    # lists the variables this code base reads, so a typo is visible); a metro override on an environment-scoped
    # flag, an empty or malformed metro part, a flag the other code base reads, and a value that is not
    # `true`/`false` are each ONE problem, in sorted variable order; variables that merely start like one
    # (`FLAGSHIP`, `flag_x`, `FLAG`) are ignored. Deleting the unregistered check turns the "FLAG_NOPE" and
    # "empty name part" rows red. Expected problems are the table's, hand-written.
    problems = environment_problems(case["environ"], CASE_FLAGS, surface=case["surface"])
    assert len(problems) == len(case["problems"]), problems
    for problem, needles in zip(problems, case["problems"], strict=True):
        for needle in needles:
            assert needle in problem, f"{needle!r} not in {problem!r}"


def test_the_real_registry_accepts_its_own_variable() -> None:
    # Proves (C3.1-D12): with the real registry, the registered variable passes in both of its legal spellings and
    # a made-up one is refused. A startup rule that rejected the one real flag would stop every process.
    assert environment_problems({"FLAG_WORKER_SCHEDULED_RUNS": "true"}) == []
    assert environment_problems({"FLAG_WORKER_SCHEDULED_RUNS": "false"}) == []
    assert len(environment_problems({"FLAG_WORKER_SCHEDULED_RUNZ": "true"})) == 1


def test_the_flags_module_imports_nothing_from_config() -> None:
    # Proves (C3.1-D6, C3.1-CR1-3, risk "a cycle at import"): `app.config` imports `app.flags` for its validator, so
    # importing `app.flags` must not pull in `app.config`, directly or through another module, or the API, worker and
    # Alembic would fail at import before any test names the cause. A fresh interpreter (so no cached
    # modules; `-c` puts the working directory on the path) imports it with `app.config` blocked (`sys.modules[...] = None` makes any import
    # of it raise); the exit status 0 is the evidence. Run from `apps/api`, the directory every entry point uses.
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['app.config'] = None; import app.flags"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# effective_flags (C3.1-T6)
# ---------------------------------------------------------------------------


def test_effective_flags_lists_every_python_flag_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T6, C3.1-D15, C3.1-D16): the dict `/health` and the run record carry has one entry per flag
    # Python reads, with the registry default when the variable is unset and the set value when it is. An entry
    # missing here is a flag the audit trail would not record.
    monkeypatch.delenv("FLAG_WORKER_SCHEDULED_RUNS", raising=False)
    assert effective_flags() == {"worker.scheduled_runs": False}
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    assert effective_flags() == {"worker.scheduled_runs": True}


def test_effective_flags_leaves_out_a_flag_python_does_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C3.1-T6, C3.1-D8): a web-only flag is not Python's to report. The seam is patched with the case
    # table's registry (one Python-only, one web-only, one both-ways) and the default values are read back.
    monkeypatch.setattr(flags, "FLAGS", CASE_FLAGS)
    assert effective_flags() == {"demo.scoped": False, "demo.python_only": False, "demo.unread": False}
