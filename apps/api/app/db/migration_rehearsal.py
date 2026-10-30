"""Rehearse a migration on a throwaway Neon branch before it touches a real database (C4-PR1-9).

HOW TO READ THIS
  A migration that works on the test database can still fail on a hosted branch, because the hosted branch has real
  rows, its own login role, and table ownership that a fresh test database does not (C3-PR1-2 was exactly that). The
  rehearsal finds out first, on a copy:

    1. ask Neon for the PARENT branch's host (so a later step can prove it is not migrating the parent);
    2. create a branch from it with the Neon CLI, set to EXPIRE by itself (`--expires-at`) so a forgotten one cleans
       itself up even if this process dies;
    3. ask for the NEW branch's host, and refuse to go on if it is the parent's;
    4. run `alembic current`, `alembic upgrade head`, `alembic current` against the new branch, as the environment's
       own login role (`calendar_staging`, ...), the way the pre-deploy step will;
    5. optionally run one SELECT to look at the result (for the slug migration: `select slug from metro`);
    6. delete the branch, whether or not the migration worked.

  The script that wraps this is `scripts/rehearse_migration.py`; `docs/dev/environments.md` ("Rehearsing a migration")
  says how to run it. This module supplies the logic and takes the outside world as arguments, so
  `app/tests/test_migration_rehearsal.py` runs the whole sequence with no Neon account: `run` executes a command and
  returns its result, `say` prints, `query` runs the check SELECT, `now` is the clock.

  Secrets: the Neon API key is read by `neonctl` from its own environment (`NEON_API_KEY` or a `neonctl login`
  session), never passed on a command line. The owner's password from `neonctl connection-string` is parsed for its
  host and discarded. The environment role's password reaches Alembic only through the `DATABASE_URL` in the child
  process's environment (the project's one-command override), and anything a command prints is scrubbed of it.

  The Neon commands and their flags are from `neonctl --help` (8.14.0; the same tool is also published as `neon`, and
  `find_neon_cli` uses whichever is installed): `connection-string [branch] --role-name
  --project-id`, `branches create --name --parent --project-id --expires-at --no-secrets`, `branches delete <name>
  --project-id`.

  Like `neon_roles.py`, this module reads no settings, so it never trips the `APP_ENV` check; it sets `APP_ENV` for the
  Alembic child process instead.
"""

import asyncio
import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.neon_roles import ROLE_FOR_ENV

# Every rehearsal branch starts with this, and `delete_branch` refuses any other name: a bug or a typo must never be
# able to delete `staging`, `dev` or the production branch.
BRANCH_PREFIX = "rehearse-"

# The branch each environment's rehearsal is cut from. `None` means "the project's default branch", which is
# production's (docs/dev/environments.md): `neonctl` uses it when no branch is named.
DEFAULT_PARENT: dict[str, str | None] = {"dev": "dev", "staging": "staging", "prod": None}

# The role whose password `neonctl` can reveal. The environment's own role (created in SQL, C3-D9) has no password the
# Neon API knows, so the caller supplies that one.
OWNER_ROLE = "neondb_owner"

# Exit codes: 0 worked; 1 the migration or a guard rail failed; 3 it worked (or failed) AND the branch could not be
# deleted, so one is left behind and will expire on its own.
EXIT_OK, EXIT_FAILED, EXIT_BRANCH_LEFT = 0, 1, 3


class RehearsalError(Exception):
    """A step failed or a guard rail refused. The message is for the person at the terminal."""


@dataclass(frozen=True)
class RunResult:
    """What a finished command left behind."""

    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    """Runs one command. `env` is added to the inherited environment; `cwd` is the working directory."""

    def __call__(self, argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> RunResult: ...


# ---------------------------------------------------------------------------
# Small pure pieces
# ---------------------------------------------------------------------------


def find_neon_cli(which: Callable[[str], str | None]) -> str:
    """The Neon CLI's program name on this machine. It is published as `neon` (the current name, `npm i -g neon`) and as
    `neonctl` (the older name, which the `neonctl` package still installs next to `neon`); they are the same tool, so
    use whichever is on PATH. `which` is `shutil.which`, passed in so a test can say what is installed. With neither
    present it returns `neon`, so the "not found" message tells the person which package to install."""
    return next((name for name in ("neon", "neonctl") if which(name)), "neon")


def branch_name(env: str, now: datetime.datetime) -> str:
    """`rehearse-staging-20261030T120000Z`: the environment and the UTC time, so two rehearsals never collide and a
    stray branch can be dated at a glance."""
    return f"{BRANCH_PREFIX}{env}-{now.astimezone(datetime.UTC):%Y%m%dT%H%M%SZ}"


def expires_at(now: datetime.datetime, ttl_minutes: int) -> str:
    """When Neon should delete the branch by itself, in the ISO form the CLI documents (`2026-10-30T14:00:00Z`)."""
    return (now.astimezone(datetime.UTC) + datetime.timedelta(minutes=ttl_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def connection_parts(uri: str) -> tuple[str, str]:
    """(host, database name) of a Neon connection URI, ignoring its user, password and query parameters."""
    parts = urlsplit(uri.strip())
    if not parts.hostname or not parts.path.strip("/"):
        raise RehearsalError("neonctl returned a connection string with no host or database name")
    return parts.hostname, parts.path.lstrip("/")


def database_url(host: str, database: str, role: str, password: str) -> str:
    """The `DATABASE_URL` the app wants for this branch and role: `postgresql+asyncpg://`, the password percent-encoded
    (so a `@` or `/` in it cannot change the host), and NO `sslmode` or `channel_binding` (docs/dev/notes.md)."""
    return f"postgresql+asyncpg://{quote(role, safe='')}:{quote(password, safe='')}@{host}/{database}"


def check_select(sql: str) -> None:
    """The verification query may only be one plain SELECT. A throwaway branch is safe to damage, but the check is
    for looking, not for changing; the rule is the simplest one that can be read at a glance (no CTE, no semicolon)."""
    if not re.match(r"^\s*select\b", sql, re.IGNORECASE) or ";" in sql:
        raise RehearsalError("--sql must be a single SELECT statement (no semicolon)")


def delete_branch(run: Runner, neonctl: str, project_id: str, name: str) -> None:
    """Delete a rehearsal branch. Refuses any name that is not one (see BRANCH_PREFIX)."""
    if not name.startswith(BRANCH_PREFIX) or name == BRANCH_PREFIX:
        raise RehearsalError(f"refusing to delete {name!r}: only branches named {BRANCH_PREFIX}* are rehearsal branches")
    _run(run, neonctl, [neonctl, "branches", "delete", name, "--project-id", project_id])


def _scrub(text: str, secrets: list[str]) -> str:
    """Replace each secret (and its URL-encoded form) with `****`, so a tool's error message cannot leak it."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "****").replace(quote(secret, safe=""), "****")
    return text


def _run(
    run: Runner,
    neonctl: str,
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    secrets: list[str] | None = None,
) -> RunResult:
    """Run a command; turn a missing program or a non-zero exit into a RehearsalError with a useful message."""
    try:
        result = run(argv, env=env, cwd=cwd)
    except FileNotFoundError as err:
        if argv[0] == neonctl:
            raise RehearsalError(f"{neonctl!r} was not found. Install the Neon CLI with: npm install -g neon") from err
        raise RehearsalError(f"{argv[0]!r} was not found on PATH") from err
    if result.returncode != 0:
        detail = _scrub((result.stderr or result.stdout).strip(), secrets or [])
        # The cause is usually the LAST line (a Python traceback ends with it), so lead with that and keep the rest
        # underneath for anyone who needs it.
        last = detail.splitlines()[-1] if detail else "(no output)"
        full = "".join(f"\n    {line}" for line in detail.splitlines()[:-1])
        raise RehearsalError(f"`{' '.join(argv[:3])} ...` exited {result.returncode}: {last}{full}")
    return result


def default_query(url: str, sql: str) -> list[tuple[Any, ...]]:
    """Run the check SELECT against the rehearsal branch and return its rows."""

    async def go() -> list[tuple[Any, ...]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return [tuple(row) for row in (await conn.execute(sa.text(sql))).fetchall()]
        finally:
            await engine.dispose()

    try:
        return asyncio.run(go())
    except (SQLAlchemyError, OSError) as err:
        raise RehearsalError(f"the check query failed: {err}") from err


# ---------------------------------------------------------------------------
# The rehearsal
# ---------------------------------------------------------------------------


def rehearse(
    env: str,
    *,
    project_id: str,
    role_password: str,
    run: Runner,
    say: Callable[[str], None],
    now: datetime.datetime,
    api_dir: Path,
    parent: str | None = None,
    ttl_minutes: int | None = 120,
    keep: bool = False,
    sql: str | None = None,
    query: Callable[[str, str], list[tuple[Any, ...]]] = default_query,
    neonctl: str = "neonctl",
) -> int:
    """Run the whole rehearsal for `env` ("dev", "staging" or "prod") and return the exit code (see EXIT_*).

    `parent` overrides the branch to copy (the default is DEFAULT_PARENT[env]); `ttl_minutes=None` omits the expiry
    (for a Neon plan that rejects expiring branches); `keep` leaves the branch for a person to inspect; `sql` is one
    SELECT to run after the upgrade.
    """
    # Everything that can be refused is refused before the first command, so a typo costs nothing.
    try:
        if env not in ROLE_FOR_ENV:
            raise RehearsalError(f"{env!r} is not rehearsable; choose one of {', '.join(ROLE_FOR_ENV)}")
        role = ROLE_FOR_ENV[env]
        if sql is not None:
            check_select(sql)
    except RehearsalError as err:
        say(f"Refused: {err}")
        return EXIT_FAILED

    parent_name = parent if parent is not None else DEFAULT_PARENT[env]
    name = branch_name(env, now)
    expiry = expires_at(now, ttl_minutes) if ttl_minutes is not None else None
    secrets = [role_password]
    created = False
    code = EXIT_FAILED

    def neon(*args: str) -> RunResult:
        return _run(run, neonctl, [neonctl, *args], secrets=secrets)

    def owner_host(branch: str | None) -> tuple[str, str]:
        """Host and database of a branch, read from the OWNER role's connection string (whose password is then dropped)."""
        branch_arg = [branch] if branch else []
        out = neon("connection-string", *branch_arg, "--role-name", OWNER_ROLE, "--project-id", project_id)
        return connection_parts(out.stdout)

    try:
        say(f"Rehearsing the {env} migration on a copy of {parent_name or 'the default branch'} (project {project_id}).")
        parent_host, _ = owner_host(parent_name)

        create = ["branches", "create", "--name", name]
        if parent_name:
            create += ["--parent", parent_name]
        create += ["--project-id", project_id]
        if expiry:
            create += ["--expires-at", expiry]
        create += ["--no-secrets"]  # do not print the new branch's credentials into our output
        neon(*create)
        created = True
        say(f"Created branch {name}" + (f", which Neon deletes by itself at {expiry}." if expiry else " (no expiry set)."))

        host, database = owner_host(name)
        if host == parent_host:
            raise RehearsalError(
                f"the new branch reports the same host as its parent ({host}); not migrating, "
                "because that would change the real branch"
            )
        url = database_url(host, database, role, role_password)
        secrets.append(url)
        say(f"Target: host {host}, database {database}, role {role}, APP_ENV={env} (host differs from the parent's).")

        alembic_env = {"APP_ENV": env, "DATABASE_URL": url}
        for step in (["current"], ["upgrade", "head"], ["current"]):
            result = _run(run, neonctl, ["uv", "run", "alembic", *step], env=alembic_env, cwd=api_dir, secrets=secrets)
            say(f"alembic {' '.join(step)}:")
            for line in _scrub(f"{result.stdout}\n{result.stderr}", secrets).splitlines():
                if line.strip():
                    say(f"    {line}")

        if sql is not None:
            say(f"Check: {sql}")
            for row in query(url, sql):
                say(f"    {row}")
        say("Rehearsal passed.")
        code = EXIT_OK
    except RehearsalError as err:
        say(f"FAILED: {err}")
        if "password authentication failed" in str(err):
            say(
                f"Hint: the copy has the {role} role only if the parent did, and the password must be the one in "
                f"{env}'s DATABASE_URL on Railway (see docs/dev/environments.md, 'Neon roles')."
            )
        code = EXIT_FAILED
    finally:
        if created:
            code = _finish(run, neonctl, project_id, name, expiry, keep, say, code)
    return code


def _finish(
    run: Runner,
    neonctl: str,
    project_id: str,
    name: str,
    expiry: str | None,
    keep: bool,
    say: Callable[[str], None],
    code: int,
) -> int:
    """Delete (or deliberately keep) the branch this run created, and say so. Returns the exit code to use."""
    delete_command = f"{neonctl} branches delete {name} --project-id {project_id}"
    if keep:
        say(f"Kept branch {name}. Delete it with: {delete_command}")
        return code
    try:
        delete_branch(run, neonctl, project_id, name)
        say(f"Deleted branch {name}.")
        return code
    except RehearsalError as err:
        when = f"it expires by itself at {expiry}" if expiry else "it has NO expiry, so delete it by hand"
        say(f"COULD NOT DELETE branch {name}: {err}. Delete it with: {delete_command} ({when}).")
        return code if code != EXIT_OK else EXIT_BRANCH_LEFT
