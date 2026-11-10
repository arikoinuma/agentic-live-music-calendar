"""The laptop command that starts a manual worker run against a hosted environment (C8-D3, C8-D14).

WHAT THIS COVERS
  `launch` (scripts/hosted_worker.py) runs `python -m agent_worker.main --trigger manual` on the developer's machine with
  a Railway service's variables loaded into it (`railway run`), so a manual extraction can be started at will on staging
  or production while the schedule is off (Dep-D12). The risk it manages is that it executes the LAPTOP'S CHECKOUT and
  not the deployed image, against a real hosted database: so it refuses unless the tree is clean and `HEAD` is the commit
  the environment deploys, asks for a typed name before touching production, and gives the child a minimal environment
  so nothing in the developer's shell (a `FLAG_*` variable, a stray `DATABASE_URL`) reaches the run.

  Everything outside this process is faked: `git` and `railway` go through injected functions that record each call, so
  these tests need neither a Railway login nor a repository state. What they pin down is the part that has to be right
  every time: which commits are compared, the exact `railway run` command line, what the child's environment contains,
  and that no guard can be skipped.

  Expected command lines are written out here from `railway run --help` (CLI 5.47.1: `-p`, `-s`, `-e`, `--no-local`,
  flags before the child command, `--` before it), not read from the module.
"""

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import hosted_worker
from scripts.hosted_worker import EXIT_REFUSED, GitResult, launch

API_DIR = Path("/repo/apps/api")
WORKDIR = Path("/tmp/hosted-worker-empty-dir")  # an empty directory: the run must not start inside apps/api
SHA = "a" * 40
OTHER = "b" * 40


class FakeGit:
    """Records every git command and answers from a small script, like a repository with a chosen state."""

    def __init__(self, *, dirty: bool = False, head: str = SHA, upstream: str = SHA, fetch_fails: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.dirty = dirty
        self.head = head
        self.upstream = upstream
        self.fetch_fails = fetch_fails

    def __call__(self, args: list[str]) -> GitResult:
        self.calls.append(list(args))
        if args[:2] == ["status", "--porcelain"]:
            return GitResult(0, " M apps/api/agent_worker/main.py\n" if self.dirty else "")
        if args[0] == "fetch":
            return GitResult(1 if self.fetch_fails else 0, "")
        if args == ["rev-parse", "HEAD"]:
            return GitResult(0, self.head + "\n")
        if args[0] == "rev-parse":
            return GitResult(0, self.upstream + "\n")
        raise AssertionError(f"unscripted git call: {args}")


class FakeRun:
    """Records every `railway` launch (argv, environment, directory) and exits with a chosen status."""

    def __init__(self, *, code: int = 0, missing: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.code = code
        self.missing = missing

    def __call__(self, argv: list[str], *, env: dict[str, str], cwd: Path) -> int:
        if self.missing:
            raise FileNotFoundError(argv[0])
        self.calls.append({"argv": list(argv), "env": env, "cwd": cwd})
        return self.code


def go(env: str, git: FakeGit, run: FakeRun, **overrides: Any) -> tuple[int, list[str], list[str]]:
    """Run `launch` with recording fakes; return (exit code, everything said, every prompt shown to the person)."""
    said: list[str] = []
    prompts: list[str] = []
    typed = overrides.pop("typed", "production")

    def confirm(prompt: str) -> str:
        prompts.append(prompt)
        return typed

    options: dict[str, Any] = {
        "project_id": "proj-123",
        "venue": None,
        "git": git,
        "run": run,
        "say": said.append,
        "confirm": confirm,
        "api_dir": API_DIR,
        "workdir": WORKDIR,
        "path": "/usr/bin:/bin",
        "home": "/home/ari",
    }
    options.update(overrides)
    return launch(env, **options), said, prompts


# ---------------------------------------------------------------------------
# The command that runs (C8-D3)
# ---------------------------------------------------------------------------


def test_staging_runs_railway_with_the_pinned_selectors_and_a_manual_trigger() -> None:
    # Proves (C8-D3): the `railway run` command names the project (`-p`), the `worker` service (`-s`) and the Railway
    # environment (`-e staging`), passes `--no-local` (so a docker-compose override cannot change the variables), puts
    # every Railway flag BEFORE `--`, and runs the worker with `--trigger manual` from the API project with `uv`. With
    # no linked project (the run starts in an empty directory) any selector left out would fall back to whatever the CLI
    # defaults to, and the check that Railway's flags and the child's are not mixed up is the position of `--`.
    git, run = FakeGit(), FakeRun()
    code, _, _ = go("staging", git, run)
    assert code == 0
    assert len(run.calls) == 1
    assert run.calls[0]["argv"] == [
        "railway", "run", "-p", "proj-123", "-s", "worker", "-e", "staging", "--no-local", "--",
        "uv", "run", "--project", str(API_DIR), "python", "-m", "agent_worker.main", "--trigger", "manual",
    ]  # fmt: skip


def test_prod_maps_to_railways_environment_named_production() -> None:
    # Proves (C8-D3): `ENV=prod` is this project's name for the environment; Railway calls it `production`, and `-e prod`
    # would be an unknown environment (or, worse, a different one). The mapping is written here from environments.md.
    code, _, _ = go("prod", FakeGit(), run := FakeRun())
    assert code == 0
    argv = run.calls[0]["argv"]
    assert argv[argv.index("-e") + 1] == "production"


def test_a_venue_is_passed_through_and_left_out_when_not_given() -> None:
    # Proves (C8-D3): `VENUE=3` becomes `--venue 3` after the worker's module name, and no `--venue` appears otherwise,
    # so an unset `VENUE` cannot become a run of one venue named "None".
    _, _, _ = go("staging", FakeGit(), with_venue := FakeRun(), venue=3)
    assert with_venue.calls[0]["argv"][-2:] == ["--venue", "3"]
    _, _, _ = go("staging", FakeGit(), without := FakeRun())
    assert "--venue" not in without.calls[0]["argv"]


def test_the_run_starts_in_an_empty_directory_with_a_minimal_environment() -> None:
    # Proves (C8-D3): the child starts in the EMPTY working directory (so `Settings` finds no `apps/api/.env` to load,
    # the lesson of the migration rehearsal, whose first real run printed a key from a developer's .env), and its
    # environment is exactly PATH, HOME and PYTHONPATH (the API directory, so `app` and `agent_worker` import from
    # elsewhere). Nothing else of the developer's shell crosses over, and `railway` adds the service's own variables.
    _, _, _ = go("staging", FakeGit(), run := FakeRun())
    call = run.calls[0]
    assert call["cwd"] == WORKDIR
    assert call["env"] == {"PATH": "/usr/bin:/bin", "HOME": "/home/ari", "PYTHONPATH": str(API_DIR)}


def test_the_workers_own_exit_status_is_the_commands_exit_status() -> None:
    # Proves (C8-D3): a worker that exits 1 (a venue failed) or 2 (a configuration problem) makes this command exit 1 or
    # 2, so a script or a person can tell a failed run from a clean one. The guards use a different status (4), which no
    # worker exits with, so a refusal is never mistaken for a run.
    for worker_code in (0, 1, 2):
        code, _, _ = go("staging", FakeGit(), FakeRun(code=worker_code))
        assert code == worker_code
    assert EXIT_REFUSED not in (0, 1, 2)


# ---------------------------------------------------------------------------
# The guards (C8-D3, C8-PR1-4)
# ---------------------------------------------------------------------------


def test_a_dirty_working_tree_is_refused_and_nothing_runs() -> None:
    # Proves (C8-PR1-4): `railway run` executes the laptop's files, so uncommitted edits would run against a hosted
    # database with code nobody reviewed. The guard refuses before any network call (not even `git fetch`), and says why.
    git, run = FakeGit(dirty=True), FakeRun()
    code, said, _ = go("staging", git, run)
    assert code == EXIT_REFUSED
    assert not run.calls
    assert not any(call[0] == "fetch" for call in git.calls)
    assert any("not clean" in line for line in said)


def test_a_head_that_is_not_the_deployed_branch_is_refused_and_both_commits_are_shown() -> None:
    # Proves (C8-PR1-4): `HEAD` must equal `origin/main` for staging (after a fetch, so a stale local copy of the branch
    # cannot pass). An unmerged branch would otherwise run its own reconcile logic against the real schema. The message
    # shows the two commits, shortened, so the person can see which way they differ.
    git, run = FakeGit(head=OTHER, upstream=SHA), FakeRun()
    code, said, _ = go("staging", git, run)
    assert code == EXIT_REFUSED
    assert not run.calls
    assert ["fetch", "origin", "main"] in git.calls
    assert any(OTHER[:12] in line and SHA[:12] in line and "origin/main" in line for line in said)


def test_production_compares_head_with_origin_production_not_main() -> None:
    # Proves (C8-PR1-4): the branch compared is the one the environment deploys from: `production` for prod (which is
    # often behind `main`: 205 commits on November 9, 2026), `main` for staging. A rule that always compared with `main`
    # would refuse every production run until a promotion, or, if it compared nothing, run unpromoted code on prod.
    git = FakeGit()
    go("prod", git, FakeRun())
    assert ["fetch", "origin", "production"] in git.calls
    assert ["rev-parse", "origin/production"] in git.calls
    assert ["rev-parse", "origin/main"] not in git.calls


def test_a_failed_fetch_is_refused() -> None:
    # Proves (C8-PR1-4): when `git fetch` fails (offline, no access), the comparison would use a stale remote branch, so
    # the run is refused rather than trusting it.
    git, run = FakeGit(fetch_fails=True), FakeRun()
    code, said, _ = go("staging", git, run)
    assert code == EXIT_REFUSED
    assert not run.calls
    assert any("fetch" in line for line in said)


def test_the_commit_that_runs_is_printed() -> None:
    # Proves (C8-PR1-4): before the run starts, the output names the commit (shortened) and the environment, so the
    # log of a manual run says exactly which code produced the rows.
    _, said, _ = go("staging", FakeGit(), FakeRun())
    assert any(SHA[:12] in line and "staging" in line for line in said)


def test_production_asks_for_the_environment_name_and_staging_does_not() -> None:
    # Proves (C8-D3, C8-D14): production needs the Railway environment's name typed, "production", which differs from
    # the `prod` on the command line so it cannot be satisfied by copying the command; staging asks nothing. A typed
    # `prod` or an empty answer is refused and nothing runs. This is the guard a console run does not have (C8-D15).
    for wrong in ("prod", "", "Production!", "staging"):
        run = FakeRun()
        code, _, prompts = go("prod", FakeGit(), run, typed=wrong)
        assert code == EXIT_REFUSED, wrong
        assert not run.calls
        assert len(prompts) == 1
    run = FakeRun()
    code, _, prompts = go("prod", FakeGit(), run, typed="production")
    assert code == 0 and len(run.calls) == 1 and len(prompts) == 1
    _, _, prompts = go("staging", FakeGit(), FakeRun())
    assert prompts == []


def test_the_guards_run_before_the_prompt() -> None:
    # Proves (C8-D3): a dirty tree is refused BEFORE the person is asked to type the production name, so they are not
    # asked to confirm something that will be refused anyway.
    _, _, prompts = go("prod", FakeGit(dirty=True), FakeRun())
    assert prompts == []


@pytest.mark.parametrize("bad", ["dev", "production", "local", "nope", ""])
def test_an_unknown_environment_is_refused_before_anything_runs(bad: str) -> None:
    # Proves (C8-D1): only `staging` and `prod` have a worker service (dev has no Railway environment, C3-D1), so
    # `dev` is refused, and so is Railway's own spelling `production`: the command takes this project's names. Nothing
    # (not even git) is touched.
    git, run = FakeGit(), FakeRun()
    code, said, _ = go(bad, git, run)
    assert code == EXIT_REFUSED
    assert not git.calls and not run.calls
    assert any("staging" in line and "prod" in line for line in said)


def test_a_missing_project_id_is_refused_with_a_clear_message() -> None:
    # Proves (C8-D3): the Railway project id is not a secret but it is required (the run starts in an empty directory,
    # so there is no linked project to default to). Without it the person is told where to put it.
    git, run = FakeGit(), FakeRun()
    code, said, _ = go("staging", git, run, project_id="")
    assert code == EXIT_REFUSED
    assert not git.calls and not run.calls
    assert any("RAILWAY_PROJECT_ID" in line for line in said)


def test_a_missing_railway_cli_is_a_clear_message_not_a_traceback() -> None:
    # Proves (C8-D3): with no `railway` on PATH the person sees how to install it and the exit status is the refusal's.
    code, said, _ = go("staging", FakeGit(), FakeRun(missing=True))
    assert code == EXIT_REFUSED
    assert any("railway" in line.lower() and "install" in line.lower() for line in said)


# ---------------------------------------------------------------------------
# The real launcher and the command line (C8-D3)
# ---------------------------------------------------------------------------


def test_the_real_launcher_gives_the_child_only_the_environment_it_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Proves (C8-D3, C3.1-D11): `run_command` REPLACES the child's environment, it does not add to the parent's. A flag
    # variable exported in the developer's shell (`FLAG_WORKER_SCHEDULED_RUNS`) must not reach the run: flags are read
    # from the process environment only, and `Settings` refuses a misspelled one or lets a stray one decide a scheduled
    # run. Uses a real subprocess (this interpreter), because the bug would be in how the environment is passed.
    monkeypatch.setenv("FLAG_WORKER_SCHEDULED_RUNS", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-leak")
    probe = "import os, sys; sys.exit(7 if 'FLAG_WORKER_SCHEDULED_RUNS' in os.environ or 'DATABASE_URL' in os.environ else 0)"
    code = hosted_worker.run_command(
        [sys.executable, "-c", probe], env={"PATH": os.environ.get("PATH", "")}, cwd=tmp_path
    )
    assert code == 0


def test_main_takes_the_project_id_from_the_option_or_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves (C8-D3): `--project-id` wins over `RAILWAY_PROJECT_ID`, and either is enough; the same value reaches
    # `launch`. A stand-in `launch` records its arguments, so no git or railway is involved.
    seen: list[dict[str, Any]] = []

    def fake_launch(env: str, **kwargs: Any) -> int:
        seen.append({"env": env, **kwargs})
        return 0

    monkeypatch.setattr(hosted_worker, "launch", fake_launch)
    assert (
        hosted_worker.main(
            ["staging", "--venue", "5"], environ={"RAILWAY_PROJECT_ID": "from-shell", "PATH": "/x", "HOME": "/h"}
        )
        == 0
    )
    assert (
        hosted_worker.main(["prod", "--project-id", "from-option"], environ={"RAILWAY_PROJECT_ID": "from-shell"}) == 0
    )
    assert (seen[0]["env"], seen[0]["project_id"], seen[0]["venue"]) == ("staging", "from-shell", 5)
    assert (seen[1]["env"], seen[1]["project_id"], seen[1]["venue"]) == ("prod", "from-option", None)
    assert seen[0]["path"] == "/x" and seen[0]["home"] == "/h"
