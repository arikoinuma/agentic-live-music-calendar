"""Pytest fixtures for tests that need a real Postgres.

Loaded as a plugin from apps/api/conftest.py (`pytest_plugins`) rather than
living in app/tests/conftest.py, so A7's agent_worker/ tests can use the same
fixtures unchanged — a conftest.py only applies to its own directory.
Design and reasoning: docs/dev/implementations/a1-data-layer.md, "Test
approach".

Three things here are easy to get dangerously wrong, so they're stated up
front:

1. These fixtures DROP and CREATE a database and run `downgrade base`. The
   guard below (`check_test_database_url`) runs before any of that. It
   checks the database name always, and the host whenever the URL was
   *derived* from DATABASE_URL — docs/dev/notes.md records DATABASE_URL once
   pointing at the production Neon database from this machine, and a
   name-only check would happily wipe `calendar_test` there.

2. Alembic runs on an *injected* connection (`cfg.attributes["connection"]`),
   not through migrations/env.py's normal path. The stock env.py
   unconditionally overrides the URL with `settings.database_url` (the dev
   database) and calls `asyncio.run`, which can't run inside pytest-asyncio's
   loop; ours skips both when a connection is injected.

3. Unreachable Postgres skips locally but FAILS under CI / REQUIRE_DB=1, so a
   misconfigured CI service can't turn the job green by skipping every DB
   test. `make test` sets REQUIRE_DB=1 for the same reason.

FIXTURE MAP (what a test gets, and what each one builds on)
    database_url_for_tests   session: guard the URL, then DROP + CREATE the
                             `calendar_test` database.
    migrated_engine          session: run the Alembic migration on that
                             database (up, down, up) and hand out an engine.
    db_conn                  per test: a connection inside a transaction that
                             is rolled back afterwards. Use for raw SQL/Core.
    db_session               per test: an ORM session on top of db_conn.
                             Use when code under test takes a session.
  Tests never use the app's own engine (app.db.session.engine); that one
  points at the dev database.

TEST_DATABASE_URL and REQUIRE_DB are shell/CI environment variables only. Do
not put them in .env: Settings is extra="forbid", so an unknown .env key
raises a ValidationError app-wide, and pydantic-settings doesn't export .env
values to os.environ anyway, so they'd never reach this module.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import NoReturn

import asyncpg  # type: ignore[import-untyped]  # ships no stubs or py.typed
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.engine.base import Connection
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings

# apps/api/ — two levels up from this file (app/testing/db.py). Used to find
# alembic.ini and the migrations/ directory regardless of the cwd.
API_DIR = Path(__file__).resolve().parents[2]
# The ONLY database name these fixtures will ever drop or migrate. A constant,
# not configurable, so a typo in an environment variable can't redirect a
# DROP DATABASE at something real.
TEST_DB_NAME = "calendar_test"
# Hosts considered safe when the test URL is derived from DATABASE_URL.
# (Hostnames are matched exactly; "::1" is IPv6 loopback.)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnsafeTestDatabaseError(RuntimeError):
    """The test database URL points somewhere these fixtures must not wipe."""


def resolve_test_database_url() -> tuple[URL, bool]:
    """The URL tests run against, and whether it was derived (not explicit).

    Derived means "DATABASE_URL with the database name swapped" — the case
    where a wrong DATABASE_URL silently becomes a wrong test target, so it's
    the case that gets the stricter host check.
    """
    # An explicit TEST_DATABASE_URL means someone chose the target on purpose,
    # so only the database name is policed. Otherwise we guess from
    # DATABASE_URL, and guessing is what gets the extra host check.
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit), False
    return make_url(settings.database_url).set(database=TEST_DB_NAME), True


def check_test_database_url(url: URL, *, derived: bool) -> None:
    """Raise UnsafeTestDatabaseError unless it is safe to wipe this database.

    Two independent checks. The name check always applies. The host check
    applies only to a *derived* URL (see resolve_test_database_url), where a
    mistaken DATABASE_URL — e.g. one pointing at the hosted Neon database —
    would otherwise quietly become the test target.
    """
    # Check 1: the database must be literally `calendar_test`.
    if url.database != TEST_DB_NAME:
        raise UnsafeTestDatabaseError(
            f"Refusing to run destructive test fixtures against database "
            f"{url.database!r}; it must be {TEST_DB_NAME!r}."
        )
    # Check 2: a guessed URL must point at this machine.
    if derived and url.host not in LOCAL_HOSTS:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL was derived from DATABASE_URL, whose host is "
            f"{url.host!r} (not local). Refusing to create/drop a database "
            f"there. Set TEST_DATABASE_URL explicitly if this is intentional."
        )


def _maintenance_dsn(url: URL) -> str:
    # Two traps in one line. str(url) masks the password as "***" in
    # SQLAlchemy 2.0, so it must be rendered explicitly; and raw asyncpg
    # rejects the "+asyncpg" driver suffix SQLAlchemy URLs carry.
    return url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )


def _db_required() -> bool:
    """True when "no database" should fail the run instead of skipping.

    CI sets `CI` automatically; `make test` / `make check` set REQUIRE_DB=1.
    A plain local `pytest` sets neither, so DB tests skip politely when
    Docker is off.
    """
    return bool(os.environ.get("CI")) or os.environ.get("REQUIRE_DB") == "1"


def _unreachable(reason: str) -> NoReturn:
    """Postgres can't be reached: fail the run if a database is required,
    otherwise skip the tests that need one (with a hint on how to start it)."""
    if _db_required():
        pytest.fail(
            f"{reason} (CI/REQUIRE_DB is set, so this is a failure, not a skip)",
            pytrace=False,
        )
    pytest.skip(f"{reason} — start Postgres with `make db-up` to run DB tests")


def alembic_config() -> Config:
    """An Alembic `Config` pointing at this project's alembic.ini and migrations/."""
    # Built from this file's location, not the cwd, so it works from any
    # directory pytest is launched in.
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    return cfg


async def run_alembic(engine: AsyncEngine, action: str, revision: str) -> None:
    """Run `alembic <action> <revision>` on a connection we own.

    Alembic's command API is synchronous and our engine is async, so the
    connection is handed over via `run_sync`; an AsyncConnection itself
    can't go in `config.attributes`. migrations/env.py sees the injected
    connection and skips its own URL override and asyncio.run.

    The commit afterwards matters: if the connection is already inside a
    transaction when Alembic configures, Alembic's begin_transaction()
    degrades to a nullcontext and never commits, leaving the migrated schema
    invisible to every other connection.
    """
    cfg = alembic_config()

    def _run(sync_conn: Connection) -> None:
        # The hand-off: migrations/env.py looks for this key and, if present,
        # runs on this connection instead of building its own engine.
        cfg.attributes["connection"] = sync_conn
        # `action` is "upgrade" or "downgrade": alembic.command.<action>(cfg, rev).
        getattr(command, action)(cfg, revision)

    async with engine.connect() as conn:
        # run_sync executes the synchronous Alembic call on this async
        # connection (SQLAlchemy bridges the two).
        await conn.run_sync(_run)
        await conn.commit()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database_url_for_tests() -> AsyncIterator[URL]:
    """Guard, then give the test database a clean slate.

    Dropped and recreated every session so a schema or alembic_version row
    left over from an older draft of the migration can't break setup, and
    so `downgrade base` in the round trip below runs against the schema this
    run's `upgrade` just built.
    """
    # Step 1: decide the target and refuse unsafe ones, before anything
    # destructive can happen.
    url, derived = resolve_test_database_url()
    check_test_database_url(url, derived=derived)

    # DROP ... WITH (FORCE) terminates any other connection to calendar_test,
    # so two pytest runs at once (an editor's test explorer alongside
    # `make check`) will kill each other's. Run one at a time.
    # Step 2: connect to the server's built-in `postgres` database (you can't
    # drop a database while connected to it) and decide: skip, fail, or go on.
    try:
        admin = await asyncpg.connect(_maintenance_dsn(url), timeout=5)
    except (OSError, TimeoutError) as exc:
        # Only connection-level failures count as "unreachable". Auth
        # failures and anything else propagate and fail the run.
        _unreachable(f"Postgres not reachable at {url.host}:{url.port} ({exc!r})")
    # Step 3: start from nothing. Plain f-string SQL is safe here only because
    # TEST_DB_NAME is a constant defined above, never user input.
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await admin.close()

    # Hand the (now empty) database's URL to dependent fixtures.
    yield url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrated_engine(database_url_for_tests: URL) -> AsyncIterator[AsyncEngine]:
    """Build the schema with the real migration, proving up *and* down work.

    Yields an engine on a database that is at the latest migration. Runs once
    per test session.
    """
    # NullPool: asyncpg connections are bound to the loop that created them,
    # and after the round trip below the enum types have new OIDs, which
    # pooled connections would hold stale type caches for.
    engine = create_async_engine(database_url_for_tests, poolclass=NullPool)

    # The name check again, on a *separate* connection, against what the
    # server says rather than what the URL says.
    async with engine.connect() as conn:
        name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
    assert name == TEST_DB_NAME, f"connected to {name!r}, refusing to migrate"

    # upgrade -> downgrade -> upgrade, every run, CI included. This is what
    # actually exercises the hand-written downgrade(); on a fresh database
    # `downgrade base` alone would do nothing.
    await run_alembic(engine, "upgrade", "head")
    await run_alembic(engine, "downgrade", "base")
    # After a clean downgrade only Alembic's own bookkeeping table may remain,
    # and no enum types: those are exactly what a sloppy downgrade() leaves.
    async with engine.connect() as conn:
        tables = (
            (
                await conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                )
            )
            .scalars()
            .all()
        )
        enums = (
            (await conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'")))
            .scalars()
            .all()
        )
    assert set(tables) <= {"alembic_version"}, f"downgrade left tables: {tables}"
    assert not enums, f"downgrade left enum types behind: {enums}"
    # Now build it for real, for the tests to use.
    await run_alembic(engine, "upgrade", "head")

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_conn(migrated_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is always rolled back.

    Whatever a test inserts disappears when it finishes, so tests are
    independent of one another and of the order they run in.
    """
    async with migrated_engine.connect() as conn:
        outer = await conn.begin()
        yield conn
        # Always roll back, never commit: this is the isolation mechanism.
        await outer.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_conn: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """An ORM session riding on db_conn's rolled-back transaction."""
    # create_savepoint: code under test may call session.commit(); that
    # releases a savepoint instead of ending the outer transaction, so the
    # rollback in db_conn still undoes everything. (The seed itself only
    # flushes, but later code under test, e.g. commit_node, will commit.)
    async with AsyncSession(
        bind=db_conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session
