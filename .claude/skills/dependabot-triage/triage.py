"""Helpers for the `dependabot-triage` skill: turn raw alert data into a triage summary.

Three subcommands, all read-only and standard-library only (run with `python3 -I` so a
stray `json.py` in the working directory can't shadow the real module):

    triage.py fetch alerts.tsv          # export the open alerts with `gh`; exit 3 if gh has no access
    triage.py summarize alerts.tsv      # what the alerts are, grouped for decision-making
    triage.py chains pnpm-audit.json    # which direct dependency drags each vulnerable npm package in

Reading order: `fetch` (get the data, or learn we can't) -> `parse_alerts` -> `summarize` (the
report) -> `chains` (root causes).

Why this exists. A repo with ~120 open alerts is unreadable as a flat list, but almost all of
them collapse into a handful of root causes (one framework pinned in three places, one CLI tool
with a deep dependency tree, one transitive library with a dozen advisories). The skill's job is
to make that collapse visible quickly and the same way every time. See SKILL.md for the workflow.

Input format for `summarize`: one alert per line, whitespace- or tab-separated, exactly what the
`gh api` command in SKILL.md prints:

    <number> <severity> <package> <scope> <manifest path>

Blank lines and lines that don't start with an integer (headers, shell noise) are skipped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Exit codes of `fetch`. The skill branches on these, so they are part of its contract.
EXIT_OK = 0
EXIT_ERROR = (
    1  # gh failed for some reason other than access (network, rate limit, bad repo)
)
EXIT_NO_ACCESS = 3  # gh has no right to read alerts: re-run where the user is logged in
EXIT_NO_GH = 4  # gh is not installed

# The jq filter that turns the API's JSON into the five columns `parse_alerts` expects.
# Only open alerts: fixed and dismissed ones are history, not work.
ALERTS_JQ = (
    '.[]|select(.state=="open")|[.number,.security_advisory.severity,'
    ".dependency.package.name,.dependency.scope,.dependency.manifest_path]|@tsv"
)

# Highest first, so every table reads "worst at the top".
SEVERITIES = ("critical", "high", "medium", "low")

# Dependabot reports the Python lockfile by path; anything else here is an npm manifest.
# (If a new ecosystem is added to .github/dependabot.yml, extend this mapping.)
PYTHON_MANIFEST_SUFFIXES = ("uv.lock", "requirements.txt", "pyproject.toml")


# --- fetch --------------------------------------------------------------------------------


def fetch(out_path: Path, repo: str) -> int:
    """Export the open alerts to `out_path` with `gh`, or say plainly that we have no access.

    Why this is a subcommand and not a line in SKILL.md: the one thing the skill must do
    differently depending on the outcome is stop when access is missing, so the outcome
    needs to be a number a script can't misread, not prose to interpret.

    Access is missing in cloud sessions: their token is a GitHub App installation token
    without the `vulnerability_alerts: read` permission, so GitHub answers 403 (see
    docs/dev/notes.md). On a developer's machine `gh` carries the user's own login and works.
    A 401 means `gh` isn't logged in at all, and has the same remedy.
    """
    try:
        proc = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/dependabot/alerts",
                "--paginate",
                "-q",
                ALERTS_JQ,
            ],
            # Not `check=True`: a non-zero exit is an expected answer here, and which kind
            # (no access vs. some other failure) is decided below from gh's message.
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        print("`gh` is not installed in this environment.", file=sys.stderr)
        return EXIT_NO_GH

    if proc.returncode != 0:
        # `gh` prints e.g. "gh: Resource not accessible by integration (HTTP 403)".
        status_403_or_401 = "HTTP 403" in proc.stderr or "HTTP 401" in proc.stderr
        print(proc.stderr.strip(), file=sys.stderr)
        return EXIT_NO_ACCESS if status_403_or_401 else EXIT_ERROR

    out_path.write_text(proc.stdout)
    rows = parse_alerts(proc.stdout)
    print(f"Wrote {len(rows)} open alerts to {out_path}")
    return EXIT_OK


# --- parsing ------------------------------------------------------------------------------


def parse_alerts(text: str) -> list[dict]:
    """Parse the export into dicts, skipping anything that isn't a well-formed alert row.

    Package names are lower-cased: Dependabot reports the same PyPI package as `PyJWT`,
    `pyjwt` and `pyJWT` depending on the advisory, and grouping on the raw spelling would
    split one root cause into three rows.
    """
    alerts = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        number, severity, package, scope, manifest = parts[:5]
        alerts.append(
            {
                "number": int(number),
                "severity": severity.lower(),
                "package": package.lower(),
                "scope": scope.lower(),
                "manifest": manifest,
            }
        )
    return alerts


def ecosystem(manifest: str) -> str:
    """Name the ecosystem a manifest belongs to, for grouping the package table."""
    return "python" if manifest.endswith(PYTHON_MANIFEST_SUFFIXES) else "npm"


def severity_cells(counter: Counter) -> list[str]:
    """One table cell per severity, in SEVERITIES order ('-' when there are none)."""
    return [str(counter[s]) if counter[s] else "-" for s in SEVERITIES]


# --- summarize ----------------------------------------------------------------------------


def summarize(alerts: list[dict]) -> str:
    """Render the triage report as markdown (so it can be pasted straight into a PR or chat)."""
    out: list[str] = []
    total = len(alerts)
    by_sev = Counter(a["severity"] for a in alerts)
    out.append(
        f"## Totals\n\n**{total} open alerts**: "
        + ", ".join(f"{by_sev[s]} {s}" for s in SEVERITIES)
    )

    # Alert numbers are never reused, so a hole in 1..max is an alert that was fixed or
    # dismissed. Listing the holes lets a reader reconcile this export against the number
    # on GitHub's Security tab (which counts only open ones).
    numbers = {a["number"] for a in alerts}
    holes = sorted(set(range(1, max(numbers) + 1)) - numbers) if numbers else []
    if holes:
        out.append(
            f"\nMissing numbers (already fixed or dismissed): {', '.join(f'#{n}' for n in holes)}"
        )

    # --- by manifest ---
    out.append(
        "\n## By manifest\n\n| Manifest | Total | Crit | High | Med | Low |\n|---|---|---|---|---|---|"
    )
    manifests = defaultdict(Counter)
    for a in alerts:
        manifests[a["manifest"]][a["severity"]] += 1
    for manifest, c in sorted(manifests.items(), key=lambda kv: -sum(kv[1].values())):
        out.append(
            f"| `{manifest}` | {sum(c.values())} | "
            + " | ".join(severity_cells(c))
            + " |"
        )

    # --- by scope ---
    # Reported for completeness, but do NOT triage by it: Dependabot labels a package
    # "runtime" if it is reachable from a `dependencies` entry, so a build/scaffolding CLI
    # listed under `dependencies` makes all of its tree "runtime". SKILL.md explains.
    scopes = Counter(a["scope"] for a in alerts)
    out.append("\n## By scope (Dependabot's label; see SKILL.md before trusting it)\n")
    out.append(", ".join(f"{n} {s}" for s, n in scopes.most_common()))

    # --- by package, split by ecosystem ---
    for eco in ("npm", "python"):
        rows = defaultdict(lambda: {"sev": Counter(), "manifests": set()})
        for a in alerts:
            if ecosystem(a["manifest"]) == eco:
                rows[a["package"]]["sev"][a["severity"]] += 1
                rows[a["package"]]["manifests"].add(a["manifest"])
        if not rows:
            continue
        eco_total = sum(sum(r["sev"].values()) for r in rows.values())
        out.append(f"\n## {eco} packages ({eco_total} alerts)\n")
        out.append(
            "| Package | Alerts | Crit | High | Med | Low | Manifests |\n|---|---|---|---|---|---|---|"
        )
        for package, r in sorted(
            rows.items(), key=lambda kv: -sum(kv[1]["sev"].values())
        ):
            n_manifests = len(r["manifests"])
            # Dependabot raises one alert per advisory PER MANIFEST, so a package pinned in
            # N manifests shows each advisory N times. Flag it: one upgrade closes all N.
            manifest_note = f"×{n_manifests}" if n_manifests > 1 else "1"
            out.append(
                f"| {package} | {sum(r['sev'].values())} | "
                + " | ".join(severity_cells(r["sev"]))
                + f" | {manifest_note} |"
            )

    # --- criticals ---
    criticals = [a for a in alerts if a["severity"] == "critical"]
    out.append(f"\n## Critical alerts ({len(criticals)})\n")
    for a in sorted(criticals, key=lambda a: (a["package"], a["number"])):
        out.append(f"- #{a['number']} `{a['package']}` in `{a['manifest']}`")

    return "\n".join(out)


# --- chains -------------------------------------------------------------------------------


def chains(audit: dict) -> str:
    """Group a `pnpm audit --json` report by the direct dependency that pulls each package in.

    Each finding carries dependency paths like `apps/calendar > shadcn@4.18.0 > hono@4.x`.
    The element after the workspace is the dependency the repo actually chose; upgrading,
    moving or replacing THAT is the lever, while the vulnerable leaf is just where the
    advisory landed. Counting leaves per lever is what turns 80 advisories into 5 decisions.
    """
    advisories = audit.get("advisories", {})
    levers = defaultdict(lambda: {"packages": defaultdict(Counter), "advisories": 0})
    for adv in advisories.values():
        hops = set()
        for finding in adv.get("findings", []):
            for path in finding.get("paths", []):
                parts = [p.strip() for p in path.split(">")]
                # parts[0] is the workspace; a 1-element path is the workspace's own direct
                # dependency (e.g. `next`), which is its own lever.
                hops.add(parts[1] if len(parts) > 1 else parts[0])
        for hop in hops:
            levers[hop]["packages"][adv["module_name"]][adv["severity"]] += 1
            levers[hop]["advisories"] += 1

    out = [
        f"## Levers ({len(advisories)} advisories; an advisory reachable through several levers counts under each)\n"
    ]
    out.append(
        "| Direct dependency | Advisories | Vulnerable packages it brings in |\n|---|---|---|"
    )
    for hop, info in sorted(levers.items(), key=lambda kv: -kv[1]["advisories"]):
        names = ", ".join(
            f"{pkg} ({sum(c.values())})"
            for pkg, c in sorted(
                info["packages"].items(), key=lambda kv: -sum(kv[1].values())
            )
        )
        out.append(f"| `{hop}` | {info['advisories']} | {names} |")
    return "\n".join(out)


# --- CLI ----------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser(
        "fetch",
        help="export open alerts with `gh`; exit 3 means no access (re-run locally)",
    )
    f.add_argument("out", type=Path, help="file to write the alert rows to")
    # `{owner}/{repo}` is gh's own placeholder, filled in from the current git remote, so the
    # default works in any checkout of this repo without hard-coding the name here.
    f.add_argument(
        "--repo",
        default="{owner}/{repo}",
        help="OWNER/REPO (default: this checkout's remote)",
    )
    s = sub.add_parser(
        "summarize", help="summarize a Dependabot alert export (use - for stdin)"
    )
    s.add_argument("file")
    c = sub.add_parser(
        "chains",
        help="group a `pnpm audit --json` report by the direct dependency responsible",
    )
    c.add_argument("file")
    args = parser.parse_args()

    if args.command == "fetch":
        return fetch(args.out, args.repo)

    raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text()
    if args.command == "summarize":
        alerts = parse_alerts(raw)
        if not alerts:
            print(
                "No alert rows found. Expected: <number> <severity> <package> <scope> <manifest>",
                file=sys.stderr,
            )
            return 1
        print(summarize(alerts))
    else:
        print(chains(json.loads(raw)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
