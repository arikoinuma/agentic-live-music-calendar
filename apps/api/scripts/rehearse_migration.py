"""Rehearse the pending migrations on a throwaway Neon branch (C4-PR1-9).

Run, from the repository root:   make rehearse-migration ENV=staging ARGS='--sql "select slug from metro"'
or from apps/api:                uv run python -m scripts.rehearse_migration staging [options]

What it does (the sequence and its reasons are in `app/db/migration_rehearsal.py`): copies the environment's Neon
branch to a new branch that expires by itself, runs `alembic upgrade head` against the copy as that environment's own
login role, shows the result, and deletes the copy. Nothing it does touches the real branch.

What you need on the machine running it:
  * the Neon CLI:           npm install -g neon   (an older `neonctl` install works too: same tool, either name)
  * a way for it to sign in: `neonctl login` once, or NEON_API_KEY in the shell (read by neonctl itself)
  * the project id:         --project-id, or NEON_PROJECT_ID in the shell
  * the environment role's password: the one in that environment's DATABASE_URL on Railway. Set
    NEON_ROLE_PASSWORD in the shell, or you are asked for it (typed hidden). It is never put on a command line.
  * `uv` and a working `apps/api` checkout (Alembic runs from there)

Exit status: 0 passed; 1 the migration or a guard rail failed; 3 the result stands but the branch could not be deleted
(it will expire on its own, and the output says when).
"""

import argparse
import datetime
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app.db.migration_rehearsal import RunResult, find_neon_cli, rehearse
from app.db.neon_roles import ROLE_FOR_ENV

# apps/api, whatever directory the script was started from: Alembic must run there.
API_DIR = Path(__file__).resolve().parents[1]


def run_command(argv: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None) -> RunResult:
    """Run a real command with the inherited environment plus `env` (this is where DATABASE_URL reaches Alembic)."""
    done = subprocess.run(  # argv is a list built by rehearse(), run without a shell
        argv, env={**os.environ, **(env or {})}, cwd=cwd, capture_output=True, text=True, check=False
    )
    return RunResult(done.returncode, done.stdout, done.stderr)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Rehearse the pending migrations on a throwaway Neon branch.")
    parser.add_argument("env", choices=sorted(ROLE_FOR_ENV), help="the environment whose migration to rehearse")
    parser.add_argument("--project-id", default=os.environ.get("NEON_PROJECT_ID"), help="Neon project id (or NEON_PROJECT_ID)")
    parser.add_argument("--parent", help="branch to copy (default: dev -> dev, staging -> staging, prod -> the default branch)")
    parser.add_argument("--sql", help="one SELECT to run after the upgrade, for example: select slug from metro")
    parser.add_argument("--keep", action="store_true", help="do not delete the branch afterwards (it still expires)")
    parser.add_argument("--ttl-minutes", type=int, default=120, help="Neon deletes the branch by itself after this long (default 120)")
    parser.add_argument("--no-expiry", action="store_true", help="do not set an expiry (if your Neon plan rejects --expires-at)")
    args = parser.parse_args(argv)

    if not args.project_id:
        sys.exit("Give the Neon project with --project-id or NEON_PROJECT_ID in the shell.")
    role = ROLE_FOR_ENV[args.env]
    password = os.environ.get("NEON_ROLE_PASSWORD") or getpass.getpass(f"Password of {role} (as in {args.env}'s DATABASE_URL): ")

    # Alembic runs in a fresh EMPTY directory so it never reads apps/api/.env (see `rehearse`).
    with tempfile.TemporaryDirectory(prefix="rehearse-migration-") as workdir:
        return rehearse(
            args.env,
            project_id=args.project_id,
            role_password=password,
            run=run_command,
            say=print,
            now=datetime.datetime.now(datetime.UTC),
            api_dir=API_DIR,
            workdir=Path(workdir),
            parent=args.parent,
            ttl_minutes=None if args.no_expiry else args.ttl_minutes,
            keep=args.keep,
            sql=args.sql,
            neonctl=os.environ.get("NEON_CLI") or find_neon_cli(shutil.which),
        )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
