"""Re-create a Neon environment's login role after a "reset from parent" (C3-D9): the sequence and its command.

Run: `uv run python -m scripts.restore_neon_role staging [--set-password]` (from apps/api), with `NEON_OWNER_URL` set in the shell
to the branch's OWNER connection (`neondb_owner`, `postgresql+asyncpg://`, direct host, no `sslmode`). The helper
`neon_restore_role <env>` in the local, uncommitted `.hosted-env.sh` sets it for you.

HOW TO READ THIS
  A Neon "reset from parent" drops the per-environment role (`calendar_staging`) and returns table ownership to the
  parent's owner (`docs/dev/environments.md`, "What a reset does"). Without the role the service cannot log in, and
  without ownership the pre-deploy `alembic upgrade head` fails with "must be owner of table". `restore_role` puts
  both back, in the order that works:

    1. create the role as a plain login role, if it is missing (an existing role keeps its password);
    2. let the connected owner `SET ROLE` to it, which `ALTER ... OWNER TO` requires;
    3. let the role create objects in `public`, which Postgres requires of a new table owner;
    4. hand every table and enum type in `public` to the role.

  The connection must be the branch's owner role (`neondb_owner`) on the branch being restored. The role is made in
  SQL, not in the Neon console, because a console-made role joins `neon_superuser` and the owner then has no admin
  rights over it (`permission denied to grant role`, verified October 28, 2026).

  The file has two halves. The first is the sequence, as functions that take a connection, so
  `scripts/tests/test_restore_neon_role.py` can run it in a rolled-back transaction on the local test database. The
  second, from `main` down, supplies the real connection and the guard rails. The sequence reads no settings, so
  importing this module never trips the `APP_ENV` check; `scripts/rehearse_migration.py` imports `ROLE_FOR_ENV` from here.

Restoring and changing a password are separate. Without the flag, the script asks for a password ONLY when the
role is missing (after a reset), and then it must be the SAME password the environment's `DATABASE_URL` already
holds, so Railway's variable stays valid. A role that exists keeps its password. `--set-password` is the
explicit, separate way to change one (then update that environment's `DATABASE_URL` to match).

Guard rails, because this edits a hosted database from a laptop: the URL must come from the shell (never `.env`),
must log in as `neondb_owner`, and the person must type the environment name after reading the host and database
that are about to change.
"""

import asyncio
import getpass
import os
import sys

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

# ---------------------------------------------------------------------------
# The sequence (tested without a hosted database)
# ---------------------------------------------------------------------------

# The three login roles, one per hosted environment (C3-D9). The role name goes into DDL as an identifier, so only
# these exact names are accepted; `local` has no hosted role.
ROLE_FOR_ENV = {"dev": "calendar_dev", "staging": "calendar_staging", "prod": "calendar_prod"}

# Hands every table and enum type in `public` to the role. Per-object `ALTER ... OWNER` rather than `REASSIGN
# OWNED BY`, which would also try to move ownership of the database itself. Sequences owned by an identity column
# follow their table.
_HAND_OVER = """
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I owner to {role}', r.tablename);
  end loop;
  for r in select t.typname from pg_type t join pg_namespace n on n.oid = t.typnamespace
           where n.nspname = 'public' and t.typtype = 'e' loop
    execute format('alter type public.%I owner to {role}', r.typname);
  end loop;
end $$
"""


def _check_allowed(role: str) -> None:
    """Refuse any role outside the allowlist, before any SQL is built from the name."""
    if role not in ROLE_FOR_ENV.values():
        raise ValueError(f"{role!r} is not one of {sorted(ROLE_FOR_ENV.values())}")


async def _quote_password(conn: AsyncConnection, password: str) -> str:
    """The password as a SQL literal. Quoted by Postgres, not pasted in: `quote_literal` is the one place that
    knows every quoting rule, so a quote or backslash in the password cannot end the string early."""
    return (await conn.execute(sa.text("select quote_literal(:pw)"), {"pw": password})).scalar_one()


async def role_exists(conn: AsyncConnection, role: str) -> bool:
    """Whether the login role is present on the connected branch (a reset removes it)."""
    _check_allowed(role)
    return (
        await conn.execute(sa.text("select exists (select 1 from pg_roles where rolname = :r)"), {"r": role})
    ).scalar_one()


async def restore_role(conn: AsyncConnection, role: str, password: str | None = None) -> bool:
    """Make `role` a login role that owns everything in `public`. Safe to run when the role already exists.

    Returns True if the role had to be created, False if it already existed. A password is needed to create the
    role and is refused when the role exists: the existing password is what the environment's DATABASE_URL holds,
    and changing it is a separate, explicit act (`set_role_password`), never a side effect of restoring ownership.
    """
    _check_allowed(role)
    exists = await role_exists(conn, role)
    if not exists:
        if password is None:
            raise ValueError(f"{role} does not exist, so creating it needs a password")
        # `role` is safe to place in the statement: it is one of the three constants above, never caller text.
        await conn.exec_driver_sql(f"create role {role} login password {await _quote_password(conn, password)}")
    elif password is not None:
        raise ValueError(f"{role} already exists; use set_role_password to change its password")

    await conn.exec_driver_sql(f"grant {role} to current_user")
    await conn.exec_driver_sql(f"grant create on schema public to {role}")
    await conn.exec_driver_sql(_HAND_OVER.format(role=role))
    return not exists


async def set_role_password(conn: AsyncConnection, role: str, password: str) -> None:
    """Change an existing role's password. Kept apart from `restore_role` so that restoring ownership can never
    overwrite the password a running service uses. Update that service's DATABASE_URL to match afterwards."""
    _check_allowed(role)
    if not await role_exists(conn, role):
        raise ValueError(f"{role} does not exist; use restore_role to create it")
    await conn.exec_driver_sql(f"alter role {role} password {await _quote_password(conn, password)}")


# ---------------------------------------------------------------------------
# The command (the real connection and the guard rails)
# ---------------------------------------------------------------------------
async def main(env: str, set_password: bool) -> None:
    if env not in ROLE_FOR_ENV:
        sys.exit(f"Usage: restore_neon_role {{{'|'.join(ROLE_FOR_ENV)}}} [--set-password]")
    role = ROLE_FOR_ENV[env]

    owner_url = os.environ.get("NEON_OWNER_URL")
    if not owner_url:
        sys.exit("NEON_OWNER_URL is not set in this shell (the branch's neondb_owner connection).")
    url = make_url(owner_url)
    if url.username != "neondb_owner":
        sys.exit(f"NEON_OWNER_URL logs in as {url.username!r}; it must be the branch owner, 'neondb_owner'.")

    # Show where this will act and make the person type the environment, so a URL left over from another branch
    # is caught by a human before anything changes.
    action = "change the password of" if set_password else "restore"
    print(f"About to {action} role {role!r} on host {url.host}, database {url.database}.")
    if input(f"Type the environment name ({env}) to continue: ").strip() != env:
        sys.exit("Not confirmed; nothing changed.")

    engine = create_async_engine(url)
    try:
        # One transaction: either everything below happens or nothing changed.
        async with engine.begin() as conn:
            exists = await role_exists(conn, role)
            if set_password:
                if not exists:
                    sys.exit(f"{role} does not exist on this branch; run without --set-password to create it.")
                password = _ask_password(f"NEW password for {role}")
                await set_role_password(conn, role, password)
                print(f"Changed the password of {role}. Update {env}'s DATABASE_URL to match.")
                return
            # Only a missing role needs a password; an existing one keeps the one its DATABASE_URL holds.
            create_password = None if exists else _ask_password(f"Password for {role} (the one its DATABASE_URL uses)")
            created = await restore_role(conn, role, create_password)
    finally:
        await engine.dispose()
    what = "Created the role and" if created else "The role already existed (password untouched);"
    print(f"{what} handed it the tables. Verify with: neon_{env} && neon_probe {env.upper()}_URL")


def _ask_password(prompt: str) -> str:
    """Read a password with no echo; an empty one is refused rather than stored."""
    password = getpass.getpass(f"{prompt}: ")
    if not password:
        sys.exit("An empty password was given; nothing changed.")
    return password


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(args[0] if args else "", "--set-password" in sys.argv))
