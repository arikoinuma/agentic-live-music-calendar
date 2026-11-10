"""The human face of the feature-flag registry: list it, evaluate it, check it, and generate its TypeScript.

Run from `apps/api` (or `make flags`, which passes `ARGS=` through):

    uv run python -m scripts.flags               # the table: every flag, its scope, default, owner, removal condition
    uv run python -m scripts.flags --effective   # this process's values, and where each came from
    uv run python -m scripts.flags --check       # the hygiene checks below; exit 1 on any problem
    uv run python -m scripts.flags --write-ts    # regenerate apps/calendar/lib/flag-registry.ts

HOW TO READ THIS
  The registry itself is `app/flags.py` (C3.1-D6). This file never decides what a flag's value is; it renders the
  registry (`registry_table`, `render_ts`), reports (`effective_report`) and checks it (`hygiene_problems`).
  `hygiene_problems` is a pure function of a registry and a source tree, so `app/tests/test_flag_hygiene.py` can run it over
  the real repository and over a synthetic tree that breaks every rule on purpose, which is how that test proves the
  checker is not vacuous (a scan that finds nothing passes by accident).

THE CHECKS (C3.1-D18)
  1. Every `is_enabled(...)` call in `app/` and `agent_worker/` (tests, `app/testing/` and `app/flags.py` excluded) and
     every `isEnabled(...)` call in `apps/calendar` (tests and the two flag modules excluded) has a STRING-LITERAL
     first argument naming a registered flag that this code base reads. A non-literal argument fails, because a
     static scan could not see which flag it reads.
  2. Every registered flag is read somewhere on each surface it declares.
  3. `docs/dev/environments.md`'s feature-flag inventory (between `flags-inventory:start` and `flags-inventory:end`)
     names exactly the registered flags' variables.

`--write-ts` is also run by `make types`, and `make contract-check` fails when the committed file is stale (C3.1-D17).

docs/dev/implementations/c3.1-feature-flags.md: C3.1-D17, C3.1-D18.
"""

import argparse
import ast
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.flags import FLAGS, Flag, env_key, environment_problems, resolve_value

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
WEB_ROOT = REPO_ROOT / "apps" / "calendar"
ENVIRONMENTS_DOC = REPO_ROOT / "docs" / "dev" / "environments.md"
TS_OUT = WEB_ROOT / "lib" / "flag-registry.ts"

INVENTORY_START = "<!-- flags-inventory:start -->"
INVENTORY_END = "<!-- flags-inventory:end -->"


@dataclass(frozen=True)
class Read:
    """One place the code reads a flag: where, and the literal name (None when the argument is not a literal)."""

    path: Path
    line: int
    name: str | None
    # How the flag was read. `is_enabled` is the one way the scan can check; anything else is reported (C3.1-CR1-2).
    via: str = "is_enabled"


# --- The table and the effective values ---------------------------------------------------------------------------


def registry_table(flags: Mapping[str, Flag]) -> str:
    """Every flag as a block of lines: name and variable, then scope, surfaces, default, owner, created, removal."""
    blocks = []
    for flag in flags.values():
        blocks.append(
            "\n".join(
                [
                    f"{flag.name}  ({env_key(flag.name)})",
                    f"  {flag.description}",
                    f"  scope: {flag.scope}   surfaces: {', '.join(flag.surfaces)}   default: "
                    f"{str(flag.default).lower()}",
                    f"  owner: {flag.owner}   created: {flag.created.isoformat()}",
                    f"  removal: {flag.removal}",
                ]
            )
        )
    return "\n\n".join(blocks)


def effective_report(flags: Mapping[str, Flag], environ: Mapping[str, str]) -> str:
    """Each flag Python reads, its value under `environ`, and whether it came from the environment or the default.

    Raises `ValueError` listing the startup problems first, because a value that `Settings` would refuse at startup is
    not an effective value of anything.
    """
    problems = environment_problems(environ, flags)
    if problems:
        raise ValueError("; ".join(problems))
    lines = []
    for flag in flags.values():
        if "python" not in flag.surfaces:
            continue
        source = "environment" if env_key(flag.name) in environ else "default"
        lines.append(f"{flag.name} = {str(resolve_value(flag, environ, None)).lower()}   ({source})")
    return "\n".join(lines)


# --- TypeScript generation ----------------------------------------------------------------------------------------


def render_ts(flags: Mapping[str, Flag]) -> str:
    """The text of `apps/calendar/lib/flag-registry.ts`: the registry as a literal, and the web-readable names.

    `WebFlagName` is a union of the literal names whose surfaces include `web`, and `never` when there are none, so
    `isEnabled("worker.scheduled_runs")` does not type-check today: a flag only Python reads must not become callable
    from the web (C3.1-D8, C3.1-D17).
    """
    entries = []
    for flag in flags.values():
        surfaces = ", ".join(f'"{s}"' for s in flag.surfaces)
        entries.append(
            f'  "{flag.name}": {{\n    scope: "{flag.scope}",\n    surfaces: [{surfaces}],\n'
            f"    default: {str(flag.default).lower()},\n  }},"
        )
    web = [f'"{flag.name}"' for flag in flags.values() if "web" in flag.surfaces]
    web_union = " | ".join(web) if web else "never"
    return (
        "// GENERATED by apps/api/scripts/flags.py (`make types`) from apps/api/app/flags.py. Do not edit by hand:\n"
        "// `make contract-check` fails when this file is stale (C3.1-D17).\n"
        "\n"
        "export const FLAG_REGISTRY = {\n" + "\n".join(entries) + "\n} as const;\n"
        "\n"
        "export type FlagName = keyof typeof FLAG_REGISTRY;\n"
        "\n"
        "// The flags the web code base reads. `never` while none is: no name type-checks, on purpose.\n"
        f"export type WebFlagName = {web_union};\n"
    )


# --- Scanning the source for reads ---------------------------------------------------------------------------------


def scan_python_reads(api_root: Path) -> list[Read]:
    """Every `is_enabled(...)` call in `app/` and `agent_worker/`, except tests, `app/testing/` and `app/flags.py`."""
    reads: list[Read] = []
    for top in ("app", "agent_worker"):
        for path in sorted((api_root / top).rglob("*.py")):
            relative = path.relative_to(api_root)
            parts = relative.parts
            if "tests" in parts or path.name.startswith("test_") or relative.as_posix() in ("app/flags.py",):
                continue
            if parts[:2] == ("app", "testing"):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                # `is_enabled` imported under another name would hide every call to it from this scan.
                if isinstance(node, ast.ImportFrom) and node.module == "app.flags":
                    for alias in node.names:
                        if alias.name == "is_enabled" and alias.asname:
                            reads.append(Read(relative, node.lineno, None, via="an alias of is_enabled"))
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                # `read_flag` and `resolve_value` are the pure seams under `is_enabled`; calling them from app code
                # would read a flag where this scan cannot see which one.
                if called in ("read_flag", "resolve_value"):
                    reads.append(Read(relative, node.lineno, None, via=called))
                    continue
                if called != "is_enabled":
                    continue
                first = node.args[0] if node.args else None
                literal = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
                reads.append(Read(relative, node.lineno, literal))
    return reads


_WEB_CALL = re.compile(r"\bisEnabled\(\s*(?P<arg>[^),]*?)\s*[,)]")
_WEB_LITERAL = re.compile(r"""^(["'])(?P<name>[^"']*)\1$""")
_WEB_SKIP_DIRS = {"node_modules", ".next", "e2e", "test"}
_WEB_SKIP_FILES = {"lib/flags.ts", "lib/flag-registry.ts"}


def scan_web_reads(web_root: Path) -> list[Read]:
    """Every `isEnabled(...)` call in the Next.js app, except tests and the two flag modules."""
    reads: list[Read] = []
    for path in sorted(web_root.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or not path.is_file():
            continue
        relative = path.relative_to(web_root)
        if set(relative.parts) & _WEB_SKIP_DIRS or relative.as_posix() in _WEB_SKIP_FILES:
            continue
        if re.search(r"\.(test|spec)\.tsx?$", path.name):
            continue
        # The whole file at once, not line by line: a formatter wraps a call across lines, and the line number is
        # recovered from the match offset (C3.1-CR1-1).
        text = path.read_text()
        for call in _WEB_CALL.finditer(text):
            literal = _WEB_LITERAL.match(call.group("arg"))
            number = text.count("\n", 0, call.start()) + 1
            reads.append(Read(relative, number, literal.group("name") if literal else None))
    return reads


# --- The checks ---------------------------------------------------------------------------------------------------


def _read_problems(reads: list[Read], flags: Mapping[str, Flag], surface: str) -> list[str]:
    problems = []
    for read in reads:
        where = f"{read.path}:{read.line}"
        if read.via != "is_enabled":
            problems.append(
                f"{where}: reads a flag through {read.via}, which this check cannot see: use is_enabled('<literal>')"
            )
        elif read.name is None:
            problems.append(f"{where}: the flag name must be a string literal, so a static check can see it")
        elif read.name not in flags:
            problems.append(f"{where}: reads {read.name!r}, which is not a registered feature flag")
        elif surface not in flags[read.name].surfaces:
            problems.append(f"{where}: reads {read.name!r}, which is not declared for the {surface} surface")
    return problems


def inventory_variables(doc: Path) -> set[str] | None:
    """The `FLAG_*` variables named between the inventory markers in `doc`, or None when a marker is missing."""
    text = doc.read_text()
    if INVENTORY_START not in text or INVENTORY_END not in text:
        return None
    block = text.split(INVENTORY_START, 1)[1].split(INVENTORY_END, 1)[0]
    return set(re.findall(r"`(FLAG_[A-Z0-9_]+)`", block))


def hygiene_problems(
    flags: Mapping[str, Flag],
    *,
    api_root: Path,
    web_root: Path,
    environments_doc: Path | None,
) -> list[str]:
    """Everything wrong with how the code reads flags and how the inventory lists them; empty when all is well.

    `environments_doc=None` skips the inventory check, so a synthetic tree in a test need not carry a document.
    """
    python_reads = scan_python_reads(api_root)
    web_reads = scan_web_reads(web_root)
    problems = _read_problems(python_reads, flags, "python") + _read_problems(web_reads, flags, "web")

    # A flag nothing reads is dead weight (and a variable set for it does nothing), so each declared surface needs
    # at least one read (check 2).
    read_on = {
        "python": {r.name for r in python_reads if r.name},
        "web": {r.name for r in web_reads if r.name},
    }
    for flag in flags.values():
        for surface in flag.surfaces:
            if flag.name not in read_on[surface]:
                problems.append(f"{flag.name!r} is registered for {surface} but nothing on that surface reads it")

    if environments_doc is not None:
        listed = inventory_variables(environments_doc)
        if listed is None:
            problems.append(f"{environments_doc.name} has lost its {INVENTORY_START} / {INVENTORY_END} markers")
        else:
            expected = {env_key(flag.name) for flag in flags.values()}
            for variable in sorted(expected - listed):
                problems.append(f"{variable} is a registered flag's variable but is missing from the inventory")
            for variable in sorted(listed - expected):
                problems.append(f"{variable} is in the inventory but no registered flag has that variable")
    return problems


# --- The command line ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List, evaluate and check the feature-flag registry.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--effective", action="store_true", help="this process's values and where each came from")
    mode.add_argument("--check", action="store_true", help="the hygiene checks; exit 1 on any problem")
    mode.add_argument("--write-ts", action="store_true", help="regenerate apps/calendar/lib/flag-registry.ts")
    args = parser.parse_args(argv)

    if args.write_ts:
        TS_OUT.write_text(render_ts(FLAGS))
        print(f"Wrote {TS_OUT}")
        return 0
    if args.effective:
        try:
            print(effective_report(FLAGS, os.environ))
        except ValueError as err:
            print(f"cannot evaluate: {err}", file=sys.stderr)
            return 1
        return 0
    if args.check:
        problems = hygiene_problems(FLAGS, api_root=API_ROOT, web_root=WEB_ROOT, environments_doc=ENVIRONMENTS_DOC)
        # The committed TypeScript must match the registry too; `make contract-check` also catches this in CI.
        if not TS_OUT.exists() or TS_OUT.read_text() != render_ts(FLAGS):
            problems.append(f"{TS_OUT.relative_to(REPO_ROOT)} is stale: run `make types`")
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        print(f"{len(FLAGS)} feature flag(s) registered; every read is registered, every flag is read.")
        return 0
    print(registry_table(FLAGS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
