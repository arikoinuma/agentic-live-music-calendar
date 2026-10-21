#!/usr/bin/env python3
"""List bare designations (D5, K2, PR1-3, ...) in the lines a branch adds.  # designation-ok

Why this exists: a designation is a short ID that points at a decision, a key point or a review item, and the same
ID means different things in different plans (docs/dev/conventions.md). Inside the plan that defines it a bare ID is
fine. Everywhere else (code, tests, comments, every other document) it must carry its scope, `A5-D7`, or nobody can
tell which plan `D7` means (designation-ok). A5's first build wrote about a hundred bare ones in comments, so this check runs on
what a branch ADDS, not on the whole repo, where older code still has known exceptions.  # designation-ok

    python3 scripts/check_designations.py <base-ref>      (or: make designation-check BASE=<base-ref>)

`base-ref` is the commit before the work began: for a milestone, the diff base its Implementation log names. (With none
given it falls back to the merge-base with `origin/main`, which is only right when the branch is one milestone: milestone
branches here are merged one after another, so `main` can be far behind.) It looks at committed, uncommitted and new
(untracked) files. Exit status 1 if it finds any, with file:line and the line. Skipped on purpose:

* files under docs/dev/implementations/: a plan file is the document that defines its own IDs, so bare is correct there;
* the files that explain the convention with bare examples: AGENTS.md, docs/dev/conventions.md and .claude/;
* `G<n>` in docs/dev/alpha-build-plan.md (the catalogue is bare inside the build plan, `v0.1-G<n>` elsewhere);
* generated and binary files, and lines carrying `noqa`, `type: ignore` or `designation-ok` (an ID-shaped token that is
  not a designation, such as a ruff rule code or "S3"; add `designation-ok` to the line to silence a false hit).
"""

import re
import subprocess
import sys

TEXT = (".py", ".md", ".sql", ".ts", ".tsx", ".sh", ".yml", ".yaml", ".toml", ".mdc")
SKIP_PREFIXES = ("docs/dev/implementations/", "apps/calendar/lib/fixtures/", ".claude/", "docs/dev/conventions.md")
SKIP_FILES = ("AGENTS.md", "CLAUDE.md")  # any directory: these files EXPLAIN the convention, with bare examples
SKIP_NAMES = ("api-types.ts", "uv.lock", "pnpm-lock.yaml")
# A bare designation: a letter code and a number not preceded by a scope (a letter, digit, dot, dash or underscore).
BARE = re.compile(r"(?<![A-Za-z0-9._-])((?:D|E|F|S|G|K)\d+|(?:PR|CR)\d+-\d+)(?![0-9A-Za-z])")
OK_MARKERS = ("noqa", "type: ignore", "designation-ok")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def base_ref() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for candidate in ("origin/main", "main"):
        merged = git("merge-base", "HEAD", candidate).strip()
        if merged:
            return merged
    return "HEAD"


def added_lines(base: str) -> dict[str, list[tuple[int, str]]]:
    """{path: [(line number, text)]} for every line added since `base`, tracked or not."""
    found: dict[str, list[tuple[int, str]]] = {}
    path, number = "", 0
    for line in git("diff", "-U0", "--no-color", base, "--").splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            found.setdefault(path, []).append((number, line[1:]))
            number += 1
    for path in git("ls-files", "--others", "--exclude-standard").split():
        try:
            lines = open(path, encoding="utf-8").read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        found[path] = list(enumerate(lines, start=1))
    return found


def main() -> int:
    hits = 0
    for path, lines in sorted(added_lines(base_ref()).items()):
        if not path.endswith(TEXT) or path.startswith(SKIP_PREFIXES) or path.rsplit("/", 1)[-1] in SKIP_NAMES + SKIP_FILES:
            continue
        for number, text in lines:
            if any(marker in text for marker in OK_MARKERS):
                continue
            for match in BARE.finditer(text):
                if path == "docs/dev/alpha-build-plan.md" and match.group(1).startswith("G"):
                    continue
                print(f"{path}:{number}: bare {match.group(1)}: {text.strip()[:140]}")
                hits += 1
    if hits:
        print(
            f"\n{hits} bare designation(s). Write the scoped form (A5-D7, A5-K2, A5-PR1-3, A5-CR1-4, A3-D9, v0.1-G6): "
            "see docs/dev/conventions.md. Add `designation-ok` to a line that is not a designation.",
            file=sys.stderr,
        )
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
