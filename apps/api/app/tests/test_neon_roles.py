"""The Neon role-restore sequence, against a real Postgres (C3-D9; docs/dev/environments.md, "Neon roles").

WHAT THIS COVERS
  A Neon "reset from parent" drops the per-environment login role and hands table ownership back to the parent's
  owner, so the role has to be re-created and given the tables again (verified on `staging`, October 28, 2026).
  `restore_role` (app/db/neon_roles.py) is that sequence as code. These tests run it on the test database and
  check what a hosted pre-deploy migration depends on: the role can log in, owns every table and enum type, and
  nothing else about it is privileged. The expected values are written out here from the plan, not read from the
  module.

  Every test runs inside `db_conn`'s outer transaction, which is always rolled back. Postgres DDL is
  transactional, so `CREATE ROLE`, `GRANT` and `ALTER ... OWNER` leave nothing behind in the local cluster
  (a role is cluster-wide, so a leak would outlive the test database).
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.neon_roles import ROLE_FOR_ENV, restore_role, role_exists, set_role_password

# The three login roles C3-D9 names, one per hosted environment. Typed out here, not imported.
EXPECTED_ROLES = {"dev": "calendar_dev", "staging": "calendar_staging", "prod": "calendar_prod"}


# ---------------------------------------------------------------------------
# Which roles the sequence may touch
# ---------------------------------------------------------------------------


def test_the_allowed_roles_are_the_three_the_plan_names() -> None:
    # Proves (C3-D9): the allowlist is exactly the three environment roles. The role name is placed into DDL as
    # an identifier, so a loose list is how a typo or a pasted value would create or take over the wrong role.
    assert ROLE_FOR_ENV == EXPECTED_ROLES


@pytest.mark.parametrize("role", ["postgres", "neondb_owner", "calendar_local", 'calendar_dev"; drop', ""])
async def test_a_role_outside_the_allowlist_is_refused(db_conn: AsyncConnection, role: str) -> None:
    # Proves: anything but the three roles raises before any SQL runs, including the owner role itself, because
    # "restoring" `neondb_owner` would hand it a new password and give its tables away.
    with pytest.raises(ValueError, match="not one of"):
        await restore_role(db_conn, role, "a-throwaway-password")


# ---------------------------------------------------------------------------
# The sequence itself
# ---------------------------------------------------------------------------


async def test_restore_creates_a_login_role_that_owns_every_table_and_enum(db_conn: AsyncConnection) -> None:
    # Proves (C3-D9): after the call the role exists, can log in, is otherwise plain, and owns all of `public`'s
    # tables and enum types. Ownership is what lets the pre-deploy `alembic upgrade head` ALTER them; the
    # unprivileged flags are why the role is created in SQL and not in the Neon console, where it would join
    # `neon_superuser`.
    await restore_role(db_conn, "calendar_staging", "a-throwaway-password")

    role = (
        await db_conn.execute(
            sa.text(
                "select rolcanlogin, rolsuper, rolcreatedb, rolcreaterole "
                "from pg_roles where rolname = 'calendar_staging'"
            )
        )
    ).one()
    assert tuple(role) == (True, False, False, False)

    table_owners = (
        await db_conn.execute(sa.text("select distinct tableowner from pg_tables where schemaname = 'public'"))
    ).scalars().all()
    assert table_owners == ["calendar_staging"]

    enum_owners = (
        await db_conn.execute(
            sa.text(
                "select distinct t.typowner::regrole::text from pg_type t "
                "join pg_namespace n on n.oid = t.typnamespace "
                "where n.nspname = 'public' and t.typtype = 'e'"
            )
        )
    ).scalars().all()
    assert enum_owners == ["calendar_staging"]


async def test_restore_works_as_a_non_superuser_owner_like_neondb_owner(db_conn: AsyncConnection) -> None:
    # Proves (C3-D9): the sequence succeeds for a connected role shaped like Neon's `neondb_owner`: it owns the
    # tables and the database, may create roles, and is NOT a superuser. The local test user is a superuser and
    # skips two rules that failed on the hosted branches (October 28, 2026): `ALTER ... OWNER TO x` needs the
    # right to `SET ROLE x` and `CREATE` on the schema for x. Removing either step turns this test red, and it
    # is the only one that does for `grant ... to current_user`.
    await db_conn.exec_driver_sql("create role fake_neondb_owner login createrole")
    await db_conn.exec_driver_sql("alter database calendar_test owner to fake_neondb_owner")
    tables = (
        await db_conn.execute(sa.text("select tablename from pg_tables where schemaname = 'public'"))
    ).scalars().all()
    for table in tables:
        await db_conn.exec_driver_sql(f'alter table public."{table}" owner to fake_neondb_owner')
    # Enum types too: a non-owner cannot move them, and they were created by the superuser.
    enums = (
        await db_conn.execute(
            sa.text(
                "select t.typname from pg_type t join pg_namespace n on n.oid = t.typnamespace "
                "where n.nspname = 'public' and t.typtype = 'e'"
            )
        )
    ).scalars().all()
    for enum in enums:
        await db_conn.exec_driver_sql(f'alter type public."{enum}" owner to fake_neondb_owner')

    await db_conn.exec_driver_sql("set local role fake_neondb_owner")
    try:
        await restore_role(db_conn, "calendar_staging", "a-throwaway-password")
    finally:
        await db_conn.exec_driver_sql("reset role")

    owners = (
        await db_conn.execute(sa.text("select distinct tableowner from pg_tables where schemaname = 'public'"))
    ).scalars().all()
    assert owners == ["calendar_staging"]


async def test_restore_gives_the_role_create_on_public(db_conn: AsyncConnection) -> None:
    # Proves: the role may create objects in `public`. Postgres refuses to make a role the owner of a table in a
    # schema where it cannot create, and a later migration that adds a table needs the same right.
    await restore_role(db_conn, "calendar_dev", "a-throwaway-password")
    can_create = (
        await db_conn.execute(sa.text("select has_schema_privilege('calendar_dev', 'public', 'CREATE')"))
    ).scalar_one()
    assert can_create is True


async def test_restore_twice_is_harmless_and_keeps_the_existing_password(db_conn: AsyncConnection) -> None:
    # Proves: the second run, when the role already exists, ends in the same state and does NOT touch the password.
    # The password is what the environment's DATABASE_URL (Railway) already holds, so a restore that overwrote it
    # with whatever was typed could break a working service over a typo. `pg_authid.rolpassword` is the stored
    # hash; it is unchanged only if no `alter role ... password` ran. The local test user is a superuser, which is
    # what lets it read that catalog.
    assert await restore_role(db_conn, "calendar_staging", "first-throwaway-password") is True
    before = await _stored_password(db_conn, "calendar_staging")
    assert await restore_role(db_conn, "calendar_staging") is False
    assert await _stored_password(db_conn, "calendar_staging") == before
    count = (
        await db_conn.execute(sa.text("select count(*) from pg_roles where rolname = 'calendar_staging'"))
    ).scalar_one()
    assert count == 1
    owners = (
        await db_conn.execute(sa.text("select distinct tableowner from pg_tables where schemaname = 'public'"))
    ).scalars().all()
    assert owners == ["calendar_staging"]


async def test_a_missing_role_needs_a_password(db_conn: AsyncConnection) -> None:
    # Proves: creating a role with no password is refused, because a login role without one cannot be used and
    # the failure would only show up later, at the service's first connection.
    with pytest.raises(ValueError, match="needs a password"):
        await restore_role(db_conn, "calendar_dev")


async def test_a_password_given_for_an_existing_role_is_refused(db_conn: AsyncConnection) -> None:
    # Proves: passing a password when the role already exists raises instead of being silently ignored (or worse,
    # applied). Changing a password is `set_role_password`'s job, so the two cannot be confused.
    await restore_role(db_conn, "calendar_dev", "first-throwaway-password")
    with pytest.raises(ValueError, match="set_role_password"):
        await restore_role(db_conn, "calendar_dev", "another-password")


async def test_set_role_password_changes_only_the_password(db_conn: AsyncConnection) -> None:
    # Proves: the separate password operation changes the stored password and leaves ownership alone.
    await restore_role(db_conn, "calendar_dev", "first-throwaway-password")
    before = await _stored_password(db_conn, "calendar_dev")
    await set_role_password(db_conn, "calendar_dev", "second-throwaway-password")
    assert await _stored_password(db_conn, "calendar_dev") != before
    assert await role_exists(db_conn, "calendar_dev") is True


async def test_set_role_password_refuses_a_missing_role_and_other_roles(db_conn: AsyncConnection) -> None:
    # Proves: the password operation will not create a role (that is `restore_role`) and shares the allowlist, so
    # it cannot be pointed at `neondb_owner`.
    with pytest.raises(ValueError, match="does not exist"):
        await set_role_password(db_conn, "calendar_dev", "a-throwaway-password")
    with pytest.raises(ValueError, match="not one of"):
        await set_role_password(db_conn, "neondb_owner", "a-throwaway-password")


async def _stored_password(conn: AsyncConnection, role: str) -> str:
    """The role's stored password hash, from the catalog (readable because the test user is a superuser)."""
    return (
        await conn.execute(sa.text("select rolpassword from pg_authid where rolname = :r"), {"r": role})
    ).scalar_one()


async def test_a_password_with_quotes_and_backslashes_is_stored_not_executed(db_conn: AsyncConnection) -> None:
    # Proves: the password is quoted by Postgres itself (`quote_literal`), not pasted into the statement, so a
    # quote or backslash in it cannot end the string early. A hand-built `f"... password '{pw}'"` would fail on
    # this value, or run the text after the quote as SQL.
    await restore_role(db_conn, "calendar_dev", "it's a \\ tricky 'pass'; select 1; --")
    exists = (
        await db_conn.execute(sa.text("select exists (select 1 from pg_roles where rolname = 'calendar_dev')"))
    ).scalar_one()
    assert exists is True
