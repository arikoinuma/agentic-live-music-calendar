"""The migration rehearsal on a throwaway Neon branch (C4-PR1-9; docs/dev/environments.md, "Rehearsing a migration").

WHAT THIS COVERS
  `rehearse` (app/db/migration_rehearsal.py) cuts a short-lived branch from a hosted environment's Neon branch, runs
  `alembic upgrade head` against it as that environment's own login role, and deletes the branch. The point is to
  find out whether a migration works on production-shaped data and roles BEFORE it touches the real database.

  Everything outside this process is faked: the `neonctl` and `alembic` commands go through an injected `run`
  function that records each call and answers from a script, so these tests need neither a Neon account nor a
  database. What they pin down is the part that has to be right every time and that a human would otherwise do by
  hand: the exact commands and their order, that the connection string handed to Alembic is the branch's own and has
  the shape the app wants, that no secret reaches a command line or the output, and that the throwaway branch is
  removed (or reported) whether the migration worked or not.

  Expected command lines are written out here from the Neon CLI's own `--help` (neonctl 8.14.0), not read from the
  module.
"""

import datetime
from pathlib import Path
from typing import Any

import pytest

from app.db.migration_rehearsal import (
    RehearsalError,
    RunResult,
    branch_name,
    check_select,
    connection_parts,
    database_url,
    delete_branch,
    expires_at,
    find_neon_cli,
    rehearse,
)

NOW = datetime.datetime(2026, 10, 30, 12, 0, 0, tzinfo=datetime.UTC)
API_DIR = Path("/repo/apps/api")
WORKDIR = Path("/tmp/rehearsal-empty-dir")  # an empty directory: the rehearsal must not run inside apps/api
# What `neonctl connection-string` prints: the owner's URL on a pooled-or-direct host, with the query parameters the
# app's DATABASE_URL must NOT carry (docs/dev/notes.md: sslmode and channel_binding).
PARENT_URI = "postgresql://neondb_owner:ownerpw@ep-parent-123.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require\n"
CHILD_URI = "postgresql://neondb_owner:ownerpw@ep-child-456.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require\n"
ROLE_PASSWORD = "p@ss/w:rd#1"  # characters that must be percent-encoded in a URL


class FakeRunner:
    """Records every command and answers from a small script, like a terminal with no Neon behind it."""

    def __init__(
        self, *, fail_on: str | None = None, same_host: bool = False, missing_cli: bool = False, leak: str = ""
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_on = fail_on  # a substring of the command line that should exit non-zero
        self.same_host = same_host  # make the new branch report the parent's host (the guard's case)
        self.missing_cli = missing_cli
        self.cs_calls = 0
        self.leak = leak  # text a failing command also prints (a tool echoing the URL it could not reach)

    def __call__(self, argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> RunResult:
        if self.missing_cli:
            raise FileNotFoundError(argv[0])
        self.calls.append({"argv": list(argv), "env": env, "cwd": cwd})
        line = " ".join(argv)
        if self.fail_on and self.fail_on in line:
            return RunResult(1, "", f"boom: {self.fail_on} {self.leak}".strip())
        if "connection-string" in argv or "cs" in argv:
            self.cs_calls += 1
            # The first connection string asked for is the parent's, the second is the new branch's.
            uri = PARENT_URI if (self.cs_calls == 1 or self.same_host) else CHILD_URI
            return RunResult(0, uri, "")
        if "current" in argv:
            return RunResult(0, "c4a1e5b7d903 (head)\n", "")
        return RunResult(0, "", "")

    def argv_lines(self) -> list[str]:
        return [" ".join(c["argv"]) for c in self.calls]


def go(runner: FakeRunner, **overrides: Any) -> tuple[int, list[str]]:
    """Run `rehearse` with the fixed clock and a recording `say`; return (exit code, everything said)."""
    said: list[str] = []
    env = overrides.pop("env", "staging")
    options: dict[str, Any] = {
        "project_id": "proj-123",
        "role_password": ROLE_PASSWORD,
        "run": runner,
        "say": said.append,
        "now": NOW,
        "api_dir": API_DIR,
        "workdir": WORKDIR,
        "query": lambda url, sql: [("msp",)],
    }
    options.update(overrides)
    code = rehearse(env, **options)
    return code, said


# ---------------------------------------------------------------------------
# The happy path: which commands, in which order
# ---------------------------------------------------------------------------


def test_the_happy_path_runs_the_commands_in_order_and_deletes_the_branch() -> None:
    # Proves: the rehearsal asks for the parent's host, creates the branch from the staging branch with an expiry,
    # asks for the new branch's host, runs `alembic current`, `upgrade head`, `current` again, and deletes the branch
    # last. The `neonctl` flags are the ones `neonctl branches create --help` lists (--name, --parent, --project-id,
    # --expires-at, --no-secrets); a flag that did not exist would fail on the first real run, not here, which is why
    # they are written out from the help text.
    runner = FakeRunner()
    code, _ = go(runner)
    assert code == 0
    assert runner.argv_lines() == [
        "neonctl connection-string staging --role-name neondb_owner --project-id proj-123",
        (
            "neonctl branches create --name rehearse-staging-20261030T120000Z --parent staging --project-id proj-123"
            " --expires-at 2026-10-30T14:00:00Z --no-secrets"
        ),
        "neonctl connection-string rehearse-staging-20261030T120000Z --role-name neondb_owner --project-id proj-123",
        f"uv run --project {API_DIR} alembic -c {API_DIR}/alembic.ini current",
        f"uv run --project {API_DIR} alembic -c {API_DIR}/alembic.ini upgrade head",
        f"uv run --project {API_DIR} alembic -c {API_DIR}/alembic.ini current",
        "neonctl branches delete rehearse-staging-20261030T120000Z --project-id proj-123",
    ]


def test_alembic_gets_the_new_branchs_url_in_the_shape_the_app_wants() -> None:
    # Proves: the one-command override the project requires (never edit .env): APP_ENV names the environment, and
    # DATABASE_URL is the NEW branch's host with the environment's own role, `postgresql+asyncpg://`, the database
    # name, the password percent-encoded, and no `sslmode` or `channel_binding` (docs/dev/notes.md). Alembic runs in
    # apps/api. Catches a rehearsal that pointed at the parent's host, which would migrate the real branch.
    runner = FakeRunner()
    go(runner)
    alembic_calls = [c for c in runner.calls if "alembic" in c["argv"]]
    assert len(alembic_calls) == 3
    for call in alembic_calls:
        assert call["cwd"] == WORKDIR
        assert call["env"]["APP_ENV"] == "staging"
        assert call["env"]["DATABASE_URL"] == (
            "postgresql+asyncpg://calendar_staging:p%40ss%2Fw%3Ard%231@ep-child-456.us-east-2.aws.neon.tech/neondb"
        )
        assert "ep-parent-123" not in call["env"]["DATABASE_URL"]


def test_alembic_runs_in_an_empty_directory_and_never_reads_the_developers_env_file() -> None:
    # Proves: the migration runs with an EMPTY working directory, not apps/api, and is told where the project and its
    # alembic.ini are by path. `Settings` loads `.env` from the working directory, and a developer's apps/api/.env holds
    # things unrelated to a hosted branch: a key the code does not know made `Settings()` refuse to start on the first
    # real run (October 30, 2026), and its value was printed in the error. Running elsewhere makes the rehearsal depend on
    # only what it passes: APP_ENV, DATABASE_URL, a placeholder MODEL_NAME (required by Settings at import), and
    # PYTHONPATH so `app` imports. The expected values are written out from that list.
    runner = FakeRunner()
    go(runner)
    alembic_calls = [c for c in runner.calls if "alembic" in c["argv"]]
    assert alembic_calls
    for call in alembic_calls:
        assert call["cwd"] == WORKDIR
        assert call["cwd"] != API_DIR
        assert call["env"]["PYTHONPATH"] == str(API_DIR)
        assert call["env"]["MODEL_NAME"] == "rehearsal-placeholder"
        assert set(call["env"]) == {"APP_ENV", "DATABASE_URL", "MODEL_NAME", "PYTHONPATH"}


def test_a_validation_error_does_not_print_the_value_it_rejected() -> None:
    # Proves: pydantic's "Extra inputs are not permitted ... input_value='sk-...'" line, which echoes the offending
    # setting's VALUE, is redacted from anything the rehearsal prints. This is the leak the first real run had: a
    # DeepInfra key from a local .env appeared in the terminal. Catches output that passes a tool's stderr through
    # untouched. The useful part (which field, and why) stays.
    leak = "model_api_key\n  Extra inputs are not permitted [type=extra_forbidden, input_value='sk-di-SECRET123', input_type=str]"
    runner = FakeRunner(fail_on="upgrade head", leak=leak)
    code, said = go(runner)
    assert code == 1
    text = "\n".join(said)
    assert "sk-di-SECRET123" not in text
    assert "model_api_key" in text
    assert "extra_forbidden" in text


def test_no_secret_reaches_a_command_line_or_the_output() -> None:
    # Proves: neither the owner's password nor the role's password appears in any argument or any line said. Command
    # lines are visible in `ps` and shell history, and the output ends up in terminals and logs.
    runner = FakeRunner()
    _, said = go(runner)
    everything = " ".join(runner.argv_lines()) + " ".join(said)
    for secret in ("ownerpw", ROLE_PASSWORD, "p%40ss"):
        assert secret not in everything


# ---------------------------------------------------------------------------
# Cleanup: the branch must not be left behind
# ---------------------------------------------------------------------------


def test_a_tools_error_message_is_scrubbed_of_the_password() -> None:
    # Proves: if a failing command echoes the connection string it was given (SQLAlchemy and asyncpg errors sometimes
    # do), neither the raw password nor its URL-encoded form reaches the terminal. Catches a rehearsal that prints a
    # tool's stderr as it came. Expected: the visible text keeps the useful part ("boom") and loses the secret.
    leak = "could not connect to postgresql+asyncpg://calendar_staging:p%40ss%2Fw%3Ard%231@ep-child-456 with p@ss/w:rd#1"
    runner = FakeRunner(fail_on="upgrade head", leak=leak)
    code, said = go(runner)
    assert code == 1
    text = "\n".join(said)
    assert "boom: upgrade head" in text
    for secret in (ROLE_PASSWORD, "p%40ss%2Fw%3Ard%231"):
        assert secret not in text


def test_a_login_failure_leads_with_its_cause_and_a_hint() -> None:
    # Proves: the cause (the last line of a traceback) is the first thing said after FAILED, not buried under forty
    # lines of stack, and a wrong or missing role password gets a hint that names where the right one lives.
    runner = FakeRunner(fail_on="upgrade head", leak='asyncpg.InvalidPasswordError: password authentication failed for user "calendar_staging"')
    code, said = go(runner)
    assert code == 1
    failed = next(line for line in said if line.startswith("FAILED:"))
    assert 'password authentication failed for user "calendar_staging"' in failed.splitlines()[0]
    assert any(line.startswith("Hint:") and "DATABASE_URL" in line for line in said)


def test_the_branch_is_deleted_even_when_the_migration_fails() -> None:
    # Proves: a failing `alembic upgrade head` is reported (non-zero exit, with the tool's own message), and the
    # throwaway branch is still deleted. That is the whole value of the script: the failure is found on a branch
    # nobody depends on, and nothing is left running.
    runner = FakeRunner(fail_on="upgrade head")
    code, said = go(runner)
    assert code == 1
    assert any("boom: upgrade head" in line for line in said)
    assert runner.argv_lines()[-1].startswith("neonctl branches delete rehearse-staging-")


def test_keep_leaves_the_branch_and_says_how_to_delete_it() -> None:
    # Proves: `--keep` (for poking at the migrated copy) skips the delete and prints the exact command, so a kept
    # branch is never forgotten silently.
    runner = FakeRunner()
    code, said = go(runner, keep=True)
    assert code == 0
    assert not any("branches delete" in line for line in runner.argv_lines())
    assert any("neonctl branches delete rehearse-staging-20261030T120000Z" in line for line in said)


def test_a_failed_delete_is_loud_and_names_the_expiry() -> None:
    # Proves: if the cleanup itself fails the exit code is 3 (distinct from a failed migration) and the output says
    # which branch is left, the command to remove it, and that it will expire by itself at the time set at creation.
    runner = FakeRunner(fail_on="branches delete")
    code, said = go(runner)
    assert code == 3
    text = "\n".join(said)
    assert "rehearse-staging-20261030T120000Z" in text
    assert "2026-10-30T14:00:00Z" in text


def test_nothing_is_deleted_when_the_branch_was_never_created() -> None:
    # Proves: if `branches create` fails there is nothing of ours to remove, so no delete is attempted (a delete
    # of a name that does not exist, or worse, one that does, is exactly what must not happen).
    runner = FakeRunner(fail_on="branches create")
    code, _ = go(runner)
    assert code == 1
    assert not any("branches delete" in line for line in runner.argv_lines())


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_it_refuses_to_migrate_if_the_new_branch_has_the_parents_host() -> None:
    # Proves: if the "new" branch resolves to the parent's host the migration is NOT run (it would alter the real
    # branch), the new branch is removed, and the exit code is non-zero. This is the one mistake that makes a
    # rehearsal dangerous, so it is checked by comparing hosts rather than trusted.
    runner = FakeRunner(same_host=True)
    code, said = go(runner)
    assert code == 1
    assert not any("alembic" in line for line in runner.argv_lines())
    assert runner.argv_lines()[-1].startswith("neonctl branches delete rehearse-staging-")
    assert any("same host" in line.lower() for line in said)


def test_delete_branch_only_ever_deletes_a_rehearsal_branch() -> None:
    # Proves: the delete helper refuses any name that is not a `rehearse-` branch, whatever called it, so a bug or a
    # typo can never delete `staging`, `dev` or the production branch.
    runner = FakeRunner()
    for name in ("staging", "dev", "main", "production", "rehearse", "my-rehearse-staging"):
        with pytest.raises(RehearsalError):
            delete_branch(runner, "neonctl", "proj-123", name)
    assert runner.calls == []


def test_an_unknown_environment_is_refused_before_any_command() -> None:
    # Proves: only dev, staging and prod are rehearsable (they are the environments with a login role), and a typo
    # costs nothing.
    runner = FakeRunner()
    code, _ = go(runner, env="local")
    assert code == 1
    assert runner.calls == []


def test_a_missing_neonctl_says_how_to_install_it() -> None:
    # Proves: a machine without the CLI gets a one-line fix instead of a Python traceback.
    code, said = go(FakeRunner(missing_cli=True))
    assert code == 1
    assert any("npm install -g neon" in line for line in said)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_production_is_cut_from_the_default_branch() -> None:
    # Proves: the production rehearsal passes no --parent and no branch name, so `neonctl` uses the project's default
    # branch (which is production's, `environments.md`), and uses the `calendar_prod` role.
    runner = FakeRunner()
    go(runner, env="prod")
    create = next(line for line in runner.argv_lines() if "branches create" in line)
    assert "--parent" not in create
    assert runner.argv_lines()[0] == "neonctl connection-string --role-name neondb_owner --project-id proj-123"
    alembic = next(c for c in runner.calls if "alembic" in c["argv"])
    assert alembic["env"]["APP_ENV"] == "prod"
    assert alembic["env"]["DATABASE_URL"].startswith("postgresql+asyncpg://calendar_prod:")


def test_an_explicit_parent_overrides_the_default() -> None:
    # Proves: `--parent` rehearses from any branch (for example a branch holding a copy of production data).
    runner = FakeRunner()
    go(runner, parent="staging-copy")
    assert "--parent staging-copy" in next(line for line in runner.argv_lines() if "branches create" in line)


def test_no_expiry_omits_the_expires_at_flag() -> None:
    # Proves: `ttl_minutes=None` (the `--no-expiry` option, for a plan that rejects expiring branches) leaves the
    # flag out, so the delete in the `finally` is then the only cleanup.
    runner = FakeRunner()
    go(runner, ttl_minutes=None)
    assert "--expires-at" not in next(line for line in runner.argv_lines() if "branches create" in line)


def test_an_optional_select_runs_against_the_migrated_branch_and_is_shown() -> None:
    # Proves: `--sql` runs AFTER the upgrade, against the new branch's URL, and its rows are printed. This is how
    # the C4 rehearsal confirms the backfill (`select slug from metro` gives `msp`).
    seen: list[tuple[str, str]] = []

    def query(url: str, sql: str) -> list[tuple[Any, ...]]:
        seen.append((url, sql))
        return [("msp",)]

    runner = FakeRunner()
    code, said = go(runner, sql="select slug from metro", query=query)
    assert code == 0
    assert seen == [
        (
            "postgresql+asyncpg://calendar_staging:p%40ss%2Fw%3Ard%231@ep-child-456.us-east-2.aws.neon.tech/neondb",
            "select slug from metro",
        )
    ]
    assert any("msp" in line for line in said)


# ---------------------------------------------------------------------------
# The small pure pieces
# ---------------------------------------------------------------------------


def test_connection_parts_reads_host_and_database_and_ignores_the_query() -> None:
    # Proves: the host and database name come out of a Neon URI whatever its query parameters are.
    assert connection_parts(PARENT_URI.strip()) == ("ep-parent-123.us-east-2.aws.neon.tech", "neondb")


def test_database_url_encodes_the_password_and_drops_the_query() -> None:
    # Proves: a password with `@`, `/`, `:` or `#` cannot change which host the URL names.
    assert database_url("h.example", "neondb", "calendar_dev", "a@b/c") == (
        "postgresql+asyncpg://calendar_dev:a%40b%2Fc@h.example/neondb"
    )


def test_branch_names_and_expiry_are_derived_from_the_clock() -> None:
    # Proves: the name carries the environment and the UTC time (so two rehearsals never collide and a stray one can be
    # dated), and the expiry is the creation time plus the TTL in the ISO form the CLI documents.
    assert branch_name("staging", NOW) == "rehearse-staging-20261030T120000Z"
    assert expires_at(NOW, 120) == "2026-10-30T14:00:00Z"


@pytest.mark.parametrize(
    ("installed", "expected"),
    [
        ({"neon", "neonctl"}, "neon"),  # both: the plugin's name wins
        ({"neonctl"}, "neonctl"),  # an older install (npm i -g neonctl)
        ({"neon"}, "neon"),  # the current install (npm i -g neon)
        (set(), "neon"),  # neither: the name the install hint tells people to get
    ],
)
def test_find_neon_cli_accepts_either_name_for_the_same_tool(installed: set[str], expected: str) -> None:
    # Proves: the Neon CLI is published as `neon` (current) and `neonctl` (older, still shipped by the `neonctl`
    # package; both are the same tool, 8.14.0), so the script uses whichever is on PATH instead of failing on a
    # machine that installed the other one. With neither, it returns `neon`, so the error names the package to get.
    assert find_neon_cli(lambda name: f"/bin/{name}" if name in installed else None) == expected


@pytest.mark.parametrize("sql", ["select slug from metro", "  SELECT count(*) FROM venue"])
def test_check_select_accepts_a_single_select(sql: str) -> None:
    # Proves: the verification query may be any single SELECT.
    check_select(sql)


@pytest.mark.parametrize(
    "sql", ["delete from metro", "select 1; drop table metro", "update metro set slug='x'", "", "with x as (select 1) select * from x"]
)
def test_check_select_refuses_anything_else(sql: str) -> None:
    # Proves: the check cannot be used to change data, even on a throwaway branch (and a CTE is refused too: the rule
    # is deliberately the simplest one that can be read at a glance).
    with pytest.raises(RehearsalError):
        check_select(sql)
