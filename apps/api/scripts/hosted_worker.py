"""Start a manual worker run against a hosted environment, from the developer's laptop (C8-D3).

Run, from the repository root:   make worker-hosted ENV=staging VENUE=3
or from apps/api:                uv run python -m scripts.hosted_worker staging [--venue 3]

WHAT IT IS: Railway's own "run now" control starts a service's configured start command, which for the worker is the
gated `--trigger scheduled`, and it cannot pass `--trigger manual` or `--venue`. This is the other way (Dep-D12):
`railway run` executes a LOCAL command with a Railway service's variables loaded into it, so the pipeline runs on this
machine against the hosted databases and model provider, recorded as `trigger='manual'`, which ignores the feature flag
`worker.scheduled_runs` and so works while the schedule is off. A run inside Railway's own container, which also
exercises the image and Railway's network, is typed in the service's console instead (C8-D15, `environments.md`).

THE RISK AND THE GUARDS: `railway run` executes whatever is checked out on THIS machine, not the deployed image, against
a real database. So, before it starts anything:
  1. the working tree must be clean (no uncommitted or untracked files);
  2. after a `git fetch`, `HEAD` must be the commit the environment deploys from: `origin/main` for staging,
     `origin/production` for prod (C8-PR1-4); the commit is printed;
  3. for prod, the person must type the Railway environment's name, `production`, which differs from the `prod` on the
     command line so it cannot be satisfied by copying the command (C8-D14).
The child runs in an EMPTY temporary directory with exactly PATH, HOME and PYTHONPATH from this shell (`railway` adds the
service's own variables), so a developer's `apps/api/.env`, a `FLAG_*` variable exported in the shell (flags are read
from the process environment only, C3.1-D11) or a stray `DATABASE_URL` cannot reach the run. Same approach as
`scripts/rehearse_migration.py`, whose first real run printed a key from a developer's `.env`.

WHAT YOU NEED: the Railway CLI, signed in (`railway login`); the project id (`--project-id`, or RAILWAY_PROJECT_ID in
the shell: it is not a secret); `uv`; a clean checkout of the branch the environment deploys from. The service must be
called `worker` in each Railway environment (`environments.md`, "The worker on Railway (C8)").

EXIT STATUS: the child's own, which is the worker's when the worker ran (0 clean, 1 at least one venue failed, 2 a
configuration problem such as an unreachable MongoDB) and the Railway CLI's own when `railway run` failed before starting it
(not signed in, an unknown project, service or environment): a 1 can mean either, and the printed output tells them apart.
4 means a guard refused or the CLI is missing, a status no worker exits with.

HOW THIS FILE IS ORGANISED: the logic takes the outside world as arguments (`git` runs a git command and returns its
output, `run` starts the child and returns its exit status, `say` prints, `confirm` asks the person to type), so
`scripts/tests/test_hosted_worker.py` runs the whole sequence with no Railway account; the command-line entry point at
the bottom supplies the real ones. It lives in `scripts/` because it is a development chore, not part of the service.

docs/dev/implementations/c8-worker-on-railway.md, C8-D1, C8-D3, C8-D14, C8-PR1-3, C8-PR1-4.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# The environments that have a worker service (C8-D1: staging and production now, dev when it has an API). The key is
# this project's name for the environment; the value is the branch it deploys from, and Railway's name for it.
BRANCH_FOR_ENV = {"staging": "main", "prod": "production"}
RAILWAY_ENV = {"staging": "staging", "prod": "production"}
# The Railway service every environment's worker runs as (environments.md, "The worker on Railway (C8)").
SERVICE = "worker"

# Exit status for "a guard refused, or the CLI is missing". The worker exits 0, 1 or 2, so this can never be mistaken
# for a run's result.
EXIT_REFUSED = 4

# apps/api, and the repository root, whatever directory the script was started from.
API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]


@dataclass(frozen=True)
class GitResult:
    """What a git command left behind: its exit status and what it printed."""

    returncode: int
    stdout: str


class Git(Protocol):
    """Runs `git <args>` in the repository and returns the result."""

    def __call__(self, args: list[str]) -> GitResult: ...


class Run(Protocol):
    """Starts the child with EXACTLY this environment (it replaces the parent's) and returns its exit status."""

    def __call__(self, argv: list[str], *, env: dict[str, str], cwd: Path) -> int: ...


def launch(
    env: str,
    *,
    project_id: str,
    venue: int | None,
    git: Git,
    run: Run,
    say: Callable[[str], None],
    confirm: Callable[[str], str],
    api_dir: Path,
    workdir: Path,
    path: str,
    home: str,
) -> int:
    """Run the guards, then start the manual worker through `railway run`; return the exit status (see EXIT_REFUSED).

    `workdir` is an EMPTY directory the child starts in; `path` and `home` are the only variables taken from the
    caller's shell.
    """
    # Everything that can be refused without touching git or Railway is refused first, so a typo costs nothing.
    if env not in BRANCH_FOR_ENV:
        say(
            f"Refused: {env!r} has no worker service; choose one of {', '.join(BRANCH_FOR_ENV)} (dev has no Railway environment yet)"
        )
        return EXIT_REFUSED
    if not project_id:
        say(
            "Refused: give the Railway project with --project-id or RAILWAY_PROJECT_ID in the shell (the id is not a secret)"
        )
        return EXIT_REFUSED

    # Guard 1 and 2: the code about to run is the code the environment deploys. A dirty tree is checked before the
    # fetch, so a refusal needs no network.
    branch = BRANCH_FOR_ENV[env]
    if git(["status", "--porcelain"]).stdout.strip():
        say(
            "Refused: the working tree is not clean. Commit or stash first: this runs the files on this machine, not the deployed image."
        )
        return EXIT_REFUSED
    if git(["fetch", "origin", branch]).returncode != 0:
        say(f"Refused: `git fetch origin {branch}` failed, so HEAD cannot be compared with what {env} deploys.")
        return EXIT_REFUSED
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    deployed = git(["rev-parse", f"origin/{branch}"]).stdout.strip()
    if head != deployed:
        say(
            f"Refused: HEAD ({head[:12]}) is not origin/{branch} ({deployed[:12]}). "
            f"Check out {branch} at the deployed commit first: this runs the files on this machine."
        )
        return EXIT_REFUSED
    say(f"Running commit {head[:12]} (origin/{branch}) against {env}, Railway environment {RAILWAY_ENV[env]!r}.")

    # Guard 3: production is typed out. After the other guards, so nobody is asked to confirm a run that is refused.
    if env == "prod":
        typed = confirm("This writes to PRODUCTION. Type the Railway environment's name, 'production', to go on: ")
        if typed.strip() != "production":
            say("Refused: not confirmed.")
            return EXIT_REFUSED

    # Railway's flags come BEFORE `--`; after it everything is the child's command (`railway run --help`, CLI 5.47.1).
    # `-p` is needed because the run starts in an empty directory, where no project is linked; `--no-local` skips any
    # docker-compose override of the variables. The child is the worker, run with the API project's environment.
    argv = ["railway", "run", "-p", project_id, "-s", SERVICE, "-e", RAILWAY_ENV[env], "--no-local", "--"]
    argv += ["uv", "run", "--project", str(api_dir), "python", "-m", "agent_worker.main", "--trigger", "manual"]
    if venue is not None:
        argv += ["--venue", str(venue)]
    child_env = {"PATH": path, "HOME": home, "PYTHONPATH": str(api_dir)}
    try:
        return run(argv, env=child_env, cwd=workdir)
    except FileNotFoundError:
        say(
            "Refused: the `railway` CLI was not found. Install it (`brew install railway` or `npm i -g @railway/cli`), then `railway login`."
        )
        return EXIT_REFUSED


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def run_git(args: list[str]) -> GitResult:
    """Run a real git command in the repository (a list, no shell)."""
    git = shutil.which("git") or "git"
    done = subprocess.run(  # noqa: S603 - argv is a fixed list built in `launch`, run without a shell
        [git, "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=False
    )
    return GitResult(done.returncode, done.stdout)


def run_command(argv: list[str], *, env: dict[str, str], cwd: Path) -> int:
    """Start the child with exactly `env` (the parent's variables are NOT inherited) and let it print live."""
    return subprocess.run(argv, env=env, cwd=cwd, check=False).returncode  # noqa: S603 - a list, no shell


def main(argv: list[str], environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="Start a manual worker run against a hosted environment.")
    parser.add_argument("env", help="staging or prod (anything else is refused)")
    parser.add_argument("--venue", type=int, help="run only this venue id (default: every venue)")
    parser.add_argument(
        "--project-id", default=environ.get("RAILWAY_PROJECT_ID"), help="Railway project id (or RAILWAY_PROJECT_ID)"
    )
    args = parser.parse_args(argv)

    # The child starts in a fresh EMPTY directory so `Settings` finds no `.env` (see the module docstring).
    with tempfile.TemporaryDirectory(prefix="hosted-worker-") as workdir:
        return launch(
            args.env,
            project_id=args.project_id or "",
            venue=args.venue,
            git=run_git,
            run=run_command,
            say=print,
            confirm=input,
            api_dir=API_DIR,
            workdir=Path(workdir),
            path=environ.get("PATH", ""),
            home=environ.get("HOME", ""),
        )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
