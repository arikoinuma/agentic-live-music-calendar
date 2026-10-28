"""The migration against a real Postgres: does it build what the models say?

HOW TO READ THIS FILE
  test_db_metadata.py checks the Python model definitions. This file checks
  the *database those models are supposed to produce*, built by the actual
  Alembic migration. The two can disagree (a migration written by hand can
  drift from the models), and the database is what the app really runs on.

  Sections, in order:
    1. The safety guard that stops these tests wiping the wrong database
       (no database needed).
    2. Schema shape: tables, enum types, indexes, constraints exist.
    3. Constraint behaviour: do the CHECK / FK / PK rules actually fire?
    4. Server-side defaults, JSONB/array round-trips, and an ORM-update check.
    5. One destructive migration test (kept last on purpose).

SETUP YOU DON'T SEE
  Written before the migration (docs/dev/implementations/a1-data-layer.md,
  "Test approach", layer 2). The `migrated_engine` fixture
  (app/testing/db.py) has already run upgrade -> downgrade -> upgrade on a
  freshly created `calendar_test` database by the time any test here starts,
  so the hand-written downgrade() is exercised on every run, CI included.
  Most tests use `db_conn`, a connection wrapped in a transaction that is
  rolled back afterwards, so tests never see each other's rows.

compare_metadata alone is a weak check — it compares enum types by name only
and ignores CHECK constraints and index method — so it is paired here with
explicit catalog assertions for exactly those things.
"""

import datetime
import decimal
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import Metro
from app.testing.db import (
    TEST_DB_NAME,
    UnsafeTestDatabaseError,
    check_test_database_url,
    run_alembic,
)
from app.tests.test_db_metadata import EXPECTED_COLUMNS, EXPECTED_ENUM_LABELS

# Shorthand: table name -> SQLAlchemy Table. Lets the tests below write
# T["show"] and run plain Core INSERT/SELECT statements without going
# through ORM objects (see the note above the constraint tests for why).
T = Base.metadata.tables


# --- The safety guard: needs no database, so it runs everywhere. ----------
#
# These fixtures DROP and recreate a database. check_test_database_url
# (app/testing/db.py) is the last line of defence against doing that to the
# wrong one, so it gets its own tests that never touch a database.


def test_guard_rejects_any_database_that_is_not_the_test_database() -> None:
    # Proves: pointing the fixtures at `calendar_dev` (or any other name) is
    # refused outright, whether or not the URL was derived.
    url = make_url("postgresql+asyncpg://u:p@localhost:5432/calendar_dev")
    with pytest.raises(UnsafeTestDatabaseError):
        check_test_database_url(url, derived=False)


def test_guard_rejects_a_derived_url_on_a_remote_host() -> None:
    # Proves: when the test URL is *derived* from DATABASE_URL, a non-local
    # host is refused even though the database name is right.
    # The Neon incident in docs/dev/notes.md: DATABASE_URL pointed at a
    # hosted database. Name-only checking would pass this.
    url = make_url(f"postgresql+asyncpg://u:p@ep-x.neon.tech:5432/{TEST_DB_NAME}")
    with pytest.raises(UnsafeTestDatabaseError):
        check_test_database_url(url, derived=True)
    check_test_database_url(url, derived=False)  # explicit opt-in is allowed


def test_guard_accepts_the_local_test_database() -> None:
    # Proves: the guard isn't so strict that the normal case fails.
    url = make_url(f"postgresql+asyncpg://u:p@localhost:5432/{TEST_DB_NAME}")
    check_test_database_url(url, derived=True)


# --- Real Postgres from here down. ----------------------------------------
#
# Schema shape: does the migrated database contain the right objects?


async def test_connected_to_the_test_database(db_conn: AsyncConnection) -> None:
    # Proves: the server itself says we're in `calendar_test`. This asks
    # Postgres (current_database()) rather than trusting the URL we built.
    name = (await db_conn.execute(sa.text("SELECT current_database()"))).scalar_one()
    assert name == TEST_DB_NAME


async def test_exactly_the_expected_tables_exist(db_conn: AsyncConnection) -> None:
    # Proves: the migration created every table, and no stray ones.
    # `alembic_version` is Alembic's own bookkeeping table (one row: which
    # migration the database is at), so it's expected alongside ours.
    rows = await db_conn.execute(sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    assert set(rows.scalars()) == set(EXPECTED_COLUMNS) | {"alembic_version"}


async def test_models_and_migration_agree(migrated_engine: AsyncEngine) -> None:
    # Proves: asking Alembic "what would you change to make this database
    # match the models?" yields nothing. This is the broad drift check —
    # columns, types, nullability, defaults, FKs. It has known blind spots
    # (enum labels, CHECKs, index method), which the next tests cover.
    def diff(sync_conn: Any) -> list[Any]:
        # compare_type/compare_server_default turn on type and DEFAULT
        # comparison; compare_server_default is off by default in Alembic.
        ctx = MigrationContext.configure(
            sync_conn, opts={"compare_type": True, "compare_server_default": True}
        )
        return compare_metadata(ctx, Base.metadata)

    async with migrated_engine.connect() as conn:
        # run_sync: Alembic's comparison API is synchronous.
        assert await conn.run_sync(diff) == []


async def test_enum_labels_in_postgres_match_enums_py(db_conn: AsyncConnection) -> None:
    # Proves: each Postgres enum type holds exactly the spec's labels, in
    # the spec's order. compare_metadata can't check this (it compares enum
    # types by name only), so ask the system catalog directly.
    rows = await db_conn.execute(
        sa.text(
            "SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder) "
            "FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid GROUP BY t.typname"
        )
    )
    in_db = {name: labels for name, labels in rows}
    assert in_db == EXPECTED_ENUM_LABELS


async def test_only_the_expected_enum_types_exist(db_conn: AsyncConnection) -> None:
    # Proves: the 13 enum types exist and no orphans are lying around.
    # typtype = 'e': pg_type also holds an array type "_<name>" per enum.
    rows = await db_conn.execute(sa.text("SELECT typname FROM pg_type WHERE typtype = 'e'"))
    assert set(rows.scalars()) == set(EXPECTED_ENUM_LABELS)


async def test_gin_indexes_and_the_check_constraint_exist(db_conn: AsyncConnection) -> None:
    # Proves: the two JSONB indexes really are GIN indexes, and the
    # free-admission CHECK constraint really exists in the database.
    # compare_metadata can't see either of these.
    rows = await db_conn.execute(
        sa.text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    )
    idx: dict[str, str] = {name: definition for name, definition in rows}
    assert "USING gin" in idx["venue_extra_metadata_idx"]
    assert "USING gin" in idx["artist_extra_metadata_idx"]
    con = (await db_conn.execute(sa.text("SELECT conname FROM pg_constraint"))).scalars().all()
    assert "show_free_admission_check" in con


# --- Constraint behaviour, asserting WHICH constraint fired. ---------------
#
# Core statements, not ORM objects: an ORM delete of a venue would null
# show.venue_id first (a NOT NULL error, not the FK error), and two ShowArtist
# objects with one primary key fail in the identity map before any SQL runs.
#
# The helpers below build rows and assert on failures; the tests after them
# are short because of that.


async def _insert(conn: AsyncConnection, table: str, **values: Any) -> int | None:
    """INSERT one row via Core and return its primary key (None for a
    composite key, which `inserted_primary_key` reports differently)."""
    result = await conn.execute(sa.insert(T[table]).values(**values))
    return result.inserted_primary_key[0] if result.inserted_primary_key else None


async def _violates(conn: AsyncConnection, stmt: sa.Executable, sqlstate: str, constraint: str) -> None:
    """Assert `stmt` fails with this SQLSTATE *and* this named constraint.

    A bare `raises(IntegrityError)` would also pass if the row failed for an
    unrelated reason (a missing NOT NULL column), proving nothing about the
    constraint under test. The savepoint keeps the outer transaction usable.
    """
    # The savepoint (begin_nested) is inside the `raises` block on purpose:
    # a failed statement aborts the surrounding Postgres transaction, and
    # rolling back to the savepoint is what lets the test keep using `conn`.
    with pytest.raises(IntegrityError) as caught:
        async with conn.begin_nested():
            await conn.execute(stmt)
    orig = caught.value.orig
    assert orig is not None
    # SQLSTATE codes: 23514 check_violation, 23503 foreign_key_violation,
    # 23505 unique_violation (primary keys report as this too).
    assert orig.sqlstate == sqlstate  # type: ignore[attr-defined]
    # constraint_name lives on the native asyncpg exception, one level down.
    assert orig.__cause__.constraint_name == constraint  # type: ignore[union-attr]


async def _venue(conn: AsyncConnection) -> int:
    """Insert a throwaway metro + venue (the minimum a show needs) and
    return the venue's id."""
    metro_id = await _insert(conn, "metro", name="Test Metro", timezone="America/Chicago")
    venue_id = await _insert(
        conn, "venue", metro_id=metro_id, name="Test Venue", calendar_url="https://example.com"
    )
    assert venue_id is not None
    return venue_id


def _show_values(venue_id: int, **extra: Any) -> dict[str, Any]:
    """The minimum columns for a valid show (venue + date), plus overrides."""
    return {"venue_id": venue_id, "date": datetime.date(2026, 10, 9), **extra}


async def test_free_admission_with_a_price_is_rejected(db_conn: AsyncConnection) -> None:
    # Proves: a show can't be both "free" and have a ticket price. This is
    # the data-model's internal-consistency rule, enforced by the database.
    venue_id = await _venue(db_conn)
    stmt = sa.insert(T["show"]).values(
        **_show_values(venue_id, free_admission=True, admission_day=decimal.Decimal("10.00"))
    )
    await _violates(db_conn, stmt, "23514", "show_free_admission_check")


@pytest.mark.parametrize("free", [False, None])
async def test_a_price_is_fine_unless_free_admission_is_true(
    db_conn: AsyncConnection, free: bool | None
) -> None:
    # Proves: the CHECK only rejects the contradictory case. A price with
    # free_admission False, or with it unstated (NULL), is accepted.
    # Guards a CHECK written backwards, or one that treats NULL as free:
    # absence of a price does not imply free, and a price does not imply
    # not-free unless the listing says so.
    venue_id = await _venue(db_conn)
    await _insert(
        db_conn, "show", **_show_values(venue_id, free_admission=free, admission_advance=decimal.Decimal("12.50"))
    )


async def test_free_admission_without_a_price_is_fine(db_conn: AsyncConnection) -> None:
    # Proves: the other half of the rule — a genuinely free show (free, no
    # price) is valid. Together with the tests above, the CHECK rejects
    # exactly one combination.
    venue_id = await _venue(db_conn)
    await _insert(db_conn, "show", **_show_values(venue_id, free_admission=True))


async def test_deleting_a_venue_that_has_shows_is_rejected(db_conn: AsyncConnection) -> None:
    # Proves: the show -> venue foreign key blocks deleting a venue that
    # still has shows (no silent cascade; removal is a deliberate act).
    venue_id = await _venue(db_conn)
    await _insert(db_conn, "show", **_show_values(venue_id))
    await _violates(db_conn, sa.delete(T["venue"]).where(T["venue"].c.id == venue_id), "23503", "show_venue_id_fkey")


async def test_the_same_artist_cannot_be_on_a_show_twice(db_conn: AsyncConnection) -> None:
    # Proves: show_artist's composite primary key rejects a duplicate
    # (show, artist) pair — an artist appears once per show's lineup.
    venue_id = await _venue(db_conn)
    show_id = await _insert(db_conn, "show", **_show_values(venue_id))
    artist_id = await _insert(db_conn, "artist", name="Test Artist")
    await _insert(db_conn, "show_artist", show_id=show_id, artist_id=artist_id)
    dup = sa.insert(T["show_artist"]).values(show_id=show_id, artist_id=artist_id)
    await _violates(db_conn, dup, "23505", "show_artist_pkey")


# --- Server-side defaults actually work for plain INSERTs. -----------------


async def test_server_defaults_apply_to_inserts_that_omit_them(db_conn: AsyncConnection) -> None:
    # Proves: inserting a row that omits the defaulted columns gets sensible
    # values from the database itself — not from any Python code. This is
    # what a raw SQL INSERT, the seed, or a future admin tool relies on.
    venue_id = await _venue(db_conn)
    show_id = await _insert(db_conn, "show", **_show_values(venue_id))
    venue = (await db_conn.execute(sa.select(T["venue"]).where(T["venue"].c.id == venue_id))).one()
    show = (await db_conn.execute(sa.select(T["show"]).where(T["show"].c.id == show_id))).one()
    assert venue.fetch_strategy == "http"
    assert show.status == "active"
    assert venue.created_at is not None and venue.updated_at is not None

    # Same for the audit tables: a run gets a start time, and a log row
    # defaults to attempt 1 with a creation time.
    run_id = await _insert(db_conn, "agent_run", venue_id=venue_id, trigger="manual")
    log_id = await _insert(db_conn, "audit_log", run_id=run_id, step_type="fetch", source="agent")
    log = (await db_conn.execute(sa.select(T["audit_log"]).where(T["audit_log"].c.id == log_id))).one()
    run = (await db_conn.execute(sa.select(T["agent_run"]).where(T["agent_run"].c.id == run_id))).one()
    assert log.attempt_number == 1
    assert log.created_at is not None
    assert run.started_at is not None


async def test_agent_run_app_env_is_optional_so_old_writers_still_work(db_conn: AsyncConnection) -> None:
    # Proves (C3-D5, expand-only): `agent_run.app_env` is nullable with no default, so an INSERT that omits it
    # (a worker deployed before this migration, a raw SQL tool, every run recorded before C3) still succeeds and
    # reads back NULL. A NOT NULL column would break the deployed worker the moment the API's pre-deploy
    # migration ran, because the API and the worker do not redeploy together (arch-initial.md section 5).
    venue_id = await _venue(db_conn)
    run_id = await _insert(db_conn, "agent_run", venue_id=venue_id, trigger="manual")
    run = (await db_conn.execute(sa.select(T["agent_run"]).where(T["agent_run"].c.id == run_id))).one()
    assert run.app_env is None
    assert T["agent_run"].c.app_env.nullable is True


async def test_updated_at_is_readable_after_an_orm_update(db_session: AsyncSession) -> None:
    # Proves: after updating a row through the ORM, `updated_at` can be read
    # without error. (This test uses the ORM on purpose — it's about ORM
    # behaviour, unlike the Core-based constraint tests above.)
    # onupdate=func.now() is a SQL expression. With SQLAlchemy's default
    # eager_defaults="auto", the value is only fetched on INSERT, so after an
    # ORM UPDATE the attribute is expired and reading it under an AsyncSession
    # means a hidden lazy load -> MissingGreenlet. A6 snapshots the row right
    # after updating it for audit_log.new_value, so it would hit exactly this.
    metro = Metro(name="Before", timezone="America/Chicago")
    db_session.add(metro)
    await db_session.flush()
    metro.name = "After"
    await db_session.flush()
    assert metro.updated_at is not None  # raises MissingGreenlet if expired


async def test_jsonb_and_array_columns_round_trip(db_conn: AsyncConnection) -> None:
    # Proves: the Postgres-specific column types (text[] and JSONB) store
    # and return Python lists/dicts intact, so venue phone numbers, emails
    # and the free-form extra_metadata blob behave as the spec describes.
    metro_id = await _insert(db_conn, "metro", name="M", timezone="America/Chicago")
    venue_id = await _insert(
        db_conn,
        "venue",
        metro_id=metro_id,
        name="V",
        calendar_url="https://example.com",
        phone_numbers=["+1-612-555-0100", "+1-612-555-0101"],
        emails=["a@example.com"],
        extra_metadata={"has_green_room": True, "capacity": 250},
    )
    row = (await db_conn.execute(sa.select(T["venue"]).where(T["venue"].c.id == venue_id))).one()
    assert row.phone_numbers == ["+1-612-555-0100", "+1-612-555-0101"]
    assert row.emails == ["a@example.com"]
    assert row.extra_metadata == {"has_green_room": True, "capacity": 250}


# --- The one destructive test ---------------------------------------------
#
# Keep this test LAST in the file: it takes the shared schema apart and puts
# it back, and every test above assumes it is at head.
async def test_upgrade_fails_loudly_if_an_enum_type_already_exists(
    migrated_engine: AsyncEngine,
) -> None:
    # Proves: if a Postgres enum type with one of our names already exists
    # (a leftover from a half-failed earlier migration, say), `alembic
    # upgrade` stops with an error instead of quietly reusing it.
    # An orphaned type (from a half-failed earlier migration, or hand-made)
    # must stop the upgrade, not be silently adopted — it might have
    # different labels. Postgres/SQLAlchemy's `.create()` defaults to
    # checkfirst=True, which would quietly reuse it; the round-trip fixture
    # can't catch that because it always starts from a fresh database.

    # Step 1: go back to an empty schema so we can plant the orphan.
    await run_alembic(migrated_engine, "downgrade", "base")
    try:
        # Step 2: plant an orphan type, then try to upgrade over it.
        async with migrated_engine.begin() as conn:
            await conn.execute(sa.text("CREATE TYPE fetch_strategy AS ENUM ('http')"))
        with pytest.raises(Exception, match="already exists"):
            await run_alembic(migrated_engine, "upgrade", "head")
    finally:
        # Step 3: restore. This runs even if the assertion above fails, so a
        # failure here can't leave the shared schema broken for other tests.
        # Whatever happened, put the schema back at head for later tests:
        # undo a (wrongly) successful upgrade, drop the orphan, upgrade clean.
        await run_alembic(migrated_engine, "downgrade", "base")
        async with migrated_engine.begin() as conn:
            await conn.execute(sa.text("DROP TYPE IF EXISTS fetch_strategy"))
        await run_alembic(migrated_engine, "upgrade", "head")
