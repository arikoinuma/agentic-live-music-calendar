"""Feature flags: named toggles that differ by environment, read through one function.

HOW TO READ THIS
  * A **feature flag** here is a named on/off switch for a behavior that must differ between environments or be
    switchable without a code change (not a user "flagging" a wrong listing, `arch-initial.md` section 7). The word
    "flag" alone keeps that other meaning (`RunTrigger.FLAG_THRESHOLD`).
  * `FLAGS` is the registry, the ONLY list of flags. Each `Flag` records its name, scope, which code bases read it,
    its default, an owner, when it was created and the condition for deleting it (C3.1-D18 makes the owner and
    the removal condition mandatory, so a flag cannot be added and forgotten).
  * `is_enabled(name, *, metro=None)` is the ONLY way to read one (C3.1-D6). Everything else here is the machinery
    behind it, written as pure functions that take their inputs so a test can hand them a registry and an
    environment the real ones cannot hold: `resolve_value`, `read_flag`, `environment_problems`.
  * `effective_flags()` is every flag Python can read, as a dict. `/health` shows it outside production and the
    worker records it on every `agent_run` (C3.1-D15, C3.1-D16).

HOW A VALUE IS SET
  A flag's variable is `FLAG_` plus its name upper-cased with `.` written `_` (`worker.scheduled_runs` is
  `FLAG_WORKER_SCHEDULED_RUNS`). A flag with `scope="metro"` also accepts a per-metro override,
  `FLAG_<NAME>__<SLUG>` (`FLAG_X__NEW_YORK` for the slug `new-york`). The value is exactly `true` or `false`.
  Precedence is the metro override, then the environment's value, then the registry default (C3.1-D10). An
  unset variable defers to the next level; a SET one never does, even when it is malformed (C3.1-D9).

  Values are read from the PROCESS ENVIRONMENT only, never from `apps/api/.env` (C3.1-D11): `Settings` refuses
  unknown `.env` keys and ignores unknown process variables, so a flag in `.env` fails at startup by design.
  On a laptop a flag is set on the one command that reads it (`FLAG_WORKER_SCHEDULED_RUNS=true make worker`).

THE LIMIT, STATED
  A value is read from the environment of a running process, so a change takes a restart or a redeploy (Railway
  redeploys on a variable change). A runaway production worker is stopped with Railway's controls, not a flag
  (Dep-D17). And because `/health` is Railway's deploy check, it now depends on flag evaluation; that is safe only
  because `Settings` runs `environment_problems` over the same environment at startup (C3.1-D12), so a process
  with a malformed flag never reaches the point where `/health` would evaluate it.

This module imports nothing from `app.config` (which imports it), so there is no import cycle; it reads
`os.environ` directly.

docs/dev/implementations/c3.1-feature-flags.md: C3.1-D6, C3.1-D8, C3.1-D9, C3.1-D10, C3.1-D12, C3.1-K1.
"""

import datetime
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

Scope = Literal["environment", "metro"]
Surface = Literal["python", "web"]

SCOPES: tuple[str, ...] = ("environment", "metro")
SURFACES: tuple[str, ...] = ("python", "web")

# A flag's name is `<area>.<name>`, lower case, words joined by single underscores. It therefore never contains
# `__`, which is what lets `environment_problems` split a variable at the FIRST `__` to find the metro part
# (C3.1-D6, C3.1-D10).
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*\.[a-z][a-z0-9]*(_[a-z0-9]+)*$")

# The metro part of an override variable: a metro slug (`^[a-z][a-z0-9-]{1,30}[a-z0-9]$`, `app/db/models`) upper-cased
# with `-` written `_`. A slug has no underscore, so the mapping is reversible (C3.1-D10).
METRO_PART = re.compile(r"^[A-Z][A-Z0-9_]{1,30}[A-Z0-9]$")

PREFIX = "FLAG_"


class UnknownFlagError(LookupError):
    """A name that is not in the registry, or that this code base does not read (C3.1-D6, C3.1-D8)."""


class FlagValueError(ValueError):
    """A flag variable that is set to something other than `true` or `false` (C3.1-D9)."""


@dataclass(frozen=True)
class Flag:
    """One registered feature flag. Frozen, so the registry cannot be edited after import."""

    name: str
    description: str
    scope: Scope
    # Which code bases read this flag (C3.1-D8): the Python code (API and worker are one code base) and/or the
    # Next.js app. A variable set for a flag the receiving code base does not read is refused at startup there.
    surfaces: tuple[Surface, ...]
    default: bool
    owner: str
    created: datetime.date
    # The condition under which this flag is deleted. Mandatory: a flag with no way out becomes permanent.
    removal: str

    def __post_init__(self) -> None:
        # A bad entry fails when the module is imported, so the first test run names it (C3.1-T1).
        if not NAME_PATTERN.match(self.name):
            raise ValueError(f"flag name {self.name!r} must look like 'area.some_name' (lower case, one dot)")
        if self.scope not in SCOPES:
            raise ValueError(f"flag {self.name}: scope {self.scope!r} is not one of {SCOPES}")
        if not self.surfaces or any(s not in SURFACES for s in self.surfaces):
            raise ValueError(f"flag {self.name}: surfaces {self.surfaces!r} must be a non-empty subset of {SURFACES}")
        for field in ("description", "owner", "removal"):
            if not getattr(self, field).strip():
                raise ValueError(f"flag {self.name}: {field} must not be empty")


def env_key(name: str) -> str:
    """The environment variable that sets a flag: `worker.scheduled_runs` -> `FLAG_WORKER_SCHEDULED_RUNS`."""
    return PREFIX + name.upper().replace(".", "_")


def metro_key(name: str, metro: str) -> str:
    """The per-metro override variable: `FLAG_<NAME>__<SLUG>`, the slug upper-cased with `-` written `_`."""
    return env_key(name) + "__" + metro.upper().replace("-", "_")


def build_registry(flags: Iterable[Flag]) -> dict[str, Flag]:
    """The registry as a dict by name, refusing a repeated name or two names that map to one variable (C3.1-D6)."""
    registry: dict[str, Flag] = {}
    variables: dict[str, str] = {}
    for flag in flags:
        if flag.name in registry:
            raise ValueError(f"flag {flag.name!r} is registered twice")
        key = env_key(flag.name)
        if key in variables:
            raise ValueError(f"flags {variables[key]!r} and {flag.name!r} both map to the variable {key}")
        registry[flag.name] = flag
        variables[key] = flag.name
    return registry


# --- The registry --------------------------------------------------------------------------------------------------
# The first and only flag today. Adding one is: add an entry here, read it with `is_enabled("<name>")` in code,
# add its variable to `docs/dev/environments.md` (the inventory block there is checked against this table), and
# run `make flags ARGS=--check`.
FLAGS: dict[str, Flag] = build_registry(
    [
        Flag(
            name="worker.scheduled_runs",
            description=(
                "Whether a worker started with `--trigger scheduled` runs. Off, it logs one line and exits 0, so a "
                "Railway cron service can exist without doing work (C3.1-D1, C3.1-D13)."
            ),
            scope="environment",
            surfaces=("python",),
            default=False,
            owner="Ari Koinuma",
            created=datetime.date(2026, 11, 9),
            removal=(
                "Delete the flag and the gate once production's scheduled run has run unattended for a month after C11 "
                "and nobody has needed the off switch, or when a database-backed flag replaces this mechanism "
                "(C3.1-D7, Dep-D17)."
            ),
        ),
    ]
)


# --- Reading a value -----------------------------------------------------------------------------------------------


def parse_flag_value(key: str, raw: str) -> bool:
    """`true` -> True, `false` -> False, anything else (including empty, `True`, `1`, `yes`) raises (C3.1-D9)."""
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise FlagValueError(f"{key}={raw!r} is not a feature flag value: write exactly 'true' or 'false'")


def resolve_value(flag: Flag, environ: Mapping[str, str], metro: str | None) -> bool:
    """The flag's value under `environ`: metro override, then the environment's value, then the default.

    Pure: it reads only its arguments, which is what lets one table of cases drive it in both languages.
    """
    # Precedence and the difference between unset and malformed (C3.1-K1; C3.1-D9, C3.1-D10): the most specific
    # level that is SET wins, a level that is UNSET defers to the next, and a level set to anything but
    # `true`/`false` is an error, never a fall-through. That is why the test is `key in environ` and not
    # `environ.get(key)`: an empty Railway value must not quietly become the default. A metro override is only
    # looked up for `metro`-scoped flags, so a stray override variable cannot change an environment-scoped flag.
    keys = [env_key(flag.name)]
    if flag.scope == "metro" and metro is not None:
        keys.insert(0, metro_key(flag.name, metro))
    for key in keys:
        if key in environ:
            return parse_flag_value(key, environ[key])
    return flag.default


def read_flag(
    name: str,
    flags: Mapping[str, Flag],
    environ: Mapping[str, str],
    *,
    metro: str | None = None,
    surface: Surface = "python",
) -> bool:
    """A flag's value from an explicit registry and environment. `is_enabled` is this with the real ones.

    Raises `UnknownFlagError` for a name that is not registered or that `surface` does not read (C3.1-D8): a
    typo then fails at the call, not as a silent `False`.
    """
    flag = flags.get(name)
    if flag is None:
        raise UnknownFlagError(f"{name!r} is not a registered feature flag (registered: {sorted(flags)})")
    if surface not in flag.surfaces:
        raise UnknownFlagError(f"{name!r} is not read by the {surface} code base (it is read by {list(flag.surfaces)})")
    return resolve_value(flag, environ, metro)


def is_enabled(name: str, *, metro: str | None = None) -> bool:
    """Whether the feature flag `name` is on, under this process's environment. The only way to read a flag.

    The name must be a string literal at the call site: `test_flag_hygiene.py` finds reads by scanning for it
    (C3.1-D18). `metro` is a metro slug, used for `metro`-scoped flags only.
    """
    return read_flag(name, FLAGS, os.environ, metro=metro)


def effective_flags() -> dict[str, bool]:
    """Every flag Python can read, at environment level (no metro), as `{name: value}`.

    What `/health` shows outside production and what the worker records on each run (C3.1-D15). The first
    `metro`-scoped Python flag must make the run record take a metro (C3.1-D15's stated limit); until then the
    environment-level value is the run's value.
    """
    return {name: resolve_value(flag, os.environ, None) for name, flag in FLAGS.items() if "python" in flag.surfaces}


# --- Startup refusal -----------------------------------------------------------------------------------------------


def environment_problems(
    environ: Mapping[str, str],
    flags: Mapping[str, Flag] = FLAGS,
    *,
    surface: Surface = "python",
) -> list[str]:
    """What is wrong with the `FLAG_*` variables in `environ`, as sentences; empty when all is well (C3.1-D12).

    `Settings` raises on a non-empty list, so a mistyped, unread or malformed flag variable stops the process at
    startup instead of doing nothing (the failure that looks like it worked). One problem per bad variable, in
    sorted variable order; the checks run in a fixed order (unregistered, unread here, metro misuse, value) so the
    TypeScript twin (`lib/flags.ts`) gives the same answer for the same cases (`flag-cases.json`).

    Only names that START with `FLAG_` count: `FLAGSHIP` and `flag_x` are other tools' variables and are ignored.
    """
    by_variable = {env_key(flag.name): flag for flag in flags.values()}
    readable = sorted(key for key, flag in by_variable.items() if surface in flag.surfaces)
    problems: list[str] = []
    for key in sorted(environ):
        if not key.startswith(PREFIX):
            continue
        # Split at the FIRST `__`: a flag name has none, so what follows is the metro part (C3.1-D6).
        base, sep, metro_part = key.partition("__")
        flag = by_variable.get(base)
        if flag is None:
            problems.append(f"{key} names no registered feature flag; the variables this code base reads: {readable}")
            continue
        if surface not in flag.surfaces:
            problems.append(
                f"{key} sets a flag that is read by {list(flag.surfaces)} only, not by {surface}; "
                "remove it from this service's variables"
            )
            continue
        if sep:
            if flag.scope != "metro":
                problems.append(f"{key} is a metro override, but {flag.name} is environment-scoped and takes none")
                continue
            if "__" in metro_part or not METRO_PART.match(metro_part):
                problems.append(
                    f"{key} has a malformed metro part {metro_part!r}: upper-case letters, digits and single "
                    "underscores, starting with a letter (a hyphen in a slug is written _)"
                )
                continue
        try:
            parse_flag_value(key, environ[key])
        except FlagValueError as err:
            problems.append(str(err))
    return problems
