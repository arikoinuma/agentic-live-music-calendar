"""Tests that pin the worker's container image to what C8 decided, without building it (C8-D2, C8-D4, C8-D10, C8-D15).

HOW TO READ THIS
  The worker runs on Railway from `apps/api/Dockerfile.worker`. A Docker build is slow and needs a daemon, so CI builds
  the image in its own job (`worker-image`, below) and these tests read the Dockerfile and `.dockerignore` as TEXT. They
  pin the decisions whose failure is silent:

    * The file is named `Dockerfile.worker`, and NO file named `Dockerfile` exists beside it (C8-D10). Railway builds a
      service with a Dockerfile whenever it finds one named exactly `Dockerfile` in the service's root directory. The
      API service is rooted at `apps/api` and builds with Railway's default builder today, so a stray `Dockerfile`
      there would change how the API is built and deployed, with no error to say so (C8-U3).
    * `.dockerignore` keeps `.env` and `.venv` out of the image (C8-D10): `Settings` reads a `.env` it finds, so one
      baked into an image would hand a laptop's values to a hosted process; `.venv` is 392 MB of the wrong platform.
    * The container starts the GATED command (C8-D4): `--trigger scheduled`, so a deploy that Railway runs on its own
      (C8-U1) is a logged skip. It calls `python` directly and not through `uv run`, and puts the virtual environment on
      `PATH` with `WORKDIR /app`, because a shell opened in a Railway console gets no tool paths of its own (observed on
      the staging API service, C8-D15): `python -m agent_worker.main --trigger manual` must work there as typed.
    * The base image and `uv` are pinned (C8-D2): the Python version follows `.python-version`, `uv` is an exact version.

  Expected values come from the plan and from the repository's own files (`.python-version`), never from the
  Dockerfile under test. Whether the image BUILDS and imports is the CI job's proof, not these tests'.
"""

import re
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = API_DIR / "Dockerfile.worker"
DOCKERIGNORE = API_DIR / ".dockerignore"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def instructions(path: Path) -> list[tuple[str, str]]:
    """The Dockerfile as (INSTRUCTION, arguments) pairs: comments and blanks dropped, `\\` continuations joined."""
    joined: list[str] = []
    pending = ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1].strip() + " "
            continue
        joined.append((pending + line).strip())
        pending = ""
    assert not pending, "a Dockerfile ends in the middle of a continued line"
    pairs = []
    for line in joined:
        word, _, rest = line.partition(" ")
        pairs.append((word.upper(), rest.strip()))
    return pairs


def lines_of(path: Path) -> set[str]:
    """The non-comment, non-blank lines of an ignore file."""
    return {ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")}


# ---------------------------------------------------------------------------
# The file name (C8-D10)
# ---------------------------------------------------------------------------


def test_no_file_named_dockerfile_exists_in_the_api_directory() -> None:
    # Proves (C8-D10, C8-U3): `apps/api` holds no file named `Dockerfile` (any case). Railway auto-detects exactly that
    # name, so adding one would silently switch the API service from its default builder to a Docker build. The worker
    # image is `Dockerfile.worker`, selected on the worker service by `RAILWAY_DOCKERFILE_PATH`.
    names = {p.name.lower() for p in API_DIR.iterdir()}
    assert "dockerfile" not in names


def test_the_worker_dockerfile_and_ignore_file_exist() -> None:
    # Proves (C8-D10): the two files the rest of these tests read are where Railway (Root Directory `apps/api`) will
    # look, so a rename or a move fails here and not on the first deploy.
    assert DOCKERFILE.is_file()
    assert DOCKERIGNORE.is_file()


# ---------------------------------------------------------------------------
# The base image and uv (C8-D2)
# ---------------------------------------------------------------------------


def test_the_base_image_is_the_slim_python_the_project_pins() -> None:
    # Proves (C8-D2): the base is `python:<version>-slim` with the version in `.python-version` (3.13), so the image and
    # the lockfile's interpreter cannot drift apart, and it is not the 1.2 GB browser image the deployment plan first
    # proposed (nothing in the worker drives a browser). Expected version is read from `.python-version`.
    wanted = (API_DIR / ".python-version").read_text().strip()
    froms = [args for word, args in instructions(DOCKERFILE) if word == "FROM"]
    assert froms == [f"python:{wanted}-slim"]


def test_uv_is_copied_from_its_image_at_an_exact_version() -> None:
    # Proves (C8-D2): `uv` comes from Astral's image at a full `major.minor.patch` tag, not `latest` or a minor range,
    # so a build next month installs with the tool this one did. (The image never runs `uv` at start: see the CMD test.)
    copies = [args for word, args in instructions(DOCKERFILE) if word == "COPY" and "--from=" in args]
    assert len(copies) == 1
    assert re.match(r"--from=ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+ /uv ", copies[0])


# ---------------------------------------------------------------------------
# Environment, layers and what is copied (C8-D2, C8-D10)
# ---------------------------------------------------------------------------


def env_values() -> dict[str, str]:
    """Every `ENV` assignment in the Dockerfile as {name: value}, whether written `A=1 B=2` or on several lines."""
    values: dict[str, str] = {}
    for word, args in instructions(DOCKERFILE):
        if word != "ENV":
            continue
        for name, value in re.findall(r'(\w+)=("[^"]*"|\S+)', args):
            values[name] = value.strip('"')
    return values


def test_the_virtual_environment_is_on_path_and_the_workdir_is_app() -> None:
    # Proves (C8-D15): `WORKDIR /app` and `/app/.venv/bin` leading `PATH`, so a shell opened in a Railway console (which
    # gets no tool paths: `python` and `uv` were "command not found" in the staging API's console) runs
    # `python -m agent_worker.main --trigger manual --venue 3` exactly as typed. `uv sync` writes the environment to
    # `.venv` under the project directory, which is `/app` here.
    assert ("WORKDIR", "/app") in instructions(DOCKERFILE)
    path = env_values()["PATH"]
    assert path.split(":")[0] == "/app/.venv/bin"
    assert "$PATH" in path.split(":")


def test_python_output_is_unbuffered_and_no_second_interpreter_is_downloaded() -> None:
    # Proves (C8-D3, C8-D2): `PYTHONUNBUFFERED=1` so a log line reaches Railway as it is written (a crash would
    # otherwise lose the buffered tail, and a run could look silent); `UV_PYTHON_DOWNLOADS=never` so a version mismatch
    # fails the build instead of quietly downloading another Python; `UV_COMPILE_BYTECODE=1` so a cron start does not
    # spend its first seconds compiling.
    env = env_values()
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["UV_PYTHON_DOWNLOADS"] == "never"
    assert env["UV_COMPILE_BYTECODE"] == "1"


def test_dependencies_are_installed_from_the_lockfile_before_the_source_is_copied() -> None:
    # Proves (C8-D2): the dependency layer is built from `pyproject.toml` and `uv.lock` alone, with `--frozen` (the
    # lockfile decides, nothing is re-resolved), `--no-dev` (no test tools in the image), `--no-install-project`, and
    # `--no-cache` (uv's cache stays out of the image), and it comes BEFORE `app/` and `agent_worker/` are copied, so a
    # code-only change reuses the cached layer instead of reinstalling about 140 packages on every Railway build.
    steps = instructions(DOCKERFILE)
    sync = next(i for i, (w, a) in enumerate(steps) if w == "RUN" and a.startswith("uv sync"))
    flags = steps[sync][1]
    for flag in ("--frozen", "--no-dev", "--no-install-project", "--no-cache"):
        assert flag in flags
    source = next(i for i, (w, a) in enumerate(steps) if w == "COPY" and a.startswith("app"))
    assert sync < source


def test_only_the_code_the_worker_runs_is_copied() -> None:
    # Proves (C8-D10): the image holds `app/` and `agent_worker/` and the three files `uv sync` needs, and nothing
    # else. A `COPY . .` would bring in `.env`, `.venv` and the captured venue pages unless the ignore file caught
    # them, so the rule is stated twice: here, and in `.dockerignore`. Each source also has to exist in the repo.
    allowed = {"pyproject.toml", "uv.lock", ".python-version", "app", "agent_worker"}
    sources: set[str] = set()
    for word, args in instructions(DOCKERFILE):
        if word == "COPY" and "--from=" not in args:
            *srcs, _dest = args.split()
            sources.update(s.rstrip("/") for s in srcs)
    assert sources == allowed
    for name in sources:
        assert (API_DIR / name).exists(), name


def test_the_image_never_runs_migrations() -> None:
    # Proves (C8-D9): the worker image contains no Alembic invocation. Only the API migrates (its pre-deploy command),
    # because the API and the worker do not redeploy together (arch-initial.md section 5); a worker that migrated on
    # start could race the API's pre-deploy or run an unreviewed migration against production.
    assert "alembic" not in DOCKERFILE.read_text().lower()


# ---------------------------------------------------------------------------
# What the container starts (C8-D4, C8-D15)
# ---------------------------------------------------------------------------


def test_the_container_command_is_the_gated_scheduled_run_called_directly() -> None:
    # Proves (C8-D4, C8-D15): the one `CMD` is `python -m agent_worker.main --trigger scheduled` in exec form. Scheduled,
    # because that is the trigger the feature flag gates (C3.1-D13): under C8-U1 any deploy may start the command, and
    # with the flag off that run is a logged skip. Called directly, not through `uv run`, which would sync the
    # environment at every start (and needs `uv` on a PATH the container does not guarantee).
    commands = [args for word, args in instructions(DOCKERFILE) if word == "CMD"]
    assert commands == ['["python", "-m", "agent_worker.main", "--trigger", "scheduled"]']
    assert not [1 for word, _ in instructions(DOCKERFILE) if word == "ENTRYPOINT"]


# ---------------------------------------------------------------------------
# The ignore file (C8-D10)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        ".env",
        ".env.*",
        ".venv",
        "agent_worker/model_eval/captured_pages",
        "agent_worker/model_eval/results",
    ],
)
def test_the_ignore_file_excludes_secrets_the_venv_and_the_eval_data(entry: str) -> None:
    # Proves (C8-D10): `.env` (and any `.env.*`) never enters the image, so `Settings` cannot read a laptop's values on
    # Railway; `.venv` (392 MB, the wrong platform) and the eval harness's captured pages and results (37 MB and 51 MB,
    # not needed at run time) are not sent to the build. The ignore file applies to the build context, so it protects
    # even a future `COPY . .`.
    assert entry in lines_of(DOCKERIGNORE)


def test_the_ignored_eval_paths_are_still_where_the_ignore_file_says() -> None:
    # Proves (C8-D10): the eval harness directory the ignore entries name exists, so a relayout like C5.1's (which moved
    # these files once) fails here instead of leaving an ignore entry that matches nothing and ships 90 MB.
    assert (API_DIR / "agent_worker" / "model_eval").is_dir()


# ---------------------------------------------------------------------------
# The CI job (C8-D2)
# ---------------------------------------------------------------------------


def test_ci_builds_the_worker_image_and_runs_it() -> None:
    # Proves (C8-D2, C8-D4): CI has a `worker-image` job that builds `Dockerfile.worker` from `apps/api` and runs
    # `python -m agent_worker.main --help` in the result, with bare `python` (so a missing `PATH` entry fails in CI and
    # not in a Railway console). A text check, not a YAML parse: it fails if the job is deleted or renamed, which would
    # otherwise let an image that cannot build or import be found first by Railway.
    text = CI_WORKFLOW.read_text()
    assert "\n  worker-image:" in text
    assert "docker build" in text and "Dockerfile.worker" in text
    assert "python -m agent_worker.main --help" in text
    # ...and runs the container's own (scheduled) command with the flag unset, expecting the logged skip (C3.1-D13).
    assert "scheduled run skipped" in text


# ---------------------------------------------------------------------------
# Code review round 1 (C8-CR1-1, C8-CR1-2)
# ---------------------------------------------------------------------------


def test_the_ci_skip_check_reads_stderr_as_well_as_stdout() -> None:
    # Proves (C8-CR1-1): the `worker-image` job's skip check captures the container's stderr too. The worker logs through
    # structlog to stderr (`app/log_config.py`), so `out=$(docker run ...)` alone captures nothing, `grep` finds no skip
    # line, and the job fails although the container did exactly the right thing. Expected values come from the reviewer's
    # run of the step as written (empty capture, exit 1), not from the workflow under test.
    text = CI_WORKFLOW.read_text()
    step = text.split("The default command is a logged skip", 1)[1].split('echo "$out"', 1)[0]
    assert "docker run" in step
    assert "2>&1" in step


def test_the_image_puts_the_app_directory_on_the_import_path() -> None:
    # Proves (C8-CR1-2): `PYTHONPATH=/app`, so `python -m agent_worker.main` imports the project from any working
    # directory. The project is not installed (`--no-install-project`), so `-m` otherwise resolves `agent_worker` from the
    # current directory and fails with `No module named 'agent_worker'` anywhere but `/app` (reproduced in the local image
    # with `docker run -w /`).
    assert env_values()["PYTHONPATH"] == "/app"


def test_the_console_runbook_does_not_depend_on_the_shell_path_or_directory() -> None:
    # Proves (C8-CR1-2): every command in `environments.md` that starts the worker by hand names the virtual
    # environment's interpreter and changes to `/app` first. A login shell on Debian resets `PATH` (so bare `python` is
    # the base image's, with no libraries), and Railway's console may start outside `/app`; neither is known (C8-U8), so
    # the runbook must not rely on either.
    doc = (REPO_ROOT / "docs" / "dev" / "environments.md").read_text()
    section = doc.split("## The worker on Railway (C8)", 1)[1].split("\n## ", 1)[0]
    commands = [line for line in section.splitlines() if "agent_worker.main" in line and not line.startswith("|")]
    runbook = [line for line in commands if "--help" in line or "nohup" in line]
    assert runbook, "the runbook commands moved; update this test"
    for line in runbook:
        assert "cd /app &&" in line, line
        assert "/app/.venv/bin/python" in line, line
