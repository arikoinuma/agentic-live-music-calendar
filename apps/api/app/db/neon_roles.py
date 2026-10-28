"""Re-create a Neon environment's login role and give it the tables (C3-D9).

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

  The logic lives here, taking a connection, so `app/tests/test_neon_roles.py` can run it in a rolled-back
  transaction on the local test database; `scripts/restore_neon_role.py` supplies the real connection, the way
  `scripts/seed.py` does for `app/db/seed.py`. This module reads no settings, so it never trips the `APP_ENV` check.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

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
